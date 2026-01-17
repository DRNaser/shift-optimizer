"""
SOLVEREIGN V4.9.2 - Constraint Checkers
=======================================

Week-aware constraint checkers for candidate evaluation.

Split from week_lookahead.py for maintainability.

WEEKLY HOURS POLICY (V4.9.2):
- HARD_CAP mode: Candidates exceeding weekly hours cap are INFEASIBLE (hard fail)
- SOFT_RISK mode: Overtime affects ranking/score but never blocks (UI shows risk label)
- Default: HARD_CAP with 55h limit (matches Austrian labor law for transport)
"""

import os
from datetime import date, datetime, timedelta
from typing import List, Tuple, Optional, Literal

from .window import DayAssignment


# =============================================================================
# WEEKLY HOURS POLICY CONFIGURATION
# =============================================================================

# Policy: HARD_CAP = exceeds cap is infeasible, SOFT_RISK = risk metric only
WeeklyHoursPolicy = Literal["HARD_CAP", "SOFT_RISK"]

# Default policy for pilot - use HARD_CAP (safer, enforces labor law compliance)
_policy_env = os.environ.get("ROSTER_WEEKLY_HOURS_POLICY", "HARD_CAP").upper()
WEEKLY_HOURS_POLICY: WeeklyHoursPolicy = "HARD_CAP" if _policy_env == "HARD_CAP" else "SOFT_RISK"

# Default cap (Austrian transport sector: 55h)
DEFAULT_WEEKLY_HOURS_CAP = float(os.environ.get("ROSTER_WEEKLY_HOURS_CAP", "55.0"))


# =============================================================================
# CONSTRAINT CHECKERS (WEEK-AWARE)
# =============================================================================

def check_overlap_week(
    candidate_assignment_start: datetime,
    candidate_assignment_end: datetime,
    driver_week_assignments: List[DayAssignment],
    buffer_minutes: int = 0,
) -> List[Tuple[DayAssignment, str]]:
    """
    Check for overlaps across the entire week.

    Returns list of (conflicting_assignment, reason) tuples.
    """
    conflicts = []
    buffer = timedelta(minutes=buffer_minutes)

    for asgn in driver_week_assignments:
        if not asgn.start_ts or not asgn.end_ts:
            continue

        # Check overlap: not (candidate_end <= asgn_start or candidate_start >= asgn_end)
        if not (candidate_assignment_end + buffer <= asgn.start_ts or
                candidate_assignment_start - buffer >= asgn.end_ts):
            conflicts.append((asgn, f"Overlaps with tour {asgn.tour_instance_id}"))

    return conflicts


def check_rest_week(
    candidate_assignment_start: datetime,
    candidate_assignment_end: datetime,
    driver_week_assignments: List[DayAssignment],
    min_rest_hours: int = 11,
) -> List[Tuple[DayAssignment, str, bool]]:
    """
    Check 11-hour rest rule across the week.

    Returns list of (conflicting_assignment, reason, is_first_slot_next_day) tuples.
    The is_first_slot_next_day flag indicates if rest violation only affects the
    first slot of the next day (single displacement churn).
    """
    conflicts = []
    min_rest = timedelta(hours=min_rest_hours)

    for asgn in driver_week_assignments:
        if not asgn.start_ts or not asgn.end_ts:
            continue

        # Check rest before candidate assignment
        rest_before = candidate_assignment_start - asgn.end_ts
        if timedelta() < rest_before < min_rest:
            hours = rest_before.total_seconds() / 3600
            # This is a past assignment affecting our new slot - not churn
            conflicts.append(
                (asgn, f"Only {hours:.1f}h rest after {asgn.day_date}", False)
            )

        # Check rest after candidate assignment (this is the lookahead churn case)
        rest_after = asgn.start_ts - candidate_assignment_end
        if timedelta() < rest_after < min_rest:
            hours = rest_after.total_seconds() / 3600
            # Check if this is the first slot of the next day
            # (simple heuristic: if assignment is in the morning and on next day)
            is_next_day = (asgn.day_date - candidate_assignment_end.date()).days == 1
            is_morning = asgn.start_ts.hour < 12 if asgn.start_ts else False
            is_first_slot_likely = is_next_day and is_morning

            conflicts.append(
                (asgn, f"Only {hours:.1f}h rest before {asgn.day_date}", is_first_slot_likely)
            )

    return conflicts


def check_max_tours_day(
    target_day: date,
    driver_week_assignments: List[DayAssignment],
    max_tours: int = 3,
) -> Tuple[bool, Optional[str]]:
    """
    Check if driver already has max tours on target day.

    Returns (exceeds_max, reason).
    """
    from datetime import date as date_type

    same_day_count = sum(1 for a in driver_week_assignments if a.day_date == target_day)

    if same_day_count >= max_tours:
        return (True, f"Already has {same_day_count} tours on {target_day}")

    return (False, None)


def check_weekly_hours(
    current_hours: float,
    added_hours: float,
    max_weekly_hours: float = DEFAULT_WEEKLY_HOURS_CAP,
    policy: Optional[WeeklyHoursPolicy] = None,
) -> Tuple[bool, float, str, bool]:
    """
    Check if adding hours would exceed weekly limit.

    Returns (exceeds_limit, overtime_amount, risk_level, is_hard_fail).

    IMPORTANT: Weekly hours cap is NOT churn.

    Policy behavior (V4.9.2):
    - HARD_CAP: exceeds_limit=True AND is_hard_fail=True → candidate is INFEASIBLE
    - SOFT_RISK: exceeds_limit=True but is_hard_fail=False → risk metric only

    The is_hard_fail flag determines if the caller should treat this as a blocker.
    """
    effective_policy = policy or WEEKLY_HOURS_POLICY
    total = current_hours + added_hours

    if total > max_weekly_hours:
        overtime = total - max_weekly_hours

        # Categorize risk level
        if overtime > 10:
            risk_level = "HIGH"
        elif overtime > 5:
            risk_level = "MED"
        else:
            risk_level = "LOW"

        # Determine if this is a hard fail based on policy
        is_hard_fail = (effective_policy == "HARD_CAP")

        return (True, overtime, risk_level, is_hard_fail)

    return (False, 0.0, "NONE", False)
