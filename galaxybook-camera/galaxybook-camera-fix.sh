#!/bin/bash
# ============================================================================
# Galaxy Book Camera Fix — Arch / BlackArch
#
# Repairs the built-in camera on Samsung Galaxy Book3/Book4 (Intel IPU6 +
# OV02C10 sensor). Installs:
#
#   [1] ov02c10 DKMS module patched for the 26 MHz external clock
#   [2] ipu-bridge DKMS module with the Samsung rotation quirk
#   [3] libcamera 0.7.2 built from source with the OV02C10 sensor helper
#   [4] OV02C10 tuning file for the Simple ISP
#   [5] Environment + group configuration (video, kvm)
#   [6] Raw IPU6 MC-node hiding (memberless camera-relay group)
#   [7] On-demand camera relay for non-PipeWire apps (Zoom, OBS, VLC)
#
# Upstream fix set: https://github.com/Andycodeman/samsung-galaxy-book-linux-fixes
#
# Usage:
#   sudo bash galaxybook-camera-fix.sh                 # full install
#   sudo bash galaxybook-camera-fix.sh --check-only    # report status, change nothing
#   sudo bash galaxybook-camera-fix.sh --sensor-only   # only the 26 MHz DKMS fix
#   sudo bash galaxybook-camera-fix.sh --skip-libcamera-rebuild
#   sudo bash galaxybook-camera-fix.sh --uninstall
#
# Requires a reboot when done.
# ============================================================================

set -uo pipefail

FIX_URL="https://github.com/Andycodeman/samsung-galaxy-book-linux-fixes/archive/refs/heads/main.tar.gz"
WORK_DIR="/tmp/samsung-galaxy-book-linux-fixes-main"
LIBCAMERA_BUILD_VER="v0.7.2"
LIBCAMERA_BUILD_DIR="/tmp/libcamera-ipu6-build"
OV02C10_DKMS_VER="1.0"
IPU_BRIDGE_DKMS_VER="1.4"

C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'
C_BLU=$'\033[0;34m'; C_DIM=$'\033[2m';    C_RST=$'\033[0m'

info()  { echo "${C_GRN}[+]${C_RST} $*"; }
warn()  { echo "${C_YEL}[!]${C_RST} $*"; }
err()   { echo "${C_RED}[x]${C_RST} $*" >&2; }
step()  { echo; echo "${C_BLU}=== $* ===${C_RST}"; }
die()   { err "$*"; exit 1; }

# ── Options ─────────────────────────────────────────────────────────────────
MODE="install"
SKIP_LIBCAMERA_REBUILD=false
for arg in "$@"; do
    case "$arg" in
        --check-only)               MODE="check" ;;
        --uninstall)                MODE="uninstall" ;;
        --sensor-only)              MODE="sensor-only" ;;
        --skip-libcamera-rebuild)   SKIP_LIBCAMERA_REBUILD=true ;;
        -h|--help)                  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) warn "Unknown argument '$arg' (ignored)" ;;
    esac
done

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"

# The camera-relay service is a systemd *user* unit, so user-scoped steps must
# run as the desktop user, not root. Recover that user from sudo.
TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
    TARGET_USER=$(loginctl list-sessions --no-legend 2>/dev/null \
                  | awk '$4 == "seat0" {print $3}' | head -1)
fi
[[ -n "$TARGET_USER" ]] || TARGET_USER="black"
TARGET_UID=$(id -u "$TARGET_USER" 2>/dev/null || echo "")
TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)

run_as_user() {
    [[ -n "$TARGET_UID" ]] || return 1
    sudo -u "$TARGET_USER" \
        XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TARGET_UID/bus" \
        "$@"
}

# ── Detection helpers ───────────────────────────────────────────────────────
ov02c10_module_path() { modinfo ov02c10 2>/dev/null | awk '/^filename:/{print $2}'; }
ov02c10_is_patched()  { ov02c10_module_path | grep -q "/updates/"; }
sensor_probed()       { dmesg 2>/dev/null | grep -q "26000000Hz clock"; }
clock_error_present() { dmesg 2>/dev/null | grep -q "external clock 26000000 is not supported"; }
libcamera_local_present() {
    compgen -G "/usr/local/lib*/libcamera.so.*" >/dev/null 2>&1 \
    || compgen -G "/usr/local/lib/*/libcamera.so.*" >/dev/null 2>&1
}

check_status() {
    step "Camera fix status"

    echo -n "  ov02c10 sensor module : "
    if ov02c10_is_patched; then echo "${C_GRN}patched (DKMS)${C_RST} — $(ov02c10_module_path)"
    else echo "${C_RED}stock${C_RST} — $(ov02c10_module_path)"; fi

    echo -n "  sensor probe          : "
    if sensor_probed; then echo "${C_GRN}OK — 26 MHz clock accepted${C_RST}"
    elif clock_error_present; then echo "${C_RED}FAILED — 26 MHz clock rejected${C_RST}"
    else echo "${C_YEL}unknown${C_RST}"; fi

    echo -n "  ipu-bridge rotation   : "
    if dkms status 2>/dev/null | grep -q "^ipu-bridge-fix/.*installed"; then
        echo "${C_GRN}DKMS fix installed${C_RST}"
    elif zstdcat "/lib/modules/$(uname -r)/kernel/drivers/media/pci/intel/ipu-bridge.ko.zst" 2>/dev/null \
         | strings | grep -q "$(cat /sys/class/dmi/id/product_name 2>/dev/null)"; then
        echo "${C_GRN}upstream has quirk${C_RST}"
    else echo "${C_YEL}not installed${C_RST} (image may be upside-down)"; fi

    echo -n "  libcamera (source)    : "
    if libcamera_local_present; then
        echo "${C_GRN}present in /usr/local${C_RST} — $(ls /usr/local/lib*/libcamera.so.0.* /usr/local/lib/*/libcamera.so.0.* 2>/dev/null | head -1)"
    else echo "${C_YEL}not built${C_RST} — using system libcamera (no OV02C10 helper → dark image)"; fi

    echo -n "  IPA module path       : "
    if [[ -n "${LIBCAMERA_IPA_MODULE_PATH:-}" ]]; then echo "${C_GRN}$LIBCAMERA_IPA_MODULE_PATH${C_RST}"
    elif [[ -f /etc/environment.d/libcamera-ipa.conf ]]; then echo "${C_GRN}configured${C_RST} (/etc/environment.d)"
    else echo "${C_YEL}not configured${C_RST}"; fi

    echo -n "  v4l2loopback          : "
    if modinfo v4l2loopback &>/dev/null; then
        local lbl; lbl=$(cat /sys/devices/virtual/video4linux/video*/name 2>/dev/null | grep -v "Intel IPU" | head -1)
        echo "${C_GRN}available${C_RST}${lbl:+ — label \"$lbl\"}"
    else echo "${C_YEL}not installed${C_RST} (relay needs it)"; fi

    echo -n "  camera-relay service  : "
    if run_as_user systemctl --user is-enabled camera-relay.service &>/dev/null; then
        echo "${C_GRN}enabled${C_RST}"
    else echo "${C_YEL}not enabled${C_RST}"; fi

    echo -n "  user groups           : "
    echo "$(id -nG "$TARGET_USER" 2>/dev/null | tr ' ' ',')"
    [[ "$(id -nG "$TARGET_USER" 2>/dev/null)" == *kvm*   ]] || echo "        ${C_YEL}missing: kvm${C_RST} (needed for /dev/udmabuf → GPU debayer)"
    [[ "$(id -nG "$TARGET_USER" 2>/dev/null)" == *video* ]] || echo "        ${C_YEL}missing: video${C_RST}"

    step "libcamera view"
    if command -v cam &>/dev/null; then
        cam -l 2>&1 | grep -E "Available cameras|Internal|camera" | sed 's/^/  /' || echo "  (no cameras listed)"
    else
        warn "cam not installed — pacman -S libcamera-tools"
    fi

    step "PipeWire view"
    if run_as_user pw-cli ls Node 2>/dev/null | grep -q "libcamera"; then
        info "PipeWire sees the camera via libcamera"
    else
        warn "PipeWire does not see a libcamera node yet"
    fi
}

# ── [1] Packages ────────────────────────────────────────────────────────────
install_packages() {
    step "[1/7] Installing dependencies"
    local pkgs=(
        base-devel dkms linux-headers git
        meson ninja pkgconf cmake
        python-yaml python-jinja python-ply
        gnutls libyaml libevent libdrm libjpeg-turbo libtiff libelf libunwind
        openssl gstreamer gst-plugins-base gst-plugin-libcamera
        libcamera libcamera-tools libcamera-ipa
        pipewire pipewire-libcamera
        v4l2loopback-dkms v4l2loopback-utils
        acl libayatana-appindicator
    )
    local missing=()
    for p in "${pkgs[@]}"; do
        pacman -Q "$p" &>/dev/null || missing+=("$p")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        info "Installing: ${missing[*]}"
        pacman -S --needed --noconfirm "${missing[@]}" \
            || warn "Some packages failed to install — continuing"
    else
        info "All dependencies already present"
    fi
}

# ── [2] ov02c10 26 MHz DKMS ─────────────────────────────────────────────────
install_ov02c10_dkms() {
    step "[2/7] Installing patched ov02c10 driver (26 MHz clock)"

    if ov02c10_is_patched && dkms status "ov02c10/$OV02C10_DKMS_VER" 2>/dev/null | grep -q installed; then
        info "Already installed and active"
        return 0
    fi

    local src_dir="/usr/src/ov02c10-$OV02C10_DKMS_VER"
    local repo_dir="$WORK_DIR/ov02c10-26mhz-fix"
    [[ -f "$repo_dir/ov02c10.c" ]] || die "Source not found: $repo_dir/ov02c10.c"

    # Neutralise stale community workarounds that pass a non-existent parameter
    local f
    for f in /etc/modprobe.d/*.conf; do
        [[ -f "$f" ]] || continue
        if grep -Eq '^[[:space:]]*options[[:space:]]+ov02c10\b.*clk_freq' "$f"; then
            cp -a "$f" "$f.ov02c10-26mhz.bak"
            sed -i -E 's/^([[:space:]]*options[[:space:]]+ov02c10\b.*clk_freq.*)$/# disabled by galaxybook-camera-fix: \1/' "$f"
            info "Neutralised stale clk_freq option in $f (backup saved)"
        fi
    done

    dkms remove "ov02c10/$OV02C10_DKMS_VER" --all &>/dev/null || true
    rm -rf "$src_dir"; mkdir -p "$src_dir"
    cp "$repo_dir/ov02c10.c" "$repo_dir/Makefile" "$repo_dir/dkms.conf" "$src_dir/"

    dkms add     "ov02c10/$OV02C10_DKMS_VER"                 || die "dkms add failed"
    dkms build   "ov02c10/$OV02C10_DKMS_VER"                 || {
        err "DKMS build failed — see /var/lib/dkms/ov02c10/$OV02C10_DKMS_VER/build/make.log"
        die "Sensor driver was not replaced"
    }
    dkms install "ov02c10/$OV02C10_DKMS_VER"                 || die "dkms install failed"

    depmod -a "$(uname -r)"
    info "Installed: $(ov02c10_module_path)"

    if lsmod | grep -q '^ov02c10'; then
        rmmod ov02c10 2>/dev/null \
            && modprobe ov02c10 2>/dev/null \
            || warn "Could not reload ov02c10 live — reboot will apply it"
    fi

    sleep 1
    if sensor_probed; then
        info "Sensor probed successfully — 26 MHz clock accepted"
    else
        warn "Sensor not confirmed this boot (stock driver may still be bound) — reboot and re-check"
    fi
}

# ── [3] ipu-bridge rotation DKMS ────────────────────────────────────────────
install_ipu_bridge_dkms() {
    step "[3/7] Checking camera rotation fix (ipu-bridge)"

    local vendor product
    vendor=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)
    product=$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)

    local needed=false
    if [[ "$vendor" == "SAMSUNG ELECTRONICS CO., LTD." ]]; then
        case "$product" in
            940XFG|940XGK|960XFG|960XFH|960XGK|960XGL|960QFG|960QGK) needed=true ;;
        esac
    fi

    if ! $needed; then
        info "No rotation quirk needed for this model (${product:-unknown})"
        return 0
    fi

    # Already installed?
    if dkms status 2>/dev/null | grep -q "^ipu-bridge-fix/.*installed"; then
        info "ipu-bridge rotation fix already installed via DKMS"
        return 0
    fi

    # Upstream kernel may have gained the quirk in the meantime
    local native
    native=$(find "/lib/modules/$(uname -r)/kernel" -name "ipu-bridge*" 2>/dev/null | head -1)
    if [[ -n "$native" ]]; then
        local decomp="cat"
        case "$native" in *.zst) decomp="zstdcat";; *.xz) decomp="xzcat";; *.gz) decomp="zcat";; esac
        if $decomp "$native" 2>/dev/null | strings | grep -q "$product"; then
            info "Upstream ipu-bridge already carries the $product quirk — no DKMS needed"
            return 0
        fi
    fi

    local src_dir="/usr/src/ipu-bridge-fix-$IPU_BRIDGE_DKMS_VER"
    local repo_dir="$WORK_DIR/webcam-fix-book5/ipu-bridge-fix"
    [[ -f "$repo_dir/ipu-bridge.c" ]] || die "Source not found: $repo_dir/ipu-bridge.c"

    # Supersede any older installed version
    local old
    while IFS= read -r old; do
        [[ -n "$old" ]] && dkms remove "ipu-bridge-fix/$old" --all &>/dev/null || true
    done < <(dkms status 2>/dev/null | awk -F'[/,: ]+' '/^ipu-bridge-fix/ {print $2}' | sort -u)
    rm -rf /usr/src/ipu-bridge-fix-*

    mkdir -p "$src_dir"
    cp -a "$repo_dir"/. "$src_dir/"

    dkms add     "ipu-bridge-fix/$IPU_BRIDGE_DKMS_VER" || die "dkms add failed (ipu-bridge-fix)"
    dkms build   "ipu-bridge-fix/$IPU_BRIDGE_DKMS_VER" || die "dkms build failed (ipu-bridge-fix)"
    dkms install "ipu-bridge-fix/$IPU_BRIDGE_DKMS_VER" || die "dkms install failed (ipu-bridge-fix)"

    info "ipu-bridge rotation fix installed — camera image will be right-side-up"
}

# ── [4] libcamera from source ───────────────────────────────────────────────
build_libcamera() {
    step "[4/7] Building libcamera $LIBCAMERA_BUILD_VER with OV02C10 sensor helper"

    # Arch's packaged libcamera 0.7.x compiles the OV02C10 helper in but the
    # factory registration is dead-code-eliminated at link time, so at runtime
    # IPASoft logs "Failed to create camera sensor helper for ov02c10" and the
    # software AGC falls back to a generic curve — a very dark image. A source
    # build is the only fix on Arch.
    #
    # The helper lives in the IPA module (ipa_soft_simple.so), not in
    # libcamera.so — checking libcamera.so for the symbol finds nothing and
    # would rebuild on every run.
    if ! $SKIP_LIBCAMERA_REBUILD && libcamera_local_present; then
        local ipa_so
        ipa_so=$(find /usr/local/lib* -name "ipa_soft_simple.so" 2>/dev/null | head -1)
        if [[ -n "$ipa_so" ]] && strings "$ipa_so" 2>/dev/null | grep -q "CameraSensorHelperOv02c10"; then
            info "Patched libcamera with the OV02C10 helper already built in /usr/local — skipping rebuild"
            ldconfig
            return 0
        fi
    fi

    if $SKIP_LIBCAMERA_REBUILD; then
        warn "--skip-libcamera-rebuild given — using the system libcamera (image may be dark)"
        return 0
    fi

    # Build against the system Python, not a pyenv/conda shim that lacks deps
    export PATH="/usr/bin:$PATH"

    rm -rf "$LIBCAMERA_BUILD_DIR"
    info "Cloning libcamera $LIBCAMERA_BUILD_VER..."
    git clone --depth 1 --branch "$LIBCAMERA_BUILD_VER" \
        https://git.libcamera.org/libcamera/libcamera.git "$LIBCAMERA_BUILD_DIR" \
        || die "libcamera clone failed"

    cd "$LIBCAMERA_BUILD_DIR" || die "cd failed"

    # ── Patch in the OV02C10 sensor helper ──────────────────────────────────
    local helper=""
    local cand
    for cand in src/ipa/libipa/camera_sensor_helper.cpp \
                src/libcamera/sensor/camera_sensor_helper.cpp; do
        [[ -f "$cand" ]] && { helper="$cand"; break; }
    done
    [[ -n "$helper" ]] || die "Could not locate camera_sensor_helper.cpp in the libcamera tree"

    if ! grep -q "CameraSensorHelperOv02c10" "$helper"; then
        info "Patching $helper"
        if grep -q "namespace ipa" "$helper"; then
            # 0.7.x: helpers live inside namespace ipa { namespace libcamera { }
            sed -i '/#endif.*__DOXYGEN__/i\
class CameraSensorHelperOv02c10 : public CameraSensorHelper\
{\
public:\
\tCameraSensorHelperOv02c10()\
\t{\
\t\tgain_ = AnalogueGainLinear{ 1, 0, 0, 16 };\
\t}\
};\
REGISTER_CAMERA_SENSOR_HELPER("ov02c10", CameraSensorHelperOv02c10)\
' "$helper"
        else
            cat >> "$helper" << 'PATCH_EOF'

class CameraSensorHelperOv02c10 : public CameraSensorHelper
{
public:
	CameraSensorHelperOv02c10()
	{
		gainType_ = AnalogueGainLinear;
		gainConstants_.linear = { 1, 0, 0, 16 };
	}
};
REGISTER_CAMERA_SENSOR_HELPER("ov02c10", CameraSensorHelperOv02c10)
PATCH_EOF
        fi
        grep -q "CameraSensorHelperOv02c10" "$helper" || die "Sensor helper patch did not apply"
        info "OV02C10 sensor helper patched in"
    else
        info "Sensor helper already present"
    fi

    # ── Configure and build ─────────────────────────────────────────────────
    info "Configuring (this takes a minute)..."
    meson setup build \
        -Dprefix=/usr/local \
        -Dpipelines=simple \
        -Dipas=simple \
        -Dgstreamer=enabled \
        -Dv4l2=true \
        -Dcam=enabled \
        -Dqcam=disabled \
        -Dlc-compliance=disabled \
        -Dtracing=disabled \
        -Ddocumentation=disabled \
        -Dpycamera=disabled \
        || die "meson setup failed"

    info "Compiling with $(nproc) jobs (a few minutes)..."
    ninja -C build -j"$(nproc)" || die "ninja build failed"

    # Deliberately no PYTHONPATH manipulation here. Forcing root's site-packages
    # into PYTHONPATH makes Python resolve a stale PyPI `typing` backport
    # (Arch's python-typing package) over the stdlib typing module, and meson
    # dies on Python 3.14 with:
    #     AttributeError: type object 'Callable' has no attribute '_abc_registry'
    # A plain `meson install` uses the distro's own mesonbuild and works.
    meson install -C build || die "meson install failed"

    info "libcamera installed to /usr/local"

    # Make the dynamic linker prefer /usr/local over the distro package.
    # Without this the packaged libcamera (no working helper) wins and the
    # source build is silently ignored.
    if [[ ! -f /etc/ld.so.conf.d/libcamera-local.conf ]]; then
        cat > /etc/ld.so.conf.d/libcamera-local.conf << 'EOF'
# Source-built libcamera with the OV02C10 sensor helper
/usr/local/lib
/usr/local/lib64
/usr/local/lib/x86_64-linux-gnu
/usr/local/lib/aarch64-linux-gnu
EOF
        info "Added /usr/local to the linker search path"
    fi
    ldconfig

    cd / || true
    rm -rf "$LIBCAMERA_BUILD_DIR"
}

# ── [5] Tuning file + environment ───────────────────────────────────────────
configure_environment() {
    step "[5/7] Installing tuning file and environment configuration"

    # ── OV02C10 tuning file for the Simple ISP ──────────────────────────────
    local tuning_src="$WORK_DIR/webcam-fix-libcamera/ov02c10.yaml"
    if [[ -f "$tuning_src" ]]; then
        local d
        for d in /usr/local/share/libcamera/ipa/simple /usr/share/libcamera/ipa/simple; do
            mkdir -p "$d"
            cp "$tuning_src" "$d/ov02c10.yaml"
        done
        info "Installed OV02C10 tuning file"
    else
        warn "ov02c10.yaml not found — the ISP will fall back to uncalibrated.yaml"
    fi

    # ── IPA module path / GStreamer plugin path ─────────────────────────────
    # libcamera >= 0.7 puts IPA modules in <libdir>/libcamera/ipa
    local ipa_dir="" libdir=""
    local d
    for d in /usr/local/lib/libcamera /usr/local/lib64/libcamera \
             /usr/local/lib/x86_64-linux-gnu/libcamera; do
        [[ -d "$d" ]] || continue
        local sub
        for sub in "$d/ipa" "$d"; do
            if ls "$sub"/ipa_*.so >/dev/null 2>&1; then
                ipa_dir="$sub"; libdir="$(dirname "$d")"; break 2
            fi
        done
    done

    if [[ -n "$ipa_dir" ]]; then
        local gst_dir="$libdir/gstreamer-1.0"
        mkdir -p /etc/environment.d
        {
            echo "# libcamera IPA module path (source-built libcamera)"
            echo "LIBCAMERA_IPA_MODULE_PATH=$ipa_dir"
            [[ -d "$gst_dir" ]] && echo "GST_PLUGIN_PATH=$gst_dir"
        } > /etc/environment.d/libcamera-ipa.conf

        {
            echo "# libcamera IPA module path (source-built libcamera)"
            echo "export LIBCAMERA_IPA_MODULE_PATH=$ipa_dir"
            [[ -d "$gst_dir" ]] && echo "export GST_PLUGIN_PATH=$gst_dir"
        } > /etc/profile.d/libcamera-ipa.sh

        export LIBCAMERA_IPA_MODULE_PATH="$ipa_dir"
        info "IPA module path set: $ipa_dir"
        [[ -d "$gst_dir" ]] && info "GStreamer plugin path set: $gst_dir"
    else
        warn "Could not locate IPA modules under /usr/local — camera may not initialise"
    fi

    # ── Groups ──────────────────────────────────────────────────────────────
    # video: general V4L2 access. kvm: /dev/udmabuf, which libcamera's software
    # ISP needs because /dev/dma_heap/system is root-only on Arch — without it
    # the GPU debayer cannot import its buffers and frames come out black.
    local g
    for g in video kvm; do
        if getent group "$g" >/dev/null 2>&1; then
            if id -nG "$TARGET_USER" | grep -qw "$g"; then
                info "$TARGET_USER already in group '$g'"
            else
                usermod -aG "$g" "$TARGET_USER"
                info "Added $TARGET_USER to group '$g' (effective after reboot)"
            fi
        fi
    done
}

# ── [6] Hide raw IPU6 MC nodes ──────────────────────────────────────────────
hide_raw_nodes() {
    step "[6/7] Hiding raw IPU6 media-controller nodes"

    local src="$WORK_DIR/camera-relay"
    [[ -d "$src" ]] || { warn "camera-relay source missing — skipping"; return 0; }

    # The ISYS driver registers one capture node per stream (48 on a Book4),
    # each flagged V4L2_CAP_IO_MC — usable only after userspace configures the
    # media graph, never as a standalone camera. Nothing carries that bit into
    # udev, so they all advertise as cameras. Move them into a memberless group
    # and strip the session ACL.
    mkdir -p /usr/local/lib/sysusers.d
    cat > /usr/local/lib/sysusers.d/camera-relay.conf << 'EOF'
# Owns the raw MC-centric camera nodes. Deliberately memberless: the relay
# pipeline acquires it through the setgid launcher, nothing else should hold it.
g camera-relay -
EOF
    command -v systemd-sysusers >/dev/null 2>&1 && systemd-sysusers >/dev/null 2>&1
    getent group camera-relay >/dev/null 2>&1 || groupadd -r camera-relay
    info "Group 'camera-relay' present (memberless by design)"

    # Writable cache for the pipeline's GStreamer registry. It maps elements to
    # .so paths that get dlopen()ed, so it must not be user-writable.
    install -d -m 2770 -o root -g camera-relay /var/cache/camera-relay

    # Order matters: the launcher must exist before the udev rule hands the raw
    # nodes to camera-relay, or nothing can open the camera at all.
    local mc_helper=/usr/local/lib/udev/camera-relay-v4l2-io-mc
    local helper_ok="" launcher_ok=""

    if gcc -O2 -Wall -o /tmp/camera-relay-v4l2-io-mc "$src/v4l2-io-mc.c" 2>/dev/null; then
        install -d -m 755 /usr/local/lib/udev
        install -m 755 /tmp/camera-relay-v4l2-io-mc "$mc_helper"
        rm -f /tmp/camera-relay-v4l2-io-mc
        helper_ok=1
    else
        warn "Failed to build the v4l2-io-mc helper (gcc required)"
    fi

    if [[ -f "$src/camera-relay-gst.c" ]] \
       && gcc -O2 -Wall -o /tmp/camera-relay-gst "$src/camera-relay-gst.c" 2>/dev/null; then
        install -o root -g camera-relay -m 755 /tmp/camera-relay-gst /usr/local/bin/camera-relay-gst
        # chgrp clears S_ISGID, so set it after the group change or the launcher
        # silently lands as 0755 and cannot reach the nodes.
        chmod 2755 /usr/local/bin/camera-relay-gst
        rm -f /tmp/camera-relay-gst
        launcher_ok=1
        info "Installed /usr/local/bin/camera-relay-gst (setgid camera-relay)"
    else
        warn "Failed to build the pipeline launcher (gcc required)"
    fi

    if [[ -n "$helper_ok" && -n "$launcher_ok" ]]; then
        cat > /etc/udev/rules.d/74-camera-relay-mc-nodes.rules << 'EOF'
# Raw MC-centric V4L2 nodes are not standalone cameras. Keyed off the kernel's
# own V4L2_CAP_IO_MC rather than a driver-specific card name, so this covers
# IPU6, IPU7 and anything else media-controller based.
#
# The 74- prefix is load-bearing, pinned by three stock rule files:
#   60-persistent-v4l.rules  runs v4l_id, which sets the properties cleared below
#   73-seat-late.rules       queues RUN{builtin}+="uaccess", the session ACL
#   95-cd-devices.rules      hands anything with ID_V4L_PRODUCT to colord
#
# TAG-="uaccess" alone does not work: 70-uaccess.rules tags every video4linux
# device unconditionally and the TAG== test in 73 matches the sticky tag list,
# which TAG-= does not touch. Stripping the ACL afterwards is reliable, because
# RUN entries execute in the order rules added them.
ACTION=="remove", GOTO="camera_relay_mc_end"
SUBSYSTEM!="video4linux", GOTO="camera_relay_mc_end"

KERNEL=="video*", ENV{ID_V4L_IO_MC}=="", \
  IMPORT{program}="/usr/local/lib/udev/camera-relay-v4l2-io-mc $devnode"

ENV{ID_V4L_IO_MC}=="1", GROUP="camera-relay", MODE="0660", TAG-="uaccess", \
  ENV{ID_V4L_CAPABILITIES}="", ENV{ID_V4L_PRODUCT}="", \
  RUN+="/usr/bin/setfacl -b $devnode"

LABEL="camera_relay_mc_end"
EOF
        rm -f /etc/udev/rules.d/90-hide-ipu6-v4l2.rules \
              /etc/udev/rules.d/90-camera-relay-mc-nodes.rules \
              /etc/udev/rules.d/72-camera-relay-mc-nodes.rules
        [[ -x /usr/bin/setfacl ]] || warn "setfacl missing — raw nodes stay visible in app pickers"
        udevadm control --reload-rules
        udevadm trigger --action=change --subsystem-match=video4linux
        info "Raw MC-centric nodes reassigned to the camera-relay group"
    else
        warn "Skipping the MC-node rule — helpers did not build, nodes left untouched"
    fi
}

# ── [7] Camera relay ────────────────────────────────────────────────────────
install_camera_relay() {
    step "[7/7] Installing on-demand camera relay"

    local src="$WORK_DIR/camera-relay"
    [[ -d "$src" ]] || { warn "camera-relay source missing — skipping"; return 0; }

    # ── v4l2loopback ────────────────────────────────────────────────────────
    if ! modinfo v4l2loopback &>/dev/null; then
        dkms autoinstall v4l2loopback &>/dev/null || true
    fi
    if modinfo v4l2loopback &>/dev/null; then
        cp "$src/99-camera-relay-loopback.conf" /etc/modprobe.d/
        echo "v4l2loopback" > /etc/modules-load.d/v4l2loopback.conf
        info "v4l2loopback configured (card label 'Camera Relay', autoload on boot)"

        # Reload if it came up with a stale label (e.g. OBS Virtual Camera)
        if lsmod | grep -q v4l2loopback; then
            local lbl
            lbl=$(cat /sys/devices/virtual/video4linux/video*/name 2>/dev/null | grep -v "Intel IPU" | head -1)
            if [[ -n "$lbl" && "$lbl" != "Camera Relay" ]]; then
                modprobe -r v4l2loopback 2>/dev/null || true
                modprobe v4l2loopback 2>/dev/null || true
                info "Reloaded v4l2loopback with the correct label"
            fi
        fi

        cat > /etc/udev/rules.d/70-camera-relay-capabilities.rules << 'EOF'
# Normalise ID_V4L_CAPABILITIES for the Camera Relay loopback: v4l_id tags the
# node before any capture format is negotiated, so the property can come up
# without ":capture:". Runs after 60-persistent-v4l.
SUBSYSTEM=="video4linux", ATTR{name}=="Camera Relay", ENV{ID_V4L_CAPABILITIES}=":capture:"
EOF
        udevadm control --reload-rules
        udevadm trigger --action=change --subsystem-match=video4linux
    else
        warn "v4l2loopback unavailable — non-PipeWire apps will not see the camera"
    fi

    # ── GStreamer libcamerasrc ──────────────────────────────────────────────
    if gst-inspect-1.0 libcamerasrc &>/dev/null; then
        info "GStreamer 'libcamerasrc' element available"
    else
        warn "libcamerasrc not loadable — the relay pipeline will not start"
        warn "  check: gst-inspect-1.0 --gst-debug=2 libcamerasrc 2>&1 | tail -20"
    fi

    # ── Binaries ────────────────────────────────────────────────────────────
    if [[ -f "$src/camera-relay-monitor.c" ]] \
       && gcc -O2 -Wall -o /tmp/camera-relay-monitor "$src/camera-relay-monitor.c"; then
        pgrep -x camera-relay-monitor >/dev/null 2>&1 && {
            run_as_user systemctl --user stop camera-relay.service 2>/dev/null || true
            pkill -x camera-relay-monitor 2>/dev/null || true
            sleep 1
        }
        install -m 755 /tmp/camera-relay-monitor /opt/blackarch/bin/camera-relay-monitor
        rm -f /tmp/camera-relay-monitor
        info "Installed /opt/blackarch/bin/camera-relay-monitor (on-demand watcher)"
    else
        warn "Failed to build the on-demand monitor (gcc required)"
    fi

    install -m 755 "$src/camera-relay" /usr/local/bin/camera-relay
    info "Installed /usr/local/bin/camera-relay"

    if [[ -f "$src/chromium-pipewire-camera.sh" ]]; then
        install -m 755 "$src/chromium-pipewire-camera.sh" /usr/local/bin/chromium-pipewire-camera
        info "Installed /usr/local/bin/chromium-pipewire-camera"
    fi

    # ── Systray ─────────────────────────────────────────────────────────────
    mkdir -p /usr/local/share/camera-relay
    install -m 755 "$src/camera-relay-systray.py" /usr/local/share/camera-relay/
    install -m 644 "$src/camera-relay-systray.desktop" /usr/share/applications/
    install -D -m 644 "$src/camera-relay-systray.desktop" /etc/xdg/autostart/camera-relay-systray.desktop
    info "Installed systray applet and autostart entry"

    if [[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]]; then
        local icon_dest="$TARGET_HOME/.local/share/icons/hicolor/symbolic/apps"
        mkdir -p "$icon_dest"
        local icon
        for icon in camera-disabled-symbolic camera-switch-symbolic camera-video-symbolic; do
            [[ -f "$src/yaru-icons/$icon.svg" ]] && \
                install -m 644 "$src/yaru-icons/$icon.svg" "$icon_dest/" && \
                info "Installed ${icon}.svg"
        done
        chown -R "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/icons"
        run_as_user gtk-update-icon-cache -f -t "$TARGET_HOME/.local/share/icons/hicolor" 2>/dev/null || true
    fi

    # ── Enable the on-demand relay (user unit) ──────────────────────────────
    if run_as_user /usr/local/bin/camera-relay enable-persistent --yes; then
        info "On-demand relay enabled — starts at login, near-zero idle CPU"
    else
        warn "Could not enable the relay now — run 'camera-relay enable-persistent' after reboot"
    fi

    # ── Chromium-family browsers ────────────────────────────────────────────
    # Chrome/Brave/Edge/Electron only accept a V4L2 node reporting VIDEO_CAPTURE
    # and *not* VIDEO_OUTPUT; the relay under exclusive_caps=0 reports both, so
    # they list zero cameras. Point them at PipeWire instead.
    if [[ -x "$src/chromium-pipewire-camera.sh" ]]; then
        "$src/chromium-pipewire-camera.sh" enable 2>/dev/null || true
    fi
}

# ── Uninstall ───────────────────────────────────────────────────────────────
uninstall() {
    step "Uninstalling the camera fix"

    run_as_user systemctl --user disable --now camera-relay.service 2>/dev/null || true
    pkill -x camera-relay-monitor 2>/dev/null || true

    dkms remove "ov02c10/$OV02C10_DKMS_VER" --all &>/dev/null || true
    rm -rf "/usr/src/ov02c10-$OV02C10_DKMS_VER"

    local old
    while IFS= read -r old; do
        [[ -n "$old" ]] && dkms remove "ipu-bridge-fix/$old" --all &>/dev/null || true
    done < <(dkms status 2>/dev/null | awk -F'[/,: ]+' '/^ipu-bridge-fix/ {print $2}' | sort -u)
    rm -rf /usr/src/ipu-bridge-fix-*

    # Restore any clk_freq modprobe.d backups this script made
    local b
    for b in /etc/modprobe.d/*.ov02c10-26mhz.bak; do
        [[ -f "$b" ]] && mv -f "$b" "${b%.ov02c10-26mhz.bak}"
    done

    rm -f /etc/ld.so.conf.d/libcamera-local.conf
    rm -rf /usr/local/lib/libcamera /usr/local/lib64/libcamera \
           /usr/local/lib/x86_64-linux-gnu/libcamera
    rm -f /usr/local/lib/libcamera.so* /usr/local/lib64/libcamera.so* \
          /usr/local/lib/x86_64-linux-gnu/libcamera.so*
    rm -rf /usr/local/share/libcamera /usr/local/bin/cam
    rm -f /usr/local/lib/gstreamer-1.0/libgstlibcamera.so
    ldconfig

    rm -f /etc/environment.d/libcamera-ipa.conf /etc/profile.d/libcamera-ipa.sh \
          /usr/share/libcamera/ipa/simple/ov02c10.yaml \
          /usr/local/share/libcamera/ipa/simple/ov02c10.yaml

    rm -f /usr/local/bin/camera-relay /opt/blackarch/bin/camera-relay-monitor \
          /usr/local/bin/camera-relay-gst /usr/local/bin/chromium-pipewire-camera
    rm -rf /usr/local/share/camera-relay /var/cache/camera-relay
    rm -f /usr/share/applications/camera-relay-systray.desktop \
          /etc/xdg/autostart/camera-relay-systray.desktop
    rm -f /usr/local/lib/sysusers.d/camera-relay.conf \
          /usr/local/lib/udev/camera-relay-v4l2-io-mc
    rm -f /etc/udev/rules.d/74-camera-relay-mc-nodes.rules \
          /etc/udev/rules.d/70-camera-relay-capabilities.rules
    rm -f /etc/modprobe.d/99-camera-relay-loopback.conf \
          /etc/modules-load.d/v4l2loopback.conf
    udevadm control --reload-rules 2>/dev/null || true

    depmod -a "$(uname -r)" 2>/dev/null || true
    if command -v limine-mkinitcpio >/dev/null 2>&1; then
        limine-mkinitcpio
    elif [[ -n "$(ls /etc/mkinitcpio.d/*.preset 2>/dev/null)" ]]; then
        mkinitcpio -P
    elif command -v mkinitcpio >/dev/null 2>&1; then
        for kver in /usr/lib/modules/*/; do
            [[ -f "$kver/modules.builtin" ]] || continue
            mkinitcpio --kernel "${kver%/}" --generate "/boot/initramfs-${kver##*/}.img" 2>/dev/null || true
        done
    fi

    warn "Group memberships (video/kvm) and the camera-relay group were left in place"
    info "Uninstalled — reboot to return to the stock drivers"
}

# ── Verify ──────────────────────────────────────────────────────────────────
verify() {
    step "Verifying"

    local ok=true

    ov02c10_is_patched \
        && info "Patched ov02c10 active: $(ov02c10_module_path)" \
        || { warn "ov02c10 still resolves to the stock module — reboot required"; ok=false; }

    if sensor_probed; then
        info "Sensor probed (26 MHz clock accepted)"
    elif clock_error_present; then
        warn "26 MHz rejection still in dmesg — reboot required"; ok=false
    fi

    # The source build must actually win over the distro package. Compare the
    # full soname (libcamera.so.0.7), not a truncated "libcamera.so.0" — the
    # latter matches nothing and reports a false failure.
    if libcamera_local_present; then
        local lc
        lc=$(ldconfig -p 2>/dev/null | awk '/libcamera\.so\.0\.[0-9]+ /{print $NF; exit}')
        if [[ "$lc" == /usr/local/* ]]; then
            info "Linker resolves libcamera from $lc (patched build)"
        else
            warn "Linker resolves libcamera from ${lc:-<none>} — the patch may not be in use"; ok=false
        fi
    fi

    # This is the check that proves the helper is really registered. The helper
    # lives in the IPA module, so grep there — libcamera.so never has it.
    if command -v cam &>/dev/null; then
        local cam_out
        cam_out=$(cam -l 2>&1)
        if echo "$cam_out" | grep -q "Internal"; then
            info "libcamera lists the internal camera"
        else
            warn "libcamera lists no internal camera — reboot and re-check"; ok=false
        fi
        if echo "$cam_out" | grep -q "Failed to create camera sensor helper"; then
            warn "OV02C10 sensor helper still not registered — the source build is not in use"; ok=false
        else
            info "OV02C10 sensor helper registered (auto-exposure will work)"
        fi
    fi

    if gst-inspect-1.0 libcamerasrc &>/dev/null; then
        info "GStreamer 'libcamerasrc' available (relay pipeline)"
    else
        warn "libcamerasrc not loadable — non-PipeWire apps will not see the camera"; ok=false
    fi

    if modinfo v4l2loopback &>/dev/null; then
        info "v4l2loopback available"
    else
        warn "v4l2loopback missing — the relay has no device to write into"; ok=false
    fi

    if $ok; then
        echo
        info "All checks passed."
    else
        echo
        warn "Some checks are pending a reboot — re-run with --check-only afterwards."
    fi

    echo
    echo "  ${C_DIM}Next:${C_RST}"
    echo "    sudo reboot"
    echo "    sudo bash $0 --check-only"
    echo
    echo "  ${C_DIM}Test after reboot:${C_RST}"
    echo "    cam -l                                    # libcamera should list the camera"
    echo "    gst-launch-1.0 libcamerasrc ! videoconvert ! autovideosink"
    echo "    camera-relay doctor                       # relay / GPU / EGL diagnostics"
    echo
}

# ── Main ────────────────────────────────────────────────────────────────────
echo "${C_BLU}=================================================${C_RST}"
echo "${C_BLU}  Galaxy Book Camera Fix — IPU6 / OV02C10${C_RST}"
echo "${C_BLU}=================================================${C_RST}"
echo "  Host     : $(cat /sys/class/dmi/id/product_name 2>/dev/null || echo unknown)"
echo "  Kernel   : $(uname -r)"
echo "  User     : $TARGET_USER"
echo "  Mode     : $MODE"

case "$MODE" in
    check)
        check_status
        exit 0
        ;;
    uninstall)
        uninstall
        exit 0
        ;;
esac

# Fetch the upstream fix sources
step "Fetching upstream fix sources"
rm -rf "$WORK_DIR"
if ! curl -fsSL "$FIX_URL" | tar xz -C /tmp/; then
    die "Could not download the fix sources from GitHub"
fi
[[ -d "$WORK_DIR" ]] || die "Extracted tree not found at $WORK_DIR"
info "Sources ready in $WORK_DIR"

install_packages
install_ov02c10_dkms

if [[ "$MODE" == "sensor-only" ]]; then
    step "Sensor-only mode — skipping the userspace stack"
    if command -v limine-mkinitcpio >/dev/null 2>&1; then
        limine-mkinitcpio
    elif [[ -n "$(ls /etc/mkinitcpio.d/*.preset 2>/dev/null)" ]]; then
        mkinitcpio -P
    elif command -v mkinitcpio >/dev/null 2>&1; then
        for kver in /usr/lib/modules/*/; do
            [[ -f "$kver/modules.builtin" ]] || continue
            mkinitcpio --kernel "${kver%/}" --generate "/boot/initramfs-${kver##*/}.img" 2>/dev/null || true
        done
    fi
    verify
    exit 0
fi

install_ipu_bridge_dkms
build_libcamera
configure_environment
hide_raw_nodes
install_camera_relay

# initramfs once, now that both DKMS modules are in place
step "Rebuilding initramfs"
if command -v limine-mkinitcpio >/dev/null 2>&1; then
    limine-mkinitcpio && info "initramfs rebuilt"
elif [[ -n "$(ls /etc/mkinitcpio.d/*.preset 2>/dev/null)" ]]; then
    mkinitcpio -P && info "initramfs rebuilt"
elif command -v mkinitcpio >/dev/null 2>&1; then
    rebuilt=false
    for kver in /usr/lib/modules/*/; do
        [[ -f "$kver/modules.builtin" ]] || continue
        mkinitcpio --kernel "${kver%/}" --generate "/boot/initramfs-${kver##*/}.img" && rebuilt=true
    done
    $rebuilt && info "initramfs rebuilt"
elif command -v dracut >/dev/null 2>&1; then
    dracut --force && info "initramfs rebuilt"
else
    warn "No initramfs tool found — rebuild manually before rebooting"
fi

# Restart PipeWire so it picks up the new libcamera SPA plugin
step "Restarting PipeWire"
if run_as_user systemctl --user restart pipewire wireplumber; then
    sleep 3
    info "PipeWire restarted"
else
    warn "Could not restart the user PipeWire session — a reboot will apply it"
fi

verify
