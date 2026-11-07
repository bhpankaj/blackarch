#!/usr/bin/env python3
# blackarch:summary=Enable, disable, or toggle a Hyprland input device
# blackarch:args=<touchpad|touchscreen> [on|off|toggle]
# blackarch:hidden=true
"""blackarch-toggle-input-device — enable, disable or toggle a Hyprland input device.

Python port of the bash original, which drives the compositor with
`hyprctl eval "hl.device({ name = …, enabled = … })"` and persists the disabled
device's name in `~/.local/state/blackarch/toggles/hypr/<kind>-disabled-name` so
a reload can re-apply it.

The persisted name is device data from USB descriptors, never shell or Lua
input: it is written as a plain line, read back with `io.open`, and interpolated
into the Lua source only through an escaping step (see `lua_string`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HYPRCTL = "hyprctl"
OSD = "blackarch-osd"
DEVICE_DETECTOR = "blackarch-hw-{kind}"

# kind -> (label shown in the OSD, icon name). The two are separate because the
# OSD icon is not the device class: "touchpad" and "touch" are distinct names.
KINDS = {
    "touchpad": ("Touchpad", "touchpad"),
    "touchscreen": ("Touchscreen", "touch"),
}

USAGE = "Usage: blackarch-toggle-input-device <touchpad|touchscreen> [on|off|toggle]"


def state_path(kind: str) -> Path:
    """`$HOME/.local/state/blackarch/toggles/hypr/<kind>-disabled-name`.

    Hardcoded to ~/.local/state rather than $XDG_STATE_HOME so the path matches
    the sibling toggle tools and keeps working when XDG_STATE_HOME diverges —
    a mismatch here would silently lose the persisted disable across a reload.
    """
    return Path(os.path.expanduser("~")) / ".local" / "state" / "blackarch" / "toggles" / "hypr" / f"{kind}-disabled-name"


def detect_device(kind: str) -> str:
    """`blackarch-hw-<kind>`, captured. An absent detector is an empty answer.

    The original runs the detector as a shell command and lets an empty result
    fall through to `require_device`, so a missing binary must not raise here.
    """
    try:
        proc = subprocess.run(
            [DEVICE_DETECTOR.format(kind=kind)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def lua_string(value: str) -> str:
    """A Lua double-quoted string literal for a device name.

    JSON's escapes for the two characters that matter here — `\\` and `"` — are
    identical to Lua's, and `ensure_ascii=False` keeps the raw bytes the bash
    `quoted=${device//\\/\\\\}` substitution passed through. Control characters
    are rejected earlier by `require_device`, so nothing else needs escaping.
    """
    return json.dumps(value, ensure_ascii=False)


def apply_device(device: str, enabled: bool) -> int:
    """`hl.device({ name = "…", enabled = <bool> })` through `hyprctl eval`.

    The bare call is the form the original used and the one `hyprctl eval`
    accepts; the `return` form is not needed and both behave identically.
    """
    expression = (
        f'hl.device({{ name = {lua_string(device)}, '
        f"enabled = {'true' if enabled else 'false'} }})"
    )
    try:
        proc = subprocess.run(
            [HYPRCTL, "eval", expression],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return 1
    return proc.returncode


def notify(icon: str, message: str) -> None:
    """Show the OSD. A shell that is not running is not a failure here."""
    try:
        subprocess.run(
            [OSD, "-i", icon, "-m", message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        pass


def require_device(device: str, kind: str) -> bool:
    """True when the name is usable. A control character means unsafe to quote."""
    if device == "":
        print(f"No {kind} device found", file=sys.stderr)
        return False
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in device):
        print(f"Invalid {kind} device name", file=sys.stderr)
        return False
    return True


def enable(kind: str, label: str, icon: str) -> int:
    """Enable the device. The persisted state is cleared before the device is
    required, so a device that stops reporting a valid name can never wedge the
    disable in place."""
    state = state_path(kind)
    try:
        state.unlink()
    except OSError:
        pass

    device = detect_device(kind)
    if not require_device(device, kind):
        return 1

    if apply_device(device, True) != 0:
        return 1
    notify(icon, f"{label} enabled")
    return 0


def disable(kind: str, label: str, icon: str) -> int:
    """Disable the device and persist its name for the reload path."""
    device = detect_device(kind)
    if not require_device(device, kind):
        return 1

    if apply_device(device, False) != 0:
        return 1

    state = state_path(kind)
    state.parent.mkdir(parents=True, exist_ok=True)
    try:
        state.write_text(f"{device}\n", encoding="utf-8")
    except OSError as exc:
        print(f"Could not persist the disabled {kind}: {exc}", file=sys.stderr)
        return 1

    notify(icon, f"{label} disabled")
    return 0


def toggle(kind: str, label: str, icon: str) -> int:
    """Toggle on the persisted file: its presence means the device is disabled."""
    if state_path(kind).is_file():
        return enable(kind, label, icon)
    return disable(kind, label, icon)


def main(argv: list[str]) -> int:
    kind = argv[0] if argv else ""
    action = argv[1] if len(argv) > 1 else "toggle"

    if kind not in KINDS:
        print(USAGE, file=sys.stderr)
        return 1

    label, icon = KINDS[kind]

    if action == "on":
        return enable(kind, label, icon)
    if action == "off":
        return disable(kind, label, icon)
    if action == "toggle":
        return toggle(kind, label, icon)

    print(USAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
