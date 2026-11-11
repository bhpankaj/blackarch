--------------------------------
---- WINDOWS AND WORKSPACES ----
--------------------------------

-- See https://wiki.hypr.land/Configuring/Basics/Window-Rules/
-- and https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/
local colors = dofile(os.getenv("HOME") .. "/.config/hypr/colors-hyprland.lua")
local active_hex = colors.active:gsub("#", "0xff")
local inactive_hex = colors.inactive:gsub("#", "0xff")
local float_hex = colors.float:gsub("#", "0xff")
local max_hex = colors.max:gsub("#", "0xff")

-- Construct the table
local active_max_color = { colors = {  max_hex, active_hex, inactive_hex }, angle = 45,}
-- local inactive_max_color = { colors = { max_hex, inactive_hex }, angle = 45,}
local active_float_color = { colors = {  float_hex },	angle = 45,}
local inactive_color = { colors = {  inactive_hex }}

local tiled_classes = {
	"pavucontrol",
}

local floating_classes = {
  ".*Gksu.*",
	"steam",
	"xdg-desktop-portal",
	"xdg-desktop-portal-gtk",
  "hyprland-share-picker",
	"kitty-float",
	"1password",
	"org.quickshell",
	"org.blackarch.blackarch-update",
  "org.blackarch.bluetui",
  "org.blackarch.impala",
  "org.blackarch.wiremix",
  "org.blackarch.btop",
  "org.blackarch.terminal",
  "org.blackarch.bash",
  "org.codeberg.dnkl.foot",
  "org.gnome.NautilusPreviewer",
  "org.gnome.Evince",
  "com.gabm.satty",
  -- "blackarch",
  "About",
  "TUI.float",
  "imv",
  "mpv",
  "wofi",
  -- "^$",
  "yad",
}

local default_size = {
  ".*ulaa-browser.*",
	".*ulaa-.*",
	".*burp.*",
	".*thunar.*",
	"*qutebrowser",
  ".*"
}

local function escape_regex(value)
	return value:gsub("([%.%+%*%?%^%$%(%)%[%]%{%}%|\\])", "\\%1")
end

local function class_match(class)
	return ("^(%s)$"):format(escape_regex(class))
end

for _, class in ipairs(tiled_classes) do
	hl.window_rule({ match = { class = class_match(class)}, tile = true})
end

for _, class in ipairs(floating_classes) do
	hl.window_rule({	match = { class = class_match(class)}, float = true, tag = "+floating-window", 	workspace = "unset", group = "unset", stay_focused = false })
end

for _, class in ipairs(default_size) do
	hl.window_rule({ match = { class = class_match(class)}, size = {"(monitor_w*0.45)", "(monitor_h*0.45)"}})
end

hl.window_rule({ match = { class = class_match("firefox"), title = "^(Picture-in-Picture)$"}, float = true})

-- hiding
hl.window_rule({ match = { title = ".*is sharing.*" }, workspace = "special:silent" })

-- Fix some dragging issues with XWayland.
-- hl.window_rule({ match = {	class = "^$",	title = "^$", xwayland = true, float = true, fullscreen = false, pin = false}, no_focus = false, no_follow_mouse = false})

-- Persion Window rules

hl.window_rule({ match = { class = "(.*aquamarine.*|org.blackarch.hyprland)" }, workspace = 5, fullscreen = true })
hl.window_rule({ match = { class = "(.*kitty.*)" } , size = {"(monitor_w*0.95)", "(monitor_h*0.95)"}, workspace = "1" })
hl.window_rule({ match = { class = "(.*hacker.*)" } , size = {"(monitor_w*0.95)", "(monitor_h*0.95)"}, workspace = "4" })
hl.window_rule({ match = { class = "(^org.blackarch.screensaver$)" }, fullscreen = true })
hl.window_rule({ match = { class = "(.*ulaa-.*)" }, workspace = "1", group = "set" })
hl.window_rule({ match = { class = "(.*youtube.com.*|.*cliamp.*)" }, workspace = "special:hacker", group = "unset",no_screen_share = on, no_shadow = on  })
hl.window_rule({ match = { class = "(.*firefox.*|.*chromium.*|.*brave.*|.*librewolf.*)" }, workspace = "2" , group = "set"})
-- hl.window_rule({ match = { class = "()"  }, size = {"(monitor_w*0.45)", "(monitor_h*0.45)"}, float = true})
hl.window_rule({ match = { class = "org.blackarch.mpv" }, workspace = "5", group = "set" })
-- hl.window_rule({ match = { class = "(.*Alacritty.*|.*kitty.*|.*ghostty.*)" }, workspace = "special:kitty", group = "set", size = {2480, 1337}})
-- hl.window_rule({ match = { class = "(.*gcr-prompter.*)" }, workspace = "special:ulaaapps" })
hl.window_rule({ match = { class = "(.*ulaa-browser.*|.*burp.*)" }, workspace = "5", group = "set" })
hl.window_rule({ match = { class = "(.*windows.cloud.*)" }, workspace = "5", group = "set" })
hl.window_rule({ match = { class = "(.*qutebrowser.*)" }, workspace = "5", group = "set" })

-- Windows apps opened with `blackarch-windows-vm app` (RDP RemoteApp / RAIL).
-- xfreerdp3 is an XWayland client and names every remote window "RAIL:<id>",
-- with no rule of its own, so a remote app would arrive at a default size and
-- tile like a stray window. Float it and give it a sensible app-window size.
hl.window_rule({ match = { class = ".*RAIL:.*" }, float = true, center = true, size = { "(monitor_w*0.7)", "(monitor_h*0.7)" } })
-- The remote session also announces helper windows ("PopupHost", the language
-- bar and notification area). Those must stay tiny: the rule above would
-- otherwise blow each one up to app-window size. Applied after, so it wins.
hl.window_rule({ match = { class = ".*RAIL:.*", title = "^PopupHost$" }, float = true, size = { 1, 1 } })

-- Cleanup Rules
hl.window_rule({ match = { class = "(xdg-desktop-portal-gtk|sublime_text|DesktopEditors|org.gnome.Nautilus)",title = "^(Open.*Files?|Open [F|f]older.*|Save.*Files?|Save.*As|Save|All Files|.*wants to [open|save].*|[C|c]hoose.*)",
	}, tag = "+floating-window"
})

hl.window_rule({ match = { class = ".*discord.com is sharing your screen.*"	}, workspace = "special:silent", group = "unset", stay_focused = false })
hl.window_rule({ match = { class = "hyprlan-run" }, move = { "20", "monitor_h-120" }, float = true })

-- Webcam Overlay
hl.window_rule({ match = { title = "(^.*WebcamOverlay.*|^.*Stream.*)" },
	tag = "+floating-window", pin = true,	 move = { "monitor_w-window_w-40", "monitor_h-window_h-40" },
})

-- Color border
hl.window_rule({ match = { title = "(^.*WebcamOverlay.*|^.*Stream.*)" }, pin = true, group = "unset", border_color = active_float_color, border_size = 2, move = { "monitor_w-window_w-40", "monitor_h-window_h-40" }, size = {100,100}})
-- hl.window_rule({ match = { focus = 1 }, border_color = active_max_color, border_size = 3})
-- hl.window_rule({ match = { focus = 0 }, border_color = inactive_color, border_size = 3})
-- hl.window_rule({ match = { float = true, focus = 1 }, border_color = active_float_color, border_size = 3})
-- hl.window_rule({ match = { fullscreen = 1, focus = 1 }, border_color = active_max_color, border_size = 3})

-- Layer Rules
hl.layer_rule({ match = { namespace = "selection" }, no_anim = true })
hl.layer_rule({ match = { namespace = "wvkbd" }, no_anim = true, no_screen_share = true, above_lock = 2 })

-- Complex/Tag Rules
-- hl.window_rule({ match = { class = "^$" }, float = true, fullscreen = false, pin = false, no_focus = true})
hl.window_rule({ match = { tag = "floating-window" }, float = true, center = true, size = { 1875, 1100 } })
hl.window_rule({ match = { tag = "pop" }, rounding = 8 })
hl.window_rule({ match = { tag = "noidle" }, idle_inhibit = "always" })
hl.window_rule({ match = { class = "RAIL:*" }, workspace = "1" })

-- Workspace Layout rules
hl.workspace_rule({ workspace = "special:hacker", layout = "master", no_screen_share = on, no_shadow = on })
hl.workspace_rule({ workspace = "special:silent", layout = "scrolling", no_screen_share = on, no_shadow = on })
hl.workspace_rule({ workspace = "special:scratchpad", layout = "master", no_screen_share = on, no_shadow = on })
hl.workspace_rule({ workspace = "1", layout = "monocle" })
hl.workspace_rule({ workspace = "2", layout = "monocle" })
hl.workspace_rule({ workspace = "3", layout = "lua:blackarch"})
hl.workspace_rule({ workspace = "4", layout = "scrolling", layout_opts = { direction = "down" } })
hl.workspace_rule({ workspace = "5", layout = "master" })
