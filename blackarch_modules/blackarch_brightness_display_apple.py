#!/usr/bin/env python3
# blackarch:summary=Show or adjust Apple Studio Display and Apple XDR Display brightness using asdcontrol.
# blackarch:args=[--no-osd] [+N%|N%-|N%]
# blackarch:examples=blackarch brightness display apple | blackarch brightness display apple +5% | blackarch brightness display apple --no-osd 50%
"""blackarch-brightness-display-apple — Apple Studio/XDR Display brightness.

Python port of the bash original. The display is an HID device; `asdcontrol
--detect` over the hiddev nodes names it, and `asdcontrol <device>` reports
BRIGHTNESS as a raw value out of 60000. The device path is cached under the
runtime dir only — with no XDG_RUNTIME_DIR caching is skipped rather than
falling back to a predictable world-writable /tmp path.
"""

import glob
import os
import re
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blackarch_modules.blackarch_helpers import waylandsudo_argv  # noqa: E402

HIDDEV_GLOBS = ("/dev/usb/hiddev*", "/dev/hiddev*")
BRIGHTNESS_LINE = re.compile(r"^BRIGHTNESS=(\d+)\s*$")


def device_cache_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return os.path.join(runtime, "blackarch-brightness-display-apple.device") if runtime else ""


def hiddev_devices() -> list[str]:
    devices: list[str] = []
    for pattern in HIDDEV_GLOBS:
        devices.extend(path for path in glob.glob(pattern) if os.path.exists(path))
    return devices


def asdcontrol(args: list[str]) -> subprocess.CompletedProcess:
    """`waylandsudo asdcontrol` — the Apple display is driven as root, with the
    Wayland session preserved across the privilege escalation."""
    return subprocess.run(waylandsudo_argv(["asdcontrol", *args]),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)


def detect_apple_display_device() -> str:
    """The first hiddev node `asdcontrol --detect` reports, or ""."""
    devices = hiddev_devices()
    if not devices:
        return ""
    proc = asdcontrol(["--detect", *devices])
    if proc.returncode != 0:
        return ""
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if re.match(r"^/dev/(usb/)?hiddev", line):
            return line.split(":", 1)[0]
    return ""


def is_hiddev_char_device(path: str) -> bool:
    """`-c $path`: a character device, not merely an existing name."""
    try:
        return stat.S_ISCHR(os.stat(path).st_mode)
    except OSError:
        return False


def find_apple_display_device() -> str:
    """A hiddev device path, from cache when it still names a character device.

    A stale or unexpected cache (a regular file, a non-hiddev node) is ignored
    and re-detected rather than handed to asdcontrol.
    """
    cache = device_cache_path()
    if cache:
        try:
            cached = open(cache, encoding="utf-8", errors="replace").read().strip()
        except OSError:
            cached = ""
        if cached.startswith("/dev/hiddev") or cached.startswith("/dev/usb/hiddev"):
            if is_hiddev_char_device(cached):
                return cached

    device = detect_apple_display_device()
    if not device:
        return ""

    if cache:
        try:
            with open(cache, "w", encoding="utf-8") as handle:
                handle.write(device + "\n")
        except OSError:
            pass
    return device


def current_brightness(device: str) -> str:
    """The brightness percentage, as `int(raw * 100 / 60000)`."""
    proc = asdcontrol([device])
    if proc.returncode != 0:
        return ""
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        match = BRIGHTNESS_LINE.match(line)
        if match:
            return str(int(int(match.group(1)) * 100 / 60000))
    return ""


def retry_with_fresh_device() -> str:
    """Drop the cache and re-detect; exits 1 with a message when none exists."""
    cache = device_cache_path()
    if cache:
        try:
            os.unlink(cache)
        except OSError:
            pass
    device = find_apple_display_device()
    if not device:
        print("No Apple Display HID device found", file=sys.stderr)
        raise SystemExit(1)
    return device


def main(argv: list[str]) -> int:
    args = list(argv)
    no_osd = False
    if args and args[0] == "--no-osd":
        no_osd = True
        args = args[1:]

    device = find_apple_display_device()
    if not device:
        print("No Apple Display HID device found", file=sys.stderr)
        return 1

    if not args:
        brightness = current_brightness(device)
        if brightness:
            print(brightness)
            return 0
        device = retry_with_fresh_device()
        print(current_brightness(device))
        return 0

    step = args[0]
    match = re.fullmatch(r"([0-9]+)%-", step)
    if match:
        step = f"-{match.group(1)}%"

    if asdcontrol([device, "--", step]).returncode != 0:
        device = retry_with_fresh_device()
        asdcontrol([device, "--", step])

    if not no_osd:
        brightness = current_brightness(device)
        if brightness:
            subprocess.run(["blackarch-osd", "-i", "brightness", "-p", brightness],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
