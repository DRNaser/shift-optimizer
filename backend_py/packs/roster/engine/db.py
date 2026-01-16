"""
SOLVEREIGN V3 Database Module
==============================

Postgres connection and CRUD operations for V3 architecture.
"""

from contextlib import contextmanager
from typing import Generator, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    raise ImportError(
        "psycopg not installed. Run: pip install 'psycopg[binary]'"
    )

from .config import config
from .models import (
    Assignment,
    AuditLog,
    ForecastVersion,
    PlanVersion,
    TourNormalized,
    TourRaw,
    FreezeWindow,
)


# ============================================================================
# Connection Management
# ============================================================================

@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """
    Context manager for database connections.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM forecast_versions")
    """
    conn = psycopg.connect(config.get_connection_string(), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def test_connection() -> bool:
    """Test database connectivity."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except psycopg.OperationalError:
        return False


# ============================================================================
# Forecast Versions
# ============================================================================

def create_forecast_version(
    source: str,
    input_hash: str,
    parser_config_hash: str,
    status: str,
    notes: Optional[str] = None,
    week_key: Optional[str] = None,
    week_anchor_date: Optional[str] = None,
    tenant_id: int = 1  # Default tenant for backward compatibility
) -> int:
    """
    Create new forecast version and return ID.

    Args:
        source: Input source (slack, csv, manual, composed)
        input_hash: SHA256 of canonical input
        parser_config_hash: Parser version hash
        status: PASS/WARN/FAIL
        notes: Optional notes
        week_key: Week identifier (e.g., "2026-W01") - REQUIRED for compose
        week_anchor_date: Monday of the week (YYYY-MM-DD)
        tenant_id: Tenant ID (default 1 for backward compatibility)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO forecast_versions (
                    source, input_hash, parser_config_hash, status, notes,
                    week_key, week_anchor_date, tenant_id
                )
                VALUES (
                    %(source)s, %(input_hash)s, %(parser_config_hash)s, %(status)s, %(notes)s,
                    %(week_key)s, %(week_anchor_date)s, %(tenant_id)s
                )
                RETURNING id
            """, {
                "source": source,
                "input_hash": input_hash,
                "parser_config_hash": parser_config_hash,
                "status": status,
                "notes": notes,
                "week_key": week_key,
                "week_anchor_date": week_anchor_date,
                "tenant_id": tenant_id
            })
            forecast_id = cur.fetchone()["id"]
            conn.commit()
    return forecast_id


def get_forecast_version(forecast_version_id: int) -> Optional[dict]:
    """Get forecast version by ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM forecast_versions WHERE id = %s
            """, (forecast_version_id,))
            return cur.fetchone()


def get_latest_forecast_version() -> Optional[dict]:
    """Get most recent forecast version."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM forecast_versions
                ORDER BY created_at DESC
                LIMIT 1
            """)
            return cur.fetchone()


def get_forecast_by_input_hash(input_hash: str) -> Optional[dict]:
    """
    Get forecast version by input_hash (for deduplication).

    Returns:
        Existing forecast version dict or None if not found
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM forecast_versions WHERE input_hash = %s
            """, (input_hash,))
            return cur.fetchone()


def get_all_forecast_versions(limit: int = 50) -> list:
    """
    Get all forecast versions ordered by creation date.

    Returns:
        List of forecast version dicts
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fv.*,
                       (SELECT COUNT(*) FROM tours_normalized tn WHERE tn.forecast_version_id = fv.id) as tour_count,
                       (SELECT COUNT(*) FROM tour_instances ti WHERE ti.forecast_version_id = fv.id) as instance_count
                FROM forecast_versions fv
                ORDER BY fv.created_at DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()


# ============================================================================
# Tours Raw
# ============================================================================

def create_tour_raw(
    forecast_version_id: int,
    line_no: int,
    raw_text: str,
    parse_status: str,
    parse_errors: Optional[list] = None,
    parse_warnings: Optional[list] = None,
    canonical_text: Optional[str] = None,
    tenant_id: int = 1  # Default tenant for backward compatibility
) -> int:
    """Create raw tour entry and return ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tours_raw (
                    forecast_version_id, line_no, raw_text, parse_status,
                    parse_errors, parse_warnings, canonical_text, tenant_id
                )
                VALUES (%(fv_id)s, %(line_no)s, %(raw_text)s, %(status)s, %(errors)s, %(warnings)s, %(canonical)s, %(tenant_id)s)
                RETURNING id
            """, {
                "fv_id": forecast_version_id,
                "line_no": line_no,
                "raw_text": raw_text,
                "status": parse_status,
                "errors": psycopg.types.json.Jsonb(parse_errors) if parse_errors else None,
                "warnings": psycopg.types.json.Jsonb(parse_warnings) if parse_warnings else None,
                "canonical": canonical_text,
                "tenant_id": tenant_id
            })
            tour_raw_id = cur.fetchone()["id"]
            conn.commit()
    return tour_raw_id


def get_tours_raw(forecast_version_id: int) -> list[dict]:
    """Get all raw tours for a forecast version."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM tours_raw
                WHERE forecast_version_id = %s
                ORDER BY line_no
            """, (forecast_version_id,))
            return cur.fetchall()


# ============================================================================
# Tours Normalized
# ============================================================================

def create_tour_normalized(
    forecast_version_id: int,
    day: int,
    start_ts: str,
    end_ts: str,
    duration_min: int,
    work_hours: float,
    tour_fingerprint: str,
    span_group_key: Optional[str] = None,
    split_break_minutes: Optional[int] = None,
    count: int = 1,
    depot: Optional[str] = None,
    skill: Optional[str] = None,
    metadata: Optional[dict] = None,
    tenant_id: int = 1  # Default tenant for backward compatibility
) -> int:
    """Create normalized tour and return ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tours_normalized (
                    forecast_version_id, day, start_ts, end_ts, duration_min, work_hours,
                    tour_fingerprint, span_group_key, split_break_minutes, count, depot, skill, metadata, tenant_id
                )
                VALUES (
                    %(fv_id)s, %(day)s, %(start)s, %(end)s, %(duration)s, %(hours)s,
                    %(fingerprint)s, %(span_key)s, %(split_break)s, %(count)s, %(depot)s, %(skill)s, %(metadata)s, %(tenant_id)s
                )
                RETURNING id
            """, {
                "fv_id": forecast_version_id,
                "day": day,
                "start": start_ts,
                "end": end_ts,
                "duration": duration_min,
                "hours": work_hours,
                "fingerprint": tour_fingerprint,
                "span_key": span_group_key,
                "split_break": split_break_minutes,
                "count": count,
                "depot": depot,
                "skill": skill,
                "metadata": psycopg.types.json.Jsonb(metadata) if metadata else None,
                "tenant_id": tenant_id
            })
            tour_id = cur.fetchone()["id"]
            conn.commit()
    return tour_id


def get_tours_normalized(forecast_version_id: int) -> list[dict]:
    """Get all normalized tours for a forecast version."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM tours_normalized
                WHERE forecast_version_id = %s
                ORDER BY day, start_ts
            """, (forecast_version_id,))
            return cur.fetchall()


# ============================================================================
# Plan Versions
# ============================================================================

def create_plan_version(
    forecast_version_id: int,
    seed: int,
    solver_config_hash: str,
    output_hash: str,
    status: str = "DRAFT",
    notes: Optional[str] = None,
    scenario_label: Optional[str] = None,
    baseline_plan_version_id: Optional[int] = None,
    solver_config_json: Optional[dict] = None,
    tenant_id: int = 1,  # Default tenant for backward compatibility
    policy_profile_id: Optional[str] = None,  # UUID of active policy profile
    policy_config_hash: Optional[str] = None,  # Hash of policy config at solve time
) -> int:
    """
    Create plan version and return ID.

    Args:
        forecast_version_id: Source forecast
        seed: Solver random seed
        solver_config_hash: Hash of solver configuration
        output_hash: Hash of output assignments
        status: Plan status (DRAFT, LOCKED, etc.)
        notes: Optional notes
        scenario_label: Scenario name for tracking
        baseline_plan_version_id: Baseline plan for churn calculation
        solver_config_json: Full solver config as dict
        tenant_id: Tenant ID
        policy_profile_id: UUID of the policy profile used (ADR-002)
        policy_config_hash: SHA256 of policy config for reproducibility
    """
    import json as json_module

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO plan_versions (
                    forecast_version_id, seed, solver_config_hash, output_hash, status, notes,
                    scenario_label, baseline_plan_version_id, solver_config_json, tenant_id,
                    policy_profile_id, policy_config_hash
                )
                VALUES (
                    %(fv_id)s, %(seed)s, %(config_hash)s, %(output_hash)s, %(status)s, %(notes)s,
                    %(scenario_label)s, %(baseline_id)s, %(config_json)s, %(tenant_id)s,
                    %(policy_profile_id)s, %(policy_config_hash)s
                )
                RETURNING id
            """, {
                "fv_id": forecast_version_id,
                "seed": seed,
                "config_hash": solver_config_hash,
                "output_hash": output_hash,
                "status": status,
                "notes": notes,
                "scenario_label": scenario_label,
                "baseline_id": baseline_plan_version_id,
                "config_json": json_module.dumps(solver_config_json) if solver_config_json else None,
                "tenant_id": tenant_id,
                "policy_profile_id": policy_profile_id,
                "policy_config_hash": policy_config_hash,
            })
            plan_id = cur.fetchone()["id"]
            conn.commit()
    return plan_id


def get_plan_version(plan_version_id: int) -> Optional[dict]:
    """Get plan version by ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM plan_versions WHERE id = %s
            """, (plan_version_id,))
            return cur.fetchone()


def lock_plan_version(
    plan_version_id: int,
    locked_by: str,
    check_freeze: bool = True,
    freeze_minutes: int = 720
) -> dict:
    """
    Lock a DRAFT plan version (transition to LOCKED).

    SPEC 8.1: Must check freeze violations before LOCK.

    Args:
        plan_version_id: Plan to lock
        locked_by: User performing lock
        check_freeze: Whether to check freeze violations (default True)
        freeze_minutes: Freeze window in minutes (default 720 = 12h)

    Returns:
        dict with: success, error, freeze_violations (if any)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # First, check if plan is DRAFT
            cur.execute("""
                SELECT pv.status, pv.forecast_version_id, pv.baseline_plan_version_id
                FROM plan_versions pv
                WHERE pv.id = %s
            """, (plan_version_id,))
            result = cur.fetchone()

            if not result:
                return {"success": False, "error": "Plan version not found"}

            if result["status"] != "DRAFT":
                return {"success": False, "error": f"Plan status is {result['status']}, not DRAFT"}

            forecast_version_id = result["forecast_version_id"]
            baseline_plan_id = result["baseline_plan_version_id"]

            # SPEC 8.1: Check freeze violations before LOCK
            freeze_violations = []
            if check_freeze and baseline_plan_id:
                # Import here to avoid circular imports
                from .solver_wrapper import check_freeze_violations
                freeze_violations = check_freeze_violations(
                    forecast_version_id,
                    baseline_plan_id,
                    freeze_minutes
                )

                if freeze_violations:
                    return {
                        "success": False,
                        "error": f"Cannot LOCK: {len(freeze_violations)} freeze violations detected",
                        "freeze_violations": freeze_violations
                    }

            # Lock the plan
            cur.execute("""
                UPDATE plan_versions
                SET status = 'LOCKED', locked_at = NOW(), locked_by = %s
                WHERE id = %s AND status = 'DRAFT'
            """, (locked_by, plan_version_id))

            # Supersede old LOCKED plans for same forecast
            cur.execute("""
                UPDATE plan_versions pv
                SET status = 'SUPERSEDED'
                WHERE pv.forecast_version_id = (
                    SELECT forecast_version_id FROM plan_versions WHERE id = %s
                )
                AND pv.id != %s
                AND pv.status = 'LOCKED'
            """, (plan_version_id, plan_version_id))

            conn.commit()

    return {"success": True, "error": None, "freeze_violations": []}


# ============================================================================
# Crash Recovery & Transaction Safety
# ============================================================================

def update_plan_status(plan_version_id: int, new_status: str, output_hash: str = None) -> bool:
    """
    Atomically update plan status.

    Valid transitions:
        SOLVING -> DRAFT (success)
        SOLVING -> FAILED (error)
        DRAFT -> LOCKED (release)

    Returns True if update succeeded, False if not found or invalid transition.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if output_hash:
                cur.execute("""
                    UPDATE plan_versions
                    SET status = %s, output_hash = %s
                    WHERE id = %s
                    RETURNING id
                """, (new_status, output_hash, plan_version_id))
            else:
                cur.execute("""
                    UPDATE plan_versions
                    SET status = %s
                    WHERE id = %s
                    RETURNING id
                """, (new_status, plan_version_id))
            result = cur.fetchone()
            conn.commit()
    return result is not None


def create_assignments_batch(plan_version_id: int, assignments: list[dict], tenant_id: int = 1) -> int:
    """
    Insert all assignments in a SINGLE transaction.

    If ANY insert fails, the entire batch is rolled back.
    This ensures atomic assignment creation for crash safety.

    Args:
        plan_version_id: Plan to assign to
        assignments: List of dicts with keys:
            - driver_id, tour_instance_id, day, block_id, role, metadata
        tenant_id: Tenant ID (default 1 for backward compatibility)

    Returns:
        Number of assignments inserted

    Raises:
        Exception: On any database error (transaction is rolled back)
    """
    if not assignments:
        return 0

    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                # Use executemany for batch insert
                values = [
                    {
                        "pv_id": plan_version_id,
                        "driver": a["driver_id"],
                        "tour_instance": a["tour_instance_id"],
                        "day": a["day"],
                        "block": a["block_id"],
                        "role": a.get("role"),
                        "metadata": psycopg.types.json.Jsonb(a.get("metadata")) if a.get("metadata") else None,
                        "tenant_id": tenant_id
                    }
                    for a in assignments
                ]

                cur.executemany("""
                    INSERT INTO assignments (
                        plan_version_id, driver_id, tour_instance_id, day, block_id, role, metadata, tenant_id
                    )
                    VALUES (%(pv_id)s, %(driver)s, %(tour_instance)s, %(day)s, %(block)s, %(role)s, %(metadata)s, %(tenant_id)s)
                """, values)

                count = cur.rowcount
                conn.commit()
                return count
        except Exception as e:
            conn.rollback()
            raise Exception(f"Batch assignment failed, transaction rolled back: {e}")


def get_solving_plans(max_age_minutes: int = 60) -> list[dict]:
    """
    Get all plans in SOLVING state older than max_age_minutes.

    These are likely crashed solver runs that need cleanup.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM plan_versions
                WHERE status = 'SOLVING'
                AND created_at < NOW() - INTERVAL '%s minutes'
                ORDER BY created_at
            """, (max_age_minutes,))
            return cur.fetchall()


def cleanup_stale_solving_plans(max_age_minutes: int = 60) -> int:
    """
    Mark stale SOLVING plans as FAILED.

    Call this on startup to recover from crashes.

    Args:
        max_age_minutes: Plans SOLVING for longer than this are marked FAILED

    Returns:
        Number of plans marked as FAILED
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Also delete any partial assignments for these plans
            cur.execute("""
                WITH stale_plans AS (
                    SELECT id FROM plan_versions
                    WHERE status = 'SOLVING'
                    AND created_at < NOW() - INTERVAL '%s minutes'
                )
                DELETE FROM assignments
                WHERE plan_version_id IN (SELECT id FROM stale_plans)
            """, (max_age_minutes,))
            deleted_assignments = cur.rowcount

            # Mark plans as FAILED
            cur.execute("""
                UPDATE plan_versions
                SET status = 'FAILED',
                    notes = COALESCE(notes, '') || ' [CRASH RECOVERY: Marked FAILED at ' || NOW()::text || ']'
                WHERE status = 'SOLVING'
                AND created_at < NOW() - INTERVAL '%s minutes'
                RETURNING id
            """, (max_age_minutes,))
            failed_plans = cur.fetchall()

            conn.commit()

            if failed_plans:
                print(f"[CRASH RECOVERY] Marked {len(failed_plans)} stale SOLVING plans as FAILED")
                print(f"[CRASH RECOVERY] Deleted {deleted_assignments} partial assignments")

            return len(failed_plans)


# ============================================================================
# Assignments
# ============================================================================

def create_assignment(
    plan_version_id: int,
    driver_id: str,
    tour_instance_id: int,
    day: int,
    block_id: str,
    role: Optional[str] = None,
    metadata: Optional[dict] = None
) -> int:
    """Create assignment and return ID (P0: uses tour_instance_id)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO assignments (
                    plan_version_id, driver_id, tour_instance_id, day, block_id, role, metadata
                )
                VALUES (%(pv_id)s, %(driver)s, %(tour_instance)s, %(day)s, %(block)s, %(role)s, %(metadata)s)
                RETURNING id
            """, {
                "pv_id": plan_version_id,
                "driver": driver_id,
                "tour_instance": tour_instance_id,
                "day": day,
                "block": block_id,
                "role": role,
                "metadata": psycopg.types.json.Jsonb(metadata) if metadata else None
            })
            assignment_id = cur.fetchone()["id"]
            conn.commit()
    return assignment_id


def get_assignments(plan_version_id: int) -> list[dict]:
    """Get all assignments for a plan version."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM assignments
                WHERE plan_version_id = %s
                ORDER BY driver_id, day
            """, (plan_version_id,))
            return cur.fetchall()


# ============================================================================
# Audit Log
# ============================================================================

def create_audit_log(
    plan_version_id: int,
    check_name: str,
    status: str,
    count: int,
    details_json: Optional[dict] = None,
    tenant_id: int = 1  # Default tenant for backward compatibility
) -> int:
    """Create audit log entry and return ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO audit_log (plan_version_id, check_name, status, count, details_json, tenant_id)
                VALUES (%(pv_id)s, %(check)s, %(status)s, %(count)s, %(details)s, %(tenant_id)s)
                RETURNING id
            """, {
                "pv_id": plan_version_id,
                "check": check_name,
                "status": status,
                "count": count,
                "details": psycopg.types.json.Jsonb(details_json) if details_json else None,
                "tenant_id": tenant_id
            })
            audit_id = cur.fetchone()["id"]
            conn.commit()
    return audit_id


def get_audit_logs(plan_version_id: int) -> list[dict]:
    """Get all audit logs for a plan version."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM audit_log
                WHERE plan_version_id = %s
                ORDER BY created_at
            """, (plan_version_id,))
            return cur.fetchall()


def can_release(plan_version_id: int) -> tuple[bool, list[str]]:
    """
    Check if plan version can be released (all gates PASS).
    Returns (can_release, list_of_blocking_checks).
    """
    mandatory_checks = [
        "COVERAGE", "OVERLAP", "REST",
        "SPAN_REGULAR", "SPAN_SPLIT", "REPRODUCIBILITY"
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT check_name, status
                FROM audit_log
                WHERE plan_version_id = %s
                AND check_name = ANY(%s)
            """, (plan_version_id, mandatory_checks))
            results = cur.fetchall()

    # Check for failures
    failed_checks = [r["check_name"] for r in results if r["status"] == "FAIL"]

    # Check if all mandatory checks were run
    run_checks = {r["check_name"] for r in results}
    missing_checks = set(mandatory_checks) - run_checks

    if missing_checks:
        return False, [f"Missing check: {check}" for check in missing_checks]

    if failed_checks:
        return False, [f"Failed check: {check}" for check in failed_checks]

    return True, []


# ============================================================================
# Freeze Windows
# ============================================================================

def get_active_freeze_windows() -> list[dict]:
    """Get all enabled freeze window rules."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM freeze_windows
                WHERE enabled = TRUE
                ORDER BY minutes_before_start DESC
            """)
            return cur.fetchall()


# ============================================================================
# Diff Results (Caching)
# ============================================================================

def create_diff_result(
    forecast_version_old: int,
    forecast_version_new: int,
    diff_type: str,
    tour_fingerprint: str,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    changed_fields: Optional[list] = None
) -> int:
    """Create diff result and return ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO diff_results (
                    forecast_version_old, forecast_version_new, diff_type, tour_fingerprint,
                    old_values, new_values, changed_fields
                )
                VALUES (%(old)s, %(new)s, %(type)s, %(fingerprint)s, %(old_vals)s, %(new_vals)s, %(changed)s)
                ON CONFLICT (forecast_version_old, forecast_version_new, tour_fingerprint)
                DO NOTHING
                RETURNING id
            """, {
                "old": forecast_version_old,
                "new": forecast_version_new,
                "type": diff_type,
                "fingerprint": tour_fingerprint,
                "old_vals": psycopg.types.json.Jsonb(old_values) if old_values else None,
                "new_vals": psycopg.types.json.Jsonb(new_values) if new_values else None,
                "changed": psycopg.types.json.Jsonb(changed_fields) if changed_fields else None
            })
            result = cur.fetchone()
            conn.commit()
    return result["id"] if result else None


def get_diff_results(forecast_version_old: int, forecast_version_new: int) -> list[dict]:
    """Get cached diff results between two forecast versions."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM diff_results
                WHERE forecast_version_old = %s AND forecast_version_new = %s
                ORDER BY diff_type, tour_fingerprint
            """, (forecast_version_old, forecast_version_new))
            return cur.fetchall()
