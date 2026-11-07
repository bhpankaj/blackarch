#!/usr/bin/env python3
# blackarch:summary=Toggle Blackarch features between enabled and disabled
# blackarch:args=<flag-name> [toggle|on|off]
# blackarch:examples=blackarch toggle bar-off | blackarch toggle bar-off on | blackarch toggle bar-off off
"""blackarch-toggle -- create or remove a Blackarch flag file.

Python port of the bash original. A flag's presence under
~/.local/state/blackarch/toggles means "enabled": the shell's bar and the
systemd units read the same files, so this one command drives every consumer.
`toggle` (the default) inverts, `on` creates, `off` removes.

Usage: blackarch-toggle <flag-name> [toggle|on|off]
"""

from __future__ import annotations

import sys
from pathlib import Path

USAGE = "Usage: blackarch-toggle <flag-name> [toggle|on|off]"

# Hardcoded to ~/.local/state rather than derived from XDG_STATE_HOME: every
# consumer (the bar's FileView, the systemd ConditionPathExists units) watches
# this exact path, and a divergence would strand a flag in one place only.
TOGGLES_DIR = Path.home() / ".local" / "state" / "blackarch" / "toggles"


def flag_path(name: str) -> Path:
    return TOGGLES_DIR / name


def enable(name: str) -> None:
    """`mkdir -p` + `touch`: create the flag, making the directory if needed."""
    path = flag_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def disable(name: str) -> None:
    """`rm -f`: removing a flag that is already gone is not an error."""
    try:
        flag_path(name).unlink()
    except OSError:
        pass


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, file=sys.stderr)
        return 0 if argv else 1

    name = argv[0]
    action = argv[1] if len(argv) > 1 else "toggle"

    if action in ("toggle", ""):
        if flag_path(name).is_file():
            disable(name)
        else:
            enable(name)
    elif action == "on":
        enable(name)
    elif action == "off":
        disable(name)
    else:
        print(USAGE, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
