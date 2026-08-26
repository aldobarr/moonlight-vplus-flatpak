#!/usr/bin/env python3

"""Select verified packaging releases outside the retention window."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


MANAGED_RELEASE_TAG = re.compile(
    r"^build-v?[0-9][0-9A-Za-z._+-]*-r[1-9][0-9]*-a[1-9][0-9]*$"
)
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def flatten_release_pages(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, list):
        raise ValueError("GitHub release inventory must be a JSON array")
    if document and all(isinstance(page, list) for page in document):
        releases = [release for page in document for release in page]
    else:
        releases = document
    if not all(isinstance(release, dict) for release in releases):
        raise ValueError("GitHub release inventory contains a non-object entry")
    return releases


def is_verified_packaging_release(
    release: dict[str, Any], verification_asset_name: str
) -> bool:
    tag = release.get("tag_name")
    published_at = release.get("published_at")
    assets = release.get("assets")
    if release.get("draft") is not False:
        return False
    if not isinstance(tag, str) or MANAGED_RELEASE_TAG.fullmatch(tag) is None:
        return False
    if not isinstance(published_at, str) or not published_at:
        return False
    if not isinstance(assets, list):
        return False

    verification_assets = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and asset.get("name") == verification_asset_name
    ]
    if len(verification_assets) != 1:
        return False
    verification_asset = verification_assets[0]
    return (
        verification_asset.get("state") == "uploaded"
        and isinstance(verification_asset.get("digest"), str)
        and SHA256_DIGEST.fullmatch(verification_asset["digest"]) is not None
    )


def expired_release_tags(
    releases: list[dict[str, Any]],
    retain: int,
    verification_asset_name: str,
    required_tag: str | None = None,
) -> list[str]:
    if retain < 1:
        raise ValueError("Retention count must be positive")

    if not verification_asset_name:
        raise ValueError("Verification asset name must not be empty")

    verified = [
        release
        for release in releases
        if is_verified_packaging_release(release, verification_asset_name)
    ]
    verified.sort(
        key=lambda release: (
            release["published_at"],
            release["id"] if isinstance(release.get("id"), int) else 0,
        ),
        reverse=True,
    )
    tags = [release["tag_name"] for release in verified]
    if len(tags) != len(set(tags)):
        raise ValueError("Verified release inventory contains duplicate tags")
    if required_tag is not None and required_tag not in tags[:retain]:
        raise ValueError(
            f"Current release {required_tag!r} is not a verified retained release"
        )
    return tags[retain:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--retain", type=int, default=2)
    parser.add_argument("--required-tag")
    parser.add_argument("--verification-asset-name", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document = json.loads(args.inventory.read_text(encoding="utf-8"))
    releases = flatten_release_pages(document)
    for tag in expired_release_tags(
        releases,
        args.retain,
        args.verification_asset_name,
        args.required_tag,
    ):
        print(tag)


if __name__ == "__main__":
    main()
