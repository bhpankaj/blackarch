#!/usr/bin/env python3
"""blackarch_helpers — importable core of blackarch-helpers.

Holds the logic of install/helpers/{as-root,logging,browser-policy}.sh so the
other ports can import it; `blackarch-helpers` is this module with a thin CLI.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Sequence

ZSHRC = os.path.expanduser("~/.zshrc")

INSTALL_LOG_FILE = os.environ.get("BLACKARCH_INSTALL_LOG_FILE", "")
LOG_TO_STDOUT = os.environ.get("BLACKARCH_LOG_TO_STDOUT") == "1"

MANAGED_DIRS = (
    "/etc/chromium/policies/managed",
    "/etc/opt/chrome/policies/managed",
    "/etc/opt/edge/policies/managed",
    "/etc/brave/policies/managed",
)

# Ancestors of the managed dirs, shortest first. A writable or attacker-owned
# parent can rename the leaf aside; install -d follows a planted symlink.
PARENT_DIRS = (
    "/etc/chromium",
    "/etc/chromium/policies",
    "/etc/opt/chrome",
    "/etc/opt/chrome/policies",
    "/etc/opt/edge",
    "/etc/opt/edge/policies",
    "/etc/brave",
    "/etc/brave/policies",
)

FIREFOX_DIRS = (
    "/usr/lib/firefox/distribution",
    "/opt/zen-browser/distribution",
)

DEFAULT_COLOR = "#1c2027"


# ── privilege escalation ─────────────────────────────────────────────────────
def current_wayland_env() -> dict[str, str]:
    """The Wayland session variables worth carrying into a root process.

    Defaults mirror the shell's own, so a caller outside the graphical session
    (an ssh or TTY invocation) still gets a usable root environment rather than
    an empty one.
    """
    uid = os.getuid()
    return {
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}",
        "DBUS_SESSION_BUS_ADDRESS": (
            os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            or f"unix:path=/run/user/{uid}/bus"),
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY") or "wayland-1",
        "HYPRLAND_INSTANCE_SIGNATURE": os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", ""),
        "BLACKARCH_PATH": os.environ.get("BLACKARCH_PATH", ""),
    }


def _zshrc_source_line() -> str:
    """Source ~/.zshrc, but only when it is safe to do so."""
    return f'[ -r "{ZSHRC}" ] && . "{ZSHRC}" >/dev/null 2>&1 || true'


def waylandsudo_argv(argv: Sequence[str]) -> list[str]:
    """How to invoke `argv` as root with the Wayland session preserved.

    `waylandsudo` is a zsh function, not a binary, so it only exists inside a
    zsh that has sourced ~/.zshrc. `-i` sources the rc file but also enables
    interactive options that make zsh refuse to run a non-interactive command,
    and `-c` alone does not source it at all — so the rc is sourced explicitly
    and the function then invoked. Falls back to `sudo /usr/bin/env` when zsh or
    the function is absent.
    """
    argv = list(argv)
    if shutil.which("zsh") and os.path.isfile(ZSHRC):
        joined = " ".join(shlex.quote(part) for part in argv)
        script = f'{_zshrc_source_line()}; waylandsudo {joined}'
        return ["zsh", "-c", script]
    env_pairs = [f"{key}={value}"
                 for key, value in current_wayland_env().items() if value]
    return ["sudo", "/usr/bin/env", *env_pairs, *argv]


def run(argv: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(argv), **kwargs)
    except OSError:
        return subprocess.CompletedProcess(list(argv), 127, b"", b"")


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def as_root(*argv: str) -> subprocess.CompletedProcess:
    """`as_root` — run through waylandsudo when not already root."""
    if os.geteuid() == 0:
        return _run(list(argv))
    return _run(waylandsudo_argv(list(argv)))


# ── logging.sh ───────────────────────────────────────────────────────────────
def log_to_stdout() -> bool:
    """`[[ ${BLACKARCH_LOG_TO_STDOUT:-} == "1" || -z ${BLACKARCH_INSTALL_LOG_FILE:-} ]]`."""
    return LOG_TO_STDOUT or not INSTALL_LOG_FILE


def log_line(message: str) -> None:
    if log_to_stdout():
        print(message)
    else:
        with open(INSTALL_LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")


def start_install_log() -> None:
    if not log_to_stdout():
        os.makedirs(os.path.dirname(INSTALL_LOG_FILE), exist_ok=True)
        Path(INSTALL_LOG_FILE).touch()
        try:
            os.chmod(INSTALL_LOG_FILE, 0o666)
        except OSError:
            pass

    os.environ.setdefault("BLACKARCH_START_TIME", _timestamp())
    os.environ.setdefault("BLACKARCH_START_EPOCH", str(int(time.time())))

    log_line(f"=== Blackarch Setup Started: {os.environ['BLACKARCH_START_TIME']} ===")


def stop_install_log() -> None:
    log_line(f"=== Blackarch Setup Completed: {_timestamp()} ===")

    start_epoch = os.environ.get("BLACKARCH_START_EPOCH")
    if start_epoch and start_epoch.isdigit():
        duration = int(time.time()) - int(start_epoch)
        log_line(f"Blackarch setup: {duration // 60}m {duration % 60}s")


def run_logged(script: str) -> int:
    """`run_logged <script>` — source a script with -eE, logging the outcome.

    The caller's errexit state is not affected: a failing script is reported,
    not propagated.
    """
    log_line(f"[{_timestamp()}] Starting: {script}")

    debug = os.environ.get("BLACKARCH_INSTALL_DEBUG") == "1"
    argv = ["bash", "-x", "-eE"] if debug else ["bash", "-eE"]
    argv += ["-c", 'source "$1"', "bash", script]

    proc = subprocess.run(argv, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
    if not log_to_stdout():
        with open(INSTALL_LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(output)

    if proc.returncode == 0:
        log_line(f"[{_timestamp()}] Completed: {script}")
    else:
        log_line(f"[{_timestamp()}] Failed: {script} (exit code: {proc.returncode})")
    return proc.returncode


# ── browser-policy.sh ────────────────────────────────────────────────────────
def purge_dir(directory: str) -> None:
    """Remove every non-root entry directly inside `directory`."""
    as_root("find", directory, "-mindepth", "1", "-maxdepth", "1",
            "!", "-user", "root", "-exec", "rm", "-rf", "--", "{}", "+")


def _stat_mode(path: str) -> str:
    try:
        return oct(os.stat(path).st_mode & 0o777)[2:].zfill(3)
    except OSError:
        return ""


def _stat_user(path: str) -> str:
    try:
        return Path(path).owner()
    except (OSError, KeyError):
        return ""


def parent_hardened(directory: str) -> bool:
    """`browser_policy_parent_hardened` — a real 0755 root-owned directory."""
    return (os.path.isdir(directory) and not os.path.islink(directory)
            and _stat_mode(directory) == "755"
            and _stat_user(directory) == "root")


def dir_hardened(directory: str) -> bool:
    return parent_hardened(directory)


def parents_hardened(directory: str) -> bool:
    for parent in PARENT_DIRS:
        if not directory.startswith(parent + "/"):
            continue
        if not (os.path.exists(parent) or os.path.islink(parent)):
            continue
        if not parent_hardened(parent):
            return False
    return True


def setup_parent(directory: str) -> None:
    """`browser_policy_setup_parent` — a symlink or non-directory is removed first."""
    if os.path.islink(directory) or (os.path.exists(directory)
                                      and not os.path.isdir(directory)):
        as_root("rm", "-rf", "--", directory)
    as_root("install", "-d", "-m", "0755", "-o", "root", "-g", "root", directory)


def setup_parents_for(directory: str) -> None:
    for parent in PARENT_DIRS:
        if directory.startswith(parent + "/"):
            setup_parent(parent)


def setup_dir(directory: str) -> None:
    setup_parents_for(directory)
    setup_parent(directory)
    purge_dir(directory)


def theme_hex(theme_rgb: str) -> str:
    """`browser_policy_theme_hex` — accept only three 0-255 components.

    Bash's `(( 10#${x} < 256 ))` forces base 10 so a leading zero is not read
    as octal; int(x, 10) is the equivalent.
    """
    match = re.fullmatch(
        r"[ \t]*([0-9]{1,3}),[ \t]*([0-9]{1,3}),[ \t]*([0-9]{1,3})[ \t]*",
        theme_rgb,
    )
    if match:
        parts = [int(part, 10) for part in match.groups()]
        if all(part < 256 for part in parts):
            return "#{:02x}{:02x}{:02x}".format(*parts)
    return DEFAULT_COLOR


def install_color(policy_dir: str, hex_color: str) -> bool:
    """Write color.json into a managed-policy dir. False on a bad color."""
    if not (os.path.isdir(policy_dir) and not os.path.islink(policy_dir)):
        return True
    if not re.fullmatch(r"#[0-9a-f]{6}", hex_color):
        return False

    dest = os.path.join(policy_dir, "color.json")

    if os.path.islink(dest) or os.path.isdir(dest):
        try:
            if os.path.islink(dest) or os.path.isfile(dest):
                os.unlink(dest)
            else:
                shutil.rmtree(dest)
        except OSError:
            return False

    staged = Path(f"{dest}.{os.getpid()}.tmp")
    staged.write_text(
        f'{{"BrowserThemeColor": "{hex_color}", "BrowserColorScheme": "device"}}\n',
        encoding="utf-8")
    result = subprocess.run(["install", "-m", "0644", "-T", str(staged), dest],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            check=False)
    try:
        staged.unlink()
    except OSError:
        pass
    return result.returncode == 0


def firefox_policy_file_ok(path: str) -> bool:
    """A real root-owned file with neither group nor other write."""
    if not (os.path.isfile(path) and not os.path.islink(path)):
        return False
    if _stat_user(path) != "root":
        return False
    mode = _stat_mode(path)
    if len(mode) != 3:
        return False
    group_write, other_write = int(mode[1]), int(mode[2])
    return not (group_write & 2) and not (other_write & 2)


def firefox_hardened(directory: str) -> bool:
    return (parent_hardened(directory)
            and firefox_policy_file_ok(os.path.join(directory, "policies.json")))


def install_firefox_policies(distribution_dir: str, policies: str = "") -> None:
    source = policies or os.path.join(
        os.environ.get("BLACKARCH_PATH", ""), "default/firefox/policies.json")
    as_root("install", "-m", "644", "-o", "root", "-g", "root", "-T", source,
            os.path.join(distribution_dir, "policies.json"))


def setup_firefox_distribution(distribution_dir: str, policies: str = "") -> None:
    setup_parent(distribution_dir)
    purge_dir(distribution_dir)
    install_firefox_policies(distribution_dir, policies)


# ── export bridge ────────────────────────────────────────────────────────────
EXPORT_KEYS = ("BLACKARCH_START_TIME", "BLACKARCH_START_EPOCH",
               "BLACKARCH_INSTALL_LOG_FILE", "BLACKARCH_LOG_TO_STDOUT")


def export_lines() -> str:
    """The environment this module materialised, for a caller's `eval`."""
    return "\n".join(f"export {key}={shlex.quote(os.environ[key])}"
                     for key in EXPORT_KEYS if key in os.environ)


def _timestamp() -> str:
    return subprocess.run(["date", "+%Y-%m-%d %H:%M:%S"], stdout=subprocess.PIPE,
                          check=False).stdout.decode().strip()


def complete_subcommands(argv, commands) -> int | None:
    """Handle `--complete`: print `commands` (iterable of str) and return 0.

    Returns None when `--complete` is not requested so callers can fall through.
    Usage:
        rc = complete_subcommands(sys.argv[1:], ["up", "down", "mute"])
        if rc is not None:
            return rc
    """
    if argv and argv[0] == "--complete":
        for command in commands:
            print(command)
        return 0
    return None


def main(argv=None) -> int:
    print(export_lines())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
