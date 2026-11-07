---
name: custom-arch-iso
description: Build custom Arch Linux ISO with archiso.
version: 1.0.0
author: black
license: MIT
metadata:
  hermes:
    tags: [arch, linux, iso, archiso, desktop, hyprland]
    related_skills: [arch-iso, linux-customization]
---

## When to Use
- Building a custom Arch Linux ISO with a desktop environment
- Creating a live/rescue ISO with Hyprland, Quickshell, or other WMs
- Adding archinstall to a custom ISO
- Troubleshooting archiso build failures

# Custom Arch Linux ISO Builder

Build a custom Arch Linux ISO with archiso.

## Quick Reference

1. Install archiso: `sudo pacman -S archiso`
2. Copy releng profile: `cp -r /usr/share/archiso/configs/releng ~/archiso-profiles/myprofile`
3. Edit `profiledef.sh` (iso_name, iso_label, install_dir)
4. Add packages to `packages.x86_64`
5. Customize `airootfs/` (user accounts, configs, services)
6. Build: `sudo mkarchiso -v -w ./work -o ./out .`

## Profile Structure

```
myprofile/
├── profiledef.sh          # ISO name, label, boot modes, compression
├── packages.x86_64        # Package list (one per line)
├── pacman.conf            # Pacman config for the live session
├── airootfs/              # Root filesystem overlay
│   ├── etc/passwd         # Add live user here
│   ├── etc/shadow
│   ├── etc/group
│   ├── etc/gshadow
│   ├── etc/sddm.conf       # Auto-login config
│   ├── etc/motd
│   ├── home/live/         # Live user home with dotfiles
│   └── usr/local/bin/     # Custom scripts
├── efiboot/               # UEFI boot config
├── grub/                  # GRUB config (BIOS)
└── syslinux/              # Syslinux config (BIOS)
```

## Key Steps

### 1. Live User Setup

Append to `airootfs/etc/passwd`:
```
live:x:1000:1000:Live User:/home/live:/usr/bin/zsh
```

Append to `airootfs/etc/shadow`:
```
live::1000::0:99999:7:::
```

Append to `airootfs/etc/group`:
```
live:x:1000:
```

### 2. Display Manager (ly or SDDM)

**ly (recommended for minimal ISOs):**

Replace `sddm` with `ly` in `packages.x86_64`. Create `airootfs/etc/ly/config.ini`:
```ini
animation = fade
clock = %c
user = live
session = /usr/share/wayland-sessions/hyprland.desktop
hide_border = false
term_reset_cmd = /usr/bin/tput reset
min_uid = 1000
max_uid = 60000
wayland = true
xauthority = /run/user/1000/.Xauthority
```

Enable service:
```bash
ln -sf /usr/lib/systemd/system/ly.service \
  airootfs/etc/systemd/system/multi-user.target.wants/ly.service
```

Remove any leftover SDDM files: `airootfs/etc/sddm.conf`, `airootfs/etc/systemd/system/multi-user.target.wants/sddm.service`.

**SDDM (alternative):**

Create `airootfs/etc/sddm.conf`:
```ini
[Autologin]
User=live
Session=hyprland.desktop

[Theme]
Current=breeze
```

Enable in `airootfs/etc/systemd/system/multi-user.target.wants/`:
```bash
ln -sf /usr/lib/systemd/system/sddm.service \
  airootfs/etc/systemd/system/multi-user.target.wants/sddm.service
```

### 3. Hyprland + Quickshell Session

Hyprland config: `airootfs/home/live/.config/hypr/hyprland.conf`
Quickshell config: `airootfs/etc/xdg/quickshell/myprofile/shell.qml`

Launch quickshell from hyprland.conf:
```
exec-once = quickshell -c /etc/xdg/quickshell/myprofile/shell.qml
```

### 4. Installer (archinstall)

archinstall is already in the releng package list. Create a desktop entry:

```ini
[Desktop Entry]
Name=Install
Exec=install-launcher
Icon=system-software-install
Type=Application
```

And a launcher script at `airootfs/usr/local/bin/install-launcher`:
```bash
#!/bin/bash
exec kitty --title "Installer" -- /usr/bin/archinstall
```

### 5. Wallpaper

Use full font path with ImageMagick (fontconfig names may not resolve):
```bash
magick -size 1920x1080 xc:'#1a1b26' \
  -fill '#88c0d0' \
  -font '/usr/share/fonts/TTF/JetBrainsMono-ExtraBold.ttf' \
  -pointsize 48 -gravity center \
  -annotate 0 'MyISO' \
  airootfs/usr/share/backgrounds/myiso/bg.jpg
```

## Adding Third-Party Repositories

### Chaotic Arch AUR

Add to `pacman.conf` after existing repos:
```ini
[chaotic-aur]
Include = /etc/pacman.d/chaotic-mirrorlist
```

Add `chaotic-keyring` and `chaotic-mirrorlist` to `packages.x86_64` so the live session can resolve packages.

### BlackArch

```ini
[blackarch]
Include = /etc/pacman.d/blackarch-mirrorlist
```

## Adding Limine Bootloader with Snapshots

Limine is not natively supported by mkarchiso (there is no `limine` bootmode). Adding it needs a post-build remaster — read the warning below before following this section.

**WARNING: `limine deploy` does not exist.** limine >= 12 exposes only `bios-install`, `enroll-config`, `version`, `help` (`limine --help`). A wrapper calling `limine deploy` always fails. Loop-mounting a built ISO to copy `limine.cfg` also never works: ISO9660 is read-only. To actually boot limine you must remaster the ISO with xorriso (add `limine-bios.sys` + `limine.cfg`, and an El Torito entry for `limine-bios-cd.bin`) and then run `limine bios-install <iso>`. The plain mkarchiso ISO (syslinux + systemd-boot) is the reliable path.

### Profile Setup

1. Add `limine` to `packages.x86_64`
2. Create `limine/limine.cfg` (UEFI) and `limine/limine-bios.cfg` (BIOS) in the profile directory
3. Do NOT add limine to `bootmodes` in `profiledef.sh` — mkarchiso rejects unknown bootmodes. Limine is deployed by the wrapper script after the build.

### Limine Config Format

```
TIMEOUT=5
GRAPHICS=yes

:Entry Name (UEFI)
    PROTOCOL=linux
    KERNEL_PATH=boot:///boot/x86_64/vmlinuz-linux
    MODULE_PATH=boot:///boot/x86_64/initramfs-linux.img
    KERNEL_CMDLINE=archisobasedir=hyprarch archisosearchuuid=${UUID} quiet splash
```

### Snapshot Boot Entries

Add snapshot entries to limine.cfg for booting into different system states:

```
:Snapshot - Base System (UEFI)
    PROTOCOL=linux
    KERNEL_PATH=boot:///boot/x86_64/vmlinuz-linux
    MODULE_PATH=boot:///boot/x86_64/initramfs-linux.img
    KERNEL_CMDLINE=archisobasedir=hyprarch archisosearchuuid=${UUID} quiet snapshot=1
```

Add `limine-snapper-sync` and `snapper` to packages for snapshot management.

### Build Wrapper Script

Create `build-with-limine.sh` in the profile directory:

```bash
#!/bin/bash
set -e
PROFILE_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="${PROFILE_DIR}/work"
OUT_DIR="${PROFILE_DIR}/out"

rm -rf "${WORK_DIR}" "${OUT_DIR}"
sudo mkarchiso -v -w "${WORK_DIR}" -o "${OUT_DIR}" "${PROFILE_DIR}"

ISO_FILE=$(find "${OUT_DIR}" -name '*.iso' -type f | head -1)

# Deploy limine
# NOTE: `limine deploy` DOES NOT EXIST (limine >= 12 has only bios-install/enroll-config).
# The mount-and-copy steps below also fail: ISO9660 is read-only. Remaster with xorriso instead.
# sudo limine bios-install "${ISO_FILE}"

# Mount and add configs
sudo mkdir -p /mnt/limine-iso
sudo mount -o loop "${ISO_FILE}" /mnt/limine-iso
sudo cp "${PROFILE_DIR}/limine/limine.cfg" /mnt/limine-iso/limine.cfg
sudo cp "${PROFILE_DIR}/limine/limine-bios.cfg" /mnt/limine-iso/boot/limine-bios.cfg
sudo mkdir -p /mnt/limine-iso/EFI/BOOT
sudo cp /usr/share/limine/BOOTX64.EFI /mnt/limine-iso/EFI/BOOT/BOOTX64.EFI
sudo umount /mnt/limine-iso
```

Install limine on the host first: `sudo pacman -S limine`.

## Common Pitfalls

### File Conflicts
Two types of conflicts can occur:

**airootfs vs package:** If a file in `airootfs/` is also provided by a package, the build fails with `conflicting files`. Fix: Remove the file from `airootfs/` — packages provide their own configs.

**Package vs package:** Two packages in `packages.x86_64` may ship the same file (e.g., `grml-zsh-config` and `athena-zsh` both provide `/etc/skel/.zshrc`). Fix: Remove the less relevant package from the list.

### ImageMagick Font Resolution
`magick -font 'JetBrains Mono'` may fail with "unable to read font". Use the full TTF path instead:
```bash
-font '/usr/share/fonts/TTF/JetBrainsMono-ExtraBold.ttf'
```

### Build Directory
Clean before rebuilding:
```bash
rm -rf ./work ./out
```

### Build Time
Full build with desktop packages takes 5-15 minutes depending on network speed.

### Limine Deploy
There is no `limine-deploy` binary and no `limine deploy` subcommand — limine >= 12 exposes only `bios-install` and `enroll-config`. `limine bios-install <iso>` writes the MBR/boot sector but cannot add files. Adding limine configs/binaries to an already-built ISO requires a xorriso remaster. Install limine on the host first: `sudo pacman -S limine`.

### Package List Generation
To add all currently installed packages to the ISO:
```bash
pacman -Qq | sort -u > /tmp/all-installed.txt
cat packages.x86_64 | grep -v '^#' | grep -v '^$' | sort -u > /tmp/existing.txt
comm -23 /tmp/all-installed.txt /tmp/existing.txt > /tmp/new-packages.txt
cat /tmp/new-packages.txt >> packages.x86_64
```

Pitfall: Host-installed packages may not exist in any enabled repo (e.g., manually built, AUR-only without repo configured, or distro-specific packages like blackarch-*). The build will fail with `error: target not found: <pkg>`. Fix: Remove unavailable packages from the list before building.

### Live User Sudoers
Create `airootfs/etc/sudoers.d/live` with `live ALL=(ALL) ALL` and chmod 0440.

## Validate the Package List Before Building

A list copied from `pacman -Qq` contains packages that exist in no enabled repo (AUR-only, distro-specific, removed) and pacstrap dies with `error: target not found: <pkg>`. Check first:

```bash
grep -v '^#' packages.x86_64 | grep -v '^$' | tr -d ' ' | sort -u > /tmp/want.txt
pacman -Sl core extra blackarch athena chaotic-aur | awk '{print $2}' | sort -u > /tmp/avail.txt
comm -23 /tmp/want.txt /tmp/avail.txt    # fix or drop every line printed
```

List exactly the repos the profile's `pacman.conf` enables — a package that only exists in a repo the ISO does not enable still fails. Mirrorlist files referenced by `Include =` must also exist inside `airootfs/etc/pacman.d/` (e.g. `chaotic-mirrorlist`), not just on the host.

Pitfall: never let `pacman -Sl` output go straight into agent output — 20k+ lines get truncated and you silently analyse a partial list. Write to a file and `comm`/`wc` in the shell.

Pitfall: the Arch `[community]` repo no longer exists; a pacman.conf that still includes it fails with `failed retrieving file 'community.db' ... 404` on every mirror.

## Trim a Pentest ISO to Role Tools

Athena/BlackArch keep curated tool lists in `~/.config/cyber-toolkit/roles/*.role`. To keep only those tools:

```bash
cat ~/.config/cyber-toolkit/roles/*.role | sed 's/#.*//' | tr -s ' \t' '\n' | sort -u > /tmp/roles.txt
```

Classify "is this a pentest tool?" with BlackArch's category groups, not the repo — the blackarch repo also carries libraries and unrelated packages:

```bash
G=$(pacman -Sg | awk '{print $1}' | grep -E '^blackarch' | tr '\n' ' ')
pacman -Sg $G | awk '{print $2}' | sort -u > /tmp/ba_tools.txt
```

Then delete `packages.x86_64` entries present in `/tmp/ba_tools.txt` (or in a curated extra-repo list: nmap, metasploit, sqlmap, hydra, john, hashcat, aircrack-ng, gobuster, nikto, wireshark-qt, wifite, kismet, reaver, radare2, ghidra, nasm, mitmproxy, proxychains-ng, wpscan, exploitdb, zaproxy, scapy, tcpdump, socat, seclists, ...) that are NOT in `/tmp/roles.txt`. Always keep repo infrastructure (`blackarch-keyring`, `blackarch-mirrorlist`, `athena-keyring`, `athena-mirrorlist`, `chaotic-keyring`, `chaotic-mirrorlist`, `cyber-toolkit`, `htb-toolkit`).

Caveats: most role tools are already on the host, so a host-derived list needs few deletions — count before promising a big win (32 of 2817 in one real case). This rule also removes wordlist/data packages (`seclists`, `exploitdb`) and general utilities (`tcpdump`, `socat`, `openbsd-netcat`); confirm with the user before dropping those.

## Build Time and Disk Budget

`pacstrap` prints `Total Installed Size` — the airootfs will be that big. Peak disk use is roughly airootfs + squashfs + ISO (~2.2x airootfs) plus the host pacman cache. A 2800-package desktop+pentest profile is ~43 GiB installed and needs ~100 GiB free to finish; an ENOSPC kill mid-pacstrap is the usual failure.

mkarchiso writes `work/<buildmode>.<function>` markers and skips finished steps on re-run. `_make_packages` only gets its marker after pacstrap succeeds, so a build killed mid-install leaves a half-populated airootfs with no marker: `rm -rf work out` and rebuild — resuming can treat half-extracted packages as installed. Keeping `work/` after a *successful* pacstrap does skip the install step.

`airootfs/etc/passwd`, `shadow`, `group`, `gshadow` do NOT conflict with the `filesystem` package (releng ships passwd/shadow too) — the custom airootfs copy runs before pacstrap and the live user survives.