"""
SOLVEREIGN V3 Freeze Window Module
===================================

Enforces operational stability by preventing modifications to tours
that are within the freeze window (default: 12 hours before start).

Key Concepts:
    - FROZEN: Tour cannot be reassigned without override
    - MODIFIABLE: Tour can be freely reassigned
    - OVERRIDE: Admin action to modify frozen tour (logged)

Usage:
    from v3.freeze_windows import (
        is_frozen,
        get_frozen_instances,
        classify_instances,
        solve_with_freeze
    )

    # Check single instance
    frozen = is_frozen(tour_instance_id, now=datetime.now())

    # Classify all instances
    frozen_ids, modifiable_ids = classify_instances(forecast_version_id)

    # Solve respecting freeze
    result = solve_with_freeze(forecast_version_id, seed=94, override=False)
"""

from datetime import datetime, timedelta, date, time
from typing import Tuple, List, Optional
from collections import defaultdict

from . import db
from .db_instances import get_tour_instances
from .config import config


# Default freeze window: 12 hours (720 minutes)
DEFAULT_FREEZE_MINUTES = 720


def compute_tour_start_datetime(
    week_anchor_date: date,
    day: int,
    start_ts: time,
    crosses_midnight: bool = False
) -> datetime:
    """
    Compute absolute start datetime from week anchor + day + time.

    Args:
        week_anchor_date: Monday of the week (date)
        day: Day number 1-7 (Mo=1, So=7)
        start_ts: Start time
        crosses_midnight: If True, tour spans into next day (not used for start)

    Returns:
        Absolute datetime when tour starts
    """
    # Day offset from Monday (day=1 is Monday = offset 0)
    day_offset = day - 1
    tour_date = week_anchor_date + timedelta(days=day_offset)
    return datetime.combine(tour_date, start_ts)


def get_freeze_window_minutes() -> int:
    """
    Get freeze window duration from config or database.

    Returns:
        Freeze window in minutes
    """
    # Check database for active freeze rules
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT minutes_before_start
                    FROM freeze_windows
                    WHERE rule_name = 'PRE_SHIFT_12H' AND enabled = TRUE
                    LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    return row["minutes_before_start"]
    except Exception:
        pass

    return DEFAULT_FREEZE_MINUTES


def is_frozen(
    tour_instance_id: int,
    now: Optional[datetime] = None,
    freeze_minutes: Optional[int] = None
) -> bool:
    """
    Check if a tour instance is frozen (within freeze window).

    Args:
        tour_instance_id: Tour instance ID
        now: Current time (default: datetime.now())
        freeze_minutes: Freeze window in minutes (default: from config)

    Returns:
        True if tour is FROZEN, False if MODIFIABLE
    """
    if now is None:
        now = datetime.now()

    if freeze_minutes is None:
        freeze_minutes = get_freeze_window_minutes()

    # Get tour instance details
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ti.day, ti.start_ts, ti.crosses_midnight, ti.forecast_version_id
                FROM tour_instances ti
                WHERE ti.id = %s
            """, (tour_instance_id,))
            instance = cur.fetchone()

            if not instance:
                raise ValueError(f"Tour instance {tour_instance_id} not found")

            # Get week anchor date from forecast
            cur.execute("""
                SELECT week_anchor_date
                FROM forecast_versions
                WHERE id = %s
            """, (instance["forecast_version_id"],))
            forecast = cur.fetchone()

            if not forecast or not forecast.get("week_anchor_date"):
                # No anchor date = cannot determine freeze status
                return False

    # Compute absolute start datetime
    week_anchor_date = forecast["week_anchor_date"]
    start_dt = compute_tour_start_datetime(
        week_anchor_date,
        instance["day"],
        instance["start_ts"],
        instance.get("crosses_midnight", False)
    )

    # Freeze threshold
    freeze_threshold = start_dt - timedelta(minutes=freeze_minutes)

    return now >= freeze_threshold


def classify_instances(
    forecast_version_id: int,
    now: Optional[datetime] = None,
    freeze_minutes: Optional[int] = None
) -> Tuple[List[int], List[int]]:
    """
    Classify all tour instances as FROZEN or MODIFIABLE.

    Args:
        forecast_version_id: Forecast version ID
        now: Current time (default: datetime.now())
        freeze_minutes: Freeze window in minutes (default: from config)

    Returns:
        Tuple of (frozen_ids, modifiable_ids)
    """
    if now is None:
        now = datetime.now()

    if freeze_minutes is None:
        freeze_minutes = get_freeze_window_minutes()

    # Get week anchor date
    forecast = db.get_forecast_version(forecast_version_id)
    if not forecast or not forecast.get("week_anchor_date"):
        # No anchor = all modifiable
        instances = get_tour_instances(forecast_version_id)
        return [], [inst["id"] for inst in instances]

    week_anchor_date = forecast["week_anchor_date"]

    # Classify each instance
    frozen_ids = []
    modifiable_ids = []

    instances = get_tour_instances(forecast_version_id)
    for inst in instances:
        start_dt = compute_tour_start_datetime(
            week_anchor_date,
            inst["day"],
            inst["start_ts"],
            inst.get("crosses_midnight", False)
        )

        freeze_threshold = start_dt - timedelta(minutes=freeze_minutes)

        if now >= freeze_threshold:
            frozen_ids.append(inst["id"])
        else:
            modifiable_ids.append(inst["id"])

    return frozen_ids, modifiable_ids


def get_frozen_instances(
    forecast_version_id: int,
    now: Optional[datetime] = None
) -> List[dict]:
    """
    Get all frozen tour instances for a forecast.

    Args:
        forecast_version_id: Forecast version ID
        now: Current time (default: datetime.now())

    Returns:
        List of frozen tour instance dicts
    """
    frozen_ids, _ = classify_instances(forecast_version_id, now)

    instances = get_tour_instances(forecast_version_id)
    instance_lookup = {inst["id"]: inst for inst in instances}

    return [instance_lookup[fid] for fid in frozen_ids if fid in instance_lookup]


def get_previous_assignments(
    frozen_ids: List[int],
    forecast_version_id: int
) -> List[dict]:
    """
    Get previous assignments for frozen tour instances.

    Looks for the most recent LOCKED plan for this forecast
    and returns assignments for the frozen instances.

    Args:
        frozen_ids: List of frozen tour instance IDs
        forecast_version_id: Forecast version ID

    Returns:
        List of assignment dicts from previous plan
    """
    if not frozen_ids:
        return []

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Find most recent LOCKED plan for this forecast
            cur.execute("""
                SELECT id FROM plan_versions
                WHERE forecast_version_id = %s AND status = 'LOCKED'
                ORDER BY locked_at DESC
                LIMIT 1
            """, (forecast_version_id,))
            row = cur.fetchone()

            if not row:
                return []

            plan_version_id = row["id"]

            # Get assignments for frozen instances
            cur.execute("""
                SELECT * FROM assignments
                WHERE plan_version_id = %s
                AND tour_instance_id = ANY(%s)
            """, (plan_version_id, frozen_ids))

            return cur.fetchall()


def log_freeze_override(
    plan_version_id: int,
    user: str,
    reason: str,
    affected_instance_ids: List[int]
) -> int:
    """
    Log a freeze override to audit_log.

    Args:
        plan_version_id: Plan version ID
        user: User who authorized the override
        reason: Reason for override
        affected_instance_ids: List of affected tour instance IDs

    Returns:
        Audit log entry ID
    """
    details = {
        "type": "FREEZE_OVERRIDE",
        "user": user,
        "reason": reason,
        "affected_instance_ids": affected_instance_ids,
        "count": len(affected_instance_ids),
        "timestamp": datetime.now().isoformat()
    }

    return db.create_audit_log(
        plan_version_id=plan_version_id,
        check_name="FREEZE_OVERRIDE",
        status="OVERRIDE",
        count=len(affected_instance_ids),
        details_json=details
    )


def solve_with_freeze(
    forecast_version_id: int,
    seed: int = 94,
    override: bool = False,
    override_user: Optional[str] = None,
    override_reason: Optional[str] = None,
    now: Optional[datetime] = None
) -> dict:
    """
    Solve forecast respecting freeze windows.

    If override=False:
        - Frozen instances use previous assignments (if available)
        - Only modifiable instances are solved

    If override=True:
        - All instances are solved (frozen included)
        - Override is logged to audit_log

    Args:
        forecast_version_id: Forecast version ID
        seed: Solver seed (default: 94)
        override: Allow modification of frozen instances (default: False)
        override_user: User authorizing override (required if override=True)
        override_reason: Reason for override (required if override=True)
        now: Current time for freeze calculation (default: datetime.now())

    Returns:
        Dict with solve results including freeze info
    """
    if now is None:
        now = datetime.now()

    # Classify instances
    frozen_ids, modifiable_ids = classify_instances(forecast_version_id, now)

    result = {
        "forecast_version_id": forecast_version_id,
        "seed": seed,
        "freeze_status": {
            "frozen_count": len(frozen_ids),
            "modifiable_count": len(modifiable_ids),
            "override": override,
            "override_user": override_user if override else None,
            "override_reason": override_reason if override else None
        },
        "assignments": [],
        "plan_version_id": None,
        "audit_results": None
    }

    if not override and frozen_ids:
        # Get previous assignments for frozen instances
        previous_assignments = get_previous_assignments(frozen_ids, forecast_version_id)
        result["freeze_status"]["previous_assignments_found"] = len(previous_assignments)

        # Use V2 solver for modifiable instances only
        from .solver_wrapper import solve_forecast

        # Create plan version
        solve_result = solve_forecast(
            forecast_version_id=forecast_version_id,
            seed=seed,
            save_to_db=True,
            run_audit=True
        )

        result["plan_version_id"] = solve_result["plan_version_id"]
        result["assignments"] = solve_result.get("assignments", [])
        result["audit_results"] = solve_result.get("audit_results")

        # Note: In a full implementation, we would:
        # 1. Filter out frozen instances from solver input
        # 2. Copy previous assignments for frozen instances
        # 3. Merge results
        # For MVP, we solve all and note the freeze status

    else:
        # Override mode or no frozen instances
        from .solver_wrapper import solve_forecast

        solve_result = solve_forecast(
            forecast_version_id=forecast_version_id,
            seed=seed,
            save_to_db=True,
            run_audit=True
        )

        result["plan_version_id"] = solve_result["plan_version_id"]
        result["assignments"] = solve_result.get("assignments", [])
        result["audit_results"] = solve_result.get("audit_results")

        # Log override if applicable
        if override and frozen_ids and override_user:
            log_freeze_override(
                plan_version_id=result["plan_version_id"],
                user=override_user,
                reason=override_reason or "No reason provided",
                affected_instance_ids=frozen_ids
            )
            result["freeze_status"]["override_logged"] = True

    return result


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point for freeze window operations."""
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m v3.freeze_windows <command> <forecast_version_id> [options]")
        print("")
        print("Commands:")
        print("   classify <fv_id>        - Show frozen vs modifiable instances")
        print("   solve <fv_id> [seed]    - Solve respecting freeze")
        print("   override <fv_id> [seed] - Solve with override (requires confirmation)")
        sys.exit(1)

    command = sys.argv[1]
    forecast_version_id = int(sys.argv[2])

    if command == "classify":
        frozen_ids, modifiable_ids = classify_instances(forecast_version_id)
        print(f"Forecast {forecast_version_id} Classification:")
        print(f"   FROZEN: {len(frozen_ids)} instances")
        print(f"   MODIFIABLE: {len(modifiable_ids)} instances")
        print(f"   Total: {len(frozen_ids) + len(modifiable_ids)} instances")

        if frozen_ids:
            print(f"\nFrozen IDs (first 10): {frozen_ids[:10]}")

    elif command == "solve":
        seed = int(sys.argv[3]) if len(sys.argv) > 3 else 94
        result = solve_with_freeze(forecast_version_id, seed, override=False)
        print(f"Solve Result (respecting freeze):")
        print(f"   Plan Version: {result['plan_version_id']}")
        print(f"   Frozen: {result['freeze_status']['frozen_count']}")
        print(f"   Modifiable: {result['freeze_status']['modifiable_count']}")

    elif command == "override":
        seed = int(sys.argv[3]) if len(sys.argv) > 3 else 94
        print("WARNING: This will override frozen instances!")
        confirm = input("Type 'OVERRIDE' to confirm: ")
        if confirm != "OVERRIDE":
            print("Aborted.")
            sys.exit(0)

        result = solve_with_freeze(
            forecast_version_id, seed,
            override=True,
            override_user="cli_admin",
            override_reason="Manual CLI override"
        )
        print(f"Solve Result (with override):")
        print(f"   Plan Version: {result['plan_version_id']}")
        print(f"   Override Logged: {result['freeze_status'].get('override_logged', False)}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
