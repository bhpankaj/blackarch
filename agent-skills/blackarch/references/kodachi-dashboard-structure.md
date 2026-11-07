# Kodachi Dashboard Layout (`/opt/blackarch/dashboard/`)

Verified on this host: `/opt/blackarch/dashboard/` holds the Kodachi v9.0.1 binary suite.

## Verified structure

- `kodachi.html` — Netscape bookmark file (Bookmarks Toolbar), NOT a dashboard HTML. Do not treat it as the UI.
- `hooks/` — the real dashboard binary + services:
  - Main binary: `hooks/kodachi-dashboard` (ELF 64-bit, v9.0.1, Tauri + Svelte desktop app, requires `libwebkit2gtk-4.1`, `libgtk-3`)
  - AI/service binaries: `ai-*` (8 binaries)
  - Security/network: `tor-switch`, `dns-switch`, `routing-switch`, `dns-leak`, `ip-fetch`, `online-auth`, `online-info-switch`, `conky-status`
  - System: `health-control`, `integrity-check`, `permission-guard`, `deps-checker`, `global-launcher`, `workflow-manager`, `kodachi-soc`, `kodachi-session-helper`
  - Update scripts: `binaries-update-scripts/` (`kodachi-autoshield.sh`, `kodachi-deps-install.sh`, `kodachi-backup`, `kodachi-debug-collector.sh`, `welcome`, `oniux-launcher`)
  - Config: `config/` (`dashboard-settings.json`, `os-info.yaml` = v9.0.1 / arch-adapted, `build-meta.json`, 58 profile JSONs, `autoshield-settings.json`, `dns-database.json`)
  - Assets: `icons/`, `flags/` (240+ PNGs), `sounds/` (10 WAV/OGG/MP3), `fonts/`, `models/` (ONNX), `conky/` (lua + desktop autostart)
  - Site/docs: `others/site/` (gallery images, binary docs, architecture overview, changelog, sitemap, videos)
  - Data/DB: `data/learning.db`, `.soc-state/` caches
  - Logs: `logs/` per binary (e.g. `kodachi-dashboard-log.log`, `health-control-log.log`)
  - Results/signatures: `results/signatures/` (`.sig` + `.sig.info` for each binary) — all present

## Verification steps (evidence-backed)

Always verify with evidence before reporting something missing:

```bash
file /opt/blackarch/dashboard/hooks/kodachi-dashboard
ldd /opt/blackarch/dashboard/hooks/kodachi-dashboard
/opt/blackarch/dashboard/hooks/kodachi-dashboard -v --json-pretty
```

Expected: version 9.0.1; `ldd` shows GTK/WebKit libs resolved; no missing dynamic libraries.

## What's actually missing / empty

- `hooks/profiles/` — empty (should contain user profile data)
- `hooks/backups/` — empty
- `hooks/signkeys/` — empty (should contain signing keys)
- `results/` — minimal (`myip.json`, `ip_history.json`, `ip-fetch-providers.json`); no full health-check output
- No `.desktop` launcher or dashboard autostart at `/opt/blackarch/dashboard/` (only `conky/autostart/` exists under hooks)
- `kodachi.html` bookmark file is misplaced at dashboard root; it belongs to a browser profile, not the dashboard directory. It is a Netscape bookmark toolbar (Bookmarks Toolbar / Security Testing links), not the UI. The actual dashboard is the native binary `hooks/kodachi-dashboard`.
- No `.desktop` launcher at `/opt/blackarch/dashboard/` (only `conky/autostart/` exists under hooks). Fix: create `kodachi-dashboard.desktop` with `Exec=/opt/blackarch/dashboard/hooks/kodachi-dashboard`, `Icon=/opt/blackarch/dashboard/hooks/icons/kodachi-dashboard.png`.
- `hooks/icons/` — MISSING `.svg` branding files (`kodachi-dashboard.svg`, `kodachi.svg`). Only `kodachi-dashboard.png` exists. Binary references `/opt/kodachi/icons/*.svg` and `/usr/share/icons/kodachi/*.svg`.
- Binary default hooks path is `/opt/kodachi/dashboard/hooks/` (per embedded strings and `KODACHI_HOOKS_DIR` env). Since everything stays at `/opt/blackarch/dashboard/`, either export `KODACHI_HOOKS_DIR=/opt/blackarch/dashboard/hooks` or create symlink `ln -s /opt/blackarch/dashboard/hooks /opt/kodachi/dashboard/hooks`.

## Pitfalls for future analysis

- Do not assume a file named `kodachi.html` is the dashboard UI — verify with `file` and `head` first.
- Verify binary compatibility with `ldd`, not just `ls -l`. A missing `libwebkit2gtk-4.1.so.0` or `libgtk-3.so.0` is a real blocker.
- Empty `profiles/`, `backups/`, `signkeys/` are normal for a fresh binary install; they are not errors unless the user expects backed-up profiles or signed keys.
- Reference the user preference: prefer open libcamera (`v0.7.2`) over proprietary AUR stacks (`libcamera-ipu6`, `icamerasrc`) when analyzing webcam/dashboard integrations.
