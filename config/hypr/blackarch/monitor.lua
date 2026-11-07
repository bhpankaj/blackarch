local monitor_output = "eDP-1"
local touch_input = "gxtp7936:00-27c6:0123"
local touch_style = "wcom016a:00-2d1f:0185-stylus"
-- The touchscreen's enabled state is owned by the toggle tools, which persist it
-- as the presence of ~/.local/state/blackarch/toggles/hypr/touchscreen-disabled-name.
-- Derived here rather than hardcoded so a toggle survives every config eval, and
-- so the file's absence means enabled (the toggle's own semantics: the file is
-- written on disable and removed on enable).
local touch_enabled = 0
local touchscreen_disabled = io.open(
  (os.getenv("HOME") or "") .. "/.local/state/blackarch/toggles/hypr/touchscreen-disabled-name",
  "r"
)
if touchscreen_disabled then
  touchscreen_disabled:close()
  touch_enabled = 0
end
local monitor_mode = "preferred"
local monitor_position = "auto"
local monitor_scale = 1.25
local monitor_transform = 0
-- Default Monitor configuration
hl.monitor({
	output = "",
	mode = "preferred",
	position = "auto",
	scale = "1",
})
-- # Touch Mapping
hl.device ({
  name = touch_input,
  output = monitor_output,
	transform = monitor_transform,
  enabled = touch_enabled
})

-- # Stylus Mapping
hl.device ({
  name = touch_style,
  output = monitor_output,
	transform = monitor_transform,
})
-- Transform for inbuild screen
hl.monitor({
	output = monitor_output,
	mode = monitor_mode,
	position = monitor_position,
	scale = monitor_scale,
	transform = monitor_transform,
})
