#!/usr/bin/env python3
# blackarch:summary=Toggle idle behavior so the system either idles normally or stays awake
# blackarch:group=toggle
# blackarch:args=[toggle|stay-awake|allow-idle|status]
# blackarch:examples=blackarch toggle idle | blackarch toggle idle stay-awake | blackarch-toggle-idle --status
"""blackarch-toggle-idle -- stay awake, or let the system idle normally.

Python port of the bash original. The state is the presence of
~/.local/state/blackarch/indicators/stay-awake; the bar's Indicators widget
shows the same flag.

Two different outputs, both meaningful: `status` prints the JSON the bar's
widget consumes (enabled/class/tooltip), while the other actions print the idle
state itself -- "disabled" when staying awake, "enabled" when idle is allowed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".local" / "state" / "blackarch" / "indicators"
STATE_FILE = STATE_DIR / "stay-awake"

USAGE = "Usage: blackarch-toggle-idle [toggle|stay-awake|allow-idle|status]"


def stay_awake_enabled() -> bool:
    return STATE_FILE.is_file()


def print_status() -> None:
    enabled = stay_awake_enabled()
    if enabled:
        payload = {"enabled": True, "class": "enabled",
                   "tooltip": "Allow Idle Lock & Screensaver"}
    else:
        payload = {"enabled": False, "class": "disabled", "tooltip": "Stay Awake"}
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def print_idle_state() -> None:
    print("disabled" if stay_awake_enabled() else "enabled")


def apply_state(action: str) -> None:
    if action == "stay-awake":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.touch(exist_ok=True)
    elif action == "allow-idle":
        try:
            STATE_FILE.unlink()
        except OSError:
            pass


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "toggle"

    if action == "toggle":
        apply_state("allow-idle" if stay_awake_enabled() else "stay-awake")
        print_idle_state()
    elif action in ("stay-awake", "awake", "on"):
        apply_state("stay-awake")
        print_idle_state()
    elif action in ("allow-idle", "idle", "off"):
        apply_state("allow-idle")
        print_idle_state()
    elif action in ("status", "--status"):
        print_status()
    else:
        print(USAGE, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
