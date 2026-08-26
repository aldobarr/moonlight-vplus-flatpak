#!/usr/bin/env python3

"""Create a build manifest for one resolved upstream release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def update_manifest(
    manifest_path: Path,
    tag: str,
    commit: str,
    version: str,
    release_date: str,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    moonlight_modules = [
        module for module in manifest.get("modules", []) if module.get("name") == "moonlight"
    ]
    if len(moonlight_modules) != 1:
        raise ValueError("Manifest must contain exactly one moonlight module")

    moonlight = moonlight_modules[0]
    git_sources = [
        source
        for source in moonlight.get("sources", [])
        if source.get("type") == "git"
        and source.get("url") == "https://github.com/qiin2333/moonlight-qt.git"
    ]
    if len(git_sources) != 1:
        raise ValueError("Moonlight module must contain exactly one upstream Git source")

    git_sources[0]["tag"] = tag
    git_sources[0]["commit"] = commit
    build_options = moonlight.setdefault("build-options", {})
    environment = build_options.setdefault("env", {})
    environment["MOONLIGHT_FLATPAK_VERSION"] = version
    environment["MOONLIGHT_FLATPAK_RELEASE_DATE"] = release_date

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-date", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    update_manifest(
        args.manifest,
        args.tag,
        args.commit,
        args.version,
        args.release_date,
    )


if __name__ == "__main__":
    main()
