#!/usr/bin/env python3
# blackarch:summary=Show or adjust brightness on the focused display.
# blackarch:args=[--no-osd] [--monitor name] [+N%|N%-|N%|off|on]
# blackarch:examples=blackarch brightness display | blackarch brightness display +5% | blackarch brightness display --monitor DP-1 50% | blackarch brightness display off | blackarch brightness display on
"""blackarch-brightness-display — show or adjust brightness on a display.

Mirrors the bash original, including the flock that drops overlapping key
events. Internal (eDP/LVDS/DSI) panels go through brightnessctl on the
runtime-discovered backlight device; external Apple and DDC/CI displays are
delegated to the sibling blackarch-brightness-display-apple / -ddc helpers.
"""

import fcntl
import json
import os
import re
import subprocess
import sys

INTERNAL_CONNECTOR = re.compile(r"^(eDP|LVDS|DSI)-")
BACKLIGHT_PATH = os.environ.get("BLACKARCH_BACKLIGHT_PATH", "/sys/class/backlight")
LOCK_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "blackarch-brightness-display.lock"
)


def run(argv, check=False):
    return subprocess.run(argv, check=check)


def hyprctl_json(command):
    try:
        result = subprocess.run(
            ["hyprctl", "-j", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout.decode())
    except (ValueError, UnicodeDecodeError):
        return None


def monitor_focused():
    return subprocess.run(
        ["blackarch-hyprland-monitor-focused"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout.decode().strip()


def monitor_is_internal(monitor):
    return bool(INTERNAL_CONNECTOR.match(monitor))


def use_apple_display(monitor):
    return (
        run(["blackarch-hyprland-monitor-focused-apple", monitor]).returncode == 0
    )


def use_ddc_display(monitor):
    return bool(monitor) and not monitor_is_internal(monitor)


def hw_display():
    """The runtime-discovered backlight device name, or "" on failure.

    Same heuristic as blackarch-hw-display: skip the Mac Touch Bar backlight,
    then prefer gmux, then amdgpu/intel/acpi, else the first remaining entry.
    """
    try:
        names = [
            name
            for name in os.listdir(BACKLIGHT_PATH)
            if name != "appletb_backlight"
        ]
    except OSError:
        return ""
    if names:
        device = names[0]
    else:
        return ""
    for pattern in ("gmux_backlight", "amdgpu_bl*", "intel_backlight", "acpi_video*"):
        import glob as _glob

        for candidate in _glob.glob(os.path.join(BACKLIGHT_PATH, pattern)):
            if os.path.exists(candidate):
                return os.path.basename(candidate)
    return device


def backlight_brightness(device):
    """The percent field of `brightnessctl -d <device> -m`, or None."""
    try:
        result = subprocess.run(
            ["brightnessctl", "-d", device, "-m"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    line = result.stdout.decode().strip()
    if not line:
        return None
    fields = line.split(",")
    if len(fields) < 4:
        return None
    percent = fields[3].replace("%", "")
    if not percent.isdigit():
        return None
    return percent


def main(argv):
    args = list(argv)
    no_osd = 0
    monitor = ""

    while args:
        first = args[0]
        if first == "--no-osd":
            no_osd = 1
            args = args[1:]
        elif first == "--monitor":
            if len(args) < 2:
                return 1
            monitor = args[1]
            args = args[2:]
        else:
            break

    if not monitor:
        monitor = monitor_focused()

    if not args:
        if use_apple_display(monitor):
            run(["blackarch-brightness-display-apple"])
            return 0
        if use_ddc_display(monitor):
            result = run(["blackarch-brightness-display-ddc", monitor])
            return result.returncode

        device = hw_display()
        if not device:
            return 1
        percent = backlight_brightness(device)
        if percent is None:
            return 1
        print(percent)
        return 0

    step = args[0]

    if step == "off":
        run(
            ["hyprctl", "dispatch", 'hl.dsp.dpms({ action = "disable" })'],
            check=False,
        )
        return 0
    if step == "on":
        # Skip the dispatch when every active display is already lit: a redundant
        # DPMS enable right after system resume forces another modeset, which blanks
        # the panel for a beat (visible flash at the unlock screen).
        monitors = hyprctl_json("monitors") or []
        if monitors and all(m.get("dpmsStatus") for m in monitors):
            return 0
        run(
            ["hyprctl", "dispatch", 'hl.dsp.dpms({ action = "enable" })'],
            check=False,
        )
        return 0

    # Drop overlapping brightness key events so concurrent invocations do not race.
    # Hardware key repeat present on some devices can otherwise glitch OSD rendering.
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0

        if use_apple_display(monitor):
            apple_args = ["blackarch-brightness-display-apple"]
            if no_osd:
                apple_args.append("--no-osd")
            apple_args.append(step)
            run(apple_args, check=False)
        elif use_ddc_display(monitor):
            brightness = subprocess.run(
                ["blackarch-brightness-display-ddc", monitor, step],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            ).stdout.decode().strip()
            if not brightness:
                return 1
            if not no_osd:
                run(["blackarch-osd", "-i", "brightness", "-p", brightness], check=False)
        else:
            # Current device highlighted
            device = hw_display()
            if not device:
                return 1

            # Current brightness percentage
            current = backlight_brightness(device)
            if current is None:
                return 1
            current = int(current)

            # Apply non-uniform step size: 1% steps if at or below 5%, otherwise set an
            # absolute target percentage to avoid raw backlight rounding causing uneven OSD steps.
            if step == "+5%":
                if current < 5:
                    target = current + 1
                else:
                    target = current + 5

                if target > 100:
                    target = 100
                step = f"{target}%"
            elif step == "5%-":
                if current <= 5:
                    target = current - 1
                else:
                    target = current - 5

                if target < 1:
                    target = 1
                step = f"{target}%"

            # Set brightness of the display device.
            run(["brightnessctl", "-d", device, "set", step], check=False)

            # Show the new brightness in OSD
            if not no_osd:
                percent = backlight_brightness(device)
                if percent is not None:
                    run(
                        ["blackarch-osd", "-i", "brightness", "-p", percent],
                        check=False,
                    )
        return 0
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
