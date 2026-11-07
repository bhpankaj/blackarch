local config_home = os.getenv("HOME") .. "/.config/hypr"
package.path = package.path .. ";" .. config_home .. "/blackarch/?.lua"
local blackarch = require("blackarch.blackarch")
blackarch.layout.register()
require("blackarch.env")
require("blackarch.startup")
require("blackarch.input")
require("blackarch.monitor")
require("blackarch.looknfeel")
require("blackarch.rules")
require("blackarch.binding_utilities")
require("blackarch.binding_tiling")
require("blackarch.binding_office")
require("blackarch.binding_hacking")
