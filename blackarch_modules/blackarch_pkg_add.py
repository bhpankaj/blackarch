#!/usr/bin/env python3
# blackarch:summary=Install packages with pacman, reporting a failed install
# blackarch:args=<package>...
# blackarch:requires-sudo=true
"""blackarch-pkg-add -- install packages that are not already present.

Python port of the bash original. `pacman -Qq` covers installed packages and
`pacman -Qgq` covers group members, so the secondary check catches a package
that pacman reports as installed but did not actually register.
"""

from __future__ import annotations

import os
import subprocess
import sys

DEVNULL = subprocess.DEVNULL


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=DEVNULL, stderr=DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127)


def present(package: str) -> bool:
    """`pacman -Qq <pkg> || pacman -Qgq <pkg>` -- installed directly or via a group."""
    return (run(["pacman", "-Qq", package]).returncode == 0
            or run(["pacman", "-Qgq", package]).returncode == 0)


USAGE = "Usage: blackarch-pkg-add <package>..."


def main(argv: list[str]) -> int:
    # Checked before anything else: `--help` is not a package name, and passing
    # it to pacman -S would be read as an option rather than refused.
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, file=sys.stderr)
        return 0 if argv else 1

    if all(present(package) for package in argv):
        return 0

    command = ["pacman", "-S", "--noconfirm", "--needed", *argv]
    if os.geteuid() != 0:
        command = ["sudo", *command]
    run(command)

    for package in argv:
        if not present(package):
            print(f"\033[31mError: Package '{package}' did not install\033[0m",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
