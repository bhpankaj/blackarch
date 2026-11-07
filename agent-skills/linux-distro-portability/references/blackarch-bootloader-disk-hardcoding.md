---
name: blackarch-bootloader-disk-hardcoding
description: Fix hardcoded nvme/sda disk paths in blackarch installer bootloader configs.
version: 1.0.0
author: black
metadata:
  hermes:
    tags: [bootloader, disk, hardcoding, uuid]
license: MIT
---

Use when the bootloader entry (limine.conf / loader.conf / cmdline) in blackarch installer references a hardcoded nvme/sda device path instead of UUID/mapper-based root references. Standing convention: disk paths must be discovered at runtime (parted/findmnt/blkid/cryptsetup); never hardcode /dev/nvme0n1p2 or /dev/sda2 in bootloader configs.

Pitfalls discovered:
- `build_new_cmdline()` must fully replace any `root=` token from SRC.cmdline with ROOT_DEVICE (mapper for encrypted, resolved partition for plain); preserving the original nvme reference produces a boot that loads the wrong disk.
- ROOT_DEVICE must be set by prepare_layout() before build_new_cmdline() is called; an empty ROOT_DEVICE falls back to the original cmdline.
- CMDLINE_FOR_ESP must receive new_cmdline, not the unmodified SRC.cmdline.
- efibootmgr NVRAM entries must resolve disk/part via parent_disk() (PKNAME is empty for dm-crypt).
- The LUKS mapping name stays random (`LUKS_MAPPING = f"crypt-{secrets.token_hex(4)}"`) per user design; whatever name is chosen must agree everywhere: `rd.luks.name=<uuid>=<name>`, `/dev/mapper/<name>`, crypttab `<name> UUID=<uuid>`, and initramfs. A mismatch (e.g. cmdline names `root` but container opens as `crypt-...`) breaks unlock. The user's standing convention keeps the random token, not a fixed `"root"`.
- When encrypted: `root=/dev/mapper/{MAPPING}` (using the same random mapping name from `LUKS_MAPPING`); when plain: `root=UUID=<blkid-resolved-target-UUID>`. Never hardcode `/dev/nvme0n1p2` or `/dev/sda2`.
- The UUID must come from the current target device (`blkid` against `/dev/mapper/{MAPPING}` or the root partition node), never copied from the source USB stick. Resolve it inside `prepare_layout()` and `mount_existing()` before `build_new_cmdline()` runs.
- NVRAM entry loader_path must match the actual EFI binary `limine-install` writes: `\EFI\limine\limine_x64.efi`, not `\EFI\limine\limine.efi`. The nvme disk's ESP (`/efi`) may carry `limine.efi` (older install); a new target ESP (`/mnt/new/efi`) only has `limine_x64.efi`. Using the wrong name causes the firmware to fall back to the nvme disk entry (`Boot0000`) instead of booting the target (`Boot0001`).
- `limine-install` must NOT use `--no-efi-register`: it should register the NVRAM entry with its default loader name. After installation, rename (not duplicate) the entry via `efibootmgr -b <bootnum> -L <label>` rather than `efibootmgr -c`. Find the registered entry by scanning `efibootmgr -v` output for the loader path, extract the hex bootnum (`BootXXXX`), and rename in place. Using `-c` creates a duplicate entry that can cause the firmware to prefer the older nvme disk entry (`Boot0000`) over the target (`Boot0001`).
- When matching loader paths from `efibootmgr -v` against the Python `loader_path` string (which uses double backslashes, `r"\\EFI\\limine\\..."`), normalize both sides by replacing backslashes with slashes (`/`) before comparing. Comparing unnormalized strings misses the entry because the raw Python string contains `\\` (literal two backslashes) while the CLI output uses `\` (literal one backslash).
