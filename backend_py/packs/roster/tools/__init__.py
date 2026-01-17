"""
SOLVEREIGN Roster Pack - CLI Tools
==================================

Public CLI tools for roster operations:
- export_matrix: Export roster matrix to CSV
- diagnostic_run: Run solver diagnostics for regression tests
- solve: Run the deterministic solver

These are the canonical entry points for CI and scripts.
"""

from .export_matrix import export_matrix, main as export_main
from .diagnostic_run import diagnostic_run, main as diagnostic_main
from .solve import solve_roster, main as solve_main

__all__ = [
    "export_matrix",
    "export_main",
    "diagnostic_run",
    "diagnostic_main",
    "solve_roster",
    "solve_main",
]
