"""
SOLVEREIGN V4.9.2 - Batch Candidate Finder
==========================================

Main entry point for batch candidate finding with week lookahead.

Split from week_lookahead.py for maintainability.

Performance guarantees:
- Single query for all week assignments per driver (NO N+1)
- Single query for frozen days
- Single query for all open slots
- Optional debug metrics for instrumentation (gated by env flag)

DEBUG METRICS SECURITY (V4.9.2):
- Debug metrics are GATED by ROSTER_CANDIDATES_DEBUG_METRICS env flag
- Default: OFF in production
- Metrics contain ONLY counts + elapsed_ms (no tenant IDs, no raw SQL, no PII)
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict, Optional, Set

from .window import (
    WeekWindow,
    DayAssignment,
    SlotContext,
    AffectedSlot,
    get_week_window,
    day_index_from_date,
)
from .scoring import CandidateImpact, rank_candidates
from .evaluator import evaluate_candidate_with_lookahead

logger = logging.getLogger(__name__)


# =============================================================================
# DEBUG METRICS CONFIGURATION
# =============================================================================

# Gate debug metrics by env flag - OFF by default in production
DEBUG_METRICS_ENABLED = os.environ.get("ROSTER_CANDIDATES_DEBUG_METRICS", "0") == "1"


# =============================================================================
# BATCH RESULT TYPES
# =============================================================================

@dataclass
class SlotResult:
    """Candidates result for a single slot."""
    slot_id: str
    tour_instance_id: int
    date: date
    time_window: str  # "HH:MM-HH:MM"
    current_driver_id: Optional[int] = None
    is_pinned: bool = False
    candidates: List[CandidateImpact] = field(default_factory=list)
    blocker_summary: Dict[str, int] = field(default_factory=dict)


@dataclass
class DebugMetrics:
    """Optional debug metrics for performance monitoring."""
    db_query_count: int = 0
    drivers_considered: int = 0
    slots_evaluated: int = 0
    elapsed_ms: float = 0.0
    lookahead_start: Optional[str] = None
    lookahead_end: Optional[str] = None


@dataclass
class CandidateBatchResult:
    """Result of batch candidate finding."""
    site_id: int
    week_start: date
    week_end: date
    generated_at: str
    is_frozen: bool = False
    frozen_days: List[date] = field(default_factory=list)
    slots: List[SlotResult] = field(default_factory=list)
    # Legacy - keep for backwards compatibility
    candidates_by_slot: Dict[str, List[CandidateImpact]] = field(default_factory=dict)
    blocker_summary_by_slot: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_open_slots: int = 0
    slots_with_candidates: int = 0
    # Debug metrics (optional)
    debug_metrics: Optional[DebugMetrics] = None


# =============================================================================
# BATCH CANDIDATE FINDER
# =============================================================================

async def find_candidates_batch(
    conn,
    tenant_id: int,
    site_id: int,
    target_date: date,
    plan_version_id: Optional[int] = None,
    allow_multiday_repair: bool = False,
    config: Optional[dict] = None,
    include_debug_metrics: bool = False,
) -> CandidateBatchResult:
    """
    Find candidates for all open/at-risk slots on a given date.

    This is the main entry point for the batch candidates API.

    Performance optimizations:
    - Single query for all week assignments per driver
    - Single query for frozen days
    - Single query for all open slots
    - No N+1 queries

    Args:
        conn: Async database connection
        tenant_id: Tenant ID
        site_id: Site ID
        target_date: Date to find candidates for
        plan_version_id: Optional plan version (uses active if not specified)
        allow_multiday_repair: If True, show churn>0 candidates
        config: Configuration overrides
        include_debug_metrics: If True, include performance metrics in result

    Returns:
        CandidateBatchResult with candidates per slot
    """
    start_time = time.time()
    cfg = config or {}
    max_candidates_per_slot = cfg.get("max_candidates_per_slot", 10)

    # Initialize debug metrics if requested AND env flag is enabled
    # V4.9.2: Debug metrics gated by ROSTER_CANDIDATES_DEBUG_METRICS env flag
    effective_include_debug = include_debug_metrics and DEBUG_METRICS_ENABLED
    debug = DebugMetrics() if effective_include_debug else None
    db_query_count = 0

    # Get week window
    week = get_week_window(target_date)

    result = CandidateBatchResult(
        site_id=site_id,
        week_start=week.week_start,
        week_end=week.week_end,
        generated_at=datetime.now(timezone.utc).isoformat() + "Z",
    )

    # =========================================================================
    # Query 1: Check if target day is frozen
    # =========================================================================

    day_row = await conn.fetchrow(
        """
        SELECT status FROM dispatch.workbench_days
        WHERE tenant_id = $1 AND site_id = $2 AND day_date = $3
        """,
        tenant_id, site_id, target_date
    )
    db_query_count += 1

    if day_row and day_row["status"] == "FROZEN":
        result.is_frozen = True
        if debug:
            debug.db_query_count = db_query_count
            debug.elapsed_ms = (time.time() - start_time) * 1000
            result.debug_metrics = debug
        # Return empty candidates - day is frozen
        return result

    # =========================================================================
    # Query 2: Get active plan version if not specified
    # =========================================================================

    if not plan_version_id:
        plan_row = await conn.fetchrow(
            """
            SELECT id FROM plan_versions
            WHERE tenant_id = $1 AND site_id = $2
              AND plan_state IN ('PUBLISHED', 'WORKING')
            ORDER BY
                CASE plan_state WHEN 'PUBLISHED' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT 1
            """,
            tenant_id, site_id
        )
        db_query_count += 1
        if not plan_row:
            logger.warning(f"No plan found for site {site_id}")
            if debug:
                debug.db_query_count = db_query_count
                debug.elapsed_ms = (time.time() - start_time) * 1000
                result.debug_metrics = debug
            return result
        plan_version_id = plan_row["id"]

    # =========================================================================
    # Query 3: Get all frozen days in the week
    # =========================================================================

    frozen_rows = await conn.fetch(
        """
        SELECT day_date FROM dispatch.workbench_days
        WHERE tenant_id = $1 AND site_id = $2
          AND day_date >= $3 AND day_date <= $4
          AND status = 'FROZEN'
        """,
        tenant_id, site_id, week.week_start, week.week_end
    )
    db_query_count += 1
    frozen_days: Set[date] = {r["day_date"] for r in frozen_rows}

    # IMPORTANT: Assign frozen_days early so all return paths include it
    result.frozen_days = list(frozen_days)

    # =========================================================================
    # Query 4: Get pinned days (days with any pinned assignments)
    # =========================================================================

    pinned_rows = await conn.fetch(
        """
        SELECT DISTINCT ti.day
        FROM roster.pins p
        JOIN tour_instances ti ON p.tour_instance_id = ti.id
        JOIN assignments a ON a.tour_instance_id = ti.id AND a.plan_version_id = p.plan_version_id
        WHERE p.plan_version_id = $1 AND p.is_active = TRUE
        """,
        plan_version_id
    )
    db_query_count += 1

    # Convert day index to actual dates
    pinned_days: Set[date] = set()
    for r in pinned_rows:
        day_idx = r["day"]
        pinned_date = week.week_start + timedelta(days=day_idx)
        pinned_days.add(pinned_date)

    # =========================================================================
    # Query 5: Get all open/at-risk slots for target date
    # =========================================================================

    day_idx = day_index_from_date(target_date)

    slots_rows = await conn.fetch(
        """
        SELECT
            ds.slot_id,
            ds.tour_instance_id,
            ds.status as slot_status,
            ti.day,
            ti.start_ts,
            ti.end_ts,
            ti.duration_min,
            a.driver_id as current_driver_id
        FROM dispatch.daily_slots ds
        JOIN tour_instances ti ON ds.tour_instance_id = ti.id
        LEFT JOIN assignments a ON a.tour_instance_id = ti.id AND a.plan_version_id = $4
        WHERE ds.tenant_id = $1 AND ds.site_id = $2 AND ds.day_date = $3
          AND ds.status IN ('PLANNED', 'ASSIGNED')
          AND (a.driver_id IS NULL OR ds.status = 'PLANNED')
        ORDER BY ti.start_ts
        """,
        tenant_id, site_id, target_date, plan_version_id
    )
    db_query_count += 1

    # Build slot contexts
    slots: List[SlotContext] = []
    for row in slots_rows:
        slots.append(SlotContext(
            slot_id=str(row["slot_id"]),
            tour_instance_id=row["tour_instance_id"],
            day_date=target_date,
            day_index=day_idx,
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            duration_minutes=row["duration_min"] or 0,
            current_driver_id=int(row["current_driver_id"]) if row["current_driver_id"] else None,
            is_open=row["current_driver_id"] is None,
            is_at_risk=row["slot_status"] == "PLANNED" and row["current_driver_id"] is None,
        ))

    result.total_open_slots = len(slots)

    if not slots:
        if debug:
            debug.db_query_count = db_query_count
            debug.slots_evaluated = 0
            debug.elapsed_ms = (time.time() - start_time) * 1000
            debug.lookahead_start = str(target_date)
            debug.lookahead_end = str(week.week_end)
            result.debug_metrics = debug
        return result

    # =========================================================================
    # Query 6: Get all available drivers
    # =========================================================================

    drivers_rows = await conn.fetch(
        """
        SELECT id, name, active, max_weekly_hours
        FROM drivers
        WHERE tenant_id = $1 AND site_id = $2 AND active = TRUE
        ORDER BY id
        """,
        tenant_id, site_id
    )
    db_query_count += 1

    drivers = {row["id"]: {
        "id": row["id"],
        "name": row["name"],
        "max_weekly_hours": row["max_weekly_hours"] or 55.0,
    } for row in drivers_rows}

    if not drivers:
        logger.warning(f"No active drivers for site {site_id}")
        if debug:
            debug.db_query_count = db_query_count
            debug.drivers_considered = 0
            debug.elapsed_ms = (time.time() - start_time) * 1000
            result.debug_metrics = debug
        return result

    # =========================================================================
    # Query 7: Get all assignments for all drivers for the LOOKAHEAD RANGE
    # CRITICAL: We only need assignments from TODAY onwards, not the whole week
    # =========================================================================

    # Lookahead range: from target_date to week_end
    lookahead_start = target_date
    lookahead_end = week.week_end

    # Convert to day indices
    lookahead_start_idx = day_index_from_date(lookahead_start)
    lookahead_end_idx = day_index_from_date(lookahead_end)
    lookahead_day_indices = list(range(lookahead_start_idx, lookahead_end_idx + 1))

    # But we also need the day BEFORE target_date for rest checks
    if lookahead_start_idx > 0:
        lookahead_day_indices.insert(0, lookahead_start_idx - 1)

    assignments_rows = await conn.fetch(
        """
        SELECT
            a.driver_id::integer as driver_id,
            a.tour_instance_id,
            ti.day as day_index,
            ti.start_ts,
            ti.end_ts,
            p.id as pin_id
        FROM assignments a
        JOIN tour_instances ti ON a.tour_instance_id = ti.id
        LEFT JOIN roster.pins p ON p.tour_instance_id = ti.id
            AND p.plan_version_id = a.plan_version_id AND p.is_active = TRUE
        WHERE a.plan_version_id = $1
          AND a.driver_id::integer = ANY($2)
          AND ti.day = ANY($3)
        ORDER BY a.driver_id, ti.day, ti.start_ts
        """,
        plan_version_id, list(drivers.keys()), lookahead_day_indices
    )
    db_query_count += 1

    # Build driver -> week assignments mapping
    driver_week_assignments: Dict[int, List[DayAssignment]] = {
        d_id: [] for d_id in drivers
    }
    driver_weekly_hours: Dict[int, float] = {d_id: 0.0 for d_id in drivers}

    for row in assignments_rows:
        d_id = row["driver_id"]
        if d_id not in driver_week_assignments:
            continue

        # Convert day index to actual date
        day_date = week.week_start + timedelta(days=row["day_index"])

        asgn = DayAssignment(
            day_date=day_date,
            day_index=row["day_index"],
            tour_instance_id=row["tour_instance_id"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            is_frozen=day_date in frozen_days,
            is_pinned=row["pin_id"] is not None,  # Per-assignment pin
        )
        driver_week_assignments[d_id].append(asgn)

        # Accumulate hours
        if row["start_ts"] and row["end_ts"]:
            hours = (row["end_ts"] - row["start_ts"]).total_seconds() / 3600
            driver_weekly_hours[d_id] += hours

    # =========================================================================
    # Evaluate candidates for each slot
    # =========================================================================

    total_evaluations = 0

    for slot in slots:
        candidates: List[CandidateImpact] = []
        blocker_counts: Dict[str, int] = {
            "overlap": 0,
            "rest": 0,
            "max_tours": 0,
            "frozen": 0,
            "hours": 0,
        }

        for driver_id, driver_info in drivers.items():
            # Skip if this is the current driver for the slot
            if slot.current_driver_id and driver_id == slot.current_driver_id:
                continue

            candidate = await evaluate_candidate_with_lookahead(
                conn=conn,
                tenant_id=tenant_id,
                site_id=site_id,
                driver_id=driver_id,
                driver_name=driver_info["name"],
                slot=slot,
                week_window=week,
                driver_week_assignments=driver_week_assignments[driver_id],
                driver_current_hours=driver_weekly_hours[driver_id],
                frozen_days=frozen_days,
                pinned_days=pinned_days,
                allow_multiday_repair=allow_multiday_repair,
                config=cfg,
            )

            candidates.append(candidate)
            total_evaluations += 1

            # Count blockers
            if not candidate.feasible_today:
                for blocker in candidate.blockers:
                    blocker_lower = blocker.lower()
                    if "overlap" in blocker_lower:
                        blocker_counts["overlap"] += 1
                    elif "rest" in blocker_lower:
                        blocker_counts["rest"] += 1
                    elif "tours" in blocker_lower:
                        blocker_counts["max_tours"] += 1
                    elif "frozen" in blocker_lower:
                        blocker_counts["frozen"] += 1
                    elif "hour" in blocker_lower:
                        blocker_counts["hours"] += 1

        # Rank candidates using lexicographic ordering with driver_id tiebreaker
        ranked_candidates = rank_candidates(candidates)

        # Take top N candidates
        top_candidates = ranked_candidates[:max_candidates_per_slot]

        # Build explanation and blocker_summary for each candidate
        for cand in top_candidates:
            if not cand.feasible_today:
                cand.blocker_summary = "; ".join(cand.blockers) if cand.blockers else "Not feasible"
                cand.today_violations = cand.blockers.copy()
                cand.explanation = f"Not feasible: {cand.blocker_summary}"
            elif not cand.explanation:
                parts = []
                if cand.churn_count == 0 and cand.churn_locked_count == 0:
                    parts.append("No downstream impact")
                if cand.churn_count > 0:
                    parts.append(f"{cand.churn_count} future repair(s) needed")
                    cand.week_violations = [f"Would require repair on {a.date}" for a in cand.affected_slots]
                if cand.tours_today_current > 0:
                    parts.append("already working today")
                cand.explanation = ", ".join(parts) if parts else f"Score: {cand.score:.1f}"

        # Legacy mappings
        result.candidates_by_slot[slot.slot_id] = top_candidates
        result.blocker_summary_by_slot[slot.slot_id] = blocker_counts

        # Build time_window string
        time_window = "00:00-00:00"
        if slot.start_ts and slot.end_ts:
            time_window = f"{slot.start_ts.strftime('%H:%M')}-{slot.end_ts.strftime('%H:%M')}"

        # Check if slot is pinned
        is_pinned = slot.day_date in pinned_days

        # Add to new slots list
        slot_result = SlotResult(
            slot_id=slot.slot_id,
            tour_instance_id=slot.tour_instance_id,
            date=slot.day_date,
            time_window=time_window,
            current_driver_id=slot.current_driver_id,
            is_pinned=is_pinned,
            candidates=top_candidates,
            blocker_summary=blocker_counts,
        )
        result.slots.append(slot_result)

        if top_candidates and top_candidates[0].feasible_today:
            result.slots_with_candidates += 1

    # frozen_days already assigned after Query 3 (line 221)
    # No need to reassign here

    # Add debug metrics if requested
    if debug:
        debug.db_query_count = db_query_count
        debug.drivers_considered = len(drivers)
        debug.slots_evaluated = total_evaluations
        debug.elapsed_ms = (time.time() - start_time) * 1000
        debug.lookahead_start = str(lookahead_start)
        debug.lookahead_end = str(lookahead_end)
        result.debug_metrics = debug

    return result
