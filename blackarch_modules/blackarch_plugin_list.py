#!/usr/bin/env python3
# blackarch:summary=List discovered shell plugins
# blackarch:group=plugin
# blackarch:args=[--json]
"""blackarch-plugin-list — list the plugins the running shell has loaded.

Python port of the bash original. It calls `blackarch-shell shell listPlugins`
and either passes the JSON through (`--json`) or renders a table. The table's
columns mirror the shell's own view: state, whether the plugin is first-party,
and the kinds it declares — so what this prints is what the bar can actually use.
"""

from __future__ import annotations

import json
import subprocess
import sys

COLUMNS = ("ID", "STATE", "SOURCE", "KINDS", "NAME")
WIDTHS = (32, 9, 11, 18, 0)


def parse_args(argv: list[str]) -> tuple[bool, str | None]:
    as_json = False
    for arg in argv:
        if arg == "--json":
            as_json = True
        elif arg in ("-h", "--help"):
            return as_json, "Usage: blackarch plugin list [--json]"
        else:
            return as_json, f"blackarch-plugin-list: unknown option: {arg}"
    return as_json, None


def load_plugins() -> list:
    proc = subprocess.run(
        ["blackarch-shell", "shell", "listPlugins"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if proc.returncode != 0:
        return []
    try:
        parsed = json.loads(proc.stdout)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def render_table(plugins: list) -> None:
    header = [c.ljust(WIDTHS[i]) for i, c in enumerate(COLUMNS[:-1])] + [COLUMNS[-1]]
    print(" ".join(header).rstrip())

    for plugin in plugins:
        kinds = plugin.get("kinds") or []
        row = [
            str(plugin.get("id", "")),
            "enabled" if plugin.get("enabled") else "disabled",
            "first-party" if plugin.get("firstParty") else "third-party",
            ",".join(str(kind) for kind in kinds),
            str(plugin.get("name", "")),
        ]
        cells = [row[i].ljust(WIDTHS[i]) for i in range(len(WIDTHS) - 1)]
        print(" ".join(cells + [row[-1]]).rstrip())


def main(argv: list[str]) -> int:
    as_json, error = parse_args(argv)
    if error:
        if error.startswith("Usage:"):
            print(error)
            return 0
        sys.stderr.write(error + "\n")
        return 1

    plugins = load_plugins()

    if as_json:
        json.dump(plugins, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    render_table(plugins)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
