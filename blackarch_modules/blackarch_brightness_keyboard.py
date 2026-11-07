#!/usr/bin/env python3
# blackarch:summary=Adjust keyboard backlight brightness using available steps.
# blackarch:args=[--no-osd] <up|down|cycle|off|restore>
"""blackarch-brightness-keyboard — step the keyboard backlight.

Mirrors the bash original. The backlight device is discovered at runtime from
/sys/class/leds by the *kbd_backlight* glob (locale collated, as bash expands
globs), then driven through brightnessctl.
"""

import glob
import locale
import os
import subprocess
import sys

LEDS_PATH = os.environ.get("BLACKARCH_LEDS_PATH", "/sys/class/leds")


def collated(paths):
    """Bash glob expansion order is locale collated, not byte order."""
    locale.setlocale(locale.LC_ALL, "")
    return sorted(paths, key=locale.strxfrm)


def find_kbd_backlight():
    for candidate in collated(glob.glob(os.path.join(LEDS_PATH, "*kbd_backlight*"))):
        if os.path.exists(candidate):
            return os.path.basename(candidate)
    return ""


def main(argv):
    args = list(argv)
    no_osd = 0
    if args and args[0] == "--no-osd":
        no_osd = 1
        args = args[1:]

    direction = args[0] if args else "up"

    device = find_kbd_backlight()

    if not device:
        print("No keyboard backlight device found", file=sys.stderr)
        return 1

    if direction == "off":
        subprocess.run(
            ["brightnessctl", "-sd", device, "set", "0"],
            stdout=subprocess.DEVNULL,
            check=False,
        )
        return 0
    if direction == "restore":
        subprocess.run(
            ["brightnessctl", "-rd", device],
            stdout=subprocess.DEVNULL,
            check=False,
        )
        return 0

    # Get current and max brightness to determine step size.
    try:
        max_brightness = int(
            subprocess.run(
                ["brightnessctl", "-d", device, "max"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            .stdout.decode()
            .strip()
        )
        current_brightness = int(
            subprocess.run(
                ["brightnessctl", "-d", device, "get"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            .stdout.decode()
            .strip()
        )
    except (ValueError, OSError):
        return 1

    # Calculate step as 10% of max brightness. Keyboards with many levels (e.g. 512)
    # need larger steps; keyboards with few levels (e.g. 3) fall back to step=1.
    step = max_brightness // 10
    if step < 1:
        step = 1

    if direction == "cycle":
        new_brightness = current_brightness + step
        if new_brightness > max_brightness:
            new_brightness = 0
    elif direction == "up":
        new_brightness = current_brightness + step
        if new_brightness > max_brightness:
            new_brightness = max_brightness
    else:
        new_brightness = current_brightness - step
        if new_brightness < 0:
            new_brightness = 0

    # Set the new brightness.
    subprocess.run(
        ["brightnessctl", "-d", device, "set", str(new_brightness)],
        stdout=subprocess.DEVNULL,
        check=False,
    )
    if not no_osd:
        subprocess.run(
            ["blackarch-osd", "-i", "keyboard", "-p", str(new_brightness * 100 // max_brightness)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
