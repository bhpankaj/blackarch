#!/usr/bin/env python3
# blackarch:summary=Open a picked PDF or EPUB in zathura
# blackarch:args=
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-zathura-document — pick a PDF or EPUB, then open it in zathura.

Python port of the bash original: index every `*.pdf` and `*.epub` under `$HOME`
by basename into a bash associative array, pipe the keys to `wofi -i -dmenu`, and
hand the chosen file to `zathura`.

The one detail of the original that matters: its `find` predicate is
`-type f -name '*.pdf' -o -name '*.epub'` with **no parentheses**, so `-type f`
binds only to the pdf arm. The epub arm matches by name alone — a directory
called `x.epub` is offered, and so is a symlink named `x.epub`. `DOCUMENT_ARMS`
splits that expression the way the shell parses it (`-o` is looser than the
implicit `-a`), so the reachable set is byte-identical rather than tidier.

Cancelling the picker is the original's `exit -1`, which the shell reports as
**255**.

Usage: blackarch-cmd-zathura-document
"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from pathlib import Path

locale.setlocale(locale.LC_ALL, "")

PICKER = ["wofi", "-i", "-dmenu"]
VIEWER = "zathura"

# `find $HOME -type f -name '*.pdf' -o -name '*.epub'`, split where the shell's
# own precedence puts the boundary: `-o` is looser than the implicit `-a`, so the
# pdf arm owns `-type f` and the epub arm owns only its name test.
DOCUMENT_ARMS = [
    ["-type", "f", "-name", "*.pdf"],
    ["-name", "*.epub"],
]

USAGE = "Usage: blackarch-cmd-zathura-document"


def find_arm(arm: list[str]) -> list[str]:
    """`find $HOME <arm>`, one path per line, or [] when find fails."""
    command = ["find", str(Path.home()), *arm]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    return completed.stdout.decode("utf-8", "replace").split("\n")


def build_map() -> dict[str, str]:
    """Index every document by basename; a later duplicate wins."""
    mapping: dict[str, str] = {}
    for arm in DOCUMENT_ARMS:
        for path in find_arm(arm):
            if not path:
                continue
            mapping[os.path.basename(path)] = path
    return mapping


def pick(keys: list[str]) -> str | None:
    """`printf '%s\\n' "${!path_map[@]}" | sort | uniq | wofi -i -dmenu`.

    Returns the chosen key, "" when the picker echoed an empty line, or None when
    it was cancelled or is missing.
    """
    ordered = sorted(set(keys), key=locale.strxfrm)
    payload = "".join(f"{key}\n" for key in ordered)

    try:
        completed = subprocess.run(
            PICKER,
            input=payload.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as error:
        print(f"{PICKER[0]}: {error}", file=sys.stderr)
        return None

    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "replace").rstrip("\n")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    mapping = build_map()
    if not mapping:
        return 0

    chosen = pick(list(mapping))
    if chosen is None:
        return 255

    selection = mapping.get(chosen, "")

    try:
        completed = subprocess.run([VIEWER, selection], check=False)
    except OSError as error:
        print(f"{VIEWER}: {error}", file=sys.stderr)
        return 127
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
