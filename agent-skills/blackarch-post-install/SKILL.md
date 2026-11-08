---
name: blackarch-post-install
description: "Use when running blackarch setup-post on a fresh install."
---

# Blackarch Post-Install Verification & Auto-Fix

## Command

    blackarch setup post   # space, not hyphen; dispatcher routes `setup` -> execute main

Requires an executable `/opt/blackarch/bin/blackarch-setup-post` (Python shebang) so `load_commands()` registers the `setup post` group subcommand, and `blackarch_modules/blackarch_setup_post.py` must expose `main()` (the bin file is only a fallback).

Runs checks and auto-fixes snapper, Ulaa flatpak, Galaxy Book webcam, Kodachi, LUKS SD-card crypttab/fstab.

## Fixes applied automatically

- Snapper: rmdir /.snapshots; create-config /; baseline snapshot
- Ulaa: flatpak install -y flathub com.ulaa.Ulaa
- Webcam: auto-detect IPU6/IPU7; run galaxybook-camera-fix.sh + reapply-flicker-fix.sh
- Kodachi: blackarch setup kodachi if dashboard missing
- LUKS SD card: report missing crypttab/fstab entries
- Battery alert: deploy ~/.config/systemd/user/battery-alert.service + .timer from defaults and enable timer
- System-path writes in setup_post (e.g. `/usr/share/applications`) must use `sudo_write`, not `Path.write_text`, or setup-post fails with PermissionError when run as the user.
- Before partitioning a target disk, unmount any of its mounted partitions even when `--keep-mounted` is set; partitioning needs the device free (wipefs/parted otherwise fail with 'device busy').
- `blackarch setup post` is the dispatcher form (space, not hyphen); it routes through `execute` main -> `setup_dispatch(rest)` with `rest=["post"]`. Requires `blackarch_modules/blackarch_setup_post.py` to expose `main()`; an executable `bin/blackarch-setup-post` alone is only a bash fallback and gets mis-executed as shell.
- Python ports need both a module with `main()` and a bin file; the dispatcher imports the module first and only falls back to bash, which would mis-execute Python as shell.
- `blackarch-battery-monitor` is now a Python port; setup-post deploys/enables `battery-alert.service`/`.timer`.
- `blackarch setup post` is the dispatcher form (space, not hyphen); it routes through `execute` main -> `setup_dispatch(rest)` with `rest=["post"]`. Requires `blackarch_modules/blackarch_setup_post.py` to expose `main()`; an executable `bin/blackarch-setup-post` alone is only a bash fallback and gets mis-executed as shell.
- Python ports need both a module with `main()` and a bin file; the dispatcher imports the module first and only falls back to bash, which would mis-execute Python as shell.
- `blackarch-battery-monitor` is now a Python port; setup-post deploys/enables `battery-alert.service`/`.timer`.

## LUKS SD card (TPM2)

    blackarch setup tpm /dev/sdb

Creates crypttab + fstab (noauto,user,nofail); overwrites existing entries.

## Pitfalls

- Snapper create-config fails if /.snapshots dir exists (not subvolume) - rmdir first.
- Webcam --ipu6 mode pulls AUR packages not in repos; use default open libcamera mode.
- setup tpm default only handles root + data disk; pass device explicitly.
