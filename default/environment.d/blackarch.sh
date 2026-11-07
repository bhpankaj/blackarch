: "${BLACKARCH_PATH:=/opt/blackarch/}"
# Strip trailing slashes so "$BLACKARCH_PATH/bin" never becomes "//bin".
BLACKARCH_PATH="${BLACKARCH_PATH%/}"

case ":${PATH}:" in
  *":${BLACKARCH_PATH}/bin:"*) ;;
  *) [ -d "${BLACKARCH_PATH}/bin" ] && PATH="${BLACKARCH_PATH}/bin:${PATH}" ;;
esac

export BLACKARCH_PATH PATH
# Source this file for non-interactive shells too (SSH, cron, bash, zsh).
export BASH_ENV=/etc/profile.d/blackarch.sh
export ENV=/etc/profile.d/blackarch.sh

waylandsudo() {
    local uid
    uid=$(id -u)
    sudo /usr/bin/env \
        XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}" \
        DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$uid/bus}" \
        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}" \
        HYPRLAND_INSTANCE_SIGNATURE="${HYPRLAND_INSTANCE_SIGNATURE}" \
        BLACKARCH_PATH="${BLACKARCH_PATH}" \
        "$@"
}
