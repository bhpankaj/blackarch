# Bash → Python Dispatcher Port

Porting a large bash script (dispatcher / system tool / installer) to Python. The
goal is one-for-one behavioural parity, not a "better" rewrite.

## Delivery shapes (confirm before writing)

- **Standalone port** — one self-contained Python file that runs on its own,
  with the bash original left in place. Do NOT add a thin launcher, a
  `<cmd>.bash-orig` copy, or a dispatcher entry unless asked. This is what the
  user means by "standalone python script only". While it is a work in
  progress it may carry a `.py` suffix; **the moment it is dropped into the
  dispatcher's bin directory it must not** — the dispatcher registers every
  `blackarch-*` file there as a command, so `blackarch-menu.py` becomes a bogus
  `menu.py` route. See SKILL.md.
- **Wired-in port** — the command keeps its existing name and PATH entry. Then
  the launcher pattern in *Launchers and symlinked command directories* below
  applies, and the original is preserved as `<cmd>.bash-orig`.
- **Family port** — one file replaces a whole `blackarch-<group>-*` family
  (`blackarch-hyprland-*`, `blackarch-restart-*`). Name it `blackarch-<group>`,
  keep it self-contained, and select the component from `argv[0]` when invoked
  as `blackarch-<group>-<name>` (strip the prefix) or from the first argument
  when invoked as `blackarch <group> <name>`. One file per member is wrong twice
  over: the dispatcher glob registers each as its own route, and the shared
  helpers (process lookup, IPC client, Hyprland socket) get copied per file.
  Callers that invoke it directly (a menu action running `blackarch-restart-shell`)
  need `/usr/sbin` symlinks — those need sudo, so hand that step to the user.

  Some members break this pattern by existing as their own file even though the
  family has a root (`blackarch installer`, `blackarch-restart-audio`),
  and some families have no root file at all (the theme switchers). Keep the
  member list in one table keyed by family and mark each member's shape; a
  dispatcher built from that table is what `references/command-family-dispatcher.md`
  covers. Do not infer a member's shape from its name.

## Procedure

1. **Read the whole original first.** Never port from excerpts; bash idioms you
   skipped (a second definition that shadows an earlier one, a commented-out
   branch that reveals intent) become silent behaviour changes.
2. **Check the runtime before designing.** `$PATH`, `id -u`, `XDG_RUNTIME_DIR`,
   `WAYLAND_DISPLAY`, whether sudo is NOPASSWD, and whether each external
   command the script calls actually exists. Do this before writing any code —
   it decides how the sudo/env helpers must be shaped.
3. **Mirror the file layout.** Keep the same section order and name each
   Python function after the bash function it replaces. Future diffing between
   the two files is the main maintenance tool.
4. **Port the helpers first**, then the leaf subcommands, then the dispatcher.
   The dispatcher is untestable until the leaves exist.
5. **Snapshot the environment once** into a module-level dict and read through
   it. Bash exports variables to children; Python does not, so anything a child
   process needs (`KBD_DEVICE`, `PATH`, session vars) must be passed explicitly
   in the child env — otherwise the port works in the shell and fails in a
   detached service.
6. **Translate each shell construct deliberately:**
   - `$1`, `${2:-x}`, `shift` → explicit positional/`argparse`-free parameters.
   - `local` variables → function scope (free).
   - `<<< "$var"`, `xargs`, `sed -n` → the string/array operation directly.
   - `printf '%q'` → `shlex.quote`; `sed -E 's/…/…/'` → `re.sub`.
   - `[[ -L ]]`, `-s`, `-e` → `Path.is_symlink()`, `read_text()`, `exists()`.
   - `case` → `if/elif` chain; keep the case arms verbatim as comments.
   - A `jq` filter → read the exact JSON path the jq expression names. The
     nesting jq selects is not always the nesting you assume — see the pitfalls.
8. **Separate "read the value" from "strip the value" in your helpers.** Bash
   `$(cmd)` strips *all* trailing whitespace; `sed -i` on a multi-line file
   needs the inner newlines intact. A single `read_text().strip()` helper used
   for both silently corrupts multi-line content. Provide two: one that strips
   for single-line sysfs/procfs values, one that strips only trailing newlines
   for file bodies.
9. **Write the harness, then run it.** Stub every side effect (run, sudo, notify,
   menu_select, hyprctl, smartthings) and test pure behaviour in bulk. Keep the
   stubs in one place so a stub overwritten mid-file cannot shadow a real
   function.
10. **Test the dispatcher against the original.** `diff <(original --help)` vs
   `<(port --help)` and compare a table-driven subcommand's output. Byte-identical
   help is a cheap, high-value check.
11. **Exercise every mode of the port, not just the happy path.** A port that
   only ever runs `--status` looks correct and ships broken install/verify paths.
   Drive each mode for real, or with `--dry-run` where a mode would mutate the
   system, and read the exit code — not the tail of the output. A failure
   printed by `warn()` and a failure that sets a non-zero exit code are different
   bugs.

## Pitfalls

- **Extract the original's algorithm into a standalone bash file and diff its
  output against the port, one case per row.** Reading bash and reasoning about
  what it "must" do produces confident wrong ports. A table of
  `(inputs, original_output, port_output)` makes divergence impossible to miss.
- **Run both sides against separate copies of the fixture.** If the port writes
  the state file before you invoke the original on the same path, the original
  reads already-transformed state and "agrees" with a bug. This produces a
  harness that reports agreement while proving nothing.
- **Do not rotate by index when the original rotates by one.** `addrs = addrs[i:] +
  addrs[:i]` and `addrs = addrs[1:] + addrs[:1]` agree on one case and diverge on
  the next. Port the loop body literally, not your idea of its intent.
- **Read the exact jq path.** `jq '.status.level.value'` selects
  `status → level → value`; porting it as `status.switchLevel.value` returns
  `None` silently. When a status lookup returns a dict where the original
  returns a scalar, the missing `.value` is the bug.
- **`json.dumps` is not `jq -c`.** The default separators put a space after `:`
  and `,`, and non-ASCII is `\u`-escaped. Any payload a receiver compares
  literally (or a downstream tool greps) diverges from `jq -nc` output. Match it
  with `json.dumps(value, separators=(",", ":"), ensure_ascii=False)`.
- **Strip quotes from BOTH sides of a key=value parse when the source quotes its
  keys.** `VBoxManage showvminfo --machinereadable` emits `"SATA-0-0"="/path/disk.vdi"` —
  keys *and* values are quoted. Stripping only the value leaves a lookup keyed on
  `SATA-0-0` matching nothing, so disk discovery silently returns empty and the
  tool reports the disk as missing. Same class of bug in any quoted INI/Makefile
  parse: normalize the key and the value independently.
- **Do not treat a `grep` on compressed data as authoritative.** A `.ko.zst` is
  zstd-compressed; `strings file.ko.zst` sees no symbols. Decompress first
  (`zstdcat`) or read `/proc/config.gz`, or the probe reports a false negative.
- **A TTY-dependent tool cannot be smoke-tested non-interactively.** Tools that
  call `termios.tcgetattr(sys.stdin)` at import die with
  `termios.error: (25, 'Inappropriate ioctl for device')` under a pipe — a failure
  that says nothing about whether the tool works. Read its version out of the
  source (`__version__ = "x.y.z"`) instead of executing it, and bound any real
  invocation with `timeout`. Never run such a probe as root: it will create a
  root-owned config dir (`~/.tool/`) that then blocks the desktop user.
- **Version comparisons must be numeric, and must refuse to downgrade.** Compare
  parsed integer tuples, not strings (`0.9.2 > 0.21.0` as strings). An updater that
  is *older* than the installed copy must say so and refuse, or it silently
  regresses a working install — and the newest upstream tag can legitimately be
  older than a `main`-branch install.
- **Fetch to a temp path, then `os.replace` into place.** A truncated or empty
  download must never overwrite a working install; verify size/non-zero and
  replace atomically, cleaning up the temp file on failure.
- **`glob`-style partition suffix stripping is disk-type dependent.** A single
  `re.sub(r"p?\d+$", "", dev)` turns `/dev/nvme0n1` into `/dev/nvme0n` — the
  nvme namespace number is part of the disk name, not a partition index. Strip
  only `p\d+$` (nvme/mmc) and bare trailing digits on sd/vd/hd.
- **Keep one implementation per concept.** Bash files routinely define a helper
  twice (the second silently wins) and carry commented-out branches. Port the
  definition that is actually reached, and say so.
- **A helper that is defined but never called is dead code.** Check
  `grep -n '<fn>'` for callers before porting; porting it adds a function that
  can never run.
- **State the fallback path.** When the original hardcodes a device or path,
  discover it at runtime and keep the original value as the fallback, so
  behaviour is unchanged when nothing else is found.
- **Prefer a single well-named dispatcher entry point over an argument parser
  for a CLI that already has its own `-h`.** `argparse` will swallow the script's
  own flags and change its help text.
- **A bash `trap` on HUP/INT/TERM plus `wait $pid` is not a Python `try/except`.**
  In bash the trap fires while `wait` is blocked and interrupts it; the loop then
  re-waits while the child is still alive and breaks once `kill -0 $pid` fails.
  Python's `subprocess.wait()` is *retried* after a signal handler returns
  (PEP 475), so a handler that only sets a flag leaves the port blocked forever
  on a child that will never exit. The handler must itself terminate the child
  (`os.kill(pid, SIGTERM)`) — that is what ends the wait. Mirror the loop by
  checking the flag after `wait()` returns *and* again after every `sleep()`,
  because a signal arriving during the backoff is only observed once the sleep
  is over (bash defers it the same way).
- **Convert `wait()`'s status to the shell convention.** Python returns
  `-signum` for a signal death; bash reports `128 + signum`. A relaunch/backoff
  message that interpolates the status prints `-15` where the original printed
  `143`. Normalize with `128 - status if status < 0 else status`.
- **A passing diff harness can prove nothing — assert the cases are real.**
  When the harness feeds routes pulled from `commands --json`, each route string
  already contains the `blackarch ` prefix, so `original $route --help` runs
  `blackarch blackarch <cmd> --help`. Both sides reject it with 127 and empty-ish
  stderr, and the comparison "passes". In one sweep, 1086 of 1152 cases passed
  without a single command executing. Strip the prefix (`${r#blackarch }`) and
  spot-check that a sample case returns the expected code (0, not 127) with
  non-empty output before trusting the pass count.
- **`command -v NAME` is not an executability test.** It reports any PATH entry
  resolving to something that is **not a directory**, and a name containing a
  slash is a path rather than a `PATH` search. `shutil.which` and
  `os.access(X_OK)` are different predicates and invert the answer for a mode
  `000` file. See `references/shell-parity-traps.md` for the full entry table and
  the matching `on_path()` implementation.
- **`find` expression precedence splits into arms, and a dropped `-type f` widens
  the match.** `-o` is looser than the implicit `-a`, so in
  `-type f -name '*.pdf' -o -name '*.epub'` the `-type f` guards the first arm
  only, and the second matches directories and symlinks too. Split the original's
  expression where the shell's own precedence puts the boundary and run the arms
  separately — the reachable set must be identical, not tidier. See
  `references/shell-parity-traps.md`.
- **Read `/proc/<pid>/comm` as raw bytes, not through a text decoder.** A name
  holding a byte that is not valid UTF-8 makes `Path.read_text()` raise
  `UnicodeDecodeError`, which aborts the scan — and in a toggle command ("is it
  running?") that turns into a false negative, so the port starts a second
  instance of a process that is already running. See
  `references/shell-parity-traps.md`.
- **A script whose whole effect is gated on one marker file is safe to call
  repeatedly — port the gate, not just the body.** When the original is
  `if [[ -f $MARKER ]]; then ...; fi`, the marker is the contract: its absence
  means "nothing to do", not an error. If the gated body depends on files that
  do not exist in the target tree, do not run it silently — add an explicit
  `--apply`/`--dry-run` pair, say so in the port's docstring, and leave the
  gate's default behaviour as a no-op. Running a first-run-style hook list
  against a tree where every path is missing produces a wall of `command not
  found` that reads as a broken port.

## Shell Constructs That Change Meaning in Python

Each of these produced a byte-difference that only showed up in a bulk diff:

| Bash | Naive Python | What actually matches |
| --- | --- | --- |
| `sort`, `sort -u`, glob expansion | `sorted(...)` | `locale.setlocale(locale.LC_ALL, "")` then key on `locale.strxfrm(s)` |
| `IFS=$'\t' read -r a b` | `line.split('\t', 1)` | split, **drop empty fields**, then `"\t".join(rest)` |
| `jq 'unique'` | `dict.fromkeys(...)` | `sorted(set(...))` — jq sorts |
| `jq` output | `json.dumps(...)` | `json.dumps(..., ensure_ascii=False)` |
| `jq -e '<filter>'` used as a test | `if result:` | exit **0** when the filter produced a value, **4** when it produced none (and 1 for `false`/`null`) |
| `${var^}` | `str.capitalize()` | `s[:1].upper() + s[1:]` — capitalize lowercases the tail |
| `${f##*/}`, `${stem#blackarch-}` | slicing | `Path.name`, `str.removeprefix()` |
| `${var//pat/rep}` | `str.replace` | same, but count occurrences explicitly (`${v//x/}` replaces all) |
| `exec "$bin" "${args[@]}"` | `subprocess.run` | `os.execv(path, [path, *args])` — keeps exit code and PID semantics |
| `while IFS= read -r line && (( n < LIMIT ))` | `for line in f` | slice first: `for line in text.split('\n')[:LIMIT]` |
| `[[ $x =~ ^a(.*)b$ ]]` | `re.match` | `re.match(r'^a(.*)b$', x)` — same greedy `.`, but bash `[[:space:]]` is `[ \t\r\n\f\v]` |
| `sed 's/--\[\[.*\]\]//g'` | `re.sub(..., flags=DOTALL)` | `re.sub(r'--\[\[[^]\n]*\]\]', ...)` — sed is **line-oriented** |
| `awk 'BEGIN{printf "%g\n", v}'` | `f"{v}"` | `f"{v:g}"` — the float text must be re-formatted |
| `cmd &` then `wait $!` | `subprocess.run` | `subprocess.Popen` + `.wait()` — you need the pid and must reap it yourself |
| `trap stop HUP INT TERM` + `wait $pid`; `kill -0 $pid \|\| break` | `signal.signal(...)` + `Popen.wait()` | the handler must `os.kill(pid, SIGTERM)` itself; PEP 475 re-arms `wait()`, so a flag alone blocks forever |
| `$SECONDS` | `time.time()` | `time.monotonic()` — wall-clock jumps otherwise reset a rate/window counter |
| `pkill NAME` / `pgrep NAME` | scan `/proc/*/comm` | unanchored **regex** on the process name; `pkill -x` / `pgrep -x` / `killall` are whole-name equality. Default signal is SIGTERM |
| `command -v NAME` | `shutil.which(NAME)` or `os.access(X_OK)` | any PATH entry resolving to something that is **not a directory** — mode `000`, a fifo, a socket and a symlink to a device all match; a directory never does. See *`command -v` is not an executability test*. |
| `find $HOME -type f -name '*.a' -o -name '*.b'` | one `find` call, or one arm with both `-type f` | `-o` is looser than the implicit `-a`, so `-type f` binds to the **first arm only**. Split the expression exactly there, or the second arm matches directories and symlinks too. |
| `jq -nc --arg k v '{k: v}'` | `json.dumps` | `json.dumps(..., separators=(",", ":"), ensure_ascii=False)` — `-c` is compact, `-nc` also leaves UTF-8 raw |
| `source script` (exports into the caller) | `import` / call | print `export KEY=VALUE` (`shlex.quote` the value) for the caller to `eval "$(cmd)"` |

Notes:

- **Locale collation matters for glob order too.** Bash expands `dir/prefix-*` in
  collated order, so the *registration* order of discovered files (and any
  per-file diagnostic listing) differs from `sorted(Path.glob(...))`. Sort glob
  results with the same `strxfrm` key.
- **Do not chase bash associative-array iteration order.** `${!arr[@]}` walks the
  internal hash table; it is stable for a given key set but not reproducible
  without reimplementing the hash, table size, and rehash policy. Make the port
  deterministic (alphabetical) and document it in a comment — this shows up as a
  one-word difference in a "did you mean" suggestion, never in real output.
- **`read` drops empty fields only for non-whitespace `IFS`.** With the default
  `IFS` bash also strips leading/trailing whitespace; with `IFS=$'\t'` it does
  not, but empty fields between separators are still dropped.
- **`sed` never spans lines.** A `s/--\[\[.*\]\]//g` block-comment strip only
  removes a `]]` that lands on the same line as its `--[[`; a Python `.*?` with
  `DOTALL` removes across lines and silently changes which rules are visible.
- **Python has no POSIX classes.** `[[:alnum:]]` inside a character class is the
  literal characters `:`, `a`, `l`, `n`, `u`, `m` — write the ranges out
  (`[-0-9A-Za-z_.+]`).

## Launchers and symlinked command directories

When the ported command lives next to a thin launcher, that launcher must find
its own directory through **any** path it was reached by:

```bash
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
```

Plain `dirname "${BASH_SOURCE[0]}"` is wrong the moment the command is
symlinked elsewhere — Blackarch symlinks its whole `bin/` into `/usr/sbin`,
which precedes `bin/` on `PATH`, so a sibling script's bare `cmd-name` call
resolves to the symlink and `here` becomes `/usr/sbin`, where the `.py` does not
exist. Symptom: the command works when you run it by absolute path and fails
when anything else calls it by name.

Keep each command's original `# blackarch:summary=` / `args` / `examples` lines
in its launcher: the dispatcher reads them to build its command listing, and
dropping them silently degrades every command's help entry.

**Metadata that lived in a launcher dies when the launcher is dropped.** A
wired-in port keeps the launcher because the dispatcher scans `blackarch-*`
files for `# blackarch:key=value` headers; a standalone port scans the
implementation file directly instead. Any command whose metadata existed ONLY in
its launcher therefore loses it — and the parser silently falls through to the
first comment line, so `summary` becomes an ASCII banner, a copyright notice,
`-*- coding: utf-8 -*-`, or `====…`. Symptom: `blackarch commands` shows
`blackarch hackinglab setup  -*- coding: utf-8 -*-` and `blackarch <cmd> --help`
prints a banner as the description. Fix by carrying the header into the
implementation file (place it in the first comment block, above the docstring).
`blackarch commands --check` reports `Missing metadata summary` per command —
run it to enumerate every affected command in one pass, then re-check.

## Triage: "is the port missing features, or just metadata?"

Before porting anything, separate the two — they need different fixes and the
second is much cheaper.

1. **Find the real reference.** A dispatcher is often a thin launcher whose
   comment says the implementation moved; the pre-port reference is the
   sibling `<name>.bash-orig` (or a `.py`). Comparing the launcher to the port
   compares a stub to a program.
2. **Count functions on both sides.** Bash `grep -oE '^[a-z_]+\(\)'` vs
   `grep -oE '^def [a-z_]+'`. Equal counts with different names is normal:
   a port replaces bash-jq plumbing (`commands_json_filter`,
   `emit_command_records`, `examples_as_lines`, `pipe_values_as_lines`) with
   native Python, and those are not lost features.
3. **Compare the dispatch surface, not the file.** Drive `--help`, `-h`,
   `<sub> --help`, group help, alias resolution, unknown-command suggestions,
   and every `commands` mode (`--all/--json/--markdown/--check`), on both sides,
   comparing first line + exit code. Identical behaviour there means the port is
   functionally complete.
4. **Diff shared entries field by field.** `comm` the binary sets, then diff the
   JSON records key by key. Remaining diffs are metadata; classify each as
   *real* (help output degrades) or *cosmetic* (a worse-looking fallback).
5. **Never compare counts across different directory trees.** The ported tree
   holds a subset of the original's `bin/` (the rest is unported), so
   `bash commands` legitimately lists far more commands than the port. Compare
   only the binaries both trees share.

The `routes` field is derived (`[route, filename_route] + aliases, unique`), so
it only moves when one of those three does — do not chase it independently.


## Harness Recipe

```python
import importlib.util, sys, os, tempfile
spec = importlib.util.spec_from_file_location("bc", "<port>.py")
m = importlib.util.module_from_spec(spec)
sys.modules["bc"] = m          # register BEFORE exec: dataclasses resolves the module
spec.loader.exec_module(m)

# snapshot real functions before stubbing any of them
_ORIG = {n: getattr(m, n) for n in ("run", "notify", "hypr_clients", "get_active_class")}

# stub every side effect in one place
m.run = lambda cmd, **k: type("P", (), {"returncode": 0, "stdout": ""})()
m.notify = lambda *a, **k: 0
m.hypr_clients = lambda: []
m.get_active_class = lambda: ""
```

Registering the module in `sys.modules` before `exec_module` is required when the
file uses `@dataclass` — dataclasses looks the class's `__module__` up in
`sys.modules` and raises `AttributeError` on a bare spec-loaded module.

### Stubbing a supervisor / daemon port

A supervisor port (relaunch loop, attempt budget, backoff, signal handling)
cannot be tested by diffing output. Stub the *external* commands on `PATH` and
drive the real scenario end to end:

```sh
# stub/systemd-cat — must exec, so the pid the port tracks is the real child
while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ $# -gt 0 ] && shift
exec "$@"

# stub/quickshell — records argv + env, then exits with a configurable code
#!/usr/bin/env python3
import os, signal, sys, time
open(os.environ["STUB_LOG"], "a").write("quickshell " + " ".join(sys.argv[1:]) + "\n")
def on_term(signum, frame):
    open(os.environ["STUB_LOG"], "a").write("quickshell got TERM\n")
    raise SystemExit(143)
signal.signal(signal.SIGTERM, on_term)
time.sleep(float(os.environ.get("QUICKSHELL_STUB_SLEEP", "0")))
raise SystemExit(int(os.environ.get("QUICKSHELL_STUB_EXIT", "0")))
```

Run with `PATH="<stubdir>:$PATH"` and `STUB_LOG=<file>`, then assert on the log
*and* on the exit code. Cover: clean exit, repeated crash with the dependency
alive (relaunch budget, give-up message, elapsed time), repeated crash with the
dependency dead (stop immediately, no relaunch), and a signal delivered to the
supervisor while the child runs (child receives it, no relaunch, prompt exit).

Write the stub child as a **Python** script, not `sh` + `trap`: a POSIX shell
defers a trap until its foreground child finishes, so
`sh -c 'trap "..." TERM; sleep 30'` does not react to TERM for 30s and the
signal case times out instead of passing.

### Stub fixtures: one dispatcher, many names

When the port shells out to several external commands, generate every stub name
as a **symlink** to a single dispatcher script branching on
`os.path.basename(sys.argv[0])`. Hand-writing sixteen one-line stubs invites a
stub that half-matches a name or that shadows a real command.

Three fixture pitfalls that cost real time:

- **Stub launches are asynchronous.** A stub reached through `setsid` (or any
  background child) writes its log *after* the port has already been checked.
  Poll the log with a deadline instead of asserting immediately, or the check
  races and reports the previous scenario's entry.
- **`AF_UNIX` paths cap at 108 bytes.** `socket.bind()` fails with
  `AF_UNIX path too long` when the fixture's runtime dir is deep. quickshell
  normally runs under `/run/user/<uid>`; keep the fixture `XDG_RUNTIME_DIR`
  short and lay sockets out as `runtime/by-id/<id>/ipc.sock`, with
  `by-shell/<hash>/<id>` and `by-pid/<pid>` symlinked to it — the layout the
  real client walks.
- **Drive scenarios from a Python harness, not `&` in a foreground shell.** A
  terminal tool that rejects backgrounding leaves the loop to be waited on,
  which cannot be signalled or timed out the way a supervisor port needs.

To exercise a "process is running" branch, copy a real binary (`/usr/bin/sleep`)
to `<fixture>/<name>` so `comm` is exactly `<name>` — `pkill -x`/`killall` match
on `comm`, and a file named `proc-<name>` matches nothing.

### Verifying a spawn/toggle port

A one-line toggle (`pgrep X && pkill X || X`) cannot be diffed by output — it
produces none. Drive both sides against a stub that *records its identity*,
then assert on the child, not on the parent's output:

```sh
# stub/wvkbd-deskintl — records who it is, then lives long enough to be observed
#!/bin/bash
exec python3 - "$@" <<'PY'
import time, os
open(os.environ['KBD_LOG'], 'a').write(
    'START pid=%d ppid=%d sid=%d pgid=%d\n' % (
        os.getpid(), os.getppid(), os.getsid(0), os.getpgrp()))
time.sleep(LIFETIME)
open(os.environ['KBD_LOG'], 'a').write('SURVIVED\n')
PY
```

Then assert four things, each of which catches a different wrong port: **the
caller blocks for the child's lifetime** (the `||` foreground), **a child named
`<name>` was started**, **the child ran to completion**, and **the port's child
leads its own session** (`sid == pgid == pid`). That last assertion is the one
that passes only when `fork` + `setsid` + `exec` was used correctly — `setsid`
makes the child a session leader *and* a process-group leader, so `sid == pgid`,
not `sid != pgid`, is the success condition.

Two traps in writing this check: invoking the **port** through `bash` (it has a
shebang, so it must be exec'd directly — see the shebang rule), and asserting
that the port returns *immediately* when the original blocks. The original
blocks because the shell is waiting on its own child; a port that detaches has
not reproduced that, and a caller relying on the block will hang.

### Loading a port with no `.py` suffix for module-level testing

`importlib.util.spec_from_file_location` returns `None` for a file with no
recognised suffix, so the documented recipe fails on an extension-less port. Use
an explicit loader instead:

```python
from importlib.machinery import SourceFileLoader
loader = SourceFileLoader("portname", "/opt/blackarch/bin/blackarch-cmd-foo")
spec = importlib.util.spec_from_loader("portname", loader)
m = importlib.util.module_from_spec(spec)
sys.modules["portname"] = m      # register BEFORE exec (dataclasses)
loader.exec_module(m)
```

`sys.modules` registration before `exec_module` still matters for `@dataclass`.

## Verification Checklist

- [ ] `--help` diffed against the original and byte-identical (modulo argv0)
- [ ] Every subcommand routed to the same handler the original uses
- [ ] **Both sides invoked the way a caller would** — the shebang-less original
      as `bash <file>`, the port exec'd directly; a `Exec format error` or a wall
      of shell syntax errors means this check was skipped, not that the port is bad
- [ ] **Harness fixtures rebuilt per scenario, and harness-controlled env vars
      cleared** — a shared working directory or a leaked variable turns one
      scenario's expected output into the next one's
- [ ] **Spawn/toggle ports**: the caller's blocking, the child's name, the child
      running to completion, and the child's `sid == pgid == pid` all asserted
- [ ] **No `exit`/`os._exit` inside a function that must return a status** — it
      discards the value `sys.exit(main(...))` delivers
- [ ] External-command argv captured and compared, not assumed
- [ ] State file / side-effect paths tested against a copy, not the live path
- [ ] `python3 -m py_compile` clean
- [ ] No unused imports or dead top-level names (check with an AST walk)
- [ ] **Every mode exercised** — status, check-only, verify, uninstall, and at
      least one install path (real or `--dry-run`), each with its exit code checked
- [ ] **Exit codes audited**: a `warn()` that does not also set a non-zero exit code
      lets a pipeline or wrapper treat a failure as success
- [ ] **Supervisor/daemon ports**: relaunch budget, give-up path, and signal
      delivery each exercised against stubbed externals
- [ ] **No root-owned artifacts left behind** — any file or config dir the tool
      creates under a user's home is owned by that user, not root
- [ ] **Multi-line helpers used on multi-line content** — no `strip()` where only
      trailing newlines should be removed
