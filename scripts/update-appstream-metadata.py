#!/usr/bin/env python3

"""Update the installed Moonlight AppStream metadata for this Flatpak."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import gzip
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


VERSION_PATTERN = re.compile(r"^[0-9][0-9A-Za-z.+_-]*$")
REMOTE_ICON_URL = "https://moonlight.barreras.dev/repo/moonlight.png"


def update_metadata(
    path: Path,
    app_id: str,
    version: str,
    release_history_base64: str,
) -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid AppStream version: {version!r}")

    try:
        release_history = json.loads(base64.b64decode(
            release_history_base64,
            validate=True,
        ).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid base64-encoded release history") from error
    validate_release_history(release_history, version)

    if path.suffix == ".gz":
        tree = ET.ElementTree(ET.fromstring(gzip.decompress(path.read_bytes())))
    else:
        tree = ET.parse(path)

    root = tree.getroot()
    component = root if root.tag == "component" else root.find("component")
    if component is None:
        raise ValueError("AppStream metadata does not contain a component")

    component_id = component.find("id")
    if component_id is None or not component_id.text:
        raise ValueError("AppStream metadata does not contain a component ID")
    component_id.text = app_id

    launchable = component.find("launchable[@type='desktop-id']")
    if launchable is None:
        raise ValueError("AppStream metadata does not contain a desktop launchable")
    launchable.text = f"{app_id}.desktop"

    remote_icon = component.find("icon[@type='remote']")
    if remote_icon is None:
        remote_icon = ET.SubElement(component, "icon")
    remote_icon.attrib = {"type": "remote", "width": "256", "height": "256"}
    remote_icon.text = REMOTE_ICON_URL

    releases = component.find("releases")
    if releases is None:
        releases = ET.SubElement(component, "releases")
    else:
        releases.clear()

    for history_entry in release_history:
        release = ET.SubElement(
            releases,
            "release",
            {"version": history_entry["version"], "date": history_entry["date"]},
        )
        details = ET.SubElement(release, "url", {"type": "details"})
        details.text = history_entry["url"]
        paragraphs = [
            line.strip()
            for line in history_entry["description"].splitlines()
            if line.strip()
        ]
        if paragraphs:
            description = ET.SubElement(release, "description")
            for paragraph in paragraphs:
                ET.SubElement(description, "p").text = paragraph

    ET.indent(tree, space="  ")
    if path.suffix == ".gz":
        xml = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
        path.write_bytes(gzip.compress(xml, mtime=0))
    else:
        tree.write(path, encoding="UTF-8", xml_declaration=True)


def validate_release_history(value: Any, current_version: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("Release history must be a non-empty list")
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("Release history entries must be objects")
        version = entry.get("version")
        release_date = entry.get("date")
        release_url = entry.get("url")
        description = entry.get("description")
        if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
            raise ValueError(f"Invalid AppStream version: {version!r}")
        if not isinstance(release_date, str):
            raise ValueError("Release history entry has no date")
        dt.date.fromisoformat(release_date)
        if not isinstance(release_url, str) or not release_url:
            raise ValueError("Release history entry has no URL")
        if not isinstance(description, str):
            raise ValueError("Release history entry has no description")
    if value[0]["version"] != current_version:
        raise ValueError("Current version must be the first release history entry")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-history-base64", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    update_metadata(
        args.path,
        args.app_id,
        args.version,
        args.release_history_base64,
    )


if __name__ == "__main__":
    main()
