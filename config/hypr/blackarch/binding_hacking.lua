local vars = require("blackarch.variables")
local Binder = require("blackarch.blackarch_binder")
local Blackarch = require("blackarch.blackarch")

local bracket_binds = {
	{ key = "BracketLeft", direction = "left" },
	{ key = "BracketRight", direction = "right" }
}

for _, bind in ipairs(bracket_binds) do
Binder.add(vars.ralt .. " + " .. bind.key, { desc = "Move focus to" .. bind.direction }, Blackarch.helper.by_layout({
				{ layout = "lua:blackarch", dispatcher = hl.dsp.focus({ direction = bind.direction }) },
				{ layout = "dwindle", dispatcher = hl.dsp.focus({ direction = bind.direction }) },
				{ layout = "monocle", dispatcher =  hl.dsp.layout("cyclenext")},-- hl.dsp.focus({ direction = bind.direction }) },
        { layout = "master",  dispatcher = hl.dsp.focus({ direction = bind.direction }) },
				{	layout = "scrolling", dispatcher = hl.dsp.focus({ direction = bind.direction }) },
      }))
end

Binder.add(vars.rctl .. " + BracketLeft", { desc = "Move previous in grouped window" }, hl.dsp.group.prev())
Binder.add(vars.rctl .. " + BracketRight", { desc = "Move next in grouped window" }, hl.dsp.group.next())

Binder.add(vars.ralt .. " + P", { desc = "Launch Powershell" }, "blackarch tui pwsh" )
Binder.add(vars.rctl .. " + P", { desc = "Launch Powershell with ROOT" }, "blackarch pwsh" )

Binder.add(vars.ralt .. " + RETURN", { desc = "Launch Kitty" }, "blackarch gui kitty" )
Binder.add(vars.rctl .. " + RETURN", { desc = "Launch Kitty with ROOT" }, "blackarch execute" )

