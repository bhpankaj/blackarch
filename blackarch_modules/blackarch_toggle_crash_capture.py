#!/usr/bin/env python3
# blackarch:summary=Toggle crash capture notifications
"""blackarch-toggle-crash-capture -- enable or disable the crash watcher.

Python port of the bash original. The flag is `crash-capture-off` (present =
disabled), and the unit watches the same file with ConditionPathExists, so
stopping and starting the unit settles the current session while the flag
decides the next login.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

# nf-md-robot_dead, escaped in the original so the file reads without a Nerd Font.
CRASH_GLYPH = chr(0xF16A1)
FLAG = "crash-capture-off"
UNIT = "blackarch-crash-watch.service"


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
        print("Usage: blackarch-toggle-crash-capture")
        return 0

    run([sibling("blackarch-toggle"), FLAG])

    disabled = run([sibling("blackarch-toggle-enabled"), FLAG]).returncode == 0
    if disabled:
        run(["systemctl", "--user", "stop", UNIT])
        message = "Crash capture disabled"
    else:
        run(["systemctl", "--user", "start", UNIT])
        message = "Crash capture enabled"

    run([sibling("blackarch-notification-send"), "-g", CRASH_GLYPH, message])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
