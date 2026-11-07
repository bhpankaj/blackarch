#!/usr/bin/env python3
# blackarch:summary=Toggle screensaver availability
"""blackarch-toggle-screensaver -- enable or disable the screensaver.

Python port of the bash original. `screensaver-off` present means the screensaver
is disabled; the notification reports which way it landed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

FLAG = "screensaver-off"
GLYPH = chr(0xF1104)


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
        print("Usage: blackarch-toggle-screensaver")
        return 0

    run([sibling("blackarch-toggle"), FLAG])

    disabled = run([sibling("blackarch-toggle-enabled"), FLAG]).returncode == 0
    message = "Screensaver disabled" if disabled else "Screensaver enabled"

    run([sibling("blackarch-notification-send"), "-g", GLYPH, message])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
