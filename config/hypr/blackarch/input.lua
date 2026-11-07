hl.config({
	input = {
		kb_layout = "us",
		kb_variant = "",
		kb_model = "",
		kb_options = "compose:caps,lv5:rctrl_switch,lv3:ralt_switch", --,ctrl:rctrl_to_hyper
		kb_rules = "",
		follow_mouse = 3,
		sensitivity = 0,
		repeat_rate = 40,
		repeat_delay = 250,
		numlock_by_default = false,
		touchpad = {
      -- middle_button_emulation = true,
			natural_scroll = false,
			clickfinger_behavior = true,
      middle_button_emulation = true,
			scroll_factor = 0.8,
		},
	},
	misc = {
		key_press_enables_dpms = true,
		-- mouse_move_enables_dpms = true,
	},
})

-- Re-apply any persisted input-device disable. hl.device()'s enabled=false is
-- runtime state, so a reload would otherwise re-enable whatever the touchpad /
-- touchscreen toggles turned off.
require("blackarch.disabled_input_device")

