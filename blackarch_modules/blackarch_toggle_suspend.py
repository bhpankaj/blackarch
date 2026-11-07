#!/usr/bin/env python3
# blackarch:summary=Toggle suspend availability in the system menu
"""blackarch-toggle-suspend -- add or remove Suspend from the system menu.

Python port of the bash original. `suspend-off` present means the menu hides
Suspend; the notification reports which way it landed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

FLAG = "suspend-off"
GLYPH = chr(0xF04B2)


def sibling(name: str) -> str:
    path = BIN_DIR / name
    return str(path) if path.is_file() else name


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-toggle-suspend")
        return 0

    run([sibling("blackarch-toggle"), FLAG])

    removed = run([sibling("blackarch-toggle-enabled"), FLAG]).returncode == 0
    message = "Suspend removed from system menu" if removed \
        else "Suspend now available in system menu"

    run([sibling("blackarch-notification-send"), "-g", GLYPH, message])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
