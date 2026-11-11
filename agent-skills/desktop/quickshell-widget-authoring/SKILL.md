---
name: quickshell-widget-authoring
description: "Author Quickshell bar widgets and popup panels."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [quickshell, qml, wayland, hyprland, bar-widget, panel, desktop]
---

# Quickshell Widget Authoring

## When to Use

Use when adding or debugging a bar widget, popup panel, or panel overlay in a
Quickshell-based desktop shell (Blackarch/Blackarch and similar). Triggers:
"add a widget showing X", "make a bar indicator for X", "popup panel for X",
editing anything under `~/.config/<distro>/plugins/`, a widget that renders
blank, or a panel change that appeared to do nothing.

The host shell is one long-running Quickshell process that mounts plugins from
disk; a widget is a directory with a `manifest.json` plus the QML it points at.

**Cross-reference:** for a control that changes *desktop-wide* state (text size,
theme, scaling), load the `desktop-text-scaling` skill too — it covers the
per-layer knobs (shell token, GTK factor, terminal font) and the startup-pin
trap that makes a saved setting appear to reset. This skill covers the widget
and its IPC mechanics.

**Read the host's own docs first.** Every Quickshell shell ships a plugin
README and UI base classes. Read them before writing — the base classes define
the properties the host injects, and guessing them produces silently-blank
widgets. This skill covers the *procedure and the traps*; the host's files are
the API reference.

## Procedure

### 1. Discover the host architecture (read-only)

```bash
# Is there a user config dir, or is the shell distro-owned?
ls ~/.config/quickshell ~/.config/<distro>/ 2>/dev/null

# What process is actually running the shell?
pgrep -af quickshell

# Find the plugin system: base classes, registries, docs
ls <shell-root>/Ui/ <shell-root>/Commons/ <shell-root>/services/
```

A missing `~/.config/quickshell/` means the shell is distro-owned and the
extension point is a **plugin directory** (e.g.
`~/.config/<distro>/plugins/<id>/`), not a standalone Quickshell config. Check
the distro's shell README for the plugin contract before assuming either.

Read the host's base classes for the exact injected API. Look for the widget
base (injected `bar` / `moduleName` / `settings`), the panel base (open/close
lifecycle, IPC), and the key-dispatcher + slider components you intend to use.

### 2. Write the manifest

Minimum viable `manifest.json`:

```json
{
  "schemaVersion": 1,
  "id": "<user>.<name>",
  "name": "Human Name",
  "version": "1.0.0",
  "author": "<user>",
  "description": "One line.",
  "kinds": ["bar-widget"],
  "entryPoints": { "barWidget": "Widget.qml" },
  "barWidget": {
    "displayName": "Human Name",
    "category": "Home",
    "allowMultiple": false,
    "defaultSection": "right",
    "defaults": { "refreshIntervalSec": 30 },
    "schema": [
      { "key": "refreshIntervalSec", "type": "integer", "label": "Refresh (s)",
        "min": 5, "max": 3600, "step": 5, "defaultValue": 30 }
    ]
  }
}
```

Validate the folder against the host schema before installing:
`<distro>-plugin validate <plugin-dir>`. A schema-invalid manifest fails
discovery silently — the widget simply never appears.

### Plugins that are both bar widget and panel

A single plugin directory can own **both** a bar widget and a popup panel by
declaring more than one entry point in `manifest.json`:

```json
{
  "schemaVersion": 1,
  "id": "<user>.<name>",
  "name": "Human Name",
  "version": "1.0.0",
  "author": "<user>",
  "description": "One line.",
  "kinds": ["bar-widget", "panel"],
  "entryPoints": {
    "barWidget": "BarWidget.qml",
    "panel": "Panel.qml"
  },
  "barWidget": { "displayName": "Human Name", "category": "Home" }
}
```

**Crucial:** the `barWidget` entry point must point at a separate QML file
containing the bar button (`BarIconButton`). A popup `Panel` (root object is a
`Panel`, not a bar icon) is **not** a valid bar widget — the bar widget
registry will try to load the whole panel as a button and fail silently, so the
widget never appears in the bar. The popup's `Panel` is a separate entry point.

#### IPC between bar widget and panel

A bar widget communicates with its panel (and other plugins) through QML
`IpcHandler`, not direct function calls:

```qml
// BarWidget.qml — request a panel function
qs.Ui.ipc.request("<user>.<name>", "methodName", arg1, arg2)

// Panel.qml — declare the handler
IpcHandler {
    target: "<user>.<name>"
    function methodName(arg1, arg2) { /* ... */ }
}
```

The handler target **must** match the plugin's `id` exactly (no `.<name>` suffix).
The request is async and returns a Promise (or you can pass a callback). Never
call a panel function directly from the bar widget — the bar widget and panel
are separate objects; direct references do not resolve.

> **Pitfall:** a bar widget that calls a panel function directly (e.g.
> `panel.someFunction()`) silently fails to resolve, the widget appears to do
> nothing, and the journal shows nothing. Use `qs.Ui.ipc.request()` instead.
> If the panel's `IpcHandler` is missing the method, the request silently
> disappears — confirm the method exists there (see Pitfalls).

### 4. Run external commands

```qml
Process {
  id: statusProc
  command: ["some-cli", "--json"]
  stdout: StdioCollector {
    waitForEnd: true
    onStreamFinished: { /* text holds the full stdout */ }
  }
  stderr: StdioCollector { waitForEnd: true; onStreamFinished: { /* ... */ } }
  onExited: function(code) { /* exit status here */ }
}
```

Guard re-entry (`if (proc.running) return`) and drive the poll from a `Timer`
with `triggeredOnStart: true`. Parse in a separate `.js` module imported with
`import "Model.js" as Model` so the QML stays declarative and the parsing is
testable on its own.

**Do not block the popup on a slow command.** If the CLI takes ~1s, poll in the
background and keep the last good snapshot rendered while a refresh is in
flight; show a spinner only as a secondary hint.

**Give every `Process` a closed stdin.** A Quickshell child inherits an *open
pipe* on stdin, and `stdinEnabled: false` does **not** close it — verified on
Quickshell 0.3.1, where the child's `/proc/<pid>/fd/0` still resolves to a
`pipe:`. Any CLI that reads or polls stdin then blocks forever, and because one
`Process` runs one command at a time, the first hang silently blocks every
later invocation. Always wrap the call so the shell closes stdin for you:

```qml
command: ["bash", "-c", "some-cli --json </dev/null"]
```

You are building a shell command now, so quote anything interpolated:

```qml
function shellQuote(v) { return "'" + String(v).replace(/'/g, "'\\''") + "'" }
```

**Queue side-effecting commands behind a watchdog.** One `Process` serialises
them, so a single wedged call starves all the rest. Keep an explicit queue,
start the next command only from the previous one's `onExited`, and arm a
`Timer` that sets `running = false` so a command that never exits cannot block
the widget for the rest of the session. Surface the child's real `stderr` on a
non-zero exit rather than a bare "command failed".

**Set a write-in-flight flag at the commit site and clear it in the exit
handler — never gate a queue on `running` alone.** `if (proc.running) {
queue(); return } proc.running = true` has a window: the `Process` can exit
between the check and the assignment, so the caller falls through, writes
`command`, sets `running = true` on a process that is already done, and the
queued change is silently dropped. Keep an explicit `writing` boolean set
immediately before `running = true` and cleared in `onRunningChanged` (which
runs strictly after the exit), and check *both* in the queue guard. When the
exit handler drains the queue, call the same commit function the caller uses
rather than re-invoking the setter, or the value can be overwritten by the
stale preview.

**Debounce a value the drag path fires per pixel.** `moved` fires once per pixel
of movement, so committing there sends one command per pixel. Set the pending
value immediately (so the knob tracks the pointer) and defer the side-effecting
write to a short `Timer`; stop the timer and flush from `onReleased` so a click
commits at once and a drag commits once when the pointer rests.

**An IPC read races the process round-trip — poll until the state converges.**
A setter call that returns the *requested* value is not evidence the write
landed; the confirmation arrives on the `Process` exit. A status dump taken
immediately after the call shows the pre-write value and reads as a failure
that is not one. (Restated at step 7, where it is actually caught.)

### 5. Install and place

```bash
<distro>-plugin validate ~/.config/<distro>/plugins/<id>
<distro>-shell shell rescanPlugins
<distro>-plugin enable <id>          # appends the widget to the bar layout
<distro>-bar move <id> --section right --index 1
```

### 6. Verify — and restart before believing anything

**A plugin reload does not re-render an already-instantiated popup, and does
not re-register an IPC handler.** This is the single most expensive trap in
this whole workflow; see Pitfalls. After any change you intend to judge:

```bash
<distro> restart shell        # mandatory before evaluating a plugin change
sleep 10
```

Then verify against real data, not against a rendered guess. Expose an
`IpcHandler` status function that returns JSON and call it — this is
scriptable and immune to rendering issues:

```qml
IpcHandler {
  target: "<user>.<name>"
  function status(): string {
    return JSON.stringify({ count: root.items.length, error: root.lastError })
  }
}
```

```bash
qs ipc -p <shell-root> call <user>.<name> status
qs ipc -p <shell-root> show            # list live targets + their signatures
```

### 7. Verify a control path without changing anything

When the widget drives something with real-world side effects (a smart-home
device, a service, a remote API), prove the control path end to end **without
mutating state**: issue commands that set each target to the value it already
holds, then confirm the CLI reports success and a before/after read-back is
identical.

```bash
# read current values, then re-send them as no-ops
<cli> ... set <target> <current-value>    # -> expect "ok" / "success"
<cli> ... read <target>                   # -> must be unchanged
```

Exercise the failure branches too — bad value, unknown target, unsupported
operation — since those are free and prove your validation actually fires.
Then diff the full state before/after to confirm nothing moved. Never test a
side-effecting command by toggling something the user owns.

**Snapshot the full baseline before you touch anything, and diff at the end.**
On a live system the user acts concurrently, and the bug you are fixing may
itself be mutating targets while you edit code, so an end-state diff alone
cannot tell you who caused what. When the diff shows changes you did not make,
attribute them by the per-attribute timestamp the service reports before saying
anything about them — do not assume your tests caused them, and do not assume
they are spurious. Report unattributable changes and ask before reverting;
silently "restoring" a value the user set deliberately is worse than leaving it.

**Assert on the side effect, never on the handler's return value.** An
`IpcHandler` method returning `"ok"` proves only that the QML body ran — it says
nothing about whether the spawned process executed or succeeded. A command that
silently hangs still returns `ok`. Confirm the real target changed by re-reading
it through the CLI, or confirm the child process actually ran; a green return
value is not evidence.

**Wait out the process round-trip before asserting state.** A setter IPC call
that returns the *requested* value is not evidence the write landed — the
confirmation arrives on the `Process` exit. Poll the JSON status until it
converges, or sleep past the round-trip. A state dump taken immediately after
the call shows the pre-write value and reads as a failure that is not one.

Grep the plugin for duplicate `id:` before you trust a load — see Pitfalls.

```bash
grep -oE 'id: [a-zA-Z_][a-zA-Z0-9_]*' <plugin>/Widget.qml | sort | uniq -d
```

**Grep for `root.<Prop>` references with no declaration after any refactor.**
`Cannot assign to non-existent property "<name>"` is the symptom, and it fires
at load, so the whole plugin disappears — but the reported property is usually
a *typo of a name you just introduced* (e.g. `textSizeQueued` where the
declaration is `textScaleQueued`). A one-liner finds them all:

```bash
grep -oE 'root\.[A-Za-z_][A-Za-z0-9_]*' <plugin>/Widget.qml | sed 's/root\.//' \
  | sort -u > /tmp/refs
{ grep -oE '^  property (var|real|bool|int|string) [A-Za-z_][A-Za-z0-9_]*' \
    <plugin>/Widget.qml | awk '{print $3}'; } | sort -u > /tmp/decls
comm -23 /tmp/refs /tmp/decls
```

Anything that is not a declared property or a function call is a typo. Run this
before restarting the shell — it catches the whole class in one pass.

## Debugging a widget that renders wrong

In order of cost:

1. **Restart the shell, reopen the panel, look again.** Half of "my fix did
   nothing" is a stale panel. Do this before investigating anything else.
2. **Check the journal for QML warnings**, filtered to the current shell pid:
   `journalctl --user --no-pager | grep "<shell-name>\[<pid>\]"`. Warnings from
   a previous pid look live and are not.
3. **Expose an `IpcHandler` returning JSON** and read the real state — do not
   infer state from pixels.
4. **Render a temporary probe** `Text` with a literal colour and screenshot:
   `grim -o <output> /tmp/probe.png`. A literal colour is greppable in the
   image — but treat **absence** of the marker as ambiguous, not as proof your
   code is unloaded. A stale panel (see the reload trap) also lacks it. Absence
   means "restart the shell and re-check", not "my code is wrong".
5. **Count pixels, don't trust the description.** A vision model will
   confidently call a populated panel "empty" when the text is small or
   low-contrast. Checking for a known marker colour with PIL is exact:

```python
from PIL import Image
im = Image.open(path).convert('RGB'); px = im.load()
w, h = im.size
hits = sum(1 for y in range(h) for x in range(w)
           if px[x, y][1] > 180 and px[x, y][0] < 120 and px[x, y][2] < 120)
print("green px:", hits)
```

## Pitfalls

- **A panel/menu entry point loaded by the shell's panel Loader must create its own surface: use `PanelWindow` (layer-shell), not `PopupWindow`.** The Loader instantiates `entryPoints.menu` with no parent window, and `PopupWindow` needs a `parentWindow` (it attaches to another window), so `summon` returns "ok" but nothing renders and nothing is logged. `PanelWindow` with `WlrLayershell.namespace/layer/keyboardFocus` creates its own layer-shell surface, like the built-in `blackarch.menu`. Verify with `hyprctl layers -j | grep <namespace>` after summoning.
- **Types under `shell/Ui/` must be listed in `shell/Ui/qmldir`.** The qmlscanner does not synthesize a qmldir when one already exists, so a type that is present on disk but absent from the qmldir fails with `<Name> is not a type` and the plugin's entry point silently fails to load. Add `<Name> 1.0 <Name>.qml` to the qmldir.
- **The host's plugin dir is `BLACKARCH_PATH/shell/plugins`, and renaming either directory silently empties the bar.** The shell host derives `firstPartyPluginsDir` from `blackarchPath + "/shell"` (upstream convention; the port renamed the dir to `quickshell/` and left the QML assuming `shell/`). When it does not resolve, `PluginRegistry` finds zero plugins and `listPlugins` returns `[]` — the shell still says "Configuration Loaded", the bar layer is created, but every widget reports `visible: false` with width 0. Six first-party plugins (`clipboard`, `emojis`, `image-picker`, `panels/dropbox`, `AppLibrary`) also hardcode `blackarchPath + "/shell/..."` for helper scripts, so they fail one by one with `Process failed to start`. Diagnose with `qs ipc -p <shell-root> call shell listPlugins` and `... call shell debugBarGeometry`; the fix is to make the directory name match the code (or resolve via `Quickshell.shellDir`) — never assume the bar is merely unstyled.
- **A `Process` child inherits an open pipe on stdin, and a CLI that polls it
  hangs forever — silently wedging every later action.** `stdinEnabled: false`
  does NOT close it (check `ls -l /proc/<child-pid>/fd/0`; it still shows
  `pipe:`). Because one `Process` runs one command at a time, the first hang
  blocks all subsequent clicks with nothing logged — it presents as "the
  buttons are dead" or "the control was never implemented". Wrap
  side-effecting calls as `["bash", "-c", "<cmd> </dev/null"]` — see step 4.
- **A reload does not re-render an open popup, and fails silently.** Editing
  plugin QML — even with a rescan — leaves an already-open panel showing the
  OLD layout, with no error and no warning. Restart the shell before judging
  any popup change. Skipping this turns every subsequent edit into a phantom
  bug hunt.
- **A reload does not re-register an `IpcHandler`.** A newly added IPC method
  appears to do nothing and logs nothing; the target keeps listing the old
  function set. Confirm with `qs ipc ... show`, then restart the shell.
- **Plugin `console.log` is swallowed.** The shell emits only its own
  `DEBUG qml:` lines; your logging never reaches the journal. Never plan to
  debug by logging — use an `IpcHandler` accessor or a coloured probe `Text`.
- **A `Row`'s implicit size includes children that are not `visible`.** A
  full-size `MouseArea` (or any full-bleed child) inside a `Row` makes the
  Row's implicit height depend on a height that depends on the Row, so the Row
  collapses to zero and the whole list renders blank. Do not put full-bleed
  input areas inside a `Row`; use an `Item` container with anchored children,
  and declare input areas after the content they cover.
- **`anchors.fill` is illegal inside a `Row`/`Column`.** It logs
  `Cannot specify left, right, horizontalCenter, fill or centerIn anchors for
  items inside Row` and the layout collapses. Size such children with explicit
  `width`/`height` instead.
- **A duplicate `id:` anywhere in the file fails the WHOLE plugin, not one
  element.** QML ids are file-scoped, so the same `id` on two elements (easy to
  leave behind when you move a child into a container during a refactor) makes
  the host refuse the plugin outright with a single
  `Plugin widget <id> failed: ... id is not unique` WARN. The symptom is
  misleading: the widget vanishes from the bar and its IPC target disappears
  entirely, which reads like a load or registration problem rather than a name
  clash. Grep for duplicates after any structural edit (command in step 7).
- **A text field inside a panel needs the key dispatcher disabled while it has
  focus.** The host key-catcher handles keys with `Keys.priority:
  Keys.BeforeItem`, so it steals them even from a focused child — typing in a
  filter box fires your row actions. Set `blocked: <field>.activeFocus` on the
  dispatcher so keys reach the editor normally.
- **An action with no visible affordance reads as missing functionality.** A
  hit target with no glyph, label, or hover state will be reported back as "you
  didn't implement this" even when the handler is wired and working. Give every
  interaction an explicit, visible control (an icon button, a labelled row) and
  document it; keep the large invisible hit area only as a convenience on top.
  When a user asks for a control that already exists, treat it as a
  discoverability bug, not a missing feature.
- **A slider has three side-effecting paths, not one: `moved`, `released` and
  `wheel`.** Wiring both `moved` and `released` sends one command per pixel of
  drag, so debounce the write and flush it on release. Read the component
  before wiring anything, commit on `released` only, and decide explicitly
  whether scroll may change the value (usually it must not). A `WheelHandler`
  that sets `event.accepted = true` over the control swallows the scroll so it
  neither mutates the value nor scrolls the list underneath.
- **Never edit a packaged/shared UI component to change its behaviour — make
  the local instance inert and drive it yourself.** Host UI components are
  reused by several panels (one slider serves audio, display, and anything else
  that wants one), so a local edit silently changes unrelated panels and is
  reverted by the next package update. Set `enabled: false` on your instance to
  switch off its built-in input handling, then overlay your own `TapHandler` /
  `DragHandler` / `WheelHandler`. It keeps rendering — confirm it has no
  `enabled`-dependent opacity before relying on that — and you own the
  interaction contract. If you must mirror its geometry (mapping a click x to a
  value), read the component's own arithmetic and reproduce it rather than
  guessing.
- **A panel opened via IPC stays open.** Summon commands have no auto-dismiss —
  close it explicitly when you are done, or you leave a panel on the user's
  screen.
- **A plugin that fails to load logs one WARN and renders nothing.** The shell
  emits `Plugin widget <id> failed: <file>:<line>: <message>` and then carries
  on without the widget. After *any* edit, grep the journal for that line before
  believing the widget is installed — absence of other errors is not proof of a
  successful load.
- **A singleton that references another singleton in the same module must
  explicitly `import qs.<Module>` it.** Relying on same-module resolution
  silently fails: the singleton falls back to a Qt builtin of the same name
  (e.g. `Color` -> `QQuickColor`), and every `Color.popups`/`Color.menu`
  binding becomes `undefined`, producing cascades of
  `Cannot read property '...' of undefined` with no load error. Symptom: a
  theme change renders the whole shell unstyled. Diagnose by checking the
  affected singleton's imports for the missing sibling import.
  When the affected singleton *is* the module's own singleton (e.g. `Color`
  inside `qs.Commons`), importing `qs.Commons` from itself does not resolve
  the sibling (`Util`); inline the needed helper (e.g. `clampAlpha`, `alpha`)
  instead of calling `Util.*`.
  - **Color.loadColors only parses 6-digit hex.** The regex
  `/^\\s*([A-Za-z0-9_-]+)\\s*=\\s*["']?(#[0-9A-Fa-f]{6})/` ignores
  matugen's 8-digit `#RRGGBBAA` (and 3-digit) values, so `foreground`,
  `background`, `accent`, etc. silently keep their defaults and the theme
  looks unchanged. Widen to `{6,8}` (or `{3,8}`) and ensure matugen's
  complex/multi-line values (e.g. `foreground = "{'dark': {...}}"`) are
  handled or normalized before parsing.
- **`PanelSlider` handles the wheel itself, so assigning `onWheel:` on an
  instance is a fatal plugin error, not a silent no-op.** The component
  declares `onWheel:` as a handler (it does not emit it), so an `onWheel:
  function(wheel) {...}` block fails the WHOLE plugin at load with `Cannot
  assign to non-existent property "onWheel"` — the widget vanishes from the
  bar and its IPC target disappears, which reads like a name clash or a load
  problem. Drive the value from `moved`/`released` instead: the component's
  own wheel handler already nudges `liveValue` by `step` and fires `released`
  on every notch, so scrolling still commits.
- **A slider whose value is an index into a stop list cannot track an external
  write.** `value: nearestStop(liveValue)` rounds any off-notch value back to a
  stop, so a change made outside the panel (another tool, a startup script, the
  user's own `gsettings set`) is silently re-rounded and the knob lies. Make
  the slider carry the *actual* value; keep the stop list only for stepping
  (walk it in the key handler) and for tick marks. The header label should
  print the real value too, not the snapped one.
- **`blackarch-restart shell` can leave the desktop with no shell at all.** The
  command kills the running Quickshell instance, then spawns
  `blackarch-launch-shell` with a plain `Popen`; the supervisor inherits the
  caller's stdout, so the invoking terminal blocks until timeout and, when that
  call is killed, the supervisor dies with it. Recover with
  `BLACKARCH_PATH=/opt/blackarch blackarch-launch-shell` run detached (the
  terminal tool's `background=true`). Prefer `setsid`/`start_new_session` for
  the spawn so the supervisor survives the caller.
- **Grep the journal by pid after a restart.** A restart spawns a new shell
  process; hundreds of stale warnings from the old pid can look like a live
  failure you just introduced.
- **`pgrep -af <name>` can match its own wrapper.** When run through an agent
  or terminal snapshot the pattern matches the invoking shell's command line,
  producing false positives. To list a process's real children use
  `ps -eo pid,ppid,comm --no-headers | awk '$2==<pid>'`.
- **Prefer a data file the host already maintains as the source of truth.**
  When the shell already curates a list (a menu definition, a settings file),
  read that file with a watching `FileView` rather than re-deriving the set
  from an API — the widget then stays in sync with the rest of the desktop and
  picks up edits live.
