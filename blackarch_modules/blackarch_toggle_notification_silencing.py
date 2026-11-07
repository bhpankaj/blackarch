#!/usr/bin/env python3
# blackarch:summary=Toggle notification do-not-disturb mode
"""blackarch-toggle-notification-silencing -- flip do-not-disturb.

Python port of the bash original: ask the shell's notifications target to toggle
DND, then nudge the bar's Indicators widget to refresh. The first call is not
quiet because its answer is the state; the refresh is, since the bar is not
required for the mode to change.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

TARGET = "notifications"
METHOD = "toggleDnd"
INDICATORS_TARGET = "blackarch.indicators"
INDICATORS_METHOD = "refresh"


def sibling(name: str) -> str:
    path = BIN_DIR / name
    return str(path) if path.is_file() else name


def run(argv: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-toggle-notification-silencing")
        return 0

    run([sibling("blackarch-shell"), TARGET, METHOD], capture=True)
    run([sibling("blackarch-shell"), "-q", INDICATORS_TARGET, INDICATORS_METHOD])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
