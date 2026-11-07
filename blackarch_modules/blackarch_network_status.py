#!/usr/bin/env python3
# blackarch:summary=Print active network status for the shell
# blackarch:group=network
# blackarch:args=[--verbose]
"""Python port of blackarch-network-status (bash)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

INTERNET_PROBE = "1.1.1.1"



def cmd_present(*cmds):
    """blackarch-cmd-present: every name must be resolvable on PATH."""
    return all(shutil.which(c) for c in cmds)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


def read_text(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def ip_route_dev(probe):
    out = run(["ip", "route", "get", probe]).stdout
    fields = out.split()
    for i, f in enumerate(fields):
        if f == "dev" and i + 1 < len(fields):
            return fields[i + 1]
    return ""


def print_status(internet_probe):
    device = ip_route_dev(internet_probe)

    if not device:
        print("disconnected\t\t\t")
        return

    if not os.path.isdir("/sys/class/net/%s/wireless" % device):
        print("ethernet\t%s\t\t" % device)
        return

    if cmd_present("nmcli"):
        nm = run(
            ["nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "dev", "show", device]
        ).stdout
        state = ""
        ssid = ""
        for line in nm.split("\n"):
            key, _, value = line.partition(":")
            if key == "GENERAL.STATE":
                state = value
                break
        for line in nm.split("\n"):
            key, _, value = line.partition(":")
            if key == "GENERAL.CONNECTION":
                ssid = value
                break

        signal = ""
        wifi_list = run(
            [
                "nmcli",
                "-t",
                "-f",
                "IN-USE,SIGNAL",
                "dev",
                "wifi",
                "list",
                "ifname",
                device,
                "--rescan",
                "no",
            ]
        ).stdout
        for line in wifi_list.split("\n"):
            first, _, second = line.partition(":")
            if first == "*":
                signal = second
                break

        freq = ""
        for line in run(["iw", "dev", device, "link"]).stdout.split("\n"):
            if "freq:" in line:
                freq = line.split()[1]
                break

        if not state.startswith("100"):
            print("disconnected\t\t\t")
            return

        print("wifi\t%s\t%s\t%s" % (ssid or device, signal, freq))
        return

    print("wifi\t%s\t\t" % device)


def ping_latency_ms(host):
    """LC_ALL=C ping -n -c 1 -W 1 host; the first time= / time< value, or ""."""
    env = dict(os.environ, LC_ALL="C")
    out = subprocess.run(
        ["ping", "-n", "-c", "1", "-W", "1", host],
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
    ).stdout
    for line in out.split("\n"):
        if "time=" not in line and "time<" not in line:
            continue
        if "time=" in line:
            rest = line.split("time=", 1)[1]
        else:
            rest = line.split("time<", 1)[1]
        return rest.split(" ")[0]
    return ""


def _ping_target(target, pipe):
    """Child side of the background ping: write the latency to pipe, or nothing."""
    latency = ping_latency_ms(target)
    pipe.write(latency)
    pipe.flush()


def print_ping_samples(gateway, internet_probe):
    """Fire both pings in parallel, then report router before internet.

    Mirrors the bash `cmd >"$file" &` jobs: both pings start before either is
    awaited, and each result is only read after its own wait.
    """
    if not cmd_present("ping"):
        return

    router_proc = None
    if gateway:
        router_pipe = os.pipe()
        router_proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--_ping", gateway],
            stdout=router_pipe[1],
            stderr=subprocess.DEVNULL,
        )
        os.close(router_pipe[1])

    internet_pipe = os.pipe()
    internet_proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--_ping", internet_probe],
        stdout=internet_pipe[1],
        stderr=subprocess.DEVNULL,
    )
    os.close(internet_pipe[1])

    if router_proc is not None:
        router_proc.wait()
        router_result = _read_pipe(router_pipe[0])
        os.close(router_pipe[0])
        print("router_ping_ms\t%s" % router_result)

    internet_proc.wait()
    internet_result = _read_pipe(internet_pipe[0])
    os.close(internet_pipe[0])
    print("internet_ping_ms\t%s" % internet_result)


def _read_pipe(fd):
    chunks = []
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace").strip()


def print_verbose(internet_probe):
    route_json = run(["ip", "-j", "route", "get", internet_probe]).stdout
    if not route_json:
        return

    try:
        route = json.loads(route_json)
    except ValueError:
        return
    if not route:
        return
    entry = route[0]

    iface = entry.get("dev") or ""
    gw = entry.get("gateway") or ""
    src = entry.get("prefsrc") or ""

    if not iface:
        return

    prefix = ""
    try:
        addr = json.loads(run(["ip", "-j", "addr", "show", iface]).stdout)
    except ValueError:
        addr = []
    if addr:
        for info in addr[0].get("addr_info") or []:
            if info.get("family") == "inet":
                prefix = info.get("prefixlen") or ""
                break

    print("iface\t%s" % iface)
    print("ip\t%s" % src)
    print("prefix\t%s" % prefix)
    print("gateway\t%s" % gw)

    rx_path = "/sys/class/net/%s/statistics/rx_bytes" % iface
    tx_path = "/sys/class/net/%s/statistics/tx_bytes" % iface
    if os.access(rx_path, os.R_OK):
        print("rx_bytes\t%s" % read_text(rx_path))
    if os.access(tx_path, os.R_OK):
        print("tx_bytes\t%s" % read_text(tx_path))

    if os.path.isdir("/sys/class/net/%s/wireless" % iface):
        print("type\twifi")

        if cmd_present("iw"):
            link = run(["iw", "dev", iface, "link"]).stdout

            if link:
                ssid = ""
                signal = ""
                freq = ""
                bitrate_value = ""
                bitrate_unit = ""
                for line in link.split("\n"):
                    if "SSID:" in line and not ssid:
                        ssid = line.split("SSID: ", 1)[1]
                    elif "signal:" in line and not signal:
                        signal = line.split()[1]
                    elif "freq:" in line and not freq:
                        freq = line.split()[1]
                    elif "tx bitrate:" in line:
                        bitrate_value = line.split()[2]
                        bitrate_unit = line.split()[3]

                print("ssid\t%s" % ssid)
                print("signal_dbm\t%s" % signal)
                print("freq\t%s" % freq)
                print("bitrate\t%s %s" % (bitrate_value, bitrate_unit))
    else:
        print("type\tethernet")
        speed_path = "/sys/class/net/%s/speed" % iface
        duplex_path = "/sys/class/net/%s/duplex" % iface
        if os.access(speed_path, os.R_OK):
            print("speed\t%s" % read_text(speed_path))
        if os.access(duplex_path, os.R_OK):
            print("duplex\t%s" % read_text(duplex_path))

    print_ping_samples(gw, internet_probe)


def main(argv):
    # `--_ping HOST` is the background ping child used by print_ping_samples.
    if len(argv) == 3 and argv[1] == "--_ping":
        _ping_target(argv[2], sys.stdout)
        return 0

    verbose = False
    if len(argv) > 1:
        if argv[1] == "--verbose":
            verbose = True
        else:
            print("Usage: blackarch-network-status [--verbose]", file=sys.stderr)
            return 2

    if verbose:
        print_verbose(INTERNET_PROBE)
    else:
        print_status(INTERNET_PROBE)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
