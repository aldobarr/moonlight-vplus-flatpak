#!/usr/bin/env python3

"""Decide whether a resolved upstream release needs a packaging build."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Release publication timestamp is missing")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def decide(upstream: dict, current: dict | None, packaging_commit: str) -> tuple[bool, str]:
    if upstream.get("selection") == "manual":
        return True, "Manual release selections are intentional overrides"
    if current is None:
        return True, "No previous build metadata is available"

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
    )
    if same_inputs:
        return False, "Upstream and packaging commits are unchanged"
    return True, "Upstream release or packaging commit changed"


def load_optional_json(path: Path | None) -> dict | None:
    if path is None:
        return None
    if not path.is_file():
        raise ValueError(f"Previous build metadata does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Previous build metadata is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("Previous build metadata must be a JSON object")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--packaging-commit", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    upstream = json.loads(args.upstream.read_text(encoding="utf-8"))
    should_build, reason = decide(
        upstream,
        load_optional_json(args.current),
        args.packaging_commit,
    )
    print(json.dumps({"should_build": should_build, "reason": reason}))


if __name__ == "__main__":
    main()
