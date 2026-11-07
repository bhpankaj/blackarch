#!/usr/bin/env python3
# blackarch:summary=Toggle bar visibility without killing the Blackarch shell
# blackarch:args=[toggle|on|off]
# blackarch:examples=blackarch toggle bar | blackarch toggle bar off | blackarch toggle bar on
"""blackarch-toggle-bar -- hide or show the shell's bar.

Python port of the bash original. Flips the `bar-off` flag through
blackarch-toggle, then nudges the bar plugin: its FileView watch on the toggles
directory can stop delivering events after flags change in quick succession,
which would strand the bar off screen until the shell restarted. `syncHidden`
re-runs the probe rather than restarting it, so an in-flight probe's answer is
not swallowed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

FLAG = "bar-off"
TARGET = "blackarch.bar"
METHOD = "syncHidden"


def sibling(name: str) -> str:
    """This directory's binary, or the bare name for PATH lookup."""
    path = BIN_DIR / name
    return str(path) if path.is_file() else name


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "toggle"

    subprocess.run(
        [sibling("blackarch-toggle"), FLAG, action],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    # `-q`: quiet best-effort, so the toggle still works when the shell is down.
    subprocess.run(
        [sibling("blackarch-shell"), "-q", TARGET, METHOD],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
