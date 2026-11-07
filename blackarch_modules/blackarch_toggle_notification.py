#!/usr/bin/env python3
# blackarch:summary=Toggle notification pausing
"""blackarch-toggle-notification -- pause or resume dunst.

Python port of the bash original, which is `[[ $(dunstctl is-paused) == true ]]
&& dunstctl set-paused false || dunstctl set-paused true`. A failed query is
treated as "not paused", so the toggle still advances when dunstctl cannot
answer.
"""

from __future__ import annotations

import subprocess
import sys

DUNSTCTL = "dunstctl"


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-toggle-notification")
        return 0

    proc = run([DUNSTCTL, "is-paused"])
    paused = proc.returncode == 0 and \
        proc.stdout.decode("utf-8", "replace").strip() == "true"

    return run([DUNSTCTL, "set-paused", "true" if not paused else "false"]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
