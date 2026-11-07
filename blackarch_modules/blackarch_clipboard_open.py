#!/usr/bin/env python3
# blackarch:summary=Open a clipboard history entry
# blackarch:args=--history-index <index>
# blackarch:hidden=true
"""blackarch-clipboard-open — open one clipboard history entry.

Python port of the bash original. Image entries go to the image editor; text
entries go to the browser when they hold a URL (or a bare domain), otherwise to
the editor in a temp file. Invoked by the blackarch.clipboard plugin with Alt+Enter.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

USAGE = "Usage: blackarch-clipboard-open --history-index <index>"

URL_RE = re.compile(r"https?://[^\s\"'<>]+")
DOMAIN_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9.\-]+\.[A-Za-z]{2,})(/[^\s]*)?\s*$")


def history_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME")
    if not state:
        state = str(Path.home() / ".local" / "state")
    return Path(state) / "blackarch" / "clipboard-history.json"


def load_entry(index: int) -> dict | None:
    """Return history[index] as a dict, or None when it is missing/invalid."""
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
    return entry if isinstance(entry, dict) else None


def run_or_report(argv: list[str]) -> int:
    """Run argv[0], naming it when it is not on PATH."""
    if not shutil.which(argv[0]):
        print(f"{argv[0]} not found on PATH", file=sys.stderr)
        return 1
    return subprocess.run(argv, check=False).returncode


def open_image(path: str) -> int:
    if not os.access(path, os.R_OK):
        return 1
    return run_or_report(["tensaku-edit", path])


def open_text(text: str) -> int:
    match = URL_RE.search(text)
    if match:
        url = match.group(0)
    else:
        domain = DOMAIN_RE.match(text)
        if not domain:
            url = ""
        else:
            url = "https://" + domain.group(1) + (domain.group(2) or "")

    if url:
        return run_or_report(["blackarch-launch-browser", url])

    open_dir = Path(
        os.environ.get("XDG_STATE_HOME")
        or str(Path.home() / ".local" / "state")
    ) / "blackarch" / "clipboard-open"
    open_dir.mkdir(parents=True, exist_ok=True)

    handle, name = tempfile.mkstemp(dir=open_dir, suffix=".txt", prefix="clipboard.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        return run_or_report(["blackarch-launch-editor", name])
    except OSError:
        print(f"could not write {name}", file=sys.stderr)
        return 1


def main(argv: list[str]) -> int:
    history_index = ""

    index = 0
    while index < len(argv):
        if argv[index] == "--history-index":
            history_index = argv[index + 1] if index + 1 < len(argv) else ""
            index += 2
        else:
            print(USAGE, file=sys.stderr)
            return 1

    if not history_index.isdigit():
        return 1

    entry = load_entry(int(history_index))
    if entry is None:
        return 1

    entry_type = entry.get("type")
    if entry_type == "image":
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            return 1
        return open_image(path)

    if entry_type == "text":
        text = entry.get("text")
        if not isinstance(text, str):
            return 1
        return open_text(text)

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
