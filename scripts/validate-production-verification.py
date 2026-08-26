#!/usr/bin/env python3

"""Validate proof that a packaging release passed the production gateway test."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def require_object(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be an object")
    return value


def require_string(record: dict[str, Any], field: str, description: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{description}.{field} must be a nonempty string")
    return value


def validate_production_verification(
    build_metadata: dict[str, Any],
    verification: dict[str, Any],
    expected_release_tag: str,
    expected_repository_url: str,
    expected_repository_index_digest: str,
) -> None:
    if build_metadata.get("schema_version") != 1:
        raise ValueError("Build metadata schema is unsupported")
    if verification.get("schema_version") != 1:
        raise ValueError("Production-verification schema is unsupported")
    if verification.get("status") != "production-repository-gateway-verified":
        raise ValueError("Production-verification status is not verified")

    packaging = require_object(build_metadata.get("packaging"), "packaging")
    release_tag = require_string(packaging, "release_tag", "packaging")
    packaging_commit = require_string(packaging, "commit", "packaging")
    run_id = require_string(packaging, "run_id", "packaging")
    run_number = require_string(packaging, "run_number", "packaging")
    run_attempt = require_string(packaging, "run_attempt", "packaging")
    if release_tag != expected_release_tag:
        raise ValueError("Build metadata does not identify GitHub's latest release")
    if COMMIT.fullmatch(packaging_commit) is None:
        raise ValueError("Packaging commit is not a full Git commit ID")
    if not all(value.isdigit() and int(value) > 0 for value in (run_id, run_number, run_attempt)):
        raise ValueError("Workflow run identity must contain positive integers")
    if build_metadata.get("repository_url") != expected_repository_url:
        raise ValueError("Build metadata uses a different repository URL")

    if verification.get("release_tag") != release_tag:
        raise ValueError("Production verification identifies a different release tag")
    if verification.get("repository_url") != expected_repository_url:
        raise ValueError("Production verification uses a different repository URL")
    if verification.get("packaging_commit") != packaging_commit:
        raise ValueError("Production verification identifies a different packaging commit")

    workflow = require_object(verification.get("workflow"), "workflow")
    expected_workflow = {
        "run_id": run_id,
        "run_number": run_number,
        "run_attempt": run_attempt,
    }
    if any(workflow.get(field) != value for field, value in expected_workflow.items()):
        raise ValueError("Production verification identifies a different workflow run")

    repository = require_object(build_metadata.get("repository"), "repository")
    repository_index = require_object(
        verification.get("repository_index"), "repository_index"
    )
    index_asset_name = require_string(repository, "index_asset_name", "repository")
    if repository_index.get("asset_name") != index_asset_name:
        raise ValueError("Production verification identifies a different repository index")
    index_sha256 = repository_index.get("sha256")
    if not isinstance(index_sha256, str) or SHA256.fullmatch(index_sha256) is None:
        raise ValueError("Production verification has an invalid repository-index digest")
    if expected_repository_index_digest != f"sha256:{index_sha256}":
        raise ValueError("Production verification identifies a different repository index")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_metadata", type=Path)
    parser.add_argument("verification", type=Path)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--repository-index-digest", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        build_metadata = json.loads(args.build_metadata.read_text(encoding="utf-8"))
        verification = json.loads(args.verification.read_text(encoding="utf-8"))
        validate_production_verification(
            require_object(build_metadata, "build metadata"),
            require_object(verification, "production verification"),
            args.release_tag,
            args.repository_url,
            args.repository_index_digest,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Invalid production verification: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"Validated production verification for {args.release_tag}")


if __name__ == "__main__":
    main()
