#!/usr/bin/env python3
# blackarch:summary=Show or configure the system DNS provider
# blackarch:args=[Cloudflare|Google|DHCP|Custom]
# blackarch:examples=blackarch dns | blackarch dns Cloudflare | blackarch dns Custom
"""blackarch-dns — show or configure the system DNS provider.

Python port of the bash original. Writes NetworkManager's global DNS drop-in,
per-connection DNS, and systemd-resolved.conf, then reloads both stacks.

The privileged half always runs from /usr/bin/blackarch-dns rather than from
whichever copy was invoked, so the sudoers rule matches even where
$BLACKARCH_PATH points at a checkout.
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blackarch_modules.blackarch_helpers import current_wayland_env, waylandsudo_argv  # noqa: E402

NM_DNS_CONF = "/etc/NetworkManager/conf.d/20-blackarch-dns.conf"
RESOLVED_CONF = "/etc/systemd/resolved.conf"
PACKAGED_PATH = "/usr/bin/blackarch-dns"

CLOUDFLARE = "1.1.1.1,1.0.0.1,2606:4700:4700::1111,2606:4700:4700::1001"
GOOGLE = "8.8.8.8,8.8.4.4,2001:4860:4860::8888,2001:4860:4860::8844"
FALLBACK = ("9.9.9.9#dns.quad9.net 149.112.112.112#dns.quad9.net "
            "2620:fe::fe#dns.quad9.net 2620:fe::9#dns.quad9.net")

USAGE = "Usage: blackarch-dns [Cloudflare|Google|DHCP|Custom]"
GLOBAL_DNS_SECTION = "[global-dns-domain-*]"
DNS_LINE = re.compile(r"^servers[ \t]*=")
RESOLVED_DNS_LINE = re.compile(r"^DNS[ \t]*=")


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return subprocess.CompletedProcess(argv, 127, b"", b"")


def provider_from_arg(argument: str) -> str:
    return {
        "Cloudflare": "Cloudflare", "cloudflare": "Cloudflare",
        "Google": "Google", "google": "Google",
        "DHCP": "DHCP", "dhcp": "DHCP",
        "Custom": "Custom", "custom": "Custom",
    }.get(argument, "")


def sudo_grants_passwordless() -> bool:
    """True when sudo would run this exact command without a password.

    `sudo -l` alone reports whether a command is permitted, which the blanket
    %wheel rule answers yes to for everything; the long listing prints the
    matched entry's tags, so !authenticate is the grant and nothing else.
    """
    proc = run(["sudo", "-n", "-l", "-l", PACKAGED_PATH])
    return b"!authenticate" in proc.stdout


def require_root(provider: str) -> None:
    """Re-exec this command as root, through waylandsudo when that will do.

    A terminal can carry sudo's own password prompt. Without one, sudo is right
    only where the grant reaches; polkit can at least put a prompt on screen and
    offer to authenticate as someone else.
    """
    if os.geteuid() == 0:
        return
    if sys.stdin.isatty() or sudo_grants_passwordless():
        argv = waylandsudo_argv([PACKAGED_PATH, provider])
        os.execvp(argv[0], argv)
    os.execvp("pkexec", ["pkexec", PACKAGED_PATH, provider])


def networkmanager_global_dns() -> str:
    """The `servers=` value under [global-dns-domain-*], or ""."""
    try:
        text = open(NM_DNS_CONF, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""

    in_default = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped == GLOBAL_DNS_SECTION:
            in_default = True
            continue
        if stripped.startswith("["):
            in_default = False
        if in_default:
            match = DNS_LINE.match(line.strip())
            if match:
                return line.split("=", 1)[1].strip()
    return ""


def resolved_dns() -> str:
    try:
        text = open(RESOLVED_CONF, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        match = RESOLVED_DNS_LINE.match(line.strip())
        if match:
            return line.split("=", 1)[1].strip()
    return ""


def current_dns_provider() -> str:
    dns = networkmanager_global_dns()
    if not re.sub(r"[\s,]", "", dns):
        dns = resolved_dns()

    compact = re.sub(r"[\s,]", "", dns)
    if not compact:
        return "DHCP"
    if any(token in dns for token in ("cloudflare-dns.com", "1.1.1.1", "2606:4700:4700::1111")):
        return "Cloudflare"
    if any(token in dns for token in ("dns.google", "8.8.8.8", "2001:4860:4860::8888")):
        return "Google"
    return "Custom"


def normalize_servers(text: str) -> str:
    """`printf '%s\\n' "$*" | tr ',\\t\\n' ' ' | xargs | tr ' ' ','`."""
    return ",".join(text.replace(",", " ").replace("\t", " ").replace("\n", " ").split())


def split_dns_servers(servers: str) -> tuple[str, str]:
    """Split a comma-separated list into (ipv4, ipv6) space-separated lists.

    Each entry loses its dns+tls:// / dns+udp:// scheme and #hostname suffix,
    and brackets around an IPv6 literal.
    """
    ipv4: list[str] = []
    ipv6: list[str] = []
    for server in servers.replace(",", " ").split():
        clean = re.sub(r"^dns\+(tls|udp)://", "", server)
        clean = clean.split("#", 1)[0]
        clean = clean.strip("[]")
        if not clean:
            continue
        (ipv6 if ":" in clean else ipv4).append(clean)
    return " ".join(ipv4), " ".join(ipv6)


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def write_networkmanager_dns(servers: str) -> None:
    write_file(
        NM_DNS_CONF,
        "# Managed by blackarch-dns. Remove this file or run blackarch dns DHCP to use "
        "DHCP DNS again.\n"
        "[global-dns]\n\n"
        "[global-dns-domain-*]\n"
        f"servers={servers}\n",
    )


def clear_networkmanager_dns() -> None:
    try:
        os.unlink(NM_DNS_CONF)
    except OSError:
        pass


def nm_connections() -> list[tuple[str, str]]:
    proc = run(["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"])
    pairs = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        uuid, _, kind = line.partition(":")
        if uuid:
            pairs.append((uuid, kind))
    return pairs


def set_connection_dns(ipv4_dns: str, ipv6_dns: str) -> None:
    for uuid, kind in nm_connections():
        if kind not in ("802-11-wireless", "802-3-ethernet"):
            continue
        run(["nmcli", "connection", "modify", uuid,
             "ipv4.ignore-auto-dns", "yes", "ipv4.dns", ipv4_dns,
             "ipv6.ignore-auto-dns", "yes", "ipv6.dns", ipv6_dns])


def clear_connection_dns() -> None:
    for uuid, kind in nm_connections():
        if kind not in ("802-11-wireless", "802-3-ethernet"):
            continue
        run(["nmcli", "connection", "modify", uuid,
             "ipv4.ignore-auto-dns", "no", "ipv4.dns", "",
             "ipv6.ignore-auto-dns", "no", "ipv6.dns", ""])


def reapply_active_dns_connections() -> None:
    proc = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        device, _, rest = line.partition(":")
        kind, _, state = rest.partition(":")
        if not device or state != "connected":
            continue
        if kind in ("wifi", "ethernet"):
            run(["nmcli", "device", "reapply", device])


def reload_dns_stack() -> None:
    if run(["systemctl", "is-active", "--quiet", "NetworkManager.service"]).returncode == 0:
        # Load the updated NetworkManager config first, then reapply the active
        # profiles — a single `conf,dns-full` reload pushes the old settings.
        if run(["nmcli", "general", "reload", "conf"]).returncode != 0:
            run(["systemctl", "reload", "NetworkManager.service"])
        reapply_active_dns_connections()

    if run(["systemctl", "reload", "systemd-resolved.service"]).returncode != 0:
        run(["systemctl", "restart", "systemd-resolved.service"])

    if run(["systemctl", "is-active", "--quiet", "NetworkManager.service"]).returncode == 0:
        # A resolved reload/restart can leave per-link DNS stale or empty.
        run(["nmcli", "general", "reload", "dns-full"])


def main(argv: list[str]) -> int:
    if not argv:
        print(current_dns_provider())
        return 0
    if len(argv) > 1:
        print(USAGE, file=sys.stderr)
        return 1

    provider = provider_from_arg(argv[0])
    if not provider:
        print(USAGE, file=sys.stderr)
        return 1

    require_root(provider)

    if provider == "Cloudflare":
        write_networkmanager_dns(CLOUDFLARE)
        ipv4, ipv6 = split_dns_servers(CLOUDFLARE)
        set_connection_dns(ipv4, ipv6)
        write_file(
            RESOLVED_CONF,
            "[Resolve]\n"
            "DNS=1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com "
            "2606:4700:4700::1111#cloudflare-dns.com 2606:4700:4700::1001#cloudflare-dns.com\n"
            f"FallbackDNS={FALLBACK}\n"
            "DNSOverTLS=opportunistic\n",
        )
    elif provider == "Google":
        write_networkmanager_dns(GOOGLE)
        ipv4, ipv6 = split_dns_servers(GOOGLE)
        set_connection_dns(ipv4, ipv6)
        write_file(
            RESOLVED_CONF,
            "[Resolve]\n"
            "DNS=8.8.8.8#dns.google 8.8.4.4#dns.google 2001:4860:4860::8888#dns.google "
            "2001:4860:4860::8844#dns.google\n"
            f"FallbackDNS={FALLBACK}\n"
            "DNSOverTLS=opportunistic\n",
        )
    elif provider == "DHCP":
        clear_networkmanager_dns()
        clear_connection_dns()
        write_file(RESOLVED_CONF, "[Resolve]\nDNSOverTLS=no\n")
    else:
        print("Enter your DNS servers (space-separated, e.g. '192.168.1.1 1.1.1.1'):")
        try:
            servers = input()
        except EOFError:
            servers = ""
        servers = normalize_servers(servers)
        if not servers:
            print("Error: No DNS servers provided.", file=sys.stderr)
            return 1
        ipv4, ipv6 = split_dns_servers(servers)
        write_networkmanager_dns(servers)
        set_connection_dns(ipv4, ipv6)
        write_file(
            RESOLVED_CONF,
            "[Resolve]\n"
            f"DNS={servers.replace(',', ' ')}\n"
            f"FallbackDNS={FALLBACK}\n",
        )

    reload_dns_stack()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
