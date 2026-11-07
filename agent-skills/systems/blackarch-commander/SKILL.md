---
name: blackarch execute
description: Use when editing blackarch execute setup.
---

# Blackarch-commander setup

Modify `/opt/blackarch/bin/blackarch execute`. Python port of bash dispatcher.

## When to use
Adding/editing `setup_*()` or wiring `setup_dispatch()`; configuring LUKS/crypttab/fstab.

## Procedure
1. Read source before patch (`read_file` with offset/limit).
2. Verify exact function names/lines; cite source lines.
3. Discover UUID/devices at runtime (`blkid`, `findmnt`, `parted -s -j`); never hardcode `/dev/nvme0n1`, partition numbers, or UUID strings like `dbfa0647-b941-4878-ab09-c84ba0c6879c`.
4. Crypttab entry for TPM2: `tpm2-device=auto`, name = `luks-<UUID>`.
5. `setup_tpm()` must add crypttab for non-root enrolled devices (exclude root) via `blkid` UUID discovery with duplicate guard (`entry_line not in content`, not just UUID substring). Mapper name = `luks-<UUID>`.
6. `setup_luks_crypt_mount()`: mapper name stays `luks-<UUID>`, mount_target drops `luks-` prefix (`/run/media/black/<UUID>`). When `lukscrypt=True`, fstab source must use the mapper device UUID (`blkid -U /dev/mapper/{mapper_name}`), not the original backing block UUID (`luks_uuid`). If mapper UUID empty, fall back to `/dev/mapper/{mapper_name}` for fstab. Wire device arg through dispatcher (`argv[1:]` when not `True`/`lukscrypt`).
7. Mount config must set crypttab and fstab unconditionally; never skip fstab or make it conditional on `lukscrypt`.
8. For crypttab and fstab writes: read the current file content first, then **replace** any existing entry for the target device/mount point instead of appending. After processing, the file must contain exactly one entry for the given device/mount target.
9. Confirm syntax: `python3 -m py_compile /opt/blackarch/bin/blackarch execute`.

## Always-on rules
- Concise, direct answers; verify edits by reading source after patch.
- Device paths and UUIDs discovered at runtime — never hardcoded in source.
- Crypttab mapper naming: `luks-<UUID>` for every non-root entry.
- Root device (`root_source_device()`) excluded from crypttab in `setup_tpm()`.
- Prefer `pacman` over AUR; prefer open libcamera source over proprietary AUR stacks.
- Ports live in `/opt/blackarch/bin/` (python shebang, no `.py` suffix); originals become thin bash launchers.

## Pitfalls
- `setup_dispatch()` `else:` fallthrough runs full default setup; place new `elif` before it.
- `setup_luks_crypt_mount`: passing `lukscrypt` bool must not suppress fstab or crypttab. Both set unconditionally.
- `sudo_write(..., append=True)` requires reading current content first to avoid duplicates; use `entry_line not in content` (full line match, not UUID substring), since UUID strings can overlap.
- Boolean parameter must not make crypttab/fstab conditional; both must be set unconditionally.
- `blkid -U` may return empty for partitions; fall back to `blkid <device>` parsing (`UUID="..."`) and then backing disk (`backing_disk()` for partition -> disk).
- If UUID discovery fails entirely (`luks_uuid == `), return without writing partial entries — but always print the failure reason (`blkid -U` empty, `blkid` empty, device path) so the call does not exit silently with zero output.
- Never invent results; always read back after editing to confirm.
- When `lukscrypt=True`: fstab must reference the mapped device UUID (not backing UUID). Get it via `blkid -U /dev/mapper/{mapper_name}`; fall back to `/dev/mapper/{mapper_name}` if empty.
- **crypttab dedup**: replace any existing line whose first field equals the mapper name **or** whose text contains `UUID="<luks_uuid>"`. Keep exactly one such line.
- **fstab dedup**: replace any existing line whose second field (mount target) equals the target mount point. Keep exactly one such line.
- See `references/crypttab-tpm.md` for UUID discovery and naming rules.
- See `references/mount-auth.md` for why Nautilus mounts without password (udisks2 + polkit active session) vs terminal `mount`/sudo.
- **Plugin tool execute bit**: `bin/blackarch` dispatcher (`load_commands`, line 330) requires `os.access(file, os.X_OK)`; new `blackarch-*` executables committed as `100644` are invisible to `blackarch plugin` group listings and fail with "Permission denied" on direct invocation. Always verify `chmod +x` and `git ls-files -s` shows `100755` after adding a tool; if a plugin command is missing from group output, the first check is the file mode, not the dispatcher logic.
- **Limine default kernel**: prefer `linux-aegis-offensive` — sort `kernel_dirs()` / `clone_kernels()` so offensive comes first and set `default_entry` to that (1-based) entry. DKMS modules such as `ov02c10/1.0` are per-kernel; installing for one kernel does not cover the other, so install for `$(uname -r)` after switching kernels.
- `kodachi` setup subcommand: runs `curl -sSL https://kodachi.cloud/apps/os/install/kodachi-deps-install.sh | sudo bash` then `curl -sSL https://kodachi.cloud/apps/os/install/kodachi-binary-install.sh | bash`. Wire as `elif sub == "kodachi"` in `setup_dispatch()` before the `else:` fallthrough.
