---
name: camera-pipeline-tuning
description: Fix camera startup flicker; keep webcam idle on demand.
version: 1.0.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [camera, webcam, v4l2loopback, libcamera, gstreamer, systemd, flicker]
    related_skills: [galaxybook-camera-fix]
---

# Camera pipeline tuning (v4l2loopback / libcamera / GStreamer)

## When to Use

Use when a camera *works* but the picture or the resource use is wrong: the image
flashes/brightens when an app opens it, the camera is powered up permanently when
it should be idle, or a locally patched helper keeps reverting after a reinstall.
For installing the underlying driver stack on a Galaxy Book (IPU6/OV02C10), see the
`galaxybook-camera-fix` skill — this one is about the pipeline above it.

## Locate the loopback by card label, never by node number

The relay's v4l2loopback node is not stable across boots (`/dev/video0` here,
`/dev/video32` there). Resolve it every time:

```bash
RELAY=$(v4l2-ctl --list-devices \
  | awk '/Camera Relay/{getline; gsub(/[ \t]/,""); print; exit}')
```

Hardcoding a node number into a script or a verification command is the single
most common way to "prove" a working camera is broken.

## Default to on-demand; always-on is a fallback, not the goal

An on-demand relay idles at ~0% CPU with the sensor and privacy LED off, and only
spins the pipeline up when an app opens the device. Always-on holds one pipeline
forever — it hides startup transients but burns ~15% of a CPU core and keeps the
LED lit from login to shutdown.

Reconcile the two with **warmup + grace**, which the patched relay monitor reads
as environment variables (set them in a systemd drop-in):

```ini
# ~/.config/systemd/user/camera-relay.service.d/10-flicker-fix.conf
[Service]
Environment=RELAY_GRACE_SECONDS=30
Environment=RELAY_WARMUP_FRAMES=15
```

- `RELAY_WARMUP_FRAMES` — on a cold pipeline start the monitor swallows that many
  leading frames and keeps writing black, so the first real frame a client sees is
  already settled. Removes the visible brighten-on-open. `0` disables it.
- `RELAY_GRACE_SECONDS` — after the last client leaves, keep the pipeline warm this
  long before tearing it down, so a quick reconnect (app restart, tab refresh,
  mute/unmute) reuses the settled pipeline and skips the warmup. `0` stops the
  moment the last client leaves (every connect then pays the warmup hold).

Both are read once at monitor startup — change the drop-in and restart the service.
The patch logic and measured results are in `references/transient-suppression.md`.

## Resolve the systemd user dir before writing a drop-in

On distro-managed desktops `~/.config/systemd/user` is often a **symlink** into the
vendor config tree (e.g. `-> /opt/<vendor>/config/systemd/user`). Write the drop-in
through `readlink -f` or you edit a path the session never reads:

```bash
DROPIN_DIR="$(readlink -f ~/.config/systemd/user)/camera-relay.service.d"
mkdir -p "$DROPIN_DIR"
```

Always `systemctl --user daemon-reload` after adding/removing a drop-in, then
restart the unit.

## Verify the transient is actually gone — measure per-frame luma

Do not judge from a screenshot or a single frame. Stream the device and print mean
luma per frame; the ramp is a step sequence in the first frames.

```bash
v4l2-ctl -d "$RELAY" --stream-mmap --stream-count=90 --stream-to=- \
  | python3 -c 'import sys
F=1920*1080*2; b=sys.stdin.buffer; i=0
while i<90:
    d=b.read(F)
    if len(d)<F: break
    print(f"frame {i:3d}: {sum(d[::128])/len(d[::128]):6.2f}"); i+=1'
```

Healthy on-demand result: the leading frames are uniform black (luma ~16), then
the picture jumps **straight** to settled (~114) with no intermediate steps. A
reconnect inside the grace window is settled from frame 0. Idle CPU is measured by
delta-sampling `/proc/<pid>/stat` utime+stime, not from `ps %CPU` (which is a
lifetime average and stays high after a busy period).

## Make local patches survive a reinstall

Vendor installer scripts re-download upstream sources and rebuild the helpers, so a
hand-patched binary silently reverts. Defend against that with all four of:

1. Keep the **patched source** and a **diff against upstream** next to each other
   (e.g. `~/Work/<thing>/foo.c.patched` + `foo.patch`), and prove the diff applies
   cleanly to a pristine upstream copy before trusting it.
2. Keep an idempotent **re-apply script** that rebuilds from the patched source,
   fixes the service mode, and restarts — so recovery is one command.
3. **Teach the installer to prefer the local patched source** over the freshly
   downloaded one, and to write the tuning drop-in. Otherwise the fix ships
   installed-and-inert on the next run.
4. After any reinstall, **verify the installed binary carries the patch**, not just
   that the service is active:
   `strings /usr/local/bin/<helper> | grep -c <marker>`.

## Pitfalls

- **Do not open the sensor to probe it while the relay is streaming.** `cam -l`
  (and anything that opens the libcamera CameraManager) resets the V4L2 flip
  controls on inverted-sensor models, and a running pipeline never re-applies them,
  so the image stays upside-down until the relay restarts. Use `pw-cli ls Node`
  (metadata only) instead, or restart the relay afterwards.
- **A device that stays present while idle is correct, not a leak.** The on-demand
  monitor holds the writer fd open so `ready_for_capture` never drops; apps still
  list the camera and simply get black frames until the pipeline warms up. Confirm
  "idle" by the absence of the gst pipeline process, not by the device disappearing.
After any reinstall of the upstream fix set, verify the installed binary carries
the patch — the service being `active (running)` does not prove it:

```bash
strings /opt/blackarch/bin/camera-relay-monitor | grep -c \
  'RELAY_GRACE_SECONDS\|RELAY_WARMUP_FRAMES\|Warmup hold complete'
stat -c '%y' /opt/blackarch/bin/camera-relay-monitor
```

If either fails, rebuild from the patched source directly:
`sudo bash ~/Work/galaxybook-camera/reapply-flicker-fix.sh`. The script is
idempotent and handles the drop-in, mode switch, and service restart.

- When a command you need is not NOPASSWD, hand the user the exact minimal
  sudoers rule and stop — do not loop retrying `sudo -n`, and do not guess at
  broad rules. State the single line, e.g.
  `black ALL=(root) NOPASSWD: /usr/bin/install -m 755 /tmp/<bin> /usr/local/bin/<bin>`,
  and wait for them to add it.
- **`ps %CPU` lies for idle checks** after any busy period. Sample utime/stime twice
  with a sleep between.
