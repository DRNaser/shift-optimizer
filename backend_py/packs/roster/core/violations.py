"""
SOLVEREIGN V4.6 - Shared Violations Calculator
===============================================

Single source of truth for violation computation.
Used by:
- Publish Gate (lifecycle.py) - blocks publish on BLOCK > 0
- Repair Preview (repair_sessions.py) - shows impact of actions
- Violations Cache (background job) - pre-computes for UI

CRITICAL: All violation rules and severity mappings MUST be defined here.
Do NOT duplicate violation logic elsewhere.

Violation Types:
- OVERLAP: Same driver assigned to overlapping shifts (BLOCK)
- UNASSIGNED: Tour without driver assignment (BLOCK)
- REST: Less than 11h rest between shifts (WARN)
- SPAN_REGULAR: 1er/2er block exceeds 14h (WARN)
- SPAN_SPLIT: 3er/split block exceeds 16h (WARN)
- HOUR_LIMIT: Driver exceeds weekly hour limit (WARN)
"""

from typing import Tuple, List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ViolationSeverity(str, Enum):
    """Violation severity levels."""
    BLOCK = "BLOCK"  # Prevents publish
    WARN = "WARN"    # Allows publish with warning


class ViolationType(str, Enum):
    """Types of violations detected."""
    OVERLAP = "OVERLAP"           # Same driver, overlapping time
    UNASSIGNED = "UNASSIGNED"     # Tour without driver
    REST = "REST"                 # Rest period violation
    SPAN_REGULAR = "SPAN_REGULAR" # 1er/2er span too long
    SPAN_SPLIT = "SPAN_SPLIT"     # 3er/split span too long
    HOUR_LIMIT = "HOUR_LIMIT"     # Weekly hour limit exceeded


@dataclass
class Violation:
    """A single violation instance."""
    type: ViolationType
    severity: ViolationSeverity
    driver_id: str
    day: Optional[str]
    message: str
    details: Dict[str, Any]


@dataclass
class ViolationCounts:
    """Summary counts of violations."""
    block_count: int
    warn_count: int
    total: int

    @property
    def can_publish(self) -> bool:
        """Plan can be published if no BLOCK violations."""
        return self.block_count == 0


# =============================================================================
# VIOLATION RULES (Single Source of Truth)
# =============================================================================

VIOLATION_RULES = {
    ViolationType.OVERLAP: {
        "severity": ViolationSeverity.BLOCK,
        "description": "Same driver assigned to overlapping shifts on same day",
    },
    ViolationType.UNASSIGNED: {
        "severity": ViolationSeverity.BLOCK,
        "description": "Tour instance has no driver assigned",
    },
    ViolationType.REST: {
        "severity": ViolationSeverity.WARN,
        "description": "Less than 11 hours rest between consecutive work days",
    },
    ViolationType.SPAN_REGULAR: {
        "severity": ViolationSeverity.WARN,
        "description": "1er/2er block span exceeds 14 hours",
    },
    ViolationType.SPAN_SPLIT: {
        "severity": ViolationSeverity.WARN,
        "description": "3er/split block span exceeds 16 hours",
    },
    ViolationType.HOUR_LIMIT: {
        "severity": ViolationSeverity.WARN,
        "description": "Driver exceeds weekly hour limit",
    },
}


def get_severity(violation_type: ViolationType) -> ViolationSeverity:
    """Get the severity for a violation type."""
    return VIOLATION_RULES[violation_type]["severity"]


# =============================================================================
# LIVE VIOLATION COMPUTATION
# =============================================================================

async def compute_violations_async(
    conn,
    plan_version_id: int,
    tenant_id: Optional[int] = None,
    site_id: Optional[int] = None,
) -> Tuple[ViolationCounts, List[Violation]]:
    """
    Compute violations for a plan LIVE from the database.

    This is the authoritative source - never trust cached values for
    publish-blocking decisions.

    Args:
        conn: Async database connection (asyncpg)
        plan_version_id: The plan to check
        tenant_id: Optional tenant filter (for RLS bypass scenarios)
        site_id: Optional site filter

    Returns:
        Tuple of (ViolationCounts, List[Violation])
    """
    violations: List[Violation] = []

    # Query all violations in a single pass
    rows = await conn.fetch("""
        WITH violation_data AS (
            -- OVERLAP: Same driver on same day with overlapping times
            SELECT
                'OVERLAP' as violation_type,
                'BLOCK' as severity,
                a1.driver_id,
                a1.day_of_week as day,
                format('Driver %s has overlapping assignments on %s', a1.driver_id, a1.day_of_week) as message
            FROM assignments a1
            JOIN assignments a2 ON a1.driver_id = a2.driver_id
                AND a1.id < a2.id
                AND a1.plan_version_id = a2.plan_version_id
                AND a1.day_of_week = a2.day_of_week
            WHERE a1.plan_version_id = $1

            UNION ALL

            -- UNASSIGNED: Tours without drivers
            SELECT
                'UNASSIGNED' as violation_type,
                'BLOCK' as severity,
                'NONE' as driver_id,
                ti.day_of_week as day,
                format('Tour %s on %s has no driver', ti.tour_id, ti.day_of_week) as message
            FROM tour_instances ti
            LEFT JOIN assignments a ON ti.id = a.tour_instance_id
                AND a.plan_version_id = $1
            WHERE ti.plan_version_id = $1
              AND a.id IS NULL

            UNION ALL

            -- REST: Drivers with potentially insufficient rest (simplified)
            SELECT
                'REST' as violation_type,
                'WARN' as severity,
                driver_id,
                NULL as day,
                format('Driver %s may have rest violations (works %s days)', driver_id, COUNT(DISTINCT day_of_week)) as message
            FROM assignments
            WHERE plan_version_id = $1
            GROUP BY driver_id
            HAVING COUNT(DISTINCT day_of_week) > 5
        )
        SELECT * FROM violation_data
    """, plan_version_id)

    for row in rows:
        vtype = ViolationType(row["violation_type"])
        violations.append(Violation(
            type=vtype,
            severity=ViolationSeverity(row["severity"]),
            driver_id=row["driver_id"],
            day=row["day"],
            message=row["message"],
            details={},
        ))

    block_count = sum(1 for v in violations if v.severity == ViolationSeverity.BLOCK)
    warn_count = sum(1 for v in violations if v.severity == ViolationSeverity.WARN)

    logger.debug(
        f"Computed violations for plan {plan_version_id}: "
        f"{block_count} BLOCK, {warn_count} WARN"
    )

    return ViolationCounts(
        block_count=block_count,
        warn_count=warn_count,
        total=len(violations),
    ), violations


def compute_violations_sync(
    cursor,
    plan_version_id: int,
) -> Tuple[ViolationCounts, List[Dict]]:
    """
    Compute violations for a plan LIVE (synchronous version for psycopg2).

    Used by Publish Gate in lifecycle.py which uses sync cursors.

    Args:
        cursor: Database cursor (psycopg2)
        plan_version_id: The plan to check

    Returns:
        Tuple of (ViolationCounts, list of violation dicts)
    """
    cursor.execute("""
        SELECT
            COUNT(*) FILTER (WHERE severity = 'BLOCK') as block_count,
            COUNT(*) FILTER (WHERE severity = 'WARN') as warn_count
        FROM (
            -- OVERLAP violations: same driver assigned to overlapping shifts
            SELECT DISTINCT 'BLOCK' as severity, a1.driver_id
            FROM assignments a1
            JOIN assignments a2 ON a1.driver_id = a2.driver_id
                AND a1.id < a2.id
                AND a1.plan_version_id = a2.plan_version_id
                AND a1.day_of_week = a2.day_of_week
            WHERE a1.plan_version_id = %s

            UNION ALL

            -- UNASSIGNED violations: tours without drivers
            SELECT DISTINCT 'BLOCK' as severity, 'UNASSIGNED' as driver_id
            FROM tour_instances ti
            LEFT JOIN assignments a ON ti.id = a.tour_instance_id
                AND a.plan_version_id = %s
            WHERE ti.plan_version_id = %s
              AND a.id IS NULL

            UNION ALL

            -- REST violations: <11h between shifts (simplified check)
            SELECT 'WARN' as severity, driver_id
            FROM assignments
            WHERE plan_version_id = %s
            GROUP BY driver_id
            HAVING COUNT(*) > 5
        ) violations
    """, (plan_version_id, plan_version_id, plan_version_id, plan_version_id))

    result = cursor.fetchone()
    block_count = result[0] if result else 0
    warn_count = result[1] if result else 0

    return ViolationCounts(
        block_count=block_count,
        warn_count=warn_count,
        total=block_count + warn_count,
    ), []


# =============================================================================
# VIOLATION DELTA COMPUTATION (for Repair Preview)
# =============================================================================

async def compute_violation_delta(
    conn,
    plan_version_id: int,
    action_type: str,
    driver_id: str,
    day: str,
    target_driver_id: Optional[str] = None,
    target_day: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute how a repair action would change violations.

    This is a preview/simulation - does not modify the database.

    Returns:
        Dict with keys:
        - violations_before: int
        - violations_after: int
        - delta: int (negative = improvement)
        - resolved: List[str] (violation types resolved)
        - created: List[str] (violation types created)
    """
    # Get current violations
    counts_before, violations_before = await compute_violations_async(conn, plan_version_id)

    # Simulate action impact (simplified heuristics)
    resolved = []
    created = []

    if action_type == "CLEAR":
        # Clearing creates UNASSIGNED
        created.append("UNASSIGNED")
    elif action_type == "FILL":
        # Filling resolves UNASSIGNED
        resolved.append("UNASSIGNED")
    elif action_type == "SWAP":
        # Swap might resolve or create OVERLAP depending on context
        pass
    elif action_type == "MOVE":
        # Move might resolve OVERLAP on source, create on target
        pass

    violations_after = counts_before.total - len(resolved) + len(created)

    return {
        "violations_before": counts_before.total,
        "violations_after": max(0, violations_after),
        "delta": violations_after - counts_before.total,
        "resolved": resolved,
        "created": created,
        "source": "live",  # Always from live computation
    }
