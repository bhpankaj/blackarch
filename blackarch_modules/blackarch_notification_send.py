#!/usr/bin/env python3
# blackarch:summary=Send an Blackarch desktop notification
# blackarch:args=[--app-name <app-name>] [-g <glyph>] [-u <low|normal|critical>] [-i <icon>] [-t <ms>] [-r <id>] [-p] [--image <path-or-uri>] <headline> [description] [--exec <program> [args...]]
# blackarch:examples=blackarch notification send "Reminder" "5 minutes are up" -g 󰢌
"""blackarch-notification-send — send a Blackarch desktop notification.

Python port of the bash original. Calls org.freedesktop.Notifications.Notify
over `busctl` — never notify-send, whose argv parsing reinterprets a relayed
headline like `--hint=…` or `-rf` as options. Signature susssasa{sv}i.

The hint vector is built as busctl triples: urgency is a byte (`y`), the rest
are strings (`s`). `--exec` rides along as the JSON array `blackarch-exec-argv`,
NUL-delimited into jq by the original so every byte survives as data.
"""

import json
import re
import subprocess
import sys

USAGE = (
    "Usage: blackarch-notification-send [--app-name <app-name>] [-g <glyph>] "
    "[-u <low|normal|critical>] [-i <icon>] [-t <ms>] [-r <id>] [-p] "
    "[--image <path-or-uri>] <headline> [description] [--exec <program> [args...]]"
)

URGENCY_BYTES = {"low": "0", "normal": "1", "critical": "2"}

VALUE_FLAGS = {
    "-g": "glyph",
    "--glyph": "glyph",
    "-u": "urgency",
    "--urgency": "urgency",
    "--app-name": "app_name",
    "-i": "app_icon",
    "--icon": "app_icon",
    "--image": "image",
    "-r": "replaces_id",
    "--replace-id": "replaces_id",
    "-t": "expire_timeout",
    "--expire-time": "expire_timeout",
}

# An option may be spelled `--flag value` or `--flag=value`.
SPLIT_EQUAL = re.compile(r"^(--[A-Za-z-]+)=(.*)$", re.DOTALL)
NUMERIC_ID = re.compile(r"^[0-9]+$")
NUMERIC_TIMEOUT = re.compile(r"^-?[0-9]+$")
KNOWN_FLAG_NAMES = frozenset(
    list(VALUE_FLAGS)
    + ["-p", "--print-id", "--exec"]
    + [f"{flag}=" for flag in VALUE_FLAGS]
)


def usage_exit() -> None:
    print(USAGE, file=sys.stderr)
    raise SystemExit(1)


def known_flag(flag: str) -> bool:
    """True when the argument is a recognized option, in either spelling."""
    if flag in KNOWN_FLAG_NAMES:
        return True
    return SPLIT_EQUAL.match(flag) is not None


def parse_option(args: list[str]) -> tuple[str, int]:
    """Return (option_name, consumed_arg_count) for a recognized option.

    Returns ("", 0) for anything unrecognized so the caller can decide whether
    the argument is the headline or a hard error. `-p`/`--print-id` is a flag
    and consumes one argument.
    """
    flag = args[0]
    match = SPLIT_EQUAL.match(flag)
    if match:
        name, value = match.group(1), match.group(2)
        if name not in VALUE_FLAGS:
            return "", 0
        if name == "-r" or name == "--replace-id":
            if not NUMERIC_ID.match(value):
                print(f"Invalid {name} value (numeric id expected): {value}",
                      file=sys.stderr)
                raise SystemExit(1)
        elif name in ("-t", "--expire-time"):
            if not NUMERIC_TIMEOUT.match(value):
                print(f"Invalid {name} value (milliseconds expected): {value}",
                      file=sys.stderr)
                raise SystemExit(1)
        return name, 1

    if flag in ("-p", "--print-id"):
        return "print-id", 1
    if flag not in VALUE_FLAGS:
        return "", 0

    if len(args) < 2:
        print(f"Missing value for {flag}", file=sys.stderr)
        raise SystemExit(1)
    return flag, 2


def main(argv: list[str]) -> int:
    app_name = "blackarch-action"
    glyph = ""
    urgency = "low"
    app_icon = ""
    image = ""
    expire_timeout = "-1"
    replaces_id = "0"
    print_id = False
    exec_args: list[str] = []
    exec_present = False

    index = 0
    while index < len(argv):
        name, consumed = parse_option(argv[index:])
        if not name:
            break
        if name == "print-id":
            print_id = True
        elif name in ("-r", "--replace-id"):
            replaces_id = argv[index + 1]
        elif name in ("-t", "--expire-time"):
            expire_timeout = argv[index + 1]
        else:
            flag = argv[index]
            match = SPLIT_EQUAL.match(flag)
            value = match.group(2) if match else argv[index + 1]
            if name in ("-g", "--glyph"):
                glyph = value
            elif name in ("-u", "--urgency"):
                urgency = value
            elif name == "--app-name":
                app_name = value
            elif name in ("-i", "--icon"):
                app_icon = value
            elif name == "--image":
                image = value
        index += consumed

    remaining = argv[index:]
    if not remaining:
        usage_exit()

    headline = remaining[0]
    index += 1

    # The description is the next positional, taken as text even when it begins
    # with a dash — "-50% off" is content, not options.
    description = ""
    if index < len(argv) and not known_flag(argv[index]):
        description = argv[index]
        index += 1

    while index < len(argv):
        if argv[index] == "--exec":
            # --exec consumes the rest of the line as the click command's argv.
            index += 1
            exec_args = argv[index:]
            exec_present = True
            break
        name, consumed = parse_option(argv[index:])
        if not name:
            print(f"Unknown option: {argv[index]}", file=sys.stderr)
            usage_exit()
        if name == "print-id":
            print_id = True
        elif name in ("-r", "--replace-id"):
            replaces_id = argv[index + 1]
        elif name in ("-t", "--expire-time"):
            expire_timeout = argv[index + 1]
        else:
            flag = argv[index]
            match = SPLIT_EQUAL.match(flag)
            value = match.group(2) if match else argv[index + 1]
            if name in ("-g", "--glyph"):
                glyph = value
            elif name in ("-u", "--urgency"):
                urgency = value
            elif name == "--app-name":
                app_name = value
            elif name in ("-i", "--icon"):
                app_icon = value
            elif name == "--image":
                image = value
        index += consumed

    if urgency not in URGENCY_BYTES:
        print(
            f"Unknown urgency: {urgency} (use low, normal, or critical)",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # a{sv} hints, as busctl triples (key, variant type, value).
    hints: list[str] = ["urgency", "y", URGENCY_BYTES[urgency]]
    if glyph:
        hints += ["blackarch-glyph", "s", glyph]
    if image:
        hints += ["image-path", "s", image]

    if exec_present:
        if not exec_args or not exec_args[0]:
            print("--exec needs a command: --exec <program> [args...]", file=sys.stderr)
            raise SystemExit(1)
        # A single word containing a space is almost always a whole command
        # passed as one quoted string. Splitting it ourselves is exactly the
        # injection this interface avoids, so reject it and point at the
        # unquoted form instead.
        if len(exec_args) == 1 and re.search(r"\s", exec_args[0]):
            print("--exec takes the command as separate words, not one quoted string.",
                  file=sys.stderr)
            print(f"Write:  --exec {exec_args[0]}", file=sys.stderr)
            raise SystemExit(1)
        encoded = json.dumps(exec_args, separators=(",", ":"), ensure_ascii=False)
        hints += ["blackarch-exec-argv", "s", encoded]

    hint_count = len(hints) // 3

    notify_cmd = [
        "busctl", "--user", "--", "call",
        "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications", "Notify", "susssasa{sv}i",
        app_name, replaces_id, app_icon, headline, description,
        "0",
        str(hint_count), *hints,
        expire_timeout,
    ]

    result = subprocess.run(notify_cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=False)
    if print_id:
        # busctl prints the UINT32 return as "u <id>"; emit just the id.
        sys.stdout.write(result.stdout.decode("utf-8", "replace").rsplit(" ", 1)[-1])
        if not result.stdout.endswith(b"\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
