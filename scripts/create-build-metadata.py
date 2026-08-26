#!/usr/bin/env python3

"""Create the release metadata used for later build decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NamedTuple

from file_hashes import sha256_file


class PackagingIdentity(NamedTuple):
    commit: str
    release_tag: str
    run_id: str
    run_number: str
    run_attempt: str


def create_metadata(
    upstream_path: Path,
    bundle_path: Path,
    output_path: Path,
    *,
    repository_url: str,
    packaging_identity: PackagingIdentity,
) -> dict:
    if not repository_url.startswith("https://") or not repository_url.endswith("/"):
        raise ValueError("Repository URL must be an HTTPS base URL ending in a slash")

    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    metadata = {
        "schema_version": 1,
        "application_id": "com.github.qiin2333.Moonlight",
        "architecture": "x86_64",
        "repository_url": repository_url,
        "upstream": upstream,
        "packaging": packaging_identity._asdict(),
        "bundle": {
            "asset_name": bundle_path.name,
            "size": bundle_path.stat().st_size,
            "sha256": sha256_file(bundle_path),
        },
    }
    output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--packaging-commit", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-number", required=True)
    parser.add_argument("--run-attempt", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    create_metadata(
        args.upstream,
        args.bundle,
        args.output,
        repository_url=args.repository_url,
        packaging_identity=PackagingIdentity(
            commit=args.packaging_commit,
            release_tag=args.release_tag,
            run_id=args.run_id,
            run_number=args.run_number,
            run_attempt=args.run_attempt,
        ),
    )


if __name__ == "__main__":
    main()
