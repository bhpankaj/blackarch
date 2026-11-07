# Shell-parity traps

Bash behaviour a Python port must reproduce deliberately. Each entry is a
silent difference: the port runs, exits 0, and produces the wrong output.

## Locale collation

Bash `sort`, `compgen` and glob expansion order by the runtime locale, not by
byte value. Python's default `sorted()` is codepoint order, so a listing that
matches bash in the C locale diverges under `en_US.UTF-8` (case and punctuation
reorder).

```python
import locale
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass
collate = locale.strxfrm
sorted(paths, key=lambda p: collate(p.name))
```

Set it once at import time, not per call.

## `read` drops empty IFS fields

`while IFS=$'\t' read -r a b` skips a field that is empty, so a row joined with
two tabs renders like one joined with a single tab. When porting a table
printer, split on the separator and drop empty fields before pairing columns:

```python
fields = [f for f in line.split("\t") if f]
```

## jq

- `jq unique` sorts its input, so `routes` comes out collated regardless of the
  order it was fed. Sort explicitly when a different order is wanted.
- `jq -r` emits raw UTF-8; without it non-ASCII is `\uXXXX`-escaped. Match the
  flag the original pipeline used.
- `jq` consumes the whole stream, so a `head -n` upstream truncates before jq
  sees the data.

## Associative-array iteration order

Bash associative arrays iterate in an internal hash order that is neither
reproducible in Python nor stable across bash versions. Never port code that
depends on it: walk the keys in a defined order (usually sorted) and say so in
a comment.

## Word splitting and globbing

An unquoted `$var` splits on IFS and globs. Python has no equivalent — expand
explicitly with `shlex.split` / `glob.glob`, and decide deliberately whether a
missing glob is an error or an empty list (bash's `nullglob` is off by default).

## `set -e` / `set -o pipefail`

Python has no equivalent. A port that ignores a failing intermediate command
changes behaviour. Check the return code of every `subprocess.run` that the
original would have aborted on.

## Exit codes

Bash `exit $?` after a pipeline reports the last command's status (or the first
failure under `pipefail`). Return the child's `returncode` from
`subprocess.run` rather than a hardcoded 0.

`exit -1` becomes **255** at the wait boundary, so a port that must reproduce a
cancelled-picker status uses `sys.exit(-1)` / `return 255` — both land on the
same number, and hardcoding 255 is clearer.

## `command -v` is not an executability test

`command -v NAME` answers "could the shell *name* this", not "would running it
work", and `shutil.which` / `os.access(X_OK)` are **not** the same predicate.

Measured against bash on a `PATH` entry:

| Entry | `command -v` |
| --- | --- |
| regular file, mode `755` | matches |
| regular file, mode `644` | matches |
| regular file, mode `000` | **matches** |
| fifo | matches |
| unix socket | matches |
| symlink to a character device | matches |
| symlink to a regular file | matches |
| directory (even `+x`) | does not match |
| dangling symlink | does not match |

Two further rules: a name containing a slash is a **path**, not a `PATH` search
(`command -v /bin/sh` succeeds, `command -v bin/sh` fails); and `PATH` entries are
tried in order with the first non-directory candidate winning.

```python
def on_path(name: str) -> bool:
    if not name:
        return False
    if "/" in name:
        return Path(name).exists() and not Path(name).is_dir()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / name
        if candidate.is_dir():
            continue
        if candidate.exists():
            return True
    return False
```

The practical consequence: a `is-installed?` gate built on this answers a
different question than one built on `shutil.which`, and a false negative starts
a second instance of a process that is already running.

## `find` expression precedence

`find` joins tests with an implicit `-a`, and `-o` binds **looser**, so in

```sh
find "$HOME" -type f -name '*.pdf' -o -name '*.epub'
```

`-type f` guards the pdf arm only. The epub arm matches by name alone: a
*directory* called `x.epub` is offered, and so is a symlink named `x.epub`.
Port it by splitting the original expression where the shell's own precedence
puts the boundary and running the arms as separate `find` calls — the reachable
set must be identical, not tidier. This is the same class of bug as an
unparenthesised boolean in any language: verify the precedence before "fixing"
what looks like a missing filter.

## `/proc` values are bytes, not text

`/proc/<pid>/comm` and friends must be read as raw bytes. A process name holding
a byte that is not valid UTF-8 makes `Path.read_text()` raise
`UnicodeDecodeError`, which aborts the scan — and in a toggle command
("is it running?") that becomes a false negative, so the port starts a second
instance of a process that is already running.

```python
fd = os.open(f"/proc/{pid}/comm", os.O_RDONLY)
try:
    raw = os.read(fd, 64)
finally:
    os.close(fd)
name = raw.split(b"\n", 1)[0].decode("utf-8", "replace")
```

`comm` is capped at 15 bytes by the kernel and always newline-terminated, which
is the same limit `pgrep`/`pkill` apply. A process that dies between `listdir`
and the read is skipped rather than fatal.

## Bash `||` with a long-running command blocks

`cmd || gui` runs `gui` in the **foreground**, so the caller waits for it. Read it
as "the shell waits", and port it as `Popen` + `.wait()`. The opposite mistake —
detaching a GUI the original ran in the foreground — breaks any caller that
relies on the block, and the failure is silent because both versions exit 0.

When the right shape is a detached GUI, `fork` + `setsid` + `exec` is the minimal
one: the child *becomes* the target, so exactly one new process appears, in its
own session, immune to a signal sent to the caller's process group. A second
`fork` is unnecessary and makes the parent's reap logic a race. `setsid` makes
the child a session leader **and** a process-group leader, so the success
condition is `sid == pgid == pid` — not `sid != pgid`.
