---
name: matugen-theming
description: Generate theme colors from images using matugen.
version: 1.0.0
author: black
license: MIT
metadata:
  hermes:
    tags: [theming, matugen, colors, wallpaper]
    related_skills: [blackarch]
---

# Matugen Theming

Generate theme colors from images using matugen.

## When to Use

- User wants to generate a color scheme from a wallpaper or image
- User wants to create or update theme files with colors extracted from an image
- User mentions matugen, color extraction, or wallpaper-based theming

## Workflow

1. **Extract colors from image:**
   ```bash
   matugen image --show-source-colors <image>  # Show possible source colors
   matugen image --prefer=darkness --json hex <image>  # Generate colors in hex format
   ```

2. **Map colors to theme files:**
   - `colors.toml` - main theme colors
   - `hyprland.conf` - window manager colors
   - `hyprlock.conf` - lock screen colors
   - `mako.ini` - notification colors
   - `btop.theme` - system monitor colors
   - `neovim.lua` - editor colors
   - `shell.toml` - shell colors
   - `gtk.css` - GTK colors
   - `waybar.css` - bar colors
   - `vscode.json` - VS Code colors

3. **Use an existing theme as reference:**
   - Copy the file structure from an existing theme
   - Replace the colors with the generated ones
   - Keep the file format and structure the same

## Pitfalls

- matugen requires `--prefer` flag when multiple colors are found and no terminal is detected
- The generated colors are in a specific format that needs to be mapped to theme file formats
- Always confirm with the user before generating large numbers of files
