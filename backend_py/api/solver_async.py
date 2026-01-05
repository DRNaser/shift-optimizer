"""
SOLVEREIGN V3.3a API - Async Solver Wrapper
============================================

Async wrapper for the synchronous V2 solver.
Runs solver in thread pool to avoid blocking the event loop.
"""

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from .database import DatabaseManager
from .logging_config import get_logger

logger = get_logger(__name__)

# Thread pool for CPU-bound solver operations
_solver_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="solver")


async def solve_forecast_async(
    db: DatabaseManager,
    tenant_id: int,
    forecast_version_id: int,
    seed: int = 94,
    run_audit: bool = True,
) -> dict:
    """
    Async wrapper for solve_forecast.

    Runs the synchronous V2 solver in a thread pool to avoid
    blocking the FastAPI event loop.

    Args:
        db: Database manager
        tenant_id: Tenant ID
        forecast_version_id: Forecast to solve
        seed: Solver seed
        run_audit: Whether to run audits after solving

    Returns:
        Solver result dict
    """
    logger.info(
        "starting_solve",
        extra={
            "tenant_id": tenant_id,
            "forecast_version_id": forecast_version_id,
            "seed": seed,
        }
    )

    start_time = datetime.now()

    # Run solver in thread pool
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _solver_executor,
        _run_solver_sync,
        tenant_id,
        forecast_version_id,
        seed,
        run_audit,
    )

    duration = (datetime.now() - start_time).total_seconds()

    logger.info(
        "solve_completed",
        extra={
            "tenant_id": tenant_id,
            "forecast_version_id": forecast_version_id,
            "plan_version_id": result.get("plan_version_id"),
            "drivers_count": result.get("drivers_count"),
            "duration_seconds": round(duration, 2),
        }
    )

    return result


def _run_solver_sync(
    tenant_id: int,
    forecast_version_id: int,
    seed: int,
    run_audit: bool,
) -> dict:
    """
    Synchronous solver execution (runs in thread pool).

    This bridges the async API layer to the sync V3 solver code.
    """
    from v3.solver_wrapper import solve_forecast, compute_plan_kpis
    from v3.audit_fixed import audit_plan_fixed

    try:
        # Run V2 solver
        result = solve_forecast(
            forecast_version_id=forecast_version_id,
            seed=seed,
            save_to_db=True,
            run_audit=run_audit,
            tenant_id=tenant_id,
        )

        # Add plan_version_id to result if not present
        if "plan_version_id" not in result:
            result["plan_version_id"] = None

        return result

    except Exception as e:
        logger.error(
            "solve_failed",
            extra={
                "tenant_id": tenant_id,
                "forecast_version_id": forecast_version_id,
                "error": str(e),
            }
        )
        raise


async def compute_plan_kpis_async(
    db: DatabaseManager,
    tenant_id: int,
    plan_version_id: int,
) -> dict:
    """
    Async wrapper for compute_plan_kpis.

    Args:
        db: Database manager
        tenant_id: Tenant ID
        plan_version_id: Plan to compute KPIs for

    Returns:
        KPIs dict
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _solver_executor,
        _compute_kpis_sync,
        plan_version_id,
    )


def _compute_kpis_sync(plan_version_id: int) -> dict:
    """Synchronous KPI computation."""
    from v3.solver_wrapper import compute_plan_kpis as sync_compute_kpis

    kpis = sync_compute_kpis(plan_version_id)

    # Flatten for API response
    return {
        "total_drivers": kpis.get("total_drivers", 0),
        "fte_drivers": kpis.get("total_drivers", 0) - kpis.get("pt_drivers", 0),
        "pt_drivers": kpis.get("pt_drivers", 0),
        "pt_ratio": kpis.get("pt_ratio", 0.0),
        "total_tours": kpis.get("total_blocks", 0),  # blocks = tour groups
        "coverage_pct": 100.0,  # Assuming full coverage for now
        "block_1er": kpis.get("block_mix", {}).get("1er", {}).get("count", 0),
        "block_2er_reg": kpis.get("block_mix", {}).get("2er", {}).get("count", 0),
        "block_2er_split": 0,  # Split tracking not in current KPIs
        "block_3er": kpis.get("block_mix", {}).get("3er", {}).get("count", 0),
        "avg_weekly_hours": kpis.get("avg_work_hours", 0.0),
        "max_weekly_hours": 0.0,  # Not in current KPIs
        "min_weekly_hours": 0.0,  # Not in current KPIs
    }


async def audit_plan_async(
    db: DatabaseManager,
    tenant_id: int,
    plan_version_id: int,
    save_to_db: bool = True,
) -> dict:
    """
    Async wrapper for audit_plan_fixed.

    Args:
        db: Database manager
        tenant_id: Tenant ID
        plan_version_id: Plan to audit
        save_to_db: Whether to save results

    Returns:
        Audit result dict
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _solver_executor,
        _audit_plan_sync,
        plan_version_id,
        save_to_db,
        tenant_id,
    )


def _audit_plan_sync(plan_version_id: int, save_to_db: bool, tenant_id: int = 1) -> dict:
    """Synchronous audit execution."""
    from v3.audit_fixed import audit_plan_fixed

    return audit_plan_fixed(plan_version_id, save_to_db=save_to_db, tenant_id=tenant_id)


# =============================================================================
# SOLVER CONFIG HASH
# =============================================================================

def compute_solver_config_hash(
    seed: int,
    weekly_hours_cap: int = 55,
    freeze_window_minutes: int = 720,
) -> str:
    """
    Compute deterministic hash of solver configuration.

    Used for:
    - Idempotency (same config = same plan)
    - Reproducibility verification
    """
    config = {
        "version": "v2_block_heuristic",
        "seed": seed,
        "weekly_hours_cap": weekly_hours_cap,
        "freeze_window_minutes": freeze_window_minutes,
        "triple_gap_min": 30,
        "triple_gap_max": 60,
        "split_break_min": 240,
        "split_break_max": 360,
        "rest_min_minutes": 660,
        "span_regular_max": 840,
        "span_split_max": 960,
    }

    return hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()
