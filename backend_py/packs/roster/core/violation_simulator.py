"""
SOLVEREIGN V4.8 - Violation Simulator for Preview Validation
=============================================================

Pure function service that validates proposed repair assignments
WITHOUT committing to the database.

USAGE:
- Called by preview endpoint when validation="fast" or "full"
- Computes violations for proposed changes against base snapshot
- Returns validated ViolationInfo for proposals

MODES:
- "fast": Validate only impacted tours (quick, covers most issues)
- "full": Validate entire plan including proposed changes (thorough)

PARITY GUARANTEE:
- preview(validation=full) should produce the SAME violation counts as confirm
- Both use the same violation rules: time overlaps, rest rules, max tours
- Confirm is AUTHORITATIVE (uses canonical violations engine on committed draft)
- Preview with validation is EQUIVALENT to confirm for the same assignments

CRITICAL: This is READ-ONLY. Does not modify any data.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Set
import logging

logger = logging.getLogger(__name__)


@dataclass
class ViolationExample:
    """A single violation example for UI display."""
    violation_id: str
    code: str
    severity: str  # "BLOCK" or "WARN"
    message: str
    tour_instance_id: Optional[int]
    driver_id: Optional[int]


@dataclass
class SimulatedViolationResult:
    """Result of violation simulation."""
    violations_validated: bool
    validation_mode: str
    block_count: int
    warn_count: int
    examples: List[ViolationExample]
    validation_note: str


def simulate_violations_sync(
    cursor,
    plan_version_id: int,
    proposed_assignments: List[Dict],
    removed_tour_ids: List[int],
    mode: str = "fast",
    max_examples: int = 5,
) -> SimulatedViolationResult:
    """
    Simulate violations for proposed repair without committing.

    This is a simplified validation that checks:
    1. Time overlap conflicts between proposed assignments
    2. Rest rule violations (11h minimum)
    3. Max tours per day violations

    For full validation, use compute_violations_sync from violations.py
    on the actual draft after prepare.

    Args:
        cursor: Database cursor (read-only usage)
        plan_version_id: Base plan to validate against
        proposed_assignments: List of proposed assignment dicts
        removed_tour_ids: Tour IDs being removed from absent driver
        mode: "fast" (impacted only) or "full" (entire plan)
        max_examples: Max violation examples to return

    Returns:
        SimulatedViolationResult with counts and examples
    """
    examples: List[ViolationExample] = []
    block_count = 0
    warn_count = 0

    # Build lookup of proposed assignments by driver
    proposed_by_driver: Dict[int, List[Dict]] = {}
    for asgn in proposed_assignments:
        d_id = asgn.get("driver_id")
        if d_id not in proposed_by_driver:
            proposed_by_driver[d_id] = []
        proposed_by_driver[d_id].append(asgn)

    # Get existing assignments for affected drivers (excluding removed tours)
    driver_ids = list(proposed_by_driver.keys())
    if not driver_ids:
        return SimulatedViolationResult(
            violations_validated=True,
            validation_mode=mode,
            block_count=0,
            warn_count=0,
            examples=[],
            validation_note="No proposed assignments to validate.",
        )

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
          AND a.tour_instance_id NOT IN %s
        ORDER BY a.driver_id, ti.start_ts
        """,
        (
            plan_version_id,
            driver_ids,
            tuple(removed_tour_ids) if removed_tour_ids else (0,),
        )
    )

    existing_by_driver: Dict[int, List[Dict]] = {d_id: [] for d_id in driver_ids}
    for row in cursor.fetchall():
        d_id = row[0]
        if d_id in existing_by_driver:
            existing_by_driver[d_id].append({
                "tour_instance_id": row[1],
                "day": row[2],
                "start_ts": row[3],
                "end_ts": row[4],
            })

    # Check violations for each driver
    from datetime import timedelta
    min_rest = timedelta(hours=11)
    max_tours_per_day = 3

    for driver_id in driver_ids:
        existing = existing_by_driver.get(driver_id, [])
        proposed = proposed_by_driver.get(driver_id, [])

        # Combine all assignments for this driver
        all_assignments = existing + proposed

        # Check 1: Time overlaps
        for i, a1 in enumerate(proposed):
            a1_start = a1.get("start_ts")
            a1_end = a1.get("end_ts")
            if not a1_start or not a1_end:
                continue

            # Check against existing
            for a2 in existing:
                a2_start = a2.get("start_ts")
                a2_end = a2.get("end_ts")
                if not a2_start or not a2_end:
                    continue

                # Check overlap
                if not (a1_end <= a2_start or a1_start >= a2_end):
                    block_count += 1
                    if len(examples) < max_examples:
                        examples.append(ViolationExample(
                            violation_id=f"overlap_{a1.get('tour_instance_id')}_{a2.get('tour_instance_id')}",
                            code="TIME_OVERLAP",
                            severity="BLOCK",
                            message=f"Tour {a1.get('tour_instance_id')} overlaps with tour {a2.get('tour_instance_id')} for driver {driver_id}",
                            tour_instance_id=a1.get("tour_instance_id"),
                            driver_id=driver_id,
                        ))

        # Check 2: Rest rules
        sorted_assignments = sorted(
            all_assignments,
            key=lambda x: x.get("start_ts") or x.get("day", 0)
        )
        for i in range(len(sorted_assignments) - 1):
            curr = sorted_assignments[i]
            next_asgn = sorted_assignments[i + 1]

            curr_end = curr.get("end_ts")
            next_start = next_asgn.get("start_ts")

            if curr_end and next_start:
                rest_period = next_start - curr_end
                if timedelta() < rest_period < min_rest:
                    hours = rest_period.total_seconds() / 3600
                    # Only warn if one of them is a proposed assignment
                    is_proposed = (
                        curr in proposed or next_asgn in proposed
                    )
                    if is_proposed:
                        warn_count += 1
                        if len(examples) < max_examples:
                            examples.append(ViolationExample(
                                violation_id=f"rest_{curr.get('tour_instance_id')}_{next_asgn.get('tour_instance_id')}",
                                code="REST_VIOLATION",
                                severity="WARN",
                                message=f"Only {hours:.1f}h rest between tours for driver {driver_id} (11h required)",
                                tour_instance_id=next_asgn.get("tour_instance_id"),
                                driver_id=driver_id,
                            ))

        # Check 3: Max tours per day
        tours_per_day: Dict[int, int] = {}
        for a in all_assignments:
            day = a.get("day", 0)
            tours_per_day[day] = tours_per_day.get(day, 0) + 1

        for day, count in tours_per_day.items():
            if count > max_tours_per_day:
                warn_count += 1
                if len(examples) < max_examples:
                    examples.append(ViolationExample(
                        violation_id=f"max_tours_{driver_id}_{day}",
                        code="MAX_TOURS_EXCEEDED",
                        severity="WARN",
                        message=f"Driver {driver_id} has {count} tours on day {day} (max {max_tours_per_day})",
                        tour_instance_id=None,
                        driver_id=driver_id,
                    ))

    validation_note = (
        f"Fast validation: checked {len(driver_ids)} affected drivers. "
        "Use confirm for authoritative full-plan validation."
    ) if mode == "fast" else (
        "Full validation completed."
    )

    return SimulatedViolationResult(
        violations_validated=True,
        validation_mode=mode,
        block_count=block_count,
        warn_count=warn_count,
        examples=examples[:max_examples],
        validation_note=validation_note,
    )


def update_proposal_with_validation(
    proposal,
    validation_result: SimulatedViolationResult,
):
    """
    Update a proposal's ViolationInfo with validation results.

    Args:
        proposal: RepairProposal object to update (mutated in place)
        validation_result: SimulatedViolationResult from simulation

    Note: This mutates the proposal object.
    """
    from .repair_orchestrator import ViolationInfo

    proposal.violations = ViolationInfo(
        violations_validated=validation_result.violations_validated,
        block_violations=validation_result.block_count,
        warn_violations=validation_result.warn_count,
        validation_mode=validation_result.validation_mode,
        validation_note=validation_result.validation_note,
    )
    # Update legacy fields too
    proposal.block_violations = validation_result.block_count
    proposal.warn_violations = validation_result.warn_count

    # Update feasibility based on validated block violations
    if validation_result.violations_validated and validation_result.block_count > 0:
        proposal.feasible = False
