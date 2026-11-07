#!/usr/bin/env python3
# blackarch:summary=Print the working directory of the active terminal window
# blackarch:args=
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-terminal-cwd — the cwd of the focused terminal, or `$HOME`.

Python port of the bash original, which is the shell's own answer to "where does
a new terminal open". It resolves the directory in two steps and falls back to
`$HOME` when neither yields an existing directory.

  * **Step 1 — kitty remote control.** When `$XDG_RUNTIME_DIR/blackarch-kitty-<pid>`
    is a socket, `kitten @ --to unix:<socket> ls --match state:focused` returns
    the focused window's `cwd`. This is the only path that works for a terminal
    the compositor reports by pid alone.
  * **Step 2 — the child process.** Otherwise, `pgrep -P <terminal_pid> | tail -n1`
    gives the shell's pid, and `/proc/<shell>/cwd` is read. The original also
    checks that the child's `exe` is listed in `/etc/shells` and clears the cwd
    when it is not — a guard against a terminal whose child is not a shell.
  * **The fallback is `echo "$HOME"`**, because the final test is `[[ -d $cwd ]]`.

`hyprctl activewindow` is parsed as *text* here, exactly as the original does
with `awk '/pid:/ {print $2}'`, so the field order the compositor emits is part
of the contract.

Usage: blackarch-cmd-terminal-cwd
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

KITTY_SOCKET_PREFIX = "blackarch-kitty-"
SHELLS_FILE = Path("/etc/shells")

USAGE = "Usage: blackarch-cmd-terminal-cwd"


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def active_terminal_pid() -> str:
    """`hyprctl activewindow | awk '/pid:/ {print $2}'` -> the pid, or "".

    The text format is `key: value` lines; the first `pid:` line wins. A
    non-numeric result is discarded by the caller.
    """
    completed = run(["hyprctl", "activewindow"])
    if completed.returncode != 0:
        return ""
    for line in completed.stdout.decode("utf-8", "replace").split("\n"):
        if "pid:" not in line:
            continue
        fields = line.split()
        for index, field in enumerate(fields):
            if field == "pid:" and index + 1 < len(fields):
                return fields[index + 1]
    return ""


def kitty_cwd(socket_path: Path) -> str:
    """`kitten @ --to unix:<socket> ls --match state:focused`, first cwd found.

    The jq filter is `.[].tabs[].windows[].cwd // empty`, so the first window
    that reports a cwd wins and `null` entries are skipped.
    """
    completed = run(
        [
            "kitten",
            "@",
            "--to",
            f"unix:{socket_path}",
            "ls",
            "--match",
            "state:focused",
        ]
    )
    if completed.returncode != 0:
        return ""
    try:
        data = json.loads(completed.stdout.decode("utf-8", "replace"))
    except ValueError:
        return ""

    for tab in data:
        if not isinstance(tab, dict):
            continue
        for window in tab.get("windows", []) or []:
            cwd = window.get("cwd") if isinstance(window, dict) else None
            if cwd:
                return str(cwd)
    return ""


def child_pid(parent: str) -> str:
    """`pgrep -P <parent> | tail -n1` -> the last child's pid, or "".

    `tail -n1` takes the *last* line, so with several children the newest one
    wins. `pgrep` returns nothing (exit 1) when the parent has no children.
    """
    completed = run(["pgrep", "-P", parent])
    if completed.returncode != 0:
        return ""
    lines = completed.stdout.decode("utf-8", "replace").split("\n")
    return lines[-1] if lines else ""


def is_login_shell(executable: str) -> bool:
    """`grep -Fqsx "$shell" /etc/shells` — a whole-line, fixed-string match."""
    if not SHELLS_FILE.is_file():
        return False
    try:
        lines = SHELLS_FILE.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return False
    return executable in lines


def resolve(terminal_pid: str) -> str:
    """The two-step resolution, returning "" when neither step produces a path."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    socket_path = Path(runtime) / f"{KITTY_SOCKET_PREFIX}{terminal_pid}"

    if socket_path.is_socket():
        cwd = kitty_cwd(socket_path)
        if cwd:
            return cwd
        # A socket that answers nothing falls through to the /proc step, which
        # is what the original's `if [[ -S $kitty_socket ]]` block does: an
        # empty `cwd` leaves the variable empty and the -d test rejects it.

    shell_pid = child_pid(terminal_pid)
    if not shell_pid:
        return ""

    try:
        cwd = os.path.realpath(f"/proc/{shell_pid}/cwd")
    except OSError:
        return ""

    try:
        executable = os.path.realpath(f"/proc/{shell_pid}/exe")
    except OSError:
        return ""

    # `grep -Fqsx "$shell" /etc/shells || cwd=""` — the guard, not a fallback.
    if not is_login_shell(executable):
        return ""

    return cwd


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    cwd = resolve(active_terminal_pid())

    # `[[ -d $cwd ]] && echo "$cwd" || echo "$HOME"`
    if cwd and Path(cwd).is_dir():
        print(cwd)
    else:
        print(str(Path.home()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
