-- $BLACKARCH_PATH is the single knob: every context (Hyprland's own exec_cmd,
-- the shells, and every app the compositor spawns) derives its PATH from it, so
-- changing it here is enough to move the whole system to another tree.
local blackarch_path = os.getenv("BLACKARCH_PATH") or "/opt/blackarch/"
-- Normalise trailing slashes: BLACKARCH_PATH="/opt/blackarch/" must yield
-- "/opt/blackarch/bin", not "/opt/blackarch//bin".
blackarch_path = blackarch_path:gsub("/+$", "")
hl.env("BLACKARCH_PATH", blackarch_path .. "/")

local bin_dir = blackarch_path .. "/bin"

-- Prepend $BLACKARCH_PATH/bin unless it is already on PATH, so a stale or
-- duplicated entry cannot shadow the directory this session actually uses.
local current_path = os.getenv("PATH") or ""
local present = false
for entry in current_path:gmatch("[^:]+") do
  if entry == bin_dir then
    present = true
    break
  end
end
if not present then
  hl.env("PATH", bin_dir .. ":" .. current_path)
end

-- Force all apps to use Wayland.
hl.env("GDK_SCALE", "1")
hl.env("XDG_CURRENT_DESKTOP", "Hyprland")
hl.env("MOZ_ENABLE_WAYLAND", "1")
hl.env("ELECTRON_OZONE_PLATFORM_HINT", "wayland")
hl.env("OZONE_PLATFORM", "wayland")
hl.env("XDG_SESSION_TYPE", "wayland")
hl.env("GTK_THEME", "Matrix-Dark")
hl.env("QT_QPA_PLATFORM", "wayland;xcb")
hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")
hl.env("QT_STYLE_OVERRIDE", "kvantum-dark")
hl.env("QT_SCALE_FACTOR", "1.25")

-- Cursor size.
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")

-- Allow better support for screen sharing (Google Meet, Discord, etc).
hl.env("XDG_CURRENT_DESKTOP", "Hyprland")
hl.env("XDG_SESSION_DESKTOP", "Hyprland")

hl.config({
	xwayland = {
		force_zero_scaling = true,
	},

	ecosystem = {
		no_update_news = true,
	},
})
