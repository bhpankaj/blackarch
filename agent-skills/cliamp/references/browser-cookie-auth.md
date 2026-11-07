# Browser Cookie Auth for YouTube (non-standard browsers)

cliamp delegates YouTube auth to yt-dlp: `cookies_from` becomes
`yt-dlp --cookies-from-browser`. That only accepts a fixed browser list, so a
Chromium **fork** (Ulaa, Zen, Brave-family derivatives, vendor builds) cannot be
named directly.

Two routes, in order of preference:

1. **Alias the fork onto a supported browser name** (below). No exported file,
   survives browser restarts, and it is what cliamp consumes natively. Prefer this.
2. **Export the cookies to a Netscape file** (see *Exporting*). Fallback when the
   alias cannot be arranged.

## Diagnosing a cookie-auth failure

Work through this in order — each step rules out one layer.

1. **Confirm the browser is even nameable.** `yt-dlp --help | grep -A2
   cookies-from-browser` lists the supported names. If the user's browser is not
   there, `cookies_from = "<it>"` can never work.
2. **Check the error text.** `cannot decrypt v11 cookies: no key found` has two
   independent causes and you must distinguish them: an *unrecognised browser*
   (its keyring label is never looked up) or an *undetectable desktop
   environment* (yt-dlp selected BASICTEXT and never consulted the keyring at
   all). Run `yt-dlp --cookies-from-browser "<name>+gnomekeyring"` — if that
   clears the error, the cause was the keyring backend, not the browser. By
   contrast, a *valid* browser with a signed-out profile yields no error at all —
   just anonymous results.
3. **Find the real profile directory.** Chromium forks put it under their own
   vendor path, e.g. `~/.config/Zoho/Ulaa/`, with one directory per profile
   (`Default`, `Default Work`, ...). The cookie DB is `<profile>/<Profile>/Cookies`.
4. **Inspect the keyring item.** `yt-dlp` matches on the label
   `"<browser> Safe Storage"` (`cookies.py: _get_gnome_keyring_password`). A fork
   registers its own label, so the lookup misses:

   ```python
   import secretstorage
   con = secretstorage.dbus_init()
   for item in secretstorage.get_default_collection(con).get_all_items():
       print(repr(item.get_label()), dict(item.get_attributes()))
   ```

   A Chromium-family entry carries `xdg:schema = chrome_libsecret_os_crypt_password_v2`.

## Why the profile-path trick is not enough

`cookies_from = "chromium:/home/user/.config/Zoho/Ulaa"` looks promising and
half-works: **listing a playlist succeeds** (metadata needs no auth) while
**playback fails** with `The provided YouTube account cookies are no longer
valid`. The v11 blobs are still undecrypted; the partial cookie set leaves a
session that authenticates for nothing. Treat a successful listing as no
evidence at all — verify with an account-only endpoint (below).

## Chromium cookie decryption on Linux

Verified against Chrome/Ulaa; the format is stable across the Chromium family.

| Item | Value |
|------|-------|
| Database | `<profile>/<Profile>/Cookies`, sqlite table `cookies` |
| Blob layout | 3-byte version prefix (`b'v10'` / `b'v11'`) + AES-128-CBC ciphertext |
| IV | `b' ' * 16` (sixteen spaces) |
| Key derivation | `pbkdf2_hmac('sha1', password, b'saltysalt', iterations=1, key_length=16)` |
| `v10` password | `b'peanuts'` — the fixed no-keyring fallback |
| `v11` password | the keyring secret, used **verbatim** (do not base64-decode it) |
| Plaintext prefix | Chromium >= v24 prepends **32 bytes of SHA256(domain)** before the cookie value — strip it or the value is garbage |

Where the key lives: `Local State` → `os_crypt.encrypted_key` holds it on
Windows (DPAPI-wrapped). On Linux that field is typically absent and the key is
the gnome-keyring / kwallet secret instead.

A useful side effect of this layout: **auth cookies are often still `v10`**
(SID, HSID, SSID, LOGIN_INFO, `__Secure-1PSID`), which need only `peanuts` and
no keyring at all. That is why a manual export can succeed where yt-dlp fails.

## Exporting

Use the bundled script — it handles v10/v11, the plaintext prefix, and copies
the DB before reading it (the live browser may hold a lock):

```bash
/usr/bin/python3 scripts/export_chromium_cookies.py \
    --browser Ulaa \
    --profile ~/.config/Zoho/Ulaa \
    --out ~/ulaa-cookies.txt
```

It needs `secretstorage` (gnome-keyring) plus a crypto lib, and it must run
under an interpreter that actually has them. Hermes ships its own Python and
puts it first on `PATH`, so the bare `python3` may lack them while the system
one has them — check before assuming a package is missing:

```bash
python3 -c "import secretstorage, Crypto" && echo ok   # the PATH python
/usr/bin/python3 -c "import secretstorage, Crypto" && echo ok   # system python
```

Invoke the interpreter whose import check passed.

## Verifying the export actually authenticates

A file with the right cookie count is not proof. Hit an account-only endpoint:

```bash
# Liked Videos ('LL') only returns rows when the session is signed in
/usr/bin/yt-dlp --cookies ~/ulaa-cookies.txt --flat-playlist --simulate \
    --print "%(title)s" "https://www.youtube.com/playlist?list=LL"
```

Real titles means the session works. Empty output means it does not.

## Wiring a fork into cliamp (verified)

cliamp's only cookie knob is `cookies_from`, which it passes verbatim to
`--cookies-from-browser`. That argument's grammar is
`BROWSER[+KEYRING][:PROFILE]`, which is enough to reach a fork without patching
anything or exporting a file. Point a *supported* browser name at the fork's
data, in three steps:

**1. Symlink the profile.** yt-dlp resolves browser dirs from the XDG config
home (`~/.config/<vendor path>`, see `_get_chromium_based_browser_settings` in
`yt_dlp/cookies.py`). Link a supported name's path to the fork's profile root:

```bash
ln -s ~/.config/Zoho/Ulaa ~/.config/BraveSoftware/Brave-Browser
```

Check for an existing link first — a distro theme or the user may have created
one already (`readlink -f ~/.config/BraveSoftware/Brave-Browser`). Do not
replace a symlink that points somewhere real.

**2. Alias the keyring item.** yt-dlp reads the key from the item labelled
`"<browser> Safe Storage"`. Duplicate the fork's secret under the supported
name, copying the secret byte-for-byte — the key is the *secret*, the label is
only a lookup name:

```python
import secretstorage
con = secretstorage.dbus_init()
col = secretstorage.get_default_collection(con)
secret = next(i for i in col.get_all_items()
              if i.get_label() == 'Ulaa Safe Storage').get_secret()
col.create_item('Brave Safe Storage',
                {'application': 'brave',
                 'xdg:schema': 'chrome_libsecret_os_crypt_password_v2'},
                secret, replace=True)
```

**3. Force the keyring backend in `cookies_from`.** Append `+gnomekeyring`:

```toml
cookies_from = "brave+gnomekeyring"
```

This suffix is not optional on a bare window manager — see below.

## The `+KEYRING` suffix is mandatory on Hyprland and other bare WMs

`_choose_linux_keyring` picks a keyring from the *desktop environment*, and when
none of `DESKTOP_SESSION`, `GNOME_DESKTOP_SESSION_ID`, or `KDE_FULL_SESSION` is
set it classifies the desktop as `OTHER` and selects **BASICTEXT**, whose
password is `None`. Every v11 cookie then fails to decrypt and yt-dlp reports
`no key found` — even for a genuinely supported browser, and even when the
keyring item and profile path are both correct.

So the plain `cookies_from = "brave"` form is unreliable here. Always state the
backend explicitly:

| Keyring | When |
|---------|------|
| `+gnomekeyring` | gnome-keyring / libsecret is the store (Chromium forks on Hyprland) |
| `+kwallet` / `+kwallet5` / `+kwallet6` | KDE wallet |
| `+basictext` | cookies are all `v10`; no keyring needed |

## Verifying cliamp actually plays (not just lists)

A loaded playlist proves nothing. Confirm audio is really streaming:

```bash
cliamp status                       # run twice, ~8s apart: Position must advance
pactl list sink-inputs | grep -A2 'PipeWire ALSA \[cliamp\]'   # expect 'Corked: no'
```

A stationary `Position` with `Corked: yes` means auth or the stream URL failed.

Note the asymmetry: an exported cookie *file* (`--cookies`) works even with a
BASICTEXT keyring, because it needs no keyring at all. The alias route depends
on the keyring, so it needs both the label alias and the `+gnomekeyring` suffix.
