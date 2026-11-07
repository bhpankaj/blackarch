# Bootstrapping an Arch root against several repositories

Building a fresh Arch root (rather than cloning a running one) when the target
needs packages from more than one repository — AthenaOS, Blackarch, chaotic-aur,
blackarch.

## Order

1. Copy `/etc/pacman.conf` into the new root.
2. Copy **every** `*-mirrorlist` from `/etc/pacman.d/` into the new root.
   pacstrap copies only the stock `mirrorlist`, so an `Include`d repo would be
   unreadable.
3. `pacstrap <root> base base-devel <kernels> <firmware> <keyrings>`.
   pacstrap copies the host's pacman keyring into the target by default
   (`-G` suppresses it, `-K` initialises an empty one), so packages signed by
   keys the running system already trusts verify without a recv-keys dance.
4. `arch-chroot <root> pacman-key --populate archlinux blackarch athena`.
   The keyring packages from step 3 must already be installed: `--populate`
   reads `/usr/share/pacman/keyrings/<repo>.gpg`, and there is nothing to
   populate from without the package.
5. A repository whose key is not published in a keyring package needs
   `pacman-key --recv-keys <key>` then `--lsign-key <key>` before its keyring
   package can be verified.
6. `arch-chroot <root> pacman -Syy --needed --noconfirm <package set>`.
7. AUR helpers and anything not in a configured repo come last, best-effort.

## Rules

- **`pacman-key --populate <repo>` needs that repo's keyring package installed
  first.** It reads `/usr/share/pacman/keyrings/<repo>.gpg`, and there is nothing
  to populate from without the package.
- **Read package lists out of the source script; do not source it.** A setup
  script that ends in `main "$@"` runs its dispatcher when sourced. Match the
  array textually, and expect multi-line arrays — `NAME=(` on one line, the
  words on the next, `)` on a third.
- **Once the target root exists, pacman reads the target's `pacman.conf`**, not
  the host's, so steps 1-2 must land before step 6.
- **A role/file-driven package list**: strip `#` comments and blank lines, then
  take the first whitespace-separated token per line. Splitting on `:` and ` `
  and taking field 2 yields empty strings for files that are plain package
  names, one per line.

## Verify

```
ls <root>/etc/pacman.d/*-mirrorlist   # every Include in pacman.conf must resolve
arch-chroot <root> pacman -Syy        # must not fail on an unreadable Include
arch-chroot <root> pacman-key --list-keys
```
