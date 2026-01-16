"""
SOLVEREIGN V4.9.2 - Candidate Scoring & Ranking
===============================================

Lexicographic ranking and scoring for candidates.

Split from week_lookahead.py for maintainability.

CRITICAL DESIGN:
- Ranking is LEXICOGRAPHIC (churn=0 ALWAYS beats churn>0)
- Final tiebreaker is driver_id for determinism
- affected_slots sorted by (date, slot_id) for stable output
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

from .window import AffectedSlot


# =============================================================================
# CANDIDATE IMPACT RESULT
# =============================================================================

@dataclass
class CandidateImpact:
    """Impact assessment for a candidate assignment."""
    driver_id: int
    driver_name: str

    # Feasibility
    feasible_today: bool = True
    lookahead_ok: bool = True  # No week-level violations

    # Churn metrics (lexicographic priority)
    churn_count: int = 0  # Number of future slots that would need repair
    churn_locked_count: int = 0  # Churn on frozen/pinned days (must be 0)
    affected_slots: List[AffectedSlot] = field(default_factory=list)

    # Risk metrics (NOT churn - for UI display only)
    overtime_risk: float = 0.0  # Hours over limit
    overtime_risk_level: str = "NONE"  # NONE/LOW/MED/HIGH

    # Score components (used only when churn is equal)
    score: float = 0.0
    risk_tier_today: int = 0  # 0=none, 1=low, 2=medium, 3=high
    wait_time_minutes: int = 0
    fairness_penalty: float = 0.0

    # Explanation (for API/UI)
    explanation: str = ""  # Human-readable summary
    blocker_summary: Optional[str] = None  # If not feasible, summary of blockers
    today_violations: List[str] = field(default_factory=list)
    week_violations: List[str] = field(default_factory=list)

    # Legacy/internal fields
    reasons: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    # Driver context
    hours_week_current: float = 0.0
    hours_week_after: float = 0.0
    tours_today_current: int = 0
    tours_today_after: int = 0
    added_minutes: int = 0


def sort_affected_slots(slots: List[AffectedSlot]) -> List[AffectedSlot]:
    """
    Sort affected slots by (date, slot_id) for deterministic output.

    This ensures the same slots always appear in the same order
    regardless of evaluation order.
    """
    return sorted(slots, key=lambda s: (s.date, s.slot_id))


def make_ranking_key(c: CandidateImpact) -> Tuple:
    """
    Create lexicographic ranking key for a candidate.

    Order (most important first):
    1. feasible_today desc (True=0 sorts before False=1)
    2. lookahead_ok desc (True=0 sorts before False=1)
    3. churn_locked_count asc (0 first)
    4. churn_count asc (0 first)
    5. risk_tier_today asc (lower risk first: NONE=0 < LOW=1 < MED=2 < HIGH=3)
    6. score asc (lower is better)
    7. driver_id asc (DETERMINISTIC TIEBREAKER)

    CRITICAL: driver_id as final tiebreaker ensures stable ordering
    when all other criteria are equal.

    V4.9.2: Added risk_tier_today AFTER churn_count but BEFORE score.
    This ensures overtime risk affects ranking when churn is equal.
    """
    return (
        not c.feasible_today,    # Feasible first (False < True as bools)
        not c.lookahead_ok,      # Lookahead OK first
        c.churn_locked_count,    # Zero locked churn first
        c.churn_count,           # Minimal churn first
        c.risk_tier_today,       # Lower overtime risk first (V4.9.2)
        c.score,                 # Best score first
        c.driver_id,             # DETERMINISTIC TIEBREAKER
    )


def rank_candidates(candidates: List[CandidateImpact]) -> List[CandidateImpact]:
    """
    Rank candidates using lexicographic ordering.

    Returns a NEW list sorted by ranking key.
    Also normalizes affected_slots ordering.
    """
    # Normalize affected_slots ordering for each candidate
    for c in candidates:
        c.affected_slots = sort_affected_slots(c.affected_slots)

    # Sort using full ranking key (includes driver_id tiebreaker)
    return sorted(candidates, key=make_ranking_key)


def compute_score(
    impact: CandidateImpact,
    max_weekly_hours: float = 55.0,
    target_hours: float = 40.0,
) -> float:
    """
    Compute score for a candidate (used only when churn is equal).

    Lower score = better candidate.

    Components:
    - Already working today: -20 (bonus for continuity)
    - Not working today: +10 (penalty for new callout)
    - Capacity remaining: -0.5 per hour (prefer drivers with more room)
    - Churn penalty: +50 per affected slot
    - Fairness: +2 per hour over target (prefer under-utilized)
    """
    score = 0.0

    # Prefer drivers already working today (continuity)
    if impact.tours_today_current > 0:
        score -= 20.0
    else:
        score += 10.0

    # Prefer drivers with more capacity
    capacity_remaining = max(0, max_weekly_hours - impact.hours_week_current)
    score -= capacity_remaining * 0.5

    # Penalty for churn (but churn=0 already wins via lexicographic)
    score += impact.churn_count * 50.0

    # Fairness: prefer under-utilized drivers
    if impact.hours_week_current < target_hours:
        gap = target_hours - impact.hours_week_current
        impact.fairness_penalty = -gap  # Negative = good
    else:
        gap = impact.hours_week_current - target_hours
        impact.fairness_penalty = gap
        score += gap * 2.0

    return score
