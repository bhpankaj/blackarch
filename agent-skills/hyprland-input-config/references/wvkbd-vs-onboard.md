# wvkbd vs onboard for Hyprland Virtual Keyboards

## wvkbd Limitations

- **Fixed layout heights**: Built-in layouts (full, landscape, simple, etc.) are locked at ~120px. The `-H` and `-L` flags only work with custom layout XML files.
- **No modifier keys**: Built-in layouts do NOT include Win/Alt/Super keys. They are designed for mobile touch input, not desktop keyboard emulation.
- **Custom layouts**: Possible but require writing XML layout files. See wvkbd source for format.

## onboard (Recommended for Desktop Use)

`onboard` is a full desktop virtual keyboard that includes all modifier keys (Win, Alt, Ctrl, Shift), is resizable, and highly configurable.

### Installation
```bash
yay -S --noconfirm onboard
```

### Toggle Script
```bash
#!/bin/bash
if pgrep -x "onboard" > /dev/null; then
    pkill -x "onboard"
else
    onboard &
fi
```

### Keybind
```lua
Binder.add(vars.mainMod .. " + K", { desc = "Toggle Virtual Keyboard" }, "$HOME/.local/bin/toggle-vkeyboard")
```

### Advantages over wvkbd
- Full desktop layout with all modifier keys
- Resizable via command-line or GUI settings
- Multiple layouts (compact, full, etc.)
- Better for desktop use cases

## Decision Guide

| Need | Solution |
|------|----------|
| Basic text input, no modifiers | wvkbd (lightweight, fast) |
| Full desktop keyboard with Win/Alt keys | onboard |
| Custom size with wvkbd | Custom layout XML |
| Touchscreen-only device | wvkbd (mobile-optimized) |
