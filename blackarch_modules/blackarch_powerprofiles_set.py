#!/usr/bin/env python3
# blackarch:summary=Set and remember the power profile for AC or battery use
# blackarch:args=[autodetect|ac|battery] [power-saver|balanced|performance]
"""blackarch-powerprofiles-set — set and remember the power profile per power source.

Python port of the bash original. The remembered profile lives in
$XDG_STATE_HOME/blackarch/powerprofiles/<ac|battery> (override with
BLACKARCH_POWERPROFILES_STATE_DIR) so the shell can restore it on power-source
changes. `powerprofilesctl set` failure propagates as this script's exit code.
"""

import os
import subprocess
import sys

USAGE = (
    "Usage: blackarch-powerprofiles-set "
    "[autodetect|ac|battery] [power-saver|balanced|performance]"
)


def usage() -> int:
    print(USAGE, file=sys.stderr)
    return 1


def list_profiles() -> list:
    """`mapfile -t profiles < <(blackarch-powerprofiles-list)`."""
    try:
        proc = subprocess.run(["blackarch-powerprofiles-list"], stdout=subprocess.PIPE)
    except OSError:
        print("blackarch-powerprofiles-list: command not found", file=sys.stderr)
        return []
    lines = proc.stdout.decode("utf-8", errors="replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def main() -> int:
    args = sys.argv[1:]
    if len(args) > 2:
        return usage()
    action = args[0] if len(args) >= 1 else "autodetect"
    requested_profile = args[1] if len(args) >= 2 else ""

    if action == "autodetect":
        # busctl stderr is /dev/null'd in the original, so a missing busctl or a
        # missing UPower both read as "on AC".
        try:
            proc = subprocess.run(
                [
                    "busctl",
                    "get-property",
                    "org.freedesktop.UPower",
                    "/org/freedesktop/UPower",
                    "org.freedesktop.UPower",
                    "OnBattery",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            on_battery = proc.stdout.decode("utf-8", errors="replace").strip() == "b true"
        except OSError:
            on_battery = False
        action = "battery" if on_battery else "ac"
    elif action not in ("ac", "battery"):
        return usage()

    profiles = list_profiles()

    def profile_available(name: str) -> bool:
        # [[ " ${profiles[*]} " == *" $1 "* ]] — a substring test on the
        # space-joined list, not an exact membership test.
        joined = " " + " ".join(profiles) + " "
        return (" " + name + " ") in joined

    state_dir = os.environ.get("BLACKARCH_POWERPROFILES_STATE_DIR") or os.path.join(
        os.environ.get("XDG_STATE_HOME")
        or os.path.join(os.environ.get("HOME", ""), ".local/state"),
        "blackarch",
        "powerprofiles",
    )
    state_file = os.path.join(state_dir, action)

    profile = ""
    if requested_profile:
        if not profile_available(requested_profile):
            print(f"Power profile is not available: {requested_profile}", file=sys.stderr)
            return 1
        profile = requested_profile
    elif os.access(state_file, os.R_OK):
        with open(state_file, encoding="utf-8", errors="replace") as handle:
            # $(<$state_file) strips all trailing newlines.
            profile = handle.read().rstrip("\n")

    if not profile or not profile_available(profile):
        if action == "ac" and profile_available("performance"):
            profile = "performance"
        else:
            profile = "balanced"

    # powerprofilesctl set "$profile" || exit — `exit` with no args uses the
    # last command's status.
    try:
        rc = subprocess.run(["/usr/bin/powerprofilesctl", "set", profile]).returncode
    except OSError:
        print("powerprofilesctl: command not found", file=sys.stderr)
        return 127
    if rc != 0:
        return rc

    if requested_profile:
        os.makedirs(state_dir, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as handle:
            handle.write(requested_profile + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
