#!/usr/bin/env python3
# blackarch:summary=Install and configure Limine with btrfs snapshot support
# blackarch:args=[--help]
# blackarch:examples=blackarch limine setup | sudo blackarch-limine-setup
"""
blackarch-limine-setup.py -- install and configure Limine with btrfs snapshot support.

Python port of blackarch-limine-setup. Every disk, partition, UUID and mount
point is discovered at runtime with GNU parted (``parted -s -j ...``) plus
findmnt/blkid/cryptsetup; nothing device-specific is hardcoded.

Usage:
    sudo python3 blackarch-limine-setup.py                # configure existing ESP
    sudo python3 blackarch-limine-setup.py --dry-run      # show what would happen
    sudo python3 blackarch-limine-setup.py --print-layout # dump detected layout as JSON
    sudo python3 blackarch-limine-setup.py --check        # self-check: no hardcoded devices
    sudo python3 blackarch-limine-setup.py --partition    # create ESP + root on a disk first

Notes:
    * The ESP, root device and LUKS container are matched to parted partitions by
      device path, so the script works on nvme0n1p1, sda1, vda1, mmcblk0p1, ...
      without any per-machine edits.
    * `--partition` is destructive. It is never run implicitly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence

# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #


class C:
    BLUE = GREEN = RED = YEL = CYAN = BOLD = NC = ""

    @classmethod
    def enable(cls) -> None:
        if not sys.stdout.isatty():
            return
        cls.BLUE, cls.GREEN, cls.RED = "\033[0;34m", "\033[0;32m", "\033[0;31m"
        cls.YEL, cls.CYAN, cls.BOLD = "\033[1;33m", "\033[0;36m", "\033[1m"
        cls.NC = "\033[0m"


def info(msg: str) -> None:
    print(f"{C.BLUE}[INFO]{C.NC} {msg}")


def ok(msg: str) -> None:
    print(f"{C.GREEN}[ok]{C.NC} {msg}")


def warn(msg: str) -> None:
    print(f"{C.YEL}[!]{C.NC} {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"{C.RED}[x]{C.NC} {msg}", file=sys.stderr)


def step(msg: str) -> None:
    print(f"{C.CYAN}[>]{C.NC} {msg}")


def highlight(msg: str) -> None:
    print(f"{C.BOLD}{msg}{C.NC}")


class SetupError(RuntimeError):
    """Fatal, user-facing error."""


# --------------------------------------------------------------------------- #
# Command execution
# --------------------------------------------------------------------------- #


def run(
    cmd: Sequence[str], *, check: bool = True, input_text: str | None = None
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        list(cmd),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise SetupError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}"
            + (f"\n  {detail[-1]}" if detail else "")
        )
    return proc


# --------------------------------------------------------------------------- #
# parted -- the only source of truth for disks and partitions
# --------------------------------------------------------------------------- #

# Partition type GUIDs we care about (GPT only).
GPT_ESP = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
GPT_LINUX_FS = "0fc63daf-8483-4772-8e79-3d69d8477de4"

_HARDCODED_DEVICE_RE = re.compile(
    r"/dev/(?:sd[a-z]+|nvme\d+n\d+|vd[a-z]+|hd[a-z]+|mmcblk\d+|loop\d+|zram\d+)"
)
_HARDCODED_PARTNUM_RE = re.compile(r"(?<![\w-])-p\s+\d+(?![\w-])")


@dataclass
class Partition:
    number: int
    name: str = ""
    uuid: str = ""
    type_uuid: str = ""
    flags: list[str] = field(default_factory=list)
    size: int = 0

    @property
    def is_esp(self) -> bool:
        return "esp" in self.flags or self.type_uuid.lower() == GPT_ESP


@dataclass
class Disk:
    path: str
    label: str = ""
    size: int = 0
    partitions: list[Partition] = field(default_factory=list)

    @property
    def base(self) -> str:
        return os.path.basename(self.path)

    @property
    def has_table(self) -> bool:
        return bool(self.label)

    def part_dev(self, part: Partition) -> str:
        """Device node for a partition of this disk.

        nvme0n1p1 / mmcblk0p1 / loop0p1 insert a 'p' before the number; sda1 /
        vda1 / sda1 do not. Derived from the disk name, never hardcoded.
        """
        base = self.base
        return (
            f"{self.path}p{part.number}"
            if base[-1:].isdigit()
            else f"{self.path}{part.number}"
        )

    def partition(self, number: int) -> Partition | None:
        for part in self.partitions:
            if part.number == number:
                return part
        return None

    def esp_partitions(self) -> list[Partition]:
        return [p for p in self.partitions if p.is_esp]


def _parse_size(text: str) -> int:
    """Parted prints sizes like "10485760B", "10.5MB" or "1049kB"; convert to bytes.

    Decimal is used so "67.1MB" is exactly 67100000 and not 67099999.
    """
    m = re.match(r"\s*([\d.]+)\s*([kKMGTP]?)i?B?", str(text))
    if not m:
        return 0
    value = Decimal(m.group(1))
    mult = {
        "": 1,
        "k": 10**3,
        "K": 10**3,
        "M": 10**6,
        "G": 10**9,
        "T": 10**12,
        "P": 10**15,
    }[m.group(2)]
    return int(value * Decimal(mult))


def _disk_from_json(data: dict, requested: str) -> Disk:
    path = data.get("path") or requested
    disk = Disk(
        path=path,
        label=data.get("label", "") or "",
        size=_parse_size(data.get("size", "0")),
    )
    for p in data.get("partitions", []) or []:
        disk.partitions.append(
            Partition(
                number=int(p.get("number", 0)),
                name=p.get("name", "") or "",
                uuid=p.get("uuid", "") or "",
                type_uuid=p.get("type-uuid", "") or "",
                flags=[str(f) for f in (p.get("flags") or [])],
                size=_parse_size(p.get("size", "0")),
            )
        )
    disk.partitions.sort(key=lambda p: p.number)
    return disk


def _parse_parted_json(text: str, requested: str) -> list[Disk]:
    """Parse `parted --json` output.

    `parted -j <dev> print` emits {"disk": {...}}; `parted -j --list` emits an
    array of disk objects (each either bare or wrapped in {"disk": {...}}).
    Both shapes are accepted so the parser does not depend on the exact
    enumeration mode that succeeded.
    """
    text = text.strip()
    if not text:
        raise SetupError("parted returned no output")
    data = json.loads(text)

    if isinstance(data, list):
        disks = []
        for item in data:
            body = (
                item.get("disk") if isinstance(item, dict) and "disk" in item else item
            )
            if isinstance(body, dict):
                disks.append(_disk_from_json(body, requested))
        return disks

    if isinstance(data, dict) and "disk" in data:
        return [_disk_from_json(data["disk"], requested)]
    if isinstance(data, dict):
        return [_disk_from_json(data, requested)]
    raise SetupError(f"unexpected parted JSON shape: {type(data).__name__}")


def parted_print(dev: str) -> Disk:
    """Return one disk's layout as reported by parted (bytes)."""
    proc = run(["parted", "--script", "--json", dev, "unit", "B", "print"], check=False)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        raise SetupError(
            f"parted cannot read {dev}: {msg[-1] if msg else 'unknown error'}"
        )
    return _parse_parted_json(proc.stdout, dev)[0]


def discover_disks() -> list[Disk]:
    """Enumerate disks with parted.

    Primary path: `parted --list` (one call, all devices).
    Fallback: walk /sys/block and ask parted about each device that exists --
    only devices parted recognises as a partitioned disk are kept.
    """
    proc = run(["parted", "--script", "--json", "--list"], check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            disks = _parse_parted_json(proc.stdout, "")
            if disks:
                return [d for d in disks if d.has_table]
        except (SetupError, ValueError) as exc:
            warn(
                f"parted --list output unparseable ({exc}); falling back to per-device probe"
            )

    disks: list[Disk] = []
    try:
        names = sorted(os.listdir("/sys/block"))
    except OSError:
        return disks
    for name in names:
        # Prune pseudo devices by class; the decision to keep a device is still
        # made by parted, not by this list.
        if name.startswith(("loop", "ram", "zram")):
            continue
        dev = f"/dev/{name}"
        if not os.path.exists(dev):
            continue
        try:
            disk = parted_print(dev)
        except SetupError:
            continue
        if disk.has_table:
            disks.append(disk)
    return disks


# --------------------------------------------------------------------------- #
# Mounts / device mapping
# --------------------------------------------------------------------------- #


def findmnt(target: str) -> tuple[str, str]:
    """(SOURCE, FSTYPE) for a mount point, or ("", "")."""
    proc = run(["findmnt", "-n", "-o", "SOURCE,FSTYPE", target], check=False)
    if proc.returncode != 0:
        return "", ""
    parts = proc.stdout.split()
    if len(parts) < 2:
        return "", ""
    source = parts[0]
    if source.startswith("/dev/mapper/") and "[" in source:  # source[/subvol]
        source = source.split("[", 1)[0]
    return source, parts[1]


def first_mountpoint_of(source: str) -> str:
    proc = run(["findmnt", "-n", "-rn", "-o", "TARGET", source], check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""


def blkid_uuid(dev: str) -> str:
    proc = run(["blkid", "-s", "UUID", "-o", "value", dev], check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def cryptsetup_luks_uuid(dev: str) -> str:
    proc = run(["cryptsetup", "luksUUID", dev], check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def is_luks(dev: str) -> bool:
    return run(["cryptsetup", "isLuks", dev], check=False).returncode == 0


# --------------------------------------------------------------------------- #
# Detected system layout
# --------------------------------------------------------------------------- #


@dataclass
class Layout:
    esp_disk: Disk
    esp_part: Partition
    esp_mount: str
    root_dev: str
    root_fstype: str
    luks_dev: str = ""  # backing partition of the LUKS container
    luks_uuid: str = ""
    luks_name: str = ""  # dm-crypt mapping name
    root_disk: Disk | None = None
    root_part: Partition | None = None

    @property
    def encrypted(self) -> bool:
        return bool(self.luks_name)

    def to_dict(self) -> dict:
        return {
            "esp_disk": self.esp_disk.path,
            "esp_partition": self.esp_part.number,
            "esp_device": self.esp_disk.part_dev(self.esp_part),
            "esp_mount": self.esp_mount,
            "root_device": self.root_dev,
            "root_fstype": self.root_fstype,
            "encrypted": self.encrypted,
            "luks_backing": self.luks_dev,
            "luks_uuid": self.luks_uuid,
            "luks_name": self.luks_name,
            "root_disk": self.root_disk.path if self.root_disk else "",
            "root_partition": self.root_part.number if self.root_part else 0,
        }


def _match_partition(
    disks: Iterable[Disk], dev: str
) -> tuple[Disk | None, Partition | None]:
    for disk in disks:
        for part in disk.partitions:
            if disk.part_dev(part) == dev:
                return disk, part
    return None, None


def detect_layout(disks: Sequence[Disk]) -> Layout:
    # --- ESP: prefer the mounted vfat, then the partition flagged "esp".
    esp_mount, esp_dev = "", ""
    for cand in ("/efi", "/boot/efi", "/boot"):
        source, fstype = findmnt(cand)
        if source.startswith("/dev/") and fstype == "vfat":
            esp_dev, esp_mount = source, first_mountpoint_of(source) or cand
            break

    esp_disk, esp_part = _match_partition(disks, esp_dev)
    if esp_part is None:
        for disk in disks:
            flagged = disk.esp_partitions()
            if flagged:
                esp_disk, esp_part = disk, flagged[0]
                break
    if esp_part is None:
        raise SetupError(
            "No EFI System Partition found. Mount your ESP first "
            "(e.g. /efi) or run with --partition to create one."
        )
    if esp_dev and not esp_part.is_esp:
        warn(
            f"{esp_dev} is mounted at {esp_mount} but is not flagged 'esp' in the partition table"
        )

    # --- Root filesystem and (optional) LUKS container.
    root_dev, root_fstype = findmnt("/")
    if not root_dev:
        raise SetupError("Could not determine the root filesystem (findmnt / failed)")

    luks_dev = luks_uuid = luks_name = ""
    if root_dev.startswith("/dev/mapper/"):
        luks_name = os.path.basename(root_dev)
        proc = run(["cryptsetup", "status", luks_name], check=False)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.strip().startswith("device:"):
                    luks_dev = line.split(":", 1)[1].strip()
                    break
        if not luks_dev:
            proc = run(["dmsetup", "deps", luks_name], check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                luks_dev = "/dev/" + re.search(r"\(([^)]+)\)", proc.stdout).group(1)
        if luks_dev:
            luks_uuid = cryptsetup_luks_uuid(luks_dev) or blkid_uuid(luks_dev)
    else:
        luks_uuid = blkid_uuid(root_dev)

    # If root was not on a mapper, look for a LUKS partition that is not root.
    if not luks_dev and root_fstype != "crypto_LUKS":
        for disk in disks:
            for part in disk.partitions:
                dev = disk.part_dev(part)
                if dev != root_dev and is_luks(dev):
                    luks_dev = dev
                    luks_uuid = cryptsetup_luks_uuid(dev)
                    luks_name = ""
                    break
            if luks_dev:
                break

    if not luks_uuid:
        warn("Could not detect a LUKS UUID; set it manually in limine.conf")

    root_disk, root_part = _match_partition(disks, luks_dev or root_dev)

    return Layout(
        esp_disk=esp_disk,
        esp_part=esp_part,
        esp_mount=esp_mount,
        root_dev=root_dev,
        root_fstype=root_fstype,
        luks_dev=luks_dev,
        luks_uuid=luks_uuid,
        luks_name=luks_name,
        root_disk=root_disk,
        root_part=root_part,
    )


# --------------------------------------------------------------------------- #
# Kernel entries on the ESP
# --------------------------------------------------------------------------- #


def machine_id() -> str:
    try:
        with open("/etc/machine-id", encoding="utf-8") as fh:
            mid = fh.read().strip()
        return mid or "unknown"
    except OSError:
        return "unknown"


def kernel_dirs(esp_mount: str) -> list[str]:
    """Subdirectories of <ESP>/<machine-id>/ that hold a kernel, newest first."""
    run(["limine-mkinitcpio"])
    base = os.path.join(esp_mount, machine_id())
    if not os.path.isdir(base):
        # Fallback: any directory on the ESP that contains a vmlinuz.
        try:
            base = next(
                os.path.join(esp_mount, d)
                for d in sorted(os.listdir(esp_mount))
                if os.path.isfile(
                    os.path.join(esp_mount, d, "linux-aegis-offensive", "vmlinuz")
                )
            )
        except StopIteration:
            raise SetupError(
                f"No kernel directory found under {esp_mount}. Run mkinitcpio first."
            )
    try:
        names = sorted(os.listdir(base))
    except OSError as exc:
        raise SetupError(f"Cannot read {base}: {exc}")
    dirs = [n for n in names if os.path.isfile(os.path.join(base, n, "vmlinuz"))]
    # Prefer the offensive kernel as the default (first) entry.
    dirs.sort(key=lambda n: 0 if "offensive" in n else 1)
    if not dirs:
        raise SetupError(f"No kernel (vmlinuz) found under {base}")
    return dirs


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


def install_packages(dry_run: bool) -> None:
    step("Installing Limine and dependencies...")
    pkgs = ["limine", "limine-mkinitcpio-hook", "snapper"]
    if dry_run:
        info(f"would run: pacman -S --noconfirm --needed {' '.join(pkgs)}")
        return
    run(["pacman", "-S", "--noconfirm", "--needed", *pkgs])
    ok("Packages installed")


def locate_limine_efi() -> str:
    """Find the packaged BOOTX64.EFI without hardcoding the share path."""
    proc = run(["pacman", "-Ql", "limine"], check=False)
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if line.endswith("BOOTX64.EFI"):
                path = line.split(None, 1)[1].strip()
                if os.path.isfile(path):
                    return path
    fallback = "/usr/share/limine/BOOTX64.EFI"
    if os.path.isfile(fallback):
        return fallback
    raise SetupError("BOOTX64.EFI not found; is the limine package installed?")


def install_efi_binary(layout: Layout, dry_run: bool) -> None:
    step("Installing Limine EFI binary...")
    src = locate_limine_efi()
    esp = layout.esp_mount
    targets = [
        os.path.join(esp, "EFI", "BOOT", "BOOTX64.EFI"),
        os.path.join(esp, "EFI", "limine", "limine_x64.efi"),
        os.path.join(esp, "EFI", "limine", "limine.efi"),
    ]
    if dry_run:
        for dst in targets:
            info(f"would copy {src} -> {dst}")
        return
    for dst in targets:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        ok(f"installed {dst}")


def configure_snapper(dry_run: bool) -> None:
    step("Configuring Snapper...")
    if dry_run:
        info(
            "would ensure a 'root' snapper config exists and create an initial snapshot"
        )
        return
    if "root" not in run(["snapper", "list-configs"], check=False).stdout:
        run(["snapper", "-c", "root", "create-config", "/"], check=False)
        ok("Snapper config created")
    else:
        info("Snapper config already exists")

    listing = run(["snapper", "-c", "root", "list"], check=False).stdout
    singles = [
        ln for ln in listing.splitlines() if "single" in ln and "current" not in ln
    ]
    if len(singles) <= 1:
        run(
            ["snapper", "-c", "root", "create", "--description", "Initial snapshot"],
            check=False,
        )
        ok("Initial snapshot created")
    else:
        info("Snapshots already exist")


def snapshot_entries(
    dry_run: bool, kernel_dir: str, layout: Layout, subvol: str
) -> list[tuple[int, str]]:
    """(number, description) for every non-current single snapshot."""
    if dry_run:
        return []
    proc = run(["snapper", "-c", "root", "list"], check=False)
    rows: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        if "single" not in line or "current" in line:
            continue
        fields = line.split("|")
        if len(fields) < 2 or not fields[0].strip().isdigit():
            continue
        number = int(fields[0].strip())
        desc = fields[2].strip() if len(fields) > 2 else ""
        rows.append((number, desc))
    return rows


def build_cmdline(layout: Layout, subvol: str) -> str:
    """Root cmdline built from detected values (LUKS only when present)."""
    parts = []
    if layout.encrypted and layout.luks_uuid:
        name = layout.luks_name or "cryptroot"
        parts.append(f"rd.luks.name={layout.luks_uuid}={name}")
        parts.append("rd.luks.options=tpm2-device=auto")
        parts.append(f"root={layout.root_dev}")
    else:
        # Plain btrfs: address the partition by its GPT PARTUUID from parted.
        partuuid = layout.root_part.uuid if layout.root_part else ""
        parts.append(
            f"root=PARTUUID={partuuid}" if partuuid else f"root={layout.root_dev}"
        )
    parts.append(f"rootflags=subvol={subvol}")
    parts += ["quiet", "loglevel=3"]
    return " ".join(parts)


def limine_conf_text(
    layout: Layout, args: argparse.Namespace, snapshot_rows: list[tuple[int, str]]
) -> str:
    esp = layout.esp_mount
    mid = machine_id()
    kdirs = kernel_dirs(esp)
    primary = kdirs[0]
    out: list[str] = []
    add = out.append

    add("### Limine configuration with btrfs snapshot support")
    add(f"# generated by blackarch-limine-setup.py for {layout.esp_disk.path}")
    add(f"hash_mismatch_panic: no")
    add(f"timeout: {args.timeout}")
    add(f"default_entry: {args.default_entry}")
    add("")

    # Normal boot entries: one per kernel directory found on the ESP.
    for idx, kdir in enumerate(kdirs, start=1):
        add(f"/+Kernel {idx}")
        add(f"comment: {kdir}")
        add("  protocol: linux")
        add(f"  path: boot():/{mid}/{kdir}/vmlinuz")
        add(f"  module_path: boot():/{mid}/{kdir}/initramfs")
        add(f"  cmdline: {build_cmdline(layout, '@')}")
        add("")

    # Snapshot entries.
    if snapshot_rows:
        add("/+Snapshots")
        add("comment: Btrfs Snapshots")
        for number, desc in snapshot_rows:
            add(f"  /snapshot:{number}")
            add(f"  comment: Snapshot {number} - {desc or 'snapshot'}")
            add("  protocol: linux")
            add(f"  path: boot():/{mid}/{primary}/vmlinuz")
            add(f"  module_path: boot():/{mid}/{primary}/initramfs")
            add(f"  cmdline: {build_cmdline(layout, f'/.snapshots/{number}/snapshot')}")
            add("")
        add("")

    add("/Systemd-boot")
    add("protocol: efi")
    add("path: boot():/EFI/systemd/systemd-bootx64.efi")
    add("")
    add("/EFI fallback")
    add("protocol: efi")
    add("path: boot():/EFI/BOOT/BOOTX64.EFI")
    add("")
    return "\n".join(out)


def write_limine_conf(layout: Layout, args: argparse.Namespace, dry_run: bool) -> str:
    step("Writing limine.conf...")
    conf_path = os.path.join(layout.esp_mount, "limine.conf")
    rows = snapshot_entries(dry_run, kernel_dirs(layout.esp_mount)[0], layout, "@")
    text = limine_conf_text(layout, args, rows)

    if dry_run:
        info(f"would write {conf_path}:")
        print(text)
        return conf_path

    if os.path.exists(conf_path):
        backup = f"{conf_path}.old"
        shutil.copy2(conf_path, backup)
        info(f"backed up existing config to {backup}")
    with open(conf_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    ok(f"limine.conf written to {conf_path}")
    return conf_path


def set_boot_order(layout: Layout, dry_run: bool) -> None:
    step("Setting boot order...")
    esp = layout.esp_disk.path
    partno = str(layout.esp_part.number)
    listing = run(["efibootmgr"], check=False).stdout
    nums = re.findall(r"Boot([0-9A-Fa-f]{4})", listing)
    limine_nums = [
        n for n in nums if re.search(rf"Boot{n}\*?\s+.*limine", listing, re.I)
    ]

    if not limine_nums:
        # Samsung (and some other) firmware auto-removes non-standard NVRAM
        # boot entries on reboot, so do NOT create one with efibootmgr -c.
        # Install the bootloader at the UEFI fallback path instead, which
        # firmware always honours without an NVRAM entry.
        src = os.path.join(layout.esp_mount, "EFI", "limine", "limine_x64.efi")
        if not os.path.exists(src):
            src = os.path.join(layout.esp_mount, "EFI", "limine", "limine.efi")
        dst_dir = os.path.join(layout.esp_mount, "EFI", "BOOT")
        dst = os.path.join(dst_dir, "BOOTX64.EFI")
        if dry_run:
            info(f"would copy {src} -> {dst} (fallback boot path; no NVRAM entry)")
            return
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
        ok(f"Limine installed to fallback path {dst} (no NVRAM entry; survives Samsung firmware purge)")
        return

    if limine_nums:
        first = limine_nums[0]
        rest = [n for n in nums if n != first]
        order = ",".join([first] + rest)
        if dry_run:
            info(f"would run: efibootmgr -o {order}")
            return
        run(["efibootmgr", "-o", order], check=False)
        ok(f"Limine set as first boot entry (Boot{first})")


# --------------------------------------------------------------------------- #
# --partition: create ESP + root with parted
# --------------------------------------------------------------------------- #


def partition_disk(disk: Disk, args: argparse.Namespace, dry_run: bool) -> None:
    """Create a GPT with an ESP and a root partition using parted.

    The disk is chosen by the caller (argument or interactive prompt), never by
    a hardcoded device name. Sizes come from the disk size parted reports.
    """
    step(f"Partitioning {disk.path} with parted...")
    esp_bytes = _parse_size(args.esp_size)
    if esp_bytes <= 0:
        raise SetupError(f"invalid --esp-size {args.esp_size!r}")
    if disk.size and esp_bytes >= disk.size:
        raise SetupError(
            f"ESP size {args.esp_size} does not fit on {disk.path} "
            f"({_human(disk.size)}); pass a smaller --esp-size"
        )

    cmds = [
        ["parted", "--script", "--fix", "-a", "optimal", disk.path, "mklabel", "gpt"],
        [
            "parted",
            "--script",
            "--fix",
            "-a",
            "optimal",
            disk.path,
            "mkpart",
            "ESP",
            "fat32",
            "1MiB",
            args.esp_size,
        ],
        [
            "parted",
            "--script",
            "--fix",
            "-a",
            "optimal",
            disk.path,
            "set",
            "1",
            "esp",
            "on",
        ],
        [
            "parted",
            "--script",
            "--fix",
            "-a",
            "optimal",
            disk.path,
            "mkpart",
            "root",
            args.root_fs,
            args.esp_size,
            "100%",
        ],
    ]

    if dry_run:
        for cmd in cmds:
            info("would run: " + " ".join(cmd))
        return

    for cmd in cmds:
        run(cmd, check=False)

    # parted is invoked with check=False; verify the layout it actually produced.
    try:
        after = parted_print(disk.path)
    except SetupError as exc:
        raise SetupError(
            f"parted did not produce a readable table on {disk.path}: {exc}"
        )
    esp, root = after.partition(1), after.partition(2)
    if esp is None or root is None or not esp.is_esp:
        raise SetupError(
            f"partitioning {disk.path} did not yield an ESP + root layout "
            f"(table={after.label}, partitions={[p.number for p in after.partitions]})"
        )
    ok(f"created GPT on {disk.path} (ESP {args.esp_size}, root {args.root_fs})")


def _human(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{n}B"


def sysfs_disk_size(dev: str) -> int:
    """Disk size in bytes from sysfs (works for blank disks parted cannot read)."""
    try:
        with open(f"/sys/block/{os.path.basename(dev)}/size", encoding="ascii") as fh:
            return int(fh.read().strip()) * 512
    except (OSError, ValueError):
        return 0


def choose_disk_interactive(disks: Sequence[Disk], blanks: Sequence[Disk]) -> Disk:
    print("\nCandidate disks (from parted):")
    for i, d in enumerate([*blanks, *disks], start=1):
        status = (
            "unpartitioned"
            if not d.has_table
            else f"{d.label} with {len(d.partitions)} partitions"
        )
        print(f"  {i:2d}. {d.path:<20} {d.size / 10**9:8.1f} GB  {status}")
    while True:
        raw = input("\nDisk to partition (number or path, empty to abort): ").strip()
        if not raw:
            raise SetupError("aborted")
        if raw.isdigit():
            idx = int(raw) - 1
            pool = [*blanks, *disks]
            if 0 <= idx < len(pool):
                return pool[idx]
        for d in disks:
            if d.path == raw:
                return d
        warn("not a listed disk, try again")


# --------------------------------------------------------------------------- #
# Self-check: prove nothing is hardcoded
# --------------------------------------------------------------------------- #


def self_check() -> int:
    """Scan this file for hardcoded disk/partition references."""
    path = os.path.abspath(__file__)
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()

    hits: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#"):
            continue
        for m in _HARDCODED_DEVICE_RE.finditer(line):
            hits.append(f"line {lineno}: device {m.group(0)} -> {line.strip()}")
        for m in _HARDCODED_PARTNUM_RE.finditer(line):
            hits.append(
                f"line {lineno}: partition number {m.group(0)} -> {line.strip()}"
            )

    print(f"scanned {path} ({len(lines)} lines)")
    if hits:
        err(f"{len(hits)} hardcoded reference(s) found:")
        for h in hits:
            print(f"  {h}")
        return 1
    ok("no hardcoded disk paths or partition numbers")
    return 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Install and configure Limine with btrfs snapshot support (parted-driven, nothing hardcoded).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be done, change nothing",
    )
    p.add_argument(
        "--yes", "-y", action="store_true", help="assume yes to destructive prompts"
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=3,
        help="Limine menu timeout in seconds (default 3)",
    )
    p.add_argument(
        "--default-entry",
        type=int,
        default=1,
        help="Limine default entry index (default 1)",
    )
    p.add_argument(
        "--no-snapper",
        action="store_true",
        help="skip snapper configuration and snapshot entries",
    )
    p.add_argument(
        "--print-layout",
        action="store_true",
        help="print the detected disk layout as JSON and exit",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="self-check for hardcoded devices, then exit",
    )
    p.add_argument(
        "--partition",
        action="store_true",
        help="create ESP + root partitions on a disk before configuring",
    )
    p.add_argument(
        "--disk",
        metavar="PATH",
        help="disk to partition (with --partition); omit to be prompted",
    )
    p.add_argument(
        "--esp-size", default="2GiB", help="ESP size for --partition (default 2GiB)"
    )
    p.add_argument(
        "--root-fs",
        default="btrfs",
        help="root partition filesystem for --partition (default btrfs)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="allow --partition on a disk that already has a partition table",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    C.enable()
    args = parse_args(argv)

    if args.check:
        return self_check()

    if os.geteuid() != 0:
        err("Run as root (sudo).")
        return 1

    step("Discovering disks with parted...")
    disks = discover_disks()
    if not disks:
        err("parted found no partitioned disk.")
        return 1
    blanks = []
    if args.partition:
        # Blank disks are not returned by the enumerator; probe them on request.
        for name in sorted(os.listdir("/sys/block")):
            if name.startswith(("loop", "ram", "zram")):
                continue
            dev = f"/dev/{name}"
            if not os.path.exists(dev):
                continue
            try:
                d = parted_print(dev)
            except SetupError:
                blanks.append(Disk(path=dev, label="", size=sysfs_disk_size(dev)))
                continue
            if not d.has_table:
                blanks.append(d)

    for d in disks:
        parts = ", ".join(
            f"{d.part_dev(p)}({','.join(p.flags) or p.name or '?'})"
            for p in d.partitions
        )
        info(
            f"{d.path} [{d.label}] {d.size / 10**9:.1f} GB  partitions: {parts or 'none'}"
        )

    layout = detect_layout(disks)
    info("Detected layout: " + json.dumps(layout.to_dict(), indent=2))

    if args.print_layout:
        print(
            json.dumps(
                {
                    "disks": [
                        {
                            "path": d.path,
                            "label": d.label,
                            "size": d.size,
                            "partitions": [p.__dict__ for p in d.partitions],
                        }
                        for d in disks
                    ],
                    "layout": layout.to_dict(),
                },
                indent=2,
            )
        )
        return 0

    if args.partition:
        target = None
        if args.disk:
            target = next((d for d in disks if d.path == args.disk), None)
            if target is None:
                err(f"{args.disk} is not a partitioned disk known to parted")
                return 1
            if target.has_table and not args.force:
                err(
                    f"{target.path} already has a {target.label} table; pass --force to overwrite"
                )
                return 1
        else:
            target = choose_disk_interactive(disks, blanks)
        if not args.yes and not args.dry_run:
            if (
                input(f"ALL DATA ON {target.path} WILL BE DESTROYED. Type 'yes': ")
                .strip()
                .lower()
                != "yes"
            ):
                err("aborted")
                return 1
        partition_disk(target, args, args.dry_run)
        if args.dry_run:
            info("dry run: not configuring Limine after a simulated partition")
            return 0
        disks = discover_disks()
        layout = detect_layout(disks)
        info("Re-detected layout after partitioning: " + json.dumps(layout.to_dict()))

    try:
        install_packages(args.dry_run)
        install_efi_binary(layout, args.dry_run)
        if not args.no_snapper:
            configure_snapper(args.dry_run)
        write_limine_conf(layout, args, args.dry_run)
        set_boot_order(layout, args.dry_run)
    except SetupError as exc:
        err(str(exc))
        return 1

    print()
    highlight("=" * 50)
    highlight("  Limine + Snapshot Setup Complete!")
    highlight("=" * 50)
    print()
    info(f"ESP:   {layout.esp_mount} ({layout.esp_disk.part_dev(layout.esp_part)})")
    info(f"Root:  {layout.root_dev} [{layout.root_fstype}]")
    info(f"Config: {os.path.join(layout.esp_mount, 'limine.conf')}")
    info("Reboot to use Limine; select 'Snapshots' in the boot menu to roll back.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
