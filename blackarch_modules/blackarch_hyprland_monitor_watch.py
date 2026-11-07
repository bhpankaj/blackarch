#!/usr/bin/env python3
import os, sys
sys.path.insert(0, "/opt/blackarch")
import blackarch_modules.blackarch_hyprland as h
def main(argv=None):
    return h.main(["monitor-watch", *(argv or [])])
if __name__ == "__main__":
    sys.exit(main())
