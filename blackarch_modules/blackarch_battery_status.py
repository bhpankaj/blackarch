#!/usr/bin/env python3
# blackarch:summary=Returns a formatted battery status string with percentage and power draw/charge.
# blackarch:args=[--shell]
"""Python port of blackarch-battery-status (bash)."""

import glob
import os
import re
import subprocess
import sys

POWER_SUPPLY_PATH = os.environ.get("BLACKARCH_POWER_SUPPLY_PATH") or "/sys/class/power_supply"


# The original emits these private-use glyphs (U+F062 / U+F063), not
# U+1F162/U+1F163; they must stay byte-identical for the shell's font.
CHARGING_GLYPH = "\uf062"
DISCHARGING_GLYPH = "\uf063"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def read_text(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def first_line_matching(text, pattern):
    """awk '/pat/ { print $2; exit }' — first matching line's second field."""
    for line in text.split("\n"):
        if re.search(pattern, line):
            fields = line.split()
            return fields[1] if len(fields) > 1 else ""
    return ""


def awk_percentage(info):
    """awk '/percentage/ { print int($2); exit }' — the % is stripped here."""
    value = first_line_matching(info, r"percentage")
    value = value.replace("%", "")
    try:
        return str(int(float(value)))
    except ValueError:
        return ""


def awk_capacity(info):
    """awk '/energy-full:/ { printf "%d", $2; exit }'"""
    value = first_line_matching(info, r"energy-full:")
    try:
        return str(int(float(value)))
    except ValueError:
        return ""


def awk_time_remaining(info):
    """awk '/time to (empty|full)/ { ... }' — value $4, unit $5."""
    for line in info.split("\n"):
        if re.search(r"time to (empty|full)", line):
            fields = line.split()
            value = float(fields[3])
            unit = fields[4]
            if unit.startswith("minute"):
                return "%dm" % int(value)
            hours = int(value)
            minutes = int((value - hours) * 60)
            if minutes > 0:
                return "%dh %dm" % (hours, minutes)
            return "%dh" % hours
    return ""


def awk_energy_rate(info):
    return first_line_matching(info, r"energy-rate")


def awk_native_path(info):
    return first_line_matching(info, r"native-path")


def awk_state(info):
    return first_line_matching(info, r"state")


def awk_threshold(info, field):
    """awk '/<field>:/ { gsub(/%/, "", $2); print int($2); exit }'"""
    value = first_line_matching(info, field + r":")
    value = value.replace("%", "")
    try:
        return str(int(float(value)))
    except ValueError:
        return ""


def format_power_rate(rate):
    r"""awk 'BEGIN { rounded = sprintf("%.1f", rate); sub(/\.0$/, "", rounded) }'"""
    rounded = "%.1f" % rate
    if rounded.endswith(".0"):
        rounded = rounded[:-2]
    return rounded


def glob_first(pattern):
    """cat "$dir"/BAT*/file 2>/dev/null | head -1 — first glob match, first line."""
    for path in sorted(glob.glob(pattern)):
        if os.access(path, os.R_OK):
            return read_text(path)
    return ""


def upower_battery():
    """upower -e | grep BAT | head -n 1"""
    out = run(["upower", "-e"]).stdout
    for line in out.split("\n"):
        if "BAT" in line:
            return line
    return ""


def upower_battery_info(device):
    return run(["upower", "-i", device]).stdout


def ac_online(power_supply_path):
    """Loop over "$path"/* looking for a Mains supply that is online."""
    for supply in sorted(glob.glob(os.path.join(power_supply_path, "*"))):
        if not os.access(os.path.join(supply, "type"), os.R_OK):
            continue
        if read_text(os.path.join(supply, "type")) != "Mains":
            continue
        if not os.access(os.path.join(supply, "online"), os.R_OK):
            continue
        if read_text(os.path.join(supply, "online")) == "1":
            return True
    return False


def power_rate_raw(battery_info, battery_path):
    """UPower's energy-rate can lag the kernel telemetry by tens of seconds.

    Use the instantaneous sysfs reading when available so the open panel stays
    live. Mirrors the bash power_now / current_now+voltage_now fallback.
    """
    raw = awk_energy_rate(battery_info)

    power_now = os.path.join(battery_path, "power_now")
    if os.access(power_now, os.R_OK):
        microwatts = read_text(power_now)
        try:
            return str(float(microwatts) / 1000000)
        except ValueError:
            return raw

    current_path = os.path.join(battery_path, "current_now")
    voltage_path = os.path.join(battery_path, "voltage_now")
    if os.access(current_path, os.R_OK) and os.access(voltage_path, os.R_OK):
        try:
            microamps = float(read_text(current_path))
            microvolts = float(read_text(voltage_path))
            return str(microamps * microvolts / 1000000000000)
        except ValueError:
            return raw

    return raw


def main(argv):
    shell_output = False
    if len(argv) > 1:
        if argv[1] == "--shell":
            shell_output = True
        else:
            print("Usage: blackarch-battery-status [--shell]", file=sys.stderr)
            return 2

    battery = upower_battery()
    if not battery:
        return 0

    battery_info = upower_battery_info(battery)

    percentage = awk_percentage(battery_info)
    capacity = awk_capacity(battery_info)
    time_remaining = awk_time_remaining(battery_info)
    native_path = awk_native_path(battery_info)
    battery_path = os.path.join(POWER_SUPPLY_PATH, native_path)

    rate_raw = power_rate_raw(battery_info, battery_path)
    power_rate = format_power_rate(float(rate_raw) if rate_raw else 0.0)
    state = awk_state(battery_info)
    threshold_start = awk_threshold(battery_info, "charge-start-threshold")
    threshold_end = awk_threshold(battery_info, "charge-end-threshold")

    if not threshold_end:
        threshold_end = glob_first(os.path.join(POWER_SUPPLY_PATH, "BAT*", "charge_control_end_threshold"))
    if not threshold_start:
        threshold_start = glob_first(os.path.join(POWER_SUPPLY_PATH, "BAT*", "charge_control_start_threshold"))

    online = ac_online(POWER_SUPPLY_PATH)
    charge_idle = (float(rate_raw) if rate_raw else 0.0) <= 0.2

    charge_holding = False
    if online and threshold_end:
        if state == "pending-charge":
            charge_holding = True
        elif state == "fully-charged" and int(float(percentage)) < 99:
            charge_holding = True
        elif (
            state == "charging"
            and charge_idle
            and int(float(threshold_end)) < 99
            and int(float(percentage)) >= int(float(threshold_end))
        ):
            charge_holding = True

    if shell_output:
        sys.stdout.write("percentage\t" + percentage + "%\n")
        if charge_holding:
            sys.stdout.write("state\tholding\n")
        else:
            sys.stdout.write("state\t" + state + "\n")
        sys.stdout.write("rate\t" + power_rate + "W\n")
        sys.stdout.write("size\t" + capacity + "Wh\n")
        sys.stdout.write("time\t" + time_remaining + "\n")

        cycles = glob_first(os.path.join(POWER_SUPPLY_PATH, "BAT*", "cycle_count"))
        if cycles:
            sys.stdout.write("cycles\t" + cycles + "\n")

        if threshold_end:
            if threshold_start and threshold_start != threshold_end:
                sys.stdout.write("threshold\t" + threshold_start + "-" + threshold_end + "%\n")
            else:
                sys.stdout.write("threshold\t" + threshold_end + "%\n")

        return 0

    if charge_holding:
        if threshold_start and threshold_start != threshold_end:
            threshold_label = threshold_start + "-" + threshold_end + "%"
        else:
            threshold_label = threshold_end + "%"
        sys.stdout.write(
            "Battery "
            + percentage
            + "%  ·  Holding at "
            + threshold_label
            + "  ·  "
            + power_rate
            + "W / "
            + capacity
            + "Wh\n"
        )
    elif state == "charging":
        sys.stdout.write(
            "Battery "
            + percentage
            + "%  ·  "
            + time_remaining
            + " to full  ·  "
            + CHARGING_GLYPH
            + " "
            + power_rate
            + "W / "
            + capacity
            + "Wh\n"
        )
    else:
        sys.stdout.write(
            "Battery "
            + percentage
            + "%  ·  "
            + time_remaining
            + " left  ·  "
            + DISCHARGING_GLYPH
            + " "
            + power_rate
            + "W / "
            + capacity
            + "Wh\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
