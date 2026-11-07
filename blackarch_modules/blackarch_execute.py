#!/usr/bin/env python3
# blackarch:summary=Run the commander (modular extraction of blackarch execute)
"""blackarch installer-commander — imports all functions from blackarch_execute_core module."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blackarch_execute_core import *  # noqa: F401,F403

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
