#!/usr/bin/env python3
# blackarch:summary=Reboot, closing every window first
# blackarch:args=
# blackarch:group=cmd
# blackarch:examples=blackarch cmd reboot
"""blackarch-cmd-reboot — reboot the machine.

Python port of the bash original. **This reboots the machine when run.**

The original's three steps, in order:

  1. `blackarch-state clear re*-required` — delete the reboot-required markers.
  2. `blackarch-hyprland-window-close-all` — close every window, so applications
     shut down cleanly.
  3. `sleep 1` — the settle window those apps need.
  4. `systemctl reboot --no-wall` — the actual reboot. `--no-wall` suppresses the
     broadcast message.

Note the asymmetry with `blackarch-cmd-shutdown`: the shutdown variant switches a
SmartThings outlet off first, and this one does not.

The port resolves the sibling commands from its own directory (`readlink -f`,
because these are symlinked into `/usr/sbin`, which precedes `bin/` on PATH) and
falls back to the bare name when the sibling is absent, exactly as the original's
bare command name does. `blackarch-hyprland-window-close-all` is reached through
the ported `blackarch-hyprland` family's `window-close-all` subcommand.

Usage: blackarch-cmd-reboot
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

SETTLE_SECONDS = 1

USAGE = "Usage: blackarch-cmd-reboot"


def sibling(name: str) -> str:
    """`$here/<name>` when it exists, else the bare name — so PATH resolves it."""
    path = BIN_DIR / name
    return str(path) if path.is_file() else name


def run(argv: list[str]) -> subprocess.CompletedProcess:
    """Run a command, discarding `OSError` the way an unchecked shell call does."""
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    # 1. Drop the reboot-required markers.
    run([sibling("blackarch-state"), "clear", "re*-required"])

    # 2. Close every window.
    run([sibling("blackarch-hyprland"), "window-close-all"])

    # 3. Let the applications shut down cleanly.
    time.sleep(SETTLE_SECONDS)

    # 4. Reboot. `--no-wall` matches the original.
    return run(["systemctl", "reboot", "--no-wall"]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
