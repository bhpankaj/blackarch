# GTK and Shell Text Scaling

Depth for the desktop-text-scaling skill: the exact keys, their ranges, how GTK
reloads a change, and the anchor arithmetic.

## gsettings keys

Schema `org.gnome.desktop.interface`:

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `text-scaling-factor` | `d` (double) | `1.0` | range `0.5`–`3.0`; multiplies every GTK text size |
| `font-name` | `s` | `'Adwaita Sans 11'` | last whitespace-separated token is the point size |
| `scaling-factor` | `uint32` | `0` | per-monitor integer scale, **not** text; `0` = unset |

Read/write with `gsettings get|set|reset org.gnome.desktop.interface
<KEY>`; `gsettings range <schema> <key>` prints the allowed range and is worth
running before clamping a value in a tool. `dconf read /org/gnome/desktop/interface/text-scaling-factor`
is the same store without gsettings.

Do not confuse `text-scaling-factor` (fractional text multiplier) with
`scaling-factor` (integer whole-output scale). A tool that sets the wrong one
appears to do nothing to text.

## Reload behaviour

With no `xsettingsd` and no GNOME settings daemon in the session, GTK reads
these keys at startup. A `gsettings set` therefore:

- affects **newly started** GTK apps immediately;
- does **not** resize already-running ones (a restart of the app is needed);
- does not touch Qt apps, which use `QT_SCALE_FACTOR` / `qt5ct` / `qt6ct`.

If live propagation is required, install and start `xsettingsd` and point it at
an xsettings config; that is a separate setup step, not something a one-shot
write can achieve.

## Anchor arithmetic

Pick one anchor and keep it consistent across the layers. With
**12px shell base == 1.0 == 12pt**:

```
factor        = px / 12
px            = round(factor * 12)
terminal_pt   = px                       # 1pt per px at the 12px anchor
quantized     = round(round(font_pt * px / 12) / font_pt, 4)   # whole-point GTK
```

The quantized form is what a shell command should write when the GTK interface
font must land on a whole point size: derive the factor from the *rounded*
point size rather than the raw ratio.

## Startup pin

Anything executed at session start that sets the factor to a literal defeats the
user's saved choice. Make it conditional on the value still being the default:

```sh
# apply the default only when the user has not chosen anything
[ "$(gsettings get org.gnome.desktop.interface text-scaling-factor)" = "1.0" ] \
  && gsettings set org.gnome.desktop.interface text-scaling-factor 1.5
```

Test both branches: a default value must be replaced, a user-set value must be
left alone.
