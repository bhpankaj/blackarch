# Provider Setup

## YouTube / YouTube Music

The YouTube provider requires credentials in the **`[ytmusic]`** section of `~/.config/cliamp/config.toml`. Both `--provider youtube` and `--provider ytmusic` read this section; there is no separate `[youtube]` credentials section.

```toml
[ytmusic]
client_id = "YOUR_CLIENT_ID"
client_secret = "YOUR_CLIENT_SECRET"
# OR use cookies from a browser:
cookies_from = "chrome"  # or "firefox", "safari"
```

`cookies_from` is passed verbatim to `yt-dlp --cookies-from-browser`, so it only
accepts yt-dlp's browser names: `brave`, `chrome`, `chromium`, `edge`, `firefox`,
`opera`, `safari`, `vivaldi`, `whale`. yt-dlp's `browser:path` syntax works for a
non-default profile location (e.g. `firefox:~/.config/zen`). A Chromium *fork*
that isn't in that list (Ulaa, etc.) cannot be decrypted this way even when
pointed at the right profile — see `browser-cookie-auth.md`.

Run `cliamp setup` for the interactive configuration wizard.

## Other Streaming Providers

| Provider | Flag | Auth Method |
|----------|------|-------------|
| Spotify | `--provider spotify` | OAuth |
| Qobuz | `--provider qobuz` | App ID + secret |
| Tidal | `--provider tidal` | OAuth |
| SoundCloud | `--provider soundcloud` | Client ID |
| Mixcloud | `--provider mixcloud` | None (public) |
| NetEase | `--provider netease` | Phone + password |
| Plex | `--provider plex` | Token |
| Jellyfin | `--provider jellyfin` | Username + password |
| Emby | `--provider emby` | Username + password |
| Navidrome | `--provider navidrome` | Username + password |
| Lyrion | `--provider lyrion` | Username + password |
| Audiobookshelf | `--provider audiobookshelf` | Username + password |
| ABS | `--provider abs` | Username + password |

## Local Files

No provider needed. Pass the file or directory path directly:
```bash
cliamp --daemon --auto-play /path/to/music/
```

## Radio

```bash
cliamp --provider radio --daemon --auto-play
```
