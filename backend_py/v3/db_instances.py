"""
SOLVEREIGN V3 Database Module - Tour Instances (P0 FIX)
=========================================================

Fixed database operations for tour_instances model.
Replaces broken tours_normalized.count logic.
"""

from contextlib import contextmanager
from typing import Generator, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    raise ImportError("psycopg not installed. Run: pip install 'psycopg[binary]'")

from .config import config


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Context manager for database connections."""
    conn = psycopg.connect(config.get_connection_string(), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


# ============================================================================
# Tour Instances (P0 FIX)
# ============================================================================

def expand_tour_template(forecast_version_id: int) -> int:
    """
    Auto-expand tours_normalized.count to tour_instances.
    
    Example:
        tours_normalized: count=3 → creates 3 tour_instances (instance_number 1,2,3)
    
    Returns:
        Number of instances created
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT expand_tour_instances(%s)", (forecast_version_id,))
            count = cur.fetchone()["expand_tour_instances"]
            conn.commit()
    return count


def get_tour_instances(forecast_version_id: int) -> list[dict]:
    """Get all tour instances for a forecast version."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM tour_instances
                WHERE forecast_version_id = %s
                ORDER BY day, start_ts, instance_number
            """, (forecast_version_id,))
            return cur.fetchall()


def get_tour_instance(instance_id: int) -> Optional[dict]:
    """Get single tour instance by ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tour_instances WHERE id = %s", (instance_id,))
            return cur.fetchone()


def create_assignment_fixed(
    plan_version_id: int,
    driver_id: str,
    tour_instance_id: int,  # ✅ FIX: Now references tour_instances
    day: int,
    block_id: str,
    role: Optional[str] = None,
    metadata: Optional[dict] = None
) -> int:
    """
    Create assignment (FIXED for tour_instances).
    
    Args:
        tour_instance_id: References tour_instances.id (not tours_normalized.id!)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO assignments (
                    plan_version_id, driver_id, tour_instance_id, day, block_id, role, metadata
                )
                VALUES (%(pv_id)s, %(driver)s, %(instance)s, %(day)s, %(block)s, %(role)s, %(metadata)s)
                RETURNING id
            """, {
                "pv_id": plan_version_id,
                "driver": driver_id,
                "instance": tour_instance_id,
                "day": day,
                "block": block_id,
                "role": role,
                "metadata": psycopg.types.json.Jsonb(metadata) if metadata else None
            })
            assignment_id = cur.fetchone()["id"]
            conn.commit()
    return assignment_id


def get_assignments_with_instances(plan_version_id: int) -> list[dict]:
    """
    Get assignments with joined tour_instance data.
    
    Returns enriched assignments with tour details.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    a.*,
                    ti.day as instance_day,
                    ti.start_ts,
                    ti.end_ts,
                    ti.crosses_midnight,
                    ti.duration_min,
                    ti.work_hours,
                    ti.depot,
                    ti.skill,
                    ti.tour_template_id,
                    ti.instance_number
                FROM assignments a
                JOIN tour_instances ti ON a.tour_instance_id = ti.id
                WHERE a.plan_version_id = %s
                ORDER BY a.driver_id, a.day, ti.start_ts
            """, (plan_version_id,))
            return cur.fetchall()


# ============================================================================
# Coverage Check (FIXED)
# ============================================================================

def check_coverage_fixed(plan_version_id: int) -> dict:
    """
    Coverage check with tour_instances (FIXED).
    
    Returns:
        {
            "status": "PASS" | "FAIL",
            "total_instances": int,
            "total_assignments": int,
            "missing_instances": [list of instance IDs],
            "extra_assignments": [list of assignment IDs]
        }
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get forecast_version_id from plan
            cur.execute("""
                SELECT forecast_version_id FROM plan_versions WHERE id = %s
            """, (plan_version_id,))
            result = cur.fetchone()
            if not result:
                return {"status": "FAIL", "error": "Plan not found"}
            
            forecast_version_id = result["forecast_version_id"]
            
            # Get all instances
            cur.execute("""
                SELECT id FROM tour_instances WHERE forecast_version_id = %s
            """, (forecast_version_id,))
            all_instances = {row["id"] for row in cur.fetchall()}
            
            # Get all assigned instances
            cur.execute("""
                SELECT tour_instance_id FROM assignments WHERE plan_version_id = %s
            """, (plan_version_id,))
            assigned_instances = {row["tour_instance_id"] for row in cur.fetchall()}
            
            # Calculate coverage
            missing = all_instances - assigned_instances
            extra = assigned_instances - all_instances
            
            status = "PASS" if not missing and not extra else "FAIL"
            
            return {
                "status": status,
                "total_instances": len(all_instances),
                "total_assignments": len(assigned_instances),
                "missing_instances": list(missing),
                "extra_assignments": list(extra),
                "coverage_ratio": len(assigned_instances) / len(all_instances) if all_instances else 0
            }
