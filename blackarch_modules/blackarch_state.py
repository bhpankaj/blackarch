#!/usr/bin/env python3
# blackarch:summary=Set or clear a named state marker
# blackarch:args=<set|clear> <state-name-or-pattern>
# blackarch:examples=blackarch state set reboot-required | blackarch state clear re*-required
"""blackarch-state -- create or remove a marker under ~/.local/state/blackarch.

Python port of the bash original: `set` touches the named file, `clear` deletes
every matching file directly inside the state directory (`find -maxdepth 1 -type
f -name <pattern> -delete`), so a glob is accepted as the pattern.
"""

from __future__ import annotations

import sys
from pathlib import Path

STATE_DIR = Path.home() / ".local" / "state" / "blackarch"


USAGE_LINE = "Usage: blackarch-state <set|clear> <state-name-or-pattern>"


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE_LINE, file=sys.stderr)
        return 0 if argv else 1

    command, name = argv[0], (argv[1] if len(argv) > 1 else "")
    if not name:
        print(USAGE_LINE, file=sys.stderr)
        return 1

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if command == "set":
        (STATE_DIR / name).touch(exist_ok=True)
    elif command == "clear":
        for path in STATE_DIR.glob(name):
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
    else:
        print(USAGE_LINE, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
