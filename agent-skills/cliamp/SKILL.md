---
name: cliamp
description: Control the cliamp terminal music player.
version: 1.0.0
---

# cliamp — Terminal Music Player

## Always-On Rules

1. **Daemon mode is required for non-TTY environments.** When running cliamp in background (terminal tool with `background=true`, cron, or any context without a real TTY), always pass `--daemon` (or `-d`). Without it, cliamp fails with `bubbletea: error opening TTY`.
2. **Provider must be specified for remote sources.** Use `--provider youtube` for YouTube URLs, `--provider ytmusic` for YouTube Music, etc. Check `cliamp --help` for the full provider list.
3. **YouTube/YouTube Music require credentials, and cookie auth runs through yt-dlp.** The provider needs `client_id`/`client_secret` or `cookies_from` in the **`[ytmusic]`** section of `~/.config/cliamp/config.toml` — the `[youtube]` section is not read for this, and a top-level `cookies_from` is likewise ignored. Without either, playback fails with "YouTube: no credentials available." `cookies_from` is handed straight to `yt-dlp --cookies-from-browser`, so it accepts **only yt-dlp's browser names** (`brave`, `chrome`, `chromium`, `edge`, `firefox`, `opera`, `safari`, `vivaldi`, `whale`). A browser yt-dlp doesn't recognise breaks cookie decryption.
4. **Always spell out the keyring backend: `cookies_from = "<browser>+gnomekeyring"`.** The value's grammar is `BROWSER[+KEYRING][:PROFILE]`. Without the suffix yt-dlp infers the backend from the desktop environment and, on a bare window manager (Hyprland and friends) where no `DESKTOP_SESSION` is exported, falls back to BASICTEXT — which has no key, so every `v11` cookie fails to decrypt with `no key found` even for a fully supported browser. To reach a browser yt-dlp does not list (a Chromium fork), alias it onto a supported name instead of exporting files — see `references/browser-cookie-auth.md`.
5. **Use `--auto-play` to start immediately.** Without it, cliamp loads but doesn't begin playback.
6. **cliamp is a singleton — check for a running instance before starting one, and never kill an instance you did not start.** All control commands talk to a single socket at `~/.config/cliamp/cliamp.sock`, and a second launch collides (`mpris: name already taken`). The user may already be playing something. Run `pgrep -a cliamp` first and leave a user-owned instance alone.
7. **Confirm playback from the audio sink, not from `cliamp status`.** A loaded track and a `playing` state are not proof of sound. Run `cliamp status` twice ~8s apart and require `Position` to advance, and check `pactl list sink-inputs` for an uncorked `PipeWire ALSA [cliamp]` entry.

## Core Workflow

### Playing a YouTube Playlist
```bash
cliamp --provider youtube --daemon --auto-play "https://www.youtube.com/playlist?list=PLAYLIST_ID"
```

### Playing a Single Track
```bash
cliamp --provider youtube --daemon --auto-play "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Playing Local Files
```bash
cliamp --daemon --auto-play /path/to/file.mp3
# or a directory
cliamp --daemon --auto-play /path/to/album/
```

### Playback Control
```bash
cliamp play          # resume
cliamp pause         # pause
cliamp toggle        # play/pause toggle
cliamp next          # next track
cliamp prev          # previous track
cliamp stop          # stop
cliamp status        # show current state
cliamp volume -3     # adjust volume in dB
cliamp shuffle       # toggle shuffle
cliamp repeat all    # set repeat mode
```

### Checking Status
```bash
cliamp status
# Returns: State, Track, Artist, Position, Volume, Shuffle, Repeat, etc.
```

## Pitfalls

- **Never run cliamp without `--daemon` in background mode.** The TUI requires a real TTY; background processes don't have one. The error `bubbletea: error opening TTY: could not open TTY: open /dev/tty: no such device or address` means you forgot `--daemon`.
- **YouTube provider fails silently without credentials.** If you see "YouTube: no credentials available," the config is missing auth. Run `cliamp setup` to configure, or manually edit `~/.config/cliamp/config.toml`.
- **Daemon mode creates a socket at `~/.config/cliamp/cliamp.sock`.** All control commands (`cliamp status`, `cliamp next`, etc.) communicate through this socket. If cliamp isn't running, these commands fail with "cliamp is not running."
- **Use `cliamp --help` to discover providers.** The provider list is long (radio, navidrome, lyrion, plex, jellyfin, emby, spotify, qobuz, tidal, soundcloud, mixcloud, netease, audiobookshelf, abs, yt, youtube, ytmusic). Not all are configured by default.
- **`cliamp stop` stops playback, not the daemon.** It leaves the daemon running and the socket in place. To shut down completely, kill the background process handle you launched (or the pid from `pgrep`) — the socket disappears with it. Confirm with `cliamp status`, which should report `cliamp is not running (no socket at ...)`.
- **`~/.config/cliamp/` is a symlink into the user's config repo.** The real path is `/opt/blackarch/config/cliamp/`, so edits made through the `~/.config` path land in the repo. Read the file before writing it — a blind `write_file` is refused by the stale-write guard, and a blind overwrite would drop the user's existing keys. Use `read_file` then `patch`, and merge rather than replace.
- **Cookie auth can half-work, which is worse than failing outright.** When cliamp can *name* a browser but cannot decrypt its cookies, listing a playlist still succeeds (metadata needs no auth) while playback fails with "The provided YouTube account cookies are no longer valid." Never treat a successful listing as proof that auth works — verify against an account-only endpoint (the `LL` Liked Videos playlist) or by resolving a playable audio URL.
- **`cannot decrypt v11 cookies: no key found` has two independent causes — check both.** (a) the browser is a Chromium fork yt-dlp doesn't know, so the `"<browser> Safe Storage"` keyring lookup misses; (b) the desktop environment was undetectable (bare WM), so yt-dlp chose the BASICTEXT keyring and never consulted the keyring at all. Rule 4 fixes (b); aliasing the fork onto a supported browser name fixes (a). See `references/browser-cookie-auth.md`.

## References

- `references/provider-setup.md` — credential and configuration details for streaming providers
- `references/browser-cookie-auth.md` — diagnosing and working around cookie auth for browsers yt-dlp doesn't support
- `scripts/export_chromium_cookies.py` — export a Chromium-family profile's cookies to Netscape format
