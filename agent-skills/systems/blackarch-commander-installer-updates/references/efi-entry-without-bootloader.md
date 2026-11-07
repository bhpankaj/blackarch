# EFI Boot Entry Without Bootloader

When `--efi-entry` is used without `--bootloader`, the installer creates an `efibootmgr` NVRAM entry pointing to the ESP's fallback loader (`\EFI\BOOT\BOOTX64.EFI`). This lets the ESP be registered in firmware without committing to Limine or systemd-boot installation.

Key commands:
- `efibootmgr -c -d /dev/<disk> -p <part> -L <label> -l \EFI\BOOT\BOOTX64.EFI`
- Derive disk from `parent_disk(esp_part)`; derive part number from `esp_part` (strip `p` for NVMe partitions).

Always verify with `python3 -m py_compile` after editing the CLI parsing or bootloader logic.
