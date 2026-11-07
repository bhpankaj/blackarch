# Limine Bootloader with Btrfs Snapshots on Arch Linux

## Overview

Limine is a lightweight UEFI bootloader that supports btrfs snapshots natively via the `snapshot:` protocol in its config. Combined with snapper, it provides a powerful rollback mechanism for Arch Linux systems with btrfs root filesystems.

## When to Use

- Arch Linux system with btrfs root filesystem (standard `@` / `@home` subvolume layout)
- UEFI boot mode (not legacy BIOS)
- User wants bootable snapshots for rollback capability
- Replacing GRUB or systemd-boot with a simpler bootloader

## Installation

### 1. Install packages

```bash
sudo pacman -S --noconfirm --needed limine limine-mkinitcpio-hook
sudo pacman -S --noconfirm --needed snapper snap-pac
```

### 2. Install EFI binary

```bash
# Copy Limine EFI binary to EFI partition
sudo cp /usr/share/limine/BOOTX64.EFI /efi/EFI/BOOT/BOOTX64.EFI
sudo mkdir -p /efi/EFI/limine
sudo cp /usr/share/limine/BOOTX64.EFI /efi/EFI/limine/limine.efi

# Create boot entry -- derive -d/-p from the ESP, never hardcode them:
#   disk  = whole disk holding the ESP   (parted -j <esp_dev> unit B print -> parent disk)
#   part  = ESP partition number         (partitions[].flags contains "esp")
sudo efibootmgr -c -d <esp_disk> -p <esp_partno> -L "Limine" -l "\\EFI\\limine\\limine.efi"

# Set Limine as first boot option (read the numbers back from efibootmgr)
sudo efibootmgr -o <limine_num>,<others>
```

Do NOT write `-d /dev/nvme0n1 -p 1` into a script or a wiki step. The ESP may be on
sda1, vda1 or mmcblk0p1, and the ESP partition is not always number 1. `parted -s -j`
reports the disk path and the partition flags; match the mounted vfat to a parted
partition to get both values. `/home/black/blackarch-limine-setup.py` implements this
(port of `blackarch-limine-setup`) and refuses to run with a hardcoded device.

### 3. Configure snapper

```bash
# Create snapper config for root filesystem
sudo snapper -c root create-config /

# Create initial snapshot
sudo snapper -c root create --description "Initial snapshot"

# List snapshots
sudo snapper -c root list
```

### 4. Configure limine.conf

The limine-mkinitcpio-hook auto-generates kernel entries. For snapshot support, add manual entries to `/efi/limine.conf`:

```
/+Snapshots
comment: Btrfs Snapshots (Snapper)

  /snapshot:1
  comment: Snapshot 1 - Initial snapshot
  protocol: linux
  path: boot():/9a95054a10c9472bb89cfd0473975730/linux-aegis-offensive/vmlinuz
  module_path: boot():/9a95054a10c9472bb89cfd0473975730/linux-aegis-offensive/initramfs
  cmdline: rd.luks.name=<uuid>=<mapped> root=/dev/mapper/<mapped> rootflags=subvol=/.snapshots/1/snapshot quiet loglevel=3
```

Replace `<uuid>`, `<mapped>`, and kernel paths with your actual values. The hash directory name is the machine-id.

## Key Files

| File | Purpose |
|---|---|
| `/efi/limine.conf` | Limine bootloader configuration |
| `/efi/EFI/limine/limine.efi` | Limine UEFI binary |
| `/efi/EFI/BOOT/BOOTX64.EFI` | Fallback UEFI binary |
| `/usr/share/limine/` | Limine binary directory |
| `/etc/snapper/configs/root` | Snapper root config |
| `/.snapshots/` | Btrfs snapshot directory |

## Pitfalls

- `parted` JSON is `-j`/`--json`, NOT `-J`. Verify with `parted --help`; a bare `-J` fails as an invalid option on GNU parted 3.8.
- `parted -j --list` and `parted -j /dev/sda print` need root (raw device nodes). As non-root, `parted --list` aborts on a device-mapper permission error and prints no JSON. A script must handle the failure, not assume empty output means "no disks".
- `parted -j --list` emits an array of disk objects (each bare or wrapped in `{"disk": {...}}`), while `parted -j <dev> print` emits a single `{"disk": {...}}`. Parse both shapes.
- Parted sizes are strings in mixed units ("10485760B", "10.5MB", "1049kB"). Convert with `Decimal`, not `float`: `float("67.1")*10**6` gives 67099999.
- Partition device naming is derived, not hardcoded: if the disk name ends in a digit (nvme0n1, mmcblk0, loop0) insert a `p` before the number, otherwise append it (sda1, vda1).
- `limine-install` may prompt for confirmation or hang — copy the EFI binary directly with `cp` instead.
- The limine-mkinitcpio-hook runs on every kernel update and regenerates limine.conf — preserve custom snapshot entries by adding them after the hook runs or by using a separate config file.
- Snapshot subvolumes live under `/.snapshots/<n>/snapshot` — the `rootflags=subvol=` path must point here, not to the snapshot metadata.
- `efibootmgr` boot numbers change when entries are added/removed — always verify with `efibootmgr` after making changes.
- Snapper's `create-config` will fail if a config already exists — check with `snapper list-configs` first.

## Workflow

### Creating a new snapshot

```bash
sudo snapper -c root create --description "Before system update"
```

### Rolling back to a snapshot

```bash
# From running system (next boot uses snapshot)
sudo snapper -c root rollback 1

# Or boot directly from snapshot via Limine boot menu
```

### Updating after kernel upgrade

The limine-mkinitcpio-hook automatically:
1. Generates new initramfs
2. Copies kernel + initramfs to EFI partition
3. Updates limine.conf with new entries

No manual intervention needed for standard updates.

## Python port (parted-driven, no hardcoded devices)

`/home/black/blackarch-limine-setup.py` is the Python port of `blackarch-limine-setup`.
It discovers disks with `parted -s -j`, matches the mounted vfat ESP and the LUKS
container to parted partitions, and derives every `-d`/`-p`/UUID/kernel-path value at
runtime. Run `sudo python3 blackarch-limine-setup.py --check` to prove the script
contains no hardcoded device path or partition number; `--dry-run` shows the generated
`limine.conf` without writing; `--partition` creates ESP + root with parted (never run
implicitly, and it refuses if the ESP size does not fit the disk).

Two rules that keep it portable:

1. **parted is the only disk source of truth.** Disk enumeration is `parted --json --list`,
   with a `/sys/block` + per-device `parted -j <dev> print` fallback. Never loop over
   globs like `/dev/nvme*n*p*`.
2. **Verify what parted actually did.** parted calls are made with `check=False`, so a
   failed `mkpart` is silent — re-read the table with `parted -j` and confirm the expected
   partitions and `esp` flag exist before reporting success.

## Timestamp Boot-Entry Labels

When multiple installs (or reinstalls) create boot entries, a static label like
`"Limine"` or `"systemd-boot"` fills the UEFI menu with identical rows. Use the
installation timestamp in the label so each entry is distinguishable.

**Limine (`limine-install` skips NVRAM; use `efibootmgr` directly):**

```python
# After limine-install --no-efi-register
label = f"Limine-{time.strftime('%Y-%m-%d %H:%M:%S')}"
run([
    "efibootmgr", "-c", "-d", esp_disk_path, "-p", part_num,
    "-L", label, "-l", r"\\EFI\\limine\\limine.efi",
], check=False)
```

Derive `disk` from `parent_disk(esp_part)` and `part_num` from the device
path (strip `p` prefix for nvme, bare digits for sd). Never hardcode
`-d /dev/sda -p 1`.

**systemd-boot (`bootctl install` supports description directly):**

```python
description = f"systemd-boot-{time.strftime('%Y-%m-%d %H:%M:%S')}"
run(["bootctl", f"--esp-path={EFI_MNT}", "install",
     f"--efi-boot-option-description={description}"])
```

`blackarch execute` (the dispatcher) does NOT include bootloader install
commands; only `blackarch installer` handles it.

## References

- Limine bootloader: https://limine-bootloader.org/
- Snapper: https://wiki.archlinux.org/title/Snapper
- Limine CONFIG.md: https://github.com/Limine-Bootloader/Limine/blob/v12.x/CONFIG.md
