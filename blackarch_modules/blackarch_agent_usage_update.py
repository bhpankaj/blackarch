#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# blackarch:summary=Regenerate the AI agent usage data files
# blackarch:args=[--force] [--limits-only] [--except <agent>] [agent...]
# blackarch:examples=blackarch agent usage-update | blackarch agent usage-update claude | blackarch agent usage-update --except codex
"""blackarch-agent-usage-update: port of the bash helper.

    Regenerate the AI agent usage data files

    Args: [--force] [--limits-only] [--except <agent>] [agent...]
    Examples: blackarch agent usage-update | blackarch agent usage-update claude | blackarch agent usage-update --except codex
"""

import glob
import json
import os
import subprocess
import sys
import tempfile

# Each blackarch-agent-usage-<agent> collector prints one display-ready JSON
# record; this writes them to ~/.local/state/blackarch/agents/usage/ where the
# agents panel watches them. Adding an agent is adding a collector -- the
# panel picks up any record that appears here.

USAGE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local/state")),
    "blackarch",
    "agents",
    "usage",
)


def collector_dir():
    """$BLACKARCH_PATH/bin, the directory the collectors are globbed from."""
    return os.path.join(os.environ.get("BLACKARCH_PATH", ""), "bin")


def parse_args(argv):
    """flags, only, excluded -- mirrors the bash argument loop."""
    flags = []
    only = []
    excluded = set()
    args = list(argv)
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--force", "--limits-only"):
            flags.append(arg)
        elif arg == "--except":
            if i + 1 < len(args):
                excluded.add(args[i + 1])
                i += 1
        else:
            only.append(arg)
        i += 1
    return flags, only, excluded


def wanted(agent, only, excluded):
    if agent in excluded:
        return False
    if not only:
        return True
    return agent in only


def collect(collector, agent, flags):
    """Write one collector's record to <usage>/<agent>.json atomically.

    The bash version mktemp's a sibling file and mv's it into place, so the
    panel's FileView never sees a half-written record.
    """
    cmd = [collector, *flags]
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        p = None
    if p is None or p.returncode != 0 or p.stdout == b"":
        sys.stderr.write("blackarch-agent-usage-update: %s collector failed\n" % agent)
        return False
    record = p.stdout.decode("utf-8", "replace")
    try:
        json.loads(record)
    except ValueError:
        sys.stderr.write("blackarch-agent-usage-update: %s collector failed\n" % agent)
        return False

    target = os.path.join(USAGE_DIR, agent + ".json")
    fd, tmp = tempfile.mkstemp(prefix=".%s." % agent, dir=USAGE_DIR)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(record if record.endswith("\n") else record + "\n")
        os.replace(tmp, target)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        sys.stderr.write("blackarch-agent-usage-update: %s collector failed\n" % agent)
        return False
    return True


def main(argv):
    os.makedirs(USAGE_DIR, exist_ok=True)
    flags, only, excluded = parse_args(argv[1:])

    collectors = sorted(
        path
        for path in glob.glob(os.path.join(collector_dir(), "blackarch-agent-usage-*"))
        if os.access(path, os.X_OK)
    )

    results = []
    for collector in collectors:
        agent = os.path.basename(collector)[len("blackarch-agent-usage-"):]
        if agent == "update":
            continue
        if not wanted(agent, only, excluded):
            continue
        results.append(collect(collector, agent, flags))

    return 1 if any(not ok for ok in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
