# Command-Family Dispatcher

Building a single front door over a set of ported commands: a selector that
lists, documents, and runs every script in a family tree. This is the layer
*above* a family port; the port itself is covered in `bash-to-python-porting.md`.

`blackarch-hacker` is not this. It is a thin wrapper that routes to `blackarch`,
`blackarch-shell` and `blackarch execute`; the family dispatch lives in the
individual family scripts (`blackarch-hyprland`, `blackarch-restart`, ...) and in
the `blackarch` command center. Use this pattern for any new front door built
over a family tree.

## The three shapes a "family" can take

Conflating these is the whole failure mode. Classify each family before
writing dispatch code.

| Shape | Root file | Members | Example |
|---|---|---|---|
| Shared-root family | exists | all route to it | `blackarch-hyprland`, `blackarch-restart` |
| File-backed member | exists | member has its own file | `blackarch installer`, `blackarch-restart-audio` |
| Member-only family | **no root file** | each member is its own file | the theme switchers |

A shape-2 member must **never** inherit the root's help menu or an injected
first argument, and a shape-3 family's own name is **not an executable**.

## Rule: a root never has a default action

A family root only ever prints its own help menu. It has no fallback handler to
run. The two failure modes this prevents:

- A file-backed member asked for `--help` falls through to the root's default
  handler and **runs the real action**. In the field this was
  `blackarch-hacker commander-installer --help` launching a destructive
  USB-to-disk clone. Always test the dangerous members with `--help` as the
  first smoke test, before touching anything else.
- A member-only family's bare name resolves to a nonexistent root and errors out
  instead of showing the menu.

```python
if family and not member and not file_backed:
    show_family_help(family)
    return 0
```

## Rule: resolve a name to a path, not a prefix

Try every plausible spelling in order instead of building a name from a prefix.
Cheap, and it survives all three shapes without special cases:

```python
for candidate in (bin_dir / name, bin_dir / root,
                  fallback_dir / name, fallback_dir / root):
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
```

## Rule: forward, do not wrap

A dispatcher's job is to reach the script, not to interpret it. Three
consequences:

- Pass everything after the name through untouched, and append `--help` when
  the user asked for help, so the script's own help text is what the user sees.
- **Never insert an argument before checking whether the target takes one.**
  `blackarch-restart-audio` takes no options at all; forwarding `--help` to it
  makes it restart the audio services. Keep an explicit argument-less table and
  refuse with a message instead of starting the action.
- Prefer `subprocess.run` and return its exit code. Do **not** `os.execv` —
  execing prevents any post-run summary and leaves no way to report what was
  about to happen.

## Rule: document what the binary does, not what the wrapper adds

Derive the listing from the scripts (`# blackarch:key=value` headers) rather
than a hand-kept table. Hand-maintained tables drift, and a stale entry is worse
than a missing one because it looks authoritative. Keep a documented table only
for ordering and grouping, and merge it with what is actually on disk so an
undocumented script still appears.

## Smoke test (run before declaring it done)

1. `dispatcher` with no args — every command listed.
2. Every shape-2 member with `--help` — help text, never an action.
3. Every shape-3 member with `--help` — help text, not "no executable".
4. A family root bare and with `--help` — its menu both times.
5. A real member call that produces output — e.g. `hyprland monitor-laptop`.
6. A genuinely unknown name — clean error, exit 2, no traceback.
7. `python3 -c "import ast; ast.parse(open(path).read())"` on the dispatcher.
