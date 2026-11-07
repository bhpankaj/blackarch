#!/usr/bin/env python3
# blackarch:summary=Apply matugen colors from a wallpaper to the running shell
# blackarch:args=[--type TYPE] [--mode MODE] [--source-color-index N] [wallpaper]
# blackarch:examples=blackarch matugen-apply ~/wall.png
"""blackarch-matugen-apply — apply matugen colors from a wallpaper to the shell.

Python port of the bash original. Runs `matugen image … -j hex`, reads the
palette out of the JSON it prints, rewrites the current theme's colors.toml and
shell.toml, then pushes both to the running shell over `blackarch-shell`.
"""

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

USAGE = ("Usage: blackarch-matugen-apply [--type TYPE] [--mode MODE] "
         "[--source-color-index N] [wallpaper]")


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


def parse_args(argv: list[str]) -> dict:
    options = {"type": "scheme-tonal-spot", "mode": "dark",
               "source_color_index": "0", "wallpaper": ""}
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag in ("--type", "--mode", "--source-color-index"):
            options[flag.lstrip("-").replace("-", "_")] = argv[index + 1]
            index += 2
        elif flag in ("-h", "--help"):
            print(USAGE)
            raise SystemExit(0)
        else:
            options["wallpaper"] = flag
            index += 1
    return options


def palette_color(node) -> str:
    """A palette entry is either {"color": "..."} or a bare string."""
    if isinstance(node, dict):
        return node.get("color", "")
    return node or ""


def main(argv: list[str]) -> int:
    options = parse_args(argv)

    wallpaper = options["wallpaper"]
    if not wallpaper:
        link = Path(os.environ.get("HOME", "")) / ".local/state/blackarch/current/background"
        wallpaper = str(Path(os.path.realpath(link)))

    if not wallpaper or not Path(wallpaper).is_file():
        print("No wallpaper found", file=sys.stderr)
        return 1

    home = os.environ.get("HOME", "")
    theme_path = Path(home) / ".local/state/blackarch/current/theme"
    if not theme_path.is_dir():
        print(f"No active theme at {theme_path}", file=sys.stderr)
        return 1

    raw = run_quiet(["matugen", "image", wallpaper, "-m", options["mode"],
                     "--source-color-index", options["source_color_index"], "-j", "hex"])
    if not raw:
        print("matugen produced no output", file=sys.stderr)
        return 1

    # matugen appends "ok" after the JSON block — drop trailing garbage lines
    # before parsing, as `sed '/^ok$/d'` did.
    body = "\n".join(line for line in raw.splitlines() if line.strip() != "ok")
    try:
        data = json.loads(body)
    except ValueError:
        print("matugen output was not valid JSON", file=sys.stderr)
        return 1

    palettes = data.get("palettes", {})
    dark = data.get("colors", {})

    def palette(name: str) -> str:
        return palette_color(palettes.get(name, {}).get("50"))

    accent = palette("primary")
    yellow = palette("tertiary")
    background = dark.get("background", {})
    if isinstance(background, dict):
        background = background.get("dark", {}).get("color", "") or background.get("default", {}).get("color", "")

    values = {
        "mode": options["mode"],
        "accent": accent,
        "foreground": dark.get("on_background", ""),
        "background": background,
        "selection": dark.get("primary_container", ""),
        "muted": dark.get("secondary_container", ""),
        "red": dark.get("error", ""),
        "green": accent,
        "yellow": yellow,
        "blue": accent,
        "cyan": palette("secondary"),
        "magenta": yellow,
    }

    colors_toml = theme_path / "colors.toml"
    colors_toml.write_text(
        "".join(f'{key} = "{value}"\n' for key, value in values.items()),
        encoding="utf-8")

    # Also update the user-level shell.toml [bar] section so bar fg/bg track
    # the new palette. `sed -i 's/^text\s*=.*/…/'` rewrites the first match.
    shell_toml = theme_path / "shell.toml"
    shell_b64 = ""
    if shell_toml.is_file():
        text = shell_toml.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^text\s*=.*$", f'text = "{accent}"', text, count=1)
        text = re.sub(r"(?m)^background\s*=.*$",
                      f'background = "{background}"', text, count=1)
        shell_toml.write_text(text, encoding="utf-8")
        shell_b64 = base64.b64encode(shell_toml.read_bytes()).decode("ascii")

    colors_b64 = base64.b64encode(colors_toml.read_bytes()).decode("ascii")

    subprocess.run(["blackarch-shell", "-q", "shell", "applyTheme",
                    colors_b64, shell_b64],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    print(f"Applied: {accent} on {background}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
