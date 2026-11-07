local Binder = {}
-- This table lives in memory and is shared across all requires
-- Binder.registry = {}
-- Ensure the registry exists globally so all modules share it
if _G.BinderRegistry == nil then
    _G.BinderRegistry = {}
end

if _G.SubmapRegistries == nil then
    _G.SubmapRegistries = {}
end

Binder.current_submap = nil
-- _G.input=hl.bind("SUPER + 9",hl.dsp.exec_cmd("wofi --dmenu --prompt 'Enter Webapp URL:' --width 400 --height 50 "),"wofi input")

Binder.is_printing = false

-- Hyprland wraper function so that keybindings can be used
function Binder.add(key, desc, cmd)
  local binding_data = { key = key, desc = desc.desc or "No description", cmd = cmd }

  -- Store binding data
  if desc.record ~= false then
      table.insert(_G.BinderRegistry, binding_data)
  end
  
  -- Store in Submap Registry if we are currently inside a submap definition
  if Binder.current_submap then
      if _G.SubmapRegistries[Binder.current_submap] == nil then
          _G.SubmapRegistries[Binder.current_submap] = {}
      end
      table.insert(_G.SubmapRegistries[Binder.current_submap], binding_data)
  end

  -- Register with Hyprland directly
  if not Binder.is_printing and _G.hl then
    if type(cmd) == "string" then
      hl.bind(key, hl.dsp.exec_cmd(cmd), desc)
    -- elseif type(cmd) == "function" then
    else
      hl.bind(key, function() hl.dispatch(cmd) end,desc)
    end
  end
end

-- Helper wrapper to cleanly capture submaps into their own variables/tables
function Binder.define_submap(name, reset_key, callback)
    Binder.current_submap = name
    
    -- Initialize the registry entry for this submap
    _G.SubmapRegistries[name] = {}

    -- Execute the original submap definition hook
    if _G.hl and hl.define_submap then
        hl.define_submap(name, reset_key, function()
            -- Run user's callback which calls Binder.add inside
            if type(callback) == "function" then
                callback()
            end
        end)
    end

    Binder.current_submap = nil -- Reset context after definition
end

-- Function to display keybindings for a specific submap via wofi
function Binder.show_submap_menu(submap_name, prompt_title)
    local submap_bindings = _G.SubmapRegistries[submap_name]
    
    if not submap_bindings or #submap_bindings == 0 then
        os.execute("notify-send 'Binder' 'No keybindings found for submap: " .. tostring(submap_name) .. "'")
        return
    end

    local choices = ""
    for _, b in ipairs(submap_bindings) do
        local key = tostring(b.key)
        local desc = tostring(b.desc)
        local last_part = string.match(key, "([^ +]+)$") or key
        local rest_of_key = string.match(key, "(.*) %+") or ""
        local new_key = "[" .. last_part .. "] + (" .. rest_of_key .. ")"
        choices = choices .. string.format("%-25s -> %s\n",new_key,desc)
        -- choices = choices .. string.format("[%-10s] -> %s\n", key, desc)
    end

    hl.exec_cmd("echo -e '" .. choices .. "' | blackarch-menu-select Keybindings -- --width 800 --height 500")
    
end

-- My Custom Function for automations
function Binder.keybindings()
    local choices = ""
    -- Sort the global registry alphabetically by key
    table.sort(_G.BinderRegistry, function(a, b)
        -- Helper function to get the last part of a string like "SUPER + ALT + F1"
        local function getLastPart(keyStr)
            if not keyStr then return "" end
            -- Match the last word after the last '+'
            -- Pattern: ([^ +]+)$ matches the last sequence of non-plus characters
            local last = string.match(keyStr, "([^ +]+)$")
            return last or keyStr
        end

        local partA = getLastPart(a and a.key)
        local partB = getLastPart(b and b.key)

        return partA < partB
    end)
    -- Build the input string for wofi (one entry per line)
    for _, b in ipairs(_G.BinderRegistry) do
      local desc = (b and b.desc) and tostring(b.desc) or "No description"
      local key = (b and b.key) and tostring(b.key) or "No Key"
      -- 1. Extract the last word after the last '+'
      local last_part = string.match(key, "([^ +]+)$") or key
      
      -- 2. Remove the last part and the last '+' from the original string
      -- Pattern explanation: Find everything up to the last ' + ' and capture it
      local rest_of_key = string.match(key, "(.*) %+") or ""
      rest_of_key = string.gsub(rest_of_key, "MOD1", "lalt")
      rest_of_key = string.gsub(rest_of_key, "MOD2", "numlock")
      rest_of_key = string.gsub(rest_of_key, "MOD3", "rctl")
      rest_of_key = string.gsub(rest_of_key, "MOD4", "super")
      rest_of_key = string.gsub(rest_of_key, "MOD5", "ralt")
      -- 3. Construct new key: Last Part + (Rest of string without the last '+')
      -- If there was no '+', rest_of_key will be empty, just display the last_part
      local new_key = "[" .. last_part .. "] + (" .. rest_of_key .. ")"
      choices = choices .. string.format("%-25s -> %s\n",new_key,desc)
        -- choices = choices .. b.key .. "->" .. b.desc 
    end
    -- hl.exec_cmd("echo -e '" .. choices .. "' | grep -v XF86 |  wofi --dmenu -i --prompt 'Select Action'")
    hl.exec_cmd("echo -e '" .. choices .. "' | grep -v XF86 | blackarch-menu-select Keybindings -- --width 800 --height 500")
end

-- Notify time
function Binder.show_time()
  local text = "   " .. os.date("%A %H:%M  —  %d %B W%V %Y")

  if my_notif then
    -- Update the existing notification object
    my_notif:set_text(text)
  else
    -- Create a new one if it doesn't exist
    my_notif = hl.notification.create({
      text = text,
      timeout = 5000,
    })
  end
end

-- Helper function to toggle DPMS
function Binder.toggle_dpms()
    -- Get the status of the monitors
    local handle = io.popen("hyprctl monitors")
    local output = handle:read("*a")
    handle:close()

    -- Check if any monitor is currently on (dpmsStatus: 1)
    if output:match("dpmsStatus: 1") then
        -- hl.dsp.dpms({ action = "disable" })
        h1.dsp.exec_cmd('hyprctl dispatch "hl.dsp.dpms({ action = "disable" })"')
    else
        -- hl.dsp.dpms({ action = "enable" }) throwing nil value at line 49
        hl.dispatch(h1.dsp.exec_cmd('hyprctl dispatch "hl.dsp.dpms({ action = "enable" })"'))
    end
end

-- Helper to register exec commands with consistent descriptions
function Binder.bind_exec(key, opts, cmd)
	opts = opts or {}
	hl.bind(key, hl.dsp.exec_cmd(cmd), {
		description = opts.desc or "",
		locked = opts.locked or false,
		repeating = opts.repeating or false,
	})
end

function Binder.send_shortcut_once(mods, key)
	return function()
		-- 	hl.dsp.send_shortcut({	mods = "CTRL", key = "INSERT" }),
		hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "down", window = "activewindow" }))

		hl.timer(function()
			hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "up", window = "activewindow" }))
		end, { timeout = 50, type = "oneshot" })
	end
end

function Binder.shell_quote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

function Binder.file_exists(path)
  local file = io.open(path, "r")
  if file then
    file:close()
    return true
  end
  return false
end

-- Hyprland reaps its own children, so os.execute() can't retrieve an exit status
-- from inside the compositor. Read a marker off stdout instead.
function Binder.shell_succeeds(command)
  -- Subshell, so the redirection covers every command rather than binding to
  -- the last one and letting an earlier one write its own OK into the pipe.
  local pipe = io.popen("( " .. command .. " ) >/dev/null 2>&1 && echo OK")
  if not pipe then
    return false
  end

  local output = pipe:read("*a") or ""
  pipe:close()

  return output:find("OK", 1, true) ~= nil
end

function Binder.cmd_present(command)
  if command:find("/", 1, true) then
    return file_exists(command)
  end

  local path = os.getenv("PATH") or "/usr/local/bin:/usr/bin"
  for directory in (path .. ":"):gmatch("([^:]*):") do
    if file_exists((directory ~= "" and directory or ".") .. "/" .. command) then
      return true
    end
  end

  return false
end

function Binder.cmd_missing(command)
  return not Binder.cmd_present(command)
end

local function command_from(value, description)
  if type(value) ~= "table" then
    return value
  end

  if value.blackarch then
    return "blackarch-launch-" .. value.blackarch
  elseif value.focus and value.launch then
    return Binder.launch_sole(value.focus, value.launch)
  elseif value.launch then
    return Binder.launch(value.launch)
  elseif value.webapp then
    if value.focus then
      return Binder.launch_webapp_sole(description, value.webapp)
    else
      return Binder.launch_webapp(value.webapp)
    end
  elseif value.tui then
    if value.focus then
      return "blackarch-launch-or-focus-tui " .. shell_quote(value.tui)
    else
      return "blackarch-launch-tui " .. shell_quote(value.tui)
    end
  end

  return value
end

function Binder.preinstalled_bindings_enabled()
  if _G.blackarch_preinstalled_bindings ~= nil then
    return _G.blackarch_preinstalled_bindings == true
  end

  return not file_exists((os.getenv("HOME") or "") .. "/.local/state/blackarch/preinstalls-removed")
end

function Binder.bind(keys, description, dispatcher, options)
  local opts = options or {}

  if description then
    opts.description = description
  end

  dispatcher = command_from(dispatcher, description)

  if type(dispatcher) == "string" then
    dispatcher = hl.dsp.exec_cmd(dispatcher)
  end

  hl.bind(keys, dispatcher, opts)
end

function Binder.launch(command)
  return "uwsm-app -- " .. command
end

function Binder.exec_on_start(command)
  hl.on("hyprland.start", function()
    hl.exec_cmd(command)
  end)
end

function Binder.launch_on_start(command)
  Binder.exec_on_start(Binder.launch(command))
end

function Binder.launch_webapp(url)
  return "blackarch-launch-webapp " .. shell_quote(url)
end

function Binder.launch_webapp_sole(name, url)
  return "blackarch-launch-or-focus-webapp " .. shell_quote(name) .. " " .. shell_quote(url)
end

function Binder.launch_sole(match, command)
  return "blackarch-launch-or-focus " .. shell_quote(match) .. " " .. shell_quote(Binder.launch(command))
end

function Binder.bind_toggle(keys, description, toggle, options)
  Binder.bind(keys, description, "blackarch-toggle-" .. toggle, options)
end

function Binder.notify(message)
  return "blackarch-notification-send -u low " .. shell_quote(message)
end

function Binder.window(match, rules)
  rules.match = rules.match or {}

  if type(match) == "string" then
    rules.match.class = match
  else
    for key, value in pairs(match) do
      rules.match[key] = value
    end
  end

  hl.window_rule(rules)
end

function Binder.system_family()
    local f = io.open("/sys/class/dmi/id/product_family", "r")
    local content = f:read("*all")
    f:close()
    return content
end


















return Binder
