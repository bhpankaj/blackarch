#!/usr/bin/env python3
# blackarch:summary=Report whether any named command is absent from PATH
# blackarch:args=<command...>
# blackarch:hidden=true
"""blackarch-cmd-missing — exit 0 as soon as one named command is NOT on PATH.

Python port of the bash original (a `command -v` loop with the inverted test). It
is the complement of `blackarch-cmd-present`, and both are used as a branch by
shell callers rather than as a report: `blackarch-cmd-missing ttfx && exit 1`.

Exit codes are exactly the original's: 0 when at least one name is missing, and 1
when the loop ran to completion without finding one. With no arguments the loop
body never executes, so control falls through to the trailing `exit 1` — the
command answers "nothing was missing" for an empty list, not "everything is
present".

`command -v`'s notion of "on PATH" is the same as `blackarch-cmd-present`'s and
is *not* an executability test: see that port's docstring. A name containing a
slash is a path and is tested directly.

Usage: blackarch-cmd-missing <command...>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def on_path(name: str) -> bool:
    """`command -v <name>` for a bare name or a slash-containing path."""
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
    for name in argv:
        if not on_path(name):
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
