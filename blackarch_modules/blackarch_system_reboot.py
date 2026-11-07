#!/usr/bin/env python3
# blackarch:summary=Reboot after closing application windows
# blackarch:examples=blackarch reboot | blackarch system reboot
# blackarch:aliases=blackarch reboot
"""blackarch-system-reboot -- schedule a reboot, then close every window.

Python port of the bash original. The reboot is scheduled in the user manager
two seconds out so closing the terminal's systemd scope cannot terminate it
before it runs.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent


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
        print("Usage: blackarch-system-reboot")
        return 0

    run(["systemd-run", "--user", "--collect", "--quiet", "--on-active=2s",
         "--timer-property=AccuracySec=100ms", "systemctl", "reboot", "--no-wall"])

    run([sibling("blackarch-osd"), "-i", "reboot", "-m", "Rebooting", "-d", "5000"])
    run([sibling("blackarch-state"), "clear", "re*-required"])

    # `blackarch-hyprland-window-close-all` is the ported blackarch-hyprland's
    # window-close-all subcommand; the standalone launcher is not in this tree.
    run([sibling("blackarch-hyprland"), "window-close-all"])

    # Allow apps like Chrome to shut down cleanly before the reboot lands.
    time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
