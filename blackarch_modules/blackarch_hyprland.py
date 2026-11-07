#!/usr/bin/env python3
# blackarch:summary=Hyprland monitor, window, workspace and toggle controls
"""blackarch-hyprland — Hyprland monitor, window and workspace controls.

Standalone Python replacement for the whole `blackarch-hyprland-*` command
family. It speaks the Hyprland IPC socket directly, so it needs no hyprctl, jq,
awk, sed, socat or flock. Sibling blackarch commands are still used where they
are the right tool (desktop notifications, hardware probing).

Usage: blackarch-hyprland.py <command> [args...]
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
HOME = Path(os.path.expanduser("~"))
TOGGLES_DIR = HOME / ".local/state/blackarch/toggles/hypr"
MONITOR_LUA = HOME / ".config/hypr/monitors.lua"
WORKSPACE_LAYOUTS_DIR = HOME / ".local/state/blackarch/workspace-layouts"
WINDOW_STATE_DIR = HOME / ".local/state/blackarch/windows"
SCALE_STATE = TOGGLES_DIR / "internal-monitor-scale"
SCALE_LOG = Path(
    os.environ.get("XDG_STATE_HOME") or (HOME / ".local/state")
) / "blackarch/monitor-scaling.log"

INTERNAL_CONNECTOR = re.compile(r"^(eDP|LVDS|DSI)-")
CONNECTOR_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_SCALE = re.compile(r"^[0-9]+([.][0-9]+)?$")
LUA_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
POSITION = re.compile(r"^[-0-9A-Za-z_.+]+$")

PRESET_SCALES = [1, 1.25, 1.6, 2, 3, 4]

RELOAD_GUARD_RUN_ROOT = os.environ.get(
    "BLACKARCH_HYPRLAND_RELOAD_GUARD_RUN_ROOT", "/run/user"
)
RELOAD_GUARD_STATE_DIR = os.environ.get(
    "BLACKARCH_HYPRLAND_RELOAD_GUARD_STATE_DIR", "/run/blackarch/hyprland-reload-guard"
)


# ── Hyprland IPC ──────────────────────────────────────────────────────────────
class HyprctlError(Exception):
    pass


def hypr_socket_path(instance: str | None = None) -> Path:
    """$XDG_RUNTIME_DIR/hypr/<signature>/.socket.sock."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    signature = instance or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not signature:
        raise HyprctlError("HYPRLAND_INSTANCE_SIGNATURE is not set")
    return Path(runtime) / "hypr" / signature / ".socket.sock"


def hypr_request(command: str, as_json: bool = False, instance: str | None = None) -> str:
    """Send one IPC request and return the raw response text.

    The wire format is a single string: `j/<command>` asks for JSON, `/<command>`
    asks for the human-readable form.
    """
    path = hypr_socket_path(instance)
    if not path.exists():
        raise HyprctlError(f"no such instance: {signature_of(instance)}")

    prefix = "j/" if as_json else "/"
    request = f"{prefix}{command}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(str(path))
        sock.sendall(request.encode())
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


def signature_of(instance: str | None) -> str:
    return instance or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or "<unset>"


def hypr_json(command: str, instance: str | None = None):
    """A JSON request, parsed. Mirrors `hyprctl -j <command>`."""
    try:
        return json.loads(hypr_request(command, as_json=True, instance=instance))
    except json.JSONDecodeError as error:
        raise HyprctlError(f"not JSON: {error}") from None


def monitors_or_empty(all_outputs: bool = False) -> list[dict]:
    """`hyprctl monitors -j | jq ...` with an unreachable compositor yields an
    empty input, which jq turns into no output rather than an error."""
    try:
        return hypr_monitors(all_outputs=all_outputs)
    except HyprctlError:
        return []


def hypr_action(command: str, instance: str | None = None) -> bool:
    """A dispatch/eval/keyword/reload request. Mirrors hyprctl's exit status:
    success is a reply starting with `ok`."""
    reply = hypr_request(command, instance=instance)
    return reply.startswith("ok")


def hypr_dispatch(lua: str, *fallback_args: str, instance: str | None = None) -> bool:
    """`hyprctl dispatch <lua> || hyprctl dispatch <fallback...>`.

    The Lua form is what works on current Hyprland; the classic form is kept as
    the fallback exactly as the shell version does.
    """
    if hypr_action(f"dispatch {lua}", instance=instance):
        return True
    if fallback_args:
        return hypr_action("dispatch " + " ".join(fallback_args), instance=instance)
    return False


def hypr_reload(instance: str | None = None) -> bool:
    return hypr_action("reload", instance=instance)


def hypr_monitors(all_outputs: bool = False, instance: str | None = None) -> list[dict]:
    return hypr_json("monitors all" if all_outputs else "monitors", instance=instance)


def hypr_active_workspace(instance: str | None = None) -> dict:
    return hypr_json("activeworkspace", instance=instance)


def hypr_active_window(instance: str | None = None) -> dict:
    return hypr_json("activewindow", instance=instance)


def hypr_clients(instance: str | None = None) -> list[dict]:
    return hypr_json("clients", instance=instance)


def hypr_workspace_rules(instance: str | None = None) -> list[dict]:
    return hypr_json("workspacerules", instance=instance)


def hypr_getoption(option: str, instance: str | None = None) -> dict | None:
    """`hyprctl -j getoption <option>`; None when the option does not exist."""
    try:
        result = hypr_json(f"getoption {option}", instance=instance)
    except (json.JSONDecodeError, HyprctlError):
        return None
    return result if isinstance(result, dict) else None


# ── sibling blackarch commands ────────────────────────────────────────────────
def notify(glyph: str, headline: str, description: str | None = None) -> None:
    command = ["blackarch-notification-send", "-g", glyph, headline]
    if description:
        command.append(description)
    subprocess.run(command, check=False)


def hw_laptop() -> bool:
    return subprocess.run(["blackarch-hw-laptop"], check=False).returncode == 0


def hw_clamshell() -> bool:
    return subprocess.run(["blackarch-hw-clamshell"], check=False).returncode == 0


# ── hyprctl-equivalent queries ────────────────────────────────────────────────
def focused_monitor() -> dict | None:
    for monitor in monitors_or_empty():
        if monitor.get("focused") is True:
            return monitor
    return None


def internal_monitor_name() -> str:
    """The built-in panel's connector, disabled outputs included."""
    for monitor in monitors_or_empty(all_outputs=True):
        if INTERNAL_CONNECTOR.match(monitor.get("name") or ""):
            return monitor["name"]
    return ""


def external_monitor_name() -> str:
    for monitor in hypr_monitors():
        if not INTERNAL_CONNECTOR.match(monitor.get("name") or ""):
            return monitor["name"]
    return ""


def external_active() -> bool:
    """True when a non-internal output is present and enabled."""
    return any(
        not INTERNAL_CONNECTOR.match(monitor.get("name") or "")
        and monitor.get("disabled") is False
        for monitor in monitors_or_empty(all_outputs=True)
    )


def monitor_modeless() -> int:
    """0 modeless, 1 not, 2 when the compositor cannot say."""
    try:
        monitors = hypr_monitors(all_outputs=True)
    except (HyprctlError, json.JSONDecodeError):
        return 2
    if any(
        monitor.get("disabled") is not True
        and (monitor.get("width") == 0 or monitor.get("height") == 0)
        for monitor in monitors
    ):
        return 0
    return 1


def session_locked() -> int:
    """0 locked, 1 unlocked, 2 undetermined.

    Hyprland reports no lock state directly, but an active ext-session-lock is
    one of the reasons a monitor cannot go solitary: LOCK in solitaryBlockedBy.
    It stays set once the lock's client dies, which is the case worth detecting.
    """
    try:
        monitors = hypr_json("monitors")
    except (HyprctlError, json.JSONDecodeError):
        return 2

    def blockers(monitor: dict) -> list:
        return monitor.get("solitaryBlockedBy") or []

    def readable(monitor: dict) -> bool:
        return "WORKSPACE" not in blockers(monitor)

    if any("LOCK" in blockers(monitor) for monitor in monitors):
        return 0
    if any(readable(monitor) for monitor in monitors):
        return 1
    return 2


# ── toggles ───────────────────────────────────────────────────────────────────
def toggle_enabled(flag_name: str) -> bool:
    return (TOGGLES_DIR / f"{flag_name}.lua").is_file()


def toggle_disabled(flag_name: str) -> bool:
    return not toggle_enabled(flag_name)


def toggle_flag(flag_name: str, action: str = "toggle") -> str:
    """Copy a flag into the toggles directory, which is sourced entirely.

    Returns the resulting state, "on" or "off", or "" when the flag definition
    is missing. Mirrors `blackarch-hyprland-toggle`, which prints that state
    and reloads Hyprland afterwards.
    """
    if action not in ("on", "off", "toggle"):
        print("Usage: blackarch-hyprland-toggle <flag-name> [on|off|toggle]", file=sys.stderr)
        raise SystemExit(1)

    source = Path(os.environ.get("BLACKARCH_PATH", "")) / "default/hypr/toggles" / f"{flag_name}.lua"
    target = TOGGLES_DIR / f"{flag_name}.lua"

    if action == "toggle":
        if target.is_file():
            target.unlink(missing_ok=True)
            state = "off"
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            state = "on"
        else:
            print(f"Flag not found: {flag_name}", file=sys.stderr)
            return ""
    elif action == "on":
        if not source.is_file():
            print(f"Flag not found: {flag_name}", file=sys.stderr)
            return ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        state = "on"
    else:
        target.unlink(missing_ok=True)
        state = "off"

    hypr_reload()
    return state


def cmd_toggle(flag_name: str, action: str = "toggle") -> int:
    state = toggle_flag(flag_name, action)
    if not state:
        return 1
    if action == "toggle":
        print(state)
    return 0


def cmd_toggle_enabled(flag_name: str) -> int:
    return 0 if toggle_enabled(flag_name) else 1


def cmd_toggle_disabled(flag_name: str) -> int:
    return 0 if toggle_disabled(flag_name) else 1


def window_no_gaps() -> None:
    toggle_flag("window-no-gaps", "toggle")


# ── commands ──────────────────────────────────────────────────────────────────
def cmd_monitor_external_active() -> int:
    # jq -e: 0 when the filter produced a value, 4 when it produced none.
    return 0 if external_active() else 4


def cmd_monitor_focused() -> int:
    monitor = focused_monitor()
    if monitor:
        print(monitor.get("name") or "")
    return 0


def cmd_monitor_focused_apple(monitor_name: str = "") -> int:
    for monitor in monitors_or_empty():
        if monitor_name:
            if monitor.get("name") != monitor_name:
                continue
        elif monitor.get("focused") is not True:
            continue
        if monitor.get("make") != "Apple Computer Inc":
            continue
        model = monitor.get("model") or ""
        if re.search(r"StudioDisplay|ProDisplayXDR|Studio XDR", model):
            return 0
    return 4


def cmd_monitor_laptop() -> int:
    name = internal_monitor_name()
    if name:
        print(name)
    return 0


def cmd_monitor_modeless() -> int:
    return monitor_modeless()


def cmd_session_locked() -> int:
    return session_locked()


def cmd_window_gaps_toggle() -> int:
    return 0 if window_no_gaps() else 1


def cmd_workspace_toggle_gaps() -> int:
    workspace_id = hypr_active_workspace().get("id")
    rules = hypr_workspace_rules()
    gaps = 0
    for rule in rules:
        if rule.get("workspaceString") == workspace_id:
            values = rule.get("gapsOut") or []
            gaps = values[0] if values else 0
            break

    if str(gaps) == "0":
        keyword = f"workspace {workspace_id}, gapsout:10, gapsin:5, bordersize:2"
    else:
        keyword = f"workspace {workspace_id}, gapsout:0, gapsin:0, bordersize:0"
    print(hypr_request(f"keyword {keyword}"))
    return 0


def cmd_workspace_layout_toggle() -> int:
    workspace = hypr_active_workspace().get("id")
    if not isinstance(workspace, int):
        return 1

    current = hypr_active_workspace().get("tiledLayout")
    new_layout = "scrolling" if current == "dwindle" else "dwindle"

    WORKSPACE_LAYOUTS_DIR.mkdir(parents=True, exist_ok=True)
    rule = f'hl.workspace_rule({{ workspace = "{workspace}", layout = "{new_layout}" }})\n'
    (WORKSPACE_LAYOUTS_DIR / f"{workspace}.lua").write_text(rule)

    if not hypr_action(
        f'eval hl.workspace_rule({{ workspace = "{workspace}", layout = "{new_layout}" }})'
    ):
        hypr_action(f"keyword workspace {workspace}, layout:{new_layout}")

    notify("\uf10ac", f"Workspace layout set to {new_layout}")
    return 0


def cmd_focus_app(app_name: str) -> int:
    pattern = re.compile(re.escape(app_name), re.IGNORECASE)
    address = ""
    for client in hypr_clients():
        if pattern.search(client.get("class") or ""):
            address = client.get("address") or ""
            break
        if client.get("initialClass") == "org.blackarch.agent" and pattern.search(
            client.get("initialTitle") or ""
        ):
            address = client.get("address") or ""
            break

    if not address:
        return 1

    hypr_dispatch(f'hl.dsp.focus({{ window = "address:{address}" }})', "focuswindow", f"address:{address}")
    return 0


def cmd_window_close_all() -> int:
    active = hypr_active_window().get("address")
    for client in hypr_clients():
        address = client.get("address")
        if not address or address == active:
            continue
        hypr_action(f'dispatch hl.dsp.window.close({{ window = "address:{address}" }})')

    if not hypr_action('dispatch hl.dsp.focus({ workspace = "1" })'):
        hypr_action("dispatch workspace 1")
    return 0


def cmd_window_tiled_fullscreen_toggle() -> int:
    fullscreen_client = hypr_active_window().get("fullscreenClient") or 0
    if fullscreen_client == 2:
        if not hypr_dispatch("hl.dsp.window.fullscreen_state({ internal = 0, client = 0 })"):
            hypr_action("dispatch fullscreenstate 0 0")
    else:
        if not hypr_dispatch("hl.dsp.window.fullscreen_state({ internal = 0, client = 2 })"):
            hypr_action("dispatch fullscreenstate 0 2")
    return 0


def cmd_window_transparency_toggle() -> int:
    address = hypr_active_window().get("address")
    if not hypr_dispatch(
        f'hl.dsp.window.set_prop({{ window = "address:{address}", prop = "opaque", value = "toggle" }})'
    ):
        hypr_action(f'dispatch setprop "address:{address}" opaque toggle')
    return 0


def cmd_window_single_square_aspect_toggle() -> int:
    state = toggle_flag("single-window-aspect-ratio", "toggle")
    if state == "on":
        notify("\uf2d0", "Enable single-window square aspect ratio")
    else:
        notify("\uf2d0", "Disable single-window square aspect ratio")
    return 0


def cmd_window_pop(width: int = 1300, height: int = 900, x: str = "", y: str = "") -> int:
    active = hypr_active_window()
    window = f'address:{active.get("address") or ""}'

    if active.get("pinned") is True:
        hypr_dispatch(f'hl.dsp.window.pin({{ window = "{window}" }})', "pin", window)
        hypr_dispatch(
            f'hl.dsp.window.float({{ window = "{window}", action = "toggle" }})',
            "togglefloating",
            window,
        )
        hypr_dispatch(f'hl.dsp.window.tag({{ window = "{window}", tag = "-pop" }})', "tagwindow -pop", window)
    elif active.get("address"):
        hypr_dispatch(
            f'hl.dsp.window.float({{ window = "{window}", action = "toggle" }})',
            "togglefloating",
            window,
        )
        hypr_dispatch(
            f"hl.dsp.window.resize({{ window = \"{window}\", x = {width}, y = {height} }})",
            f"resizeactive exact {width} {height}",
            window,
        )

        if x and y:
            hypr_dispatch(
                f'hl.dsp.window.move({{ window = "{window}", x = {x}, y = {y} }})',
                f"moveactive {x} {y}",
                window,
            )
        else:
            hypr_dispatch(f'hl.dsp.window.center({{ window = "{window}" }})', "centerwindow", window)

        hypr_dispatch(f'hl.dsp.window.pin({{ window = "{window}" }})', "pin", window)
        hypr_dispatch(
            f'hl.dsp.window.alter_zorder({{ window = "{window}", mode = "top" }})',
            "alterzorder top",
            window,
        )
        hypr_dispatch(f'hl.dsp.window.tag({{ window = "{window}", tag = "+pop" }})', "tagwindow +pop", window)
    return 0


def cmd_monitor_internal(action: str) -> int:
    internal = internal_monitor_name()
    disable_flag = "internal-monitor-disable"
    mirror_flag = "internal-monitor-mirror"

    def wake() -> None:
        hypr_dispatch('hl.dsp.dpms({ action = "enable" })')

    def on() -> None:
        if toggle_enabled(disable_flag):
            toggle_flag(disable_flag, "off")
            notify("\uf0379", "Laptop display enabled")
        wake()

    def off() -> int:
        if not internal:
            notify("\uf0379", "No laptop display found")
            return 1
        if not CONNECTOR_NAME.match(internal):
            notify("\uf0379", "Refusing unsafe monitor name")
            return 1
        if not external_active():
            notify("\uf0379", "Can't disable the only active display")
            return 1
        if toggle_disabled(disable_flag) and toggle_disabled(mirror_flag):
            (TOGGLES_DIR / f"{disable_flag}.lua").write_text(
                f'hl.monitor({{ output = "{internal}", disabled = true }})\n'
            )
            notify("\uf0379", "Laptop display disabled")
            hypr_reload()
        return 0

    def recover() -> int:
        if external_active():
            return 0
        if not toggle_enabled(disable_flag):
            return 0
        toggle_flag(disable_flag, "off")
        wake()
        return 0

    def toggle() -> int:
        return on() if toggle_enabled(disable_flag) else off()

    actions = {"on": on, "off": off, "recover": recover, "toggle": toggle}
    if action not in actions:
        print("Usage: blackarch-hyprland-monitor-internal {on|off|toggle|recover}", file=sys.stderr)
        return 1
    result = actions[action]()
    return 0 if result is None else result


def cmd_monitor_internal_mirror(action: str) -> int:
    internal = internal_monitor_name()
    external = external_monitor_name()
    toggle_name = "internal-monitor-mirror"
    disable_flag = "internal-monitor-disable"

    def on() -> int:
        if not external:
            notify("\uf0379", "No external monitors found for mirror")
            return 1
        if not internal:
            notify("\uf0379", "No laptop monitor found to mirror")
            return 1
        for output in (internal, external):
            if not CONNECTOR_NAME.match(output):
                notify("\uf0379", "Refusing unsafe monitor name")
                return 1

        toggle_flag(disable_flag, "off")

        if toggle_disabled(toggle_name):
            (TOGGLES_DIR / f"{toggle_name}.lua").write_text(
                f'hl.monitor({{ output = "{external}", mode = "preferred", position = "auto", '
                f'scale = 1, mirror = "{internal}" }})\n'
            )
            notify("\uf0379", f"Mirroring enabled ({external})")
            hypr_reload()
        return 0

    def off() -> int:
        if toggle_enabled(toggle_name):
            toggle_flag(toggle_name, "off")
            notify("\uf0379", "Extended mode restored")
        return 0

    def recover() -> int:
        if not external_active() and toggle_enabled(toggle_name):
            toggle_flag(toggle_name, "off")
        return 0

    def toggle() -> int:
        return off() if toggle_enabled(toggle_name) else on()

    actions = {"on": on, "off": off, "recover": recover, "toggle": toggle}
    if action not in actions:
        print(
            "Usage: blackarch-hyprland-monitor-internal-mirror {on|off|toggle|recover}",
            file=sys.stderr,
        )
        return 1
    result = actions[action]()
    return 0 if result is None else result


# ── monitor scaling math (the awk pieces) ────────────────────────────────────
def gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def clean_scale(scale: float, width: int, height: int) -> float:
    """Round a scale up to the nearest value Hyprland accepts.

    Hyprland only accepts scales where the mode divides into whole logical pixels
    (in 1/120 steps), so clean scales are divisors of gcd(w*120, h*120).
    """
    divisor = gcd(width * 120, height * 120)
    k = math.floor(scale * 120 + 0.5)
    if k > divisor:
        k = divisor
    while divisor % k != 0:
        k += 1
    return k / 120


def format_number(value: float) -> str:
    """awk's `%g`: 6 significant digits, trailing zeros stripped."""
    return f"{value:g}"


def scale_from_current(current: float, direction: str, width: int, height: int) -> float:
    """Step from `current` through the preset list, the awk scale_from_current piece."""
    effective: dict[str, tuple[float, float, float]] = {}
    for preset in PRESET_SCALES:
        value = clean_scale(preset, width, height)
        key = f"{value:.8f}"
        distance = abs(preset - value)
        if key not in effective or distance < effective[key][2]:
            effective[key] = (value, preset, distance)

    entries = sorted(effective.values(), key=lambda item: item[0])
    if not entries:
        return 1.0

    best = min(range(len(entries)), key=lambda i: abs(current - entries[i][0]))
    if direction == "next":
        index = best + 1 if best < len(entries) - 1 else len(entries) - 1
    elif direction == "previous":
        index = best - 1 if best > 0 else 0
    else:
        index = best
    return entries[index][1]


def cmd_monitor_scaling(argument: str = "") -> int:
    if argument == "":
        monitor = focused_monitor()
        if monitor is not None:
            print(format_number(float(monitor.get("scale") or 1)))
        return 0

    if argument in ("-h", "--help"):
        print("Usage: blackarch-hyprland-monitor-scaling [up|down|SCALE]")
        return 0

    def set_scale(requested_scale: str, requested: str | None = None) -> int:
        requested = requested or requested_scale
        monitor = focused_monitor() or {}
        name = monitor.get("name") or ""
        current = monitor.get("scale")
        width = int(monitor.get("width") or 0)
        height = int(monitor.get("height") or 0)
        refresh = monitor.get("refreshRate") or 0

        # `name` is written into the Lua string eval'd below, so only a plain
        # connector name may pass.
        if not CONNECTOR_NAME.match(name):
            print("Refusing unsafe monitor name", file=sys.stderr)
            return 1

        new_scale = clean_scale(float(requested_scale), width, height)
        # GTK only honours integer GDK_SCALE values, so persist the nearest
        # whole factor even when the monitor scale itself is fractional.
        new_gdk_scale = math.floor(new_scale + 0.5)

        scale_text = format_number(new_scale)
        hypr_action(
            f'eval hl.monitor({{ output = "{name}", mode = "{width}x{height}@{refresh}", '
            f'position = "auto", scale = {scale_text} }})'
        )
        audit_scale_change(requested, name, current, new_scale)
        persist_scale(new_scale, new_gdk_scale)
        return 0

    if argument == "up":
        monitor = focused_monitor() or {}
        current = float(monitor.get("scale") or 1)
        width = int(monitor.get("width") or 0)
        height = int(monitor.get("height") or 0)
        return set_scale(
            format_number(scale_from_current(current, "next", width, height)), "up"
        )

    if argument == "down":
        monitor = focused_monitor() or {}
        current = float(monitor.get("scale") or 1)
        width = int(monitor.get("width") or 0)
        height = int(monitor.get("height") or 0)
        return set_scale(
            format_number(scale_from_current(current, "previous", width, height)), "down"
        )

    if argument in [format_number(p) for p in PRESET_SCALES] or re.match(
        r"^[0-9]+([.][0-9]+)?$", argument
    ):
        if SAFE_SCALE.match(argument) and 1 <= float(argument) <= 4:
            return set_scale(argument, argument)

    print("Usage: blackarch-hyprland-monitor-scaling [up|down|SCALE]", file=sys.stderr)
    return 1


def audit_scale_change(
    requested: str, monitor_name: str, current, new_scale: float
) -> None:
    SCALE_LOG.parent.mkdir(parents=True, exist_ok=True)

    def cmdline(pid: int) -> str:
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            return ""
        return re.sub(r"\s+", " ", raw.decode("utf-8", "replace")).strip()

    parent_pid = os.getppid()
    try:
        stat = Path(f"/proc/{parent_pid}/stat").read_text()
        grandparent_pid = int(stat.rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        grandparent_pid = 0

    with SCALE_LOG.open("a") as log:
        log.write(
            f"at={time.strftime('%Y-%m-%dT%H:%M:%S%z')}\trequested={requested}\t"
            f"current={current}\tnew={format_number(new_scale)}\tmonitor={monitor_name}\t"
            f"pid={os.getpid()}\tppid={parent_pid}\tparent={cmdline(parent_pid)}\t"
            f"gppid={grandparent_pid}\tgrandparent={cmdline(grandparent_pid)}\n"
        )


def persist_scale(new_scale: float, new_gdk_scale: int) -> None:
    """Update monitors.lua in place, but only while it still holds Blackarch's
    generic catch-all defaults."""
    if not MONITOR_LUA.is_file():
        return
    text = MONITOR_LUA.read_text()

    if re.search(r"^local blackarch_monitor_scale = ", text, re.MULTILINE):
        text = re.sub(
            r"^local blackarch_monitor_scale = .*",
            f"local blackarch_monitor_scale = {format_number(new_scale)}",
            text,
            flags=re.MULTILINE,
        )
        text = re.sub(
            r"^local blackarch_gdk_scale = .*",
            f"local blackarch_gdk_scale = {new_gdk_scale}",
            text,
            flags=re.MULTILINE,
        )
    elif re.search(
        r'^hl\.monitor\(\{ output = "", mode = "preferred", position = "auto", '
        r'scale = ("auto"|[0-9.]+) \}\)',
        text,
        re.MULTILINE,
    ):
        text = re.sub(
            r'^(hl\.monitor\(\{ output = "", mode = "preferred", position = "auto", scale = )'
            r'([^ ]+)( \}\))',
            lambda m: f"{m.group(1)}{format_number(new_scale)}{m.group(3)}",
            text,
            flags=re.MULTILINE,
        )
        text = re.sub(
            r'^hl\.env\("GDK_SCALE", ".*"\)',
            f'hl.env("GDK_SCALE", "{new_gdk_scale}")',
            text,
            flags=re.MULTILINE,
        )
    else:
        return

    MONITOR_LUA.write_text(text)


# ── monitors.lua parsing (the sed pieces) ────────────────────────────────────
def lua_local_value(name: str) -> str:
    """The value assigned by `local <name> = ...`, without quotes or a comment."""
    if not LUA_IDENTIFIER.match(name) or not MONITOR_LUA.is_file():
        return ""

    pattern = re.compile(
        r'^[ \t]*local[ \t]+' + re.escape(name) + r'[ \t]*=[ \t]*("[^"]*"|[^"[ \t]+)[ \t]*(--.*)?$'
    )
    for line in MONITOR_LUA.read_text().splitlines():
        match = pattern.match(line)
        if match:
            value = match.group(1)
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            return value
    return ""


def lua_scalar(value: str) -> str:
    """A quoted value stands for itself; a bare word may name a local."""
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return lua_local_value(value) or value


def monitor_rules() -> str:
    """The config with its comments cut away."""
    if not MONITOR_LUA.is_file():
        return ""
    text = MONITOR_LUA.read_text()
    # sed is line-oriented: a block comment only spans lines when its `]]`
    # lands on the same one.
    text = re.sub(r"--\[\[[^]\n]*\]\]", "", text)
    text = re.sub(r"--.*", "", text)
    return text


def monitor_rule_regex(output: str) -> re.Pattern:
    return re.compile(
        r'^[ \t]*hl\.monitor\(\{.*output[ \t]*=[ \t]*"' + re.escape(output) + '"'
    )


def configured_monitor_value(output: str, key: str) -> str:
    value = ""
    for line in monitor_rules().splitlines():
        if not monitor_rule_regex(output).match(line):
            continue
        match = re.search(
            r"[{,; \t]" + re.escape(key) + r'[ \t]*=[ \t]*("[^"]*"|[^,;}[ \t]+)[ \t]*([,;}].*)?$',
            line,
        )
        if match:
            value = match.group(1)
            break
    return lua_scalar(value)


def configured_internal_monitor_value(key: str, internal: str) -> str:
    if not internal:
        return ""
    return configured_monitor_value(internal, key)


def configured_monitor_scale(internal: str) -> str:
    scale = configured_internal_monitor_value("scale", internal)
    if not scale:
        scale = configured_monitor_value("", "scale")
    if not scale:
        scale = lua_local_value("blackarch_monitor_scale")
    return scale


def current_internal_scale(internal: str) -> str:
    if not internal:
        return ""
    for monitor in monitors_or_empty(all_outputs=True):
        if monitor.get("name") == internal and monitor.get("disabled") is not True:
            return format_number(float(monitor.get("scale") or 0))
    return ""


def store_internal_scale(scale: str) -> None:
    if not SAFE_SCALE.match(scale):
        return
    TOGGLES_DIR.mkdir(parents=True, exist_ok=True)
    SCALE_STATE.write_text(f"{scale}\n")


def valid_scale(value: str) -> bool:
    return bool(SAFE_SCALE.match(value))


def scales_match(left: str, right: str) -> bool:
    if not (valid_scale(left) and valid_scale(right)):
        return False
    return abs(float(left) - float(right)) < 0.001


def read_monitor_scale(internal: str, configured: str = "") -> str:
    scale = configured or configured_monitor_scale(internal)
    if valid_scale(scale):
        return scale
    if SCALE_STATE.is_file():
        stored = SCALE_STATE.read_text().strip()
        if valid_scale(stored):
            return stored
    return "2"


def read_monitor_position(internal: str) -> str:
    position = configured_internal_monitor_value("position", internal)
    if POSITION.match(position):
        return position
    return "auto"


def enable_internal_output(internal: str, scale: str = "") -> None:
    if not internal:
        return
    scale = scale or read_monitor_scale(internal)
    position = read_monitor_position(internal)
    hypr_dispatch(
        f'hl.monitor({{ output = "{internal}", mode = "preferred", position = "{position}", '
        f"scale = {scale} }})"
    )


def sync_internal_scale(internal: str) -> None:
    if not internal:
        return
    configured = configured_monitor_scale(internal)
    active = current_internal_scale(internal)

    # A config without a usable number delegates the scale to the compositor, so
    # whatever it resolved IS the configured scale.
    if not valid_scale(configured) and valid_scale(active):
        return

    desired = read_monitor_scale(internal, configured)
    if scales_match(active, desired):
        return
    enable_internal_output(internal, desired)


def dpms_internal(internal: str, action: str) -> None:
    if not internal:
        return
    hypr_dispatch(f'hl.dsp.dpms({{ action = "{action}", monitor = "{internal}" }})')


def cmd_monitor_clamshell() -> int:
    internal = internal_monitor_name()

    # INTERNAL is written into generated Lua and hyprctl eval below, so a name
    # that is not a plain connector string could execute on the next reload.
    if internal and not CONNECTOR_NAME.match(internal):
        print("Refusing unsafe internal monitor name", file=sys.stderr)
        return 1

    def remember_scale() -> None:
        store_internal_scale(current_internal_scale(internal))

    def enable_internal() -> None:
        changed = False
        flag = TOGGLES_DIR / "internal-monitor-clamshell.lua"
        if flag.is_file():
            flag.unlink()
            changed = True

        if changed:
            hypr_reload()

        manual_disable = TOGGLES_DIR / "internal-monitor-disable.lua"
        if manual_disable.is_file() and external_active():
            return
        sync_internal_scale(internal)
        if changed:
            dpms_internal(internal, "enable")

    def disable_internal() -> None:
        if not internal:
            return
        manual_disable = TOGGLES_DIR / "internal-monitor-disable.lua"
        if manual_disable.is_file():
            return

        TOGGLES_DIR.mkdir(parents=True, exist_ok=True)
        remember_scale()

        config = f'hl.monitor({{ output = "{internal}", disabled = true }})'
        flag = TOGGLES_DIR / "internal-monitor-clamshell.lua"
        if not flag.is_file() or flag.read_text().strip() != config:
            flag.write_text(f"{config}\n")
            hypr_reload()

    # Recover first: the watcher calls this every few seconds, so it must be a
    # no-op unless it actually re-enables a display.
    cmd_monitor_internal("recover")
    cmd_monitor_internal_mirror("recover")

    if hw_clamshell() and external_active():
        disable_internal()
    else:
        enable_internal()
    return 0


# ── window width save/restore ────────────────────────────────────────────────
def cmd_window_width(action: str) -> int:
    if action not in ("save", "restore"):
        print("Usage: blackarch-hyprland-window-width save|restore", file=sys.stderr)
        return 1

    active = hypr_active_window()
    parts = [active.get("class"), active.get("initialClass"), active.get("title")]
    key = next((part for part in parts if part), "")
    if not key:
        return 1

    workspace = active.get("workspace") or {}
    workspace_id = workspace.get("id") or workspace.get("name") or ""
    if not workspace_id:
        return 1

    filename = f"workspace-{workspace_id}-{key}".replace("/", "_").replace("\n", "_")
    state_file = WINDOW_STATE_DIR / f"{filename}.width"

    def window_width(address: str) -> int:
        for client in hypr_clients():
            if client.get("address") == address:
                size = client.get("size") or []
                if size:
                    return int(size[0])
        raise SystemExit(1)

    def resize_by(window: str, delta: int) -> None:
        hypr_dispatch(
            f'hl.dsp.window.resize({{ window = "{window}", x = {delta}, y = 0, relative = true }})',
            "resizeactive",
            str(delta),
            "0",
            window,
        )

    if action == "save":
        size = active.get("size") or []
        if not size:
            return 1
        width = size[0]
        WINDOW_STATE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = WINDOW_STATE_DIR / f".width.{os.getpid()}"
        temporary.write_text(f"{width}\n")
        temporary.replace(state_file)
        notify(
            "\uf07e",
            f"Saved width for {key} on workspace {workspace_id}",
            "Restore using Super + Home on this workspace.",
        )
        print(f"Saved width for {key} on workspace {workspace_id}")
        return 0

    # restore
    if not state_file.is_file():
        notify(
            "\uf07e",
            f"No saved width found for {key} on workspace {workspace_id}",
            "Use Super + Alt + Home to save one for this workspace.",
        )
        return 1

    width = state_file.read_text().strip()
    if not re.match(r"^[0-9]+$", width):
        return 1

    address = active.get("address") or ""
    if not address:
        return 1
    window = f"address:{address}"

    current_width = window_width(address)
    if current_width == int(width):
        return 0

    direction = ""
    for probe in (10, -10):
        resize_by(window, probe)
        next_width = window_width(address)
        if next_width != current_width:
            direction = 1 if (next_width - current_width) * probe > 0 else -1
            current_width = next_width
            break

    if not direction:
        return 1

    for _ in range(6):
        delta = int(width) - current_width
        if delta == 0:
            break
        resize_by(window, delta * direction)
        next_width = window_width(address)
        if next_width == current_width:
            break
        current_width = next_width
    return 0


# ── reload guard ─────────────────────────────────────────────────────────────
def reload_guard_instances() -> list[tuple[str, str]]:
    instances = []
    root = Path(RELOAD_GUARD_RUN_ROOT)
    if not root.is_dir():
        return instances

    for instance_dir in sorted(root.glob("*/hypr/*")):
        if not instance_dir.is_dir():
            continue
        signature = instance_dir.name
        hypr_dir = instance_dir.parent
        runtime_dir = hypr_dir.parent
        if not runtime_dir.name.isdigit():
            continue
        instances.append((str(runtime_dir), signature))
    return instances


def reload_guard_pause(runtime_dir: str, signature: str) -> None:
    state_file = Path(RELOAD_GUARD_STATE_DIR) / signature
    Path(RELOAD_GUARD_STATE_DIR).mkdir(parents=True, exist_ok=True)

    if not state_file.is_file():
        disable_autoreload = hypr_getoption(
            "misc.disable_autoreload", instance=signature
        )
        suppress_errors = hypr_getoption("debug.suppress_errors", instance=signature)
        if disable_autoreload is None or suppress_errors is None:
            return
        state_file.write_text(
            f"{runtime_dir}\t{str(disable_autoreload.get('bool')).lower()}\t"
            f"{str(suppress_errors.get('bool')).lower()}\n"
        )

    hypr_action_with_runtime(
        runtime_dir,
        signature,
        'eval hl.config({ misc = { disable_autoreload = true }, '
        'debug = { suppress_errors = true } })',
    )


def hypr_action_with_runtime(runtime_dir: str, signature: str, command: str) -> str:
    path = Path(runtime_dir) / "hypr" / signature / ".socket.sock"
    if not path.exists():
        return ""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        try:
            sock.connect(str(path))
            sock.sendall(f"/{command}".encode())
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError:
            return ""
    return b"".join(chunks).decode("utf-8", "replace")


def reload_guard_resume(state_file: Path) -> None:
    fields = state_file.read_text().split("\t")
    if len(fields) < 3:
        return
    runtime_dir, disable_autoreload, suppress_errors = fields[0], fields[1], fields[2]
    signature = state_file.name

    if Path(runtime_dir).is_dir():
        hypr_action_with_runtime(
            runtime_dir,
            signature,
            f"eval hl.config({{ debug = {{ suppress_errors = {suppress_errors} }} }})",
        )
        hypr_action_with_runtime(runtime_dir, signature, "reload")
        hypr_action_with_runtime(
            runtime_dir,
            signature,
            f"eval hl.config({{ misc = {{ disable_autoreload = {disable_autoreload} }}, "
            f"debug = {{ suppress_errors = {suppress_errors} }} }})",
        )

    state_file.unlink(missing_ok=True)


def cmd_reload_guard(command: str) -> int:
    if command not in ("pause", "resume", "paused"):
        print("Usage: blackarch-hyprland-reload-guard pause|resume|paused", file=sys.stderr)
        return 1

    if command == "paused":
        return 0 if list(Path(RELOAD_GUARD_STATE_DIR).glob("*")) else 1

    if command == "pause":
        for runtime_dir, signature in reload_guard_instances():
            reload_guard_pause(runtime_dir, signature)
        return 0

    state_dir = Path(RELOAD_GUARD_STATE_DIR)
    if not state_dir.is_dir():
        return 0
    for state_file in sorted(state_dir.glob("*")):
        if state_file.is_file():
            reload_guard_resume(state_file)
    try:
        state_dir.rmdir()
    except OSError:
        pass
    return 0


# ── monitor watch ────────────────────────────────────────────────────────────
def cmd_monitor_watch() -> int:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    socket_path = Path(runtime) / "hypr" / (
        os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or ""
    ) / ".socket2.sock"
    clamshell_lock = Path(runtime) / "blackarch-monitor-clamshell.lock"
    modeless_lock = Path(runtime) / "blackarch-monitor-modeless.lock"

    clamshell_lock_fd = os.open(clamshell_lock, os.O_CREAT | os.O_RDWR, 0o644)
    modeless_lock_fd = os.open(modeless_lock, os.O_CREAT | os.O_RDWR, 0o644)

    poll_process: subprocess.Popen | None = None

    def sync_clamshell() -> None:
        try:
            fcntl.flock(clamshell_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        try:
            cmd_monitor_clamshell()
        finally:
            fcntl.flock(clamshell_lock_fd, fcntl.LOCK_UN)

    def sync_clamshell_after_monitor_change() -> None:
        sync_clamshell()

        def retries() -> None:
            for delay in (1, 3, 7):
                time.sleep(delay)
                sync_clamshell()

        threading.Thread(target=retries, daemon=True).start()

    def recover_modeless() -> None:
        def loop() -> None:
            try:
                fcntl.flock(modeless_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return

            delay = 3
            unanswered = 0
            try:
                while True:
                    state = monitor_modeless()
                    if state == 1:
                        break
                    if state == 2:
                        unanswered += 1
                        if unanswered > 20:
                            break
                    else:
                        unanswered = 0

                    reloaded = False
                    if state == 0 and cmd_reload_guard("paused") != 0:
                        hypr_reload()
                        reloaded = True

                    time.sleep(delay)
                    if reloaded:
                        delay = min(delay * 2, 60)
            finally:
                fcntl.flock(modeless_lock_fd, fcntl.LOCK_UN)

        threading.Thread(target=loop, daemon=True).start()

    def poll_clamshell_state() -> None:
        while True:
            time.sleep(2)
            sync_clamshell()

    def sync_poll_state() -> None:
        nonlocal poll_process
        if hw_laptop() and external_active():
            if poll_process is None or poll_process.poll() is not None:
                poll_process = subprocess.Popen(
                    [
                        "/usr/bin/python3",
                        str(Path(__file__).resolve()),
                        "monitor-watch-poll",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        elif poll_process is not None:
            poll_process.terminate()
            poll_process = None

    def watch_poll() -> None:
        """Run the poll loop in-process (used by monitor-watch-poll)."""
        while True:
            time.sleep(2)
            sync_clamshell()

    sync_clamshell_after_monitor_change()
    sync_poll_state()
    recover_modeless()

    # Process substitution (not a pipe) keeps the loop in the main process.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(None)
        sock.connect(str(socket_path))
        buffer = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                event = line.decode("utf-8", "replace")
                if event.startswith(("monitoradded>", "monitoraddedv2>")) or event.startswith(
                    ("monitorremoved>", "monitorremovedv2>")
                ):
                    sync_clamshell_after_monitor_change()
                    sync_poll_state()
                    recover_modeless()
                elif event.startswith("configreloaded>"):
                    recover_modeless()
    return 0


def cmd_monitor_watch_poll() -> int:
    """The background clamshell reconciliation poll."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    lock = Path(runtime) / "blackarch-monitor-clamshell.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o644)
    while True:
        time.sleep(2)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            continue
        try:
            cmd_monitor_clamshell()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


# ── dispatch ─────────────────────────────────────────────────────────────────
COMMANDS = {
    "focus-app": (cmd_focus_app, "<app-name>"),
    "monitor-clamshell": (cmd_monitor_clamshell, ""),
    "monitor-external-active": (cmd_monitor_external_active, ""),
    "monitor-focused": (cmd_monitor_focused, ""),
    "monitor-focused-apple": (cmd_monitor_focused_apple, "[monitor]"),
    "monitor-internal": (cmd_monitor_internal, "<on|off|toggle|recover>"),
    "monitor-internal-mirror": (cmd_monitor_internal_mirror, "<on|off|toggle|recover>"),
    "monitor-laptop": (cmd_monitor_laptop, ""),
    "monitor-modeless": (cmd_monitor_modeless, ""),
    "monitor-scaling": (cmd_monitor_scaling, "[up|down|SCALE]"),
    "monitor-watch": (cmd_monitor_watch, ""),
    "monitor-watch-poll": (cmd_monitor_watch_poll, ""),
    "reload-guard": (cmd_reload_guard, "<pause|resume|paused>"),
    "session-locked": (cmd_session_locked, ""),
    "toggle": (cmd_toggle, "<flag-name> [on|off|toggle]"),
    "toggle-disabled": (cmd_toggle_disabled, "<flag-name>"),
    "toggle-enabled": (cmd_toggle_enabled, "<flag-name>"),
    "window-close-all": (cmd_window_close_all, ""),
    "window-gaps-toggle": (cmd_window_gaps_toggle, ""),
    "window-pop": (cmd_window_pop, "[width height [x y]]"),
    "window-single-square-aspect-toggle": (cmd_window_single_square_aspect_toggle, ""),
    "window-tiled-fullscreen-toggle": (cmd_window_tiled_fullscreen_toggle, ""),
    "window-transparency-toggle": (cmd_window_transparency_toggle, ""),
    "window-width": (cmd_window_width, "<save|restore>"),
    "workspace-layout-toggle": (cmd_workspace_layout_toggle, ""),
    "workspace-toggle-gaps": (cmd_workspace_toggle_gaps, ""),
}


FAMILY_PREFIX = "blackarch-hyprland-"


def component_from_argv0(argv0: str) -> str:
    """The subcommand implied by this program's own name.

    The keybindings call the family by member name (`blackarch-hyprland-monitor-internal`),
    but one file implements the whole family, so a symlink named after the member
    is how the dispatcher-free call resolves. Strip the prefix and return the
    rest; "" when this is the plain `blackarch-hyprland` binary.
    """
    name = os.path.basename(argv0 or "")
    if name.startswith(FAMILY_PREFIX):
        return name[len(FAMILY_PREFIX):]
    return ""


def main(argv: list[str]) -> int:
    # `blackarch hyprland <name>` passes the name as the first argument;
    # `blackarch-hyprland-<name>` reaches us through argv[0]. Both are accepted,
    # with argv[0] taking precedence so a direct member call works.
    implied = component_from_argv0(sys.argv[0] if sys.argv else "")
    if implied:
        argv = [implied, *argv]

    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: blackarch-hyprland <command> [args...]")
        print("Commands: " + " ".join(sorted(COMMANDS)))
        return 0

    command, args = argv[0], argv[1:]
    if command not in COMMANDS:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1

    handler, _ = COMMANDS[command]

    if command == "focus-app":
        if not args:
            print("Usage: blackarch-hyprland-focus-app <app-name>", file=sys.stderr)
            return 1
        return handler(args[0])
    if command == "monitor-focused-apple":
        return handler(args[0] if args else "")
    if command == "monitor-internal":
        return handler(args[0] if args else "")
    if command == "monitor-internal-mirror":
        return handler(args[0] if args else "")
    if command == "monitor-scaling":
        return handler(args[0] if args else "")
    if command == "reload-guard":
        return handler(args[0] if args else "")
    if command == "toggle":
        if not args:
            print("Usage: blackarch-hyprland-toggle <flag-name> [on|off|toggle]", file=sys.stderr)
            return 1
        return handler(args[0], args[1] if len(args) > 1 else "toggle")
    if command in ("toggle-enabled", "toggle-disabled"):
        return handler(args[0]) if args else 1
    if command == "window-width":
        return handler(args[0] if args else "")
    if command == "window-pop":
        width = int(args[0]) if len(args) > 0 else 1300
        height = int(args[1]) if len(args) > 1 else 900
        x = args[2] if len(args) > 2 else ""
        y = args[3] if len(args) > 3 else ""
        return handler(width, height, x, y)

    return handler()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
