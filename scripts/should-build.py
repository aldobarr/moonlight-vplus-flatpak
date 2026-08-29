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

from release_protocol import UPSTREAM_TAG_PATTERN, bundle_name


METADATA_MARKER = re.compile(
    r"^<!-- moonlight-flatpak-build-v1:([A-Za-z0-9+/]+={0,2}) -->$",
    re.MULTILINE,
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Release publication timestamp is missing")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def decide(
    upstream: dict,
    current: dict | None,
) -> tuple[bool, str]:
    if current is None:
        return True, "This upstream tag has not been published"

    current_upstream = current.get("upstream")
    current_packaging = current.get("packaging")
    if not isinstance(current_upstream, dict) or not isinstance(current_packaging, dict):
        raise ValueError("Previous build metadata is incomplete")

    upstream_tag = upstream.get("tag")
    if (
        current_upstream.get("tag") != upstream_tag
        or current_packaging.get("release_tag") != upstream_tag
    ):
        raise ValueError("Published release metadata does not match its upstream tag")
    return False, "This upstream tag already has a published Flatpak release"


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
        or UPSTREAM_TAG_PATTERN.fullmatch(upstream_tag) is None
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

    expected_bundle = bundle_name(upstream_tag)
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    upstream = load_json(args.upstream)
    should_build, reason = decide(
        upstream,
        load_optional_release(args.current_release),
    )
    print(json.dumps({"should_build": should_build, "reason": reason}))


if __name__ == "__main__":
    main()
