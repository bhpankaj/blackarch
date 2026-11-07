#!/usr/bin/env python3
# blackarch:summary=Enable a shell plugin
# blackarch:group=plugin
# blackarch:args=<id> [placement]
# blackarch:examples=blackarch plugin enable acme.weather --section right
"""blackarch-plugin-enable — enable a plugin, optionally placing it in the bar.

Python port of the bash original. A bar (`kinds` containing "bar") is not a widget
that takes a place in a bar — it *replaces* the bar in use, so passing a
placement for one is refused rather than silently ignored. Placement is forwarded
to the shell as JSON, and the result is reported from what the shell actually did.

A bar's `defaultSection` is honoured by the shell only when no explicit placement
is given, so `blackarch plugin enable <bar>` switches the bar in use.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

SECTIONS = ("left", "center", "right")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def fail(message: str) -> int:
    print(f"blackarch-plugin-enable: {message}", file=sys.stderr)
    return 1


def is_bar(plugin_id: str) -> bool:
    """True when the plugin declares the `bar` kind, i.e. it is a bar option."""
    proc = subprocess.run(
        ["blackarch-plugin-catalog"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if proc.returncode != 0:
        return False
    try:
        entries = json.loads(proc.stdout)
    except ValueError:
        return False
    for entry in entries:
        if entry.get("id") == plugin_id:
            return "bar" in (entry.get("kinds") or [])
    return False


def parse_args(argv: list[str]) -> dict:
    """Split argv into id and placement. A leading non-option is the section."""
    section = ""
    index = ""
    before = ""
    after = ""

    if not argv:
        return {"error": "plugin id is required"}

    plugin_id = argv[0]
    rest = argv[1:]

    if rest and not rest[0].startswith("--"):
        section = rest[0]
        rest = rest[1:]

    while rest:
        option = rest.pop(0)
        if option == "--section":
            if section:
                return {"error": "specify a section positionally or with --section, not both"}
            if not rest:
                return {"error": "--section requires a section"}
            section = rest.pop(0)
        elif option == "--index":
            if not rest:
                return {"error": "--index requires an index"}
            index = rest.pop(0)
        elif option == "--before":
            if not rest:
                return {"error": "--before requires a widget id"}
            before = rest.pop(0)
        elif option == "--after":
            if not rest:
                return {"error": "--after requires a widget id"}
            after = rest.pop(0)
        else:
            return {"error": f"unknown placement option: {option}"}

    if section and section not in SECTIONS:
        return {"error": "section must be left, center, or right"}
    if index and not index.isdigit():
        return {"error": "index must be a non-negative integer"}
    if before and after:
        return {"error": "use only one of --before or --after"}

    placement = {}
    if section:
        placement["section"] = section
    if index:
        placement["index"] = int(index)
    if before:
        placement["before"] = before
    if after:
        placement["after"] = after

    return {
        "id": plugin_id,
        "placement": placement,
    }


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch plugin enable <id> [placement]")
        return 0

    parsed = parse_args(argv)
    if "error" in parsed:
        return fail(parsed["error"])

    plugin_id = parsed["id"]
    placement = parsed["placement"]

    if placement and is_bar(plugin_id):
        return fail(
            f"'{plugin_id}' is a bar; it replaces the bar in use rather than taking a place in one"
        )

    proc = subprocess.run(
        ["blackarch-shell", "shell", "enablePlugin", plugin_id, json.dumps(placement)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    result = (proc.stdout or "").strip()

    if result == "unknown":
        return fail(f"plugin '{plugin_id}' is not known; run: blackarch-shell shell rescanPlugins")
    if result != "ok":
        return fail(result or f"plugin '{plugin_id}' could not be enabled")

    if placement:
        print(f"Enabled and moved {plugin_id}")
    elif is_bar(plugin_id):
        print(f"Now using {plugin_id} as the bar")
    else:
        print(f"Enabled {plugin_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
