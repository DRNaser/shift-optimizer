"""
SOLVEREIGN V4.9.2 - Week Lookahead Candidate Finder
===================================================

Enhanced candidate finder with whole-week lookahead for minimal repair churn.

Key Features:
1. Default lookahead = today → Sunday (not full week)
2. Churn calculation (count of affected future slots, NOT violations)
3. Frozen/pinned day hard-blocking
4. Transparent explanations per candidate
5. Deterministic ranking with driver_id tiebreaker

CRITICAL DESIGN DECISIONS:
- Churn = 0 is always preferred over any other score (lexicographic)
- Frozen days are NEVER modified (hard block)
- Pinned days require explicit allow_multiday_repair=True
- Overtime is a RISK metric, NOT churn
- All operations are read-only until user confirms

Module Structure:
- window.py: Week boundaries, data structures
- constraints.py: Constraint checkers (overlap, rest, hours)
- scoring.py: Ranking and scoring logic
- evaluator.py: Single candidate evaluation
- batch.py: Batch candidate finding entry point

Backwards Compatibility:
All public APIs from the original week_lookahead.py are re-exported here.
"""

# Window types and helpers
from .window import (
    AffectedSlot,
    WeekWindow,
    DayAssignment,
    SlotContext,
    get_week_window,
    day_index_from_date,
    get_lookahead_range,
)

# Constraint checkers
from .constraints import (
    check_overlap_week,
    check_rest_week,
    check_max_tours_day,
    check_weekly_hours,
    WEEKLY_HOURS_POLICY,
    DEFAULT_WEEKLY_HOURS_CAP,
)

# Scoring and ranking
from .scoring import (
    CandidateImpact,
    sort_affected_slots,
    make_ranking_key,
    rank_candidates,
    compute_score,
)

# Evaluator
from .evaluator import (
    ChurnResult,
    compute_minimal_churn,
    evaluate_candidate_with_lookahead,
)

# Batch finder
from .batch import (
    SlotResult,
    DebugMetrics,
    CandidateBatchResult,
    find_candidates_batch,
    DEBUG_METRICS_ENABLED,
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
    "WEEKLY_HOURS_POLICY",
    "DEFAULT_WEEKLY_HOURS_CAP",
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
    "DEBUG_METRICS_ENABLED",
]
