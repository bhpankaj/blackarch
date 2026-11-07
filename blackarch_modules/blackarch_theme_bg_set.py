#!/usr/bin/env python3
# blackarch:summary=Set the current background image
# blackarch:args=<path-to-image>
# blackarch:examples=blackarch theme bg set ~/Pictures/background.png
"""blackarch-theme-bg-set — set the current background image."""
import os
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1]:
        print("Usage: blackarch-theme-bg-set <path-to-image>", file=sys.stderr)
        return 1

    background = os.path.realpath(sys.argv[1])
    if not os.path.isfile(background):
        print(f"File does not exist: {background}", file=sys.stderr)
        return 1

    home = os.environ.get("HOME", "")
    state = os.path.join(home, ".local/state/blackarch/current")
    os.makedirs(state, exist_ok=True)
    link = os.path.join(state, "background")
    try:
        if os.path.lexists(link):
            if os.path.isdir(link) and not os.path.islink(link):
                import shutil
                shutil.rmtree(link)
            else:
                os.unlink(link)
        os.symlink(background, link)
    except OSError as exc:
        print(f"ln: {exc}", file=sys.stderr)
        return 1

    try:
        subprocess.run(
            ["blackarch-shell", "-q", "background", "set", background],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())