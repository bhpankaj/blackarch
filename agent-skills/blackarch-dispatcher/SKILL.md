---
name: blackarch-dispatcher
description: Use when working with blackarch CLI dispatcher.
---

# Blackarch dispatcher

- Flattened execute subcommands live in /opt/blackarch/bin/blackarch via _exec_cmds.
- New top-level commands only appear in `blackarch --complete` if registered in GROUP_DESCRIPTIONS (blackarch_core.py); unregistered commands still run via module import or bash fallback but stay invisible to completion.
- Autocomplete via --complete includes flattened list.
- Window ring is single-file rotating list; swap rotates first->last, focuses first.
- Audio dispatch supports -h/--help.
- USB SD-card reader (STORAGE DEVICE) skipped in disk selection.
- Installer: ask_yesno defaults to True; abort on partition prompt falls back to --existing; sysctl userns removed from installer; flatpak install uses --noninteractive; kodachi setup enabled by default (skip via --skip-kodachi); smartthings CLI installed via npm; USB SD-card reader (STORAGE DEVICE) skipped in disk selection.
- Execute: setup-post runs flatpak ulaa, creates blackarch-webapp.desktop (via sudo_write), sets xdg defaults, runs ipu6 webcam if /dev/video0, runs TPM setup, kodachi setup.
- setup-post is a group subcommand (`blackarch setup post`): it needs an executable `bin/blackarch-setup-post` for dispatcher discovery; the `blackarch_modules/blackarch_setup_post.py` module alone is not enough.
- Installer: `--efi-entry` removed; EFI boot entry is created only when `--bootloader` is given.
- Installer: `blackarch installer --gui` launches a PySide6 module (`blackarch_installer_gui`) that runs `sudo blackarch installer ...` and exposes all installer flags including `--skip-copy-sudoers`.
- Installer: `bootstrap_pacman()` copies the host pacman.conf + mirrorlists, then injects blackarch/athena/chaotic-aur/garuda repo entries and downloads their mirrorlists if missing.
- Installer: remove options --webcam-setup, --skip-kodachi; unlock default password.
- Setup: `blackarch setup` with no arg prints help; existing all-in-one behavior moved out.
- Flatpak: `blackarch flatpak-ulaa` command added.
- SmartThings: `blackarch smartthings install|menu|status|value|widget` and device toggle; menu uses `blackarch toggle smartthings`.
- Installer: ulaa flatpak removed from installer; webcam setup opt-in; sysctl userns removed; flatpak install uses --noninteractive.
