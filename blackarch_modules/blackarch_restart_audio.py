#!/usr/bin/env python3
# blackarch:summary=Restart audio services and recover stuck USB audio devices.
# blackarch:examples=blackarch restart audio | blackarch-restart-audio
"""blackarch-restart-audio — restart audio services, recover stuck USB audio.

Python port of the bash original. Restarts the three user services, and when
PipeWire is still unresponsive afterwards, looks for a USB audio device whose
stream is stuck in the SETUP state and resets it with usbreset.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blackarch_modules.blackarch_helpers import waylandsudo_argv  # noqa: E402

SERVICES = ("wireplumber.service", "pipewire.service", "pipewire-pulse.service")
RESTART_TIMEOUT = 25
HEALTH_TIMEOUT = 5

CARD_RE = re.compile(r"^/sys/class/sound/card(\d+)$")
PCM_STATUS_RE = re.compile(r"^/proc/asound/card(\d+)/pcm\d+p/sub\d+/status$")
OWNER_PID_LINE = re.compile(r"^owner_pid\s*:\s*(\S+)")
STATE_LINE = re.compile(r"^state:\s*(\S+)")


def run(argv: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def restart_audio_services() -> bool:
    print("Restarting audio services...\n")

    if run(["systemctl", "--user", "restart", *SERVICES], timeout=RESTART_TIMEOUT).returncode == 0:
        return True

    print("\nAudio services did not restart cleanly. Forcing stuck services down...\n")
    run(["systemctl", "--user", "cancel"])
    run(["systemctl", "--user", "kill", "--kill-whom=all", "--signal=KILL", *SERVICES])
    run(["systemctl", "--user", "reset-failed", *SERVICES])
    run(["systemctl", "--user", "start", "pipewire.service",
         "pipewire-pulse.service", "wireplumber.service"], timeout=RESTART_TIMEOUT)
    return True


def wpctl_healthy() -> bool:
    return run(["wpctl", "status"], timeout=HEALTH_TIMEOUT).returncode == 0


def usb_device_for_card(card: str) -> str:
    """Walk the card's sysfs ancestors until a USB device node is found."""
    try:
        path = Path(f"/sys/class/sound/card{card}").resolve()
    except OSError:
        return ""
    while str(path) != "/":
        if all((path / name).is_file() for name in ("idVendor", "idProduct", "busnum", "devnum")):
            return path.name
        path = path.parent
    return ""


def append_unique(value: str, existing: list[str]) -> str:
    if not value or value in existing:
        return ""
    return value


def audio_process_blocked_on_usb() -> bool:
    """A pipewire/wireplumber process parked in a USB wait channel."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if not (entry / "comm").is_file() or not (entry / "wchan").is_file():
                continue
            name = (entry / "comm").read_text(errors="replace").strip()
        except OSError:
            continue
        if name not in ("wireplumber", "pipewire"):
            continue
        try:
            wchan = (entry / "wchan").read_text(errors="replace").strip()
        except OSError:
            continue
        if "usb" in wchan:
            return True
    return False


def usb_audio_devices() -> list[str]:
    devices: list[str] = []
    try:
        cards = sorted(Path("/sys/class/sound").glob("card*"))
    except OSError:
        return devices

    for card in cards:
        match = CARD_RE.match(str(card))
        if not match:
            continue
        device = usb_device_for_card(match.group(1))
        if append_unique(device, devices):
            devices.append(device)
    return devices


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME")
                or os.path.join(os.environ.get("HOME", ""), ".local/state")) / "wireplumber"


def clear_usb_audio_defaults() -> None:
    """Drop USB default-sink/route entries; they keep a dead device selected."""
    directory = state_dir()
    if not directory.is_dir():
        return

    for name, drop_lines in (
        ("default-nodes", ("default.configured.audio.sink=alsa_output.usb-",)),
        ("default-routes", ("alsa_card.usb-",)),
    ):
        path = directory / name
        if not path.is_file():
            continue
        try:
            backup = directory / f"{name}.bak.{int(time.time())}"
            backup.write_bytes(path.read_bytes())
            kept = [
                line for line in path.read_text(errors="replace").splitlines()
                if not any(line.startswith(prefix) for prefix in drop_lines)
                and not re.match(r"^default\.configured\.audio\.sink\.\d+=alsa_output\.usb-", line)
            ]
            path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except OSError:
            continue


def stuck_usb_audio_devices() -> list[str]:
    """USB devices whose PCM stream is stuck in the SETUP state."""
    devices: list[str] = []
    try:
        statuses = sorted(Path("/proc/asound").glob("card*/pcm*p/sub*/status"))
    except OSError:
        return devices

    for status in statuses:
        match = PCM_STATUS_RE.match(str(status))
        if not match:
            continue
        try:
            text = status.read_text(errors="replace")
        except OSError:
            continue

        state = ""
        owner_pid = ""
        for line in text.splitlines():
            if not state:
                found = STATE_LINE.match(line)
                if found:
                    state = found.group(1)
                    continue
            if not owner_pid:
                found = OWNER_PID_LINE.match(line)
                if found:
                    owner_pid = found.group(1)
        if state != "SETUP":
            continue

        if not owner_pid.isdigit():
            continue
        try:
            owner_name = Path(f"/proc/{owner_pid}/comm").read_text(errors="replace").strip()
        except OSError:
            continue
        if owner_name not in ("wireplumber", "pipewire"):
            continue

        device = usb_device_for_card(match.group(1))
        if append_unique(device, devices):
            devices.append(device)
    return devices


def reset_usb_audio_device(device: str) -> bool:
    sysfs = Path(f"/sys/bus/usb/devices/{device}")
    if not sysfs.is_dir():
        return False
    if run(["blackarch-cmd-present", "usbreset"]).returncode != 0:
        print(f"usbreset is not installed; replug or power-cycle {device} to recover it.")
        return False

    try:
        busnum = int((sysfs / "busnum").read_text().strip())
        devnum = int((sysfs / "devnum").read_text().strip())
        product = (sysfs / "product").read_text(errors="replace").strip() or "device"
    except (OSError, ValueError):
        return False

    bus_device = f"{busnum:03d}/{devnum:03d}"
    print(f"\nResetting stuck USB audio device: {product} ({bus_device})...\n")

    # A USB reset needs root, but it runs from a graphical session, so the
    # escalation goes through waylandsudo rather than a bare sudo.
    if run(waylandsudo_argv(["usbreset", bus_device]), timeout=RESTART_TIMEOUT).returncode == 0:
        return True
    print(f"Could not reset {product} automatically. Replug or power-cycle it, then run "
          "blackarch-restart-audio again.")
    return False


def recover_stuck_usb_audio() -> bool:
    devices: list[str] = stuck_usb_audio_devices()

    if not devices and audio_process_blocked_on_usb():
        print("Audio service is blocked in USB I/O; resetting USB audio devices...")
        clear_usb_audio_defaults()
        devices.extend(usb_audio_devices())

    unique: list[str] = []
    for device in devices:
        if append_unique(device, unique):
            unique.append(device)
    if not unique:
        return False

    resets = 0
    for device in unique:
        if reset_usb_audio_device(device):
            resets += 1
    return resets > 0


def main(argv: list[str]) -> int:
    restart_audio_services()

    if not wpctl_healthy():
        print("\nPipeWire is still not responding. Checking for stuck USB audio devices...\n")
        if recover_stuck_usb_audio():
            print("\nRestarting audio services after USB audio reset...\n")
            restart_audio_services()
        else:
            print("No stuck USB audio device was detected automatically.")

    time.sleep(2)

    print("\nAudio status:\n")
    if run(["wpctl", "status"], timeout=HEALTH_TIMEOUT).returncode != 0:
        print("Audio services are still not responding. Try replugging or power-cycling "
              "the selected USB audio device.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
