#!/usr/bin/env python3

"""Stage an OSTree repository as deterministically named release assets."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

GITHUB_ASSET_LIMIT = 1_000
GITHUB_ASSET_SIZE_LIMIT = 2 * 1024 * 1024 * 1024


def repository_asset_name(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return f"repo-{digest}"


def stage_repository(repository: Path, output: Path, reserved_assets: int) -> int:
    if not repository.is_dir():
        raise ValueError(f"Repository directory does not exist: {repository}")
    if reserved_assets < 1 or reserved_assets >= GITHUB_ASSET_LIMIT:
        raise ValueError("Reserved asset count must be between 1 and 999")

    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(f"Release asset directory must be empty: {output}")

    repository_file_count = 0
    asset_names = set()
    for source in sorted(repository.rglob("*")):
        if source.is_symlink():
            raise ValueError(f"Repository must not contain symbolic links: {source}")
        if not source.is_file():
            continue

        relative_path = source.relative_to(repository).as_posix()
        asset_name = repository_asset_name(relative_path)
        if asset_name in asset_names:
            raise ValueError(f"Repository asset-name collision for {relative_path}")
        asset_names.add(asset_name)

        size = source.stat().st_size
        if size >= GITHUB_ASSET_SIZE_LIMIT:
            raise ValueError(f"Repository file exceeds GitHub's per-asset limit: {relative_path}")

        destination = output / asset_name
        shutil.copyfile(source, destination)
        repository_file_count += 1

    if repository_file_count + reserved_assets > GITHUB_ASSET_LIMIT:
        raise ValueError(
            "Release would exceed GitHub's 1,000-asset limit: "
            f"{repository_file_count} repository files plus {reserved_assets} reserved assets"
        )
    return repository_file_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--reserved-assets",
        type=int,
        default=2,
        help="Assets reserved for build metadata and the Flatpak bundle",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repository_file_count = stage_repository(
        args.repository, args.output, args.reserved_assets
    )
    print(f"Staged {repository_file_count} repository files")


if __name__ == "__main__":
    main()
