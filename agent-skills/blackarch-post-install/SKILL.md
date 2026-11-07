---
name: blackarch-post-install
description: "Use when running blackarch setup-post on a fresh install."
---

# Blackarch Post-Install Verification & Auto-Fix

## Command

    blackarch setup-post

Runs checks and auto-fixes snapper, Ulaa flatpak, Galaxy Book webcam, Kodachi, LUKS SD-card crypttab/fstab.

## Fixes applied automatically

- Snapper: rmdir /.snapshots; create-config /; baseline snapshot
- Ulaa: flatpak install -y flathub com.ulaa.Ulaa
- Webcam: auto-detect IPU6/IPU7; run galaxybook-camera-fix.sh + reapply-flicker-fix.sh
- Kodachi: blackarch setup kodachi if dashboard missing
- LUKS SD card: report missing crypttab/fstab entries

## LUKS SD card (TPM2)

    blackarch setup tpm /dev/sdb

Creates crypttab + fstab (noauto,user,nofail); overwrites existing entries.

## Pitfalls

- Snapper create-config fails if /.snapshots dir exists (not subvolume) - rmdir first.
- Webcam --ipu6 mode pulls AUR packages not in repos; use default open libcamera mode.
- setup tpm default only handles root + data disk; pass device explicitly.
