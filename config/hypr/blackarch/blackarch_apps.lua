local M = {}

-- 1. Configuration Map (Predefined apps)
local apps = {
    ["Claude"] = { url = "https://claude.ai/" },
    ["Discord"] = { url = "https://discord.com/login" },
    ["Gemini"] = { url = "https://gemini.google.com/app" },
    -- Add more apps as needed
    ["Gmail"] = { url = "https://mail.google.com" },
    ["Calendar"] = { url = "https://calendar.google.com" },
}

-- Extracts the window pattern using bash regex logic:
-- [[ "${URL}" =~ ^https?://?([^/]+)(/[^?#]*)?(\?[^#]*)? ]]
-- WINDOW_PATTERN="${domain_port}_${path//\//_}"
local function get_window_pattern(url)
    -- Remove protocol (http:// or https://) - handle optional //
    local clean_url = url:gsub("^https?://?", "")
    
    -- Extract domain_port (group 1) and path (group 2)
    local domain_port, path = clean_url:match("^([^/]+)(/[^?#]*)?")
    
    -- If path exists, replace slashes with underscores like ${path//\//_}
    if path and path ~= "" then
        local formatted_path = path:gsub("/", "_")
        return domain_port .. "_" .. formatted_path
    else
        return domain_port
    end
end

function M.launch_webapp(input)
    local target_url = input
    local pattern = nil

    -- Check if input matches a predefined app name
    if apps[input] then
        target_url = apps[input].url
        pattern = get_window_pattern(target_url)
    else
        -- Add http:// if no protocol is specified
        if not input:match("^https?://") then
            target_url = "https://" .. input
        end
        -- Generate the pattern using the bash-equivalent regex logic
        pattern = get_window_pattern(target_url)
    end

    -- 2. Search for existing window natively (case-insensitive)
    local found_window = nil
    for _, client in ipairs(hl.clients) do
        -- Use lower() for case-insensitive matching
        local client_class = client.class and client.class:lower() or ""
        local client_title = client.title and client.title:lower() or ""
        local pattern_lower = pattern:lower()
        
        if client_class:find(pattern_lower, 1, true) or 
           client_title:find(pattern_lower, 1, true) then
            found_window = client
            break
        end
    end

    -- 3. Focus or Launch
    if found_window then
        -- Focus the existing window
        hl.dsp.focus("focuswindow", "address:" .. found_window.address)
        
        -- Optional: Bring to current workspace if needed
        -- hl.dispatch("movetoworkspace", "current,address:" .. found_window.address)
    else
        -- Launch new window with chrome/ulaa-browser
        -- Add --new-window to ensure it opens as a separate window
        local cmd = string.format("ulaa-browser --profile-directory=Default --app=%s --new-window", target_url)
        hl.spawn(cmd)
    end
end

function M.PromptAndLaunch()
    -- Get input from wofi with better formatting
    local input = hl.dispatch(hl.dsp.exec_cmd(
        "echo -e " .. M.list_apps.app_list .. "wofi --dmenu --prompt 'Webapp URL:' --width 400 --height 50"
    ))

    if input and input ~= "" then
        -- Clean the string (remove newline/whitespace)
        input = input:gsub("%s+", "")
        
        if input ~= "" then
            M.launch_webapp(input)
        end
    end
end

-- Optional: Add keybinding helper function
function M.setup_keybindings(mod, key)
    -- Example: Bind to Super+W for prompt
    -- In your hyprland.conf: bind = $mainMod, W, exec, hyprctl dispatch exec "lua /path/to/this/script.lua"
    -- Or use: bind = $mainMod, W, exec, "python3 -c \"import hyprland; hyprland.dispatch('exec', 'lua /path/to/this/script.lua')\""
end

-- Optional: Add function to list available apps
function M.list_apps()
    local app_list = {}
    for name, _ in pairs(apps) do
        table.insert(app_list, name)
    end
    return table.concat(app_list, ", ")
end

return M
