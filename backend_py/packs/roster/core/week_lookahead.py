"""
SOLVEREIGN V4.9.2 - Week Lookahead Candidate Finder (Thin Wrapper)
==================================================================

This file is a BACKWARDS COMPATIBILITY wrapper.
All logic has been moved to the week_lookahead/ package.

Migration path:
- Old: from packs.roster.core.week_lookahead import X
- New: from packs.roster.core.week_lookahead import X (same!)

The package __init__.py re-exports all public APIs.
"""

# Re-export everything from the package for backwards compatibility
from packs.roster.core.week_lookahead import (
    # Window types
    AffectedSlot,
    WeekWindow,
    DayAssignment,
    SlotContext,
    get_week_window,
    day_index_from_date,
    get_lookahead_range,
    # Constraints
    check_overlap_week,
    check_rest_week,
    check_max_tours_day,
    check_weekly_hours,
    # Scoring
    CandidateImpact,
    sort_affected_slots,
    make_ranking_key,
    rank_candidates,
    compute_score,
    # Evaluator
    ChurnResult,
    compute_minimal_churn,
    evaluate_candidate_with_lookahead,
    # Batch
    SlotResult,
    DebugMetrics,
    CandidateBatchResult,
    find_candidates_batch,
)

__all__ = [
    # Window types
    "AffectedSlot",
    "WeekWindow",
    "DayAssignment",
    "SlotContext",
    "get_week_window",
    "day_index_from_date",
    "get_lookahead_range",
    # Constraints
    "check_overlap_week",
    "check_rest_week",
    "check_max_tours_day",
    "check_weekly_hours",
    # Scoring
    "CandidateImpact",
    "sort_affected_slots",
    "make_ranking_key",
    "rank_candidates",
    "compute_score",
    # Evaluator
    "ChurnResult",
    "compute_minimal_churn",
    "evaluate_candidate_with_lookahead",
    # Batch
    "SlotResult",
    "DebugMetrics",
    "CandidateBatchResult",
    "find_candidates_batch",
]
