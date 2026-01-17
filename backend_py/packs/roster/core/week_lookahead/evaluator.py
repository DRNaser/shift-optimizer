"""
SOLVEREIGN V4.9.2 - Candidate Evaluator
======================================

Week-aware candidate evaluation with minimal churn calculation.

Split from week_lookahead.py for maintainability.

CRITICAL DESIGN DECISIONS:
1. Lookahead starts from TODAY (day_date), not week_start
2. Churn = count of downstream assignment changes, NOT violations
3. Overtime is a RISK metric, not churn
4. Frozen days are NEVER touched (hard block)
5. Pinned days require explicit allow_multiday_repair=True
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple

from .window import (
    WeekWindow,
    DayAssignment,
    SlotContext,
    AffectedSlot,
    day_index_from_date,
    get_lookahead_range,
)
from .constraints import (
    check_overlap_week,
    check_rest_week,
    check_max_tours_day,
    check_weekly_hours,
)
from .scoring import CandidateImpact, compute_score


# =============================================================================
# MINIMAL CHURN COMPUTATION
# =============================================================================

@dataclass
class ChurnResult:
    """Result of minimal churn computation."""
    churn_count: int = 0
    churn_locked_count: int = 0
    affected_slots: List[AffectedSlot] = field(default_factory=list)
    overtime_risk: float = 0.0
    overtime_risk_level: str = "NONE"


def compute_minimal_churn(
    slot: SlotContext,
    driver_week_assignments: List[DayAssignment],
    frozen_days: Set[date],
    pinned_days: Set[date],
    allow_multiday_repair: bool,
    min_rest_hours: int = 11,
) -> ChurnResult:
    """
    Compute MINIMAL repair churn for a candidate assignment.

    Churn = estimated number of downstream assignment changes required.

    CRITICAL: This is NOT the same as violation count!
    - REST violation that only blocks first slot next day = +1 churn
    - OVERLAP with one slot = +1 churn
    - Weekly hours cap = NOT CHURN (it's overtime risk)

    Args:
        slot: The slot being assigned
        driver_week_assignments: All current assignments for the driver
        frozen_days: Days that cannot be modified (hard block)
        pinned_days: Days with pinned assignments
        allow_multiday_repair: If False, pinned days also hard block
        min_rest_hours: Minimum rest hours (default 11)

    Returns:
        ChurnResult with churn counts and affected slots
    """
    result = ChurnResult()

    if not slot.start_ts or not slot.end_ts:
        return result

    # Only check FUTURE assignments (lookahead, not past)
    lookahead_start = slot.day_date
    future_assignments = [
        a for a in driver_week_assignments
        if a.day_date > lookahead_start and a.start_ts and a.end_ts
    ]

    # Check rest violations with future assignments
    for future_asgn in future_assignments:
        rest_after = future_asgn.start_ts - slot.end_ts
        if timedelta() < rest_after < timedelta(hours=min_rest_hours):
            hours = rest_after.total_seconds() / 3600

            # Is this assignment on a locked day?
            is_frozen = future_asgn.day_date in frozen_days
            is_pinned = future_asgn.is_pinned or future_asgn.day_date in pinned_days
            is_locked = is_frozen or (is_pinned and not allow_multiday_repair)

            # Determine reason code
            if is_frozen:
                reason = "FROZEN"
            elif is_pinned:
                reason = "PINNED"
            else:
                # Check if it's likely the first slot of the day
                is_next_day = (future_asgn.day_date - slot.day_date).days == 1
                is_morning = future_asgn.start_ts.hour < 12
                if is_next_day and is_morning:
                    reason = "REST_NEXTDAY_FIRST_SLOT"
                else:
                    reason = "REST_VIOLATION"

            affected = AffectedSlot(
                date=future_asgn.day_date,
                slot_id=future_asgn.slot_id or str(future_asgn.tour_instance_id),
                tour_instance_id=future_asgn.tour_instance_id,
                reason=reason,
                current_driver_id=None,  # It's the same driver being displaced
                severity="HARD" if is_locked else "WARN",
            )
            result.affected_slots.append(affected)

            if is_locked:
                result.churn_locked_count += 1
            else:
                # Each rest violation = 1 slot displacement
                result.churn_count += 1

    # Check overlap violations with future assignments
    for future_asgn in future_assignments:
        # Direct overlap check (should be rare for future days but possible
        # with multi-day tours or late-night shifts)
        if not (slot.end_ts <= future_asgn.start_ts or slot.start_ts >= future_asgn.end_ts):
            is_frozen = future_asgn.day_date in frozen_days
            is_pinned = future_asgn.is_pinned or future_asgn.day_date in pinned_days
            is_locked = is_frozen or (is_pinned and not allow_multiday_repair)

            reason = "FROZEN" if is_frozen else ("PINNED" if is_pinned else "OVERLAP")

            affected = AffectedSlot(
                date=future_asgn.day_date,
                slot_id=future_asgn.slot_id or str(future_asgn.tour_instance_id),
                tour_instance_id=future_asgn.tour_instance_id,
                reason=reason,
                current_driver_id=None,
                severity="HARD" if is_locked else "WARN",
            )

            # Avoid duplicates (if already added from rest check)
            existing_ids = {(s.date, s.slot_id) for s in result.affected_slots}
            if (affected.date, affected.slot_id) not in existing_ids:
                result.affected_slots.append(affected)
                if is_locked:
                    result.churn_locked_count += 1
                else:
                    result.churn_count += 1

    return result


# =============================================================================
# CANDIDATE EVALUATOR
# =============================================================================

async def evaluate_candidate_with_lookahead(
    conn,
    tenant_id: int,
    site_id: int,
    driver_id: int,
    driver_name: str,
    slot: SlotContext,
    week_window: WeekWindow,
    driver_week_assignments: List[DayAssignment],
    driver_current_hours: float,
    frozen_days: Set[date],
    pinned_days: Set[date],
    allow_multiday_repair: bool = False,
    config: Optional[dict] = None,
) -> CandidateImpact:
    """
    Evaluate a single candidate with whole-week lookahead.

    This is the core algorithm for minimal-churn candidate selection.

    Steps:
    1. Check today feasibility (hard constraints)
    2. Compute minimal churn for downstream impacts
    3. Compute risk metrics (overtime, NOT churn)
    4. Compute score (used only when churn tied)
    5. Build explanations

    CRITICAL CHANGES FROM V4.9.1:
    - Lookahead starts from today, not week_start
    - Churn is computed via compute_minimal_churn(), not violation count
    - Overtime is a risk metric, NOT counted as churn

    Args:
        conn: Database connection (unused in evaluation, kept for API compat)
        tenant_id: Tenant ID
        site_id: Site ID
        driver_id: Candidate driver ID
        driver_name: Driver display name
        slot: The slot to fill
        week_window: The week boundary
        driver_week_assignments: All assignments for this driver in the week
        driver_current_hours: Driver's current weekly hours
        frozen_days: Set of frozen dates
        pinned_days: Set of pinned dates
        allow_multiday_repair: If True, allow candidates that cause future repairs
        config: Configuration overrides

    Returns:
        CandidateImpact with full evaluation
    """
    cfg = config or {}
    min_rest_hours = cfg.get("min_rest_hours", 11)
    max_tours_per_day = cfg.get("max_tours_per_day", 3)
    max_weekly_hours = cfg.get("max_weekly_hours", 55.0)

    impact = CandidateImpact(
        driver_id=driver_id,
        driver_name=driver_name,
        hours_week_current=driver_current_hours,
    )

    # Calculate assignment duration
    duration_minutes = slot.duration_minutes
    if slot.start_ts and slot.end_ts:
        duration_minutes = int((slot.end_ts - slot.start_ts).total_seconds() / 60)
    duration_hours = duration_minutes / 60

    impact.added_minutes = duration_minutes
    impact.hours_week_after = driver_current_hours + duration_hours

    # Count current tours today
    today_tours = [a for a in driver_week_assignments if a.day_date == slot.day_date]
    impact.tours_today_current = len(today_tours)
    impact.tours_today_after = len(today_tours) + 1

    # =========================================================================
    # STEP 1: Check TODAY feasibility (hard constraints)
    # =========================================================================

    blockers = []
    reasons = []

    # Check if target day is frozen
    if slot.day_date in frozen_days:
        impact.feasible_today = False
        impact.blockers.append("Target day is frozen")
        return impact

    # Check overlap on target day
    if slot.start_ts and slot.end_ts:
        overlaps = check_overlap_week(slot.start_ts, slot.end_ts, today_tours)
        if overlaps:
            impact.feasible_today = False
            for _, reason in overlaps:
                blockers.append(f"Today: {reason}")

    # Check rest rule with PAST/SAME-DAY assignments only (not future - that's churn)
    if slot.start_ts and slot.end_ts:
        # Only check assignments from day before or same day for TODAY feasibility
        adjacent_past = [
            a for a in driver_week_assignments
            if a.day_date <= slot.day_date and abs((a.day_date - slot.day_date).days) <= 1
        ]
        rest_conflicts = check_rest_week(
            slot.start_ts, slot.end_ts, adjacent_past, min_rest_hours
        )
        # Only past/same-day conflicts block TODAY feasibility
        for asgn, reason, _ in rest_conflicts:
            if asgn.day_date <= slot.day_date:
                impact.feasible_today = False
                blockers.append(f"Rest: {reason}")

    # Check max tours on target day
    exceeds_max, max_reason = check_max_tours_day(
        slot.day_date, driver_week_assignments, max_tours_per_day
    )
    if exceeds_max:
        impact.feasible_today = False
        blockers.append(max_reason)

    # Check weekly hours - HARD_CAP policy means infeasible, SOFT_RISK means risk metric only
    exceeds_hours, overtime, risk_level, is_hard_fail = check_weekly_hours(
        driver_current_hours, duration_hours, max_weekly_hours
    )
    if exceeds_hours:
        # Store risk metrics regardless of policy
        impact.overtime_risk = overtime
        impact.overtime_risk_level = risk_level
        impact.risk_tier_today = {"NONE": 0, "LOW": 1, "MED": 2, "HIGH": 3}.get(risk_level, 0)

        if is_hard_fail:
            # HARD_CAP policy: exceeding weekly hours is a hard block
            impact.feasible_today = False
            blockers.append(f"Would exceed {max_weekly_hours}h cap ({impact.hours_week_after:.1f}h total)")
        else:
            # SOFT_RISK policy: just add to reasons, not a blocker
            reasons.append(f"Would have {impact.hours_week_after:.1f}h (overtime: {overtime:.1f}h)")

    impact.blockers = blockers

    if not impact.feasible_today:
        impact.reasons = blockers
        return impact

    # =========================================================================
    # STEP 2: Compute MINIMAL CHURN (lookahead from today to week_end)
    # =========================================================================

    churn_result = compute_minimal_churn(
        slot=slot,
        driver_week_assignments=driver_week_assignments,
        frozen_days=frozen_days,
        pinned_days=pinned_days,
        allow_multiday_repair=allow_multiday_repair,
        min_rest_hours=min_rest_hours,
    )

    impact.affected_slots = churn_result.affected_slots
    impact.churn_count = churn_result.churn_count
    impact.churn_locked_count = churn_result.churn_locked_count

    # Lookahead is NOT OK if there are locked conflicts
    impact.lookahead_ok = (churn_result.churn_locked_count == 0)

    # If multiday repair not allowed, any churn is a blocker
    if not allow_multiday_repair and churn_result.churn_count > 0:
        impact.lookahead_ok = False
        blockers.append(f"Would require {churn_result.churn_count} future repair(s)")

    # =========================================================================
    # STEP 3: Compute score (used only when churn is equal)
    # =========================================================================

    impact.score = compute_score(impact, max_weekly_hours)

    # =========================================================================
    # STEP 4: Build explanations
    # =========================================================================

    if not blockers:
        parts = []
        if impact.churn_count == 0 and impact.churn_locked_count == 0:
            parts.append("No downstream impact")
        if impact.churn_count > 0:
            parts.append(f"{impact.churn_count} future slot(s) would need repair")
            impact.week_violations = [
                f"Would require repair on {a.date}" for a in impact.affected_slots
            ]
        if impact.tours_today_current > 0:
            parts.append("already working today")
        if impact.overtime_risk > 0:
            parts.append(f"overtime risk: {impact.overtime_risk_level}")
        impact.explanation = ", ".join(parts) if parts else f"Score: {impact.score:.1f}"
    else:
        impact.today_violations = blockers.copy()
        impact.reasons = blockers

    return impact
