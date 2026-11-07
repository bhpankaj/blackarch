#!/usr/bin/env python3
# blackarch:summary=Rotate the default audio sink and show an OSD
# blackarch:args=
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-audio-switch — move the default sink to the next available one.

Python port of the bash original, which shells out to `hyprctl`, `pactl`, `jq`
and `wpctl` to build the sink list, pick the next entry, and raise a swayosd
banner. This needs none of them: the sink list is parsed from `pactl -f json`,
the focused monitor name from `hyprctl monitors -j`, and the rest is arithmetic.

Behaviour preserved from the original:

  * **Availability filter.** A sink survives when it has *no* ports at all, or
    when at least one port is not `not available`. The jq filter is
    `select((.ports | length == 0) or ([.ports[]? | .availability != "not available"] | any))`,
    so a sink with no ports is kept unconditionally.
  * **Rotation is by index, not by name.** `current_sink_index` is
    `map(.name) | index($current_sink_name)` over the *filtered* list; when the
    current sink is not in it the index is `null`, which the `[ != "null" ]` test
    treats as "not found" and rotation restarts at 0. Rotation is
    `(index + 1) % count`.
  * **The default is only set when it actually changes.** `pactl set-default-sink`
    is skipped when the next sink already is the current one.
  * **Volume icon thresholds.** muted or 0% -> `muted`; <=33 -> `low`;
    <=66 -> `medium`; else `high`. The icon name is `sink-volume-<state>-symbolic`.
  * **The description fallback is best-effort.** When `description` is `null`,
    `(null)`, or empty, the original greps `wpctl status` for the sink's
    `object.id` and takes the text after the `N.` prefix, dropping a trailing
    `[...]` block. It is a fallback: an unmatched grep yields an empty
    description, which is what swayosd is then told to show.
  * **Exit 1 with an OSD message when no sink is available.**

Usage: blackarch-cmd-audio-switch
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

OSD = "swayosd-client"

NOT_AVAILABLE = "not available"

# `sink-volume-${icon_state}-symbolic`
ICON_TEMPLATE = "sink-volume-{state}-symbolic"

# The original's `[ "$next_sink_description" = "(null)" ] || = "null" || -z` test.
NULL_DESCRIPTIONS = ("(null)", "null", "")

# `grep -E "\s+\*?\s+${sink_id}\."` over `wpctl status`, then two seds.
WPCTL_LINE = re.compile(r"\s+\*?\s+" + r"(\d+)" + r"\.")
WPCTL_PREFIX = re.compile(r"^.*[0-9]+\.\s+")
WPCTL_SUFFIX = re.compile(r"\s+\[.*$")

USAGE = "Usage: blackarch-cmd-audio-switch"


def run(argv: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run a command, swallowing `OSError` the way the original's empty `$(...)` does."""
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=check,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def hyprctl_monitors() -> list:
    """`hyprctl monitors -j`, or [] when the compositor is unreachable.

    jq turns an empty input into no output rather than an error, so an
    unreachable compositor yields an empty list, never a crash.
    """
    completed = run(["hyprctl", "monitors", "-j"])
    if completed.returncode != 0:
        return []
    try:
        return json.loads(completed.stdout.decode("utf-8", "replace"))
    except ValueError:
        return []


def focused_monitor(monitors: list) -> str:
    """`.[] | select(.focused == true).name`."""
    for monitor in monitors:
        if monitor.get("focused") is True:
            return str(monitor.get("name") or "")
    return ""


def pactl_sinks() -> list:
    """`pactl -f json list sinks` -> the sink array, or [] on failure."""
    completed = run(["pactl", "-f", "json", "list", "sinks"])
    if completed.returncode != 0:
        return []
    try:
        data = json.loads(completed.stdout.decode("utf-8", "replace"))
    except ValueError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Newer pactl emits an object; the array is under `sinks`.
        sinks = data.get("sinks")
        if isinstance(sinks, list):
            return sinks
    return []


def sink_is_available(sink: dict) -> bool:
    """`(.ports | length == 0) or ([.ports[]? | .availability != "not available"] | any)`."""
    ports = sink.get("ports")
    if not isinstance(ports, list):
        return True
    if len(ports) == 0:
        return True
    return any(
        port.get("availability") != NOT_AVAILABLE
        for port in ports
        if isinstance(port, dict)
    )


def sink_names(sinks: list) -> list[str]:
    return [str(sink.get("name") or "") for sink in sinks]


def index_of(names: list[str], target: str):
    """jq's `map(.name) | index($name)`: the index, or None for jq's `null`."""
    try:
        return names.index(target)
    except ValueError:
        return None


def first_volume_percent(sink: dict) -> int:
    """`.volume | to_entries[0].value.value_percent | sub("%"; "")` as an int.

    The original pipes this into `[ "$v" -eq 0 ]` and `-le 33`, so a missing or
    non-numeric value is the shell's arithmetic error — which is fatal there
    (`set -e` is absent, so it degrades to a comparison that fails). Reading it
    as 0 is the same outcome for the icon state: `0` is muted.
    """
    volume = sink.get("volume")
    if not isinstance(volume, dict) or not volume:
        return 0
    first = next(iter(volume.values()))
    if not isinstance(first, dict):
        return 0
    text = str(first.get("value_percent") or "").replace("%", "").strip()
    try:
        return int(text)
    except ValueError:
        return 0


def wpctl_description(sink_id: str) -> str:
    """The original's wpctl fallback: match the object id, strip prefix/suffix.

    `grep -E "\\s+\\*?\\s+${sink_id}\\."` is an *unanchored, unescaped* match, so
    the id is used as a regex fragment and any line containing a match counts.
    The two seds are `s/^.*[0-9]+\\.\\s+//` (drop through the last `N. ` prefix)
    and `s/\\s+\\[.*$//` (drop a trailing `[vol: ...]` block).
    """
    completed = run(["wpctl", "status"])
    if completed.returncode != 0:
        return ""
    pattern = re.compile(r"\s+\*?\s+" + sink_id + r"\.")
    for line in completed.stdout.decode("utf-8", "replace").split("\n"):
        if not pattern.search(line):
            continue
        text = WPCTL_PREFIX.sub("", line)
        return WPCTL_SUFFIX.sub("", text)
    return ""


def volume_icon(sink: dict) -> str:
    muted = sink.get("mute") is True
    volume = first_volume_percent(sink)

    if muted or volume == 0:
        state = "muted"
    elif volume <= 33:
        state = "low"
    elif volume <= 66:
        state = "medium"
    else:
        state = "high"
    return ICON_TEMPLATE.format(state=state)


def osd(monitor: str, message: str, icon: str = "") -> None:
    argv = [OSD, "--monitor", monitor, "--custom-message", message]
    if icon:
        argv += ["--custom-icon", icon]
    run(argv)


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    monitor = focused_monitor(hyprctl_monitors())

    sinks = [sink for sink in pactl_sinks() if sink_is_available(sink)]
    if not sinks:
        # `exit 1` after the OSD call; the original's exit status is 1.
        osd(monitor, "No audio devices found")
        return 1

    names = sink_names(sinks)

    completed = run(["pactl", "get-default-sink"])
    current = ""
    if completed.returncode == 0:
        current = completed.stdout.decode("utf-8", "replace").strip()

    position = index_of(names, current)
    next_index = 0 if position is None else (position + 1) % len(sinks)

    next_sink = sinks[next_index]
    next_name = names[next_index]

    description = str(next_sink.get("description") or "")
    if description in NULL_DESCRIPTIONS:
        object_id = str((next_sink.get("properties") or {}).get("object.id") or "")
        description = wpctl_description(object_id) if object_id else ""

    icon = volume_icon(next_sink)

    if next_name != current:
        run(["pactl", "set-default-sink", next_name])

    osd(monitor, description, icon)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
