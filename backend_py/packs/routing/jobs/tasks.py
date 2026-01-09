# =============================================================================
# SOLVEREIGN Routing Pack - Celery Tasks
# =============================================================================
# Async tasks for route optimization and repair.
#
# P0-2: Worker RLS/Tenant Isolation
# - Every task loads tenant_id from scenario FIRST
# - All subsequent queries use tenant_transaction()
# - Advisory locks prevent concurrent solves on same scenario
# =============================================================================

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from ..db.connection import (
    get_connection,
    tenant_transaction,
    try_acquire_scenario_lock,
    release_scenario_lock,
    get_scenario_tenant_id,
    get_plan_tenant_id,
)

logger = logging.getLogger(__name__)


class RoutingTask(Task):
    """
    Base task class for routing operations.

    Provides:
    - Automatic retry on transient failures
    - Logging and error handling
    - Status tracking
    """

    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3, "countdown": 60}
    retry_backoff = True
    retry_backoff_max = 300  # Max 5 minutes between retries

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails after all retries."""
        logger.error(
            f"Task {task_id} failed permanently: {exc}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "args": args,
                "kwargs": kwargs,
            }
        )

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is being retried."""
        logger.warning(
            f"Task {task_id} retrying due to: {exc}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "retry_count": self.request.retries,
            }
        )


@celery_app.task(bind=True, base=RoutingTask, name="routing.solve_scenario")
def solve_routing_scenario(
    self,
    scenario_id: str,
    config: Dict[str, Any],
    tenant_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Async Route Optimization Job.

    P0-2 SECURITY: Tenant Isolation Pattern
    1. Load tenant_id from scenario FIRST (before any other DB ops)
    2. Acquire advisory lock (prevent double-solve)
    3. All subsequent operations use tenant_transaction(tenant_id)
    4. Release lock on completion or failure

    Args:
        scenario_id: UUID of the routing scenario
        config: Solver configuration dict
        tenant_id: Optional tenant override (for testing only)

    Returns:
        Dict with plan_id, status, and metrics
    """
    import time
    start_time = time.time()
    plan_id = None
    lock_acquired = False
    effective_tenant_id = None

    try:
        logger.info(
            f"Starting solve for scenario {scenario_id}",
            extra={"task_id": self.request.id, "scenario_id": scenario_id}
        )

        # =====================================================================
        # STEP 1: Load tenant_id from scenario (P0-2: RLS)
        # This MUST happen FIRST before any tenant-scoped operations
        # =====================================================================
        if tenant_id is not None:
            # Testing override
            effective_tenant_id = tenant_id
            logger.warning(f"Using provided tenant_id override: {tenant_id}")
        else:
            # Production: load from DB
            with get_connection() as conn:
                effective_tenant_id = get_scenario_tenant_id(conn, scenario_id)

            if effective_tenant_id is None:
                logger.error(f"Scenario {scenario_id} not found")
                return {
                    "status": "FAILED",
                    "scenario_id": scenario_id,
                    "error": "Scenario not found"
                }

        logger.info(f"Tenant context: tenant_id={effective_tenant_id}")

        # =====================================================================
        # STEP 2: Acquire advisory lock (prevent double-solve)
        # =====================================================================
        with get_connection() as conn:
            lock_acquired = try_acquire_scenario_lock(conn, effective_tenant_id, scenario_id)

        if not lock_acquired:
            logger.warning(f"Scenario {scenario_id} is already being solved")
            return {
                "status": "ALREADY_SOLVING",
                "scenario_id": scenario_id,
                "error": "Scenario is already being solved by another worker"
            }

        # =====================================================================
        # STEP 3: All operations via tenant_transaction (P0-2)
        # =====================================================================
        with tenant_transaction(effective_tenant_id) as conn:
            # Update status: SOLVING
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE routing_plans
                    SET status = 'SOLVING', started_at = NOW()
                    WHERE scenario_id = %s AND status = 'QUEUED'
                    RETURNING id
                    """,
                    (scenario_id,)
                )
                result = cur.fetchone()
                plan_id = result["id"] if result else None

            if not plan_id:
                # Create new plan if none exists
                with conn.cursor() as cur:
                    solver_config_hash = _compute_config_hash(config)
                    cur.execute(
                        """
                        INSERT INTO routing_plans (
                            scenario_id, tenant_id, status, seed,
                            solver_config_hash, started_at
                        )
                        VALUES (%s, %s, 'SOLVING', %s, %s, NOW())
                        ON CONFLICT (scenario_id, solver_config_hash)
                        DO UPDATE SET status = 'SOLVING', started_at = NOW()
                        RETURNING id
                        """,
                        (scenario_id, effective_tenant_id, config.get("seed", 42), solver_config_hash)
                    )
                    result = cur.fetchone()
                    plan_id = result["id"] if result else None

            logger.info(f"Plan {plan_id} status: SOLVING")

            # Load stops, vehicles, depots
            stops = _load_stops(conn, scenario_id)
            vehicles = _load_vehicles(conn, scenario_id)
            depots = _load_depots(conn, effective_tenant_id, vehicles)

            if not stops:
                _update_plan_failed(conn, plan_id, "No stops found for scenario")
                return {
                    "status": "FAILED",
                    "plan_id": plan_id,
                    "scenario_id": scenario_id,
                    "error": "No stops found"
                }

            if not vehicles:
                _update_plan_failed(conn, plan_id, "No vehicles found for scenario")
                return {
                    "status": "FAILED",
                    "plan_id": plan_id,
                    "scenario_id": scenario_id,
                    "error": "No vehicles found"
                }

            # Run solver
            # TODO: Implement actual solver call
            logger.info(f"Running solver with {len(stops)} stops, {len(vehicles)} vehicles")

            solve_time = time.time() - start_time

            # Update plan status
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE routing_plans
                    SET status = 'SOLVED',
                        completed_at = NOW(),
                        total_vehicles = %s,
                        total_distance_km = 0,
                        total_duration_min = 0,
                        unassigned_count = 0
                    WHERE id = %s
                    """,
                    (len(vehicles), plan_id)
                )

        logger.info(
            f"Solve completed for scenario {scenario_id}",
            extra={
                "task_id": self.request.id,
                "scenario_id": scenario_id,
                "plan_id": plan_id,
                "solve_time": solve_time,
            }
        )

        return {
            "status": "SUCCESS",
            "plan_id": plan_id,
            "scenario_id": scenario_id,
            "tenant_id": effective_tenant_id,
            "solve_time_seconds": solve_time,
            "metrics": {
                "stops_count": len(stops) if stops else 0,
                "vehicles_count": len(vehicles) if vehicles else 0,
            }
        }

    except SoftTimeLimitExceeded:
        logger.error(f"Solve timed out for scenario {scenario_id}")
        if plan_id and effective_tenant_id:
            with tenant_transaction(effective_tenant_id) as conn:
                _update_plan_failed(conn, plan_id, "Solver exceeded time limit")
        return {
            "status": "TIMEOUT",
            "plan_id": plan_id,
            "scenario_id": scenario_id,
            "error": "Solver exceeded time limit"
        }

    except Exception as e:
        logger.exception(f"Solve failed for scenario {scenario_id}: {e}")
        if plan_id and effective_tenant_id:
            with tenant_transaction(effective_tenant_id) as conn:
                _update_plan_failed(conn, plan_id, str(e))
        return {
            "status": "FAILED",
            "plan_id": plan_id,
            "scenario_id": scenario_id,
            "error": str(e)
        }

    finally:
        # ALWAYS release lock
        if lock_acquired and effective_tenant_id:
            with get_connection() as conn:
                release_scenario_lock(conn, effective_tenant_id, scenario_id)


@celery_app.task(bind=True, base=RoutingTask, name="routing.repair_route")
def repair_route(
    self,
    plan_id: str,
    event: Dict[str, Any],
    freeze_scope: Dict[str, Any],
    tenant_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Async Route Repair Job.

    P0-2 SECURITY: Same tenant isolation pattern as solve.

    Args:
        plan_id: UUID of the plan to repair
        event: Event details (type, affected_stop_ids, etc.)
        freeze_scope: Which stops/assignments are locked
        tenant_id: Optional tenant override (for testing)

    Returns:
        Dict with new_plan_id, churn metrics, and diff
    """
    import time
    start_time = time.time()
    new_plan_id = None
    effective_tenant_id = None

    try:
        logger.info(
            f"Starting repair for plan {plan_id}",
            extra={
                "task_id": self.request.id,
                "plan_id": plan_id,
                "event_type": event.get("type"),
            }
        )

        # STEP 1: Load tenant_id from plan
        if tenant_id is not None:
            effective_tenant_id = tenant_id
        else:
            with get_connection() as conn:
                effective_tenant_id = get_plan_tenant_id(conn, plan_id)

            if effective_tenant_id is None:
                return {
                    "status": "FAILED",
                    "old_plan_id": plan_id,
                    "error": "Plan not found"
                }

        # STEP 2: All operations via tenant_transaction
        with tenant_transaction(effective_tenant_id) as conn:
            # Load current plan
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM routing_plans WHERE id = %s",
                    (plan_id,)
                )
                plan = cur.fetchone()

            if not plan:
                return {
                    "status": "FAILED",
                    "old_plan_id": plan_id,
                    "error": "Plan not found"
                }

            event_type = event.get("type", "UNKNOWN")
            affected_stop_ids = event.get("affected_stop_ids", [])

            logger.info(f"Event type: {event_type}, affected stops: {len(affected_stop_ids)}")

            # TODO: Implement repair logic
            repair_time = time.time() - start_time
            new_plan_id = f"repair_{plan_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        logger.info(
            f"Repair completed for plan {plan_id}",
            extra={
                "task_id": self.request.id,
                "old_plan_id": plan_id,
                "new_plan_id": new_plan_id,
                "repair_time": repair_time,
            }
        )

        return {
            "status": "SUCCESS",
            "old_plan_id": plan_id,
            "new_plan_id": new_plan_id,
            "tenant_id": effective_tenant_id,
            "repair_time_seconds": repair_time,
            "churn": {
                "stops_moved": 0,
                "vehicles_changed": 0,
            }
        }

    except SoftTimeLimitExceeded:
        logger.error(f"Repair timed out for plan {plan_id}")
        return {
            "status": "TIMEOUT",
            "old_plan_id": plan_id,
            "error": "Repair exceeded time limit"
        }

    except Exception as e:
        logger.exception(f"Repair failed for plan {plan_id}: {e}")
        return {
            "status": "FAILED",
            "old_plan_id": plan_id,
            "error": str(e)
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _compute_config_hash(config: Dict[str, Any]) -> str:
    """Compute deterministic hash of solver config."""
    import hashlib
    import json
    config_str = json.dumps(config, sort_keys=True)
    return hashlib.sha256(config_str.encode()).hexdigest()


def _load_stops(conn, scenario_id: str) -> list:
    """Load stops for a scenario."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, order_id, service_code, category,
                   lat, lng, tw_start, tw_end, tw_is_hard,
                   service_duration_min, requires_two_person,
                   required_skills, volume_m3, weight_kg
            FROM routing_stops
            WHERE scenario_id = %s
            """,
            (scenario_id,)
        )
        return cur.fetchall()


def _load_vehicles(conn, scenario_id: str) -> list:
    """Load vehicles for a scenario."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, external_id, team_size, skills,
                   shift_start_at, shift_end_at,
                   start_depot_id, end_depot_id,
                   capacity_volume_m3, capacity_weight_kg
            FROM routing_vehicles
            WHERE scenario_id = %s
            """,
            (scenario_id,)
        )
        return cur.fetchall()


def _load_depots(conn, tenant_id: int, vehicles: list) -> list:
    """Load depots referenced by vehicles."""
    if not vehicles:
        return []

    depot_ids = set()
    for v in vehicles:
        depot_ids.add(v["start_depot_id"])
        depot_ids.add(v["end_depot_id"])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, site_id, name, lat, lng, loading_time_min
            FROM routing_depots
            WHERE id = ANY(%s) AND tenant_id = %s
            """,
            (list(depot_ids), tenant_id)
        )
        return cur.fetchall()


def _update_plan_failed(conn, plan_id: str, error_message: str):
    """Update plan status to FAILED."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE routing_plans
            SET status = 'FAILED',
                completed_at = NOW(),
                error_message = %s
            WHERE id = %s
            """,
            (error_message, plan_id)
        )
