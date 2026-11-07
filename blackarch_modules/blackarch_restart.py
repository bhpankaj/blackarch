#!/usr/bin/env python3
# blackarch:summary=Restart Blackarch components
# blackarch:args=<component>
# blackarch:examples=blackarch restart audio | blackarch restart shell | blackarch-restart-shell
"""blackarch-restart — restart Blackarch components.

Standalone Python replacement for the whole `blackarch-restart-*` command
family: app, audio, bluetooth, btop, gum, helix, herdr, hyprctl, hypridle,
hyprsunset, opencode, pipewire, shell, swayosd, terminal, tmux, trackpad,
waybar, wifi, xcompose.

Usage: blackarch-restart <component> [args...]
   or: blackarch-restart-<component> [args...]

The Hyprland IPC socket is spoken directly for `hyprctl` and for the shell
relaunch, so those need no hyprctl binary. Process lookup (pgrep/pkill/killall)
reads /proc instead of forking psmisc. Everything else drives the same external
tools the bash versions did.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blackarch_modules.blackarch_helpers import waylandsudo_argv  # noqa: E402

HOME = Path(os.path.expanduser("~"))

# A component's own name, when invoked as `blackarch-restart-<component>`.
SELF_PREFIX = "blackarch-restart-"

USAGE = """Usage: blackarch restart <component> [args...]

Components:
  app <command> [args...]   Kill and relaunch a command through uwsm
  audio                     Restart audio services, recover stuck USB audio
  bluetooth                 Unblock and list bluetooth
  btop                      Reload btop configuration
  gum                       Print shell exports for the current gum styling
  helix                     Reload Helix configuration
  herdr                     Reload herdr configuration
  hyprctl                   Reload Hyprland configuration
  hypridle                  Restart hypridle
  hyprsunset                Restart hyprsunset
  opencode                  Reload opencode configuration
  pipewire                  Restart the pipewire service
  shell                     Restart the Blackarch shell
  swayosd                   Restart swayosd-server
  terminal                  Reload the terminal emulator configuration
  tmux                     Restart tmux with the latest configuration
  trackpad                  Reset the trackpad driver
  waybar                    Restart waybar
  wifi                      Unblock and restart Wi-Fi
  xcompose                  Restart fcitx5"""


# ── process helpers (pgrep / pkill / killall) ─────────────────────────────────
def process_name(pid: int) -> str | None:
    """/proc/<pid>/comm — the same 15-char name pgrep and pkill match on."""
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return None


def matching_pids(pattern: str, exact: bool) -> list[int]:
    """pids whose process name matches `pattern`.

    `pgrep -x`/`killall` compare the whole name; bare `pgrep`/`pkill` treat the
    pattern as an unanchored regex.
    """
    if exact:
        regex = re.compile(f"^{re.escape(pattern)}$")
    else:
        try:
            regex = re.compile(pattern)
        except re.error:
            return []

    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        name = process_name(int(entry))
        if name is not None and regex.search(name):
            pids.append(int(entry))
    return pids


def kill_matching(pattern: str, sig: int, exact: bool) -> bool:
    """Signal every match; True when at least one process was found."""
    killed = False
    for pid in matching_pids(pattern, exact):
        try:
            os.kill(pid, sig)
            killed = True
        except OSError:
            pass
    return killed


def process_running(name: str) -> bool:
    """pgrep -x <name>."""
    return bool(matching_pids(name, exact=True))


# ── command helpers ───────────────────────────────────────────────────────────
def run(command: list[str], timeout: float | None = None, quiet: bool = False) -> int:
    """Run a command, returning its exit status (124 on timeout, 127 if missing).

    Mirrors `timeout Ns cmd`, including the status it reports when the deadline
    expires, since callers branch on that.
    """
    devnull = subprocess.DEVNULL if quiet else None
    try:
        result = subprocess.run(
            command, stdout=devnull, stderr=devnull, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124
    except OSError:
        return 127
    return result.returncode


def run_input(command: list[str], text: str, quiet: bool = True) -> int:
    """Run a command with `text` on stdin (the `echo x | cmd` shape)."""
    devnull = subprocess.DEVNULL if quiet else None
    try:
        result = subprocess.run(
            command, input=text, text=True, stdout=devnull, stderr=devnull
        )
    except OSError:
        return 127
    return result.returncode


def run_capture(command: list[str]) -> str:
    """stdout of a command, or "" when it cannot run or writes nothing."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout


def run_background(command: list[str], quiet: bool = False) -> subprocess.Popen | None:
    """Run a command in the background, returning the Popen object."""
    devnull = subprocess.DEVNULL if quiet else None
    try:
        process = subprocess.Popen(command, stdout=devnull, stderr=devnull)
        return process
    except OSError:
        return None


# ── Hyprland IPC ──────────────────────────────────────────────────────────────
def hypr_socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not signature:
        raise RuntimeError("HYPRLAND_INSTANCE_SIGNATURE is not set")
    return Path(runtime) / "hypr" / signature / ".socket.sock"


def hypr_request(command: str) -> str:
    """Send one IPC request (`/<command>`) and return the raw response."""
    path = hypr_socket_path()
    if not path.exists():
        raise RuntimeError(f"no Hyprland instance at {path}")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(str(path))
        sock.sendall(f"/{command}".encode())
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


# ── shell IPC ─────────────────────────────────────────────────────────────────
def shell_ipc(
    session_path: str, target: str, method: str, *args: str, timeout: str = "0.5s"
):
    """Run blackarch-shell against the session, returning (status, stdout)."""
    env = {
        **os.environ,
        "BLACKARCH_PATH": session_path,
        "BLACKARCH_SHELL_IPC_TIMEOUT": timeout,
    }
    try:
        result = subprocess.run(
            ["blackarch-shell", target, method, *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return 127, ""
    return result.returncode, result.stdout


def lock_status(session_path: str) -> dict:
    _, out = shell_ipc(session_path, "lock", "status")
    try:
        return json.loads(out) if out.strip() else {}
    except ValueError:
        return {}


# ── components ────────────────────────────────────────────────────────────────
def cmd_app(args: list[str]) -> int:
    """pkill -x <command>; setsid uwsm-app -- <command> [args...]"""
    if not args:
        print("Usage: blackarch-restart-app <command> [args...]", file=sys.stderr)
        return 1

    kill_matching(args[0], signal.SIGTERM, exact=True)

    # No start_new_session: the setsid binary forks when the caller is not a
    # process group leader, so it returns at once and the caller never waits.
    subprocess.Popen(
        ["setsid", "uwsm-app", "--", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return 0


AUDIO_SERVICES = ["wireplumber.service", "pipewire.service", "pipewire-pulse.service"]


def restart_audio_services() -> int:
    print("Restarting audio services...\n")

    if run(["systemctl", "--user", "restart", *AUDIO_SERVICES], timeout=25) == 0:
        return 0

    print("\nAudio services did not restart cleanly. Forcing stuck services down...\n")
    run(["systemctl", "--user", "cancel"], quiet=True)
    run(
        [
            "systemctl",
            "--user",
            "kill",
            "--kill-whom=all",
            "--signal=KILL",
            *AUDIO_SERVICES,
        ],
        quiet=True,
    )
    run(["systemctl", "--user", "reset-failed", *AUDIO_SERVICES], quiet=True)

    return run(
        [
            "systemctl",
            "--user",
            "start",
            "pipewire.service",
            "pipewire-pulse.service",
            "wireplumber.service",
        ],
        timeout=25,
    )


def wpctl_healthy() -> bool:
    return run(["wpctl", "status"], timeout=5, quiet=True) == 0


def usb_device_for_card(card: str) -> str | None:
    """The USB device node backing an ALSA card, walking up the sysfs chain."""
    path = os.path.realpath(f"/sys/class/sound/card{card}")
    while path != "/":
        if all(
            os.path.isfile(os.path.join(path, name))
            for name in ("idVendor", "idProduct", "busnum", "devnum")
        ):
            return os.path.basename(path)
        path = os.path.dirname(path)
    return None


def append_unique(value: str | None, existing: list[str]) -> str | None:
    """The value unless it is empty or already listed (bash `append_unique`)."""
    if not value:
        return None
    for seen in existing:
        if seen == value:
            return None
    return value


def audio_process_blocked_on_usb() -> bool:
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        if process_name(int(entry)) not in ("wireplumber", "pipewire"):
            continue
        try:
            wchan = Path(f"/proc/{entry}/wchan").read_text().strip()
        except OSError:
            continue
        if "usb" in wchan:
            return True
    return False


def usb_audio_devices() -> list[str]:
    devices: list[str] = []
    for card in sorted(glob.glob("/sys/class/sound/card*")):
        match = re.search(r"/card([0-9]+)$", card)
        if not match:
            continue
        unique = append_unique(usb_device_for_card(match.group(1)), devices)
        if unique:
            devices.append(unique)
    return devices


def clear_usb_audio_defaults() -> None:
    state_dir = (
        Path(os.environ.get("XDG_STATE_HOME") or (HOME / ".local/state"))
        / "wireplumber"
    )
    if not state_dir.is_dir():
        return

    # sed -i deletions, with a timestamped backup first.
    deletions = {
        "default-nodes": [
            r"^default\.configured\.audio\.sink=alsa_output\.usb-",
            r"^default\.configured\.audio\.sink\.[0-9]\+=alsa_output\.usb-",
        ],
        "default-routes": [r"^alsa_card\.usb-"],
    }
    for name, patterns in deletions.items():
        target = state_dir / name
        if not target.is_file():
            continue
        try:
            shutil.copy2(target, state_dir / f"{name}.bak.{int(time.time())}")
        except OSError:
            pass
        kept = "".join(
            line
            for line in target.read_text(errors="replace").splitlines(keepends=True)
            if not any(re.search(pattern, line) for pattern in patterns)
        )
        try:
            target.write_text(kept)
        except OSError:
            pass


def stuck_usb_audio_devices() -> list[str]:
    devices: list[str] = []
    for status in sorted(glob.glob("/proc/asound/card*/pcm*p/sub*/status")):
        try:
            text = Path(status).read_text()
        except OSError:
            continue

        state = next(
            (
                line.split()[1]
                for line in text.splitlines()
                if line.startswith("state:") and len(line.split()) >= 2
            ),
            None,
        )
        if state != "SETUP":
            continue

        # The kernel writes `owner_pid : <pid>`, so the pid is field three —
        # the same field awk's `$3` picks.
        owner = next(
            (
                line.split()[2]
                for line in text.splitlines()
                if re.match(r"^owner_pid\s*:", line) and len(line.split()) >= 3
            ),
            None,
        )
        if not owner or process_name(int(owner) if owner.isdigit() else -1) not in (
            "wireplumber",
            "pipewire",
        ):
            continue

        match = re.search(r"/card([0-9]+)", status)
        if not match:
            continue
        unique = append_unique(usb_device_for_card(match.group(1)), devices)
        if unique:
            devices.append(unique)
    return devices


def reset_usb_audio_device(device: str) -> int:
    sysfs = Path(f"/sys/bus/usb/devices/{device}")
    if not sysfs.is_dir():
        return 1

    if shutil.which("usbreset") is None:
        print(
            f"usbreset is not installed; replug or power-cycle {device} to recover it."
        )
        return 1

    try:
        busnum = (sysfs / "busnum").read_text().strip()
        devnum = (sysfs / "devnum").read_text().strip()
    except OSError:
        return 1

    try:
        product = (sysfs / "product").read_text().strip() or device
    except OSError:
        product = device

    bus_device = f"{int(busnum):03d}/{int(devnum):03d}"
    print(f"\nResetting stuck USB audio device: {product} ({bus_device})...")

    if run(waylandsudo_argv(["usbreset", bus_device]), timeout=25) == 0:
        return 0

    print(
        f"Could not reset {product} automatically. Replug or power-cycle it, "
        "then run blackarch-restart-audio again."
    )
    return 1


def recover_stuck_usb_audio() -> bool:
    detected = [device for device in stuck_usb_audio_devices() if device]

    if not detected and audio_process_blocked_on_usb():
        print("Audio service is blocked in USB I/O; resetting USB audio devices...")
        clear_usb_audio_defaults()
        detected += [device for device in usb_audio_devices() if device]

    devices: list[str] = []
    for device in detected:
        if append_unique(device, devices):
            devices.append(device)

    if not devices:
        return False

    resets = 0
    for device in devices:
        if reset_usb_audio_device(device) == 0:
            resets += 1
    return resets > 0


def cmd_audio() -> int:
    restart_audio_services()

    if not wpctl_healthy():
        print(
            "\nPipeWire is still not responding. Checking for stuck USB audio devices..."
        )

        if recover_stuck_usb_audio():
            print("\nRestarting audio services after USB audio reset...\n")
            restart_audio_services()
        else:
            print("No stuck USB audio device was detected automatically.")

    time.sleep(2)

    print("\nAudio status:\n")
    if run(["wpctl", "status"], timeout=5) != 0:
        print(
            "Audio services are still not responding. Try replugging or "
            "power-cycling the selected USB audio device."
        )
        return 1
    return 0


def cmd_bluetooth() -> int:
    print("Unblocking bluetooth...\n")
    run(["rfkill", "unblock", "bluetooth"])
    return run(["rfkill", "list", "bluetooth"])


def cmd_btop() -> int:
    return 0 if kill_matching("btop", signal.SIGUSR2, exact=False) else 1


GUM_ENV_RE = re.compile(r'hl\.env\("([A-Z0-9_]+)", "([^"]+)"\)')


def cmd_gum() -> int:
    """Print `export KEY=VALUE` lines for the current gum styling.

    The bash version was sourced, so it exported into the caller's shell. A
    Python script cannot be sourced, so it prints shell commands instead; use it
    as `eval "$(blackarch-restart-gum)"`.
    """
    source = HOME / ".local/state/blackarch/current/theme/gum_env.lua"
    if not source.is_file():
        return 0

    for key, value in GUM_ENV_RE.findall(source.read_text(errors="replace")):
        if key and value:
            print(f"export {key}={shlex.quote(value)}")
    return 0


def cmd_helix() -> int:
    if process_running("helix"):
        kill_matching("helix", signal.SIGUSR1, exact=True)
    return 0


def cmd_herdr() -> int:
    status = run_capture(["herdr", "status", "server", "--json"])
    try:
        running = json.loads(status).get("running") if status.strip() else None
    except ValueError:
        running = None

    if running not in (True, "true"):
        return 0

    reload_out = run_capture(["herdr", "server", "reload-config"])
    try:
        data = json.loads(reload_out) if reload_out.strip() else {}
    except ValueError:
        data = {}

    diagnostics = (data.get("result") or {}).get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            if isinstance(diagnostic, str):
                print(diagnostic, file=sys.stderr)
            else:
                print(json.dumps(diagnostic, separators=(",", ":")), file=sys.stderr)

    message = (data.get("error") or {}).get("message")
    if message is not None:
        print(message, file=sys.stderr)

    result = data.get("result") or {}
    if result.get("status", "failed") == "failed":
        return 1
    return 0


def cmd_hyprctl() -> int:
    try:
        hypr_request("reload")
    except (RuntimeError, OSError):
        return 1
    return 0


def cmd_hypridle() -> int:
    return cmd_app(["hypridle"])


def cmd_hyprsunset() -> int:
    return cmd_app(["hyprsunset"])


def cmd_opencode() -> int:
    if process_running("opencode"):
        kill_matching("opencode", signal.SIGUSR2, exact=True)
    return 0


def cmd_pipewire() -> int:
    print("Restarting pipewire audio service...\n")
    return run(["systemctl", "--user", "restart", "pipewire.service"])


def session_blackarch_path() -> str:
    """BLACKARCH_PATH from the user manager, falling back to this environment."""
    last = ""
    for line in run_capture(["systemctl", "--user", "show-environment"]).splitlines():
        if line.startswith("BLACKARCH_PATH="):
            last = line[len("BLACKARCH_PATH=") :]
    return last or os.environ.get("BLACKARCH_PATH", "")


def recover_hyprland_signature() -> None:
    """Derive HYPRLAND_INSTANCE_SIGNATURE from the newest instance runtime dir."""
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return

    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    instances = []
    try:
        for entry in Path(runtime, "hypr").iterdir():
            if entry.is_dir():
                instances.append((entry.stat().st_mtime, entry.name))
    except OSError:
        return

    if instances:
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = max(instances)[1]


def relock_session(session_path: str) -> bool:
    """Request the lock and poll until the session reports secure."""
    deadline = time.monotonic() + 30

    while time.monotonic() < deadline:
        status = lock_status(session_path)
        if status.get("secure") is True:
            return True
        if status.get("requested") is not True:
            shell_ipc(session_path, "lock", "lock")
        time.sleep(0.1)

    return False


def cmd_shell() -> int:
    session_path = session_blackarch_path()
    config_dir = f"{session_path}/shell"
    if not os.path.isfile(f"{config_dir}/shell.qml"):
        print(f"Blackarch shell config not found: {config_dir}", file=sys.stderr)
        return 1

    recover_hyprland_signature()

    # Only a locker reporting the lock secure or in progress is worth keeping:
    # a LOCK session without an active locker sits in Hyprland's failsafe with no
    # way to authenticate, and a restart is the only way back in.
    relock = False
    if run(["blackarch-hyprland", "session-locked"], quiet=True) == 0:
        status = lock_status(session_path)
        if bool(status.get("secure") or status.get("requested")):
            print(
                "Refusing to restart Blackarch shell while the session is locked.",
                file=sys.stderr,
            )
            return 1
        relock = True

    # Each kill stops the oldest matching instance and returns once it has fully
    # exited, so the relaunch below cannot race a dying shell.
    while (
        run(
            ["quickshell", "kill", "-p", config_dir, "--any-display"],
            timeout=5,
            quiet=True,
        )
        == 0
    ):
        pass

    # Spawn from Hyprland so the shell inherits the canonical session
    # environment, not transient variables from a terminal or SSH connection.
    try:
        # hypr_request('dispatch hl.dsp.exec_cmd("blackarch-launch-shell")')
        run_background(["blackarch-launch-shell"])
    except (RuntimeError, OSError):
        pass

    for _ in range(20):
        if shell_ipc(session_path, "shell", "ping")[0] == 0:
            if relock and not relock_session(session_path):
                print(
                    "Blackarch shell restarted, but the session lock was not re-secured.",
                    file=sys.stderr,
                )
                return 1

            # Invitation toasts die with the old shell, and their notify-send
            # waiters hang forever: the dying server never emits
            # NotificationClosed. A still-running invitation unit is therefore
            # an unanswered invitation — re-run it.
            run(
                [
                    "systemctl",
                    "--user",
                    "try-restart",
                    "blackarch-*-invitation.service",
                ],
                quiet=True,
            )
            return 0
        time.sleep(0.1)

    # print("Blackarch shell did not become ready after restart.", file=sys.stderr)
    return 1


def cmd_swayosd() -> int:
    return cmd_app(["swayosd-server"])


def cmd_terminal() -> int:
    alacritty = HOME / ".config/alacritty/alacritty.toml"
    if alacritty.is_file():
        alacritty.touch()

    if process_running("kitty"):
        kill_matching("kitty", signal.SIGUSR1, exact=True)
    if process_running("ghostty"):
        kill_matching("ghostty", signal.SIGUSR2, exact=True)
    return 0


def cmd_tmux() -> int:
    if run(["tmux", "has-session"], quiet=True) != 0:
        return 0
    return run(["tmux", "source-file", str(HOME / ".config/tmux/tmux.conf")])


I2C_DRIVER = "/sys/bus/i2c/drivers/i2c_hid_acpi"


def cmd_trackpad() -> int:
    for device in sorted(glob.glob(f"{I2C_DRIVER}/i2c-*")):
        name = os.path.basename(device)
        print(f"Resetting {name} via i2c_hid_acpi unbind/rebind...")
        run_input(waylandsudo_argv(["tee", f"{I2C_DRIVER}/unbind"]), f"{name}\n")
        time.sleep(1)
        run_input(waylandsudo_argv(["tee", f"{I2C_DRIVER}/bind"]), f"{name}\n")
        print("Done")

    if "intel_quicki2c" in run_capture(["lsmod"]):
        print("Reloading intel_quicki2c...")
        if run(waylandsudo_argv(["modprobe", "-r", "intel_quicki2c"])) == 0:
            return run(waylandsudo_argv(["modprobe", "intel_quicki2c"]))
    return 0


def cmd_waybar() -> int:
    return cmd_app(["waybar"])


def cmd_wifi() -> int:
    print("Unblocking wifi...\n")
    run(["rfkill", "unblock", "wifi"])
    run(["nmcli", "networking", "on"])
    run(["nmcli", "radio", "wifi", "on"])
    run(["nmcli", "device", "wifi", "rescan"], quiet=True)
    return run(["rfkill", "list", "wifi"])


def cmd_xcompose() -> int:
    return cmd_app(["fcitx5"])


# ── dispatch ──────────────────────────────────────────────────────────────────
COMMANDS = {
    "app": (cmd_app, "[command] [args...]"),
    "audio": (cmd_audio, ""),
    "bluetooth": (cmd_bluetooth, ""),
    "btop": (cmd_btop, ""),
    "gum": (cmd_gum, ""),
    "helix": (cmd_helix, ""),
    "herdr": (cmd_herdr, ""),
    "hyprctl": (cmd_hyprctl, ""),
    "hypridle": (cmd_hypridle, ""),
    "hyprsunset": (cmd_hyprsunset, ""),
    "opencode": (cmd_opencode, ""),
    "pipewire": (cmd_pipewire, ""),
    "shell": (cmd_shell, ""),
    "swayosd": (cmd_swayosd, ""),
    "terminal": (cmd_terminal, ""),
    "tmux": (cmd_tmux, ""),
    "trackpad": (cmd_trackpad, ""),
    "waybar": (cmd_waybar, ""),
    "wifi": (cmd_wifi, ""),
    "xcompose": (cmd_xcompose, ""),
}


def main(argv: list[str]) -> int:
    invoked = Path(sys.argv[0]).name if sys.argv else "blackarch-restart"
    component = ""
    args = list(argv)

    # `blackarch-restart-<component>` selects the component through argv[0];
    # `blackarch restart <component>` passes it as the first argument.
    if invoked.startswith(SELF_PREFIX):
        component = invoked[len(SELF_PREFIX) :]
    elif argv:
        component = argv[0]
        args = argv[1:]

    if component in ("-h", "--help", "help") or not component:
        print(USAGE)
        return 0

    if component not in COMMANDS:
        print(f"Unknown component: {component}", file=sys.stderr)
        return 1

    handler = COMMANDS[component][0]
    if component == "app":
        return handler(args)
    return handler()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
