#!/usr/bin/env python3
# blackarch:summary=Take a screenshot of a region, window, or the whole output
# blackarch:args=[smart|region|windows|fullscreen] [slurp|clipboard]
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-screenshot — select an area, then save or copy the capture.

Python port of the bash original. It freezes the screen with `wayfreeze`, asks
`slurp` for a geometry string, kills the freeze, and pipes `grim -g` into either
`satty` (annotate, then save to the Pictures dir) or `wl-copy`.

Preserved from the original:

  * **The `pkill slurp` short-circuit.** `pkill slurp && exit 0` runs *before*
    any mode dispatch, so a second press while `slurp` is already waiting kills
    it and exits 0. That is the "press twice to cancel" behaviour, and it is
    also why the freeze from a cancelled first run is left standing.
  * **`smart` picks the enclosing rectangle when the selection is tiny.** When
    the area is under 20 px² the click point is tested against every rectangle
    from `get_rectangles()` and the first one containing it wins — the guard
    against an accidental 2 px snapshot. The rectangles are monitor geometry
    (scaled) followed by window geometry, in that order, and the first match
    wins.
  * **`wayfreeze` is started before `slurp` and killed after.** It is a
    background child with a 0.1 s settle, killed without a signal check; the
    port reaps it so the process table does not accumulate freezes.
  * **An empty selection exits 0 silently** (`[ -z "$SELECTION" ] && exit 0`).
  * **The output directory is created when missing** — the original's
    `mkdir -p` replaced a notify-send, so a missing Pictures dir is not an error.
  * **Geometry is `x,y WxH`**, and `[[:space:]]` in the regex is the ASCII set
    `[ \t\r\n\f\v]`.

Usage: blackarch-cmd-screenshot [smart|region|windows|fullscreen] [slurp|clipboard]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

FREEZE = "wayfreeze"
SELECTOR = "slurp"
CAPTURE = "grim"
ANNOTATOR = "satty"
CLIPBOARD = "wl-copy"

# `[[ $SELECTION =~ ^([0-9]+),([0-9]+)[[:space:]]([0-9]+)x([0-9]+)$ ]]`
GEOMETRY = re.compile(r"^([0-9]+),([0-9]+)[ \t\r\n\f\v]([0-9]+)x([0-9]+)$")

# Below this area (W*H < 20) a click selects the rectangle containing it.
MIN_AREA = 20

USAGE = "Usage: blackarch-cmd-screenshot [smart|region|windows|fullscreen] [slurp|clipboard]"


def run(argv: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def hyprctl_json(request: str):
    """`hyprctl -j <request>`, parsed; None when the compositor is unreachable."""
    completed = run(["hyprctl", "-j", request])
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None


def output_dir() -> str:
    """`${BLACKARCH_SCREENSHOT_DIR:-${XDG_PICTURES_DIR:-$HOME/Pictures}}`."""
    return os.environ.get("BLACKARCH_SCREENSHOT_DIR") or os.environ.get(
        "XDG_PICTURES_DIR"
    ) or str(Path.home() / "Pictures")


def focused_workspace(monitors: list) -> int | None:
    for monitor in monitors:
        if monitor.get("focused") is True:
            workspace = monitor.get("activeWorkspace")
            if isinstance(workspace, dict):
                return workspace.get("id")
            return None
    return None


def monitor_rectangles(monitors: list, workspace_id: int) -> list[str]:
    """Monitor geometry for `workspace_id`, scaled to logical pixels.

    `.[] | select(.activeWorkspace.id == ($ws | tonumber)) | "\\(.x),\\(.y)
    \\((.width / .scale) | floor)x\\((.height / .scale) | floor)"`
    """
    rectangles: list[str] = []
    for monitor in monitors:
        active = monitor.get("activeWorkspace")
        if not isinstance(active, dict) or active.get("id") != workspace_id:
            continue
        scale = float(monitor.get("scale") or 1)
        width = float(monitor.get("width") or 0) / scale
        height = float(monitor.get("height") or 0) / scale
        rectangles.append(
            f"{monitor.get('x')},{monitor.get('y')} {int(width)}x{int(height)}"
        )
    return rectangles


def window_rectangles(clients: list, workspace_id: int) -> list[str]:
    """Window geometry for `workspace_id`: `.at[0],.at[1] .size[0]x.size[1]`."""
    rectangles: list[str] = []
    for client in clients:
        workspace = client.get("workspace")
        if not isinstance(workspace, dict) or workspace.get("id") != workspace_id:
            continue
        at = client.get("at") or [0, 0]
        size = client.get("size") or [0, 0]
        rectangles.append(f"{at[0]},{at[1]} {size[0]}x{size[1]}")
    return rectangles


def get_rectangles(workspace_id: int) -> list[str]:
    """Monitor rectangles first, then window rectangles — the order `slurp` sees."""
    monitors = hyprctl_json("monitors") or []
    clients = hyprctl_json("clients") or []
    return monitor_rectangles(monitors, workspace_id) + window_rectangles(
        clients, workspace_id
    )


def focused_monitor_rectangle() -> str:
    """`fullscreen` geometry: the focused monitor, scaled and floored."""
    monitors = hyprctl_json("monitors") or []
    for monitor in monitors:
        if monitor.get("focused") is not True:
            continue
        scale = float(monitor.get("scale") or 1)
        width = float(monitor.get("width") or 0) / scale
        height = float(monitor.get("height") or 0) / scale
        return f"{monitor.get('x')},{monitor.get('y')} {int(width)}x{int(height)}"
    return ""


def freeze_and_select(arguments: list[str]) -> str:
    """`wayfreeze & PID=$!; sleep .1; slurp <args>; kill $PID`.

    Returns the selector's stdout, which is "" both when it was cancelled and
    when it produced nothing. `kill` is not checked: the original discards its
    status, and a freeze that already exited is not an error.
    """
    try:
        freeze = subprocess.Popen(
            [FREEZE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        freeze = None

    import time

    time.sleep(0.1)

    completed = run([SELECTOR, *arguments])
    selection = completed.stdout.decode("utf-8", "replace").strip()

    if freeze is not None:
        try:
            freeze.terminate()
            freeze.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                freeze.kill()
                freeze.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    return selection


def enclosing_rectangle(selection: str, rectangles: list[str]) -> str:
    """Replace a tiny selection with the first rectangle containing its corner.

    The click point is the selection's own top-left corner, and the comparison is
    `x >= rx && x < rx+rw && y >= ry && y < ry+rh` — half-open on the far edge.
    """
    match = GEOMETRY.match(selection)
    if not match:
        return selection

    click_x, click_y, width, height = (int(group) for group in match.groups())
    if width * height >= MIN_AREA:
        return selection

    for rectangle in rectangles:
        rect = GEOMETRY.match(rectangle)
        if not rect:
            continue
        rect_x, rect_y, rect_w, rect_h = (int(group) for group in rect.groups())
        if (
            rect_x <= click_x < rect_x + rect_w
            and rect_y <= click_y < rect_y + rect_h
        ):
            return f"{rect_x},{rect_y} {rect_w}x{rect_h}"
    return selection


def capture_and_pipe(capture_args: list[str], consumer: list[str]) -> int:
    """`grim -g <sel> - | <consumer>`, as one shell pipeline.

    `subprocess.run(..., input=...)` cannot express this: `grim` must write into
    the consumer's stdin while both are running, and buffering the whole capture
    first would defeat a streaming annotator. The pipe is wired by hand, grim's
    stdout is handed to the consumer and closed in this process so grim sees
    EPIPE rather than writing into a full buffer, and the *consumer's* exit
    status is reported — that is what bash's `$?` gives for a pipeline.
    """
    try:
        grim = subprocess.Popen(
            capture_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return 127

    try:
        consumer_process = subprocess.Popen(
            consumer,
            stdin=grim.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        grim.kill()
        grim.wait()
        return 127

    # Let the consumer own the read end before grim can get EPIPE.
    if grim.stdout is not None:
        grim.stdout.close()

    consumer_process.wait()
    grim.wait()
    return consumer_process.returncode


def annotate(selection: str, filename: str) -> int:
    """`grim -g <sel> - | satty --filename - --output-filename <f> ...`."""
    return capture_and_pipe(
        [CAPTURE, "-g", selection, "-"],
        [
            ANNOTATOR,
            "--filename",
            "-",
            "--output-filename",
            filename,
            "--early-exit",
            "--actions-on-enter",
            "save-to-clipboard",
            "--save-after-copy",
            "--copy-command",
            CLIPBOARD,
        ],
    )


def copy(selection: str) -> int:
    """`grim -g <sel> - | wl-copy`."""
    return capture_and_pipe([CAPTURE, "-g", selection, "-"], [CLIPBOARD])


def timestamp() -> str:
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    # `[[ -f ~/.config/user-dirs.dirs ]] && source ~/.config/user-dirs.dirs`
    user_dirs = Path.home() / ".config" / "user-dirs.dirs"
    if user_dirs.is_file():
        # Only XDG_*_DIR assignments matter here; anything else is skipped.
        for line in user_dirs.read_text(encoding="utf-8", errors="replace").split("\n"):
            match = re.match(r"^(XDG_[A-Z_]+_DIR)=(.*)$", line.strip())
            if not match:
                continue
            value = match.group(2).strip().strip('"')
            if value.startswith("$HOME/"):
                value = str(Path.home() / value[len("$HOME/"):])
            os.environ.setdefault(match.group(1), value)

    directory = output_dir()
    # The original's mkdir replaced a notify-send: a missing dir is not an error.
    try:
        Path(directory).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # `pkill slurp && exit 0` — a second press cancels an in-flight selection.
    try:
        already_waiting = subprocess.run(
            ["pkill", "slurp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    except OSError:
        already_waiting = False
    if already_waiting:
        return 0

    mode = argv[0] if argv else "smart"
    processing = argv[1] if len(argv) > 1 else "slurp"

    monitors = hyprctl_json("monitors") or []
    workspace_id = focused_workspace(monitors)
    if workspace_id is None:
        workspace_id = 0

    selection = ""

    if mode == "region":
        selection = freeze_and_select([])
    elif mode == "windows":
        selection = freeze_and_select(["-r"])
    elif mode == "fullscreen":
        selection = focused_monitor_rectangle()
    else:
        # `smart|*)` — anything unrecognised falls through to the smart path.
        rectangles = get_rectangles(workspace_id)
        selection = freeze_and_select([])
        if selection:
            selection = enclosing_rectangle(selection, rectangles)

    if not selection:
        return 0

    if processing == "slurp":
        return annotate(selection, f"{directory}/screenshot-{timestamp()}.png")
    return copy(selection)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
