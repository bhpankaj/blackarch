#!/usr/bin/env python3
# blackarch:summary=Returns true when the laptop lid is closed
# blackarch:hidden=true
"""blackarch-hw-laptop-closed — true (exit 0) when the laptop lid is closed.

Mirrors the bash original: every readable /proc/acpi/button/lid/*/state whose
contents contain the substring "closed" (lowercase, case-sensitive, anywhere in
the line) makes the script exit 0; otherwise it exits 1. No stdout is written —
the consumer wraps this in `... && echo closed || echo open`.
"""

import glob
import os
import sys


def main(argv):
    for state in glob.glob("/proc/acpi/button/lid/*/state"):
        if not os.access(state, os.R_OK):
            continue
        try:
            with open(state, "r", errors="replace") as handle:
                contents = handle.read()
        except OSError:
            continue
        if "closed" in contents:
            return 0

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
