#!/usr/bin/env python3
# blackarch:summary=Copy a file to the clipboard and paste it
# blackarch:args=[--copy-only] <mime-type> <path>
# blackarch:examples=blackarch clipboard paste file image/png /tmp/screenshot.png
# blackarch:hidden=true
"""blackarch-clipboard-paste-file — put a file's bytes on the clipboard with a mime type.

Python port of the bash original. Used by the blackarch.clipboard plugin for
image entries: wl-copy takes the payload straight from the file, then Shift+Insert
pastes it into the focused window unless --copy-only was given.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PASTE_DELAY = 0.15

USAGE = "Usage: blackarch-clipboard-paste-file [--copy-only] <mime-type> <path>"


def main(argv: list[str]) -> int:
    copy_only = False
    if argv and argv[0] == "--copy-only":
        copy_only = True
        argv = argv[1:]

    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 1

    mime, path = argv[0], argv[1]
    source = Path(path)
    if not source.is_file() or not os.access(source, os.R_OK):
        return 1

    wl_copy = shutil.which("wl-copy")
    if not wl_copy:
        print("wl-copy not found on PATH", file=sys.stderr)
        return 1

    with open(source, "rb") as handle:
        subprocess.run([wl_copy, "--type", mime], stdin=handle, check=False)

    if copy_only:
        return 0

    time.sleep(PASTE_DELAY)

    wtype = shutil.which("wtype")
    if not wtype:
        print(
            "wtype not found on PATH: file copied but not pasted "
            "(install wtype or ydotool to paste into the focused window)",
            file=sys.stderr,
        )
        return 0

    subprocess.run([wtype, "-M", "shift", "-k", "Insert", "-m", "shift"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
