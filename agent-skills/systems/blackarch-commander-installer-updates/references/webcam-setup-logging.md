---
name: webcam-setup-logging
description: Persistent file + console logging for blackarch-webcam-setup so AUR/DKMS builds are auditable inside chroot.
---

When `blackarch-webcam-setup` runs (especially inside `arch-chroot` via `--webcam-setup`), stdout/stderr must be captured to a persistent file because interactive visibility is lost when the parent installer uses `capture_output=False` but the chroot session ends after a timeout.

Requirements:
- `LOGFILE = Path("/var/log/webcam-setup.log")`
- `setup_logging()` creates `logging.getLogger("webcam_setup")` with:
  - Console handler (`INFO+`)
  - File handler (`DEBUG+`, append mode, `%(asctime)s [%(levelname)s] %(message)s`)
- `setup_logging()` called as the first action in `main()` (after argument parsing, before `banner()`).
- The `run()` helper logs:
  - `logger.info("Running: %s (cwd=%s)", ...)`
  - Every stdout line: `logger.debug("  %s", line)`
  - Failure: `logger.warning("Command failed (exit=%d): %s", ...)`
- Without this mechanism, a 10-20 minute AUR/libcamera build (`yay -S libcamera-ipu6 ...`) produces no recoverable trace after a timeout or crash — only the installer's `/var/log/usb2disk/install.log` shows the exit code, not the build output.

Always verify syntax after changes (`python3 -m py_compile`).
