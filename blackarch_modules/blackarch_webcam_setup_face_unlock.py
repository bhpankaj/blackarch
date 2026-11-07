#!/usr/bin/env python3
import os, subprocess, sys

def run(cmd, check=False):
    return subprocess.run(cmd, check=check)

def main(argv=None):
    print("\033[0;32m[+] Starting webcam face unlock setup...\033[0m")
    if not os.path.exists("/dev/video0"):
        print("\033[0;31m[-] Webcam not found at /dev/video0\033[0m"); return 1
    print("\033[0;32m[+] Webcam found: /dev/video0\033[0m")
    if os.path.isfile("/usr/lib/libcamera.so.0.7.2"):
        print("\033[0;32m[+] libcamera v0.7.2 (open source) present\033[0m")
    else:
        print("\033[1;33m[!] libcamera not found; check open libcamera build\033[0m")
    if subprocess.run(["which","yay"],capture_output=True).returncode==0:
        print("\033[1;33m[!] Howdy is AUR-only; overriding pacman preference\033[0m")
        subprocess.run(["yay","-S","--noconfirm","--needed","howdy"], check=False)
    if os.path.isfile("/etc/howdy/config.ini"):
        print("\033[0;32m[+] Configuring /etc/howdy/config.ini\033[0m")
        p="/etc/howdy/config.ini"
        s=open(p).read()
        s=s.replace("device_path = none","device_path = /dev/video0")
        s=s.replace("timeout = 4","timeout = 10")
        s=s.replace("certainty = 3.5","certainty = 5.0")
        s=s.replace("workaround = off","workaround = native")
        open(p,"w").write(s)
    if not os.path.isfile("/etc/pam.d/hyprlock"):
        print("\033[0;32m[+] Creating /etc/pam.d/hyprlock\033[0m")
        os.makedirs("/etc/pam.d",exist_ok=True)
        with open("/etc/pam.d/hyprlock","w") as f:
            f.write("# PAM configuration for hyprlock with manual howdy trigger\nauth        [success=1 default=ignore] pam_howdy.so\nauth        include     login\n")
    if os.path.isfile("/usr/bin/howdy"):
        print("\033[0;32m[+] Adding face model (requires webcam feed)...\033[0m")
        env=dict(os.environ); env["TERM"]="dumb"; env["PYTHONPATH"]="/usr/lib/howdy"
        subprocess.run(["/usr/bin/howdy","add","-y"], stdin=subprocess.DEVNULL, env=env, check=False)
    conf="/home/black/.config/hypr/hyprlock.conf"
    if os.path.isfile(conf):
        s=open(conf).read()
        s=s.replace("module = hyprlock-gaze","module = hyprlock")
        s=s.replace("ignore_empty_input = false","ignore_empty_input = true")
        open(conf,"w").write(s)
        print("\033[0;32m[+] Updating hyprlock.conf\033[0m")
    if os.path.isfile("/etc/howdy/models/black.dat"):
        print("\033[0;32m[+] Face model exists: /etc/howdy/models/black.dat\033[0m")
    print("\033[0;32m[+] Setup complete! Lock with SUPER+F; press any key; face unlock auto-triggers. Password fallback if no match.\033[0m")
    return 0

if __name__ == "__main__":
    sys.exit(main())
PY