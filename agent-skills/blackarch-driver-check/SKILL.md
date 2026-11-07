---
name: blackarch-driver-check
description: Discover missing device drivers via lspci, dmesg, sysfs.
---

# Blackarch driver discovery

Use for identifying devices with missing kernel drivers or firmware on Galaxy Book / Arch.

## Procedure
1. Run `/opt/blackarch/bin/blackarch-driver-check`.
2. Check `lspci -nnk` output for devices with no `Kernel driver in use:`.
3. Check `dmesg` hits for `firmware`, `missing`, `not loaded`, `unknown`.
4. Check `/sys/bus/pci/devices/` for devices without a `driver` symlink.
5. For USB devices, install `usbutils` (`pacman -S usbutils`) if `lsusb` missing.

## Always-on rules
- Prefer runtime discovery (`lspci -nnk`, `dmesg`, `sysfs`) over hardcoding device IDs.
- Report actual device names (e.g., `Egis Technology`) rather than user-stated assumptions.
- Never claim a device works without verifying the driver symlink in `/sys/`.

## Pitfalls
- `lsusb` requires `usbutils`; absence does not mean no USB devices.
- PCI devices without `Kernel driver in use:` (e.g., `Intel GNA Scoring Accelerator [8086:a74f]`) are real missing drivers.
- `systemctl is-active fprintd` may show `inactive` without blocking fingerprint functionality.
