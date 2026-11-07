-- Blackarch Hyprland setup: helpers, defaults, and current theme overrides.

require("blackarch.blackarch_helpers")
local require_optional = require("blackarch.require_optional")

-- Use Blackarch defaults, but don't edit these directly.
-- require("blackarch.autostart")
if _G.blackarch_default_bindings ~= false then
  -- require("blackarch.bindings.media")
  -- require("blackarch.bindings.clipboard")
  -- require("blackarch.bindings.tiling")
  -- require("blackarch.bindings.utilities")
  require("blackarch.bindings.voxtype")
  require_optional.module("blackarch.bindings.applications")
end
-- require("blackarch.envs")
-- require("blackarch.looknfeel")
-- require("blackarch.input")
-- require("blackarch.windows")
--
-- -- Current theme overrides.
-- require_optional.module("blackarch.current.theme.hyprland")
