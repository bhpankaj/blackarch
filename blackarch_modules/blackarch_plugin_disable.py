#!/usr/bin/env python3
# blackarch:summary=Disable a shell plugin
# blackarch:group=plugin
# blackarch:args=<id>
"""blackarch-plugin-disable — switch a plugin off.

Python port of the bash original. A non-bar plugin that is already off is left
alone (the shell's `setEnabled` is idempotent), and an unknown id is reported
rather than silently succeeding, so a typo does not read as "done".
"""

from __future__ import annotations

import subprocess
import sys


def fail(message: str) -> int:
    print(f"blackarch-plugin-disable: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch plugin disable <id>")
        return 0

    plugin_id = argv[0] if argv else ""
    if not plugin_id:
        return fail("plugin id is required")

    proc = subprocess.run(
        ["blackarch-shell", "shell", "setPluginEnabled", plugin_id, "false"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    result = (proc.stdout or "").strip()

    if result != "ok":
        return fail(f"plugin '{plugin_id}' is not known; run: blackarch-shell shell rescanPlugins")

    print(f"Disabled {plugin_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
