# Hyprland IPC (hyprctl) — wire protocol

Everything needed to talk to a running Hyprland compositor from a standalone
script with **no `hyprctl` binary**. Reverse-engineered from the Hyprland
sources and confirmed against a live 0.56.2 compositor.

## Transport

Unix domain socket at `$XDG_RUNTIME_DIR/hypr/<HYPRLAND_INSTANCE_SIGNATURE>/.socket.sock`.

## Request format

A **single string**, no framing, no length prefix, no trailing newline:

```
j/<command> [args]     # ask for JSON
/<command> [args]     # ask for the human-readable form
```

The first character is the mode, the second is a literal `/`. `hyprctl -j X`
sends `j/X`; `hyprctl X` sends `/X`. The flag position on the hyprctl command line
does not matter.

## Response

Plain text, UTF-8, no terminator beyond what the command itself emits. For JSON
requests it is a JSON document (pretty-printed with 4 spaces).

## Modelling hyprctl's exit status

| request | reply | hyprctl exit |
| --- | --- | --- |
| `dispatch <lua>` | `ok` | 0 |
| `dispatch <lua>` | `error: ...` + hint block | 7 |
| `eval <lua>` | `ok` | 0 |
| `keyword <kw>` | `ok` | 0 |
| `keyword <bad>` | `Not enough arguments in '...'` | 255 |
| `reload` | `ok` | 0 |
| `getoption <x>` | JSON, or `no such option` | 0 either way |

So the success test for `dispatch` / `eval` / `keyword` / `reload` is
**reply starts with `ok`**; everything else is the error path. A wrapper that
treats any non-zero exit as "not running" gets the right answer for transport
failures and for the `keyword`/`dispatch` errors alike.

## Commands used by the Blackarch tooling

```
j/monitors            j/monitors all        j/activeworkspace
j/activewindow        j/clients             j/workspacerules
j/getoption <name>
/dispatch <lua>        /eval <lua>           /keyword <kw>
/reload
```

`monitors all` includes disabled outputs; plain `monitors` does not.
`getoption` returns `{"option", "bool", "set"}` and exits 0 even for an
unknown option (`no such option`).

## The Lua dispatch path is the only working one

Hyprland 0.56 builds `dispatch` by wrapping the arguments as
`return hl.dispatch(<args>)`. The classic `hyprctl dispatch focuswindow <addr>`
therefore produces a Lua parse error and exits 7:

```
error: [string "return hl.dispatch(focuswindow address:0x..."]:1: ')' expected
```

Only `dispatch 'hl.dsp.<module>.<fn>({ ... })'` works. Any Blackarch script that
has a `hyprctl dispatch hl.dsp... || hyprctl dispatch <classic>` fallback is
carrying a dead branch — port the fallback anyway to stay faithful, but do not
expect it to run.

`keyword` is likewise a no-op on current builds:

```
keyword can't work with non-legacy parsers. Use eval.
```

## Instance selection

`HYPRLAND_INSTANCE_SIGNATURE` names the directory. `hyprctl --instance <sig>`
sends the same request to `$XDG_RUNTIME_DIR/hypr/<sig>/.socket.sock` — used by
tools that fan out to several compositors (e.g. a reload guard). When the
signature is unset, fall back to the single `/run/user/<uid>/hypr/*` entry.

## Event stream

`.socket2.sock` (same directory) streams newline-terminated events:
`monitoradded>>eDP-1`, `monitoraddedv2>>`, `monitorremoved>>`,
`configreloaded>>`. Reading it is a plain socket read; `socat -U - UNIX-CONNECT:<path>`
is only a convenience. Blocking reads are fine — the connection stays open.
