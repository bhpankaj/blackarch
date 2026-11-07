#!/usr/bin/env python3
# blackarch:summary=Print CPU and memory stats for the shell
# blackarch:group=system
# blackarch:args=[--bar-widget]
"""blackarch-system-stats — CPU and memory stats for the shell.

Python port of the bash original, which read /proc/stat, /proc/meminfo and
/proc/loadavg through awk and used `top -bn1` for the instantaneous CPU
percentage. Same three output shapes: `key\tvalue` for --bar-widget, and the
human-readable `cpu\tNN%` / `memory\tX.XGB / YGB` pair otherwise.
"""

import re
import subprocess
import sys

USAGE = "Usage: blackarch-system-stats [--bar-widget]"


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def meminfo_values(text: str):
    """awk '/^MemTotal:/ { total = $2 } /^MemAvailable:/ { avail = $2 }'."""
    total = 0
    avail = 0
    for line in text.split("\n"):
        if line.startswith("MemTotal:"):
            total = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1])
    return total, avail


def bar_widget_stats() -> None:
    # awk NR == 1 { idle = $5; total = 0; for (i = 2; i <= NF; i++) total += $i }
    first = read("/proc/stat").split("\n", 1)[0].split()
    idle = first[4]
    total = sum(int(x) for x in first[1:])
    print("cpu\t%s\t%s" % (idle, total))

    # awk '/^MemTotal:/ ... END { printf "memory\t%.2f\n", ((total-avail)/total)*100 }'
    mem_total, mem_avail = meminfo_values(read("/proc/meminfo"))
    if mem_total > 0:
        print("memory\t%.2f" % (((mem_total - mem_avail) / mem_total) * 100))

    # awk '{ print "load\t" $1 }' /proc/loadavg
    print("load\t" + read("/proc/loadavg").split()[0])


def cpu_percent() -> str:
    """top -bn1 | awk '/^%?Cpu/ { gsub(/,/,""); ... printf "%.0f%%", 100-$i }'."""
    try:
        proc = subprocess.run(["top", "-bn1"], stdout=subprocess.PIPE)
    except OSError:
        print("top: command not found", file=sys.stderr)
        return ""
    for line in proc.stdout.decode("utf-8", errors="replace").split("\n"):
        if not re.match(r"^%?Cpu", line):
            continue
        fields = line.replace(",", "").split()
        # for (i = 1; i <= NF; i++) if ($(i + 1) == "id") { ...; exit }
        for i in range(len(fields) - 1):
            if fields[i + 1] == "id":
                return "%.0f%%" % (100 - float(fields[i]))
    return ""


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--bar-widget":
        bar_widget_stats()
        return 0
    if arg != "":
        print(USAGE, file=sys.stderr)
        return 1

    cpu = cpu_percent()
    total, avail = meminfo_values(read("/proc/meminfo"))
    used = total - avail
    print("cpu\t%s" % cpu)
    print("memory\t%.1fGB / %.0fGB" % (used / 1024 / 1024, total / 1024 / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
