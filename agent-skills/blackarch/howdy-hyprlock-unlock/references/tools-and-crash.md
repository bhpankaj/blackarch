Howdy vs gaze distinction

- `howdy`: AUR package (`howdy` / `howdy-git`), Python-based, uses `dlib` + OpenCV for face recognition. PAM module: `pam_howdy.so`. No daemon (runs on-demand via PAM). Config: `/etc/howdy/config.ini`. Model files in `/usr/share/dlib-data/`.
- `gaze`: Separate C++ face-auth package. PAM module: `pam_gaze.so`. Provides `gazed` daemon, `hyprlock-gaze` PAM service, and `hyprpolkitagent` (polkit agent, not face recognition). Config: `~/.config/hypr/hyprlock.conf` with `auth { pam { module = ... } }`. Documented in `hyprlock-webcam-face-unlock`.

When user asks for "webcam to unlock hyprlock", confirm which tool: `howdy` or `gaze`. They have different PAM modules, different packages, and different config files.

Crash/debugging reference (howdy CLI core dump)

If `howdy test` crashes (core dump, abort) even though webcam (`VideoCapture`) and dlib models load individually:
- Check `TERM=dumb` and `PYTHONPATH=/usr/lib/howdy` are set.
- Verify `device_path` in `/etc/howdy/config.ini` points to working device (`/dev/video0`).
- Verify `recording_plugin = opencv` (default).
- Test model loading individually (`dlib.get_frontal_face_detector()`, `shape_predictor`, `face_recognition_model_v1`) — if these work, crash is in video capture initialization or CLI display loop, not model loading.
- Check `opencl-icd-loader` and `python-opencv` compatibility (system package versions vs AUR build).
- `howdy add -y` must be invoked directly: `TERM=dumb PYTHONPATH=/usr/lib/howdy stdin=/dev/null /usr/bin/howdy add -y`. Do not wrap through `/usr/bin/python3` (`/usr/bin/howdy` is a binary/script, not a Python module path).
- If crash is only in headless terminal (`cv2.imshow` requires display): this is expected. `howdy add -y` works headlessly (no display window). The PAM auth (`pam_howdy.so`) also runs without a display. Only treat the crash as blocking if it happens during actual desktop lock (where display exists) or during `add`.

Manual trigger mechanism (button + keybind):
- Add label in `hyprlock.conf`: `label { text = "Face Unlock: Press any key" ... }`
- Add keybind in `binding_tiling.lua`: `Binder.add(vars.mainMod .. " + F", { desc = "Face Unlock Trigger" }, "blackarch execute brightness lock" )`
- Set `ignore_empty_input = true` in `hyprlock.conf` so PAM (and howdy) activates only on keyboard interaction, not automatically.
- `workaround = native` stops PAM prompt automatically after scan completes without injecting keystrokes (avoids the `input` permission error). `workaround = input` fails with "Insufficient permissions to send Enter press" because PAM blocks keystroke injection.
