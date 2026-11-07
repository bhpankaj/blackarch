#!/usr/bin/env python3
# blackarch:summary=Write the current theme color into the browser policy directories
# blackarch:args=<rrggbb>
# blackarch:hidden=true
"""blackarch-theme-set-browser-policy — write the theme color into browser policy.

Python port of the bash original. Only browsers Blackarch has installed have a
policy directory; creating one here would hand a browser a managed-policy root
it does not otherwise have. The color is written as color.json into each
existing managed-policy directory.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blackarch_modules.blackarch_helpers import current_wayland_env, waylandsudo_argv  # noqa: E402

PACKAGED_PATH = "/usr/bin/blackarch-theme-set-browser-policy"
POLICY_DIRS = (
    "/etc/chromium/policies/managed",
    "/etc/opt/chrome/policies/managed",
    "/etc/opt/edge/policies/managed",
    "/etc/brave/policies/managed",
)
HEX_COLOR = re.compile(r"^[0-9a-f]{6}$")


def usage() -> None:
    print("Usage: blackarch-theme-set-browser-policy <rrggbb>", file=sys.stderr)


def sudo_grants_passwordless() -> bool:
    """True when sudo would run this exact command without a password.

    The long listing prints the matched entry's tags, so !authenticate is the
    grant in /etc/sudoers.d/blackarch-theme-browser and nothing else.
    """
    try:
        proc = subprocess.run(["sudo", "-n", "-l", "-l", PACKAGED_PATH],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return False
    return b"!authenticate" in proc.stdout


def require_root(color: str) -> None:
    """Re-exec this command as root, through waylandsudo when that will do.

    A bare `sudo` loses the Wayland session variables, so a policy write
    triggered from the graphical session would run as root with no compositor
    to talk to. waylandsudo sources ~/.zshrc and re-supplies them.
    """
    if os.geteuid() == 0:
        return
    if sys.stdin.isatty() or sudo_grants_passwordless():
        argv = waylandsudo_argv([PACKAGED_PATH, color])
        os.execvp(argv[0], argv)
    os.execvp("pkexec", ["pkexec", PACKAGED_PATH, color])


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        usage()
        return 1

    color = argv[0]

    # Six lowercase hex digits is the whole of what this accepts. The leading
    # "#" is added when the JSON is written rather than passed in: "#" opens a
    # comment in sudoers, and keeping it out of argv lets the sudoers rule spell
    # the argument as a plain six-character glob.
    if not HEX_COLOR.match(color):
        print(f"blackarch-theme-set-browser-policy: expected six lowercase hex digits, "
              f"got '{color}'", file=sys.stderr)
        return 1

    require_root(color)

    failed = 0
    staged = ""

    for policy_dir in POLICY_DIRS:
        if not (os.path.isdir(policy_dir) and not os.path.islink(policy_dir)):
            continue

        dest = os.path.join(policy_dir, "color.json")

        # A temp file is installed over the destination atomically-ish: install
        # -T refuses to write through a symlink, and a staged copy means a failed
        # write leaves the previous policy in place.
        handle, staged = tempfile.mkstemp(prefix="blackarch-browser-policy-")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(f'{{"BrowserThemeColor": "#{color}", '
                      f'"BrowserColorScheme": "device"}}\n')

        if os.path.islink(dest) or os.path.isdir(dest):
            try:
                if os.path.islink(dest) or os.path.isfile(dest):
                    os.unlink(dest)
                else:
                    shutil.rmtree(dest)
            except OSError:
                os.unlink(staged)
                staged = ""
                print(f"blackarch-theme-set-browser-policy: cannot replace {dest}",
                      file=sys.stderr)
                failed = 1
                continue

        # install -m 0644 -o root -g root -T <staged> <dest>
        result = subprocess.run(["install", "-m", "0644", "-o", "root", "-g", "root",
                                 "-T", staged, dest],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                check=False)
        os.unlink(staged)
        staged = ""
        if result.returncode != 0:
            print(f"blackarch-theme-set-browser-policy: cannot write {dest}",
                  file=sys.stderr)
            failed = 1

    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
