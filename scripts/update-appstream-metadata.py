#!/usr/bin/env python3

"""Update the installed Moonlight AppStream metadata for this Flatpak."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import xml.etree.ElementTree as ET
from pathlib import Path


VERSION_PATTERN = re.compile(r"^[0-9][0-9A-Za-z.+_-]*$")


def update_metadata(path: Path, app_id: str, version: str, release_date: str) -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid AppStream version: {version!r}")

    dt.date.fromisoformat(release_date)
    tree = ET.parse(path)
    component = tree.getroot()

    component_id = component.find("id")
    if component_id is None or not component_id.text:
        raise ValueError("AppStream metadata does not contain a component ID")
    component_id.text = app_id

    launchable = component.find("launchable[@type='desktop-id']")
    if launchable is None:
        raise ValueError("AppStream metadata does not contain a desktop launchable")
    launchable.text = f"{app_id}.desktop"

    releases = component.find("releases")
    if releases is None:
        releases = ET.SubElement(component, "releases")

    current_release = None
    for release in list(releases):
        if release.tag != "release" or release.get("version") != version:
            continue
        if current_release is None:
            current_release = release
        else:
            releases.remove(release)

    if current_release is None:
        current_release = ET.Element("release")
        current_release.set("version", version)
    else:
        releases.remove(current_release)

    current_release.set("date", release_date)
    releases.insert(0, current_release)

    ET.indent(tree, space="  ")
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-date", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    update_metadata(args.path, args.app_id, args.version, args.release_date)


if __name__ == "__main__":
    main()
