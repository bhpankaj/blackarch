# IPU6 hardware-ISP stack — what `--ipu6` does

The default path in this script is the **open libcamera stack** (source-built
libcamera 0.7.2 + the camera relay). `--ipu6` installs the **proprietary
hardware-ISP stack** instead. They are alternatives, not layers: only one should
be active at a time.

IPU6 outputs raw Bayer, so it needs Intel's HAL (`libcamhal`) to debayer and run
3A, `icamerasrc` to expose it to GStreamer, and `v4l2-relayd` to present it as a
normal `/dev/video` node — `icamerasrc` creates no device of its own.

## Usage

```
sudo blackarch-webcam-setup --ipu6           # install the AUR stack
sudo blackarch-webcam-setup --ipu6 status    # report only, install nothing
sudo blackarch-webcam-setup --ipu6 verify    # verify an existing install
```

`--ipu6` refuses to run on IPU7 hardware and points at `--ipu7` instead.

## What gets installed

| Package | Role |
|---|---|
| `intel-ipu6-camera-bin` | IPU firmware (`lib/firmware/intel/ipu/*.bin`) + ISP libs (`libia_*.so`, `libgcss*.so`) |
| `intel-ipu6-camera-hal-git` | `libcamhal` HAL, provides `ipu6-camera-hal` |
| `icamerasrc-git` | GStreamer source plugin |
| `libcamera-ipu6` + `-ipa` | libcamera with the IPU6 pipeline handler |
| `gst-plugin-libcamera-ipu6` | GStreamer plugin |
| `v4l2-relayd` | relay daemon (omarchy repo) |

Plus `/etc/default/v4l2-relayd` (points at `icamerasrc`, 1280x720 NV12) and a
`v4l2-relayd.service.d/` override labelling the loopback `IPU6 Camera` so it is
distinguishable from the open stack's `Camera Relay` node.

## Kernel driver: use the in-tree one

`intel-ipu6-dkms-git` (Intel's `ipu6-drivers` tree) is **broken on kernel >=
6.10** — the in-tree `intel_ipu6`/`intel_ipu6_isys` drivers took over and the
out-of-tree package no longer works. This script installs only the AUR userspace
stack and warns if the stale DKMS package is present:

```
dkms remove ipu6-drivers/<version> --all
```

On kernel < 6.10 the DKMS package *is* required, and the script says so.

Required kernel config (all present on this kernel):
`CONFIG_VIDEO_INTEL_IPU6=m`, `CONFIG_IPU_BRIDGE=m`, `CONFIG_INTEL_SKL_INT3472=m`,
`CONFIG_VIDEO_OV02C10=m`.

## Known build quirks in the AUR packages

- `intel-ipu6-camera-hal-git`: unused-variable errors under `-Werror` need
  `sed -i 's/-Werror//g' intel-ipu6-camera-hal/CMakeLists.txt` in `build()`.
- `libcamera-ipu6`: its `check()` runs `v4l2_compat` tests that fail; filter
  with `| grep -v v4l2_compat`, and fix the relative `../` paths if you use a
  custom `BUILDDIR`.

## Verify after reboot

```bash
sudo blackarch-webcam-setup --ipu6 status
sudo blackarch-webcam-setup --ipu6 verify
gst-inspect-1.0 icamerasrc
ls /usr/lib/libcamhal/plugins/                 # HAL plugins for your platform
systemctl status v4l2-relayd
```

If the loopback is black: confirm `/etc/default/v4l2-relayd` has
`VIDEOSRC="icamerasrc buffer-count=7"` and that the HAL plugin for your platform
matches the IPU generation (`intel-ipu6-camera-hal-git` covers Tiger/Alder/
Meteor Lake).

