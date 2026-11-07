#!/usr/bin/env python3
# blackarch:summary=Print the detected Hyprland touchpad or trackpad device name
# blackarch:hidden=true
"""blackarch-hw-touchpad — print the Hyprland touchpad device name.

Python port of the bash original, which is `hyprctl devices -j | jq -r
'[.mice[] | .name | select(test("touchpad|trackpad"; "i"))] | first // empty'`.
jq's `test` is a case-insensitive regex search, not an anchored match, so
`re.search` here is the equivalent rather than `re.match`.
"""

import json
import re
import shutil
import subprocess
import sys

HYPRCTL = "hyprctl"
TOUCHPAD_RE = re.compile(r"touchpad|trackpad", re.IGNORECASE)


def device_name() -> str:
    """The first mouse whose name matches touchpad|trackpad, or ""."""
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

    mice = devices.get("mice")
    if not isinstance(mice, list):
        return ""

    for entry in mice:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str) and TOUCHPAD_RE.search(name):
            return name

    return ""


def main(argv: list[str]) -> int:
    print(device_name())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
