#!/usr/bin/env python3
import os, subprocess, sys
DASHBOARD_BIN = "/opt/kodachi/dashboard/hooks/kodachi-dashboard"
LOG_FILE = "/tmp/kodachi-dashboard.log"

def main(argv=None):
    if not os.path.isfile(DASHBOARD_BIN):
        print("[ERROR] Dashboard binary not found at", DASHBOARD_BIN)
        print("        Run the Arch setup script first.")
        return 1
    if not os.path.islink("/usr/local/bin/kodachi-dashboard"):
        print("[INFO] Creating symlinks...")
        subprocess.run(["sudo","ln","-sf",DASHBOARD_BIN,"/usr/local/bin/kodachi-dashboard"], check=False)
    missing = [c for c in ("jq","curl","wget","tor") if subprocess.run(["which",c],capture_output=True).returncode != 0]
    if missing:
        print("[WARN] Missing dependencies:", " ".join(missing))
        print("       Install with: sudo pacman -S", " ".join(missing))
    print("[INFO] Launching Kodachi Dashboard...")
    print("[INFO] Log:", LOG_FILE)
    with open(LOG_FILE,"w") as log:
        proc = subprocess.Popen([DASHBOARD_BIN,"--no-gpu",*(argv or [])], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            sys.stdout.write(line); log.write(line)
        return proc.wait()

if __name__ == "__main__":
    sys.exit(main())
