# Debian/Ubuntu to Arch Linux Migration Reference

## Package Manager Mapping

| Operation | Debian/Ubuntu | Arch Linux |
|---|---|---|
| Install package | `apt-get install` | `pacman -S` |
| Update databases | `apt-get update` | `pacman -Sy` |
| Upgrade all | `apt-get upgrade` | `pacman -Suu` |
| Search | `apt-cache search` | `pacman -Ss` |
| List installed | `dpkg -l` | `pacman -Q` |
| Query package files | `dpkg -L` | `pacman -Ql` |
| Which package owns file | `dpkg -S` | `pacman -Qo` |
| Package info | `dpkg -s` | `pacman -Qi` |
| Remove package | `apt-get remove` | `pacman -R` |
| Remove + deps | `apt-get autoremove` | `pacman -Rns` |

## Package Name Mapping

| Debian Package | Arch Package | Repository |
|---|---|---|
| `conky-all` | `conky` | extra |
| `dnscrypt-proxy` | `dnscrypt-proxy` | AUR |
| `ufw` | `ufw` | extra |
| `nftables` | `nftables` | core |
| `iptables` | `iptables` | core |
| `wireguard-tools` | `wireguard-tools` | core |
| `openvpn` | `openvpn` | extra |
| `tor` | `tor` | extra |
| `dnsmasq` | `dnsmasq` | extra |
| `privoxy` | `privoxy` | extra |
| `macchanger` | `macchanger` | community |
| `jq` | `jq` | core |
| `gum` | `gum` | AUR |
| `dracut` | `mkinitcpio` | core (different tool) |
| `initramfs-tools` | `mkinitcpio` | core (different tool) |
| `ram-wipe` | (custom mkinitcpio hook) | AUR |
| `build-essential` | `base-devel` (group) | core |
| `dnsutils` / `bind9-dnsutils` | `bind` | extra |
| `conky-all` | `conky` | extra |
| `libwebkit2gtk-4.1-0` | `webkit2gtk-4.1` | extra |
| `ttf-mscorefonts-installer` | `ttf-ms-fonts` | AUR |
| `rng-tools-debian` | `rng-tools` | extra |
| `libxcb1-dev` / `libxcb-xkb-dev` | `libxcb` | extra |
| `resolvconf` | `openresolv` | extra |
| `tor-geoipdb` | (bundled with tor) | extra |
| `apt-transport-tor` | (no equivalent — skip) | N/A |
| `systemd-resolved` | (part of systemd) | N/A |
| `cryptsetup-initramfs` | (Debian-only — skip) | N/A |
| `cryptsetup-nuke-password` | (Debian-only — skip) | N/A |
| `unattended-upgrades` | (Debian-only — skip) | N/A |
| `libgstreamer1.0-0` | `gstreamer` | extra |
| `libgstreamer-plugins-base1.0-0` | `gst-plugins-base-libs` | extra |
| `gstreamer1.0-plugins-base` | `gst-plugins-base` | extra |

## Path Differences

| Debian Path | Arch Path | Notes |
|---|---|---|
| `/usr/sbin/ufw` | `/usr/bin/ufw` | Arch merged /usr |
| `/usr/sbin/nft` | `/usr/bin/nft` | |
| `/usr/sbin/iptables` | `/usr/bin/iptables` | |
| `/usr/sbin/ip6tables` | `/usr/bin/ip6tables` | |
| `/usr/sbin/wg` | `/usr/bin/wg` | |
| `/usr/sbin/reboot` | `/usr/bin/reboot` | |
| `/usr/sbin/shutdown` | `/usr/bin/shutdown` | |
| `/usr/sbin/poweroff` | `/usr/bin/poweroff` | |
| `/usr/sbin/traceroute` | `/usr/bin/traceroute` | |
| `/usr/sbin/netstat` | `/usr/bin/netstat` | |
| `/usr/sbin/ss` | `/usr/bin/ss` | |
| `/usr/sbin/lsof` | `/usr/bin/lsof` | |
| `/usr/sbin/dnsmasq` | `/usr/bin/dnsmasq` | |
| `/var/lib/dpkg/info/` | `/var/lib/pacman/local/` | Package DB |
| `/.debian-live-build` | `/.arch-release` | Distro marker |

## Boot System Mapping

| Feature | Debian | Arch |
|---|---|---|
| Initramfs generator | `initramfs-tools` | `mkinitcpio` |
| Kernel module config | `/etc/modprobe.d/` | `/etc/modprobe.d/` (same) |
| Bootloader | GRUB | GRUB/systemd-boot/Limine |
| Init system | systemd | systemd (same) |
| RAM wipe at boot | dracut module | mkinitcpio hook |
| Boot snapshot support | (none native) | Limine `snapshot:` protocol + snapper |

## Distro Detection

```bash
# Portable distro detection
if [ -f /etc/arch-release ]; then
  DISTRO=arch
elif [ -f /etc/debian_version ]; then
  DISTRO=deb
elif [ -f /etc/fedora-release ]; then
  DISTRO=fedora
fi

# Package manager detection
if command -v pacman &>/dev/null; then
  PKG="pacman"
elif command -v apt-get &>/dev/null; then
  PKG="apt"
fi
```
