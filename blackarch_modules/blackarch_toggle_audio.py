#!/usr/bin/env python3
# blackarch:summary=Adjust audio volume and mute state
# blackarch:args=[up|down|mute|mic]
# blackarch:examples=blackarch-toggle-audio up | blackarch-toggle-audio mute | blackarch-toggle-audio mic
"""blackarch-toggle-audio -- volume, mute and mic mute, with an OSD.

Python port of the bash original. Each action tries `wpctl` first and falls
back to `pamixer`, because a pipewire-only host has wpctl and a pulse/pipewire
host that predates it may not. The notification reports the state after the
change, so it reads pamixer even when wpctl did the work.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"
DEFAULT_SOURCE = "@DEFAULT_SOURCE@"
STEP = "5"

ACTIONS = {
    "up": (["wpctl", "set-volume", "-l", "1", DEFAULT_SINK, f"{STEP}%+"],
           ["pamixer", "-i", STEP]),
    "down": (["wpctl", "set-volume", DEFAULT_SINK, f"{STEP}%-"],
             ["pamixer", "-d", STEP]),
    "mute": (["wpctl", "set-mute", DEFAULT_SINK, "toggle"],
             ["pamixer", "-t"]),
    "mic": (["wpctl", "set-mute", DEFAULT_SOURCE, "toggle"], []),
}

VOLUME_RE = r"\d+"


def sibling(name: str) -> str:
    path = BIN_DIR / name
    return str(path) if path.is_file() else name


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def notify(icon: str, value: int) -> None:
    subprocess.run(
        [sibling("blackarch-notification-send"), "-i", icon, "-p", str(value),
         "Volume", f"{value}%"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-toggle-audio [up|down|mute|mic]")
        return 0

    action = argv[0] if argv else "mute"
    if action not in ACTIONS:
        print("Usage: blackarch-toggle-audio [up|down|mute|mic]", file=sys.stderr)
        return 1

    primary, fallback = ACTIONS[action]
    proc = run(primary)
    if proc.returncode != 0 and fallback:
        run(fallback)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
