---
name: blackarch
description: >
  REQUIRED for end-user customization of Linux desktop, window manager, or system config.
  Use when editing ~/.config/hypr/, ~/.config/blackarch/,
  ~/.config/alacritty/, ~/.config/foot/, ~/.config/kitty/, or ~/.config/ghostty/.
  Triggers: Hyprland, window rules, animations, keybindings, monitors, gaps, borders,
  blur, opacity, blackarch-shell, bar, terminal config, themes, background,
  night light, idle, lock screen, screenshots, reminders, layer rules, workspace
  settings, display config, and user-facing blackarch commands. Excludes Blackarch
  source development through `blackarch dev link` workflows.
---

# Blackarch Skill

Manage [Blackarch](https://blackarch.org/) Linux systems - a beautiful, modern, opinionated Arch Linux distribution with Hyprland.

This skill is for end-user customization on installed systems.
It is not for contributing to Blackarch source code.

## When This Skill MUST Be Used

**ALWAYS invoke this skill for end-user requests involving ANY of these:**

- Editing ANY file in `~/.config/hypr/` (window rules, animations, keybindings, monitors, etc.)
- Editing `~/.config/blackarch/shell.json` (status bar layout, widgets)
- Editing terminal configs (alacritty, foot, kitty, ghostty)
- Editing ANY file in `~/.config/blackarch/`
- Window behavior, animations, opacity, blur, gaps, borders
- Layer rules, workspace settings, display/monitor configuration
- Themes, backgrounds, fonts, appearance changes
- User-facing `blackarch` commands (`blackarch theme ...`, `blackarch refresh ...`, `blackarch restart ...`, etc.)
- Screenshots, screen recording, reminders, night light, idle behavior, lock screen

**If you're about to edit a config file in ~/.config/ on this system, STOP and use this skill first.**

**Do NOT use this skill for Blackarch development tasks** (editing the Blackarch source tree, creating migrations, or running `blackarch dev ...` workflows).

## Topic Guides

Deeper instructions for common areas live next to this file. Read the
matching guide before starting:

- [`hyprland.md`](hyprland.md) - keybindings, monitors, window rules, and other Hyprland config
- [`references/kodachi-dashboard-structure.md`](references/kodachi-dashboard-structure.md) - verified layout and gaps for `/opt/blackarch/dashboard/` (v9.0.1 binary suite, bookmark file misplacement, empty profiles/backups/signkeys)
- [`references/kodachi-called-binaries.md`](references/kodachi-called-binaries.md) - full inventory of binaries and scripts Kodachi calls (launcher, AI/service/system binaries, update scripts, deps, log-evidenced runtime calls)
- [`plugins.md`](plugins.md) - the Blackarch shell: bar layout, widgets, plugins, idle behavior
- [`theming.md`](theming.md) - themes, backgrounds, and fonts
- [`hooks.md`](hooks.md) - automation hooks that run on system events
- [`capture.md`](capture.md) - screenshots, screen recordings, OCR text capture, and file sharing
- [`contributing.md`](contributing.md) - reporting Blackarch bugs and submitting fixes upstream

## Critical Safety Rules

For privileged commands, follow the Privilege Escalation rules below: `sudo` when a terminal is available for the password prompt, `pkexec` when it is not. Do not wrap commands that already manage privilege elevation themselves.

**For end-user customization tasks, NEVER modify anything in `/usr/share/blackarch/`** - but READING is safe and encouraged.

This directory is owned by the blackarch package. Any local changes will be
overwritten on the next `blackarch update`.

```
/usr/share/blackarch/     # READ-ONLY - NEVER EDIT (reading is OK)
├── bin/                    # Command source (packaged binaries are on PATH)
├── config/                 # Default config templates
├── themes/                 # Stock themes
├── default/                # System defaults
├── shell/                  # Blackarch shell source and defaults
├── migrations/             # Update migrations
└── install/                # Installation scripts
```

**Reading `/usr/share/blackarch/` is SAFE and useful** - do it freely to:
- Understand how blackarch commands work: `blackarch theme set --help` or `cat $(which blackarch-theme-set)`
- See default configs before customizing: `cat "$BLACKARCH_PATH/config/blackarch/shell.json"`
- Check stock theme files to copy for customization
- Reference default hyprland settings: `cat /usr/share/blackarch/default/hypr/*`

**Always use these safe locations instead:**
- `~/.config/` - User configuration (safe to edit)
- `~/.config/blackarch/themes/<custom-name>/` - Custom themes
- `~/.config/blackarch/hooks/` - Custom automation hooks

If the request is to develop Blackarch itself, this skill is out of scope. Follow repository development instructions instead of this skill.

## Privilege Escalation

For an interactive script or command run in a visible terminal, use `sudo` for
privileged work. Blackarch may grant passwordless `sudo` access to particular
commands, and the terminal is the appropriate place to request a password
when one is needed.

Use `pkexec` only when the caller cannot interact with a terminal or cannot
enter a password there, such as a command launched by an agent or a graphical
background process. Do not replace `sudo` with `pkexec` merely because a
command changes system state.

## System Architecture

Blackarch is built on:

| Component | Purpose | Config Location |
|-----------|---------|-----------------|
| **Arch Linux** | Base OS | `/etc/`, `~/.config/` |
| **Hyprland** | Wayland compositor/WM | `~/.config/hypr/` |
| **Blackarch shell** | Status bar + notifications (Quickshell) | `~/.config/blackarch/shell.json` |
| **Launcher/menus** | Quickshell menu | `~/.config/blackarch/extensions/blackarch-menu.jsonc` |
| **Alacritty/Foot/Kitty/Ghostty** | Terminals | `~/.config/<terminal>/` |
| **Blackarch OSD** | On-screen display | Quickshell plugin |

## Command Discovery

Blackarch ships a single `blackarch` CLI that dispatches to all `blackarch-*` binaries via `blackarch <group> <action>`. Always prefer this form — it is self-documenting and stable. The underlying `blackarch-*` binaries still exist on `PATH` and remain safe to read for source.

```bash
# List every documented command and its summary (--all includes hidden commands)
blackarch commands

# Show the commands inside a group
blackarch theme --help
blackarch refresh --help
blackarch restart --help

# Show help for a specific command (does not execute it)
blackarch theme set --help

# Machine-readable listing (binary, route, summary, args, aliases)
blackarch commands --json

# Read a command's source to understand it
cat $(which blackarch-theme-set)
```

### Command Groups

Run `blackarch --help` for the full list. The most common groups:

| Group | Purpose | Example |
|-------|---------|---------|
| `blackarch refresh` | Reset config to defaults (backs up first) | `blackarch refresh shell` |
| `blackarch restart` | Restart a service/app | `blackarch restart shell` |
| `blackarch toggle` | Toggle feature on/off | `blackarch toggle nightlight` |
| `blackarch theme` | Theme management | `blackarch theme set <name>` |
| `blackarch bar` | Bar layout and widgets | `blackarch bar move blackarch.clock --section right` |
| `blackarch plugin` | Manage/clone shell plugins | `blackarch plugin clone blackarch.clock` |
| `blackarch hook` | Install automation hooks | `blackarch hook install theme-set <script>` |
| `blackarch install` | Install optional software / packages | `blackarch install docker dbs` |
| `blackarch launch` | Launch apps | `blackarch launch browser` |
| `blackarch capture` | Screenshots and recordings | `blackarch capture screenshot` |
| `blackarch reminder` | Desktop notification reminders | `blackarch reminder 15 "Pickup Jack"` |
| `blackarch pkg` | Package management | `blackarch pkg add <pkg>` |
| `blackarch setup` | Interactive setup wizards | `blackarch setup security fingerprint` |
| `blackarch update` | System updates | `blackarch update` |

## Configuration Locations

Hyprland config lives in `~/.config/hypr/` — see [`hyprland.md`](hyprland.md).
The Blackarch shell (bar, notifications, plugins, idle) is configured in
`~/.config/blackarch/shell.json` — see [`plugins.md`](plugins.md).

### Terminals

```
~/.config/alacritty/alacritty.toml
~/.config/foot/foot.ini
~/.config/kitty/kitty.conf
~/.config/ghostty/config
```

**Command:** `blackarch restart terminal`

### Other Configs

| App | Location |
|-----|----------|
| btop | `~/.config/btop/btop.conf` |
| fastfetch | `/etc/fastfetch/config.jsonc` default; `~/.config/fastfetch/config.jsonc` user override |
| lazygit | `~/.config/lazygit/config.yml` |
| starship | `~/.config/starship.toml` |
| git | `~/.config/git/config` |

## Safe Customization Patterns

### Edit User Config Directly

For simple changes, edit files in `~/.config/`:

```bash
# 1. Read current config
cat ~/.config/hypr/bindings.lua

# 2. Backup before changes
cp ~/.config/hypr/bindings.lua ~/.config/hypr/bindings.lua.bak.$(date +%s)

# 3. Make changes with Edit tool

# 4. Apply changes
# - Hyprland: auto-reloads on save, but MUST validate with `hyprctl reload` and `hyprctl configerrors`
# - Blackarch shell: shell.json and user plugin code under ~/.config/blackarch/plugins/ hot-reload on save
# - Menus/launcher: ~/.config/blackarch/extensions/blackarch-menu.jsonc hot-reloads on save
# - Terminals: apply with `blackarch restart terminal` (reloads running terminals; foot picks changes up in new windows)
```

### Reset to Defaults -- ALWAYS SEEK USER CONFIRMATION BEFORE RUNNING

When customizations go wrong:

```bash
# Reset specific config (creates backup automatically)
blackarch refresh shell
blackarch refresh hyprland

# The refresh command:
# 1. Backs up current config with timestamp
# 2. Copies default from $BLACKARCH_PATH/config/
# 3. Restarts the component where the refresh needs it (e.g. `refresh shell`)
```

## System Commands

```bash
blackarch update                  # Full system update
blackarch version                 # Show Blackarch version
blackarch debug --no-sudo --print # Debug info (ALWAYS use these flags)
blackarch system lock             # Lock screen
blackarch system shutdown         # Shutdown
blackarch system reboot           # Reboot
```

**IMPORTANT:** Always run `blackarch debug` with `--no-sudo --print` flags to avoid interactive sudo prompts that will hang the terminal.

## Troubleshooting

```bash
# Get debug information (ALWAYS use these flags to avoid interactive prompts)
blackarch debug --no-sudo --print

# Reset specific config to defaults
blackarch refresh <app>

# Refresh specific config file
# config-file path is relative to ~/.config/
# eg. `blackarch refresh config hypr/hyprland.lua` will refresh ~/.config/hypr/hyprland.lua
blackarch refresh config <config-file>

# Full reinstall of configs (nuclear option)
blackarch reinstall
```

## Decision Framework

When user requests system changes:

1. **Is it a stock blackarch command?** Use it directly
2. **Is it a config edit?** Edit in `~/.config/`, never `/usr/share/blackarch/`
3. **Is it a theme customization?** Follow [`theming.md`](theming.md); create a NEW custom theme directory
4. **Is it automation?** Follow [`hooks.md`](hooks.md); use `blackarch hook install` and the hook `.d` directories
5. **Is it a package install?** Use `blackarch pkg add <pkgs...>` (or `blackarch pkg aur add <pkgs...>` for AUR-only packages)
6. **Is it built-in shell/plugin code?** Follow [`plugins.md`](plugins.md); clone it with `blackarch plugin clone`, never edit the packaged copy
7. **Unsure if command exists?** Run `blackarch commands` (or `blackarch <group> --help` for one group)

### Reminder Requests

When the user asks to set a reminder, use `blackarch reminder <minutes> [message]` directly. Convert natural language durations to minutes and title-case short reminder labels when appropriate.

```bash
blackarch reminder 15 "Pickup Jack"
blackarch reminder 60 "Check laundry"
blackarch reminder show
blackarch reminder clear
```

## Out of Scope

This skill intentionally does not cover Blackarch source development. Do not use this skill for:
- Editing files in `/usr/share/blackarch/` (`bin/`, `config/`, `default/`, `shell/`, `themes/`, `migrations/`, etc.)
- Creating or editing migrations
- Running `blackarch dev ...` commands

## Example Requests

- "Change my theme to catppuccin" -> `blackarch theme set catppuccin`
- "Add a keybinding for Super+E to open file manager" -> Check existing bindings first, call `hl.unbind` if needed, then `o.bind` in `~/.config/hypr/bindings.lua`
- "Configure my external monitor" -> Edit `~/.config/hypr/monitors.lua`
- "Make the window gaps smaller" -> Edit `~/.config/hypr/looknfeel.lua`
- "Turn on night light" -> `blackarch toggle nightlight` (for time-based schedules, edit `~/.config/hypr/hyprsunset.conf` profiles, then `blackarch restart hyprsunset`)
- "Set a reminder to pickup jack in 15 minutes" -> `blackarch reminder 15 "Pickup Jack"`
- "Show my reminders" -> `blackarch reminder show`
- "Clear all reminders" -> `blackarch reminder clear`
- "Customize the catppuccin theme colors" -> Overlay: put an edited `colors.toml` in `~/.config/blackarch/themes/catppuccin/`, then re-apply the theme (see `theming.md`)
- "Run a script every time I change themes" -> Install it with `blackarch hook install theme-set <script>`
- "Change how workspace labels are rendered" -> Clone `blackarch.workspaces`, which switches the bar to `<username>.workspaces`, then edit the clone
- "Lock after ten minutes" -> Set `idle.lock` to `600` in `~/.config/blackarch/shell.json`
- "Reset shell/bar to defaults" -> `blackarch refresh shell`
- "Record my screen" -> `blackarch screenrecord --fullscreen`, then `blackarch screenrecord --stop-recording` (see `capture.md`)
- "Enable/disable touchscreen during autorotate" -> `blackarch-setup-autorotateMonitor --enable-touch` / `--disable-touch` (modifies `monitor.lua` and toggle file; uses `set_touch()` function added to script)
- "Report this bug to Blackarch" -> Gather diagnostics and a capture of the problem, then file it (see `contributing.md`)

## Quickshell shell theming pitfalls (this host)

- `Commons/Color.qml` (the `Color` singleton) must not depend on `Util` or any
  `.js` helper via `import "...js" as X`: Quickshell on this host silently
  ignores non-directory JS imports, so the singleton fails to instantiate and
  `Color.<surface>` becomes undefined. Inline any helper (e.g. `canonicalColor`,
  `clampAlpha`, `alpha`) directly into `Color.qml`.
- `Color.loadColors` only parses `#[0-9A-Fa-f]{6,8}`; matugen emits 8-digit
  `#RRGGBBAA`, so the regex must allow 6-8 digits or colors fall back to defaults.
- Nested `readonly property QtObject <surface>: QtObject { ... }` surfaces can
  evaluate to undefined when their initializers throw; prefer root-level computed
  values when a surface stays undefined.

## Porting pitfalls (this host)

- Python ports that replaced `os.execvp(menu, ...)` must **capture** the menu's stdout and act on it (e.g. `blackarch-theme-bg-switcher` must run `blackarch-menu-images`, then call `blackarch-theme-bg-set <selection>`); `execvp` hands control away and the selection is lost.
- Bash thin launchers for ported families must exec the **ported entrypoint binary** (`blackarch-hyprland`), not a nonexistent `blackarch-<name>.py` — the `.py` module lives under `blackarch_modules/`, not `bin/`.
- Suppressing IPC errors (`>/dev/null 2>&1`) hides "target not found" / missing-env failures; verify with a verbose `blackarch-shell <target> <method>` before assuming the call succeeded.

- When the user says "everywhere" (or any unambiguous global scope), apply globally
  without further clarification — do not narrow to a subset and ask again.
- This host's repo/config tree lives at `/opt/blackarch`, not `/opt/BlackarchHacker/blackarch`.
  All path references to the distro tree should use `/opt/blackarch`.
- Prefer `pacman` over AUR (`yay`/`paru`); prefer bash scripts using only `pacman` packages
  over proprietary AUR stacks when the user asks for a bash-based webcam/install fix.
- Disk/partition references must be discovered at runtime (`parted -s -j`, `findmnt`, `blkid`);
  never hardcode `/dev/nvme0n1` or `-p 1`.
- Hardware device paths (keyboard backlight LED `/sys/class/leds/*kbd*`, input event devices) must be discovered at runtime (`brightnessctl --list`, `os.listdir('/sys/class/leds')`); never hardcode `samsung-galaxybook::kbd_backlight` or a fixed `/dev/input/eventN`. Scripts placed in `/opt/blackarch/bin/`; docs/config in `/opt/blackarch/`.
- Prefer open libcamera source build (v0.7.2) over proprietary AUR stacks (`libcamera-ipu6` etc.).
- For this user: concise, direct responses; minimal code versions; verify before reporting missing items. Evidence-backed checks (`file`, `ldd`, `head`, binary strings) are required — never assume a file's purpose from its name (e.g. `kodachi.html` is bookmarks, not the UI). Keep all artifacts at their current location (`/opt/blackarch/dashboard/`); do not relocate files to other paths.
- Workspace focus fix: when a switched-to workspace's window stays invisible, add `hl.dispatch(hl.dsp.window.bring_to_top())` after `hl.dsp.focus({ workspace = ... })`, and set `focus_new_on_workspace_switch = true` in `looknfeel.lua` general settings. This is the standard fix for first-switch hidden-window on this host's blackarch hypr config (`binding_tiling.lua`, `looknfeel.lua`).