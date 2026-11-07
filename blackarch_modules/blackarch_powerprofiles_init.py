#!/usr/bin/env python3
import os, subprocess, sys
sys.path.insert(0, "/opt/blackarch")
import blackarch_modules.blackarch_powerprofiles_set as pps

def main(argv=None):
    sys.argv = ["blackarch-powerprofiles-set", "autodetect"]
    return pps.main()

if __name__ == "__main__":
    sys.exit(main())
