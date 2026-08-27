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


def packaging_release_tag(
    upstream_tag: str,
    run_number: int,
    run_attempt: int,
) -> str:
    validate_upstream_tag(upstream_tag)
    if run_number < 1 or run_attempt < 1:
        raise ValueError("GitHub run number and attempt must be positive integers")
    return f"build-{upstream_tag}-r{run_number}-a{run_attempt}"


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream_tag")
    parser.add_argument("--run-number", required=True, type=positive_integer)
    parser.add_argument("--run-attempt", required=True, type=positive_integer)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            {
                "bundle_name": bundle_name(args.upstream_tag),
                "release_tag": packaging_release_tag(
                    args.upstream_tag,
                    args.run_number,
                    args.run_attempt,
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
