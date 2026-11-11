#!/usr/bin/env python3
"""Generate a Quickshell application menu from the XDG menu spec + .desktop files.

Reads freedesktop menu definitions (/etc/xdg/menus/*.menu), evaluates every
<Include>/<Exclude> rule against the desktop entries found in the XDG
application directories, and builds the flat JSONC map the Quickshell menu
plugin consumes (shell/plugins/menu/MenuModel.js).

This is a library module as well as a CLI. `blackarch shell generate` imports
`generate()` directly; `bin/blackarch-xdg-menu-to-jsonc` is a thin wrapper around
`main()` for the command line.

The module name deliberately does not match a `blackarch <words>` route: the
dispatcher resolves `blackarch_modules.blackarch_<joined argv>` first, so a
module called `blackarch_xdg_menu` would capture `blackarch xdg menu ...` and be
handed the trailing words as arguments.

Usage:
  blackarch xdg menu to jsonc [options]

Options:
  --menu FILE      menu definition to read; repeatable, and all named files are
                   each emitted as their own root menu (default: DEFAULT_MENUS,
                   falling back to $XDG_MENU_PREFIX applications.menu)
  --root-id ID     id of the generated top-level menu (default: applications)
  --output FILE    write to FILE instead of stdout
  --no-merge       do not merge <MergeDir>/<DefaultMergeDirs> files
  --no-icons       emit no category glyphs
  --leftover LABEL label for a catch-all menu of unclaimed entries
  --no-leftover    drop entries no menu claimed
  --stats          print a per-menu entry count summary to stderr
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

SUFFIX = ".desktop"

# The menu definitions `blackarch shell generate` combines by default: the
# forensic suites plus the standard Xfce categories, each becoming its own
# top-level menu named after its file. Missing files are skipped, so a partial
# install still generates.
DEFAULT_MENUS: tuple[str, ...] = (
    "/etc/xdg/menus/red-applications.menu",
    "/etc/xdg/menus/mitre-applications.menu",
    "/etc/xdg/menus/blue-applications.menu",
    "/etc/xdg/menus/xfce-applications.menu",
    "/etc/xdg/menus/applications-merged/X-BlackArch.menu",
)

# Category glyphs, taken from the set already used by
# default/blackarch/blackarch-menu.jsonc so the generated tree renders in the
# same icon font. The menu plugin draws `icon` as TEXT, so the themed icon
# names carried by .directory files cannot be used here.
CATEGORY_ICONS = {
    "accessories": "\uf489",
    "accessibility": "\uf0d7",
    "development": "\U000f0d6e",
    "education": "\U000f09d1",
    "games": "\uf11b",
    "graphics": "\uf03e",
    "internet": "\uf268",
    "multimedia": "\uf03d",
    "office": "\uf15c",
    "science": "\U000f09d1",
    "settings": "\uf005",
    "system": "\ue615",
    "other": "\U000f003b",
    "archlinux": "\U000f08c7",
    "utility": "\uf489",
    "network": "\U000f06f3",
    "audiovideo": "\uf03d",
    "programming": "\U000f0d6e",
    "uncategorized": "\U000f003b",
    "applications": "\U000f003b",
    # File-derived root menus (red-applications.menu -> "Red Applications").
    "red": "\uf489",
    "mitre": "\U000f09d1",
    "blue": "\U000f06f3",
    "xfce": "\ue615",
}

# Fallback keyword match for menus the table above does not name explicitly
# (the red/mitre/blue forensic menus use their own category names).
CATEGORY_KEYWORDS = (
    ("usual", "\uf489"),
    # MITRE ATT&CK / red-team taxonomy names.
    ("recon", "\uf489"),
    ("resource development", "\U000f0d6e"),
    ("initial access", "\U000f0d6e"),
    ("execution", "\uf489"),
    ("persistence", "\U000f07f5"),
    ("privilege", "\U000f07f5"),
    ("evasion", "\U000f003b"),
    ("credential", "\U000f07f5"),
    ("discovery", "\U000f09d1"),
    ("lateral", "\U000f06f3"),
    ("collection", "\uf15c"),
    ("command", "\uf489"),
    ("exfil", "\U000f06f3"),
    ("impact", "\uf03e"),
    ("identify", "\U000f09d1"),
    ("protect", "\U000f07f5"),
    ("detect", "\U000f003b"),
    ("respond", "\uf489"),
    ("recover", "\U000f0453"),
    ("info", "\uf489"),
    ("vuln", "\U000f07f5"),
    ("service", "\uf487"),
    ("blackarch", "\ue90c"),
    ("game", "\uf11b"),
    ("video", "\uf03d"),
    ("audio", "\uf03d"),
    ("graphic", "\uf03e"),
    ("office", "\uf15c"),
    ("develop", "\U000f0d6e"),
    ("educat", "\U000f09d1"),
    ("science", "\U000f09d1"),
    ("forensic", "\U000f09d1"),
    ("setting", "\uf005"),
    ("system", "\ue615"),
    ("network", "\U000f06f3"),
    ("internet", "\uf268"),
    ("web", "\uf268"),
    ("exploit", "\uf489"),
    ("password", "\U000f07f5"),
    ("wireless", "\U000f06f3"),
    ("database", "\uf1c0"),
    ("recon", "\uf489"),
    ("tunnel", "\U000f06f3"),
    ("report", "\uf15c"),
    ("social", "\U000f066f"),
    ("sniff", "\uf489"),
    ("spoof", "\uf489"),
    ("reverse", "\uf489"),
    ("hardware", "\uef70"),
)


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return text.strip("-") or "item"


def humanize(value: str) -> str:
    """'red-applications' -> 'Red Applications'."""
    words = [word for word in re.split(r"[-_.\s]+", value.strip()) if word]
    return " ".join(word[:1].upper() + word[1:] for word in words) or value


def icon_for(label: str, name: str = "") -> str:
    # Prefer the menu's own <Name>: the .directory label can differ
    # (Arch names the Development menu "Programming", Multimedia "Sound & Video").
    for value in (name, label):
        key = slug(value)
        if key in CATEGORY_ICONS:
            return CATEGORY_ICONS[key]
        # "Red Applications" -> try "red", so any <team>-<thing> menu gets a glyph.
        first = key.split("-")[0]
        if first in CATEGORY_ICONS:
            return CATEGORY_ICONS[first]
    for value in (label, name):
        lowered = value.lower()
        for needle, glyph in CATEGORY_KEYWORDS:
            if needle in lowered:
                return glyph
    return ""


def xdg_dirs(env_name: str, default: list[str]) -> list[Path]:
    raw = os.environ.get(env_name, "")
    values = [v for v in raw.split(":") if v] if raw else list(default)
    return [Path(v) for v in values]


def data_dirs() -> list[Path]:
    return xdg_dirs("XDG_DATA_DIRS", ["/usr/local/share", "/usr/share"])


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def config_dirs() -> list[Path]:
    return xdg_dirs("XDG_CONFIG_DIRS", ["/etc/xdg"])


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def menu_prefix() -> str:
    return os.environ.get("XDG_MENU_PREFIX", "")


def app_dirs() -> list[Path]:
    dirs = [d / "applications" for d in data_dirs()]
    dirs.append(data_home() / "applications")
    return [d for d in dirs if d.is_dir()]


def directory_dirs() -> list[Path]:
    dirs = [d / "desktop-directories" for d in data_dirs()]
    dirs.append(data_home() / "desktop-directories")
    return [d for d in dirs if d.is_dir()]


def merge_dirs() -> list[Path]:
    return [d / "menus" / f"{menu_prefix()}applications-merged" for d in config_dirs()]


def locale_tag() -> str:
    for var in ("LC_MESSAGES", "LC_ALL", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX"):
            return value.split(".")[0].split("@")[0]
    return ""


def clean_exec(exec_str: str) -> str:
    """Drop desktop entry field codes; keep the command the user sees."""
    if not exec_str:
        return ""
    protected = exec_str.replace("%%", "\x00")
    protected = re.sub(r"%[fFuUdDnNivmck]", "", protected)
    return protected.replace("\x00", "%").strip()


class DesktopEntry:
    __slots__ = (
        "path",
        "ids",
        "name",
        "generic_name",
        "comment",
        "icon",
        "exec",
        "categories",
        "keywords",
        "no_display",
        "hidden",
        "type",
    )

    def __init__(self, path: Path, app_root: Path, locale: str):
        self.path = path
        self.ids: set[str] = set()
        self.name = ""
        self.generic_name = ""
        self.comment = ""
        self.icon = ""
        self.exec = ""
        self.type = ""
        self.no_display = False
        self.hidden = False
        self.categories: list[str] = []
        self.keywords: list[str] = []

        rel = path.relative_to(app_root)
        full = str(rel).replace("/", "-")
        self.ids.add(full)
        self.ids.add(full[: -len(SUFFIX)] if full.endswith(SUFFIX) else full)
        self.ids.add(path.name)
        self.ids.add(path.stem)

        fields: dict[str, str] = {}
        section = ""
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section != "Desktop Entry" or "=" not in line:
                continue
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()

        def pick(base: str) -> str:
            if not locale:
                return fields.get(base, "")
            for candidate in (
                f"{base}[{locale}]",
                f"{base}[{locale.split('_')[0]}]",
                base,
            ):
                if candidate in fields:
                    return fields[candidate]
            return ""

        self.name = pick("Name")
        self.generic_name = pick("GenericName")
        self.comment = pick("Comment")
        self.icon = fields.get("Icon", "")
        self.exec = fields.get("Exec", "")
        self.type = fields.get("Type", "Application")
        self.no_display = fields.get("NoDisplay", "").lower() == "true"
        self.hidden = fields.get("Hidden", "").lower() == "true"
        self.categories = [
            c.strip() for c in fields.get("Categories", "").split(";") if c.strip()
        ]
        self.keywords = [
            c.strip() for c in fields.get("Keywords", "").split(";") if c.strip()
        ]

    @property
    def app_id(self) -> str:
        """The desktop-file-id without the .desktop suffix (gtk-launch form)."""
        for value in self.ids:
            if value.endswith(SUFFIX):
                return value[: -len(SUFFIX)]
        return sorted(self.ids)[0]

    def label(self) -> str:
        return self.name or self.app_id


class MenuNode:
    def __init__(self, elem: ET.Element, parent: "MenuNode | None" = None):
        self.name = (elem.findtext("Name") or "").strip()
        self.directory = (elem.findtext("Directory") or "").strip()
        self.includes = elem.findall("Include")
        self.excludes = elem.findall("Exclude")
        self.only_unallocated = elem.find("OnlyUnallocated") is not None
        self.children: list[MenuNode] = [
            MenuNode(c, self) for c in elem.findall("Menu")
        ]
        self.parent = parent
        self.merge_files: list[Path] = []
        self.merge_dirs: list[Path] = []
        self.default_merge_dirs = elem.find("DefaultMergeDirs") is not None

        for tag, target in (
            ("MergeFile", self.merge_files),
            ("MergeDir", self.merge_dirs),
        ):
            for found in elem.findall(tag):
                text = (found.text or "").strip()
                if text:
                    target.append(Path(text))


def find_menu(node: MenuNode, name: str) -> MenuNode | None:
    if node.name == name:
        return node
    for child in node.children:
        found = find_menu(child, name)
        if found is not None:
            return found
    return None


def ensure_path(root: MenuNode, parts: list[str]) -> MenuNode | None:
    node = root
    for part in parts:
        part = part.strip()
        if not part:
            continue
        existing = next((c for c in node.children if c.name == part), None)
        if existing is None:
            existing = MenuNode(ET.Element("Menu"))
            existing.name = part
            existing.parent = node
            node.children.append(existing)
        node = existing
    return node


class MenuGenerator:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.locale = locale_tag()
        self.entries: list[DesktopEntry] = []
        self.directories: dict[str, dict[str, str]] = {}
        self.used_ids: set[str] = set()
        self.allocated: set[str] = set()
        self.out: dict[str, dict] = {}
        self.stats: list[tuple[str, int]] = []
        self.warnings: list[str] = []

    # ---------------------------------------------------------------- loading

    def load_entries(self) -> None:
        seen: set[Path] = set()
        for app_dir in app_dirs():
            try:
                candidates = sorted(app_dir.rglob(f"*{SUFFIX}"))
            except OSError:
                continue
            for path in candidates:
                try:
                    resolved = path.resolve()
                except OSError:
                    resolved = path
                if resolved in seen:
                    continue
                seen.add(resolved)
                entry = DesktopEntry(path, app_dir, self.locale)
                if not entry.name or entry.type != "Application":
                    continue
                if entry.no_display or entry.hidden or not entry.exec:
                    continue
                self.entries.append(entry)

    def load_directories(self) -> None:
        for directory in directory_dirs():
            for path in sorted(directory.glob("*.directory")):
                fields: dict[str, str] = {}
                section = ""
                try:
                    lines = path.read_text(errors="replace").splitlines()
                except OSError:
                    continue
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        section = line[1:-1]
                        continue
                    if section != "Desktop Entry" or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    fields[key.strip()] = value.strip()
                self.directories[path.name] = fields

    def directory_name(self, filename: str, fallback: str) -> str:
        fields = self.directories.get(filename)
        if not fields:
            return fallback
        if self.locale:
            for candidate in (
                f"Name[{self.locale}]",
                f"Name[{self.locale.split('_')[0]}]",
                "Name",
            ):
                if fields.get(candidate):
                    return fields[candidate]
        return fields.get("Name") or fallback

    # -------------------------------------------------------------- menu spec

    def menu_paths(self) -> list[Path]:
        """Every menu definition to read, in the order given."""
        if self.args.menu:
            paths = [Path(value) for value in self.args.menu]
        else:
            paths = [Path(value) for value in DEFAULT_MENUS if Path(value).is_file()]
            if not paths:
                paths = [self.resolve_menu_file()]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise SystemExit("menu definition not found: " + ", ".join(missing))
        return paths

    def resolve_menu_file(self) -> Path:
        prefix = menu_prefix()
        for base in (config_home(), *config_dirs()):
            candidate = base / "menus" / f"{prefix}applications.menu"
            if candidate.is_file():
                return candidate
        for base in (config_home(), *config_dirs()):
            candidate = base / "menus" / "arch-applications.menu"
            if candidate.is_file():
                return candidate
        for base in (config_home(), *config_dirs()):
            found = sorted((base / "menus").glob("*.menu"))
            if found:
                return found[0]
        raise SystemExit(
            "no menu definition found in " + ", ".join(str(d) for d in config_dirs())
        )

    def parse(self, path: Path) -> MenuNode:
        root = ET.parse(path).getroot()
        # The document element is <Menu> itself; only descend when it is a wrapper.
        elem = root if root.tag == "Menu" else root.find("Menu")
        if elem is None:
            raise SystemExit(f"no <Menu> element in {path}")
        return MenuNode(elem)

    def apply_moves(
        self, path: Path, root: MenuNode, index: dict[str, MenuNode]
    ) -> None:
        """Apply <Move><Old/><New/></Move> re-parenting from the raw XML.

        `index` holds every menu from every input file, so a move may pull in a
        menu that this file does not define (the red/mitre/blue menus re-parent
        Accessories, Development, ... which live in the standard menu). Such a
        node is cloned in, keeping the other file's own tree untouched.
        """
        try:
            xml_root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return
        elem = xml_root if xml_root.tag == "Menu" else xml_root.find("Menu")
        if elem is None:
            return
        for move in elem.findall("Move"):
            old = (move.findtext("Old") or "").strip()
            new = (move.findtext("New") or "").strip()
            if not old or not new:
                continue
            source = find_menu(root, old)
            if source is None and old in index:
                source = self.clone_tree(index[old])
            if source is None or source is root:
                self.warnings.append(f"move source not found: {old}")
                continue
            # <New> is the moved menu's full new path, so only the parent part
            # is created; the last component is this node's name at its new home.
            parts = [part.strip() for part in new.split("/") if part.strip()]
            if not parts:
                continue
            parent = ensure_path(root, parts[:-1]) if len(parts) > 1 else root
            if parent is None or parent is source or is_ancestor(source, parent):
                self.warnings.append(f"cannot move {old} -> {new}")
                continue
            if source.parent is parent:
                continue
            if source.parent is not None:
                source.parent.children.remove(source)
            source.name = parts[-1]
            parent.children.append(source)
            source.parent = parent

    def merge_into(self, node: MenuNode, merged: MenuNode) -> None:
        # Same-named menus combine their rules, so a category shared by two
        # definitions keeps the entries of both.
        if node.only_unallocated and merged.only_unallocated:
            # An Include-free OnlyUnallocated menu already claims everything
            # still unallocated, so it is the broader of the two.
            if not node.includes or not merged.includes:
                node.includes = []
            else:
                node.includes.extend(merged.includes)
        else:
            node.includes.extend(merged.includes)
        node.excludes.extend(merged.excludes)
        for child in merged.children:
            existing = next((c for c in node.children if c.name == child.name), None)
            if existing is None:
                child.parent = node
                node.children.append(child)
            else:
                self.merge_into(existing, child)

    def load_merges(
        self, node: MenuNode, depth: int = 0, explicit: frozenset[Path] = frozenset()
    ) -> None:
        if depth > 8 or self.args.no_merge:
            return
        if node.default_merge_dirs:
            for directory in merge_dirs():
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.menu")):
                    # An explicitly named file is emitted as its own root, so
                    # pulling it in again here would duplicate its whole subtree.
                    if path in explicit:
                        continue
                    self.merge_file(node, path)
        for path in node.merge_files:
            self.merge_file(node, path)
        for directory in node.merge_dirs:
            if directory.is_dir():
                for path in sorted(directory.glob("*.menu")):
                    self.merge_file(node, path)
        for child in list(node.children):
            self.load_merges(child, depth + 1, explicit)

    def merge_file(self, node: MenuNode, path: Path) -> None:
        try:
            merged = self.parse(path)
        except (ET.ParseError, OSError) as exc:
            self.warnings.append(f"{path}: {exc}")
            return
        self.merge_into(node, merged)

    def union_index(self, trees: list[MenuNode]) -> dict[str, MenuNode]:
        """Every menu from every input file, keyed by <Name>, first one wins."""
        index: dict[str, MenuNode] = {}
        for tree in trees:
            self._index_tree(tree, index)
        return index

    def _index_tree(self, node: MenuNode, index: dict[str, MenuNode]) -> None:
        index.setdefault(node.name, node)
        # A <Move><Old/> may name a menu by the label its .directory provides
        # (xfce's "Network" menu is displayed as "Internet").
        label = self.directory_name(node.directory, node.name)
        if label and label != node.name:
            index.setdefault(label, node)
        for child in node.children:
            self._index_tree(child, index)

    def clone_tree(self, node: MenuNode) -> MenuNode:
        """Deep copy a menu subtree, so a moved node can join another tree."""
        clone = MenuNode(ET.Element("Menu"))
        clone.name = node.name
        clone.directory = node.directory
        clone.includes = node.includes
        clone.excludes = node.excludes
        clone.only_unallocated = node.only_unallocated
        clone.merge_files = list(node.merge_files)
        clone.merge_dirs = list(node.merge_dirs)
        clone.default_merge_dirs = node.default_merge_dirs
        for child in node.children:
            copy = self.clone_tree(child)
            copy.parent = clone
            clone.children.append(copy)
        return clone

    # ------------------------------------------------------------- evaluation

    def eval_rule(self, node: ET.Element, entry: DesktopEntry) -> bool:
        tag = node.tag
        if tag == "All":
            return True
        if tag == "Category":
            return (node.text or "").strip() in entry.categories
        if tag == "Filename":
            return (node.text or "").strip() in entry.ids
        if tag == "And":
            return all(self.eval_rule(child, entry) for child in node)
        if tag == "Or":
            return any(self.eval_rule(child, entry) for child in node)
        if tag == "Not":
            return not any(self.eval_rule(child, entry) for child in node)
        return True

    def matches(self, rule_root: ET.Element, entry: DesktopEntry) -> bool:
        """An <Include>/<Exclude> lists alternative rules; any match is enough.

        The arch menu relies on this: Development is
        <And><Category>Development</Category></And> plus <Filename>emacs.desktop</Filename>,
        i.e. the category set *or* that one file.
        """
        return any(self.eval_rule(child, entry) for child in rule_root)

    def menu_entries(self, node: MenuNode) -> list[DesktopEntry]:
        included = {
            entry.path: entry
            for rule in node.includes
            for entry in self.entries
            if self.matches(rule, entry)
        }
        excluded = {
            entry.path
            for rule in node.excludes
            for entry in self.entries
            if self.matches(rule, entry)
        }
        selected = [entry for path, entry in included.items() if path not in excluded]
        if node.only_unallocated:
            selected = [entry for entry in selected if entry.path not in self.allocated]
        self.allocated.update(entry.path for entry in selected)
        selected.sort(key=lambda entry: entry.label().lower())
        return selected

    # ----------------------------------------------------------------- output

    def unique_id(self, base: str) -> str:
        candidate = base
        counter = 2
        while candidate in self.used_ids:
            candidate = f"{base}-{counter}"
            counter += 1
        self.used_ids.add(candidate)
        return candidate

    def emit_menu(self, node: MenuNode, parent_id: str, is_root: bool = False) -> None:
        label = self.directory_name(node.directory, node.name)
        if is_root:
            menu_id = self.unique_id(parent_id)
        else:
            base = f"{parent_id}.{slug(node.name)}" if parent_id else slug(node.name)
            menu_id = self.unique_id(base)
        entries = self.menu_entries(node)
        if not entries and not node.children:
            self.warnings.append(f"empty menu skipped: {label}")
            return
        item: dict[str, object] = {"label": label}
        if self.args.icons:
            glyph = icon_for(label, node.name)
            if glyph:
                item["icon"] = glyph
        self.out[menu_id] = item
        for child in node.children:
            self.emit_menu(child, menu_id)
        self.stats.append((menu_id, len(entries)))
        for entry in entries:
            self.emit_app(entry, menu_id)

    def emit_app(self, entry: DesktopEntry, menu_id: str) -> None:
        app_id = self.unique_id(f"{menu_id}.{slug(entry.app_id)}")
        item: dict[str, object] = {
            "label": entry.label(),
            "kind": "app",
            "appId": entry.app_id,
            "appIcon": entry.icon,
            "action": clean_exec(entry.exec),
        }
        aliases = [
            value for value in (entry.generic_name, " ".join(entry.keywords)) if value
        ]
        if aliases:
            item["aliases"] = aliases
        if entry.comment:
            item["description"] = entry.comment
        self.out[app_id] = item

    # ------------------------------------------------------------------- run

    def emit_file_root(self, path: Path, tree: MenuNode) -> None:
        """One top-level menu per input file, named after that file.

        The file stem is the root menu's identity (`red-applications`), so the
        four definitions stay separate instead of collapsing into one tree; the
        file's own submenus hang underneath it.
        """
        root_id = self.unique_id(slug(path.stem))
        label = humanize(path.stem)
        item: dict[str, object] = {"label": label}
        if self.args.icons:
            glyph = icon_for(label)
            if glyph:
                item["icon"] = glyph
        self.out[root_id] = item
        for child in tree.children:
            self.emit_menu(child, root_id)
        entries = self.menu_entries(tree)
        self.stats.append((root_id, len(entries)))
        for entry in entries:
            self.emit_app(entry, root_id)

    def emit_leftover(self, parent_id: str) -> None:
        """Catch entries no menu claimed, so the menu is a complete app list.

        The arch "Other" menu only takes entries carrying Category=Application, so
        most of the 550 installed apps would otherwise vanish.
        """
        remaining = [
            entry for entry in self.entries if entry.path not in self.allocated
        ]
        if not remaining:
            return
        remaining.sort(key=lambda entry: entry.label().lower())
        label = self.args.leftover
        menu_id = self.unique_id(f"{parent_id}.{slug(label)}")
        item: dict[str, object] = {"label": label}
        if self.args.icons:
            glyph = icon_for(label, "")
            if glyph:
                item["icon"] = glyph
        self.out[menu_id] = item
        for entry in remaining:
            self.emit_app(entry, menu_id)
        self.stats.append((menu_id, len(remaining)))

    def run(self) -> dict[str, dict]:
        self.load_entries()
        self.load_directories()
        paths = self.menu_paths()
        trees = [self.parse(path) for path in paths]
        index = self.union_index(trees)
        explicit = frozenset(path.resolve() for path in paths)
        for path, tree in zip(paths, trees):
            self.apply_moves(path, tree, index)
            self.load_merges(tree, explicit=explicit)
        if len(trees) == 1:
            # A single definition keeps the requested root identity.
            self.emit_menu(trees[0], self.args.root_id, is_root=True)
            leftover_parent = self.args.root_id
        else:
            # Each file is its own top-level menu, named after the file.
            for path, tree in zip(paths, trees):
                self.emit_file_root(path, tree)
            leftover_parent = ""
        if self.args.leftover:
            self.emit_leftover(leftover_parent)
        return self.out


def is_ancestor(candidate: MenuNode, node: MenuNode) -> bool:
    current = node.parent
    while current is not None:
        if current is candidate:
            return True
        current = current.parent
    return False


def _namespace(
    menus: Sequence[str] | None,
    root_id: str,
    icons: bool,
    leftover: str | None,
    merge: bool,
) -> argparse.Namespace:
    return argparse.Namespace(
        menu=list(menus) if menus else None,
        root_id=slug(root_id),
        output=None,
        no_merge=not merge,
        icons=icons,
        leftover=(leftover or "").strip(),
        no_leftover=leftover is None,
        stats=False,
    )


def generate(
    menus: Sequence[str] | None = None,
    root_id: str = "blackarch",
    icons: bool = True,
    leftover: str | None = "Uncategorized",
    merge: bool = True,
) -> dict[str, dict]:
    """Build the Quickshell menu map and return it.

    `menus` is the list of menu definitions to read; None means DEFAULT_MENUS
    (only those that exist). With more than one file each becomes its own
    top-level menu named after the file, so the result maps directly into the
    JSONC the menu plugin loads. `leftover=None` drops entries no menu claimed.
    """
    return MenuGenerator(_namespace(menus, root_id, icons, leftover, merge)).run()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="blackarch xdg menu to jsonc",
        description="Generate a Quickshell application menu from the XDG menu spec.",
    )
    parser.add_argument(
        "--menu",
        action="extend",
        nargs="+",
        metavar="FILE",
        help="menu definition to read; repeatable, and each named file is "
        "emitted as its own top-level menu (default: the red/mitre/blue/xfce "
        "definitions plus applications-merged/X-BlackArch.menu)",
    )
    parser.add_argument(
        "--root-id", default="applications", help="id of the top-level menu"
    )
    parser.add_argument("--output", help="write to FILE instead of stdout")
    parser.add_argument(
        "--no-merge", action="store_true", help="skip merged menu files"
    )
    parser.add_argument(
        "--no-icons", action="store_true", help="emit no category glyphs"
    )
    parser.add_argument(
        "--leftover",
        default="Uncategorized",
        metavar="LABEL",
        help="label for a catch-all menu of entries no menu claimed "
        "(default: Uncategorized; empty disables)",
    )
    parser.add_argument(
        "--no-leftover", action="store_true", help="drop entries no menu claimed"
    )
    parser.add_argument(
        "--stats", action="store_true", help="print per-menu counts to stderr"
    )
    args = parser.parse_args(argv)

    args.root_id = slug(args.root_id)
    args.icons = not args.no_icons
    args.leftover = (args.leftover or "").strip()
    if args.no_leftover:
        args.leftover = ""
    generator = MenuGenerator(args)
    data = generator.run()

    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {len(data)} items to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)

    if args.stats:
        for menu_id, count in generator.stats:
            print(f"{count:4d}  {menu_id}", file=sys.stderr)
    for warning in generator.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
