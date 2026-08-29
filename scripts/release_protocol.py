#!/usr/bin/env python3

"""Define the release names shared by the build and publication pipeline."""

from __future__ import annotations

import argparse
import json
import re


UPSTREAM_TAG_PATTERN = re.compile(r"^v?[0-9][0-9A-Za-z._+-]*$")


def validate_upstream_tag(tag: str) -> str:
    if not isinstance(tag, str) or UPSTREAM_TAG_PATTERN.fullmatch(tag) is None:
        raise ValueError(f"Unsupported upstream release tag: {tag!r}")
    return tag


def bundle_name(upstream_tag: str) -> str:
    return f"moonlight-qt-{validate_upstream_tag(upstream_tag)}-x86_64.flatpak"


def packaging_release_tag(upstream_tag: str) -> str:
    return validate_upstream_tag(upstream_tag)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream_tag")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            {
                "bundle_name": bundle_name(args.upstream_tag),
                "release_tag": packaging_release_tag(args.upstream_tag),
            }
        )
    )


if __name__ == "__main__":
    main()
