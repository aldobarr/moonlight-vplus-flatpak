#!/usr/bin/env python3

"""Create the release metadata used for auditing and later build decisions."""

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
    repository_index_path: Path,
    bundle_path: Path,
    output_path: Path,
    *,
    repository_url: str,
    packaging_identity: PackagingIdentity,
) -> dict:
    if not repository_url.startswith("https://") or not repository_url.endswith("/"):
        raise ValueError("Repository URL must be an HTTPS base URL ending in a slash")

    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    repository_index = json.loads(repository_index_path.read_text(encoding="utf-8"))
    summary = next(
        (
            item
            for item in repository_index.get("files", [])
            if item.get("repository_path") == "summary"
        ),
        None,
    )
    summary_signature = next(
        (
            item
            for item in repository_index.get("files", [])
            if item.get("repository_path") == "summary.sig"
        ),
        None,
    )
    if summary is None or summary_signature is None:
        raise ValueError("Signed repository index must contain summary and summary.sig")

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
        "repository": {
            "index_asset_name": repository_index_path.name,
            "file_count": repository_index.get("repository_file_count"),
            "summary_asset_name": summary.get("asset_name"),
            "summary_sha256": summary.get("sha256"),
            "summary_signature_asset_name": summary_signature.get("asset_name"),
            "summary_signature_sha256": summary_signature.get("sha256"),
        },
    }
    output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("repository_index", type=Path)
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
        args.repository_index,
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
