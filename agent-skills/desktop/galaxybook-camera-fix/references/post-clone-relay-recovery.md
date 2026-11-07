# Post-Clone Webcam Relay Recovery

After a system clone (e.g. `blackarch installer --install clone`), the open
libcamera relay (`camera-relay.service`, user-level, `v4l2loopback` loopback label
`Camera Relay`) may break even though the device nodes exist. The upstream
reinstall script (`galaxybook-camera-fix.sh`) rebuilds `/opt/blackarch/bin/camera-relay-monitor`
from unpatched upstream source, removing the grace-period / warmup-hold fix.

Symptoms (verified on this host): camera node `/dev/video0` has label `Camera Relay`,
`v4l2loopback` loaded, `video1-32` (raw `isys` MC nodes) owned by `root:camera-relay`,
`camera-relay.service` active (user), `v4l2-relayd.service` inactive (expected for open
stack — system relay is only for proprietary AUR `--ipu6`), but camera LED
(`OVTI02C1_00::privacy_led`) stays off and video is black.

Recovery command (idempotent, bash, uses only `pacman` packages):

```bash
sudo bash ~/Work/galaxybook-camera/reapply-flicker-fix.sh
```

What it does:
1. Rebuilds `/opt/blackarch/bin/camera-relay-monitor` from `camera-relay-monitor.c.patched`
   (restores `RELAY_GRACE_SECONDS` and `RELAY_WARMUP_FRAMES`)
2. Removes `.config/systemd/user/camera-relay.service.d/always-on.conf` (restores on-demand)
3. Writes `10-flicker-fix.conf` (tuning: `RELAY_GRACE_SECONDS=30`, `RELAY_WARMUP_FRAMES=15`)
4. Restarts `camera-relay.service` (user)

Verification sequence (run as desktop user, not root):

```bash
# Relay service state
systemctl --user status camera-relay.service

# Loopback label
cat /sys/devices/virtual/video4linux/video0/name   # must return "Camera Relay"

# Module present
lsmod | grep v4l2loopback

# Group for raw nodes
getent group camera-relay

# Raw node ownership
ls -l /dev/video1

# LED device (discover at runtime, not hardcoded)
cat /sys/class/leds/samsung-galaxybook::kbd_backlight/brightness  # keyboard only
# Camera privacy LED: check input device property
cat /sys/class/input/input*/capabilities/* 2>/dev/null | grep -i lens || echo "Check SW_CAMERA_LENS_COVER (bit 23) on Samsung Galaxy Book Camera Lens Cover input device"
```

The user's standing preference: bash scripts preferred over proprietary stacks; open libcamera
source build preferred over proprietary AUR (`libcamera-ipu6`, `icamerasrc`, `v4l2-relayd`);
`pacman` over AUR (`yay`/`paru`); no hardcoding of device paths.
