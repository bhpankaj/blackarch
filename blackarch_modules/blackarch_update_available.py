#!/usr/bin/env python3
# blackarch:summary=Report pending package updates as Waybar JSON
# blackarch:examples=blackarch update available | blackarch-update-available
"""blackarch-update-available — report pending package updates as Waybar JSON.

Standalone Python replacement for the bash `blackarch-update-available` (the
Waybar `custom-updates` module). It elevates through `sudo -E` when it is not
already root, refreshes the sync database, counts upgradable packages from
pacman plus the AUR helper (dnf on Fedora), and prints the payload the bar
widget reads:

  {"text": "N", "alt": "N", "tooltip": "Click to update your system", "class": "green|yellow|red"}

The thresholds are 0 (green), 25 (yellow) and 100 (red); the widget itself keys
off the process exit status, and this command exits 0 either way.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blackarch_modules.blackarch_helpers import current_wayland_env, waylandsudo_argv  # noqa: E402

THRESHOLD_GREEN = 0
THRESHOLD_YELLOW = 25
THRESHOLD_RED = 100


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


def decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def line_count(text: str) -> int:
    """`wc -l`: newline characters, not lines."""
    return text.count("\n")


def run_as_user(*args: str) -> str:
    """`run_as_user`: run a command as the invoking user."""
    user = os.environ.get("SUDO_USER") or "blackarch"
    proc = subprocess.run(["sudo", "-u", user, *args], stdout=subprocess.PIPE)
    return decode(proc.stdout)


def count_instances(script_name: str) -> int:
    """`ps aux | grep -F "$script_name" | grep -v grep | grep -v $$ | wc -l`."""
    proc = subprocess.run(["ps", "aux"], stdout=subprocess.PIPE)
    pid = str(os.getpid())
    count = 0
    for line in decode(proc.stdout).split("\n"):
        if script_name in line and "grep" not in line and pid not in line:
            count += 1
    return count


def check_lock_files() -> None:
    """`check_lock_files`: wait for another pacman/checkup run to finish."""
    pacman_lock = "/var/lib/pacman/db.lck"
    checkup_lock = os.path.join(
        os.environ.get("TMPDIR") or "/tmp", f"checkup-db-{os.getuid()}/db.lck"
    )
    while os.path.exists(pacman_lock) or os.path.exists(checkup_lock):
        time.sleep(1)


def main() -> int:
    # Ensure the script is run with sudo.
    if os.geteuid() != 0:
        try:
            # `sudo -E` keeps the caller's environment; going through waylandsudo
            # instead also keeps the Wayland session, which this command needs to
            # reach the AUR helper and pacman from the graphical session.
            env_pairs = [f"{key}={value}"
                         for key, value in current_wayland_env().items() if value]
            argv = ["sudo", "-E", "/usr/bin/env", *env_pairs,
                    sys.argv[0], *sys.argv[1:]]
            os.execvp(argv[0], argv)
        except OSError:
            pass
        return 1

    subprocess.run(["pacman", "-Sy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Count the instances.
    script_name = os.path.basename(sys.argv[0])
    instance_count = count_instances(script_name)
    if instance_count > 1:
        time.sleep(instance_count)

    updates = 0

    # Arch
    if command_exists("pacman"):
        check_lock_files()

        yay_installed = command_exists("yay")
        paru_installed = command_exists("paru")
        if yay_installed and not paru_installed:
            aur_helper = "yay"
        elif not yay_installed and paru_installed:
            aur_helper = "paru"
        else:
            aur_helper = "yay"

        updates_pacman = line_count(decode(
            subprocess.run(["pacman", "-Qun"], stdout=subprocess.PIPE).stdout
        ))
        updates_aur = line_count(run_as_user(aur_helper, "-Qum"))
        updates = updates_aur + updates_pacman

    # Fedora
    elif command_exists("dnf"):
        out = decode(subprocess.run(["dnf", "check-update", "-q"], stdout=subprocess.PIPE).stdout)
        updates = sum(1 for line in out.split("\n") if re.match(r"[a-z0-9]", line))

    # Others
    else:
        updates = 0

    # Output in JSON format for Waybar Module custom-updates.
    css_class = "green"
    if updates > THRESHOLD_YELLOW:
        css_class = "yellow"
    if updates > THRESHOLD_RED:
        css_class = "red"

    if updates != 0:
        if updates > THRESHOLD_GREEN:
            sys.stdout.write(
                '{"text": "%s", "alt": "%s", "tooltip": "Click to update your system",'
                ' "class": "%s"}' % (updates, updates, css_class)
            )
        else:
            sys.stdout.write(
                '{"text": "0", "alt": "0", "tooltip": "No updates available",'
                ' "class": "green"}'
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
