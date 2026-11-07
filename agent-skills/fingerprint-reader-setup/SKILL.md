---
name: fingerprint-reader-setup
description: Configure fingerprint reader via fprintd and PAM.
---

# Fingerprint reader setup

Use when configuring built-in fingerprint readers (fprintd + libfprint) and integrating them with system login and hyprlock on Blackarch / Galaxy Book.

## When to use
- Laptop has a built-in fingerprint sensor (discovered via fprintd-list, not assumed).
- User wants fingerprint authentication alongside or instead of password for system login (PAM) and hyprlock.
- The existing `/etc/pam.d/hyprlock` has another auth mechanism (e.g. `howdy` / `pam_howdy.so`) that must be preserved.

## Procedure
1. Discover actual sensor model: `fprintd-list $USER`. Never assume the user's stated model (e.g. Goodix 511 when device reports Egis Technology LighTuning Match-on-Chip).
2. Install packages: `sudo pacman -S fprintd libfprint` (prefer pacman over AUR per standing convention).
3. Restart service: `systemctl restart fprintd`.
4. Configure `/etc/pam.d/system-auth`: add `auth sufficient pam_fprintd.so` before `pam_unix.so` so fingerprint succeeds independently and falls back to password.
5. Configure `/etc/pam.d/hyprlock`: add `auth sufficient pam_fprintd.so` alongside existing auth (e.g. `pam_howdy.so`) — do not replace blindly.
6. Verify PAM edits: `grep -n fprintd /etc/pam.d/system-auth /etc/pam.d/hyprlock`.
7. Interactive enrollment: `fprintd-enroll` (requires physical finger; no automation possible).
8. Verify enrollment: `fprintd-verify`.
9. Check device state: `systemctl status fprintd`; `systemctl is-active fprintd` may show `inactive` when no client connects — service activates on D-Bus demand.

## Script
The Python script `blackarch-fingerprint-setup` (`/opt/blackarch/bin/blackarch-fingerprint-setup`) automates steps 2–6 and offers `--enroll` / `--verify` flags. It is executable (`chmod +x`, git mode `100755`) and uses `python3 -m py_compile` verification.

## Always-on rules
- Prefer `pacman` over AUR for `fprintd` and `libfprint`.
- Verify the actual device with `fprintd-list` before trusting any user-stated model.
- Modify PAM files with `sudo` (the `patch` tool refuses `/etc/pam.d/` writes); read current content before inserting.
- Never replace existing PAM stacks blindly (e.g. `pam_howdy.so` in hyprlock); add `pam_fprintd.so` alongside.

## Pitfalls
- Sensor model discrepancy: user assumption vs. `fprintd-list` output — always verify.
- `systemctl is-active fprintd` may return `inactive`; the service activates on-demand via D-Bus.
- Enrollment requires a real finger scan; `fprintd-enroll` cannot be fully automated. Multiple scan stages (`enroll-stage-passed`) must complete; a partial scan (interrupted by timeout or `enroll-finger-not-centered`) leaves no persistent print (`fprintd-list` shows empty). The `Egis Technology` sensor is sensitive to finger centering during enrollment.
- Enrollment persistence: check with `fprintd-list $USER` after `fprintd-enroll`; if empty despite `enroll-stage-passed`, the scan did not finalize — repeat enrollment with centered finger until `fprintd-verify` returns `verify-match`.
- PAM file edits must use `sudo tee` or equivalent; standard file-write tools are blocked by system-path protections.
