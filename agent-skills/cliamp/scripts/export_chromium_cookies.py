#!/usr/bin/env python3
"""Export cookies from a Chromium-family profile to Netscape format.

Why this exists: yt-dlp's --cookies-from-browser only knows a fixed set of
browser names. For a Chromium fork it does not list (Ulaa, Zen, vendor builds)
it looks for a keyring item labelled "<browser> Safe Storage", misses, and
gives up with "cannot decrypt v11 cookies: no key found" -- leaving cookie auth
half-working (playlist listing succeeds, playback fails). This script reads the
profile's cookie DB directly and writes a cookie file yt-dlp can consume.

Chromium cookie storage on Linux:
  db:     <profile>/<Profile>/Cookies   (sqlite, table `cookies`)
  blob:   3-byte version b'v10'/b'v11' + AES-128-CBC ciphertext
  IV:     b' ' * 16
  key:    pbkdf2_hmac('sha1', password, b'saltysalt', iterations=1, key_length=16)
          v10 -> password is b'peanuts'      (fixed no-keyring fallback)
          v11 -> password is the keyring secret, used VERBATIM
  note:   Chromium >= v24 prepends 32 bytes of SHA256(domain) to the decrypted
          value -- strip it or the value is garbage.

Run under an interpreter that has `secretstorage` and a crypto lib. Hermes ships
its own Python and puts it first on PATH, so the bare `python3` may lack them:

    python3 -c "import secretstorage, Crypto" && echo ok
    /usr/bin/python3 -c "import secretstorage, Crypto" && echo ok

Usage:
    /usr/bin/python3 export_chromium_cookies.py \
        --browser Ulaa --profile ~/.config/Zoho/Ulaa --out ~/ulaa-cookies.txt

Verify the result against an account-only endpoint (empty output = not signed in):

    yt-dlp --cookies ~/ulaa-cookies.txt --flat-playlist --simulate \
        --print "%(title)s" "https://www.youtube.com/playlist?list=LL"
"""
import argparse
import base64
import hashlib
import os
import shutil
import sqlite3
import tempfile

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

CHROME_EPOCH = 11644473600  # seconds between 1601-01-01 and 1970-01-01
IV = b" " * 16
DEFAULT_HOSTS = ("youtube.com", "google.com", "googlevideo.com")


def keyring_secret(browser):
    """Read the '<Browser> Safe Storage' secret from gnome-keyring."""
    import secretstorage

    label = f"{browser} Safe Storage"
    con = secretstorage.dbus_init()
    for item in secretstorage.get_default_collection(con).get_all_items():
        if item.get_label() == label:
            return item.get_secret()
    raise SystemExit(f"keyring item {label!r} not found")


def derive(password):
    return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1, 16)


def decrypt(blob, v10_key, v11_key, v11_key_b64):
    """v10 uses the fixed peanuts key; v11 the keyring secret."""
    version, ciphertext = blob[:3], blob[3:]
    candidates = (v10_key,) if version == b"v10" else (v11_key, v11_key_b64, v10_key)
    for key in candidates:
        if key is None:
            continue
        try:
            return unpad(AES.new(key, AES.MODE_CBC, IV).decrypt(ciphertext), 16)
        except Exception:
            continue
    return None


def strip_domain_hash(plaintext):
    """Chromium >= v24 prefixes a 32-byte SHA256(domain) before the value."""
    return plaintext[32:] if len(plaintext) > 32 else plaintext


def export(profile_dir, browser, out_path, hosts, profile_name="Default"):
    src = os.path.join(profile_dir, profile_name, "Cookies")
    if not os.path.exists(src):
        raise SystemExit(f"no cookie db at {src}")

    # Copy first: the running browser may hold a lock on the live DB.
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(src, tmp)

    secret = keyring_secret(browser)
    v10_key = derive(b"peanuts")
    v11_key = derive(secret)  # used verbatim
    v11_key_b64 = derive(base64.b64decode(secret))

    con = sqlite3.connect(tmp)
    rows = con.execute(
        "SELECT host_key, name, encrypted_value, value, path, expires_utc, "
        "is_secure, has_expires FROM cookies"
    ).fetchall()

    lines = ["# Netscape HTTP Cookie File", "# generated from Chromium profile", ""]
    kept = 0
    for host, name, blob, plain, path, expires, secure, has_expires in rows:
        if not any(host.endswith(h) or h.endswith(host) for h in hosts):
            continue
        if plain:
            value = plain
        else:
            decrypted = decrypt(blob, v10_key, v11_key, v11_key_b64)
            if decrypted is None:
                continue
            value = strip_domain_hash(decrypted).decode("utf-8", "replace")
        if not value:
            continue
        expiry = int(expires / 1_000_000 - CHROME_EPOCH) if has_expires else 0
        lines.append("\t".join([
            host,
            "TRUE" if host.startswith(".") else "FALSE",
            path or "/",
            "TRUE" if secure else "FALSE",
            str(max(expiry, 0)),
            name,
            value,
        ]))
        kept += 1

    con.close()
    os.unlink(tmp)

    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(out_path, 0o600)
    print(f"wrote {kept} cookies -> {out_path}")
    if not kept:
        raise SystemExit("no cookies exported -- wrong profile dir or host filter?")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile", required=True,
                        help="browser profile root, e.g. ~/.config/Zoho/Ulaa")
    parser.add_argument("--browser", required=True,
                        help="keyring label prefix, e.g. Ulaa -> 'Ulaa Safe Storage'")
    parser.add_argument("--out", required=True, help="output cookie file")
    parser.add_argument("--profile-name", default="Default",
                        help="Chromium profile subdir (default: Default)")
    parser.add_argument("--hosts", nargs="*", default=list(DEFAULT_HOSTS),
                        help=f"host suffixes to keep (default: {' '.join(DEFAULT_HOSTS)})")
    args = parser.parse_args()

    export(os.path.expanduser(args.profile), args.browser,
           os.path.expanduser(args.out), args.hosts, args.profile_name)


if __name__ == "__main__":
    main()
