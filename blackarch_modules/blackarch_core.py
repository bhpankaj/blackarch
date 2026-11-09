#!/usr/bin/env python3
"""Blackarch command center.

Python port of the bash `blackarch` dispatcher: scans its own bin directory for
`blackarch-*` executables, reads `# blackarch:key=value` metadata headers, and
either dispatches to the real binary or renders help / command listings.

Usage:
  blackarch <command> [args...]
  blackarch commands [--all] [--json] [--markdown] [--check]
  blackarch <group> --help
  blackarch <group> <command> --help
"""

from __future__ import annotations

import importlib
import json
import locale
import os
import re
import sys
from pathlib import Path
from typing import Callable, TextIO

BLACKARCH_BIN_DIR = Path("/opt/blackarch/bin")
METADATA_SCAN_LIMIT = 80


def _init_collation() -> Callable[[str], str]:
    """Match GNU `sort`: collate with the runtime locale, not by byte value."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    return locale.strxfrm


collate = _init_collation()

COMMAND_KEYS: list[str] = []
ROUTE_COLLISIONS: list[str] = []

COMMAND_ROUTE: dict[str, str] = {}
COMMAND_FALLBACK_ROUTE: dict[str, str] = {}
COMMAND_BINARY: dict[str, str] = {}
COMMAND_GROUP: dict[str, str] = {}
COMMAND_NAME: dict[str, str] = {}
COMMAND_SUMMARY: dict[str, str] = {}
COMMAND_USAGE: dict[str, str] = {}
COMMAND_ARGS: dict[str, str] = {}
COMMAND_EXAMPLES: dict[str, str] = {}
COMMAND_REQUIRES_SUDO: dict[str, str] = {}
COMMAND_HIDDEN: dict[str, str] = {}
COMMAND_ALIASES: dict[str, str] = {}
COMMAND_HAS_SUMMARY: dict[str, str] = {}
COMMAND_METADATA_ERRORS: dict[str, str] = {}
ROUTE_TO_KEY: dict[str, str] = {}
ROUTE_IS_ALIAS: dict[str, str] = {}
BINARY_TO_KEY: dict[str, str] = {}

GROUP_DESCRIPTIONS: dict[str, str] = {
    "agent": "AI coding agent usage data",
    "audio": "Audio input and output controls",
    "bar": "Blackarch shell bar layout and settings",
    "battery": "Battery status helpers",
    "bluetooth": "Bluetooth device controls",
    "branch": "Blackarch git branch management",
    "branding": "About and screensaver branding",
    "brightness": "Display and keyboard brightness",
    "capture": "Screenshots and screen recording",
    "channel": "Blackarch release channel management",
    "clipboard": "Clipboard helpers",
    "cmd": "Command and shortcut helpers",
    "config": "System configuration helpers",
    "debug": "Diagnostics and support logs",
    "finalize": "Finalize user setup",
    "default": "Default application selection",
    "dev": "Blackarch development tools",
    "disk": "Disk performance helpers",
    "display": "Display and text scaling",
    "dns": "DNS resolver configuration",
    "drive": "Drive selection and encryption",
    "file": "File selection helpers",
    "font": "Font management",
    "games": "Game launchers and helpers",
    "hibernation": "Hibernation setup and removal",
    "hook": "User hook runner",
    "hw": "Hardware detection and controls",
    "hyprland": "Hyprland window, monitor, and toggle controls",
    "install": "Optional software installers",
    "installer": "Blackarch installer (blackarch_modules.blackarch_installer)",
    "installed": "Installed optional service checks",
    "launch": "Application launchers",
    "menu": "Blackarch menu commands",
    "migrate": "Migration runner",
    "monitor": "Monitor status helpers",
    "network": "Network status helpers",
    "notification": "Notification helpers",
    "mise": "Mise tool wrappers",
    "openclaw": "OpenClaw agent platform setup",
    "osd": "On-screen display status helpers",
    "pkg": "Package management helpers",
    "plugin": "Blackarch shell plugin and bar widget management",
    "plymouth": "Plymouth boot theme management",
    "power": "Power supply detection",
    "powerprofiles": "Power profile management",
    "refresh": "Reset config to defaults",
    "reinstall": "Reinstall and reset workflows",
    "reminder": "Desktop notification reminders",
    "remove": "Removal workflows",
    "restart": "Restart Blackarch components",
    "setup": "Interactive setup wizards",
    "shell": "Blackarch shell IPC helpers",
    "screensaver": "Screensaver branding and animation",
    "snapshot": "System snapshots",
    "sudo": "Sudo configuration helpers",
    "system": "System status, reboot, shutdown, logout, and lock",
    "tailscale": "Tailscale helpers",
    "theme": "Theme management",
    "toggle": "Toggle Blackarch features",
    "transcode": "Image and video transcoding",
    "tui": "Terminal UI launchers",
    "update": "Blackarch and system updates",
    "version": "Version and channel information",
    "voxtype": "Voxtype dictation",
    "weather": "Weather status",
    "webapp": "Web app launchers",
    "wifi": "Wi-Fi helpers",
    "windows": "Windows VM management",
}

# Module-backed commands: the dispatcher has no `blackarch-<name>` executable
# for these, so it hands them to a Python module instead of exec'ing a binary.
# Keys are routes ("blackarch private"), values are module names.
MODULE_COMMANDS: dict[str, str] = {
    "blackarch private": "blackarch_core_execute",
    "blackarch work": "blackarch_core_execute",
    "blackarch webapp": "blackarch_core_execute",
    "blackarch flatpak-ulaa": "blackarch_core_execute",
    "blackarch window": "blackarch_core_execute",
    "blackarch focus": "blackarch_core_execute",
    "blackarch gui": "blackarch_core_execute",
    "blackarch tui": "blackarch_core_execute",
    "blackarch vpn": "blackarch_core_execute",
    "blackarch update": "blackarch_core_execute",
    "blackarch update-system": "blackarch_core_execute",
    "blackarch brightness": "blackarch_core_execute",
    "blackarch audio": "blackarch_core_execute",
    "blackarch charger": "blackarch_core_execute",
    "blackarch banner": "blackarch_core_execute",
    "blackarch quickshell": "blackarch_core_execute",
}

# Bash [[:space:]] is locale dependent; this is the portable ASCII set.
SPACE = r"[ \t\r\n\f\v]"
METADATA_RE = re.compile(rf"^{SPACE}*#{SPACE}*blackarch:([A-Za-z0-9_-]+)=(.*)$")
COMMENT_RE = re.compile(rf"^{SPACE}*#{SPACE}*(.+)$")
BLANK_RE = re.compile(rf"^{SPACE}*$")
PLAIN_COMMENT_RE = re.compile(rf"^{SPACE}*#")


def join_words(separator: str, words: list[str]) -> str:
    return separator.join(words)


def append_pipe_value(current: str, addition: str) -> str:
    if not current:
        return addition
    return f"{current}|{addition}"


def split_pipe_values(values: str) -> list[str]:
    """Split a `|`-joined value, trimming one leading/trailing space per field."""
    out: list[str] = []
    for value in values.split("|"):
        if value.startswith(" "):
            value = value[1:]
        if value.endswith(" "):
            value = value[:-1]
        if value:
            out.append(value)
    return out


def remaining_has_flag(args: list[str], flags: set[str]) -> bool:
    """True when any token before a `--` separator is one of `flags`."""
    for token in args:
        if token == "--":
            break
        if token in flags:
            return True
    return False


def remaining_has_help_flag(args: list[str]) -> bool:
    return remaining_has_flag(args, {"--help", "-h"})


def remaining_has_json_flag(args: list[str]) -> bool:
    return remaining_has_flag(args, {"--json"})


def register_route(route: str, key: str, is_alias: bool = False) -> None:
    if not route or not key:
        return

    existing = ROUTE_TO_KEY.get(route)
    if existing is not None and existing != key:
        ROUTE_COLLISIONS.append(f"{route} -> {existing} conflicts with {key}")
        return

    ROUTE_TO_KEY[route] = key
    if is_alias:
        ROUTE_IS_ALIAS[route] = "true"


def register_command(file: Path) -> None:
    file_binary = file.name
    group = ""
    name = ""
    summary = ""
    args = ""
    examples = ""
    aliases = ""
    requires_sudo = ""
    hidden = ""
    name_seen = False
    has_summary = False
    metadata_errors = ""
    fallback_summary = ""

    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    for line_number, line in enumerate(text.split("\n")[:METADATA_SCAN_LIMIT], start=1):
        if line_number == 1 and line.startswith("#!"):
            continue
        if BLANK_RE.match(line):
            continue
        if not PLAIN_COMMENT_RE.match(line):
            break

        match = METADATA_RE.match(line)
        if match:
            metadata_key = match.group(1)
            metadata_value = match.group(2)
            if metadata_value.endswith("\r"):
                metadata_value = metadata_value[:-1]
            metadata_value = metadata_value.replace("\t", " ")

            if metadata_key == "group":
                group = metadata_value
            elif metadata_key == "name":
                name = metadata_value
                name_seen = True
            elif metadata_key == "summary":
                summary = metadata_value
                has_summary = metadata_value != ""
            elif metadata_key == "args":
                args = metadata_value
            elif metadata_key == "examples":
                examples = metadata_value
            elif metadata_key in ("alias", "aliases"):
                aliases = metadata_value
            elif metadata_key == "requires-sudo":
                requires_sudo = metadata_value
                if metadata_value != "true":
                    metadata_errors = append_pipe_value(
                        metadata_errors, "requires-sudo must be omitted or true"
                    )
            elif metadata_key == "hidden":
                hidden = metadata_value
                if metadata_value != "true":
                    metadata_errors = append_pipe_value(
                        metadata_errors, "hidden must be omitted or true"
                    )
            continue

        if not fallback_summary:
            comment = COMMENT_RE.match(line)
            if comment:
                fallback_summary = comment.group(1)
                if fallback_summary.endswith("\r"):
                    fallback_summary = fallback_summary[:-1]
                fallback_summary = fallback_summary.replace("\t", " ")
                if not fallback_summary or fallback_summary.startswith("blackarch:"):
                    fallback_summary = ""

    stem = file_binary.removeprefix("blackarch-")
    fallback_group = stem
    fallback_name = ""
    fallback_route = "blackarch " + stem.replace("-", " ")

    if "-" in stem:
        fallback_group = stem.split("-", 1)[0]
        fallback_name = stem.split("-", 1)[1].replace("-", " ")

    if not group:
        group = fallback_group
    if not name_seen:
        name = fallback_name
    if not summary and fallback_summary:
        summary = fallback_summary
    if not summary:
        summary = f"Run the {stem.replace('-', ' ')} command"

    route = "blackarch " + group
    if name:
        route += " " + name

    usage = route
    if args:
        usage += " " + args

    if requires_sudo != "true":
        requires_sudo = "false"
    if hidden != "true":
        hidden = "false"

    key = file_binary
    COMMAND_KEYS.append(key)
    COMMAND_ROUTE[key] = route
    COMMAND_FALLBACK_ROUTE[key] = fallback_route
    COMMAND_BINARY[key] = file_binary
    COMMAND_GROUP[key] = group
    COMMAND_NAME[key] = name
    COMMAND_SUMMARY[key] = summary
    COMMAND_USAGE[key] = usage
    COMMAND_ARGS[key] = args
    COMMAND_EXAMPLES[key] = examples
    COMMAND_REQUIRES_SUDO[key] = requires_sudo
    COMMAND_HIDDEN[key] = hidden
    COMMAND_HAS_SUMMARY[key] = "true" if has_summary else "false"
    COMMAND_METADATA_ERRORS[key] = metadata_errors

    BINARY_TO_KEY[file_binary] = key
    register_route(route, key)
    register_route(fallback_route, key)

    for alias_route in split_pipe_values(aliases):
        if alias_route == route:
            continue
        register_route(alias_route, key, True)
        COMMAND_ALIASES[key] = append_pipe_value(
            COMMAND_ALIASES.get(key, ""), alias_route
        )


def load_commands() -> None:
    for file in sorted(
        BLACKARCH_BIN_DIR.glob("blackarch-*"), key=lambda p: collate(p.name)
    ):
        if file.is_file() and os.access(file, os.X_OK):
            register_command(file)


def load_command_by_binary(binary: str) -> bool:
    file = BLACKARCH_BIN_DIR / binary
    if not (file.is_file() and os.access(file, os.X_OK)):
        return False
    register_command(file)
    return True


def load_child_commands_by_binary(binary: str) -> None:
    for file in sorted(
        BLACKARCH_BIN_DIR.glob(f"{binary}-*"), key=lambda p: collate(p.name)
    ):
        if file.is_file() and os.access(file, os.X_OK):
            register_command(file)


def group_has_child_commands(group: str) -> bool:
    for file in BLACKARCH_BIN_DIR.glob(f"blackarch-{group}-*"):
        if file.is_file() and os.access(file, os.X_OK):
            return True
    return False


def group_has_binary_commands(group: str) -> bool:
    binary = BLACKARCH_BIN_DIR / f"blackarch-{group}"
    if binary.is_file() and os.access(binary, os.X_OK):
        return True
    return group_has_child_commands(group)


def command_requires_args(key: str) -> bool:
    required = COMMAND_ARGS[key]
    while True:
        stripped = re.sub(r"\[[^][]*\]", "", required, count=1)
        if stripped == required:
            break
        required = stripped
    return required.replace(" ", "") != ""


def load_group_commands(group: str) -> None:
    binary = BLACKARCH_BIN_DIR / f"blackarch-{group}"
    if binary.is_file() and os.access(binary, os.X_OK):
        register_command(binary)

    for file in sorted(
        BLACKARCH_BIN_DIR.glob(f"blackarch-{group}-*"), key=lambda p: collate(p.name)
    ):
        if file.is_file() and os.access(file, os.X_OK):
            register_command(file)


def resolve_direct_route(args: list[str]) -> bool:
    for prefix_count in range(len(args), 0, -1):
        route = "blackarch " + join_words(" ", args[:prefix_count])
        binary = "blackarch-" + join_words("-", args[:prefix_count])
        candidate = BLACKARCH_BIN_DIR / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            DIRECT_RESOLVED_BINARY[0] = binary
            DIRECT_RESOLVED_COUNT[0] = prefix_count
            DIRECT_RESOLVED_ROUTE[0] = route
            return True
    return False


DIRECT_RESOLVED_BINARY: list[str] = [""]
DIRECT_RESOLVED_COUNT: list[int] = [0]
DIRECT_RESOLVED_ROUTE: list[str] = [""]
RESOLVED_KEY: list[str] = [""]
RESOLVED_COUNT: list[int] = [0]
RESOLVED_ROUTE: list[str] = [""]


def sorted_keys(include_all: bool) -> list[str]:
    pairs = set()
    for key in COMMAND_KEYS:
        if not include_all and COMMAND_HIDDEN[key] == "true":
            continue
        pairs.add((COMMAND_ROUTE[key], key))
    return [key for _, key in sorted(pairs, key=lambda pair: collate("\t".join(pair)))]


def fallback_group_for_key(key: str) -> str:
    fallback = COMMAND_FALLBACK_ROUTE[key]
    if fallback.startswith("blackarch "):
        fallback = fallback[len("blackarch ") :]
    return fallback.partition(" ")[0]


def command_route_for_group(key: str, group: str) -> str:
    if fallback_group_for_key(key) == group and COMMAND_GROUP[key] != group:
        return COMMAND_FALLBACK_ROUTE[key]
    return COMMAND_ROUTE[key]


def command_usage_for_group(key: str, group: str) -> str:
    route = command_route_for_group(key, group)
    if COMMAND_ARGS[key]:
        route += " " + COMMAND_ARGS[key]
    return route


def sorted_group_keys(group: str, include_all: bool) -> list[str]:
    pairs = set()
    for key in COMMAND_KEYS:
        if not include_all and COMMAND_HIDDEN[key] == "true":
            continue
        fallback_group = fallback_group_for_key(key)
        if COMMAND_GROUP[key] != group and fallback_group != group:
            continue
        pairs.add((command_route_for_group(key, group), key))
    return [key for _, key in sorted(pairs, key=lambda pair: collate("\t".join(pair)))]


def show_group_list() -> None:
    for name in sorted(GROUP_DESCRIPTIONS):
        print(f"  {name:<14} {GROUP_DESCRIPTIONS[name]}")


def show_main_help() -> None:
    print("""Blackarch command center

Usage:
  blackarch <command> [args...]
  blackarch commands [--all] [--json] [--check]
  blackarch <group> --help
  blackarch <group> <command> --help

Common commands:
  blackarch update              Update Blackarch and system packages
  blackarch theme list          List available themes
  blackarch theme set <name>    Apply a theme
  blackarch font list           List available fonts
  blackarch screenshot          Take a screenshot
  blackarch debug               Print debugging information

Groups:""")
    show_group_list()
    print("""
Discovery:
  blackarch commands            List all commands
  blackarch commands --all      Include commands explicitly marked hidden
  blackarch commands --json     Machine-readable command list
  blackarch commands --check    Validate command metadata and routes""")


def show_commands_help(out: TextIO = sys.stdout) -> None:
    print(
        """Usage:
  blackarch commands [--all] [--json] [--markdown] [--check]

List commands known to the Blackarch command center.

Options:
  --all       Include commands explicitly marked hidden
  --json      Emit machine-readable JSON
  --markdown  Emit a Markdown command table
  --check     Validate command metadata and route collisions""",
        file=out,
    )


def print_command_table(rows: str) -> None:
    """Render a tab-separated table, matching bash `IFS=$'\t' read -r command rest`.

    Empty fields between separators are dropped, so a row joined with two tabs
    renders like one joined with a single tab.
    """
    parsed: list[tuple[str, str]] = []
    for line in rows.split("\n"):
        if not line:
            continue
        fields = [field for field in line.split("\t") if field]
        if not fields:
            continue
        parsed.append((fields[0], "\t".join(fields[1:])))

    if not parsed:
        return

    max_width = max(len(command) for command, _ in parsed)
    for command, rest in parsed:
        print(f"  {command:<{max_width}}  {rest}")


def show_commands(include_all: bool) -> None:
    print("Blackarch commands (all):" if include_all else "Blackarch commands:")

    rows = ""
    for key in sorted_keys(include_all):
        rows += COMMAND_USAGE[key] + "\t" + COMMAND_SUMMARY[key] + "\n"
    print_command_table(rows)

    alias_rows = ""
    for route in ROUTE_IS_ALIAS:
        key = ROUTE_TO_KEY[route]
        if not include_all and COMMAND_HIDDEN[key] == "true":
            continue
        alias_rows += route + "\t" + COMMAND_ROUTE[key] + "\n"

    if alias_rows:
        print("")
        print("Aliases:")
        alias_text = "\n".join(sorted(alias_rows.rstrip("\n").split("\n"), key=collate))
        print_command_table(alias_text)


def markdown_escape(value: str) -> str:
    return value.replace("|", r"\|")


def show_commands_markdown(include_all: bool) -> None:
    print("| Command | Binary | Summary |")
    print("| --- | --- | --- |")
    for key in sorted_keys(include_all):
        print(
            f"| `{markdown_escape(COMMAND_USAGE[key])}` | "
            f"`{markdown_escape(COMMAND_BINARY[key])}` | "
            f"{markdown_escape(COMMAND_SUMMARY[key])} |"
        )


def command_record(key: str) -> dict[str, object]:
    aliases = split_pipe_values(COMMAND_ALIASES.get(key, ""))
    # jq's `unique` sorts its input, so `routes` comes out collated.
    routes = sorted({COMMAND_ROUTE[key], COMMAND_FALLBACK_ROUTE[key], *aliases})
    return {
        "route": COMMAND_ROUTE[key],
        "binary": COMMAND_BINARY[key],
        "group": COMMAND_GROUP[key],
        "name": COMMAND_NAME[key],
        "summary": COMMAND_SUMMARY[key],
        "requires_sudo": COMMAND_REQUIRES_SUDO[key] == "true",
        "hidden": COMMAND_HIDDEN[key] == "true",
        "args": COMMAND_ARGS[key],
        "examples": split_pipe_values(COMMAND_EXAMPLES[key]),
        "aliases": aliases,
        "filename_route": COMMAND_FALLBACK_ROUTE[key],
        "routes": routes,
    }


def show_commands_json(include_all: bool) -> None:
    commands = [command_record(key) for key in sorted_keys(include_all)]
    print(json.dumps({"ok": True, "commands": commands}, indent=2, ensure_ascii=False))


def show_command_json(key: str) -> None:
    print(
        json.dumps(
            {"ok": True, "command": command_record(key)}, indent=2, ensure_ascii=False
        )
    )


def show_commands_check() -> int:
    failures = 0

    for collision in ROUTE_COLLISIONS:
        print(f"Route collision: {collision}", file=sys.stderr)
        failures += 1

    for key in COMMAND_KEYS:
        if COMMAND_HAS_SUMMARY[key] != "true":
            print(f"Missing metadata summary: {COMMAND_BINARY[key]}", file=sys.stderr)
            failures += 1

        errors = COMMAND_METADATA_ERRORS.get(key, "")
        if errors:
            for error in split_pipe_values(errors):
                print(
                    f"Invalid metadata in {COMMAND_BINARY[key]}: {error}",
                    file=sys.stderr,
                )
                failures += 1

        if not os.access(BLACKARCH_BIN_DIR / COMMAND_BINARY[key], os.X_OK):
            print(f"Missing binary: {COMMAND_BINARY[key]}", file=sys.stderr)
            failures += 1

    if failures > 0:
        print(f"Command metadata check failed ({failures} issues)", file=sys.stderr)
        return 1

    print(f"Command metadata check passed ({len(COMMAND_KEYS)} commands)")
    return 0


def parse_commands_args(argv: list[str]) -> int:
    include_all = False
    emit_json = False
    markdown = False
    check = False

    for option in argv[1:]:
        if option == "--all":
            include_all = True
        elif option == "--json":
            emit_json = True
        elif option == "--markdown":
            markdown = True
        elif option == "--check":
            check = True
        elif option in ("--help", "-h"):
            show_commands_help()
            return 0
        else:
            print(f"Unknown option for blackarch commands: {option}", file=sys.stderr)
            show_commands_help(sys.stderr)
            return 2

    if check:
        return show_commands_check()
    if emit_json:
        show_commands_json(include_all)
    elif markdown:
        show_commands_markdown(include_all)
    else:
        show_commands(include_all)
    return 0


def group_exists(group: str) -> bool:
    for key in COMMAND_KEYS:
        if COMMAND_GROUP[key] == group and COMMAND_NAME[key]:
            return True
    return False


def show_group_help(group: str, include_all: bool = False) -> None:
    title = GROUP_DESCRIPTIONS.get(group)
    label = group[:1].upper() + group[1:]
    if title:
        print(f"{label} commands — {title}:")
    else:
        print(f"{label} commands:")

    rows = ""
    for key in sorted_group_keys(group, include_all):
        rows += (
            command_usage_for_group(key, group) + "\t\t" + COMMAND_SUMMARY[key] + "\n"
        )

    if rows:
        print_command_table(rows)
    else:
        print("  No documented commands found. Try: blackarch commands --all")


def show_prefix_help(prefix: str) -> bool:
    prefix_with_space = prefix + " "
    rows = ""
    for key in sorted_keys(False):
        if COMMAND_USAGE[key].startswith(prefix_with_space):
            rows += COMMAND_USAGE[key] + "\t\t" + COMMAND_SUMMARY[key] + "\n"

    if not rows:
        return False

    label = prefix[len("blackarch ") :] if prefix.startswith("blackarch ") else prefix
    print(f"{label} commands:")
    print_command_table(rows)
    return True


def show_related_commands(key: str) -> None:
    group = COMMAND_GROUP[key]
    if COMMAND_NAME[key]:
        return

    rows = ""
    for child_key in sorted_group_keys(group, False):
        if child_key == key:
            continue
        rows += (
            command_usage_for_group(child_key, group)
            + "\t\t"
            + COMMAND_SUMMARY[child_key]
            + "\n"
        )

    if rows:
        print("")
        print("Related commands:")
        print_command_table(rows)


def show_command_help(key: str) -> None:
    print("Usage:")
    print(f"  {COMMAND_USAGE[key]}")
    print("")
    print(COMMAND_SUMMARY[key])

    args = COMMAND_ARGS[key]
    if args:
        print("")
        print("Arguments:")
        print(f"  {args}")

    examples = COMMAND_EXAMPLES[key]
    if examples:
        print("")
        print("Examples:")
        for example in split_pipe_values(examples):
            print(f"  {example}")

    aliases = COMMAND_ALIASES.get(key, "")
    if aliases:
        print("")
        print("Aliases:")
        for alias in split_pipe_values(aliases):
            print(f"  {alias}")

    print("")
    print("Binary:")
    print(f"  {COMMAND_BINARY[key]}")

    if COMMAND_FALLBACK_ROUTE[key] != COMMAND_ROUTE[key]:
        print("")
        print("Filename route:")
        print(f"  {COMMAND_FALLBACK_ROUTE[key]}")

    show_related_commands(key)


def resolve_route(args: list[str]) -> bool:
    for prefix_count in range(len(args), 0, -1):
        route = "blackarch " + join_words(" ", args[:prefix_count])
        key = ROUTE_TO_KEY.get(route)
        if key is not None:
            RESOLVED_KEY[0] = key
            RESOLVED_COUNT[0] = prefix_count
            RESOLVED_ROUTE[0] = route
            return True
    return False


def suggest_command(first: str) -> str:
    """Suggest a route whose name starts with `first`.

    Bash picks whichever match comes first in its associative-array hash
    iteration order, which is an internal detail that does not reproduce. The
    port walks routes alphabetically instead, so the suggestion is stable.
    """
    for candidate in sorted(ROUTE_TO_KEY):
        if candidate.startswith("blackarch "):
            candidate = candidate[len("blackarch ") :]
        if candidate.startswith(first):
            return candidate.partition(" ")[0]
    return ""


def exec_binary(binary_path: str, remaining: list[str]) -> None:
    os.execv(binary_path, [binary_path, *remaining])


def dispatch_fast_or_help(args: list[str]) -> int:
    if resolve_direct_route(args):
        count = DIRECT_RESOLVED_COUNT[0]
        binary = DIRECT_RESOLVED_BINARY[0]
        remaining = args[count:]
        binary_path = BLACKARCH_BIN_DIR / binary

        if remaining_has_help_flag(remaining):
            if not load_command_by_binary(binary):
                print(f"Binary is missing or not executable: {binary}", file=sys.stderr)
                return 127

            if count == 1:
                load_child_commands_by_binary(binary)

            key = BINARY_TO_KEY[binary]
            if remaining_has_json_flag(remaining):
                show_command_json(key)
            else:
                show_command_help(key)
            return 0

        if len(remaining) == 0:
            load_command_by_binary(binary)
            key = BINARY_TO_KEY.get(binary, "")

            if key and command_requires_args(key):
                if count == 1 and group_has_child_commands(args[0]):
                    load_group_commands(args[0])
                    show_group_help(args[0])
                else:
                    show_command_help(key)
                return 0

        exec_binary(str(binary_path), remaining)

    if len(args) == 1 and group_has_binary_commands(args[0]):
        load_group_commands(args[0])
        show_group_help(args[0])
        return 0

    if (
        len(args) >= 2
        and args[1] in ("--help", "-h")
        and group_has_binary_commands(args[0])
    ):
        load_group_commands(args[0])
        show_group_help(args[0])
        return 0

    load_commands()
    return dispatch_or_help(args)


def dispatch_or_help(args: list[str]) -> int:
    if resolve_route(args):
        count = RESOLVED_COUNT[0]
        key = RESOLVED_KEY[0]
        remaining = args[count:]

        if remaining_has_help_flag(remaining):
            if remaining_has_json_flag(remaining):
                show_command_json(key)
            else:
                show_command_help(key)
            return 0

        binary_path = BLACKARCH_BIN_DIR / COMMAND_BINARY[key]
        if not (binary_path.is_file() and os.access(binary_path, os.X_OK)):
            print(
                f"Binary is missing or not executable: {COMMAND_BINARY[key]}",
                file=sys.stderr,
            )
            return 127

        if len(remaining) == 0 and command_requires_args(key):
            if count == 1 and group_exists(args[0]):
                show_group_help(args[0])
            else:
                show_command_help(key)
            return 0

        exec_binary(str(binary_path), remaining)

    if len(args) == 1 and group_exists(args[0]):
        show_group_help(args[0])
        return 0

    if len(args) >= 2 and args[1] in ("--help", "-h") and group_exists(args[0]):
        show_group_help(args[0])
        return 0

    if show_prefix_help("blackarch " + " ".join(args)):
        return 0

    print(f"Unknown Blackarch command: blackarch {' '.join(args)}", file=sys.stderr)
    suggestion = suggest_command(args[0])
    if suggestion:
        print(f"Did you mean: blackarch {suggestion} ?", file=sys.stderr)
    print(
        "Run 'blackarch commands --all' to discover available commands.",
        file=sys.stderr,
    )
    return 127


def dispatch_module(args: list[str]) -> int | None:
    """Run a module-backed command, or None when no route matches.

    Longest prefix wins, mirroring resolve_route(). The module's main() always
    receives the full argv (not the remainder) because the flattened execute
    commands read their own subcommand from argv[0].
    """
    for prefix_count in range(len(args), 0, -1):
        route = "blackarch " + join_words(" ", args[:prefix_count])
        module_name = MODULE_COMMANDS.get(route)
        if module_name is None:
            continue
        try:
            module = importlib.import_module(f"blackarch_modules.{module_name}")
        except ImportError as exc:
            print(f"Cannot load module for {route}: {exc}", file=sys.stderr)
            return 1
        handler = getattr(module, "main", None)
        if handler is None:
            print(f"Module {module_name} has no main()", file=sys.stderr)
            return 1
        if remaining_has_help_flag(args[prefix_count:]):
            printer = getattr(module, "print_help", None)
            if printer is None:
                print(
                    f"Module-backed command. Run it with:\n"
                    f"  blackarch {join_words(' ', args[:prefix_count])} <arguments>"
                )
                return 0
            printer()
            return 0
        result = handler(args)
        return 0 if result is None else int(result)
    return None


def main(argv: list[str]) -> int:
    if not argv:
        show_main_help()
        return 0

    if argv[0] in ("--help", "-h"):
        show_main_help()
        return 0

    if argv[0] == "commands":
        load_commands()
        return parse_commands_args(argv)

    # Module-backed commands (no separate executable wrappers required)
    if argv and argv[0] == "installer":
        sys.path.insert(0, BLACKARCH_BIN_DIR)
        import blackarch_modules.blackarch_core_installer as _inst

        if "--complete" in argv[1:]:
            print(
                "--disk --scheme --esp-size --install --existing --no-encrypt --bootloader --hostname --cache-dir --skip-pacstrap --no-copy-home --copy-home --skip-home-dir --skip-home-ext --skip-vm --efi-part --root-part --luks-part --skip-network --skip-timezone --keep-mounted"
            )
            return 0
        args = _inst.parse_args(argv[1:])
        return _inst.main(args=args)

    if argv[0] in MODULE_COMMANDS:
        handled = dispatch_module(argv)
        if handled is not None:
            return handled

    return dispatch_fast_or_help(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
