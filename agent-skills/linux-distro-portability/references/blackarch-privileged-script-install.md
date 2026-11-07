---
name: blackarch-privileged-script-install
description: Security boundary for privileged bash script installation (priv_target, packaged binary, root ownership, no symlinks).
version: 1.0.0
author: black
metadata:
  hermes:
    tags: [privileged-script, root-owned, priv_target, packaged-binary, no-symlink]
license: MIT
---

Use when fixing or auditing a bash script that uses `priv_target()` / `priv()` (e.g. `blackarch-windows-vm`) to elevate via `pkexec`. These scripts have a strict security boundary: the packaged binary must be root-owned, the path must be hardcoded (not resolved from `BASH_SOURCE`), and installation must be direct (no symlink) because `priv_target()` verifies every parent directory is root-owned and non-writable.

## Always-on rules

- The packaged binary lives at `/usr/bin/blackarch-<name>` (direct file, never a symlink). Development/repo copies live at `/opt/blackarch/bin/` (user-owned).
- `priv_target()` hardcodes the packaged path (`/usr/bin/blackarch-<name>`). It must NOT resolve dynamically from `BASH_SOURCE[0]` or `$0` — the user explicitly requires the packaged path for security.
- `priv_target()` verifies: file exists, is non-symlink (`! -L`), executable (`-x`), root-owned (`stat -Lc '%u'` == 0), and mode has no group/other write (`! ((8#$mode & 022))`).
- It walks up the directory chain (`dirname` loop) applying the same ownership/mode check to EVERY parent, including `/usr/bin`, `/usr`, `/`. Any writable parent fails closed.
- Installation: `cp` directly to `/usr/bin/` (not `ln -s`). Then `chown root:root` and `chmod 755`. Do not modify the source `/opt/blackarch/bin/` file's ownership for the packaged install.

## The fix pattern (what this session produced)

When a privileged script fails with:
```
blackarch-windows-vm: refusing to run a non-root-owned command as root
❌ Failed to write the Windows VM configuration.
```

The issue is almost always one of:
1. `priv_target()` points to a non-existent `/usr/bin/` file (packaged binary missing).
2. The packaged binary is installed but not root-owned or is a symlink.
3. A parent directory (`/opt/blackarch/bin`) is user-owned, so the parent walk fails.

Fix: install the packaged binary directly at `/usr/bin/blackarch-<name>` (copy, no symlink), root-owned, mode 755. Keep `priv_target()` hardcoded to that path. Leave the repo file at `/opt/blackarch/bin/` user-owned.

## Pitfall: no symlink

Never create `/usr/bin/blackarch-<name>` as a symlink to `/opt/blackarch/bin/<name>`. `priv_target()` requires `! -L $candidate`; a symlink fails the check. The user explicitly requires direct installation (no symlink) for packaged privileged binaries.
