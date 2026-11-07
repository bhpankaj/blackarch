#!/usr/bin/env python3
"""blackarch-fingerprint-setup — configure fingerprint (fprintd) + PAM + interactive enrollment.
Python port. Keeps existing howdy in /etc/pam.d/hyprlock; adds pam_fprintd.so alongside.
Configures /etc/pam.d/system-auth and /etc/pam.d/hyprlock, installs packages, enrolls.
"""

from __future__ import annotations

import subprocess
import sys
import argparse
import os

FINGERPRINT_PAM = "auth       sufficient                  pam_fprintd.so"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"[run] {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def sudo_write_pam_file(path: str, insert_before: str | None = None, append_after: str | None = None) -> bool:
    result = subprocess.run(
        ["cat", path], capture_output=True, text=True
    )
    content = result.stdout
    if "pam_fprintd.so" in content:
        print(f"[skip] {path} already contains pam_fprintd.so")
        return False
    new_content = content
    lines = content.splitlines(keepends=True)
    new_lines = []
    inserted = False
    for line in lines:
        if not inserted and insert_before and line.startswith(insert_before):
            new_lines.append(FINGERPRINT_PAM + "\n")
            inserted = True
        new_lines.append(line)
    if not inserted and append_after:
        # append after specific line
        for i, line in enumerate(new_lines):
            if append_after in line:
                new_lines.insert(i + 1, FINGERPRINT_PAM + "\n")
                inserted = True
                break
    if not inserted:
        # fallback: insert after first auth line that isn't preauth/comment
        for i, line in enumerate(new_lines):
            stripped = line.strip()
            if stripped.startswith("auth") and "preauth" not in stripped and not stripped.startswith("#"):
                new_lines.insert(i + 1, FINGERPRINT_PAM + "\n")
                inserted = True
                break
    if not inserted:
        new_lines.insert(3, FINGERPRINT_PAM + "\n")
    result = subprocess.run(
        ["sudo", "tee", path], input="".join(new_lines), capture_output=False, text=True
    )
    return result.returncode == 0


def configure_system_auth() -> bool:
    print("[config] /etc/pam.d/system-auth")
    # Insert before pam_unix.so line
    result = subprocess.run(
        ["grep", "-n", "pam_unix.so", "/etc/pam.d/system-auth"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("[warn] pam_unix.so not found in system-auth; falling back to generic insert")
    return sudo_write_pam_file(
        "/etc/pam.d/system-auth", insert_before="auth       [success=1"
    )


def configure_hyprlock() -> bool:
    print("[config] /etc/pam.d/hyprlock (keep howdy, add fprintd)")
    return sudo_write_pam_file(
        "/etc/pam.d/hyprlock", append_after="pam_howdy.so"
    )


def install_packages() -> bool:
    print("[install] pacman -Sy --noconfirm fprintd libfprint")
    r = run(["pacman", "-Sy", "--noconfirm", "fprintd", "libfprint"], check=False)
    if r.returncode != 0:
        # Try with sudo explicitly
        r = run(["sudo", "pacman", "-S", "--noconfirm", "fprintd", "libfprint"], check=False)
    return r.returncode == 0


def restart_fprintd() -> bool:
    print("[service] systemctl restart fprintd")
    r = run(["systemctl", "restart", "fprintd"], check=False)
    return r.returncode == 0


def discover_device() -> bool:
    r = run(["fprintd-list", os.getenv("USER", "black")], check=False)
    if r.returncode == 0 and "found" in (r.stdout or ""):
        print(f"[device] {r.stdout.strip()}")
        return True
    else:
        print(f"[warn] fprintd device check: {r.stdout or r.stderr or 'no output'}")
        return False


def enroll() -> bool:
    user = os.getenv("USER", "black")
    print(f"[enroll] Running fprintd-enroll for user {user}. Scan finger when prompted...")
    r = subprocess.run(["fprintd-enroll", user], capture_output=False, text=True)
    return r.returncode == 0


def verify() -> bool:
    user = os.getenv("USER", "black")
    print(f"[verify] fprintd-verify for user {user}")
    r = run(["fprintd-verify", user], check=False)
    return r.returncode == 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Fingerprint setup + enrollment + auth (system-auth + hyprlock)"
    )
    parser.add_argument("--enroll", action="store_true", help="Run interactive fingerprint enrollment")
    parser.add_argument("--verify", action="store_true", help="Test fingerprint verification")
    parser.add_argument("--skip-install", action="store_true", help="Skip package install")
    parser.add_argument("--skip-pam", action="store_true", help="Skip PAM configuration")
    args = parser.parse_args(argv)

    if not args.skip_install:
        if not install_packages():
            print("[error] package install failed")
            return 1
    if not args.skip_pam:
        configure_system_auth()
        configure_hyprlock()
    restart_fprintd()
    discover_device()
    if args.enroll:
        if not enroll():
            print("[warn] enrollment returned non-zero (expected if no scan or device unavailable)")
        else:
            print("[ok] enrollment completed")
    if args.verify:
        verify()
    if args.enroll or args.verify or (not args.skip_pam):
        print("[done] fingerprint setup complete.")
        print("[note] Actual device on this host: Egis Technology (LighTuning) Match-on-Chip,")
        print("       not Goodix 511. Verify with 'fprintd-list $USER'.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
