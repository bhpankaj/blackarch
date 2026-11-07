# Kodachi Called Binaries & Scripts Inventory

Evidence-backed inventory of every binary and script the Kodachi v9.0.1
dashboard suite launches or references. Verified on this host against
`/opt/blackarch/dashboard/hooks/` (the real binary suite) and
`/opt/blackarch/dashboard/hooks/binaries-update-scripts/`.

## How to verify

```bash
ls -la /opt/blackarch/dashboard/hooks/
ls -la /opt/blackarch/dashboard/hooks/binaries-update-scripts/
file /opt/blackarch/dashboard/hooks/kodachi-dashboard
strings /opt/blackarch/dashboard/hooks/kodachi-dashboard | grep -E '/(usr|bin|sbin|opt)|\.sh|curl|wget|tor|jq'
tail -f /opt/blackarch/dashboard/hooks/logs/*.log
```

## Launcher scripts

- `bin/blackarch-kodachi-launcher` — standalone launcher. Resolves
  `DASHBOARD_BIN=/opt/blackarch/dashboard/hooks/kodachi-dashboard`, ensures a
  `/usr/local/bin/kodachi-dashboard` symlink, checks deps, then
  `exec "$DASHBOARD_BIN" --no-gpu "$@" | tee /tmp/kodachi-dashboard.log`.
- `dashboard/kodachi-dashboard.desktop` — desktop entry
  (`Exec=/opt/blackarch/dashboard/hooks/kodachi-dashboard`).
- `binaries-update-scripts/kodachi-binary-install.sh` — Arch-adapted
  installer (pacman), ported from the Debian `blackarch-binary-install.sh`.

## Main binary

- `hooks/kodachi-dashboard` — ELF 64-bit, v9.0.1, Tauri + Svelte desktop app
  (Rust: gtk-0.18, webkit2gtk, zbus, reqwest, async-executor, cookie_store).
  Requires `libwebkit2gtk-4.1`, `libgtk-3`. Default hooks path is
  `/opt/kodachi/dashboard/hooks/` (env `KODACHI_HOOKS_DIR`); stays at
  `/opt/blackarch/dashboard/` via symlink or env override.

## AI / service binaries (`hooks/`, ELF)

`ai-admin`, `ai-cmd`, `ai-discovery`, `ai-gateway`, `ai-learner`, `ai-monitor`,
`ai-scheduler`, `ai-trainer` (8 binaries).

## Security / network binaries (`hooks/`, ELF)

`tor-switch`, `dns-switch`, `routing-switch`, `dns-leak`, `ip-fetch`,
`online-auth`, `online-info-switch`, `conky-status`.

## System binaries (`hooks/`, ELF)

`health-control`, `integrity-check`, `permission-guard`, `deps-checker`,
`global-launcher`, `workflow-manager`, `kodachi-soc`,
`kodachi-session-helper`, `logs-hook`.

## Update / helper scripts (`hooks/binaries-update-scripts/`)

- `kodachi-autoshield.sh` — production login-session status display, installed
  at `/etc/profile.d/blackarch-autoshield.sh` by the live-build overlay.
- `kodachi-autoshield-shell.sh` — MANUAL-TESTING variant (no early-return
  gating; top-level signal wrappers). NOT installed at profile.d; do not source.
- `kodachi-deps-install.sh` — dependency installer (Debian).
- `kodachi-backup` — restic wrapper, backs up DATA only (no hardcoded
  usernames/paths; passphrase from prompt or `RESTIC_PASSWORD`).
- `kodachi-debug-collector.sh` — Arch-adapted diagnostic collector.
- `oniux-launcher` — safe `oniux` wrapper (enables
  `kernel.unprivileged_userns_clone`, disables AppArmor userns restriction).
- `welcome` — manual wrapper to run the autoshield script interactively.
- `dnscrypt-resolvers/` — directory (resolver list).

## Dependencies the launcher expects

`jq`, `curl`, `wget`, `tor` (missing → WARN, `sudo pacman -S <missing>`).

## Log-evidenced runtime calls (from `hooks/logs/`)

Confirmed active by recent log entries:

- `tor-switch` — checks/corrects file perms, lists Tor instances.
- `dns-switch` — pi-hole status, DNSCrypt status, auto-detects mode (legacy).
- `routing-switch` — status checks; needs cached profiles per provider.
- `ip-fetch` — fetches IP from `https://kodachi.cloud/apps/ip-check-plain.php`;
  Tor quorum via `https://www.kodachi.cloud/apps/tor.php`.
- `online-auth` — binary signature verification (per-binary), cert pinning,
  secure session login status.
- `online-info-switch` — crypto prices (BTC, ETH, XMR, NEAR, AZERO), metals,
  releases, rss.
- `conky-status` — periodic status refresh (15s cadence); adapters
  `online-info-switch`, `system`, `display_power`.
- `kodachi-soc` / `kodachi-session-helper` — SoC + session watchdog
  (evdev inactivity warnings).
- `workflow-manager` — lists workflow templates.
- `security_scoring` — computes comprehensive score (logs 18/100 Critical).
- `hostname` — sets random hostname (e.g. "Sony-Xperia-1-V").
- `display_power` — calls `conky-status`.

## Pitfalls

- `dashboard/kodachi.html` is a misplaced Netscape bookmark file, NOT the UI.
  Verify with `file`/`head` before assuming.
- `hooks/profiles/`, `hooks/backups/`, `hooks/signkeys/` are empty — normal for
  a fresh binary install.
- A missing `libwebkit2gtk-4.1.so.0` / `libgtk-3.so.0` in `ldd` is a real
  blocker, not cosmetic.
- Reference the user preference: prefer open libcamera over proprietary AUR
  stacks when analyzing dashboard/webcam integrations.
