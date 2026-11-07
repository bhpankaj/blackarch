# Profile.d sourcing: bash, zsh, non-interactive, sudo

When a script installs `/etc/profile.d/<name>.sh` into a new Arch root, it must
be sourced in every shell context — interactive login/non-login, non-interactive
(bash `BASH_ENV`, zsh `ENV`), and through sudo.

## What each mechanism covers

| Context | Mechanism | File / setting |
|---|---|---|
| Bash interactive login | `/etc/profile` sources `/etc/profile.d/*.sh` | profile.d file (0644) |
| Bash interactive non-login | `/etc/bash.bashrc` | append `[ -r /etc/profile.d/<name>.sh ] && . ...` |
| Bash non-interactive | `BASH_ENV` env var | `export BASH_ENV=/etc/profile.d/<name>.sh` inside profile.d |
| Zsh interactive login | `/etc/zprofile` (sources `/etc/profile`) | profile.d file |
| Zsh interactive non-login | `/etc/zsh/zshrc` | append same source line |
| Zsh non-interactive | `ENV` env var | `export ENV=/etc/profile.d/<name>.sh` inside profile.d |
| Sudo (any) | `env_keep` + `secure_path` | `/etc/sudoers.d/<name>` with `Defaults env_keep += ...` and `Defaults secure_path` including `/opt/blackarch/bin` |

## Pitfall: sudo resets PATH by default

`env_reset` strips almost everything. Even when the user's shell sourced
profile.d, `sudo cmd` receives a minimal environment with only `secure_path`.
Always pair profile.d installation with a sudoers file:

```
Defaults env_keep += "BLACKARCH_PATH PATH BASH_ENV ENV"
Defaults secure_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/blackarch/bin"
```

Mode must be `440`. Without `secure_path`, `/opt/blackarch/bin` disappears from
PATH under sudo regardless of `env_keep`.
