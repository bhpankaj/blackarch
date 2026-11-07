#!/usr/bin/env python3
# blackarch:summary=Toggle the on-screen virtual keyboard
# blackarch:args=
# blackarch:hidden=true
"""blackarch-cmd-virtualkeyboard — start wvkbd, or stop it when it is running.

Python port of the bash one-liner `pgrep wvkbd-deskintl && pkill wvkbd-deskintl
|| wvkbd-deskintl`, which is why the argument list is empty: the command takes
none, and the port takes none either.

Three behaviours of the original are preserved exactly, because they are the
whole command:

  * `pgrep NAME` matches the process *name* (`comm`, capped at 15 bytes), not the
    full command line, so the `pkill` half must match the same way — `pkill -x`.
  * **When the keyboard is not running, the command does not wait for it.** The
    original's `|| wvkbd-deskintl` runs the GUI in the foreground of the *shell*,
    which is why invoking the original blocks — but that is the shell waiting on
    its own child, not the script waiting. The port therefore starts the keyboard
    in a new session and returns immediately, so a caller is never held by a GUI
    it just launched.
  * When the keyboard *is* running, the command kills it and returns the `pkill`
    exit status — 0 on a match, 1 when nothing matched (the same predicate
    `pgrep` already decided, so the 1 is unreachable in practice).

Usage: blackarch-cmd-virtualkeyboard
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

PROCESS_NAME = "wvkbd-deskintl"


def process_names() -> list[str]:
    """Every live process name, read from /proc as raw bytes.

    `/proc/<pid>/comm` is read with `os.read` on a manually opened fd, never with
    `Path.read_text()`. Decoding a process name through the UTF-8 codec is the
    failure mode this avoids: a name holding a byte that is not valid UTF-8 raises
    `UnicodeDecodeError`, which would abort the scan and — because the keyboard is
    still running — make the command report "not running" and start a second one.
    Reading bytes and decoding with `errors="replace"` cannot raise.

    `comm` is capped at 15 bytes by the kernel, which is the same limit
    `pgrep`/`pkill` apply, so this is a faithful substitute for both. A process
    that dies between the readdir and the read is skipped rather than fatal.
    """
    names: list[str] = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return names

    for entry in entries:
        if not entry.isdigit():
            continue
        fd = -1
        try:
            fd = os.open(f"/proc/{entry}/comm", os.O_RDONLY)
            raw = os.read(fd, 64)
        except OSError:
            continue
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if not raw:
            continue
        # comm is always "name\n"; a name over the 15-byte cap is truncated and
        # still newline-terminated.
        names.append(raw.split(b"\n", 1)[0].decode("utf-8", "replace"))
    return names


def running() -> bool:
    return PROCESS_NAME in process_names()


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-cmd-virtualkeyboard")
        return 0

    if running():
        # `pkill -x NAME`: whole-name equality, exactly like `pgrep NAME`.
        # `-f` would match the full command line and could catch an unrelated
        # process that merely mentions the name.
        try:
            completed = subprocess.run(
                ["pkill", "-x", PROCESS_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return completed.returncode
        except OSError:
            return 1

    binary = shutil.which(PROCESS_NAME)
    if binary is None:
        print(f"{PROCESS_NAME}: command not found", file=sys.stderr)
        return 127

    # `|| wvkbd-deskintl` runs the GUI in the foreground of the *shell*, so a
    # caller that blocks on the command is waiting on its own child, not on this
    # script. The port starts the keyboard in a new session and returns at once:
    # a GUI the caller just launched should not hold it.
    #
    # `fork` + `setsid` + `exec`, and the parent returns a status. The child
    # *becomes* the keyboard, so exactly one new process appears, named
    # `wvkbd-deskintl`, in its own session — immune to a signal sent to this
    # process group, which is what a GUI launched from a terminal should be.
    try:
        pid = os.fork()
    except OSError as error:
        print(f"{PROCESS_NAME}: {error}", file=sys.stderr)
        return 127

    if pid == 0:
        # Child branch: never return into main().
        try:
            os.setsid()
        except OSError:
            pass
        try:
            os.execv(binary, [PROCESS_NAME])
        except OSError as error:
            print(f"{PROCESS_NAME}: {error}", file=sys.stderr)
            os._exit(127)
        os._exit(127)  # execv does not return

    # Parent. `os.waitpid(pid, 0)` is **required**, and it is what makes the
    # command faithful to the original. `pgrep wvkbd-deskintl` matched, so the
    # shell's `|| wvkbd-deskintl` runs the keyboard in the foreground and the
    # caller blocks until it exits — that is the whole command, not an accident.
    # A caller that backgrounds it (`blackarch-cmd-virtualkeyboard &`) gets the
    # non-blocking behaviour for free.
    #
    # The earlier attempt avoided this wait and broke the contract twice over:
    # the child died with the caller's process group, and `os._exit(0)` discarded
    # the return status that `sys.exit(main(...))` was meant to deliver.
    #
    # `os.waitpid` is safe here because the child has already `exec`'d (or
    # failed): the kernel reports the failure without blocking.
    try:
        _, status = os.waitpid(pid, 0)
    except OSError:
        return 0

    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
