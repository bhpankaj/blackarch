---
name: desktop-text-scaling
description: "Scale text across a Wayland desktop consistently."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [text-scaling, gtk, gsettings, wayland, hyprland, quickshell, accessibility]
---

# Desktop Text Scaling

## When to Use

Use when changing apparent text size across a Wayland desktop — a panel slider,
a CLI command, a settings toggle, or "text is too small/large everywhere".
Triggers: "make text bigger", "add a text size slider", "the slider does
nothing", "scale text across apps", "GTK text is huge after a setting changed".

Apparent text size is not one setting. It is at least three, and a change that
touches only one produces a desktop where the panel, the apps, and the
terminals disagree. This skill covers driving them together and the traps that
make a change appear to do nothing.

## The moving parts

| Layer | Knob | Where it lives |
| --- | --- | --- |
| Shell (Quickshell/wayland bars & panels) | font base-size | the shell's `shell.toml` `[font] base-size`; every token derives from it |
| GTK / GNOME apps | `org.gnome.desktop.interface text-scaling-factor` | gsettings/dconf, range `0.5`–`3.0`, default `1.0` |
| Terminals | font point size | each emulator's own config |

Anchor them to one value so they stay proportional: **shell 12px == factor 1.0
== terminal 12pt** is the usual baseline, and a shell base-size maps to a factor
by `factor = px / 12`.

## Procedure

1. **Find the existing knob before writing one.** A distro shell or desktop
   almost always already has a text-size command, a settings entry, or a theme
   token. Search the bin directory and config tree first (`grep -rn
   "text-scaling-factor\|base-size\|font-size"`). Reusing it keeps the panel,
   the CLI, and any external tool agreeing; adding a second one creates two
   sources of truth that drift.
2. **Pick the anchor and document it.** Whatever single value the slider
   carries, state the mapping in a comment at the declaration so the next reader
   can invert it.
3. **Drive all layers from that one value.** One command should write the shell
   token, the GTK factor, and the terminal fonts together, so no layer is left
   behind. Order matters if one layer is watched live (see step 4).
4. **Close the loop with a read-back.** After writing, read the value back from
   the real target and report *that*, not the value you just set. A write can be
   rejected (out of range, read-only, a schema default silently re-applied) and
   the caller cannot tell otherwise.
5. **Check for a startup pin that will stomp the value.** Anything that runs at
   session start and sets the factor literally — an autostart script, a
   `hyprland.start` handler, a systemd unit — will silently undo whatever the
   user chose on the previous session. Grep the startup path and make it
   conditional on the value still being the default, or remove it.
6. **Verify per layer, not just in the panel.** Read each knob back through its
   own tool and confirm the number changed.

## Pitfalls

- **A `gsettings` write does not resize already-running GTK apps.** There is no
  settings daemon on a bare Hyprland/Wayland session, so `text-scaling-factor`
  is read at app startup: new windows pick it up, existing ones do not. Do not
  report the change as "nothing happened" from a stale window — open a new one
  to confirm. `xsettingsd` (or a GNOME settings daemon) would propagate it
  live; if a desktop needs live updates, that is a separate install.
- **Never pin the factor in a startup script.** Writing a literal at session
  start overrides the user's choice every login and the slider appears to reset.
  Gate it: only apply the default when the value is still the schema default.
- **Quantize the factor if the GTK interface font must land on whole points.**
  `gsettings font-name` carries a point size; a raw ratio yields fractional
  point sizes, and fractional GTK4 text clips at the ascenders on scale-1
  monitors. Round to the nearest whole point size and derive the factor from
  that.
- **A slider whose value is an index into a stop list cannot track an external
  write.** The knob must carry the real value; keep the stop list for stepping
  and tick marks only. See the widget-authoring skill for the QML mechanics.
- **A CLI that writes several config files must preserve each file's shape.**
  Upsert the key in place, leave sibling keys and other sections untouched, and
  do not invent or strip trailing newlines. See the bash-to-python porting
  reference for the harness recipe that proves this.
- **An off-notch value should be displayed as-is.** Rounding the header label to
  the nearest stop makes the UI lie about what the target is actually using.

## References

- `references/gtk-and-shell-scaling.md` — the gsettings keys and their ranges,
  the live-vs-restart reload behaviour, and the anchor arithmetic

**When the knob lives in a Quickshell panel**, the widget-side mechanics
(read-back parsing, the Process queue, IPC verification) belong to the
`quickshell-widget-authoring` skill — read it before wiring the slider.

