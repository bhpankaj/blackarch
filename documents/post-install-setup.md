# Post-Install Setup Steps (blackarch installer)

Generated from the installer's finalize() and print_summary() behavior.
Run these after the installer finishes and you have rebooted into the new system.

## 1. Reboot into the new system
- Reboot, remove the USB stick, and select the target disk in the firmware boot menu.
- The installer writes no bootloader unless you passed --bootloader limine|systemd-boot or --efi-entry.
  If you passed --efi-entry, an efibootmgr entry was created for limine or systemd-boot.
  If no bootloader was installed, install one manually before relying on the disk.

## 2. Credentials / sudo
- Root and all users are copied verbatim (passwords unchanged).
- The UID-1000 desktop user gets /etc/sudoers.d/uid-1000 (NOPASSWD:ALL).
  Verify: `sudo -l -U <user>`.

## 3. Encrypted root (LUKS) unlock
- If the root is encrypted, unlock uses the passphrase you entered.
- With --unlock tpm2-fallback or tpm2-only, a TPM2 token is enrolled (PCR 7 by default).
- If tpm2-only was chosen, no password prompt at boot; keep a recovery passphrase safe.
- Verify crypttab: `cat /etc/crypttab` — mapper name is `luks-<UUID>`.

## 4. Bootloader / EFI
- With --bootloader limine: limine.conf entries + per-kernel vmlinuz/initramfs; NVRAM entry created.
- With --bootloader systemd-boot: loader/entries/ pointing at unified kernel images in EFI/Linux.
- With --efi-entry only: an efibootmgr entry is added; loader must be installed separately.
- Confirm NVRAM entries: `efibootmgr -v`.

## 5. Initramfs / hooks
- Hooks include sd-encrypt (unlocks LUKS + makes TPM2 token readable at boot).
- Inspect: `grep '^HOOKS=' /etc/mkinitcpio.conf`.
- If you switch kernels later, reinstall DKMS modules (e.g. ov02c10/1.0) for that kernel.

## 6. Snapper / snapshots
- If snapper is not configured yet, create the root config and a baseline snapshot:
  `sudo snapper -c root create-config /`
  `sudo snapper -c root create --description "baseline after post-install"`
- Verify: `snapper -c root list`.
- (Or run `blackarch snapshot create` to snapshot all configured configs.)

## 7. Home subvolume
- If @home subvolume exists, homes are mounted via fstab at /run/media/black/<UUID> (or /home).
- LUKS-backed home mount uses the mapper device UUID, not the backing UUID.

## 8. Webcam (Galaxy Book / IPU6)
- If you did NOT pass --webcam-setup during install, run it now:
  `sudo /opt/blackarch/bin/blackarch-webcam-setup --ipu6`
  (or --ipu7 for IPU7; --sensor-only only if dmesg shows
   "external clock 26000000 is not supported").
- AUR builds run as UID 1000; ensure sudo privileges exist first (step 2).
- Logs: /var/log/webcam-setup.log, /var/log/usb2disk/install.log.

## 9. Network / hostname / locale
- Hostname set from --hostname or source. Verify: `hostnamectl`.
- Timezone copied from the running system (unless --skip-timezone).
- Locale generated via locale-gen. Verify: `locale`.

## 10. Services
- enable_target_services() was called during install; review enabled units:
  `systemctl list-unit-files --state=enabled`.

## 10b. Ulaa browser (flatpak)
- If not installed during setup, install now:
  `flatpak install flathub com.ulaa.Ulaa`
- Verify: `flatpak list | grep -i ulaa`

## 11. Theme / text scaling (optional)
- GTK text scaling via gsettings org.gnome.desktop.interface text-scaling-factor.
- Use blackarch-display-text-size to adjust (12px == 1.0 anchor).

## 12. Cleanup
- If --keep-mounted was used, unmount manually:
  `umount -R /mnt`, `cryptsetup close luks-<UUID>`.
- Otherwise mounts were already unmounted by cleanup_mounts().

## Verification checklist
- `findmnt /` shows the new root subvolume.
- `blkid` shows LUKS UUID matching crypttab.
- `efibootmgr -v` lists the new entry (if bootloader installed).
- `snapper -c root list` shows baseline snapshot.
- Login as the UID-1000 user and confirm sudo works.
