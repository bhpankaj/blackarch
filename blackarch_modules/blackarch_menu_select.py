#!/usr/bin/env python3
# blackarch:summary=Pick one option from a menu
# blackarch:group=menu
# blackarch:name=select
# blackarch:args=prompt [option...] [-- menu args...]
# blackarch:examples=blackarch menu select Format jpg png|blackarch-menu-select Resolution 4k 1080p 720p -- --width 400
"""blackarch-menu-select — pick one option from a menu.

Python port of the bash original. An option may lead with an icon, as
"<glyph><TAB><label>", and may trail a subtext shown under the label, as
"<glyph><TAB><label><TAB><subtext>". The menu shows the glyph but never returns
it. A plain option returns the label alone; an option with a subtext returns
"<label><TAB><subtext>", so callers with same-named rows get the subtext back
as the stable key.

The menu runs as a summoned shell target: this process writes the chosen option
to a selection file and waits for the shell to create a done file. Options are
passed as a JSON array so a glyph, a space, or a newline in an option survives
transit as data.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

USAGE = "Usage: blackarch-menu-select <prompt> [option...] [-- menu args...]"

MENU_WIDTH_KEYS = ("--width",)
MENU_HEIGHT_KEYS = ("--height", "--maxheight")


def usage_exit() -> None:
    print(USAGE, file=sys.stderr)
    raise SystemExit(1)


def parse_args(argv: list[str]) -> tuple[str, list[str], dict[str, str]]:
    """Split argv into prompt, options, and the trailing menu-argument block."""
    if not argv:
        usage_exit()

    prompt = argv[0]
    index = 1
    options: list[str] = []
    menu_args: dict[str, str] = {}

    while index < len(argv):
        if argv[index] == "--":
            index += 1
            while index < len(argv):
                flag = argv[index]
                if flag in MENU_WIDTH_KEYS:
                    index += 1
                    if index >= len(argv):
                        print("blackarch-menu-select: --width requires a value",
                              file=sys.stderr)
                        raise SystemExit(1)
                    menu_args["--width"] = argv[index]
                elif flag in MENU_HEIGHT_KEYS:
                    index += 1
                    if index >= len(argv):
                        print(f"blackarch-menu-select: {flag} requires a value",
                              file=sys.stderr)
                        raise SystemExit(1)
                    menu_args["--height"] = argv[index]
                index += 1
            break
        options.append(argv[index])
        index += 1

    return prompt, options, menu_args


def read_stdin_options() -> list[str]:
    """`mapfile -t options` when no options were given on the command line."""
    if sys.stdin.isatty():
        return []
    return [line for line in sys.stdin.read().split("\n") if line != ""]


def build_payload(prompt: str, options: list[str], selection_file: str,
                  done_file: str, menu_args: dict[str, str]) -> str:
    payload = {
        "mode": "select",
        "prompt": prompt,
        "options": options,
        "selectionFile": selection_file,
        "doneFile": done_file,
    }
    if "--width" in menu_args:
        payload["width"] = int(menu_args["--width"])
    if "--height" in menu_args:
        payload["maxHeight"] = int(menu_args["--height"])
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def main(argv: list[str]) -> int:
    prompt, options, menu_args = parse_args(argv)

    if not options:
        options = read_stdin_options()
    if not options:
        usage_exit()

    selection_file = tempfile.mkstemp(prefix="blackarch-menu-select-")[1]
    done_file = tempfile.mkstemp(prefix="blackarch-menu-select-done-")[1]
    os.unlink(done_file)

    try:
        payload = build_payload(prompt, options, selection_file, done_file, menu_args)
        with open(os.devnull, "wb") as devnull:
            subprocess.run(
                ["blackarch-shell", "shell", "summon", "blackarch.menu", payload],
                stdout=devnull, stderr=devnull, check=False,
            )

        while not os.path.exists(done_file):
            time.sleep(0.05)

        if os.path.getsize(selection_file) > 0:
            with open(selection_file, encoding="utf-8", errors="replace") as handle:
                sys.stdout.write(handle.read())
            return 0
        return 1
    finally:
        for path in (selection_file, done_file):
            try:
                os.unlink(path)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
