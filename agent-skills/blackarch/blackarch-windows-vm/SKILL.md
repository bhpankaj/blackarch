---
name: blackarch-windows-vm
description: Use when installing or managing the Blackarch Windows VM.
---

## When to Use
Installing or managing the Windows VM via `blackarch-windows-vm install|launch|connect|app|stop|status|remove`, when the "Windows" / "Windows Connect" / "Windows Edge" / "Windows PowerShell" / "Windows App" desktop entry or apps-menu item is involved, or when a Windows GUI app is to be opened in its own window on the Linux desktop.

## Prerequisites
- `/dev/kvm` exists and the user is in the `kvm` group.
- Docker daemon running and enabled: `systemctl enable --now docker`. The user must be in the `docker` group so `priv` can run docker actions directly when sudoless Docker is on.
- `docker-compose` installed: `sudo pacman -S docker-compose`. The script's `dc()` shells out to the standalone `docker-compose`, not the `docker compose` plugin.
- `freerdp`, `openbsd-netcat`, `gum`: `blackarch-pkg-add freerdp openbsd-netcat gum`.
- At least 42 GB free (32 GB disk + 10 GB image overhead).

## Privilege model (the usual blocker)
`priv_target()` refuses to pkexec a script unless it AND every parent directory up to `/` are root-owned with no group/other write bits. A user-owned `/opt/blackarch` checkout fails with `refusing to run a non-root-owned command as root`, so `write_compose` (which always elevates) aborts the install.
Fix: install a root-owned copy and point the helper at it:

    sudo install -Dm755 -o root -g root /opt/blackarch/bin/blackarch-windows-vm /usr/local/sbin/blackarch-windows-vm
    # then set priv_target()'s candidate= to /usr/local/sbin/blackarch-windows-vm

`up`/`down`/`status` run directly for a docker-group user once the lock dir and pinned bind mounts exist; `write_compose` and `remove` always elevate.

## Install
`blackarch-windows-vm install` is interactive (gum): RAM, CPU cores, disk size, Windows username/password, confirmation. It writes the root-owned compose `/var/lib/blackarch/windows/docker-compose.yml` and private credentials `~/.config/windows/credentials`, then runs `docker-compose up -d`, pulling `dockurr/windows` and starting container `blackarch-windows`. Run it in a real terminal (a floating kitty window works); it cannot run unattended, and the polkit dialog for `write_compose` needs the user's password.

## Launch / connect / stop / status
- `blackarch-windows-vm launch` starts the container if needed, waits for the guest, then opens RDP (`xfreerdp3`, 127.0.0.1:3389). `--keep-alive` keeps the VM running after RDP closes (default auto-stops).
- `blackarch-windows-vm connect` (alias `rdp`) is connect-only: it reads the saved credentials and opens RDP against the port the compose publishes. It never calls `priv`, `dc`, `up`, or `down`, so it cannot start or stop the VM — safe to expose as a menu entry next to "Windows".
- `blackarch-windows-vm stop` stops it.
- `blackarch-windows-vm status` prints RUNNING / web UI / RDP.
- Web monitor: http://127.0.0.1:8006 (HTTP 401 is expected; the console is protected when `PROTECT=Y`).

### Connect details
- Credentials come from `~/.config/windows/credentials` (`USERNAME=` / `PASSWORD=`, 0600), falling back to the compose only when it is readable. `read_credential` treats an empty value as missing.
- The target is resolved from the compose's published binding (`HOST:PORT:3389/tcp`), not hardcoded, so a configuration with a different host port still connects. `rdp_target` reads the file into a variable first so an unreadable compose reports a clean error instead of a raw `sed` failure.
- `connect` reuses `launch`'s realm-less `~/.config/windows/krb5.conf` and Hyprland scale detection.
- Verify the command without opening a window: put a stub `xfreerdp3` on PATH that echoes its argv, then run `connect` and check the `/u:`, `/p:`, `/v:` arguments.

## Running a Windows app in its own window (RemoteApp)
`blackarch-windows-vm app <name>` starts one Windows program inside the VM and shows only its window on the Linux desktop. The mechanism is RDP RemoteApp (RAIL), not a shared desktop:

    blackarch-windows-vm app edge          # built-in
    blackarch-windows-vm app powershell    # built-in
    blackarch-windows-vm app               # picker (blackarch-menu-select)
    blackarch-windows-vm app list
    blackarch-windows-vm app add <name> <windows-path> [args]
    blackarch-windows-vm app remove <name>

- Built-ins live in `default_apps()`; user entries in `~/.config/windows/apps` (`name|path|args`) override a built-in of the same name. `app add`/`app remove` rewrite that file atomically and preserve other entries.
- `launch_app()` builds `/app:program:<path>,name:<name>[,cmd:<args>]`. The spec is a single argv element, so a path with spaces is fine; an `args` value must not contain a comma (it would split the spec).
- FreeRDP 3.32 on this host DOES carry RAIL (`WITH_CLIENT_CHANNELS=ON`, `INFO_HIDEF_RAIL_SUPPORTED`), contrary to the usual "FreeRDP 3 dropped RemoteApp" advice. Verified live: the guest negotiates `TS_RAIL_ORDER_HANDSHAKE_EX` and a real per-app window appears. `xfreerdp3 /help` lists `/app: program:[<path>|<||alias>],cmd:...,name:...`.
- The window class is `RAIL:<id>`; `config/hypr/blackarch/rules.lua` floats those windows and sizes them to 0.7 of the monitor, with a later rule keeping `PopupHost` helper windows at 1x1 (without it every helper window is blown up to app size).
- Edge is slow to show: allow ~30-60s. PowerShell and Notepad appear in a few seconds.

### Caveat: remote apps persist
The guest is a single autologoned Windows session, so a RemoteApp program keeps running after its local window is closed, and the next `app` connection re-announces the windows of every app started this way. Launching PowerShell can therefore also re-show a previously launched Edge. Close the unwanted windows locally (`hyprctl clients -j | jq -r '.[] | select(.class|startswith("RAIL:")) | .address'` then `hyprctl dispatch closewindow address:<a>`), or stop the VM to clear them. There is no per-app session isolation while one user account owns the session.

## Menu entries
The default menu has a `windows` submenu (`windows.install` / `launch` / `connect` / `edge` / `powershell` / `app`) in `default/blackarch/blackarch-menu.jsonc`. The generated XDG app menus get their rows from desktop entries in `~/.local/share/applications/` (`windows-vm*.desktop`), written by `write_windows_desktop()` at install time. Do NOT hand-add rows to `default/blackarch/menus/*.jsonc` for these: `blackarch shell generate` rebuilds those files from the desktop entries and wipes hand edits.

## Camera in the Windows VM
The guest has no virtual-webcam device and the built-in sensor is MIPI (not USB), so the camera reaches Windows as an RTSP stream, not a USB passthrough:
- Host: `blackarch camera stream` (module `blackarch_modules/blackarch_camera_stream.py`) publishes the relay loopback (`/dev/video0`, label "Camera Relay") as H.264 RTSP on `0.0.0.0:8554/camera`. Needs `gst-rtsp-server` and `gst-plugins-ugly` (x264enc). The loopback is natively 1920x1080 YUYV; the streamer negotiates that and scales to `--width/--height` (default 1280x720).
- Windows: connect to `rtsp://172.18.0.1:8554/camera` (the docker bridge gateway; the container can reach it) with a virtual-webcam app (OBS Studio Media Source + Start Virtual Camera, or an IP-camera app), then pick that virtual camera in the target app.
- The stream is not persistent by default; run it in a terminal or add a systemd user unit.

## Pitfalls
- Refresh the root-owned copy after editing the repo script, or privileged actions run stale code: `sudo install -Dm755 -o root -g root /opt/blackarch/bin/blackarch-windows-vm /usr/local/sbin/blackarch-windows-vm`.
- `~/.windows` (storage) and `~/Windows` (shared) are bind-mounted from root-owned anchors under `/var/lib/blackarch/windows/mounts/users/<uid>/`. Never move the compose or those anchors under `$HOME` — the elevated writer derives the anchors from the authenticated uid and validates them.
- The `install.windows` menu action calls `blackarch-launch-floating-terminal-with-presentation`, which is absent from the repo, so it does nothing; invoke the installer directly in a terminal. The installer is now reached through the `windows` submenu as `windows.install`. A row that runs a command directly (`blackarch-windows-vm connect`, `... app edge`) works without that launcher.
- A Windows menu row must be a plain action row (omit `kind`) and its id prefix must resolve to an existing menu row — see the menu-row rules in the blackarch-dispatcher skill and its `scripts/verify-menu-row.js`. `kind:"app"` rows launch through `AppLibrary.launch()` -> `gtk-launch <appId>.desktop` and IGNORE the row's `action`, so an app-kind row for a custom command silently launches the wrong thing.
- The generated XDG menu rows come from `~/.local/share/applications/windows-vm*.desktop`; create or edit those files rather than `default/blackarch/menus/*.jsonc`, which `blackarch shell generate` overwrites.
