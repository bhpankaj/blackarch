#!/usr/bin/env python3
# blackarch:summary=Returns true when an external monitor is physically connected.
"""blackarch-hw-external-monitors — true (exit 0) when an external monitor is
physically connected.

Python port of the bash original. Walks every `card*-*/status` under the DRM
sysfs root, skipping the internal connectors (eDP/LVDS/DSI), and reports the
first one whose status reads "connected".
"""

import os
import re
import sys
from pathlib import Path

DRM_PATH = Path(os.environ.get("BLACKARCH_DRM_PATH", "/sys/class/drm"))
INTERNAL_CONNECTOR = re.compile(r"-(?:eDP|LVDS|DSI)-[^/]+/status$")
STATUS_FILE = re.compile(r"^card\d+-.*/status$")


def external_connected() -> bool:
    try:
        entries = sorted(DRM_PATH.iterdir(), key=lambda p: p.name)
    except OSError:
        return False

    for entry in entries:
        if not STATUS_FILE.match(entry.name):
            continue
        if INTERNAL_CONNECTOR.search(str(entry)):
            continue
        try:
            if entry.read_text(errors="replace").strip() == "connected":
                return True
        except OSError:
            continue
    return False


def main(argv: list[str]) -> int:
    return 0 if external_connected() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
