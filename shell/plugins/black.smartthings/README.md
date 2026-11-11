# SmartThings — Blackarch bar widget

Live switch state and dimmer control for the SmartThings devices curated in
Blackarch's menu, in the Blackarch (Quickshell) bar.

## Device list

The widget shows exactly the devices listed in
`$BLACKARCH_PATH/default/blackarch/menus/smartthings.jsonc` — every
`smartthings.<uuid>` key in that file. That is the same list
`blackarch shell generate` writes, so the bar widget and the Blackarch menu
always agree on which devices exist and what they are called.

- Menu **labels** are used, not the hub's labels.
- Menu **order** is preserved.
- The file is watched (`FileView.watchChanges`), so a device added or removed
  by the launcher appears or disappears without restarting the shell.

If the file is missing or has no `smartthings.*` entries, the widget falls
back to every switch-capable device in the account rather than showing nothing.
The popup header marks the curated case with a `menu` tag.

## What it shows

The bar icon is a bulb: solid when at least one switch is on, hollow when
everything is off, with a count badge of how many are on. The tooltip reads
`SmartThings — N of M on`.

Left click opens the popup. Right click forces a refresh.

## Popup

One row per device, in menu order:

- state dot — lit when the device is on
- device name
- `ON` / `OFF` (or `—` when the hub reports no switch value)
- dimmer level as a percentage, when the device has `switchLevel`
- a power glyph at the right edge — lit when the device is on, dim when off

### Controlling a device

**Toggle on/off** — either:

- click the power glyph at the right of the row, or
- click anywhere else on the row's name strip.

Both send `switch:on` / `switch:off` (the opposite of the current state).

**Dimmer level** — click (or drag) on the slider that appears under the name row
for any device reporting `switchLevel`. Clicking a point on the track jumps to
that level; dragging scrubs continuously.

**Scrolling never changes a level.** Scrolling with the mouse wheel or a
touchpad anywhere over the popup — including directly over a slider — is
ignored, and does not scroll the device list either. This is deliberate:
`PanelSlider` fires its `released` signal on every wheel notch, so an
unmodified slider silently changes the level when you scroll past it.

To make that work the packaged `PanelSlider` is rendered inert
(`enabled: false`) and the interaction is driven by our own `TapHandler`,
`DragHandler` and `WheelHandler`. `PanelSlider` is a shared component used by
the audio and display panels too, so it is never edited — only the local
instance is disabled.

### Keyboard

| Key | Action |
|---|---|
| `j` / `k` or arrows | move the cursor |
| `enter` / `space` | toggle the selected device |
| `+` / `=` | raise the cursor row's dimmer by 5 |
| `-` / `_` | lower the cursor row's dimmer by 5 |
| `/` (type into filter) | narrow the list by name |
| `esc` | leave the filter, then close |
| `tab` / `shift+tab` | switch to the neighbouring panel |

### Control by device id

Both actions are also addressable over IPC, so they can be scripted or wired
to a keybind without opening the panel:

```bash
IPC="qs ipc -p $BLACKARCH_PATH/shell call black.smartthings"
$IPC setSwitch        <deviceId> on|off      # -> ok | error text
$IPC toggleDeviceById <deviceId>             # -> ok | error text
$IPC setLevelById     <deviceId> 0-100       # -> ok | error text
```

Each returns `ok` or a human-readable reason (`unknown device: …`,
`state must be 'on' or 'off'`, `device has no switchLevel: …`,
`level must be a number 0-100`).

## How it gets data

```
smartthings devices --status -j -c switch     # poll, every refreshIntervalSec
smartthings devices:commands <id> switch:on|off
smartthings devices:commands <id> switchLevel:setLevel(<0-100>)
```

The status dump is ~290 KB and takes ~1.3s, so it is fetched on a timer into
the background and parsed once per response. After any command the widget
re-reads status ~900 ms later, so a row settles on what the hub actually
reports rather than an optimistic local guess.

`-c switch` is a server-side capability filter: it keeps the payload to
switch-bearing devices instead of all 79 devices in the account.

The status query is deliberately unfiltered by menu membership — the whole
switch set comes back and the menu set is applied locally, so editing the menu
re-filters from the cached payload with no extra round trip.

## IPC

```
qs ipc -p $BLACKARCH_PATH/shell call black.smartthings status   # JSON summary
qs ipc -p $BLACKARCH_PATH/shell call black.smartthings toggle
qs ipc -p $BLACKARCH_PATH/shell call black.smartthings refresh
```

`status` returns `menuPath`, `curated`, `menuCount`, `deviceCount`, `onCount`,
`error`, and the full device rows. Useful for scripting and for checking the
curated list is wired.

## Configuration

Settings live inline on the widget's entry in `~/.config/blackarch/shell.json`:

```json
{ "id": "black.smartthings", "refreshIntervalSec": 30, "showLevels": true }
```

| Key | Default | Meaning |
|---|---|---|
| `refreshIntervalSec` | `30` | Poll interval, clamped to ≥ 5 |
| `showLevels` | `true` | Render dimmer sliders and percentages |
| `menuFile` | `""` | Override the curated-list path. Empty = the shared Blackarch menu file |

Set them with `blackarch bar set black.smartthings refreshIntervalSec 60`.
Use `menuFile` to drive the widget from a personal list without touching the
shared menu — e.g. `blackarch bar set black.smartthings menuFile ~/my-devices.jsonc`.

## Requirements

- `smartthings` CLI on `PATH`, authenticated (`smartthings config`)
- The CLI must be reachable from the shell's environment — the shell is
  started by Hyprland autostart, so it inherits the session environment,
  not an interactive shell's `PATH`. `smartthings` lives in `/usr/sbin`,
  which is on the default system `PATH`.
- `$BLACKARCH_PATH` set in the shell environment (it is, by Hyprland autostart)

## Install / move

```bash
blackarch plugin enable black.smartthings
blackarch bar move black.smartthings --section right --index 1
```

Code changes under `~/.config/blackarch/plugins/` hot-reload on save. If a
change does not take, run `blackarch-shell shell rescanPlugins`.

## Notes

- **A hot-reload does not re-register the IPC handler.** Adding or changing an
  `IpcHandler` method needs `blackarch restart shell`; editing existing methods
  is fine. The target will otherwise keep listing the old function set with no
  error logged.
- `PanelSlider` emits `moved` on press and on every drag step, and `released`
  once at the end. Only `released` is wired, so one drag produces one command
  instead of one per pixel.
- `anchors.fill` is illegal inside a `Row`; the row click target is sized with
  explicit `width`/`height` instead.
- Only devices whose `main` component carries `switch` are listed. Devices
  that expose a switch on a non-`main` component (e.g. multi-button remotes)
  are intentionally excluded.
- The menu file is JSONC; `Model.js` strips comments and trailing commas
  before parsing so a hand-edited file does not silently yield an empty list.
