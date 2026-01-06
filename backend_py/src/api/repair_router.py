"""
SOLVEREIGN V3.3b - Repair API Router
=====================================

POST /api/v1/plans/{pv_id}/repair

Requirements:
- Deterministic (sorted candidate lists, tie-breaker: lowest driver_id)
- Tenant-scoped (RLS via app.current_tenant_id)
- Advisory lock (prevents concurrent repair on same plan)
- Idempotent (X-Idempotency-Key header)
- Auditable (repair_log + audit_log entries)
- Proper error codes (409/422, not 500)

Status Machine: Creates NEW plan_version, does NOT patch existing.
"""

import time
import json
import hashlib
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header, Request, Depends
from pydantic import BaseModel, Field

# V3 imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from v3.db import get_connection
from v3.driver_model import (
    RepairRequest,
    RepairResult,
    RepairStatus,
    RepairStrategy,
    validate_driver_ids_exist,
    create_repair_log,
    update_repair_log,
)
from v3.repair_engine import RepairEngine

logger = logging.getLogger(__name__)

repair_router = APIRouter(tags=["repair"])


# =============================================================================
# PYDANTIC MODELS
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


class RepairResponsePayload(BaseModel):
    """Response payload for repair endpoint."""
    repair_log_id: int
    status: str
    new_plan_version_id: Optional[int] = None
    tours_reassigned: int = 0
    drivers_affected: int = 0
    churn_rate: float = 0.0
    freeze_violations: int = 0
    execution_time_ms: int = 0
    error_message: Optional[str] = None
    audit_results: Optional[dict] = None


# =============================================================================
# DEPENDENCIES
# =============================================================================

def get_tenant_id(request: Request) -> str:
    """
    Extract tenant ID from request.
    In production, this comes from JWT claims or API key.
    For MVP, use header or default.
    """
    # Check for tenant header (development/testing)
    tenant_id = request.headers.get("X-Tenant-ID")
    if tenant_id:
        return tenant_id

    # Default tenant for backward compatibility
    return "00000000-0000-0000-0000-000000000001"


def get_user_id(request: Request) -> Optional[str]:
    """Extract user ID for audit trail."""
    return request.headers.get("X-User-ID", "system")


# =============================================================================
# ADVISORY LOCK HELPERS
# =============================================================================

def compute_advisory_lock_key(tenant_id: str, plan_version_id: int) -> int:
    """
    Compute advisory lock key from tenant + plan.
    Uses hash to ensure consistent key within int64 range.
    """
    lock_string = f"{tenant_id}:{plan_version_id}"
    hash_bytes = hashlib.sha256(lock_string.encode()).digest()
    # Use first 8 bytes as int64
    lock_key = int.from_bytes(hash_bytes[:8], byteorder='big', signed=True)
    return lock_key


def try_advisory_lock(conn, lock_key: int) -> bool:
    """Try to acquire advisory lock (non-blocking)."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
        return cur.fetchone()['pg_try_advisory_lock']


def release_advisory_lock(conn, lock_key: int):
    """Release advisory lock."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))


# =============================================================================
# IDEMPOTENCY HELPERS
# =============================================================================

def check_idempotency(tenant_id: str, idempotency_key: str) -> Optional[dict]:
    """
    Check if this idempotency key was already processed.
    Returns previous result if found.
    """
    if not idempotency_key:
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id as repair_log_id,
                    status,
                    result_plan_id as new_plan_version_id,
                    tours_reassigned,
                    drivers_affected,
                    churn_rate,
                    freeze_violations,
                    execution_time_ms,
                    error_message
                FROM repair_log
                WHERE tenant_id = %s AND idempotency_key = %s
            """, (tenant_id, idempotency_key))
            row = cur.fetchone()

            if row:
                return dict(row)
    return None


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_plan_exists_and_not_locked(plan_version_id: int, tenant_id: str) -> dict:
    """
    Validate plan exists and is not LOCKED.
    Returns plan data or raises HTTPException.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, status, forecast_version_id, tenant_id
                FROM plan_versions
                WHERE id = %s
            """, (plan_version_id,))
            plan = cur.fetchone()

            if not plan:
                raise HTTPException(
                    status_code=404,
                    detail=f"Plan version {plan_version_id} not found"
                )

            # Check tenant isolation
            if str(plan['tenant_id']) != tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: plan belongs to different tenant"
                )

            if plan['status'] == 'LOCKED':
                raise HTTPException(
                    status_code=409,
                    detail="Cannot repair LOCKED plan. Create a new plan version."
                )

            return dict(plan)


def validate_absent_drivers(tenant_id: str, absent_driver_ids: List[int]) -> None:
    """
    Validate all absent driver IDs exist and belong to tenant.
    Raises HTTPException on validation failure.
    """
    if not absent_driver_ids:
        raise HTTPException(
            status_code=422,
            detail="absent_driver_ids cannot be empty"
        )

    invalid_ids = validate_driver_ids_exist(tenant_id, absent_driver_ids)
    if invalid_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid driver IDs: {invalid_ids}"
        )


# =============================================================================
# TENANT CONTEXT FOR RLS
# =============================================================================

def set_tenant_context(conn, tenant_id: str):
    """Set tenant context for RLS policies."""
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id', %s, true)", (tenant_id,))


# =============================================================================
# REPAIR ENDPOINT
# =============================================================================

@repair_router.post(
    "/plans/{pv_id}/repair",
    response_model=RepairResponsePayload,
    responses={
        200: {"description": "Repair successful, new plan created"},
        404: {"description": "Plan not found"},
        409: {"description": "Plan is LOCKED or concurrent repair in progress"},
        422: {"description": "Validation error (invalid drivers, empty list, etc.)"},
    }
)
async def repair_plan(
    pv_id: int,
    payload: RepairRequestPayload,
    request: Request,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    tenant_id: str = Depends(get_tenant_id),
    user_id: str = Depends(get_user_id),
):
    """
    Repair a plan by reassigning tours from absent drivers.

    Creates a NEW plan_version (does not modify the original).

    **Algorithm**: MIN_CHURN (minimize reassignments)
    - Sort tours by (day, start_ts, tour_instance_id)
    - For each affected tour, find valid candidates
    - Select lowest driver_id (deterministic tie-breaker)

    **Constraints enforced**:
    - No overlap
    - Rest >= 11h between blocks
    - Span rules (14h regular, 16h split/3er)
    - Freeze window (12h before tour start)
    - Fatigue (no 3er->3er on consecutive days)
    - Skills (driver must have tour.skill)
    - Max weekly hours (driver.max_weekly_hours)

    **Returns**:
    - new_plan_version_id: The repaired plan
    - tours_reassigned: Number of tours moved to different drivers
    - drivers_affected: Number of drivers with changed schedules
    - churn_rate: tours_reassigned / total_tours
    """
    start_time = time.time()

    logger.info(
        "Repair request received",
        extra={
            "plan_version_id": pv_id,
            "tenant_id": tenant_id,
            "absent_driver_count": len(payload.absent_driver_ids),
            "idempotency_key": x_idempotency_key,
        }
    )

    # ------------------------------------------------------------------
    # 1. Idempotency Check
    # ------------------------------------------------------------------
    if x_idempotency_key:
        existing = check_idempotency(tenant_id, x_idempotency_key)
        if existing:
            logger.info(
                "Returning cached idempotent response",
                extra={"repair_log_id": existing['repair_log_id']}
            )
            return RepairResponsePayload(**existing)

    # ------------------------------------------------------------------
    # 2. Validate Plan Exists and Not LOCKED
    # ------------------------------------------------------------------
    plan = validate_plan_exists_and_not_locked(pv_id, tenant_id)

    # ------------------------------------------------------------------
    # 3. Validate Absent Driver IDs
    # ------------------------------------------------------------------
    validate_absent_drivers(tenant_id, payload.absent_driver_ids)

    # ------------------------------------------------------------------
    # 4. Parse Strategy
    # ------------------------------------------------------------------
    try:
        strategy = RepairStrategy(payload.strategy)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid strategy: {payload.strategy}. Supported: MIN_CHURN"
        )

    # ------------------------------------------------------------------
    # 5. Acquire Advisory Lock (Prevent Concurrent Repairs)
    # ------------------------------------------------------------------
    lock_key = compute_advisory_lock_key(tenant_id, pv_id)

    with get_connection() as conn:
        # Set tenant context for RLS
        set_tenant_context(conn, tenant_id)

        # Try to acquire lock
        if not try_advisory_lock(conn, lock_key):
            raise HTTPException(
                status_code=409,
                detail="Concurrent repair in progress for this plan. Try again later."
            )

        try:
            # ------------------------------------------------------------------
            # 6. Create Repair Request
            # ------------------------------------------------------------------
            repair_request = RepairRequest(
                plan_version_id=pv_id,
                absent_driver_ids=payload.absent_driver_ids,
                respect_freeze=payload.respect_freeze,
                strategy=strategy,
                time_budget_seconds=payload.time_budget_seconds,
                seed=payload.seed,
                idempotency_key=x_idempotency_key,
            )

            # ------------------------------------------------------------------
            # 7. Create Repair Log Entry (PENDING)
            # ------------------------------------------------------------------
            repair_log_id = create_repair_log(
                tenant_id=tenant_id,
                request=repair_request,
                requested_by=user_id
            )

            logger.info(
                "Created repair log entry",
                extra={"repair_log_id": repair_log_id, "status": "PENDING"}
            )

            # ------------------------------------------------------------------
            # 8. Execute Repair Engine
            # ------------------------------------------------------------------
            engine = RepairEngine(tenant_id=tenant_id)
            result = engine.repair(repair_request)

            # Update result with repair_log_id
            result.repair_log_id = repair_log_id
            result.execution_time_ms = int((time.time() - start_time) * 1000)

            # ------------------------------------------------------------------
            # 9. Update Repair Log with Result
            # ------------------------------------------------------------------
            update_repair_log(repair_log_id, result)

            logger.info(
                "Repair completed",
                extra={
                    "repair_log_id": repair_log_id,
                    "status": result.status.value,
                    "new_plan_version_id": result.new_plan_version_id,
                    "tours_reassigned": result.tours_reassigned,
                    "execution_time_ms": result.execution_time_ms,
                }
            )

            # ------------------------------------------------------------------
            # 10. Return Response
            # ------------------------------------------------------------------
            return RepairResponsePayload(
                repair_log_id=result.repair_log_id,
                status=result.status.value,
                new_plan_version_id=result.new_plan_version_id,
                tours_reassigned=result.tours_reassigned,
                drivers_affected=result.drivers_affected,
                churn_rate=result.churn_rate,
                freeze_violations=result.freeze_violations,
                execution_time_ms=result.execution_time_ms,
                error_message=result.error_message,
                audit_results=result.audit_results,
            )

        finally:
            # Always release the advisory lock
            release_advisory_lock(conn, lock_key)


# =============================================================================
# DRIVER MANAGEMENT ENDPOINTS (Optional MVP Support)
# =============================================================================

class DriverCreatePayload(BaseModel):
    """Payload for creating a driver."""
    external_ref: str = Field(..., description="External reference ID")
    display_name: Optional[str] = None
    home_depot: Optional[str] = None
    max_weekly_hours: float = Field(default=55.0, ge=0, le=60)


class DriverAvailabilityPayload(BaseModel):
    """Payload for setting driver availability."""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    status: str = Field(..., description="AVAILABLE, SICK, VACATION, or BLOCKED")
    note: Optional[str] = None


@repair_router.get("/drivers")
async def list_drivers(
    active_only: bool = True,
    depot: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """List drivers for the tenant."""
    from v3.driver_model import get_drivers

    drivers = get_drivers(tenant_id, active_only=active_only, depot=depot)
    return {
        "drivers": [
            {
                "id": d.id,
                "external_ref": d.external_ref,
                "display_name": d.display_name,
                "home_depot": d.home_depot,
                "is_active": d.is_active,
                "max_weekly_hours": float(d.max_weekly_hours),
            }
            for d in drivers
        ],
        "count": len(drivers),
    }


@repair_router.post("/drivers")
async def create_driver(
    payload: DriverCreatePayload,
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a new driver."""
    from decimal import Decimal
    from v3.driver_model import create_driver

    driver = create_driver(
        tenant_id=tenant_id,
        external_ref=payload.external_ref,
        display_name=payload.display_name,
        home_depot=payload.home_depot,
        max_weekly_hours=Decimal(str(payload.max_weekly_hours)),
    )

    return {
        "id": driver.id,
        "external_ref": driver.external_ref,
        "display_name": driver.display_name,
        "home_depot": driver.home_depot,
        "max_weekly_hours": float(driver.max_weekly_hours),
    }


@repair_router.post("/drivers/{driver_id}/availability")
async def set_availability(
    driver_id: int,
    payload: DriverAvailabilityPayload,
    tenant_id: str = Depends(get_tenant_id),
    user_id: str = Depends(get_user_id),
):
    """Set driver availability for a specific date."""
    from datetime import datetime
    from v3.driver_model import set_driver_availability, AvailabilityStatus

    try:
        status = AvailabilityStatus(payload.status)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status: {payload.status}. Valid: AVAILABLE, SICK, VACATION, BLOCKED"
        )

    try:
        avail_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid date format. Use YYYY-MM-DD"
        )

    availability = set_driver_availability(
        tenant_id=tenant_id,
        driver_id=driver_id,
        availability_date=avail_date,
        status=status,
        note=payload.note,
        source="api",
        reported_by=user_id,
    )

    return {
        "id": availability.id,
        "driver_id": availability.driver_id,
        "date": str(availability.date),
        "status": availability.status.value,
        "note": availability.note,
    }


# =============================================================================
# REPAIR HISTORY ENDPOINT
# =============================================================================

@repair_router.get("/plans/{pv_id}/repairs")
async def get_repair_history(
    pv_id: int,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get repair history for a plan."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id, parent_plan_id, result_plan_id,
                    absent_driver_ids, status, error_message,
                    tours_reassigned, drivers_affected, churn_rate,
                    freeze_violations, execution_time_ms,
                    requested_at, completed_at, requested_by
                FROM repair_log
                WHERE tenant_id = %s AND parent_plan_id = %s
                ORDER BY requested_at DESC
            """, (tenant_id, pv_id))
            rows = cur.fetchall()

            return {
                "plan_version_id": pv_id,
                "repairs": [dict(r) for r in rows],
                "count": len(rows),
            }
