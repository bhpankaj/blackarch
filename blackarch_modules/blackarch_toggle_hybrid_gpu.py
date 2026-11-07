#!/usr/bin/env python3
# blackarch:summary=Toggle dedicated vs integrated GPU mode via supergfxd (for hybrid gpu laptops, like Asus G14).
# blackarch:requires-sudo=true
"""blackarch-toggle-hybrid-gpu -- switch between Integrated and Hybrid GPU mode.

Python port of the bash original. supergfxd is installed on demand with its
config written before the service starts, because a first boot without the
config hangs. The mode is read with a bounded retry, and the switch is applied
only after every supporting file is in place, so a failed step leaves the GPU
config unswitched and safe to retry.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
BLACKARCH_PATH = Path(os.environ.get("BLACKARCH_PATH", "/opt/blackarch"))

GUM = "gum"
SUPERGFXCTL = "supergfxctl"
SUPERSVC = "supergfxd"

SUPERGFXD_CONF = Path("/etc/supergfxd.conf")
DELAY_DROPLET_DIR = Path("/etc/systemd/system/supergfxd.service.d")
DELAY_DROPLET = DELAY_DROPLET_DIR / "delay-start.conf"
FORCE_IGPU_HOOK = Path("/usr/lib/systemd/system-sleep/force-igpu")

# Written before the service starts; a first boot without it hangs.
SUPERGFXD_CONF_BODY = """{
  "mode": "Hybrid",
  "vfio_enable": true,
  "vfio_save": false,
  "always_reboot": false,
  "no_logind": false,
  "logout_timeout_s": 180,
  "hotplug_type": "None"
}
"""

STAGE_RE = re.compile(r"^\.[^.]+?\.blackarch\.[A-Za-z0-9]{6}$")


def sibling(name: str) -> str:
    path = BIN_DIR / name
    return str(path) if path.is_file() else name


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def run_output(argv: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return 127, ""
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def as_root(argv: list[str]) -> subprocess.CompletedProcess:
    """`sudo <argv>` when not already root, so a root step never fails on a prompt."""
    if os.geteuid() == 0:
        return run(argv)
    return run(["sudo", *argv])


def as_root_output(argv: list[str]) -> tuple[int, str]:
    """`sudo <argv>` with stdout captured, for commands that print a result."""
    command = ["sudo", *argv] if os.geteuid() != 0 else argv
    try:
        proc = subprocess.run(command, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return 127, ""
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def cmd_missing(command: str) -> bool:
    """`blackarch-cmd-missing`: True when the command is not on PATH."""
    return run(["sh", "-c", f"command -v {command}"]).returncode != 0


def safe_stage_path(stage: Path, destination: Path) -> bool:
    """Reject a stage path that does not sit beside its destination.

    The original checks the mktemp prefix and a 6-character alnum suffix, so a
    stage anywhere else (a symlink, another directory) is refused before install.
    """
    prefix = f"{destination.parent}/.{destination.name}.blackarch."
    name = stage.name
    if not name.startswith(f".{destination.name}.blackarch."):
        return False
    suffix = name[len(f".{destination.name}.blackarch."):]
    if not stage.parent == destination.parent:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9]{6}", suffix))


def install_root_file(source: Path, destination: Path, mode: str) -> bool:
    """Stage beside the destination, install as root, then rename into place.

    `install` follows a symlink, and `mv -T` refuses to overwrite one, so a
    planted symlink at the stage or destination is caught rather than written
    through.
    """
    code, out = as_root_output(
        ["mktemp", "--", f"{destination.parent}/.{destination.name}.blackarch.XXXXXX"])
    if code != 0 or not out:
        return False
    stage = Path(out)
    if not stage.is_file() or not safe_stage_path(stage, destination):
        run(["rm", "-f", "--", str(stage)])
        return False

    if not as_root(["install", "-m", mode, "-o", "root", "-g", "root",
                    "-T", str(source), str(stage)]).returncode == 0:
        run(["rm", "-f", "--", str(stage)])
        return False

    if as_root(["mv", "-Tf", "--", str(stage), str(destination)]).returncode != 0:
        run(["rm", "-f", "--", str(stage)])
        return False
    return True


def gpu_mode() -> str:
    """`supergfxctl -g`, retried three times with a kill-after timeout."""
    for attempt in range(3):
        code, out = run_output(["timeout", "--kill-after=1s", "3s",
                                SUPERGFXCTL, "-g"])
        if code == 0 and out:
            return out
        if attempt < 2:
            import time
            time.sleep(1)
    return ""


def confirm(prompt: str) -> bool:
    return run([GUM, "confirm", prompt]).returncode == 0


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: blackarch-toggle-hybrid-gpu")
        return 0

    if cmd_missing(SUPERGFXCTL):
        run([sibling("blackarch-pkg-add"), SUPERGFXCTL])

        # The config must exist before the service starts or the first boot hangs.
        command = (["sudo", "tee", str(SUPERGFXD_CONF)] if os.geteuid() != 0
                   else ["tee", str(SUPERGFXD_CONF)])
        subprocess.run(command, input=SUPERGFXD_CONF_BODY.encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)
        as_root(["systemctl", "enable", "--now", SUPERSVC])

    mode = gpu_mode()
    if not mode:
        print("supergfxd is not responding. Try again, or check: "
              "systemctl status supergfxd", file=sys.stderr)
        return 1

    if mode == "Integrated":
        if not confirm("Enable dedicated GPU and reboot?"):
            return 0
        as_root(["sed", "-i",
                 's/"mode": ".*"/"mode": "Hybrid"/', str(SUPERGFXD_CONF)])
        # Hybrid needs neither the startup delay nor the forced-iGPU sleep hook.
        as_root(["rm", "-rf", "--", "/usr/lib/systemd/system-sleep/force-igpu"])
        as_root(["rm", "-rf", "--", str(DELAY_DROPLET)])
        return run([sibling("blackarch-system-reboot")]).returncode

    if mode == "Hybrid":
        if not confirm("Use only integrated GPU and reboot?"):
            return 0

        as_root(["mkdir", "-p", "--", str(DELAY_DROPLET_DIR)])
        if not install_root_file(
                BLACKARCH_PATH / "default/systemd/system/supergfxd.service.d/delay-start.conf",
                DELAY_DROPLET, "0644"):
            print("Could not install the supergfxd startup-delay override",
                  file=sys.stderr)
            return 1

        as_root(["mkdir", "-p", "--", str(FORCE_IGPU_HOOK.parent)])
        if not install_root_file(
                BLACKARCH_PATH / "default/systemd/system-sleep/force-igpu",
                FORCE_IGPU_HOOK, "0755"):
            print("Could not install the force-igpu system-sleep hook",
                  file=sys.stderr)
            return 1

        # Both settings in one atomic config rewrite, only after every
        # supporting file is installed.
        as_root(["sed", "-i",
                 "-e", 's/"mode": ".*"/"mode": "Integrated"/',
                 "-e", 's/"vfio_enable": false/"vfio_enable": true/',
                 str(SUPERGFXD_CONF)])
        return run([sibling("blackarch-system-reboot")]).returncode

    print("Hybrid GPU not found or in unknown mode.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
