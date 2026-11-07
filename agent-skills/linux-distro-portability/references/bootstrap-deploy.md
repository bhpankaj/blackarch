# Bootstrap / Deploy Rules (Arch + Blackarch)

Always-on rules for `blackarch installer` and any bootstrap/deploy step.

## Copy / Sync
- Never guard a tree sync (`rsync`) with `if os.path.isdir(target): return`. A directory existing does not mean its contents are up to date. Always sync so ports, dispatcher files, and script updates propagate.
- Use `--no-specials --no-devices` with `rsync -a` for tree copies that must skip sockets/devices the same way a Python `copy_function` skips non-regular files. Treat exit 23/24 as a recoverable partial transfer (use `try_run` / check exit rather than `run` with `check=True`). Verify the entry-point binary exists after the sync rather than trusting the exit code alone.

## AUR / makepkg inside chroot
- `arch-chroot` runs commands as root by default. Calling `yay` or any `makepkg`-triggering AUR helper inside it without switching to a non-root user produces `makepkg: Running makepkg as root is not allowed` (exit 10). Use the desktop user that has UID 1000 (looked up from the host `/etc/passwd`, typically `black`) and run with `runuser -u black --`. Do not create a temporary `builder` user — the chroot should use the real user so credentials and file ownership stay consistent.

## `/proc/self/exe` defense in chrooted commands
- Python's interpreter tries to read `/proc/self/exe` at startup. Inside a chroot (e.g., `arch-chroot`) this may be unreadable and can cause the command to print `Failed to read /proc/self/exe` and exit non-zero. Add a defensive `try/except` at module import time in the script (before `import glob`): set `sys.executable = "/usr/bin/python3"` as a fallback when reading it fails. This keeps the dispatcher executable even when `/proc` behavior differs under `chroot`.

## Running dispatcher commands inside chroot
- When calling `blackarch execute` (or any Python port) inside `arch-chroot`, invoke through the interpreter explicitly (`/usr/bin/python3 <script> ...`) rather than relying on the shebang (`#!/usr/bin/env python3`). The `env` binary or `/proc/self/exe` resolution may fail inside the chroot namespace and produce `No such file or directory` (exit 127) even when both the script and interpreter exist. The defensive `/proc/self/exe` fallback in the script plus explicit `python3` invocation covers this.

## Destination ownership
- Confirm `/mnt/new` (and any target root) is owned by the copying user (`chown -R`) before starting `rsync`, not only before reading the result.
