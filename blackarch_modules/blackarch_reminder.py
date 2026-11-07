#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# blackarch:summary=Set and show lightweight desktop notification reminders
# blackarch:args=[-i|--interactive] | <minutes> [message] | show [-j|--json] | clear
# blackarch:examples=blackarch reminder -i | blackarch reminder 5 | blackarch reminder 30 "Check the oven" | blackarch reminder show | blackarch reminder show --json | blackarch reminder clear
"""blackarch-reminder: port of the bash helper.

    Set and show lightweight desktop notification reminders

    Args: [-i|--interactive] | <minutes> [message] | show [-j|--json] | clear
    Examples: blackarch reminder -i | blackarch reminder 5 | blackarch reminder 30 "Check the oven" | blackarch reminder show | blackarch reminder show --json | blackarch reminder clear
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Reminder state lives in ${XDG_RUNTIME_DIR:-/tmp}/blackarch-reminders as
# <unit>.message files, next to the systemd --user timers of the same unit names.
REMINDER_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "blackarch-reminders")
TIMER_GLOB = "blackarch-reminder-*.timer"
ICON = "\U000f088c"


def run(argv, check=True, capture=False):
    """Run a command; returns CompletedProcess or None if it could not start."""
    kwargs = {"check": check}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.DEVNULL
    try:
        return subprocess.run(argv, **kwargs)
    except OSError:
        return None


def run_capture(argv):
    """stdout of a command as text with trailing whitespace stripped (like $(...))."""
    p = run(argv, check=False, capture=True)
    if p is None or p.returncode != 0:
        return ""
    return p.stdout.decode("utf-8", "replace").strip()


def format_remaining(seconds):
    minutes, remainder = divmod(seconds, 60)
    if minutes > 0 and remainder > 0:
        return "%dm %ds" % (minutes, remainder)
    if minutes > 0:
        return "%dm" % minutes
    return "%ds" % remainder


def active_reminder_timers(now=None):
    """`systemctl --user list-timers` entries for reminder timers that have not fired.

    Yields (timer, next_ms) pairs. systemd reports the next elapse in microseconds
    since the epoch; the bash version divides by 1e6 for a whole second.
    """
    if now is None:
        now = int(datetime.now().timestamp())
    text = run_capture(
        [
            "systemctl",
            "--user",
            "list-timers",
            "--all",
            "--output=json",
            TIMER_GLOB,
        ]
    )
    if not text:
        return
    try:
        entries = json.loads(text)
    except ValueError:
        return
    for entry in entries:
        timer = entry.get("unit", "")
        nxt = entry.get("next", "")
        if not timer or not nxt:
            continue
        try:
            next_ms = int(nxt)
        except ValueError:
            continue
        if next_ms <= now * 1000000:
            continue
        yield timer, next_ms


def read_message(unit):
    """The reminder message body stored for `unit`, "" when there is none."""
    path = os.path.join(REMINDER_DIR, unit + ".message")
    try:
        with open(path, "r") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def at_time(next_ms):
    """Wall-clock HH:MM of an elapse, with no zero padding (`date +%-H:%M`)."""
    return datetime.fromtimestamp(next_ms / 1000000).strftime("%-H:%M")


def remind_at(minutes):
    """Wall-clock HH:MM `minutes` from now (`date -d "+N minutes" +%-H:%M`)."""
    delta = timedelta(minutes=minutes)
    stamp = datetime.now() + delta
    return "%d:%02d" % (stamp.hour, stamp.minute)


def refresh_indicator():
    """Ask the shell to refresh its indicators; failure is ignored."""
    run(
        ["blackarch-shell", "-q", "blackarch.indicators", "refresh"],
        check=False,
    )


def notify(title, body):
    run(["blackarch-notification-send", "-g", ICON, title, body], check=False)


def open_interactive():
    run(["blackarch-shell", "shell", "summon", "blackarch.reminders", "{}"], check=False)


def show_reminders():
    now = int(datetime.now().timestamp())
    body = ""
    for timer, next_ms in active_reminder_timers(now):
        remaining = next_ms // 1000000 - now
        unit = timer[:-len(".timer")] if timer.endswith(".timer") else timer
        reminder = unit[len("blackarch-reminder-"):] if unit.startswith("blackarch-reminder-") else unit
        reminder_minutes = reminder.split("m-", 1)[0]
        message = read_message(unit)

        if message:
            line = "%s in %s (%s)" % (message, format_remaining(remaining), at_time(next_ms))
        else:
            line = "%s-min reminder in %s (%s)" % (
                reminder_minutes,
                format_remaining(remaining),
                at_time(next_ms),
            )
        body += line + "\n"

    if not body:
        notify("Upcoming reminders", "No outstanding reminders")
    else:
        notify("Upcoming reminders", body[:-1])


def show_json():
    now = int(datetime.now().timestamp())
    count = 0
    reminders = []
    tooltip = "Set Reminder"

    for timer, next_ms in active_reminder_timers(now):
        count += 1
        unit = timer[:-len(".timer")] if timer.endswith(".timer") else timer
        reminder = unit[len("blackarch-reminder-"):] if unit.startswith("blackarch-reminder-") else unit
        reminder_minutes = reminder.split("m-", 1)[0]
        if not re.match(r"^[0-9]+$", reminder_minutes):
            reminder_minutes = "0"
        minutes = int(reminder_minutes)
        remaining = next_ms // 1000000 - now
        message = read_message(unit)
        label = message if message else "%s-min reminder" % reminder_minutes

        reminders.append(
            {
                "unit": unit,
                "timer": timer,
                "minutes": minutes,
                "message": message,
                "label": label,
                "remaining": format_remaining(remaining),
                "remainingSeconds": remaining,
                "at": next_ms,
                "atTime": at_time(next_ms),
            }
        )

    if count == 1:
        tooltip = "1 reminder"
    elif count > 1:
        tooltip = "%d reminders" % count

    print(
        json.dumps(
            {
                "count": count,
                "active": count > 0,
                "tooltip": tooltip,
                "reminders": reminders,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )


def clear_reminders():
    text = run_capture(
        [
            "systemctl",
            "--user",
            "list-timers",
            "--all",
            "--no-legend",
            "--no-pager",
            TIMER_GLOB,
        ]
    )
    units = []
    for line in text.split("\n"):
        fields = line.split()
        if len(fields) >= 2:
            units.append(fields[-2])
            units.append(fields[-1])
    if units:
        run(["systemctl", "--user", "stop", *units], check=False)

    directory = Path(REMINDER_DIR)
    if directory.is_dir():
        for path in directory.glob("blackarch-reminder-*.message"):
            try:
                path.unlink()
            except OSError:
                pass
    refresh_indicator()
    notify("All reminders have been cleared", "")


USAGE = (
    "Usage: blackarch-reminder [-i|--interactive]\n"
    "       blackarch-reminder <minutes> [message]\n"
    "       blackarch-reminder show [-j|--json]\n"
    "       blackarch-reminder clear\n"
)


def usage():
    """The bash helper's usage() echoes to stdout."""
    sys.stdout.write(USAGE)


def main(argv):
    args = argv[1:]

    if args and args[0] in ("-i", "--interactive"):
        open_interactive()
        return 0

    if args and args[0] in ("show", "list"):
        if len(args) > 1:
            if args[1] in ("-j", "--json"):
                show_json()
            elif args[1] == "":
                show_reminders()
            else:
                usage()
                return 1
        else:
            show_reminders()
        return 0

    if args and args[0] == "clear":
        clear_reminders()
        return 0

    minutes_arg = args[0] if args else ""
    message = " ".join(args[1:])

    if minutes_arg == "" or not re.match(r"^[0-9]+$", minutes_arg) or int(minutes_arg) == 0:
        usage()
        return 1

    minutes = int(minutes_arg)
    if message == "":
        message = "Your %d minutes are up" % minutes

    set_at = int(datetime.now().timestamp())
    remind_at_str = remind_at(minutes)
    unit = "blackarch-reminder-%dm-%d" % (minutes, set_at)
    message_file = os.path.join(REMINDER_DIR, unit + ".message")
    confirmation = "You'll be reminded at %s" % remind_at_str
    confirmation_title = "Reminder set for %d minutes" % minutes

    os.makedirs(REMINDER_DIR, exist_ok=True)

    if message != "":
        with open(message_file, "w") as fh:
            fh.write(message)
        confirmation_title = "%s in %d minutes" % (message, minutes)

    script = (
        "blackarch-notification-send -g %s \"Reminder\" \"$1\"; rm -f \"$2\"; "
        "blackarch-shell -q blackarch.indicators refresh >/dev/null 2>&1 || true"
        % ICON
    )
    run(
        [
            "systemd-run",
            "--user",
            "--quiet",
            "--collect",
            "--on-active=%dm" % minutes,
            "--unit=%s" % unit,
            "bash",
            "-c",
            script,
            "bash",
            message,
            message_file,
        ],
        check=False,
    )

    refresh_indicator()
    notify(confirmation_title, confirmation)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
