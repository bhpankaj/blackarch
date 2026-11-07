#!/usr/bin/env python3
# blackarch:summary=Check if a toggle is enabled (flag file exists)
# blackarch:args=<flag-name>
"""blackarch-toggle-enabled -- exit 0 when the named flag file exists.

Python port of the bash original, which is a single `[[ -f ... ]]`. The exit
status is the entire interface: callers branch on it, so nothing is printed
either way and a missing flag is exit 1, never an exception.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOGGLES_DIR = Path.home() / ".local" / "state" / "blackarch" / "toggles"


def main(argv: list[str]) -> int:
    if not argv:
        return 1
    return 0 if (TOGGLES_DIR / argv[0]).is_file() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
