---
name: ssh-agent-setup
description: Configure ssh-agent for persistent SSH key management.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [ssh, agent, arch, linux, key-management]
    related_skills: []
---

# SSH Agent Setup

Configure ssh-agent so SSH key passphrases are entered once and remembered across sessions.

## When to Use

- User wants to avoid entering SSH key passphrase on every connection
- Setting up persistent ssh-agent on Arch/BlackArch Linux
- Migrating from gnome-keyring ssh component (removed in v50.0+)

## Procedure

1. **Create systemd user service** at `~/.config/systemd/user/ssh-agent.service`:
   ```ini
   [Unit]
   Description=SSH key agent

   [Service]
   Type=simple
   ExecStart=/usr/bin/ssh-agent -D -a %t/ssh-agent.socket
   Restart=on-failure

   [Install]
   WantedBy=default.target
   ```

2. **Enable and start**:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now ssh-agent.service
   ```

3. **Set environment variable** in shell rc (`.zshrc` / `.bashrc`):
   ```bash
   export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/ssh-agent.socket"
   ```

4. **Install askpass helper** for GUI passphrase prompt:
   ```bash
   sudo pacman -S --noconfirm x11-ssh-askpass
   ```

5. **Add key** (one-time, GUI prompt appears):
   ```bash
   ssh-add ~/.ssh/id_ed25519
   ```

6. **Verify**:
   ```bash
   ssh-add -l    # lists loaded keys
   ssh-add -L    # shows public keys
   ```

## Pitfalls

- **gnome-keyring 50.0+ removed the ssh component.** Do NOT attempt `gnome-keyring-daemon --components=ssh` — it silently fails to provide `SSH_AUTH_SOCK`. Use systemd user service instead.
- **Keys are NOT persisted across reboots.** ssh-agent holds keys in memory only. After reboot, run `ssh-add` once. For fully persistent storage, use a hardware key or accept the one-time entry.
- **Ensure `loginctl show-user <user>` shows `Linger=yes`** so the systemd user instance (and thus ssh-agent) starts at boot without an active login session. Enable with `sudo loginctl enable-linger <user>`.
- **The socket path uses `%t` (runtime dir)** which expands to `$XDG_RUNTIME_DIR` (typically `/run/user/<uid>`). Do not hardcode `/run/user/1000` — use the environment variable.
