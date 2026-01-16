#!/usr/bin/env python3
"""
SOLVEREIGN Diagnostic Run Script
=================================

Thin wrapper for regression tests. Delegates to packs.roster.tools.

This script runs the solver and outputs detailed results to JSON for
validation by test suites (test_regression_best_balanced.py).

Usage:
    python scripts/diagnostic_run.py --time_budget 60 --output_profile BEST_BALANCED

Output:
    diag_run_result.json - Detailed solver results

NOTE: This script delegates to packs.roster.tools (not packs.roster.engine directly).
"""

import sys
from pathlib import Path

# Ensure backend_py is in path for imports
SCRIPT_DIR = Path(__file__).parent.absolute()
BACKEND_DIR = SCRIPT_DIR.parent / "backend_py"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from packs.roster.tools.diagnostic_run import main

if __name__ == "__main__":
    sys.exit(main())
