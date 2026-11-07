#!/usr/bin/env python3
# blackarch:summary=One installer for the hacking lab (boxes, VMs, tools)
"""
blackarch-hackinglab-setup.py -- one installer for the hacking lab.

Consolidates the separate launchers in bin/ behind a single selector:

    blackarch-hackinglab-beeBox                      Bee-Box (bWAPP in a box)
    blackarch-hackinglab-metasploitable2             Metasploitable 2 (Linux)
    blackarch-hackinglab-metasploitable3             Metasploitable 3 (Vagrant)
    blackarch-hackinglab-vple                        VPLE
    blackarch-hackinglab-vWapp                       bWAPP
    blackarch-hackinglab-install-virtualbox          VirtualBox host + kernel module
    blackarch-hackingtool-penelope                    Penelope shell handler
    blackarch-launch-hackingTools                    desktop menu entry

Every lab VM is driven through VBoxManage against a VM that already exists, so
nothing here guesses a device or a partition. VM names are resolved from the
hypervisor, not hardcoded.

Usage:
    blackarch-hackinglab-setup.py --list
    blackarch-hackinglab-setup.py --status
    blackarch-hackinglab-setup.py --select
    blackarch-hackinglab-setup.py --install metasploitable2 penelope
    blackarch-hackinglab-setup.py --install penelope --launch
    blackarch-hackinglab-setup.py --install all --yes

Notes:
    * ``--install`` on its own only provisions the host (packages, groups, kernel
      module). Lab VMs are never downloaded or registered implicitly -- they are
      large and each one is a deliberate choice.
    * The download helpers query SourceForge's mirror redirect rather than
      guessing a URL, because the file name is not stable across releases.
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
from pathlib import Path
from typing import Callable, Iterable, Sequence

# ── Palette ─────────────────────────────────────────────────────────────────
C_RED, C_GRN, C_YEL = "\033[0;31m", "\033[0;32m", "\033[1;33m"
C_BLU, C_DIM, C_RST = "\033[0;34m", "\033[2m", "\033[0m"


def info(msg: str) -> None:
    print(f"{C_GRN}[+]{C_RST} {msg}")


def warn(msg: str) -> None:
    print(f"{C_YEL}[!]{C_RST} {msg}")


def err(msg: str) -> None:
    print(f"{C_RED}[x]{C_RST} {msg}", file=sys.stderr)


def step(msg: str) -> None:
    print(f"\n{C_BLU}=== {msg} ==={C_RST}")


def die(msg: str, code: int = 1) -> None:
    err(msg)
    raise SystemExit(code)


def hr(title: str) -> None:
    print(f"\n{C_BLU}{'─' * 66}{C_RST}")
    print(f"{C_BLU}  {title}{C_RST}")
    print(f"{C_BLU}{'─' * 66}{C_RST}")


# ── Command helpers ─────────────────────────────────────────────────────────
def run(argv: Sequence[str], *, check: bool = False, input_text: str | None = None,
        **kw) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        list(argv), input=input_text, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, **kw,
    )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, list(argv), proc.stdout)
    return proc


def quiet(argv: Sequence[str], **kw) -> bool:
    try:
        return run(argv, **kw).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def out(argv: Sequence[str], **kw) -> str:
    """stdout with trailing whitespace stripped — matches shell $(...) semantics."""
    try:
        return run(argv, **kw).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def lines(argv: Sequence[str], **kw) -> list[str]:
    try:
        return run(argv, **kw).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


def which(prog: str) -> bool:
    return shutil.which(prog) is not None


def is_root() -> bool:
    return os.geteuid() == 0


def desktop_user() -> str:
    """The user who owns the desktop session (SUDO_USER first, then seat0)."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        return sudo_user
    for line in out(["loginctl", "list-sessions", "--no-legend"]).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3] == "seat0":
            return parts[2]
    return os.environ.get("USER", "black")


# ── Hypervisor helpers ──────────────────────────────────────────────────────
VBOX_DIR_CANDIDATES = (
    "/virtualbox",
    Path.home() / "VirtualBox VMs",
    Path.home() / "vms",
)


def vm_list() -> list[str]:
    """VM names registered with the hypervisor (empty when it is unavailable)."""
    raw = out(["VBoxManage", "list", "vms"])
    return re.findall(r'^"(.+?)"', raw, re.MULTILINE)


def vm_exists(name: str) -> bool:
    return name in vm_list()


def vm_running(name: str) -> bool:
    raw = out(["VBoxManage", "list", "runningvms"])
    return name in re.findall(r'^"(.+?)"', raw, re.MULTILINE)


def vm_info(name: str) -> dict:
    """Parse `VBoxManage showvminfo --machinereadable` into a flat dict.

    The output quotes every key as well as every value ("SATA-0-0"="..."), so
    both sides are stripped — keying on the raw line would silently match nothing.
    """
    data: dict[str, str] = {}
    for line in lines(["VBoxManage", "showvminfo", name, "--machinereadable"]):
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip().strip('"')] = value.strip().strip('"')
    return data


def vm_find_vmdk(name: str) -> str:
    """Locate a VM's virtual disk, wherever it actually lives."""
    info_map = vm_info(name)
    for key, value in info_map.items():
        if not re.match(r"^(SATA|IDE|NVMe|SCSI|SAS)-\d", key):
            continue
        # Skip the UUID bookkeeping entries; only the image path is interesting.
        if "UUID" in key or "hot-pluggable" in key or "rotational" in key \
                or "discard" in key or "nonrotational" in key:
            continue
        if value.endswith((".vmdk", ".vdi", ".qcow2", ".vhd")) and os.path.exists(value):
            return value
    # Fall back to the conventional location for a VM this script created.
    for base in VBOX_DIR_CANDIDATES:
        for candidate in Path(base).glob(f"{name}/**/*.vmdk"):
            return str(candidate)
    return ""


def vm_register(name: str, ostype: str = "Linux_64") -> bool:
    if vm_exists(name):
        info(f"VM '{name}' already registered")
        return True
    if not which("VBoxManage"):
        warn("VBoxManage is not installed — install the virtualbox tool first")
        return False
    if not quiet(["VBoxManage", "createvm", "--name", name, "--ostype", ostype, "--register"]):
        err(f"Could not register VM '{name}'")
        return False
    info(f"Registered VM '{name}' ({ostype})")
    return True


def vm_configure(name: str, *, memory: int = 1024) -> None:
    """Apply the settings every lab VM needs. Idempotent."""
    settings = (
        ["VBoxManage", "modifyvm", name, "--memory", str(memory),
         "--acpi", "on", "--boot1", "disk", "--nic1", "nat"],
    )
    for argv in settings:
        if not quiet(argv):
            warn(f"modifyvm failed: {' '.join(argv[3:])}")
            return
    info(f"Configured '{name}' (memory {memory} MB, NAT, boot from disk)")


def vm_attach_disk(name: str, vmdk: str) -> bool:
    if not vmdk:
        warn("No virtual disk given")
        return False
    if not os.path.exists(vmdk):
        die(f"Virtual disk not found: {vmdk}")
    if vm_info(name).get("SATA-0-0", "") == vmdk:
        info("Disk already attached")
        return True
    quiet(["VBoxManage", "storagectl", name, "--name", "SATA Controller",
           "--add", "sata", "--controller", "IntelAhci"])
    if not quiet(["VBoxManage", "storageattach", name, "--storagectl",
                  "SATA Controller", "--port", "0", "--device", "0", "--type",
                  "hdd", "--medium", vmdk]):
        err(f"Could not attach {vmdk}")
        return False
    info(f"Attached {vmdk}")
    return True


def vm_start(name: str, *, headless: bool = True) -> bool:
    if vm_running(name):
        info(f"'{name}' is already running")
        return True
    mode = "headless" if headless else "gui"
    if not quiet(["VBoxManage", "startvm", name, "--type", mode]):
        err(f"Could not start '{name}'")
        return False
    info(f"Started '{name}' ({mode})")
    return True


def vm_unregister(name: str) -> bool:
    if not vm_exists(name):
        info(f"VM '{name}' is not registered")
        return True
    quiet(["VBoxManage", "controlvm", name, "poweroff"])
    if not quiet(["VBoxManage", "unregistervm", name, "--delete"]):
        err(f"Could not remove '{name}'")
        return False
    info(f"Removed VM '{name}'")
    return True


# ── Download helpers ────────────────────────────────────────────────────────
def sourceforge_download_url(project: str, *, latest: bool = False) -> str:
    """Resolve a SourceForge download URL through its mirror redirect.

    The file name is not stable across releases, so the landing page is parsed
    rather than the URL guessed.
    """
    slug = f"{project}/files/latest/download" if latest else project
    url = f"https://sourceforge.net/projects/{slug}"
    page = out(["curl", "-sSL", url])
    match = re.search(r'href="(https://sourceforge\.net/projects/[^"]*?download[^"]*)"', page)
    if match:
        return match.group(1)
    match = re.search(r'(https://[^"]*?download[^"]*)', page)
    return match.group(1) if match else ""


def download(url: str, dest: Path, *, tool: str = "aria2c") -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not url:
        warn("No download URL resolved")
        return False
    info(f"Downloading {url}")
    if tool == "aria2c" and which("aria2c"):
        proc = run(["aria2c", "-c", "-x", "8", "-s", "8", "-d", str(dest.parent),
                    "-o", dest.name, url])
    else:
        proc = run(["curl", "-fSL", "-C", "-", "-o", str(dest), url])
    if proc.returncode != 0:
        err("Download failed")
        return False
    info(f"Saved {dest}")
    return True


def extract(archive: Path, dest: Path) -> bool:
    """Extract a .zip/.7z archive, using whichever tool is present."""
    dest.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    if suffix == ".zip" and which("unzip"):
        ok = quiet(["unzip", "-o", "-q", str(archive), "-d", str(dest)])
    elif suffix == ".7z" and which("7z"):
        ok = quiet(["7z", "x", "-y", f"-o{dest}", str(archive)])
    else:
        warn(f"No extractor for {suffix} (need unzip or 7z)")
        return False
    if not ok:
        err(f"Extraction failed for {archive}")
        return False
    info(f"Extracted {archive} -> {dest}")
    return True


# ── Tool definitions ────────────────────────────────────────────────────────
@dataclass
class Tool:
    """One installable unit."""

    key: str
    label: str
    description: str
    kind: str                      # "host" | "lab" | "app"
    needs_root: bool = True
    needs_vm: bool = False
    vm_name: str = ""
    packages: tuple[str, ...] = ()
    post: tuple[str, ...] = ()     # shell snippets run after install
    install: Callable[["Ctx"], bool] | None = None
    launch: Callable[["Ctx"], bool] | None = None

    @property
    def id(self) -> str:
        return self.key


@dataclass
class Ctx:
    """Shared runtime state passed to every tool handler."""

    yes: bool = False
    dry_run: bool = False
    verbose: bool = False
    selected: list[str] = field(default_factory=list)
    results: dict[str, bool] = field(default_factory=dict)

    def confirm(self, prompt: str) -> bool:
        if self.yes:
            return True
        try:
            return input(f"{C_YEL}[?]{C_RST} {prompt} [y/N] ").strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print()
            return False


def pkg_install(packages: Iterable[str]) -> bool:
    missing = [p for p in packages if not quiet(["pacman", "-Q", p])]
    if not missing:
        info("All packages already present")
        return True
    info(f"Installing: {' '.join(missing)}")
    if not quiet(["pacman", "-S", "--needed", "--noconfirm", *missing]):
        err("pacman install failed")
        return False
    return True


def group_add(user: str, group: str) -> bool:
    if not quiet(["getent", "group", group]):
        warn(f"Group '{group}' does not exist on this system")
        return False
    if group in out(["id", "-nG", user]).split():
        info(f"{user} already in '{group}'")
        return True
    if not quiet(["usermod", "-aG", group, user]):
        err(f"Could not add {user} to {group}")
        return False
    info(f"Added {user} to '{group}' (effective at next login)")
    return True


# ── Tool handlers ───────────────────────────────────────────────────────────
def install_virtualbox(ctx: Ctx) -> bool:
    """Host-side VirtualBox plus its kernel module."""
    if not which("VBoxManage"):
        if not pkg_install(TOOLS["virtualbox"].packages):
            return False
    else:
        info("VirtualBox host is installed")

    # virtualbox-kvm (chaotic-aur) and virtualbox-host-modules-arch (extra) are
    # alternatives for the kernel module; use whichever the host already has.
    if not quiet(["modinfo", "vboxdrv"]):
        for module_pkg in ("virtualbox-host-modules-arch", "virtualbox-host-dkms"):
            if quiet(["pacman", "-Si", module_pkg]):
                if pkg_install([module_pkg]):
                    break
        else:
            warn("No VirtualBox kernel-module package could be installed")
    else:
        info("vboxdrv kernel module is available")

    user = desktop_user()
    group_add(user, "vboxusers")

    if quiet(["lsmod"]) and "vboxdrv" not in out(["sh", "-c", "lsmod"]):
        if quiet(["modprobe", "vboxdrv"]):
            info("Loaded vboxdrv")
        else:
            warn("Could not load vboxdrv now — a reboot usually applies it")
    return True


def install_metasploitable2(ctx: Ctx) -> bool:
    """Metasploitable 2 Linux VM."""
    vmdk = str(Path("/virtualbox/Metasploitable2-Linux/Metasploitable.vmdk"))
    if not os.path.exists(vmdk):
        archive = Path.home() / "Downloads/metasploitable-linux-2.0.0.zip"
        if not archive.is_file():
            url = sourceforge_download_url("metasploitable")
            if not url:
                warn("Could not resolve the Metasploitable download URL")
                return False
            if not ctx.confirm(f"Download Metasploitable 2 (~{C_DIM}800 MB{C_RST})?"):
                return False
            if not download(url, archive):
                return False
        if not extract(archive, Path("/virtualbox")):
            return False

    if not vm_register("Metasploitable2"):
        return False
    vm_configure("Metasploitable2", memory=512)
    if not vm_attach_disk("Metasploitable2", vmdk):
        return False
    return vm_start("Metasploitable2")


def install_beebox(ctx: Ctx) -> bool:
    """Bee-Box: bWAPP shipped as a ready-made VM."""
    vmdk = str(Path("/virtualbox/bee-box/bee-box.vmdk"))
    if not os.path.exists(vmdk):
        archive = Path.home() / "Downloads/bee-box_v1.6.7z"
        if not archive.is_file():
            url = sourceforge_download_url("bwapp/files/bee-box/bee-box_v1.6.7z")
            if not url:
                warn("Could not resolve the Bee-Box download URL")
                return False
            if not ctx.confirm("Download Bee-Box (~600 MB)?"):
                return False
            if not download(url, archive):
                return False
        if not extract(archive, Path("/virtualbox")):
            return False
        # The archive nests the disk; find it wherever it landed.
        found = next(Path("/virtualbox").rglob("*.vmdk"), None)
        if found is None:
            warn("Bee-Box extracted but no .vmdk was found under /virtualbox")
            return False
        vmdk = str(found)

    if not vm_register("Bee-Box"):
        return False
    vm_configure("Bee-Box", memory=1024)
    if not vm_attach_disk("Bee-Box", vmdk):
        return False
    return vm_start("Bee-Box")


def install_vwapp(ctx: Ctx) -> bool:
    """bWAPP (the LAMP-style web app) as a VM."""
    vmdk = str(Path("/virtualbox/bwapp/bwapp.vmdk"))
    if not os.path.exists(vmdk):
        archive = Path.home() / "Downloads/bwapp.zip"
        if not archive.is_file():
            url = sourceforge_download_url("bwapp", latest=True)
            if not url:
                warn("Could not resolve the bWAPP download URL")
                return False
            if not ctx.confirm("Download bWAPP (~300 MB)?"):
                return False
            if not download(url, archive):
                return False
        if not extract(archive, Path("/virtualbox")):
            return False
        found = next(Path("/virtualbox").rglob("*.vmdk"), None)
        if found is None:
            warn("bWAPP extracted but no .vmdk was found under /virtualbox")
            return False
        vmdk = str(found)

    if not vm_register("bWAPP"):
        return False
    vm_configure("bWAPP", memory=1024)
    if not vm_attach_disk("bWAPP", vmdk):
        return False
    return vm_start("bWAPP")


def install_vple(ctx: Ctx) -> bool:
    """VPLE (Vulnerable Pentestly Linux by Pentestly Academy)."""
    vmdk = str(Path("/virtualbox/VPLE/VPLE.vmdk"))
    if not os.path.exists(vmdk):
        archive = Path.home() / "Downloads/VPLE.zip"
        if not archive.is_file():
            url = sourceforge_download_url("vple", latest=True)
            if not url:
                warn("Could not resolve the VPLE download URL")
                return False
            if not ctx.confirm("Download VPLE (~2 GB)?"):
                return False
            if not download(url, archive):
                return False
        if not extract(archive, Path("/virtualbox")):
            return False
        found = next(Path("/virtualbox").rglob("*.vmdk"), None)
        if found is None:
            warn("VPLE extracted but no .vmdk was found under /virtualbox")
            return False
        vmdk = str(found)

    if not vm_register("VPLE"):
        return False
    vm_configure("VPLE", memory=2048)
    if not vm_attach_disk("VPLE", vmdk):
        return False
    return vm_start("VPLE")


def install_metasploitable3(ctx: Ctx) -> bool:
    """Metasploitable 3, which ships as a Vagrant box rather than a disk image."""
    if not which("vagrant"):
        warn("Metasploitable 3 needs Vagrant; install it first:")
        warn("  sudo pacman -S vagrant")
        return False
    workdir = Path("/virtualbox/metasploitable3-workspace")
    workdir.mkdir(parents=True, exist_ok=True)
    vagrantfile = workdir / "Vagrantfile"
    if not vagrantfile.is_file():
        info("Fetching the Metasploitable 3 Vagrantfile")
        if not quiet(["curl", "-fsSL", "-o", str(vagrantfile),
                      "https://raw.githubusercontent.com/rapid7/metasploitable3/"
                      "master/Vagrantfile"]):
            err("Could not fetch the Vagrantfile")
            return False
    info("Running 'vagrant up' (this downloads a large box — first run is slow)")
    proc = run(["vagrant", "up"], cwd=workdir)
    if proc.returncode != 0:
        err("vagrant up failed")
        return False
    info("Metasploitable 3 is up")
    return True


def install_penelope(ctx: Ctx) -> bool:
    """Penelope shell handler — a bundled script, no package needed.

    The probe here deliberately runs as the DESKTOP user, not root. Penelope is a
    TTY app (it calls termios.tcgetattr at import), so it cannot be smoke-tested
    without a terminal, and running it as root would create a root-owned
    ~/.penelope that then blocks the desktop user from ever starting it.
    """
    bundled = Path("/opt/blackarch/bin/blackarch-hackingtool-penelope")
    installed = PENELOPE_INSTALL_PATH
    if not bundled.is_file():
        warn(f"Bundled script not found: {bundled}")
        return False
    if not installed.is_file():
        if is_root():
            shutil.copy2(bundled, installed)
            os.chmod(installed, 0o755)
        else:
            if not quiet(["install", "-m", "755", str(bundled), str(installed)]):
                err(f"Could not install {installed}")
                return False
        info(f"Installed {installed}")
    else:
        info(f"{installed} is already present (version {penelope_version(installed) or 'unknown'})")
        info("Use --penelope-from upstream|main to fetch a different version")
    return _finish_penelope(ctx)


def penelope_version(path: Path | None = None) -> str:
    """Version declared inside the script (its __version__ constant).

    Parsed out of the source rather than by running it: Penelope needs a TTY, so
    executing it to read a version would fail for reasons unrelated to the
    version itself.
    """
    target = path or Path("/usr/local/bin/penelope")
    if not target.is_file():
        return ""
    try:
        match = re.search(r'__version__\s*=\s*"([^"]+)"',
                          target.read_text(errors="replace"))
    except OSError:
        return ""
    return match.group(1) if match else ""


def penelope_source_version(url: str) -> str:
    """Version declared in a remote copy of the script."""
    text = out(["curl", "-fsSL", url])
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else ""


def fetch_penelope(url: str, dest: Path) -> bool:
    """Fetch a Penelope script from the internet into place."""
    if not url:
        warn("No URL given")
        return False
    info(f"Fetching {url}")
    if not quiet(["curl", "-fsSL", "--fail", "-o", str(dest), url]):
        err("Download failed")
        return False
    os.chmod(dest, 0o755)
    info(f"Installed {dest} (version {penelope_version(dest) or 'unknown'})")
    return True


# ── Penelope ────────────────────────────────────────────────────────────────
PENELOPE_REPO = "https://github.com/brightio/penelope"
PENELOPE_RAW_MAIN = f"{PENELOPE_REPO}/raw/refs/heads/main/penelope.py"
PENELOPE_RAW_TAG = f"{PENELOPE_REPO}/raw/refs/tags"
PENELOPE_INSTALL_PATH = Path("/usr/local/bin/penelope")


def latest_penelope_tag() -> str:
    """Newest release tag upstream (tags are unordered, so sort by version)."""
    tags = []
    for line in out(["git", "ls-remote", "--tags", "--refs", PENELOPE_REPO]).splitlines():
        ref = line.split()[-1] if line.split() else ""
        tag = ref.rsplit("/", 1)[-1]
        if tag.startswith("v") and tag[1:].replace(".", "").isdigit():
            tags.append(tag)
    def key(tag: str) -> tuple:
        return tuple(int(p) for p in tag[1:].split("."))
    return sorted(tags, key=key)[-1] if tags else ""


def penelope_install(ctx: Ctx, source: str = "upstream") -> bool:
    """Install Penelope from the internet.

    Sources:
      upstream  latest release tag (default, stable)
      main      the moving head of the default branch (bleeding edge)
      bundled   the copy shipped in bin/
    """
    if source == "bundled":
        return install_penelope(ctx)
    if source == "main":
        url = PENELOPE_RAW_MAIN
    else:
        tag = latest_penelope_tag()
        if not tag:
            warn("Could not determine the latest upstream tag — falling back to main")
            url = PENELOPE_RAW_MAIN
        else:
            url = f"{PENELOPE_RAW_TAG}/{tag}/penelope.py"
    info(f"Penelope source: {source} -> {url}")
    if not is_root():
        die("Root required to install into /usr/local/bin: sudo ...")
    if not fetch_penelope(url, PENELOPE_INSTALL_PATH):
        return False
    return _finish_penelope(ctx)


def penelope_update(ctx: Ctx, source: str = "upstream") -> bool:
    """Update Penelope in place, refusing to silently downgrade."""
    installed = PENELOPE_INSTALL_PATH
    current = penelope_version(installed)
    if not current:
        warn(f"{installed} is missing or has no readable version — install it first")
        return False

    if source == "main":
        url = PENELOPE_RAW_MAIN
    else:
        tag = latest_penelope_tag()
        if not tag:
            warn("Could not determine the latest upstream tag")
            return False
        url = f"{PENELOPE_RAW_TAG}/{tag}/penelope.py"

    remote = penelope_source_version(url)
    if not remote:
        warn(f"Could not read the version at {url}")
        return False
    info(f"Installed: {current}   Upstream: {remote}")
    if remote == current:
        info("Already up to date")
        return True
    if _version_tuple(remote) < _version_tuple(current):
        warn(f"Upstream {remote} is OLDER than installed {current} — refusing to downgrade")
        warn("  pass a specific tag or 'main' if you really want it")
        return False

    # Fetch to a temp file first: a truncated download must not replace a
    # working install.
    tmp = installed.with_suffix(".new")
    if not quiet(["curl", "-fsSL", "--fail", "-o", str(tmp), url]):
        err("Download failed — installed copy left untouched")
        return False
    if not tmp.is_file() or tmp.stat().st_size == 0:
        err("Downloaded file is empty — installed copy left untouched")
        tmp.unlink(missing_ok=True)
        return False
    os.chmod(tmp, 0o755)
    try:
        os.replace(tmp, installed)
    except OSError as exc:
        err(f"Could not replace {installed}: {exc}")
        tmp.unlink(missing_ok=True)
        return False
    info(f"Updated {installed} -> {remote}")
    return _finish_penelope(ctx)


def _version_tuple(version: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:3]) or (0, 0, 0)


def _finish_penelope(ctx: Ctx) -> bool:
    """Shared post-install checks: config dir ownership and a startup probe."""
    # Make sure a stale root-owned config dir cannot wedge the desktop user.
    user = desktop_user()
    stale = Path(f"/home/{user}/.penelope")
    if stale.is_dir():
        owner = out(["stat", "-c", "%U", str(stale)])
        if owner and owner != user:
            warn(f"{stale} is owned by {owner}, not {user} — Penelope will not start")
            warn(f"  fix: sudo chown -R {user}:{user} {stale}")
        else:
            info(f"{stale} is writable by {user}")
    else:
        info(f"{stale} will be created by Penelope on first run")

    # --version only sets a flag; the tool then blocks on the terminal, so a
    # timeout bounds it and neither 0 nor 124 counts as a failure.
    probe = subprocess.run(["timeout", "5", "penelope", "--version"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    started = bool(probe.stdout.strip()) or probe.returncode in (0, 124)
    if started:
        info(f"penelope {penelope_version() or '?'} is ready (needs a TTY to run)")
    else:
        warn(f"penelope failed to start (exit {probe.returncode})")
        warn(f"  {probe.stdout.strip()[:200]}")
        return False
    return True


def launch_penelope(ctx: Ctx) -> bool:
    """Start a Penelope listener in a terminal."""
    if not which("penelope"):
        warn("penelope is not on PATH — install it with --install penelope")
        return False
    proc = run(["penelope", "-l"])
    if proc.returncode != 0:
        err(proc.stdout)
        return False
    info("Penelope started")
    return True


def install_launch_menu(ctx: Ctx) -> bool:
    """Regenerate the desktop 'Hacking Tools' menu entry."""
    launcher = Path("/opt/blackarch/bin/blackarch-launch-hackingTools")
    if not launcher.is_file():
        warn(f"Launcher not found: {launcher}")
        return False
    info("Regenerating the Hacking Tools menu")
    proc = run(["bash", str(launcher), "menu"])
    if proc.returncode != 0:
        err("Menu generation failed")
        return False
    dest = Path("/opt/blackarch/default/blackarch/additional-menu.jsonc")
    info(f"Menu written to {dest}")
    return True


TOOLS: dict[str, Tool] = {
    "virtualbox": Tool(
        key="virtualbox",
        label="VirtualBox host",
        description="VirtualBox + kernel module + vboxusers membership (needed by every lab VM)",
        kind="host",
        packages=("virtualbox",),
        install=install_virtualbox,
    ),
    "metasploitable2": Tool(
        key="metasploitable2",
        label="Metasploitable 2",
        description="Deliberately vulnerable Linux VM (Ubuntu 8.04, lots of services)",
        kind="lab",
        needs_vm=True,
        vm_name="Metasploitable2",
        install=install_metasploitable2,
    ),
    "metasploitable3": Tool(
        key="metasploitable3",
        label="Metasploitable 3",
        description="Vulnerable Windows 2008 VM, delivered as a Vagrant box",
        kind="lab",
        needs_vm=True,
        vm_name="Metasploitable3",
        install=install_metasploitable3,
    ),
    "beebox": Tool(
        key="beebox",
        label="Bee-Box",
        description="bWAPP bundled as a ready-made VM (Bee-Box v1.6)",
        kind="lab",
        needs_vm=True,
        vm_name="Bee-Box",
        install=install_beebox,
    ),
    "vwapp": Tool(
        key="vwapp",
        label="bWAPP",
        description="bWAPP web app — bugs ranging from XSS to SQL injection and RCE",
        kind="lab",
        needs_vm=True,
        vm_name="bWAPP",
        install=install_vwapp,
    ),
    "vple": Tool(
        key="vple",
        label="VPLE",
        description="Vulnerable Pentestly Linux — a large CTF-style target (~2 GB)",
        kind="lab",
        needs_vm=True,
        vm_name="VPLE",
        install=install_vple,
    ),
    "penelope": Tool(
        key="penelope",
        label="Penelope",
        description="Shell handler — bindshells, reverse shells, payloads, file server",
        kind="app",
        needs_root=False,
        install=install_penelope,
        launch=launch_penelope,
    ),
    "launch": Tool(
        key="launch",
        label="Hacking Tools menu",
        description="Regenerate the desktop 'Hacking Tools' menu from the cyber-toolkit roles",
        kind="app",
        needs_root=False,
        install=install_launch_menu,
    ),
}

LAB_TOOLS = tuple(k for k, t in TOOLS.items() if t.kind == "lab")
HOST_TOOLS = ("virtualbox",)

# Tools that can be refreshed in place. Everything else is either a VM image
# (which would have to be re-downloaded whole) or a package (handled by pacman).
UPDATABLE: dict[str, Callable[[Ctx, str], bool]] = {
    "penelope": penelope_update,
}


# ── Selection helpers ───────────────────────────────────────────────────────
def resolve_selection(requested: Sequence[str]) -> list[str]:
    """Expand aliases and validate keys; unknown names abort loudly."""
    if not requested:
        return []
    expanded: list[str] = []
    for name in requested:
        key = name.lower().strip()
        if key in ("all", "labs", "everything"):
            expanded.extend(TOOLS)
        elif key in ("vulnhubs", "vuln"):
            expanded.extend(LAB_TOOLS)
        elif key in TOOLS:
            expanded.append(key)
        else:
            die(f"Unknown tool '{name}'. Run --list to see what is available.")
    # De-duplicate, keep first-seen order.
    seen, result = set(), []
    for key in expanded:
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def dependency_order(keys: Sequence[str]) -> list[str]:
    """Install the VirtualBox host before any VM that needs it."""
    ordered = []
    for key in keys:
        if TOOLS[key].needs_vm and "virtualbox" not in ordered and "virtualbox" in TOOLS:
            ordered.append("virtualbox")
        if key not in ordered:
            ordered.append(key)
    return ordered


def print_list() -> None:
    hr("Available tools")
    for kind, title in (("host", "Host prerequisites"),
                        ("lab", "Lab VMs"),
                        ("app", "Applications")):
        print(f"\n{C_BLU}{title}{C_RST}")
        for key, tool in TOOLS.items():
            if tool.kind != kind:
                continue
            vm = f"  {C_DIM}[VM: {tool.vm_name}]{C_RST}" if tool.needs_vm else ""
            print(f"  {C_GRN}{key:<16}{C_RST} {tool.label}{vm}")
            print(f"  {'':<16} {C_DIM}{tool.description}{C_RST}")
    print()
    print(f"{C_DIM}Examples:{C_RST}")
    print(f"  {sys.argv[0]} --list")
    print(f"  {sys.argv[0]} --install metasploitable2 penelope")
    print(f"  {sys.argv[0]} --install vulnhubs --yes")
    print(f"  {sys.argv[0]} --penelope-from upstream   # install from the internet")
    print(f"  {sys.argv[0]} --update penelope          # refresh it")
    print()


# ── Status ──────────────────────────────────────────────────────────────────
def tool_status(tool: Tool) -> tuple[bool, str]:
    """(installed, detail) for one tool."""
    if tool.key == "virtualbox":
        if which("VBoxManage"):
            return True, "installed"
        return False, "not installed"
    if tool.key == "metasploitable3":
        if which("vagrant"):
            return True, "vagrant available"
        return False, "vagrant missing"
    if tool.key == "penelope":
        if not which("penelope"):
            return False, "not on PATH"
        installed = penelope_version()
        tag = latest_penelope_tag()
        remote = penelope_source_version(
            f"{PENELOPE_RAW_TAG}/{tag}/penelope.py") if tag else ""
        if not remote:
            return True, f"{installed or 'version unknown'}"
        if installed == remote:
            return True, f"{installed} (up to date)"
        if _version_tuple(installed or "0") < _version_tuple(remote):
            return True, f"{installed} -> {remote} available"
        return True, f"{installed} (newer than upstream {remote})"
    if tool.key == "launch":
        dest = Path("/opt/blackarch/default/blackarch/"
                    "additional-menu.jsonc")
        return dest.is_file(), str(dest)
    if tool.needs_vm and tool.vm_name:
        if vm_exists(tool.vm_name):
            if vm_running(tool.vm_name):
                return True, f"{tool.vm_name} registered, running"
            return True, f"{tool.vm_name} registered, stopped"
        return False, f"no VM named '{tool.vm_name}'"
    return False, "unknown"


def print_status() -> None:
    hr("Tool status")
    for key, tool in TOOLS.items():
        ok, detail = tool_status(tool)
        mark = f"{C_GRN}yes{C_RST}" if ok else f"{C_YEL}no{C_RST}"
        print(f"  {key:<16} {mark}  {detail}")
    print()
    if which("VBoxManage"):
        vms = vm_list()
        print(f"  Registered VMs ({len(vms)}): {', '.join(vms) if vms else C_DIM + 'none' + C_RST}")
        running = [v for v in vms if vm_running(v)]
        print(f"  Running VMs ({len(running)}): {', '.join(running) if running else C_DIM + 'none' + C_RST}")
    else:
        print(f"  {C_YEL}VirtualBox is not installed — no VMs can be listed{C_RST}")
    print()


# ── Interactive selector ────────────────────────────────────────────────────
def interactive_select() -> list[str]:
    """Numbered checklist; comma-separated numbers and ranges are accepted."""
    keys = list(TOOLS)
    hr("Select tools to install")
    for index, key in enumerate(keys, start=1):
        tool = TOOLS[key]
        ok, detail = tool_status(tool)
        mark = f"{C_GRN}✓{C_RST}" if ok else f"{C_YEL}○{C_RST}"
        vm = f"  {C_DIM}[{tool.vm_name}]{C_RST}" if tool.needs_vm else ""
        print(f"  {mark} {index:>2}. {C_GRN}{key:<16}{C_RST} {tool.label}{vm}")
        print(f"        {C_DIM}{tool.description}{C_RST}")
    print()
    print(f"{C_DIM}Enter numbers, ranges or names: 1,3,5-7   (blank = all lab VMs){C_RST}")

    try:
        answer = input(f"{C_BLU}[?]{C_RST} Selection: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []

    if not answer:
        return list(LAB_TOOLS)

    chosen: list[str] = []
    for token in re.split(r"[,\s]+", answer):
        token = token.strip()
        if not token:
            continue
        if token.isdigit() and 1 <= int(token) <= len(keys):
            chosen.append(keys[int(token) - 1])
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if 1 <= start <= end <= len(keys):
                chosen.extend(keys[start - 1:end])
                continue
        if token.lower() in TOOLS:
            chosen.append(token.lower())
        else:
            warn(f"Ignoring unknown selection '{token}'")

    seen, result = set(), []
    for key in chosen:
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


# ── Install driver ──────────────────────────────────────────────────────────
def install_tools(ctx: Ctx, keys: Sequence[str]) -> int:
    if not keys:
        warn("Nothing selected")
        return 1
    ordered = dependency_order(keys)
    # The VirtualBox host is injected into the order for VM tools, so its root
    # requirement has to be checked after ordering, not against the raw selection.
    if not ctx.dry_run and not is_root() and any(TOOLS[k].needs_root for k in ordered):
        die("Root required for the selected tools: sudo blackarch-hackinglab-setup.py ...")

    if ordered != list(keys):
        info(f"Install order: {' → '.join(ordered)}")

    step(f"Installing {len(ordered)} tool(s)")
    failures = 0
    for key in ordered:
        tool = TOOLS[key]
        hr(f"{tool.label}  ({key})")
        if ctx.dry_run:
            info(f"Would install: {key}")
            ctx.results[key] = True
            continue
        try:
            ok = tool.install(ctx) if tool.install else False
        except SystemExit:
            raise
        except Exception as exc:                     # noqa: BLE001 - report and continue
            err(f"Unexpected error in {key}: {exc}")
            ok = False
        ctx.results[key] = bool(ok)
        if not ok:
            failures += 1
            warn(f"{key}: NOT installed")
        else:
            info(f"{key}: done")

    print()
    hr("Summary")
    for key in ordered:
        mark = f"{C_GRN}ok{C_RST}" if ctx.results.get(key) else f"{C_RED}failed{C_RST}"
        print(f"  {key:<18} {mark}")
    print()
    if failures:
        warn(f"{failures} of {len(ordered)} tool(s) failed")
        return 1
    info("All selected tools installed")
    return 0


def launch_tools(ctx: Ctx, keys: Sequence[str]) -> int:
    """Run the launch handler for tools that have one."""
    launched = 0
    for key in keys:
        tool = TOOLS.get(key)
        if tool is None or tool.launch is None:
            continue
        hr(f"Launching {tool.label}")
        if tool.launch(ctx):
            launched += 1
    return 0 if launched else 1


def update_tools(ctx: Ctx, keys: Sequence[str], source: str = "upstream") -> int:
    """Update updatable tools in place. Penelope is the only one today."""
    if not keys:
        warn("Nothing to update")
        return 1
    if not ctx.dry_run and not is_root():
        die("Root required: sudo blackarch-hackinglab-setup.py --update ...")

    unknown = [k for k in keys if k not in UPDATABLE]
    if unknown:
        warn(f"Nothing to update for: {', '.join(unknown)}")
        warn(f"Updatable tools: {', '.join(sorted(UPDATABLE))}")
        return 1

    rc = 0
    for index, key in enumerate(keys):
        # One banner per tool: no bare step() heading, so the output never
        # contains an empty section.
        if index == 0:
            hr(f"Updating {', '.join(keys)}")
        hr(TOOLS[key].label if key in TOOLS else key)
        if ctx.dry_run:
            info(f"Would update: {key}")
            continue
        if not UPDATABLE[key](ctx, source):
            warn(f"{key}: update failed")
            rc = 1
        else:
            info(f"{key}: updated")
    return rc


def remove_tools(ctx: Ctx, keys: Sequence[str]) -> int:
    """Unregister lab VMs and drop the penelope install."""
    if not keys:
        warn("Nothing selected")
        return 1
    if not ctx.dry_run and not is_root():
        die("Root required: sudo blackarch-hackinglab-setup.py --remove ...")
    for key in keys:
        tool = TOOLS[key]
        if tool.needs_vm and tool.vm_name:
            vm_unregister(tool.vm_name)
        elif key == "penelope":
            target = Path("/usr/local/bin/penelope")
            if target.is_file():
                target.unlink()
                info(f"Removed {target}")
        else:
            warn(f"Nothing to remove for '{key}' (packages are left in place)")
    return 0


# ── Options ─────────────────────────────────────────────────────────────────
def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="blackarch-hackinglab-setup",
        description="Install and manage the hacking lab: vulnerable VMs, "
                    "VirtualBox, and helper tools.",
    )
    p.add_argument("--list", action="store_true",
                   help="list every available tool")
    p.add_argument("--status", action="store_true",
                   help="show install state for each tool and list VMs")
    p.add_argument("--select", action="store_true",
                   help="interactive checklist to choose what to install")
    p.add_argument("--install", nargs="+", metavar="TOOL", default=None,
                   help="install the named tools (names, 'vulnhubs', or 'all')")
    p.add_argument("--remove", nargs="+", metavar="TOOL", default=None,
                   help="unregister lab VMs / remove the penelope install")
    p.add_argument("--launch", action="store_true",
                   help="launch the tools named by --install (e.g. penelope)")
    p.add_argument("--penelope-from", choices=("upstream", "main", "bundled"),
                   default=None, metavar="SOURCE",
                   help="install Penelope from the internet (upstream release, "
                        "bleeding-edge main) or from the bundled copy")
    p.add_argument("--update", nargs="+", metavar="TOOL", default=None,
                   help="update tools in place (currently only 'penelope')")
    p.add_argument("--update-from", choices=("upstream", "main"),
                   default="upstream", metavar="SOURCE",
                   help="source for --update penelope (default: upstream release)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="answer every prompt with yes")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be done, change nothing")
    p.add_argument("--json", action="store_true",
                   help="machine-readable status output")
    return p.parse_args(argv)


def print_json_status() -> None:
    # Probe each tool once: tool_status() runs its own commands, so calling it
    # twice per tool here would double every VBoxManage invocation.
    statuses = {k: tool_status(t) for k, t in TOOLS.items()}
    vms = vm_list()
    payload = {
        "virtualbox": which("VBoxManage"),
        "vms": vms,
        "running": [v for v in vms if vm_running(v)],
        "tools": {k: {"installed": ok, "detail": detail}
                  for k, (ok, detail) in statuses.items()},
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


# ── Main ────────────────────────────────────────────────────────────────────
def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.json:
        print_json_status()
        return 0
    if args.list:
        print_list()
        return 0
    if args.status:
        print_status()
        return 0

    ctx = Ctx(yes=args.yes, dry_run=args.dry_run)

    if args.remove:
        return remove_tools(ctx, resolve_selection(args.remove))

    if args.update:
        return update_tools(ctx, args.update, args.update_from)

    if args.penelope_from:
        return 0 if penelope_install(ctx, args.penelope_from) else 1

    if args.install:
        keys = resolve_selection(args.install)
        rc = install_tools(ctx, keys)
        if rc == 0 and args.launch and not ctx.dry_run:
            launch_tools(ctx, keys)
        return rc

    if args.select:
        chosen = interactive_select()
        if not chosen:
            info("Nothing selected")
            return 0
        return install_tools(ctx, chosen)

    # No action given: show the status table, then offer the checklist.
    print_status()
    try:
        if input(f"\n{C_BLU}[?]{C_RST} Run the interactive selector? [y/N] ").strip().lower() \
                not in ("y", "yes"):
            print(f"\n{C_DIM}Use --list to see tools, --install <tool> to install.{C_RST}")
            return 0
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    return install_tools(ctx, interactive_select())


if __name__ == "__main__":
    raise SystemExit(main())
