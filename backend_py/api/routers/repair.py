"""
SOLVEREIGN V3.3b API - Repair Router
=====================================

Repair API for handling driver absences and plan modifications.
Migrated from legacy repair_router.py for Enterprise API.

Endpoints:
- POST /plans/{plan_id}/repair  Repair plan for driver absences
- GET  /plans/{plan_id}/repair/{repair_id}  Get repair status
"""

import time
import json
import hashlib
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_current_tenant, TenantContext
from ..database import DatabaseManager


logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class RepairRequestPayload(BaseModel):
    """Request payload for repair endpoint."""
    absent_driver_ids: List[int] = Field(
        ...,
        description="List of driver IDs that are absent (e.g., sick)"
    )
    respect_freeze: bool = Field(
        default=True,
        description="If true, frozen tours cause FAIL (default: true)"
    )
    strategy: str = Field(
        default="MIN_CHURN",
        description="Repair strategy: MIN_CHURN (default)"
    )
    time_budget_seconds: int = Field(
        default=60,
        ge=1,
        le=300,
        description="Time budget in seconds (1-300)"
    )
    seed: Optional[int] = Field(
        default=None,
        description="Optional seed for reproducibility"
    )


class TourReassignment(BaseModel):
    """Details of a tour reassignment."""
    tour_id: str
    from_driver_id: int
    to_driver_id: int
    day: int
    start_time: str
    reason: str


class RepairResponsePayload(BaseModel):
    """Response payload for repair endpoint."""
    repair_log_id: int
    status: str  # SUCCESS, PARTIAL, FAILED
    new_plan_version_id: Optional[int] = None
    tours_reassigned: int = 0
    drivers_affected: int = 0
    churn_rate: float = 0.0
    freeze_violations: int = 0
    execution_time_ms: int = 0
    reassignments: List[TourReassignment] = Field(default_factory=list)
    error_message: Optional[str] = None
    audit_results: Optional[Dict[str, Any]] = None


class RepairStatusResponse(BaseModel):
    """Status of a repair operation."""
    repair_log_id: int
    plan_version_id: int
    status: str
    created_at: str
    completed_at: Optional[str] = None
    tours_reassigned: int = 0
    new_plan_version_id: Optional[int] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/{plan_id}/repair", response_model=RepairResponsePayload)
async def repair_plan(
    plan_id: int,
    payload: RepairRequestPayload,
    db: DatabaseManager = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    Repair a plan for driver absences.

    Creates a NEW plan version with reassigned tours.
    Does NOT modify the existing plan (immutable).

    Strategies:
    - MIN_CHURN: Minimize total reassignments (default)

    Returns:
    - 200: Repair successful
    - 409: Concurrent repair in progress (advisory lock)
    - 422: Validation error (drivers not found, plan locked, etc.)
    """
    start_time = time.time()

    try:
        # Import repair engine
        from packs.roster.engine.repair_engine import RepairEngine
        from packs.roster.engine.db import get_connection

        # Validate plan exists and belongs to tenant
        async with db.get_connection() as conn:
            plan = await conn.fetchrow(
                """
                SELECT id, status, forecast_version_id
                FROM plan_versions
                WHERE id = $1 AND tenant_id = $2
                """,
                plan_id,
                tenant.tenant_id,
            )

            if not plan:
                raise HTTPException(
                    status_code=404,
                    detail=f"Plan {plan_id} not found"
                )

            if plan["status"] == "LOCKED":
                raise HTTPException(
                    status_code=422,
                    detail="Cannot repair a locked plan. Create a new plan version first."
                )

        # Try to acquire advisory lock
        lock_key = hashlib.md5(
            f"repair:{tenant.tenant_id}:{plan_id}".encode()
        ).hexdigest()[:8]
        lock_int = int(lock_key, 16)

        async with db.get_connection() as conn:
            lock_acquired = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)",
                lock_int
            )

            if not lock_acquired:
                raise HTTPException(
                    status_code=409,
                    detail="Concurrent repair in progress. Please wait."
                )

            try:
                # Create repair log entry
                repair_log_id = await conn.fetchval(
                    """
                    INSERT INTO repair_logs (
                        plan_version_id, tenant_id, status,
                        absent_driver_ids, strategy, created_at
                    )
                    VALUES ($1, $2, 'RUNNING', $3, $4, NOW())
                    RETURNING id
                    """,
                    plan_id,
                    tenant.tenant_id,
                    payload.absent_driver_ids,
                    payload.strategy,
                )

                # Run repair engine
                engine = RepairEngine(
                    plan_version_id=plan_id,
                    tenant_id=tenant.tenant_id,
                    absent_driver_ids=payload.absent_driver_ids,
                    respect_freeze=payload.respect_freeze,
                    strategy=payload.strategy,
                    time_budget_seconds=payload.time_budget_seconds,
                    seed=payload.seed,
                )

                result = engine.run()

                # Update repair log
                execution_time_ms = int((time.time() - start_time) * 1000)

                await conn.execute(
                    """
                    UPDATE repair_logs
                    SET status = $1,
                        new_plan_version_id = $2,
                        tours_reassigned = $3,
                        drivers_affected = $4,
                        churn_rate = $5,
                        freeze_violations = $6,
                        execution_time_ms = $7,
                        completed_at = NOW()
                    WHERE id = $8
                    """,
                    result.status,
                    result.new_plan_version_id,
                    result.tours_reassigned,
                    result.drivers_affected,
                    result.churn_rate,
                    result.freeze_violations,
                    execution_time_ms,
                    repair_log_id,
                )

                # Build response
                return RepairResponsePayload(
                    repair_log_id=repair_log_id,
                    status=result.status,
                    new_plan_version_id=result.new_plan_version_id,
                    tours_reassigned=result.tours_reassigned,
                    drivers_affected=result.drivers_affected,
                    churn_rate=result.churn_rate,
                    freeze_violations=result.freeze_violations,
                    execution_time_ms=execution_time_ms,
                    reassignments=[
                        TourReassignment(
                            tour_id=str(r.tour_id),
                            from_driver_id=r.from_driver_id,
                            to_driver_id=r.to_driver_id,
                            day=r.day,
                            start_time=r.start_time,
                            reason=r.reason,
                        )
                        for r in result.reassignments
                    ],
                    audit_results=result.audit_results,
                )

            finally:
                # Release advisory lock
                await conn.execute("SELECT pg_advisory_unlock($1)", lock_int)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Repair failed")
        raise HTTPException(
            status_code=500,
            detail=f"Repair failed: {str(e)}"
        )


@router.get("/{plan_id}/repair/{repair_id}", response_model=RepairStatusResponse)
async def get_repair_status(
    plan_id: int,
    repair_id: int,
    db: DatabaseManager = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
):
    """Get status of a repair operation."""
    async with db.get_connection() as conn:
        repair = await conn.fetchrow(
            """
            SELECT id, plan_version_id, status, created_at,
                   completed_at, tours_reassigned, new_plan_version_id
            FROM repair_logs
            WHERE id = $1 AND plan_version_id = $2 AND tenant_id = $3
            """,
            repair_id,
            plan_id,
            tenant.tenant_id,
        )

        if not repair:
            raise HTTPException(
                status_code=404,
                detail=f"Repair {repair_id} not found"
            )

        return RepairStatusResponse(
            repair_log_id=repair["id"],
            plan_version_id=repair["plan_version_id"],
            status=repair["status"],
            created_at=repair["created_at"].isoformat() if repair["created_at"] else "",
            completed_at=repair["completed_at"].isoformat() if repair["completed_at"] else None,
            tours_reassigned=repair["tours_reassigned"] or 0,
            new_plan_version_id=repair["new_plan_version_id"],
        )


@router.get("/{plan_id}/repairs")
async def list_repairs(
    plan_id: int,
    db: DatabaseManager = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
    limit: int = 20,
    offset: int = 0,
):
    """List repair operations for a plan."""
    async with db.get_connection() as conn:
        repairs = await conn.fetch(
            """
            SELECT id, status, created_at, completed_at,
                   tours_reassigned, new_plan_version_id
            FROM repair_logs
            WHERE plan_version_id = $1 AND tenant_id = $2
            ORDER BY created_at DESC
            LIMIT $3 OFFSET $4
            """,
            plan_id,
            tenant.tenant_id,
            limit,
            offset,
        )

        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM repair_logs
            WHERE plan_version_id = $1 AND tenant_id = $2
            """,
            plan_id,
            tenant.tenant_id,
        )

        return {
            "repairs": [
                {
                    "repair_log_id": r["id"],
                    "status": r["status"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                    "tours_reassigned": r["tours_reassigned"] or 0,
                    "new_plan_version_id": r["new_plan_version_id"],
                }
                for r in repairs
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
