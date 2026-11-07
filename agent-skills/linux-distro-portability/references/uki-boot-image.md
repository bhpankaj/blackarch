# Unified Kernel Image (UKI) boot step

Installing a bootable Arch clone/bootstrap: systemd-boot + UKI, and the traps in
building the image.

## The step

1. `mkinitcpio -k <kver> -g /boot/initramfs-<owner>.img` inside the clone. The
   `-g` matters: with `-U`/`--uki` mkinitcpio emits its own UKI into
   `/efi/EFI/Linux` or `/boot/EFI/Linux` — hardcoded, and not the ESP you are
   installing to.
2. `ukify build` once per kernel into `<ESP>/EFI/Linux/<owner>-<kver>.efi`.
   systemd-boot discovers those by itself, so **no `loader/entries/*.conf` is
   needed**.
3. `bootctl --esp-path=<ESP> install`. `--esp-path` is mandatory when the ESP is
   not mounted at `/efi` (a live session): without it bootctl writes into the
   live USB's own ESP.

## Traps

- **ukify must run under the system python.** Its shebang is
  `#!/usr/bin/env python3` and it needs `pefile`, a system package. A python3
  earlier on PATH (a venv, say) has no `pefile` and ukify dies with
  `ModuleNotFoundError: No module named 'pefile'`. Invoke it as
  `/usr/bin/python3 <path-to-ukify>` rather than by name.
- **`--os-release` needs `@`.** It is `--os-release TEXT|@PATH`; a bare path is
  embedded as the section *text*, so `.osrel` ends up containing
  `/usr/lib/os-release` and systemd-boot has no `PRETTY_NAME` to title the entry
  with. Athena's own `rebuild-ukis` has this bug — its UKIs carry the path too,
  which stays invisible only because it writes explicit loader entries.
- **A UKI bakes in its cmdline.** A boot entry cannot override it, so a snapper
  snapshot needs its *own* UKI (different `rootflags=subvol=`), not an entry
  pointing at the kernel's image.
- **Microcode goes in `.ucode`** via ukify's `--microcode`, not as a second
  `--initrd`.
- **efivarfs** must be mounted for `bootctl install` to create the NVRAM entry;
  without it bootctl only copies the binaries and the firmware never finds them.
- `bootctl install` also writes the fallback `EFI/BOOT/BOOTX64.EFI`, so the disk
  stays bootable from the removable-media path.

## Verify

```
objdump -h <uki>.efi | awk '/^ *[0-9]+ \./ {print $2}'
# want: .osrel .cmdline .uname .linux .initrd (.ucode when microcode is present)
objcopy -O binary --only-section=.cmdline <uki>.efi /dev/stdout | tr -d '\0'
objcopy -O binary --only-section=.osrel   <uki>.efi /dev/stdout | tr -d '\0'
```
