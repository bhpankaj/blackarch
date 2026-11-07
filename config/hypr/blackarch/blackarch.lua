---@class HL.Custom
---@field dsp HL.Custom.DspNamespace
---@field helper HL.Custom.HelperNamespace
---@field layout HL.Custom.LayoutNamespace
---@type HL.Custom
local M = {
	dsp = require("blackarch.blackarch_dispatcher"),
	helper = require("blackarch.blackarch_helper"),
	layout = require("blackarch.blackarch_layout"),
}

return M
