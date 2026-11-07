-- hyprland_startup.lua
hl.on("hyprland.shutdown", function()
	hl.exec_cmd("blackarch execute charger off")
end)

hl.on("hyprland.start", function()
  hl.exec_cmd("systemctl --user import-environment $(env | cut -d'=' -f 1)")
  hl.exec_cmd("dbus-update-activation-environment --systemd --all")
  hl.exec_cmd("blackarch-launch-shell")
  hl.exec_cmd("blackarch-powerprofiles-init")
  hl.exec_cmd("blackarch-hyprland-monitor-watch")
  hl.exec_cmd("udiskie --automount --no-notify --no-tray")
  hl.exec_cmd("systemctl --user start hyprpolkitagent")
	hl.exec_cmd("/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1")
	hl.exec_cmd("blackarch-server-wallpaper")
	hl.exec_cmd("xrdb -load " .. os.getenv("HOME") .. "/.Xresources")
	hl.exec_cmd("wl-paste --type text --watch cliphist store")
	hl.exec_cmd("wl-paste --type image --watch cliphist store")
	hl.exec_cmd("gsettings set org.gnome.desktop.interface color-scheme prefer-dark")
	-- Only pin the factor when nothing has been chosen yet. Writing a literal
	-- here would overwrite whatever the Display panel's text-size slider set on
	-- the previous session, so the slider appears to reset on every login.
	hl.exec_cmd("bash -c 'gsettings get org.gnome.desktop.interface text-scaling-factor | grep -qx 1.0 && gsettings set org.gnome.desktop.interface text-scaling-factor 1.5 || true'")
	hl.exec_cmd("gsettings set org.gnome.desktop.interface icon-theme 'HackTheBox'")
	hl.exec_cmd("gsettings set org.gnome.desktop.interface cursor-theme Afterglow-Dracula-Green")
  hl.exec_cmd("blueman-applet")
  hl.exec_cmd("nm-applet")
  hl.exec_cmd("sudo blackarch-kbd-backlight-monitor 30")
	-- hl.exec_cmd("blackarch execute charger on")
end)

	-- hl.exec_cmd("blackarch execute shell touchscreen_orientation")

  -- hl.exec_cmd("blackarch-provision-first-run")
  -- hl.exec_cmd("sleep 2 && blackarch-hook post-boot")
  --
	-- hl.exec_cmd("swaybg -m fill -i " .. os.getenv("HOME") .. "/.config/blackarch/current/background")
	-- hl.exec_cmd("blackarch-start-waybar")
  -- Run post-boot hooks after startup config has loaded.
	-- hl.exec_cmd("hypridle" )
	-- hl.exec_cmd("easyeffects -p" )
	-- hl.exec_cmd("gost -L socks5://127.0.0.1:1080?interface=wlan0" )
	-- hl.exec_cmd("gost -L socks5://127.0.0.1:1081?interface=enp0s20f0u2")
	-- hl.exec_cmd("nm-applet --indicator")
	-- hl.exec_cmd("foot --server")
	-- hl.exec_cmd("apply-gsettings")
	-- hl.exec_cmd("")
	-- hl.exec_cmd("systemctl --user start hyprland-session.target")
	-- hl.exec_cmd("dunst")
  -- Auto-showing virtual keyboard: registers as a zwp_input_method_v2 input
  -- method, so Hyprland shows/hides it as text fields gain and lose focus.
  -- hl.exec_cmd("blackarch execute toggle virtualkeyboard toggle")
