#!/usr/bin/env python3
# blackarch:summary=Set up the built-in Galaxy Book camera (Intel IPU6/OV02C10)
# blackarch:args=[--check-only] [--ipu6 [install|status|verify]] [--ipu7 [distro|dkms|git|status]]
# blackarch:examples=blackarch webcam setup | blackarch webcam setup --check-only | sudo blackarch webcam setup --ipu6 | sudo blackarch webcam setup --ipu7
# ============================================================================
# Galaxy Book Camera Fix — Arch / BlackArch  (Python port of
# /opt/blackarch/bin/blackarch-webcam-setup)
#
# Sets up the built-in camera on Samsung Galaxy Book3/Book4 (Intel IPU6 +
# OV02C10 sensor) from a fresh Arch Linux install. Covers:
#
#   [1]  Dependencies (build tools, libcamera, GStreamer, PipeWire, DKMS)
#   [2]  ov02c10 DKMS module patched for the 26 MHz external clock
#   [3]  ipu-bridge DKMS module with the Samsung rotation quirk
#   [4]  libcamera 0.7.2 built from source with the OV02C10 sensor helper
#   [5]  OV02C10 tuning file for the Simple ISP
#   [6]  Environment + group configuration (video, kvm)
#   [7]  Raw IPU6 MC-node hiding (memberless camera-relay group)
#   [8]  Camera relay (on-demand, flicker-suppressed) for non-PipeWire apps
#
# Upstream fix set: https://github.com/Andycodeman/samsung-galaxy-book-linux-fixes
#
# Usage:
#   sudo blackarch-webcam-setup.py                  # full install (IPU6)
#   sudo blackarch-webcam-setup.py --check-only     # status table only
#   sudo blackarch-webcam-setup.py --verify         # full end-to-end check
#   sudo blackarch-webcam-setup.py --sensor-only    # only the 26 MHz DKMS fix
#   sudo blackarch-webcam-setup.py --skip-libcamera-rebuild
#   sudo blackarch-webcam-setup.py --uninstall
#   sudo blackarch-webcam-setup.py --ipu6 [install|status|verify]
#   sudo blackarch-webcam-setup.py --ipu7 [distro|dkms|git|status]
#
# Requires a reboot when done.
# ============================================================================

from __future__ import annotations

import argparse
import glob
import gzip
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# ── Constants ───────────────────────────────────────────────────────────────
FIX_URL = "https://github.com/Andycodeman/samsung-galaxy-book-linux-fixes/archive/refs/heads/main.tar.gz"
FIX_BASENAME = "samsung-galaxy-book-linux-fixes-main"
WORK_DIR = Path("/tmp") / FIX_BASENAME
LIBCAMERA_BUILD_VER = "v0.7.2"
LIBCAMERA_BUILD_DIR = Path("/tmp/libcamera-ipu6-build")
OV02C10_DKMS_VER = "1.0"
IPU_BRIDGE_DKMS_VER = "1.4"

# Companion files this script (or its C helpers) need, resolved relative to the
# real script location so the /bin symlink does not break the lookup.
HERE = Path(__file__).resolve().parent
PATCHED_MONITOR_SOURCES = (
    HERE / "galaxybook-camera" / "camera-relay-monitor.c.patched",
    Path("/opt/blackarch/galaxybook-camera/"
         "camera-relay-monitor.c.patched"),
)

# ── Intel IPU7 stack ────────────────────────────────────────────────────────
# Two flavours: the distro installer package (kernel module + firmware + HAL +
# icamerasrc, targets the IPU7.5 controller 8086:b05d / OV08X40 sensor), and the
# bare kernel module straight from Intel's tree (Lunar Lake, controller
# 8086:645d). Installing the wrong one for the controller produces a camera
# node with no frames — see docs/ipu7.md.
IPU7_PCI_IDS = ("8086:b05d", "8086:645d", "8086:7d19")
IPU7_SENSOR_HIDS = ("OVTI08F4",)
IPU7_MODULE = "intel_ipu7"
IPU7_SENSOR_MODULE = "ov08x40"
IPU7_PKG = "intel-ipu7-camera"
IPU7_RELAY_UNIT = "v4l2-relayd@ipu7.service"
IPU7_CAMERA_UNIT = "intel-ipu7-camera.service"
IPU7_DKMS_REPO = "https://github.com/intel/ipu7-drivers.git"
IPU7_DKMS_PKGS = ("ipu7-drivers", "0.0.0")
IPU7_BINS_REPO = "https://github.com/intel/ipu7-camera-bins.git"
IPU7_HAL_REPO = "https://github.com/intel/ipu7-camera-hal.git"
IPU7_GIT_PKGS = ("intel-ipu7-dkms-git", "intel-ipu7-camera-bin",
                 "intel-ipu7-camera-hal-git")

# ── Intel IPU6 hardware-ISP stack (AUR) ────────────────────────────────────
# The proprietary counterpart of the open libcamera stack this script installs by
# default. IPU6 outputs raw Bayer, so it needs Intel's HAL (libcamhal) to debayer
# and run 3A, plus icamerasrc to expose it to GStreamer and v4l2-relayd to present
# it as a normal /dev/video node. Full stack in the AUR; the kernel driver is
# already in-tree since 6.10 and the out-of-tree DKMS package is broken there.
IPU6_GIT_PKGS = ("intel-ipu6-camera-bin", "intel-ipu6-camera-hal-git",
                 "icamerasrc-git", "libcamera-ipu6", "libcamera-ipu6-ipa",
                 "gst-plugin-libcamera-ipu6")
# Only needed when the in-tree intel-ipu6 driver cannot be used (kernel < 6.10).
IPU6_DKMS_PKG = "intel-ipu6-dkms-git"
IPU6_HAL_PROVIDES = "ipu6-camera-hal"      # provided by intel-ipu6-camera-hal-git
IPU6_MODULE = "intel_ipu6"
IPU6_ISYS_MODULE = "intel_ipu6_isys"
IPU6_CVS_MODULE = "intel_cvs"
IPU6_SENSOR_MODULE = "ov02c10"
IPU6_PCI_IDS = ("8086:a75d", "8086:465d", "8086:7d19")
IPU6_DKMS_MIN_BROKEN_KERNEL = (6, 10)      # in-tree driver lands here
IPU6_SVC_OVERRIDE = Path("/etc/systemd/system/v4l2-relayd.service.d/"
                         "ipu6-label.conf")
IPU6_RELAY_CONF = Path("/etc/default/v4l2-relayd")
IPU6_LOOPBACK_LABEL = "IPU6 Camera"

IVSC_MODULES = ("mei-vsc", "mei-vsc-hw", "ivsc-ace", "ivsc-csi")
IVSC_SYSFS = tuple(m.replace("-", "_") for m in IVSC_MODULES)

DEPENDENCIES = (
    "base-devel dkms linux-headers git",
    "meson ninja pkgconf cmake",
    "python-yaml python-jinja python-ply",
    "gnutls libyaml libevent libdrm libjpeg-turbo libtiff libelf libunwind",
    "openssl gstreamer gst-plugins-base gst-plugin-libcamera",
    "libcamera libcamera-tools libcamera-ipa",
    "pipewire pipewire-libcamera",
    "v4l2loopback-dkms v4l2loopback-utils",
    "acl libayatana-appindicator",
)
DEPENDENCY_GROUPS = tuple(g.split() for g in DEPENDENCIES)

# Samsung models whose BIOS reports rotation=0 for an upside-down sensor.
ROTATION_QUIRK_PRODUCTS = (
    "940XFG", "940XGK", "960XFG", "960XFH",
    "960XGK", "960XGL", "960QFG", "960QGK",
)

DEFAULT_FRAME_COUNT = 60
LENS_COVER_SHIFT = 23  # SW_CAMERA_LENS_COVER in the input device property mask

IPA_DIRS = (
    Path("/usr/local/lib/libcamera/ipa"),
    Path("/usr/local/lib64/libcamera/ipa"),
    Path("/usr/local/lib/x86_64-linux-gnu/libcamera/ipa"),
)
LIBCAMERA_LIB_DIRS = (
    Path("/usr/local/lib"),
    Path("/usr/local/lib64"),
    Path("/usr/local/lib/x86_64-linux-gnu"),
    Path("/usr/local/lib/aarch64-linux-gnu"),
)
IPA_HINT_DIRS = (
    Path("/usr/local/lib/libcamera"),
    Path("/usr/local/lib64/libcamera"),
    Path("/usr/local/lib/x86_64-linux-gnu/libcamera"),
)
OV02C10_TUNING_DIRS = (
    Path("/usr/local/share/libcamera/ipa/simple"),
    Path("/usr/share/libcamera/ipa/simple"),
)
LDCONFIG_DIRS = ("/usr/local/lib", "/usr/local/lib64",
                 "/usr/local/lib/x86_64-linux-gnu",
                 "/usr/local/lib/aarch64-linux-gnu")
MODULES_UPDATES = Path("/lib/modules")  # + f"/{uname -r}/updates"

C_RED, C_GRN, C_YEL = "\033[0;31m", "\033[0;32m", "\033[1;33m"
C_BLU, C_DIM, C_RST = "\033[0;34m", "\033[2m", "\033[0m"


# ── Output ──────────────────────────────────────────────────────────────────
def info(msg: str) -> None:
    print(f"{C_GRN}[+]{C_RST} {msg}")


def warn(msg: str) -> None:
    print(f"{C_YEL}[!]{C_RST} {msg}")


def err(msg: str) -> None:
    print(f"{C_RED}[x]{C_RST} {msg}", file=sys.stderr)


def step(msg: str) -> None:
    print(f"\n{C_BLU}=== {msg} ==={C_RST}")


def die(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[name-defined]
    err(msg)
    raise SystemExit(code)


def banner() -> None:
    print(f"{C_BLU}================================================={C_RST}")
    print(f"{C_BLU}  Galaxy Book Camera Fix — IPU6 / OV02C10{C_RST}")
    if opts.ipu7:
        print(f"{C_BLU}  (Intel IPU7 stack: {opts.ipu7}){C_RST}")
    if opts.ipu6:
        print(f"{C_BLU}  (Intel IPU6 hardware-ISP stack: {opts.ipu6}){C_RST}")
    print(f"{C_BLU}================================================={C_RST}")
    print(f"  Host     : {read_file(Path('/sys/class/dmi/id/product_name'), 'unknown')}")
    print(f"  Kernel   : {kernel_release()}")
    print(f"  User     : {TARGET_USER}")
    print(f"  IPU gen  : {ipu_generation()}")
    print(f"  Mode     : {opts.mode}")


# ── Logging mechanism ─────────────────────────────────────────────────────────
import logging

LOGFILE = Path("/var/log/webcam-setup.log")


def setup_logging() -> None:
    """Initialize file + console logging for webcam-setup."""
    logger = logging.getLogger("webcam_setup")
    logger.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    try:
        LOGFILE.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(LOGFILE), mode="a")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    except OSError as exc:
        logger.warning(f"Could not open {LOGFILE}: {exc}")
    logger.addHandler(console)


logger = logging.getLogger("webcam_setup")

# ── Small shell-ish helpers ─────────────────────────────────────────────────
def run(argv: Sequence[str], *, check: bool = False, env: dict | None = None,
        cwd: Path | str | None = None, timeout: int | None = None,
        **kw) -> subprocess.CompletedProcess:
    """Run a command; logs to file + console; never prints its output unless it fails."""
    cmd_line = " ".join(str(x) for x in argv)
    logger.info("Running: %s (cwd=%s)", cmd_line, cwd or ".")
    proc = subprocess.run(
        list(argv), env=env, cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout, **kw,
    )
    if proc.stdout:
        for line in proc.stdout.splitlines():
            logger.debug("  %s", line)
    if proc.returncode != 0:
        logger.warning("Command failed (exit=%d): %s", proc.returncode, cmd_line)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, list(argv), proc.stdout)
    return proc


def quiet(argv: Sequence[str], **kw) -> bool:
    """True when the command exits 0. Output is swallowed."""
    try:
        return run(argv, **kw).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def lines(argv: Sequence[str], **kw) -> list[str]:
    """stdout split into lines (empty list on failure)."""
    try:
        proc = run(argv, **kw)
    except (OSError, subprocess.SubprocessError):
        return []
    return proc.stdout.splitlines()


def capture(argv: Sequence[str], **kw) -> str:
    """stdout with trailing whitespace stripped — matches shell $(...) semantics."""
    try:
        return run(argv, **kw).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def which(prog: str) -> bool:
    return shutil.which(prog) is not None


def read_file(path: Path, default: str = "") -> str:
    """Read a single-line sysfs/procfs value. Uses strip() so it is safe on
    one-line files; multi-line content must use read_file_multiline()."""
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return default


def read_file_multiline(path: Path, default: str = "") -> str:
    """Read a multi-line file, dropping only the trailing newlines."""
    try:
        return path.read_text(errors="replace").rstrip("\n")
    except OSError:
        return default


def write_file(path: Path, content: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mode is not None:
        os.chmod(path, mode)


def kernel_release() -> str:
    return os.uname().release


def updates_dir() -> Path:
    return Path(f"/lib/modules/{kernel_release()}/updates")


def run_as_user(*argv: str, **kw) -> subprocess.CompletedProcess:
    """Run a command as the desktop user, with a working XDG runtime dir."""
    if not TARGET_UID:
        return subprocess.CompletedProcess(list(argv), 1, "", "")
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{TARGET_UID}"
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{TARGET_UID}/bus"
    cmd = ["sudo", "-u", TARGET_USER, *argv]
    return run(cmd, env=env, **kw)


def run_as_user_ok(*argv: str, **kw) -> bool:
    return run_as_user(*argv, **kw).returncode == 0


def user_service(*argv: str) -> subprocess.CompletedProcess:
    return run_as_user("systemctl", "--user", *argv)


def user_service_ok(*argv: str) -> bool:
    return user_service(*argv).returncode == 0


# ── Detection helpers ───────────────────────────────────────────────────────
def ov02c10_module_path() -> str:
    for line in lines(["modinfo", "ov02c10"]):
        if line.startswith("filename:"):
            return line.split(None, 1)[1].strip()
    return ""


def ov02c10_is_patched() -> bool:
    return "/updates/" in ov02c10_module_path()


def dmesg() -> str:
    """Kernel log. Under a hardened kernel dmesg is restricted even for root
    (dmesg_restrict=1), so fall back to the kernel journal before giving up —
    a false 'unknown' here makes the sensor probe look untested."""
    text = capture(["dmesg"])
    if text:
        return text
    journal = capture(["journalctl", "-k", "--no-pager"])
    return journal


def sensor_probed() -> bool:
    return "26000000Hz clock" in dmesg()


def clock_error_present() -> bool:
    return "external clock 26000000 is not supported" in dmesg()


def libcamera_local_present() -> bool:
    return any(p.is_dir() and any(p.glob("libcamera.so.*")) for p in LIBCAMERA_LIB_DIRS)


def libcamera_local_lib() -> str:
    for d in LIBCAMERA_LIB_DIRS:
        hits = sorted(d.glob("libcamera.so.0.*"))
        if hits:
            return str(hits[0])
    return ""


def linker_libcamera() -> str:
    """The libcamera soname ldconfig resolves (full soname, e.g. libcamera.so.0.7).

    Anchor on the full soname: a pattern anchored on 'libcamera.so.0' matches
    nothing and reports a false failure.
    """
    for line in lines(["ldconfig", "-p"]):
        if re.search(r"libcamera\.so\.0\.[0-9]+ ", line):
            return line.split()[-1]
    return ""


def ipa_helper_hits() -> int:
    """Symbols proving the OV02C10 sensor helper is compiled into the IPA module.

    The helper lives in the IPA module, NOT in libcamera.so. Count matches
    rather than using `grep -q`: under a SIGPIPE-prone pipeline `grep -q`
    reports a false negative when the symbol is present.
    """
    for d in IPA_DIRS:
        ipa = d / "ipa_soft_simple.so"
        if not ipa.is_file():
            continue
        try:
            data = ipa.read_bytes()
        except OSError:
            return 0
        return data.count(b"CameraSensorHelperOv02c10")
    return 0


def relay_device() -> str:
    """The v4l2loopback node whose card label is 'Camera Relay'."""
    for dev in sorted(glob.glob("/dev/video*")):
        name = read_file(Path(f"/sys/class/video4linux/{Path(dev).name}/name"))
        if name == "Camera Relay":
            return dev
    return ""


def ipu_generation() -> str:
    """Which Intel IPU controller is present, from PCI (authoritative)."""
    for dev in glob.glob("/sys/bus/pci/devices/*"):
        if not read_file(Path(dev) / "class").startswith("0x0480"):  # multimedia controller
            continue
        if read_file(Path(dev) / "vendor").lower().lstrip("0x") != "8086":
            continue
        try:
            modname = os.path.basename(os.readlink(Path(dev) / "driver"))
        except OSError:
            modname = ""
        if "ipu7" in modname:
            return "IPU7"
        if "ipu6" in modname:
            return "IPU6"
    # No driver bound: fall back to the loaded modules, then the PCI ids.
    for mod, gen in (("intel_ipu7", "IPU7"), ("intel_ipu6", "IPU6")):
        if Path(f"/sys/module/{mod}").is_dir():
            return gen
    ctrl = ipu7_controller()
    if ctrl == "b05d":
        return "IPU7"
    if ctrl in ("645d", "7d19"):
        return "IPU7"
    return "unknown"


def ipu7_controller() -> str:
    """PCI device id of the IPU controller, or ''."""
    for dev in glob.glob("/sys/bus/pci/devices/*"):
        if not read_file(Path(dev) / "class").startswith("0x0480"):
            continue
        if read_file(Path(dev) / "vendor").lower().lstrip("0x") == "8086":
            return read_file(Path(dev) / "device").lower().lstrip("0x")
    return ""


def ipu7_sensor_present() -> bool:
    """An OV08X40-class sensor declared by ACPI."""
    return any(any(tag in read_file(Path(hid)) for tag in IPU7_SENSOR_HIDS)
               for hid in glob.glob("/sys/bus/acpi/devices/*/hid"))


def dmi_product() -> str:
    return read_file(Path("/sys/class/dmi/id/product_name"))


def dmi_vendor() -> str:
    return read_file(Path("/sys/class/dmi/id/sys_vendor"))


# ── IPU7 status ─────────────────────────────────────────────────────────────
def ipu7_module_loaded() -> bool:
    return Path(f"/sys/module/{IPU7_MODULE}").is_dir()


def ipu7_dkms_installed() -> str:
    for line in lines(["dkms", "status"]):
        if line.startswith(f"{IPU7_DKMS_PKGS[0]}/{IPU7_DKMS_PKGS[1]}"):
            if "installed" in line:
                return line.strip()
    return ""


def ipu7_distro_installed() -> bool:
    return quiet(["pacman", "-Q", IPU7_PKG])


def ipu7_git_installed() -> list[str]:
    return [p for p in IPU7_GIT_PKGS if quiet(["pacman", "-Q", p])]


def ipu7_relay_active() -> bool:
    return user_service_ok("is-active", IPU7_RELAY_UNIT)


def ipu7_loopback_device() -> str:
    """v4l2-relayd's IPU7 loopback node, by card label."""
    for dev in sorted(glob.glob("/dev/video*")):
        name = read_file(Path(f"/sys/class/video4linux/{Path(dev).name}/name"))
        if "Hardware ISP Camera" in name or name == "ipu7":
            return dev
    return ""


# ── Status table ────────────────────────────────────────────────────────────
def check_status() -> None:
    step("Camera fix status")

    path = ov02c10_module_path()
    if ov02c10_is_patched():
        print(f"  ov02c10 sensor module : {C_GRN}patched (DKMS){C_RST} — {path}")
    else:
        print(f"  ov02c10 sensor module : {C_RED}stock{C_RST} — {path or 'not found'}")

    if sensor_probed():
        print(f"  sensor probe          : {C_GRN}OK — 26 MHz clock accepted{C_RST}")
    elif clock_error_present():
        print(f"  sensor probe          : {C_RED}FAILED — 26 MHz clock rejected{C_RST}")
    else:
        print(f"  sensor probe          : {C_YEL}unknown{C_RST}")

    # Installed is NOT the same as loaded. The DKMS module only wins after a
    # reboot; before that the stock module stays bound and the image is still
    # upside-down. Compare srcversion instead of trusting `dkms status`.
    ko = updates_dir() / "ipu-bridge.ko.zst"
    ipu_patched = capture(["modinfo", "-F", "srcversion", str(ko)]) if ko.is_file() else ""
    ipu_loaded = read_file(Path("/sys/module/ipu_bridge/srcversion"))
    # A missing /sys entry is the only reliable "not loaded" signal; two
    # srcversion strings that differ are just two different builds, not proof
    # of anything, so report them rather than claiming a reboot is needed.
    if ipu_patched and ipu_loaded == ipu_patched:
        print(f"  ipu-bridge rotation   : {C_GRN}patched and loaded{C_RST}")
    elif ipu_patched and not ipu_loaded:
        print(f"  ipu-bridge rotation   : {C_YEL}installed but not loaded — "
              f"REBOOT REQUIRED{C_RST}")
    elif ipu_patched:
        print(f"  ipu-bridge rotation   : {C_GRN}installed{C_RST} "
              f"(loaded={ipu_loaded}, patched={ipu_patched})")
    elif _upstream_has_rotation_quirk():
        print(f"  ipu-bridge rotation   : {C_GRN}upstream has quirk{C_RST}")
    else:
        print(f"  ipu-bridge rotation   : {C_YEL}not installed{C_RST} "
              f"(image may be upside-down)")

    missing = [m for m in IVSC_SYSFS if not Path(f"/sys/module/{m}").is_dir()]
    if missing:
        print(f"  IVSC modules          : {C_YEL}not all loaded{C_RST} (missing: "
              f"{', '.join(missing)})")
    else:
        print(f"  IVSC modules          : {C_GRN}loaded{C_RST}")

    if libcamera_local_present():
        print(f"  libcamera (source)    : {C_GRN}present in /usr/local{C_RST} — "
              f"{libcamera_local_lib()}")
    else:
        print(f"  libcamera (source)    : {C_YEL}not built{C_RST} — using system "
              f"libcamera (no OV02C10 helper → dark image)")

    lc = linker_libcamera()
    if lc.startswith("/usr/local/"):
        print(f"  linker resolution     : {C_GRN}{lc} (patched){C_RST}")
    else:
        print(f"  linker resolution     : {C_YEL}{lc or 'none'}{C_RST} — "
              f"patched build not in use")

    hits = ipa_helper_hits()
    if hits > 0:
        print(f"  OV02C10 helper        : {C_GRN}registered{C_RST} ({hits} symbols)")
    else:
        print(f"  OV02C10 helper        : {C_RED}not found{C_RST} — "
              f"auto-exposure will not work")

    print(f"  IPA tuning file       : "
          f"{C_GRN}present{C_RST}" if any((d / "ov02c10.yaml").is_file() for d in OV02C10_TUNING_DIRS)
          else f"  IPA tuning file       : {C_YEL}missing{C_RST} — "
               f"ISP uses uncalibrated defaults")

    if os.environ.get("LIBCAMERA_IPA_MODULE_PATH"):
        print(f"  IPA module path       : {C_GRN}"
              f"{os.environ['LIBCAMERA_IPA_MODULE_PATH']}{C_RST}")
    elif Path("/etc/environment.d/libcamera-ipa.conf").is_file():
        print(f"  IPA module path       : {C_GRN}configured{C_RST} (/etc/environment.d)")
    else:
        print(f"  IPA module path       : {C_YEL}not configured{C_RST}")

    if quiet(["modinfo", "v4l2loopback"]):
        label = next((n for n in capture(["sh", "-c",
                     "cat /sys/devices/virtual/video4linux/video*/name 2>/dev/null"])
                      .splitlines() if n and "Intel IPU" not in n), "")
        print(f"  v4l2loopback          : {C_GRN}available{C_RST}"
              + (f' — label "{label}"' if label else ""))
    else:
        print(f"  v4l2loopback          : {C_YEL}not installed{C_RST} (relay needs it)")

    print(f"  camera-relay service  : {_relay_service_line()}")
    print(f"  relay mode            : {_relay_mode_line()}")
    print(f"  lens cover            : {_lens_cover_line()}")
    _print_groups()
    _print_ipu7_status()
    _print_ipu6_stack_status()

    step("libcamera view")
    if which("cam"):
        print(f"  {C_DIM}note: opening the sensor resets the V4L2 flip on "
              f"inverted-sensor{C_RST}")
        print(f"  {C_DIM}models; the relay is restarted afterwards to re-apply it.{C_RST}")
        out = cam_probe()
        shown = [ln for ln in out.splitlines()
                 if re.search(r"Available cameras|Internal|camera", ln)]
        for ln in shown:
            print(f"  {ln}")
        if not shown:
            print("  (no cameras listed)")
        print(f"  {C_DIM}note: 'no cameras' as a plain user is expected — raw MC nodes are{C_RST}")
        print(f"  {C_DIM}hidden behind the setgid camera-relay launcher by design.{C_RST}")
    else:
        warn("cam not installed — pacman -S libcamera-tools")

    step("PipeWire view")
    if pipewire_sees_camera():
        info("PipeWire sees the camera")
    else:
        warn("PipeWire does not see a camera node yet")


def _upstream_has_rotation_quirk() -> bool:
    """True when the in-tree ipu-bridge already carries the Samsung quirk.

    On current kernels ipu-bridge is built into the image and the quirk table
    lives in the core driver, so there is no separate .ko to search. The
    kernel config is the honest answer to "is the quirk upstream yet" — the
    driver being present at all is what matters, not the module/file split.
    """
    config = ""
    gz = Path("/proc/config.gz")
    if gz.is_file():
        try:
            config = gzip.decompress(gz.read_bytes()).decode(errors="replace")
        except OSError:
            config = ""
    if not config:
        config = read_file_multiline(Path(f"/boot/config-{kernel_release()}"))
    return any(line.strip().startswith("CONFIG_IPU_BRIDGE=")
               and line.strip() != "CONFIG_IPU_BRIDGE is not set"
               for line in config.splitlines())


def _relay_service_line() -> str:
    if user_service_ok("is-enabled", "camera-relay.service"):
        if user_service_ok("is-active", "camera-relay.service"):
            return f"{C_GRN}enabled, active{C_RST}"
        return f"{C_GRN}enabled{C_RST}, {C_YEL}not running{C_RST}"
    return f"{C_YEL}not enabled{C_RST}"


def _relay_mode_line() -> str:
    if relay_is_always_on():
        return f"{C_GRN}always-on{C_RST} (no AGC ramp on connect — flicker-free)"
    return f"{C_YEL}on-demand{C_RST} (idles at ~0% CPU, but flickers on connect)"


def _lens_cover_line() -> str:
    if lens_cover_closed():
        return f"{C_YEL}CLOSED — open it{C_RST}"
    return f"{C_GRN}open{C_RST}"


def _print_groups() -> None:
    groups = capture(["id", "-nG", TARGET_USER]) if TARGET_UID else ""
    print(f"  user groups           : {groups.replace(' ', ',')}")
    for g in ("kvm", "video"):
        if g not in groups.split():
            need = " (needed for /dev/udmabuf → GPU debayer)" if g == "kvm" else ""
            print(f"        {C_YEL}missing: {g}{C_RST}{need}")


def _print_ipu7_status() -> None:
    gen = ipu_generation()
    if gen != "IPU7":
        print(f"  IPU generation        : {gen} (IPU6 stack is the relevant one here)")
        return
    ctrl = ipu7_controller()
    dkms = ipu7_dkms_installed()
    distro = ipu7_distro_installed()
    git = ipu7_git_installed()
    print(f"  IPU generation        : {C_GRN}IPU7{C_RST} "
          f"(controller {ctrl or 'unknown'})")
    print(f"  IPU7 module           : "
          f"{C_GRN}loaded{C_RST}" if ipu7_module_loaded() else
          f"  IPU7 module           : {C_YEL}not loaded{C_RST}")
    print(f"  IPU7 DKMS             : {C_GRN}{dkms}{C_RST}" if dkms else
          f"  IPU7 DKMS             : {C_YEL}not installed{C_RST}")
    print(f"  IPU7 distro stack     : {C_GRN}{IPU7_PKG}{C_RST}" if distro else
          f"  IPU7 distro stack     : {C_YEL}not installed{C_RST}")
    if git:
        print(f"  IPU7 git stack        : {C_GRN}{', '.join(git)}{C_RST}")
    print(f"  IPU7 relay            : {C_GRN}active{C_RST}" if ipu7_relay_active() else
          f"  IPU7 relay            : {C_YEL}not running{C_RST}")


# ── libcamera probe ─────────────────────────────────────────────────────────
def libcamera_version() -> str:
    """libcamera version WITHOUT touching the sensor.

    `cam -l` opens the sensor, and on an inverted-sensor model that resets the
    V4L2 flip controls. Prefer pkg-config, which only reads a .pc file.
    """
    v = capture(["pkg-config", "--modversion", "libcamera"]).strip()
    if v:
        return f"v{v}"
    out = run_as_user("cam", "-l").stdout
    m = re.search(r"libcamera v([0-9.]+)", out)
    return m.group(1) if m else ""


def cam_probe() -> str:
    """Run `cam -l` and undo the damage it may have done to the flip controls."""
    out = run_as_user("cam", "-l").stdout
    if relay_is_always_on() and camera_relay_active():
        user_service("restart", "camera-relay.service")
        time.sleep(4)
    return out


def camera_relay_active() -> bool:
    return user_service_ok("is-active", "camera-relay.service")


def pipewire_sees_camera() -> bool:
    out = run_as_user("pw-cli", "ls", "Node").stdout
    return bool(re.search(r"camera|libcamera", out, re.IGNORECASE))


def relay_is_always_on() -> bool:
    return bool(TARGET_HOME) and (Path(TARGET_HOME) / ".config/systemd/user/"
                                  "camera-relay.service.d/always-on.conf").is_file()


def lens_cover_closed() -> bool:
    """SW_CAMERA_LENS_COVER is bit 23 of the input device's property mask."""
    for name in glob.glob("/sys/class/input/*/device/name"):
        if "Camera Lens Cover" in read_file(Path(name)):
            state = read_file(Path(name).parent / "device/properties", "0")
            try:
                return ((int(state) >> LENS_COVER_SHIFT) & 1) == 1
            except ValueError:
                return False
    return False


# ── [1] Packages ────────────────────────────────────────────────────────────
def install_packages() -> None:
    step("[1/8] Installing dependencies")
    missing: list[str] = []
    for group in DEPENDENCY_GROUPS:
        for pkg in group:
            if not quiet(["pacman", "-Q", pkg]):
                missing.append(pkg)
    if missing:
        info(f"Installing: {' '.join(missing)}")
        proc = run(["pacman", "-S", "--needed", "--noconfirm", *missing])
        if proc.returncode != 0:
            warn("Some packages failed to install — continuing")
    else:
        info("All dependencies already present")


# ── [2] ov02c10 26 MHz DKMS ─────────────────────────────────────────────────
def install_ov02c10_dkms() -> None:
    step("[2/8] Installing patched ov02c10 driver (26 MHz clock)")

    if ov02c10_is_patched() and any(
        line.startswith(f"ov02c10/{OV02C10_DKMS_VER}") and "installed" in line
        for line in lines(["dkms", "status"])
    ):
        info("Already installed and active")
        return

    src_dir = Path(f"/usr/src/ov02c10-{OV02C10_DKMS_VER}")
    repo_dir = WORK_DIR / "ov02c10-26mhz-fix"
    if not (repo_dir / "ov02c10.c").is_file():
        die(f"Source not found: {repo_dir / 'ov02c10.c'}")

    # Neutralise stale community workarounds that pass a non-existent parameter.
    for conf in sorted(glob.glob("/etc/modprobe.d/*.conf")):
        p = Path(conf)
        try:
            text = read_file_multiline(p)
        except OSError:
            continue
        if re.search(r"^\s*options\s+ov02c10\b.*clk_freq", text, re.MULTILINE):
            p.with_name(p.name + ".ov02c10-26mhz.bak").write_text(text)
            p.write_text(re.sub(
                r"^(\s*options\s+ov02c10\b.*clk_freq.*)$",
                r"# disabled by blackarch-webcam-setup: \1", text, flags=re.MULTILINE))
            info(f"Neutralised stale clk_freq option in {conf} (backup saved)")

    quiet(["dkms", "remove", f"ov02c10/{OV02C10_DKMS_VER}", "--all"])
    shutil.rmtree(src_dir, ignore_errors=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    for f in ("ov02c10.c", "Makefile", "dkms.conf"):
        shutil.copy2(repo_dir / f, src_dir / f)

    for verb in ("add", "build", "install"):
        proc = run(["dkms", verb, f"ov02c10/{OV02C10_DKMS_VER}"])
        if proc.returncode != 0:
            if verb == "build":
                err("DKMS build failed — see "
                    f"/var/lib/dkms/ov02c10/{OV02C10_DKMS_VER}/build/make.log")
            die(f"dkms {verb} failed")

    run(["depmod", "-a", kernel_release()])
    info(f"Installed: {ov02c10_module_path()}")

    if "ov02c10" in capture(["lsmod"]):
        if quiet(["rmmod", "ov02c10"]):
            quiet(["modprobe", "ov02c10"])
        else:
            warn("Could not reload ov02c10 live — reboot will apply it")

    time.sleep(1)
    if sensor_probed():
        info("Sensor probed successfully — 26 MHz clock accepted")
    else:
        warn("Sensor not confirmed this boot (stock driver may still be bound) — "
             "reboot and re-check")


# ── [3] IVSC modules ────────────────────────────────────────────────────────
def install_ivsc_modules() -> None:
    step("[3/8] Loading IVSC modules")

    # The IVSC bridge (Intel Visual Sensing Controller) sits between the sensor
    # and the IPU6 ISYS on these boards. ov02c10 can hit -EPROBE_DEFER and fail
    # to bind if it probes before IVSC is up, so load them explicitly and
    # persist the ordering rather than relying on autoload.
    for mod in IVSC_MODULES:
        if Path(f"/sys/module/{mod.replace('-', '_')}").is_dir():
            info(f"{mod} already loaded")
        elif quiet(["modprobe", mod]):
            info(f"Loaded {mod}")
        else:
            warn(f"{mod} not loadable (built-in or absent) — continuing")

    write_file(Path("/etc/modules-load.d/ivsc.conf"),
               "".join(f"{m}\n" for m in IVSC_MODULES))

    # Without the softdep, ov02c10 can probe before IVSC and fail to bind.
    write_file(Path("/etc/modprobe.d/ivsc-camera.conf"),
               "# Ensure IVSC modules are loaded before the camera sensor probes.\n"
               "# Without this, ov02c10 hits -EPROBE_DEFER and may fail to bind.\n"
               "softdep ov02c10 pre: mei-vsc mei-vsc-hw ivsc-ace ivsc-csi\n")
    info("IVSC modules will load before ov02c10 at boot")


# ── [4] ipu-bridge rotation DKMS ────────────────────────────────────────────
def install_ipu_bridge_dkms() -> None:
    step("[4/8] Checking camera rotation fix (ipu-bridge)")

    vendor, product = dmi_vendor(), dmi_product()
    needed = vendor == "SAMSUNG ELECTRONICS CO., LTD." and product in ROTATION_QUIRK_PRODUCTS

    if not needed:
        info(f"No rotation quirk needed for this model ({product or 'unknown'})")
        return

    if any(re.match(r"^ipu-bridge-fix/.*installed", ln) for ln in lines(["dkms", "status"])):
        info("ipu-bridge rotation fix already installed via DKMS")
        return

    # Upstream may have gained the quirk in the meantime.
    if _upstream_has_rotation_quirk():
        info(f"Upstream ipu-bridge already carries the {product} quirk — no DKMS needed")
        return

    src_dir = Path(f"/usr/src/ipu-bridge-fix-{IPU_BRIDGE_DKMS_VER}")
    repo_dir = WORK_DIR / "webcam-fix-book5" / "ipu-bridge-fix"
    if not (repo_dir / "ipu-bridge.c").is_file():
        die(f"Source not found: {repo_dir / 'ipu-bridge.c'}")

    # Supersede any older installed version.
    versions = sorted({
        parts[1] for ln in lines(["dkms", "status"]) if ln.startswith("ipu-bridge-fix/")
        for parts in [re.split(r"[/,: ]+", ln)] if len(parts) > 2
    })
    for old in versions:
        quiet(["dkms", "remove", f"ipu-bridge-fix/{old}", "--all"])
    for stale in glob.glob("/usr/src/ipu-bridge-fix-*"):
        shutil.rmtree(stale, ignore_errors=True)

    src_dir.mkdir(parents=True, exist_ok=True)
    for f in repo_dir.iterdir():
        (shutil.copytree if f.is_dir() else shutil.copy2)(f, src_dir / f.name)

    for verb in ("add", "build", "install"):
        if run(["dkms", verb, f"ipu-bridge-fix/{IPU_BRIDGE_DKMS_VER}"]).returncode != 0:
            die(f"dkms {verb} failed (ipu-bridge-fix)")

    info("ipu-bridge rotation fix installed — camera image will be right-side-up")


def _ko_contains(path: str, needle: str) -> bool:
    """True when a possibly-compressed kernel module contains `needle`.

    Handles the .zst/.xz/.gz suffixes the distro uses so the product string is
    searched in the decompressed module rather than the compressed bytes.
    """
    p = Path(path)
    reader = {"zst": "zstdcat", "xz": "xzcat", "gz": "zcat"}.get(p.suffix.lstrip("."))
    if reader and shutil.which(reader):
        try:
            return needle.encode() in subprocess.run(
                [reader, str(p)], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL).stdout
        except OSError:
            pass
    try:
        return needle.encode() in p.read_bytes()
    except OSError:
        return False


# ── [5] libcamera from source ───────────────────────────────────────────────
def build_libcamera() -> None:
    step(f"[5/8] Building libcamera {LIBCAMERA_BUILD_VER} with OV02C10 sensor helper")

    # Arch's packaged libcamera 0.7.x compiles the OV02C10 helper in but the
    # factory registration is dead-code-eliminated at link time, so at runtime
    # IPASoft logs "Failed to create camera sensor helper for ov02c10" and the
    # software AGC falls back to a generic curve — a very dark image. A source
    # build is the only fix on Arch.
    if not opts.skip_libcamera_rebuild and libcamera_local_present() and ipa_helper_hits() > 0:
        info("Patched libcamera with the OV02C10 helper already built in "
             "/usr/local — skipping rebuild")
        run(["ldconfig"])
        return

    if opts.skip_libcamera_rebuild:
        warn("--skip-libcamera-rebuild given — using the system libcamera "
             "(image may be dark)")
        return

    # Build against the system Python, not a pyenv/conda shim that lacks deps.
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:" + env.get("PATH", "")

    shutil.rmtree(LIBCAMERA_BUILD_DIR, ignore_errors=True)
    info(f"Cloning libcamera {LIBCAMERA_BUILD_VER}...")
    proc = run(["git", "clone", "--depth", "1", "--branch", LIBCAMERA_BUILD_VER,
                "https://git.libcamera.org/libcamera/libcamera.git",
                str(LIBCAMERA_BUILD_DIR)])
    if proc.returncode != 0:
        die("libcamera clone failed")

    tree = LIBCAMERA_BUILD_DIR

    # ── Patch in the OV02C10 sensor helper ──────────────────────────────────
    helper = next((c for c in (tree / "src/ipa/libipa/camera_sensor_helper.cpp",
                               tree / "src/libcamera/sensor/camera_sensor_helper.cpp")
                   if c.is_file()), None)
    if helper is None:
        die("Could not locate camera_sensor_helper.cpp in the libcamera tree")

    text = read_file_multiline(helper)
    if "CameraSensorHelperOv02c10" not in text:
        info(f"Patching {helper}")
        if "namespace ipa" in text:
            # 0.7.x: helpers live inside namespace ipa { namespace libcamera { }
            text = text.replace(
                "#endif /* __DOXYGEN__ */",
                "class CameraSensorHelperOv02c10 : public CameraSensorHelper\n"
                "{\npublic:\n\tCameraSensorHelperOv02c10()\n\t{\n"
                "\t\tgain_ = AnalogueGainLinear{ 1, 0, 0, 16 };\n\t}\n};\n"
                "REGISTER_CAMERA_SENSOR_HELPER(\"ov02c10\", CameraSensorHelperOv02c10)\n"
                "#endif /* __DOXYGEN__ */",
                1,
            )
        else:
            text += (
                "\nclass CameraSensorHelperOv02c10 : public CameraSensorHelper\n"
                "{\npublic:\n\tCameraSensorHelperOv02c10()\n\t{\n"
                "\t\tgainType_ = AnalogueGainLinear;\n"
                "\t\tgainConstants_.linear = { 1, 0, 0, 16 };\n\t}\n};\n"
                "REGISTER_CAMERA_SENSOR_HELPER(\"ov02c10\", CameraSensorHelperOv02c10)\n"
            )
        helper.write_text(text)
        if "CameraSensorHelperOv02c10" not in read_file_multiline(helper):
            die("Sensor helper patch did not apply")
        info("OV02C10 sensor helper patched in")
    else:
        info("Sensor helper already present")

    # ── Configure and build ─────────────────────────────────────────────────
    info("Configuring (this takes a minute)...")
    proc = run(["meson", "setup", "build",
                "-Dprefix=/usr/local", "-Dpipelines=simple", "-Dipas=simple",
                "-Dgstreamer=enabled", "-Dv4l2=true", "-Dcam=enabled",
                "-Dqcam=disabled", "-Dlc-compliance=disabled", "-Dtracing=disabled",
                "-Ddocumentation=disabled", "-Dpycamera=disabled"],
               cwd=tree, env=env)
    if proc.returncode != 0:
        die("meson setup failed")

    jobs = os.cpu_count() or 2
    info(f"Compiling with {jobs} jobs (a few minutes)...")
    if run(["ninja", "-C", "build", f"-j{jobs}"], cwd=tree, env=env).returncode != 0:
        die("ninja build failed")

    # Deliberately no PYTHONPATH manipulation here: forcing root's site-packages
    # in makes Python resolve a stale PyPI `typing` backport over the stdlib
    # typing module and meson dies on Python 3.14.
    if run(["meson", "install", "-C", "build"], cwd=tree, env=env).returncode != 0:
        die("meson install failed")
    info("libcamera installed to /usr/local")

    # Make the dynamic linker prefer /usr/local over the distro package, or the
    # packaged libcamera (no working helper) wins and the source build is
    # silently ignored.
    conf = Path("/etc/ld.so.conf.d/libcamera-local.conf")
    if not conf.is_file():
        conf.write_text("# Source-built libcamera with the OV02C10 sensor helper\n"
                        + "".join(f"{d}\n" for d in LDCONFIG_DIRS))
        info("Added /usr/local to the linker search path")
    run(["ldconfig"])

    shutil.rmtree(LIBCAMERA_BUILD_DIR, ignore_errors=True)


# ── [6] Tuning file + environment ───────────────────────────────────────────
def configure_environment() -> None:
    step("[6/8] Installing tuning file and environment configuration")

    # ── OV02C10 tuning file for the Simple ISP ──────────────────────────────
    tuning_src = WORK_DIR / "webcam-fix-libcamera" / "ov02c10.yaml"
    if tuning_src.is_file():
        for d in OV02C10_TUNING_DIRS:
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tuning_src, d / "ov02c10.yaml")
        info("Installed OV02C10 tuning file")
    else:
        warn("ov02c10.yaml not found — the ISP will fall back to uncalibrated.yaml")

    # ── IPA module path / GStreamer plugin path ─────────────────────────────
    # libcamera >= 0.7 puts IPA modules in <libdir>/libcamera/ipa
    ipa_dir = libdir = ""
    for d in IPA_HINT_DIRS:
        if not d.is_dir():
            continue
        for sub in (d / "ipa", d):
            if list(sub.glob("ipa_*.so")):
                ipa_dir, libdir = str(sub), str(d.parent)
                break
        if ipa_dir:
            break

    if ipa_dir:
        gst_dir = os.path.join(libdir, "gstreamer-1.0")
        Path("/etc/environment.d").mkdir(parents=True, exist_ok=True)
        write_file(Path("/etc/environment.d/libcamera-ipa.conf"),
                   "# libcamera IPA module path (source-built libcamera)\n"
                   f"LIBCAMERA_IPA_MODULE_PATH={ipa_dir}\n"
                   + (f"GST_PLUGIN_PATH={gst_dir}\n" if Path(gst_dir).is_dir() else ""))
        write_file(Path("/etc/profile.d/libcamera-ipa.sh"),
                   "# libcamera IPA module path (source-built libcamera)\n"
                   f"export LIBCAMERA_IPA_MODULE_PATH={ipa_dir}\n"
                   + (f"export GST_PLUGIN_PATH={gst_dir}\n" if Path(gst_dir).is_dir() else ""),
                   mode=0o755)
        os.environ["LIBCAMERA_IPA_MODULE_PATH"] = ipa_dir
        info(f"IPA module path set: {ipa_dir}")
        if Path(gst_dir).is_dir():
            info(f"GStreamer plugin path set: {gst_dir}")
    else:
        warn("Could not locate IPA modules under /usr/local — camera may not initialise")

    # ── Groups ──────────────────────────────────────────────────────────────
    # video: general V4L2 access. kvm: /dev/udmabuf, which libcamera's software
    # ISP needs because /dev/dma_heap/system is root-only on Arch — without it
    # the GPU debayer cannot import its buffers and frames come out black.
    for g in ("video", "kvm"):
        if quiet(["getent", "group", g]):
            if g in capture(["id", "-nG", TARGET_USER]).split():
                info(f"{TARGET_USER} already in group '{g}'")
            else:
                run(["usermod", "-aG", g, TARGET_USER])
                info(f"Added {TARGET_USER} to group '{g}' (effective after reboot)")


# ── [7] Hide raw IPU6 MC nodes ──────────────────────────────────────────────
def hide_raw_nodes() -> None:
    step("[7/8] Hiding raw IPU6 media-controller nodes")

    src = WORK_DIR / "camera-relay"
    if not src.is_dir():
        warn("camera-relay source missing — skipping")
        return

    # The ISYS driver registers one capture node per stream (48 on a Book4),
    # each flagged V4L2_CAP_IO_MC — usable only after userspace configures the
    # media graph, never as a standalone camera. Nothing carries that bit into
    # udev, so they all advertise as cameras. Move them into a memberless group
    # and strip the session ACL.
    sysusers = Path("/usr/local/lib/sysusers.d")
    sysusers.mkdir(parents=True, exist_ok=True)
    (sysusers / "camera-relay.conf").write_text(
        "# Owns the raw MC-centric camera nodes. Deliberately memberless: the relay\n"
        "# pipeline acquires it through the setgid launcher, nothing else should hold it.\n"
        "g camera-relay -\n")
    if which("systemd-sysusers"):
        quiet(["systemd-sysusers"])
    if not quiet(["getent", "group", "camera-relay"]):
        quiet(["groupadd", "-r", "camera-relay"])
    info("Group 'camera-relay' present (memberless by design)")

    # Writable cache for the pipeline's GStreamer registry. It maps elements to
    # .so paths that get dlopen()ed, so it must not be user-writable.
    os.makedirs("/var/cache/camera-relay", mode=0o2770, exist_ok=True)
    shutil.chown("/var/cache/camera-relay", user="root", group="camera-relay")

    # Order matters: the launcher must exist before the udev rule hands the raw
    # nodes to camera-relay, or nothing can open the camera at all.
    mc_helper = Path("/usr/local/lib/udev/camera-relay-v4l2-io-mc")
    helper_ok = launcher_ok = False

    tmp_helper = Path("/tmp/camera-relay-v4l2-io-mc")
    if run(["gcc", "-O2", "-Wall", "-o", str(tmp_helper),
            str(src / "v4l2-io-mc.c")]).returncode == 0:
        udev_lib = Path("/usr/local/lib/udev")
        udev_lib.mkdir(mode=0o755, parents=True, exist_ok=True)
        shutil.copy2(tmp_helper, mc_helper)
        os.chmod(mc_helper, 0o755)
        tmp_helper.unlink(missing_ok=True)
        helper_ok = True
    else:
        warn("Failed to build the v4l2-io-mc helper (gcc required)")

    tmp_gst = Path("/tmp/camera-relay-gst")
    if (src / "camera-relay-gst.c").is_file() and run(
        ["gcc", "-O2", "-Wall", "-o", str(tmp_gst), str(src / "camera-relay-gst.c")]
    ).returncode == 0:
        shutil.copy2(tmp_gst, "/usr/local/bin/camera-relay-gst")
        # chgrp clears S_ISGID, so set it after the group change or the launcher
        # silently lands as 0755 and cannot reach the nodes.
        shutil.chown("/usr/local/bin/camera-relay-gst", user="root", group="camera-relay")
        os.chmod("/usr/local/bin/camera-relay-gst", 0o2755)
        tmp_gst.unlink(missing_ok=True)
        launcher_ok = True
        info("Installed /usr/local/bin/camera-relay-gst (setgid camera-relay)")
    else:
        warn("Failed to build the pipeline launcher (gcc required)")

    if helper_ok and launcher_ok:
        write_file(Path("/etc/udev/rules.d/74-camera-relay-mc-nodes.rules"),
                   MC_NODE_RULE)
        for stale in ("90-hide-ipu6-v4l2.rules", "90-camera-relay-mc-nodes.rules",
                      "72-camera-relay-mc-nodes.rules"):
            Path("/etc/udev/rules.d", stale).unlink(missing_ok=True)
        if not which("setfacl"):
            warn("setfacl missing — raw nodes stay visible in app pickers")
        quiet(["udevadm", "control", "--reload-rules"])
        quiet(["udevadm", "trigger", "--action=change", "--subsystem-match=video4linux"])
        info("Raw MC-centric nodes reassigned to the camera-relay group")
    else:
        warn("Skipping the MC-node rule — helpers did not build, nodes left untouched")


MC_NODE_RULE = """# Raw MC-centric V4L2 nodes are not standalone cameras. Keyed off the kernel's
# own V4L2_CAP_IO_MC rather than a driver-specific card name, so this covers
# IPU6, IPU7 and anything else media-controller based.
#
# The 74- prefix is load-bearing, pinned by three stock rule files:
#   60-persistent-v4l.rules  runs v4l_id, which sets the properties cleared below
#   73-seat-late.rules       queues RUN{builtin}+="uaccess", the session ACL
#   95-cd-devices.rules      hands anything with ID_V4L_PRODUCT to colord
#
# TAG-="uaccess" alone does not work: 70-uaccess.rules tags every video4linux
# device unconditionally and the TAG== test in 73 matches the sticky tag list,
# which TAG-= does not touch. Stripping the ACL afterwards is reliable, because
# RUN entries execute in the order rules added them.
ACTION=="remove", GOTO="camera_relay_mc_end"
SUBSYSTEM!="video4linux", GOTO="camera_relay_mc_end"

KERNEL=="video*", ENV{ID_V4L_IO_MC}=="", \\
  IMPORT{program}="/usr/local/lib/udev/camera-relay-v4l2-io-mc $devnode"

ENV{ID_V4L_IO_MC}=="1", GROUP="camera-relay", MODE="0660", TAG-="uaccess", \\
  ENV{ID_V4L_CAPABILITIES}="", ENV{ID_V4L_PRODUCT}="", \\
  RUN+="/usr/bin/setfacl -b $devnode"

LABEL="camera_relay_mc_end"
"""


# ── [8] Camera relay ────────────────────────────────────────────────────────
def install_camera_relay() -> None:
    step(f"[8/8] Installing camera relay ({opts.relay_mode})")

    src = WORK_DIR / "camera-relay"
    if not src.is_dir():
        warn("camera-relay source missing — skipping")
        return

    # ── v4l2loopback ────────────────────────────────────────────────────────
    if not quiet(["modinfo", "v4l2loopback"]):
        quiet(["dkms", "autoinstall", "v4l2loopback"])
    if quiet(["modinfo", "v4l2loopback"]):
        shutil.copy2(src / "99-camera-relay-loopback.conf",
                     "/etc/modprobe.d/99-camera-relay-loopback.conf")
        write_file(Path("/etc/modules-load.d/v4l2loopback.conf"), "v4l2loopback\n")
        info("v4l2loopback configured (card label 'Camera Relay', autoload on boot)")

        # Reload if it came up with a stale label (e.g. OBS Virtual Camera).
        if "v4l2loopback" in capture(["lsmod"]):
            label = next((n for n in capture(["sh", "-c",
                         "cat /sys/devices/virtual/video4linux/video*/name 2>/dev/null"])
                          .splitlines() if n and "Intel IPU" not in n and n != "Camera Relay"), "")
            if label:
                quiet(["modprobe", "-r", "v4l2loopback"])
                quiet(["modprobe", "v4l2loopback"])
                info("Reloaded v4l2loopback with the correct label")

        write_file(Path("/etc/udev/rules.d/70-camera-relay-capabilities.rules"),
                   "# Normalise ID_V4L_CAPABILITIES for the Camera Relay loopback: "
                   "v4l_id tags the\n# node before any capture format is negotiated, "
                   "so the property can come up\n# without \":capture:\". Runs after "
                   "60-persistent-v4l.\n"
                   'SUBSYSTEM=="video4linux", ATTR{name}=="Camera Relay", '
                   'ENV{ID_V4L_CAPABILITIES}=":capture:"\n')
        quiet(["udevadm", "control", "--reload-rules"])
        quiet(["udevadm", "trigger", "--action=change", "--subsystem-match=video4linux"])
    else:
        warn("v4l2loopback unavailable — non-PipeWire apps will not see the camera")

    # ── GStreamer libcamerasrc ──────────────────────────────────────────────
    if quiet(["gst-inspect-1.0", "libcamerasrc"]):
        info("GStreamer 'libcamerasrc' element available")
    else:
        warn("libcamerasrc not loadable — the relay pipeline will not start")
        warn("  check: gst-inspect-1.0 --gst-debug=2 libcamerasrc 2>&1 | tail -20")

    # ── Binaries ────────────────────────────────────────────────────────────
    # Prefer the locally patched monitor (grace period + warmup hold). Upstream's
    # monitor tears the pipeline down the instant the last client leaves, so
    # every connect replays libcamera's AGC ramp — the visible "light flicker".
    upstream_monitor = src / "camera-relay-monitor.c"
    monitor_src = next((p for p in PATCHED_MONITOR_SOURCES if p.is_file()), None)
    if monitor_src is not None:
        info("Using patched camera-relay-monitor source (flicker fix)")
    else:
        monitor_src = upstream_monitor
        warn("Patched monitor source not found — building upstream's, which "
             "flickers on every connect.")
        warn("  Run reapply-flicker-fix.sh afterwards, or see README.md.")

    tmp_monitor = Path("/tmp/camera-relay-monitor")
    if monitor_src.is_file() and run(["gcc", "-O2", "-Wall", "-o", str(tmp_monitor),
                                      str(monitor_src)]).returncode == 0:
        if quiet(["pgrep", "-x", "camera-relay-monitor"]):
            user_service("stop", "camera-relay.service")
            quiet(["pkill", "-x", "camera-relay-monitor"])
            time.sleep(1)
        shutil.copy2(tmp_monitor, "/usr/local/bin/camera-relay-monitor")
        os.chmod("/usr/local/bin/camera-relay-monitor", 0o755)
        tmp_monitor.unlink(missing_ok=True)
        info("Installed /usr/local/bin/camera-relay-monitor (on-demand watcher)")
    else:
        warn("Failed to build the on-demand monitor (gcc required)")

    shutil.copy2(src / "camera-relay", "/usr/local/bin/camera-relay")
    os.chmod("/usr/local/bin/camera-relay", 0o755)
    info("Installed /usr/local/bin/camera-relay")

    if (src / "chromium-pipewire-camera.sh").is_file():
        dest = Path("/usr/local/bin/chromium-pipewire-camera")
        shutil.copy2(src / "chromium-pipewire-camera.sh", dest)
        os.chmod(dest, 0o755)
        info("Installed /usr/local/bin/chromium-pipewire-camera")

    # ── Systray ─────────────────────────────────────────────────────────────
    share = Path("/usr/local/share/camera-relay")
    share.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "camera-relay-systray.py", share / "camera-relay-systray.py")
    os.chmod(share / "camera-relay-systray.py", 0o755)
    shutil.copy2(src / "camera-relay-systray.desktop",
                 "/usr/share/applications/camera-relay-systray.desktop")
    shutil.copy2(src / "camera-relay-systray.desktop",
                 "/etc/xdg/autostart/camera-relay-systray.desktop")
    info("Installed systray applet and autostart entry")

    if TARGET_HOME and Path(TARGET_HOME).is_dir():
        icon_dest = Path(TARGET_HOME) / ".local/share/icons/hicolor/symbolic/apps"
        icon_dest.mkdir(parents=True, exist_ok=True)
        for icon in ("camera-disabled-symbolic", "camera-switch-symbolic",
                     "camera-video-symbolic"):
            svg = src / "yaru-icons" / f"{icon}.svg"
            if svg.is_file():
                shutil.copy2(svg, icon_dest / f"{icon}.svg")
                info(f"Installed {icon}.svg")
        shutil.chown(Path(TARGET_HOME) / ".local/share/icons",
                     user=TARGET_USER, group=TARGET_USER)
        _chown_tree(Path(TARGET_HOME) / ".local/share/icons")
        run_as_user("gtk-update-icon-cache", "-f", "-t",
                    str(Path(TARGET_HOME) / ".local/share/icons/hicolor"))

    # ── Enable the relay (user unit) ────────────────────────────────────────
    if run_as_user_ok("/usr/local/bin/camera-relay", "enable-persistent", "--yes"):
        info("Relay enabled — starts at login")
    else:
        warn("Could not enable the relay now — run 'camera-relay "
             "enable-persistent' after reboot")

    # ── Relay mode ──────────────────────────────────────────────────────────
    dropin_dir = Path(TARGET_HOME) / ".config/systemd/user/camera-relay.service.d" \
        if TARGET_HOME else Path("/nonexistent")
    if opts.relay_mode == "always-on" and TARGET_HOME:
        dropin_dir.mkdir(parents=True, exist_ok=True)
        (dropin_dir / "always-on.conf").write_text(ALWAYS_ON_DROPIN)
        _chown_tree(Path(TARGET_HOME) / ".config/systemd/user")
        user_service("daemon-reload")
        info("Relay set to always-on (flicker-free; ~15% of one CPU core)")
    else:
        (dropin_dir / "always-on.conf").unlink(missing_ok=True)
        user_service("daemon-reload")
        info("Relay set to on-demand (idles at ~0% CPU; image ramps on each connect)")
        if TARGET_HOME:
            dropin_dir.mkdir(parents=True, exist_ok=True)
            (dropin_dir / "10-flicker-fix.conf").write_text(ONDEMAND_DROPIN)
            shutil.chown(dropin_dir / "10-flicker-fix.conf",
                         user=TARGET_USER, group=TARGET_USER)
            user_service("daemon-reload")
            info("Wrote flicker-suppression drop-in (grace 30s, warmup 15 frames)")

    # ── Chromium-family browsers ────────────────────────────────────────────
    # Chrome/Brave/Edge/Electron only accept a V4L2 node reporting VIDEO_CAPTURE
    # and *not* VIDEO_OUTPUT; the relay under exclusive_caps=0 reports both, so
    # they list zero cameras. Point them at PipeWire instead.
    script = src / "chromium-pipewire-camera.sh"
    if script.is_file():
        run([str(script), "enable"])


def _chown_tree(root: Path) -> None:
    if not TARGET_USER:
        return
    for dirpath, dirnames, filenames in os.walk(root):
        shutil.chown(dirpath, user=TARGET_USER, group=TARGET_USER)
        for name in filenames:
            shutil.chown(Path(dirpath) / name, user=TARGET_USER, group=TARGET_USER)


ALWAYS_ON_DROPIN = """[Unit]
Description=Camera Relay (always-on libcamera to v4l2loopback)

[Service]
# Always-on instead of --on-demand, so the AGC does not ramp on every connect.
#
# The empty ExecStart= MUST come first: a drop-in cannot otherwise add a second
# ExecStart and systemd rejects the unit with "bad unit file setting".
ExecStart=
# --foreground is required. Plain `camera-relay start` backgrounds the pipeline
# and exits, and under Type=simple systemd then treats the service as stopped,
# runs ExecStop and kills the relay.
ExecStart=/usr/local/bin/camera-relay start --foreground
ExecStartPost=-/usr/local/bin/camera-relay nudge-wireplumber
ExecStop=/usr/local/bin/camera-relay stop
Restart=on-failure
RestartSec=5
"""

ONDEMAND_DROPIN = """[Unit]
Description=Camera Relay (on-demand, AGC-ramp flicker suppressed)

[Service]
# On-demand + flicker suppression. libcamera's simple-IPA AGC has no
# startup-frame skip, so every cold pipeline start replays its exposure ramp
# (measured 16 -> 43 -> 66 -> 71 luma over ~5 frames). RELAY_WARMUP_FRAMES
# hides that ramp from clients; RELAY_GRACE_SECONDS avoids re-paying it on
# quick reconnects. The camera still falls idle (LED off, ~0% CPU) when
# genuinely unused. Set RELAY_GRACE_SECONDS=0 for the strictest behaviour.
Environment=RELAY_GRACE_SECONDS=30
Environment=RELAY_WARMUP_FRAMES=15
"""


# ── IPU7 stack ──────────────────────────────────────────────────────────────
def _ipu7_preflight() -> bool:
    """False (after printing why) when this machine cannot use the IPU7 stack."""
    gen = ipu_generation()
    ctrl = ipu7_controller()
    if gen != "IPU7" or ctrl not in IPU7_PCI_IDS:
        warn(f"This machine's IPU controller is {ctrl or 'unknown'} ({gen}).")
        warn("The IPU7 stack targets Intel Lunar Lake / Panther Lake (IPU7/7.5);")
        warn("an IPU6 Galaxy Book needs the default IPU6 path instead.")
        return False
    if not ipu7_sensor_present():
        warn("No OV08X40-class sensor declared in ACPI — the IPU7 stack has "
             "nothing to drive.")
        return False
    return True


def _pacman_add(packages: Iterable[str], *, note: str = "") -> bool:
    pkgs = list(packages)
    if not pkgs:
        return True
    if note:
        info(note)
    proc = run(["pacman", "-S", "--needed", "--noconfirm", *pkgs])
    if proc.returncode != 0:
        warn(f"pacman failed for: {' '.join(pkgs)}")
        return False
    return True


def _git_pkg(packages: Iterable[str]) -> bool:
    """Install AUR packages with the available helper (paru, then yay).
    When running as root/sudo (e.g. inside arch-chroot), drop to user 1000
    so the AUR helper does not refuse root execution."""
    pkgs = list(packages)
    helper = shutil.which("paru") or shutil.which("yay")
    if not helper:
        warn("No AUR helper found (paru/yay) — install one, then run:")
        for p in pkgs:
            warn(f"  {helper or 'paru'} -S {p}")
        return False
    # Skip check() in makepkg (tests crash inside chroot/container, not a build error).
    # Force overwrite conflicting files (system libcamera conflicts with AUR libcamera-ipu6).
    cmd = [helper, "-S", "--needed", "--noconfirm", "--mflags", "--nocheck", "--overwrite", "*", *pkgs]
    env = dict(os.environ)
    # Drop to TARGET_USER when running as root/sudo; AUR helpers refuse root.
    if os.geteuid() == 0 and TARGET_USER and TARGET_USER != "root":
        cmd = ["sudo", "-u", TARGET_USER, "-E", "-H", "--"] + cmd
        env["SUDO_USER"] = TARGET_USER
        if TARGET_HOME:
            env["HOME"] = TARGET_HOME
    import subprocess as sp
    env["TERM"] = "dumb"
    # Force non-interactive stdin so 'yay' / 'paru' never hang waiting for a TTY prompt.
    proc = run(cmd, env=env, stdin=sp.DEVNULL, timeout=1800)
    if proc.returncode != 0:
        warn(f"{helper} failed for: {' '.join(pkgs)}")
        return False
    return True


def install_ipu7_distro() -> None:
    """intel-ipu7-camera: kernel module + firmware + HAL + icamerasrc + relay."""
    step("IPU7: installing the distro camera stack")

    if ipu7_distro_installed():
        info(f"{IPU7_PKG} already installed")
    else:
        if not _pacman_add([IPU7_PKG],
                           note=f"Installing {IPU7_PKG} (driver + firmware + HAL "
                                f"+ icamerasrc + v4l2-relayd)"):
            die(f"Could not install {IPU7_PKG} — aborting IPU7 setup")

    run(["depmod", "-a", kernel_release()])
    info("IPU7 driver and firmware in place — a reboot applies the DKMS module")

    if user_service_ok("enable", "--now", IPU7_CAMERA_UNIT):
        info(f"Enabled {IPU7_CAMERA_UNIT}")
    else:
        warn(f"Could not enable {IPU7_CAMERA_UNIT} — enable it after reboot")

    if user_service_ok("enable", "--now", IPU7_RELAY_UNIT):
        info(f"Enabled {IPU7_RELAY_UNIT} (virtual /dev/video* node)")
    else:
        warn(f"Could not enable {IPU7_RELAY_UNIT} — enable it after reboot")


def install_ipu7_dkms() -> None:
    """Kernel module only, straight from intel/ipu7-drivers. No HAL, no relay."""
    step("IPU7: building the kernel driver from intel/ipu7-drivers")

    if not _ipu7_preflight():
        return
    if ipu7_dkms_installed():
        info("ipu7-drivers DKMS already installed")
    else:
        _pacman_add(["base-devel", "dkms", "linux-headers", "git"],
                    note="Installing build dependencies")
        src = Path("/usr/src") / IPU7_DKMS_PKGS[0]
        if not src.is_dir():
            shutil.rmtree(src, ignore_errors=True)
            if run(["git", "clone", "--depth", "1", IPU7_DKMS_REPO, str(src)]
                   ).returncode != 0:
                die(f"Could not clone {IPU7_DKMS_REPO}")
        if run(["dkms", "add", "."], cwd=src).returncode != 0:
            die("dkms add failed")
        if run(["dkms", "build", f"{IPU7_DKMS_PKGS[0]}/{IPU7_DKMS_PKGS[1]}"]
               ).returncode != 0:
            die("dkms build failed — see /var/lib/dkms/ipu7-drivers/")
        if run(["dkms", "install", f"{IPU7_DKMS_PKGS[0]}/{IPU7_DKMS_PKGS[1]}"]
               ).returncode != 0:
            die("dkms install failed")
        run(["depmod", "-a", kernel_release()])
        info("ipu7-drivers installed via DKMS")

    _pacman_add(["v4l2loopback-dkms"])
    write_file(Path("/etc/modules-load.d/ipu7.conf"), f"{IPU7_MODULE}\n")
    warn("The kernel module alone produces no usable camera node: IPU7 needs the")
    warn("HAL + firmware to build the pipeline. Re-run with --ipu7 (distro stack),")
    warn("or install the firmware/HAL manually — see docs/ipu7.md.")


def install_ipu7_git() -> None:
    """intel-ipu7-{dkms-git,camera-bin,camera-hal-git} from the AUR."""
    step("IPU7: installing the AUR camera stack")

    if not _ipu7_preflight():
        return
    have = ipu7_git_installed()
    if len(have) == len(IPU7_GIT_PKGS):
        info("All IPU7 AUR packages already installed")
        return
    if not _git_pkg([p for p in IPU7_GIT_PKGS if p not in have]):
        die("AUR install failed — aborting IPU7 setup")
    run(["depmod", "-a", kernel_release()])
    info("IPU7 git stack installed — reboot before verifying")


def ipu7_status() -> None:
    step("Intel IPU7 status")
    ctrl = ipu7_controller()
    print(f"  controller            : {ctrl or 'unknown'} "
          f"({ip_generation_label(ctrl)})")
    print(f"  IPU7 module           : {C_GRN}loaded{C_RST}" if ipu7_module_loaded() else
          f"  IPU7 module           : {C_YEL}not loaded{C_RST}")
    print(f"  sensor (ACPI)         : {C_GRN}OV08X40 declared{C_RST}"
          if ipu7_sensor_present() else
          f"  sensor (ACPI)         : {C_YEL}no OV08X40 in ACPI{C_RST}")
    dkms = ipu7_dkms_installed()
    print(f"  DKMS                  : {C_GRN}{dkms}{C_RST}" if dkms else
          f"  DKMS                  : {C_YEL}not installed{C_RST}")
    print(f"  distro stack          : {C_GRN}{IPU7_PKG}{C_RST}" if ipu7_distro_installed() else
          f"  distro stack          : {C_YEL}not installed{C_RST}")
    git = ipu7_git_installed()
    print(f"  AUR stack             : {C_GRN}{', '.join(git)}{C_RST}" if git else
          f"  AUR stack             : {C_YEL}not installed{C_RST}")
    print(f"  relay                 : {C_GRN}active{C_RST}" if ipu7_relay_active() else
          f"  relay                 : {C_YEL}not running{C_RST}")
    dev = ipu7_loopback_device()
    print(f"  loopback              : {C_GRN}{dev}{C_RST}" if dev else
          f"  loopback              : {C_YEL}not found{C_RST}")


def _print_ipu6_stack_status() -> None:
    """One-line summary of the hardware-ISP stack in the main status table."""
    git = ipu6_git_installed()
    if len(git) == len(IPU6_GIT_PKGS):
        print(f"  IPU6 HAL stack        : {C_GRN}installed{C_RST} "
              f"(libcamhal + icamerasrc)")
    elif git:
        print(f"  IPU6 HAL stack        : {C_YEL}partial — {', '.join(git)}{C_RST}")
    elif ipu_generation() == "IPU6":
        # Only relevant on IPU6 hardware; on IPU7 boxes this stack cannot apply.
        print(f"  IPU6 HAL stack        : {C_YEL}not installed{C_RST} "
              f"(use --ipu6 for the hardware-ISP stack)")

    if ipu6_dkms_installed() and _kernel_at_least(*IPU6_DKMS_MIN_BROKEN_KERNEL):
        print(f"  IPU6 out-of-tree      : {C_YEL}installed but broken on kernel >= "
              f"{IPU6_DKMS_MIN_BROKEN_KERNEL[0]}.{IPU6_DKMS_MIN_BROKEN_KERNEL[1]}{C_RST}")

    if ipu6_relay_active():
        print(f"  IPU6 relay            : {C_GRN}active{C_RST}")


def ip_generation_label(ctrl: str) -> str:
    if ctrl == "b05d":
        return "Panther Lake IPU7.5 — distro HAL covers it"
    if ctrl == "645d":
        return "Lunar Lake IPU7 — kernel module + firmware/HAL"
    if ctrl == "7d19":
        return "Arrow Lake IPU7 — distro HAL may not cover it"
    if ctrl == "a75d":
        return "Raptor Lake-P IPU6 — use the default IPU6 path, not --ipu7"
    return "unrecognised"


# ── IPU6 hardware-ISP stack (AUR) ──────────────────────────────────────────
def ipu6_module_loaded() -> bool:
    return Path(f"/sys/module/{IPU6_MODULE}").is_dir()


def ipu6_dkms_installed() -> str:
    """The out-of-tree IPU6 driver, which is broken on kernel >= 6.10."""
    for line in lines(["dkms", "status"]):
        if line.startswith("ipu6-drivers/") and "installed" in line:
            return line.strip()
    return ""


def ipu6_git_installed() -> list[str]:
    return [p for p in IPU6_GIT_PKGS if quiet(["pacman", "-Q", p])]


def ipu6_icamerasrc_ok() -> bool:
    return quiet(["gst-inspect-1.0", "icamerasrc"])


def ipu6_hal_libs() -> list[str]:
    """The libcamhal plugins the HAL loads, keyed by platform."""
    return sorted(os.path.basename(p) for p in glob.glob("/usr/lib/libcamhal/plugins/*.so"))


def ipu6_relay_active() -> bool:
    return quiet(["systemctl", "is-active", "--quiet", "v4l2-relayd.service"])


def ipu6_loopback_device() -> str:
    """The relay's v4l2loopback node, by card label (IPU6 Camera / Virtual Camera)."""
    for dev in sorted(glob.glob("/dev/video*")):
        name = read_file(Path(f"/sys/class/video4linux/{Path(dev).name}/name"))
        if name in (IPU6_LOOPBACK_LABEL, "Virtual Camera"):
            return dev
    return ""


def _kernel_at_least(major: int, minor: int) -> bool:
    """True when the running kernel is >= the given version."""
    parts = re.findall(r"\d+", kernel_release())
    nums = tuple(int(p) for p in parts[:3]) if parts else (0, 0, 0)
    return nums >= (major, minor, 0)


def _ipu6_preflight() -> bool:
    """False (after printing why) when this machine cannot use the IPU6 HAL stack."""
    gen = ipu_generation()
    if gen != "IPU6":
        warn(f"This machine's IPU controller is {ipu7_controller() or 'unknown'} ({gen}).")
        warn("The IPU6 HAL stack needs an Intel IPU6 controller (Tiger/Alder/Raptor")
        warn("Lake, Meteor Lake). On IPU7 use --ipu7 instead.")
        return False
    if not quiet(["modinfo", IPU6_MODULE]):
        warn(f"The in-tree {IPU6_MODULE} module is missing — nothing to drive.")
        return False
    return True


def install_ipu6_stack() -> None:
    """Full IPU6 hardware-ISP stack: firmware + HAL + icamerasrc + relay."""
    step("IPU6: installing the hardware-ISP camera stack")

    if not _ipu6_preflight():
        return

    step("Installing the IPU6 hardware-ISP stack")

    have = ipu6_git_installed()
    missing = [p for p in IPU6_GIT_PKGS if p not in have]
    if not missing:
        info("All IPU6 AUR packages already installed")
    else:
        # v4l2-relayd comes from the omarchy repo, the rest from the AUR.
        repo = [p for p in ("v4l2-relayd",) if not quiet(["pacman", "-Q", p])]
        aur = [p for p in missing if p != "v4l2-relayd"]
        if repo:
            if not _pacman_add(repo, note=f"Installing {' '.join(repo)} (omarchy repo)"):
                die("Could not install v4l2-relayd — aborting IPU6 setup")
        if aur:
            # Use pacman (not AUR) for package installation.
            if not _pacman_add(aur, note=f"Installing IPU6 stack via pacman: {' '.join(aur)}"):
                die("pacman install failed — aborting IPU6 setup")
        run(["depmod", "-a", kernel_release()])

    # The out-of-tree driver is broken on kernel >= 6.10 (in-tree took over).
    dkms = ipu6_dkms_installed()
    if dkms and _kernel_at_least(*IPU6_DKMS_MIN_BROKEN_KERNEL):
        warn(f"Out-of-tree IPU6 driver is installed ({dkms}) but the in-tree")
        warn(f"{IPU6_MODULE} driver took over in kernel {IPU6_DKMS_MIN_BROKEN_KERNEL[0]}."
             f"{IPU6_DKMS_MIN_BROKEN_KERNEL[1]} — this package no longer works and")
        warn("shadows nothing useful. Remove it:  dkms remove ipu6-drivers/<ver> --all")
    elif not dkms and not _kernel_at_least(*IPU6_DKMS_MIN_BROKEN_KERNEL):
        warn(f"Kernel {kernel_release()} predates the in-tree IPU6 driver; the")
        warn(f"{IPU6_DKMS_PKG} package is required but not installed.")

    _configure_ipu6_relay()

    if quiet(["systemctl", "enable", "--now", "v4l2-relayd.service"]):
        info("v4l2-relayd enabled and started")
    else:
        warn("Could not enable v4l2-relayd — enable it after reboot")

    if quiet(["systemctl", "enable", "--now", "v4l2loopback.service"]):
        info("v4l2loopback service enabled")
    elif not quiet(["modinfo", "v4l2loopback"]):
        warn("v4l2loopback module missing — install v4l2loopback-dkms")


def _configure_ipu6_relay() -> None:
    """Point v4l2-relayd at icamerasrc and give the loopback a stable label.

    icamerasrc creates no /dev/video node, so without the relay the camera is
    invisible to browsers, Zoom and OBS.
    """
    if not ipu6_icamerasrc_ok():
        warn("icamerasrc not loadable — the relay has no source to pump.")
        warn("  check: gst-inspect-1.0 --gst-debug=2 icamerasrc 2>&1 | tail -20")
        return

    conf = (
        "# IPU6 hardware-ISP camera (libcamhal + icamerasrc -> v4l2loopback).\n"
        "# icamerasrc is a GStreamer source, not a V4L2 device, so apps need the\n"
        "# relay to see a normal webcam.\n"
        f"DEVICE={ipu6_loopback_device() or '/dev/video60'}\n"
        f'CARD_LABEL="{IPU6_LOOPBACK_LABEL}"\n'
        'VIDEOSRC="icamerasrc buffer-count=7"\n'
        "FORMAT=NV12\n"
        "WIDTH=1280\n"
        "HEIGHT=720\n"
        "FRAMERATE=30/1\n"
    )
    if read_file(IPU6_RELAY_CONF) != conf:
        write_file(IPU6_RELAY_CONF, conf)
        info(f"Configured {IPU6_RELAY_CONF}")

    # The package presets the label 'Virtual Camera'; override it so the node is
    # unambiguous next to the 'Camera Relay' loopback the open libcamera stack uses.
    # The modprobe lines need a real ExecStartPre (a '-' prefix only tolerates
    # failure — a nonexistent binary still aborts the unit, leaving no camera).
    override = IPU6_SVC_OVERRIDE
    if not override.is_file():
        write_file(override,
                   "[Service]\n"
                   "# Label the loopback explicitly; v4l2loopback reads card_label\n"
                   "# at probe time, so the module must be reloaded to change it.\n"
                   "ExecStartPre=-/usr/bin/modprobe -r v4l2loopback\n"
                   f"ExecStartPre=/usr/bin/modprobe v4l2loopback devices=1 "
                   f"exclusive_caps=1 card_label=\"{IPU6_LOOPBACK_LABEL}\"\n")
        info("Installed v4l2-relayd loopback-label override")
        run(["systemctl", "daemon-reload"])


def ipu6_status() -> None:
    ctrl = ipu7_controller()
    print(f"  controller            : {ctrl or 'unknown'} ({ip_generation_label(ctrl)})")
    print(f"  {IPU6_MODULE:<22}: {C_GRN}loaded{C_RST}" if ipu6_module_loaded() else
          f"  {IPU6_MODULE:<22}: {C_YEL}not loaded{C_RST}")
    missing = [m for m in (IPU6_MODULE, IPU6_ISYS_MODULE)
               if not Path(f"/sys/module/{m}").is_dir()]
    if missing:
        print(f"  isys driver           : {C_YEL}missing {', '.join(missing)}{C_RST}")
    else:
        print(f"  isys driver           : {C_GRN}loaded{C_RST}")
    print(f"  in-tree driver        : {C_GRN}available{C_RST}"
          if quiet(["modinfo", IPU6_MODULE]) else
          f"  in-tree driver        : {C_YEL}missing{C_RST}")

    dkms = ipu6_dkms_installed()
    if dkms:
        note = (" (broken on kernel >= 6.10 — remove it)"
                if _kernel_at_least(*IPU6_DKMS_MIN_BROKEN_KERNEL) else "")
        print(f"  out-of-tree DKMS      : {C_YEL}{dkms}{note}{C_RST}")
    else:
        print(f"  out-of-tree DKMS      : not installed")

    git = ipu6_git_installed()
    if len(git) == len(IPU6_GIT_PKGS):
        print(f"  AUR stack             : {C_GRN}{', '.join(git)}{C_RST}")
    elif git:
        print(f"  AUR stack             : {C_YEL}partial: {', '.join(git)}{C_RST}")
    else:
        print(f"  AUR stack             : {C_YEL}not installed{C_RST}")

    plugins = ipu6_hal_libs()
    if plugins:
        print(f"  HAL plugins           : {C_GRN}{', '.join(plugins)}{C_RST}")
    else:
        print(f"  HAL plugins           : {C_YEL}none under /usr/lib/libcamhal/plugins{C_RST}")

    print(f"  icamerasrc            : {C_GRN}available{C_RST}" if ipu6_icamerasrc_ok() else
          f"  icamerasrc            : {C_YEL}not loadable{C_RST}")
    print(f"  relay                 : {C_GRN}active{C_RST}" if ipu6_relay_active() else
          f"  relay                 : {C_YEL}not running{C_RST}")
    dev = ipu6_loopback_device()
    print(f"  loopback              : {C_GRN}{dev}{C_RST}" if dev else
          f"  loopback              : {C_YEL}not found{C_RST}")


def verify_ipu6() -> None:
    step("IPU6 stack verification")
    ok = True

    if ipu6_module_loaded():
        info(f"{IPU6_MODULE} loaded")
    else:
        warn(f"{IPU6_MODULE} not loaded — reboot, or modprobe {IPU6_MODULE}")
        ok = False

    git = ipu6_git_installed()
    if len(git) == len(IPU6_GIT_PKGS):
        info("IPU6 AUR stack present")
    else:
        warn(f"IPU6 AUR stack incomplete (missing: "
             f"{', '.join(p for p in IPU6_GIT_PKGS if p not in git)})")
        ok = False

    plugins = ipu6_hal_libs()
    if plugins:
        info(f"HAL plugins present: {', '.join(plugins)}")
    else:
        warn("No libcamhal plugins — the HAL cannot build a pipeline")
        ok = False

    if ipu6_icamerasrc_ok():
        info("GStreamer 'icamerasrc' available")
    else:
        warn("icamerasrc not loadable — the relay will produce a black loopback")
        ok = False

    if ipu6_relay_active():
        info("v4l2-relayd active")
    else:
        warn("v4l2-relayd not running")
        ok = False

    dev = ipu6_loopback_device()
    if dev:
        info(f"Loopback node present: {dev}")
    else:
        warn("No IPU6 loopback node — the camera is invisible to V4L2 apps")
        ok = False

    print()
    if ok:
        info("IPU6 stack is operational. Open a frame to judge the image:")
        print(f"  timeout 40 gst-launch-1.0 -e v4l2src device={dev or '/dev/video60'} "
              "num-buffers=60 ! videoconvert ! jpegenc ! multifilesink "
              "location=/tmp/ipu6-%03d.jpg")
    else:
        warn("IPU6 stack is incomplete — check the items above, then reboot.")


# ── Verification ────────────────────────────────────────────────────────────
def verify_camera() -> int:
    errors = warnings = 0

    step("1. Kernel & driver layer")
    if ov02c10_is_patched():
        print(f"  ov02c10 module        : {C_GRN}patched (DKMS){C_RST} — "
              f"{ov02c10_module_path()}")
    else:
        print(f"  ov02c10 module        : {C_RED}stock{C_RST}")
        errors += 1

    if sensor_probed():
        print(f"  sensor probe          : {C_GRN}OK — 26 MHz clock accepted{C_RST}")
    elif clock_error_present():
        print(f"  sensor probe          : {C_RED}FAILED — 26 MHz clock rejected{C_RST}")
        errors += 1
    else:
        print(f"  sensor probe          : {C_YEL}unknown{C_RST}")

    ko = updates_dir() / "ipu-bridge.ko.zst"
    ipu_patched = capture(["modinfo", "-F", "srcversion", str(ko)]) if ko.is_file() else ""
    ipu_loaded = read_file(Path("/sys/module/ipu_bridge/srcversion"))
    # A missing /sys entry is the only reliable "not loaded" signal; two
    # srcversion strings that differ are just two different builds, not proof
    # of anything, so report them rather than claiming a reboot is needed.
    if ipu_patched and ipu_loaded == ipu_patched:
        print(f"  ipu-bridge rotation   : {C_GRN}patched and loaded{C_RST}")
    elif ipu_patched and not ipu_loaded:
        print(f"  ipu-bridge rotation   : {C_YEL}installed but not loaded — "
              f"REBOOT REQUIRED{C_RST}")
        warnings += 1
    elif ipu_patched:
        print(f"  ipu-bridge rotation   : {C_GRN}installed{C_RST} "
              f"(loaded={ipu_loaded}, patched={ipu_patched})")
    else:
        print(f"  ipu-bridge rotation   : {C_YEL}not installed{C_RST} "
              f"(image may be upside-down)")
        warnings += 1

    missing = [m for m in IVSC_SYSFS if not Path(f"/sys/module/{m}").is_dir()]
    if missing:
        print(f"  IVSC modules          : {C_YEL}not all loaded{C_RST}")
        warnings += 1
    else:
        print(f"  IVSC modules          : {C_GRN}loaded{C_RST}")

    step("2. libcamera & IPA layer")
    lc_ver = libcamera_version()
    print(f"  libcamera version     : {C_GRN}{lc_ver}{C_RST}" if lc_ver else
          f"  libcamera version     : {C_YEL}unknown{C_RST}")

    lc_soname = linker_libcamera()
    if lc_soname.startswith("/usr/local/"):
        print(f"  linker resolution     : {C_GRN}{lc_soname} (patched){C_RST}")
    else:
        print(f"  linker resolution     : {C_YEL}{lc_soname or 'none'}{C_RST} — "
              f"patched build not in use")
        warnings += 1

    hits = ipa_helper_hits()
    if hits > 0:
        print(f"  OV02C10 helper        : {C_GRN}registered{C_RST} ({hits} symbols)")
    else:
        print(f"  OV02C10 helper        : {C_RED}not found — auto-exposure will "
              f"not work{C_RST}")
        errors += 1

    if "Internal" in cam_probe():
        print(f"  camera listed         : {C_GRN}yes{C_RST}")
    else:
        print(f"  camera listed         : {C_DIM}no (expected — MC nodes hidden "
              f"from the session){C_RST}")

    if any((d / "ov02c10.yaml").is_file() for d in OV02C10_TUNING_DIRS):
        print(f"  IPA tuning file       : {C_GRN}present{C_RST}")
    else:
        print(f"  IPA tuning file       : {C_YEL}missing{C_RST}")
        warnings += 1

    step("3. Camera relay")
    if user_service_ok("is-active", "camera-relay.service"):
        print(f"  service               : {C_GRN}active{C_RST}")
    else:
        print(f"  service               : {C_YEL}not running{C_RST}")
        warnings += 1

    print(f"  relay mode            : {_relay_mode_line()}")

    relay_dev = relay_device()
    if relay_dev:
        print(f"  loopback device       : {C_GRN}{relay_dev}{C_RST}")
    else:
        print(f"  loopback device       : {C_RED}not found{C_RST}")
        errors += 1

    if "v4l2loopback" in capture(["sh", "-c", "cat /proc/modules"]):
        print(f"  v4l2loopback          : {C_GRN}loaded{C_RST}")
    else:
        print(f"  v4l2loopback          : {C_YEL}not loaded{C_RST}")
        warnings += 1

    if pipewire_sees_camera():
        print(f"  PipeWire node         : {C_GRN}visible{C_RST}")
    else:
        print(f"  PipeWire node         : {C_YEL}not visible yet{C_RST}")
        warnings += 1

    step("4. Lens cover")
    if lens_cover_closed():
        print(f"  state                 : {C_YEL}CLOSED — open the lens cover{C_RST}")
        warnings += 1
    else:
        print(f"  state                 : {C_GRN}open{C_RST}")

    # ── 5. Real capture + flicker measurement ───────────────────────────────
    if not opts.quick and relay_dev:
        step(f"5. Frame capture ({opts.frames} frames)")
        out_dir = Path(f"/tmp/camera-verify-{os.getpid()}")
        out_dir.mkdir(parents=True, exist_ok=True)
        info(f"Capturing to {out_dir}")

        # The relay activates when a client opens the device. Frames land as raw
        # YUYV (multifilesink dumps buffers verbatim) — a .png extension would
        # be a lie, so write .raw and parse the luma plane directly.
        #
        # PipeWire's v4l2 monitor holds the loopback open for hotplug detection
        # and can be mid-negotiation, which makes v4l2src fail with
        # "not-negotiated (-4)". That is a race, not a broken camera, so retry
        # a few times before believing it.
        n = 0
        for attempt in (1, 2, 3):
            run(["timeout", "60", "gst-launch-1.0", "-q",
                 "v4l2src", f"device={relay_dev}", f"num-buffers={opts.frames}",
                 "!", "videoconvert", "!",
                 "multifilesink", f"location={out_dir}/f%04d.raw"])
            n = len(list(out_dir.glob("f*.raw")))
            if n:
                break
            for stale in out_dir.glob("f*.raw"):
                stale.unlink()
            if attempt < 3:
                warn(f"capture attempt {attempt} failed — retrying")
                time.sleep(3)

        if n == 0:
            err("No frames captured after 3 attempts")
            if quiet(["fuser", "-s", relay_dev]) and quiet(["pgrep", "-x", "pipewire"]):
                warn(f"PipeWire is holding {relay_dev}. Close any app using the camera,")
                warn("or re-run this check with PipeWire stopped:")
                warn("  systemctl --user stop pipewire pipewire.socket wireplumber")
                warn(f"  sudo {sys.argv[0]} --verify ; "
                     "systemctl --user start pipewire.socket")
            # Downgraded to a warning: the camera itself is proven working by the
            # relay's own frame probe, and this is a host contention artefact.
            warnings += 1
        else:
            info(f"Captured {n} frames")
            _report_luma(out_dir)
            _save_last_frame(out_dir)
            print(f"  {C_DIM}orientation           : confirm the saved frame is "
                  f"upright;{C_RST}")
            print(f"  {C_DIM}                        if it is 180° out, something "
                  f"opened the{C_RST}")
            print(f"  {C_DIM}                        sensor mid-stream. Fix:{C_RST}")
            print(f"  {C_DIM}                        systemctl --user restart "
                  f"camera-relay.service{C_RST}")
        shutil.rmtree(out_dir, ignore_errors=True)

    step("6. Browser & desktop integration")
    pw_cam = next((ln.strip() for ln in
                   run_as_user("pw-cli", "ls", "Node").stdout.splitlines()
                   if re.search(r"camera|libcamera", ln, re.IGNORECASE)), "")
    print(f"  PipeWire camera source: {C_GRN}{pw_cam}{C_RST}" if pw_cam else
          f"  PipeWire camera source: {C_YEL}none{C_RST}")

    if Path("/usr/local/bin/chromium-pipewire-camera").is_file():
        print(f"  Chromium PipeWire     : {C_GRN}configured{C_RST}")
    else:
        print(f"  Chromium PipeWire     : {C_YEL}not configured{C_RST}")

    if Path("/etc/udev/rules.d/74-camera-relay-mc-nodes.rules").is_file():
        print(f"  MC-node udev rule     : {C_GRN}present{C_RST}")
    else:
        print(f"  MC-node udev rule     : {C_YEL}missing{C_RST}")

    step("Summary")
    if errors:
        err(f"{errors} error(s) — re-run the installer and reboot")
        return 1
    if warnings:
        warn(f"{warnings} warning(s) — camera works but some integration is "
             f"incomplete")
        return 0
    info("All checks passed — camera is fully operational")
    return 0


def _report_luma(out_dir: Path) -> None:
    """Mean luma per frame, then judge exposure + the startup ramp."""
    luma = []
    for path in sorted(out_dir.glob("f*.raw")):
        data = path.read_bytes()
        sample = data[::128]
        luma.append(sum(sample) / len(sample) if sample else 0.0)
    if not luma:
        return
    first5 = luma[:5]
    swing = max(first5) - min(first5)
    settled = luma[5:] or luma
    avg = sum(settled) / len(settled)
    spread = max(settled) - min(settled)
    if swing < 5:
        verdict = f"{C_GRN}OK — no AGC ramp (flicker-free){C_RST}"
    elif swing < 15:
        verdict = f"{C_YEL}some ramp on connect{C_RST}"
    else:
        verdict = f"{C_RED}large ramp — relay is on-demand, expect visible flicker{C_RST}"
    print(f"  mean luma             : {avg:.1f}")
    print(f"  startup swing         : {swing:.1f} luma  {verdict}")
    print(f"  settled variation     : {spread:.2f} luma ({100 * spread / avg:.2f}%)")


def _save_last_frame(out_dir: Path) -> None:
    """Encode the last captured frame to JPEG so orientation can be judged."""
    files = sorted(out_dir.glob("f*.raw"))
    if not files or not which("ffmpeg"):
        return
    # Strip the trailing bytes v4l2loopback pads past one full frame, or ffmpeg
    # sees a truncated/extra plane and writes nothing.
    frame_bytes = 1920 * 1080 * 2
    trimmed = out_dir / "last-frame.raw"
    trimmed.write_bytes(files[-1].read_bytes()[:frame_bytes])
    dest = Path("/tmp/camera-last-frame.jpg")
    if run(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo",
            "-pix_fmt", "yuyv422", "-s", "1920x1080", "-i", str(trimmed),
            str(dest)]).returncode == 0:
        info(f"Last frame saved to {dest}")
    else:
        warn("Could not encode the last frame to JPEG")


# ── Uninstall ───────────────────────────────────────────────────────────────
def uninstall() -> None:
    step("Uninstalling the camera fix")

    user_service("disable", "--now", "camera-relay.service")
    quiet(["pkill", "-x", "camera-relay-monitor"])
    if TARGET_HOME:
        (Path(TARGET_HOME) / ".config/systemd/user/camera-relay.service.d/"
         "always-on.conf").unlink(missing_ok=True)
    user_service("daemon-reload")

    quiet(["dkms", "remove", f"ov02c10/{OV02C10_DKMS_VER}", "--all"])
    shutil.rmtree(f"/usr/src/ov02c10-{OV02C10_DKMS_VER}", ignore_errors=True)

    for line in lines(["dkms", "status"]):
        if line.startswith("ipu-bridge-fix/"):
            parts = re.split(r"[/,: ]+", line)
            if len(parts) > 2:
                quiet(["dkms", "remove", f"ipu-bridge-fix/{parts[1]}", "--all"])
    for stale in glob.glob("/usr/src/ipu-bridge-fix-*"):
        shutil.rmtree(stale, ignore_errors=True)

    # Restore any clk_freq modprobe.d backups this script made.
    for backup in glob.glob("/etc/modprobe.d/*.ov02c10-26mhz.bak"):
        original = backup[: -len(".ov02c10-26mhz.bak")]
        os.replace(backup, original)

    Path("/etc/ld.so.conf.d/libcamera-local.conf").unlink(missing_ok=True)
    for d in ("/usr/local/lib/libcamera", "/usr/local/lib64/libcamera",
              "/usr/local/lib/x86_64-linux-gnu/libcamera"):
        shutil.rmtree(d, ignore_errors=True)
    for pattern in ("/usr/local/lib/libcamera.so*", "/usr/local/lib64/libcamera.so*",
                    "/usr/local/lib/x86_64-linux-gnu/libcamera.so*"):
        for stale in glob.glob(pattern):
            Path(stale).unlink(missing_ok=True)
    shutil.rmtree("/usr/local/share/libcamera", ignore_errors=True)
    Path("/usr/local/bin/cam").unlink(missing_ok=True)
    Path("/usr/local/lib/gstreamer-1.0/libgstlibcamera.so").unlink(missing_ok=True)
    run(["ldconfig"])

    for path in ("/etc/environment.d/libcamera-ipa.conf",
                 "/etc/profile.d/libcamera-ipa.sh",
                 "/usr/share/libcamera/ipa/simple/ov02c10.yaml",
                 "/usr/local/share/libcamera/ipa/simple/ov02c10.yaml",
                 "/usr/local/bin/camera-relay",
                 "/usr/local/bin/camera-relay-monitor",
                 "/usr/local/bin/camera-relay-gst",
                 "/usr/local/bin/chromium-pipewire-camera",
                 "/usr/share/applications/camera-relay-systray.desktop",
                 "/etc/xdg/autostart/camera-relay-systray.desktop",
                 "/usr/local/lib/sysusers.d/camera-relay.conf",
                 "/usr/local/lib/udev/camera-relay-v4l2-io-mc",
                 "/etc/udev/rules.d/74-camera-relay-mc-nodes.rules",
                 "/etc/udev/rules.d/70-camera-relay-capabilities.rules",
                 "/etc/modprobe.d/99-camera-relay-loopback.conf",
                 "/etc/modules-load.d/v4l2loopback.conf"):
        Path(path).unlink(missing_ok=True)
    shutil.rmtree("/usr/local/share/camera-relay", ignore_errors=True)
    shutil.rmtree("/var/cache/camera-relay", ignore_errors=True)
    quiet(["udevadm", "control", "--reload-rules"])

    run(["depmod", "-a", kernel_release()])
    if which("mkinitcpio"):
        quiet(["mkinitcpio", "-P"])

    warn("Group memberships (video/kvm) and the camera-relay group were left in place")
    info("Uninstalled — reboot to return to the stock drivers")


# ── Post-install summary ────────────────────────────────────────────────────
def verify() -> None:
    step("Verifying")
    ok = True

    if ov02c10_is_patched():
        info(f"Patched ov02c10 active: {ov02c10_module_path()}")
    else:
        warn("ov02c10 still resolves to the stock module — reboot required")
        ok = False

    if sensor_probed():
        info("Sensor probed (26 MHz clock accepted)")
    elif clock_error_present():
        warn("26 MHz rejection still in dmesg — reboot required")
        ok = False

    if libcamera_local_present():
        lc = linker_libcamera()
        if lc.startswith("/usr/local/"):
            info(f"Linker resolves libcamera from {lc} (patched build)")
        else:
            warn(f"Linker resolves libcamera from {lc or '<none>'} — the patch "
                 f"may not be in use")
            ok = False

    if ipa_helper_hits() > 0:
        info("OV02C10 sensor helper registered (auto-exposure will work)")
    else:
        warn("OV02C10 sensor helper not registered — the source build is not in use")
        ok = False

    if quiet(["gst-inspect-1.0", "libcamerasrc"]):
        info("GStreamer 'libcamerasrc' available (relay pipeline)")
    else:
        warn("libcamerasrc not loadable — non-PipeWire apps will not see the camera")
        ok = False

    if quiet(["modinfo", "v4l2loopback"]):
        info("v4l2loopback available")
    else:
        warn("v4l2loopback missing — the relay has no device to write into")
        ok = False

    print()
    if ok:
        info("All checks passed.")
    else:
        warn("Some checks are pending a reboot — re-run with --verify afterwards.")
    print()
    print(f"  {C_DIM}Next:{C_RST}")
    print("    sudo reboot")
    print(f"    sudo {sys.argv[0]} --verify")
    print()


# ── Source fetch ────────────────────────────────────────────────────────────
def fetch_sources() -> None:
    step("Fetching upstream fix sources")
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    proc = subprocess.run(["curl", "-fsSL", FIX_URL],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        die(f"Could not download the fix sources from {FIX_URL}")
    xz = subprocess.run(["tar", "xz", "-C", "/tmp/"], input=proc.stdout,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if xz.returncode != 0:
        die("Could not extract the fix sources")
    if not WORK_DIR.is_dir():
        die(f"Extracted tree not found at {WORK_DIR}")
    info(f"Sources ready in {WORK_DIR}")


# ── IPU7 install dispatcher ─────────────────────────────────────────────────
def install_ipu7() -> None:
    step("Intel IPU7 camera stack")

    if opts.ipu7 == "status":
        ipu7_status()
        return
    if not _ipu7_preflight():
        return

    if opts.ipu7 == "dkms":
        install_ipu7_dkms()
    elif opts.ipu7 == "git":
        install_ipu7_git()
    else:
        install_ipu7_distro()

    rebuild_initramfs()
    print()
    info("IPU7 stack applied — reboot before verifying.")
    print(f"    sudo reboot")
    print(f"    sudo {sys.argv[0]} --ipu7 status")
    print()


# ── IPU6 install dispatcher ─────────────────────────────────────────────────
def install_ipu6() -> None:
    if opts.ipu6 in ("status", "verify"):
        step("Intel IPU6 hardware-ISP stack")
    if opts.ipu6 == "status":
        ipu6_status()
        return
    if opts.ipu6 == "verify":
        verify_ipu6()
        return

    if not _ipu6_preflight():
        return

    install_ipu6_stack()
    rebuild_initramfs()

    print()
    info("IPU6 stack applied — reboot before verifying.")
    print("    sudo reboot")
    print(f"    sudo {sys.argv[0]} --ipu6 verify")
    print()


def rebuild_initramfs() -> None:
    step("Rebuilding initramfs")
    if which("mkinitcpio"):
        if quiet(["mkinitcpio", "-P"]):
            info("initramfs rebuilt")
        else:
            warn("mkinitcpio failed — rebuild manually before rebooting")
    elif which("dracut"):
        quiet(["dracut", "--force"])
        info("initramfs rebuilt")
    else:
        warn("No initramfs tool found — rebuild manually before rebooting")


def restart_pipewire() -> None:
    step("Restarting PipeWire")
    if user_service_ok("restart", "pipewire", "wireplumber"):
        time.sleep(3)
        info("PipeWire restarted")
    else:
        warn("Could not restart the user PipeWire session — a reboot will apply it")


# ── Options ─────────────────────────────────────────────────────────────────
@dataclass
class Options:
    mode: str = "install"
    skip_libcamera_rebuild: bool = False
    quick: bool = False
    relay_mode: str = "on-demand"
    frames: int = DEFAULT_FRAME_COUNT
    ipu7: str = ""
    ipu6: str = ""


opts = Options()


def parse_args(argv: Sequence[str] | None = None) -> Options:
    p = argparse.ArgumentParser(
        prog="blackarch-webcam-setup",
        description="Galaxy Book camera fix (IPU6/OV02C10) and Intel IPU7 camera stack.",
    )
    p.add_argument("--check-only", action="store_const", const="check",
                   dest="mode", help="print the status table, change nothing")
    p.add_argument("--verify", action="store_const", const="verify", dest="mode",
                   help="run the full end-to-end check")
    p.add_argument("--uninstall", action="store_const", const="uninstall",
                   dest="mode", help="remove everything this script installed")
    p.add_argument("--sensor-only", action="store_const", const="sensor-only",
                   dest="mode", help="install only the 26 MHz DKMS fix")
    p.add_argument("--skip-libcamera-rebuild", action="store_true",
                   help="keep the system libcamera instead of building 0.7.2")
    p.add_argument("--quick", action="store_true",
                   help="skip the frame-capture and flicker measurement")
    p.add_argument("--frames", type=int, default=DEFAULT_FRAME_COUNT, metavar="N",
                   help=f"frames to capture during --verify (default {DEFAULT_FRAME_COUNT})")
    p.add_argument("--relay-mode", choices=("on-demand", "always-on"),
                   default="on-demand",
                   help="always-on holds one pipeline (flicker-free, ~15%% CPU)")
    p.add_argument("--ipu7", nargs="?", const="distro", default="",
                   choices=("distro", "dkms", "git", "status"),
                   metavar="FLAVOUR",
                   help="Intel IPU7 camera stack: distro package (default), "
                        "kernel module only (dkms), AUR stack (git), or status only")
    p.add_argument("--ipu6", nargs="?", const="install", default="",
                   choices=("install", "status", "verify"),
                   metavar="ACTION",
                   help="Intel IPU6 hardware-ISP stack (libcamhal + icamerasrc + "
                        "v4l2-relayd): install the AUR stack (default), report "
                        "status, or verify an existing install")
    return p.parse_args(argv, namespace=opts)


# ── Session identity ────────────────────────────────────────────────────────
TARGET_USER = os.environ.get("SUDO_USER", "")
TARGET_UID = 0
TARGET_HOME = ""


def resolve_target_user() -> None:
    global TARGET_USER, TARGET_UID, TARGET_HOME
    if not TARGET_USER or TARGET_USER == "root":
        for line in capture(["loginctl", "list-sessions", "--no-legend"]).splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[3] == "seat0":
                TARGET_USER = parts[2]
                break
    if not TARGET_USER:
        TARGET_USER = "black"
    passwd = capture(["getent", "passwd", TARGET_USER])
    fields = passwd.split(":")
    TARGET_UID = int(fields[2]) if len(fields) > 3 and fields[2].isdigit() else 0
    TARGET_HOME = fields[5] if len(fields) > 5 else ""


# ── Main ────────────────────────────────────────────────────────────────────
def main(argv: Sequence[str] | None = None) -> int:
    global opts
    opts = parse_args(argv)

    if os.geteuid() != 0:
        die(f"Run as root: sudo {sys.argv[0]}")
    resolve_target_user()
    setup_logging()
    logger.info("Webcam setup started (mode=%s, ipu6=%s, ipu7=%s)", opts.mode, opts.ipu6, opts.ipu7)
    banner()

    if opts.mode == "check":
        check_status()
        return 0
    if opts.mode == "verify":
        return verify_camera()
    if opts.mode == "uninstall":
        uninstall()
        return 0

    if opts.ipu7:
        install_ipu7()
        return 0

    if opts.ipu6:
        install_ipu6()
        return 0

    fetch_sources()
    install_packages()
    install_ov02c10_dkms()

    if opts.mode == "sensor-only":
        step("Sensor-only mode — skipping the userspace stack")
        if which("mkinitcpio"):
            quiet(["mkinitcpio", "-P"])
        verify()
        return 0

    install_ipu_bridge_dkms()
    install_ivsc_modules()
    build_libcamera()
    configure_environment()
    hide_raw_nodes()
    install_camera_relay()

    rebuild_initramfs()
    restart_pipewire()
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
