#!/usr/bin/env python3
# blackarch:summary=Wake displays and restore brightness after idle
# blackarch:group=system
# blackarch:name=wake
# blackarch:examples=blackarch system wake
"""blackarch-system-wake — wake displays and restore brightness after idle.

Mirrors the bash original: enable DPMS, restore the keyboard backlight, then
re-apply the clamshell state (whose failure is ignored).
"""

import subprocess
import sys


def main(argv):
    subprocess.run(["blackarch-brightness-display", "on"], check=False)
    subprocess.run(["blackarch-brightness-keyboard", "restore"], check=False)
    subprocess.run(
        ["blackarch-hyprland-monitor-clamshell"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
