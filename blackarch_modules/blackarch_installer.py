#!/usr/bin/env python3
# blackarch:summary=Run the installer (modular extraction of blackarch installer)
"""blackarch installer — imports all functions from blackarch_installer_core module."""

import os
import sys

# Ensure module importable when invoked by absolute path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blackarch_installer_core import *  # noqa: F401,F403
from blackarch_installer_core import _entry

if __name__ == "__main__":
    _entry()
