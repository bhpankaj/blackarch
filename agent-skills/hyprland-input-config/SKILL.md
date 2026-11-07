---
name: hyprland-input-config
description: "Set up virtual keyboards and keybinds on Hyprland/Wayland."
version: 1.0.0
author: Hermes Agent
platforms: [linux]
metadata:
  hermes:
    tags: [hyprland, wayland, virtual-keyboard, wvkbd, input, desktop]
---

# Hyprland Input Configuration

## When to Use

Use when configuring virtual keyboards, input devices, or keybindings on
Hyprland/Wayland. Triggers: "virtual keyboard", "on-screen keyboard",
"wvkbd", "toggle keyboard", "keybind", "input config".

## Virtual Keyboard (wvkbd)

wvkbd is the standard virtual keyboard for wlroots compositors. Install from AUR:

```bash
yay -S --noconfirm wvkbd
```

**Binary name**: `wvkbd-mobintl` (NOT `wvkbd-mobland`). Always verify with
`pacman -Ql wvkbd | grep bin` before referencing in scripts.

### Toggle Script

Create `~/.local/bin/toggle-vkeyboard`:

```bash
#!/bin/bash
if pgrep -x "wvkbd-mobintl" > /dev/null; then
    pkill -x "wvkbd-mobintl"
else
    wvkbd-mobintl &
fi
```

Make executable: `chmod +x ~/.local/bin/toggle-vkeyboard`

### Hyprland Keybind

Add to the appropriate binding file (e.g., `~/.config/hypr/blackarch/binding_utilities.lua`):

```lua
Binder.add(vars.mainMod .. " + K", { desc = "Toggle Virtual Keyboard" }, "$HOME/.local/bin/toggle-vkeyboard")
```

Reload: `hyprctl reload`

## Right Alt as mainMod

Hyprland has no RIGHT_ALT mod. `hl.bind` maps both `ALT` and `MOD1` to
`HL_MODIFIER_ALT` (bit 3, modmask 8), and `CKeybindManager::keycodeToModifier`
hard-codes keycode 108 (`KEY_RIGHTALT`) to that same bit. Left and Right Alt can
therefore never be distinguished in a bind string — `ALT + W` already fires on
Right Alt.

The only way to give Right Alt its own modmask is to move it onto a real
modifier bit nothing else claims. Mod5 (`HL_MODIFIER_MOD5`, modmask 128) is the
one that is free, and it is the real bit behind the `LevelThree` virtual
modifier (AltGr). So:

```lua
-- blackarch/input.lua
kb_options = "compose:caps,lv3:ralt_switch",
```

```lua
-- blackarch/variables.lua
vars.mainMod = "MOD5"
```

`lv3:ralt_switch` redefines `<RALT>` to emit `ISO_Level3_Shift`. Two things fall
out of that at once: Right Alt now sets Mod5, and because no key emits `Alt_R`
anymore, the indirect `modifier_map Mod1 { Alt_L, Alt_R, ... }` from
`symbols/pc` can no longer resolve Right Alt, so it drops off Mod1 too. Verify
with `hyprctl binds -j` — the mainMod binds should move from modmask 64
(SUPER) to 128 (MOD5).

Notes and pitfalls:
- Mod5 is bit 7 (128). Do not confuse the modmask histogram: 64 is SUPER
  (`HL_MODIFIER_META`), 8 is ALT, 1 is SHIFT, 4 is CTRL.
- A custom `.xkb` keymap via `input:kb_file` works too but is unnecessary here;
  it also silently discards `kb_options`, so Caps-as-Compose would be lost.
  Prefer the `kb_options` route.
- `us` (basic) has no level 3, so no key changes meaning. On a layout that does,
  AltGr keeps working because level 3 is still reachable via Right Alt.
- `Shift + Right Alt` is still just Mod5 + Shift, so `MOD5 + SHIFT + KEY`
  binds behave normally.
- Verify the keymap with libxkbcommon itself rather than by pressing keys:
  compile a tiny C program that calls `xkb_keymap_new_from_names()` with the
  same `kb_layout`/`kb_options`, then `xkb_state_update_key(state, 108, DOWN)`
  and print `xkb_state_serialize_mods()`. That is the exact code path Hyprland
  uses, and it proves which real bits a key sets.
- `hyprctl dispatch <dispatcher>` is unusable when the config provider is Lua —
  it falls back to parsing the args as Lua and errors with
  `')' expected near '<arg>'`. Drive the compositor through `hyprctl eval`
  (`hl.dispatch(hl.dsp.exec_cmd(...))`) instead.
- There is no way to inject a physical keypress for testing from the CLI;
  `hl.dsp.send_shortcut`/`send_key_state` target a window, not the keybind
  manager. Ask the user to press the key once.

## Wayland Text Input Detection

**Limitation**: There is no Wayland protocol for external tools to detect when
a text field is focused. The `zwp_text_input_v3` protocol is internal to the
application. Auto-show on textbox focus is NOT reliably possible.

Workarounds:
- Manual toggle keybind (see above)
- Per-app window rules (app-specific auto-show)
- Touchscreen tap gesture binding (if touchscreen available)

## Hyprland Lua Config Structure

This user's Hyprland config uses a custom Lua-based system with `blackarch` modules:
- Main config: `~/.config/hypr/hyprland.lua`
- Bindings: `~/.config/hypr/blackarch/binding_*.lua`
- Variables: `~/.config/hypr/blackarch/variables.lua`
- The `vars.mainMod` is `SUPER` (or `ALT` in nested sessions)

When adding bindings, use the `Binder.add()` pattern with `vars.mainMod` as the modifier prefix.

## References

- `references/wvkbd-vs-onboard.md` — Comparison of wvkbd vs onboard, decision guide for choosing the right virtual keyboard

## Pitfalls

- **wvkbd binary name**: The package installs `wvkbd-mobintl`, not `wvkbd-mobland`. Always verify the binary name with `pacman -Ql wvkbd | grep bin` before referencing it in scripts.
- **Hyprland reload required**: After modifying Lua binding files, run `hyprctl reload` for changes to take effect.
- **No textbox auto-detection on Wayland**: Do not attempt to detect text field focus externally — the protocol does not expose this information. Use manual toggle or per-app rules instead.
- **wvkbd built-in layouts have fixed heights**: The `-H` flag only works with custom layout XML files. Built-in layouts (full, landscape, simple, etc.) are locked at ~120px height regardless of `-H` or `-L` flags. Do not waste time trying different built-in layouts to change size — create a custom layout or use `onboard` instead.
- **wvkbd built-in layouts lack modifier keys**: The built-in layouts are designed for mobile touch input and do NOT include Win/Alt/Super modifier keys. If the user needs modifier keys on the virtual keyboard, recommend `onboard` (full desktop keyboard with all modifiers, resizable, configurable) or create a custom wvkbd layout XML.
- **Don't repeat identical diagnostic commands**: If a command returns the same unexpected result 2-3 times, change the approach instead of re-running the same command. The user noticed and it wastes their time.
