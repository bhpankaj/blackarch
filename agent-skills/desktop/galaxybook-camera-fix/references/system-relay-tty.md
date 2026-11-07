# System-level camera relay for TTY unlock

When `howdy` PAM (configured in `/etc/pam.d/hyprlock`) must access `/dev/video0` before the first user login, a user-level `systemd --user` service (`camera-relay.service`) is insufficient — it starts after the session.

Use a system-level service (`/etc/systemd/system/camera-relay.service`):

- `Before=getty.target systemd-user-sessions.service`
- `After=local-fs.target`
- `WantedBy=multi-user.target`
- Same `ExecStart` (`/usr/local/bin/camera-relay start --on-demand`), `ExecStop`, env vars (`LIBCAMERA_IPA_MODULE_PATH`, `GST_PLUGIN_PATH`, `LD_LIBRARY_PATH`) as the open libcamera user service.
- `v4l2loopback` loaded at boot (`/etc/modules-load.d/v4l2loopback.conf`).

Enable: `systemctl daemon-reload && systemctl enable camera-relay.service`.

This applies to the open libcamera stack (`pacman` preferred). The proprietary AUR `--ipu6` path uses `v4l2-relayd.service` (system-level by design); do not mix the two.
