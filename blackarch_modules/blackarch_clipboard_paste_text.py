#!/usr/bin/env python3
# blackarch:summary=Copy text to the clipboard and type or paste it
# blackarch:args=[--shift-insert] [--copy-only] [--history-index <index>|<text>]
# blackarch:examples=blackarch clipboard paste text "hello" | blackarch clipboard paste text --shift-insert "hello"
# blackarch:hidden=true
"""blackarch-clipboard-paste-text — put a history entry or literal text on the clipboard.

Python port of the bash original. The blackarch.clipboard plugin calls it when a
row is activated: the entry goes back onto the Wayland clipboard, then the text is
either typed into the focused window or delivered as a synthesised Shift+Insert.

A history entry that is not a text entry exits 0 silently, as the original does.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PASTE_DELAY = 0.15


def history_path() -> Path:
    """The clipboard history file, honouring XDG_STATE_HOME like capture.sh."""
    state = os.environ.get("XDG_STATE_HOME")
    if not state:
        state = str(Path.home() / ".local" / "state")
    return Path(state) / "blackarch" / "clipboard-history.json"


def load_text_entry(index: int) -> str | None:
    """Return history[index].text for a text entry, or None when it is not one."""
    try:
        raw = history_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    try:
        parsed = json.loads(raw)
    except ValueError:
        return None

    if not isinstance(parsed, list) or index < 0 or index >= len(parsed):
        return None

    entry = parsed[index]
    if not isinstance(entry, dict) or entry.get("type") != "text":
        return None

    text = entry.get("text")
    return text if isinstance(text, str) else None


def wl_copy(text: str) -> bool:
    """Feed text to wl-copy; False when wl-copy is unavailable."""
    exe = shutil.which("wl-copy")
    if not exe:
        print("wl-copy not found on PATH", file=sys.stderr)
        return False
    subprocess.run([exe], input=text.encode("utf-8"), check=False)
    return True


def wtype(argv: list[str]) -> None:
    """Run wtype, or report plainly that the paste step cannot be delivered."""
    exe = shutil.which("wtype")
    if not exe:
        # The entry is already on the clipboard at this point, so say so rather
        # than failing silently the way `wtype ... || true` did.
        print(
            "wtype not found on PATH: entry copied but not typed "
            "(install wtype or ydotool to paste into the focused window)",
            file=sys.stderr,
        )
        return
    subprocess.run([exe, *argv], check=False)


def main(argv: list[str]) -> int:
    use_shift_insert = False
    copy_only = False
    history_index: str | None = None
    text = ""

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--shift-insert":
            use_shift_insert = True
            index += 1
        elif arg == "--copy-only":
            copy_only = True
            index += 1
        elif arg == "--history-index":
            history_index = argv[index + 1] if index + 1 < len(argv) else ""
            index += 2
        else:
            break

    if history_index is not None:
        if not history_index.isdigit():
            return 0
        text = load_text_entry(int(history_index))
        if text is None:
            return 0
    else:
        text = argv[index] if index < len(argv) else ""
        if not text:
            return 0

    if not wl_copy(text):
        return 1

    if copy_only:
        return 0

    # A history entry is already on the clipboard, so deliver it as a paste
    # rather than retyping the whole (possibly very large) string.
    if history_index is not None:
        use_shift_insert = True

    time.sleep(PASTE_DELAY)

    if use_shift_insert:
        wtype(["-M", "shift", "-k", "Insert", "-m", "shift"])
    else:
        wtype([text])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
