# Quickshell IPC (qs ipc) — wire protocol

Everything needed to call a running quickshell instance from a standalone
script with **no `qs` binary**. Reverse-engineered from the quickshell sources
(`quickshell-mirror/quickshell`, commit `43d4fa9e`) and confirmed against a live
instance. Used by the `blackarch-shell` Python port.

## Transport

Unix domain socket at `$XDG_RUNTIME_DIR/quickshell/by-id/<instanceId>/ipc.sock`
(default `/run/user/<uid>` when `XDG_RUNTIME_DIR` is unset).

The stream is a sequence of `QDataStream` values, all **big-endian**.

## QString codec (QDataStream)

```
quint32 byteLength      # 0xFFFFFFFF means a null QString
byteLength bytes of UTF-16BE   # no BOM, no terminator
```

`byteLength` counts **bytes**, not characters, and is always even.

## Request: StringCallCommand

Variant index **3** — the 4th alternative of
`std::variant<monostate, IpcKillCommand, QueryMetadataCommand, StringCallCommand,
SignalListenCommand, StringPropReadCommand>`. The variant tag is a single
`quint8`.

```
quint8  3                      # StringCallCommand
QString target
QString function
quint32 argumentCount
QString argument[argumentCount]
```

## Response: StringCallResponse

```
quint8 variantIndex
```

| index | alternative          | payload |
| ----- | -------------------- | ------- |
| 0     | monostate            | — (server closed the connection) |
| 1     | NoCurrentGeneration  | — |
| 2     | TargetNotFound       | — |
| 3     | EntryNotFound        | — |
| 4     | ArgParseFailed       | WireFunctionDefinition, bool isCountMismatch, quint8 paramIndex |
| 5     | Completed            | bool isVoid, QString returnValue |

`WireFunctionDefinition` = `QString name`, `QString returnType`,
`quint32 argCount`, then `argCount` × (`QString paramName`, `QString paramType`).

## What `qs ipc call` prints

All of these go to **stdout**, and `qs` exits **0** for IPC-level failures —
only a transport failure (cannot connect, wrong display) is a non-zero exit.
That is why a wrapper script that captures stdout and ignores stderr still sees
these strings.

| response | stdout |
| --- | --- |
| 1 | `Not ready to accept queries yet.` |
| 2 | `Target not found.` |
| 3 | `Function not found.` |
| 4, count mismatch | `Too {many\|few} arguments provided ({required} required but {provided} were provided.)` then `Function definition: {def}` |
| 4, bad value | `Unable to parse argument {n} as {type}. Provided argument: {value}` then `Function definition: {def}` |
| 5, not void | the return value |

`{def}` is rendered as
`function {name}({param}: {type}, ...): {returnType}`.

## Instance discovery

quickshell keeps a runtime tree under `$XDG_RUNTIME_DIR/quickshell/`:

```
by-id/<instanceId>/          # holds ipc.sock and instance.lock
by-shell/<shellId>/<id>  ->  by-id/<id>
by-path/<shellId>        ->  by-shell/<shellId>
by-pid/<pid>            ->  by-id/<id>
```

`shellId` is **md5 of the `shell.qml` path** (lowercase hex, of the *cleaned*
absolute path — hashing both the literal and the symlink-resolved spelling is
cheap insurance). So:

```
socket = $XDG_RUNTIME_DIR/quickshell/by-shell/<md5(shell.qml)>/<id>/ipc.sock
```

`by-pid` is the only way to map an instance back to a pid without parsing
`instance.lock`.

## Display matching

`qs` filters instances by display. `instance.lock` records the display as
`<protocol>/<name>`, e.g. `wayland/wayland-1` or `x11/:0`. Reading it means
parsing `InstanceInfo` (4 QStrings, a QDateTime, a `qint32` pid, a QString) —
fragile across versions.

Simpler and version-proof: read the instance's own display from
`/proc/<pid>/environ` (via the `by-pid` symlinks) and format it the same way:
`wayland/<WAYLAND_DISPLAY>` if set, else `x11/<DISPLAY>`, else `x11/:0`.

With no matching instance `qs` exits **255**; a wrapper that treats any
non-zero exit as "not running" gets the right answer either way, so the
display filter is an edge case (a `WAYLAND_DISPLAY` pointing at a different
compositor) rather than a correctness requirement. If the instance's display
cannot be determined, prefer talking to the instance over refusing it.

## Recovering WAYLAND_DISPLAY

A caller from outside the graphical session (ssh, TTY) has no
`WAYLAND_DISPLAY`. Recover it from the newest compositor socket:

```python
runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
sockets = [p for p in runtime.glob("wayland-[0-9]*") if not p.name.endswith(".lock")]
if sockets and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ["WAYLAND_DISPLAY"] = max(sockets, key=lambda p: p.stat().st_mtime_ns).name
```

## Timeout

`timeout --kill-after=1s 2s qs ...` returns 124 (SIGTERM) or 137 (SIGKILL).
A single socket deadline over connect + send + receive models this exactly;
both codes mean "not responding".

## Useful references

- `src/ipc/ipccommand.hpp` — variant order (defines the command/response tags)
- `src/io/ipccomm.hpp` — command field order
- `src/io/ipccomm.cpp` — `callFunction`, the exact error strings
- `src/core/paths.cpp` — `QsPaths`, the runtime tree layout
- `src/core/instanceinfo.hpp` — `InstanceInfo` field order
