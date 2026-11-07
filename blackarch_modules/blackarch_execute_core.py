#!/usr/bin/env python3
# blackarch:summary=Interactive dispatcher over every ported Blackarch script
"""
blackarch -- Python port of the bash dispatcher at
/sbin/blackarch.

The layout mirrors the original one-for-one so the two stay comparable:

  helpers      shell quoting, hyprctl JSON, sudo-with-Wayland-env, tee-as-root,
               config linking, webapp window classes, TPM enrollment
  setup_*      keyrings, sudo, tpm, install, aur, hyprland, cyber, post,
               dotfiles, mount, virtualbox, kvm, hermes, smartthings
  window ring  clipboard / swap / save1..N / clear slot management
  hardware     hyprlock, suspend, audio + brightness notifications, virtual
               keyboard, touch screen orientation
  smartthings  device listing, toggling, laptop charger
  update       pacman / AUR / orphan update flow
  menu         quickshell menus, additional-menu.jsonc generation
  main         the top-level argv[1] dispatcher

Anything the original runs as root goes through sudo with the Wayland session
variables preserved (XDG_RUNTIME_DIR, DBUS_SESSION_BUS_ADDRESS,
WAYLAND_DISPLAY, HYPRLAND_INSTANCE_SIGNATURE, BLACKARCH_PATH).

Usage:
    blackarch <command> [<subcommand> [<args...>]]
    blackarch --help
"""

from __future__ import annotations

import functools
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from blackarch_packages import *

try:
    from blackarch_modules.blackarch_logging import get_logger

    logger = get_logger("commander")
except ImportError:
    import logging

    logger = logging.getLogger("commander")

BROWSERS = [
    "blackarch-webapp.desktop",
    "com.ulaa.Ulaa.desktop",
    "ulaa-browser.desktop",
    "chromium.desktop",
    "firefox.desktop",
]
BROWSER = BROWSERS[1]
Location_Home = 100
LOCATION_ID = "09b162fe-6f6a-4790-ab41-e2e6793edc00"
DEVICE_ID = "4e715c22-7aa0-4bd6-9425-b694b26e325d"
HYPR_MONITOR_LUA = str(Path.home() / ".config/hypr/blackarch/monitor.lua")
TOGGLE_STATE_DIR = Path.home() / ".local" / "state" / "blackarch" / "toggles" / "hypr"
TOUCHSCREEN_DISABLED_FILE = TOGGLE_STATE_DIR / "touchscreen-disabled-name"
TPM_PUBKEY = "/etc/systemd/tpm2-pcr-initrd-public-key.pem"
DEFAULTS_DIR = os.getenv("BLACKARCH_PATH", "/opt/blackarch")
CYBER_ROLE_DIR = "/usr/share/cyber-toolkit/roles"
ADDITIONAL_MENU = f"{DEFAULTS_DIR}/default/blackarch/additional-menu.jsonc"
SMARTTHINGS_TGZ = (
    "https://github.com/SmartThingsCommunity/smartthings-cli/releases/latest/"
    "download/smartthings-linux-x64.tgz"
)
HERMES_INSTALL = "https://hermes-agent.nousresearch.com/install.sh"
OLLAMA_INSTALL = "https://ollama.com/install.sh"
BLACKARCH_BIN_DIR = f"{DEFAULTS_DIR}/bin"
MAX_SLOTS = 3
WVKBD_BIN = "wvkbd-deskintl"
WVKBD_ARGS = ["-H", "1200", "-L", "600", "-R", "20", "--fn", "DejaVu Sans 24"]


ICON_PENTEST = "\uf489"  # nerd-font terminal glyph
ICON_DEVICE = "\U000f0b4e"  # nerd-font lightbulb glyph

_URL_RE = re.compile(r"^https?://?([^/]+)(/[^?#]*)?(\?[^#]*)?")
# Environment snapshot.  Read by most helpers and exported to children where the
# original relies on the shell's own export (KBD_DEVICE for brightness_notify).
E = os.environ.copy()

PROFILE_D_BLACKARCH_SH = ': "${BLACKARCH_PATH:=/opt/blackarch/}"\n# Strip trailing slashes so "$BLACKARCH_PATH/bin" never becomes "//bin".\nBLACKARCH_PATH="${BLACKARCH_PATH%/}"\n\ncase ":${PATH}:" in\n  *":${BLACKARCH_PATH}/bin:"*) ;;\n  *) [ -d "${BLACKARCH_PATH}/bin" ] && PATH="${BLACKARCH_PATH}/bin:${PATH}" ;;\nesac\n\nexport BLACKARCH_PATH PATH\n# Source this file for non-interactive shells too (SSH, cron, bash, zsh).\nexport BASH_ENV=/etc/profile.d/blackarch.sh\nexport ENV=/etc/profile.d/blackarch.sh\n\nwaylandsudo() {\n    local uid\n    uid=$(id -u)\n    sudo /usr/bin/env \\\n        XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}" \\\n        DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$uid/bus}" \\\n        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}" \\\n        HYPRLAND_INSTANCE_SIGNATURE="${HYPRLAND_INSTANCE_SIGNATURE}" \\\n        BLACKARCH_PATH="${BLACKARCH_PATH}" \\\n        "$@"\n}\n'


# Auto-logging decorator for all dispatcher functions
def log_all(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(
            f"dispatcher: {func.__name__} called", extra={"command": func.__name__}
        )
        return func(*args, **kwargs)

    return wrapper


@log_all
def write_profile_d() -> None:
    """Write /etc/profile.d/blackarch.sh into the new root.

    The file is what makes `blackarch` and its helpers work in every login shell
    of the clone: it derives PATH from $BLACKARCH_PATH instead of hardcoding a
    path, and it defines `waylandsudo` -- the escalation helper that keeps
    XDG_RUNTIME_DIR, the D-Bus address and WAYLAND_DISPLAY when sudoing, so a
    command that talks to the compositor still works as root.

    Call it after deploy_blackarch_tree(): the script prepends
    ${BLACKARCH_PATH}/bin only when that directory exists, so a root without the
    tree would otherwise gain a PATH entry pointing nowhere.
    """
    # step("Writing /etc/profile.d/blackarch.sh")
    ROOT_MNT = "/"
    path = os.path.join(ROOT_MNT, "etc/profile.d/blackarch.sh")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    existed = os.path.exists(path)
    with open(path, "w") as fh:
        fh.write(PROFILE_D_BLACKARCH_SH)
    # Sourced by shells, not executed: 0644 matches the other profile.d files.
    os.chmod(path, 0o644)

    # Ensure interactive non-login shells also source it (bash + zsh).
    bashrc_path = os.path.join(ROOT_MNT, "etc/bash.bashrc")
    bashrc_marker = "# blackarch installer: source profile.d/blackarch.sh"
    bashrc_line = (
        "[ -r /etc/profile.d/blackarch.sh ] && . /etc/profile.d/blackarch.sh\n"
    )
    try:
        existing = open(bashrc_path).read() if os.path.isfile(bashrc_path) else ""
        if bashrc_marker not in existing:
            with open(bashrc_path, "a") as bh:
                bh.write(f"\n{bashrc_marker}\n{bashrc_line}")
    except OSError:
        pass

    # Ensure zsh interactive/non-login shells also source it.
    for zsh_path in ("/etc/zsh/zprofile", "/etc/zsh/zshrc"):
        dst = os.path.join(ROOT_MNT, zsh_path.lstrip("/"))
        try:
            marker = "# blackarch installer: source profile.d/blackarch.sh"
            line = (
                "[ -r /etc/profile.d/blackarch.sh ] && . /etc/profile.d/blackarch.sh\n"
            )
            existing = open(dst).read() if os.path.isfile(dst) else ""
            if marker not in existing:
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                with open(dst, "a") as zh:
                    zh.write(f"\n{marker}\n{line}")
        except OSError:
            pass

    # Ensure sudo commands preserve BLACKARCH_PATH / PATH and include the bin.
    sudoers_path = os.path.join(ROOT_MNT, "etc/sudoers.d/blackarch")
    # Include content from /etc/sudoers.d/00_black
    sudoers_content = (
        "# blackarch installer: combined privileges (00_black + secure_path)\n"
        "# Source: /etc/sudoers.d/blackarch \n"
        "black ALL=(ALL:ALL) ALL \n"
        "black ALL=(ALL) NOPASSWD: SETENV: /usr/bin/pacman, /usr/sbin/env \n"
        "black ALL=(root) NOPASSWD: /opt/blackarch/bin/blackarch-dns Cloudflare, /opt/blackarch/bin/blackarch-dns Google, /opt/blackarch/bin/blackarch-dns DHCP, /opt/blackarch/bin/blackarch-kbd-backlight-monitor \n"
        "black ALL=(root) NOPASSWD: /opt/blackarch/bin/blackarch-theme-set-browser-policy [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f],  /usr/sbin/timedatectl ^set-timezone [A-Za-z0-9_+][A-Za-z0-9_+.-]*(/[A-Za-z0-9_+][A-Za-z0-9_+.-]*)*$ \n"
        "\n# secure_path / env_keep (original blackarch content)\n"
        'Defaults env_keep += "BLACKARCH_PATH PATH BASH_ENV ENV"\n'
        "Defaults secure_path = "
        '"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/blackarch/bin"\n'
    )
    try:
        os.makedirs(os.path.dirname(sudoers_path) or ".", exist_ok=True)
        with open(sudoers_path, "w") as sh:
            sh.write(sudoers_content)
        os.chmod(sudoers_path, 0o440)
    except OSError:
        pass

    ok(
        f"{path} "
        + ("rewritten" if existed else "written")
        + f" ({len(PROFILE_D_BLACKARCH_SH)} bytes)"
    )


@log_all
def argv0() -> str:
    """How to re-invoke this script (falls back to the bash original)."""
    return sys.argv[0] if sys.argv and sys.argv[0] else "/sbin/blackarch"


class C:
    BLUE = GREEN = RED = YEL = CYAN = BOLD = NC = ""

    @classmethod
    def enable(cls) -> None:
        if not sys.stdout.isatty():
            return
        cls.BLUE, cls.GREEN, cls.RED = "\033[0;34m", "\033[0;32m", "\033[0;31m"
        cls.YEL, cls.CYAN, cls.BOLD = "\033[1;33m", "\033[0;36m", "\033[1m"
        cls.NC = "\033[0m"


@log_all
def info(msg: str) -> None:
    print(f"{C.BLUE}[INFO]{C.NC} {msg}")


@log_all
def ok(msg: str) -> None:
    print(f"{C.GREEN}[ok]{C.NC} {msg}")


@log_all
def warn(msg: str) -> None:
    print(f"{C.YEL}[!]{C.NC} {msg}", file=sys.stderr)


@log_all
def err(msg: str) -> None:
    print(f"{C.RED}[x]{C.NC} {msg}", file=sys.stderr)


@log_all
def uid() -> int:
    return os.getuid()


@log_all
def is_root() -> bool:
    return uid() == 0


@log_all
def sandbox_args() -> list[str]:
    """Chromium's --no-sandbox is only required when running as root."""
    return ["--no-sandbox"] if is_root() else []


@log_all
def runtime_dir() -> str:
    return E.get("XDG_RUNTIME_DIR") or f"/run/user/{uid()}"


@log_all
def dbus_addr() -> str:
    return E.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path=/run/user/{uid()}/bus"


@log_all
def wayland_display() -> str:
    return E.get("WAYLAND_DISPLAY") or "wayland-1"


@log_all
def user_name() -> str:
    return E.get("USER") or Path.home().name


@log_all
def run(
    cmd: Sequence[str],
    *,
    check: bool = False,
    capture: bool = False,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run a command and return its CompletedProcess.

    Never raises on a non-zero exit (pass check=True for that); a missing
    binary yields returncode 127 so callers can degrade gracefully.
    """
    try:
        return subprocess.run(
            list(cmd),
            input=input_text,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            env=env if env is not None else E,
            timeout=timeout,
            check=check,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(list(cmd), 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(list(cmd), 124, exc.stdout or "", "timeout")


@log_all
def sudo_env_pairs() -> list[str]:
    """`sudo /usr/bin/env KEY=VALUE ...` -- keeps the Wayland session reachable."""
    return [
        f"XDG_RUNTIME_DIR={runtime_dir()}",
        f"DBUS_SESSION_BUS_ADDRESS={dbus_addr()}",
        f"WAYLAND_DISPLAY={wayland_display()}",
        f"HYPRLAND_INSTANCE_SIGNATURE={E.get('HYPRLAND_INSTANCE_SIGNATURE', '')}",
        f"BLACKARCH_PATH={E.get('BLACKARCH_PATH', '')}",
    ]


@log_all
def sudo_run(cmd: Sequence[str], **kw: Any) -> subprocess.CompletedProcess:
    return run(["sudo", "/usr/bin/env", *sudo_env_pairs(), *cmd], **kw)


@log_all
def sudo_write(path: str | Path, content: str, append: bool = False) -> None:
    """Write a file as root via `sudo tee` (mirrors `... | waylandsudo tee path`).

    stdout is discarded exactly like the original's `>/dev/null`, so only the
    caller's own messages reach the terminal.
    """
    cmd = [
        "sudo",
        "/usr/bin/env",
        *sudo_env_pairs(),
        "tee",
        *(["-a"] if append else []),
        str(path),
    ]
    proc = run(cmd, input_text=content, capture=True)
    if proc.returncode != 0:
        raise RuntimeError(f"sudo_write failed for {path}: {proc.stderr.strip()}")


@log_all
def have(name: str) -> bool:
    return shutil.which(name) is not None


@log_all
def require(*names: str) -> None:
    missing = [n for n in names if not have(n)]
    if missing:
        sys.exit(f"missing required command(s): {', '.join(missing)}")


@log_all
def read_text(path: str | Path, default: str = "") -> str:
    try:
        return Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return default


@log_all
def write_text(path: str | Path, text: str) -> None:
    Path(path).write_text(text)


@log_all
def run_shell(command: str) -> int:
    """Run a shell string through /bin/sh and return its exit status.

    The child inherits this terminal: a root installer needs the tty for its
    password prompt and for `isatty` checks.  Callers that need the output use
    run(capture=True) instead.  Raises if the shell itself cannot be launched.
    """
    try:
        return subprocess.run(["/bin/sh", "-c", command], text=True, env=E).returncode
    except OSError as exc:
        raise RuntimeError(f"cannot run shell command: {exc}") from exc


@log_all
def hyprctl_json(args: Sequence[str]) -> Any:
    proc = run(["hyprctl", *args, "-j"], capture=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


@log_all
def hypr_clients() -> list[dict]:
    data = hyprctl_json(["clients"])
    return data if isinstance(data, list) else []


@log_all
def get_window_address(pattern: str) -> str | None:
    """Address of the first client whose class or initialClass matches."""
    rx = re.compile(pattern, re.IGNORECASE)
    for client in hypr_clients():
        for key in ("class", "initialClass"):
            if rx.search(client.get(key) or ""):
                return client.get("address")
    return None


@log_all
def is_window_alive(app_id: str) -> bool:
    return any((c.get("class") or "") == app_id for c in hypr_clients())


@log_all
def get_active_class() -> str:
    return (hyprctl_json(["activewindow"]) or {}).get("class") or ""


@log_all
def hypr_dispatch(expr: str) -> bool:
    return run(["hyprctl", "dispatch", expr], capture=True).returncode == 0


@log_all
def under_hyprland() -> bool:
    return (
        E.get("XDG_CURRENT_DESKTOP") == "Hyprland"
        or E.get("XDG_SESSION_DESKTOP") == "Hyprland"
    )


@log_all
def focus_window(app_id: str | None = None) -> bool:
    """Focus a window by app id, or interactively choose one."""
    if not app_id:
        classes = [c.get("class") for c in hypr_clients() if c.get("class")]
        if not classes:
            return False
        chosen = menu_select("Focus selected window", classes, width=800, height=500)
        if chosen is None:
            return False
        app_id = chosen
    print(app_id)
    if not under_hyprland():
        return False
    address = get_window_address(app_id)
    if not address:
        return False
    if hypr_dispatch(f'hl.dsp.focus({{ window = "address:{address}" }})'):
        return True
    return (
        run(
            ["hyprctl", "dispatch", f"focuswindow address:{address}"], capture=True
        ).returncode
        == 0
    )


@log_all
def menu_select(
    prompt: str, options: Sequence[str], width: int = 0, height: int = 0
) -> str | None:
    """Single-select via blackarch-menu-select; None means cancelled."""
    cmd = ["blackarch-menu-select", prompt, *options]
    if width or height:
        extra: list[str] = []
        if width:
            extra += ["--width", str(width)]
        if height:
            extra += ["--height", str(height)]
        cmd += ["--", *extra]
    proc = run(cmd, capture=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


@log_all
def notify(
    headline: str,
    description: str = "",
    *,
    app_name: str = "blackarch-action",
    icon: str = "",
    urgency: str = "low",
    replaces_id: int | None = None,
    print_id: bool = False,
    expire_timeout: int = -1,
) -> int:
    """Send a notification; returns the id (0 when unavailable).

    Option order follows blackarch-notification-send's parser: -u, --app-name,
    -i, -t, -r, -p, then the positional headline and description.
    """
    cmd = ["blackarch-notification-send", "-u", urgency, "--app-name", app_name]
    if icon:
        cmd += ["-i", icon]
    if expire_timeout != -1:
        cmd += ["-t", str(expire_timeout)]
    if replaces_id:
        cmd += ["-r", str(replaces_id)]
    if print_id:
        cmd += ["-p"]
    cmd.append(headline)
    if description:
        cmd.append(description)
    proc = run(cmd, capture=True)
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


@log_all
def notify_replace(
    state_file: str,
    headline: str,
    description: str,
    *,
    app_name: str = "",
    icon: str = "",
    default_id: int = 0,
) -> None:
    """Send a notification and record its id for in-place replacement.

    Mirrors the original `blackarch-notification-send ... -p -r $ID > $FD`.
    """
    try:
        replaces = int(Path(state_file).read_text().strip() or default_id)
    except (OSError, ValueError):
        replaces = default_id
    new_id = notify(
        headline,
        description,
        app_name=app_name,
        icon=icon,
        replaces_id=replaces,
        print_id=True,
    )
    if new_id:
        write_text(state_file, str(new_id))


@log_all
def blackarch_bin_dst() -> str:
    """First of /usr/bin, /usr/sbin, /bin, /sbin present on PATH."""
    for entry in E.get("PATH", "").split(os.pathsep):
        entry = entry.rstrip("/")
        if entry in ("/usr/bin", "/usr/sbin", "/bin", "/sbin"):
            return entry
    return "/usr/bin"


@log_all
def blackarch_bin_path() -> str:
    return E.get("BLACKARCH_PATH") or ""


@log_all
def link_configs(src_root: str, target_root: str, apps: Sequence[str]) -> None:
    """Symlink config entries into place, backing up anything already there.

    The three "special" roots (the bin staging dir, BLACKARCH_PATH and
    /usr/share) link via sudo; everything else moves an existing target into
    ~/backup first.
    """
    if not os.path.isdir(target_root):
        os.makedirs(target_root, exist_ok=True)
    special = (
        src_root == f"{BLACKARCH_BIN_DIR}/"
        or target_root == blackarch_bin_path()
        or target_root == "/usr/share"
    )
    for app in apps:
        source = os.path.join(src_root, app)
        target = os.path.join(target_root, app)
        if not os.path.exists(source):
            print(f"[-] Skipping: {app} (Source not found at {src_root})")
            continue
        if os.path.islink(target):
            print(f"[~] Already linked: {app}")
            continue
        if special:
            if sudo_run(["ln", "-s", source, target]).returncode == 0:
                print(f"[+] Linked: {app} -> {target}")
            continue
        if os.path.exists(target):
            print(f"[!] Warning: {target} exists. Moving to backup/")
            backup = Path.home() / "backup"
            backup.mkdir(parents=True, exist_ok=True)
            shutil.move(target, backup / Path(target).name)
        os.symlink(source, target)
        print(f"[+] Linked: {app}")


@log_all
def shell_quote_url(url: str) -> str:
    return shlex.quote(url)


@log_all
def webapp_id(url: str = "") -> str:
    """Window class for a webapp URL: '<host>_<path with / replaced by _>'."""
    match = _URL_RE.match(url or "")
    if not match:
        return ""
    return f"{match.group(1)}_{(match.group(2) or '').replace('/', '_')}"


@log_all
def browser_exec(desktop: str = BROWSER) -> str:
    """The Exec= binary of the browser .desktop file."""
    for path in (
        Path("/var/lib/flatpak/exports/share/applications") / desktop,
        Path.home() / ".local/share/applications" / desktop,
        Path.home() / ".nix-profile/share/applications" / desktop,
        Path("/usr/share/applications") / desktop,
    ):
        if path.exists():
            for line in path.read_text(errors="replace").splitlines():
                if line.startswith("Exec=") and "flatpak" in line:
                    return line.split("=", 1)[1]
                elif line.startswith("Exec="):
                    return line.split("=", 1)[1].strip().split()[0]
    return ""


@log_all
def enroll_with_pubkey(device: str) -> int:
    return sudo_run(
        [
            "systemd-cryptenroll",
            "--tpm2-device=auto",
            "--wipe-slot=tpm2",
            f"--tpm2-public-key={TPM_PUBKEY}",
            "--tpm2-public-key-pcrs=11",
            "--tpm2-pcrs=7",
            device,
        ]
    ).returncode


@log_all
def enroll_without_pubkey(device: str) -> int:
    return sudo_run(
        [
            "systemd-cryptenroll",
            "--tpm2-device=auto",
            "--wipe-slot=tpm2",
            "--tpm2-pcrs=7",
            device,
        ]
    ).returncode


@log_all
def root_source_device() -> str:
    """Root filesystem source, unwrapped from its LUKS mapper name."""
    source = run(["findmnt", "-no", "SOURCE", "/"], capture=True).stdout.strip()
    if source.startswith("/dev/mapper/"):
        mapper_name = source[len("/dev/mapper/") :]
        # findmnt may append [/@] or similar mount suffixes to the mapper name.
        mapper_name = re.sub(r"\[.*$", "", mapper_name)
        # Resolve backing device via cryptsetup status (handles any mapper name).
        proc = sudo_run(["cryptsetup", "status", mapper_name], capture=True)
        for line in (proc.stdout or "").splitlines():
            if line.startswith("  device:"):
                dev = line.split(":", 1)[1].strip()
                if dev:
                    return dev
        # Fallback: try to unwrap from mapper name only if it ends with known suffixes.
        source = "/dev/" + mapper_name
        return re.sub(r"crypted$", "", source)
    return source


@log_all
def backing_disk(device: str) -> str:
    """Whole disk behind a partition: /dev/nvme0n1p2 -> /dev/nvme0n1.

    nvme namespace numbers are part of the disk name, so only a trailing "pN"
    (nvme/mmc) or a bare trailing digit on sd/vd/hd is a partition suffix.
    """
    if re.search(r"p\d+$", device):
        return re.sub(r"p\d+$", "", device)
    if re.match(r"^/dev/(nvme\d+n\d+|mmcblk\d+|sd[a-z]+|vd[a-z]+|hd[a-z]+)$", device):
        return device
    return re.sub(r"\d+$", "", device)


WHOLE_DISK_PATTERNS = (
    "/dev/sd?",
    "/dev/nvme?n?",
    "/dev/vd?",
    "/dev/hd?",
    "/dev/mmcblk?",
)


@log_all
def data_disk() -> str:
    """The encrypted data disk, discovered at runtime.

    The original hardcodes /dev/sda; here the first whole disk that is not the
    one holding the root filesystem is used, with /dev/sda as the fallback so
    behaviour is unchanged when nothing else is found.
    """
    root_disk = backing_disk(root_source_device())
    for pattern in WHOLE_DISK_PATTERNS:
        for dev in sorted(glob.glob(pattern)):
            if dev != root_disk:
                return dev
    return "/dev/sda"


@log_all
def setup_keyrings() -> None:
    sudo_run(["pacman-key", "--init"])
    print("Populating Arch Linux keys...")
    sudo_run(["pacman-key", "--populate", "archlinux", "blackarch", "athena"])
    for key in ("F0134EE680CAC571", "40DFB630FF42BCFFB047046CF0134EE680CAC571"):
        sudo_run(["pacman-key", "--recv-keys", key])
        sudo_run(["pacman-key", "--lsign-key", key])
    sudo_run(["pacman-key", "--finger", "F0134EE680CAC571"])
    if "omarchy" not in read_text("/etc/pacman.conf"):
        sudo_write(
            "/etc/pacman.conf",
            "[omarchy]\nServer = https://pkgs.omarchy.org/stable/$arch\n",
            append=True,
        )
    sudo_run(
        [
            "pacman",
            "-Syy",
            "--needed",
            "--noconfirm",
            "blackarch-keyring",
            "athena-keyring",
            "chaotic-keyring",
            "archlinux-keyring",
            "omarchy-keyring",
        ]
    )


@log_all
def setup_aur_tools() -> None:
    sudo_run(["pacman", "-S", "--needed", "--noconfirm", "yay"])
    run(["yay", "-S", "--needed", "--noconfirm", *AUR_TOOLS])


@log_all
def setup_hyprland_tools() -> None:
    sudo_run(
        [
            "pacman",
            "-S",
            "--needed",
            "--noconfirm",
            *DEV_TOOLS,
            *SYSTEM_PACKAGES,
            *SYSTEM_UTILITIES,
            *MY_UTILITIES,
            *OMARCHY_PKGS,
            *ATHENA_TOOLS,
            *HYPRLAND_PACKAGES,
        ]
    )
    run(["xdg-mime", "default", "kitty.desktop", "x-scheme-handler/terminal"])


@log_all
def setup_cyber_tools() -> None:
    role_files = sorted(glob.glob(f"{CYBER_ROLE_DIR}/*.role"))
    if role_files:
        for path in role_files:
            text = read_text(path)
            patched = re.sub(r"impacket.*", "impacket-ba", text)
            if patched != text:
                sudo_write(path, patched)
        run_shell("echo n | cyber-toolkit red")
        tools: list[str] = []
        for path in role_files:
            for line in read_text(path).splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "cuda" in line:
                    continue
                tools.append(line.split()[0])
        sudo_run(
            [
                "pacman",
                "-S",
                "--needed",
                "--noconfirm",
                *tools,
                *HACKING_TOOLS,
            ]
        )
    if not Path("/opt/username-anarchy").is_dir():
        sudo_run(
            [
                "git",
                "clone",
                "https://github.com/urbanadventurer/username-anarchy.git",
                "/opt/username-anarchy",
            ]
        )


@log_all
def setup_install() -> None:
    setup_keyrings()
    setup_hyprland_tools()
    setup_cyber_tools()


@log_all
def setup_sudo() -> None:
    """Write the user's sudoers drop-in."""
    target = blackarch_bin_dst()
    blackarch_bin = blackarch_bin_path() or target
    content = (
        f"{user_name()} ALL=(ALL:ALL) ALL\n"
        f"{user_name()} ALL=(ALL) NOPASSWD: SETENV: /usr/bin/pacman, /usr/sbin/env\n"
        f"{user_name()} ALL=(root) NOPASSWD: {blackarch_bin}/blackarch-dns Cloudflare, "
        f"{blackarch_bin}/blackarch-dns Google, {blackarch_bin}/blackarch-dns DHCP, "
        f"!{blackarch_bin}/asdcontrol\n"
        f"{user_name()} ALL=(root) NOPASSWD: {blackarch_bin}/asdcontrol "
        f"^--detect (/dev/(usb/)?hiddev[0-9]+)( /dev/(usb/)?hiddev[0-9]+)*$, "
        f"{blackarch_bin}/asdcontrol ^/dev/(usb/)?hiddev[0-9]+$, "
        f"{blackarch_bin}/asdcontrol ^/dev/(usb/)?hiddev[0-9]+ -- [+-]?[0-9]{{1,3}}%$, "
        f"{blackarch_bin}/blackarch-theme-set-browser-policy "
        f"[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f], "
        f"{blackarch_bin}/timedatectl ^set-timezone [A-Za-z0-9_+][A-Za-z0-9_+.-]*"
        f"(/[A-Za-z0-9_+][A-Za-z0-9_+.-]*)*$\n"
    )
    sudo_write(f"/etc/sudoers.d/00_{user_name()}", content)


@log_all
def setup_mount() -> None:
    """Mount and configure storage; device paths are discovered at runtime."""
    disk = data_disk()
    if not os.path.exists(disk):
        return
    if not Path("/dev/mapper/sdacrypted").exists():
        sudo_run(["cryptsetup", "open", disk, "sdacrypted"])

    def blkid_uuid(device: str) -> str:
        proc = run(["blkid", device], capture=True)
        match = re.search(r'UUID="([^"]+)"', proc.stdout or "")
        return match.group(1) if match else ""

    blkid = blkid_uuid(disk)
    blkcryptid = blkid_uuid("/dev/mapper/sdacrypted")

    if blkid and blkid not in read_text("/etc/crypttab"):
        sudo_write(
            "/etc/crypttab",
            f'sdacrypted UUID="{blkid}"    none    tpm2-device=auto\n',
            append=True,
        )
        print("Updated /etc/crypttab  details\n")
    if blkcryptid and blkcryptid not in read_text("/etc/fstab"):
        sudo_write(
            "/etc/fstab",
            f"UUID={blkcryptid}   /opt/BlackarchHacker/       btrfs   "
            f"rw,relatime,ssd,space_cache=v2,X-mount.mkdir    0 0\n",
            append=True,
        )
        print("Updated /etc/fstab  details\n")
    sudo_run(["mount", "-a"])


@log_all
def setup_luks_crypt_mount(lukscrypt: bool = False, device: str | None = None) -> None:
    """Configure LUKS crypt device mount; UUID discovered at runtime; mapper = luks-UUID."""
    # Discover device at runtime: argument, else backing disk from data_disk fallback
    if device and os.path.exists(device):
        target_device = device
    elif device and device.startswith("/dev/"):
        target_device = device
    else:
        target_device = data_disk()

    # Discover UUID at runtime from the actual device/partition
    proc = run(["blkid", "-U", target_device], capture=True)
    luks_uuid = proc.stdout.strip()
    if not luks_uuid:
        proc2 = run(["blkid", target_device], capture=True)
        match = re.search(r'UUID="([^"]+)"', proc2.stdout or "")
        if match:
            luks_uuid = match.group(1)
    # If still not found, fall back to backing device of target_device (partition -> disk)
    if not luks_uuid:
        backing_dev = backing_disk(target_device)
        if backing_dev != target_device:
            proc3 = run(["blkid", "-U", backing_dev], capture=True)
            luks_uuid = proc3.stdout.strip()
            if luks_uuid:
                target_device = backing_dev
            else:
                proc4 = run(["blkid", backing_dev], capture=True)
                match4 = re.search(r'UUID="([^"]+)"', proc4.stdout or "")
                if match4:
                    luks_uuid = match4.group(1)
                else:
                    luks_uuid = ""

    if not luks_uuid:
        print(
            f"[!] No UUID discovered for {target_device}; blkid -U and blkid returned empty. Not writing crypttab/fstab."
        )
        return

    # Use luks-UUID naming for device mapper
    mapper_name = f"luks-{luks_uuid}"
    mount_target = f"/run/media/black/luks-{luks_uuid}"

    # Ensure crypttab entry for tpm2; replace any existing entry for this mapper/UUID
    crypttab_path = "/etc/crypttab"
    crypttab_content = read_text(crypttab_path)
    crypttab_entry = f'{mapper_name} UUID="{luks_uuid}"    none    tpm2-device=auto\n'
    new_crypt_lines = []
    found = False
    for line in crypttab_content.splitlines():
        parts = line.split()
        if (
            parts
            and not line.startswith("#")
            and (parts[0] == mapper_name or f'UUID="{luks_uuid}"' in line)
        ):
            if not found:
                new_crypt_lines.append(crypttab_entry.rstrip())
                found = True
        else:
            new_crypt_lines.append(line)
    if not found:
        new_crypt_lines.append(crypttab_entry.rstrip())
    new_crypttab_content = "\n".join(new_crypt_lines)
    if new_crypttab_content != crypttab_content:
        sudo_write(crypttab_path, new_crypttab_content)
        print(f"Updated {crypttab_path} with tpm2 crypttab entry for {mapper_name}\n")

    # Open LUKS device if not already mapped
    mapper_path = f"/dev/mapper/{mapper_name}"
    if not Path(mapper_path).exists():
        blk_proc = run(["blkid", "-U", luks_uuid], capture=True)
        backing_device = blk_proc.stdout.strip()
        if backing_device and backing_device.startswith("/dev/"):
            sudo_run(["cryptsetup", "open", backing_device, mapper_name])
        else:
            sudo_run(["systemd-cryptsetup", "attach", luks_uuid, mapper_name, "none"])

    # Prefer mapper device UUID for fstab; fall back to mapper path if blkid is silent
    mapper_uuid = ""
    if Path(mapper_path).exists():
        mapper_uuid_proc = run(["blkid", "-U", mapper_path], capture=True)
        mapper_uuid = mapper_uuid_proc.stdout.strip()
        if not mapper_uuid:
            mapper_uuid_proc2 = run(["blkid", mapper_path], capture=True)
            match = re.search(r'UUID="([^"]+)"', mapper_uuid_proc2.stdout or "")
            if match:
                mapper_uuid = match.group(1)

    # Ensure mount point exists
    Path(mount_target).mkdir(parents=True, exist_ok=True)

    # Detect filesystem dynamically from mapped/backing device
    fs_type = "btrfs"
    mapped_device_for_fs = f"/dev/mapper/{mapper_name}"
    if Path(mapped_device_for_fs).exists():
        blk_fs = run(
            ["blkid", "-s", "TYPE", "-o", "value", mapped_device_for_fs], capture=True
        )
        detected = (blk_fs.stdout or "").strip()
        if detected:
            fs_type = detected
    else:
        # Try backing device via UUID
        blk_back = run(["blkid", "-U", luks_uuid], capture=True)
        backing_dev = blk_back.stdout.strip()
        if backing_dev:
            blk_fs_back = run(
                ["blkid", "-s", "TYPE", "-o", "value", backing_dev], capture=True
            )
            detected_back = (blk_fs_back.stdout or "").strip()
            if detected_back:
                fs_type = detected_back

    # Must have fstab entry set using the mapped device identity, not the backing block UUID
    fstab_path = "/etc/fstab"
    fstab_content = read_text(fstab_path)
    fstab_source = (
        f"UUID={mapper_uuid}" if mapper_uuid else f"/dev/mapper/{mapper_name}"
    )
    fstab_opts = (
        "rw,relatime,ssd,space_cache=v2,X-mount.mkdir"
        if fs_type == "btrfs"
        else "defaults"
    )
    fstab_line = f"{fstab_source}   {mount_target}   {fs_type}   {fstab_opts}    0 2\n"

    # Replace all existing fstab entries for this mount target; keep exactly one
    new_lines = []
    seen = False
    for line in fstab_content.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == mount_target and not line.startswith("#"):
            if not seen:
                new_lines.append(fstab_line.rstrip())
                seen = True
        else:
            new_lines.append(line)
    if not seen:
        new_lines.append(fstab_line.rstrip())
    new_content = "\n".join(new_lines)
    if new_content != fstab_content:
        sudo_write(fstab_path, new_content)
        print(f"Updated {fstab_path} with mapper UUID for {mount_target}\n")

    # Mount if not already mounted
    mount_proc = run(["findmnt", "-no", "SOURCE,TARGET", mount_target], capture=True)
    if mount_target not in (mount_proc.stdout or ""):
        mapped_device = f"/dev/mapper/{mapper_name}"
        if Path(mapped_device).exists():
            sudo_run(["mount", mapped_device, mount_target])


@log_all
def setup_tpm(extra: list[str] | None = None) -> None:
    """TPM enrolment for the LUKS-encrypted root disk and the data disk."""

    def add_crypttab_for(device: str) -> None:
        proc = run(["blkid", "-U", device], capture=True)
        uuid = proc.stdout.strip()
        if not uuid:
            proc2 = run(["blkid", device], capture=True)
            match = re.search(r'UUID="([^"]+)"', proc2.stdout or "")
            if match:
                uuid = match.group(1)
        if not uuid:
            return
        crypttab_path = "/etc/crypttab"
        crypttab_content = read_text(crypttab_path)
        mapper_name = f"luks-{uuid}"
        entry_line = f'{mapper_name} UUID="{uuid}"    none    tpm2-device=auto\n'
        lines = crypttab_content.splitlines()
        new_lines = [l for l in lines if not l.startswith(mapper_name + " ")]
        new_lines.append(entry_line.rstrip("\n"))
        sudo_write(crypttab_path, "\n".join(new_lines) + "\n")
        print(f"Updated {crypttab_path} with tpm2 crypttab entry for {mapper_name}\n")

    if extra and extra[0]:
        device = extra[0]
        enroll_without_pubkey(device)
        root_dev = root_source_device()
        if device != root_dev:
            add_crypttab_for(device)
            import subprocess as _sp

            _u = _sp.run(
                ["blkid", "-s", "UUID", "-o", "value", device],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not _u:
                _m = __import__("re").search(
                    r'UUID="([^"]+)"',
                    _sp.run(["blkid", device], capture_output=True, text=True).stdout
                    or "",
                )
                _u = _m.group(1) if _m else ""
            if _u:
                _fstab = read_text("/etc/fstab")
            _lines = [
                l for l in _fstab.splitlines() if f"/dev/mapper/luks-{_u}" not in l
            ]
            _lines.append(
                f"/dev/mapper/luks-{_u}  /run/media/black/luks-{_u}  auto  rw,X-mount.mkdir,user,nofail  0  0"
            )
            sudo_write("/etc/fstab", "\n".join(_lines) + "\n")
        return
    root_dev = root_source_device()
    enroll_without_pubkey(root_dev)
    # Crypttab entry intentionally excluded for root device
    data_dev = data_disk()
    enroll_without_pubkey(data_dev)
    add_crypttab_for(data_dev)
    # fstab entry for data disk (manual mount, user-mountable)
    import re as _re
    import subprocess as _sp

    _u = _sp.run(
        ["blkid", "-s", "UUID", "-o", "value", data_dev], capture_output=True, text=True
    ).stdout.strip()
    if not _u:
        _m = _re.search(
            r'UUID="([^"]+)"',
            _sp.run(["blkid", data_dev], capture_output=True, text=True).stdout or "",
        )
        _u = _m.group(1) if _m else ""
    if _u:
        _fstab = read_text("/etc/fstab")
        _lines = [l for l in _fstab.splitlines() if f"/dev/mapper/luks-{_u}" not in l]
        _lines.append(
            f"/dev/mapper/luks-{_u}  /run/media/black/luks-{_u}  auto  noauto,user,nofail  0  0"
        )
        sudo_write("/etc/fstab", "\n".join(_lines) + "\n")


@log_all
def setup_post_config() -> None:
    # setup_tpm(None)
    blackarch_flatpak_ulaa()
    desktop = Path("/usr/share/applications/blackarch-webapp.desktop")
    sudo_write(
        desktop,
        "[Desktop Entry]\nType=Application\nName=Blackarch WebApp\n"
        "Exec=blackarch webapp %u\n"
        "MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;\n",
    )
    run(
        [
            "xdg-mime",
            "default",
            "blackarch-webapp.desktop",
            "x-scheme-handler/http",
            "x-scheme-handler/https",
        ]
    )
    run(["xdg-settings", "set", "default-web-browser", BROWSER])
    setup_kodachi()

    # smartthings installation
    if not have("smartthings"):
        install_smartthings()

    # webcam setup if IPU6 device present
    if Path("/dev/video0").exists():
        # run(["/opt/blackarch/bin/blackarch-webcam-setup", "--ipu6"])
        sudo_run(["/opt/blackarch/galaxybook-camera/galaxybook-camera-fix.sh"])
        sudo_run(["/opt/blackarch/galaxybook-camera/reapply-flicker-fix.sh"])
    sudo_write(
        "/etc/NetworkManager/conf.d/NetworkManager.conf",
        "[device]\n  wifi.backend=iwd\n",
    )
    sudo_write(
        "/etc/iwd/main.conf",
        "[General]\n  EnableNetworkConfiguration=true\n\n"
        "[Network]\n  NameResolvingService=systemd\n",
    )
    resolved = Path("/etc/systemd/resolved.conf")
    if resolved.exists():
        text = resolved.read_text()
        text = re.sub(r"^#DNS=.*$", "DNS=1.1.1.1 9.9.9.9", text, flags=re.M)
        text = re.sub(r"^#FallbackDNS=.*$", "FallbackDNS=", text, flags=re.M)
        sudo_write(resolved, text)
    sudo_run(["systemctl", "disable", "--now", "wpa_supplicant.service"])
    sudo_run(
        ["systemctl", "enable", "--now", "systemd-resolved", "iwd", "NetworkManager"]
    )
    sudo_run(["systemctl", "restart", "NetworkManager.service", "systemd-resolved"])
    time.sleep(3)
    sudo_run(["ln", "-sf", "/run/systemd/resolve/stub-resolv.conf", "/etc/resolv.conf"])
    if not Path.home().joinpath(".ssh").exists():
        os.symlink("/opt/BlackarchHacker/.ssh", str(Path.home() / ".ssh"))
    run(["systemctl", "--user", "daemon-reexec"])
    run(
        [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "battery-alert.timer",
            "hyprpolkitagent",
        ]
    )


@log_all
def setup_dotfiles() -> None:
    standard_apps = (
        "qt5ct qt6ct hypr xdg-desktop-portal kitty starship tmux nvim yazi yt-dlp mpv "
        "xsettingsd burpsuite cliamp"
    ).split()
    shared_apps = "easyeffects color-schemes nwg-look".split()
    profile_apps = [
        ".gitconfig",
        ".bash_profile",
        ".bashrc",
        ".profile",
        ".zprofile",
        ".zshrc",
    ]

    systemd_target = Path.home() / ".config/systemd"
    user_dir = systemd_target / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    for item in (Path(DEFAULTS_DIR) / "config/systemd/user").glob("*"):
        if not (user_dir / item.name).exists():
            shutil.copy2(item, user_dir / item.name)

    brave = Path.home() / ".config/BraveSoftware"
    if not brave.exists():
        brave.mkdir(parents=True, exist_ok=True)
        os.symlink(
            str(Path.home() / ".var/app/com.ulaa.Ulaa/cache/Zoho/Ulaa"),
            str(brave / "Brave-Browser"),
        )

    print("--- Deploying profile Configs ---")
    link_configs(f"{DEFAULTS_DIR}/home", str(Path.home()), profile_apps)

    print("--- Deploying Standard Configs ---")
    link_configs(f"{DEFAULTS_DIR}/config", str(Path.home() / ".config"), standard_apps)

    print("--- Deploying Shared Configs ---")
    link_configs(
        f"{DEFAULTS_DIR}/share", str(Path.home() / ".local/share"), shared_apps
    )

    user_systemd = Path.home() / ".config/systemd/user"
    user_systemd.mkdir(parents=True, exist_ok=True)
    for _unit in ("battery-alert.service", "battery-alert.timer"):
        _src = Path(DEFAULTS_DIR) / "config/systemd/user" / _unit
        _dst = user_systemd / _unit
        if _src.exists() and not _dst.exists():
            shutil.copy2(_src, _dst)
    run(["systemctl", "--user", "daemon-reexec"])
    run(["systemctl", "--user", "enable", "--now", "battery-alert.timer"])


@log_all
def setup_xdg_mime() -> None:
    desktop_path = Path.home() / ".local/share/applications/blackarch-webapp.desktop"
    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    desktop_path.write_text(
        "[Desktop Entry]\n"
        "Name=BlackArch WebApp Handler\n"
        "Comment=Open URLs using BlackArch webapp execution script\n"
        "Exec=/opt/blackarch/bin/blackarch webapp %u\n"
        "Terminal=false\n"
        "Type=Application\n"
        "MimeType=x-scheme-handler/http;x-scheme-handler/https;\n"
        "Categories=Network;\n",
        encoding="utf-8",
    )
    run(["xdg-mime", "default", "blackarch-webapp.desktop", "x-scheme-handler/http"])
    run(["xdg-mime", "default", "blackarch-webapp.desktop", "x-scheme-handler/https"])
    print("xdg-mime webapp handler configured")


@log_all
def setup_battery_threshold(threshold: int = 100) -> None:
    path = "/sys/class/power_supply/BAT1/charge_control_end_threshold"
    if not os.path.exists(path):
        warn("charge_control_end_threshold not supported on this battery")
        return
    try:
        with open(path, "w") as f:
            f.write(str(threshold))
        ok(f"battery charge end threshold set to {threshold}%")
    except PermissionError:
        sudo_run(["bash", "-c", f"echo {threshold} > {path}"])
        ok(f"battery charge end threshold set to {threshold}%")


@log_all
def virtualbox_setup() -> None:
    if (
        sudo_run(
            ["pacman", "-S", "--noconfirm", "--needed", "virtualbox-kvm"]
        ).returncode
        != 0
    ):
        sudo_run(["pacman", "-S", "--noconfirm", "--needed", "virtualbox"])
    sudo_run(["usermod", "-aG", "vboxusers", user_name()])
    sudo_run(["modprobe", "vboxdrv"])
    sudo_run(["modprobe", "-a", "vboxguest", "vboxsf", "vboxvideo"])


@log_all
def kvm_setup() -> None:
    sudo_run(
        [
            "pacman",
            "-S",
            "--noconfirm",
            "--needed",
            "qemu",
            "qemu-img",
            "virt-manager",
            "seabios",
        ]
    )


@log_all
def install_smartthings() -> None:
    if have("smartthings"):
        return
    tmp = Path("/tmp/smartthings-linux-x64.tgz")
    run(["wget", "-c", "-O", str(tmp), SMARTTHINGS_TGZ])
    sudo_run(["tar", "-xvf", str(tmp), "-C", "/usr/bin"])


@log_all
def setup_kodachi() -> None:
    sudo_run(
        [
            "curl",
            "-sSL",
            "https://kodachi.cloud/apps/os/install/kodachi-deps-install.sh",
            "|",
            "bash",
        ]
    )
    sudo_run(
        [
            "curl",
            "-sSL",
            "https://kodachi.cloud/apps/os/install/kodachi-binary-install.sh",
            "|",
            "bash",
        ]
    )


@log_all
def setup_hermes(conf):
    logger.info("setup_hermes: called", extra={"command": "setup_hermes"})
    match conf:
        case "install" | "update":
            cmd = f"curl -fsSL {HERMES_INSTALL} | sh"
            # sudo_run(["bash", "-c", cmd])
            run_shell(cmd)
        case _:
            run_shell("hermes config set skills.create_dir /opt/blackarch/agent-skills")
            run_shell(
                'hermes config set skills.external_dirs \'["/opt/blackarch/agent-skills"]'
            )
            run_shell("hermes config set skills.project_discovery false")


@log_all
def print_help_setup() -> None:
    print("Usage: blackarch setup <subcommand>")
    print(
        "Subcommands: keyrings, sudo, tpm, mount, profile, dotfiles, virtualbox, kvm, ollama, hermes, kodachi, xdg-mime, aur, hyprland, cyber, post, smartthings, lukscrypt, battery-threshold, install"
    )


@log_all
def setup_dispatch(argv: Sequence[str]) -> int:
    sub = argv[0] if argv else ""
    if sub == "keyrings":
        setup_keyrings()
    elif sub == "sudo":
        setup_sudo()
    elif sub == "tpm":
        setup_tpm(argv[1:] if len(argv) > 1 else None)
    elif sub == "install":
        setup_install()
    elif sub == "aur":
        setup_aur_tools()
    elif sub == "hyprland":
        setup_hyprland_tools()
    elif sub.startswith("cyber"):
        setup_cyber_tools()
    elif sub == "post":
        setup_post_config()
    elif sub == "dotfiles":
        setup_dotfiles()
    elif sub == "mount":
        setup_mount()
    elif sub == "profile":
        write_profile_d()
    elif sub == "virtualbox":
        virtualbox_setup()
    elif sub == "kvm":
        kvm_setup()
    elif sub == "ollama":
        cmd = f"curl -fsSL {OLLAMA_INSTALL} | sh"
        sudo_run(["bash", "-c", cmd])
    elif sub == "hermes":
        setup_hermes(sys.argv[2:])
    elif sub == "kodachi":
        setup_kodachi()
    elif sub == "lukscrypt" or sub == "luks":
        lukscrypt_param = len(argv) > 1 and argv[1] in (
            "lukscrypt",
            "True",
            "true",
            "1",
        )
        device_arg = (
            argv[1]
            if len(argv) > 1 and argv[1] not in ("lukscrypt", "True", "true", "1")
            else None
        )
        setup_luks_crypt_mount(lukscrypt=lukscrypt_param, device=device_arg)
    elif sub == "xdg-mime" or sub == "xdgmime":
        setup_xdg_mime()
    elif sub == "battery-threshold" or sub == "charge-threshold":
        thr = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 100
        setup_battery_threshold(thr)
    else:
        print_help_setup()
    return 0


@dataclass
class WindowRing:
    """Single-file window address ring."""

    base_file: str
    max_slots: int = MAX_SLOTS

    def _path(self) -> str:
        return self.base_file

    def read_all(self) -> list[str]:
        try:
            text = Path(self._path()).read_text(encoding="utf-8")
        except OSError:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    def write_all(self, addrs: list[str]) -> None:
        Path(self._path()).parent.mkdir(parents=True, exist_ok=True)
        Path(self._path()).write_text(
            "\n".join(addrs) + ("\n" if addrs else ""), encoding="utf-8"
        )

    def slots(self) -> list[str]:
        return self.read_all()

    def _remove_file(self) -> None:
        try:
            os.remove(self._path())
        except OSError:
            pass

    def clear_slot(self, slot: int) -> None:
        self._remove_file()

    def cleanup_closed_windows(self) -> None:
        self.write_all([a for a in self.read_all() if is_window_alive(a)])

    def is_duplicate_address(self, target: str, ignore_slot: int = 0) -> bool:
        return target in self.read_all()

    def clipboard(self) -> None:
        browser = shlex.split(browser_exec())
        self.cleanup_closed_windows()
        url = run(["wl-paste"], capture=True).stdout.strip()
        if not _URL_RE.match(url):
            return
        pattern = webapp_id(url)
        address = get_window_address(pattern)
        if not address:
            subprocess.Popen(
                [
                    *browser,
                    *sandbox_args(),
                    "--profile-directory=Default",
                    f"--app={url}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(20):
                time.sleep(0.2)
                address = get_window_address(pattern)
                if address:
                    break
        if not address:
            return
        addrs = self.read_all()
        if address in addrs:
            focus_window(address)
            return
        if len(addrs) < self.max_slots:
            addrs.append(address)
            notify("Clipboard WebApp", f"Auto-saved (slot {len(addrs)}).")
        else:
            addrs = [address] + addrs[:-1]
            notify("Clipboard WebApp", "Slots full. Shifted to front.")
        self.write_all(addrs)
        focus_window(address)

    def swap(self) -> None:
        self.cleanup_closed_windows()
        addrs = self.read_all()
        if not addrs:
            return
        if len(addrs) > 1:
            addrs = addrs[1:] + addrs[:1]
            self.write_all(addrs)
        focus_window(addrs[0])

    def save(self, slot: int) -> None:
        self.cleanup_closed_windows()
        active = get_active_class()
        if not active:
            sys.exit(1)
        if active in self.read_all():
            notify("Window Manager", "Error: Window already saved.")
            sys.exit(1)
        addrs = self.read_all()
        if len(addrs) >= self.max_slots:
            addrs = [active] + addrs[:-1]
        else:
            addrs.append(active)
        self.write_all(addrs)
        notify("Window Manager", f"Saved ({len(addrs)}).")

    def clear(self) -> None:
        self._remove_file()
        notify("Window Rotation", "All slots cleared.")


@log_all
def window_dispatch(argv: Sequence[str]) -> int:
    """`blackarch window <clipboard|swap|saveN|clear> [base]`."""
    cmd = argv[0] if argv else "swap"
    base = argv[1] if len(argv) > 1 else "/tmp/modWin"
    ring = WindowRing(base_file=base)
    if cmd == "clipboard":
        ring.clipboard()
    elif cmd in ("swap", ""):
        ring.swap()
    elif re.fullmatch(r"save\d+", cmd):
        ring.save(int(cmd[4:]))
    elif cmd == "clear":
        ring.clear()
    else:
        print(f"Usage: blackarch [clipboard|swap|save1..save{ring.max_slots}|clear]")
    return 0


@log_all
def blackarch_hyprlock() -> None:
    logger.info("hyprlock: lock screen triggered", extra={"command": "hyprlock"})

    run(["pkill", "-f", "org.blackarch.screensaver"])

    is_locked_str = run(["hyprctl", "--instance", "0", "locked"], capture=True)
    if is_locked_str.stdout.strip() == "true":
        run(["pkill", "hyprlock"])

        clear_cmd = [
            "hyprctl",
            "--instance",
            "0",
            "eval",
            "hl.clear_crashed_lockscreen()",
        ]
        is_crashed_clear = run(clear_cmd, capture=True)
        print("crashed clear: ", is_crashed_clear)
    else:
        pid_check = run(["pidof", "hyprlock"], capture=True).returncode
        if pid_check != 0:
            subprocess.Popen(
                ["hyprlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )


@log_all
def blackarch_suspend() -> None:
    logger.info("suspend: suspend triggered", extra={"command": "suspend"})
    laptop_charge("off")
    blackarch_hyprlock()
    run(["systemctl", "suspend"])
    laptop_charge("on")
    blackarch_brightness("unlock")


@log_all
def blackarch_flatpak_ulaa() -> None:
    run(["flatpak", "install", "--noninteractive", "com.ulaa.Ulaa"])


@log_all
def audio_notify() -> None:
    logger.info("audio: notify triggered", extra={"command": "audio"})
    proc = run(["pamixer", "--get-volume"], capture=True)
    vol = proc.stdout.split()[0] if proc.returncode == 0 and proc.stdout else "0"
    run(["pamixer", "--get-mute"], capture=True)
    notify_replace(
        "/tmp/audio_id",
        "Volume",
        f"{vol}%",
        app_name="Volume",
        icon="audio-volume-muted-symbolic",
        default_id=2000,
    )


@log_all
def brightness_percent() -> int:
    val = int(run(["brightnessctl", "g"], capture=True).stdout.strip() or 0)
    maximum = int(run(["brightnessctl", "m"], capture=True).stdout.strip() or 1)
    return val * 100 // maximum if maximum else 0


@log_all
def brightness_notify(screen: str, keyboard: str) -> None:
    run(["brightnessctl", "set", str(screen)])
    if E.get("KBD_DEVICE"):
        run(["brightnessctl", f"--device={E['KBD_DEVICE']}", "set", str(keyboard)])
    notify_replace(
        "/tmp/brightness_id",
        "backlight",
        f"{brightness_percent()}%",
        app_name="Backlight",
        icon="display-brightness-symbolic",
        default_id=1000,
    )


@log_all
def kbd_device() -> str:
    proc = run(["brightnessctl", "--list"], capture=True)
    for line in (proc.stdout or "").splitlines():
        if "kbd" in line.lower():
            match = re.search(r"'([^']+)'", line)
            if match:
                return match.group(1)
    return ""


DIM_SCREEN, DIM_KBD = 20, 1
WORK_SCREEN, WORK_KBD = 200, 3


@log_all
def blackarch_brightness(mode: str = "toggle") -> None:
    logger.info("brightness: mode=%s", mode, extra={"command": "brightness"})
    E["KBD_DEVICE"] = kbd_device()
    current = int(run(["brightnessctl", "g"], capture=True).stdout.strip() or 0)
    if mode in ("up", "+"):
        brightness_notify("+5%", "+1")
    elif mode in ("down", "-"):
        kb = "1-" if brightness_percent() < 15 else "3"
        brightness_notify("5%-", kb)
    elif mode == "lock":
        blackarch_hyprlock()
        blackarch_brightness("unlock")
    elif mode == "unlock":
        brightness_notify(WORK_SCREEN, WORK_KBD)
    elif mode == "low":
        brightness_notify(DIM_SCREEN, DIM_KBD)
    elif mode == "off":
        brightness_notify(0, 0)
    elif mode == "suspend":
        blackarch_suspend()
    elif mode == "toggle":
        blackarch_brightness("low" if current > DIM_SCREEN else "unlock")


@log_all
def audio_dispatch(sub: str) -> None:
    if sub in ("-h", "--help", ""):
        print("audio subcommands: up, down, mute, mic")
        return
    if sub == "up":
        if (
            run(
                ["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", "5%+"]
            ).returncode
            != 0
        ):
            run(["pamixer", "-i", "5"])
    elif sub == "down":
        if run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]).returncode != 0:
            run(["pamixer", "-d", "5"])
    elif sub == "mute":
        if run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]).returncode != 0:
            run(["pamixer", "-t"])
    elif sub == "mic":
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"])
    audio_notify()


@log_all
def laptop_charge(state: str = "on") -> None:
    run(["smartthings", "devices:commands", DEVICE_ID, f"switch:{state}"])


@log_all
def toggle_laptop_charger(state: str = "on") -> None:
    if get_device_status_value(LOCATION_ID) == 100:
        run(["smartthings", "devices:commands", DEVICE_ID, f"switch:{state}"])
        notify("Smartthings", f"charger turned {state}")


@log_all
def smartthings_json(args: Sequence[str]) -> Any:
    proc = run(["smartthings", "devices", "--status", "-j", *args], capture=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


@log_all
def _capability_status(device: dict, capability: str, field: str) -> Any:
    """Read .components[main].capabilities[capability].status.<field>."""
    for component in device.get("components", []):
        if component.get("id") != "main":
            continue
        for cap in component.get("capabilities", []):
            if cap.get("id") == capability:
                return (cap.get("status") or {}).get(field)
    return None


@log_all
def get_device_status_value(location_id: str) -> int:
    data = smartthings_json(["-d", location_id])
    if not isinstance(data, list):
        return 0
    for device in data:
        value = _capability_status(device, "switchLevel", "level")
        if value is not None:
            return value.get("value", 0)
    return 0


@log_all
def get_device_status() -> list[dict]:
    data = smartthings_json([])
    devices = []
    if not isinstance(data, list):
        return devices
    for device in data:
        name = device.get("label", "")
        if "switchs13" in name or name == "Master Switch":
            continue
        devices.append(
            {
                "name": name,
                "id": device.get("deviceId", ""),
                "status": (_capability_status(device, "switch", "switch") or {}).get(
                    "value", ""
                ),
                "type": device.get("type", ""),
            }
        )
    return devices


@log_all
def toggle_status(filter_value: str) -> None:
    devs = [
        d
        for d in get_device_status()
        if re.search(filter_value, f"{d['name']} {d['id']}", re.IGNORECASE)
    ]
    if not devs:
        return
    if filter_value == filter_value.split("-")[-1] and len(devs) > 1:
        chosen = menu_select(
            "Smartthings",
            [f"{d['name']} => {d['id']}" for d in devs],
            width=800,
            height=500,
        )
        if chosen is None:
            return
        devs = [d for d in devs if f"{d['name']} => {d['id']}" == chosen]
    device = devs[0]
    status = "off" if device["status"] == "on" else "on"
    print(f"{device['name']} => {device['id']} => {device['type']} => {status}")
    if status == "on" and device["type"] != "VIPER":
        levels = (
            "1\n2\n3\n4\n5\n11\n12\n13\n14\n15\n16\n21\n22\n23\n31\n32\n33\n34\n41\n42\n43\n44\n"
            "51\n52\n53\n54\n55\n100\n50\n0"
        )
        chosen = menu_select("Smartthings", levels.split(), width=800, height=500)
        if chosen:
            run(
                [
                    "smartthings",
                    "devices:commands",
                    device["id"],
                    f"switchLevel:setLevel({chosen})",
                ]
            )
    run(["smartthings", "devices:commands", device["id"], f"switch:{status}"])
    notify("Smartthings", f"{device['name']} turned {status}")


@log_all
def smartthings_dispatch(argv: Sequence[str]) -> int:
    if argv and argv[0] == "--complete":
        for c in ["install", "menu", "status", "value", "widget"]:
            print(c)
        return 0
    sub = argv[0] if argv else ""
    if sub == "install":
        install_smartthings()
        return 0
    if sub == "menu":
        run(["blackarch", "toggle", "smartthings"])
        return 0
    elif sub == "status":
        for device in get_device_status():
            print(
                f"{device['name']} => {device['status']} => {device['id']} => {device['type']}"
            )
    elif sub == "value":
        print(get_device_status_value(LOCATION_ID))
    elif sub == "widget":
        plugins = run(["blackarch-shell", "shell", "listPlugins"], capture=True).stdout
        try:
            enabled = next(
                p["enabled"]
                for p in json.loads(plugins)
                if p.get("id") == "blackarch.smartthings"
            )
        except (json.JSONDecodeError, StopIteration, TypeError):
            enabled = None
        if enabled is True:
            run(["blackarch", "plugin", "disable", "blackarch.smartthings"])
            notify("SmartThings", "disabled", replaces_id=2001)
        else:
            run(["blackarch", "plugin", "enable", "blackarch.smartthings"])
            run(["blackarch-shell", "shell", "toggle", "blackarch.smartthings"])
    elif "-" in sub:
        toggle_status(sub)
    else:
        print(
            "smartthings app is available with below options only\n"
            "        menu - to launch quikshell menu\n"
            "        filter - can be name or device ID to filter and toggle status of the device"
        )
    return 0


@log_all
def toggle_vpn() -> None:
    proc = run(
        ["nmcli", "-f", "NAME,TYPE", "connection", "show", "--active"], capture=True
    )
    active = next(
        (
            line.split()[0]
            for line in (proc.stdout or "").splitlines()
            if "vpn" in line.lower()
        ),
        "",
    )
    if active:
        run(["nmcli", "connection", "down", active])
        notify("VPN", f"{active} disconnected")
        return
    proc = run(["nmcli", "-f", "NAME,TYPE", "connection", "show"], capture=True)
    names = [
        line.split()[0]
        for line in (proc.stdout or "").splitlines()
        if "vpn" in line.lower()
    ]
    chosen = menu_select("Smartthings", names, width=800, height=500)
    if chosen:
        sudo_run(["nmcli", "connection", "up", chosen])


@log_all
def touch_enabled() -> bool:
    match = re.search(r"touch_enabled\s*=\s*(\S+)", read_text(HYPR_MONITOR_LUA))
    return bool(match and match.group(1) not in ("0", "false", "nil"))


@log_all
def touchscreen_persist(enabled: bool) -> None:
    """Persist the touchscreen's enabled state where the config reads it.

    monitor.lua derives `touch_enabled` from this file at every config eval, and
    blackarch-toggle-input-device writes it too, so it is the single source of
    truth -- a writer that edits `touch_enabled` in monitor.lua directly is
    overwritten on the next eval. The file's contents are the device name, which
    the re-apply module needs in order to address the device.
    """
    if enabled:
        try:
            TOUCHSCREEN_DISABLED_FILE.unlink()
        except OSError:
            pass
        return

    TOGGLE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    match = re.search(r"touch_input\s*=\s*\"([^\"]+)\"", read_text(HYPR_MONITOR_LUA))
    write_text(TOUCHSCREEN_DISABLED_FILE, f"{match.group(1) if match else ''}\n")


@log_all
def blackarch_virtualkeyboard(mode: str = "auto") -> int:
    def running() -> bool:
        return run(["pgrep", "-x", WVKBD_BIN], capture=True).returncode == 0

    log_path = f"{runtime_dir()}/wvkbd.log"
    if mode == "auto":
        if running():
            return 0
        with open(log_path, "a") as log:
            subprocess.Popen(
                [WVKBD_BIN, "--auto", "--hidden", *WVKBD_ARGS],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
    elif mode == "toggle":
        blackarch_virtualkeyboard("show" if touch_enabled() else "hide")
    elif mode == "show":
        if not running():
            with open(log_path, "a") as log:
                subprocess.Popen(
                    [WVKBD_BIN, "--auto", *WVKBD_ARGS],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        run(["pkill", "-USR2", "-x", WVKBD_BIN])
    elif mode == "hide":
        run(["pkill", "-USR1", "-x", WVKBD_BIN])
    elif mode == "stop":
        run(["pkill", "-x", WVKBD_BIN])
        touchscreen_persist(False)
        for pid in run(
            ["pgrep", "-f", "touchscreen_orientation"], capture=True
        ).stdout.split():
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
    else:
        print("usage: wvkbd-launcher {auto|toggle|show|hide|stop}", file=sys.stderr)
        return 2
    return 0


ORIENTATIONS = (
    ("normal", 0, "Normal"),
    ("left-up", 1, "Left"),
    ("bottom-up", 2, "Bottom"),
    ("right-up", 3, "Right"),
)


@log_all
def touch_screen_orientation() -> None:
    if not have("jq"):
        sys.exit("Error: 'jq' is required to parse monitor data. Please install it.")
    monitors = hyprctl_json(["monitors"]) or []
    focused = next((m for m in monitors if m.get("focused")), None)
    if not focused:
        return
    name = focused.get("name")
    res = f"{focused.get('width')}x{focused.get('height')}@{focused.get('refreshRate')}"

    def apply_rotation(transform: int, label: str, touch_status: int = 1) -> None:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] {label:<10} -> Transform: {transform}"
        )
        lua = Path(HYPR_MONITOR_LUA)
        if not lua.exists():
            return
        text = lua.read_text()
        text = re.sub(r"monitor_output\s*=.*", f'monitor_output = "{name}"', text)
        text = re.sub(
            r"monitor_transform\s*=.*", f"monitor_transform = {transform}", text
        )
        write_text(lua, text)
        touchscreen_persist(touch_status == 1)

    print(f"Monitoring {name} at {res}...")
    proc = subprocess.Popen(["monitor-sensor"], stdout=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if "Accelerometer orientation changed" not in line:
                continue
            orientation = line.split(": ", 1)[-1].strip()
            for key, transform, label in ORIENTATIONS:
                if orientation == key:
                    apply_rotation(transform, label)
    except KeyboardInterrupt:
        proc.terminate()


@log_all
def generate_menu() -> None:
    """Build additional-menu.jsonc from the cyber-toolkit role files."""
    entries: dict[str, dict] = {}
    for path in sorted(glob.glob(f"{CYBER_ROLE_DIR}/*.role")):
        team = Path(path).stem
        entries[f"blackarch.pentest.{team}"] = {
            "icon": ICON_PENTEST,
            "label": team.upper(),
            "aliases": ["app", "applications"],
            "provider": "apps",
        }
        for line in read_text(path).splitlines():
            line = re.sub(r"(%|null)\s*$", "", line).strip()
            if not line or line.startswith("#") or "cuda" in line:
                continue
            tool = line.split()[0]
            entries[f"blackarch.pentest.{team}.{tool}"] = {
                "icon": ICON_PENTEST,
                "label": tool,
                "when": f"blackarch-cmd-present {tool}",
                "action": f"blackarch {tool}",
            }
    for device in get_device_status():
        entries[f"smartthings.{device['id']}"] = {
            "icon": ICON_DEVICE,
            "label": device["name"],
            "action": f"blackarch smartthings {device['id']}",
        }
    write_text(
        ADDITIONAL_MENU, json.dumps(entries, indent=2, ensure_ascii=False) + "\n"
    )


@log_all
def quickshell_dispatch(argv: Sequence[str]) -> int:
    sub = argv[0] if argv else ""
    arg = argv[1] if len(argv) > 1 else ""
    menus = {
        "apps": "apps",
        "root": "root",
        "blackarch": "blackarch",
        "academy": "blackarch.webapp.learn.academy",
        "pentest": "blackarch.pentest",
        "favorite": "blackarch.favorite",
        "smartthings": "smartthings",
        "learn": "blackarch.webapp.learn",
    }
    if sub == "generate":
        generate_menu()
        print("menu generated successfully")
    elif sub in menus:
        run(
            [
                "blackarch-shell",
                "shell",
                "toggle",
                "blackarch.menu",
                json.dumps({"menu": menus[sub]}),
            ]
        )
    elif sub == "touchscreen_orientation":
        touch_screen_orientation()
    elif sub == "virtualkeyboard":
        return blackarch_virtualkeyboard(arg or "auto")
    elif sub == "background":
        bg = run(["blackarch", "theme", "bg-switcher"], capture=True)
        run(["blackarch", "theme", "bg", "set", bg.stdout.strip()])
    elif sub == "theme":
        run(["blackarch", "theme", "switcher"])
    return 0


@log_all
def blackarch_update() -> None:
    sync_dir = Path("/var/lib/pacman/sync")
    threshold = 21600  # 6 hours
    dbs = ("extra.db", "core.db", "blackarch.db")
    should_update = True
    for db in dbs:
        path = sync_dir / db
        if not path.exists() or time.time() - path.stat().st_mtime >= threshold:
            should_update = True
            break
        should_update = False
    if should_update:
        print("Databases are old, syncing now...")
        if run(["pgrep", "-l", "pacman"], capture=True).returncode == 0:
            time.sleep(15)
        sudo_run(["pacman", "-Syyu", "--noconfirm", "--needed"])
    else:
        print("Databases are sufficiently fresh. Skipping sync.")
    print(f"\nUpdate system packages - {user_name()}")
    while run(["pgrep", "-l", "pacman"], capture=True).returncode == 0:
        time.sleep(5)
    sudo_run(["pacman", "-Su", "--noconfirm"])
    if sudo_run(["pacman", "-Qem"], capture=True).returncode == 0:
        print("\nUpdate AUR packages")
        run(["yay", "-Syua", "--noconfirm"])
    orphans = sudo_run(["pacman", "-Qtdq"], capture=True).stdout.split()
    if orphans:
        print("\nRemove orphan system packages")
        for pkg in orphans:
            sudo_run(["pacman", "-Rs", "--noconfirm", pkg])
        print()


@log_all
def resolve_gui(argv: Sequence[str]) -> tuple[str, str]:
    """Map a GUI request to (app_id, command)."""
    joined = " ".join(argv)
    if "nvim" in joined:
        return "org.blackarch.nvim", f"kitty --app-id=org.blackarch.nvim -e {joined}"
    if "kitty" in joined:
        return "kitty", "kitty"
    if "obsidian" in joined:
        return "obsidian$", f"obsidian -disable-gpu --enable-wayland-ime {joined}"
    if "aquamarine" in joined:
        return (
            "aquamarine",
            f"dbus-run-session hyprland -c {Path.home()}/.config/hypr/hyprland.lua --watchdog-fd 3",
        )
    if "burpsuite" in joined:
        return (
            "burp-",
            f"burpsuite --user-config-file={Path.home()}/.config/burpsuite/burp_user_config.json "
            f"{joined}",
        )
    if "zaproxy" in joined:
        return "zaproxy", "zaproxy"
    if "blackarch-agent" in joined:
        return "org.blackarch.agent", joined
    return (argv[0] if argv else ""), joined


@log_all
def launch(id_kind: str, cmd: str, app_id: str = "", app_instance: str = "") -> None:
    """Hand off to the right launcher, mirroring the original case block."""
    browser = shlex.split(browser_exec())
    browser_args = shlex.split(app_instance)
    if id_kind in ("TUI", "GUI"):
        os.execvp("setsid", ["setsid", "uwsm-app", "--", *shlex.split(cmd)])
    elif id_kind == "kitty":
        os.execvp(
            "kitty",
            [
                "kitty",
                "--hold",
                f"--app-id={app_id}",
                "-e",
                "bash",
                "-c",
                f"{argv0()} banner",
            ],
        )
    elif id_kind in ("hacker", "Root"):
        sudo_run(
            [
                "kitty",
                "--hold",
                f"--app-id={app_id}",
                "-e",
                "bash",
                "-c",
                f"{argv0()} banner; {cmd}",
            ]
        )
    elif id_kind == "webapp":
        os.execvp(
            "setsid",
            [
                "setsid",
                "uwsm-app",
                "--",
                *browser,
                *sandbox_args(),
                "--profile-directory=Default",
                *browser_args,
            ],
        )
    elif id_kind == "work":
        os.execvp(
            "setsid",
            [
                "setsid",
                "uwsm-app",
                "--",
                *browser,
                *sandbox_args(),
                "--profile-directory=Default Work",
                *browser_args,
            ],
        )
    elif id_kind == "private":
        os.execvp(
            "setsid",
            [
                "setsid",
                "uwsm-app",
                "--",
                browser,
                *sandbox_args(),
                "--incognito",
                "--profile-directory=Default Kids",
                *browser_args,
            ],
        )
    else:
        os.execvp(
            "xdg-terminal-exec",
            [
                "xdg-terminal-exec",
                "--app-id=org.blackarch.blackarch-update",
                "--",
                *shlex.split(cmd),
            ],
        )


@log_all
def print_help() -> None:
    print(f"""{argv0()} - <command> <subcommand>
------------------------------------------------------------------------------------------------------------------------------------------
Command     	        Description                                          Subcommands / Arguments
------------------------------------------------------------------------------------------------------------------------------------------
shell/toggle	      Manage Quickshell menus and UI elements.	            generate, apps, root, blackarch, academy, pentest, favorite, smartthings, learn
                                                                                  touchscreen_orientation, 
                                                                                  virtualkeyboard (auto | toggle | show | hide | stop)
                                                                                  background, theme
vpn                   Toggle VPN connection via nmcli.                   
                        Disconnects if active, else choose profile.      
smartthings           Manage smart home devices.                            menu, status, value, widget (on | off), <device filter/id>
update                update-system	Perform system maintenance and       
                        package updates and orphan cleanup.              
webapp/work/private   Launch a web application inside a dedicated        
                        profile window.	<url>                            
tui                   Run a Text User Interface (TUI) application.       
                        Runs inside a dedicated kitty instance.          
gui                   Launch a Graphical User Interface (GUI)            
                        apps with Pre-configured window rules.           
window                Control the 3-slot window ring management system.	    clipboard, swap, save1 | save2 | save3, clear
brightness            Adjust display backlight and KBD illumination.	    up, down, lock, unlock, low, off, toggle, +, -
audio	              Control system volume and microphone via wpctl.	    up, down, mute, mic
focus	              Switch input focus to a specified application.	    <app_id>
setup	              Run provisioning and configuration.           	    keyrings, sudo, tpm, mount, profile, dotfiles,   
                                                                            xdg-mime, aur, hyprland, cyber, post, smartthings, lukscrypt
                                                                            virtualbox, kvm, hermes, kodachi, ollama
""")


@log_all
def main(argv: Sequence[str]) -> int:
    if argv and argv[0] == "--complete":
        for c in sorted(
            [
                "shell",
                "toggle",
                "vpn",
                "smartthings",
                "update",
                "update-system",
                "webapp",
                "work",
                "private",
                "tui",
                "gui",
                "window",
                "brightness",
                "audio",
                "focus",
                "setup",
            ]
        ):
            print(c)
        return 0
    if argv and argv[0] == "setup" and len(argv) > 1 and argv[1] == "--complete":
        for c in sorted(
            [
                "keyrings",
                "sudo",
                "tpm",
                "mount",
                "profile",
                "dotfiles",
                "virtualbox",
                "kvm",
                "ollama",
                "hermes",
                "kodachi",
                "xdg-mime",
                "aur",
                "hyprland",
                "cyber",
                "post",
                "lukscrypt",
                "install",
            ]
        ):
            print(c)
        return 0
    if not argv:
        print_help()
        return 0
    command, rest = argv[0], list(argv[1:])

    if command in ("-h", "--help"):
        print_help()
        return 0
    if command in ("quickshell", "shell", "toggle"):
        return quickshell_dispatch(rest)
    if command == "vpn":
        toggle_vpn()
        return 0
    if command == "smartthings":
        return smartthings_dispatch(rest)
    if command == "setup":
        return setup_dispatch(rest)
    if command == "update-system":
        launch("TUI", f"{argv0()} update", "org.blackarch.blackarch-update")
        return 0
    if command == "update":
        blackarch_update()
        return 0
    if command == "charger":
        toggle_laptop_charger(rest[0] if rest else "on")
        return 0
    if command in ("webapp", "work", "private"):
        url = rest[0] if rest else ""
        app_id = webapp_id(url) or BROWSER.replace(".desktop", "")
        app_instance = f"--app={shell_quote_url(url)} {' '.join(rest[1:])}".strip()
        if focus_window(app_id):
            return 0
        launch(command, app_id, app_id, app_instance)
        return 0
    if command == "tui":
        cmd = " ".join(rest)
        app_id = f"org.blackarch.{cmd.split()[0] if cmd else ''}"
        if focus_window(app_id):
            return 0
        launch("TUI", f"kitty --app-id={app_id} -e {cmd}", app_id)
        return 0
    if command == "gui":
        app_id, cmd = resolve_gui(rest)
        if focus_window(app_id):
            return 0
        launch("GUI", cmd, app_id)
        return 0
    if command == "focus":
        focus_window(rest[0] if rest else None)
        return 0
    if command == "window":
        return window_dispatch(rest)
    if command == "brightness":
        blackarch_brightness(rest[0] if rest else "toggle")
        return 0
    if command == "flatpak-ulaa":
        blackarch_flatpak_ulaa()
        return 0
    if command == "audio":
        audio_dispatch(rest[0] if rest else "")
        return 0
    # Default: run the request in a root kitty terminal.
    cmd = " ".join(argv)
    app_id = "org.blackarch.hacker"
    if focus_window(app_id):
        return 0
    launch("hacker", cmd, app_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
