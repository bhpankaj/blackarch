---
name: cryptsetup-status-device-resolution
description: Resolve LUKS backing device from a dm-crypt mapper name.
version: 1.0.0
author: black
metadata:
  hermes:
    tags: [luks, cryptsetup, findmnt, mapper, device-resolution]
license: MIT
---

When a script must pass the backing block device to `systemd-cryptenroll` or `cryptsetup`, resolve it from the mapper name rather than stripping strings.

- `findmnt -no SOURCE /` on encrypted root returns `/dev/mapper/<name>[/@]`. Strip the `[/@]` mount suffix (`re.sub(r"\[.*$", "", ...)`) before using the mapper name.
- `cryptsetup status <mapper_name>` returns `device: <backing_device>` (e.g. `/dev/nvme0n1p2`). Use that line directly.
- A naive `re.sub(r"crypted$", "", "/dev/crypt-...")` produces a non-existent device (`/dev/crypt-2b06eb39[/@]`) and causes `systemd-cryptenroll` to fail with "Block device required".
- Never hardcode `/dev/nvme0n1p2` or `/dev/sda2`; keep the runtime-discovered device as the primary path and fall back to the original value only when discovery fails.
