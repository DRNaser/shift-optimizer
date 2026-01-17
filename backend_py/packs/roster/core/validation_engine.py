"""
SOLVEREIGN V4.9 - Validation Engine for Dispatch Workbench

Fast and full validation modes for draft mutations.
- Fast: Overlap, rest violation, pin conflict checks (instant)
- Full: Complete validation with parity guarantee

Non-negotiables:
- NO FAKE GREEN: Never claim 0 violations unless actually validated
- PARITY GUARANTEE: validate(full) == confirm validation
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
import asyncpg
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

MIN_REST_HOURS = 11  # Minimum rest between shifts (§ 5 ArbZG)
MAX_DAILY_HOURS = 10  # Maximum daily working hours
MAX_WEEKLY_HOURS = 60  # Maximum weekly working hours


class ValidationMode(str, Enum):
    NONE = "none"
    FAST = "fast"
    FULL = "full"


class Severity(str, Enum):
    HARD_BLOCK = "HARD_BLOCK"  # Cannot proceed
    SOFT_BLOCK = "SOFT_BLOCK"  # Warning, can override
    INFO = "INFO"  # Informational only


class ViolationType(str, Enum):
    # Hard blocks
    OVERLAP = "OVERLAP"
    REST_VIOLATION = "REST_VIOLATION"
    PIN_CONFLICT = "PIN_CONFLICT"

    # Soft blocks
    HOURS_EXCEEDED = "HOURS_EXCEEDED"
    COMPATIBILITY_UNKNOWN = "COMPATIBILITY_UNKNOWN"
    SKILL_MISMATCH = "SKILL_MISMATCH"
    PREFERENCE_VIOLATION = "PREFERENCE_VIOLATION"


@dataclass
class Violation:
    type: ViolationType
    severity: Severity
    message: str
    driver_id: Optional[int] = None
    tour_instance_id: Optional[int] = None
    suggested_action: Optional[str] = None
    details: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    is_valid: bool
    mode: ValidationMode
    hard_blocks: int
    soft_blocks: int
    violations: list[Violation]
    parity_hash: Optional[str] = None  # Hash for full validation parity guarantee


def classify_risk_tier(hard_blocks: int, soft_blocks: int) -> str:
    """
    Classify risk tier based on violation counts.

    Returns:
        Risk tier string: CRITICAL, HIGH, MEDIUM, LOW
    """
    if hard_blocks > 0:
        return "CRITICAL" if hard_blocks >= 3 else "HIGH"
    if soft_blocks > 0:
        return "MEDIUM" if soft_blocks >= 5 else "LOW"
    return "LOW"


# =============================================================================
# FAST VALIDATION (Instant checks)
# =============================================================================

async def validate_fast(
    conn: asyncpg.Connection,
    session_id: str,
    tenant_id: int,
    site_id: int,
) -> ValidationResult:
    """
    Fast validation: Overlap, rest, and pin conflict checks.
    Returns immediately with hard/soft block status.
    """
    violations: list[Violation] = []

    # Get all pending mutations for this session
    mutations = await conn.fetch("""
        SELECT
            dm.mutation_id,
            dm.op,
            dm.tour_instance_id,
            dm.driver_id,
            dm.day,
            ti.start_ts,
            ti.end_ts,
            ti.tour_name
        FROM roster.draft_mutations dm
        JOIN tour_instances ti ON ti.id = dm.tour_instance_id
        WHERE dm.session_id = $1
          AND dm.status = 'PENDING'
        ORDER BY dm.sequence_no
    """, session_id)

    if not mutations:
        return ValidationResult(
            is_valid=True,
            mode=ValidationMode.FAST,
            hard_blocks=0,
            soft_blocks=0,
            violations=[],
        )

    # Group mutations by driver for overlap/rest checks
    driver_mutations: dict[int, list] = {}
    for m in mutations:
        if m['driver_id']:
            driver_id = m['driver_id']
            if driver_id not in driver_mutations:
                driver_mutations[driver_id] = []
            driver_mutations[driver_id].append(m)

    # Check each driver's mutations
    for driver_id, muts in driver_mutations.items():
        driver_violations = await _check_driver_constraints(
            conn, driver_id, muts, tenant_id, site_id
        )
        violations.extend(driver_violations)

    # Check pin conflicts
    pin_violations = await _check_pin_conflicts(conn, mutations, tenant_id)
    violations.extend(pin_violations)

    # Count by severity
    hard_blocks = sum(1 for v in violations if v.severity == Severity.HARD_BLOCK)
    soft_blocks = sum(1 for v in violations if v.severity == Severity.SOFT_BLOCK)

    return ValidationResult(
        is_valid=(hard_blocks == 0),
        mode=ValidationMode.FAST,
        hard_blocks=hard_blocks,
        soft_blocks=soft_blocks,
        violations=violations,
    )


async def _check_driver_constraints(
    conn: asyncpg.Connection,
    driver_id: int,
    mutations: list,
    tenant_id: int,
    site_id: int,
) -> list[Violation]:
    """Check overlap and rest violations for a driver."""
    violations = []

    # Get driver's existing assignments for the relevant days
    days = set(m['day'] for m in mutations)
    min_day = min(days) - 1  # Include previous day for rest check
    max_day = max(days) + 1  # Include next day for rest check

    existing = await conn.fetch("""
        SELECT
            a.id as assignment_id,
            a.tour_instance_id,
            ti.start_ts,
            ti.end_ts,
            ti.day_of_week,
            a.is_pinned
        FROM assignments a
        JOIN tour_instances ti ON ti.id = a.tour_instance_id
        WHERE a.driver_id = $1
          AND ti.site_id = $2
          AND ti.day_of_week BETWEEN $3 AND $4
        ORDER BY ti.start_ts
    """, driver_id, site_id, min_day, max_day)

    # Build timeline of all shifts (existing + new from mutations)
    shifts = []

    # Add existing shifts
    for e in existing:
        shifts.append({
            'tour_instance_id': e['tour_instance_id'],
            'start_ts': e['start_ts'],
            'end_ts': e['end_ts'],
            'day': e['day_of_week'],
            'is_new': False,
            'is_pinned': e['is_pinned'],
        })

    # Add new shifts from ASSIGN mutations, remove UNASSIGN
    unassigned_tours = set()
    for m in mutations:
        if m['op'] == 'unassign':
            unassigned_tours.add(m['tour_instance_id'])

    for m in mutations:
        if m['op'] == 'assign' and m['tour_instance_id'] not in unassigned_tours:
            shifts.append({
                'tour_instance_id': m['tour_instance_id'],
                'start_ts': m['start_ts'],
                'end_ts': m['end_ts'],
                'day': m['day'],
                'is_new': True,
                'is_pinned': False,
            })

    # Filter out unassigned shifts
    shifts = [s for s in shifts if s['tour_instance_id'] not in unassigned_tours]

    # Sort by start time
    shifts.sort(key=lambda s: s['start_ts'] if s['start_ts'] else datetime.min)

    # Check for overlaps
    for i, shift1 in enumerate(shifts):
        for shift2 in shifts[i+1:]:
            if shift1['start_ts'] and shift1['end_ts'] and shift2['start_ts']:
                if shift1['end_ts'] > shift2['start_ts']:
                    violations.append(Violation(
                        type=ViolationType.OVERLAP,
                        severity=Severity.HARD_BLOCK,
                        message=f"Shift overlap detected for driver {driver_id}",
                        driver_id=driver_id,
                        tour_instance_id=shift2['tour_instance_id'],
                        suggested_action="Remove one of the overlapping assignments",
                        details={
                            'shift1_end': str(shift1['end_ts']),
                            'shift2_start': str(shift2['start_ts']),
                        }
                    ))

    # Check rest violations (minimum 11h between shifts)
    for i in range(len(shifts) - 1):
        shift1 = shifts[i]
        shift2 = shifts[i + 1]

        if shift1['end_ts'] and shift2['start_ts']:
            rest_hours = (shift2['start_ts'] - shift1['end_ts']).total_seconds() / 3600

            if rest_hours < MIN_REST_HOURS:
                violations.append(Violation(
                    type=ViolationType.REST_VIOLATION,
                    severity=Severity.HARD_BLOCK,
                    message=f"Insufficient rest ({rest_hours:.1f}h < {MIN_REST_HOURS}h) for driver {driver_id}",
                    driver_id=driver_id,
                    tour_instance_id=shift2['tour_instance_id'],
                    suggested_action=f"Ensure at least {MIN_REST_HOURS}h rest between shifts",
                    details={
                        'rest_hours': rest_hours,
                        'required_hours': MIN_REST_HOURS,
                    }
                ))

    return violations


async def _check_pin_conflicts(
    conn: asyncpg.Connection,
    mutations: list,
    tenant_id: int,
) -> list[Violation]:
    """Check for conflicts with pinned assignments."""
    violations = []

    # Get tour instance IDs that we're trying to modify
    tour_ids = [m['tour_instance_id'] for m in mutations if m['op'] in ('unassign', 'move')]

    if not tour_ids:
        return violations

    # Check if any are pinned
    pinned = await conn.fetch("""
        SELECT
            a.tour_instance_id,
            a.driver_id,
            a.pin_reason
        FROM assignments a
        WHERE a.tour_instance_id = ANY($1)
          AND a.is_pinned = true
    """, tour_ids)

    for p in pinned:
        violations.append(Violation(
            type=ViolationType.PIN_CONFLICT,
            severity=Severity.HARD_BLOCK,
            message=f"Cannot modify pinned assignment (reason: {p['pin_reason'] or 'N/A'})",
            driver_id=p['driver_id'],
            tour_instance_id=p['tour_instance_id'],
            suggested_action="Unpin the assignment first or choose a different slot",
            details={
                'pin_reason': p['pin_reason'],
            }
        ))

    return violations


# =============================================================================
# FULL VALIDATION (Complete checks with parity guarantee)
# =============================================================================

async def validate_full(
    conn: asyncpg.Connection,
    session_id: str,
    tenant_id: int,
    site_id: int,
    plan_version_id: int,
) -> ValidationResult:
    """
    Full validation with parity guarantee.

    PARITY GUARANTEE: The validation result here MUST match what
    confirm() would produce. No fake green allowed.
    """
    # First run fast validation
    fast_result = await validate_fast(conn, session_id, tenant_id, site_id)

    if fast_result.hard_blocks > 0:
        # Already have hard blocks, no need to continue
        fast_result.mode = ValidationMode.FULL
        return fast_result

    violations = list(fast_result.violations)

    # Get all pending mutations
    mutations = await conn.fetch("""
        SELECT
            dm.mutation_id,
            dm.op,
            dm.tour_instance_id,
            dm.driver_id,
            dm.day
        FROM roster.draft_mutations dm
        WHERE dm.session_id = $1
          AND dm.status = 'PENDING'
        ORDER BY dm.sequence_no
    """, session_id)

    # Additional full validation checks

    # 1. Check driver hours (weekly limit)
    hours_violations = await _check_driver_hours(conn, mutations, tenant_id, site_id)
    violations.extend(hours_violations)

    # 2. Check skill compatibility
    skill_violations = await _check_skill_compatibility(conn, mutations, tenant_id)
    violations.extend(skill_violations)

    # 3. Compute parity hash (deterministic hash of validation state)
    parity_hash = await _compute_parity_hash(conn, session_id, violations)

    # Count by severity
    hard_blocks = sum(1 for v in violations if v.severity == Severity.HARD_BLOCK)
    soft_blocks = sum(1 for v in violations if v.severity == Severity.SOFT_BLOCK)

    return ValidationResult(
        is_valid=(hard_blocks == 0),
        mode=ValidationMode.FULL,
        hard_blocks=hard_blocks,
        soft_blocks=soft_blocks,
        violations=violations,
        parity_hash=parity_hash,
    )


async def _check_driver_hours(
    conn: asyncpg.Connection,
    mutations: list,
    tenant_id: int,
    site_id: int,
) -> list[Violation]:
    """Check if driver would exceed weekly hour limits."""
    violations = []

    # Group by driver
    driver_hours: dict[int, float] = {}

    for m in mutations:
        if m['op'] == 'assign' and m['driver_id']:
            driver_id = m['driver_id']

            # Get tour duration
            tour = await conn.fetchrow("""
                SELECT
                    EXTRACT(EPOCH FROM (end_ts - start_ts)) / 3600 as hours
                FROM tour_instances
                WHERE id = $1
            """, m['tour_instance_id'])

            if tour and tour['hours']:
                if driver_id not in driver_hours:
                    # Get existing hours for this week
                    existing = await conn.fetchval("""
                        SELECT COALESCE(SUM(
                            EXTRACT(EPOCH FROM (ti.end_ts - ti.start_ts)) / 3600
                        ), 0)
                        FROM assignments a
                        JOIN tour_instances ti ON ti.id = a.tour_instance_id
                        WHERE a.driver_id = $1
                          AND ti.site_id = $2
                    """, driver_id, site_id)
                    driver_hours[driver_id] = float(existing or 0)

                driver_hours[driver_id] += float(tour['hours'])

    # Check limits
    for driver_id, total_hours in driver_hours.items():
        if total_hours > MAX_WEEKLY_HOURS:
            violations.append(Violation(
                type=ViolationType.HOURS_EXCEEDED,
                severity=Severity.SOFT_BLOCK,
                message=f"Driver {driver_id} would exceed weekly hour limit ({total_hours:.1f}h > {MAX_WEEKLY_HOURS}h)",
                driver_id=driver_id,
                suggested_action="Reduce assignments or get management approval",
                details={
                    'total_hours': total_hours,
                    'limit': MAX_WEEKLY_HOURS,
                }
            ))

    return violations


async def _check_skill_compatibility(
    conn: asyncpg.Connection,
    mutations: list,
    tenant_id: int,
) -> list[Violation]:
    """Check if drivers have required skills for tours."""
    violations = []

    for m in mutations:
        if m['op'] == 'assign' and m['driver_id']:
            # Get tour requirements
            tour_skills = await conn.fetch("""
                SELECT skill_code
                FROM tour_skill_requirements
                WHERE tour_instance_id = $1
            """, m['tour_instance_id'])

            if not tour_skills:
                continue

            required = set(s['skill_code'] for s in tour_skills)

            # Get driver skills
            driver_skills = await conn.fetch("""
                SELECT skill_code
                FROM driver_skills
                WHERE driver_id = $1
            """, m['driver_id'])

            has_skills = set(s['skill_code'] for s in driver_skills)

            missing = required - has_skills
            if missing:
                violations.append(Violation(
                    type=ViolationType.SKILL_MISMATCH,
                    severity=Severity.SOFT_BLOCK,
                    message=f"Driver {m['driver_id']} missing skills: {', '.join(missing)}",
                    driver_id=m['driver_id'],
                    tour_instance_id=m['tour_instance_id'],
                    suggested_action="Assign a driver with required skills",
                    details={
                        'missing_skills': list(missing),
                        'required_skills': list(required),
                    }
                ))

    return violations


async def _compute_parity_hash(
    conn: asyncpg.Connection,
    session_id: str,
    violations: list[Violation],
) -> str:
    """
    Compute deterministic hash for parity guarantee.

    This hash MUST be the same when validate(full) and confirm() are called
    with the same draft state.
    """
    import hashlib
    import json

    # Get ordered mutations
    mutations = await conn.fetch("""
        SELECT
            mutation_id,
            op,
            tour_instance_id,
            driver_id,
            sequence_no
        FROM roster.draft_mutations
        WHERE session_id = $1
          AND status = 'PENDING'
        ORDER BY sequence_no
    """, session_id)

    # Build canonical representation
    canonical = {
        'session_id': session_id,
        'mutations': [
            {
                'id': str(m['mutation_id']),
                'op': m['op'],
                'tour': m['tour_instance_id'],
                'driver': m['driver_id'],
            }
            for m in mutations
        ],
        'violation_count': len(violations),
        'hard_blocks': sum(1 for v in violations if v.severity == Severity.HARD_BLOCK),
    }

    canonical_json = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(canonical_json.encode()).hexdigest()[:16]


# =============================================================================
# VALIDATION API
# =============================================================================

async def validate_draft(
    conn: asyncpg.Connection,
    session_id: str,
    mode: ValidationMode,
    tenant_id: int,
    site_id: int,
    plan_version_id: Optional[int] = None,
) -> ValidationResult:
    """
    Main validation entry point.

    Args:
        conn: Database connection
        session_id: Repair session ID
        mode: Validation mode (none, fast, full)
        tenant_id: Tenant ID for RLS
        site_id: Site ID
        plan_version_id: Optional plan version for full validation

    Returns:
        ValidationResult with violations and parity hash
    """
    if mode == ValidationMode.NONE:
        return ValidationResult(
            is_valid=True,  # NOT VALIDATED - client must show GREY status
            mode=ValidationMode.NONE,
            hard_blocks=0,
            soft_blocks=0,
            violations=[],
        )

    if mode == ValidationMode.FAST:
        return await validate_fast(conn, session_id, tenant_id, site_id)

    if mode == ValidationMode.FULL:
        if not plan_version_id:
            # Get plan version from session
            session = await conn.fetchrow("""
                SELECT plan_version_id
                FROM roster.repair_sessions
                WHERE session_id = $1
            """, session_id)
            plan_version_id = session['plan_version_id'] if session else None

        return await validate_full(conn, session_id, tenant_id, site_id, plan_version_id)

    raise ValueError(f"Unknown validation mode: {mode}")
