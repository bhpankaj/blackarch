#!/usr/bin/env python3
# blackarch:summary=Record the screen, with optional audio and webcam overlay
# blackarch:args=[--with-desktop-audio] [--with-microphone-audio] [--with-webcam] [--stop-recording]
# blackarch:group=cmd
# blackarch:hidden=true
"""blackarch-cmd-screenrecord — start or stop a screen recording.

Python port of the bash original. It wraps `wf-recorder`, optionally raising an
`ffplay` webcam overlay, and drives the waybar recording indicator.

Preserved from the original:

  * **`--stop-recording` with nothing running exits 1.** The final `else` arm is
    reached only when no recording is active *and* the flag was passed, so the
    caller gets a failure it can act on.
  * **A webcam-only session is torn down separately.** When `WebcamOverlay` is
    running but `wf-recorder` is not, the original calls `cleanup_webcam` alone
    rather than stopping a recording that does not exist.
  * **`SIGINT` is required to stop cleanly.** `pkill -SIGINT -f "^wf-recorder"`
    is followed by up to 5 s of polling at 0.1 s intervals; only then does
    `pkill -9` run, and the failure notification is a *critical* 5 s message
    warning that the video may be corrupted.
  * **`^wf-recorder` is an anchored match on the full command line** (`-f`), so
    a process merely mentioning wf-recorder is never signalled. `WebcamOverlay`
    is matched unanchored, because the original's ffplay invocation carries it
    as the `-window_title` value.
  * **`toggle_screenrecording_indicator` is `pkill -RTMIN+8 waybar`** — a
    real-time signal, not a signal that kills, so a waybar that is not running
    costs nothing.
  * **The webcam overlay is sized from the focused monitor's scale.** The target
    width is `round(360 * scale)`, the resolution list is tried in order
    against `v4l2-ctl --list-formats-ext -d /dev/video0`, and `ffplay` is
    started in the foreground of a backgrounded shell — the port spawns it and
    lets it run.
  * **`wf-recorder` is started without a `&` in the original**, so the script
    blocks until it exits. The port reproduces that by waiting.

Usage: blackarch-cmd-screenrecord [--with-desktop-audio] [--with-microphone-audio]
                                  [--with-webcam] [--stop-recording]
"""

from __future__ import annotations

import datetime
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

RECORDER = "wf-recorder"
PLAYER = "ffplay"
INDICATOR = "waybar"

# The original's two `-f` patterns, verbatim.
RECORDER_PATTERN = re.compile(r"^wf-recorder")
OVERLAY_PATTERN = re.compile(r"WebcamOverlay")

PREFERRED_RESOLUTIONS = ("640x360", "1280x720", "1920x1080")
BASE_WEBCAM_WIDTH = 360
VIDEO_DEVICE = "/dev/video0"
FRAMERATE = 30

# `while pgrep ... && [ $count -lt 50 ]; do sleep 0.1; done`
STOP_POLL_SECONDS = 5.0
STOP_POLL_INTERVAL = 0.1

INDICATOR_SIGNAL = signal.SIGRTMIN + 8

USAGE = (
    "Usage: blackarch-cmd-screenrecord [--with-desktop-audio] "
    "[--with-microphone-audio] [--with-webcam] [--stop-recording]"
)


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def output_dir() -> str:
    return os.environ.get("BLACKARCH_SCREENRECORD_DIR") or os.environ.get(
        "XDG_VIDEOS_DIR"
    ) or str(Path.home() / "Videos")


def notify(headline: str, body: str = "", urgency: str = "normal", timeout: int = 2000) -> None:
    """`notify-send <headline> <body> -u <urgency> -t <ms>`.

    The original calls `notify-send` for these three messages; when it is absent
    the message is simply lost, which is the same outcome as the original's
    unchecked call.
    """
    argv = ["notify-send", headline]
    if body:
        argv.append(body)
    argv += ["-u", urgency, "-t", str(timeout)]
    run(argv)


def process_command_lines() -> list[str]:
    """Every process's full command line, from /proc.

    `pkill -f`/`pgrep -f` match the whole command line, which `/proc/<pid>/cmdline`
    (NUL-separated) reproduces exactly. A process that dies mid-walk is skipped.
    """
    lines: list[str] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            raw = Path(f"/proc/{entry}/cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            # A kernel thread has an empty cmdline and is never a match.
            continue
        lines.append(raw.replace(b"\0", b" ").decode("utf-8", "replace").rstrip(" "))
    return lines


def signal_matching(pattern: re.Pattern, sig: int) -> bool:
    """`pkill [-SIGINT] -f <pattern>`: signal every match, report whether any."""
    import os as _os

    matched = False
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            raw = Path(f"/proc/{entry}/cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        command = raw.replace(b"\0", b" ").decode("utf-8", "replace").rstrip(" ")
        if not pattern.search(command):
            continue
        try:
            _os.kill(int(entry), sig)
            matched = True
        except OSError:
            continue
    return matched


def any_matching(pattern: re.Pattern) -> bool:
    return any(
        pattern.search(command) for command in process_command_lines()
    )


def recording_active() -> bool:
    """`pgrep -f "^wf-recorder" || pgrep -f "WebcamOverlay"`."""
    return any_matching(RECORDER_PATTERN) or any_matching(OVERLAY_PATTERN)


def overlay_active() -> bool:
    return any_matching(OVERLAY_PATTERN)


def toggle_indicator() -> None:
    """`pkill -RTMIN+8 waybar` — a custom signal, so waybar is not killed."""
    signal_matching(re.compile(r"^waybar"), INDICATOR_SIGNAL)


def cleanup_webcam() -> None:
    """`pkill -f "WebcamOverlay"`; the original discards a missing match."""
    signal_matching(OVERLAY_PATTERN, signal.SIGTERM)


def focused_scale() -> float:
    """`.[] | select(.focused == true) | .scale`, defaulting to 1.0."""
    completed = run(["hyprctl", "monitors", "-j"])
    if completed.returncode != 0:
        return 1.0
    try:
        monitors = json.loads(completed.stdout.decode("utf-8", "replace"))
    except ValueError:
        return 1.0
    for monitor in monitors if isinstance(monitors, list) else []:
        if monitor.get("focused") is True:
            try:
                return float(monitor.get("scale") or 1.0)
            except (TypeError, ValueError):
                return 1.0
    return 1.0


def video_size_argument() -> str:
    """`-video_size <resolution>` for the first size the device advertises.

    `v4l2-ctl --list-formats-ext -d /dev/video0` is grepped for each candidate;
    when the device is absent or lists nothing, no argument is passed and ffplay
    falls back to its own negotiation.
    """
    completed = run(["v4l2-ctl", "--list-formats-ext", "-d", VIDEO_DEVICE])
    if completed.returncode != 0:
        return ""
    available = completed.stdout.decode("utf-8", "replace")
    for resolution in PREFERRED_RESOLUTIONS:
        if resolution in available:
            return f"-video_size {resolution}"
    return ""


def start_webcam_overlay() -> None:
    """Kill any previous overlay, then raise `ffplay` on the focused monitor.

    The target width is `awk "BEGIN {printf \\"%.0f\\", 360 * $scale}"`, which is
    round-half-to-even on the exact double — `round()` in Python is the same
    IEEE operation, so 360 * 1.5 -> 540 on both sides.
    """
    cleanup_webcam()

    scale = focused_scale()
    target_width = round(BASE_WEBCAM_WIDTH * scale)
    video_size = video_size_argument()

    argv = [PLAYER, "-f", "v4l2"]
    if video_size:
        argv += video_size.split()
    argv += [
        "-framerate",
        str(FRAMERATE),
        VIDEO_DEVICE,
        "-vf",
        f"scale={target_width}:-1",
        "-window_title",
        "WebcamOverlay",
        "-noborder",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-loglevel",
        "quiet",
    ]

    # `&` in the original: the overlay outlives the script and is never reaped
    # by it. `start_new_session` detaches it from this process group so a later
    # signal to the recording session cannot take the overlay with it.
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return

    time.sleep(1)


def start_screenrecording(
    desktop_audio: bool, microphone_audio: bool
) -> subprocess.CompletedProcess:
    """`wf-recorder -f <file>`, with the audio args the original computes.

    The original builds `-a <devices>` and appends it after the filename, but the
    active line in the original is `wf-recorder -f "$filename"` with the audio
    arguments left unused (the `portal` variant is commented out). The port
    reproduces the reached call, and keeps the device merge in a comment because
    it documents intent, not behaviour.
    """
    filename = (
        f"{output_dir()}/screenrecording-"
        f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.mp4"
    )

    # The original's audio plumbing, for reference:
    #   audio_devices = "default_output" [| "default_input"]
    #   audio_args = ["-a", audio_devices]
    # It is not on the reached command line, so it is not passed.
    completed = run([RECORDER, "-f", filename])
    toggle_indicator()
    return completed


def stop_screenrecording() -> int:
    """`pkill -SIGINT`, wait up to 5 s, then `pkill -9` and warn."""
    signal_matching(RECORDER_PATTERN, signal.SIGINT)

    deadline = time.monotonic() + STOP_POLL_SECONDS
    while any_matching(RECORDER_PATTERN) and time.monotonic() < deadline:
        time.sleep(STOP_POLL_INTERVAL)

    if any_matching(RECORDER_PATTERN):
        signal_matching(RECORDER_PATTERN, signal.SIGKILL)
        cleanup_webcam()
        notify(
            "Screen recording error",
            "Recording process had to be force-killed. Video may be corrupted.",
            urgency="critical",
            timeout=5000,
        )
    else:
        cleanup_webcam()
        notify(
            "Screen recording saved to " + output_dir(),
            urgency="normal",
            timeout=2000,
        )

    toggle_indicator()
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    desktop_audio = False
    microphone_audio = False
    webcam = False
    stop_recording = False

    for argument in argv:
        if argument == "--with-desktop-audio":
            desktop_audio = True
        elif argument == "--with-microphone-audio":
            microphone_audio = True
        elif argument == "--with-webcam":
            webcam = True
        elif argument == "--stop-recording":
            stop_recording = True

    directory = output_dir()
    if not Path(directory).is_dir():
        notify(
            f"Screen recording directory does not exist: {directory}",
            urgency="critical",
            timeout=3000,
        )
        return 1

    active = recording_active()
    if active:
        if overlay_active() and not any_matching(RECORDER_PATTERN):
            # Webcam overlay only: tear it down, leave nothing else running.
            cleanup_webcam()
            return 0
        return stop_screenrecording()

    if not stop_recording:
        if webcam:
            start_webcam_overlay()
        completed = start_screenrecording(desktop_audio, microphone_audio)
        if completed.returncode != 0:
            cleanup_webcam()
        return 0 if completed.returncode == 0 else 1

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
