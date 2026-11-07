---
name: webcam-setup-flag
description: Webcam/IPU detection and conditional 26 MHz patch for blackarch installer.
---

When `--webcam-setup` is used, derive the IPU generation from the running host before calling `blackarch-webcam-setup`.

Detection order (same as `blackarch-webcam-setup`):
1. PCI multimedia controller (`/sys/bus/pci/devices/*/class` == `0x0480`, vendor `8086`). Read `driver` symlink name (`ipu6` / `ipu7`).
2. Fallback to loaded modules (`/sys/module/intel_ipu6` / `intel_ipu7`).
3. Fallback to PCI device IDs (`a75d` / `465d` → IPU6; `b05d` / `645d` / `7d19` → IPU7).

26 MHz patch (`--sensor-only`) decision:
- Read `dmesg` (or `journalctl -k --no-pager` if `dmesg_restrict` hides it).
- `clock_patch_needed = ("external clock 26000000 is not supported" in dmesg_text)`.
- Only append `--sensor-only` when `True`. Unnecessary rebuild delays boot.

Call pattern:
- `IPU6`: `/opt/blackarch/bin/blackarch-webcam-setup --ipu6`
- `IPU7`: `/opt/blackarch/bin/blackarch-webcam-setup --ipu7`
- `IPU6` + patch: `... --ipu6 --sensor-only`
- `IPU7` + patch: `... --ipu7 --sensor-only`

- AUR install must never hang on a TTY prompt: pass `stdin=sp.DEVNULL`, set `TERM=dumb`, set `env["TERM"] = "dumb"`, and give a generous build timeout (`timeout=1800` in `_git_pkg()`, `timeout=3600` in the installer's chroot call). `yay`/`paru` can block on interactive prompts even with `--noconfirm` when stdin is a terminal (`/dev/pts/0`); forcing `DEVNULL` eliminates the hang.

Always verify syntax after changing CLI parsing (`python3 -m py_compile`). Run the webcam-setup command as a subprocess (`timeout=3600s`, `capture_output=False`) so failure does not abort the install.

Chroot invocation rules (`--webcam-setup` inside install):
- Stream output live: `subprocess.run(cmd, capture_output=False, timeout=300)`; never hide stdout/stderr or failures become invisible (only exit 1 visible).
- AUR install (`_git_pkg`) must drop to user 1000: `sudo -u TARGET_USER -E -H -- paru -S ...` with `HOME` set to `TARGET_HOME`. AUR helpers refuse root execution.
- After install, user UID 1000 needs sudo privileges: write `/etc/sudoers.d/uid-1000` (`user ALL=(ALL) NOPASSWD:ALL`).
- `--keep-mounted`: when set, skip `umount -R` and `cryptsetup close` in `cleanup_mounts()`; leave ESP/home binds and LUKS mapper open.
