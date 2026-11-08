local Binder = require("blackarch.blackarch_binder")
local vars = require("blackarch.variables")
require("blackarch.binding_submap")

-- Alt
Binder.add(vars.mainMod .. " + ALT + W", { desc = "Kill wofi" }, hl.dsp.exec_cmd("pkill wofi"))


-- ClipBoard
Binder.add(vars.mainMod .. " + C", { desc = "Global Copy",  repeatable = false }, Binder.send_shortcut_once("CTRL", "Insert"))
Binder.add(vars.mainMod .. " + V", { desc = "Global Paste",  repeatable = false }, Binder.send_shortcut_once("SHIFT", "Insert"))
-- Binder.bind("SUPER + CTRL + V", "Clipboard manager", "blackarch-shell shell toggle blackarch.clipboard")
Binder.bind(vars.super .. " + CTRL + V", "Clipboard manager", "blackarch-shell shell toggle blackarch.clipboard")
-- Binder.add(vars.mainMod .. " + CTRL + V",{ desc = "Global Select to Paste", repeatable = false }, "cliphist list |  | cliphist decode | wl-copy")
-- Binder.add(vars.mainMod .. " + CTRL + V", { desc = "Toggle menu" }, "blackarch-menu; env|grep PATH &> /tmp/test.txt")
Binder.add(vars.mainMod .. " + X", { desc = "Global Cut",  repeatable = false }, Binder.send_shortcut_once("CTRL", "X"))

-- Audio & Media
Binder.add("XF86AudioRaiseVolume",		{ repeating = true,desc = "Raise Volume", locked = true },	"blackarch audio up")
Binder.add("XF86AudioLowerVolume",  { repeating = true,desc = "Lower Volume", locked = true },	"blackarch audio down")
Binder.add("XF86AudioMute",  { desc = "Mute Audio", locked = true }, "blackarch audio mute")
Binder.add("XF86AudioMicMute",		{ desc = "Audio Mic Mute", locked = true },	"blackarch-toggle-audio mic")
Binder.add("XF86MonBrightnessUp",  { repeating = true,desc = "Screen Brightness UP", locked = true }, "blackarch brightness up")
Binder.add("XF86MonBrightnessDown",  { repeating = true,desc = "Screen Brightness Down", locked = true }, "blackarch brightness down")
Binder.add("XF86AudioNext",  { desc = "Play Next", locked = true } , "playerctl next")
Binder.add("XF86AudioPause",  { desc = "play-pause", locked = true } , "playerctl play-pause")
Binder.add("XF86AudioPlay",  { desc = "Play", locked = true } , "playerctl play-pause")
Binder.add("XF86AudioPrev",  { desc = "Play Previous", locked = true } , "playerctl previous")
Binder.add("XF86PowerOff",  { desc = "Poweroff Menu", locked = true } , "blackarch-menu system")
Binder.add("XF86Calculator",  { desc = "Calculator", locked = true } , "gnome-calculator")
Binder.add(vars.mainMod .. " + F6",  { desc = "Mute Audio", locked = true }, "blackarch audio mute")
Binder.add("F7",  { repeating = true,desc = "Lower Volume", locked = true },	"blackarch audio down")
Binder.add("F8",		{ repeating = true,desc = "Raise Volume", locked = true },	"blackarch audio up")
Binder.add("F10",		{ desc = "Audio Mic Mute", locked = true },	"blackarch audio mic")
Binder.add(vars.mainMod .. " + SHIFT + F6",	{ desc = "Toggle dictation"}, "voxtype record toggle")
Binder.add(vars.mainMod .. " + SHIFT + F7",	{ desc = "Stop dictation (push-to-talk)"}, "voxtype record stop")
Binder.add(vars.mainMod .. " + SHIFT + F8",	{ desc = "Start dictation (push-to-talk)"}, "voxtype record start")

-- Youtube Control
Binder.add(vars.mainMod .. " + ALT + N", { desc = "Youtube, Next Music", record = false}, hl.dsp.send_shortcut({ mods = "SHIFT", key = "N", window = "class:^.*youtube.com.*$" }))
Binder.add(vars.mainMod .. " + ALT + P", { desc = "Youtube, Previous Music", record = false}, hl.dsp.send_shortcut({ mods = "SHIFT", key = "P", window = "class:^.*youtube.com.*$" }))
Binder.add(vars.mainMod .. " + ALT + F", { desc = "Youtube, Full Screen", record = false}, hl.dsp.send_shortcut({ mods = "", key = "F", window = "class:^.*youtube.com.*$" }))
Binder.add(vars.mainMod .. " + ALT + T", { desc = "Youtube, Theater Mode", record = false}, hl.dsp.send_shortcut({ mods = "", key = "T", window = "class:^.*youtube.com.*$" }))
Binder.add(vars.mainMod .. " + ALT + I", { desc = "Youtube, Insert or minimized mode", record = false}, hl.dsp.send_shortcut({ mods = "", key = "I", window = "class:^.*youtube.com.*$" }))
Binder.add(vars.mainMod .. " + ALT + K", { desc = "Youtube, Play or Pause", record = false}, hl.dsp.send_shortcut({ mods = "", key = "K", window = "class:^.*youtube.com.*$" }))
Binder.add(vars.mainMod .. " + ALT + M", { desc = "Youtube, Mute or Unmute Audio", record = false}, hl.dsp.send_shortcut({ mods = "", key = "M", window = "class:^.*youtube.com.*$" }))
Binder.add(vars.mainMod .. " + ALT + W", { desc = "Kill youtube", record = false}, hl.dsp.send_shortcut({ mods = "CTRL", key = "W", window = "class:^.*youtube.com.*$" }))

-- Media Player Controls
Binder.add(vars.mainMod .. " + SHIFT + P", { desc = "Play Next" }, "playerctl play-pause" )
Binder.add(vars.mainMod .. " + CTRL + P", { desc = "Play Previous" }, "playerctl previous" )
Binder.add(vars.mainMod .. " + P", { desc = "Play Next" }, "playerctl next" )

-- PRINT
Binder.add(vars.mainMod .. " + PRINT",  { desc = "Capture menu" }, "blackarch-menu toggle capture")
Binder.add("PRINT",  { desc = "Take Screenshot" } , "blackarch-cmd-screenshot")
Binder.add("SHIFT + PRINT",  { desc = "Take Screenshot and Copy to Clipboard" } , "blackarch-cmd-screenshot smart clipboard")
Binder.add("ALT + PRINT",  { desc = "Record Screen" }, "blackarch-menu screenrecord")
Binder.add("CTRL + PRINT",  { desc = "Take Screenshot" }, "pkill hyprpicker || hyprpicker -a")

-- Window Management
Binder.add(vars.numlock .. " + ALT + tab", { desc = "NUMLOCK - Swap Focus on selected Windows"}, "blackarch window select /tmp/numWin" )
Binder.add(vars.rctl .. " + ALT + tab", { desc = "RCTL - Swap Focus on selected Windows"}, "blackarch window select /tmp/ctrlWin" )
Binder.add(vars.ralt .. " + ALT + tab", { desc = "RALT - Swap Focus on selected Windows"}, "blackarch window select /tmp/altWin" )
Binder.add(vars.super .. " + ALT + tab", { desc = "SUPER - Swap Focus on selected Windows"}, "blackarch window select" )

Binder.add(vars.numlock .. " + delete", { desc = "NUMLOCK - Clear Swap Windows"}, "blackarch window clear /tmp/numWin" )
Binder.add(vars.rctl .. " + delete", { desc = "RCTL - Clear Swap Windows"}, "blackarch window clear /tmp/ctrlWin" )
Binder.add(vars.ralt .. " + delete", { desc = "RALT - Clear Swap Windows"}, "blackarch window clear /tmp/altWin" )
Binder.add(vars.super .. " + delete", { desc = "SUPER - Clear Swap Windows"}, "blackarch window clear" )

Binder.add(vars.numlock .. " + BACKSLASH", { desc = "NUMLOCK - Swap Focus"}, "blackarch window swap /tmp/numWin" )
Binder.add(vars.rctl .. " + BACKSLASH", { desc = "RCTL - Swap Focus"}, "blackarch window swap /tmp/ctrlWin" )
Binder.add(vars.ralt .. " + BACKSLASH", { desc = "RALT - Swap Focus"}, "blackarch window swap /tmp/altWin" )
Binder.add(vars.super .. " + BACKSLASH", { desc = "SUPER - Swap Focus"}, "blackarch window swap" )

Binder.add(vars.numlock .. " + SHIFT + BACKSLASH", { desc = "NUMLOCK - ClipBoard save window"}, "blackarch window clipboard /tmp/numWin" )
Binder.add(vars.rctl .. " + SHIFT + BACKSLASH", { desc = "RCTL - save Window"}, "blackarch window save /tmp/ctrlWin" )
Binder.add(vars.ralt .. " + SHIFT + BACKSLASH", { desc = "RALT - save Window"}, "blackarch window save /tmp/altWin" )
Binder.add(vars.super .. " + SHIFT + BACKSLASH", { desc = "SUPER - save Window"}, "blackarch window save" )

Binder.add(vars.numlock .. " + CTRL + BACKSLASH", { desc = "NUMLOCK - save Window"}, "blackarch window count /tmp/numWin" )
Binder.add(vars.rctl .. " + CTRL + BACKSLASH", { desc = "RCTL - save Window"}, "blackarch window save /tmp/ctrlWin" ) -- not working
Binder.add(vars.ralt .. " + CTRL + BACKSLASH", { desc = "RALT - save Window"}, "blackarch window count /tmp/altWin" )
Binder.add(vars.super .. " + CTRL + BACKSLASH", { desc = "SUPER - save Window"}, "blackarch window count" )

Binder.add(vars.numlock .. " + ALT + BACKSLASH", { desc = "NUMLOCK - Remove Windows"}, "blackarch window remove /tmp/numWin" )
Binder.add(vars.rctl .. " + ALT + BACKSLASH", { desc = "RCTL - Remove Windows"}, "blackarch window remove /tmp/ctrlWin" )
Binder.add(vars.ralt .. " + ALT + BACKSLASH", { desc = "RALT - Remove Windows"}, "blackarch window remove /tmp/altWin" )
Binder.add(vars.super .. " + ALT + BACKSLASH", { desc = "SUPER - Remove Windows"}, "blackarch window remove" )


-- Web Applications
Binder.add(vars.mainMod .. " + CTRL + E", { desc = "Emojis"}, "blackarch-shell shell toggle blackarch.emojis")
Binder.add(vars.mainMod .. " + slash",{desc = "HTB Academy"}, "blackarch webapp 'https://academy.hackthebox.com'" )
Binder.add(vars.mainMod .. " + period",{desc = "HTB Labs"}, "blackarch webapp 'https://app.hackthebox.com'")
Binder.add(vars.mainMod .. " + W",{desc = "Web Utilities"}, "blackarch toggle learn")


-- Brightness
Binder.add("F2", { repeating = true, desc = "Toggle Brightness", locked = true  }, "blackarch brightness down" )
Binder.add("F3", { repeating = true, desc = "Toggle Brightness", locked = true  }, "blackarch brightness up" )

-- blackarch
    -- Binder.add(vars.mainMod .. " + CTRL + PERIOD", "Transcode", "blackarch-transcode")
Binder.add(vars.mainMod .. " + CTRL + ALT + W", "Toggle weather", "blackarch-notification-weather")

-- Terminal & Utilities
Binder.add(vars.mainMod .. " + ALT + B", { desc = "Launch BTOP" }, "blackarch tui btop" )
-- Binder.add(vars.mainMod .. " + CTRL + B", { desc = "bluetui" }, "blackarch gui blackarch-launch-bluetooth" )
Binder.add(vars.super .. " + CTRL + B", { desc = "Bluetooth" }, "blackarch-shell shell toggle blackarch.bluetooth")
Binder.add(vars.super .. " + SHIFT + B", {desc = "Hacking Tools"}, "blackarch toggle pentest")
Binder.add(vars.super .. " + B", {desc = "My Favorite Hacking Tools"}, "blackarch toggle favorite")

Binder.add(vars.mainMod .. " + D", { desc = "Discord"}, "blackarch gui discord")

Binder.add(vars.ralt .. " + F", { desc = "Firefox" }, "blackarch gui firefox" )
-- Binder.add(vars.mainMod .. " + SHIFT + F", { desc = "Swtich focus to any open windows" }, "blackarch focus" )

Binder.add(vars.mainMod .. " + CTRL + I", { desc = "Toggle Idle" }, "blackarch-toggle-idle" )
-- Binder.add(vars.mainMod .. " + SHIFT + I", { desc = "impala" }, "blackarch gui blackarch-launch-wifi" )
Binder.add(vars.mainMod .. " + SHIFT + I", { desc = "Network" }, "blackarch-shell shell toggle blackarch.network" )
Binder.add(vars.mainMod .. " + I", { desc = "Quickshell Learn Menu" }, "blackarch toggle learn" )

Binder.add(vars.mainMod .. " + N", { desc = "Thunar" }, "blackarch gui nautilus" )
Binder.add(vars.mainMod .. " + SHIFT + N", { desc = "Launch NVIM" }, "blackarch gui nvim")
Binder.add(vars.mainMod .. " + CTRL + N", { desc = "Toggle Night" }, "blackarch-toggle-nightlight" )

Binder.add(vars.mainMod .. " + O", { desc = "Launch Obsidian" }, "blackarch gui obsidian")

Binder.add(vars.mainMod .. " + S", { desc = "Smartthings" }, "blackarch toggle smartthings" )
Binder.add(vars.mainMod .. " + SHIFT + S", { desc = "Smartthings widget" }, "blackarch smartthings widget" )
Binder.add(vars.mainMod .. " + CTRL + S", "Share", "blackarch-menu toggle share")

Binder.add(vars.ralt .. " + U", { desc = "Launch Ulaa-Browser with personal profile" }, "blackarch webapp" )
Binder.add(vars.mainMod .. " + CTRL + U", { desc = "Update Blackarch Linux" }, "blackarch tui 'blackarch update'")
Binder.add(vars.mainMod .. " + SHIFT + U", { desc = "Launch Ulaa-Browser with private profile" }, "blackarch private" )
Binder.add(vars.mainMod .. " + U", { desc = "Launch Ulaa-Browser with work profile" }, "blackarch work" )

Binder.add(vars.mainMod .. " + Y", { desc = "Youtube"}, "blackarch webapp 'https://www.youtube.com/'" )
Binder.add(vars.mainMod .. " + ALT + Y", { desc = "Cliamp offline songs" }, "blackarch tui cliamp /run/media/black/luks-04244121-3fee-4ce4-a0ca-2217d37faa1d/Music/Songs/" )
Binder.add(vars.mainMod .. " + CTRL + Y", { desc = "Cliamp offline songs" }, "blackarch tui cliamp /run/media/black/luks-04244121-3fee-4ce4-a0ca-2217d37faa1d/Music/" )
Binder.add(vars.mainMod .. " + SHIFT + Y", { desc = "Cliamp my Music playlist from Youtube" }, "blackarch tui cliamp --auto-play  --provider youtube 'https://www.youtube.com/watch?v=XfI0gtVwcAQ&list=PLwD_w_9-195-Bwik4HhiDV3rorVbF-_cL&pp=sAgC'" )

Binder.add(vars.mainMod .. " + CTRL + W", { desc = "wiremix" }, "blackarch tui wiremix" )

Binder.add("F1", { desc = "Power" }, "blackarch-shell shell toggle blackarch.power")
Binder.add(vars.mainMod .. " + F1", { desc = "Agent" }, "blackarch tui hermes")

Binder.add(vars.mainMod .. " + F2", { desc = "Set reminder" }, "blackarch-menu toggle reminder-set")

Binder.add(vars.mainMod .. " + F3", { desc = "Show reminders" }, "blackarch-reminder show")
Binder.add(vars.mainMod .. " + SHIFT + F3", { desc = "Clear reminders" }, "blackarch-reminder clear")

Binder.add("F4", { desc = "Display" }, "blackarch-shell shell toggle blackarch.monitor")
Binder.add(vars.mainMod .. " + SHIFT + F4", { desc = "Toggle laptop display mirroring" }, "blackarch-hyprland-monitor-internal-mirror toggle")
-- Binder.add(vars.mainMod .. " + CTRL + F4", { desc = "Toggle laptop display" }, "blackarch-hyprland-monitor-internal toggle")

Binder.add("F5", { desc = "Calendar" }, "blackarch-shell shell toggle blackarch.clock")
Binder.add(vars.mainMod .. " + SHIFT + F5", { desc = "Hardware menu" }, "blackarch-menu toggle hardware")

Binder.add("F6", { desc = "Audio" }, "blackarch-shell shell toggle blackarch.audio")

Binder.add("F9",  { desc = "Key Bindings" }, function() Binder.keybindings() end)
Binder.add(vars.mainMod .. " + F9",  { desc = "Tmux keybindings" }, "blackarch-menu-tmux-keybindings")
Binder.add(vars.mainMod .. " + SHIFT + F9",  { desc =  "Herdr keybindings" }, "blackarch-menu-herdr-keybindings")
Binder.add(vars.mainMod .. " + CTRL + F9",  { desc = "Virtual keyboard", locked = true }, "blackarch-cmd-virtualkeyboard")

Binder.add(vars.mainMod .. " + SHIFT + F10", { desc = "Toggle VPN" }, "blackarch vpn")

Binder.add("F11",  { desc = "Notify Time" }, "blackarch-notification-time")
Binder.add(vars.mainMod .. " + F11", { desc = "Show battery remaining" }, "blackarch-notification-battery")
Binder.add(vars.mainMod .. " + SHIFT + F11", { desc = "Easyeffects" }, "blackarch-toggle-easyeffects" )
Binder.add(vars.mainMod .. " + CTRL + F11", { desc = "Launch share menu" }, "blackarch-menu toggle share" )

Binder.add(vars.mainMod .. " + ESCAPE", { desc = "Launch blackarch-menu system" }, "blackarch-menu toggle system || blackarch-menu system" )
Binder.add(vars.mainMod .. " + SHIFT + ESCAPE", { desc = "Launch Web Portals" }, "blackarch-menu portals" )
Binder.bind_toggle(vars.mainMod .. " + CTRL + ESCAPE", "Toggle top bar", "bar")

Binder.add(vars.mainMod .. " + SPACE", { desc = "Launch blackarch menu" }, "blackarch toggle root")
Binder.add(vars.ralt .. " + SPACE", { desc = "Launch blackarch-menu apps" }, "blackarch toggle apps")
Binder.add(vars.mainMod .. " + SHIFT + SPACE", { desc = "Theme Switcher" }, "blackarch toggle theme" )
Binder.add(vars.mainMod .. " + CTRL + SPACE", { desc = "Change Wallpaper/Background Image" }, "blackarch toggle background" )

