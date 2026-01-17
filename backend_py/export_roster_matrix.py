#!/usr/bin/env python3
"""
SOLVEREIGN CI Entry Point: export_roster_matrix.py
===================================================

Thin wrapper delegating to packs.roster.tools.export_matrix.

This script is the canonical CI entry point for running the solver
and exporting results. It reads "forecast input.csv" and produces
"roster_matrix.csv" in the current directory.

Usage (CI):
    python backend_py/export_roster_matrix.py --time-budget 60 --seed 42

Usage (Local):
    cd backend_py
    python export_roster_matrix.py --time-budget 60 --seed 42

NOTE: This script delegates to packs.roster.tools (not packs.roster.engine directly).
"""

import sys
from pathlib import Path

# Ensure backend_py is in path for imports
SCRIPT_DIR = Path(__file__).parent.absolute()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from packs.roster.tools.export_matrix import main

if __name__ == "__main__":
    sys.exit(main())
