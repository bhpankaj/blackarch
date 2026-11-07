#!/usr/bin/env python3
# blackarch:summary=Launch the Blackarch shell with its log kept in the journal
# blackarch:hidden=true
"""blackarch-launch-shell — supervise the Blackarch quickshell instance.

Python port of the bash `blackarch-launch-shell`. It starts Quickshell under
systemd-cat so the shell's log survives in the journal across sessions, then
relaunches it whenever it dies unexpectedly, bounded to five relaunches inside
one minute. A clean exit (status 0) and a dead compositor both end supervision.

This script takes no arguments; Hyprland autostart runs it once per session with
BLACKARCH_PATH exported.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

LOG_TAG = "blackarch-shell"
SHELL_CONFIG_SUFFIX = "/shell"

ATTEMPT_WINDOW = 60.0  # seconds; the relaunch budget resets once this elapses
MAX_ATTEMPTS = 5  # relaunches allowed inside ATTEMPT_WINDOW
RELAUNCH_BACKOFF = 1.0
COMPOSITOR_ATTEMPTS = 3
COMPOSITOR_RETRY = 0.5

terminating = False
shell_pid: int | None = None


def log(message: str) -> None:
    subprocess.run(["logger", "-t", LOG_TAG, message], check=False)


def stop_handler(signum: int, frame: object) -> None:
    """HUP/INT/TERM: stop relaunching and hand the signal to Quickshell."""
    global terminating
    terminating = True
    if shell_pid is None:
        return
    try:
        os.kill(shell_pid, signal.SIGTERM)
    except OSError:
        pass


def run_shell(blackarch_path: str) -> int:
    """Start Quickshell and block until it exits; return its exit status."""
    global shell_pid
    process = subprocess.Popen(
        [
            "systemd-cat",
            "-t",
            LOG_TAG,
            "--",
            "quickshell",
            "-n",
            "-p",
            f"{blackarch_path}{SHELL_CONFIG_SUFFIX}",
        ],
        env={**os.environ, "QS_DISABLE_FILE_WATCHER": "1", "QS_NO_RELOAD_POPUP": "1"},
    )
    shell_pid = process.pid
    try:
        status = process.wait()
    finally:
        shell_pid = None

    # Bash reports a signal death as 128 + signum; wait() returns -signum.
    return 128 - status if status < 0 else status


def compositor_alive() -> bool:
    """Query the compositor, retrying while it is busy reconfiguring outputs."""
    for attempt in range(1, COMPOSITOR_ATTEMPTS + 1):
        alive = (
            subprocess.run(
                ["hyprctl", "-j", "monitors"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
        if alive:
            return True
        if attempt < COMPOSITOR_ATTEMPTS:
            time.sleep(COMPOSITOR_RETRY)
    return False


def main() -> int:
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_handler)

    blackarch_path = os.environ.get("BLACKARCH_PATH", "")
    attempts = 0
    window_started = time.monotonic()

    while True:
        # A signal during the backoff only reaches the handler once the sleep
        # is over, so terminating is checked here as well.
        if terminating:
            return 0

        status = run_shell(blackarch_path)

        if terminating:
            return 0
        if status == 0:
            return 0

        # Relaunching into a session already tearing down burns the budget.
        if not compositor_alive():
            return 0

        if time.monotonic() - window_started > ATTEMPT_WINDOW:
            attempts = 0
            window_started = time.monotonic()

        attempts += 1
        if attempts > MAX_ATTEMPTS:
            log(
                f"Giving up on the Blackarch shell after {attempts} relaunches "
                "in under a minute."
            )
            return 1

        log(f"Blackarch shell exited with status {status}; relaunching.")
        time.sleep(RELAUNCH_BACKOFF)


if __name__ == "__main__":
    sys.exit(main())
