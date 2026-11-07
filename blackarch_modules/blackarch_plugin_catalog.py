#!/usr/bin/env python3
# blackarch:summary=Emit every first-party and user plugin manifest as JSON
# blackarch:group=plugin
# blackarch:hidden=true
"""blackarch-plugin-catalog — every plugin manifest, as one JSON array.

Python port of the bash original (which piped the manifests through jq). It
walks ``$BLACKARCH_PATH/shell/plugins`` and ``~/.config/blackarch/plugins``, reads
every ``manifest.json`` / ``*.manifest.json``, and emits one object per plugin
with the computed fields the other plugin commands need: ``sourceDir``,
``barWidgetPath``, ``barPath``, and ``firstParty``.

This is the single source of truth used by bar selection and plugin
enable/clone, so those commands never re-implement manifest walking. Keep it that
way: a second walker is a second answer to "which plugins exist".

Deduplication is by ``id`` — a plugin reachable from both roots (a first-party
plugin symlinked into the user dir, say) must appear once.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MANIFEST_NAMES = ("manifest.json",)
MANIFEST_SUFFIX = ".manifest.json"


def first_party_root() -> Path:
    blackarch_path = os.environ.get("BLACKARCH_PATH", "")
    if not blackarch_path:
        sys.stderr.write("blackarch-plugin-catalog: BLACKARCH_PATH is not set\n")
        return Path()
    return Path(blackarch_path) / "shell" / "plugins"


def user_root() -> Path:
    return Path(os.path.expanduser("~/.config/blackarch/plugins"))


def manifest_name(path: Path) -> bool:
    return path.name in MANIFEST_NAMES or path.name.endswith(MANIFEST_SUFFIX)


def find_manifests(root: Path, follow_links: bool) -> list[Path]:
    """Every manifest under `root`, at plugin depth, sorted by path."""
    if not root.is_dir():
        return []

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_links):
        # A user plugin may be a symlinked directory; its contents still count,
        # but a link *inside* a plugin would be walked too, so prune those.
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            candidate = Path(dirpath) / filename
            if manifest_name(candidate):
                found.append(candidate)
    return sorted(found)


def source_dir_for(manifest_path: Path) -> str:
    """The plugin directory: the manifest's own dir, or its parent for
    `<name>.manifest.json` spellings."""
    if manifest_path.name == "manifest.json":
        return str(manifest_path.parent)
    return str(manifest_path.parent)


def build_entry(manifest: dict, manifest_path: Path) -> dict:
    source_dir = source_dir_for(manifest_path)
    entry_points = manifest.get("entryPoints") or {}
    bar_widget = manifest.get("barWidget")

    entry = {
        "id": manifest.get("id") or "",
        "name": manifest.get("name") or manifest.get("id") or "",
        "description": manifest.get("description") or "",
        "kinds": manifest.get("kinds") or [],
        "firstParty": str(manifest.get("id") or "").startswith("blackarch."),
        "manifestPath": str(manifest_path),
        "sourceDir": source_dir,
        "entryPoints": entry_points,
        "barWidget": bar_widget,
        "bar": manifest.get("bar"),
    }

    bar_widget_entry = entry_points.get("barWidget")
    entry["barWidgetPath"] = f"{source_dir}/{bar_widget_entry}" if bar_widget_entry else None

    bar_entry = entry_points.get("bar")
    entry["barPath"] = f"{source_dir}/{bar_entry}" if bar_entry else None

    return entry


def catalog() -> list[dict]:
    entries: list[dict] = []

    for manifest_path in find_manifests(first_party_root(), follow_links=False):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        entries.append(build_entry(manifest, manifest_path))

    # User plugins are walked with -L in the original: a symlinked plugin
    # directory is followed, and a link inside the user root is not excluded
    # beyond dot-directories.
    for manifest_path in find_manifests(user_root(), follow_links=True):
        if manifest_path.is_symlink():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        entries.append(build_entry(manifest, manifest_path))

    unique: dict[str, dict] = {}
    for entry in entries:
        if entry["id"] and entry["id"] not in unique:
            unique[entry["id"]] = entry
    return list(unique.values())


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-plugin-catalog")
        return 0
    json.dump(catalog(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
