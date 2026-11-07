#!/usr/bin/env python3
# blackarch:summary=Enable, disable, or toggle the touchpad
# blackarch:args=[on|off|toggle]
"""blackarch-toggle-touchpad — toggle the touchpad.

Python port of the bash original, which is `exec blackarch-toggle-input-device
touchpad "${1:-toggle}"`. The default is toggle, and an absent argument is the
empty string rather than an error.
"""

import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
TARGET = BIN_DIR / "blackarch-toggle-input-device"
KIND = "touchpad"


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "toggle"

    if not TARGET.is_file():
        print(f"blackarch-toggle-touchpad: missing {TARGET}", file=sys.stderr)
        return 127

    try:
        return subprocess.run([str(TARGET), KIND, action], check=False).returncode
    except OSError as exc:
        print(f"blackarch-toggle-touchpad: could not run {TARGET}: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
