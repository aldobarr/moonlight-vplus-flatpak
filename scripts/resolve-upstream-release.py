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


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def get_json(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{API_ROOT}{path}",
            headers={
                "Accept": "application/vnd.github+json",
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
    return {
        "tag": tag,
        "version": version,
        "commit": commit,
        "published_at": published_at,
        "release_date": release_date,
        "prerelease": bool(release.get("prerelease")),
        "selection": selection,
        "html_url": release.get("html_url"),
    }


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
