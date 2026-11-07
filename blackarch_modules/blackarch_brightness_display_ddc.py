#!/usr/bin/env python3
# blackarch:summary=Show or adjust DDC/CI display brightness for a Hyprland monitor.
# blackarch:args=<monitor> [+N%|N%-|N%]
# blackarch:examples=blackarch-brightness-display-ddc DP-1 | blackarch-brightness-display-ddc DP-1 50%
"""blackarch-brightness-display-ddc — show or adjust DDC/CI brightness.

Python port of the bash original. The I2C bus for a Hyprland monitor name comes
from `ddcutil --skip-ddc-checks detect --brief`, and the brightness from
`ddcutil --bus <bus> getvcp 10 --brief`. Both are cached under the runtime dir so
repeated key presses do not re-probe; an unreachable monitor is cached as
"unavailable" for 60s, a bus/brightness pair for 10s.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

UNAVAILABLE_CACHE_SECONDS = 60
RANGE_CACHE_SECONDS = 10

I2C_BUS_LINE = re.compile(r"^I2C bus:\s+(\S+)\s*$")
DRM_CONNECTOR_LINE = re.compile(r"^DRM connector:\s+(\S+)\s*$")
VCP_LINE = re.compile(r"^VCP\s+([0-9A-Fa-f]{2})\s+([A-Z])\s+([0-9]+)\s+([0-9]+)\s*$")


def run_quiet(argv: list[str]) -> str:
    """stdout with trailing whitespace stripped; "" on failure."""
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def cache_paths(monitor: str) -> Path:
    """The per-monitor cache file. The monitor name is sanitized to [A-Za-z0-9_.-]."""
    cache_dir = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "blackarch-brightness-display-ddc"
    cache_name = re.sub(r"[^0-9A-Za-z_.-]", "_", monitor)
    return cache_dir / f"{cache_name}.bus"


def cache_unavailable(path: Path) -> None:
    """Record that the monitor could not be probed, timestamped."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"unavailable {int(time.time())}\n")
    except OSError:
        pass


def detect_bus(monitor: str) -> str:
    """The I2C bus number for `monitor`, parsed out of ddcutil's detect output."""
    bus = ""
    for line in run_quiet(["ddcutil", "--skip-ddc-checks", "detect", "--brief"]).splitlines():
        match = I2C_BUS_LINE.match(line)
        if match:
            bus = match.group(1)
            bus = re.sub(r"^.*/i2c-", "", bus)
            continue
        match = DRM_CONNECTOR_LINE.match(line)
        if match:
            connector = re.sub(r"^card[0-9]+-", "", match.group(1))
            if connector == monitor and bus:
                return bus
            bus = ""
    return ""


def find_bus(monitor: str) -> str:
    """A bus number for `monitor`, from cache when it is still fresh."""
    path = cache_paths(monitor)
    bus = ""

    try:
        fields = path.read_text(errors="replace").split()
    except OSError:
        fields = []

    if fields:
        bus = fields[0]
        if bus == "unavailable":
            timestamp = fields[1] if len(fields) > 1 else ""
            if timestamp.isdigit() and int(time.time()) - int(timestamp) < UNAVAILABLE_CACHE_SECONDS:
                return ""
            bus = ""
            try:
                path.unlink()
            except OSError:
                pass

    if not bus:
        bus = detect_bus(monitor)
        if not bus.isdigit():
            cache_unavailable(path)
            return ""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{bus}\n")
        except OSError:
            pass

    return bus


def read_vcp(bus: str) -> str:
    """"current maximum" for VCP code 10 (brightness), or ""."""
    for line in run_quiet(["ddcutil", "--bus", bus, "--skip-ddc-checks", "getvcp", "10", "--brief"]).splitlines():
        match = VCP_LINE.match(line)
        if match and match.group(1).lower() == "10" and match.group(2) == "C":
            current, maximum = match.group(3), match.group(4)
            if maximum.isdigit() and int(maximum) > 0:
                return f"{current} {maximum}"
    return ""


def read_brightness(monitor: str) -> tuple[str, str, str]:
    """(bus, current, maximum) for `monitor`, updating the cache."""
    path = cache_paths(monitor)
    bus = find_bus(monitor)
    if not bus:
        return "", "", ""

    values = read_vcp(bus)
    if not values:
        try:
            path.unlink()
        except OSError:
            pass
        return "", "", ""

    now = int(time.time())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{bus} {values.split()[-1]} {now}\n")
    except OSError:
        pass
    parts = values.split()
    return bus, parts[0], parts[1]


def percent(current: str, maximum: str) -> int:
    """(current * 100 + maximum / 2) / maximum — bash integer arithmetic."""
    return (int(current) * 100 + int(maximum) // 2) // int(maximum)


def set_vcp(bus: str, value: int) -> bool:
    return subprocess.run(
        ["ddcutil", "--bus", bus, "--skip-ddc-checks", "--noverify", "setvcp", "10", str(value)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0


def main(argv: list[str]) -> int:
    monitor = argv[0] if argv else ""
    step = argv[1] if len(argv) > 1 else ""

    if not monitor:
        return 1

    path = cache_paths(monitor)

    if not step:
        bus, current, maximum = read_brightness(monitor)
        if not (bus and current and maximum):
            return 1
        print(percent(current, maximum))
        return 0

    set_percent = re.fullmatch(r"([0-9]+)%", step)
    plus_percent = re.fullmatch(r"\+([0-9]+)%", step)
    minus_percent = re.fullmatch(r"([0-9]+)%-", step)
    if not (set_percent or plus_percent or minus_percent):
        return 1

    target = 0
    range_fresh = False

    if set_percent:
        target = int(set_percent.group(1))
        try:
            fields = path.read_text(errors="replace").split()
        except OSError:
            fields = []
        if len(fields) >= 3 and all(f.isdigit() for f in fields[:3]) and int(fields[1]) > 0:
            now = int(time.time())
            if int(fields[2]) <= now < int(fields[2]) + RANGE_CACHE_SECONDS:
                range_fresh = True
        if not range_fresh:
            bus, current, maximum = read_brightness(monitor)
            if not (bus and current and maximum):
                return 1
        else:
            bus, maximum = fields[0], fields[1]
    else:
        bus, current, maximum = read_brightness(monitor)
        if not (bus and current and maximum):
            return 1
        amount = int(plus_percent.group(1)) if plus_percent else int(minus_percent.group(1))
        current_percent = percent(current, maximum)
        if plus_percent:
            # A +5% press below 5% moves to 6% rather than staying put.
            target = current_percent + 1 if amount == 5 and current_percent < 5 else current_percent + amount
        else:
            target = current_percent - 1 if amount == 5 and current_percent <= 5 else current_percent - amount

    if target < 1:
        target = 1
    if target > 100:
        target = 100

    raw_target = (target * int(maximum) + 50) // 100

    if not set_vcp(bus, raw_target):
        try:
            path.unlink()
        except OSError:
            pass
        return 1

    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
