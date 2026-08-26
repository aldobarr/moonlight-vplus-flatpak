#!/usr/bin/env python3

"""Decide whether a resolved upstream release needs a packaging build."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


METADATA_MARKER = re.compile(
    r"^<!-- moonlight-flatpak-build-v1:([A-Za-z0-9+/]+={0,2}) -->$",
    re.MULTILINE,
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TAG_PATTERN = re.compile(r"^v?[0-9][0-9A-Za-z._+-]*$")


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Release publication timestamp is missing")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def decide(
    upstream: dict,
    current: dict | None,
    packaging_commit: str,
    repository_url: str,
) -> tuple[bool, str]:
    if upstream.get("selection") == "manual":
        return True, "Manual release selections are intentional overrides"
    if current is None:
        return True, "No usable previous release metadata is available"

    current_upstream = current.get("upstream")
    current_packaging = current.get("packaging")
    if not isinstance(current_upstream, dict) or not isinstance(current_packaging, dict):
        raise ValueError("Previous build metadata is incomplete")

    candidate_time = timestamp(upstream.get("published_at"))
    current_time = timestamp(current_upstream.get("published_at"))

    if current_upstream.get("tag") != upstream.get("tag") and current_time > candidate_time:
        return False, "Current upstream selection is newer than the latest stable release"

    same_inputs = (
        current_upstream.get("commit") == upstream.get("commit")
        and current_upstream.get("tag") == upstream.get("tag")
        and current_upstream.get("prerelease") == upstream.get("prerelease")
        and current_packaging.get("commit") == packaging_commit
        and current.get("repository_url") == repository_url
    )
    if same_inputs:
        return False, "Upstream and packaging commits are unchanged"
    return True, "Build inputs changed"


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"JSON input is invalid: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def release_metadata(release: dict | None) -> dict | None:
    if release is None or release.get("draft") is not False:
        return None

    body = release.get("body")
    if not isinstance(body, str):
        return None
    matches = METADATA_MARKER.findall(body)
    if len(matches) != 1:
        return None

    try:
        decoded = base64.b64decode(matches[0], validate=True)
        metadata = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None

    upstream = metadata.get("upstream")
    packaging = metadata.get("packaging")
    if not isinstance(upstream, dict) or not isinstance(packaging, dict):
        return None

    upstream_tag = upstream.get("tag")
    upstream_commit = upstream.get("commit")
    upstream_prerelease = upstream.get("prerelease")
    packaging_commit = packaging.get("commit")
    packaging_release_tag = packaging.get("release_tag")
    if (
        not isinstance(upstream_tag, str)
        or TAG_PATTERN.fullmatch(upstream_tag) is None
        or not isinstance(upstream_commit, str)
        or SHA_PATTERN.fullmatch(upstream_commit) is None
        or not isinstance(upstream_prerelease, bool)
        or not isinstance(packaging_commit, str)
        or SHA_PATTERN.fullmatch(packaging_commit) is None
        or packaging_release_tag != release.get("tag_name")
        or packaging_commit != release.get("target_commitish")
    ):
        return None
    try:
        timestamp(upstream.get("published_at"))
    except ValueError:
        return None

    expected_bundle = f"moonlight-qt-{upstream_tag}-x86_64.flatpak"
    assets = release.get("assets")
    if not isinstance(assets, list) or len(assets) != 1:
        return None
    asset = assets[0]
    if not isinstance(asset, dict):
        return None
    digest = asset.get("digest")
    if (
        asset.get("name") != expected_bundle
        or asset.get("state") != "uploaded"
        or not isinstance(digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
    ):
        return None
    return metadata


def load_optional_release(path: Path | None) -> dict | None:
    if path is None:
        return None
    return release_metadata(load_json(path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("--current-release", type=Path)
    parser.add_argument("--packaging-commit", required=True)
    parser.add_argument("--repository-url", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    upstream = load_json(args.upstream)
    should_build, reason = decide(
        upstream,
        load_optional_release(args.current_release),
        args.packaging_commit,
        args.repository_url,
    )
    print(json.dumps({"should_build": should_build, "reason": reason}))


if __name__ == "__main__":
    main()
