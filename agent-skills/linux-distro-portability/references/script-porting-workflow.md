# Debian-to-Arch Script Porting Workflow

## Overview

When porting a large Debian deps-install or binary-install script (100KB+) to Arch, use this structured approach.

## Step 1: Inventory the Original

```bash
# List all Debian-specific references
grep -n 'apt-get\|dpkg\|/etc/apt\|DEBIAN_FRONTEND\|initramfs\|dracut\|resolvconf\|live-build' <script>

# Extract all package names from apt-get install lines
grep -oP '(?<=apt-get install -y )[a-z0-9._+-]+' <script> | sort -u

# Find package list variables
grep -n 'PACKAGES=\|_PACKAGES=\|packages_to_install\|missing_packages' <script>
```

## Step 2: Build the Package Mapping

Create a `pkg_map()` function that maps each Debian package to its Arch equivalent:

```bash
pkg_map() {
  local deb="$1"
  case "$deb" in
    # Same name on both distros
    curl|wget|openssl|ca-certificates|coreutils|findutils|grep|procps|psmisc \
    |systemd|sudo|dmidecode|lsof|acl|util-linux|mount|uuid-runtime)
      echo "$deb" ;;
    # Renamed packages
    build-essential) echo "base-devel" ;;
    dnsutils|bind9-dnsutils) echo "bind" ;;
    conky-all) echo "conky" ;;
    # Debian-only (skip)
    apt-transport-tor|systemd-resolved|cryptsetup-initramfs \
    |cryptsetup-nuke-password|unattended-upgrades|dracut|initramfs-tools \
    |ram-wipe|resolvconf)
      echo "" ;;
    # Unknown — skip
    *) echo "" ;;
  esac
}
```

## Step 3: Create the Install Helper

```bash
_install_pkgs() {
  local -a pkgs=()
  local deb arch
  for deb in "$@"; do
    arch=$(pkg_map "$deb")
    [[ -n "$arch" ]] && pkgs+=("$arch")
  done
  # Deduplicate
  IFS=$'\n' read -r -d '' -a pkgs < <(printf '%s\n' "${pkgs[@]}" | sort -u) || true
  [[ ${#pkgs[@]} -eq 0 ]] && return 0
  pacman -S --noconfirm --needed "${pkgs[@]}"
}
```

## Step 4: AUR Helper Detection

```bash
detect_aur_helper() {
  if command -v yay >/dev/null 2>&1; then echo "yay"
  elif command -v paru >/dev/null 2>&1; then echo "paru"
  elif command -v trizen >/dev/null 2>&1; then echo "trizen"
  elif command -v pikaur >/dev/null 2>&1; then echo "pikaur"
  else echo ""; fi
}
```

## Step 5: Path Compatibility Symlinks

```bash
# Debian /usr/sbin → Arch /usr/bin
for cmd in ufw nft iptables ip6tables wg reboot shutdown poweroff \
           traceroute netstat ss lsof; do
  [[ -f "/usr/bin/$cmd" && ! -e "/usr/sbin/$cmd" ]] && \
    ln -sf "/usr/bin/$cmd" "/usr/sbin/$cmd"
done
```

## Step 6: Sudoers Configuration

- Debian uses `%sudo` group; Arch uses `%wheel` group
- Update all binary paths from `/usr/sbin/` to `/usr/bin/`
- Validate with `visudo -c -f <file>`

## Step 7: Debug Collector Adaptation

Replace dpkg queries:
- `dpkg -l` → `pacman -Q`
- `dpkg -l | grep ^ii` → `pacman -Q | grep <pattern>`
- `dpkg-query -W -f='${Status}'` → `pacman -Qi <pkg>`
- `dpkg -s <pkg>` → `pacman -Qi <pkg>`

Replace initramfs paths:
- `/etc/initramfs-tools/` → `/etc/mkinitcpio.conf` + `/usr/lib/initcpio/`
- `/usr/share/initramfs-tools/hooks/` → `/usr/lib/initcpio/hooks/`
- `/usr/share/initcpio/install/` → `/usr/lib/initcpio/install/`

## Step 8: Syntax Check

Always run `bash -n <script>` after writing — catches typos that would fail silently at runtime.

## Common Pitfalls

- The original script may contain typos in package names (e.g. `firejanger` instead of `firejail`) — these will silently fail on Arch since pacman won't find them
- `pacman -S` with a non-existent package name will fail the entire transaction — always verify package names exist first with `pacman -Ss`
- The `pkg_map` function should return empty string for unknown packages, not the original name — otherwise pacman will fail trying to install a Debian package name
- When the original script has `apt-get install -y $var` with a variable, the ported version must handle word splitting carefully — use arrays, not strings
