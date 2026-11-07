# Fingerprint script and PAM patterns

Script: `/opt/blackarch/bin/blackarch-fingerprint-setup`
- Executable python3 script (`chmod +x`, git mode `100755`).
- Flags: `--enroll` (interactive `fprintd-enroll`), `--verify` (`fprintd-verify`), `--skip-install`, `--skip-pam`.
- Uses `python3 -m py_compile` verification.

PAM insertion rules:
- `/etc/pam.d/system-auth`: `auth sufficient pam_fprintd.so` before `pam_unix.so`.
- `/etc/pam.d/hyprlock`: add `auth sufficient pam_fprintd.so` alongside existing auth (e.g. `pam_howdy.so`); never replace blindly.
- Edit requires `sudo tee` — `patch` tool blocks `/etc/pam.d/` writes.

Device discrepancy rule:
- Always verify with `fprintd-list $USER` before trusting user-stated model (e.g. user said Goodix 511; actual device was Egis Technology LighTuning Match-on-Chip).

Enrollment persistence:
- `fprintd-enroll` requires full multi-stage scan; partial stages (`enroll-stage-passed`) without finalization leave no persistent print (`fprintd-list` empty). Re-enroll with centered finger until `fprintd-verify` returns `verify-match`.

Autorotate touch toggle (`blackarch-setup-autorotateMonitor`):
- Added `set_touch()` function (modifies `monitor.lua` `local touch_enabled` and toggle file `~/.local/state/blackarch/toggles/hypr/touchscreen-disabled-name`).
- CLI flags: `--enable-touch` (sets `touch_enabled = 1`, removes toggle file), `--disable-touch` (sets `touch_enabled = 0`, creates toggle file).
