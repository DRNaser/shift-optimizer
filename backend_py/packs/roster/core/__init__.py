"""
SOLVEREIGN Roster Pack - Core Module
=====================================

Shared components used across the roster pack.
"""

from .violations import (
    ViolationSeverity,
    ViolationType,
    Violation,
    ViolationCounts,
    VIOLATION_RULES,
    get_severity,
    compute_violations_async,
    compute_violations_sync,
    compute_violation_delta,
)

from .assignment_key import (
    AssignmentKeyComponents,
    compute_assignment_key,
    compute_assignment_key_from_row,
    compute_pin_lookup_key,
)

__all__ = [
    # Violations
    "ViolationSeverity",
    "ViolationType",
    "Violation",
    "ViolationCounts",
    "VIOLATION_RULES",
    "get_severity",
    "compute_violations_async",
    "compute_violations_sync",
    "compute_violation_delta",
    # Assignment Keys
    "AssignmentKeyComponents",
    "compute_assignment_key",
    "compute_assignment_key_from_row",
    "compute_pin_lookup_key",
]
