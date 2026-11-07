-- Re-apply a persisted input-device disable on every config load.
--
-- blackarch-toggle-input-device writes the disabled device's name to
-- ~/.local/state/blackarch/toggles/hypr/<kind>-disabled-name. hl.device()'s
-- enabled=false is runtime state only: a reload (or a relogin) re-adds every
-- device enabled, so without this the toggle silently re-enables the device the
-- next time the config is evaluated.
--
-- The name is read as data and passed to hl.device as a literal — it is never
-- loaded as Lua, because it comes from USB descriptors.
--
-- This module is loaded from input.lua, which hyprland.lua requires on every
-- eval, so it runs on both start and reload.

local home = os.getenv("HOME") or ""

--- The path a toggle tool writes the disabled device's name to.
local function name_file(kind)
  -- Hardcoded to ~/.local/state to match blackarch-toggle-input-device and the
  -- sibling toggle tools, which all write there regardless of XDG_STATE_HOME.
  return home .. "/.local/state/blackarch/toggles/hypr/" .. kind .. "-disabled-name"
end

--- Disable one device kind if its name file exists.
local function apply(kind)
  local file = io.open(name_file(kind), "r")
  if not file then
    return
  end

  local name = file:read("*l")
  file:close()

  if name and name ~= "" then
    -- The name is a literal string in the generated source, so it must be
    -- escaped the same way the bash tool escaped it before interpolating.
    local escaped = name:gsub("\\", "\\\\"):gsub('"', '\\"')
    local source = 'return hl.device({ name = "' .. escaped .. '", enabled = false })'
    local chunk = load(source, "=disabled-input-device", "t")
    if chunk then
      chunk()
    end
  end
end

apply("touchpad")
apply("touchscreen")
