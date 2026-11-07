#!/usr/bin/env python3
"""blackarch:summary=Post-install setup verification and auto-fix"""

import sys

sys.path.insert(0, "/opt/blackarch")


def main(argv=None):
    from blackarch_modules.blackarch_execute_core import setup_post_config

    setup_post_config()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
