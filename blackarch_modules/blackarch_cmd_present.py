#!/usr/bin/env python3
# blackarch:summary=Report whether each named command is on PATH
# blackarch:args=<command...>
# blackarch:hidden=true
"""blackarch-cmd-present — exit 0 only when every named command is on PATH.

Python port of the bash original (a one-line `command -v` loop). It exists so a
caller can write `if blackarch-cmd-present kitty; then ...` without forking
`command -v` itself, and so a missing optional tool reads as a branch rather
than a crash. Extra arguments are each checked; any one missing fails the call.

**`command -v` is not "is this executable".** It reports any name that resolves
to something on PATH which is not a directory, and it does not test the execute
bit: a regular file with mode 000, a fifo, a unix socket and a symlink to a
character device all count as present, while a directory — even a searchable one
— and a dangling symlink do not. Verified against bash directly, and reproduced
here as `not candidate.is_dir()` on a path that must exist. The practical
consequence: this answers "could the shell *name* this", not "would running it
work".

A name containing a slash is a path, not a PATH lookup: `command -v /bin/sh`
succeeds and `command -v bin/sh` fails. The port therefore tests the literal path
when a slash is present and searches PATH only for a bare name.

Usage: blackarch-cmd-present <command...>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def on_path(name: str) -> bool:
    """`command -v <name>`: found, or False when it would fail.

    A bare name is searched in each PATH entry; the first entry whose candidate
    is not a directory wins. A name containing a slash is tested as a path.
    """
    if not name:
        return False

    if "/" in name:
        return Path(name).exists() and not Path(name).is_dir()

    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / name
        if candidate.is_dir():
            continue
        if candidate.exists():
            return True
    return False


def main(argv: list[str]) -> int:
    if not argv:
        return 0
    return 0 if all(on_path(name) for name in argv) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
