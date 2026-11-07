#!/usr/bin/env python3
# blackarch:summary=Returns true when running on a laptop (has a lid or laptop chassis).
"""blackarch-hw-laptop — true (exit 0) when running on a laptop.

Python port of the bash original. A lid switch is the definitive signal for
clamshell-capable hardware; the DMI chassis type is the fallback for laptops
that do not expose an ACPI lid button. 8=Portable 9=Laptop 10=Notebook
14=Sub Notebook 30=Tablet 31=Convertible 32=Detachable.
"""

import sys
from pathlib import Path

DMI_CHASSIS_TYPE = Path("/sys/class/dmi/id/chassis_type")
LAPTOP_CHASSIS_TYPES = frozenset({"8", "9", "10", "14", "30", "31", "32"})


def has_lid_switch() -> bool:
    """/proc/acpi/button/lid/*/state — existence is the test, not the content."""
    return any(Path("/proc/acpi/button/lid").glob("*/state"))


def laptop_chassis() -> bool:
    """`case $(< /sys/class/dmi/id/chassis_type)` over the portable chassis types."""
    try:
        chassis = DMI_CHASSIS_TYPE.read_text(errors="replace").strip()
    except OSError:
        return False
    return chassis in LAPTOP_CHASSIS_TYPES


def main(argv: list[str]) -> int:
    if has_lid_switch():
        return 0
    return 0 if laptop_chassis() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
