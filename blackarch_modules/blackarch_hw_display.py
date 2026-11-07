#!/usr/bin/env python3
# blackarch:summary=Show the runtime-discovered backlight device for this machine
# blackarch:examples=blackarch-hw-display
"""blackarch-hw-display — print the backlight device name for this machine.

Python port of the bash original. The Mac Touch Bar backlight is skipped first;
gmux is preferred, then amdgpu, intel, then acpi, else the first remaining
entry. The device name is a bare name under /sys/class/backlight, not a path.
"""

import glob
import os
import sys
from pathlib import Path

BACKLIGHT_PATH = Path(os.environ.get("BLACKARCH_BACKLIGHT_PATH", "/sys/class/backlight"))
SKIP_NAMES = ("appletb_backlight",)
PREFERENCE_PATTERNS = ("gmux_backlight", "amdgpu_bl*", "intel_backlight", "acpi_video*")


def hw_display() -> str:
    try:
        names = [name for name in os.listdir(BACKLIGHT_PATH) if name not in SKIP_NAMES]
    except OSError:
        return ""

    device = names[0] if names else ""
    for pattern in PREFERENCE_PATTERNS:
        for candidate in glob.glob(str(BACKLIGHT_PATH / pattern)):
            if os.path.exists(candidate):
                return os.path.basename(candidate)
    return device


def main(argv: list[str]) -> int:
    print(hw_display())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
