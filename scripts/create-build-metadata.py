#!/usr/bin/env python3

"""Create the release metadata used for later build decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NamedTuple


class PackagingIdentity(NamedTuple):
    commit: str
    release_tag: str
    run_number: str


def create_metadata(
    upstream_path: Path,
    output_path: Path,
    *,
    repository_url: str,
    packaging_identity: PackagingIdentity,
) -> None:
    if not repository_url.startswith("https://") or not repository_url.endswith("/"):
        raise ValueError("Repository URL must be an HTTPS base URL ending in a slash")

    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    metadata = {
        "repository_url": repository_url,
        "upstream": upstream,
        "packaging": packaging_identity._asdict(),
    }
    output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--packaging-commit", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--run-number", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    create_metadata(
        args.upstream,
        args.output,
        repository_url=args.repository_url,
        packaging_identity=PackagingIdentity(
            commit=args.packaging_commit,
            release_tag=args.release_tag,
            run_number=args.run_number,
        ),
    )


if __name__ == "__main__":
    main()
