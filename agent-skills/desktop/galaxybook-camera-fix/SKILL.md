---
name: galaxybook-camera-fix
description: Fix a dead Galaxy Book camera (IPU6/OV02C10) on Arch.
---

# Galaxy Book camera fix (IPU6 / OV02C10)

Use when the built-in camera fails on a Samsung Galaxy Book (Intel IPU6 + OV02C10) under
Arch/BlackArch. Covers the kernel clock rejection, the libcamera source build, the rotation
quirk, and the camera relay.

## Diagnose first — the kernel log names the exact failure

```bash
sudo dmesg | grep -i -E "ov02c10|ipu6|isys"
```

The signature failure:

```
ov02c10 i2c-OVTI02C1:00: error -EINVAL: external clock 26000000 is not supported
ov02c10 i2c-OVTI02C1:00: probe with driver ov02c10 failed with error -22
```

The in-tree `ov02c10` driver only accepts a 19.2 MHz external clock. Some Galaxy Book
boards (Book3/Book4, incl. 960QFG) wire the sensor to 26 MHz. Probe fails, so **no camera
device is ever created** — every userspace stack (libcamera, PipeWire, the relay) then
fails for its own reason and masks the real cause. Fix the clock first; treat the
userspace stack as a separate step.

`/dev/video0..31` existing proves nothing: those are the `isys` capture nodes, which
appear even with no working sensor.

## The fix is upstream in a third-party repo

`https://github.com/Andycodeman/samsung-galaxy-book-linux-fixes` — has `ov02c10-26mhz-fix/`
(DKMS), `webcam-fix-libcamera/` (userspace), `camera-relay/`, and `webcam-fix-book5/ipu-bridge-fix/`.
The bundled `install.sh` scripts target Ubuntu/Fedora; on Arch, drive the pieces directly.

## IPU6 vs IPU7 — they are different stacks

`ov08x40` (ACPI HID `OVTI08F4`) ships behind **both** IPU6 and IPU7, so detecting the
sensor alone installs the IPU7 stack where it cannot work (open blackarch#7697/#14069).
Detect the **PCI controller** first: `b05d` = Panther Lake IPU7.5, `645d` = Lunar Lake
IPU7, `7d19` = Arrow Lake IPU7, `a75d` = Raptor Lake-P IPU6. The distro `intel-ipu7-camera`
package ships one HAL plugin (`ipu75xa.so`), so on IPU6 `icamerasrc` finds no HAL and
`v4l2-relayd@ipu7` yields a loopback with black frames. On IPU6 the working path is the
in-tree driver + libcamera — the IPU6 half of the fix below.

`bin/blackarch-webcam-setup.py` (Python port of the bash `blackarch-webcam-setup`) has
`--ipu6 [install|status|verify]` and `--ipu7 [distro|dkms|git|status]`.

The default install is the **open libcamera** stack. `--ipu6` installs the **proprietary
hardware-ISP** stack instead (AUR: `intel-ipu6-camera-bin` + `-hal-git` + `icamerasrc-git` +
`libcamera-ipu6(-ipa)` + `gst-plugin-libcamera-ipu6`, plus `v4l2-relayd`). They are
alternatives, not layers — only one active at a time.

IPU6 outputs raw Bayer, so it needs Intel's HAL (`libcamhal`) to debayer and run 3A,
`icamerasrc` for GStreamer, and `v4l2-relayd` to create a `/dev/video` node (`icamerasrc`
creates none). The HAL is a process-level singleton owned by the relay service.

**Do NOT install `intel-ipu6-dkms-git` on kernel >= 6.10** — the in-tree `intel_ipu6` /
`intel_ipu6_isys` drivers took over and the out-of-tree package no longer works. AUR
build quirks: `intel-ipu6-camera-hal-git` needs `sed -i 's/-Werror//g'` in `build()`, and
`libcamera-ipu6`'s `check()` fails on `v4l2_compat` (filter with `| grep -v v4l2_compat`).

A ready-made Arch script lives at `~/Work/galaxybook-camera-fix.sh` (modes: default,
`--check-only`, `--sensor-only`, `--uninstall`).

A companion verification script lives at `~/Work/verify-camera.sh` (modes: default,
`--quick`, `--frames N`). Run it as the desktop user, not root. It captures real
frames through the relay and judges them by file size.

Detailed notes on this whole fix (manual procedure, scripts, verification,
troubleshooting) are in the Obsidian vault under `Camera Fix - *.md`.

## Four separate layers — all are needed for a working camera

1. **ov02c10 26 MHz DKMS** — makes the sensor probe at all.
2. **libcamera source build** — Arch's packaged libcamera 0.7.x compiles the OV02C10
   sensor helper in but the factory registration is **dead-code-eliminated at link time**.
   Symptom: `IPASoft: Failed to create camera sensor helper for ov02c10` and a very dark
   image. A source build of v0.7.2 with the helper patched in is the only fix. Build 0.7.2,
   not 0.7.0 — 0.7.0's SoftISP AGC has an auto-exposure bug that blows out bright scenes.
3. **ipu-bridge rotation DKMS** — Samsung's BIOS reports `rotation=0` for an upside-down
   sensor. Model-gated (940XFG/940XGK/960XFG/960XFH/960XGK/960XGL/960QFG/960QGK). Check
   whether the upstream module already carries the quirk before building:
   `zstdcat /lib/modules/$(uname -r)/kernel/drivers/media/pci/intel/ipu-bridge.ko.zst | strings | grep <PRODUCT>`
4. **camera relay** — v4l2loopback bridge for non-PipeWire apps (Zoom, OBS, VLC).

## Flickering image (the on-demand AGC ramp)

Symptom: the image visibly brightens in steps on every app connect, and again if
the relay restarts. Cause: AGC state is per-pipeline, not persisted, and the
on-demand relay starts a FRESH pipeline (from black idle frames) each time a
client opens the device — so the app sees libcamera's startup exposure ramp
(`kNumStartupFrames = 10` fast frames, measured 16->43->66->71 luma).

Fix: run the relay always-on so one pipeline stays up and the AGC settles before
any app connects. Measured startup swing 27.0 -> 1.0 luma, at the cost of ~15%
of one CPU core (the software ISP debayers continuously).

Use a systemd drop-in at `~/.config/systemd/user/camera-relay.service.d/always-on.conf`
(two non-obvious requirements — both are load-bearing):

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/camera-relay start --foreground
```

- The empty `ExecStart=` MUST come first; a drop-in cannot otherwise add a second
  ExecStart and systemd rejects the unit with "bad unit file setting".
- `--foreground` is mandatory: plain `start` backgrounds the pipeline and exits,
  so under `Type=simple` systemd considers the service stopped, runs ExecStop and
  kills the relay.

Do NOT chase this as mains-frequency (50/60 Hz) banding — that would be a spatial
row-brightness oscillation. Measure the detrended row residual to tell them apart.
And the Simple IPA has NO anti-flicker support at all (`grep -ri flicker
src/ipa/simple/` -> nothing), so AeFlickerMode/flickerPeriod cannot be set from a
tuning file; stable exposure is the only lever.

## Pitfalls that cost real debugging time

- **Do NOT set `PYTHONPATH` before `meson install`.** Arch ships a PyPI `typing` backport
  (`python-typing`) in site-packages; putting site-packages on PYTHONPATH makes it shadow
  the stdlib `typing` module and meson dies on Python 3.14 with
  `AttributeError: type object 'Callable' has no attribute '_abc_registry'`.
  Plain `meson install -C build` works. The upstream installer's PYTHONPATH hint is for a
  different (Ubuntu pip) failure mode and actively breaks Arch.
- **The OV02C10 helper lives in the IPA module, not libcamera.so.** Grep
  `/usr/local/lib/libcamera/ipa/ipa_soft_simple.so` for `CameraSensorHelperOv02c10` to
  prove the patch is live. Grepping `libcamera.so` finds nothing and causes endless rebuilds.
- **The relay's systemd *user* unit runs `sudo modprobe v4l2loopback`.** This fails
  silently under a user service without NOPASSWD sudo, and the service then crash-loops
  with `status=1/FAILURE` while the device never appears. Load the module at boot via
  `/etc/modules-load.d/v4l2loopback.conf` instead (the installer writes this) and preload
  it once so the relay finds it.
- **`ldconfig -p` soname is `libcamera.so.0.7`**, not `libcamera.so.0`. An awk pattern
  anchored on the latter matches nothing and reports a false "linker resolves the wrong
  library" failure.
- **`strings | grep -q` under `set -o pipefail` reports FALSE NEGATIVES.** `grep -q`
  exits on the first match, `strings` dies of SIGPIPE, and the pipeline's exit
  status becomes non-zero even though the symbol IS present. Use `grep -c` and
  compare the count instead: `hits=$(strings f | grep -c Sym || true)`.
  In the Python port use `data.count(b"Sym")` on the file bytes — no pipe at all.
- **Hardened kernels restrict `dmesg` even for root** (`dmesg_restrict=1`), and
  `/dev/kmsg` is unreadable too, so `dmesg | grep` returns empty and a working
  sensor probe reads as `unknown`. Fall back to `journalctl -k --no-pager` before
  reporting the probe as untested.
- **`ipu-bridge` is built into the kernel, not a module**, so searching
  `/lib/modules/$(uname -r)/kernel/**/ipu-bridge.ko*` for the Samsung product string
  always finds nothing and reports a false "not installed". Answer "is the quirk
  upstream yet" from `/proc/config.gz` (`CONFIG_IPU_BRIDGE=m|y`) instead.
- **Do not report "REBOOT REQUIRED" from a srcversion mismatch.** Two different
  srcversion strings are just two different builds; only a *missing*
  `/sys/module/ipu_bridge/srcversion` proves the module is not loaded.
- **A black first frame is not necessarily broken.** The software AGC needs a few frames
  to settle — early frames are ~41 KB (uniform black), later ones ~400 KB with real detail.
  Capture 100+ frames before judging, and verify with a vision model rather than trusting
  file size alone.
- **`cam -l` / `gst-launch-1.0 libcamerasrc` as an unprivileged user can report zero
  cameras by design.** Raw MC-centric nodes are moved to the memberless `camera-relay`
  group and reached through a setgid launcher. Test through the relay loopback
  (`/dev/video32`) instead, or run `camera-relay doctor`.
- **`sudo` in this environment is not NOPASSWD for arbitrary commands**, though
  `sudo /usr/sbin/env <cmd>` is. Long installs run in the foreground; a backgrounded
  `sudo` fails with "a terminal is required to read the password".
- **AUR `libcamera-ipu6` / `libcamera-ipu6-ipa` conflict with the distro `libcamera` / `libcamera-ipa` packages.** The user's preference is `pacman` over AUR (`yay`/`paru`): in the Python port, replace `_git_pkg()` with `_pacman_add()` for the AUR package list. If an AUR path must be kept, remove the conflicting distro packages (`libcamera`, `libcamera-ipa`, `libcamera-tools`, `gst-plugin-libcamera`) with `pacman -Rdn --noconfirm` before calling the AUR helper; `yay -S --overwrite *` handles file conflicts but not package-level conflicts.
- **New bash script** `/home/black/webcam-setup-current.sh` provides the open libcamera source-build path (26 MHz DKMS, IVSC, relay) using only `pacman` packages — no proprietary AUR stack. Use it when the user asks for a bash-based webcam install.
- **`v4l2-relayd -i` takes a GStreamer pipeline string, not a keyword.** `-i libcamera` does not select the libcamera source; it is parsed as a (broken) pipeline and the relay produces no frames. Use the provided `camera-relay` wrapper (`camera-relay start`, `camera-relay enable-persistent --yes`) which builds the correct `libcamerasrc ! videoconvert` pipeline and manages the loopback device. If a legacy app sees no frames, check `camera-relay status` / `camera-relay doctor` before debugging the sensor.
- **Lens-cover state is readable** via the `Samsung Galaxy Book Camera Lens Cover` input
   device (SW_CAMERA_LENS_COVER, bit 23) if a black frame needs ruling out.

## System-level relay for TTY unlock (howdy / hyprlock PAM)

If the webcam must be available before the first TTY login (for `howdy` PAM via `/etc/pam.d/hyprlock`), the user-level `camera-relay.service` is not enough — it starts after login. Create a system-level service that runs before `getty`:

`/etc/systemd/system/camera-relay.service`: `Before=getty.target systemd-user-sessions.service`, `After=local-fs.target`. Use the same `ExecStart`/`ExecStop`/env (`LIBCAMERA_IPA_MODULE_PATH=/usr/local/lib/libcamera`, `GST_PLUGIN_PATH=/usr/local/lib/gstreamer-1.0`, `LD_LIBRARY_PATH=/usr/local/lib`) as the user service. Enable with `systemctl enable camera-relay.service`. Ensure `v4l2loopback` loads at boot (`/etc/modules-load.d/v4l2loopback.conf`). This uses the open libcamera stack (`pacman` preferred), not the proprietary AUR `--ipu6` stack (`v4l2-relayd.service`).

## Verify (after reboot)

```bash
sudo bash ~/Work/galaxybook-camera-fix.sh --check-only
cam -l                              # must list "Internal front camera"
camera-relay doctor                 # GPU/EGL, loopback format, relay state

timeout 40 gst-launch-1.0 v4l2src device=/dev/video32 num-buffers=120 \
  ! videoconvert ! jpegenc ! multifilesink location=/tmp/f%03d.jpg
```

Judge the *last* frame, and look at it — a black frame at the start is expected.

## Defend the patch after a reinstall

`galaxybook-camera-fix.sh` re-downloads upstream sources and rebuilds the monitor
binary from unpatched upstream, silently undoing the flicker fix. After any
reinstall, verify the installed binary before trusting the service:

```bash
# 1. The binary must contain the patch markers
strings /usr/local/bin/camera-relay-monitor | grep -c \
  'RELAY_GRACE_SECONDS\|RELAY_WARMUP_FRAMES\|Warmup hold complete'

# 2. The build time must be newer than the upstream download (not the original install)
stat -c '%y' /usr/local/bin/camera-relay-monitor

# 3. If either check fails, rebuild from the patched source directly:
sudo bash ~/Work/galaxybook-camera/reapply-flicker-fix.sh
```

- **After clone/reinstall (`blackarch installer`), the relay shows black frames and the camera LED (`OVTI02C1_00::privacy_led`) stays off.** The clone preserves the user service (`camera-relay.service`) but the upstream installer rebuilds `/usr/local/bin/camera-relay-monitor` from unpatched upstream source, which tears down the pipeline instantly (no grace period / warmup hold). The open libcamera stack (not the proprietary `--ipu6` AUR stack) relies on the user relay (`v4l2loopback` device label `Camera Relay`, `video*` node); `v4l2-relayd.service` (system) is only for the AUR `--ipu6` path. Recovery: `sudo bash ~/Work/galaxybook-camera/reapply-flicker-fix.sh`. Verify with: `systemctl --user status camera-relay.service`, `cat /sys/devices/virtual/video4linux/video0/name` = `Camera Relay`, `lsmod | grep v4l2loopback`. Never hardcode the LED device (`/sys/class/leds/*kbd*`); discover at runtime.
- **The 26 MHz ov02c10 DKMS module is per-kernel.** `/usr/src/ov02c10-1.0` builds for one kernel at a time; after booting a different kernel (e.g. hardened vs offensive), `cam -l` reports `No sensor found` even though the module is installed for the other kernel. Install it for the running kernel with `sudo dkms install ov02c10/1.0 -k $(uname -r)`, then `sudo modprobe -r ov02c10 && sudo modprobe ov02c10` and re-check `sudo dmesg | grep ov02c10`. Do not assume one install covers both kernels.
- **`reapply-flicker-fix.sh` is idempotent: it builds from `camera-relay-monitor.c.patched`,
removes any `always-on.conf`, writes `10-flicker-fix.conf`, and restarts the user
service. It is the single recovery command when the upstream installer undoes the fix.
- See `references/post-clone-relay-recovery.md` for clone/reinstall recovery.
- See `references/system-relay-tty.md` for system-level relay (before TTY/getty) for howdy PAM.
