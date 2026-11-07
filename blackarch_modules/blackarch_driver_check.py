#!/usr/bin/env python3
"""blackarch-driver-check — scan PCI, USB, dmesg, sysfs for missing/unbound drivers.
Python port. Reports devices with no kernel driver, missing firmware, or unknown IDs.
"""

from __future__ import annotations

import subprocess
import sys
import os


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def header(title: str) -> None:
    print(f"\n=== {title} ===")


def main(argv: list[str]) -> int:
    missing: list[str] = []
    notes: list[str] = []

    header("PCI devices (lspci -nnk)")
    r = run(["lspci", "-nnk"])
    current_device = ""
    for line in r.stdout.splitlines():
        # Device line: 00:02.0 ... [xxxx:yyyy]
        if line.startswith("\t") and ":" in line and "[" in line:
            # Extract device info without leading tab
            pass
        # A full device entry starts with a bus:slot.func format (not tab-indented)
        # But lspci -nnk outputs device lines with leading whitespace only for sub-items.
        # The first non-empty line that isn't a tab-indented sub-item is the device.
        if line.startswith("00:") or line.startswith("01:") or line.startswith("02:") or line.startswith("03:") or line.startswith("04:") or line.startswith("05:") or line.startswith("06:") or line.startswith("07:") or line.startswith("08:"):
            current_device = line.strip()
            print(current_device)
        elif line.startswith("\t"):
            content = line.strip()
            print("  " + content)
            if "Kernel driver in use:" in content:
                driver = content.split(":", 1)[1].strip()
                if not driver or driver == "unknown" or "?" in driver:
                    missing.append(f"PCI {current_device.split()[0]} — no driver ({current_device.split()[-2] if len(current_device.split()) > 2 else 'unknown'})")
                    notes.append(f"  No driver for {current_device}")
            if "Kernel modules:" in content:
                modules = content.split(":", 1)[1].strip()
                if not modules or modules == "" or modules == "unknown":
                    missing.append(f"PCI {current_device.split()[0]} — no modules")
        else:
            current_device = ""

    # Check for devices with no driver line at all
    header("PCI driver gap check")
    r = run(["lspci", "-nn"])
    devices_without_driver: list[str] = []
    # A simpler approach: find lines in lspci -nnk that are device lines and check if they have a driver line after them
    # We already printed; now summarize.
    # We can also scan /sys/bus/pci/devices for devices without a driver symlink.
    sys_pci_dir = "/sys/bus/pci/devices/"
    if os.path.isdir(sys_pci_dir):
        for entry in sorted(os.listdir(sys_pci_dir)):
            driver_link = os.path.join(sys_pci_dir, entry, "driver")
            has_driver = os.path.islink(driver_link) or os.path.exists(driver_link)
            if not has_driver:
                # Check vendor/device from vendor/device files
                vendor_path = os.path.join(sys_pci_dir, entry, "vendor")
                device_path = os.path.join(sys_pci_dir, entry, "device")
                vendor = device = ""
                try:
                    with open(vendor_path) as f:
                        vendor = f.read().strip()
                except Exception:
                    pass
                try:
                    with open(device_path) as f:
                        device = f.read().strip()
                except Exception:
                    pass
                # Only report if it has vendor/device (not empty)
                if vendor or device:
                    info = f"{entry} vendor={vendor or 'unknown'} device={device or 'unknown'}"
                    devices_without_driver.append(info)
                    missing.append(f"PCI /sys {entry} — no driver symlink")
    if devices_without_driver:
        print("PCI devices missing /sys driver symlink:\n  " + "\n  ".join(devices_without_driver))
    else:
        print("All scanned PCI devices have driver symlinks.")

    header("USB devices")
    r = run(["lsusb", "-v"], check=False)
    if r.returncode != 0 or not r.stdout.strip():
        print("lsusb not available or no USB devices found (install usbutils for full scan).")
        # Try /sys/bus/usb/devices
        usb_sys_dir = "/sys/bus/usb/devices/"
        if os.path.isdir(usb_sys_dir):
            for entry in sorted(os.listdir(usb_sys_dir)):
                manufacturer_path = os.path.join(usb_sys_dir, entry, "manufacturer")
                product_path = os.path.join(usb_sys_dir, entry, "product")
                driver_link = os.path.join(usb_sys_dir, entry, "driver")
                has_driver = os.path.islink(driver_link) or os.path.exists(driver_link)
                mfr = product = ""
                try:
                    with open(manufacturer_path) as f:
                        mfr = f.read().strip()
                except Exception:
                    pass
                try:
                    with open(product_path) as f:
                        product = f.read().strip()
                except Exception:
                    pass
                info = f"USB {entry} mfr={mfr or 'unknown'} product={product or 'unknown'} driver={'loaded' if has_driver else 'NONE'}"
                print(info)
                if not has_driver:
                    missing.append(f"USB {entry} — no driver")
    else:
        for line in r.stdout.splitlines():
            print(line)

    header("dmesg — missing firmware / unknown / driver failures")
    r = run(["dmesg"])
    hits: list[str] = []
    keywords = ["firmware", "missing", "unknown", "not loaded", "no such device", "cannot find", "not supported", "driver", "failed", "not recognized"]
    for line in r.stdout.splitlines():
        low = line.lower()
        if any(k in low for k in keywords):
            # Filter very noisy non-driver lines
            noisy = ["timestamp", "time", "clock", "tick", "hz"]
            if any(n in low for n in noisy) and "firmware" not in low and "missing" not in low:
                continue
            # Only include if it mentions a device or hardware
            if any(d in low for d in ["device", "pci", "usb", "audio", "video", "network", "firmware", "driver", "module"]):
                hits.append(line)
    if hits:
        for h in hits[:30]:
            print(h)
        if len(hits) > 30:
            print(f"... ({len(hits) - 30} more hits; truncated)")
    else:
        print("No dmesg driver/firmware hits found.")

    header("sysfs device scan (scanning /sys/class)")
    for cls in ["net", "input", "video4linux", "sound", "leds", "backlight", "block"]:
        sys_path = f"/sys/class/{cls}"
        if not os.path.isdir(sys_path):
            continue
        print(f"-- /sys/class/{cls} --")
        try:
            for entry in sorted(os.listdir(sys_path)):
                full_path = os.path.join(sys_path, entry)
                # Check for device symlink or driver
                driver_link = None
                # Some devices have driver symlink directly; others via subsystem
                if os.path.islink(os.path.join(full_path, "device", "driver")) if os.path.islink(os.path.join(full_path, "device")) else False:
                    pass
                # Print entry name and whether it has a driver or device link
                device_link_target = ""
                driver_link_target = ""
                try:
                    if os.path.islink(os.path.join(full_path, "device")):
                        device_link_target = os.readlink(os.path.join(full_path, "device"))
                except Exception:
                    pass
                try:
                    if os.path.islink(os.path.join(full_path, "driver")):
                        driver_link_target = os.readlink(os.path.join(full_path, "driver"))
                except Exception:
                    pass
                info_parts = [entry]
                if device_link_target:
                    info_parts.append(f"device={os.path.basename(device_link_target)}")
                else:
                    info_parts.append("device=NONE")
                if driver_link_target:
                    info_parts.append(f"driver={os.path.basename(driver_link_target)}")
                else:
                    info_parts.append("driver=NONE")
                print("  " + " ".join(info_parts))
        except Exception as e:
            print(f"  (scan error: {e})")

    header("Summary — potential missing drivers")
    if missing:
        print(f"Found {len(missing)} potential missing-driver items:")
        for item in missing:
            print("  - " + item)
    else:
        print("No obvious missing drivers detected from lspci + dmesg + sysfs scans.")
        print("Note: Some devices (e.g. fingerprint sensors) may rely on userspace drivers")
        print("      (fprintd/libfprint) rather than kernel modules — verify separately.")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main(sys.argv[1:]))
