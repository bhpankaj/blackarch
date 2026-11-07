#!/usr/bin/env bash
# ============================================================================
# Re-apply the camera-relay flicker fix + on-demand mode
#
# Why this exists: galaxybook-camera-fix.sh downloads the upstream fix set and
# rebuilds /opt/blackarch/bin/camera-relay-monitor from upstream source on every
# run, then writes the always-on drop-in. Both of those undo this fix. Run
# this script after any camera-fix reinstall.
#
#   sudo bash reapply-flicker-fix.sh
#
# What it does:
#   1. Rebuilds camera-relay-monitor from the patched source (grace period +
#      warmup hold) and installs it to /usr/local/bin.
#   2. Removes the always-on drop-in so the relay runs on-demand.
#   3. Writes the 10-flicker-fix.conf drop-in (tuning knobs).
#   4. Restarts camera-relay.service.
#
# Idempotent: safe to run repeatedly.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$HERE/camera-relay-monitor-flicker-fix.patch"
PATCHED_C="$HERE/camera-relay-monitor.c.patched"
MONITOR=/usr/local/bin/camera-relay-monitor
UPSTREAM_RAW="https://raw.githubusercontent.com/Andycodeman/samsung-galaxy-book-linux-fixes/main/camera-relay/camera-relay-monitor.c"

# systemd user drop-in dir (the desktop user's ~/.config/systemd is a symlink
# into the distro config tree on this box; resolve it so we write the real file)
TARGET_USER="${SUDO_USER:-black}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
DROPIN_DIR="$(readlink -f "$TARGET_HOME/.config/systemd/user/camera-relay.service.d")"

[[ $EUID -eq 0 ]] || { echo "run as root: sudo bash $0" >&2; exit 1; }
command -v gcc >/dev/null || { echo "gcc required" >&2; exit 1; }

echo "[+] Rebuilding patched camera-relay-monitor"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [[ -f "$PATCHED_C" ]]; then
    cp "$PATCHED_C" "$TMP/camera-relay-monitor.c"
else
    # Fall back to fetching upstream and applying the patch, so a missing
    # patched copy does not leave the box without the fix.
    curl -fsSL "$UPSTREAM_RAW" -o "$TMP/camera-relay-monitor.c"
    patch -p0 -d "$TMP" < "$PATCH"
fi

# Sanity: the patched source must carry both knobs before we install it.
grep -q RELAY_GRACE_SECONDS "$TMP/camera-relay-monitor.c" \
    || { echo "patched source is missing the grace-period code" >&2; exit 1; }
grep -q RELAY_WARMUP_FRAMES "$TMP/camera-relay-monitor.c" \
    || { echo "patched source is missing the warmup-hold code" >&2; exit 1; }

gcc -O2 -Wall -o "$TMP/camera-relay-monitor" "$TMP/camera-relay-monitor.c" 2>/dev/null
install -m 755 "$TMP/camera-relay-monitor" "$MONITOR"
echo "[+] Installed $MONITOR"

echo "[+] Switching relay to on-demand"
mkdir -p "$DROPIN_DIR"
# The always-on drop-in is what pins the relay into the always-on pipeline.
if [[ -f "$DROPIN_DIR/always-on.conf" ]]; then
    mv -f "$DROPIN_DIR/always-on.conf" "$DROPIN_DIR/always-on.conf.disabled"
fi
# The on-demand base unit is written by `camera-relay enable-persistent`; if it
# was replaced by an always-on drop-in, regenerate it.
run_as_user() {
    local uid; uid="$(id -u "$TARGET_USER")"
    sudo -u "$TARGET_USER" \
        XDG_RUNTIME_DIR="/run/user/$uid" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" "$@"
}
if [[ ! -f "$TARGET_HOME/.config/systemd/user/camera-relay.service" ]] \
   || ! grep -q -- '--on-demand' "$TARGET_HOME/.config/systemd/user/camera-relay.service"; then
    run_as_user /usr/local/bin/camera-relay enable-persistent --yes || true
fi

echo "[+] Writing tuning drop-in"
cat > "$DROPIN_DIR/10-flicker-fix.conf" <<'EOF'
[Unit]
Description=Camera Relay (on-demand, AGC-ramp flicker suppressed)

[Service]
# On-demand + flicker suppression. See README.md in this directory for the
# full rationale. libcamera's simple-IPA AGC has no startup-frame skip, so
# every cold pipeline start replays its exposure ramp; the warmup hold hides
# that ramp from clients and the grace period avoids re-paying it on quick
# reconnects. The camera still falls idle (LED off, ~0% CPU) when unused.
Environment=RELAY_GRACE_SECONDS=30
Environment=RELAY_WARMUP_FRAMES=15
EOF
chown "$TARGET_USER:$TARGET_USER" "$DROPIN_DIR/10-flicker-fix.conf" 2>/dev/null || true

echo "[+] Restarting camera-relay.service"
run_as_user systemctl --user daemon-reload
run_as_user systemctl --user restart camera-relay.service

sleep 6
run_as_user systemctl --user --no-pager status camera-relay.service | head -12
echo "[+] Done. Camera is on-demand; LED lights only while (and 30s after) use."
