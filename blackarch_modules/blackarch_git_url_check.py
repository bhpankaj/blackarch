#!/usr/bin/env python3
# blackarch:summary=Check that a git URL names a repository, not a transport helper
# blackarch:args=<git-url>
# blackarch:hidden=true
"""blackarch-git-url-check — refuse git URLs that name a transport helper.

Python port of the bash original. git picks a remote helper -- an executable it
runs at clone time -- out of a URL in exactly two shapes, and no others:
``<helper>::<address>``, and ``<scheme>://<address>`` for any scheme git does not
handle itself. A single colon is always scp-style ssh, and a bare path is always
a path; neither can reach a helper.

The ``::`` shape is refused outright, because no helper reachable that way is one
a theme or plugin URL has business naming, and ``ext::`` runs a shell command.
The ``://`` shape cannot be refused the same way, since it is also how every
legitimate URL arrives -- so it is allowlisted instead. The list is the transports
git still connects itself, ``git+ssh`` and ``ssh+git`` included: those two are
spelled like a helper but are read as plain ssh. ``ext`` and ``fd`` are left out
deliberately -- git ships a helper for each, and ``ext`` runs whatever command
the URL carries.
"""

from __future__ import annotations

import re
import sys

TRANSPORTS = ("ssh", "git", "git+ssh", "ssh+git", "http", "https", "ftp", "ftps", "file")

HELPER_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.-]*::")
SCHEME_SHAPE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9+.-]*)://")


def fail(message: str) -> int:
    print(f"blackarch-git-url-check: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    url = argv[0] if argv else ""

    if not url:
        return fail("a git URL is required")

    if url.startswith("-") or HELPER_SHAPE.match(url):
        return fail(f"'{url}' names a git option or transport helper, not a repository.")

    match = SCHEME_SHAPE.match(url)
    if match:
        scheme = match.group(1)
        if scheme not in TRANSPORTS:
            return fail(f"'{url}' names the '{scheme}' transport, which Blackarch does not clone from.")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
