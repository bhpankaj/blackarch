#!/usr/bin/env python3
# blackarch:summary=Match against the computer's DMI product name or product family (case-insensitive).
# blackarch:args=<pattern>
"""blackarch-hw-match — true (exit 0) when the DMI product name or product
family matches the given pattern, case-insensitively.

Python port of the bash original, which is two `grep -qi` invocations over
/sys/class/dmi/id/product_name and product_family. `grep -q` matches anywhere
in the file (not line-anchored), so the substring test here is a plain
`in` on the lowercased contents; an unreadable file is a non-match, never an
error.
"""

import sys
from pathlib import Path

DMI_IDS = (Path("/sys/class/dmi/id/product_name"), Path("/sys/class/dmi/id/product_family"))


def main(argv: list[str]) -> int:
    pattern = argv[0] if argv else ""
    if not pattern:
        return 1
    needle = pattern.lower()

    for path in DMI_IDS:
        try:
            contents = path.read_text(errors="replace").lower()
        except OSError:
            continue
        if needle in contents:
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
