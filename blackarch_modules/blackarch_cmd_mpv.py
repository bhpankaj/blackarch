#!/usr/bin/env python3
# blackarch:summary=Open a picked audio directory or playlist in mpv
# blackarch:args=<directory|playlist>
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-mpv-directory / -playlist — pick a file, then hand it to mpv.

Python ports of the two bash originals, which are the same program with the
picker target swapped: `mpv-directory` keys on the *directory* holding each
`*.mp3`, `mpv-playlist` keys on the file's own basename. The component is chosen
from `argv[0]` (strip the `blackarch-cmd-mpv-` prefix) or from the first
argument, so `blackarch-cmd-mpv-directory`, `blackarch-cmd-mpv-playlist` and
`blackarch cmd mpv-directory` all reach the same code.

What the originals do, and what this reproduces:

  * `find $HOME -type f -name '*.mp3'` (or `-L ... '*.playlist'`) is run with
    `HOME` as the search root, and the resulting path is split into a key and a
    value by basename/dirname. `mpv-directory` collapses every track in a folder
    onto the folder's own name, so picking `Jazz` plays the whole directory;
    `mpv-playlist` keys on the filename, so picking `mix.playlist` plays that
    file. A later duplicate key wins, exactly as the second assignment to a bash
    associative array does.
  * Keys are piped to `wofi -i -dmenu`, so the picker's stdin is exactly the
    key list and its stdout is exactly the chosen key. `sort | uniq` orders the
    keys the way GNU `sort` does under the runtime locale, which is
    `locale.strxfrm` — not codepoint order.
  * Cancelling the picker exits with the bash `exit -1` status, which the shell
    reports as **255**. `sys.exit(-1)` lands on the same number.
  * `mpv` is started in the foreground with the caller's stdout/stderr, and the
    port's exit status is mpv's — the original's last command is `mpv "$sel"`,
    so nothing after it runs.

Usage:
  blackarch-cmd-mpv-directory
  blackarch-cmd-mpv-playlist
  blackarch cmd mpv-directory
"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from pathlib import Path

locale.setlocale(locale.LC_ALL, "")

# `wofi -i -dmenu` is the picker the original pipes the key list into.
PICKER = ["wofi", "-i", "-dmenu"]
PLAYER = "mpv"

# Component -> (find predicate, key extractor). The predicates are the two
# `find` name arguments verbatim from the originals.
COMPONENTS = {
    "directory": ("-name", "*.mp3", "directory"),
    "playlist": ("-name", "*.playlist", "file"),
}

USAGE = "Usage: blackarch-cmd-mpv-<directory|playlist>"


def component_from_argv0(argv0: str) -> str:
    """`blackarch-cmd-mpv-directory` -> `directory`."""
    name = Path(argv0).name
    for prefix in ("blackarch-cmd-mpv-", "blackarch-cmd-mpv."):
        if name.startswith(prefix):
            return name[len(prefix):]
    return ""


def select_component(argv: list[str]) -> str:
    implied = component_from_argv0(sys.argv[0] if sys.argv else "")
    if implied:
        return implied
    if argv and argv[0] in COMPONENTS:
        return argv[0]
    return ""


def find_files(pattern: str, follow: bool) -> list[str]:
    """`find [-L] $HOME -type f -name <pattern>`, one path per line.

    `-L` follows symlinks (the playlist original passes it, the directory one
    does not). Paths are kept as `find` prints them; nothing is split on
    whitespace, which is the bug the original's unquoted `$(find ...)` has and
    the reason this is a `subprocess` call rather than a glob.
    """
    command = ["find"]
    if follow:
        command.append("-L")
    command += [str(Path.home()), "-type", "f", "-name", pattern]

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


def build_map(paths: list[str], key_kind: str) -> dict[str, str]:
    """Collapse `paths` into the bash associative array `path_map`.

    `directory`: key = basename(dirname(path)), value = dirname(path).
    `file`:      key = basename(path),        value = path.

    `dirname` of a bare filename is `.` in bash but `""` in `os.path`, so the
    original's `k=[.]` for a loose file in `$HOME` needs the same substitution
    here or the key would differ.
    """
    mapping: dict[str, str] = {}
    for path in paths:
        if not path:
            continue
        if key_kind == "directory":
            parent = os.path.dirname(path)
            key = os.path.basename(parent) if parent else "."
            mapping[key] = parent if parent else "."
        else:
            mapping[os.path.basename(path)] = path
    return mapping


def pick(keys: list[str]) -> str | None:
    """Run the picker over `keys`; return the choice, or None if cancelled.

    The keys are sorted and de-duplicated the way `printf '%s\\n' | sort | uniq`
    does them: locale collation, then uniq (which only collapses *adjacent*
    duplicates — harmless after a sort). An empty key sorts first and is kept,
    matching `printf` emitting a bare newline for an empty array slot.
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

    # `chosen=$(wofi ...)` strips trailing newlines; an empty line is a real
    # (if useless) choice and is returned as "".
    return completed.stdout.decode("utf-8", "replace").rstrip("\n")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    component = select_component(argv)
    if component not in COMPONENTS:
        print(USAGE, file=sys.stderr)
        return 1

    _, pattern, key_kind = COMPONENTS[component]
    follow = component == "playlist"

    mapping = build_map(find_files(pattern, follow), key_kind)
    if not mapping:
        return 0

    chosen = pick(list(mapping))
    if chosen is None:
        # `exit -1` -> 255.
        return 255

    selection = mapping.get(chosen, "")

    # The original's last command is `mpv "$final_selection"`, so its exit
    # status is ours. `--playlist=<path>` for the playlist component.
    if component == "playlist":
        command = [PLAYER, f"--playlist={selection}"]
    else:
        command = [PLAYER, selection]

    try:
        completed = subprocess.run(command, check=False)
    except OSError as error:
        print(f"{PLAYER}: {error}", file=sys.stderr)
        return 127
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
