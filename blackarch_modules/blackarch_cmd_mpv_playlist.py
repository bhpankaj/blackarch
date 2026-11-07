#!/usr/bin/env python3
import os, sys
sys.path.insert(0, "/opt/blackarch")
import blackarch_modules.blackarch_cmd_mpv as m
def main(argv=None):
    name = "blackarch-cmd-mpv-playlist"
    return m.main([name, *(argv or [])])
if __name__ == "__main__":
    sys.exit(main())
