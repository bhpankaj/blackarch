#!/usr/bin/env python3
# blackarch:summary=Run the animated screensaver until any key or click exits
# blackarch:args=
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-screensaver — full-screen animation that exits on any input.

Python port of the bash original, which runs inside the terminal that
`blackarch-launch-screensaver` opens with `--class=org.blackarch.screensaver`.

This is a **TTY program**, and the original's whole behaviour depends on it:
`printf` writes mouse-tracking escape sequences to the terminal, `read -rsn1`
polls stdin for a keystroke with a timeout, and `tty`/`pgrep -t` identify the
terminal so the animation loop can be watched from inside the process. Under a
pipe (`sys.stdin.isatty()` false) the escape sequences still go out but the
`read` equivalent returns immediately with no byte, which is exactly what bash's
`read -t 0.1` does at EOF — the port reproduces that rather than refusing.

Preserved from the original:

  * **Exit on any input, and on the screensaver window losing focus.** The inner
    loop tests `read -rsn1 -t 1 || ! screensaver_in_focus` on every tick, so a
    keypress, a mouse event (mouse tracking was enabled above), or the window
    ceasing to be the active one all end it.
  * **The signal trap runs `exit_screensaver`.** SIGINT/SIGTERM/SIGHUP/SIGQUIT
    each restore the cursor and kill the animation, then exit 0 — so a caller
    that signals the terminal takes the screensaver down cleanly.
  * **`cursor:invisible` is set before the loop and cleared on the way out**,
    via `hyprctl keyword`.
  * **The background is forced black** with `printf '\\033]11;rgb:00/00/00\\007'`.
  * **The `tte` line is commented out in the original; the live binary is
    `ttfx`.** The port runs `ttfx` and leaves the `tte` variant as the comment
    the original carries.
  * **`pgrep -t "${tty#/dev/}" -x ttfx`** matches by controlling terminal and
    whole process name, so a ttfx started elsewhere is not mistaken for ours.

Usage: blackarch-cmd-screensaver
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import termios
import tty
from pathlib import Path

ANIMATOR = "ttfx"
SCREENSAVER_CLASS = "org.blackarch.screensaver"
ANIMATION_FILE = Path.home() / ".config" / "blackarch" / "branding" / "screensaver.txt"

# `printf '\e[?1000h\e[?1003h'` — enable mouse click (1000) and movement (1003)
# reporting, so the terminal delivers escape sequences for both.
MOUSE_TRACKING_ON = "\x1b[?1000h\x1b[?1003h"

# `printf '\033]11;rgb:00/00/00\007'` — set the terminal background to black.
BACKGROUND_BLACK = "\x1b]11;rgb:00/00/00\x07"

# `read -rsn1 -t 0.1` / `-t 1`: silent, no backslash processing, exactly one byte.
POLL_INTERVAL = 0.1
INPUT_TIMEOUT = 1.0

USAGE = "Usage: blackarch-cmd-screensaver"


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def hyprctl_keyword(keyword: str, value: str) -> None:
    """`hyprctl keyword <keyword> <value>`."""
    run(["hyprctl", "keyword", keyword, value])


def screensaver_in_focus() -> bool:
    """`hyprctl activewindow -j | jq -e '.class == "org.blackarch.screensaver"'`.

    `jq -e` exits **0** when the filter produced a value, 4 when it produced none
    (and 1 for false/null). Here the filter yields a boolean, so: true -> 0,
    false -> 1, no window / unreachable compositor -> 4 or non-zero. Both
    non-zero cases mean "not in focus", which is the only distinction the caller
    draws.
    """
    completed = run(["hyprctl", "activewindow", "-j"])
    if completed.returncode != 0:
        return False
    try:
        window = json.loads(completed.stdout.decode("utf-8", "replace"))
    except ValueError:
        return False
    return isinstance(window, dict) and window.get("class") == SCREENSAVER_CLASS


def controlling_terminal() -> str:
    """`tty 2>/dev/null` -> e.g. `/dev/pts/3`, or "" when there is no tty."""
    try:
        return os.ttyname(sys.stdin.fileno())
    except OSError:
        return ""


def animator_running(terminal: str) -> bool:
    """`pgrep -t "${tty#/dev/}" -x ttfx` — by controlling terminal and name.

    `-t` takes the terminal name without the `/dev/` prefix; `-x` is whole-name
    equality on `comm`. Both filters matter: an animator started on another
    terminal must not keep this loop alive.
    """
    name = terminal.removeprefix("/dev/")
    if not name:
        return False
    try:
        completed = subprocess.run(
            ["pgrep", "-t", name, "-x", ANIMATOR],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def kill_animator() -> None:
    """`pkill -x tte` / `pkill -f org.blackarch.screensaver`, status discarded."""
    run(["pkill", "-x", "tte"])
    run(["pkill", "-f", SCREENSAVER_CLASS])


class Screensaver:
    """The running screensaver: owns the terminal mode and the exit path."""

    def __init__(self) -> None:
        self.fileno: int | None = None
        self.original: list | None = None
        self.stopping = False

    # ── exit path ────────────────────────────────────────────────────────────
    def exit_screensaver(self) -> None:
        """`exit_screensaver`: restore the cursor, kill the animation, exit 0.

        `exit 0` in the original is a *plain* exit, so the trap's own status does
        not become the command's — it is always 0. This method therefore reports
        0 whatever happened, including on a signal.
        """
        self.stopping = True
        hyprctl_keyword("cursor:invisible", "false")
        kill_animator()
        self.restore_terminal()
        # The mirror of the enable sequence above: stop reporting clicks and
        # movement, or the next program on this terminal eats escape sequences.
        sys.stdout.write("\x1b[?1000l\x1b[?1003l")
        sys.stdout.flush()
        raise SystemExit(0)

    def restore_terminal(self) -> None:
        if self.fileno is None or self.original is None:
            return
        try:
            termios.tcsetattr(self.fileno, termios.TCSADRAIN, self.original)
        except termios.error:
            pass

    def on_signal(self, signum: int, frame) -> None:
        """The `trap exit_screensaver SIGINT SIGTERM SIGHUP SIGQUIT` handler.

        The handler must itself raise: a signal that only sets a flag leaves the
        blocking read in progress, because Python re-arms an interrupted read
        (PEP 475) — bash's `trap` fires *during* `read -t` and ends it.
        """
        self.exit_screensaver()

    # ── animation loop ───────────────────────────────────────────────────────
    def spawn_animator(self) -> subprocess.Popen | None:
        """`ttfx -i <file> --frame-rate 120 ... &`, or None when ttfx is absent."""
        if not ANIMATION_FILE.is_file():
            return None
        argv = [
            ANIMATOR,
            "-i",
            str(ANIMATION_FILE),
            "--frame-rate",
            "120",
            "--canvas-width",
            "0",
            "--canvas-height",
            "0",
            "--reuse-canvas",
            "--anchor-canvas",
            "c",
            "--anchor-text",
            "c",
            "--random-effect",
            "--no-eol",
            "--no-restore-cursor",
        ]
        try:
            return subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=sys.stdout,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return None

    def flush_pending_input(self) -> None:
        """`while read -rsn1 -t 0.1; do :; done` — drain buffered keystrokes.

        Without a tty there is no input to drain, and the loop simply ends, which
        is what the original does at EOF.
        """
        while self.read_byte(POLL_INTERVAL) is not None:
            pass

    def read_byte(self, timeout: float) -> bytes | None:
        """`read -rsn1 -t <timeout>`: one byte, or None on timeout/EOF/exit.

        `-n1` returns as soon as one byte is read, so a newline does not have to
        arrive. At EOF bash's `read -t` returns non-zero while still assigning
        the partial byte, which this reproduces: a byte is returned, then None
        forever after.
        """
        if self.fileno is None:
            return None
        import select

        try:
            ready, _, _ = select.select([self.fileno], [], [], timeout)
        except (OSError, ValueError):
            return None
        if not ready:
            return None
        try:
            data = os.read(self.fileno, 1)
        except OSError:
            return None
        if not data:
            return None
        return data

    def run(self) -> int:
        self.fileno = sys.stdin.fileno() if sys.stdin.isatty() else None

        for sig in (
            signal.SIGINT,
            signal.SIGTERM,
            signal.SIGHUP,
            signal.SIGQUIT,
        ):
            signal.signal(sig, self.on_signal)

        # Mouse tracking on, then the black background.
        sys.stdout.write(MOUSE_TRACKING_ON)
        sys.stdout.flush()

        if self.fileno is not None:
            try:
                self.original = termios.tcgetattr(self.fileno)
                tty.setraw(self.fileno)
            except termios.error:
                self.original = None

        self.flush_pending_input()

        sys.stdout.write(BACKGROUND_BLACK)
        sys.stdout.flush()

        hyprctl_keyword("cursor:invisible", "true")

        terminal = controlling_terminal()

        while True:
            # The commented-out `tte` invocation the original carries:
            #   tte -i ~/.config/blackarch/branding/screensaver.txt \
            #     --frame-rate 120 --canvas-width 0 --canvas-height 0 \
            #     --reuse-canvas --anchor-canvas c --anchor-text c \
            #     --random-effect --exclude-effects dev_worm \
            #     --no-eol --no-restore-cursor &
            animator = self.spawn_animator()

            while animator_running(terminal):
                if self.stopping:
                    self.exit_screensaver()
                byte = self.read_byte(INPUT_TIMEOUT)
                if byte is not None or not screensaver_in_focus():
                    self.exit_screensaver()

            if animator is not None:
                try:
                    animator.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    animator.kill()
                    animator.wait()


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    try:
        Screensaver().run()
    except SystemExit as exit_request:
        return int(exit_request.code or 0)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
