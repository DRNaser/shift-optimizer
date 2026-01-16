"""
SOLVEREIGN V3.3b - Driver Model

=============================================================================
Driver Pool + Availability + Repair Support
=============================================================================

Key Design Decisions:
1. external_ref is stable ID (for imports), id is internal SERIAL
2. Availability is date-based (not timestamp), timezone = Europe/Vienna
3. Default availability = AVAILABLE (if no row exists)
4. All queries ORDER BY stable keys for determinism
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class AvailabilityStatus(Enum):
    """Driver availability status."""
    AVAILABLE = "AVAILABLE"     # Can be assigned
    SICK = "SICK"               # Sick leave (primary repair trigger)
    VACATION = "VACATION"       # Planned absence
    BLOCKED = "BLOCKED"         # Other unavailability


class RepairStrategy(Enum):
    """Repair algorithm strategy."""
    MIN_CHURN = "MIN_CHURN"     # Minimize reassignments (default)
    MIN_HOURS = "MIN_HOURS"     # Minimize total driver hours
    BALANCED = "BALANCED"       # Balance load across drivers


class RepairStatus(Enum):
    """Repair operation status."""
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Driver:
    """Driver record."""
    id: int
    tenant_id: str
    external_ref: str
    display_name: Optional[str] = None
    home_depot: Optional[str] = None
    is_active: bool = True
    max_weekly_hours: Decimal = Decimal("55.0")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class DriverSkill:
    """Driver skill/qualification."""
    id: int
    tenant_id: str
    driver_id: int
    skill_code: str
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None


@dataclass
class DriverAvailability:
    """Driver availability for a specific date."""
    id: int
    tenant_id: str
    driver_id: int
    date: date
    status: AvailabilityStatus
    note: Optional[str] = None
    source: Optional[str] = None
    reported_at: Optional[datetime] = None
    reported_by: Optional[str] = None


@dataclass
class RepairRequest:
    """Request to repair a plan due to driver absences."""
    plan_version_id: int
    absent_driver_ids: List[int]
    respect_freeze: bool = True
    strategy: RepairStrategy = RepairStrategy.MIN_CHURN
    time_budget_seconds: int = 60
    seed: Optional[int] = None
    idempotency_key: Optional[str] = None


@dataclass
class RepairResult:
    """Result of a repair operation."""
    repair_log_id: int
    status: RepairStatus
    new_plan_version_id: Optional[int] = None
    tours_reassigned: int = 0
    drivers_affected: int = 0
    churn_rate: float = 0.0
    freeze_violations: int = 0
    execution_time_ms: int = 0
    error_message: Optional[str] = None
    audit_results: Optional[dict] = None


@dataclass
class EligibleDriver:
    """Driver eligible for assignment."""
    driver_id: int
    external_ref: str
    home_depot: Optional[str]
    max_weekly_hours: Decimal
    skills: List[str] = field(default_factory=list)
    current_hours: float = 0.0  # Hours already assigned this week


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def get_drivers(
    tenant_id: str,
    active_only: bool = True,
    depot: Optional[str] = None
) -> List[Driver]:
    """
    Get drivers for a tenant.

    Args:
        tenant_id: Tenant UUID
        active_only: If True, only return active drivers
        depot: Filter by home depot

    Returns:
        List of Driver objects (ORDER BY id for determinism)
    """
    from . import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT id, tenant_id, external_ref, display_name, home_depot,
                       is_active, max_weekly_hours, created_at, updated_at
                FROM drivers
                WHERE tenant_id = %s
            """
            params = [tenant_id]

            if active_only:
                query += " AND is_active = TRUE"

            if depot:
                query += " AND home_depot = %s"
                params.append(depot)

            query += " ORDER BY id"  # Deterministic!

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                Driver(
                    id=row['id'],
                    tenant_id=str(row['tenant_id']),
                    external_ref=row['external_ref'],
                    display_name=row['display_name'],
                    home_depot=row['home_depot'],
                    is_active=row['is_active'],
                    max_weekly_hours=row['max_weekly_hours'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
                for row in rows
            ]


def get_driver_availability(
    tenant_id: str,
    driver_id: int,
    from_date: date,
    to_date: date
) -> List[DriverAvailability]:
    """
    Get availability records for a driver in date range.

    Returns empty list for dates with no record (defaults to AVAILABLE).
    """
    from . import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, tenant_id, driver_id, date, status, note,
                       source, reported_at, reported_by
                FROM driver_availability
                WHERE tenant_id = %s
                  AND driver_id = %s
                  AND date >= %s
                  AND date <= %s
                ORDER BY date
            """, (tenant_id, driver_id, from_date, to_date))

            return [
                DriverAvailability(
                    id=row['id'],
                    tenant_id=str(row['tenant_id']),
                    driver_id=row['driver_id'],
                    date=row['date'],
                    status=AvailabilityStatus(row['status']),
                    note=row['note'],
                    source=row['source'],
                    reported_at=row['reported_at'],
                    reported_by=row['reported_by']
                )
                for row in cur.fetchall()
            ]


def set_driver_availability(
    tenant_id: str,
    driver_id: int,
    availability_date: date,
    status: AvailabilityStatus,
    note: Optional[str] = None,
    source: str = "api",
    reported_by: Optional[str] = None
) -> DriverAvailability:
    """
    Set availability for a driver on a specific date.

    Uses UPSERT to handle updates.
    """
    from . import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO driver_availability
                    (tenant_id, driver_id, date, status, note, source, reported_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, driver_id, date) DO UPDATE SET
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    source = EXCLUDED.source,
                    reported_at = NOW(),
                    reported_by = EXCLUDED.reported_by
                RETURNING id, reported_at
            """, (tenant_id, driver_id, availability_date, status.value,
                  note, source, reported_by))

            row = cur.fetchone()
            conn.commit()

            return DriverAvailability(
                id=row['id'],
                tenant_id=tenant_id,
                driver_id=driver_id,
                date=availability_date,
                status=status,
                note=note,
                source=source,
                reported_at=row['reported_at'],
                reported_by=reported_by
            )


def get_eligible_drivers_for_date(
    tenant_id: str,
    target_date: date,
    exclude_driver_ids: Optional[List[int]] = None
) -> List[EligibleDriver]:
    """
    Get drivers who are AVAILABLE on the given date.

    Args:
        tenant_id: Tenant UUID
        target_date: Date to check availability
        exclude_driver_ids: Optional list of driver IDs to exclude

    Returns:
        List of EligibleDriver (ORDER BY driver_id for determinism)
    """
    from . import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Use the helper function for deterministic results
            cur.execute("""
                SELECT driver_id, external_ref, home_depot, max_weekly_hours
                FROM get_eligible_drivers(%s, %s)
            """, (tenant_id, target_date))

            rows = cur.fetchall()

            # Apply exclusions
            exclude_set = set(exclude_driver_ids or [])

            result = []
            for row in rows:
                if row['driver_id'] in exclude_set:
                    continue

                # Get skills for this driver
                cur.execute("""
                    SELECT skill_code
                    FROM driver_skills
                    WHERE driver_id = %s
                      AND (valid_from IS NULL OR valid_from <= %s)
                      AND (valid_until IS NULL OR valid_until >= %s)
                    ORDER BY skill_code
                """, (row['driver_id'], target_date, target_date))

                skills = [r['skill_code'] for r in cur.fetchall()]

                result.append(EligibleDriver(
                    driver_id=row['driver_id'],
                    external_ref=row['external_ref'],
                    home_depot=row['home_depot'],
                    max_weekly_hours=row['max_weekly_hours'],
                    skills=skills
                ))

            return result


def get_eligible_drivers_for_week(
    tenant_id: str,
    week_start: date,
    exclude_driver_ids: Optional[List[int]] = None
) -> List[EligibleDriver]:
    """
    Get drivers who are AVAILABLE for all 7 days of the week.

    Args:
        tenant_id: Tenant UUID
        week_start: Monday of the week
        exclude_driver_ids: Optional list of driver IDs to exclude

    Returns:
        List of EligibleDriver (ORDER BY driver_id for determinism)
    """
    from . import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT driver_id, external_ref, home_depot, max_weekly_hours
                FROM get_eligible_drivers_week(%s, %s)
            """, (tenant_id, week_start))

            rows = cur.fetchall()
            exclude_set = set(exclude_driver_ids or [])

            result = []
            for row in rows:
                if row['driver_id'] in exclude_set:
                    continue

                result.append(EligibleDriver(
                    driver_id=row['driver_id'],
                    external_ref=row['external_ref'],
                    home_depot=row['home_depot'],
                    max_weekly_hours=row['max_weekly_hours'],
                    skills=[]  # Would need separate query if needed
                ))

            return result


def create_driver(
    tenant_id: str,
    external_ref: str,
    display_name: Optional[str] = None,
    home_depot: Optional[str] = None,
    max_weekly_hours: Decimal = Decimal("55.0")
) -> Driver:
    """Create a new driver."""
    from . import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO drivers
                    (tenant_id, external_ref, display_name, home_depot, max_weekly_hours)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at, updated_at
            """, (tenant_id, external_ref, display_name, home_depot, max_weekly_hours))

            row = cur.fetchone()
            conn.commit()

            return Driver(
                id=row['id'],
                tenant_id=tenant_id,
                external_ref=external_ref,
                display_name=display_name,
                home_depot=home_depot,
                max_weekly_hours=max_weekly_hours,
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )


def bulk_create_drivers(
    tenant_id: str,
    drivers: List[dict]
) -> List[Driver]:
    """
    Bulk create drivers (UPSERT by external_ref).

    Args:
        tenant_id: Tenant UUID
        drivers: List of dicts with keys: external_ref, display_name?, home_depot?, max_weekly_hours?

    Returns:
        List of created/updated Driver objects
    """
    from . import db

    if not drivers:
        return []

    created = []
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            for d in drivers:
                cur.execute("""
                    INSERT INTO drivers
                        (tenant_id, external_ref, display_name, home_depot, max_weekly_hours)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, external_ref) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        home_depot = EXCLUDED.home_depot,
                        max_weekly_hours = EXCLUDED.max_weekly_hours,
                        updated_at = NOW()
                    RETURNING id, created_at, updated_at
                """, (
                    tenant_id,
                    d['external_ref'],
                    d.get('display_name'),
                    d.get('home_depot'),
                    d.get('max_weekly_hours', Decimal("55.0"))
                ))

                row = cur.fetchone()
                created.append(Driver(
                    id=row['id'],
                    tenant_id=tenant_id,
                    external_ref=d['external_ref'],
                    display_name=d.get('display_name'),
                    home_depot=d.get('home_depot'),
                    max_weekly_hours=d.get('max_weekly_hours', Decimal("55.0")),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                ))

            conn.commit()

    return created


# =============================================================================
# REPAIR LOG OPERATIONS
# =============================================================================

def create_repair_log(
    tenant_id: str,
    request: RepairRequest,
    requested_by: Optional[str] = None
) -> int:
    """Create a repair log entry (PENDING status)."""
    from . import db
    import json

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO repair_log
                    (tenant_id, parent_plan_id, absent_driver_ids, respect_freeze,
                     strategy, time_budget_ms, seed, status, idempotency_key, requested_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                tenant_id,
                request.plan_version_id,
                json.dumps(request.absent_driver_ids),
                request.respect_freeze,
                request.strategy.value,
                request.time_budget_seconds * 1000,
                request.seed,
                RepairStatus.PENDING.value,
                request.idempotency_key,
                requested_by
            ))

            row = cur.fetchone()
            conn.commit()
            return row['id']


def update_repair_log(
    repair_log_id: int,
    result: RepairResult
) -> None:
    """Update repair log with result."""
    from . import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE repair_log SET
                    result_plan_id = %s,
                    status = %s,
                    error_message = %s,
                    tours_reassigned = %s,
                    drivers_affected = %s,
                    churn_rate = %s,
                    freeze_violations = %s,
                    execution_time_ms = %s,
                    completed_at = NOW()
                WHERE id = %s
            """, (
                result.new_plan_version_id,
                result.status.value,
                result.error_message,
                result.tours_reassigned,
                result.drivers_affected,
                result.churn_rate,
                result.freeze_violations,
                result.execution_time_ms,
                repair_log_id
            ))
            conn.commit()


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_driver_ids_exist(
    tenant_id: str,
    driver_ids: List[int]
) -> List[int]:
    """
    Validate that all driver IDs exist and belong to tenant.

    Returns:
        List of invalid driver IDs (empty if all valid)
    """
    from . import db

    if not driver_ids:
        return []

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM drivers
                WHERE tenant_id = %s AND id = ANY(%s)
            """, (tenant_id, driver_ids))

            found = {row['id'] for row in cur.fetchall()}
            return [d for d in driver_ids if d not in found]


def check_drivers_assigned_to_plan(
    plan_version_id: int,
    driver_ids: List[int]
) -> List[int]:
    """
    Check which of the given driver IDs have assignments in the plan.

    Returns:
        List of driver IDs that have assignments
    """
    from . import db

    if not driver_ids:
        return []

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Check real_driver_id first
            cur.execute("""
                SELECT DISTINCT real_driver_id
                FROM assignments
                WHERE plan_version_id = %s
                  AND real_driver_id = ANY(%s)
            """, (plan_version_id, driver_ids))

            return [row['real_driver_id'] for row in cur.fetchall()]
