# Galaxy Book camera — flicker fix + on-demand mode

Machine: Samsung Galaxy Book (Intel IPU6 + OV02C10 sensor), BlackArch/Arch,
Hyprland. Camera stack installed by `~/Work/galaxybook-camera-fix.sh`
(upstream: https://github.com/Andycodeman/samsung-galaxy-book-linux-fixes).

## The two problems

**1. Flickering light.** The image visibly brightens ("flashes") when an app
opens the camera, and again on any relay restart mid-call.

Root cause: libcamera's *simple* IPA auto-exposure algorithm has **no
startup-frame skip**. In libcamera v0.7.2,
`src/ipa/simple/algorithms/agc.cpp` corrects exposure from the very first
frame — there is no `kNumStartupFrames` hold in this backend (that constant
exists in the Raspberry Pi IPA, not here). AGC state lives in the *pipeline*
(`context.activeState.agc`), not in the sensor, so it starts from the bottom
every time a pipeline is created. Measured ramp on this machine:

    16 -> 43 -> 66 -> 71 mean luma over the first ~5 frames

That ramp *is* the flicker. The always-on relay mode upstream ships to work
around it keeps one pipeline alive so the ramp happens once, before any client
connects — but that means the camera (and its privacy LED) is powered up and
consuming CPU from login to shutdown.

Note: the simple IPA also has **no `AeFlickerMode` support at all**
(`grep -ri flicker src/ipa/simple/` returns nothing), so mains-frequency
banding cannot be fixed from a tuning file. Keeping exposure stable is the
only available lever.

**2. Camera should be up only on demand.** The relay was running in
always-on mode (`~/.config/systemd/user/camera-relay.service.d/always-on.conf`),
holding the sensor and LED on permanently and burning ~15% of one CPU core.

## The fix

On-demand mode, with the AGC ramp hidden from clients by two knobs added to
the monitor (`camera-relay-monitor.c`):

| Knob | Default | What it does |
|------|---------|--------------|
| `RELAY_WARMUP_FRAMES` | `15` | On a cold pipeline start, swallow this many leading frames and keep writing black. The first real frame a client sees is already settled, so there is no visible brighten-on-open. 15 frames ≈ 0.5 s of extra black. |
| `RELAY_GRACE_SECONDS` | `30` | After the last client disconnects, keep the pipeline warm this long instead of tearing it down. A reconnect inside the window (app restart, tab refresh, camera mute/unmute) reuses the settled pipeline and skips the warmup hold entirely. After the window the pipeline stops and the camera goes idle. |

Set `RELAY_GRACE_SECONDS=0` for the strictest behaviour (pipeline stops the
moment the last client leaves; every connect pays the ~0.5 s warmup hold).

Both knobs are read once at monitor startup; edit the drop-in and restart the
service to change them.

### Measured behaviour (this machine)

Cold start (idle → app opens camera):

    frame   0..17:  16.00   <- black, warmup hold (15 pipeline frames + startup)
    frame  18..89:  ~114    <- settled picture, no ramp visible

Reconnect within the grace window:

    frame   0: 114.16   <- settled immediately, no hold, no ramp

Grace expiry:

    [monitor] All clients gone — grace period 30s
    [monitor] Grace period expired — stopping pipeline
    state: idle, gst pipeline gone, LED off

Idle cost: monitor process **~0.17% CPU, ~6 MB RSS** (delta-sampled from
`/proc/<pid>/stat`). Compare always-on: ~15% CPU, ~93 MB RSS, continuously.

The loopback device and its PipeWire node stay present while idle (the monitor
holds the writer fd so `ready_for_capture` never drops), so apps still list
"Camera Relay" and just get black frames until the pipeline warms up.

## Files

| Path | What |
|------|------|
| `/opt/blackarch/bin/camera-relay-monitor` | patched monitor (grace + warmup) |
| `~/Work/galaxybook-camera/camera-relay-monitor.c.patched` | full patched source |
| `~/Work/galaxybook-camera/camera-relay-monitor-flicker-fix.patch` | diff vs upstream |
| `~/Work/galaxybook-camera/reapply-flicker-fix.sh` | rebuild + reinstall + switch mode |
| `/opt/blackarch/config/systemd/user/camera-relay.service.d/10-flicker-fix.conf` | the two `Environment=` knobs |
| `…/camera-relay.service.d/always-on.conf.disabled` | the old always-on override, kept for rollback |

`~/.config/systemd/user` is a symlink to
`/opt/blackarch/config/systemd/user` on this box, so the
drop-in lives in the distro config tree.

## Re-applying after a camera-fix reinstall

`galaxybook-camera-fix.sh` re-downloads upstream sources, rebuilds
`camera-relay-monitor` from *upstream* source, and rewrites the always-on
drop-in — all three undo this fix. After any reinstall:

    sudo bash ~/Work/galaxybook-camera/reapply-flicker-fix.sh

That rebuilds the patched monitor, removes the always-on drop-in, writes the
tuning drop-in, and restarts the service. Idempotent.

## Rolling back

To return to upstream always-on behaviour:

    cd /opt/blackarch/config/systemd/user/camera-relay.service.d
    rm -f 10-flicker-fix.conf
    mv always-on.conf.disabled always-on.conf
    systemctl --user daemon-reload && systemctl --user restart camera-relay.service

(The patched monitor still works in always-on mode; the knobs are simply
inert there because the pipeline never restarts.)

## Verifying

    # state and process
    cat $XDG_RUNTIME_DIR/camera-relay-state          # idle | streaming
    systemctl --user status camera-relay.service

    # monitor's own log (warmup / grace events land here)
    tail -f $XDG_RUNTIME_DIR/camera-relay.log

    # confirm the ramp is hidden — run a capture and watch the first frames
    v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=90 --stream-to=- \
      | python3 -c 'import sys
F=1920*1080*2; b=sys.stdin.buffer; i=0
while i<90:
    d=b.read(F)
    if len(d)<F: break
    print(f"frame {i:3d}: {sum(d[::128])/len(d[::128]):6.2f}"); i+=1'

    # idle CPU
    MP=$(pgrep -f 'camera-relay-monitor /dev/video0'); ps -o %cpu,rss -p "$MP"

## Gotchas

- **Do not run `cam -l` while the relay is streaming.** Opening the sensor
  resets the V4L2 flip controls on inverted-sensor models, and a running
  pipeline never re-applies them, so the image stays upside-down until the
  relay restarts. Use `pw-cli ls Node` (does not open the sensor) or restart
  the relay afterwards.
- **sudo for the monitor install.** `/usr/local/bin` is root-owned and the
  stock sudoers rules on this box do not cover `install`; a rule was added:
  `black ALL=(root) NOPASSWD: /usr/bin/install -m 755 /tmp/camera-relay-monitor /opt/blackarch/bin/camera-relay-monitor`
- The warmup hold delays the *first* frame by ~0.5 s on a cold start. That is
  deliberate: a client that connects before AGC settles would otherwise see
  the ramp. If a 0.5 s black lead-in is worse than the ramp for a given app,
  lower `RELAY_WARMUP_FRAMES`.
