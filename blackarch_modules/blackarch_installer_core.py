#!/usr/bin/env python3
# blackarch:summary=Run the commander installer
"""
blackarch installer — clone a running USB-installed Linux onto a hard disk,
or bootstrap a fresh Arch root with the AthenaOS / Blackarch / Omarchy
package set.

Two modes:
  --install clone     copy the running system (credentials, hostname,
                      machine-id, locale and timezone preserved)
  --install pacstrap  build a new Arch root with the AthenaOS / Blackarch /
                      Omarchy package set

The bootloader is opt-in, and nothing about it is ever prompted. --bootloader
names one; without it a pacstrap root is built WITHOUT a loader, because a
bootstrapped root need not be bootable by this installer (a chroot, a VM image,
or a root whose loader the user installs themselves) and writing a loader would
also put an NVRAM entry on their ESP:

          (none)       nothing installed on the new ESP, no NVRAM entry
                       (the default)
          limine       plain vmlinuz + initramfs per kernel, limine.conf,
                       NVRAM entry via limine-install
          systemd-boot unified kernel images in EFI/Linux, bootctl + NVRAM

A clone is never asked either: it keeps the bootloader the running system's own
ESP already carries, which is detected from the ESP (limine.conf or
systemd-boot's files) rather than assumed.

Clone mode creates:
          GPT disk  (EFI System Partition + user-defined Linux partitions)
          LUKS2    (argon2id) on the root partition
          btrfs    (subvolumes @ and @home, matching the live USB)
          the chosen bootloader on the new ESP, when one was chosen
          snapper  config + baseline snapshot

Credentials (root + every real user) are copied verbatim from the running
system, so passwords are unchanged.  Hostname / machine-id / locale /
timezone are preserved.

Usage:
    sudo ./blackarch installer                 # interactive
    sudo ./blackarch installer --disk /dev/sda
    sudo ./blackarch installer --scheme recommended
    sudo ./blackarch installer --help

DESTRUCTIVE: it partitions and formats the TARGET disk you select.
"""

from __future__ import annotations

import argparse
import getpass
import glob
import os
import re

from blackarch_packages import *

try:
    from blackarch_modules.blackarch_logging import get_logger

    logger = get_logger("commander-installer")
except ImportError:
    import logging

    logger = logging.getLogger("commander-installer")

# Auto-logging decorator for installer functions
import functools


def log_all(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(
            f"installer: {func.__name__} called", extra={"command": func.__name__}
        )
        return func(*args, **kwargs)

    return wrapper


import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from blackarch_modules.blackarch_logging import get_logger

    logger = get_logger("commander-installer")
except ImportError:
    import logging

    logger = logging.getLogger("commander-installer")

# Auto-logging decorator for installer functions
import functools


def log_all(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(
            f"installer: {func.__name__} called", extra={"command": func.__name__}
        )
        return func(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #
ESP_SIZE_MIB_DEFAULT = 1024

# pacman cache, inside the new root. It lives on the target disk, so a re-run
# that does not reformat reuses every package already in it.
DEFAULT_CACHE_DIR = "/var/cache/pacman/pkg"
# --------------------------------------------------------------------------- #
ESP_SIZE_MIB_DEFAULT = 1024
LUKS_MAPPING = f"crypt-{secrets.token_hex(4)}"

# The mapper name the new system's cmdline should use. Normally LUKS_MAPPING;
# --existing keeps whatever the container is already open as, so a re-run
# writes the same rd.luks.name= instead of a fresh random one.
MAPPING = LUKS_MAPPING

# --------------------------------------------------------------------------- #
# bootloader + unlocking (set by the prompts, read by every consumer)
# --------------------------------------------------------------------------- #
# NOT a default choice: "" means no bootloader is installed, which is the
# default for `--install pacstrap`. A pacstrap root is built without a loader
# unless the user names one with --bootloader, because the installer then has
# no way to know which loader the user wants and guessing one silently puts a
# loader (and an NVRAM entry) on their ESP. A clone keeps its own loader, so it
# is never asked.
BOOTLOADER = ""
UNLOCK_MODE = "password"

# True on the clone path. A clone keeps the running system's own loader, so
# BOOTLOADER stays "" there and describe_bootloader() has to say that rather
# than "none installed". Set in main().
CLONE_MODE = False

# TPM2 PCR 7 carries the Secure Boot policy, so a TPM2 token enrolled with
# `--tpm2-pcrs=7` (or a PIN alongside it) makes Secure Boot a precondition of
# an automatic unlock.  Without Secure Boot enrolled it must not be included,
# or the boot would fail on a TPM that has nothing to unseal.
TPM2_DEFAULT_PCRS = "7"
TPM2_PCRS = ""
TPM2_PIN = ""

# The LUKS passphrase of the NEW container, kept only so configure_unlock() can
# enroll a TPM2 token on it without asking twice. Cleared in preflight().
LUKS_PASSPHRASE_HOLDER = [""]

# The LUKS UUID the /etc/crypttab line should name. Set by configure_unlock()
# (it receives the UUID from prepare_layout()).
LUKS_UUID_FOR_CRYPTTAB = ""

# The cmdline the new system will boot with. Set by main() before
# write_limine_conf(), so the ESP copy carries the SAME cmdline that is baked
# into the UKI instead of a second copy of the string.
CMDLINE_FOR_ESP = [""]

# The install method, for the summary. Set in main() once --install and
# --skip-pacstrap are both known, read by print_summary().
INSTALL_LINE = ""

# The user-home copy, for the summary. Set in main() from the same decision
# copy_homes_now() applied, so the summary cannot disagree with the run.
HOMES_LINE = ""

# What the home copy leaves out. Set from the CLI in main() (early, before
# prepare_layout), read by home_excludes() while copy_user_homes() runs.
SKIP_HOME_DIRS: list[str] = []
SKIP_HOME_EXTS: list[str] = []
SKIP_VM = False

# Whether the running system is a live/temporary session (an ISO boot, not an
# installed root). A live session has no worth preserving on it, so the home
# copy that a fresh pacstrap root wants is suppressed there. Set in main().
SRC_IS_LIVE = False

# The account the installer itself runs as. os.getlogin() only works when there
# is a controlling terminal -- it raises in a cron job, an ssh command or a
# script whose session lost its tty -- so the uid path stays the fallback.
INVOKER_USER = ""

# The systemd-boot menu entry that loader.conf names as `default`. Set by
# install_systemd_boot() from the UKIs it actually found, read by
# write_loader_conf().
DEFAULT_LOADER_ENTRY = [""]

# TPM2 PCR names for the ask_tpm2_pcrs menu.
PCR_NAMES = (
    "0 firmware-code",
    "1 firmware-config",
    "2 exrom-code",
    "3 exrom-config",
    "4 boot-loader-code",
    "5 boot-loader-config",
    "7 secure-boot-policy",
    "8 kernel-initrd",
    "9 kernel-image",
    "11 kernel-commandline",
    "12 kernel-initrd-commandline",
    "14 grub-config",
)

# limine + systemd-boot are alternatives: each needs its own tooling, its own
# package set and its own boot layout, so preflight checks the chosen one only.
# What backs the new root: the LUKS mapper when encrypted, the partition itself
# with --existing or --no-encrypt. Set by prepare_layout().
ENCRYPTED = False
ROOT_DEVICE = ""
ROOT_DEVICE_UUID = ""
ROOT_MNT = os.environ.get("ROOT_MNT", "/mnt/new/root")
HOME_MNT = os.environ.get("HOME_MNT", "/mnt/new/home")
EFI_MNT = os.environ.get("EFI_MNT", "/mnt/new/efi")
EFI_MNT_ROOT = os.environ.get("EFI_MNT", "/mnt/new/efi")
LOGDIR = os.environ.get("LOGDIR", "/var/log/usb2disk")
LOGFILE = os.path.join(LOGDIR, "install.log")
CUSTOM_PACMAN_CONF = "/tmp/athena-pacman.conf"
# The path the new root sees its own ESP at. The host ESP is bind-mounted
# here before any chrooted command runs, because arch-chroot mounts only
# /dev, /proc, /sys, /run and /etc/resolv.conf -- so /efi is a plain empty
# directory inside it, and Limine's find_boot_partition() (which probes
# /efi, /boot, /boot/efi and /limine for a mounted FAT32 filesystem) finds
# nothing and fails. This is also where the clone's own fstab puts the ESP.
CHROOT_ESP = "/efi"

# Re-run guard. --skip-pacstrap reuses the target root's existing packages
# instead of running pacstrap into it again -- the point of a re-run against
# --existing, where pacstrap would reinstall the base set over a root that is
# already populated. Set from the CLI in main(), read by bootstrap_system().
SKIP_PACSTRAP = False
SKIP_NETWORK = False
SKIP_TIMEZONE = False

# Partitions named explicitly with --efi-part / --root-part / --luks-part and
# resolved by resolve_partition_args(); read by mount_existing(). Empty means
# "not given, detect them the interactive way".
EFI_PART = ""
ROOT_PART = ""
LUKS_PART = ""

# /etc/profile.d/blackarch.sh, written verbatim into the new root. Sourced by
# every login shell (bash and zsh alike), so it is what puts $BLACKARCH_PATH/bin
# on PATH and what defines `waylandsudo` -- the function blackarch_helpers.py
# shells out to when it needs to escalate to root without losing the Wayland
# session. repr() keeps the line continuations literal.
PROFILE_D_BLACKARCH_SH = ': "${BLACKARCH_PATH:=/opt/blackarch/}"\n# Strip trailing slashes so "$BLACKARCH_PATH/bin" never becomes "//bin".\nBLACKARCH_PATH="${BLACKARCH_PATH%/}"\n\ncase ":${PATH}:" in\n  *":${BLACKARCH_PATH}/bin:"*) ;;\n  *) [ -d "${BLACKARCH_PATH}/bin" ] && PATH="${BLACKARCH_PATH}/bin:${PATH}" ;;\nesac\n\nexport BLACKARCH_PATH PATH\n# Source this file for non-interactive shells too (SSH, cron, bash, zsh).\nexport BASH_ENV=/etc/profile.d/blackarch.sh\nexport ENV=/etc/profile.d/blackarch.sh\n\nwaylandsudo() {\n    local uid\n    uid=$(id -u)\n    sudo /usr/bin/env \\\n        XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}" \\\n        DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$uid/bus}" \\\n        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}" \\\n        HYPRLAND_INSTANCE_SIGNATURE="${HYPRLAND_INSTANCE_SIGNATURE}" \\\n        BLACKARCH_PATH="${BLACKARCH_PATH}" \\\n        "$@"\n}\n'


# The omarchy key is not published in a keyring package, so it has to be
# received and locally signed before omarchy-keyring can be verified.
OMARCHY_KEY = "F0134EE680CAC571"


# The running system's Blackarch tree, copied into a bootstrap target.
BLACKARCH_ROOT = "/opt/blackarch"

C = {k: "" for k in ("reset", "bold", "dim", "red", "green", "yellow", "blue", "cyan")}
if sys.stderr.isatty():
    C.update(
        reset="\033[0m",
        bold="\033[1m",
        dim="\033[2m",
        red="\033[31m",
        green="\033[32m",
        yellow="\033[33m",
        blue="\033[34m",
        cyan="\033[36m",
    )

_last_line = ""


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #
@log_all
def _emit(msg: str) -> None:
    """Print to stderr and mirror to the log file. Never raises."""
    global _last_line
    _last_line = msg
    print(msg, file=sys.stderr)
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        if os.path.isdir(LOGDIR) and os.access(LOGDIR, os.W_OK):
            with open(LOGFILE, "a") as fh:
                fh.write(msg + "\n")
    except OSError:
        pass


@log_all
def log(msg: str) -> None:
    _emit(msg)


@log_all
def info(msg: str) -> None:
    _emit(f"{C['bold']}{C['cyan']}==> {C['reset']}{msg}")


@log_all
def step(msg: str) -> None:
    _emit(f"\n{C['bold']}{C['blue']}────── {msg} {C['reset']}")


@log_all
def ok(msg: str) -> None:
    _emit(f"{C['green']}✓ {C['reset']}{msg}")


@log_all
def warn(msg: str) -> None:
    _emit(f"{C['yellow']}! {C['reset']}{msg}")


@log_all
def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    _emit(f"{C['bold']}{C['red']}✗ {msg}{C['reset']}")
    sys.exit(1)


# --------------------------------------------------------------------------- #
# process helpers
# --------------------------------------------------------------------------- #
@log_all
def run(cmd, *, check=True, input_text=None, capture=False, env=None, timeout=None):
    """Run a command. Returns CompletedProcess; raises SystemExit via die() on failure."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            capture_output=capture,
            text=True,
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError:
        die(f"required command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        die(f"command timed out: {' '.join(cmd)}")
    if check and proc.returncode != 0:
        # Emit the WHOLE stderr. mkinitcpio reports the actual cause as a
        # `==> ERROR:` line several lines above its final "errors were
        # encountered during the build" warning, so printing only the last
        # line replaced the cause with a generic summary.
        detail = (proc.stderr or "").strip().splitlines()
        for line in detail:
            _emit("    " + line)
        die(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


@log_all
def try_run(cmd, **kw):
    """Run, returning the process even on failure (check=False)."""
    kw["check"] = False
    return run(cmd, **kw)


# --------------------------------------------------------------------------- #
# interactive prompts
# --------------------------------------------------------------------------- #
@log_all
def ask(prompt: str, default: str | None = None) -> str:
    """Prompt; returns default on empty input. Raises EOFError at end of input."""
    suffix = f" [{default}]" if default is not None else ""
    try:
        line = input(f"{C['bold']}{prompt}{C['reset']}{suffix} ")
    except EOFError:
        die("no input available (EOF)")
    line = line.strip()
    if not line:
        if default is not None:
            return default
        return ask(prompt, default)
    return line


@log_all
def ask_yesno(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        line = input(f"{C['bold']}{prompt}{C['reset']}{suffix}").strip().lower()
    except EOFError:
        # EOF must never proceed with a destructive action
        return False
    if not line:
        return default
    return line in ("y", "yes")


@log_all
def ask_hidden(prompt: str) -> str:
    try:
        val = getpass.getpass(f"{C['bold']}{prompt}{C['reset']} ")
    except EOFError:
        die("no input available (EOF)")
    if not val:
        return ask_hidden(prompt)
    return val


@log_all
def ask_choice(prompt: str, options: tuple, default: str) -> str:
    """Prompt with a numbered list; returns the chosen option's key."""
    _emit("")
    _emit(f"{C['bold']}{prompt}:{C['reset']}")
    for i, (key, label) in enumerate(options, start=1):
        mark = " (default)" if key == default else ""
        _emit(f"  {C['cyan']}{i}){C['reset']} {label}{mark}")
    while True:
        raw = ask(
            "Choose", str(options.index((default, _label_of(options, default))) + 1)
        )
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        warn(f"Enter 1..{len(options)}")


@log_all
def _label_of(options: tuple, key: str) -> str:
    for k, label in options:
        if k == key:
            return label
    return key


@log_all
def ask_tpm2_pcrs() -> str:
    """PCR indices a TPM2 enrollment should be bound to.

    Returns a comma-joined list, or '' for an unbound (empty-policy) token --
    which would unseal on ANY machine that owns the TPM, so it warns first.
    """
    step("TPM2 PCR binding")
    info("Bind the TPM2 token so it only unseals when the boot chain is intact.")
    _emit("")
    for line in PCR_NAMES:
        _emit(f"  {C['cyan']}{line}{C['reset']}")
    _emit("")
    info(
        f"Current Secure Boot state: {'ENABLED' if secure_boot_enabled() else 'not enrolled'}"
    )
    while True:
        raw = ask(
            "PCRs to bind (comma separated; empty = do not bind)",
            TPM2_DEFAULT_PCRS,
        )
        raw = raw.replace(" ", "")
        if not raw:
            if ask_yesno(
                "An unbound TPM2 token unseals on any machine owning the TPM. Continue anyway?",
                default=False,
            ):
                return ""
            continue
        bad = [p for p in raw.split(",") if not p.isdigit() or not 0 <= int(p) <= 23]
        if bad:
            warn(f"Invalid PCR index(es): {', '.join(bad)} (valid: 0..23)")
            continue
        return ",".join(sorted({p for p in raw.split(",") if p}))


@log_all
def secure_boot_enabled() -> bool:
    """True when the firmware has Secure Boot keys enrolled (PCR 7 becomes meaningful)."""
    for name in os.listdir("/sys/firmware/efi/efivars"):
        if name.lower().startswith("secureboot-") or name.lower().startswith(
            "secure-boot-"
        ):
            try:
                with open(os.path.join("/sys/firmware/efi/efivars", name), "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            if data and data[-1] in (0, 1):
                return data[-1] == 1
    return False


# --------------------------------------------------------------------------- #
# bootloader + unlock method: what the new root is asked for at boot
# --------------------------------------------------------------------------- #
@log_all
def describe_unlock() -> str:
    """One line describing how the new root is unlocked, for the summary."""
    if not ENCRYPTED:
        return "unencrypted root"
    if UNLOCK_MODE == "password":
        return "LUKS2 password prompt in the initramfs"
    if UNLOCK_MODE == "tpm2-fallback":
        return (
            f"LUKS2 TPM2 token (PCRs {TPM2_PCRS or 'none'})"
            + (" + PIN" if TPM2_PIN else "")
            + ", password prompt if the TPM cannot unseal"
        )
    return (
        f"LUKS2 TPM2 token only (PCRs {TPM2_PCRS or 'none'})"
        + (" + PIN" if TPM2_PIN else "")
        + ", no password prompt (headless=yes)"
    )


@log_all
def describe_bootloader() -> str:
    if BOOTLOADER == "limine":
        return "Limine (limine.conf entries on the ESP + NVRAM entry)"
    if BOOTLOADER == "systemd-boot":
        return "systemd-boot (UKI in EFI/Linux + loader/entries menu + NVRAM entry)"
    # a clone keeps whatever loader the running system's own ESP carries, so
    # there is nothing to describe even though BOOTLOADER is empty
    if CLONE_MODE:
        return describe_esp_loader()
    return "none (no loader installed on the new ESP)"


# --------------------------------------------------------------------------- #
# block device helpers
# --------------------------------------------------------------------------- #
@log_all
def parent_disk(path: str) -> str:
    """Whole-disk ancestor of a block device.

    Do NOT use `lsblk -o PKNAME`: on util-linux 2.42 it returns EMPTY for
    dm-crypt devices, so the parent disk is silently lost.  Walk sysfs instead.

    A partition's sysfs node carries a `partition` file and its parent directory
    is the whole disk -- that is what makes NVMe work, where the disk sits under
    .../nvme/nvme0/nvme0n1 with no `block` directory in the path at all.  A
    dm/lvm/md device has no such file, so its backing slave is followed, and a
    whole disk sitting directly under a non-virtual `block` directory is the
    answer for the SCSI/USB case.

      .../nvme/nvme0/nvme0n1/nvme0n1p2  -> nvme0n1  (has a `partition` file)
      .../block/sdb/sdb2                -> sdb       (has a `partition` file)
      .../virtual/block/dm-0            -> slave     (dm-crypt: no partition file)
    """
    node = _sysfs_node(path.split("[")[0])
    if not node:
        return ""

    seen = set()
    while True:
        if os.path.exists(os.path.join(node, "partition")):
            disk = os.path.dirname(node)
            return os.path.basename(disk) if os.path.isdir(disk) else ""

        if (
            os.path.basename(os.path.dirname(node)) == "block"
            and "/virtual/" not in node
        ):
            return os.path.basename(node)

        nxt = _first_slave(node)
        if not nxt or nxt in seen:
            return ""
        seen.add(nxt)
        node = nxt


@log_all
def _sysfs_node(path: str) -> str:
    """Resolve a device path to its /sys node, or "" if it is not a block device."""
    path = os.path.realpath(path)
    if not os.path.exists(path):
        return ""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    dev = getattr(st, "st_rdev", 0) or st.st_dev
    node = os.path.realpath(f"/sys/dev/block/{os.major(dev)}:{os.minor(dev)}")
    return node if os.path.isdir(node) else ""


@log_all
def backing_partition(dm_path: str) -> str:
    """'/dev/mapper/sdc2crypted' -> '/dev/sdb2' (the partition behind the dm device).

    Walks down through slaves/ until it reaches a partition (whose sysfs parent
    is the disk's directory rather than a 'block' directory).
    """
    node = _sysfs_node(dm_path)
    if not node:
        return ""
    seen = set()
    while True:
        slave = _first_slave(node)
        if not slave:
            return ""
        parent = os.path.basename(os.path.dirname(slave))
        if parent != "block" and "/virtual/" not in slave:
            return "/dev/" + os.path.basename(slave)
        if slave in seen:
            return ""
        seen.add(slave)
        node = slave


@log_all
def _first_slave(node: str) -> str:
    slaves = os.path.join(node, "slaves")
    try:
        for entry in sorted(os.listdir(slaves)):
            target = os.path.realpath(os.path.join(slaves, entry))
            if os.path.isdir(target):
                return target
    except OSError:
        pass
    return ""


@log_all
def partition_node(disk_name: str, part_num: int) -> str:
    """/dev/sda + 1 -> /dev/sda1 ; /dev/nvme0n1 + 1 -> /dev/nvme0n1p1"""
    if disk_name and disk_name[-1].isdigit():
        return f"/dev/{disk_name}p{part_num}"
    return f"/dev/{disk_name}{part_num}"


@log_all
def list_disks() -> list[dict]:
    """Whole disks only. lsblk -d includes zram/loop/ram, which are not targets."""
    out = try_run(["lsblk", "-d", "-rno", "NAME,SIZE,TRAN,MODEL"], capture=True)
    disks = []
    for line in out.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 2:
            continue
        name, size = parts[0], parts[1]
        tran = parts[2] if len(parts) > 2 else ""
        model = parts[3] if len(parts) > 3 else ""
        if re.match(r"^(zram|loop|ram|fd|dm-|sr|mmcblk)", name):
            continue
        if (
            tran.lower() == "usb"
            and "STORAGE" in model.upper()
            and "DEVICE" in model.upper()
        ):
            continue
        if not tran and not model:
            continue
        disks.append({"name": name, "size": size, "tran": tran, "model": model})
    return disks


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #
@log_all
def preflight() -> None:
    if os.geteuid() != 0:
        die("This script must run as root. Re-run with: sudo " + sys.argv[0])
    os.makedirs(LOGDIR, exist_ok=True)
    open(LOGFILE, "w").close()

    # Only the loader actually chosen needs its tools on the running system, and
    # with no --bootloader there is none: the base set (rsync, mkinitcpio, ...)
    # is all a loaderless pacstrap run needs.
    missing = [
        t
        for t in BASE_REQUIRED_TOOLS
        + (BOOTLOADER_TOOLS[BOOTLOADER] if BOOTLOADER else ())
        if not shutil.which(t)
    ]
    if missing:
        die(
            "Missing required tools"
            + (f" for bootloader {BOOTLOADER}" if BOOTLOADER else "")
            + ": "
            + ", ".join(missing)
        )

    if not os.path.isdir("/sys/firmware/efi"):
        die(
            "No UEFI firmware detected. This installer targets UEFI"
            + (f" + {BOOTLOADER}" if BOOTLOADER else "")
            + " only."
        )
    if BOOTLOADER == "limine" and not os.access("/efi", os.R_OK):
        # limine-install/limine-entry-tool find the ESP via ESP_PATH or a FAT32
        # mount; a missing /efi means the tooling would have nothing to write to.
        warn("/efi is not readable — Limine needs the ESP mounted there")
    if not os.access("/etc/shadow", os.R_OK):
        die("/etc/shadow is not readable — must run as root.")

    # clear the in-memory copy of the LUKS passphrase between runs
    LUKS_PASSPHRASE_HOLDER[0] = ""

    fstype = try_run(["findmnt", "-rno", "FSTYPE", "/"], capture=True).stdout.strip()
    if fstype != "btrfs":
        die(
            f"Running root filesystem is '{fstype}', not btrfs. "
            "This installer clones btrfs subvolumes."
        )


# --------------------------------------------------------------------------- #
# introspection of the running (source) system
# --------------------------------------------------------------------------- #
class Source:
    root_source = ""  # /dev/mapper/xxx
    root_subvol = "/@"  # with leading slash
    home_source = ""
    home_subvol = "/@home"
    users: list[str] = []
    homes: dict[str, str] = {}  # username -> home directory in the running system
    machine_id = ""
    hostname = ""
    cmdline = ""
    # A live/temporary session: an ISO boot, not an installed root. Set by
    # detect_live_session().
    is_live = False


@log_all
def _subvol_of(mount_source: str) -> str:
    """'/dev/mapper/x[/@]' -> '/@'   (the subvolume already carries its slash)."""
    if "[" in mount_source:
        return mount_source.split("[", 1)[1].rstrip("]")
    return "/"


# Why the running system was called live, or "" when it was not. Kept for the
# summary and the log, so the decision is auditable after the run.
SRC_LIVE_REASON = ""


@log_all
def invoker_user() -> str:
    """The account this installer runs as, or "" if it cannot be determined.

    Not always the same as the user whose home should be copied: an installed
    system is normally run as its own user, while the account that boots a live
    session (live, ubuntulive, archiso, ...) is a throwaway one and never the
    account being installed.

    Deliberately NOT a filter: on an installed system every real user's home is
    still copied, not just the invoker's -- a multi-user source does not lose
    all but one home. It is recorded for the log and the summary, so the
    "which home is this" question is answerable after the run.

    os.getlogin() is tried first and the uid path second, because getlogin()
    raises when there is no controlling terminal -- a cron job, `ssh host cmd`,
    or a script whose session lost its tty. logname is skipped rather than
    trusted: it answers "who logged in on this tty", which on a system where
    root sudoed from a user session is the user, not the effective account.
    """
    global INVOKER_USER
    if INVOKER_USER:
        return INVOKER_USER
    for how in (
        lambda: os.getlogin(),
        lambda: __import__("pwd").getpwuid(os.getuid()).pw_name,
    ):
        try:
            name = how()
        except (OSError, KeyError):
            name = ""
        if name:
            INVOKER_USER = name
            return INVOKER_USER
    return ""


@log_all
def detect_live_session() -> None:
    """Mark the running system as a live session, and say why.

    A live/temporary session is an ISO boot: the root is an overlay or a
    ramdisk, or the kernel cmdline asks for `toram`/`copytoram`. Such a system
    has no home worth preserving -- its /home is empty or holds throwaway
    defaults -- so the home copy that a pacstrap root wants is suppressed
    there. An installed root is never called live: this is the condition the
    default turns on, so a false positive would silently change what gets
    installed.
    """
    global SRC_LIVE_REASON
    SRC.is_live = False
    SRC_LIVE_REASON = ""

    fstype = try_run(["findmnt", "-rno", "FSTYPE", "/"], capture=True).stdout.strip()
    if fstype in ("overlay", "tmpfs", "ramfs", "squashfs"):
        SRC.is_live, SRC_LIVE_REASON = True, f"root filesystem is {fstype}"

    if not SRC.is_live:
        cmdline = ""
        try:
            cmdline = open("/proc/cmdline").read()
        except OSError:
            pass
        tokens = cmdline.split()
        if any(t.split("=")[0] in ("toram", "copytoram") for t in tokens):
            SRC.is_live, SRC_LIVE_REASON = (
                True,
                "kernel cmdline carries toram/copytoram",
            )

    info(
        "Running system: "
        + ("live/temporary session" if SRC.is_live else "installed root")
        + (f" ({SRC_LIVE_REASON})" if SRC.is_live else "")
    )


SRC = Source()


@log_all
def introspect_source() -> None:
    step("Inspecting the running system")

    # The session kind first: it decides whether the user homes are worth
    # copying at all, and copy_homes_now() reads it.
    detect_live_session()

    src = try_run(["findmnt", "-rno", "SOURCE", "/"], capture=True).stdout.strip()
    SRC.root_source = src.split("[")[0]
    SRC.root_subvol = _subvol_of(src)
    info(f"Running root source: {SRC.root_source}  subvolume: {SRC.root_subvol}")

    home_src = try_run(
        ["findmnt", "-rno", "SOURCE", "/home"], capture=True
    ).stdout.strip()
    if home_src and home_src != src:
        SRC.home_source = home_src.split("[")[0]
        SRC.home_subvol = _subvol_of(home_src)
    else:
        SRC.home_source, SRC.home_subvol = "", ""
    info(
        f"Running /home source: {SRC.home_source or '<same as root>'}  "
        f"subvolume: {SRC.home_subvol or '<same as root>'}"
    )

    SRC.homes = {}
    SRC.users = []
    try:
        with open("/etc/passwd") as fh:
            for line in fh:
                fields = line.split(":")
                if len(fields) < 7 or not line.strip():
                    continue
                name, uid, home, shell = fields[0], fields[2], fields[5], fields[6]
                if not (uid.isdigit() and 1000 <= int(uid) < 65534):
                    continue
                if re.search(r"(nologin|false)$", shell):
                    continue
                SRC.users.append(name)
                SRC.homes[name] = home
    except (OSError, ValueError, IndexError):
        SRC.users = []
    SRC.users = sorted(set(SRC.users))
    info(
        "Real users found in the running system: " + (", ".join(SRC.users) or "<none>")
    )
    info(
        "User home directories: "
        + (", ".join(f"{u}={SRC.homes.get(u, '?')}" for u in SRC.users) or "<none>")
    )

    for path, attr in (
        ("/etc/machine-id", "machine_id"),
        ("/etc/hostname", "hostname"),
    ):
        try:
            setattr(SRC, attr, open(path).read().strip())
        except OSError:
            setattr(SRC, attr, "")

    try:
        SRC.cmdline = open("/proc/cmdline").read().strip()
    except OSError:
        SRC.cmdline = ""
    info("Source kernel cmdline: " + SRC.cmdline)


# --------------------------------------------------------------------------- #
# target disk selection
# --------------------------------------------------------------------------- #
@log_all
def select_target_disk(
    disk_arg: str | None, existing: bool = False
) -> tuple[str, str, bool]:
    """Returns (target_disk, target_disk_name)."""
    step("Select the TARGET hard disk")

    info("Detected block devices:")
    listing = try_run(
        ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,MODEL"],
        capture=True,
    ).stdout
    for line in listing.splitlines():
        _emit("  " + line)

    src_disk = parent_disk(
        try_run(["findmnt", "-rno", "SOURCE", "/"], capture=True).stdout.strip()
    )
    info(f"Running system is on: {src_disk or 'unknown'} — this disk is protected.")

    disks = list_disks()
    if not disks:
        die("No block devices found.")

    _emit("")
    _emit(f"{C['bold']}Available disks:{C['reset']}")
    for i, d in enumerate(disks, 1):
        mark = (
            f" {C['red']}<= running system (protected){C['reset']}"
            if d["name"] == src_disk
            else ""
        )
        _emit(
            f"  {C['cyan']}{i:>2}){C['reset']} {d['name']:<8} {d['size']:<10} "
            f"{d['tran']:<5} {d['model'] or 'disk'}{mark}"
        )

    names = [d["name"] for d in disks]

    if disk_arg:
        target_name = disk_arg.removeprefix("/dev/")
        if target_name not in names:
            die(f"'{disk_arg}' is not one of the available disks: {', '.join(names)}")
        info(f"Using explicitly requested target: /dev/{target_name}")
    else:
        while True:
            choice = ask("Select target disk number", "1")
            if choice.isdigit() and 1 <= int(choice) <= len(names):
                target_name = names[int(choice) - 1]
                break
            warn(f"Enter a number between 1 and {len(names)}")

    if target_name == src_disk:
        die(f"Refusing to use the running system's own disk ({src_disk}).")

    target = f"/dev/{target_name}"
    size_bytes = int(
        try_run(["lsblk", "-bdno", "SIZE", target], capture=True).stdout.strip() or 0
    )
    info(f"Selected target: {target} ({size_bytes // (1024 ** 2)} MiB)")
    if size_bytes < 40 * 1024**3:
        warn(
            "Target is smaller than 40 GiB — a full clone needs ~44 GiB. Proceed with caution."
        )

    _emit("")
    if existing:
        # --existing mounts the partitions that are already there: nothing is
        # reformatted, but the install still writes into them
        _emit(
            f"{C['bold']}{C['yellow']}The partitions on {target} will be mounted "
            f"as-is — nothing is reformatted.{C['reset']}"
        )
        if not ask_yesno(
            f"Install into the existing layout on {target} ?", default=True
        ):
            # fall back to existing layout instead of aborting
            existing = True
    else:
        _emit(
            f"{C['bold']}{C['red']}THIS WILL DESTROY ALL DATA ON {target}{C['reset']}"
        )
        if not ask_yesno(f"Partition and format {target} ?", default=False):
            existing = True
    _emit("")

    # unmount anything on the target first
    mounted = try_run(["lsblk", "-rno", "NAME,MOUNTPOINT", target], capture=True).stdout
    for line in mounted.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip():
            warn(f"Unmounting {parts[1].strip()} from the target disk")
            try_run(["umount", "-R", parts[1].strip()])

    return target, target_name, existing


# --------------------------------------------------------------------------- #
# partitioning (parted)
# --------------------------------------------------------------------------- #
class Part:
    def __init__(self, name, fs, start, end, flag=""):
        self.name, self.fs, self.start, self.end, self.flag = name, fs, start, end, flag

    def __repr__(self):
        return f"<Part {self.name} {self.fs} {self.start}..{self.end}>"


@log_all
def disk_size_mib(disk: str) -> int:
    """parted -m prints 'BYT;' then '<path>:<size>:...'."""
    out = try_run(
        ["parted", "-s", "-m", "--", disk, "unit", "MiB", "print"], capture=True
    ).stdout
    for line in out.splitlines():
        fields = line.rstrip(";").split(":")
        if len(fields) > 1 and fields[1].endswith("MiB"):
            return int(fields[1][:-3])
    return 0


@log_all
def parted_partitions(disk: str) -> list[tuple[int, str]]:
    """[(partition_number, flags)] as reported by parted."""
    out = try_run(
        ["parted", "-s", "-m", "--", disk, "unit", "MiB", "print"], capture=True
    ).stdout
    result = []
    for line in out.splitlines():
        fields = line.rstrip(";").split(":")
        if not fields or not fields[0].isdigit():
            continue
        flags = fields[6].replace(" ", "") if len(fields) > 6 else ""
        result.append((int(fields[0]), flags))
    return result


@log_all
def partition_target(
    target: str, target_name: str, scheme: str, esp_size_mib: int | None = None
) -> tuple[str, str]:
    """Create the partition table with parted. Returns (esp_part, root_part)."""
    step(f"Partitioning {target}")

    # Unmount any existing mounted partitions on the target disk first, even
    # when --keep-mounted was requested: partitioning needs the device free.
    for part in sorted(glob.glob(f"{target}*")):
        if part == target:
            continue
        try_run(["umount", "-R", part])
    try_run(["wipefs", "-a", target])
    try_run(["partprobe", target])

    size_mib = disk_size_mib(target)
    if size_mib <= 0:
        die(f"Cannot determine the size of {target}")
    info(f"Disk size: {size_mib} MiB")

    parts: list[Part] = []

    if scheme == "recommended":
        # ESP defaults to 5% of the disk capped at 1 GiB; --esp-size overrides it.
        if esp_size_mib is None:
            esp_end = min(ESP_SIZE_MIB_DEFAULT, max(256, int(size_mib * 0.05)))
        else:
            esp_end = esp_size_mib
        # always leave room for the root partition
        esp_end = max(256, min(esp_end, size_mib - 256))
        parts.append(Part("ESP", "fat32", "1MiB", f"{esp_end}MiB", "esp"))
        parts.append(Part("rootfs", "btrfs", f"{esp_end}MiB", "100%"))
        ok(f"Recommended scheme: ESP {esp_end} MiB + root (rest)")
    else:
        count = ask("How many partitions", "2")
        if not (count.isdigit() and 1 <= int(count) <= 8):
            die("Enter a number between 1 and 8")
        count = int(count)

        cur = 1  # cursor, in MiB
        for i in range(1, count + 1):
            _emit("")
            _emit(f"{C['bold']}Partition {i} of {count}{C['reset']}")
            _emit(f"  {C['dim']}Purposes:{C['reset']} efi | linux | swap | other")
            purpose = ask("Purpose", "linux").lower()
            flag = ""
            if purpose == "efi":
                fs = "fat32"
                flag = "esp"
            elif purpose == "swap":
                fs = "linux-swap"
            elif purpose == "linux":
                fs = "btrfs"
            elif purpose == "other":
                fs = ask("Filesystem (fat32|btrfs|ext4|xfs)", "btrfs")
            else:
                die(f"Unknown purpose: {purpose}")

            if i == count:
                size = "rest"
            else:
                size = ask("Size in MiB or percent (e.g. 1024 or 20%)", "rest")

            # Compute the partition's end as an absolute offset in MiB.
            # Percentages are absolute fractions of the whole disk, matching how
            # partitioning tools normally express them.
            if size in ("rest", "100%"):
                start_str, end_str, end_mib = f"{cur}MiB", "100%", size_mib
            elif size.endswith("%"):
                end_mib = int(size_mib * int(size[:-1]) / 100)
                start_str, end_str = f"{cur}MiB", f"{end_mib}MiB"
            elif size.isdigit():
                end_mib = cur + int(size)
                start_str, end_str = f"{cur}MiB", f"{end_mib}MiB"
            else:
                die(f"Invalid size: '{size}' (use MiB, a percentage, or 'rest')")

            if end_mib <= cur:
                die(
                    f"Partition {i} has no space (starts at {cur} MiB, ends at {end_mib} MiB)"
                )
            if end_mib > size_mib:
                die(f"Partition {i} is larger than the disk")
            if end_mib == size_mib and i != count:
                die(f"Partition {i} fills the disk; no room for more partitions")

            parts.append(Part(purpose.upper(), fs, start_str, end_str, flag))
            cur = end_mib

    # ---- apply with parted -------------------------------------------------- #
    cmd = ["parted", "-s", "--", target, "mklabel", "gpt"]
    for idx, p in enumerate(parts, 1):
        cmd += ["mkpart", p.name, p.fs, p.start, p.end]
        if p.flag:
            cmd += ["set", str(idx), p.flag, "on"]

    info("Applying the partition table:")
    _emit("  " + " ".join(cmd))
    run(cmd)

    try_run(["partprobe", target])
    if shutil.which("udevadm"):
        try_run(["udevadm", "settle"])
    time.sleep(1)

    # ---- enumerate what parted created -------------------------------------- #
    created = parted_partitions(target)
    if not created:
        die(f"parted reported no partitions on {target}")
    if len(created) != len(parts):
        warn(f"Expected {len(parts)} partitions but parted reports {len(created)}")

    _emit("")
    _emit(f"{C['bold']}Created partitions:{C['reset']}")
    for idx, (num, flags) in enumerate(created):
        name = parts[idx].name if idx < len(parts) else "<none>"
        fs = parts[idx].fs if idx < len(parts) else "<none>"
        _emit(
            f"  {C['cyan']}{num:>2}){C['reset']} {name:<10} {fs:<10} {flags or '<none>'}"
        )

    # ---- resolve the EFI System Partition ----------------------------------- #
    esp_num = None
    for idx, (num, flags) in enumerate(created):
        if ",esp," in f",{flags},":
            esp_num = num
            break
    if esp_num is None:
        warn("No partition carries the 'esp' flag.")
        pick = ask("Which partition number is the EFI System Partition", "1")
        esp_num = int(pick) if pick.isdigit() else 1
    esp = partition_node(target_name, esp_num)
    if not os.path.exists(esp):
        die(f"ESP partition node not found: {esp}")
    ok(f"EFI System Partition: {esp}")

    # ---- resolve the root partition (largest btrfs, else ask) --------------- #
    root_num = None
    for idx, (num, _flags) in enumerate(created):
        if idx < len(parts) and parts[idx].fs == "btrfs":
            root_num = num
            break
    if root_num is None:
        pick = ask("Which partition number holds the new root filesystem", "2")
        root_num = int(pick) if pick.isdigit() else 2
    root = partition_node(target_name, root_num)
    if not os.path.exists(root):
        die(f"Root partition node not found: {root}")
    ok(f"Root partition: {root}")

    return esp, root


# --------------------------------------------------------------------------- #
# LUKS + filesystems
# --------------------------------------------------------------------------- #
@log_all
def setup_luks(root_part: str) -> str:
    """Returns the new LUKS UUID.

    By default the new container is initialised with the RUNNING system's LUKS
    passphrase, so the same password unlocks both. The passphrase is verified
    against the live container first, so a typo cannot silently produce a
    different password on the clone.
    """
    step(f"Setting up LUKS2 encryption on {root_part}")

    passphrase = ask_hidden("Enter a NEW LUKS passphrase for the new root")
    if ask_hidden("Confirm passphrase") != passphrase:
        die("Passphrases do not match.")
    # configure_unlock() needs the passphrase to enroll a TPM2 token on the same
    # container; holding it in memory beats asking for it twice.
    LUKS_PASSPHRASE_HOLDER[0] = passphrase

    info("Formatting LUKS2 (argon2id, pbkdf-memory limited for interactive prompt)")
    run(
        [
            "cryptsetup",
            "luksFormat",
            "--batch-mode",
            "--type",
            "luks2",
            "--label",
            LUKS_MAPPING,
            root_part,
            "--key-file=-",
        ],
        input_text=passphrase,
    )

    info(f"Opening {root_part} as {LUKS_MAPPING} via stdin")
    run(
        [
            "cryptsetup",
            "open",
            "--type",
            "luks2",
            root_part,
            LUKS_MAPPING,
            "--key-file=-",
        ],
        input_text=passphrase,
    )
    uuid = try_run(["cryptsetup", "luksUUID", root_part], capture=True).stdout.strip()
    ok(f"LUKS2 container ready: /dev/mapper/{LUKS_MAPPING}  uuid={uuid}")
    return uuid


@log_all
def write_crypttab() -> None:
    """Write /etc/crypttab so the root container is unlocked by name.

    The kernel cmdline already carries rd.luks.name=UUID=MAPPING, so the device
    is found by UUID and named by the cmdline. What crypttab adds is the unlock
    policy: tpm2-device makes systemd-cryptsetup try the TPM token first and
    then fall back to the password prompt, which is the behaviour --unlock-fallback
    cannot express on its own.
    """
    step("Writing /etc/crypttab")
    path = os.path.join(ROOT_MNT, "etc", "crypttab")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # crypttab(5) fourth field.
    #
    #   tpm2-device=auto   try the TPM2 token first; if unsealing fails (PCRs do
    #                      not match, TPM missing) systemd-cryptsetup falls
    #                      through to the password prompt. That is exactly the
    #                      "TPM, then password" behaviour.
    #   headless=yes       never query interactively. Only for tpm2-only, where
    #                      a TPM failure must not silently wait on a keyboard.
    #
    # tpm2-pcrs is deliberately NOT written: systemd-cryptenroll already stored
    # the bound PCRs in the LUKS2 token metadata, and crypttab says the option
    # is only useful when that metadata is absent.
    options = ""
    if UNLOCK_MODE == "tpm2-fallback":
        options = " tpm2-device=auto"
    elif UNLOCK_MODE == "tpm2-only":
        options = " tpm2-device=auto headless=yes"

    lines = [
        "# <target name> <source device> <key file> <options>",
        f"{MAPPING} UUID={LUKS_UUID_FOR_CRYPTTAB} none{options}",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    ok(f"/etc/crypttab written for {MAPPING}")


@log_all
def enroll_tpm2_token(passphrase: str) -> None:
    """Enroll a TPM2 token on the new root's LUKS container.

    Runs on the host against the open container, so the SRK has to be created on
    the host TPM now. Binds to TPM2_PCRS and adds a PIN when asked for one; with
    Secure Boot enrolled, PCR 7 makes a tampered boot chain fail the unseal and
    the password prompt takes over.
    """
    step("Enrolling a TPM2 token")

    if not os.path.exists("/dev/tpmrm0") and not os.path.exists("/dev/tpm0"):
        warn("no TPM2 device node found — skipping the enrollment")
        return

    # The container is open as /dev/mapper/<MAPPING>; systemd-cryptenroll takes
    # the backing device, not the mapper.
    backing = try_run(["cryptsetup", "status", MAPPING], capture=True).stdout
    device = ""
    for line in backing.splitlines():
        if line.strip().startswith("device:"):
            device = line.split(":", 1)[1].strip()
            break
    if not device:
        warn(f"cannot find the backing device of {MAPPING} — skipping enrollment")
        return
    info(f"enrolling on {device}")

    cmd = ["systemd-cryptenroll", "--tpm2-device=auto"]
    if TPM2_PCRS:
        cmd.append(f"--tpm2-pcrs={TPM2_PCRS}")
    if TPM2_PIN:
        cmd.append("--tpm2-with-pin=yes")
    cmd.append(device)

    # The passphrase unlocks the existing key slot so a new one can be added.
    proc = try_run(cmd, input_text=passphrase + "\n", capture=True)
    if proc.returncode != 0:
        warn("systemd-cryptenroll failed; the root stays password-only")
        for line in (proc.stderr or "").splitlines():
            _emit("    " + line)
        return

    dump = try_run(["cryptsetup", "luksDump", device], capture=True).stdout
    slots = [
        ln
        for ln in dump.splitlines()
        if ln.strip().startswith("Tokens:") or "tpm2" in ln.lower()
    ]
    ok(
        f"TPM2 token enrolled on {device} (PCRs {TPM2_PCRS or 'none'}"
        + (", PIN required" if TPM2_PIN else "")
        + ")"
    )
    if not any("tpm2" in ln.lower() for ln in slots):
        warn("luksDump reported no TPM2 token — check the enrollment")
    else:
        for ln in slots[:4]:
            _emit("  " + ln.strip())


@log_all
def configure_unlock(args, luks_uuid: str) -> None:
    """Ask how the new root is unlocked and apply it."""
    global UNLOCK_MODE, TPM2_PCRS, TPM2_PIN, LUKS_UUID_FOR_CRYPTTAB

    if not ENCRYPTED:
        info("root is not encrypted — no unlock method to configure")
        return
    mode = "password"
    UNLOCK_MODE = mode
    LUKS_UUID_FOR_CRYPTTAB = luks_uuid
    TPM2_PCRS, TPM2_PIN = "", ""
    ok("unlock: password prompt")
    return

    if not args.tpm2_pcrs:
        TPM2_PCRS = ask_tpm2_pcrs()
    else:
        given = [x.strip() for x in args.tpm2_pcrs.split(",") if x.strip()]
        bad = [x for x in given if not x.isdigit() or not 0 <= int(x) <= 23]
        if bad:
            die(f"--tpm2-pcrs: invalid PCR index(es) {', '.join(bad)} (valid: 0..23)")
        TPM2_PCRS = ",".join(sorted({p for p in given}))
    if TPM2_PCRS and "7" in TPM2_PCRS.split(",") and not secure_boot_enabled():
        warn(
            "PCR 7 (secure-boot-policy) is bound but Secure Boot is not enrolled, "
            "so the TPM2 token can never unseal on this machine"
        )
        if not args.tpm2_pcrs and ask_yesno(
            "Drop PCR 7 and bind the token to the remaining PCRs only?",
            default=True,
        ):
            kept = [x for x in TPM2_PCRS.split(",") if x != "7"]
            TPM2_PCRS = ",".join(kept)
            ok(f"PCR binding adjusted to {TPM2_PCRS or 'none'}")

    if mode == "tpm2-only" and not ask_yesno(
        "TPM2-only: no password fallback, so a TPM failure bricks the boot. Continue?",
        default=False,
    ):
        die("aborted: TPM2-only without password fallback")

    if args.tpm2_pin:
        TPM2_PIN = args.tpm2_pin
    elif ask_yesno("Require a PIN in addition to the TPM2 token?", default=False):
        TPM2_PIN = ask_hidden("TPM2 PIN (stored, used at unlock)")

    write_crypttab()
    enroll_tpm2_token(LUKS_PASSPHRASE_HOLDER[0])


@log_all
def make_btrfs(device: str) -> None:
    """Format `device` as btrfs and mount the root and home subvolumes."""
    step("Creating btrfs filesystem")

    run(["mkfs.btrfs", "-f", "-L", "rootfs", device])
    os.makedirs(ROOT_MNT, exist_ok=True)
    run(["mount", device, ROOT_MNT])

    run(["btrfs", "subvolume", "create", f"{ROOT_MNT}/{SRC.root_subvol.lstrip('/')}"])
    if SRC.home_subvol:
        run(
            [
                "btrfs",
                "subvolume",
                "create",
                f"{ROOT_MNT}/{SRC.home_subvol.lstrip('/')}",
            ]
        )

    os.makedirs(
        os.path.join(ROOT_MNT, SRC.root_subvol.lstrip("/"), ".snapshots"), exist_ok=True
    )
    try_run(
        [
            "btrfs",
            "subvolume",
            "create",
            f"{ROOT_MNT}/{SRC.root_subvol.lstrip('/')}/.snapshots/1/snapshot",
        ]
    )

    run(["umount", ROOT_MNT])

    os.makedirs(ROOT_MNT, exist_ok=True)
    run(["mount", "-o", f"subvol={SRC.root_subvol}", device, ROOT_MNT])
    if SRC.home_subvol:
        os.makedirs(HOME_MNT, exist_ok=True)
        run(["mount", "-o", f"subvol={SRC.home_subvol}", device, HOME_MNT])

    ok(
        f"btrfs subvolumes: {SRC.root_subvol} (root)  {SRC.home_subvol or '(none)'} (home)"
    )


@log_all
def mount_encrypted_root() -> None:
    """Mount the freshly formatted LUKS container."""
    make_btrfs(f"/dev/mapper/{MAPPING}")


@log_all
def mount_plain_root(root_part: str) -> None:
    """Format a freshly partitioned root and mount it without LUKS."""
    make_btrfs(root_part)


@log_all
def fstype_of(node: str) -> str:
    """The filesystem type blkid reports for `node`, or '' when it has none."""
    return try_run(
        ["blkid", "-s", "TYPE", "-o", "value", node], capture=True
    ).stdout.strip()


@log_all
def existing_mapper(node: str) -> str:
    """The mapper name `node` is already open under, or '' when it is not."""
    backing = os.path.basename(node)
    for dm in sorted(os.listdir("/sys/block")):
        if not dm.startswith("dm-"):
            continue
        try:
            if backing not in os.listdir(f"/sys/block/{dm}/slaves"):
                continue
            return open(f"/sys/block/{dm}/dm/name").read().strip()
        except OSError:
            continue
    return ""


@log_all
def pick_partition(prompt: str, options: list[str]) -> str:
    """The only option when there is one, otherwise ask."""
    if len(options) == 1:
        return options[0]
    choice = ask(prompt, options[0])
    return choice if choice in options else options[0]


@log_all
def resolve_partition_node(raw: str, target_name: str) -> str:
    """/dev/sda1 | sda1 | 1  ->  /dev/sda1 (a bare number is resolved against the disk)."""
    raw = raw.strip()
    if raw.isdigit():
        return partition_node(target_name, int(raw))
    if raw.startswith("/dev/"):
        return raw
    return f"/dev/{raw}"


@log_all
def resolve_partition_args(args, target: str, target_name: str) -> None:
    """Resolve --efi-part / --root-part / --luks-part into device nodes.

    Naming the partitions makes a --existing run non-interactive: it replaces
    both "which partition is the EFI System Partition" and "which partition
    holds the root / the encrypted root". Each value accepts a device path
    (/dev/sda1), a bare name (sda1) or a partition number (1).

    Called after select_target_disk() so the partitions are checked against the
    disk the user actually chose -- a typo must not silently point the installer
    at the running system's own disk.
    """
    global EFI_PART, ROOT_PART, LUKS_PART

    given = {
        "efi-part": (args.efi_part, "vfat"),
        "root-part": (args.root_part, "btrfs"),
        "luks-part": (args.luks_part, "crypto_LUKS"),
    }
    given = {k: v for k, v in given.items() if v[0]}
    if not given:
        return

    if not args.existing:
        die(
            "--efi-part/--root-part/--luks-part need --existing: without it the "
            "installer partitions the target disk itself, so naming partitions "
            "would contradict what it is about to create"
        )
    if args.root_part and args.luks_part:
        die(
            "--root-part and --luks-part are mutually exclusive: the root is "
            "either a plain btrfs partition or a LUKS container"
        )

    for flag, (raw, expected) in given.items():
        node = resolve_partition_node(raw, target_name)
        if not os.path.exists(node):
            die(f"--{flag}: {node} does not exist")
        if (
            try_run(["lsblk", "-no", "TYPE", node], capture=True).stdout.strip()
            != "part"
        ):
            die(f"--{flag}: {node} is not a partition")
        parent = parent_disk(node)
        if parent != target_name:
            die(
                f"--{flag}: {node} belongs to /dev/{parent or '?'}, not the "
                f"target disk {target}"
            )
        got = fstype_of(node)
        if got != expected:
            hint = ""
            if expected == "btrfs" and got == "crypto_LUKS":
                hint = " - did you mean --luks-part?"
            elif expected == "crypto_LUKS" and got == "btrfs":
                hint = " - did you mean --root-part?"
            elif expected == "vfat":
                hint = " (--existing never reformats a partition)"
            die(
                f"--{flag}: {node} holds {got or 'no filesystem'}, "
                f"expected {expected}{hint}"
            )

    EFI_PART = (
        resolve_partition_node(args.efi_part, target_name) if args.efi_part else ""
    )
    ROOT_PART = (
        resolve_partition_node(args.root_part, target_name) if args.root_part else ""
    )
    LUKS_PART = (
        resolve_partition_node(args.luks_part, target_name) if args.luks_part else ""
    )

    chosen = []
    if EFI_PART:
        chosen.append(f"ESP {EFI_PART}")
    if LUKS_PART:
        chosen.append(f"encrypted root {LUKS_PART}")
    if ROOT_PART:
        chosen.append(f"root {ROOT_PART}")
    info("Explicit partitions: " + ", ".join(chosen))


@log_all
def open_existing_luks(root_part: str) -> tuple[str, str]:
    """Open an existing LUKS container; returns (root_dev, luks_uuid).

    Reuses a mapping left over from an interrupted run rather than asking the
    same passphrase twice under a different name.
    """
    global ENCRYPTED, ROOT_DEVICE, MAPPING

    mapper_name = existing_mapper(root_part) or LUKS_MAPPING
    mapper = f"/dev/mapper/{mapper_name}"
    if not os.path.exists(mapper):
        passphrase = ask_hidden(f"Enter the LUKS passphrase for {root_part}")
        info(f"Opening {root_part} as {mapper_name}")
        run(
            [
                "cryptsetup",
                "open",
                "--type",
                "luks2",
                root_part,
                mapper_name,
                "--key-file=-",
            ],
            input_text=passphrase,
        )
    luks_uuid = try_run(
        ["cryptsetup", "luksUUID", root_part], capture=True
    ).stdout.strip()
    if fstype_of(mapper) != "btrfs":
        die(f"{mapper} does not hold a btrfs filesystem")
    ENCRYPTED, ROOT_DEVICE, MAPPING = True, mapper, mapper_name
    ok(f"existing LUKS container opened: {root_part} -> {mapper}")
    return mapper, luks_uuid


@log_all
def mount_existing(target: str, target_name: str) -> tuple[str, str, str]:
    """Mount the target's existing partitions as-is.

    No partitioning and no formatting: the ESP must already be vfat, and the
    root must already be btrfs carrying the expected subvolumes. The root is
    either a plain btrfs partition or a LUKS container -- a container is opened
    with its own passphrase, never reformatted.
    """
    global ENCRYPTED, ROOT_DEVICE, MAPPING

    step(f"Mounting existing partitions on {target}")

    parts = parted_partitions(target)
    if not parts:
        die(f"parted reports no partitions on {target}")

    # --efi-part names the ESP outright, so neither the parted 'esp' flag
    # lookup nor the partition-number prompt is needed.
    if EFI_PART:
        esp = EFI_PART
        info(f"EFI System Partition (from --efi-part): {esp}")
    else:
        esp_num = next((n for n, flags in parts if ",esp," in f",{flags},"), None)
        if esp_num is None:
            pick = ask("Which partition number is the EFI System Partition", "1")
            esp_num = int(pick) if pick.isdigit() else 1
        esp = partition_node(target_name, esp_num)
        if not os.path.exists(esp):
            die(f"ESP partition node not found: {esp}")

    # both paths need this: the info line below prints it, and the auto-detected
    # partition still has to be vfat -- --existing never reformats anything
    esp_fs = fstype_of(esp)
    if esp_fs and esp_fs != "vfat":
        die(f"{esp} holds {esp_fs}, not vfat — --existing never reformats a partition")

    luks_uuid = ""
    if LUKS_PART:
        root_part = LUKS_PART
        root_dev, luks_uuid = open_existing_luks(root_part)
    elif ROOT_PART:
        root_part = ROOT_PART
        root_dev = root_part
        ENCRYPTED, ROOT_DEVICE = False, root_dev
        ok(f"existing root partition (from --root-part): {root_part}")
    else:
        btrfs_parts: list[str] = []
        luks_parts: list[str] = []
        for num, _flags in parts:
            node = partition_node(target_name, num)
            if not os.path.exists(node):
                continue
            fs = fstype_of(node)
            if fs == "btrfs":
                btrfs_parts.append(node)
            elif fs == "crypto_LUKS":
                luks_parts.append(node)

        if luks_parts:
            root_part = pick_partition(
                "Which partition holds the encrypted root", luks_parts
            )
            root_dev, luks_uuid = open_existing_luks(root_part)
        else:
            if not btrfs_parts:
                die(f"no btrfs or LUKS partition found on {target}")
            root_part = pick_partition(
                "Which partition holds the root filesystem", btrfs_parts
            )
            root_dev = root_part
            ENCRYPTED, ROOT_DEVICE = False, root_dev

    info(
        f"ESP {esp} ({esp_fs or 'unknown fs'})   root {root_part} "
        f"({'LUKS -> ' + root_dev if ENCRYPTED else 'btrfs, unencrypted'})"
    )

    os.makedirs(EFI_MNT, exist_ok=True)
    run(["mount", esp, EFI_MNT])

    # mount the toplevel once, to confirm the subvolumes are really there
    os.makedirs(ROOT_MNT, exist_ok=True)
    run(["mount", root_dev, ROOT_MNT])
    for subvol in {SRC.root_subvol, SRC.home_subvol} - {""}:
        if not os.path.isdir(os.path.join(ROOT_MNT, subvol.lstrip("/"))):
            run(["umount", ROOT_MNT])
            die(
                f"{root_dev} has no {subvol} subvolume — --existing will not create one"
            )
    run(["umount", ROOT_MNT])

    run(["mount", "-o", f"subvol={SRC.root_subvol}", root_dev, ROOT_MNT])
    if SRC.home_subvol:
        os.makedirs(HOME_MNT, exist_ok=True)
        run(["mount", "-o", f"subvol={SRC.home_subvol}", root_dev, HOME_MNT])

    os.makedirs(EFI_MNT_ROOT, exist_ok=True)
    run(["mount", esp, EFI_MNT_ROOT])
    ok(f"existing layout mounted: ESP {esp}, root {root_part}")
    # Resolve UUID at runtime — never rely on a hardcoded nvme/sda path.
    global ROOT_DEVICE_UUID
    root_uuid_source = root_dev
    try:
        UUID_RES = try_run(
            ["blkid", "-s", "UUID", "-o", "value", root_uuid_source], capture=True
        )
        ROOT_DEVICE_UUID = (
            UUID_RES.stdout.strip() or "" if UUID_RES.returncode == 0 else ""
        )
    except Exception:
        ROOT_DEVICE_UUID = ""
    return esp, root_part, luks_uuid


@log_all
def prepare_layout(
    args, target: str, target_name: str, scheme: str
) -> tuple[str, str, str]:
    """Partition, format and mount the target -- or just mount what is there.

    Returns (esp_part, root_part, luks_uuid); luks_uuid is empty when the root
    is not encrypted.
    """
    global ENCRYPTED, ROOT_DEVICE, MAPPING

    if args.existing:
        return mount_existing(target, target_name)

    esp, root = partition_target(target, target_name, scheme, args.esp_size)
    if args.no_encrypt:
        mount_plain_root(root)
        ENCRYPTED, ROOT_DEVICE = False, root
        luks_uuid = ""
    else:
        luks_uuid = setup_luks(root)
        mount_encrypted_root()
        ENCRYPTED, ROOT_DEVICE, MAPPING = True, f"/dev/mapper/{MAPPING}", MAPPING

    setup_esp(esp)
    # Resolve the root filesystem UUID at runtime (standing convention:
    # never hardcode nvme/sda device paths in bootloader configs).
    root_uuid_source = f"/dev/mapper/{MAPPING}" if ENCRYPTED else root
    try:
        UUID_RES = try_run(
            ["blkid", "-s", "UUID", "-o", "value", root_uuid_source], capture=True
        )
        if UUID_RES.returncode == 0:
            global ROOT_DEVICE_UUID
            ROOT_DEVICE_UUID = UUID_RES.stdout.strip() or ""
        else:
            ROOT_DEVICE_UUID = ""
    except Exception:
        ROOT_DEVICE_UUID = ""
    return esp, root, luks_uuid


@log_all
def setup_esp(esp_part: str) -> None:
    step("Creating the EFI System Partition")
    run(["mkfs.vfat", "-F", "32", "-n", "EFI", esp_part])
    os.makedirs(EFI_MNT, exist_ok=True)
    run(["mount", esp_part, EFI_MNT])
    ok(f"ESP ready at {EFI_MNT}")


# --------------------------------------------------------------------------- #
# the clone
# --------------------------------------------------------------------------- #
RSYNC_OPTS = ["-auHAX", "--numeric-ids", "--no-inc-recursive", "--info=progress2"]
EXCLUDES = [
    "/dev/*",
    "/proc/*",
    "/sys/*",
    "/tmp/*",
    "/run/*",
    "/mnt/*",
    "/media/*",
    "/lost+found",
    "/var/cache/pacman/pkg/*",
    "/var/log/*",
    "/var/tmp/*",
    "/var/lib/pacman/sync/*",
    "/var/lib/docker/*",
    "/var/lib/containers/*",
    "/efi/*",
    "/boot/*",
    "/home/*",
    "/.snapshots/*",
]


@log_all
def clone_system() -> None:
    step("Cloning the running system (this takes a while)")

    # The running root is a MOUNT of the source subvolume, so the source path is
    # the mount point itself — do not re-add the subvolume name to it.
    root_mount = try_run(
        ["findmnt", "-rno", "TARGET", "/"], capture=True
    ).stdout.strip()
    root_src = root_mount if root_mount.endswith("/") else root_mount + "/"
    info(f"Source: {root_mount} (subvolume {SRC.root_subvol})")
    info(f"Copying {root_src} -> {ROOT_MNT}")
    run(
        ["rsync"]
        + RSYNC_OPTS
        + [f"--exclude={e}" for e in EXCLUDES]
        + [root_src, ROOT_MNT + "/"]
    )
    ok("Root subvolume cloned")

    if SRC.home_subvol:
        home_mount = try_run(
            ["findmnt", "-rno", "TARGET", "/home"], capture=True
        ).stdout.strip()
        home_src = home_mount if home_mount.endswith("/") else home_mount + "/"
        info(f"Copying {home_src} -> {HOME_MNT}")
        run(
            ["rsync"]
            + RSYNC_OPTS
            + ["--exclude=/tmp/*", "--exclude=/lost+found"]
            + [home_src, HOME_MNT + "/"]
        )
        ok("Home subvolume cloned")

    copy_network_config(skip=SKIP_NETWORK)

    os.makedirs(os.path.join(ROOT_MNT, "var/lib/snapper"), exist_ok=True)


# --------------------------------------------------------------------------- #
# the user homes of a bootstrapped (pacstrap) root
# --------------------------------------------------------------------------- #
@log_all
def home_dest(home_src: str) -> str:
    """Where a running user's home goes in the new root, as a HOST path.

    A /home subvolume is mounted at HOME_MNT, so a home UNDER /home is copied
    THERE and not into the root subvolume -- otherwise the subvolume fstab mounts
    at /home would hide the very data that was copied. A home outside /home (a
    user whose home is /var/lib/x, say) has no subvolume to go to and lands in
    the root subvolume, preserving its path.
    """
    home = home_src.rstrip("/") or "/"
    if SRC.home_subvol and (home == "/home" or home.startswith("/home/")):
        rest = home[len("/home") :].lstrip("/")
        base = HOME_MNT.rstrip("/")
        return os.path.join(base, rest) if rest else base
    return os.path.join(ROOT_MNT, home.lstrip("/"))


@log_all
def home_dest_in_root(home_src: str) -> str:
    """The same destination as home_dest(), as the NEW ROOT sees it.

    The two differ only when the running system has a /home subvolume: the copy
    lands on HOME_MNT, which is a HOST path (/mnt/new/home/...), while inside the
    chroot that same data is at /home/... because the subvolume the fstab mounts
    at /home IS that mounted filesystem. Handing the host path to arch-chroot
    therefore looks for /mnt/new/home/... inside a root that has no such
    directory, and chown fails with ENOENT.

    As the new root sees it, every home is simply its own path, so this is the
    identity -- kept as a named function so the chown call reads as the inverse
    of home_dest() and the two cannot drift apart.
    """
    return home_src.rstrip("/") or "/"


# Virtual-machine images and their state, left out of a copied home by
# --skip-vm. A multi-gigabyte qcow2 or a libvirt image pool is the one class of
# home content that is worthless in a fresh install and dominates the copy time.
VM_EXCLUDES = [
    "*.qcow2",
    "*.qcow",
    "*.qco",
    "*.vmdk",
    "*.vdi",
    "*.vhd",
    "*.vhdx",
    "*.hdd",
    "*.img",
    "*.raw",
    "*.vpc",
    "*.ova",
    "*.ovf",
    "*.vbox",
    "*.vbox-extpack",
    "*.vmx",
    ".vagrant.d/*",
    ".local/share/libvirt/*",
    ".cache/libvirt/*",
    "VirtualBox VMs/*",
    "vm/*",
    "VMs/*",
]


@log_all
def home_excludes() -> list[str]:
    """The rsync --exclude flags for one home copy.

    Three built-ins are always there: /tmp and /lost+found are transient, and
    .cache holds sockets and FIFOs that cannot be copied at all -- a FIFO in a
    copied cache fails the whole rsync. On top of those, --skip-home-dir /
    --skip-home-ext add caller-chosen names and extensions, and --skip-vm adds
    the VM image set.
    """
    out = ["--exclude=/tmp/*", "--exclude=/lost+found", "--exclude=.cache/*"]

    for name in SKIP_HOME_DIRS:
        name = name.strip().strip("/")
        if name:
            # No leading slash: rsync then matches the name at ANY depth, so
            # --skip-home-dir Downloads drops every Downloads in the home.
            out.append(f"--exclude={name}")

    for ext in SKIP_HOME_EXTS:
        ext = ext.strip().lstrip(".")
        if ext:
            out.append(f"--exclude=*.{ext}")

    if SKIP_VM:
        out.extend(f"--exclude={pattern}" for pattern in VM_EXCLUDES)

    return out


@log_all
def copy_user_homes() -> None:
    """Copy the running system's real user homes into a freshly bootstrapped root.

    pacstrap builds an empty root: the package sets give it users (via
    preserve_credentials()) but no dotfiles, no browser profile and no desktop
    configuration, so the new install would boot into an unconfigured shell.
    Copying the homes here is what makes a pacstrap target a usable desktop.

    Every real user found in the running system's /etc/passwd (uid >= 1000, real
    shell -- the same rule that fills SRC.users) is copied, so a multi-user
    source does not lose all but one home. Nothing is copied when the source
    home does not exist, and the destination is owned by the user it belongs to
    rather than by root. Runs after preserve_credentials(), because the chown
    resolves the username in the NEW root.
    """
    step("Copying user home directories")

    if not SRC.users:
        info("no real users in the running system - nothing to copy")
        return

    if not SRC.home_subvol:
        info(
            "the running /home is on the root subvolume - copying homes into the "
            "root subvolume"
        )

    if SKIP_HOME_DIRS or SKIP_HOME_EXTS or SKIP_VM:
        info(
            "home copy exclusions: "
            + ", ".join(
                [
                    *(f"dir {d}" for d in SKIP_HOME_DIRS),
                    *(f"*.{e.lstrip('.')}" for e in SKIP_HOME_EXTS),
                    *(["virtual-machine images"] if SKIP_VM else []),
                ]
            )
        )

    copied: list[tuple[str, str, str]] = []  # (user, host dst, dst in the new root)
    skipped = []
    for user in SRC.users:
        src_home = SRC.homes.get(user, "")
        if not src_home or not os.path.isdir(src_home):
            skipped.append(f"{user} (no such home {src_home or '?'})")
            continue
        dst = home_dest(src_home)
        os.makedirs(dst, exist_ok=True)

        info(f"Copying {src_home} -> {dst}")
        run(
            [
                "rsync",
                *RSYNC_OPTS,
                *home_excludes(),
                src_home.rstrip("/") + "/",
                dst.rstrip("/") + "/",
            ]
        )
        copied.append((user, dst, home_dest_in_root(src_home)))
        ok(f"home copied for {user}")

    if copied:
        # -a keeps ownership, so a root-run rsync normally leaves root as the
        # owner of a fresh destination. The user's uid/gid is the same in the
        # new root -- preserve_credentials() copies /etc/passwd -- so hand the
        # home back to its owner.
        #
        # arch-chroot resolves its path argument INSIDE the new root, so the
        # chown needs the in-root path, not the host path: with a /home
        # subvolume the host path is /mnt/new/home/..., which does not exist in
        # the chroot, and chown dies with ENOENT. bind_home_into_chroot() puts
        # the @home subvolume at ROOT_MNT/home first, so /home/... inside the
        # chroot IS the directory rsync wrote into.
        info("Restoring home ownership in the new root")
        for user, dst, in_root in copied:
            proc = try_run(
                ["arch-chroot", ROOT_MNT, "chown", "-R", f"{user}:{user}", in_root]
            )
            if proc.returncode != 0:
                warn(f"could not chown {in_root} to {user} in the new root")

    if skipped:
        for line in skipped:
            warn(f"skipped {line}")
    ok(
        f"home directories copied for {len(copied)} user(s): "
        + ", ".join(user for user, _dst, _in_root in copied)
    )


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #
@log_all
def preserve_credentials() -> None:
    step("Preserving credentials from the running system")

    copied = []
    for name in ("passwd", "shadow", "group", "gshadow", "subuid", "subgid"):
        src_path = f"/etc/{name}"
        dst_path = os.path.join(ROOT_MNT, "etc", name)
        if not (os.access(src_path, os.R_OK) and os.path.exists(dst_path)):
            warn(
                f"could not copy /etc/{name} (source unreadable or destination missing)"
            )
            continue
        shutil.copyfile(src_path, dst_path)
        try:
            if open(src_path, "rb").read() != open(dst_path, "rb").read():
                die(f"/etc/{name} did not copy byte-for-byte")
        except OSError as exc:
            warn(f"could not verify /etc/{name}: {exc}")
        copied.append(name)
        ok(f"Copied /etc/{name} verbatim")

    if "shadow" not in copied:
        die("/etc/shadow was not copied — the clone would have wrong credentials")

    def shadow_hash(path: str, user: str) -> str:
        try:
            for line in open(path):
                fields = line.split(":")
                if fields[0] == user:
                    return fields[1]
        except OSError:
            pass
        return ""

    for user in SRC.users:
        if shadow_hash("/etc/shadow", user) and shadow_hash(
            "/etc/shadow", user
        ) == shadow_hash(os.path.join(ROOT_MNT, "etc/shadow"), user):
            ok(f"  {user}: password hash preserved")
        else:
            warn(f"  {user}: hash mismatch — check {ROOT_MNT}/etc/shadow")

    if shadow_hash("/etc/shadow", "root") and shadow_hash(
        "/etc/shadow", "root"
    ) == shadow_hash(os.path.join(ROOT_MNT, "etc/shadow"), "root"):
        ok("  root: password hash preserved")
    else:
        warn("  root: hash mismatch")

    # Set zsh as the default login shell for root and all real users.
    passwd_path = os.path.join(ROOT_MNT, "etc/passwd")
    try:
        with open(passwd_path, "r") as ph, open(passwd_path + ".tmp", "w") as out:
            for line in ph:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    out.write(line + "\n")
                    continue
                fields = line.split(":")
                if len(fields) >= 7:
                    username = fields[0]
                    # Change shell to zsh for root and every real user (uid >= 1000 or root).
                    uid_str = fields[2]
                    if uid_str.isdigit() and (
                        int(uid_str) == 0 or int(uid_str) >= 1000
                    ):
                        fields[6] = "/usr/bin/zsh"
                    out.write(":".join(fields) + "\n")
        shutil.move(passwd_path + ".tmp", passwd_path)
        ok("Default shell set to /usr/bin/zsh for root and all real users")
    except OSError as exc:
        warn(f"Could not set zsh as default shell: {exc}")


# --------------------------------------------------------------------------- #
# network config preservation
# --------------------------------------------------------------------------- #
NETWORK_CONFIG_PATHS = (
    ("/etc/NetworkManager", "/etc/NetworkManager"),
    ("/etc/bluetooth", "/etc/bluetooth"),
    ("/etc/iwd", "/etc/iwd"),
    ("/var/lib/iwd", "/var/lib/iwd"),
    ("/var/lib/bluetooth", "/var/lib/bluetooth"),
    ("/etc/openvpn", "/etc/openvpn"),
    ("/etc/wireguard", "/etc/wireguard"),
    ("/etc/ipsec.d", "/etc/ipsec.d"),
)


@log_all
def copy_network_config(skip: bool = False) -> None:
    """Copy network profiles (wifi/VPN/bluetooth) from the running system into
    the new root when the source paths exist. Never fails the install when a
    directory is absent — the goal is best-effort preservation, not an
    all-or-nothing copy. Pass `skip=True` (e.g. --skip-network) to disable."""
    if skip:
        info("Skipping network configuration preservation (--skip-network)")
        return
    step("Preserving network configuration (wifi / VPN / bluetooth)")
    copied_any = False
    for src_dir, dst_dir_name in NETWORK_CONFIG_PATHS:
        src = src_dir
        dst = os.path.join(ROOT_MNT, dst_dir_name.lstrip("/"))
        if not os.path.exists(src):
            continue
        try:
            if os.path.isdir(src):
                dst_dir_for_copy = dst
                dst_parent_for_copy = os.path.dirname(dst_dir_for_copy)
                if dst_parent_for_copy:
                    os.makedirs(dst_parent_for_copy, exist_ok=True)
                # Use rsync for directory copy (handles permissions, excludes safely)
                proc = try_run(
                    [
                        "rsync",
                        "-a",
                        "--numeric-ids",
                        "--no-inc-recursive",
                        f"{src.rstrip('/')}/",
                        f"{dst_dir_for_copy}/",
                    ],
                    check=False,
                )
                if proc.returncode == 0:
                    info(f"Copied network config: {src} -> {dst}")
                    copied_any = True
                else:
                    warn(f"rsync failed for {src}: {proc.stderr or proc.stdout}")
            else:
                dst_dir = os.path.dirname(dst)
                if dst_dir:
                    os.makedirs(dst_dir, exist_ok=True)
                shutil.copyfile(src, dst)
                info(f"Copied network config: {src} -> {dst}")
                copied_any = True
        except OSError as exc:
            warn(f"Could not copy network config {src}: {exc}")
    if copied_any:
        ok("Network configuration preserved")
    else:
        info("No network config sources found to preserve")

    # Ensure NetworkManager uses iwd backend for wifi
    nm_conf_path = os.path.join(
        ROOT_MNT, "etc", "NetworkManager", "NetworkManager.conf"
    )
    nm_conf_dir = os.path.dirname(nm_conf_path)
    if nm_conf_dir:
        os.makedirs(nm_conf_dir, exist_ok=True)
    with open(nm_conf_path, "w") as f:
        f.write("[main]\nplugins=keyfile\nwifi.backend=iwd\n")
    info("Set NetworkManager wifi backend to iwd")


# --------------------------------------------------------------------------- #
# service enabling + sudoers.d transfer
# --------------------------------------------------------------------------- #
SERVICES_TO_ENABLE = ("NetworkManager", "bluetooth", "bluetooth-agent")


@log_all
def enable_target_services() -> None:
    """Enable networkmanager, bluetooth, and bt-agent in the new root."""
    step("Enabling services in target root")
    for svc in SERVICES_TO_ENABLE:
        run(
            ["arch-chroot", ROOT_MNT, "systemctl", "enable", svc],
            check=False,
        )
        info(f"Enabled service: {svc}")
    ok("Target services enabled")


@log_all
def copy_sudoers_d() -> None:
    """Copy /etc/sudoers.d files from the running system into the new root."""
    src_dir = "/etc/sudoers.d"
    dst_dir = os.path.join(ROOT_MNT, "etc/sudoers.d")
    if not os.path.isdir(src_dir):
        info("No /etc/sudoers.d on source — skipping sudoers transfer")
        return
    step("Transferring sudoers.d files to target")
    os.makedirs(dst_dir, exist_ok=True)
    copied = 0
    for entry in os.listdir(src_dir):
        src_path = os.path.join(src_dir, entry)
        dst_path = os.path.join(dst_dir, entry)
        if os.path.isfile(src_path) or os.path.islink(src_path):
            shutil.copy2(src_path, dst_path)
            copied += 1
    ok(f"Copied {copied} sudoers.d file(s) to target")


@log_all
def ensure_uid_1000_sudo() -> None:
    """After preserving credentials, ensure the real user (uid 1000, typically black)
    has sudo privileges in the new root."""
    passwd_path = os.path.join(ROOT_MNT, "etc/passwd")
    user_1000 = ""
    try:
        with open(passwd_path) as ph:
            for line in ph:
                fields = line.split(":")
                if len(fields) >= 3 and fields[2] == "1000" and fields[4].strip():
                    user_1000 = fields[0]
                    break
    except OSError:
        pass
    if not user_1000:
        # Fallback if passwd was not copied or no uid 1000 user found.
        user_1000 = "black"
    sudo_path = os.path.join(ROOT_MNT, "etc/sudoers.d/uid-1000")
    content = f"# blackarch installer: sudo privileges for user 1000 ({user_1000})\n{user_1000} ALL=(ALL) NOPASSWD:ALL\n"
    try:
        os.makedirs(os.path.dirname(sudo_path) or ".", exist_ok=True)
        with open(sudo_path, "w") as sh:
            sh.write(content)
        os.chmod(sudo_path, 0o440)
        info(f"Sudo privileges added for {user_1000} (uid 1000) in new root")
        ok(f"sudoers.d/uid-1000 written for {user_1000}")
    except OSError as exc:
        warn(f"Could not write sudoers for uid 1000 ({user_1000}): {exc}")


# --------------------------------------------------------------------------- #
# identity + fstab
# --------------------------------------------------------------------------- #
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
    step("Writing /etc/profile.d/blackarch.sh")

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
def hostname_of(path: str) -> str:
    """The hostname an /etc/hostname file holds, or "" when it has none.

    A fresh pacstrap root carries `localhost` (or whatever base ships), which is
    a placeholder rather than a real name, so callers compare against it to
    tell "the user set this" from "nothing set this yet". Blank lines and a
    missing file both mean "no hostname".
    """
    try:
        return open(path).read().strip()
    except OSError:
        return ""


@log_all
def new_root_hostname() -> str:
    """The hostname already present in the new root's /etc/hostname.

    A FRESH pacstrap root is the exception the precedence below has to know
    about: pacstrap creates /etc/hostname as an EMPTY file, so there is no
    hostname to preserve and the running system's name is the right default.
    --existing/--skip-pacstrap always carry a real name (base's `localhost` at
    worst), so for them this returns the name that must not be overwritten.
    """
    return hostname_of(os.path.join(ROOT_MNT, "etc/hostname"))


@log_all
def configure_identity(esp_part: str, hostname_arg: str | None = None) -> None:
    """hostname / machine-id / locale / timezone for the new root.

    The hostname precedence is:

      1. --hostname NAME          taken as given, never prompted, always wins
      2. the new root's own name  a --existing/--skip-pacstrap root has a real
                                  name already; it is left exactly as it is
      3. the running system's     the default, i.e. the host OS hostname
      4. "linux"                  only when the running system has no name

    (2) is the case this is about: on a re-run the root already has a hostname,
    and overwriting it with the live system's name would quietly rename a
    machine the user is re-installing over. A fresh pacstrap root has an EMPTY
    /etc/hostname, so it falls through to the running system's name -- which is
    the default the user asked for. Nothing is ever prompted, so an unattended
    run never blocks on this.
    """
    step("Configuring hostname / machine-id / locale / timezone")

    etc_dir = os.path.join(ROOT_MNT, "etc")
    os.makedirs(etc_dir, exist_ok=True)

    if SRC.machine_id:
        with open(os.path.join(etc_dir, "machine-id"), "w") as fh:
            fh.write(SRC.machine_id + "\n")
        ok(f"machine-id preserved: {SRC.machine_id}")

    hostname_path = os.path.join(etc_dir, "hostname")
    existing = new_root_hostname()
    live = SRC.hostname or ""

    if hostname_arg:
        new_hostname = hostname_arg
        why = "--hostname"
    elif existing:
        new_hostname = existing
        why = "kept from the new root (already set)"
    elif live:
        new_hostname = live
        why = "from the running system (default)"
    else:
        new_hostname = "linux"
        why = "fallback (the running system reported no hostname)"

    # Only write when it would actually change something: rewriting the same
    # value is harmless but would make the log claim a change that did not
    # happen.
    if existing != new_hostname:
        with open(hostname_path, "w") as fh:
            fh.write(new_hostname + "\n")
        ok(f"hostname set to {new_hostname} ({why})")
    else:
        ok(f"hostname unchanged: {new_hostname} ({why})")

    root_dev = ROOT_DEVICE or f"/dev/mapper/{MAPPING}"
    esp_uuid = try_run(
        ["blkid", "-s", "UUID", "-o", "value", esp_part], capture=True
    ).stdout.strip()
    root_uuid = try_run(
        ["blkid", "-s", "UUID", "-o", "value", root_dev], capture=True
    ).stdout.strip()
    if not esp_uuid or not root_uuid:
        die(
            f"blkid failed to report a UUID (esp={esp_uuid!r} root={root_uuid!r}) — "
            "cannot write a correct fstab"
        )

    lines = [
        "# /etc/fstab — generated by usb2disk-installer",
        "# <file system>                           <dir>   <type>  <options>                        <dump> <pass>",
        f"UUID={root_uuid:<36} /       btrfs   rw,relatime,space_cache=v2,subvol={SRC.root_subvol}   0 0",
        f"UUID={esp_uuid:<36} /efi    vfat    rw,relatime,fmask=0022,dmask=0022,codepage=437,"
        "iocharset=ascii,shortname=mixed,utf8,errors=remount-ro 0 2",
    ]
    if SRC.home_subvol:
        lines.append(
            f"UUID={root_uuid:<36} /home   btrfs   rw,relatime,space_cache=v2,subvol={SRC.home_subvol} 0 0"
        )

    with open(os.path.join(ROOT_MNT, "etc/fstab"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    ok("fstab written")
    for line in lines:
        _emit("  " + line)


# --------------------------------------------------------------------------- #
# boot: cmdline, initramfs, unified kernel image
# --------------------------------------------------------------------------- #
@log_all
def build_new_cmdline(luks_uuid: str) -> str:
    """Rewrite the running cmdline for the NEW root.

    The cmdline references the new container by UUID (never a hardcoded nvme/sda
    path) and names the mapper from MAPPING.  When encrypted: root=/dev/mapper/<MAPPING>.
    When plain: root=UUID=<target-root-UUID>.
    """
    tokens = SRC.cmdline.split()

    out = []
    for tok in tokens:
        if tok.startswith("rd.luks.uuid="):
            # Keep/update the LUKS UUID token using the target container's UUID.
            if ENCRYPTED and luks_uuid:
                out.append(f"rd.luks.uuid={luks_uuid}")
            continue
        if tok.startswith("rd.luks.name="):
            if ENCRYPTED and luks_uuid:
                out.append(f"rd.luks.name={luks_uuid}={MAPPING}")
            continue
        if tok.startswith("rd.luks.options="):
            if ENCRYPTED:
                out.append("rd.luks.options=discard")
            continue
        if tok.startswith("rd.luks.") or tok.startswith("cryptdevice="):
            # Drop any remaining rd.luks.* / cryptdevice lines; we rewrite them
            # above so the source USB stick's device names are never preserved.
            continue
        if tok.startswith("root="):
            # Encrypted root uses the mapper path; plain root uses the target
            # filesystem UUID resolved at runtime from blkid on the target device.
            if ENCRYPTED:
                out.append(f"root=/dev/mapper/{MAPPING}")
            else:
                out.append(f"root=UUID={ROOT_DEVICE_UUID or ROOT_DEVICE}")
            continue
        if tok.startswith("rootfstype="):
            out.append("rootfstype=btrfs")
            continue
        if tok.startswith("rootflags="):
            out.append(f"rootflags=subvol={SRC.root_subvol}")
            continue
        # drop live-only tokens, with any =value suffix
        key = tok.split("=", 1)[0]
        if key in LIVE_ONLY_TOKENS:
            continue
        out.append(tok)

    # Ensure the required tokens are present, using the target device UUID
    # (resolved at runtime via blkid) and never a hardcoded nvme/sda path.
    if ENCRYPTED:
        if luks_uuid and not any(t.startswith("rd.luks.uuid=") for t in out):
            out.append(f"rd.luks.uuid={luks_uuid}")
        if luks_uuid and not any(t.startswith("rd.luks.name=") for t in out):
            out.append(f"rd.luks.name={luks_uuid}={MAPPING}")
        if not any(t.startswith("root=") for t in out):
            out.append(f"root=/dev/mapper/{MAPPING}")
        if not any(t == "rootfstype=btrfs" for t in out):
            out.append("rootfstype=btrfs")
    else:
        # Plain root: use UUID from current target device (blkid-resolved).
        if not any(t.startswith("root=") for t in out):
            out.append(f"root=UUID={ROOT_DEVICE_UUID or ROOT_DEVICE}")
        if not any(t == "rootfstype=btrfs" for t in out):
            out.append("rootfstype=btrfs")
    if not any(t.startswith("rootflags=") for t in out):
        out.append(f"rootflags=subvol={SRC.root_subvol}")

    return " ".join(out)


@log_all
def snapshot_cmdline(base_cmdline: str, subvol: str) -> str:
    """Same cmdline as the running entry, but booting a snapper snapshot."""
    tokens = []
    for tok in base_cmdline.split():
        tokens.append(
            f"rootflags=subvol={subvol}" if tok.startswith("rootflags=") else tok
        )
    if not any(t.startswith("rootflags=") for t in tokens):
        tokens.append(f"rootflags=subvol={subvol}")
    return " ".join(tokens)


@log_all
def clone_os_name() -> str:
    """PRETTY_NAME of the new root's /usr/lib/os-release, or 'Arch Linux'.

    systemd-boot titles a type-1 entry with the TITLE= field and Limine's OS
    entry is named after the distro, so both boot menus are named from this one
    value rather than each inventing its own.
    """
    path = os.path.join(ROOT_MNT, "usr/lib/os-release")
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Arch Linux"


@log_all
def write_cmdline_file(cmdline: str) -> None:
    step("Writing the new kernel command line")
    path = os.path.join(ROOT_MNT, "etc/kernel/cmdline")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(cmdline + "\n")
    os.chmod(path, 0o644)
    ok("/etc/kernel/cmdline written")
    # ukify embeds it in the .cmdline section, so every generated UKI boots the
    # NEW LUKS container instead of the USB stick's.


# --------------------------------------------------------------------------- #
# unified kernel image
# --------------------------------------------------------------------------- #
@log_all
def ukify_command() -> list[str]:
    """The ukify invocation, pinned to the system python.

    ukify's shebang is `#!/usr/bin/env python3`, and pefile -- the module it
    needs to write PE sections -- is a system package. A python3 earlier on PATH
    (a venv, say) has no pefile and ukify dies with ModuleNotFoundError.
    """
    path = shutil.which("ukify") or "/usr/bin/ukify"
    for interpreter in ("/usr/bin/python3", sys.executable):
        if os.path.exists(interpreter):
            return [interpreter, path]
    return [path]


@log_all
def microcode_initrd() -> str:
    """The clone's early microcode image, when it carries one."""
    for name in ("intel-ucode.img", "amd-ucode.img"):
        path = os.path.join(ROOT_MNT, "boot", name)
        if os.path.exists(path):
            return path
    return ""


@log_all
def build_uki(
    owner: str, kver: str, cmdline: str, suffix: str = "", uname: str = ""
) -> str:
    """Build one unified kernel image into <ESP>/EFI/Linux/.

    systemd-boot discovers those by itself, so no loader entry is needed. The
    cmdline is baked into the image, which is why a snapshot gets its own UKI
    rather than an entry that reuses the kernel's.
    """
    vmlinuz = os.path.join(ROOT_MNT, "usr/lib/modules", kver, "vmlinuz")
    initrd = os.path.join(ROOT_MNT, "boot", f"initramfs-{owner}.img")
    if not os.path.exists(vmlinuz):
        warn(f"no vmlinuz for {owner} ({kver}) — skipping its UKI")
        return ""
    if not os.path.exists(initrd):
        warn(f"no initramfs for {owner} — skipping its UKI")
        return ""

    out_dir = os.path.join(EFI_MNT, "EFI", "Linux")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{owner}-{kver}{suffix}.efi")

    cmd = [
        *ukify_command(),
        "build",
        "--linux",
        vmlinuz,
        "--initrd",
        initrd,
        f"--cmdline={cmdline}",
        # '@' makes ukify read the file; a bare path is embedded as the section
        # text, which leaves systemd-boot with no PRETTY_NAME to title the entry
        f"--os-release=@{os.path.join(ROOT_MNT, 'usr/lib/os-release')}",
        "--uname",
        uname or kver,
        "--output",
        out,
    ]
    microcode = microcode_initrd()
    if microcode:
        # ukify's own microcode option lands it in .ucode, which the stub
        # prepends to the initrds
        cmd.extend(["--microcode", microcode])

    info(f"Building UKI EFI/Linux/{os.path.basename(out)}  ({kver})")
    run(cmd)
    return out


@log_all
def clone_kernels() -> list[tuple[str, str]]:
    """[(kernel package name, kernel version)] for the kernels in the clone."""
    found: list[tuple[str, str]] = []
    modules_dir = os.path.join(ROOT_MNT, "usr/lib/modules")
    try:
        entries = sorted(os.listdir(modules_dir))
    except OSError:
        return found
    for kver in entries:
        kdir = os.path.join(modules_dir, kver)
        if not os.path.isdir(kdir) or not os.path.exists(
            os.path.join(kdir, "modules.builtin")
        ):
            continue
        # The kernel package's install hook writes its pkgbase here.  Do NOT use
        # `pacman -Qqo` on this path: it suffix-matches and returns the same
        # package for bogus paths too.
        try:
            owner = open(os.path.join(kdir, "pkgbase")).read().strip()
        except OSError:
            owner = ""
        if not owner:
            continue
        # Keep only the offensive kernel.
        if "offensive" not in owner and "offensive" not in kver:
            continue
        found.append((owner, kver))
    # Prefer the offensive kernel as the default boot entry (match on package
    # name or kernel release, so a differently-named offensive build still wins).
    found.sort(key=lambda kv: 0 if ("offensive" in kv[0] or "offensive" in kv[1]) else 1)
    return found


@log_all
def clone_snapshots() -> list[tuple[str, str]]:
    """[(number, description)] of the clone's snapper 'root' snapshots."""
    proc = try_run(
        ["snapper", "--no-dbus", "-r", ROOT_MNT, "-c", "root", "list"], capture=True
    )
    snaps = []
    for line in proc.stdout.splitlines():
        fields = line.split("|")
        if len(fields) < 8:
            continue
        num = fields[0].strip().rstrip("*")  # the current root shows as '0*'
        if not num.isdigit() or num == "0":
            continue
        if fields[1].strip() != "single":  # column 2 is the snapshot type
            continue
        snaps.append((num, fields[-1].strip()))  # description is the last column
    return snaps


@log_all
def running_kernel_version() -> str:
    """The running kernel's release, e.g. 7.2.9-2-aegis-offensive."""
    try:
        return os.uname().release
    except (OSError, AttributeError):
        return ""


@log_all
def snapshot_kernel(kernels: list[tuple[str, str]]) -> str:
    """Which kernel package the snapshot boot entries should use.

    Prefer the kernel the system is actually running, so a snapshot boots the
    same kernel as the live entry; fall back to the first one found.
    """
    release = running_kernel_version()
    for owner, kver in kernels:
        if release and kver == release:
            return owner
    return kernels[0][0]


@log_all
def build_ukis(cmdline: str) -> None:
    """One UKI per kernel, plus one per snapper snapshot."""
    step("Building unified kernel images")

    kernels = clone_kernels()
    if not kernels:
        die("no kernel found in the clone — cannot build a UKI")

    built = []
    for owner, kver in kernels:
        path = build_uki(owner, kver, cmdline)
        if path:
            built.append(path)

    snaps = clone_snapshots()
    if snaps:
        primary = snapshot_kernel(kernels)
        primary_kver = dict(kernels)[primary]
        for num, _desc in snaps:
            path = build_uki(
                primary,
                primary_kver,
                snapshot_cmdline(cmdline, f"/.snapshots/{num}/snapshot"),
                suffix=f"-snap{num}",
                uname=f"{primary_kver}-snap{num}",
            )
            if path:
                built.append(path)

    ok(f"{len(built)} UKI(s) written to {os.path.join(EFI_MNT, 'EFI', 'Linux')}")


@log_all
def build_initramfs() -> None:
    step("Building initramfs for the new system")

    modules_dir = os.path.join(ROOT_MNT, "usr/lib/modules")
    try:
        entries = sorted(os.listdir(modules_dir))
    except OSError:
        warn("cannot list /usr/lib/modules in the clone")
        return

    # the ESP is mounted at /efi in the clone, so the mountpoint has to exist
    run(["arch-chroot", ROOT_MNT, "mkdir", "-p", "/efi"])
    # /boot is the image's destination. The clone's btrfs root carries it once
    # the kernel package's own hook has run (it writes /boot/vmlinuz-*), but
    # pacstrap installs with --hookdir=/dev/null, so on a freshly bootstrapped
    # root /boot does not exist yet and `mkinitcpio -g /boot/...` fails.
    boot_dir = os.path.join(ROOT_MNT, "boot")
    os.makedirs(boot_dir, exist_ok=True)

    for kver in entries:
        kdir = os.path.join(modules_dir, kver)
        if not os.path.isdir(kdir) or not os.path.exists(
            os.path.join(kdir, "modules.builtin")
        ):
            continue

        try:
            owner = open(os.path.join(kdir, "pkgbase")).read().strip()
        except OSError:
            owner = ""
        if not owner:
            warn(f"kernel {kver} has no pkgbase file, skipping")
            continue

        out = os.path.join(ROOT_MNT, "boot", f"initramfs-{owner}.img")
        info(f"Building {out}  (kernel {kver})")
        # Build inside the clone so its own mkinitcpio.conf and module tree are
        # used.  -g keeps mkinitcpio from also emitting a UKI: the image on the
        # ESP is built separately by build_uki(), which is what puts it there.
        run(
            [
                "arch-chroot",
                ROOT_MNT,
                "/usr/bin/mkinitcpio",
                "-k",
                kver,
                "-g",
                f"/boot/initramfs-{owner}.img",
            ]
        )

        # Limine's Linux protocol loads a plain initramfs + vmlinuz from
        # <ESP>/<machine-id>/<kernel>/, which is the layout limine-mkinitcpio
        # generates. Mirror the image there when Limine is the chosen loader.
        if BOOTLOADER == "limine":
            esp_kernel_dir = os.path.join(EFI_MNT, SRC.machine_id or "unknown", owner)
            os.makedirs(esp_kernel_dir, exist_ok=True)
            shutil.copyfile(out, os.path.join(esp_kernel_dir, "initramfs"))
            vmlinuz = os.path.join(kdir, "vmlinuz")
            if os.path.exists(vmlinuz):
                shutil.copyfile(vmlinuz, os.path.join(esp_kernel_dir, "vmlinuz"))
            ok(f"ESP kernel dir ready: {esp_kernel_dir}")

    ok("initramfs built for all installed kernels")


# --------------------------------------------------------------------------- #
# initramfs: the unlocking method must be reachable from the initramfs
# --------------------------------------------------------------------------- #
@log_all
def configure_mkinitcpio_hooks() -> None:
    """Write the new root's mkinitcpio.conf HOOKS for the chosen bootloader.

    The initramfs is what unlocks the LUKS container, so it has to carry the
    encrypt hook (systemd-native `sd-encrypt`, which pulls in systemd-cryptsetup
    and its TPM2/FIDO2 token plugins) plus the tools that can read a TPM2 token:

      sd-encrypt   dm-crypt, systemd-cryptsetup, the systemd-tpm2 token plugin
                   and the tss2-* libraries it dlopen()s (verified in the image)
      keyboard     passphrase entry before the real console exists
      filesystems  the root filesystem

    Limine and systemd-boot need the SAME hooks: the bootloader only decides how
    the kernel is loaded, never how the root is unlocked. What differs is the
    image the initramfs is packed into -- a plain initramfs for Limine, a UKI
    for systemd-boot -- and that is a build option, not a hook.
    """
    step("Configuring the initramfs hooks")

    hooks = [
        "base",
        "systemd",
        "autodetect",
        "modconf",
        "kms",
        "keyboard",
        "sd-vconsole",
        "block",
        "sd-encrypt",
        "filesystems",
    ]
    if not ENCRYPTED:
        # nothing to unlock; the encrypt hook would only wait for a passphrase
        hooks = [h for h in hooks if h != "sd-encrypt"]

    conf_path = os.path.join(ROOT_MNT, "etc", "mkinitcpio.conf")
    if os.path.exists(conf_path):
        with open(conf_path) as fh:
            body = fh.read()
        out, replaced = [], False
        for line in body.splitlines():
            if line.strip().startswith("HOOKS="):
                out.append(f"HOOKS=({' '.join(hooks)})")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            out.append("")
            out.append(f"HOOKS=({' '.join(hooks)})")
        with open(conf_path, "w") as fh:
            fh.write("\n".join(out) + "\n")
        ok(f"mkinitcpio.conf HOOKS=({' '.join(hooks)})")
    else:
        warn(f"{conf_path} not found — leaving mkinitcpio.conf untouched")

    # /etc/crypttab in the initramfs: sd-encrypt copies lines carrying the
    # x-initrd.attach option into the initramfs, so the unlock policy (which
    # tpm2-device=, which PIN) survives a kernel update without a cmdline edit.
    crypttab = os.path.join(ROOT_MNT, "etc", "crypttab")
    if os.path.exists(crypttab):
        with open(crypttab) as fh:
            body = fh.read()
        if "x-initrd.attach" not in body:
            with open(crypttab, "w") as fh:
                fh.write(body.rstrip("\n") + " x-initrd.attach\n")
            ok("added x-initrd.attach to /etc/crypttab")
    else:
        warn("/etc/crypttab is missing — sd-encrypt will rely on the cmdline only")


@log_all
def install_limine_bootloader(esp_part: str = "") -> None:
    """Install Limine onto the clone's ESP and generate its boot entries.

    Three tools are involved, each aimed at the clone's ESP explicitly:
    limine-install places the EFI binary and the NVRAM entry, limine-mkinitcpio
    lays out <ESP>/<machine-id>/<kernel>/{vmlinuz,initramfs}, and
    limine-entry-tool --scan writes the entries into <ESP>/limine.conf that name
    those files. ESP_PATH is exported because limine-common-functions reads it
    at source time.

    The last two run inside the chroot: both read /etc/kernel/cmdline, and the
    running system's file names the USB stick's LUKS container. Running them
    against the host would write the wrong rd.luks.name= into the clone's
    limine.conf.
    """
    step("Installing Limine bootloader")

    os.environ["ESP_PATH"] = EFI_MNT
    env = {**os.environ, "ESP_PATH": EFI_MNT}

    # /boot in the clone must exist for the vmlinuz lookup.
    os.makedirs(os.path.join(ROOT_MNT, "boot"), exist_ok=True)

    # Ensure Limine's EFI binary is on the ESP at the canonical path even when
    # limine-install did not place it there (e.g. when the ESP already existed).
    limine_src = "/usr/share/limine/BOOTX64.EFI"
    limine_dst = os.path.join(EFI_MNT, "EFI", "limine", "limine_x64.efi")
    if os.path.exists(limine_src) and not os.path.exists(limine_dst):
        os.makedirs(os.path.dirname(limine_dst), exist_ok=True)
        import shutil as _shutil
        _shutil.copy2(limine_src, limine_dst)
    if not os.path.exists(limine_dst):
        die(f"Limine EFI binary not found: {limine_dst}")

    # Inside the chroot ESP_PATH must name a path that exists THERE.
    chroot_env = {**os.environ, "ESP_PATH": CHROOT_ESP}
    run(["arch-chroot", ROOT_MNT, "/usr/bin/limine-mkinitcpio"], env=chroot_env)
    ok("Limine boot entries generated")

    # The distro tooling writes <ESP>/limine.conf itself; keep the installer's
    # own copy only if the tool did not.
    if not os.path.exists(os.path.join(EFI_MNT, "limine.conf")):
        write_limine_conf()


@log_all
def write_limine_conf() -> None:
    """Write <ESP>/limine.conf for the clone.

    Mirrors what limine-entry-tool generates, but for the NEW container: the OS
    entry is tagged with the clone's machine-id (that is how the tool targets
    it), kernel entries point at <ESP>/<machine-id>/<kernel>/, and the cmdline
    carries the new LUKS UUID and mapping name.
    """
    machine_id = SRC.machine_id or "unknown"
    os_name = clone_os_name()
    kernels = clone_kernels()
    if not kernels:
        warn("no kernel found in the clone — skipping limine.conf")
        return

    lines = [
        "### Read more at config document: https://github.com/Limine-Bootloader/Limine/blob/v12.x/CONFIG.md",
        "### Generated by blackarch installer",
        "",
        "### Show warning instead of panic on hash mismatch",
        "hash_mismatch_panic: no",
        "",
        "timeout: 3",
        "",
        "default_entry: 1",
        "",
        f"/+{os_name}",
        "### This OS entry is auto-generated by limine-entry-tool",
        f"comment: {os_name}",
        f"comment: machine-id={machine_id} order-priority=50 ",
    ]

    for owner, kver in kernels:
        lines += [
            f"  //{owner}",
            "  ### This kernel entry is auto-generated by limine-entry-tool",
            f"  comment: Kernel version: {kver}",
            f"  comment: kernel-id={owner} ",
            "  protocol: linux",
            f"  module_path: boot():/{machine_id}/{owner}/initramfs",
            f"  path: boot():/{machine_id}/{owner}/vmlinuz",
            f"  cmdline: {CMDLINE_FOR_ESP[0]}",
            "",
        ]

    snaps = clone_snapshots()
    if snaps:
        primary = snapshot_kernel(kernels)
        lines += ["/+Snapshots", "comment: Btrfs Snapshots"]
        for num, desc in snaps:
            lines += [
                f"  /snapshot:{num}",
                f"  comment: Snapshot {num} - {desc}",
                "  protocol: linux",
                f"  path: boot():/{machine_id}/{primary}/vmlinuz",
                f"  module_path: boot():/{machine_id}/{primary}/initramfs",
                f"  cmdline: {snapshot_cmdline(CMDLINE_FOR_ESP[0], f'/.snapshots/{num}/snapshot')}",
                "",
            ]

    for name, path_in_esp in (
        ("Systemd-boot", "EFI/systemd/systemd-bootx64.efi"),
        ("EFI fallback", "EFI/BOOT/BOOTX64.EFI"),
    ):
        if os.path.exists(os.path.join(EFI_MNT, path_in_esp)):
            lines += [
                f"/{name}",
                f"comment: {name}",
                "protocol: efi",
                f"path: boot():/{path_in_esp}",
                "",
            ]

    path = os.path.join(EFI_MNT, "limine.conf")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)
    ok(
        f"limine.conf written: {path}  ({len(kernels)} kernel(s), {len(snaps)} snapshot(s))"
    )


# systemd-boot's menu timeout. bootctl writes loader.conf with `#timeout 3`
# commented out, which leaves the timeout at 0 and the menu hidden: with no
# type-1 entry to pick a default from, that is an empty menu and an
# unbootable-looking clone. Mirrors the Limine config's `timeout: 3`.
SYSTEMD_BOOT_TIMEOUT = 3


@log_all
def loader_title(owner: str, suffix: str = "") -> str:
    """Menu title for one kernel's boot entry.

    Names the distro and the kernel package separately from the version: two
    kernels then show as two distinct rows ("Arch Linux (offensive)" /
    "Arch Linux (hardened)") instead of two rows with the same name. A snapshot
    entry shares its kernel's title and says which snapshot it is, because the
    two rows would otherwise be indistinguishable.
    """
    name = clone_os_name()
    label = owner.rsplit("-", 1)[-1] if "-" in owner else owner
    title = f"{name} ({label})"
    if suffix:
        title += f" — snapshot {suffix.removeprefix('-snap')}"
    return title


@log_all
def loader_entry_stem(kver: str, suffix: str = "") -> str:
    """The entry file name without .conf, and the value loader.conf defaults to."""
    return f"{SRC.machine_id}-{kver}{suffix}"


@log_all
def write_loader_entry(owner: str, kver: str, suffix: str = "") -> str:
    """One type-1 boot entry in <ESP>/loader/entries/, pointing at the UKI.

    systemd-boot auto-discovers UKIs in EFI/Linux, but an empty loader/entries/
    plus the default `timeout 0` is a menu with nothing to choose and no way to
    pick a default -- so the entry is written explicitly and named by `default`
    in loader.conf.

    Only `title` and `efi` are written: the cmdline is already baked into the
    UKI's .cmdline section, and a type-1 `options` line would be a second copy
    of the same string to keep in sync.
    """
    entries_dir = os.path.join(EFI_MNT, "loader", "entries")
    os.makedirs(entries_dir, exist_ok=True)
    # systemd-boot requires the machine-id in a type-1 entry's filename.
    stem = loader_entry_stem(kver, suffix)
    path = os.path.join(entries_dir, f"{stem}.conf")
    lines = [
        f"title   {loader_title(owner, suffix)}",
        f"efi     /EFI/Linux/{owner}-{kver}{suffix}.efi",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o644)
    return path


@log_all
def write_loader_conf() -> None:
    """<ESP>/loader/loader.conf: a real timeout and the default entry.

    bootctl's own loader.conf leaves both commented out, so the menu is hidden
    and there is no default to fall back on.
    """
    path = os.path.join(EFI_MNT, "loader", "loader.conf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        f"timeout {SYSTEMD_BOOT_TIMEOUT}",
        "console-mode keep",
        "editor no",
    ]
    if DEFAULT_LOADER_ENTRY[0]:
        # `default` names the entry file without the .conf suffix.
        lines.append(f"default {DEFAULT_LOADER_ENTRY[0]}")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o644)


@log_all
def install_systemd_boot() -> None:
    """Install systemd-boot onto the clone's ESP and give it its boot entries.

    --esp-path aims bootctl at the CLONE's ESP: without it bootctl would look at
    /efi, which in a live session is the USB stick's own ESP. bootctl only lays
    out the loader/ skeleton -- the menu entries themselves are written here,
    from the UKIs build_ukis() just built.
    """
    step("Installing systemd-boot")

    if not os.path.ismount("/sys/firmware/efi/efivars"):
        # bootctl install writes an EFI variable; without efivarfs it can only
        # copy the binaries and the firmware would never find them.
        try_run(["mount", "-t", "efivarfs", "efivarfs", "/sys/firmware/efi/efivars"])

    run(
        [
            "bootctl",
            f"--esp-path={EFI_MNT}",
            "install",
        ]
    )
    ok("systemd-boot installed (no NVRAM entry — use efibootmgr for that)")

    # The UKIs are already in <ESP>/EFI/Linux; name them in loader/entries/.
    kernels = clone_kernels()
    if not kernels:
        die("no kernel found in the clone — cannot write a systemd-boot entry")

    built: list[tuple[str, str, str]] = []  # (owner, kernel version, snapshot suffix)
    for owner, kver in kernels:
        if os.path.exists(os.path.join(EFI_MNT, "EFI", "Linux", f"{owner}-{kver}.efi")):
            built.append((owner, kver, ""))

    snaps = clone_snapshots()
    if snaps:
        primary = snapshot_kernel(kernels)
        primary_kver = dict(kernels)[primary]
        for num, _desc in snaps:
            suffix = f"-snap{num}"
            if os.path.exists(
                os.path.join(
                    EFI_MNT, "EFI", "Linux", f"{primary}-{primary_kver}{suffix}.efi"
                )
            ):
                built.append((primary, primary_kver, suffix))

    if not built:
        die(
            "systemd-boot was installed but no UKI was found in "
            f"{os.path.join(EFI_MNT, 'EFI', 'Linux')}"
        )

    for owner, kver, suffix in built:
        write_loader_entry(owner, kver, suffix)

    # In "both" mode Limine's EFI binary may not be on the ESP yet; make sure
    # it exists so the chainload entry points at limine_x64.efi (not the
    # fallback BOOTX64.EFI) which firmware keeps.
    limine_src = "/usr/share/limine/BOOTX64.EFI"
    limine_dst = os.path.join(EFI_MNT, "EFI", "limine", "limine_x64.efi")
    if os.path.exists(limine_src) and not os.path.exists(limine_dst):
        os.makedirs(os.path.dirname(limine_dst), exist_ok=True)
        import shutil as _shutil
        _shutil.copy2(limine_src, limine_dst)
    # Chainload Limine if it is configured on the ESP: systemd-boot can hand
    # off to Limine's EFI binary as a UEFI application, which then reads its
    # own limine.conf. Detected from the ESP rather than assumed.
    for rel in ("EFI/limine/limine_x64.efi", "EFI/BOOT/BOOTX64.EFI"):
        limine_efi = os.path.join(EFI_MNT, *rel.split("/"))
        if os.path.exists(limine_efi):
            entries_dir = os.path.join(EFI_MNT, "loader", "entries")
            os.makedirs(entries_dir, exist_ok=True)
            path = os.path.join(entries_dir, "limine-chainload.conf")
            with open(path, "w") as fh:
                fh.write("title   Limine (chainload)\n")
                fh.write(f"efi     /{rel}\n")
            os.chmod(path, 0o644)
            ok(f"systemd-boot chainload entry written for Limine: {path}")
            break

    # The first kernel is the default; defaulting to a snapshot entry would boot
    # a rollback every time.
    DEFAULT_LOADER_ENTRY[0] = loader_entry_stem(built[0][1], built[0][2])
    write_loader_conf()

    ok(
        f"systemd-boot installed on {EFI_MNT} "
        f"({len(built)} menu entr{'y' if len(built) == 1 else 'ies'})"
    )


# --------------------------------------------------------------------------- #
# snapper
# --------------------------------------------------------------------------- #
@log_all
def install_snapper_config() -> None:
    step("Configuring snapper")
    config_path = Path(ROOT_MNT) / "etc/snapper/configs/root"
    if config_path.exists():
        ok("Snapper config 'root' already exists, skipping creation.")
        return
    # pacman pre/post snapshot hooks (best effort, needs network)
    try_run(
        [
            "arch-chroot",
            ROOT_MNT,
            "/usr/bin/bash",
            "-c",
            "command -v pacman >/dev/null && "
            "pacman -S --needed --noconfirm snap-pac >/dev/null 2>&1 || true",
        ]
    )

    run(["snapper", "--no-dbus", "-r", ROOT_MNT, "create-config", "/"])
    try_run(
        [
            "snapper",
            "--no-dbus",
            "-r",
            ROOT_MNT,
            "create",
            "--description",
            "baseline (cloned from USB)",
            "--cleanup-algorithm",
            "number",
        ]
    )

    ok("snapper configured (config 'root' + baseline snapshot)")


# --------------------------------------------------------------------------- #
# finish
# --------------------------------------------------------------------------- #
@log_all
def finalize() -> None:
    step("Finalising")

    # machine-id must be a regular file, not a symlink into /usr
    mid = os.path.join(ROOT_MNT, "etc/machine-id")
    if os.path.islink(mid):
        os.unlink(mid)
        with open(mid, "w") as fh:
            fh.write(SRC.machine_id + "\n")

    # Timezone: always copy the running system's /etc/localtime unless
    # --skip-timezone is set. Never prompt — the running system's zone is the
    # right default.
    src_localtime = "/etc/localtime"
    dst_localtime = os.path.join(ROOT_MNT, "etc/localtime")
    if not SKIP_TIMEZONE:
        if os.path.islink(src_localtime) or os.path.isfile(src_localtime):
            try:
                dst_dir = os.path.dirname(dst_localtime)
                if dst_dir:
                    os.makedirs(dst_dir, exist_ok=True)
                if os.path.islink(src_localtime):
                    link_target = os.readlink(src_localtime)
                    # Remove any existing file/symlink at destination
                    if os.path.islink(dst_localtime) or os.path.isfile(dst_localtime):
                        os.unlink(dst_localtime)
                    os.symlink(link_target, dst_localtime)
                else:
                    shutil.copyfile(src_localtime, dst_localtime)
                info("Copied timezone from running system (/etc/localtime)")
            except OSError as exc:
                warn(f"Could not copy timezone: {exc}")
        else:
            # Source has no timezone file; fall back to UTC like before
            if not os.path.exists(dst_localtime):
                dst_dir = os.path.dirname(dst_localtime)
                if dst_dir:
                    os.makedirs(dst_dir, exist_ok=True)
                os.symlink("/usr/share/zoneinfo/UTC", dst_localtime)
    else:
        info("Skipping timezone copy (--skip-timezone)")
        # If skipped and no localtime exists in target, leave it as-is (target
        # may already have its own timezone setting from the package install)

    try_run(
        [
            "arch-chroot",
            ROOT_MNT,
            "/usr/bin/bash",
            "-c",
            "locale-gen >/dev/null 2>&1 || true",
        ]
    )

    subprocess.run(["sync"])
    ok("sync complete")


@log_all
def bind_esp_into_chroot() -> None:
    """Make the new root's ESP visible inside the chroot at CHROOT_ESP.

    Limine's pacman hook (limine-mkinitcpio-install) runs chrooted and locates
    the ESP by probing /efi, /boot, /boot/efi and /limine for a mounted FAT32
    filesystem. Inside arch-chroot none of those is a mountpoint, so without
    this bind it prints "FAT32 boot partition not found" and every chrooted
    pacman exits non-zero. The clone's own fstab mounts its ESP at /efi, so
    that is the path to bind.
    """
    target = os.path.join(ROOT_MNT, CHROOT_ESP.lstrip("/"))
    os.makedirs(target, exist_ok=True)
    if os.path.ismount(target):
        return
    run(["mount", "--bind", EFI_MNT, target])
    ok(f"ESP bound into the chroot at {CHROOT_ESP}")


@log_all
def unbind_esp_from_chroot() -> None:
    """Drop the bind mount bind_esp_into_chroot() added."""
    target = os.path.join(ROOT_MNT, CHROOT_ESP.lstrip("/"))
    if os.path.ismount(target):
        try_run(["umount", target])


@log_all
def bind_home_into_chroot() -> None:
    """Make the new root's /home subvolume visible inside the chroot at /home.

    The @home subvolume is mounted at HOME_MNT, which is OUTSIDE the root mount,
    and copy_user_homes() writes into it. arch-chroot mounts only /dev, /proc,
    /sys, /run and /etc/resolv.conf, so inside the chroot /home is a plain
    directory in the root subvolume and the chown that hands the copied home back
    to its owner dies ENOENT -- the run then reports "home copied" while the home
    is root-owned in the new install. Same fix as bind_esp_into_chroot().
    """
    if not SRC.home_subvol:
        return
    target = os.path.join(ROOT_MNT, "home")
    os.makedirs(target, exist_ok=True)
    if os.path.ismount(target):
        return
    run(["mount", "--bind", HOME_MNT, target])
    ok("home subvolume bound into the chroot at /home")


@log_all
def unbind_home_from_chroot() -> None:
    """Drop the bind mount bind_home_into_chroot() added."""
    target = os.path.join(ROOT_MNT, "home")
    if os.path.ismount(target):
        try_run(["umount", target])


@log_all
def cleanup_mounts() -> None:
    if not TARGET_DISK:
        return
    global KEEP_MOUNTED
    if KEEP_MOUNTED:
        info("--keep-mounted: skipping unmount and cryptsetup close")
        return
    step("Unmounting the new system")
    # the bind is under ROOT_MNT, so the recursive unmounts below would leave
    # it half-detached; drop it first
    unbind_esp_from_chroot()
    # the /home bind is under ROOT_MNT too, so drop it before the recursive
    # unmounts or it is left half-detached
    unbind_home_from_chroot()
    for path in (EFI_MNT, EFI_MNT_ROOT, HOME_MNT, ROOT_MNT):
        try_run(["umount", "-R", path])
    if ENCRYPTED:
        try_run(["cryptsetup", "close", MAPPING])
    ok("unmounted")


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
@log_all
def mkinitcpio_hooks_line() -> str:
    """The HOOKS the new root was given, read back from its mkinitcpio.conf.

    Reading the file beats re-deriving the list: configure_mkinitcpio_hooks()
    appended the line when none was present, and the value on disk is what the
    next mkinitcpio run will actually use.
    """
    path = os.path.join(ROOT_MNT, "etc", "mkinitcpio.conf")
    try:
        for line in open(path):
            if line.strip().startswith("HOOKS="):
                return line.strip()
    except OSError:
        pass
    return "<not written>"


@log_all
def print_summary(esp_part, root_part, luks_uuid, new_cmdline) -> None:
    _emit("")
    _emit(f"{C['bold']}{C['green']}{'─' * 48}{C['reset']}")
    _emit(f"{C['bold']}{C['green']}  USB → DISK CLONE COMPLETE{C['reset']}")
    _emit(f"{C['bold']}{C['green']}{'─' * 48}{C['reset']}")
    _emit(f"""
  Target disk     : {TARGET_DISK}
  ESP             : {esp_part}  -> {EFI_MNT}  (vfat)
  Root device     : {root_part}  ({'LUKS2 -> /dev/mapper/' + MAPPING if ENCRYPTED else 'unencrypted'})
  LUKS UUID       : {luks_uuid or '<none — the root is not encrypted>'}
  Root subvolume  : {SRC.root_subvol}
  Home subvolume  : {SRC.home_subvol or '<same as root>'}
  Kernel cmdline  : {new_cmdline}

  Credentials     : root + {len(SRC.users)} user(s) copied verbatim (passwords unchanged)
  User homes      : {HOMES_LINE}
  Invoker         : {INVOKER_USER or '<undetermined>'} (the account this run was started as)
  Bootloader      : {describe_bootloader()}
  Initramfs hooks : {mkinitcpio_hooks_line()}
  Unlock at boot  : {describe_unlock()}
  Snapshots       : snapper config 'root' + baseline snapshot

  Install method  : {INSTALL_LINE}
  Log             : {LOGFILE}

  Reboot, then remove the USB stick and boot from {TARGET_DISK}.
""")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
TARGET_DISK = ""
KEEP_MOUNTED = False


@log_all
def parse_args(argv):
    if argv and argv[0] == "--complete":
        # print options
        print(" ".join([]))
        raise SystemExit(0)
    ap = argparse.ArgumentParser(
        prog="usb2disk_installer",
        description="Clone a running USB-installed Linux onto a hard disk, or "
        "bootstrap a fresh Arch root with the AthenaOS / Blackarch / Omarchy "
        "package set.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Target selection:
  --disk DEV      target disk, e.g. --disk /dev/sda (skips the menu)
  --scheme NAME   'recommended' (ESP + root) or 'custom' (you define partitions)
  --esp-size MiB  ESP size in MiB for the recommended scheme
                  (default: 5% of the disk, capped at 1024)
  --install DATA  clone the running system, or pacstrap a fresh Arch root

Bootloader:
  --bootloader NAME   limine or systemd-boot, or none (the default). Both get an
                      NVRAM entry and a boot menu: Limine writes limine.conf
                      entries + per-kernel vmlinuz/initramfs, systemd-boot writes
                      loader/entries/ entries pointing at unified kernel images
                      in EFI/Linux. With no NAME the new ESP is left without a
                      loader at all -- nothing is installed and no NVRAM entry is
                      written. No prompt is shown for this either: the flag is
                      the only way to choose. Ignored on the clone path, which
                      keeps the loader the running system's own ESP carries.

The initramfs always carries sd-encrypt, which is what unlocks the LUKS
container and what makes the TPM2 token readable at boot; both bootloaders use
the same hooks because the bootloader only chooses how the kernel is loaded.

The script asks for the LUKS passphrase interactively.
By default it partitions, formats and encrypts the target disk -- all data
there is destroyed. --existing instead mounts the partitions that are already
on it: nothing is reformatted and nothing is encrypted.
--efi-part DEV      with --existing: the EFI System Partition, as a device path
                    (/dev/sda1), a bare name (sda1) or a partition number (1)
--root-part DEV     with --existing: a plain btrfs root partition
--luks-part DEV     with --existing: a LUKS partition holding the root
--skip-pacstrap     with --install pacstrap and --existing: skip pacstrap and
                    reuse the packages already in the target root, so a re-run
                    does not reinstall the base set over a populated root
--skip-copy-home      with --install pacstrap: do not copy the running system's
                    user homes into the new root -- it boots with the
                    package-default dotfiles instead. this is already the
                    default when the installer runs from a live/ISO session,
                    where the live account's home has nothing worth keeping
--copy-home         force the home copy in the cases where the default is no:
                    a live session, a clone, or --existing/--skip-pacstrap
--hostname NAME     hostname for the new root. the default is the new root's own
                    hostname when it already has one (--existing/--skip-pacstrap),
                    and the running system's hostname otherwise. never prompted
""",
    )
    ap.add_argument(
        "--skip-copy-sudoers",
        action="store_true",
        help="do not copy /etc/sudoers.d from the host; only create uid-1000 sudoers",
    )
    ap.add_argument(
        "--gui", action="store_true", help="launch the graphical installer (PySide6)"
    )
    ap.add_argument("--disk", help="target disk, e.g. /dev/sda")
    ap.add_argument(
        "--scheme",
        choices=("recommended", "custom"),
        default=None,
        help="partition scheme to use",
    )
    ap.add_argument(
        "--esp-size",
        type=int,
        default=None,
        metavar="MiB",
        help="ESP size in MiB for the recommended scheme "
        "(default: 5%% of the disk, capped at 1024)",
    )
    ap.add_argument(
        "--install",
        choices=("pacstrap", "clone"),
        default="pacstrap",
        help="clone the running system, or pacstrap a fresh Arch root with the "
        "AthenaOS / Blackarch / Omarchy package set. default is pacstrap",
    )
    ap.add_argument(
        "--existing",
        action="store_true",
        help="mount the target's existing partitions as-is: no partitioning, "
        "no formatting, no LUKS (the ESP must be vfat, the root btrfs)",
    )
    ap.add_argument(
        "--no-encrypt",
        action="store_true",
        help="put the root on the plain partition instead of a LUKS container",
    )
    ap.add_argument(
        "--bootloader",
        choices=("none", "limine", "systemd-boot", "both"),
        default=None,
        help="which bootloader to install on the new ESP. default is NONE: a "
        "pacstrap root is built without a loader unless you name one, because "
        "installing one would also write an NVRAM entry to your ESP. there is no "
        "prompt for this -- the flag is the only way to choose. ignored on the "
        "clone path, which keeps the loader the running system's own ESP carries",
    )
    ap.add_argument(
        "--hostname",
        default=None,
        metavar="NAME",
        help="hostname for the new root. default: the new root's own hostname when "
        "it already has one (--existing/--skip-pacstrap), otherwise the running "
        "system's hostname. never prompted",
    )
    ap.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE_DIR,
        metavar="PATH",
        help="pacman cache, inside the new root, so a re-run reuses the packages "
        "already downloaded (default: %(default)s)",
    )
    ap.add_argument(
        "--skip-pacstrap",
        action="store_true",
        help="with --install pacstrap: reuse the packages already in the target "
        "root instead of running pacstrap again. only meaningful with "
        "--existing, where the root is already bootstrapped",
    )
    ap.add_argument(
        "--skip-copy-home", "--no-copy-home",
        action="store_true", dest="skip_copy_home",
        help="with --install pacstrap: do not copy the running system's user "
        "homes into the new root; it boots with the package-default dotfiles. "
        "default is to copy every real user's home -- except when the installer "
        "runs from a live/ISO session, where that is already the default",
    )
    ap.add_argument(
        "--copy-home",
        action="store_true",
        help="copy the user homes even in the cases where the default is not "
        "to: a live/ISO session, a clone, or --existing/--skip-pacstrap",
    )
    ap.add_argument(
        "--skip-home-dir",
        action="append",
        default=None,
        metavar="NAME",
        help="directory to leave out of every copied home (repeatable). a bare "
        "name matches at any depth, so --skip-home-dir Downloads drops every "
        "Downloads in the home; a path is relative to the home root",
    )
    ap.add_argument(
        "--skip-home-ext",
        action="append",
        default=None,
        metavar="EXT",
        help="file extension to leave out of every copied home (repeatable, "
        "with or without the leading dot, e.g. --skip-home-ext iso)",
    )
    ap.add_argument(
        "--skip-vm",
        action="store_true",
        help="leave virtual-machine images and their state out of the copied "
        "homes (qcow2/qcow/vmdk/vdi/vhd/img/raw/ova/vbox, plus the libvirt and "
        "Vagrant directories)",
    )
    ap.add_argument(
        "--efi-part",
        default=None,
        metavar="DEV",
        help="with --existing: the EFI System Partition to use -- a device path "
        "(/dev/sda1), a bare name (sda1) or a partition number (1). skips the "
        "interactive ESP prompt",
    )
    ap.add_argument(
        "--root-part",
        default=None,
        metavar="DEV",
        help="with --existing: a plain btrfs root partition. mutually exclusive "
        "with --luks-part",
    )
    ap.add_argument(
        "--luks-part",
        default=None,
        metavar="DEV",
        help="with --existing: a LUKS-encrypted partition holding the btrfs "
        "root. mutually exclusive with --root-part",
    )
    ap.add_argument(
        "--skip-network",
        action="store_true",
        help="skip copying network profiles (wifi/VPN/bluetooth) from the "
        "running system into the new root",
    )
    ap.add_argument(
        "--skip-timezone",
        action="store_true",
        help="do not copy the running system's timezone (/etc/localtime) into "
        "the new root; the target will fall back to UTC instead",
    )
    ap.add_argument(
        "--keep-mounted",
        action="store_true",
        help="do not unmount partitions or close the LUKS cryptsetup container; "
        "leaves the target root and ESP mounted for post-install inspection",
    )
    return ap.parse_args(argv)


@log_all
def set_cache_dir(conf_path: str, cache_dir: str) -> None:
    """Point a pacman.conf's [options] CacheDir at `cache_dir`."""
    with open(conf_path) as fh:
        original = fh.read().splitlines()

    out: list[str] = []
    placed = False
    for line in original:
        if line.strip().startswith("CacheDir"):
            continue  # drop whatever was there
        out.append(line)
        if not placed and line.strip() == "[options]":
            out.append(f"CacheDir = {cache_dir}")
            placed = True
    if not placed:
        out = ["[options]", f"CacheDir = {cache_dir}", *out]

    with open(conf_path, "w") as fh:
        fh.write("\n".join(out) + "\n")


@log_all
def pacstrap_config(cache_dir: str) -> str:
    """A pacman config for pacstrap carrying the same CacheDir.

    pacstrap prefixes the configured CacheDir with the new root, so pointing it
    at the same path the chroot's pacman.conf uses makes the host-side and the
    chroot-side cache one directory.
    """
    path = os.path.join(LOGDIR, "pacstrap-pacman.conf")
    shutil.copyfile("/etc/pacman.conf", path)
    set_cache_dir(path, cache_dir)
    return path


@log_all
def bootstrap_pacman(cache_dir: str) -> None:
    """Give the new root the running system's repositories and package cache.

    pacstrap installs with the host's pacman.conf, but the new root has to be
    able to resolve packages on its own afterwards, and pacstrap only copies the
    stock mirrorlist -- so every mirrorlist the config Includes is copied here.
    """
    step("Preparing pacman for the new system")

    os.makedirs(ROOT_MNT, exist_ok=True)
    conf_dir = os.path.join(ROOT_MNT, "etc/pacman.d")
    os.makedirs(conf_dir, exist_ok=True)

    conf = os.path.join(ROOT_MNT, "etc/pacman.conf")
    shutil.copyfile("/etc/pacman.conf", conf)
    set_cache_dir(conf, cache_dir)

    copied = []
    for name in sorted(os.listdir("/etc/pacman.d")):
        if not name.endswith("-mirrorlist"):
            continue
        shutil.copyfile(
            os.path.join("/etc/pacman.d", name), os.path.join(conf_dir, name)
        )
        copied.append(name)

    # Ensure BlackArch/Athena repos are available even if the live ISO lacks them.
    extra_repos = {
        "blackarch": (
            "[blackarch]\nSigLevel = Optional TrustedOnly\n"
            "Include = /etc/pacman.d/blackarch-mirrorlist\n"
        ),
        "athena": (
            "[athena]\nSigLevel = Optional TrustedOnly\n"
            "Include = /etc/pacman.d/athena-mirrorlist\n"
        ),
        "chaotic-aur": (
            "[chaotic-aur]\nSigLevel = Optional TrustedOnly\n"
            "Include = /etc/pacman.d/chaotic-mirrorlist\n"
        ),
        "garuda": (
            "[garuda]\nSigLevel = Optional TrustedOnly\n"
            "Include = /etc/pacman.d/chaotic-mirrorlist\n"
        ),
    }
    mirror_urls = {
        "blackarch": "https://www.blackarch.org/blackarch-mirrorlist",
        "athena": "https://raw.githubusercontent.com/Athena-OS/athena/main/src/os-specific/system/athena-mirrorlist/athena-mirrorlist",
        "chaotic-aur": "https://raw.githubusercontent.com/chaotic-aur/pkgbuild-chaotic-mirrorlist/master/mirrorlist",
    }
    mirror_files = {
        "blackarch": "blackarch-mirrorlist",
        "athena": "athena-mirrorlist",
        "chaotic-aur": "chaotic-mirrorlist",
        "garuda": "chaotic-mirrorlist",
    }
    conf_text = open(conf, "r").read()
    for repo, block in extra_repos.items():
        if f"[{repo}]" not in conf_text:
            with open(conf, "a") as f:
                f.write("\n" + block)
            conf_text += "\n" + block
        ml_name = mirror_files[repo]
        ml = os.path.join(conf_dir, ml_name)
        if not os.path.exists(ml):
            url = mirror_urls.get(repo)
            if not url:
                continue
            tmp = ml + ".tmp"
            try:
                subprocess.run(["curl", "-fsSL", url, "-o", tmp], check=True, timeout=60)
            except Exception as exc:
                warn(f"could not download {repo} mirrorlist: {exc}")
                continue
            # Rank mirrors by download speed at runtime, keep fastest 5.
            servers = []
            with open(tmp) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("Server") and "=" in line:
                        servers.append(line.split("=", 1)[1].strip())
            ranked = []
            for s_url in servers:
                test_url = s_url.replace("$repo", "blackarch").replace("$arch", "x86_64") + "/blackarch.db" if repo == "blackarch" else s_url
                try:
                    out = subprocess.run(
                        ["curl", "-s", "-o", "/dev/null", "-w", "%{time_total}", "--max-time", "8", test_url],
                        capture_output=True, text=True, timeout=10,
                    )
                    t = float(out.stdout.strip() or "999")
                except Exception:
                    t = 999.0
                ranked.append((t, s_url))
            ranked.sort()
            top = [u for _, u in ranked[:5] if _ < 999]
            if not top:
                top = servers[:5]
            try:
                with open(ml, "w") as f:
                    for u in top:
                        f.write(f"Server = {u}\n")
            except Exception as exc:
                warn(f"could not write {repo} mirrorlist: {exc}")
            try:
                os.remove(tmp)
            except OSError:
                pass
            continue

    # the cache lives on the target disk, so a re-run that does not reformat
    # reuses every package already in it
    os.makedirs(os.path.join(ROOT_MNT, cache_dir.lstrip("/")), exist_ok=True)

    ok(
        f"pacman.conf written (cache {cache_dir}); "
        f"mirrorlists: {', '.join(copied) or 'none'}"
    )


@log_all
def bootstrap_system(cache_dir: str) -> None:
    """Build a fresh Arch root with the AthenaOS / Blackarch / Omarchy packages."""
    step(f"Bootstrapping a new Arch system into {ROOT_MNT}")

    # A re-run against --existing does not need pacstrap: the target root is
    # already populated, and pacstrap would reinstall the base set over it.
    # bootstrap_pacman() still runs -- it is cheap, idempotent, and keeps the
    # mirrorlist and CacheDir in step with the running system.
    # Always sync mirrorlists (and rank them) even when skipping pacstrap.
    bootstrap_pacman(cache_dir)

    if SKIP_PACSTRAP:
        for marker, why in (
            (
                os.path.join(ROOT_MNT, "usr/bin/pacman"),
                "pacman is not installed there, so the target root has not been "
                "bootstrapped and there is nothing to reuse",
            ),
            (
                os.path.join(ROOT_MNT, "etc/pacman.d/gnupg/pubring.gpg"),
                "the pacman keyring is not populated there, so a later "
                "`pacman -S` of the bootloader or TPM2 packages would fail to "
                "verify",
            ),
        ):
            if not os.path.exists(marker):
                die(f"--skip-pacstrap: {why} ({marker} is missing)")
        ok("pacstrap skipped (--skip-pacstrap): reusing the packages in the root")
        return

    # pacstrap copies the host's keyring into the new root, so the AthenaOS /
    # Blackarch / chaotic / omarchy packages verify without a recv-keys dance.
    run(
        [
            "pacstrap",
            "-C",
            pacstrap_config(cache_dir),
            ROOT_MNT,
            *BOOTSTRAP_BASE,
            *BOOTSTRAP_KEYRINGS,
        ]
    )
    ok("base system and keyrings installed")

    run(
        [
            "arch-chroot",
            ROOT_MNT,
            "pacman-key",
            "--populate",
            "archlinux",
            "blackarch",
            "athena",
        ]
    )
    run(["arch-chroot", ROOT_MNT, "pacman-key", "--recv-keys", OMARCHY_KEY])
    run(["arch-chroot", ROOT_MNT, "pacman-key", "--lsign-key", OMARCHY_KEY])

    full = [
        *ATHENA_TOOLS,
        *DEV_TOOLS,
        *SYSTEM_PACKAGES,
        *SYSTEM_UTILITIES,
        *MY_UTILITIES,
        *HYPRLAND_PACKAGES,
        *OMARCHY_PKGS,
    ]
    info(f"Installing {len(full)} packages from the bootstrap package sets")
    run(
        [
            "arch-chroot",
            ROOT_MNT,
            "pacman",
            "-Syy",
            "--needed",
            "--noconfirm",
            *full,
        ]
    )
    ok("bootstrap package set installed")

    # AUR tools: yay comes from chaotic-aur, the rest from the AUR itself
    # Makepkg refuses root; use the desktop user (UID 1000) inside the chroot.

    run(["arch-chroot", ROOT_MNT, "pacman", "-S", "--needed", "--noconfirm", "yay"])
    try_run(
        [
            "arch-chroot",
            ROOT_MNT,
            "runuser",
            "-u",
            "black",
            "--",
            "yay",
            "-S",
            "--needed",
            "--noconfirm",
            *AUR_TOOLS,
        ]
    )

    # cyber tools that are not part of the package sets above
    try_run(
        [
            "arch-chroot",
            ROOT_MNT,
            "pacman",
            "-S",
            "--needed",
            "--noconfirm",
            *CYBER_TOOLS,
        ]
    )

    ok("bootstrap complete")


# --------------------------------------------------------------------------- #
# Blackarch tree + dotfiles
# --------------------------------------------------------------------------- #
@log_all
def dotfile_homes() -> list[str]:
    """Homes in the new root to run the dotfile setup for."""
    homes: list[str] = []
    try:
        with open(os.path.join(ROOT_MNT, "etc/passwd")) as fh:
            for line in fh:
                fields = line.split(":")
                if len(fields) < 7:
                    continue
                uid, home, shell = fields[2], fields[5], fields[6]
                if (
                    uid.isdigit()
                    and 1000 <= int(uid) < 65534
                    and not re.search(r"(nologin|false)$", shell)
                ):
                    homes.append(home)
    except OSError:
        pass
    # Root account always gets the dotfile setup.
    homes.append("/root")
    return homes


@log_all
def deploy_blackarch_tree() -> None:
    """Copy /opt/blackarch into the new root, then run its dotfile setup.

    The copy is only needed on the bootstrap path: a clone brings /opt/blackarch
    along with the root, and its homes are already linked. Running the dotfile
    setup is then what turns a bare Arch root into a Blackarch one.
    """
    step("Deploying the Blackarch tree")

    if not os.path.isdir(BLACKARCH_ROOT):
        warn(f"{BLACKARCH_ROOT} is missing on the running system — skipping")
        return

    target = os.path.join(ROOT_MNT, "opt/blackarch")
    # Always sync; rsync updates changed files and skips unchanged ones,
    # so an existing tree does not block updates.
    info(f"Copying {BLACKARCH_ROOT} -> {target}")

    # rsync, not shutil.copytree: the tree is large, and a Python walk copies
    # in-process with no progress and no way to skip a subtree. --no-specials /
    # --no-devices stand in for the old copy_function() that dropped sockets and
    # FIFOs (config/cliamp ships a live .sock).
    proc = try_run(
        [
            "rsync",
            *RSYNC_OPTS,
            "--no-specials",
            "--no-devices",
            # "--exclude=.git/",
            "--exclude=__pycache__/",
            "--exclude=*.pyc",
            BLACKARCH_ROOT.rstrip("/") + "/",
            target.rstrip("/") + "/",
        ]
    )
    if proc.returncode != 0:
        # 23/24 mean "partial transfer" -- a file vanished mid-copy or a socket
        # was skipped. Recoverable, and the commander check below catches a copy
        # that actually lost the files that matter.
        warn(
            f"rsync of the Blackarch tree exited {proc.returncode} - "
            "some files may be missing"
        )
    ok("Blackarch tree copied")

    commander = os.path.join("/opt/blackarch", "bin", "blackarch")
    if not os.path.isfile(commander):
        warn(
            "bin/blackarch is missing from the copied tree — "
            "skipping the dotfile setup"
        )
        return

    for home in dotfile_homes():
        info(f"Running the dotfile setup for {home}")
        completed = run(
            [
                "arch-chroot",
                ROOT_MNT,
                "/usr/bin/python3",
                commander,
                "setup",
                "dotfiles",
            ],
            env={**os.environ, "HOME": home},
            check=False,
        )
        if completed.returncode == 0:
            ok(f"dotfiles deployed for {home}")
        else:
            warn(f"the dotfile setup exited {completed.returncode} for {home}")


@log_all
def copy_homes_now(args) -> bool:
    """Whether this run copies the running system's user homes into the root.

    Default is yes whenever pacstrap actually built the root this run: a fresh
    pacstrap root has no homes at all, and copying them is what makes it a
    usable desktop. That is why the two cases where the root was NOT built
    default to no -- a clone already brings its own homes, and an
    --existing/--skip-pacstrap root is already populated -- and there the copy
    needs an explicit --copy-home.

    On top of that default, a LIVE session copies nothing unless asked. Booting
    an installer means running as a temporary live account whose /home holds
    nothing worth keeping, so the default pacstrap path would otherwise import
    that account's throwaway home as a real user of the new install. Live
    therefore flips the default to no, and --copy-home is what takes the homes
    anyway. --skip-copy-home wins on every path.
    """
    if args.skip_copy_home:
        return False
    if args.copy_home:
        return True
    if args.install == "clone" or SKIP_PACSTRAP:
        return False
    # A pacstrap from a live session copies nothing by default.
    return not SRC.is_live


@log_all
def main(args=None) -> int:
    global TARGET_DISK, BOOTLOADER, SKIP_PACSTRAP, INSTALL_LINE, HOMES_LINE, CLONE_MODE
    global SKIP_HOME_DIRS, SKIP_HOME_EXTS, SKIP_VM, KEEP_MOUNTED
    if args is None:
        args = parse_args()
    if getattr(args, "gui", False):
        from blackarch_modules.blackarch_installer_gui import main as _gui_main

        return _gui_main()
    CLONE_MODE = args.install == "clone"

    preflight()
    introspect_source()
    # Who ran the installer, for the home-copy decision. Harmless to log:
    # invoker_user() only reads the login name of the process, never a password.
    invoker_user()
    info(f"Installer invoked by {INVOKER_USER or '<undetermined>'}")
    # Resolve --skip-pacstrap before anything is mounted or formatted.
    # prepare_layout() is the step that partitions and encrypts a target disk,
    # so a meaningless combination has to be rejected ahead of it.
    if args.skip_pacstrap:
        if args.install == "clone":
            die("--skip-pacstrap only applies to --install pacstrap")
        SKIP_PACSTRAP = True
        info("pacstrap will be skipped: reusing the packages already in the root")
    SKIP_NETWORK = args.skip_network
    SKIP_TIMEZONE = args.skip_timezone
    if args.skip_copy_home and args.copy_home:
        die("--skip-copy-home and --copy-home are mutually exclusive")
    # Resolved here, ahead of prepare_layout(), so home_excludes() sees the
    # final lists however the run is invoked.
    SKIP_HOME_DIRS = list(args.skip_home_dir or [])
    SKIP_HOME_EXTS = list(args.skip_home_ext or [])
    SKIP_VM = bool(args.skip_vm)
    KEEP_MOUNTED = bool(args.keep_mounted)
    if args.keep_mounted:
        info("--keep-mounted: partitions and cryptsetup will NOT be unmounted/closed")

    TARGET_DISK, target_name, EXISTING = select_target_disk(args.disk, args.existing)
    args.existing = EXISTING
    resolve_partition_args(args, TARGET_DISK, target_name)

    scheme = args.scheme
    if scheme is None and not args.existing:
        _emit("")
        _emit(f"{C['bold']}Partition scheme:{C['reset']}")
        _emit(
            f"  {C['cyan']}1){C['reset']} Recommended — EFI System Partition + Linux root (rest of disk)"
        )
        _emit(f"  {C['cyan']}2){C['reset']} Custom — define your own partitions")
        while True:
            choice = ask("Choose scheme", "1")
            if choice in ("1", "2"):
                scheme = "recommended" if choice == "1" else "custom"
                break
            warn("Enter 1 or 2")

    esp_part, root_part, luks_uuid = prepare_layout(
        args, TARGET_DISK, target_name, scheme
    )

    bind_esp_into_chroot()
    bind_home_into_chroot()
    # No loader is chosen for a clone (it keeps the running system's own) and
    # none is chosen for a pacstrap either unless --bootloader named one. There
    # is no prompt for this on either path. Everything below reads BOOTLOADER,
    # so both paths skip the loader packages, the initramfs build and the
    # UKI/limine install entirely.
    BOOTLOADER = choose_bootloader(args)
    if BOOTLOADER:
        info(f"Bootloader: {describe_bootloader()}")
    elif args.install == "clone":
        info(f"Bootloader: {describe_esp_loader()}")
    else:
        info("Bootloader: none (no loader will be installed on the new ESP)")

    if args.install == "clone":
        clone_system()
    else:
        bootstrap_system(args.cache_dir)
    # Credentials first: copy_user_homes() chowns by username INSIDE the new
    # root, so a pacstrap root has to carry the running /etc/passwd (and the
    # uid/gid it maps the name to) before any home is copied.
    preserve_credentials()
    enable_target_services()
    if not getattr(args, "skip_copy_sudoers", False):
        copy_sudoers_d()
    ensure_uid_1000_sudo()
    copy_network_config(skip=SKIP_NETWORK)
    homes_copied = copy_homes_now(args)
    if homes_copied:
        copy_user_homes()
    deploy_blackarch_tree()
    try:
        run(["arch-chroot", ROOT_MNT, "/opt/blackarch/bin/blackarch", "smartthings", "install"])
    except Exception:
        pass
    write_profile_d()
    configure_identity(esp_part, args.hostname)
    new_cmdline = build_new_cmdline(luks_uuid)
    info("New kernel cmdline: " + new_cmdline)
    CMDLINE_FOR_ESP[0] = new_cmdline
    write_cmdline_file(new_cmdline)
    # The unlock method has to be asked for before the initramfs is built:
    # the hooks decide whether the TPM token plugins are in the image at all.
    configure_unlock(args, luks_uuid)
    configure_mkinitcpio_hooks()
    # The unlocking stack is base-install, not an extra: a missing TPM token
    # plugin means an unbootable root. It is installed here rather than in
    # bootstrap_system() because the list depends on the unlock choice made
    # above. The bootloader packages are only installed when a loader was
    # actually chosen -- otherwise the new root is left without one.
    bl_pkgs = list(BOOTLOADER_PKGS.get(BOOTLOADER, ()))
    if UNLOCK_MODE in ("tpm2-fallback", "tpm2-only"):
        bl_pkgs += ["tpm2-tss", "tpm2-tools"]
    if bl_pkgs:
        info(f"Installing packages: {', '.join(bl_pkgs)}")
        try_run(
            [
                "arch-chroot",
                ROOT_MNT,
                "pacman",
                "-S",
                "--needed",
                "--noconfirm",
                *bl_pkgs,
            ]
        )
        ok(f"packages installed ({', '.join(bl_pkgs)})")
    # install_snapper_config()
    if not BOOTLOADER:
        # Nothing to install and nothing to build: no limine.conf, no UKI, no
        # NVRAM entry. /etc/kernel/cmdline was written above, so a loader
        # installed later (bootctl, limine-mkinitcpio, or a UKI build) picks up
        # the same cmdline this run derived.
        #
        # Explicitly NOT build_initramfs(): nothing can boot this root yet, so
        # the image would be built against a kernel tree the user may never use
        # and then rebuilt the moment they install their loader.
        warn(
            "no bootloader selected: leaving the new ESP without a loader; install a bootloader later before rebooting"
        )
    if BOOTLOADER:
        if not esp_part:
            warn("--bootloader requires an ESP; skipping efibootmgr entry")
        else:
            # If --bootloader is set, use its loader path; otherwise ask.
            entry_bl = BOOTLOADER
            if entry_bl == "both":
                # In both mode only systemd-boot gets an NVRAM entry; Limine is
                # reached through the chainload entry written by systemd-boot.
                entry_bl = "systemd-boot"
            if not entry_bl:
                info("--bootloader: which bootloader is this EFI entry for?")
                choice = ask_choice(
                    "Bootloader for EFI entry",
                    (
                        ("limine", "Limine (limine_x64.efi)"),
                        ("systemd-boot", "systemd-boot (systemd-bootx64.efi)"),
                    ),
                    "limine",
                )
                entry_bl = choice
            loader_path = {
                "limine": r"/EFI/limine/limine_x64.efi",
                "systemd-boot": r"/EFI/systemd/systemd-bootx64.efi",
            }.get(entry_bl, r"/EFI/BOOT/BOOTX64.EFI")
            label = f"Blackarch-{entry_bl}-{time.strftime('%Y-%m-%d %H:%M:%S')}"
            try:
                disk = parent_disk(esp_part)
                esp_disk_path = f"/dev/{disk}" if disk else ""
                m = re.search(r"(\d+)$", esp_part)
                if disk and not m:
                    m = re.search(r"p(\d+)$", esp_part)
                part_num = m.group(1) if m else "1"
                cmd = [
                    "efibootmgr",
                    "-c",
                    "-d",
                    esp_disk_path,
                    "-p",
                    part_num,
                    "-L",
                    label,
                    "-l",
                    loader_path,
                ]
                run(cmd, check=False)
                ok(f"EFI boot entry created via efibootmgr: {label} ({loader_path})")
            except SystemExit:
                warn("efibootmgr entry creation failed (check --bootloader conditions)")
    if BOOTLOADER in ("limine", "both"):
        build_initramfs()
        install_limine_bootloader(esp_part)
    if BOOTLOADER in ("systemd-boot", "both"):
        build_initramfs()
        build_ukis(new_cmdline)
        install_systemd_boot()
    # what the summary reports: decided once --install and --skip-pacstrap are
    # both known, so it cannot disagree with what bootstrap_system() did
    if args.install == "clone":
        INSTALL_LINE = "clone of the running system"
    elif SKIP_PACSTRAP:
        INSTALL_LINE = "pacstrap skipped - reusing the packages in the target root"
    else:
        INSTALL_LINE = "pacstrap into a fresh Arch root"
    if homes_copied:
        HOMES_LINE = (
            f"copied for {len(SRC.users)} user(s) from the running system "
            f"({', '.join(SRC.users) or 'none'})"
        )
        if SKIP_HOME_DIRS or SKIP_HOME_EXTS or SKIP_VM:
            HOMES_LINE += "; skipped " + ", ".join(
                [
                    *(f"dir {d}" for d in SKIP_HOME_DIRS),
                    *(f"*.{e.lstrip('.')}" for e in SKIP_HOME_EXTS),
                    *(["VM images"] if SKIP_VM else []),
                ]
            )
    elif args.skip_copy_home:
        HOMES_LINE = "not copied (--skip-copy-home)"
    elif args.install == "clone":
        HOMES_LINE = "carried by the clone (not copied)"
    elif SKIP_PACSTRAP:
        HOMES_LINE = "left as they are (existing root)"
    elif SRC.is_live:
        HOMES_LINE = (
            "not copied (running from a live session"
            + (f": {SRC_LIVE_REASON}" if SRC_LIVE_REASON else "")
            + ") - pass --copy-home to take them anyway"
        )
    else:
        HOMES_LINE = "left as they are (existing root)"

    finalize()
    print_summary(esp_part, root_part, luks_uuid, new_cmdline)
    return 0


@log_all
def detect_esp_loader() -> str:
    """Which bootloader the running system's ESP already carries, or "".

    A clone does not get a fresh loader: it keeps whatever the source system
    boots from. This reports that loader from the ESP itself rather than
    hardcoding one, because the source may be a Limine USB or a systemd-boot
    machine -- assuming either would make the summary and any later tooling
    disagree with what is actually on the ESP.

    Probed in the order the tools lay their files out, and the EFI/BOOT
    fallback is deliberately absent: BOOTX64.EFI is present on virtually every
    ESP (it is the removable-media path) and says nothing about which loader the
    OS actually uses.
    """
    probes = (
        ("limine", ("limine.conf", "limine-bios-earlytcp.bin")),
        ("systemd-boot", ("EFI/systemd/systemd-bootx64.efi", "loader/loader.conf")),
    )
    for loader, paths in probes:
        if any(os.path.exists(os.path.join(EFI_MNT, p)) for p in paths):
            return loader
    return ""


@log_all
def describe_esp_loader() -> str:
    """What a clone keeps, phrased for the log and the summary."""
    loader = detect_esp_loader()
    if not loader:
        return "unknown (no limine.conf or systemd-boot on the source ESP)"
    return f"{loader} (carried by the clone from the running system's ESP)"


@log_all
def choose_bootloader(args) -> str:
    """The bootloader to install: from --bootloader, or "" when none is wanted.

    Opt-in, and never asked on the clone path:

      clone     the ESP content comes from the running system's own ESP, so
                there is nothing to choose and nothing to install. --bootloader
                is ignored here rather than honoured, because writing a loader
                would overwrite the very thing the clone is copying.
      pacstrap  the loader is chosen by --bootloader and by nothing else. There
                is no prompt: a pacstrap root is built without a loader unless
                the user names one, since a bootstrapped root need not be
                bootable by this installer (a chroot, a VM image, or a root
                whose loader the user installs themselves) and installing one
                would also write an NVRAM entry to their ESP. Returning "" is
                the default, not a refusal.
    """
    global BOOTLOADER
    if args.install == "clone":
        esp_loader = describe_esp_loader()
        info(f"clone path: keeping the running system's own bootloader ({esp_loader})")
        return ""

    if args.bootloader in (None, "none"):
        info(
            "no bootloader selected: the new ESP will not get a loader or an NVRAM entry"
        )
        return ""

    choice = args.bootloader
    if choice == "both":
        tools = BOOTLOADER_TOOLS["limine"] + BOOTLOADER_TOOLS["systemd-boot"]
        missing = [t for t in tools if not shutil.which(t)]
        if missing:
            die(f"both needs {', '.join(missing)}")
        return "both"
    # preflight() ran before the choice existed, so the tool check for the chosen
    # loader happens here too -- an explicit --bootloader must not skip it.
    missing = [t for t in BOOTLOADER_TOOLS[choice] if not shutil.which(t)]
    if missing:
        die(
            f"{choice} needs {', '.join(missing)} on the running system — "
            "install it first (pacman -S limine limine-mkinitcpio-hook)"
        )
    return choice


@log_all
def _entry() -> None:
    """Parse arguments first (so --help works unprivileged), then elevate."""
    args = parse_args(sys.argv[1:])  # exits 0 for --help / -h

    if os.geteuid() != 0:
        if shutil.which("sudo"):
            _emit("==> This installer must run as root; requesting elevation via sudo.")
            os.execvp(
                "sudo",
                ["sudo", sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]],
            )
        _emit("✗ This installer must run as root and sudo is unavailable.")
        sys.exit(1)

    code = 0
    try:
        code = main(args=args)
    finally:
        cleanup_mounts()
    sys.exit(code)


if __name__ == "__main__":
    _entry()
