"""
SOLVEREIGN V3.3b API - Plans Router
===================================

Solve, audit, lock, and export endpoints.

SECURITY:
- Lock endpoint requires APPROVER role (Entra App Roles)
- Other endpoints use standard tenant auth
"""

from datetime import datetime
from typing import Optional, List
import logging

from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks, status
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_current_tenant, TenantContext
from ..database import DatabaseManager, try_acquire_solve_lock, release_solve_lock
from ..exceptions import (
    PlanNotFoundError,
    ForecastNotFoundError,
    SolveLockError,
    PlanLockedError,
)

# Entra ID authentication with RBAC
from ..security.entra_auth import (
    EntraUserContext,
    get_current_user,
    RequireApprover,
)

logger = logging.getLogger(__name__)


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class SolveRequest(BaseModel):
    """Request to solve a forecast."""
    forecast_version_id: int = Field(..., description="Forecast to solve")
    seed: Optional[int] = Field(94, description="Solver seed for reproducibility")
    run_audit: bool = Field(True, description="Run audit checks after solving")


class SolveResponse(BaseModel):
    """Response after solving."""
    plan_version_id: int
    status: str
    forecast_version_id: int
    seed: int
    output_hash: str
    total_drivers: int
    total_tours: int
    coverage_pct: float
    pt_ratio: float
    max_weekly_hours: float
    audit_passed: Optional[bool] = None
    audit_checks_run: Optional[int] = None
    audit_checks_passed: Optional[int] = None
    duration_seconds: float
    message: str


class PlanStatusResponse(BaseModel):
    """Detailed plan status."""
    id: int
    status: str
    forecast_version_id: int
    seed: int
    output_hash: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    locked_at: Optional[datetime]
    locked_by: Optional[str]
    audit_passed_count: int
    audit_failed_count: int
    error_message: Optional[str]


class PlanKPIsResponse(BaseModel):
    """Plan KPIs."""
    plan_version_id: int
    total_drivers: int
    fte_drivers: int
    pt_drivers: int
    pt_ratio: float
    total_tours: int
    coverage_pct: float
    block_1er: int
    block_2er_reg: int
    block_2er_split: int
    block_3er: int
    avg_weekly_hours: float
    max_weekly_hours: float
    min_weekly_hours: float


class AuditCheckResult(BaseModel):
    """Single audit check result."""
    check_name: str
    status: str
    violation_count: int
    details: Optional[dict] = None


class AuditResponse(BaseModel):
    """Full audit results."""
    plan_version_id: int
    all_passed: bool
    checks_run: int
    checks_passed: int
    checks_failed: int
    results: List[AuditCheckResult]


class LockRequest(BaseModel):
    """Request to lock a plan."""
    locked_by: str = Field(..., min_length=1, description="User or system locking the plan")
    notes: Optional[str] = Field(None, description="Optional lock notes")


class LockResponse(BaseModel):
    """Response after locking."""
    plan_version_id: int
    status: str
    locked_at: datetime
    locked_by: str
    message: str


class ExportResponse(BaseModel):
    """Export metadata."""
    plan_version_id: int
    format: str
    filename: str
    download_url: str
    created_at: datetime


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/solve", response_model=SolveResponse)
async def solve_forecast(
    request: SolveRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    Solve a forecast and create a new plan.

    Uses advisory locks to prevent concurrent solves of the same forecast.
    Returns solver results including KPIs and optional audit results.
    """
    import time
    start_time = time.perf_counter()

    async with db.transaction() as conn:
        # Verify forecast exists and belongs to tenant
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, status, week_anchor_date
                FROM forecast_versions
                WHERE id = %s AND tenant_id = %s
                """,
                (request.forecast_version_id, tenant.tenant_id)
            )
            forecast = await cur.fetchone()

            if not forecast:
                raise ForecastNotFoundError(request.forecast_version_id, tenant.tenant_id)

            if forecast["status"] == "FAIL":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Cannot solve FAIL forecast. Fix parse errors first."
                )

        # Try to acquire advisory lock
        if not await try_acquire_solve_lock(conn, tenant.tenant_id, request.forecast_version_id):
            raise SolveLockError(tenant.tenant_id, request.forecast_version_id)

        try:
            # Import async solver wrappers
            from ..solver_async import (
                solve_forecast_async,
                compute_plan_kpis_async,
                audit_plan_async,
            )

            # Solve (runs in thread pool)
            solve_result = await solve_forecast_async(
                db,
                tenant.tenant_id,
                request.forecast_version_id,
                seed=request.seed,
                run_audit=False,  # We'll run audit separately
            )

            plan_version_id = solve_result["plan_version_id"]

            # Get KPIs
            kpis = await compute_plan_kpis_async(db, tenant.tenant_id, plan_version_id)

            # Run audit if requested
            audit_result = None
            if request.run_audit:
                audit_result = await audit_plan_async(db, tenant.tenant_id, plan_version_id)

            duration = time.perf_counter() - start_time

            return SolveResponse(
                plan_version_id=plan_version_id,
                status=solve_result["status"],
                forecast_version_id=request.forecast_version_id,
                seed=request.seed,
                output_hash=solve_result["output_hash"],
                total_drivers=kpis["total_drivers"],
                total_tours=kpis["total_tours"],
                coverage_pct=kpis["coverage_pct"],
                pt_ratio=kpis["pt_ratio"],
                max_weekly_hours=kpis["max_weekly_hours"],
                audit_passed=audit_result["all_passed"] if audit_result else None,
                audit_checks_run=audit_result["checks_run"] if audit_result else None,
                audit_checks_passed=audit_result["checks_passed"] if audit_result else None,
                duration_seconds=round(duration, 2),
                message=f"Solved in {duration:.2f}s with {kpis['total_drivers']} drivers",
            )

        finally:
            # Always release lock
            await release_solve_lock(conn, tenant.tenant_id, request.forecast_version_id)


@router.get("/{plan_id}", response_model=PlanStatusResponse)
async def get_plan_status(
    plan_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """Get detailed plan status."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    id, status, forecast_version_id, seed, output_hash,
                    created_at, started_at, completed_at, locked_at, locked_by,
                    audit_passed_count, audit_failed_count, error_message
                FROM plan_versions
                WHERE id = %s AND tenant_id = %s
                """,
                (plan_id, tenant.tenant_id)
            )
            row = await cur.fetchone()

            if not row:
                raise PlanNotFoundError(plan_id, tenant.tenant_id)

            return PlanStatusResponse(**row)


@router.get("/{plan_id}/kpis", response_model=PlanKPIsResponse)
async def get_plan_kpis(
    plan_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """Get plan KPIs."""
    from v3.solver_wrapper import compute_plan_kpis

    async with db.connection() as conn:
        # Verify plan exists
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM plan_versions WHERE id = %s AND tenant_id = %s",
                (plan_id, tenant.tenant_id)
            )
            if not await cur.fetchone():
                raise PlanNotFoundError(plan_id, tenant.tenant_id)

        kpis = await compute_plan_kpis(conn, tenant.tenant_id, plan_id)
        return PlanKPIsResponse(plan_version_id=plan_id, **kpis)


@router.get("/{plan_id}/audit", response_model=AuditResponse)
async def get_plan_audit(
    plan_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """Get audit results for a plan."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Verify plan exists
            await cur.execute(
                "SELECT id FROM plan_versions WHERE id = %s AND tenant_id = %s",
                (plan_id, tenant.tenant_id)
            )
            if not await cur.fetchone():
                raise PlanNotFoundError(plan_id, tenant.tenant_id)

            # Get audit results
            await cur.execute(
                """
                SELECT check_name, status, count as violation_count, details_json as details
                FROM audit_log
                WHERE plan_version_id = %s
                ORDER BY created_at
                """,
                (plan_id,)
            )
            rows = await cur.fetchall()

            results = [AuditCheckResult(**r) for r in rows]
            passed = sum(1 for r in results if r.status == "PASS")
            failed = sum(1 for r in results if r.status == "FAIL")

            return AuditResponse(
                plan_version_id=plan_id,
                all_passed=(failed == 0),
                checks_run=len(results),
                checks_passed=passed,
                checks_failed=failed,
                results=results,
            )


@router.post("/{plan_id}/lock", response_model=LockResponse)
async def lock_plan(
    plan_id: int,
    request: LockRequest,
    user: EntraUserContext = Depends(RequireApprover),
    db: DatabaseManager = Depends(get_db),
):
    """
    Lock a plan for production release.

    SECURITY:
    - Requires APPROVER role (Entra App Roles: APPROVER or TENANT_ADMIN)
    - M2M tokens (client credentials) CANNOT lock plans - requires human approval

    Requirements:
    - Plan must be in DRAFT status
    - All audit checks must pass
    - User must have APPROVER role
    """
    # Log the lock attempt
    logger.info(
        "plan_lock_attempt",
        extra={
            "plan_id": plan_id,
            "user_id": user.user_id,
            "tenant_id": user.tenant_id,
            "roles": user.roles,
            "is_app_token": user.is_app_token,
        }
    )

    # M2M tokens cannot lock plans (human approval required)
    if user.is_app_token:
        logger.warning(
            "plan_lock_denied_app_token",
            extra={
                "plan_id": plan_id,
                "app_id": user.app_id,
                "tenant_id": user.tenant_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "APP_TOKEN_NOT_ALLOWED",
                "message": "Plan locking requires human approval. App tokens cannot lock plans.",
            }
        )

    # Use tenant_transaction to ensure RLS is set on THIS connection
    async with db.tenant_transaction(user.tenant_id) as conn:
        async with conn.cursor() as cur:
            # Get plan - RLS enforced + explicit tenant_id filter (defense in depth)
            await cur.execute(
                """
                SELECT id, status, audit_failed_count
                FROM plan_versions
                WHERE id = %s AND tenant_id = %s
                FOR UPDATE
                """,
                (plan_id, user.tenant_id)
            )
            plan = await cur.fetchone()

            if not plan:
                raise PlanNotFoundError(plan_id, user.tenant_id)

            if plan["status"] == "LOCKED":
                raise PlanLockedError(plan_id)

            if plan["status"] != "DRAFT":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot lock plan in {plan['status']} status. Must be DRAFT."
                )

            if plan["audit_failed_count"] > 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot lock plan with {plan['audit_failed_count']} failed audits."
                )

            # Use user info from JWT for locked_by (not from request body for security)
            locked_by = user.email or user.name or user.user_id

            # Lock the plan
            await cur.execute(
                """
                UPDATE plan_versions
                SET status = 'LOCKED', locked_at = NOW(), locked_by = %s, notes = %s
                WHERE id = %s
                RETURNING locked_at
                """,
                (locked_by, request.notes, plan_id)
            )
            result = await cur.fetchone()

            # Supersede previous locked plan for same forecast
            await cur.execute(
                """
                UPDATE plan_versions
                SET status = 'SUPERSEDED'
                WHERE forecast_version_id = (SELECT forecast_version_id FROM plan_versions WHERE id = %s)
                  AND status = 'LOCKED'
                  AND id != %s
                """,
                (plan_id, plan_id)
            )

            logger.info(
                "plan_locked",
                extra={
                    "plan_id": plan_id,
                    "locked_by": locked_by,
                    "tenant_id": user.tenant_id,
                    "user_id": user.user_id,
                }
            )

            return LockResponse(
                plan_version_id=plan_id,
                status="LOCKED",
                locked_at=result["locked_at"],
                locked_by=locked_by,
                message=f"Plan {plan_id} locked successfully by {locked_by}",
            )


@router.get("/{plan_id}/export/{format}")
async def export_plan(
    plan_id: int,
    format: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Export plan in specified format.

    Supported formats:
    - csv: Roster matrix CSV
    - json: Full plan JSON
    - proof: Proof pack ZIP
    """
    if format not in ("csv", "json", "proof"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: {format}. Use: csv, json, proof"
        )

    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, status FROM plan_versions WHERE id = %s AND tenant_id = %s",
                (plan_id, tenant.tenant_id)
            )
            plan = await cur.fetchone()

            if not plan:
                raise PlanNotFoundError(plan_id, tenant.tenant_id)

    # TODO: Implement actual export logic
    # For now, return metadata
    return ExportResponse(
        plan_version_id=plan_id,
        format=format,
        filename=f"plan_{plan_id}.{format}",
        download_url=f"/api/v1/plans/{plan_id}/download/{format}",
        created_at=datetime.now(),
    )
