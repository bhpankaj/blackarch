#!/usr/bin/env python3
# blackarch:summary=Open the Blackarch background switcher
# blackarch:group=theme
# blackarch:name=bg-switcher
# blackarch:aliases=blackarch background
"""blackarch-theme-bg-switcher — open the background picker for the current theme.

Python port of the bash original: reads the current theme name and the resolved
current background, then hands both image directories to `blackarch-menu-images`
via exec.
"""

import os
import subprocess
import sys


def main() -> int:
    home = os.environ.get("HOME", "")
    state = os.path.join(home, ".local/state/blackarch/current")

    try:
        with open(os.path.join(state, "theme.name"), encoding="utf-8", errors="replace") as fh:
            theme_name = fh.read().rstrip("\n")
    except OSError:
        theme_name = ""

    background_link = os.path.join(state, "background")
    # readlink -f: resolves to an absolute path and still prints it when only
    # the final component is missing (or is a dangling symlink), but prints
    # nothing when a parent directory does not exist. os.path.realpath matches
    # every case except the last, which needs the explicit guard.
    parent = os.path.dirname(background_link)
    current_background = os.path.realpath(background_link) if os.path.isdir(parent) else ""

    args = [
        "blackarch-menu-images",
        "--selected",
        current_background,
        os.path.join(state, "theme", "backgrounds"),
        os.path.join(home, ".config/blackarch/backgrounds", theme_name),
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except OSError:
        print(f"exec: {args[0]}: not found", file=sys.stderr)
        return 127
    selection = result.stdout.strip()
    if selection:
        subprocess.run(["blackarch-theme-bg-set", selection], check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
