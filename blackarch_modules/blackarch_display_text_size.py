#!/usr/bin/env python3
# blackarch:summary=Scale text everywhere — blackarch shell, GTK apps, and terminals
# blackarch:group=display
# blackarch:args=[factor|size|reset]
# blackarch:examples=blackarch display text size | blackarch display text size 1.5 | blackarch display text size 16 | blackarch display text size reset
"""blackarch-display-text-size — one knob for apparent text size.

Python port of the bash original. It drives three settings in lockstep,
anchored to a 12px shell base:

  * the blackarch shell's font base-size — ~/.config/blackarch/shell.toml
    [font] base-size. The shell watches the file, so shell text re-flows live.
  * GNOME/GTK's text-scaling-factor — org.gnome.desktop.interface. This is
    quantized so the GTK interface font (gsettings font-name) lands on a whole
    point size; raw ratios yield fractional point sizes, and GTK4 menus clip at
    the ascenders on scale-1 monitors.
  * the terminal font point size — anchored so 12px shell base == 12pt.

Two call styles:

  factor form   1.5      — the GTK text-scaling-factor itself. Shell base-size
                           and terminal pt follow the same 12px == 1.0 anchor, so
                           1.5 -> 18px shell / 18pt terminal.
  size form     16       — a shell base-size in px (9-20), converted to a factor
                           exactly as the original did.

Because the two forms are both plain numbers, the argument decides: anything
with a fractional part (1.5, 0.75) is a factor; a bare integer is a px size.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys

MIN_PX = 9
MAX_PX = 20

# Anchors: 12px shell base == factor 1.0 == 12pt terminal font.
BASE_PX = 12
BASE_FACTOR = 1.0
DEFAULT_PX = 12
DEFAULT_PT = 12

GKEY_SCHEMA = "org.gnome.desktop.interface"
GKEY_FACTOR = "text-scaling-factor"
GKEY_FONT_NAME = "font-name"

FACTOR_MIN = 0.5
FACTOR_MAX = 3.0

SHELL_CONFIG = os.path.expanduser("~/.config/blackarch/shell.toml")

# A gsettings font-name is `Family [Style...] Size`; the size is the last
# whitespace-separated token. Fall back to the GNOME default (11) when the
# value can't be read.
QUOTED = re.compile(r"^\s*'([^']*)'\s*$|^\s*\"([^\"]*)\"\s*$")


def run(argv, check=False, capture=False):
    return subprocess.run(
        argv,
        check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.DEVNULL,
    )


def usage(stream):
    print("Usage: blackarch-display-text-size [factor|size|reset]", file=stream)
    print("  (no args)     print the current factor, shell size, and terminal size", file=stream)
    print(f"  <factor>      GTK text-scaling-factor directly ({FACTOR_MIN}-{FACTOR_MAX}); shell + terminals follow", file=stream)
    print(f"  <size>        shell base-size in px ({MIN_PX}-{MAX_PX}); converted to a factor", file=stream)
    print(f"  reset         return everything to the defaults ({DEFAULT_PX}px / {BASE_FACTOR} / {DEFAULT_PT}pt)", file=stream)


# ---- shell base-size: the rem root every shell type size derives from ----


def parse_font_section(text):
    """Return {key: value} for the [font] section of a shell.toml file.

    The shell's own TOML walker (Commons/Color.qml parseShell) accepts quoted
    strings, bare numbers and bare words, so values are kept verbatim here and
    coerced by the caller.
    """
    section = None
    found = {}
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line[1 : line.find("]")] if "]" in line else None
            continue
        if section != "font" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        found[key.strip()] = value.split("#", 1)[0].strip()
    return found


def current_base_size():
    """The base-size currently set under [font], or None when unset."""
    try:
        with open(SHELL_CONFIG, "r", encoding="utf-8", errors="replace") as handle:
            value = parse_font_section(handle.read()).get("base-size")
    except OSError:
        return None
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def write_text(path, body, trailing_newline=True):
    """Write `body` (already "\\n"-joined), ending with a newline unless told not."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
        if trailing_newline:
            handle.write("\n")


def set_base_size(size):
    """Upsert base-size under [font]; other sections and keys are untouched."""
    try:
        os.makedirs(os.path.dirname(SHELL_CONFIG), exist_ok=True)
    except OSError:
        pass

    try:
        with open(SHELL_CONFIG, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        text = ""

    # Split without inventing or losing a trailing blank line: a final "\n"
    # yields one empty element, which is dropped here and re-added below.
    lines = text.split("\n")
    trailing_newline = lines and lines[-1] == ""
    if trailing_newline:
        lines.pop()

    section = None
    done = False
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if section == "font" and not done:
                out.append(f"base-size = {size}")
                done = True
            section = stripped[1 : stripped.find("]")] if "]" in stripped else None
            out.append(line)
            continue
        if section == "font" and re.match(r"^\s*base-size\s*=", line):
            if not done:
                out.append(f"base-size = {size}")
                done = True
            continue
        out.append(line)

    if not done:
        while out and out[-1].strip() == "":
            out.pop()
        if out:
            out.append("")
        out.append("[font]")
        out.append(f"base-size = {size}")

    write_text(SHELL_CONFIG, "\n".join(out), trailing_newline or not out)


def reset_base_size():
    """Drop the base-size line, returning the shell to the theme/default size."""
    try:
        with open(SHELL_CONFIG, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return

    lines = text.split("\n")
    trailing_newline = lines and lines[-1] == ""
    if trailing_newline:
        lines.pop()

    section = None
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped[1 : stripped.find("]")] if "]" in stripped else None
        elif section == "font" and re.match(r"^\s*base-size\s*=", line):
            continue
        out.append(line)

    write_text(SHELL_CONFIG, "\n".join(out), trailing_newline or not out)


# ---- GTK text-scaling-factor ----


def gtk_font_pt():
    """Point size of the GTK interface font, used to quantize the factor."""
    proc = run(["gsettings", "get", GKEY_SCHEMA, GKEY_FONT_NAME], check=False, capture=True)
    if proc.stdout is None:
        return 11.0
    raw = proc.stdout.decode("utf-8", "replace").strip()
    match = QUOTED.match(raw)
    if not match:
        return 11.0
    name = match.group(1) or match.group(2) or ""
    parts = name.split()
    if not parts:
        return 11.0
    try:
        return float(parts[-1])
    except ValueError:
        return 11.0


def factor_for_size(px, font_pt=None):
    """px base-size -> factor, quantized so the interface font is whole points."""
    pt = gtk_font_pt() if font_pt is None else font_pt
    return round(round(pt * px / BASE_PX) / pt, 4)


def size_for_factor(factor):
    """factor -> shell base-size in px (the inverse of factor_for_size)."""
    return max(MIN_PX, min(MAX_PX, int(round(factor * BASE_PX))))


def read_factor():
    proc = run(["gsettings", "get", GKEY_SCHEMA, GKEY_FACTOR], check=False, capture=True)
    if proc.stdout is None:
        return None
    try:
        return float(proc.stdout.decode("utf-8", "replace").strip())
    except ValueError:
        return None


def set_factor(factor):
    run(["gsettings", "set", GKEY_SCHEMA, GKEY_FACTOR, str(factor)], check=False)


def reset_factor():
    run(["gsettings", "reset", GKEY_SCHEMA, GKEY_FACTOR], check=False)


# ---- terminal font point size ----


def term_pt_for(px):
    return int(round(px * DEFAULT_PT / BASE_PX))


def set_terminal_size(pt):
    """Set the font point size in terminal configs, creating kitty overrides
    when it inherits its size from the system config. Family is untouched —
    that is blackarch-font-set's job. Live-reload signals mirror
    blackarch-font-set; foot has no reload signal, so running instances are
    nudged with a notification."""
    home = os.path.expanduser("~")

    alacritty = os.path.join(home, ".config", "alacritty", "alacritty.toml")
    if os.path.isfile(alacritty):
        rewrite_setting(alacritty, r"^size\s*=", f"size = {pt}")

    kitty_conf = os.path.join(home, ".config", "kitty", "kitty.conf")
    if os.path.isfile(kitty_conf) or command_present("kitty"):
        os.makedirs(os.path.dirname(kitty_conf), exist_ok=True)
        rewrite_setting(kitty_conf, r"^\s*font_size\s+", f"font_size {pt}.0")
        signal_process("kitty", "USR1")

    ghostty = os.path.join(home, ".config", "ghostty", "config")
    if os.path.isfile(ghostty):
        rewrite_setting(ghostty, r"^font-size\s*=", f"font-size = {pt}")
        signal_process("ghostty", "USR2")

    foot_ini = os.path.join(home, ".config", "foot", "foot.ini")
    if os.path.isfile(foot_ini):
        rewrite_foot_size(foot_ini, pt)
        if process_running("foot"):
            notify_foot()


def rewrite_setting(path, key_pattern, new_value):
    """Set `key = new_value` (or `key new_value` for kitty) in place.

    `key_pattern` matches the line's key as it appears in that file, including
    its separator. A key that is absent is appended at the end of the file, so a
    terminal that inherits its size from the system config gets an override.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return

    lines = text.split("\n")
    trailing_newline = lines and lines[-1] == ""
    if trailing_newline:
        lines.pop()

    regex = re.compile(key_pattern)
    out = []
    replaced = False
    for line in lines:
        if regex.match(line):
            if not replaced:
                out.append(new_value)
                replaced = True
            continue
        out.append(line)

    if not replaced:
        while out and out[-1].strip() == "":
            out.pop()
        if out:
            out.append("")
        out.append(new_value)

    write_text(path, "\n".join(out), trailing_newline or not out)


def rewrite_foot_size(path, pt):
    """foot keeps its size inline in the font= value: font=Mono:size=10."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return

    updated = re.sub(r"(:size=)[0-9.]+", rf"\g<1>{pt}", text)
    if updated != text:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(updated)
        return

    # No font= line to edit: fall back to a standalone :size key.
    rewrite_setting(path, r"^\s*:size\s*=", f":size={pt}")


def term_current_pt():
    """Report the current terminal point size from whichever config we find."""
    home = os.path.expanduser("~")

    ghostty = os.path.join(home, ".config", "ghostty", "config")
    if os.path.isfile(ghostty):
        value = grep_first(ghostty, r"^font-size\s*=\s*([0-9.]+)")
        if value:
            return value

    alacritty = os.path.join(home, ".config", "alacritty", "alacritty.toml")
    if os.path.isfile(alacritty):
        value = grep_first(alacritty, r"^size\s*=\s*([0-9.]+)")
        if value:
            return value

    kitty_conf = os.path.join(home, ".config", "kitty", "kitty.conf")
    if os.path.isfile(kitty_conf):
        value = grep_first(kitty_conf, r"^\s*font_size\s+([0-9.]+)")
        return value or str(DEFAULT_PT)

    foot_ini = os.path.join(home, ".config", "foot", "foot.ini")
    if os.path.isfile(foot_ini):
        value = grep_first(foot_ini, r":size=([0-9.]+)")
        if value:
            return value

    if command_present("kitty"):
        return str(DEFAULT_PT)
    return ""


def grep_first(path, pattern):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = re.search(pattern, line)
                if match:
                    return match.group(1)
    except OSError:
        pass
    return ""


def command_present(name):
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if os.access(os.path.join(directory, name), os.X_OK):
            return True
    return False


def process_running(name):
    proc = subprocess.run(
        ["pgrep", "-x", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return proc.returncode == 0


def signal_process(name, signal_name):
    """pkill's -<name> form takes a bare signal name (USR1, not -USR1)."""
    try:
        subprocess.run(
            ["pkill", f"-{signal_name}", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def notify_foot():
    """Nudge the user that foot needs a restart, reusing one notification id
    (freedesktop replaces_id) so dragging through several sizes refreshes a
    single toast instead of stacking a pile."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    id_file = os.path.join(runtime_dir, "blackarch-display-text-size.foot-notif-id")
    previous = ""
    try:
        with open(id_file, "r", encoding="utf-8") as handle:
            previous = handle.readline().strip()
    except OSError:
        previous = ""

    argv = ["blackarch-notification-send", "Restart Foot to apply the new terminal font size"]
    if previous.isdigit():
        argv += ["-r", previous]
    argv += ["-p"]

    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        new_id = proc.stdout.decode("utf-8", "replace").strip()
    except OSError:
        new_id = ""
    if new_id.isdigit():
        try:
            with open(id_file, "w", encoding="utf-8") as handle:
                handle.write(new_id + "\n")
        except OSError:
            pass


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        usage(sys.stdout)
        return 0

    argument = argv[0]

    if argument in ("reset", "default"):
        reset_base_size()
        reset_factor()
        set_terminal_size(DEFAULT_PT)
        return 0

    if not re.match(r"^[0-9]+(\.[0-9]+)?$", argument):
        print("Size must be a number between 0.5 and 3.0.", file=sys.stderr)
        usage(sys.stderr)
        return 1

    value = float(argument)
    if "." in argument:
        factor = round(max(FACTOR_MIN, min(FACTOR_MAX, value)), 4)
        px = size_for_factor(factor)
    elif MIN_PX <= value <= MAX_PX:
        px = int(value)
        factor = factor_for_size(px)
    elif FACTOR_MIN <= value <= FACTOR_MAX:
        # An integer outside the px range still names a factor: 2 is 2.0, not 2px.
        factor = round(float(value), 4)
        px = size_for_factor(factor)
    else:
        print(f"Size must be between {MIN_PX} and {MAX_PX} (px), or a factor 0.5-3.0.", file=sys.stderr)
        usage(sys.stderr)
        return 1

    set_base_size(px)
    set_factor(factor)
    set_terminal_size(term_pt_for(px))
    return 0


def show_status():
    base = current_base_size()
    factor = read_factor()
    term = term_current_pt()
    print(f"text size: {base if base is not None else str(DEFAULT_PX) + ' (default)'} px")
    print(f"gtk text-scaling-factor: {factor if factor is not None else 'n/a'}")
    print(f"terminal font: {term if term else 'n/a'} pt")


def main_entry(argv):
    if not argv:
        show_status()
        return 0
    return main(argv)


if __name__ == "__main__":
    sys.exit(main_entry(sys.argv[1:]))
