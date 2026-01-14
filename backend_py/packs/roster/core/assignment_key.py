"""
SOLVEREIGN V4.6 - Deterministic Assignment Key
===============================================

Generates stable keys for assignments that survive:
- Plan rebuilds
- Repair actions (SWAP/MOVE/FILL)
- Re-solving with same inputs

CRITICAL: Pin lookups MUST use this key, not database IDs.
Database assignment IDs change on every solve. This key doesn't.

Key Format: hash(site_id, driver_id, day, shift_start, shift_end, service_code, [tour_id])

For blocks (2er/3er):
- Key is computed from the FIRST tour in the block
- All tours in a block share the same pin
"""

import hashlib
from typing import Optional
from dataclasses import dataclass


@dataclass
class AssignmentKeyComponents:
    """Components used to build a deterministic assignment key."""
    driver_id: str
    day: str  # mon/tue/wed/thu/fri/sat/sun or ISO date
    shift_start: str  # HH:MM format
    shift_end: Optional[str] = None  # HH:MM format (for collision resistance)
    service_code: str = "1er"  # e.g., "1er", "2er", "3er"
    site_id: int = 0
    tour_id: Optional[str] = None  # Optional: specific tour identifier


def compute_assignment_key(
    driver_id: str,
    day: str,
    shift_start: str,
    service_code: str,
    site_id: int,
    shift_end: Optional[str] = None,
    tour_id: Optional[str] = None,
) -> str:
    """
    Compute a deterministic, stable key for an assignment.

    This key survives:
    - Plan re-solves (same input = same key)
    - Repair actions that move assignments
    - Database migrations

    Args:
        driver_id: The driver identifier (e.g., "D001")
        day: Day of week (e.g., "mon") or ISO date
        shift_start: Shift start time in HH:MM format
        service_code: Block type (e.g., "1er", "2er", "3er")
        site_id: Site identifier
        shift_end: Shift end time in HH:MM format (for collision resistance)
        tour_id: Optional specific tour ID

    Returns:
        32-character hex string (SHA-256 truncated)

    Example:
        >>> compute_assignment_key("D001", "mon", "06:00", "2er", 10, "14:00")
        'a1b2c3d4e5f6...'
    """
    # Build canonical string (order matters!)
    components = [
        str(site_id),
        str(driver_id).upper(),
        str(day).lower(),
        str(shift_start),
    ]

    # Include shift_end for collision resistance (two shifts same start, different end)
    if shift_end:
        components.append(str(shift_end))

    components.append(str(service_code).lower())

    if tour_id:
        components.append(str(tour_id))

    canonical = "|".join(components)

    # SHA-256, truncated to 32 chars for readability
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def compute_assignment_key_from_row(row: dict, site_id: int) -> str:
    """
    Compute assignment key from a database row.

    Expects row to have: driver_id, day_of_week, shift_start, shift_end, service_code

    Args:
        row: Dictionary with assignment data
        site_id: Site identifier

    Returns:
        32-character assignment key
    """
    return compute_assignment_key(
        driver_id=row.get("driver_id", ""),
        day=row.get("day_of_week", row.get("day", "")),
        shift_start=row.get("shift_start", row.get("start_time", "00:00")),
        service_code=row.get("service_code", row.get("block_type", "1er")),
        site_id=site_id,
        shift_end=row.get("shift_end", row.get("end_time")),  # Collision resistance
        tour_id=row.get("tour_id"),
    )


def compute_pin_lookup_key(
    driver_id: str,
    day: str,
    tour_instance_id: Optional[int] = None,
) -> str:
    """
    Compute a simpler key for pin lookups.

    This is used when we don't have full shift details,
    just driver + day (+ optionally tour instance).

    Args:
        driver_id: The driver identifier
        day: Day of week or ISO date
        tour_instance_id: Optional tour instance ID

    Returns:
        32-character hex string
    """
    components = [
        str(driver_id).upper(),
        str(day).lower(),
    ]

    if tour_instance_id:
        components.append(str(tour_instance_id))

    canonical = "|".join(components)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


# =============================================================================
# PIN MIGRATION HELPER
# =============================================================================

def migrate_pins_to_assignment_keys(conn, site_id: int) -> int:
    """
    Backfill assignment_key column for existing pins.

    This is a one-time migration helper. Call once per site after
    adding the assignment_key column.

    Args:
        conn: Database connection (sync)
        site_id: Site to migrate

    Returns:
        Number of pins updated
    """
    cursor = conn.cursor()

    # Get pins without assignment_key
    cursor.execute("""
        SELECT p.id, p.driver_id, p.day, p.tour_instance_id,
               ti.shift_start, ti.service_code, ti.tour_id
        FROM roster.pins p
        LEFT JOIN tour_instances ti ON p.tour_instance_id = ti.id
        WHERE p.site_id = %s
          AND p.assignment_key IS NULL
    """, (site_id,))

    pins = cursor.fetchall()
    updated = 0

    for pin in pins:
        pin_id, driver_id, day, tour_instance_id, shift_start, service_code, tour_id = pin

        if shift_start and service_code:
            # Full key with shift details
            key = compute_assignment_key(
                driver_id=driver_id,
                day=day,
                shift_start=str(shift_start),
                service_code=service_code,
                site_id=site_id,
                tour_id=tour_id,
            )
        else:
            # Simple key (driver + day)
            key = compute_pin_lookup_key(driver_id, day, tour_instance_id)

        cursor.execute("""
            UPDATE roster.pins
            SET assignment_key = %s
            WHERE id = %s
        """, (key, pin_id))

        updated += 1

    conn.commit()
    return updated
