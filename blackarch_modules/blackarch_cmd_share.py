#!/usr/bin/env python3
# blackarch:summary=Send the clipboard or files through LocalSend
# blackarch:args=<clipboard|file|folder> [file...]
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-share — hand the clipboard or files to LocalSend.

Python port of the bash original: it either captures the clipboard into a temp
file or resolves a file/folder selection, then starts `localsend --headless send`
under a detached `systemd-run --user` unit so the GUI outlives the caller.

Preserved from the original:

  * **`clipboard` mode always uses a temp file.** `wl-paste` is captured into
    `mktemp --suffix=.txt` and that path is sent; the file is deliberately *not*
    removed, because LocalSend's GUI reads it after this process exits.
  * **`file`/`folder` mode with no arguments picks through `fzf`.** `folder`
    runs `find $HOME -type d | fzf` (one selection), `file` runs
    `find $HOME -type f | fzf --multi` (one or more). An empty selection exits 0.
  * **The multi-file test is `echo "$FILES" | grep -q $'\\n'`.** A single
    selection is a one-line string with no newline *in the variable*, but the
    original's `echo` appends one, so this test is true for **every** non-empty
    selection — including a single file. The port reproduces that: a non-empty
    selection always takes the `readarray` branch. It is harmless rather than
    wrong, because `readarray -t <<<"$FILES"` yields a one-element array for a
    single line and the argv is identical.
  * **`$# == 0` is an error** for every mode: the usage line goes to stdout and
    the exit status is 1.

Usage: blackarch-cmd-share [clipboard|file|folder] [file...]
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

CLIPBOARD_READ = "wl-paste"
PICKER = "fzf"
RECEIVER = "localsend"

USAGE = "Usage: blackarch-cmd-share [clipboard|file|folder]"


def run(argv: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def capture_clipboard() -> str:
    """`mktemp --suffix=.txt` + `wl-paste >$TEMP_FILE`, returning the path."""
    try:
        handle, path = tempfile.mkstemp(suffix=".txt")
    except OSError:
        return ""
    with os.fdopen(handle, "wb") as stream:
        captured = run([CLIPBOARD_READ])
        stream.write(captured.stdout)
    return path


def pick(selector_args: list[str]) -> list[str]:
    """`find $HOME -type <d|f> 2>/dev/null | fzf <args>` -> the selection.

    `$(...)` strips trailing newlines, so a single line arrives without its
    terminator and `readarray -t <<<"$FILES"` still yields exactly one element.
    A cancelled picker yields no output, which is the empty list.
    """
    find_type = "d" if "folder" in selector_args else "f"
    find_completed = run(["find", str(Path.home()), "-type", find_type])
    if find_completed.returncode != 0:
        return []

    picker_completed = run(
        [PICKER, *selector_args], stdin=find_completed.stdout
    )
    if picker_completed.returncode != 0:
        return []

    selection = picker_completed.stdout.decode("utf-8", "replace")
    # `readarray -t <<<"$FILES"`: the here-string appends a newline, and `-t`
    # strips it, so an empty result is one empty element — filtered out here
    # because an empty path is not a file to send.
    return [line for line in selection.split("\n") if line]


def send(files: list[str]) -> int:
    """`systemd-run --user --quiet --collect localsend --headless send <files...>`."""
    return run(
        [
            "systemd-run",
            "--user",
            "--quiet",
            "--collect",
            RECEIVER,
            "--headless",
            "send",
            *files,
        ]
    ).returncode


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    if not argv:
        # `echo "Usage: ..."` goes to stdout; the exit status is 1.
        print(USAGE)
        return 1

    mode = argv[0]
    rest = argv[1:]

    if mode == "clipboard":
        files = [capture_clipboard()]
    elif rest:
        # `if (($# > 0)); then FILES="$*"` — every remaining word is a path.
        files = rest
    elif mode == "folder":
        files = pick([])
    else:
        files = pick(["--multi"])

    # `[ -z "$FILES" ] && exit 0` guards only the picker branch.
    if not files:
        return 0

    # The multi-file branch. The original decides with
    # `echo "$FILES" | grep -q $'\n'`, which is true for every non-empty
    # selection (echo terminates the line), so a single file lands here too.
    return send(files)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
