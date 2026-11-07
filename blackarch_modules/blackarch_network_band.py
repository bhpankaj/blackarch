#!/usr/bin/env python3
# blackarch:summary=Show or pin the Wi-Fi band for the active connection
# blackarch:group=network
# blackarch:args=[auto|2.4|5|6]
# blackarch:examples=blackarch network band | blackarch network band 5 | blackarch network band auto
"""blackarch-network-band — show or pin the Wi-Fi band for the active connection.

Standalone Python replacement for the bash `blackarch-network-band`. With no
argument it prints `band`/`available`/`selected` as tab-separated lines; with a
band argument it pins `802-11-wireless.band` on the connection profile and
reconnects, reverting if the radio cannot come back up. NetworkManager 1.44+
accepts a third band value, so 5GHz and 6GHz can be pinned apart; pinning the
band rather than a BSSID keeps working when the AP rotates BSSIDs and leaves
roaming between APs intact. No awk, sed or shell pipes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

USAGE = "Usage: blackarch-network-band [auto|2.4|5|6]\n"

BAND_FOR_NM = {"2.4": "bg", "5": "a", "6": "6GHz"}
BAND_FROM_NM = {"bg": "2.4", "a": "5", "6GHz": "6"}


class BashExit(Exception):
    """Raised where `set -euo pipefail` would abort the bash script."""

    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def sh(args, env=None, stderr=None, check=False):
    """Run a command, returning (exit status, stdout bytes)."""
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=stderr, env=env)
    except FileNotFoundError:
        return 127, b""
    if check and proc.returncode != 0:
        raise BashExit(proc.returncode)
    return proc.returncode, proc.stdout


def decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


# ── band helpers ─────────────────────────────────────────────────────────────
def nm_band_for(target: str):
    """`nm_band_for`: the NetworkManager value for a band, or None."""
    return BAND_FOR_NM.get(target)


def band_from_nm(value: str) -> str:
    """`band_from_nm`: the label for a NetworkManager band value."""
    return BAND_FROM_NM.get(value, "auto")


def band_for_freq(freq: str):
    """`band_for_freq`: the band for a frequency, or None when out of range.

    Accepts either nmcli's "2412 MHz" or iw's "5745.0": the leading digits are
    kept and whatever unit or fraction follows is ignored. The boundaries
    mirror Model.js formatHeaderFreq so the panel's label and this command
    cannot disagree.
    """
    match = re.match(r"[0-9]*", freq)
    digits = match.group(0)
    if digits == "":
        return None
    mhz = int(digits)
    if 2400 <= mhz < 2500:
        return "2.4"
    if 4900 <= mhz < 5925:
        return "5"
    if 5925 <= mhz < 7125:
        return "6"
    return None


# ── NetworkManager / iw ──────────────────────────────────────────────────────
def nm_get(*args: str):
    """`LC_ALL=C nmcli -e no -g "$@" 2>/dev/null`.

    LC_ALL=C because nmcli translates state words such as "connected", which
    would silently stop matching under a non-English session; `-e no` because
    `-g` otherwise escapes ':' and '\\' in values, and an escaped SSID would
    never match iw's raw one. Returns (exit status, stdout) with the trailing
    newlines command substitution would strip.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    rc, out = sh(["nmcli", "-e", "no", "-g", *args], env=env, stderr=subprocess.DEVNULL)
    return rc, decode(out).rstrip("\n")


def wifi_device():
    """`wifi_device`: the first connected Wi-Fi device."""
    rc, out = nm_get("DEVICE,TYPE,STATE", "device", "status")
    device = ""
    for line in out.split("\n"):
        fields = line.split(":")
        if len(fields) >= 3 and fields[1] == "wifi" and fields[2] == "connected":
            device = fields[0]
            break
    # pipefail: the pipeline's status is nmcli's when nmcli failed.
    return (rc if rc != 0 else 0), device


def wifi_profile(device: str):
    """`wifi_profile`: the active connection profile of a device."""
    return nm_get("GENERAL.CONNECTION", "device", "show", device)


def selected_band(profile: str) -> str:
    """`selected_band`: the band pinned on a connection profile."""
    _, value = nm_get("802-11-wireless.band", "connection", "show", profile)
    return band_from_nm(value)


def read_link(device: str):
    """`read_link`: $ssid and $freq from one `iw dev <device> link`.

    iw prints the SSID as the rest of its line, so an SSID containing ':' needs
    no special handling.
    """
    rc, out = sh(["iw", "dev", device, "link"], stderr=subprocess.DEVNULL)
    if rc != 0:
        raise BashExit(rc)
    link = decode(out)

    ssid = ""
    for line in link.split("\n"):
        if "SSID:" in line:
            index = line.rfind("SSID: ")
            # awk's sub(/.*SSID: /, "") is greedy: strip through the last
            # "SSID: ". With no trailing space the record is printed unchanged.
            ssid = line if index == -1 else line[index + len("SSID: "):]
            break

    freq = ""
    for line in link.split("\n"):
        if "freq:" in line:
            fields = line.split()
            freq = fields[1] if len(fields) >= 2 else ""
            break

    return ssid, freq


def available_bands(device: str, ssid: str, current: str) -> str:
    """`available_bands`: every band the SSID is reachable on, low to high.

    The band already in use is always included -- a weak radio gets missed by
    plenty of scans, and the band we are sitting on must never be absent from
    its own list of options. A band the AP does not answer on is never offered:
    pinning to it would drop the connection with nothing to reassociate to.

    `--rescan no` reads NetworkManager's cache, which the panel's own scanner
    keeps warm; forcing a scan here would stall every poll. The kernel's own
    cache (iw scan dump) is pruned far harder and would make bands flicker.
    """
    values = []
    if current:
        values.append(current)

    rc, out = nm_get("FREQ,SSID", "dev", "wifi", "list", "ifname", device, "--rescan", "no")
    if rc != 0:
        raise BashExit(rc)

    for line in out.split("\n"):
        fields = line.split(":")
        name = fields[1] if len(fields) >= 2 else ""
        for field in fields[2:]:
            name = name + ":" + field
        if name != ssid:
            continue
        band = band_for_freq(fields[0])
        if band:
            values.append(band)

    # sort -u -g, then the newlines become single spaces.
    return " ".join(sorted(set(values), key=float))


# ── modes ────────────────────────────────────────────────────────────────────
def print_status() -> None:
    """`print_status`: the tab-separated lines the panel's parser reads."""
    rc, device = wifi_device()
    if rc != 0:
        raise BashExit(rc)
    if not device:
        return

    ssid, freq = read_link(device)
    if not ssid:
        return

    band = band_for_freq(freq) or ""
    available = available_bands(device, ssid, band)

    profile_rc, profile = wifi_profile(device)
    if profile_rc != 0:
        raise BashExit(profile_rc)

    sys.stdout.write(f"band\t{band}\n")
    sys.stdout.write(f"available\t{available}\n")
    if profile:
        sys.stdout.write(f"selected\t{selected_band(profile)}\n")


def set_band(target: str) -> None:
    """`set_band`: pin a band, reconnecting and reverting on failure."""
    rc, device = wifi_device()
    if rc != 0:
        raise BashExit(rc)
    if not device:
        sys.stderr.write("Error: no connected Wi-Fi device.\n")
        raise SystemExit(1)

    profile_rc, profile = wifi_profile(device)
    if profile_rc != 0:
        raise BashExit(profile_rc)
    if not profile:
        sys.stderr.write("Error: no active Wi-Fi connection profile.\n")
        raise SystemExit(1)

    if target == "auto":
        desired = ""
    else:
        ssid, freq = read_link(device)
        available = available_bands(device, ssid, band_for_freq(freq) or "")
        if f" {target} " not in f" {available} ":
            sys.stderr.write(f"Error: {target}GHz is not available on this network.\n")
            raise SystemExit(1)
        desired = nm_band_for(target)

    previous_rc, previous = nm_get("802-11-wireless.band", "connection", "show", profile)
    if previous_rc != 0:
        raise BashExit(previous_rc)
    if previous == desired:
        return

    sh(["nmcli", "connection", "modify", profile, "802-11-wireless.band", desired],
       stdout=subprocess.DEVNULL, check=True)

    # A band change only takes effect on reassociation. If the radio cannot
    # come back up on the requested band, put the previous setting back and
    # reconnect rather than leaving the machine stranded offline.
    rc, _ = sh(["nmcli", "connection", "up", profile],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if rc != 0:
        sh(["nmcli", "connection", "modify", profile, "802-11-wireless.band", previous],
           stdout=subprocess.DEVNULL, check=True)
        sh(["nmcli", "connection", "up", profile],
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sys.stderr.write(f"Error: could not connect on {target}; reverted to previous band.\n")
        raise SystemExit(1)


def usage() -> None:
    """`usage`: the stderr banner for a bad invocation."""
    sys.stderr.write(USAGE)


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print_status()
        return 0
    if len(argv) > 1:
        usage()
        return 1
    target = argv[0]
    if target in ("auto", "2.4", "5", "6"):
        set_band(target)
        return 0
    usage()
    return 1


if __name__ == "__main__":
    try:
        code = main()
    except BashExit as exc:
        code = exc.code
    sys.exit(code)
