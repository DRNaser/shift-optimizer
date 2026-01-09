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

from ..dependencies import get_db, get_current_tenant, TenantContext, require_tenant_not_blocked, is_scope_blocked
from ..database import DatabaseManager, try_acquire_solve_lock, release_solve_lock
from ..exceptions import (
    PlanNotFoundError,
    ForecastNotFoundError,
    SolveLockError,
    PlanLockedError,
    ServiceBlockedError,
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
# STATE MACHINE SCHEMAS (V3.4 SaaS)
# =============================================================================

class ApproveRequest(BaseModel):
    """Request to approve a solved plan."""
    reason: Optional[str] = Field(None, description="Approval reason/notes")


class PublishRequest(BaseModel):
    """Request to publish an approved plan."""
    reason: Optional[str] = Field(None, description="Publish reason/notes")
    kpi_snapshot: Optional[dict] = Field(None, description="KPI snapshot at publish time")
    # V3.7.2: Force during freeze window
    force_during_freeze: bool = Field(False, description="Force publish during active freeze window")
    force_reason: Optional[str] = Field(None, min_length=10, description="Required reason when forcing during freeze (min 10 chars)")


class RejectRequest(BaseModel):
    """Request to reject a plan."""
    reason: str = Field(..., min_length=1, description="Rejection reason (required)")


class PlanStateResponse(BaseModel):
    """Response after state transition."""
    plan_version_id: int
    previous_state: str
    new_state: str
    transitioned_by: str
    transitioned_at: datetime
    reason: Optional[str] = None
    success: bool
    message: str


class PlanStateInfo(BaseModel):
    """Full plan state information."""
    plan_version_id: int
    plan_state: str
    can_modify: bool
    is_frozen: bool
    created_at: datetime
    state_changed_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None
    # V3.7: Versioning fields
    current_snapshot_id: Optional[int] = None
    publish_count: int = 0
    freeze_until: Optional[datetime] = None


class SnapshotInfo(BaseModel):
    """Published snapshot information."""
    snapshot_id: str
    version_number: int
    status: str
    published_at: datetime
    published_by: str
    publish_reason: Optional[str] = None
    freeze_until: datetime
    is_frozen: bool
    is_legacy: bool = False  # V3.7.2: True if snapshot has empty payload (pre-V3.7.2)
    kpis: Optional[dict] = None
    hashes: Optional[dict] = None


class SnapshotHistoryResponse(BaseModel):
    """List of published snapshots for a plan."""
    plan_version_id: int
    snapshots: List[SnapshotInfo]
    active_version: Optional[int] = None


class RepairRequest(BaseModel):
    """Request to create a repair version from a published snapshot."""
    reason: str = Field(..., min_length=1, description="Repair reason (required for audit trail)")


class RepairResponse(BaseModel):
    """Response after creating a repair version."""
    new_plan_version_id: int
    source_snapshot_id: int
    source_version_number: int
    freeze_window_active: bool
    created_by: str
    created_at: datetime
    success: bool
    message: str


class PublishSnapshotResponse(BaseModel):
    """Response after publishing (creating snapshot)."""
    plan_version_id: int
    snapshot_id: int
    version_number: int
    published_by: str
    freeze_until: datetime
    previous_state: str
    new_state: str
    success: bool
    message: str
    # V3.7.2: Force tracking
    forced_during_freeze: bool = False


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/solve", response_model=SolveResponse)
async def solve_forecast(
    request: SolveRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_tenant_not_blocked("tenant")),
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
    - Blocked if tenant has active S0/S1 escalation

    Requirements:
    - Plan must be in DRAFT status
    - All audit checks must pass
    - User must have APPROVER role
    - Tenant scope must not be blocked
    """
    # Check if tenant scope is blocked (Fix C: write-block enforcement)
    blocked = await is_scope_blocked(db, "tenant", str(user.tenant_id))
    if blocked:
        raise ServiceBlockedError(
            scope_type="tenant",
            scope_id=str(user.tenant_id)
        )

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


# =============================================================================
# STATE MACHINE ENDPOINTS (V3.4 SaaS)
# =============================================================================

@router.get("/{plan_id}/state", response_model=PlanStateInfo)
async def get_plan_state(
    plan_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Get full plan state information.

    V3.7: Includes versioning fields (snapshot_id, publish_count, freeze_until).

    Returns the current state and whether the plan can be modified or is frozen.
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    pv.id as plan_version_id,
                    COALESCE(pv.plan_state, 'DRAFT') as plan_state,
                    pv.created_at,
                    pv.plan_state_changed_at as state_changed_at,
                    pv.current_snapshot_id,
                    COALESCE(pv.publish_count, 0) as publish_count,
                    pv.freeze_until,
                    pa_approve.performed_by as approved_by,
                    pa_approve.created_at as approved_at,
                    pa_publish.performed_by as published_by,
                    pa_publish.created_at as published_at
                FROM plan_versions pv
                LEFT JOIN plan_approvals pa_approve
                    ON pv.id = pa_approve.plan_version_id AND pa_approve.to_state = 'APPROVED'
                LEFT JOIN plan_approvals pa_publish
                    ON pv.id = pa_publish.plan_version_id AND pa_publish.to_state = 'PUBLISHED'
                WHERE pv.id = %s AND pv.tenant_id = %s
                """,
                (plan_id, tenant.tenant_id)
            )
            row = await cur.fetchone()

            if not row:
                raise PlanNotFoundError(plan_id, tenant.tenant_id)

            plan_state = row["plan_state"]

            # Determine if plan can be modified (V3.7: PUBLISHED plans CAN be modified now!)
            # Only snapshots are immutable, not the working plan
            can_modify = plan_state not in ("SOLVING",)  # Only block during active solve

            # Check if in freeze window
            freeze_until = row.get("freeze_until")
            is_frozen = False
            if freeze_until and freeze_until > datetime.now():
                is_frozen = True

            return PlanStateInfo(
                plan_version_id=row["plan_version_id"],
                plan_state=plan_state,
                can_modify=can_modify,
                is_frozen=is_frozen,
                created_at=row["created_at"],
                state_changed_at=row["state_changed_at"],
                approved_by=row["approved_by"],
                approved_at=row["approved_at"],
                published_by=row["published_by"],
                published_at=row["published_at"],
                current_snapshot_id=row.get("current_snapshot_id"),
                publish_count=row.get("publish_count", 0),
                freeze_until=freeze_until,
            )


@router.post("/{plan_id}/approve", response_model=PlanStateResponse)
async def approve_plan(
    plan_id: int,
    request: ApproveRequest,
    user: EntraUserContext = Depends(RequireApprover),
    db: DatabaseManager = Depends(get_db),
):
    """
    Approve a solved plan.

    SECURITY:
    - Requires APPROVER role (Entra App Roles)
    - M2M tokens CANNOT approve plans - requires human approval
    - Plan must be in SOLVED state
    - All audits must pass

    State transition: SOLVED → APPROVED
    """
    # Check if tenant scope is blocked
    blocked = await is_scope_blocked(db, "tenant", str(user.tenant_id))
    if blocked:
        raise ServiceBlockedError(scope_type="tenant", scope_id=str(user.tenant_id))

    # M2M tokens cannot approve plans
    if user.is_app_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "APP_TOKEN_NOT_ALLOWED",
                "message": "Plan approval requires human review. App tokens cannot approve plans.",
            }
        )

    performed_by = user.email or user.name or user.user_id

    async with db.tenant_transaction(user.tenant_id) as conn:
        async with conn.cursor() as cur:
            # Get current plan state
            await cur.execute(
                """
                SELECT id, COALESCE(plan_state, 'DRAFT') as plan_state, audit_failed_count
                FROM plan_versions
                WHERE id = %s AND tenant_id = %s
                FOR UPDATE
                """,
                (plan_id, user.tenant_id)
            )
            plan = await cur.fetchone()

            if not plan:
                raise PlanNotFoundError(plan_id, user.tenant_id)

            if plan["plan_state"] != "SOLVED":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot approve plan in {plan['plan_state']} state. Must be SOLVED."
                )

            if plan["audit_failed_count"] and plan["audit_failed_count"] > 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot approve plan with {plan['audit_failed_count']} failed audits."
                )

            # Transition state
            await cur.execute(
                """
                UPDATE plan_versions
                SET plan_state = 'APPROVED', plan_state_changed_at = NOW()
                WHERE id = %s
                """,
                (plan_id,)
            )

            # Record approval in audit trail
            await cur.execute(
                """
                INSERT INTO plan_approvals (plan_version_id, from_state, to_state, performed_by, reason)
                VALUES (%s, %s, 'APPROVED', %s, %s)
                """,
                (plan_id, plan["plan_state"], performed_by, request.reason)
            )

            logger.info(
                "plan_approved",
                extra={
                    "plan_id": plan_id,
                    "approved_by": performed_by,
                    "tenant_id": user.tenant_id,
                }
            )

            return PlanStateResponse(
                plan_version_id=plan_id,
                previous_state=plan["plan_state"],
                new_state="APPROVED",
                transitioned_by=performed_by,
                transitioned_at=datetime.now(),
                reason=request.reason,
                success=True,
                message=f"Plan {plan_id} approved by {performed_by}",
            )


@router.post("/{plan_id}/publish", response_model=PublishSnapshotResponse)
async def publish_plan(
    plan_id: int,
    request: PublishRequest,
    user: EntraUserContext = Depends(RequireApprover),
    db: DatabaseManager = Depends(get_db),
):
    """
    Publish an approved plan for production use.

    V3.7: Creates an IMMUTABLE SNAPSHOT via publish_plan_snapshot() function.

    SECURITY:
    - Requires APPROVER role (Entra App Roles)
    - M2M tokens CANNOT publish plans - requires human approval
    - Plan must be in APPROVED state

    State transition: APPROVED → PUBLISHED

    Once published:
    - An immutable snapshot is created in plan_snapshots table
    - Working plan (plan_versions) can still be modified/re-solved
    - Only the snapshot is immutable
    - 12-hour freeze window starts for driver notification
    """
    # Check if tenant scope is blocked
    blocked = await is_scope_blocked(db, "tenant", str(user.tenant_id))
    if blocked:
        raise ServiceBlockedError(scope_type="tenant", scope_id=str(user.tenant_id))

    # M2M tokens cannot publish plans
    if user.is_app_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "APP_TOKEN_NOT_ALLOWED",
                "message": "Plan publishing requires human approval. App tokens cannot publish plans.",
            }
        )

    performed_by = user.email or user.name or user.user_id

    async with db.tenant_transaction(user.tenant_id) as conn:
        async with conn.cursor() as cur:
            # Verify plan exists and belongs to tenant
            await cur.execute(
                """
                SELECT id, COALESCE(plan_state, 'DRAFT') as plan_state
                FROM plan_versions
                WHERE id = %s AND tenant_id = %s
                """,
                (plan_id, user.tenant_id)
            )
            plan = await cur.fetchone()

            if not plan:
                raise PlanNotFoundError(plan_id, user.tenant_id)

            previous_state = plan["plan_state"]

            # V3.7.2: Build snapshot payload from DB (assignments + routes)
            await cur.execute(
                "SELECT build_snapshot_payload(%s) AS payload",
                (plan_id,)
            )
            payload_result = await cur.fetchone()
            snapshot_payload = payload_result["payload"] if payload_result else {}

            assignments_snapshot = snapshot_payload.get("assignments", [])
            routes_snapshot = snapshot_payload.get("routes", {})

            # Call DB function to create immutable snapshot
            import json
            kpi_json = json.dumps(request.kpi_snapshot) if request.kpi_snapshot else '{}'
            assignments_json = json.dumps(assignments_snapshot)
            routes_json = json.dumps(routes_snapshot)

            # V3.7.2: Include force parameters for freeze window override
            await cur.execute(
                """
                SELECT publish_plan_snapshot(
                    %s,  -- p_plan_version_id
                    %s,  -- p_published_by
                    %s,  -- p_publish_reason
                    %s::jsonb,  -- p_kpi_snapshot
                    %s::jsonb,  -- p_assignments_snapshot
                    %s::jsonb,  -- p_routes_snapshot
                    %s,  -- p_force_during_freeze
                    %s   -- p_force_reason
                ) AS result
                """,
                (plan_id, performed_by, request.reason, kpi_json,
                 assignments_json, routes_json,
                 request.force_during_freeze, request.force_reason)
            )
            result = await cur.fetchone()
            publish_result = result["result"]

            if not publish_result.get("success"):
                error_msg = publish_result.get("error", "Unknown error")

                # V3.7.2: Check if blocked by freeze window
                if "freeze window" in error_msg.lower():
                    logger.warning(
                        "plan_publish_blocked_freeze",
                        extra={
                            "plan_id": plan_id,
                            "freeze_until": publish_result.get("freeze_until"),
                            "minutes_remaining": publish_result.get("minutes_remaining"),
                            "tenant_id": user.tenant_id,
                        }
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error": "FREEZE_WINDOW_ACTIVE",
                            "message": error_msg,
                            "freeze_until": str(publish_result.get("freeze_until")),
                            "minutes_remaining": publish_result.get("minutes_remaining"),
                            "hint": publish_result.get("hint", "Use force_during_freeze=true with force_reason"),
                        }
                    )

                logger.error(
                    "plan_publish_failed",
                    extra={
                        "plan_id": plan_id,
                        "error": error_msg,
                        "tenant_id": user.tenant_id,
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=error_msg
                )

            logger.info(
                "plan_published",
                extra={
                    "plan_id": plan_id,
                    "snapshot_id": publish_result.get("snapshot_id"),
                    "version_number": publish_result.get("version_number"),
                    "published_by": performed_by,
                    "tenant_id": user.tenant_id,
                    "has_kpi_snapshot": request.kpi_snapshot is not None,
                }
            )

            # Parse freeze_until from result
            freeze_until_str = publish_result.get("freeze_until")
            if isinstance(freeze_until_str, str):
                from datetime import datetime as dt
                freeze_until = dt.fromisoformat(freeze_until_str.replace('Z', '+00:00'))
            else:
                freeze_until = freeze_until_str or datetime.now()

            return PublishSnapshotResponse(
                plan_version_id=plan_id,
                snapshot_id=publish_result.get("snapshot_id"),
                version_number=publish_result.get("version_number"),
                published_by=performed_by,
                freeze_until=freeze_until,
                previous_state=previous_state,
                new_state="PUBLISHED",
                success=True,
                message=publish_result.get("message", f"Plan {plan_id} published as version {publish_result.get('version_number')}"),
                forced_during_freeze=publish_result.get("forced_during_freeze", False),
            )


@router.post("/{plan_id}/reject", response_model=PlanStateResponse)
async def reject_plan(
    plan_id: int,
    request: RejectRequest,
    user: EntraUserContext = Depends(RequireApprover),
    db: DatabaseManager = Depends(get_db),
):
    """
    Reject a plan.

    SECURITY:
    - Requires APPROVER role (Entra App Roles)
    - Reason is required for audit trail

    Can reject plans in: SOLVED, APPROVED states
    State transition: SOLVED/APPROVED → REJECTED
    """
    # Check if tenant scope is blocked
    blocked = await is_scope_blocked(db, "tenant", str(user.tenant_id))
    if blocked:
        raise ServiceBlockedError(scope_type="tenant", scope_id=str(user.tenant_id))

    performed_by = user.email or user.name or user.user_id

    async with db.tenant_transaction(user.tenant_id) as conn:
        async with conn.cursor() as cur:
            # Get current plan state
            await cur.execute(
                """
                SELECT id, COALESCE(plan_state, 'DRAFT') as plan_state
                FROM plan_versions
                WHERE id = %s AND tenant_id = %s
                FOR UPDATE
                """,
                (plan_id, user.tenant_id)
            )
            plan = await cur.fetchone()

            if not plan:
                raise PlanNotFoundError(plan_id, user.tenant_id)

            if plan["plan_state"] not in ("SOLVED", "APPROVED"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot reject plan in {plan['plan_state']} state. Must be SOLVED or APPROVED."
                )

            # Transition state
            await cur.execute(
                """
                UPDATE plan_versions
                SET plan_state = 'REJECTED', plan_state_changed_at = NOW()
                WHERE id = %s
                """,
                (plan_id,)
            )

            # Record rejection in audit trail
            await cur.execute(
                """
                INSERT INTO plan_approvals (plan_version_id, from_state, to_state, performed_by, reason)
                VALUES (%s, %s, 'REJECTED', %s, %s)
                """,
                (plan_id, plan["plan_state"], performed_by, request.reason)
            )

            logger.warning(
                "plan_rejected",
                extra={
                    "plan_id": plan_id,
                    "rejected_by": performed_by,
                    "tenant_id": user.tenant_id,
                    "reason": request.reason,
                }
            )

            return PlanStateResponse(
                plan_version_id=plan_id,
                previous_state=plan["plan_state"],
                new_state="REJECTED",
                transitioned_by=performed_by,
                transitioned_at=datetime.now(),
                reason=request.reason,
                success=True,
                message=f"Plan {plan_id} rejected by {performed_by}: {request.reason}",
            )


# =============================================================================
# VERSIONING ENDPOINTS (V3.7 SaaS - Plan Snapshots)
# =============================================================================

@router.get("/{plan_id}/snapshots", response_model=SnapshotHistoryResponse)
async def get_snapshot_history(
    plan_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Get all published snapshots for a plan.

    Returns version history showing all published versions, their status,
    and whether they are currently frozen.
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Verify plan exists
            await cur.execute(
                "SELECT id FROM plan_versions WHERE id = %s AND tenant_id = %s",
                (plan_id, tenant.tenant_id)
            )
            if not await cur.fetchone():
                raise PlanNotFoundError(plan_id, tenant.tenant_id)

            # Get snapshot history via DB function
            await cur.execute(
                "SELECT get_snapshot_history(%s) AS snapshots",
                (plan_id,)
            )
            result = await cur.fetchone()
            snapshots_json = result["snapshots"] or []

            # Transform to response model
            snapshots = []
            active_version = None

            for s in snapshots_json:
                is_frozen = s.get("is_frozen", False)
                status = s.get("status", "ACTIVE")

                if status == "ACTIVE":
                    active_version = s.get("version_number")

                # Parse datetime strings
                published_at = s.get("published_at")
                if isinstance(published_at, str):
                    from datetime import datetime as dt
                    published_at = dt.fromisoformat(published_at.replace('Z', '+00:00'))

                freeze_until = s.get("freeze_until")
                if isinstance(freeze_until, str):
                    from datetime import datetime as dt
                    freeze_until = dt.fromisoformat(freeze_until.replace('Z', '+00:00'))

                snapshots.append(SnapshotInfo(
                    snapshot_id=str(s.get("snapshot_id")),
                    version_number=s.get("version_number"),
                    status=status,
                    published_at=published_at,
                    published_by=s.get("published_by"),
                    publish_reason=s.get("publish_reason"),
                    freeze_until=freeze_until,
                    is_frozen=is_frozen,
                    is_legacy=s.get("is_legacy", False),
                    kpis=s.get("kpis"),
                    hashes=s.get("hashes"),
                ))

            return SnapshotHistoryResponse(
                plan_version_id=plan_id,
                snapshots=snapshots,
                active_version=active_version,
            )


@router.get("/{plan_id}/freeze-status")
async def get_freeze_status(
    plan_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db),
):
    """
    Check if plan has an active frozen snapshot.

    Returns freeze window details including remaining time.
    Used by UI to show warning before allowing repair during freeze window.
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Verify plan exists
            await cur.execute(
                "SELECT id FROM plan_versions WHERE id = %s AND tenant_id = %s",
                (plan_id, tenant.tenant_id)
            )
            if not await cur.fetchone():
                raise PlanNotFoundError(plan_id, tenant.tenant_id)

            # Get freeze status via DB function
            await cur.execute(
                "SELECT is_plan_frozen(%s) AS status",
                (plan_id,)
            )
            result = await cur.fetchone()
            freeze_status = result["status"]

            return {
                "plan_version_id": plan_id,
                **freeze_status
            }


@router.post("/{plan_id}/repair", response_model=RepairResponse)
async def create_repair_version(
    plan_id: int,
    request: RepairRequest,
    user: EntraUserContext = Depends(RequireApprover),
    db: DatabaseManager = Depends(get_db),
):
    """
    Create a new draft plan from the current published snapshot.

    V3.7: Repair flow for when dispatcher finds issues after publish.

    SECURITY:
    - Requires APPROVER role (Entra App Roles)
    - M2M tokens CANNOT create repairs - requires human decision
    - Plan must have an ACTIVE published snapshot

    FLOW:
    1. Get the active snapshot for this plan
    2. Create new plan_versions row in DRAFT state
    3. New plan can be re-solved, approved, published independently
    4. Original snapshot remains immutable

    NOTE: If freeze window is active, repair is ALLOWED but a warning is logged.
    Dispatcher must use judgment (e.g., emergency vs. minor fix).
    """
    # Check if tenant scope is blocked
    blocked = await is_scope_blocked(db, "tenant", str(user.tenant_id))
    if blocked:
        raise ServiceBlockedError(scope_type="tenant", scope_id=str(user.tenant_id))

    # M2M tokens cannot create repairs
    if user.is_app_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "APP_TOKEN_NOT_ALLOWED",
                "message": "Repair creation requires human decision. App tokens cannot create repairs.",
            }
        )

    performed_by = user.email or user.name or user.user_id

    async with db.tenant_transaction(user.tenant_id) as conn:
        async with conn.cursor() as cur:
            # Get the plan and its active snapshot
            await cur.execute(
                """
                SELECT pv.id, pv.current_snapshot_id
                FROM plan_versions pv
                WHERE pv.id = %s AND pv.tenant_id = %s
                """,
                (plan_id, user.tenant_id)
            )
            plan = await cur.fetchone()

            if not plan:
                raise PlanNotFoundError(plan_id, user.tenant_id)

            if not plan["current_snapshot_id"]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Plan has no published snapshot. Cannot create repair version."
                )

            snapshot_id = plan["current_snapshot_id"]

            # Call DB function to create repair version
            await cur.execute(
                """
                SELECT create_repair_version(
                    %s,  -- p_snapshot_id
                    %s,  -- p_created_by
                    %s   -- p_repair_reason
                ) AS result
                """,
                (snapshot_id, performed_by, request.reason)
            )
            result = await cur.fetchone()
            repair_result = result["result"]

            if not repair_result.get("success"):
                error_msg = repair_result.get("error", "Unknown error")
                logger.error(
                    "repair_version_failed",
                    extra={
                        "plan_id": plan_id,
                        "snapshot_id": snapshot_id,
                        "error": error_msg,
                        "tenant_id": user.tenant_id,
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=error_msg
                )

            # Log with appropriate level based on freeze window
            freeze_active = repair_result.get("freeze_window_active", False)
            log_level = logging.WARNING if freeze_active else logging.INFO

            logger.log(
                log_level,
                "repair_version_created",
                extra={
                    "original_plan_id": plan_id,
                    "new_plan_id": repair_result.get("new_plan_version_id"),
                    "snapshot_id": snapshot_id,
                    "source_version": repair_result.get("source_version_number"),
                    "freeze_window_active": freeze_active,
                    "created_by": performed_by,
                    "reason": request.reason,
                    "tenant_id": user.tenant_id,
                }
            )

            return RepairResponse(
                new_plan_version_id=repair_result.get("new_plan_version_id"),
                source_snapshot_id=snapshot_id,
                source_version_number=repair_result.get("source_version_number"),
                freeze_window_active=freeze_active,
                created_by=performed_by,
                created_at=datetime.now(),
                success=True,
                message=repair_result.get("message", f"Repair version created from snapshot v{repair_result.get('source_version_number')}"),
            )
