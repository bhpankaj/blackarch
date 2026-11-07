#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# blackarch:summary=Print PulseAudio sink availability for the shell
# blackarch:group=audio
"""blackarch-audio-sink-availability: port of the bash helper.

    Print PulseAudio sink availability for the shell

    Group: audio
"""

import os
import re
import subprocess
import sys

# A speaker tuning is a virtual sink in front of the real speakers. Both exist
# in the graph, but selecting the physical one would only bypass the tuning, so
# report it unavailable and keep it out of the output list.


def fronted_sink():
    """`blackarch-audio-tuning fronted-sink`, its stdout stripped; "" if it fails."""
    try:
        p = subprocess.run(
            ["blackarch-audio-tuning", "fronted-sink"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return ""
    if p.returncode != 0:
        return ""
    return p.stdout.decode("utf-8", "replace").strip()


def emit_sink(name, port_count, available, fronted):
    """One `name<TAB>0|1` line; the fronted (tuned) sink reads unavailable."""
    if name == "":
        return
    if fronted != "" and name == fronted:
        print(name + "\t0")
        return
    print(name + "\t" + ("1" if (port_count == 0 or available) else "0"))


def main(argv):
    fronted = fronted_sink()

    try:
        p = subprocess.run(
            ["pactl", "list", "sinks"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return 0
    if p.returncode != 0:
        return 0
    text = p.stdout.decode("utf-8", "replace")

    name = ""
    in_ports = False
    port_count = 0
    available = False

    for line in text.split("\n"):
        if line.startswith("Sink #"):
            emit_sink(name, port_count, available, fronted)
            name = ""
            in_ports = False
            port_count = 0
            available = False
        elif re.match(r"^[ \t]*Name:", line):
            parts = line.split()
            name = parts[1] if len(parts) > 1 else ""
        elif re.match(r"^[ \t]*Ports:$", line):
            in_ports = True
        elif in_ports and re.match(r"^\tActive Port:", line):
            in_ports = False
        elif in_ports and re.match(r"^\t\t", line):
            port_count += 1
            if "not available" not in line:
                available = True

    emit_sink(name, port_count, available, fronted)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
