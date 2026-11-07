---
name: hyprland-keybinding-safety
description: "Use when editing Hyprland keybindings. Never destructive."
version: 1.0.0
author: black
metadata:
  hermes:
    tags: [hyprland, keybindings, safety, blackarch, window-manager]
license: MIT
---

# Hyprland Keybinding Safety

Rules for inspecting or editing the Hyprland keybindings on this machine. They
are absolute — the user has stated them explicitly and repeated them.

## When to Use

- Reviewing or updating `~/.config/hypr/blackarch/binding_*.lua`
- Adding a new keybinding to the Blackarch Hyprland config
- Auditing what a key chord does before reusing it
- Any task that asks you to inspect, "fix up", or regenerate the keybindings

## Hard rules

1. **No keybinding may log out, reboot, shut down, exit the session, or kill.**
   No exceptions, including "behind a confirmation prompt" or "only with a
   modifier stack".
2. **Nothing is ever bound to the DELETE key.** Not a destructive action, not a
   safe one, not as a fallback. DELETE is simply not a keybinding.

Rule 2 supersedes any weaker wording you may remember ("avoid DELETE",
"especially DELETE") — it is a prohibition, not a preference.

## What this means in practice

The bindings that used to exist and are gone:

| Binding | What it did |
|---|---|
| `mainMod + DELETE` | close every window |
| `mainMod + SHIFT + DELETE` | exit Hyprland |
| `mainMod + CTRL + DELETE` | shutdown |
| `mainMod + ALT + DELETE` | reboot |

None of them comes back, and no new binding takes over a DELETE chord. The
power actions themselves (`blackarch-cmd-shutdown`, `blackarch-cmd-reboot`,
`blackarch-hyprland-window-close-all`) remain available as commands and can
stay on PATH — the rule is about *keybindings*, not about deleting the tools.

## How to verify

```sh
grep -rn "DELETE" ~/.config/hypr/blackarch/binding_*.lua
```

Expect zero hits. If this returns anything, a destructive binding is back —
remove it and say so.

When the bindings are spread across several `binding_*.lua` files, grep all of
them at once rather than reading one file and concluding the job is done; a
later-loaded file can carry a chord an earlier one does not.

## Related

- The ported commands these bindings call are documented in the dispatcher
  skill: `linux-distro-portability` → `references/command-family-dispatcher.md`.
- Prefer removing a dangerous binding over replacing it with a safe one on the
  same chord: the rule is about the chord, not the action.
