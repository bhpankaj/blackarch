local vars = {}
local Binder = require("blackarch.blackarch_binder")

-- Grab the command used to launch the session
local hypr_cmd = os.getenv("HYPRLAND_CMD") or ""
local system_family = Binder.system_family()

vars.lalt = "MOD1"-- left_alt   -> MOD1
vars.numlock = "MOD2"-- num_lock   -> MOD2
vars.rctl = "MOD3"-- right_ctrl -> MOD3
vars.super = "MOD4"-- SUPER      -> MOD4
vars.ralt = "MOD5"-- right_alt  -> MOD5

if hypr_cmd:match("hyprland%.lua") or  system_family:match("Virtual Machine") then
    vars.mainMod = vars.numlock
else
    vars.mainMod = vars.super
end

return vars
