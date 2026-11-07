# Crypttab format for TPM2

Use `blkid -U <device>` for UUID discovery; fall back to parsing `blkid <device>` output (`UUID="..."`), then backing disk (`backing_disk()` for partition -> disk).

Always include `tpm2-device=auto` in the options field (never omit it for `setup_tpm`).

Format: `<name> UUID="<uuid>"    none    tpm2-device=auto`

Mapper naming: `luks-<UUID>` for every non-root entry (e.g., `luks-dbfa0647-b941-4878-ab09-c84ba0c6879c`). Root device excluded from crypttab in `setup_tpm()`.

## Deduplication rule
Before writing crypttab or fstab, read the current file and **replace** matching entries rather than append. After the write, the file must contain exactly one entry for the target device or mount point.

- **crypttab**: match by mapper name (first field) or by `UUID="<uuid>"` substring in the line.
- **fstab**: match by mount target (second field).
