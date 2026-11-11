# Windows VM (`blackarch-windows-vm`)

The Windows VM runs the `dockurr/windows` container under Docker with KVM and is
reachable over RDP at `127.0.0.1:3389`. Managed by `bin/blackarch-windows-vm`.

## Commands

    blackarch-windows-vm install     # interactive first-time setup
    blackarch-windows-vm launch      # start (if needed) + connect via RDP; auto-stops on close
    blackarch-windows-vm launch -k   # keep the VM running after RDP closes
    blackarch-windows-vm connect     # connect only, against the running VM (no start/stop)
    blackarch-windows-vm app [name]  # open a Windows app in its own window (RemoteApp)
    blackarch-windows-vm stop
    blackarch-windows-vm status
    blackarch-windows-vm remove

`launch` and `connect` call `xfreerdp3` with a realm-less
`~/.config/windows/krb5.conf` so NLA falls straight through to NTLM instead of
querying a KDC. `connect` resolves the published RDP port from the compose rather
than hardcoding 3389.

## Running a Windows app in its own window

`app` uses RDP RemoteApp (RAIL): the program runs inside the VM and only its
window is shown on the Linux desktop.

    blackarch-windows-vm app edge          # built-in
    blackarch-windows-vm app powershell    # built-in
    blackarch-windows-vm app               # picker
    blackarch-windows-vm app list
    blackarch-windows-vm app add <name> <windows-path> [args]
    blackarch-windows-vm app remove <name>

Built-ins are in `default_apps()`; `~/.config/windows/apps` (`name|path|args`)
overrides a built-in of the same name. FreeRDP 3.32 on this host carries RAIL
(`WITH_CLIENT_CHANNELS=ON`), so `/app:program:<path>,name:<name>` works — the
window class is `RAIL:<id>`, and `config/hypr/blackarch/rules.lua` floats those
windows at 0.7 of the monitor while keeping `PopupHost` helpers at 1x1.

Caveat: the guest is a single autologoned Windows session, so a RemoteApp program
keeps running after its local window is closed and the next `app` connection
re-announces the windows of every app started this way.

## The installer is interactive — run it in a floating terminal

`install` drives `gum choose` / `gum input` / `gum confirm` prompts (RAM, CPU
cores, disk size, Windows username/password, confirmation). It exits if stdin is
not a TTY, so it cannot be piped or run headless. Launch it in a floating kitty
window and let the user answer:

    kitty --class kitty-float -e bash -c 'blackarch-windows-vm install; echo "rc=$?"; sleep 3600'

`--class kitty-float` matches the floating-window rule in
`config/hypr/blackarch/rules.lua`; the trailing `sleep` keeps the window open so
the result is readable after the installer exits.

## Privilege

- `write_compose` ALWAYS elevates: the compose file is root-owned at
  `/var/lib/blackarch/windows/docker-compose.yml`, so a polkit password prompt
  appears even when sudoless Docker is on.
- `blackarch-sudo-docker` returning 0 means docker-group users run the daemon
  operations directly, without pkexec.
- The installer installs `freerdp`, `openbsd-netcat` and `gum` via
  `blackarch-pkg-add`.
- `connect` and `app` never elevate: they only read the credentials and talk to
  the already-running daemon.

## State and verification

- Config/compose: `/var/lib/blackarch/windows/` (root-owned).
- Private RDP credentials: `~/.config/windows/credentials` (0600).
- Windows app registry: `~/.config/windows/apps`.
- Launchers: `~/.local/share/applications/windows-vm*.desktop`, created by
  install via `write_windows_desktop()`.
- Check with `blackarch-windows-vm status`, `docker ps`, and the presence of the
  launcher files.

## Menu entries

The default menu (`default/blackarch/blackarch-menu.jsonc`) has a `windows`
submenu: `windows.install`, `windows.launch`, `windows.connect`, `windows.edge`,
`windows.powershell`, `windows.app`.

The generated XDG app menus (`default/blackarch/menus/*.jsonc`) get their Windows
rows from the `~/.local/share/applications/windows-vm*.desktop` files, which
`blackarch shell generate` reads. Do not hand-add Windows rows to those files —
the generator overwrites them.

Verify a row the way the shell renders it:

    node agent-skills/blackarch-dispatcher/scripts/verify-menu-row.js \
      default/blackarch/blackarch-menu.jsonc windows.edge windows.powershell
