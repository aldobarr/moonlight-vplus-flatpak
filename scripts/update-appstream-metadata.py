#!/usr/bin/env python3

"""Update the installed Moonlight AppStream metadata for this Flatpak."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import re
import xml.etree.ElementTree as ET
from pathlib import Path


VERSION_PATTERN = re.compile(r"^[0-9][0-9A-Za-z.+_-]*$")


def update_metadata(
    path: Path,
    app_id: str,
    version: str,
    release_date: str,
    release_url: str,
    release_notes_base64: str,
) -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid AppStream version: {version!r}")

    dt.date.fromisoformat(release_date)
    try:
        release_notes = base64.b64decode(
            release_notes_base64,
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ValueError("Invalid base64-encoded release notes") from error

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
    else:
        releases.clear()

    current_release = ET.SubElement(
        releases,
        "release",
        {"version": version, "date": release_date},
    )
    details = ET.SubElement(current_release, "url", {"type": "details"})
    details.text = release_url
    paragraphs = [line.strip() for line in release_notes.splitlines() if line.strip()]
    if paragraphs:
        description = ET.SubElement(current_release, "description")
        for paragraph in paragraphs:
            ET.SubElement(description, "p").text = paragraph

    ET.indent(tree, space="  ")
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-date", required=True)
    parser.add_argument("--release-url", required=True)
    parser.add_argument("--release-notes-base64", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    update_metadata(
        args.path,
        args.app_id,
        args.version,
        args.release_date,
        args.release_url,
        args.release_notes_base64,
    )


if __name__ == "__main__":
    main()
