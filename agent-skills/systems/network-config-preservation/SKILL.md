---
name: network-config-preservation
description: Preserve wifi/VPN/bluetooth profiles in installer, plus service enablement and sudoers.d transfer during bootstrap.
---

Steps: verify standard paths at runtime, add `copy_network_config()` with shutil, call from clone and pacstrap paths, only copy when present, never hardcode device paths. Add `--skip-network` flag and `--skip-timezone` flag; make timezone preservation unconditional (no prompt) with skip option.

During pacstrap/bootstrap and clone paths, also enable NetworkManager, bluetooth, and bt-agent (`systemctl enable` inside the new root via `arch-chroot`). Transfer `/etc/sudoers.d` files from the running system into the target root (`shutil.copy2`) so privileges and NOPASSWD rules survive the install. Call these after `preserve_credentials()` and before `copy_network_config()`.

Pitfalls:
- `systemctl enable` must run against the target root (`arch-chroot ROOT_MNT systemctl enable ...`), not the host, or it enables services on the running USB/session instead.
- `bluetooth-agent` / `bt-agent` service names vary by distribution; use `check=False` so a missing service does not abort the install.
- Sudoers files must preserve permissions (`copy2` keeps mode); never assume `/etc/sudoers.d` exists on the source (live sessions may lack it).
- Do not create sudoers files from scratch — only copy existing ones from the source system.
