local vars = require("blackarch.variables")
local Binder = require("blackarch.blackarch_binder")
local Blackarch = require("blackarch.blackarch")
-- require("blackarch.binding_submap")

local hjkl_binds = {
	{ key = "H", direction = "left" },
	{ key = "J", direction = "down" },
	{ key = "K", direction = "up" },
	{ key = "L", direction = "right"},
}

for _, bind in ipairs(hjkl_binds) do
  Binder.add(vars.mainMod .. " + ALT + " .. bind.key, { desc = "Swap window or move workspace to monitor " .. bind.direction }, function()
          local monitors = hl.get_monitors()
          if monitors ~= nil and #monitors > 1 then
                  hl.dispatch(hl.dsp.workspace.move({ monitor = bind.direction }))
          else
                  hl.dispatch(hl.dsp.window.swap({ direction = bind.direction }))
          end
  end)
	Binder.add(vars.mainMod .. " + " .. bind.key, { desc = "Move focus to" .. bind.direction }, Blackarch.helper.by_layout({
				{ layout = "lua:blackarch", dispatcher = hl.dsp.focus({ direction = bind.direction }) },
				{ layout = "dwindle", dispatcher = hl.dsp.focus({ direction = bind.direction }) },
				{ layout = "monocle", dispatcher =  hl.dsp.layout("cyclenext")},-- hl.dsp.focus({ direction = bind.direction }) },
        { layout = "master",  dispatcher = hl.dsp.focus({ direction = bind.direction }) },
				{	layout = "scrolling", dispatcher = hl.dsp.focus({ direction = bind.direction }) },
      }))
	Binder.add(vars.mainMod .. " + CTRL + " .. bind.key, { desc = "Swap or cycle_next window to " .. bind.direction }, Blackarch.helper.by_layout({
				{ layout = "lua:blackarch", dispatcher = hl.dsp.window.swap({ direction = bind.direction }) },
				{ layout = "dwindle", dispatcher = hl.dsp.window.swap({ direction = bind.direction }) },
				{ layout = "monocle", dispatcher =  hl.dsp.layout("cyclenext")},-- hl.dsp.focus({ direction = bind.direction }) },
        { layout = "master",  dispatcher = hl.dsp.window.swap({ direction = bind.direction }) },
				{	layout = "scrolling", dispatcher = function()
						local fn
						if bind.direction == "left" or bind.direction == "right" then
							fn = hl.dsp.layout("swapcol " .. (bind.direction == "left" and "l" or "r"))
						else
							fn = hl.dsp.window.swap({ direction = bind.direction })
						end
						hl.dispatch(fn)
					end, },}))
  Binder.add(vars.mainMod .. " + SHIFT + " .. bind.key, { desc = "Move window into_group on" .. bind.direction  },  hl.dsp.window.move({ into_group = bind.direction }))
	end

	---- Group Management

Binder.add(vars.mainMod .. " + G", { desc = "Toggle grouped" }, hl.dsp.group.toggle())
Binder.add(vars.mainMod .. " + SHIFT + G", { desc = "Move window out_of_group to right" }, hl.dsp.window.move({  out_of_group = "right"  }))

Binder.add(vars.mainMod .. " + ALT + BracketRight", { desc = "Next Layout" }, Blackarch.dsp.next_layout())
Binder.add(vars.mainMod .. " + ALT + BracketLeft", { desc = "Previous Layout" }, Blackarch.dsp.prev_layout())

Binder.add(vars.mainMod .. " + BracketLeft", { desc = "Move previous in grouped window" }, hl.dsp.group.prev())
Binder.add(vars.mainMod .. " + BracketRight", { desc = "Move next in grouped window" }, hl.dsp.group.next())

Binder.add(vars.mainMod .. " + SHIFT + BracketLeft", { desc = "Focus on previous window"}, hl.dsp.window.cycle_next({ next = false }))
Binder.add(vars.mainMod .. " + SHIFT + BracketRight", { desc = "Focus on next window"}, hl.dsp.window.cycle_next())

Binder.add(vars.mainMod .. " + CTRL + BracketRight", { desc =  "Next workspace"}, hl.dsp.focus({ workspace = "next" }))
Binder.add(vars.mainMod .. " + CTRL + BracketLeft", { desc =  "Previous workspace"}, hl.dsp.focus({ workspace = "previous" }))

	-- Window Size increase or decrease
Binder.add( vars.mainMod .. " + equal", { desc = "Resize window to right" },	Blackarch.helper.by_layout({
			{ layout = "dwindle", dispatcher = function() Blackarch.dsp.resize_window(5, 0) end},
			{ layout = "scrolling", dispatcher = function() hl.dsp.layout("colresize +conf") end},
		}),	{ repeating = true })
Binder.add( vars.mainMod .. " + minus", { desc = "Resize window to Left" },	Blackarch.helper.by_layout({
			{ layout = "dwindle", dispatcher = function() Blackarch.dsp.resize_window(-5, 0) end },
			{ layout = "scrolling", dispatcher = function() hl.dsp.layout("colresize -conf") end},
		}),	{ repeating = true })
Binder.add(vars.mainMod .. " + SHIFT + equal", { repeating = true, desc = "Scrolling layout right" }, function() Blackarch.dsp.resize_window(5,0) end)
Binder.add(vars.mainMod .. " + SHIFT + minus", { repeating = true, desc = "Scrolling layout left" }, function() Blackarch.dsp.resize_window(-5,0) end)

Binder.add("SUPER + CTRL + equal", { desc = "Zoom in" }, function()
  local zoom = hl.get_config("cursor.zoom_factor") or 1
  hl.config({ cursor = { zoom_factor = zoom + 1 } })
end)

Binder.add("SUPER + CTRL + minus", { desc = "Reset zoom" }, function()
  hl.config({ cursor = { zoom_factor = 1 } })
end)

	-- Mouse Events
Binder.add(vars.mainMod .. " + mouse:272", { mouse = true, desc = "Drag with Mouse with mainMod" }, hl.dsp.window.drag())
Binder.add(vars.mainMod .. " + mouse:273", { mouse = true, desc = "Resize with Mouse with mainMod" }, hl.dsp.window.resize())
Binder.add("mouse:274", { desc = "Mouse middle click to toggle brightness of screen", locked = true }, hl.dsp.exec_cmd("blackarch brightness toggle"))

  -- Touch Screen events
Binder.add(vars.mainMod .. " + F4", { desc = "Toggle touch screen", locked = true }, hl.dsp.exec_cmd("blackarch-toggle-touchscreen"))

  -- Touchpad events
Binder.add(vars.mainMod .. " + F5", { desc = "Toggle touchpad", locked = true }, hl.dsp.exec_cmd("blackarch-toggle-touchpad"))
Binder.add(vars.mainMod .. " + ALT + F5", { desc = "Stop Virtual Keyboard and Disable Touch-Screen" }, "blackarch toggle virtualkeyboard stop")
Binder.add(vars.mainMod .. " + CTRL + F5", { desc = "Touchscreen Rotation in tablet mode" }, "blackarch toggle virtualkeyboard auto;blackarch shell touchscreen_orientation")
-- Binder.add(vars.mainMod .. " + CTRL + F5", { desc = "Toggle Virtualkeyboard on" }, "blackarch toggle virtualkeyboard auto")

	---- Window Management
	-- DELETE
Binder.add("ALT + F4", { desc = "Kill active window", repeatable = false }, hl.dsp.window.close())
Binder.add(vars.mainMod .. " + DELETE", { desc = "Kill other inactive windows" },hl.dsp.exec_cmd("blackarch-hyprland-window-close-all"))
Binder.add(vars.mainMod .. " + SHIFT + DELETE", { desc = "Exit hyprland" }, hl.dsp.exit())
Binder.add(vars.mainMod .. " + CTRL + DELETE", { desc = "Shutdown" }, hl.dsp.exec_cmd("blackarch-cmd-shutdown"))
Binder.add(vars.mainMod .. " + ALT + DELETE", { desc = "Reboot" }, hl.dsp.exec_cmd("blackarch-cmd-reboot"))

	-- Return
Binder.add(vars.mainMod .. " + ALT + RETURN", { desc = "Center" }, hl.dsp.window.center())
Binder.add(vars.mainMod .. " + SHIFT + RETURN", { desc = "Toggle floating" },hl.dsp.window.float({ action = "toggle" }))
Binder.add(vars.mainMod .. " + CTRL + RETURN", { desc = "toggle maximize active window" },hl.dsp.window.fullscreen({ mode = "maximized" }))
Binder.add(vars.mainMod .. " + SHIFT + CTRL + RETURN", { desc =  "Reveal active window on top"}, hl.dsp.window.bring_to_top())
Binder.add(vars.mainMod .. " + RETURN", { desc = "toggle fullscreen active window" },hl.dsp.window.fullscreen({ mode = "fullscreen" }))

	-- TAB MAPPINGS: Combined for Group and Window Cycling
Binder.add("ALT + TAB", { desc = "Focus to one of the opened window"}, "blackarch focus")
Binder.add(vars.mainMod .. " + TAB", { desc = "Focus on next window"}, hl.dsp.window.cycle_next())
Binder.add(vars.mainMod .. " + SHIFT + TAB", { desc = "Focus on previous window"}, hl.dsp.window.cycle_next({ next = false }))
Binder.add(vars.mainMod .. " + ALT + TAB", { desc = "Switching to next window in the group" }, hl.dsp.group.next())
-- Binder.add(vars.mainMod .. " + ALT + TAB", { desc =  "Reveal active window on top"}, hl.dsp.window.bring_to_top())
Binder.add(vars.mainMod .. " + ALT + SHIFT + TAB", { desc = "Switching to previous window in the group" },hl.dsp.group.prev())
-- Binder.add(vars.mainMod .. " + ALT + SHIFT + TAB", { desc =  "Reveal active window on top"}, hl.dsp.window.bring_to_top())
Binder.add(vars.mainMod .. " + CTRL + TAB", { desc =  "Former workspace"}, hl.dsp.focus({ workspace = "next" }))
Binder.add(vars.mainMod .. " + CTRL + SHIFT + TAB", { desc =  "Former workspace"}, hl.dsp.focus({ workspace = "previous" }))

	---- Layout Management
Binder.add(vars.mainMod .. " + ALT + S", { desc = "Toggle split" }, hl.dsp.layout("togglesplit"))

 -- Notification Management
Binder.add(vars.mainMod .. " + comma",  { desc = "Dismiss last notification" }, "blackarch-shell notifications dismissOne")
Binder.add(vars.mainMod .. " + SHIFT + comma",  { desc = "Dismiss all notifications" }, "blackarch-shell notifications dismissAll")
Binder.bind_toggle(vars.mainMod .. " + CTRL + comma", "Toggle silencing notifications", "notification-silencing")
Binder.add(vars.mainMod .. " + ALT + comma",  { desc = "Invoke last notification" }, "blackarch-shell notifications invokeLast")
Binder.add(vars.mainMod .. " + SHIFT + ALT + comma",  { desc = "Open notification history" }, "blackarch-shell notifications showHistory")

Binder.add(vars.mainMod .. " + code:20", { desc =  "Expand window left" },  hl.dsp.window.resize({ x = -100, y = 0, relative = true }))
Binder.add(vars.mainMod .. " + code:21", { desc =  "Shrink window left" },  hl.dsp.window.resize({ x = 100, y = 0, relative = true }))
Binder.add(vars.mainMod .. " + SHIFT + code:20", { desc =  "Shrink window up" },  hl.dsp.window.resize({ x = 0, y = -100, relative = true }))
Binder.add(vars.mainMod .. " + SHIFT + code:21", { desc =  "Expand window down" },  hl.dsp.window.resize({ x = 0, y = 100, relative = true }))

Binder.add(vars.mainMod .. " + ALT + code:20", { desc =  "Expand window left a little" },  hl.dsp.window.resize({ x = -25, y = 0, relative = true }))
Binder.add(vars.mainMod .. " + ALT + code:21", { desc =  "Shrink window left a little" },  hl.dsp.window.resize({ x = 25, y = 0, relative = true }))
Binder.add(vars.mainMod .. " + SHIFT + ALT + code:20", { desc =  "Shrink window up a little" },  hl.dsp.window.resize({ x = 0, y = -25, relative = true }))
Binder.add(vars.mainMod .. " + SHIFT + ALT + code:21", { desc =  "Expand window down a little" },  hl.dsp.window.resize({ x = 0, y = 25, relative = true }))

Binder.add(vars.mainMod .. " + CTRL + code:20", { desc =  "Expand window left a lot" },  hl.dsp.window.resize({ x = -300, y = 0, relative = true }))
Binder.add(vars.mainMod .. " + CTRL + code:21", { desc =  "Shrink window left a lot" },  hl.dsp.window.resize({ x = 300, y = 0, relative = true }))
Binder.add(vars.mainMod .. " + CTRL + SHIFT + code:20", { desc =  "Shrink window up a lot" },  hl.dsp.window.resize({ x = 0, y = -300, relative = true }))
Binder.add(vars.mainMod .. " + CTRL + SHIFT + code:21", { desc =  "Expand window down a lot" },  hl.dsp.window.resize({ x = 0, y = 300, relative = true }))

	---- Workspace Management
Binder.add(vars.mainMod .. " + 1", { desc = "Workspace 1" }, function()
  hl.dispatch(hl.dsp.focus({ workspace = "1"}))
  hl.dispatch(hl.dsp.window.bring_to_top())
end)
Binder.add(vars.mainMod .. " + 2", { desc = "Workspace 2" }, function() hl.dispatch(hl.dsp.focus({ workspace = "2"})) hl.dispatch(hl.dsp.window.bring_to_top()) end)
Binder.add(vars.mainMod .. " + 3", { desc = "Workspace 3" }, function() hl.dispatch(hl.dsp.focus({ workspace = "3"})) hl.dispatch(hl.dsp.window.bring_to_top()) end)
Binder.add(vars.mainMod .. " + 4", { desc = "Workspace 4" }, function() hl.dispatch(hl.dsp.focus({ workspace = "4"})) hl.dispatch(hl.dsp.window.bring_to_top()) end)
Binder.add(vars.mainMod .. " + 5", { desc = "Workspace 5" }, function() hl.dispatch(hl.dsp.focus({ workspace = "5"})) hl.dispatch(hl.dsp.window.bring_to_top()) end)
Binder.add(vars.mainMod .. " + 6", { desc = "Workspace scratchpad" }, function() hl.dispatch(hl.dsp.workspace.toggle_special("ScratchPad")) hl.dispatch(hl.dsp.window.bring_to_top()) end)
Binder.add(vars.mainMod .. " + 7", { desc = "Workspace hacker" }, function() hl.dispatch(hl.dsp.workspace.toggle_special("hacker")) hl.dispatch(hl.dsp.window.bring_to_top()) end)
Binder.add(vars.mainMod .. " + 8", { desc = "Workspace silent" }, function() hl.dispatch(hl.dsp.workspace.toggle_special("silent")) hl.dispatch(hl.dsp.window.bring_to_top()) end)

Binder.add(vars.mainMod .. " + SHIFT + 1", { desc = "Move to Workspace 1" }, hl.dsp.window.move({ workspace = "1"}))
Binder.add(vars.mainMod .. " + SHIFT + 2", { desc = "Move to Workspace 2" }, hl.dsp.window.move({ workspace = "2" }))
Binder.add(vars.mainMod .. " + SHIFT + 3", { desc = "Move to Workspace 3" }, hl.dsp.window.move({ workspace = "3"}))
Binder.add(vars.mainMod .. " + SHIFT + 4", { desc = "Move to Workspace 4" }, hl.dsp.window.move({ workspace = "4"}))
Binder.add(vars.mainMod .. " + SHIFT + 5", { desc = "Move to Workspace 5" }, hl.dsp.window.move({ workspace = "5"}))
Binder.add(vars.mainMod .. " + SHIFT + 6", { desc = "Move to  special:Workspace scratchpad" }, hl.dsp.window.move({ workspace = "special:ScratchPad"}))
Binder.add(vars.mainMod .. " + SHIFT + 7", { desc = "Move to  special:Workspace hacker" }, hl.dsp.window.move({ workspace = "special:hacker"}))
Binder.add(vars.mainMod .. " + SHIFT + 8", { desc = "Move to  special:Workspace silent" }, hl.dsp.window.move({ workspace = "special:silent"}))



Binder.add(vars.mainMod .. " + 9", { desc = "Hyprland" }, "blackarch gui aquamarine" )

 -- Lid Handling
Binder.add("switch:off:Lid Switch", { desc = "Lock Screen" }, "blackarch brightness lock")
Binder.add("switch:on:Lid Switch", { desc = "Toggle brightness to Work mode" }, "blackarch brightness unlock")
-- Binder.add("switch:on:Intel HID switches", { desc = "Touchscreen Rotation in tablet mode" }, "blackarch shell touchscreen_orientation")
-- Binder.add("switch:on:Intel HID switches", { desc = "Toggle Virtualkeyboard on" }, "blackarch toggle virtualkeyboard auto")
Binder.add("switch:off:Intel HID switches", { desc = "Toggle Virtualkeyboard off" }, "blackarch toggle virtualkeyboard off")

Binder.add("F12", { desc = "Toggle Brightness" }, "blackarch brightness toggle" )
Binder.add(vars.numlock .. " + F12", { desc = "Face Unlock Trigger", locked = true }, "blackarch brightness lock")
Binder.add(vars.mainMod .. " + F12", { desc = "Set brightness to off" }, "blackarch brightness off" )
Binder.add(vars.mainMod .. " + CTRL + F12", { desc = "Launch screensaver" }, "blackarch-launch-screensaver" )
Binder.add(vars.mainMod .. " + SHIFT + F12", { desc = "Lock and Suspend" }, "blackarch brightness suspend" )

--NumLock Keybindings
Binder.add(vars.numlock .. " + backspace", { desc = "Bluetooth" }, "blackarch-shell shell toggle blackarch.bluetooth")
Binder.add(vars.numlock .. " + RETURN", { desc = "Network" }, "blackarch-shell shell toggle blackarch.network" )
Binder.bind_toggle(vars.numlock .. " + DELETE", "Toggle top bar", "bar")

