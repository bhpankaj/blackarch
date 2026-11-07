#!/usr/bin/env python3
# blackarch:summary=Toggle nightlight screen temperature
# blackarch:args=[--status]
# blackarch:examples=blackarch toggle nightlight
"""blackarch-toggle-nightlight -- switch the screen colour temperature.

Python port of the bash original. hyprsunset applies its own default
temperature at the end of its boot, which overrides anything set before then,
so the set-and-verify loop resends the target up to ten times until
`hyprctl hyprsunset temperature` reports it back.

`--status` prints JSON for the bar's Nightlight indicator: enabled means "below
the identity temperature", not merely that hyprsunset is running.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

ON_TEMP = 4000
OFF_TEMP = 6500
IDENTITY_TEMP = 6000

ATTEMPTS = 10
SETTLE_SECONDS = 0.2

TEMPERATURE_RE = re.compile(r"\d+")

USAGE = "Usage: blackarch-toggle-nightlight [--status]"


def sibling(name: str) -> str:
    path = BIN_DIR / name
    return str(path) if path.is_file() else name


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def current_temp() -> str:
    """The first number in `hyprctl hyprsunset temperature`, or "".

    The original is `grep -oE '[0-9]+' | head -1`: an empty answer is a normal
    outcome (hyprsunset not up yet), not an error.
    """
    proc = run(["hyprctl", "hyprsunset", "temperature"])
    if proc.returncode != 0:
        return ""
    match = TEMPERATURE_RE.search(proc.stdout.decode("utf-8", "replace"))
    return match.group(0) if match else ""


def status_json() -> str:
    temp = current_temp()
    enabled = bool(temp) and int(temp) < IDENTITY_TEMP
    return json.dumps({"enabled": enabled,
                       "temperature": int(temp) if temp else None},
                      separators=(",", ":"), ensure_ascii=False)


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    if argv and argv[0] == "--status":
        print(status_json())
        return 0

    # `pgrep -x hyprsunset`: start it only when it is not already running.
    if run(["pgrep", "-x", "hyprsunset"]).returncode != 0:
        subprocess.Popen(["setsid", "uwsm-app", "--", "hyprsunset"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    temp = current_temp()
    target = ON_TEMP if (not temp or temp == str(OFF_TEMP)) else OFF_TEMP

    for _ in range(ATTEMPTS):
        run(["hyprctl", "hyprsunset", "temperature", str(target)])
        time.sleep(SETTLE_SECONDS)
        if current_temp() == str(target):
            break

    # `-q`: the shell is not required for the temperature to be applied.
    run([sibling("blackarch-shell"), "-q", "nightlight", "refresh"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
