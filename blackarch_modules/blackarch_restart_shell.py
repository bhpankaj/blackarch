#!/usr/bin/env python3
import os, signal, subprocess, sys, time
sys.path.insert(0, "/opt/blackarch")
import blackarch_modules.blackarch_launch_shell as ls

def main(argv=None):
    subprocess.run(["pkill", "-f", "quickshell"], check=False)
    time.sleep(1)
    return ls.main()

if __name__ == "__main__":
    sys.exit(main())
