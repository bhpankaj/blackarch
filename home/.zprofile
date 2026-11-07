# Portable zprofile for root and any user (no hardcoded /home paths).
# Source blackarch profile for interactive and non-interactive zsh login shells.
[ -r /etc/profile.d/blackarch.sh ] && source /etc/profile.d/blackarch.sh

# Hermes Agent command
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
# Auto-launch start-hyprland from tty
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  exec start-hyprland
fi
