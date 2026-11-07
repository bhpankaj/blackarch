#!/usr/bin/env python3
# blackarch:summary=Power off, closing every window first
# blackarch:args=
# blackarch:group=cmd
# blackarch:examples=blackarch cmd shutdown
"""blackarch-cmd-shutdown — power off the machine.

Python port of the bash original. **This shuts the machine down when run.**

The original's four steps, in order:

  1. `smartthings devices:commands 4e715c22-7aa0-4bd6-9425-b694b26e325d switch:off`
     — a SmartThings outlet, switched off before the host powers down. It runs
     even when the `smartthings` CLI is missing, which costs a `command not
     found` on stderr and nothing else: the original does not check its status.
  2. `blackarch-state clear re*-required` — delete the reboot-required markers.
  3. `blackarch-hyprland-window-close-all` — close every window, so applications
     shut down cleanly.
  4. `sleep 1` — the settle window those apps need.
  5. `systemctl poweroff --no-wall` — the actual poweroff. `--no-wall` suppresses
     the broadcast message.

The port resolves the sibling commands from its own directory (`readlink -f`,
because these are symlinked into `/usr/sbin`, which precedes `bin/` on PATH) and
falls back to the bare name when the sibling is absent, exactly as the original's
bare command name does.

Usage: blackarch-cmd-shutdown
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent

SMARTTHINGS_DEVICE = "4e715c22-7aa0-4bd6-9425-b694b26e325d"
SETTLE_SECONDS = 1

USAGE = "Usage: blackarch-cmd-shutdown"


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

    # 1. The outlet, best-effort and unchecked in the original.
    run(["smartthings", "devices:commands", SMARTTHINGS_DEVICE, "switch:off"])

    # 2. Drop the reboot-required markers.
    run([sibling("blackarch-state"), "clear", "re*-required"])

    # 3. Close every window.
    run([sibling("blackarch-hyprland"), "window-close-all"])

    # 4. Let the applications shut down cleanly.
    time.sleep(SETTLE_SECONDS)

    # 5. Power off. `--no-wall` matches the original.
    return run(["systemctl", "poweroff", "--no-wall"]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
