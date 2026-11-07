#!/usr/bin/env python3
# blackarch:summary=Stream voxtype --follow status as bar-friendly JSON
"""blackarch-voxtype-status — stream `voxtype status --follow` as bar JSON.

Standalone Python replacement for the bash `blackarch-voxtype-status`. When
voxtype is not installed it prints the idle payload the Dictation indicator
expects; otherwise it replaces itself with `setpriv --pdeathsig TERM voxtype
status --follow --extended --format json`, keeping the status follower as the
bar's direct child. Quickshell clean up their direct child when they restart;
a shell pipeline or coprocess would leave `voxtype status --follow` orphaned
under the user systemd instance.
"""

from __future__ import annotations

import os
import sys

IDLE = '{"alt": "", "class": "idle", "tooltip": ""}'


def command_exists(name: str) -> bool:
    """bash `command -v`: a PATH entry of that name, executable or not."""
    path = os.environ.get("PATH")
    if not path:
        return False
    for directory in path.split(os.pathsep):
        if directory == "":
            directory = "."
        if os.path.exists(os.path.join(directory, name)):
            return True
    return False


def main() -> int:
    if not command_exists("voxtype"):
        sys.stdout.write(IDLE + "\n")
        return 0

    try:
        os.execvp(
            "setpriv",
            ["setpriv", "--pdeathsig", "TERM", "voxtype", "status",
             "--follow", "--extended", "--format", "json"],
        )
    except OSError:
        sys.stderr.write(f"{sys.argv[0]}: setpriv: command not found\n")
        return 127
    return 127


if __name__ == "__main__":
    sys.exit(main())
