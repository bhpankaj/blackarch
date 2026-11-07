---
name: arch-initramfs-rebuild
description: Use when rebuilding initramfs on Arch Linux.
---
# Rebuilding initramfs on Arch Linux

## When to use
After installing/updating a kernel, building DKMS modules, or changing mkinitcpio config/hooks.

## Procedure
1. Detect the bootloader/initramfs setup and use the matching tool:
   - If `limine-mkinitcpio` is available (Limine + limine-mkinitcpio-hook): run `limine-mkinitcpio`. It rebuilds every installed kernel and updates the bootloader config.
   - Else if `/etc/mkinitcpio.d/*.preset` files exist (systemd-boot / standard Arch): run `mkinitcpio -P`.
   - Else if `mkinitcpio` exists but no presets (custom kernels without presets): iterate installed kernels:
     ```
     for kver in /usr/lib/modules/*/; do
       [[ -f "$kver/modules.builtin" ]] || continue
       mkinitcpio --kernel "${kver%/}" --generate "/boot/initramfs-${kver##*/}.img"
     done
     ```
   - Else if `dracut` exists: `dracut --force`.
   - Otherwise warn and ask user to rebuild manually.
2. Verify the resulting images exist in `/boot` (or `/efi`) and were updated (mtime).

## Pitfalls
- `mkinitcpio -P` errors with "No presets found in /etc/mkinitcpio.d" on systems using limine-mkinitcpio-hook, because that hook drives mkinitcpio via `--kernel` and never creates preset files. Do not assume presets exist.
- Custom kernels (e.g. `linux-aegis-*`) often have no preset; use the per-kernel `--kernel/--generate` form.
- On limine systems, prefer `limine-mkinitcpio` over hand-rolled mkinitcpio calls so the bootloader config stays in sync.
- Do not hardcode kernel versions or image paths; discover installed kernels from `/usr/lib/modules/*/modules.builtin`.