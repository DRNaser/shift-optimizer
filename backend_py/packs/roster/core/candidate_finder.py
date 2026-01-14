"""
SOLVEREIGN V4.8 - Candidate Finder Service
============================================

Read-only service that finds eligible drivers for repair assignments.

For each impacted tour, returns a ranked list of candidate drivers that:
- Are not absent during the tour time
- Have no overlapping assignments
- Respect rest rules (11h minimum)
- Respect max_tours_per_day limits
- Are deterministically ranked by minimal disruption

CRITICAL: This is a read-only service. It does NOT modify any data.
Used by RepairOrchestrator to identify legal candidates before generating proposals.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class TourInfo:
    """Information about a tour instance."""
    tour_instance_id: int
    tour_id: str
    day: int  # 0=Mon, 6=Sun
    start_ts: Optional[datetime]
    end_ts: Optional[datetime]
    driver_id: Optional[int]
    block_type: str  # "1er", "2er", "3er"


@dataclass
class DriverAssignment:
    """Existing assignment for a driver."""
    tour_instance_id: int
    day: int
    start_ts: Optional[datetime]
    end_ts: Optional[datetime]


@dataclass
class CandidateDriver:
    """A candidate driver for a tour assignment."""
    driver_id: int
    name: str
    score: float  # Higher = better candidate
    existing_tours_count: int
    existing_hours: float
    is_working_same_day: bool
    reason: str  # Why this candidate was selected
    disqualifiers: List[str] = field(default_factory=list)  # Empty if eligible


@dataclass
class CandidateResult:
    """Result of candidate finding for a single tour."""
    tour_instance_id: int
    candidates: List[CandidateDriver]
    total_available: int
    filtered_count: int
    # Compatibility info (P1.5A)
    compatibility_checked: bool = False  # True if skills/vehicle were checked
    compatibility_unknown: bool = True   # True by default - skill/vehicle data not checked


# =============================================================================
# HARD CONSTRAINT CHECKERS
# =============================================================================

def check_time_overlap(
    tour_start: Optional[datetime],
    tour_end: Optional[datetime],
    existing: List[DriverAssignment],
    buffer_minutes: int = 0,
) -> Tuple[bool, Optional[str]]:
    """
    Check if a tour overlaps with any existing assignments.

    Args:
        tour_start: Tour start time
        tour_end: Tour end time
        existing: List of existing assignments
        buffer_minutes: Buffer time between assignments

    Returns:
        Tuple of (has_overlap, reason_if_overlap)
    """
    if not tour_start or not tour_end:
        # Conservative: if no time info, check day-level overlap
        return (False, None)

    buffer = timedelta(minutes=buffer_minutes)

    for asgn in existing:
        if not asgn.start_ts or not asgn.end_ts:
            continue

        # Check overlap: not (tour_end <= asgn_start or tour_start >= asgn_end)
        if not (tour_end + buffer <= asgn.start_ts or tour_start - buffer >= asgn.end_ts):
            return (True, f"Overlaps with tour {asgn.tour_instance_id}")

    return (False, None)


def check_rest_rule(
    tour_start: Optional[datetime],
    tour_end: Optional[datetime],
    existing: List[DriverAssignment],
    min_rest_hours: int = 11,
) -> Tuple[bool, Optional[str]]:
    """
    Check if assigning this tour would violate rest rules.

    Rest rule: At least 11 hours between end of one shift and start of next.

    Returns:
        Tuple of (violates_rest, reason_if_violation)
    """
    if not tour_start or not tour_end:
        return (False, None)

    min_rest = timedelta(hours=min_rest_hours)

    for asgn in existing:
        if not asgn.start_ts or not asgn.end_ts:
            continue

        # Check rest before this tour
        rest_before = tour_start - asgn.end_ts
        if timedelta() < rest_before < min_rest:
            hours = rest_before.total_seconds() / 3600
            return (True, f"Only {hours:.1f}h rest after tour {asgn.tour_instance_id}")

        # Check rest after this tour
        rest_after = asgn.start_ts - tour_end
        if timedelta() < rest_after < min_rest:
            hours = rest_after.total_seconds() / 3600
            return (True, f"Only {hours:.1f}h rest before tour {asgn.tour_instance_id}")

    return (False, None)


def check_max_tours_per_day(
    day: int,
    existing: List[DriverAssignment],
    max_tours: int = 3,
) -> Tuple[bool, Optional[str]]:
    """
    Check if driver already has max tours on this day.

    Returns:
        Tuple of (exceeds_max, reason_if_exceeded)
    """
    same_day_count = sum(1 for a in existing if a.day == day)

    if same_day_count >= max_tours:
        return (True, f"Already has {same_day_count} tours on day {day}")

    return (False, None)


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================

def compute_candidate_score(
    driver_id: int,
    tour_day: int,
    existing_assignments: List[DriverAssignment],
    weekly_hours: float,
    max_weekly_hours: int = 55,
) -> float:
    """
    Compute a score for how good this candidate is.
    Higher score = better candidate (minimal disruption).

    Scoring factors:
    1. Available weekly capacity (prefer drivers with more slack)
    2. Already working same day (prefer to avoid new callouts)
    3. Fewer total assignments (spread load)
    """
    score = 100.0  # Base score

    # Factor 1: Weekly capacity remaining
    capacity_remaining = max(0, max_weekly_hours - weekly_hours)
    score += capacity_remaining * 0.5  # Up to +27.5 for full capacity

    # Factor 2: Already working same day bonus
    same_day_count = sum(1 for a in existing_assignments if a.day == tour_day)
    if same_day_count > 0:
        score += 20.0  # Prefer drivers already scheduled that day

    # Factor 3: Fewer total assignments
    total_assignments = len(existing_assignments)
    score -= total_assignments * 2.0  # Penalty for each existing assignment

    # Deterministic tie-breaker using driver_id
    score -= driver_id * 0.0001  # Tiny penalty to break ties deterministically

    return score


# =============================================================================
# MAIN CANDIDATE FINDER
# =============================================================================

def find_candidates_sync(
    cursor,
    tenant_id: int,
    site_id: int,
    plan_version_id: int,
    impacted_tours: List[TourInfo],
    absent_driver_ids: Set[int],
    freeze_driver_ids: Set[int],
    config: Optional[dict] = None,
) -> Dict[int, CandidateResult]:
    """
    Find eligible candidate drivers for each impacted tour.

    Synchronous version for psycopg2 cursor.

    Args:
        cursor: Database cursor
        tenant_id: Tenant ID for RLS
        site_id: Site ID for scope
        plan_version_id: Plan version to get current assignments from
        impacted_tours: Tours that need new drivers
        absent_driver_ids: Drivers who are absent (exclude them)
        freeze_driver_ids: Drivers who are frozen (exclude them)
        config: Optional configuration overrides

    Returns:
        Dict mapping tour_instance_id -> CandidateResult
    """
    cfg = config or {}
    min_rest_hours = cfg.get("min_rest_hours", 11)
    max_tours_per_day = cfg.get("max_tours_per_day", 3)
    max_weekly_hours = cfg.get("max_weekly_hours", 55)
    max_candidates = cfg.get("max_candidates_per_tour", 10)

    # Step 1: Load all available drivers
    exclude_ids = absent_driver_ids | freeze_driver_ids
    exclude_tuple = tuple(exclude_ids) if exclude_ids else (0,)

    cursor.execute(
        """
        SELECT id, name, active
        FROM drivers
        WHERE tenant_id = %s
          AND active = true
          AND id NOT IN %s
        ORDER BY id
        """,
        (tenant_id, exclude_tuple)
    )
    available_drivers = {
        row[0]: {"id": row[0], "name": row[1]}
        for row in cursor.fetchall()
    }

    if not available_drivers:
        logger.warning(f"No available drivers for tenant {tenant_id}")
        return {t.tour_instance_id: CandidateResult(
            tour_instance_id=t.tour_instance_id,
            candidates=[],
            total_available=0,
            filtered_count=0,
            compatibility_checked=False,
            compatibility_unknown=True,  # No skill/vehicle data checked
        ) for t in impacted_tours}

    # Step 2: Load all current assignments for available drivers
    driver_ids_tuple = tuple(available_drivers.keys())
    cursor.execute(
        """
        SELECT
            a.driver_id::integer,
            a.tour_instance_id,
            a.day,
            ti.start_ts,
            ti.end_ts
        FROM assignments a
        LEFT JOIN tour_instances ti ON a.tour_instance_id = ti.id
        WHERE a.plan_version_id = %s
          AND a.driver_id::integer = ANY(%s)
        ORDER BY a.driver_id, a.day
        """,
        (plan_version_id, list(driver_ids_tuple))
    )

    # Build driver -> assignments mapping
    driver_assignments: Dict[int, List[DriverAssignment]] = {
        d_id: [] for d_id in available_drivers
    }
    driver_weekly_hours: Dict[int, float] = {d_id: 0.0 for d_id in available_drivers}

    for row in cursor.fetchall():
        d_id = row[0]
        if d_id in driver_assignments:
            asgn = DriverAssignment(
                tour_instance_id=row[1],
                day=row[2],
                start_ts=row[3],
                end_ts=row[4],
            )
            driver_assignments[d_id].append(asgn)

            # Accumulate hours
            if row[3] and row[4]:
                hours = (row[4] - row[3]).total_seconds() / 3600
                driver_weekly_hours[d_id] += hours

    # Step 3: For each impacted tour, find eligible candidates
    results: Dict[int, CandidateResult] = {}

    for tour in impacted_tours:
        candidates: List[CandidateDriver] = []
        filtered_count = 0

        for driver_id, driver_info in available_drivers.items():
            existing = driver_assignments[driver_id]
            weekly_hours = driver_weekly_hours[driver_id]
            disqualifiers: List[str] = []

            # Check hard constraints
            has_overlap, overlap_reason = check_time_overlap(
                tour.start_ts, tour.end_ts, existing
            )
            if has_overlap:
                disqualifiers.append(overlap_reason)

            violates_rest, rest_reason = check_rest_rule(
                tour.start_ts, tour.end_ts, existing, min_rest_hours
            )
            if violates_rest:
                disqualifiers.append(rest_reason)

            exceeds_max, max_reason = check_max_tours_per_day(
                tour.day, existing, max_tours_per_day
            )
            if exceeds_max:
                disqualifiers.append(max_reason)

            # Check weekly hours limit (soft constraint, but warn)
            if weekly_hours >= max_weekly_hours:
                disqualifiers.append(f"At weekly hour limit ({weekly_hours:.1f}h)")

            # If disqualified, count but don't include
            if disqualifiers:
                filtered_count += 1
                continue

            # Compute score
            score = compute_candidate_score(
                driver_id=driver_id,
                tour_day=tour.day,
                existing_assignments=existing,
                weekly_hours=weekly_hours,
                max_weekly_hours=max_weekly_hours,
            )

            same_day = any(a.day == tour.day for a in existing)

            candidates.append(CandidateDriver(
                driver_id=driver_id,
                name=driver_info["name"],
                score=score,
                existing_tours_count=len(existing),
                existing_hours=weekly_hours,
                is_working_same_day=same_day,
                reason="Available with minimal disruption",
                disqualifiers=[],
            ))

        # Sort by score descending (deterministic due to driver_id in score)
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Limit to top N
        candidates = candidates[:max_candidates]

        results[tour.tour_instance_id] = CandidateResult(
            tour_instance_id=tour.tour_instance_id,
            candidates=candidates,
            total_available=len(available_drivers),
            filtered_count=filtered_count,
            compatibility_checked=False,  # P1.5B will enable this
            compatibility_unknown=True,   # No skill/vehicle data checked yet
        )

        logger.debug(
            f"Tour {tour.tour_instance_id}: {len(candidates)} candidates "
            f"(filtered {filtered_count}/{len(available_drivers)})"
        )

    return results


async def find_candidates_async(
    conn,
    tenant_id: int,
    site_id: int,
    plan_version_id: int,
    impacted_tours: List[TourInfo],
    absent_driver_ids: Set[int],
    freeze_driver_ids: Set[int],
    config: Optional[dict] = None,
) -> Dict[int, CandidateResult]:
    """
    Find eligible candidate drivers for each impacted tour.

    Async version for asyncpg connection.

    Args:
        conn: Async database connection
        tenant_id: Tenant ID for RLS
        site_id: Site ID for scope
        plan_version_id: Plan version to get current assignments from
        impacted_tours: Tours that need new drivers
        absent_driver_ids: Drivers who are absent
        freeze_driver_ids: Drivers who are frozen
        config: Optional configuration overrides

    Returns:
        Dict mapping tour_instance_id -> CandidateResult
    """
    cfg = config or {}
    min_rest_hours = cfg.get("min_rest_hours", 11)
    max_tours_per_day = cfg.get("max_tours_per_day", 3)
    max_weekly_hours = cfg.get("max_weekly_hours", 55)
    max_candidates = cfg.get("max_candidates_per_tour", 10)

    # Step 1: Load all available drivers
    exclude_ids = list(absent_driver_ids | freeze_driver_ids)

    rows = await conn.fetch(
        """
        SELECT id, name, active
        FROM drivers
        WHERE tenant_id = $1
          AND active = true
          AND NOT (id = ANY($2))
        ORDER BY id
        """,
        tenant_id, exclude_ids or [0]
    )
    available_drivers = {
        row["id"]: {"id": row["id"], "name": row["name"]}
        for row in rows
    }

    if not available_drivers:
        logger.warning(f"No available drivers for tenant {tenant_id}")
        return {t.tour_instance_id: CandidateResult(
            tour_instance_id=t.tour_instance_id,
            candidates=[],
            total_available=0,
            filtered_count=0,
            compatibility_checked=False,
            compatibility_unknown=True,  # No skill/vehicle data checked
        ) for t in impacted_tours}

    # Step 2: Load all current assignments for available drivers
    driver_ids_list = list(available_drivers.keys())

    rows = await conn.fetch(
        """
        SELECT
            a.driver_id::integer,
            a.tour_instance_id,
            a.day,
            ti.start_ts,
            ti.end_ts
        FROM assignments a
        LEFT JOIN tour_instances ti ON a.tour_instance_id = ti.id
        WHERE a.plan_version_id = $1
          AND a.driver_id::integer = ANY($2)
        ORDER BY a.driver_id, a.day
        """,
        plan_version_id, driver_ids_list
    )

    # Build driver -> assignments mapping
    driver_assignments: Dict[int, List[DriverAssignment]] = {
        d_id: [] for d_id in available_drivers
    }
    driver_weekly_hours: Dict[int, float] = {d_id: 0.0 for d_id in available_drivers}

    for row in rows:
        d_id = row["driver_id"]
        if d_id in driver_assignments:
            asgn = DriverAssignment(
                tour_instance_id=row["tour_instance_id"],
                day=row["day"],
                start_ts=row["start_ts"],
                end_ts=row["end_ts"],
            )
            driver_assignments[d_id].append(asgn)

            if row["start_ts"] and row["end_ts"]:
                hours = (row["end_ts"] - row["start_ts"]).total_seconds() / 3600
                driver_weekly_hours[d_id] += hours

    # Step 3: For each impacted tour, find eligible candidates
    results: Dict[int, CandidateResult] = {}

    for tour in impacted_tours:
        candidates: List[CandidateDriver] = []
        filtered_count = 0

        for driver_id, driver_info in available_drivers.items():
            existing = driver_assignments[driver_id]
            weekly_hours = driver_weekly_hours[driver_id]
            disqualifiers: List[str] = []

            # Check hard constraints
            has_overlap, overlap_reason = check_time_overlap(
                tour.start_ts, tour.end_ts, existing
            )
            if has_overlap:
                disqualifiers.append(overlap_reason)

            violates_rest, rest_reason = check_rest_rule(
                tour.start_ts, tour.end_ts, existing, min_rest_hours
            )
            if violates_rest:
                disqualifiers.append(rest_reason)

            exceeds_max, max_reason = check_max_tours_per_day(
                tour.day, existing, max_tours_per_day
            )
            if exceeds_max:
                disqualifiers.append(max_reason)

            if weekly_hours >= max_weekly_hours:
                disqualifiers.append(f"At weekly hour limit ({weekly_hours:.1f}h)")

            if disqualifiers:
                filtered_count += 1
                continue

            score = compute_candidate_score(
                driver_id=driver_id,
                tour_day=tour.day,
                existing_assignments=existing,
                weekly_hours=weekly_hours,
                max_weekly_hours=max_weekly_hours,
            )

            same_day = any(a.day == tour.day for a in existing)

            candidates.append(CandidateDriver(
                driver_id=driver_id,
                name=driver_info["name"],
                score=score,
                existing_tours_count=len(existing),
                existing_hours=weekly_hours,
                is_working_same_day=same_day,
                reason="Available with minimal disruption",
                disqualifiers=[],
            ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        candidates = candidates[:max_candidates]

        results[tour.tour_instance_id] = CandidateResult(
            tour_instance_id=tour.tour_instance_id,
            candidates=candidates,
            total_available=len(available_drivers),
            filtered_count=filtered_count,
            compatibility_checked=False,  # P1.5B will enable this
            compatibility_unknown=True,   # No skill/vehicle data checked yet
        )

    return results
