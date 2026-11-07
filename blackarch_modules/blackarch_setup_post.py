#!/usr/bin/env python3
"""blackarch:summary=Post-install setup verification and checklist"""
import subprocess, os, sys

def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)

checks = []
# root subvol
rc, out = run("findmnt -no SOURCE /")
checks.append(("Root is LUKS/btrfs subvol @", rc == 0 and "[/@]" in out, out))
# sudo
rc, out = run("sudo -n cat /etc/sudoers.d/uid-1000")
checks.append(("UID-1000 NOPASSWD sudo", rc == 0 and "NOPASSWD:ALL" in out, "ok" if rc==0 else out))
# hooks
rc, out = run("grep '^HOOKS=' /etc/mkinitcpio.conf")
checks.append(("sd-encrypt hook present", rc == 0 and "sd-encrypt" in out, out))
# efibootmgr
rc, out = run("efibootmgr 2>/dev/null | grep -iE 'limine|systemd|linux boot'")
checks.append(("Bootloader EFI entry present", rc == 0 and out != "", "ok" if rc==0 else "none"))
# home subvol
rc, out = run("findmnt -no SOURCE /home")
checks.append(("Home subvol @home mounted", rc == 0 and "[/@home]" in out, out))
# snapper
rc, out = run("test -f /etc/snapper/configs/root && echo present")
checks.append(("Snapper root config exists", rc == 0 and "present" in out, "MISSING" if "present" not in out else "ok"))
# text scaling
rc, out = run("gsettings get org.gnome.desktop.interface text-scaling-factor")
checks.append(("GTK text-scaling set", rc == 0, out))
# webcam
rc, out = run("ls /dev/video0 2>/dev/null")
checks.append(("Webcam device present", rc == 0, "/dev/video0" if rc==0 else "none"))
# ulaa
rc, out = run("flatpak list 2>/dev/null | grep -i ulaa")
checks.append(("Ulaa flatpak installed", rc == 0 and out.strip() != "", "MISSING" if rc != 0 else "ok"))

print("Post-install setup verification:")
for name, ok, detail in checks:
    print(f"  [{'OK' if ok else '!!'}] {name}: {detail}")

# Run Galaxy Book camera fix scripts
for sc in ("/opt/blackarch/galaxybook-camera/galaxybook-camera-fix.sh",
           "/opt/blackarch/galaxybook-camera/reapply-flicker-fix.sh"):
    if os.path.exists(sc):
        print(f"\nRunning {sc}")
        subprocess.run(f"bash {sc}", shell=True)

# Kodachi setup (if dashboard not present)
rc, out = run("test -f /usr/share/applications/kodachi-dashboard.desktop && echo present")
checks.append(("Kodachi dashboard installed", rc == 0 and "present" in out, "MISSING" if "present" not in out else "ok"))
if "present" not in out:
    print("\n  -> running blackarch setup kodachi")
    subprocess.run("blackarch setup kodachi", shell=True)

# Dynamic LUKS SD-card check: if a LUKS device with UUID 04244121-... exists, require an fstab entry
rc, out = run("sudo blkid 2>/dev/null | grep -i '04244121-3fee-4ce4-a0ca-2217d37faa1d'")
if "crypto_LUKS" in out:
    rc2, out2 = run("grep -i '04244121-3fee-4ce4-a0ca-2217d37faa1d' /etc/fstab")
    rc3, out3 = run("sudo grep -i '04244121-3fee-4ce4-a0ca-2217d37faa1d' /etc/crypttab")
    checks.append(("LUKS SD-card crypttab entry", rc3 == 0 and out3.strip() != "", "MISSING" if rc3 != 0 else "ok"))
    if rc2 != 0 or rc3 != 0:
        print("\n  ! LUKS SD card found. Add crypttab + fstab entries (TPM2 unlock):")
        print("    crypttab: luks-04244121-3fee-4ce4-a0ca-2217d37faa1d  UUID=04244121-3fee-4ce4-a0ca-2217d37faa1d  none  tpm2-device=auto")
        print("    fstab:    /dev/mapper/luks-04244121-3fee-4ce4-a0ca-2217d37faa1d  /run/media/black/luks-04244121-3fee-4ce4-a0ca-2217d37faa1d  auto  noauto,user,nofail  0  0")

# Auto-detect and install webcam (IPU6/IPU7) irrespective of status
gen = subprocess.run(
    ["python3", "-c", "import sys; sys.path.insert(0, '/opt/blackarch'); from blackarch_modules.blackarch_webcam_setup import ipu_generation; print(ipu_generation())"],
    capture_output=True, text=True).stdout.strip()
flag = "--ipu7" if gen == "IPU7" else ""  # default = open libcamera build
print(f"\nWebcam auto-setup: detected {gen}, running {flag}")
subprocess.run(f"sudo /opt/blackarch/bin/blackarch-webcam-setup {flag}".strip(), shell=True)

missing = [n for n, ok, _ in checks if not ok]
if missing:
    print("\nIncomplete — attempting fixes:")
    if "Snapper root config exists" in missing:
        print("  -> creating snapper root config + baseline snapshot")
        subprocess.run("sudo rmdir /.snapshots 2>/dev/null; sudo snapper -c root create-config /", shell=True)
        subprocess.run("sudo snapper -c root create --description 'baseline after post-install'", shell=True)
    if "Ulaa flatpak installed" in missing:
        print("  -> installing Ulaa via flatpak")
        subprocess.run("flatpak install -y flathub com.ulaa.Ulaa", shell=True)
    # re-check
    print("\nRe-checking:")
    for name, ok, detail in checks:
        print(f"  [{'OK' if ok else '!!'}] {name}")
else:
    print("\nAll checks passed.")
