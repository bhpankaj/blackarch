# systemd-boot + unified kernel image

Installing the boot path on a cloned or bootstrapped Arch system.

## The step

1. `mkinitcpio -k <kver> -g /boot/initramfs-<owner>.img` inside the target root.
   `-g` matters: with `-U`/`--uki` mkinitcpio emits its own UKI into a
   hardcoded `/efi/EFI/Linux` or `/boot/EFI/Linux`, which is not the ESP being
   installed to.
2. `ukify build` once per kernel into `<ESP>/EFI/Linux/<owner>-<kver>.efi`.
   systemd-boot discovers those by itself — no `loader/entries/*.conf` needed.
3. `bootctl --esp-path=<ESP> install`. `--esp-path` is mandatory when the ESP is
   not mounted at `/efi` (a live session): without it bootctl writes into the
   live medium's own ESP. It also writes the fallback `EFI/BOOT/BOOTX64.EFI`.

## Traps

- **ukify must run under the system python.** Its shebang is
  `#!/usr/bin/env python3` and it needs `pefile`, a system package. A python3
  earlier on PATH (a venv, say) has no `pefile` and ukify dies with
  `ModuleNotFoundError: No module named 'pefile'`. Invoke it as
  `/usr/bin/python3 <path-to-ukify>`.
- **`--os-release` needs `@`.** It is `--os-release TEXT|@PATH`; a bare path is
  embedded as the section *text*, so `.osrel` ends up containing
  `/usr/lib/os-release` and systemd-boot has no `PRETTY_NAME` to title the entry
  with. Distro UKI builders that pass a bare path carry this bug; it stays
  invisible only while they also write explicit loader entries.
- **A UKI bakes in its cmdline.** A boot entry cannot override it, so a snapper
  snapshot needs its *own* UKI (different `rootflags=subvol=`), not an entry
  pointing at the kernel's image.
- **Microcode goes in `.ucode`** via ukify's `--microcode`, not as a second
  `--initrd`.
- **efivarfs must be mounted** for `bootctl install` to create the NVRAM entry;
  without it bootctl only copies the binaries and the firmware never finds them.

## Verify

```
objdump -h <uki>.efi | awk '/^ *[0-9]+ \./ {print $2}'
# want .osrel .cmdline .uname .linux .initrd  (+ .ucode when microcode is present)
objcopy -O binary --only-section=.cmdline <uki>.efi /dev/stdout | tr -d '\0'
objcopy -O binary --only-section=.osrel   <uki>.efi /dev/stdout | tr -d '\0'
```
