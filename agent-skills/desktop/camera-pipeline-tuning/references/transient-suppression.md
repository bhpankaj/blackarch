# Suppressing a capture pipeline's startup transient

Depth for the warmup/grace knobs in SKILL.md. Applies to any pipeline whose
auto-exposure (or auto-anything) state is per-pipeline and re-initialises on every
start.

## Why the transient exists

libcamera's *simple* IPA auto-exposure has **no startup-frame skip**. In v0.7.2
`src/ipa/simple/algorithms/agc.cpp` corrects exposure from the very first frame —
there is no `kNumStartupFrames` hold in this backend (that constant belongs to the
Raspberry Pi IPA, not the simple one). AGC state lives in the pipeline context
(`context.activeState.agc`), not in the sensor, so every newly created pipeline
replays the ramp from the bottom.

Measured on an OV02C10 / IPU6 Galaxy Book, cold start: mean luma steps
`16 -> 43 -> 66 -> 71` over roughly the first 5 frames. That step sequence is what
the eye reads as "the light flickers when I open the camera".

Two corollaries worth knowing before you try to fix it elsewhere:

- The simple IPA has **no `AeFlickerMode` support at all** (`grep -ri flicker
  src/ipa/simple/` returns nothing), so mains-frequency banding cannot be tuned
  from a YAML tuning file. Keeping exposure stable is the only lever.
- Mains banding is a *spatial* row-brightness oscillation, not a temporal ramp. If
  in doubt, measure the detrended row residual across a frame to tell them apart
  before chasing the wrong cause.

## The two-lever fix

Both levers are applied in the relay monitor (`camera-relay-monitor.c`), which
sits between the GStreamer pipeline and the v4l2loopback device and owns the frame
loop. Patch shape:

1. Read `RELAY_GRACE_SECONDS` and `RELAY_WARMUP_FRAMES` from the environment once
   at startup, with sane defaults (30 / 15) and bounds-checked parsing.
2. In the relay loop, while `frames_seen < warmup_frames`, increment `frames_seen`
   and write the **black** frame instead of the frame just read from the pipeline.
   Reset `frames_seen = 0` every time a pipeline is (re)started and on stop.
3. When the client count has been zero for the existing stop-delay, do **not** stop
   immediately. Enter a grace state, decrement a counter once per second, and only
   stop when it reaches zero. If a client reappears during grace, cancel it and
   keep serving the warm pipeline.

Key detail: the warmup hold must be reset on **every** pipeline start, not just the
first, or a cold restart after grace expiry shows the ramp again.

## Why not just run always-on

Always-on keeps one pipeline alive so the ramp happens once, before any client
connects. It works, and it was the original recommendation, but it is the wrong
trade: the sensor and privacy LED stay powered and the software ISP debayers
continuously (~15% of one CPU core, ~93 MB RSS) whether or not anything uses the
camera. Warmup+grace gets the same flicker-free result at ~0.17% CPU / ~6 MB RSS
while idle, and only powers the camera while it is actually in use.

## Verification recipe

Cold start (no client -> client connects): leading frames black (~16), then a
straight jump to settled (~114) with no intermediate steps.

Reconnect inside the grace window: frame 0 already settled (~114), no black lead-in.

Grace expiry: the monitor log shows the grace countdown then
`Grace period expired — stopping pipeline`; the gst pipeline process disappears and
the service state reads `idle` while the device stays present.

Measure idle CPU with a delta sample:

```bash
MP=$(pgrep -f 'camera-relay-monitor /dev/video0' | head -1)
set -- $(awk '{print $14,$15}' /proc/$MP/stat); U1=$1; S1=$2
sleep 6
set -- $(awk '{print $14,$15}' /proc/$MP/stat); U2=$1; S2=$2
echo "idle: $(awk -v u=$((U2-U1)) -v s=$((S2-S1)) -v hz=$(getconf CLK_TCK) \
  'BEGIN{printf "%.2f%%\n", (u+s)/hz/6*100}')"
```

## Rollback

Keep the old service-mode drop-in renamed rather than deleted
(`always-on.conf` -> `always-on.conf.disabled`) so returning to the previous
behaviour is a `mv` + `daemon-reload` + restart, not a reconstruction.
