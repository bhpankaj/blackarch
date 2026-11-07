#
# ~/.bash_profile
#

[[ -f ~/.bashrc ]] && . ~/.bashrc
# Source profile (sets PATH, blackarch env, non-interactive BASH_ENV).
[[ -f ~/.profile ]] && . ~/.profile

# Hermes Agent command
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
