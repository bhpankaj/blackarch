#!/usr/bin/env python3
# blackarch:summary=Print monitor panel state for the shell
# blackarch:group=monitor
"""blackarch-monitor-state — print monitor panel state for the shell.

Standalone Python replacement for the bash `blackarch-monitor-state`. It
writes the eight newline-separated fields the monitor panel reads:

  0  focused monitor brightness, or "" when there is none
  1  first internal monitor (eDP/LVDS/DSI) name
  2  first external monitor name
  3  first enabled internal monitor name
  4  mirror target, when any monitor mirrors another
  5  focused monitor name
  6  focused monitor scale
  7  compact JSON for Model.parseDisplays: [{name, enabled, focused, width, height}]

Hyprland is still queried with `hyprctl`, and brightness/scaling stay external
commands, but the jq filters are implemented here, so no jq, awk or sed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

INTERNAL_NAME = re.compile(r"^(eDP|LVDS|DSI)-")

# `jq` reading empty input produces no results at all, which is not the same
# thing as a result of null, so the two cases have to be told apart.
EMPTY = object()


class RawNumber(str):
    """A JSON number kept in the exact form jq 1.8 (decNumber) prints it."""


def _number(text: str) -> RawNumber:
    return RawNumber(text)


def loads(text: str):
    """json.loads that keeps number literals verbatim."""
    return json.loads(text, parse_int=_number, parse_float=_number)


# ── jq number formatting (decNumber to-scientific-string) ────────────────────
def _plain(digits: str, exponent: int) -> str:
    if exponent == 0:
        return digits
    point = len(digits) + exponent
    if point <= 0:
        return "0." + "0" * -point + digits
    return digits[:point] + "." + digits[point:]


def _scientific(digits: str, adjusted: int) -> str:
    head, rest = digits[0], digits[1:]
    mantissa = head + ("." + rest if rest else "")
    return mantissa + "E" + ("+" if adjusted >= 0 else "-") + str(abs(adjusted))


def decnumber_str(literal: str) -> str:
    """Render a JSON number literal the way jq 1.8 does."""
    text = literal.strip()
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    elif text.startswith("+"):
        text = text[1:]

    if "e" in text or "E" in text:
        index = text.find("e") if "e" in text else text.find("E")
        mantissa, exponent = text[:index], int(text[index + 1:])
    else:
        mantissa, exponent = text, 0

    int_part, _, frac_part = mantissa.partition(".")
    digits = int_part + frac_part
    exponent -= len(frac_part)

    stripped = digits.lstrip("0")
    coefficient_digits = stripped or "0"
    adjusted = exponent + len(coefficient_digits) - 1

    if exponent <= 0 and adjusted >= -6:
        return sign + _plain(coefficient_digits, exponent)
    return sign + _scientific(coefficient_digits, adjusted)


def jq_dumps(value) -> str:
    """jq -c: compact separators, raw non-ASCII, decNumber numbers."""
    if isinstance(value, RawNumber):
        return decnumber_str(str(value))
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(jq_dumps(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + jq_dumps(item)
            for key, item in value.items()
        ) + "}"
    return json.dumps(value, ensure_ascii=False)


def jq_load(text: str):
    """`printf '%s\\n' "$text" | jq .` → (rc, data, error message or None)."""
    if text.strip() == "":
        return 0, EMPTY, None
    try:
        return 0, loads(text), None
    except ValueError as exc:
        return 5, None, f"jq: parse error: {exc}\n"


def jq_iterate_error(data) -> str:
    if data is None:
        described = "null (null)"
    elif isinstance(data, bool):
        described = f"boolean ({str(data).lower()})"
    elif isinstance(data, (int, float, RawNumber)):
        described = f"number ({data})"
    elif isinstance(data, str):
        described = f"string ({json.dumps(data)})"
    else:
        described = "value"
    return f"jq: error (at <stdin>:0): Cannot iterate over {described}\n"


def monitors_of(data):
    """jq's `.[]`: arrays iterate, objects yield their values."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return None


# ── the jq filters ───────────────────────────────────────────────────────────
def _name_of(monitor: dict) -> str:
    name = monitor.get("name")
    if name is None or name is False:
        return ""
    return name


def _is_internal(monitor: dict) -> bool:
    name = monitor.get("name")
    return isinstance(name, str) and INTERNAL_NAME.search(name) is not None


def jq_focused(text: str):
    """`[.[] | select(.focused == true)][0].name // ""`."""
    rc, data, error = jq_load(text)
    if error:
        sys.stderr.write(error)
    if data is EMPTY or data is None:
        return rc, ""
    monitors = monitors_of(data)
    if monitors is None:
        sys.stderr.write(jq_iterate_error(data))
        return 5, ""
    for monitor in monitors:
        if isinstance(monitor, dict) and monitor.get("focused") is True:
            return rc, _name_of(monitor)
    return rc, ""


def jq_monitor_fields(text: str):
    """The four comma-separated jq values: internal, external, enabled, mirror."""
    rc, data, error = jq_load(text)
    if error:
        sys.stderr.write(error)
    if data is EMPTY or data is None:
        return rc, None
    monitors = monitors_of(data)
    if monitors is None:
        sys.stderr.write(jq_iterate_error(data))
        return 5, None

    internal = external = enabled_internal = mirror = ""
    found_internal = found_external = found_enabled = found_mirror = False

    for monitor in monitors:
        if not isinstance(monitor, dict):
            continue
        is_internal = _is_internal(monitor)

        if not found_internal and is_internal:
            internal, found_internal = _name_of(monitor), True
        if not found_external and not is_internal:
            external, found_external = _name_of(monitor), True
        if not found_enabled and is_internal and monitor.get("disabled") is not True:
            enabled_internal, found_enabled = _name_of(monitor), True

        mirror_of = monitor.get("mirrorOf")
        if not found_mirror and not (isinstance(mirror_of, str) and mirror_of == "none"):
            value = mirror_of if is_internal else monitor.get("name")
            mirror = "" if value is None or value is False else value
            found_mirror = True

    return rc, [internal, external, enabled_internal, mirror]


def jq_displays(text: str):
    """`[.[] | {name, enabled:(.disabled != true), focused:(.focused == true), width, height}]`."""
    rc, data, error = jq_load(text)
    if error:
        sys.stderr.write(error)
    if data is EMPTY or data is None:
        return rc, None
    monitors = monitors_of(data)
    if monitors is None:
        sys.stderr.write(jq_iterate_error(data))
        return 5, None

    displays = []
    for monitor in monitors:
        if not isinstance(monitor, dict):
            sys.stderr.write(jq_iterate_error(monitor))
            return 5, None
        displays.append({
            "name": monitor.get("name"),
            "enabled": monitor.get("disabled") is not True,
            "focused": monitor.get("focused") is True,
            "width": monitor.get("width"),
            "height": monitor.get("height"),
        })
    return rc, jq_dumps(displays)


# ── process helpers ──────────────────────────────────────────────────────────
def run_stdout(args, stderr=None):
    """Run a command, returning (exit status, stdout bytes).

    `stderr=None` leaves the child's stderr attached to ours, which is what an
    unredirected bash command does.
    """
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=stderr)
    except FileNotFoundError:
        return 127, b""
    return proc.returncode, proc.stdout


def decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def main() -> int:
    # monitors_json=$(hyprctl monitors all -j)  -- command substitution strips
    # every trailing newline.
    _, raw = run_stdout(["hyprctl", "monitors", "all", "-j"])
    monitors_text = decode(raw).rstrip("\n")

    _, focused = jq_focused(monitors_text)

    # { blackarch-brightness-display --monitor "$focused_monitor" 2>/dev/null; echo; } | head -n 1
    _, brightness = run_stdout(
        ["blackarch-brightness-display", "--monitor", focused],
        stderr=subprocess.DEVNULL,
    )
    head = (decode(brightness) + "\n").split("\n", 1)[0]
    sys.stdout.write(head + "\n")

    _, fields = jq_monitor_fields(monitors_text)
    if fields is not None:
        sys.stdout.write("".join(field + "\n" for field in fields))

    sys.stdout.write(focused + "\n")

    # blackarch-hyprland-monitor-scaling 2>/dev/null || echo
    scale_rc, scale = run_stdout(
        ["blackarch-hyprland-monitor-scaling"], stderr=subprocess.DEVNULL
    )
    sys.stdout.write(decode(scale))
    if scale_rc != 0:
        sys.stdout.write("\n")

    displays_rc, displays = jq_displays(monitors_text)
    if displays is not None:
        sys.stdout.write(displays + "\n")

    return displays_rc


if __name__ == "__main__":
    sys.exit(main())
