# Blackarch (Arch Linux desktop port)

**This setup is intended for pentesting or red teaming only.**

Arch Linux port of the Kodachi OS tooling and desktop environment, built
around Hyprland + Quickshell, with privacy/security tooling, hardware
support (notably Galaxy Book IPU6 camera), and Python-ported command-line
utilities.

## Top-level layout

- `bin/` — command-line entry points. Every `blackarch-*` name is a thin
  launcher (no `.py` suffix) with a Python shebang; the real implementation
  lives in `blackarch_modules/`. Dispatched by `bin/blackarch` (the
  dispatcher, which globs `bin/blackarch-*`). Originally bash scripts from
  the Kodachi repo, ported to Python; originals become thin bash launchers
  that `exec` the `.py`.
- `blackarch_modules/` — Python implementations backing `bin/`. Shared
  helpers in `blackarch_core.py`, `blackarch_helpers.py`, etc. Package
  marker `__init__.py` present so modules are importable.
- `shell/` — single long-running Quickshell instance hosting the whole
  desktop (bar, panels, overlays). Entry point `shell/shell.qml`;
  plugins under `shell/plugins/`. See `shell/README.md`.
- `config/` — per-app configuration (hypr, kitty, btop, …) deployed to
  `~/.config`.
- `default/` — default system/user files (bash, fonts, systemd, udev, …).
- `themes/` — color themes (`blackarch-turq`, `blackarch-uniq`, `azure-glow-theme`).
- `galaxybook-camera/` — IPU6/OV02C10 camera fix and build scripts.
- `agent-skills/` — bundled Hermes/agent skill definitions.
- `home/`, `share/`, `documents/` — supporting assets.

## bin/

~470 `blackarch-*` commands covering audio, battery, bluetooth, brightness,
capture/screenshot, clipboard, display, hyprland, menu, network, packages,
plugins, power profiles, restart, system, theme, toggle, and more. Plus
top-level helpers: `blackarch`, `blackarch-shell`, `blackarch-menu`,
`blackarch-restart`, `blackarch-hacker`, `blackarch-commander`,
`blackarch-installer`, `blackarch-launch-shell`.

## blackarch_modules/

Python modules mirroring `bin/` names (e.g. `bin/blackarch-audio-tuning` →
`blackarch_modules/blackarch_audio_tuning.py`). Heavy logic lives in
`blackarch_execute_core.py`, `blackarch_installer_core.py`,
`blackarch_linux_commander.py`, `blackarch_linux_installer.py`.

## quickshell

The desktop shell is a single Quickshell process (`shell/shell.qml`) with
plugins registered via `PluginRegistry.qml` and bar widgets via
`BarWidgetRegistry.qml`. IPC drives panels; see
`agent-skills/linux-distro-portability/references/quickshell-ipc.md`.

## Conventions

- Disk/partition handling is discovered at runtime (`parted -s -j`,
  `findmnt`, `blkid`, `cryptsetup`) — never hardcoded.
- Prefer `pacman` over AUR; open libcamera source build preferred over
  proprietary IPU6 stacks.
- Ports live in `bin/` without `.py`; originals in old repo become thin
  bash launchers using `readlink -f`.
