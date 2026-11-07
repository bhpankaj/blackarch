#!/usr/bin/env python3
# blackarch:summary=Toggle the EasyEffects audio effects process
# blackarch:args=[preset]
"""blackarch-toggle-easyeffects -- start or stop EasyEffects.

Python port of the bash original, which is `pgrep easyeffects && pkill
easyeffects || easyeffects -p`. The `||` binds to the whole `&&` list, so a
running process is killed and a stopped one is started with the last preset
(`-p`); the port keeps that structure rather than an if/else, because the two
branches are exactly "kill" and "start".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EASYEFFECTS = "easyeffects"


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-toggle-easyeffects [preset]")
        return 0

    if run(["pgrep", "-x", EASYEFFECTS]).returncode == 0:
        return run(["pkill", "-x", EASYEFFECTS]).returncode

    subprocess.Popen([EASYEFFECTS, "-p"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
