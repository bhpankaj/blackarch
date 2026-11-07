#!/usr/bin/env python3
# blackarch:summary=Send an IPC call to the running Blackarch shell
# blackarch:args=[-q] <target> <method> [args...]
# blackarch:examples=blackarch shell shell ping | blackarch-shell shell toggle blackarch.menu '{"menu":"root"}'
"""blackarch-shell — send an IPC call to the running Blackarch shell.

Python port of the bash `blackarch-shell`. It speaks the quickshell IPC
protocol directly over the instance's unix socket, so it needs no `qs` binary,
no `timeout(1)`, and no other external command.

Usage: blackarch-shell [-q] <target> <method> [args...]
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import struct
import sys
from pathlib import Path

# ── quickshell IPC wire format ────────────────────────────────────────────────
# Request  : quint8 3 (StringCallCommand) | QString target | QString function
#            | quint32 argCount | QString arg...
# Response : quint8 variantIndex | payload
# The variant index is the 1-based position in
# std::variant<monostate, NoCurrentGeneration, TargetNotFound, EntryNotFound,
#              ArgParseFailed, Completed>.
COMMAND_STRING_CALL = 3

RESPONSE_NOT_READY = 1
RESPONSE_TARGET_NOT_FOUND = 2
RESPONSE_FUNCTION_NOT_FOUND = 3
RESPONSE_ARGUMENT_MISMATCH = 4
RESPONSE_COMPLETED = 5

MAX_QSTRING_BYTES = 1 << 20  # quickshell's own QString size cap

DEFAULT_IPC_TIMEOUT = 2.0
KILL_AFTER = 1.0

DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)?")


# ── Qt QDataStream string codec ───────────────────────────────────────────────
def encode_qstring(value: str) -> bytes:
    """QDataStream QString: quint32 byte length + UTF-16BE (no BOM)."""
    encoded = value.encode("utf-16-be")
    if len(encoded) > MAX_QSTRING_BYTES:
        raise ValueError(f"QString is too large: {len(encoded)} bytes")
    return struct.pack(">I", len(encoded)) + encoded


class QStringReader:
    """Reads QDataStream QStrings out of a buffer."""

    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.offset = offset

    def read(self) -> str | None:
        if self.offset + 4 > len(self.data):
            raise EOFError("truncated QString length")
        (length,) = struct.unpack_from(">I", self.data, self.offset)
        self.offset += 4

        if length == 0xFFFFFFFF:  # null QString
            return None
        if length % 2 != 0 or length > MAX_QSTRING_BYTES:
            raise ValueError(f"invalid QString length: {length} bytes")
        if self.offset + length > len(self.data):
            raise EOFError("truncated QString body")

        value = self.data[self.offset : self.offset + length].decode("utf-16-be")
        self.offset += length
        return value

    def read_u32(self) -> int:
        if self.offset + 4 > len(self.data):
            raise EOFError("truncated uint32")
        (value,) = struct.unpack_from(">I", self.data, self.offset)
        self.offset += 4
        return value

    def read_u8(self) -> int:
        if self.offset + 1 > len(self.data):
            raise EOFError("truncated uint8")
        value = self.data[self.offset]
        self.offset += 1
        return value


# ── quickshell instance discovery ─────────────────────────────────────────────
def runtime_dir() -> Path:
    """$XDG_RUNTIME_DIR/quickshell, or /run/user/<uid>/quickshell.

    qs appends "quickshell" itself; this is not "shell".
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        base = f"/run/user/{os.getuid()}"
    return Path(base) / "quickshell"


def shell_id(shell_qml: Path) -> str:
    """quickshell's per-config directory id: md5 of the shell.qml path."""
    return hashlib.md5(str(shell_qml).encode("utf-8")).hexdigest()


def instance_sockets(shell_qml: Path) -> list[Path]:
    """Every live socket for this config, via by-path -> by-shell -> by-id."""
    sid = shell_id(shell_qml)
    run = runtime_dir()

    # qs hashes the cleaned config path; accept both the literal and the
    # symlink-resolved spelling so a symlinked BLACKARCH_PATH still resolves.
    for candidate in (shell_qml, Path(os.path.realpath(shell_qml))):
        candidate_sid = hashlib.md5(str(candidate).encode("utf-8")).hexdigest()
        shell_dir = run / "by-shell" / candidate_sid
        if not shell_dir.is_dir():
            continue
        sockets = []
        for entry in sorted(shell_dir.iterdir()):
            sock = entry / "ipc.sock"
            if sock.exists():
                sockets.append(sock)
        if sockets:
            return sockets
    return []


def instance_pids() -> dict[str, int]:
    """Map instance id -> pid, from the by-pid symlinks."""
    by_pid = runtime_dir() / "by-pid"
    if not by_pid.is_dir():
        return {}

    pids: dict[str, int] = {}
    for entry in sorted(by_pid.iterdir()):
        if not entry.name.isdigit():
            continue
        try:
            target = entry.resolve()
        except OSError:
            continue
        if target.parent.name == "by-id":
            pids[target.name] = int(entry.name)
    return pids


def protocol_display(wayland_display: str | None, x11_display: str | None) -> str:
    """Render a display the way qs does: "<protocol>/<name>"."""
    if wayland_display:
        return f"wayland/{wayland_display}"
    if x11_display:
        return f"x11/{x11_display}"
    return "x11/:0"


def current_display() -> str:
    return protocol_display(
        os.environ.get("WAYLAND_DISPLAY"), os.environ.get("DISPLAY")
    )


def process_display(pid: int) -> str | None:
    """The display a running instance was started on, read from its environment."""
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None

    env: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        key, sep, value = entry.partition(b"=")
        if sep:
            env[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return protocol_display(env.get("WAYLAND_DISPLAY"), env.get("DISPLAY"))


def select_socket(shell_qml: Path, display: str) -> Path | None:
    """Pick the live instance socket matching the current display, or None.

    qs filters instances by display; when the instance's display cannot be
    determined we keep the candidate rather than refusing to talk to it.

    An instance whose pid is gone is skipped. qs leaves `by-shell` entries and
    `ipc.sock` files behind after an instance dies, so a bare display match can
    otherwise select a corpse: `process_display` returns None for a missing
    `/proc/<pid>`, and None is treated as "keep", which puts the dead entry back
    in the candidate list. The first corpse in sorted order then wins, and every
    later call fails with "blackarch-shell is not running" even though a live
    shell is running. Requiring a live pid is what makes the choice meaningful.
    """
    pids = instance_pids()
    matching: list[Path] = []

    for sock in instance_sockets(shell_qml):
        instance_id = sock.parent.name
        if instance_id not in pids:
            continue
        if not Path(f"/proc/{pids[instance_id]}").is_dir():
            continue
        instance_display = process_display(pids[instance_id])
        if instance_display is None or instance_display == display:
            matching.append(sock)

    return matching[0] if matching else None


def recover_wayland_display() -> None:
    """Fill in WAYLAND_DISPLAY from the compositor socket when it is unset.

    A caller from outside the graphical session (an ssh or TTY
    blackarch-restart-shell, and the migrations it runs for) has none.
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        return

    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    sockets = []
    for entry in runtime.glob("wayland-[0-9]*"):
        if entry.name.endswith(".lock"):
            continue
        try:
            sockets.append((entry.stat().st_mtime_ns, entry.name))
        except OSError:
            continue

    if sockets:
        os.environ["WAYLAND_DISPLAY"] = max(sockets)[1]


# ── IPC call ──────────────────────────────────────────────────────────────────
def parse_duration(text: str) -> float:
    """Parse a coreutils `timeout` duration: '2s', '500ms', '3', '1m30s'."""
    position = 0
    total = 0.0
    units = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}

    for match in DURATION_RE.finditer(text):
        if match.start() != position:
            raise ValueError(f"invalid duration: {text!r}")
        position = match.end()
        total += float(match.group(1)) * units[match.group(2) or "s"]

    if position != len(text) or total <= 0:
        raise ValueError(f"invalid duration: {text!r}")
    return total


def function_definition(
    name: str, return_type: str, arguments: list[tuple[str, str]]
) -> str:
    params = ", ".join(f"{arg_name}: {arg_type}" for arg_name, arg_type in arguments)
    return f"function {name}({params}): {return_type}"


def build_request(target: str, function: str, arguments: list[str]) -> bytes:
    payload = bytes([COMMAND_STRING_CALL])
    payload += encode_qstring(target)
    payload += encode_qstring(function)
    payload += struct.pack(">I", len(arguments))
    for argument in arguments:
        payload += encode_qstring(argument)
    return payload


class IpcError(Exception):
    """A response the CLI surfaces as a plain failure."""


def call(target: str, function: str, arguments: list[str], timeout: float) -> str:
    """Send one StringCallCommand and return what `qs ipc call` would print.

    Raises IpcError with the message qs prints, or OSError when the shell
    cannot be reached at all.
    """
    request = build_request(target, function, arguments)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(SOCKET_PATH))
        sock.sendall(request)

        data = bytearray()
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("ipc timeout") from None
            if not chunk:
                break
            data += chunk

    reader = QStringReader(bytes(data))
    code = reader.read_u8()

    if code == RESPONSE_COMPLETED:
        is_void = reader.read_u8()
        value = reader.read()
        return "" if is_void else (value or "")

    if code == RESPONSE_TARGET_NOT_FOUND:
        raise IpcError("Target not found.")
    if code == RESPONSE_FUNCTION_NOT_FOUND:
        raise IpcError("Function not found.")
    if code == RESPONSE_NOT_READY:
        raise IpcError("Not ready to accept queries yet.")

    if code == RESPONSE_ARGUMENT_MISMATCH:
        name = reader.read() or ""
        return_type = reader.read() or ""
        count = reader.read_u32()
        arguments_def = [
            (reader.read() or "", reader.read() or "") for _ in range(count)
        ]
        is_count_mismatch = reader.read_u8()
        param_index = reader.read_u8()
        definition = function_definition(name, return_type, arguments_def)

        if is_count_mismatch:
            required = len(arguments_def)
            provided = len(arguments)
            which = "many" if required < provided else "few"
            raise IpcError(
                f"Too {which} arguments provided ({required} required but {provided} "
                f"were provided.)\nFunction definition: {definition}"
            )

        argument_type = arguments_def[param_index][1]
        provided = arguments[param_index]
        raise IpcError(
            f"Unable to parse argument {param_index + 1} as {argument_type}. "
            f"Provided argument: {provided}\nFunction definition: {definition}"
        )

    raise IpcError("Received invalid IPC response.")


# ── CLI ───────────────────────────────────────────────────────────────────────
SOCKET_PATH: Path | None = None


def usage() -> None:
    print("""Usage: blackarch-shell [-q] <target> <method> [args...]

Forwards an IPC call to the running Blackarch shell. The shell is expected
to already be running; this command does not start it.

Options:
  -q  Quiet best-effort mode. Suppress output and return success even when
      the shell, target, method, or arguments are unavailable.

Examples:
  blackarch-shell shell ping
  blackarch-shell -q blackarch.indicators refresh
  blackarch-shell shell listPlugins
  blackarch-shell shell toggle blackarch.menu '{"menu":"root"}'""")


def main(argv: list[str]) -> int:
    quiet = False
    if argv and argv[0] == "-q":
        quiet = True
        argv = argv[1:]

    def fail(message: str) -> int:
        if quiet:
            return 0
        print(message, file=sys.stderr)
        return 1

    if not argv or argv[0] in ("-h", "--help"):
        usage()
        return 0

    if len(argv) < 2:
        return fail("Usage: blackarch-shell <target> <method> [args...]")

    blackarch_path = os.environ.get("BLACKARCH_PATH")
    if not blackarch_path:
        return fail("BLACKARCH_PATH is not set")

    shell_qml = Path(blackarch_path) / "shell" / "shell.qml"
    if not shell_qml.is_file():
        return fail(f"blackarch-shell config not found: {shell_qml}")

    recover_wayland_display()

    # A `shell summon|toggle <target>` call takes an optional payload; without
    # one it is the same as an empty JSON object.
    if len(argv) == 3 and argv[0] == "shell" and argv[1] in ("summon", "toggle"):
        argv = [*argv, "{}"]

    global SOCKET_PATH
    SOCKET_PATH = select_socket(shell_qml, current_display())
    if SOCKET_PATH is None:
        return fail("blackarch-shell is not running")

    try:
        timeout = parse_duration(os.environ.get("BLACKARCH_SHELL_IPC_TIMEOUT", "2s"))
    except ValueError:
        timeout = DEFAULT_IPC_TIMEOUT

    try:
        output = call(argv[0], argv[1], argv[2:], timeout)
    except TimeoutError:
        return fail("blackarch-shell is not responding")
    except OSError:
        return fail("blackarch-shell is not running")
    except IpcError as error:
        return fail(str(error))

    if not quiet and output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
