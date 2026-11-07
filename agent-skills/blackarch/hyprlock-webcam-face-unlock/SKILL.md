---
name: hyprlock-webcam-face-unlock
description: Configure hyprlock webcam face unlock with gaze PAM.
version: 1.0.0
author: Hermes + Blackarch
license: MIT
---
# Configure webcam face unlock for hyprlock (gaze / hyprpolkitagent)

Use when configuring webcam-based face authentication to unlock hyprlock on Blackarch/Hyprland systems.

## Related skills

- `howdy-hyprlock-unlock` — the AUR-based `howdy` (IR camera + `pam_howdy.so`) alternative to `gaze`.
- `fingerprint-reader-setup` — fingerprint (`fprintd`) authentication for system login and hyprlock; adds `pam_fprintd.so` alongside existing PAM stacks rather than replacing them.

## Mechanism

- `gaze` provides `pam_gaze.so` and the `hyprlock-gaze` PAM service.
- `hyprpolkitagent` is a polkit authentication agent (shows auth dialogs), NOT face-recognition software. It is separate from the face-unlock pipeline.
- `hyprlock` supports PAM auth modules. The `hyprlock-gaze` service stacks `pam_gaze.so` over the system auth stack.

## Prerequisites

- Webcam working (IPU6/IPU7, libcamera/gstreamer, camera-relay active).
- `gaze` package installed (provides `pam_gaze.so`, `gazed`, `gaze` binary, `hyprlock-gaze` PAM service file).
  Note: `gaze` is NOT packaged in standard Arch repos as of this writing. Install from upstream releases or build from source.
- User added to `video` group (for V4L2/camera access by `gazed`).

## Config files

### PAM (`/etc/pam.d/hyprlock`)

Replace with the gaze service:
```
auth        include     hyprlock-gaze
```
Or for simultaneous mode (face + password in parallel): use `hyprlock-gaze-simultaneous`.

The `hyprlock-gaze` service (from the gaze package) includes:
- `pam_nologin.so` and `pam_faillock.so preauth` before `pam_gaze.so`
- `system-auth` / `common-auth` fallback after `pam_gaze.so` fails

### hyprlock (`~/.config/hypr/hyprlock.conf`)

Add auth section:
```
auth {
    pam {
        module = hyprlock-gaze
    }
}
```
For simultaneous mode:
```
auth {
    pam {
        module = hyprlock-gaze-simultaneous
    }
}
```

Also set:
```
general {
    ignore_empty_input = false
}
```
Otherwise hyprlock skips PAM when input is empty (blocking auto-unlock triggers).

### Hidden trigger label (optional, for auto-start face scan)

Some setups use a hidden `label` with `blackarch-face-unlock` or `ydotool` to trigger PAM. This is only needed if `hyprlock` does not auto-start the PAM flow on lock. Check the gaze docs for current recommendations.

### hyprpolkitagent config (`~/.config/hyprpolkitagent/hyprpolkitagent.conf`)

Only needed for polkit authentication (not face unlock directly):
```
general {
    allow_empty_password = false
    show_details         = true
}
```

## Verification steps

1. Confirm webcam: `dmesg | grep -i ov02c10`, `ls /dev/video*`, camera-relay active.
2. Confirm gaze installed: `pacman -Q gaze`, `ls /usr/lib/security/pam_gaze.so`, `systemctl --user status gazed`.
3. Confirm PAM config: `cat /etc/pam.d/hyprlock`
4. Confirm hyprlock config has `auth { pam { module = hyprlock-gaze } }`
5. Lock screen (`hyprlock`) and observe face match / fallback.

## Pitfalls

- Never hardcode `/dev/video*` device paths; discover at runtime.
- `gaze` requires the user in `video` group and `gazed` DBus service running.
- `hyprpolkitagent` is the polkit agent (shows auth dialogs); it does NOT provide face recognition. The actual face-unlock mechanism is `gaze` (PAM) or `howdy` (IR). Do not confuse the three.
- Check existing `/etc/pam.d/hyprlock` before replacing — a pre-existing `howdy` (`pam_howdy.so`) or other PAM stack may already be in place. Replace intentionally, not blindly. When adding fingerprint (`pam_fprintd.so`), add it alongside rather than removing the existing mechanism (see `fingerprint-reader-setup`).
- If the webcam setup is incomplete (IPU6 DKMS missing, libcamera missing), `pam_gaze.so` will fail silently and fall back to password. Fix webcam first.
