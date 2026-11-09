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
- Module naming: heavy logic modules are `blackarch_core_<domain>.py` (blackarch_core_execute, blackarch_core_installer) and live in `/opt/blackarch/blackarch_modules/`. When renaming one, update every importer: bin/blackarch, blackarch_core.py (MODULE_COMMANDS + the installer import), the thin alias modules (blackarch_execute.py, blackarch_installer.py), blackarch_installer_gui.py, blackarch_setup_post.py, README.md, and the agent skills.
- Installer: `bootstrap_pacman()` copies the host pacman.conf + mirrorlists, then injects blackarch/athena/chaotic-aur/garuda repo entries and downloads their mirrorlists if missing.
- Installer: remove options --webcam-setup, --skip-kodachi; unlock default password.
- Setup: `blackarch setup` with no arg prints help; existing all-in-one behavior moved out.
- Flatpak: `blackarch flatpak-ulaa` command added.
- Module-backed commands: commands with no `bin/blackarch-<name>` executable (private, work, webapp, flatpak-ulaa, window, focus, gui, tui, vpn, update, update-system, brightness, audio, charger, banner, quickshell) are listed in MODULE_COMMANDS in blackarch_core.py; `dispatch_module()` imports `blackarch_modules.<module>` and calls its `main(argv)` with the FULL argv, because blackarch_core_execute reads its subcommand from argv[0]. Register every new flattened route there or it dies with `Unknown Blackarch command` (exit 127).
- `bin/blackarch` also keeps its own duplicate `_exec_cmds` flatten list; a route must be added in BOTH places (MODULE_COMMANDS and the wrapper list, plus the `--complete` list) or it stays unreachable.
- blackarch_core_execute `main()` treats every argument as real input, so `blackarch <cmd> --help` must be intercepted before calling it; the wrapper prints `print_help()` instead, and `dispatch_module()` prefers the module's own `print_help`.
- launch(id_kind="private") must splat the browser (`*browser`, not `browser`): `browser` is already a list from shlex.split, so passing it whole makes os.execvp raise `TypeError: expected str, bytes or os.PathLike object, not list`.
- A bare `except Exception: pass` around the execute-module import in `bin/blackarch` hides these failures and lets the core dispatcher print `Unknown Blackarch command`; when a flattened command misbehaves, reproduce the import and call manually to see the real traceback.
- SmartThings: `blackarch smartthings install|menu|status|value|widget` and device toggle; menu uses `blackarch toggle smartthings`.
- Installer: ulaa flatpak removed from installer; webcam setup opt-in; sysctl userns removed; flatpak install uses --noninteractive.
