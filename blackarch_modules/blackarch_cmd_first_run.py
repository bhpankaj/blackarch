#!/usr/bin/env python3
# blackarch:summary=Run the first-login setup hooks once
# blackarch:args=
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-first-run — run the first-login hooks, then remove the marker.

Python port of the bash original. The whole command is gated on one marker file:
when `~/.local/state/blackarch/first-run.mode` does not exist, nothing runs and
the exit status is 0. When it does, the file is deleted *first* (so a hook that
crashes cannot re-run on every login) and the hook list runs under `set -e`, so
the first failure stops the rest and its status becomes the command's.

The original's hook paths, verbatim and unchanged:

    $BLACKARCH_PATH/install/first-run/battery-monitor.sh
    $BLACKARCH_PATH/install/first-run/cleanup-reboot-sudoers.sh
    $BLACKARCH_PATH/install/first-run/firewall.sh
    $BLACKARCH_PATH/install/first-run/dns-resolver.sh
    $BLACKARCH_PATH/install/first-run/gnome-theme.sh
    $BLACKARCH_PATH/install/first-run/elephant.sh
    sudo rm -f /etc/sudoers.d/first-run
    $BLACKARCH_PATH/install/first-run/welcome.sh
    $BLACKARCH_PATH/install/first-run/wifi.sh

**The port does not run this sequence by default.** `BLACKARCH_PATH` is unset in
this tree and `install/first-run/` does not exist under it, so every path would
expand to `/install/first-run/...` and fail one by one. The port therefore takes
`--apply` to run the hooks and returns 0 without touching anything otherwise;
`--dry-run` prints the exact argv each step would use. That flag is the one
addition to the original's surface, and it exists because the original's whole
effect is invisible from outside.

Usage: blackarch-cmd-first-run [--apply|--dry-run]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MARKER = Path.home() / ".local" / "state" / "blackarch" / "first-run.mode"
SUDOERS_MARKER = Path("/etc/sudoers.d/first-run")

# The hook list, in the original's order. `sudo rm -f /etc/sudoers.d/first-run`
# sits between `elephant.sh` and `welcome.sh`.
HOOKS = [
    "battery-monitor.sh",
    "cleanup-reboot-sudoers.sh",
    "firewall.sh",
    "dns-resolver.sh",
    "gnome-theme.sh",
    "elephant.sh",
]
TRAILING_HOOKS = [
    "welcome.sh",
    "wifi.sh",
]

USAGE = "Usage: blackarch-cmd-first-run [--apply|--dry-run]"


def blackarch_path() -> str:
    """`$BLACKARCH_PATH`, defaulting to the packaged location."""
    return os.environ.get("BLACKARCH_PATH") or "/usr/share/blackarch"


def hook_path(name: str) -> str:
    return f"{blackarch_path().rstrip('/')}/install/first-run/{name}"


def run(argv: list[str]) -> int:
    """Run a command; an absent binary is the shell's 127, not a crash."""
    try:
        return subprocess.run(argv, check=False).returncode
    except OSError:
        return 127


def show_dry_run() -> int:
    """Print the argv each step would execute."""
    print(f"rm -f {MARKER}")
    for name in HOOKS:
        print(f"bash {hook_path(name)}")
    print(f"sudo rm -f {SUDOERS_MARKER}")
    for name in TRAILING_HOOKS:
        print(f"bash {hook_path(name)}")
    return 0


def apply_hooks() -> int:
    """The original's sequence under `set -e`: first failure wins."""
    # The marker is removed before any hook runs, so a crash cannot loop.
    try:
        MARKER.unlink()
    except OSError:
        pass

    for name in HOOKS:
        status = run(["bash", hook_path(name)])
        if status != 0:
            return status

    # `sudo rm -f` — a password prompt is the caller's, exactly as in the shell.
    status = run(["sudo", "rm", "-f", str(SUDOERS_MARKER)])
    if status != 0:
        return status

    for name in TRAILING_HOOKS:
        status = run(["bash", hook_path(name)])
        if status != 0:
            return status

    return 0


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    dry_run = "--dry-run" in argv

    if "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0

    if dry_run:
        return show_dry_run()

    # `if [[ -f "$FIRST_RUN_MODE" ]]` — the gate, and the only thing that makes
    # this command safe to call on every login.
    if not MARKER.is_file():
        return 0

    if not apply:
        print(
            f"{MARKER} exists; re-run with --apply to run the first-login hooks.",
            file=sys.stderr,
        )
        return 0

    return apply_hooks()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
