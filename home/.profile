export TERM=xterm-256color
export EDITOR=nvim
export VISUAL=nvim
# Use Kvantum as the style
export QT_STYLE_OVERRIDE=kvantum
# Use qt5ct/qt6ct for settings management
export QT_QPA_PLATFORMTHEME=qt5ct
export CC=gcc
export LD=ld.bfd
export KERNELDIR=/usr/lib/modules/$(uname -r)/build

# Hermes Agent command
# Source blackarch profile for interactive and non-interactive shells.
[ -r /etc/profile.d/blackarch.sh ] && source /etc/profile.d/blackarch.sh

case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
alias gda='git add'
alias gdc='git commit -m'
alias gdf='git diff'
alias gdp='git push'
alias gds='git status' 
