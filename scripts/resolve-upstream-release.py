#!/usr/bin/env python3

"""Resolve an eligible qiin2333/moonlight-qt GitHub Release."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from release_protocol import validate_upstream_tag


API_ROOT = "https://api.github.com"
UPSTREAM_REPOSITORY = "qiin2333/moonlight-qt"
STABLE_RELEASE_TAG_PATTERN = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+$")
RELEASE_VERSION_PREFIX_PATTERN = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)")


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def get_json(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{API_ROOT}{path}",
            headers={
                "Accept": "application/vnd.github.full+json",
                "User-Agent": "moonlight-vplus-flatpak-release-resolver",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API request failed ({error.code}): {detail}") from error


def resolve_release(client: GitHubClient, requested_tag: str | None) -> dict[str, Any]:
    if requested_tag:
        validate_upstream_tag(requested_tag)
        encoded_tag = urllib.parse.quote(requested_tag, safe="")
        release = client.get_json(
            f"/repos/{UPSTREAM_REPOSITORY}/releases/tags/{encoded_tag}"
        )
        selection = "manual"
    else:
        release = client.get_json(f"/repos/{UPSTREAM_REPOSITORY}/releases/latest")
        selection = "automated"

    if not isinstance(release, dict):
        raise ValueError("GitHub returned an invalid upstream Release")

    tag = release.get("tag_name")
    if not isinstance(tag, str):
        raise ValueError("Upstream Release does not contain a tag name")
    validate_upstream_tag(tag)
    if requested_tag and tag != requested_tag:
        raise ValueError(f"Requested tag {requested_tag!r} resolved as {tag!r}")
    if release.get("draft"):
        raise ValueError(f"Draft upstream Release {tag!r} is not eligible")
    if selection == "automated" and release.get("prerelease"):
        raise ValueError("GitHub's latest stable Release endpoint returned a prerelease")

    published_at = release.get("published_at")
    if not isinstance(published_at, str):
        raise ValueError(f"Upstream Release {tag!r} has no publication timestamp")
    release_date = datetime.fromisoformat(published_at.replace("Z", "+00:00")).date().isoformat()

    version = tag[1:] if tag.startswith("v") else tag
    commit = resolve_tag_commit(client, tag)
    release_title = release.get("name")
    if not isinstance(release_title, str) or not release_title:
        release_title = tag
    release_body, release_notes = resolve_release_text(client, release, commit)
    return {
        "tag": tag,
        "version": version,
        "commit": commit,
        "published_at": published_at,
        "release_date": release_date,
        "prerelease": bool(release.get("prerelease")),
        "selection": selection,
        "html_url": release.get("html_url"),
        "release_notes": release_notes,
        "release_title": release_title,
        "release_body": release_body,
        "release_history": resolve_release_history(client, release, commit),
    }


def list_releases(client: GitHubClient) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        result = client.get_json(
            f"/repos/{UPSTREAM_REPOSITORY}/releases?per_page=100&page={page}"
        )
        if not isinstance(result, list) or not all(
            isinstance(release, dict) for release in result
        ):
            raise ValueError("GitHub returned an invalid upstream Release list")
        releases.extend(result)
        if len(result) < 100:
            return releases
        page += 1


def release_timestamp(release: dict[str, Any], tag: str) -> datetime:
    published_at = release.get("published_at")
    if not isinstance(published_at, str):
        raise ValueError(f"Upstream Release {tag!r} has no publication timestamp")
    return datetime.fromisoformat(published_at.replace("Z", "+00:00"))


def release_version(tag: str) -> tuple[int, int, int] | None:
    match = RELEASE_VERSION_PREFIX_PATTERN.match(tag)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def resolve_release_text(
    client: GitHubClient,
    release: dict[str, Any],
    commit: str | None = None,
) -> tuple[str, str]:
    body = release.get("body")
    if not isinstance(body, str):
        body = ""
    if not body.strip():
        tag = release.get("tag_name")
        if not isinstance(tag, str):
            raise ValueError("Upstream Release does not contain a tag name")
        body = resolve_commit_message(
            client,
            commit or resolve_tag_commit(client, tag),
        )

    notes = release.get("body_text")
    if not isinstance(notes, str) or not notes.strip():
        notes = body
    return body, notes


def resolve_release_history(
    client: GitHubClient,
    selected_release: dict[str, Any],
    selected_commit: str,
) -> list[dict[str, str]]:
    selected_tag = selected_release.get("tag_name")
    if not isinstance(selected_tag, str):
        raise ValueError("Upstream Release does not contain a tag name")
    selected_timestamp = release_timestamp(selected_release, selected_tag)
    selected_version = release_version(selected_tag)

    history: list[
        tuple[bool, tuple[int, int, int], datetime, dict[str, str]]
    ] = []
    seen_tags: set[str] = set()
    for release in [selected_release, *list_releases(client)]:
        tag = release.get("tag_name")
        if not isinstance(tag, str) or tag in seen_tags or release.get("draft"):
            continue
        published_at = release_timestamp(release, tag)
        if published_at > selected_timestamp:
            continue
        if tag != selected_tag and (
            release.get("prerelease") or STABLE_RELEASE_TAG_PATTERN.fullmatch(tag) is None
        ):
            continue
        version = release_version(tag)
        if tag != selected_tag and selected_version is not None:
            if version is None:
                raise ValueError(f"Invalid stable Release version: {tag!r}")
            if version > selected_version:
                continue

        seen_tags.add(tag)
        _, notes = resolve_release_text(
            client,
            release,
            selected_commit if tag == selected_tag else None,
        )
        release_url = release.get("html_url")
        if not isinstance(release_url, str) or not release_url:
            raise ValueError(f"Upstream Release {tag!r} has no URL")
        history.append(
            (
                tag == selected_tag,
                version or selected_version or (0, 0, 0),
                published_at,
                {
                    "version": tag[1:] if tag.startswith("v") else tag,
                    "date": published_at.date().isoformat(),
                    "url": release_url,
                    "description": notes,
                },
            )
        )

    history.sort(key=lambda item: item[:3], reverse=True)
    return [release for _, _, _, release in history]


def resolve_tag_commit(client: GitHubClient, tag: str) -> str:
    encoded_tag = urllib.parse.quote(tag, safe="")
    ref = client.get_json(f"/repos/{UPSTREAM_REPOSITORY}/git/ref/tags/{encoded_tag}")
    target = ref.get("object")

    for _ in range(10):
        if not isinstance(target, dict):
            break
        target_type = target.get("type")
        sha = target.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            break
        if target_type == "commit":
            return sha
        if target_type != "tag":
            break
        tag_object = client.get_json(f"/repos/{UPSTREAM_REPOSITORY}/git/tags/{sha}")
        target = tag_object.get("object")

    raise ValueError(f"Unable to resolve upstream tag {tag!r} to a commit")


def resolve_commit_message(client: GitHubClient, commit: str) -> str:
    commit_object = client.get_json(
        f"/repos/{UPSTREAM_REPOSITORY}/git/commits/{commit}"
    )
    message = commit_object.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError(f"Upstream commit {commit!r} has no release message")
    return message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Explicit published Release tag; prereleases are allowed")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = GitHubClient(os.environ.get("GITHUB_TOKEN"))
    print(json.dumps(resolve_release(client, args.tag), indent=2))


if __name__ == "__main__":
    main()
