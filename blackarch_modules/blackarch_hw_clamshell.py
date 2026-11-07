#!/usr/bin/env python3
# blackarch:summary=Returns true when clamshell mode is active
# blackarch:hidden=true
"""blackarch-hw-clamshell — true (exit 0) when clamshell mode is active.

Python port of the bash original: clamshell is the lid being closed while one
or more external monitors are connected, which is the conjunction of
blackarch-hw-laptop-closed and blackarch-hw-external-monitors.
"""

import subprocess
import sys


def sibling_succeeds(name: str) -> bool:
    """A missing sibling is a false answer, never a traceback — the `&&` chain
    in the original treats any non-zero exit as "false", whatever the cause."""
    try:
        return subprocess.run(
            [name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
    except OSError:
        return False


def main(argv: list[str]) -> int:
    if not sibling_succeeds("blackarch-hw-laptop-closed"):
        return 1
    return 0 if sibling_succeeds("blackarch-hw-external-monitors") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
