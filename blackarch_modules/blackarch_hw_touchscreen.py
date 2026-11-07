#!/usr/bin/env python3
# blackarch:summary=Print the detected Hyprland touchscreen or tablet device name
# blackarch:hidden=true
"""blackarch-hw-touchscreen — print the Hyprland touchscreen device name.

Python port of the bash original, which is `hyprctl devices -j | jq -r
'[.touch[]?.name, .tablets[]?.name] | first // empty'`. The `// empty` in jq
emits nothing at all for an empty array, so the port prints an empty line and
still exits 0 — a caller that needs a usable name checks for the empty string,
never the exit status.
"""

import json
import shutil
import subprocess
import sys

# `hyprctl` rather than an absolute path: it is on PATH in every session this
# tool runs in, and a hardcoded /usr/bin/hyprctl would break a tree moved
# elsewhere. A missing binary is an empty answer, not a traceback.
HYPRCTL = "hyprctl"


def device_name() -> str:
    """The first touch or tablet device name, or "" when none is found.

    The bash pipeline takes touch names before tablet names and keeps the
    first of either, so the order of the two groups is preserved here.
    """
    if shutil.which(HYPRCTL) is None:
        return ""

    try:
        proc = subprocess.run(
            [HYPRCTL, "devices", "-j"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return ""

    if proc.returncode != 0:
        return ""

    try:
        devices = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        return ""

    if not isinstance(devices, dict):
        return ""

    for group in ("touch", "tablets"):
        entries = devices.get(group)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if isinstance(name, str) and name != "":
                return name

    return ""


def main(argv: list[str]) -> int:
    print(device_name())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
