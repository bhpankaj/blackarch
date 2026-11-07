#!/usr/bin/env python3
# blackarch:summary=List powerprofilesctl profiles in reverse order for the bar
"""blackarch-powerprofiles-list — list powerprofilesctl profiles in reverse order.

Python port of the bash original. It shells out to `powerprofilesctl list` and
keeps the pipeline's exact semantics: the profile name lines are filtered and
reversed (`tac`), and the exit status is the pipeline's last stage, so a
broken or missing `powerprofilesctl` still exits 0 with empty stdout while its
stderr passes straight through to the caller.
"""

import re
import subprocess
import sys

# awk: /^\s*[* ]\s*[a-zA-Z0-9\-]+:$/
# `\s` in gawk is [ \t\n\r\f\v]; write the class out explicitly so no Unicode
# whitespace can sneak in.
FILTER = re.compile(r"^[ \t\n\r\f\v]*[* ][ \t\n\r\f\v]*[a-zA-Z0-9\-]+:$")

# awk: gsub(/^[*[:space:]]+|:$/, "")
# POSIX [:space:] is [ \t\n\r\f\v]; `^` only matches at the start, so this
# strips the leading run then the trailing colon (at most two replacements).
STRIP = re.compile(r"^[*\t\n\r\f\v ]+|:$")


def main() -> int:
    try:
        proc = subprocess.run(["/usr/bin/powerprofilesctl", "list"], stdout=subprocess.PIPE)
    except OSError:
        # `powerprofilesctl list | awk | tac` — a missing binary still yields an
        # empty pipeline with status 0 (tac's).
        return 0

    out = proc.stdout.decode("utf-8", errors="replace")
    names = []
    for line in out.split("\n"):
        if not FILTER.match(line):
            continue
        active = "*" in line.split(":")[0] if ":" in line else "*" in line
        name = STRIP.sub("", line)
        names.append((name, active))
    for name, active in reversed(names):
        if active:
            print(f"{name}\t1")
        else:
            print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
