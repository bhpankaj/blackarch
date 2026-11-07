-- Keep only your personal keybinding overrides here. Add new bindings or
-- unbind defaults before replacing them.

-- See current bindings and descriptions:
--   blackarch menu keybindings --print

-- To disable every Blackarch default binding, set this in
-- ~/.config/hypr/hyprland.lua before require("default.hypr.blackarch"), then add
-- only the bindings you want below:
--   blackarch_default_bindings = false

-- To disable all preinstalled app/webapp bindings, set:
--   blackarch_preinstalled_bindings = false

-- Add a new binding.
-- o.bind("SUPER + SHIFT + R", "SSH", "alacritty -e ssh your-server")

-- Change an existing binding by unbinding it first, then binding the key again.
-- This example changes SUPER+SPACE from the launcher to the Blackarch root menu.
-- hl.unbind("SUPER + SPACE")
-- o.bind("SUPER + SPACE", "Blackarch menu", "blackarch-menu toggle root")

-- Disable a default binding without replacing it.
-- hl.unbind("SUPER + SHIFT + B")

-- Logitech MX Keys examples:
-- o.bind("SUPER + SHIFT + S", nil, "blackarch-capture-screenshot")
-- o.bind("SUPER + H", nil, "voxtype record toggle")
-- o.bind("SUPER + PERIOD", nil, "blackarch-shell shell toggle blackarch.emojis")
