local Binder = require("blackarch.blackarch_binder")
local vars = require("blackarch.variables")

Binder.add(vars.mainMod .. " + A", { desc = "Launch AVD|VDI in work profile" }, "blackarch work https://windows.cloud.microsoft/?navFrom=avdweb#/devices" )
Binder.add(vars.mainMod .. " + SHIFT + O", { desc = "Launch outlook in work profile" }, "blackarch work https://outlook.office.com/mail/" )
Binder.add(vars.mainMod .. " + T", { desc = "Launch teams app" }, "blackarch gui  teams-for-linux" )
Binder.add(vars.mainMod .. " + SHIFT + T", { desc = "Launch teams in work profile" }, "blackarch work https://teams.cloud.microsoft/" )
-- Binder.add(vars.mainMod .. " + CTRL + U", { desc = "Launch Browser with work profile" }, "blackarch work" )
-- Binder.add(vars.mainMod .. " + T", { desc = "Launch teams-for-linux" }, "blackarch execute-gui-tools  teams-for-linux" )
