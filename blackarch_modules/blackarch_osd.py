#!/usr/bin/env python3
# blackarch:summary=Show the Blackarch Quickshell on-screen display
# blackarch:args=[-i|--icon <icon>] [-m|--message <text>] [-p|--progress <0-100>] [-d|--duration <ms>]
# blackarch:examples=blackarch osd -i brightness -p 50 | blackarch osd -m "Hello"
"""blackarch-osd — show the Blackarch Quickshell on-screen display.

Python port of the bash original. It builds the JSON payload the shell's OSD
expects and forwards it through `blackarch-shell osd show`. The payload is
emitted with compact separators and raw UTF-8 so it is byte-identical to the
`jq -cn` the original used — the shell parses it, but a payload that differs
only in escaping is a needless divergence.
"""

import json
import subprocess
import sys

PAYLOAD_KEYS = (
    "icon",
    "message",
    "value",
    "progressText",
    "max",
    "duration",
)


def usage() -> None:
    print(
        "Usage: blackarch-osd [-i|--icon <icon>] [-m|--message <text>] "
        "[-p|--progress <0-100>] [-d|--duration <ms>]",
        file=sys.stderr,
    )


def parse_args(argv: list[str]) -> dict:
    """Return the option dict, or raise SystemExit(1) on an unknown option."""
    options: dict[str, str] = {}
    index = 0

    value_flags = {
        "-i": "icon",
        "--icon": "icon",
        "-m": "message",
        "--message": "message",
        "-p": "progress",
        "--progress": "progress",
        "-d": "duration",
        "--duration": "duration",
    }

    while index < len(argv):
        flag = argv[index]
        if flag in ("-h", "--help"):
            raise SystemExit(0)
        if flag not in value_flags:
            print(f"Unknown OSD option: {flag}", file=sys.stderr)
            raise SystemExit(1)
        # `${2:-}`: a missing value is the empty string, not an error.
        options[value_flags[flag]] = argv[index + 1] if index + 1 < len(argv) else ""
        index += 2

    return options


def build_payload(options: dict[str, str]) -> str:
    progress = options.get("progress", "")
    payload = {
        "icon": options.get("icon", ""),
        "message": options.get("message", ""),
        "value": progress,
        "progressText": f"{progress}%" if progress else "",
        "max": "100",
        "duration": options.get("duration", ""),
    }
    # jq -cn: compact separators, UTF-8 raw.
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def main(argv: list[str]) -> int:
    try:
        options = parse_args(argv)
    except SystemExit as error:
        # -h prints the usage line and exits 0; anything else exits 1.
        return 0 if error.code in (0, None) else 1

    payload = build_payload(options)
    subprocess.run(["blackarch-shell", "-q", "osd", "show", payload], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
