---
name: howdy-hyprlock-unlock
description: Configure howdy face unlock for hyprlock with webcam.
---

Trigger: user wants webcam-based face unlock integrated with hyprlock via howdy.
Distinction: `howdy` (AUR, Python/dlib) is separate from `gaze` (C++ face auth, covered by `hyprlock-webcam-face-unlock`). Confirm which tool before acting.

Always-on rules:
- User prefers concise, direct responses; minimal code versions. Do not over-explain steps.
- Default preference: MANUAL TRIGGER (`workaround = native`, `timeout = 10`, `certainty = 5.0`, `ignore_empty_input = true`, PAM `[success=1 default=ignore] pam_howdy.so`). Confirm before switching to instant; user may override (e.g., to instant with `workaround = input` + `auth sufficient pam_howdy.so`). `workaround = native` stops the PAM prompt automatically after scan without injecting keystrokes. `workaround = input` sends an Enter keypress when scan finishes but fails with "Insufficient permissions to send Enter press" (PAM blocks keystroke injection); document the user's explicit acceptance of this risk when used.
- Prefer open libcamera (v0.7.2, source build) over proprietary AUR stacks (`libcamera-ipu6`, `icamerasrc`).
- Howdy is AUR-only (`yay -S howdy` / `paru -S howdy`) — conflicts with pacman preference; user must confirm AUR override.
- Webcam must work before PAM/auth changes; verify `/dev/video*` exists and `VideoCapture` reads frames.
- Never present an unverified sequence (e.g., a crash path) as best practice; document blockers explicitly.

Steps:
1. Verify webcam: `ls /dev/video*`, test with OpenCV (`VideoCapture` reads frame, shape verified).
2. Confirm open libcamera: `/usr/lib/libcamera.so.0.7.2` present; default webcam device is `/dev/video0` (discover at runtime — do not hardcode).
3. Confirm user wants `howdy`, not `gaze`. Check `hyprlock-webcam-face-unlock` for `gaze` (different PAM module `pam_gaze.so`, different package).
4. Note AUR override: user must explicitly confirm `yay -S howdy` (pacman preference overridden).
5. Install `howdy` from AUR (`TERM=dumb`, stdin=/dev/null to avoid interactive hang). Install/depend: `python-dlib`, `python-opencv`, `python-pillow`, `dlib-data` (`/usr/share/dlib-data/`).
6. Configure `/etc/howdy/config.ini`: set `device_path = /dev/video0` (discover at runtime — never hardcode). Set `recording_plugin = opencv`. Choose trigger mode:
   - MANUAL (default, preferred): `timeout = 10`, `certainty = 5.0`, `workaround = native`. Set `ignore_empty_input = true` in `hyprlock.conf`. Note: `workaround = native` stops the PAM prompt after scan without injecting keystrokes.
   - INSTANT (only on explicit user override): `workaround = input`. Document user's explicit risk acceptance (PAM may block Enter press). Keep `timeout = 10`, `certainty = 5.0`. Note: `workaround = input` attempts to send Enter when scan finishes but fails with "Insufficient permissions to send Enter press" — do not present it as best practice.
7. Verify dlib models exist (`/usr/share/dlib-data/*.dat`). Test model loading individually (`dlib.get_frontal_face_detector()`, `shape_predictor`, `face_recognition_model_v1`) before running full CLI.
8. Configure PAM `/etc/pam.d/hyprlock` based on chosen mode:
   - MANUAL: `auth [success=1 default=ignore] pam_howdy.so` then `auth include login`. The conditional form requires interaction (any keyboard trigger activates PAM); `native` stops the prompt after scan; allows password fallback.
   - INSTANT (user override only, verified working): `auth sufficient pam_howdy.so` + `workaround = native`. `workaround = input` was tested and fails at runtime with "Insufficient permissions to send Enter press"; `native` stops the PAM prompt on face match without keystroke injection. `sufficient` unlocks immediately on face match; `auth include login` provides password fallback.
9. Before relying on auth: verify webcam captures frames (`VideoCapture` init OK, `read_frame()` works) and dlib models load individually. Note: `howdy test` opens `cv2.namedWindow("Howdy Test")` and crashes (core dump) in headless terminals — this is expected and does NOT mean auth is broken. The PAM path (`pam_howdy.so`) runs without a display window. Do NOT treat the `test` crash as a blocker for `howdy add`.
10. Once webcam and dlib are verified: `TERM=dumb PYTHONPATH=/usr/lib/howdy stdin=/dev/null /usr/bin/howdy add -y` (headless-safe; captures frames, saves `/etc/howdy/models/<user>.dat`). Confirm model exists (`ls /etc/howdy/models/`) before relying on auth. Note: do not invoke through `/usr/bin/python3` — `/usr/bin/howdy` runs directly.
11. Verify: `howdy test` (requires display; headless crash is expected), check model exists (`ls /etc/howdy/models/`), review `/var/log/howdy/` if needed, confirm PAM syntax (`cat /etc/pam.d/hyprlock`), confirm `hyprlock.conf` auth `module = hyprlock` (not `hyprlock-gaze`).

References:
- `references/tools-and-crash.md` — howdy vs gaze distinction, CLI core-dump debugging steps, manual trigger mechanism.
- `references/logging-mechanism.md` — structured file + console + JSON logging (`blackarch_logging.py`), directory auto-creation (`os.makedirs(..., exist_ok=True)`), environment variables (`BLACKARCH_LOG_FILE`, `FORMAT`, `LEVEL`, `STDOUT`).

Pitfalls:
- Manual trigger is the stable default (`workaround = native` + `timeout = 10` + `certainty = 5.0` + `ignore_empty_input = true` + PAM `[success=1 default=ignore] pam_howdy.so`). If user overrides to instant (`workaround = input` + `auth sufficient`), document the explicit risk: `input` sends Enter on scan finish but fails with "Insufficient permissions to send Enter press" (PAM blocks keystroke injection). Do not treat instant config as best practice. Verify the user's override in session notes.
- AUR install requires `TERM=dumb`, stdin=DEVNULL; `yay` hangs on interactive prompts without this.
- `dlib` is a heavy C++ dependency — allow long build timeout (`timeout=1800` minimum).
- Webcam must work before PAM/auth changes; fix `libcamera`/IPU6 setup first.
- `howdy` CLI `test` crashes in headless terminals because `cv2.namedWindow("Howdy Test")` requires a display — expected behavior, not an auth failure. `howdy add -y` and PAM (`pam_howdy.so`) work without a display.
- `hyprpolkitagent` is a polkit agent (not face-recognition); `gaze` is a separate face-auth tool. Do not confuse the two when configuring PAM.
- Original `hyprlock.conf` uses variables (`$background`, `$foreground`) and deprecated options (`no_fade_in`, `no_fade_out`, `grace`, `disable_loading_bar`) that hyprlock v0.9.6 rejects. Fix before relying on lock: replace variables with literal RGBA values (`rgba(20, 20, 20, 1)`, `rgba(240, 240, 240, 1)`) and remove unsupported options. Add `# Profile Picture` comment (not bare `Profile Picture` line). The auth module must reference the PAM service (`module = hyprlock` for `/etc/pam.d/hyprlock`), not `hyprlock-gaze`.
- PAM changes affect authentication; verify syntax (`cat /etc/pam.d/hyprlock`) before applying.
- `blackarch installer` creates `/etc/sudoers.d/blackarch` (original: secure_path/env_keep only). The user updated it to include `/etc/sudoers.d/00_black` content (NOPASSWD rules + secure_path/env_keep combined). The installer script (`blackarch installer`) writes this combined content when bootstrapping.
- If the session ends with an unverified crash/blocker, document it explicitly; do not present failed attempts as a validated workflow.
- Setup script path errors (`/opt/blackarch/config/hypr/hyprlock.conf` instead of `~/.config/hypr/hyprlock.conf`, `/usr/lib/howdy/cli.py` instead of `/usr/bin/howdy`) will silently skip auth updates. Verify the target file exists at the actual user config path before relying on sed replacements in any bootstrap script (`blackarch-webcam-setup-face-unlock`).
