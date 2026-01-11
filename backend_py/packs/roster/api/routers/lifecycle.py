"""
SOLVEREIGN V4.7 - Roster Lifecycle API (Internal RBAC)
=======================================================

Roster Pack lifecycle endpoints with:
- Internal RBAC authentication (session cookies)
- CSRF protection on writes
- Idempotency key enforcement on creates
- Evidence + audit hooks

Routes:
- GET  /api/v1/roster/plans          - List plans (tenant-scoped)
- POST /api/v1/roster/plans          - Create plan (CSRF + idempotency)
- GET  /api/v1/roster/plans/{id}     - Get plan detail
- GET  /api/v1/roster/snapshots      - List snapshots (tenant-scoped)
- POST /api/v1/roster/snapshots/publish - Publish snapshot (CSRF + idempotency)
- GET  /api/v1/roster/snapshots/{id} - Get snapshot detail

NON-NEGOTIABLES:
- Tenant isolation via user context (NEVER from headers)
- CSRF check on all writes
- Idempotency key required on creates
- Evidence generation on lifecycle events
"""

import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    InternalUserContext,
    TenantContext,
    require_tenant_context,
    require_tenant_context_with_permission,
    require_csrf_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roster", tags=["roster-lifecycle"])


# =============================================================================
# SCHEMAS
# =============================================================================

class CreatePlanRequest(BaseModel):
    """Request to create a new plan version."""
    scenario_ref: Optional[str] = Field(None, description="Week/scenario reference")
    forecast_version_id: Optional[int] = Field(None, description="Forecast to base plan on")
    policy_hash: Optional[str] = Field(None, description="Policy profile hash")
    seed: int = Field(94, description="Solver seed for reproducibility")


class CreatePlanResponse(BaseModel):
    """Response after creating a plan."""
    success: bool = True
    plan_version_id: int
    status: str
    seed: int
    policy_hash: Optional[str]
    evidence_ref: Optional[str]
    created_at: datetime
    message: str


class PlanSummary(BaseModel):
    """Plan summary for list view."""
    id: int
    status: str
    plan_state: str
    forecast_version_id: Optional[int]
    seed: int
    output_hash: Optional[str]
    audit_passed_count: int
    audit_failed_count: int
    current_snapshot_id: Optional[int]
    publish_count: int
    created_at: datetime


class PlanListResponse(BaseModel):
    """List of plans response."""
    success: bool = True
    plans: List[PlanSummary]
    total: int


class PlanDetailResponse(BaseModel):
    """Detailed plan information."""
    success: bool = True
    plan: PlanSummary
    assignments_count: int
    snapshots: List[dict]
    evidence_ref: Optional[str]
    audit_events: List[dict]


class PublishSnapshotRequest(BaseModel):
    """Request to publish a snapshot."""
    plan_version_id: int = Field(..., description="Plan to publish")
    reason: Optional[str] = Field(None, description="Publish reason for audit")
    kpi_snapshot: Optional[dict] = Field(None, description="KPI data at publish time")
    force_during_freeze: bool = Field(False, description="Force publish during freeze")
    force_reason: Optional[str] = Field(None, min_length=10)


class PublishSnapshotResponse(BaseModel):
    """Response after publishing snapshot."""
    success: bool = True
    snapshot_id: int
    snapshot_uuid: str
    version_number: int
    published_by: str
    freeze_until: datetime
    evidence_ref: Optional[str]
    forced_during_freeze: bool = False
    message: str


class SnapshotSummary(BaseModel):
    """Snapshot summary for list view."""
    id: int
    snapshot_id: str
    plan_version_id: int
    version_number: int
    status: str
    published_at: datetime
    published_by: str
    publish_reason: Optional[str]
    freeze_until: datetime
    is_frozen: bool


class SnapshotListResponse(BaseModel):
    """List of snapshots response."""
    success: bool = True
    snapshots: List[SnapshotSummary]
    total: int


class SnapshotDetailResponse(BaseModel):
    """Detailed snapshot information."""
    success: bool = True
    snapshot: SnapshotSummary
    kpi_snapshot: Optional[dict]
    assignments_count: int
    hashes: dict
    evidence_ref: Optional[str]


# =============================================================================
# IDEMPOTENCY HELPERS
# =============================================================================

# In-memory idempotency store (replace with Redis/DB in production)
_idempotency_cache: dict[str, dict] = {}


def check_idempotency(key: str) -> Optional[dict]:
    """Check if idempotency key exists and return cached response."""
    if key in _idempotency_cache:
        cached = _idempotency_cache[key]
        # Check if not expired (1 hour TTL)
        if (datetime.now(timezone.utc) - cached["created_at"]).total_seconds() < 3600:
            return cached["response"]
    return None


def store_idempotency(key: str, response: dict) -> None:
    """Store response for idempotency key."""
    _idempotency_cache[key] = {
        "response": response,
        "created_at": datetime.now(timezone.utc),
    }


def require_idempotency_key(
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
) -> str:
    """Dependency to require idempotency key on write operations."""
    if not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "x-idempotency-key header is required for this operation",
            },
        )
    # Validate UUID format
    try:
        UUID(x_idempotency_key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_IDEMPOTENCY_KEY",
                "message": "x-idempotency-key must be a valid UUID",
            },
        )
    return x_idempotency_key


# =============================================================================
# EVIDENCE HELPERS
# =============================================================================

def generate_evidence_ref(
    tenant_id: int,
    site_id: Optional[int],
    action: str,
    entity_id: int,
) -> str:
    """Generate evidence reference string."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"evidence/roster_{action}_{tenant_id}_{site_id or 0}_{entity_id}_{ts}.json"


def write_evidence_file(
    evidence_ref: str,
    data: dict,
) -> None:
    """Write evidence JSON to file system."""
    import os
    evidence_dir = "evidence"
    os.makedirs(evidence_dir, exist_ok=True)

    filepath = os.path.join(evidence_dir, os.path.basename(evidence_ref))
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)

    logger.info(f"Evidence written: {filepath}")


# =============================================================================
# AUDIT HELPERS
# =============================================================================

def record_audit_event(
    conn,
    event_type: str,
    user: InternalUserContext,
    details: dict,
    target_tenant_id: Optional[int] = None,
) -> None:
    """Record audit event in auth.audit_log."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth.audit_log (
                event_type, user_id, user_email, tenant_id, site_id,
                details, target_tenant_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                event_type,
                user.user_id,
                user.email,
                user.tenant_id or user.active_tenant_id,
                user.site_id or user.active_site_id,
                json.dumps(details, default=str),
                target_tenant_id,
            )
        )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
):
    """
    List plan versions for the current tenant/site.

    Filters by tenant_id from user context (never from client).
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Build query with tenant filter
        base_query = """
            SELECT
                id, status, COALESCE(plan_state, 'DRAFT') as plan_state,
                forecast_version_id, seed, output_hash,
                COALESCE(audit_passed_count, 0) as audit_passed_count,
                COALESCE(audit_failed_count, 0) as audit_failed_count,
                current_snapshot_id, COALESCE(publish_count, 0) as publish_count,
                created_at
            FROM plan_versions
            WHERE tenant_id = %s
        """
        params = [ctx.tenant_id]

        if ctx.site_id:
            base_query += " AND site_id = %s"
            params.append(ctx.site_id)

        if status_filter:
            base_query += " AND (status = %s OR plan_state = %s)"
            params.extend([status_filter, status_filter])

        base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(base_query, tuple(params))
        rows = cur.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) FROM plan_versions WHERE tenant_id = %s"
        count_params = [ctx.tenant_id]
        if ctx.site_id:
            count_query += " AND site_id = %s"
            count_params.append(ctx.site_id)

        cur.execute(count_query, tuple(count_params))
        total = cur.fetchone()[0]

    plans = [
        PlanSummary(
            id=row[0],
            status=row[1],
            plan_state=row[2],
            forecast_version_id=row[3],
            seed=row[4],
            output_hash=row[5],
            audit_passed_count=row[6],
            audit_failed_count=row[7],
            current_snapshot_id=row[8],
            publish_count=row[9],
            created_at=row[10],
        )
        for row in rows
    ]

    return PlanListResponse(plans=plans, total=total)


@router.post(
    "/plans",
    response_model=CreatePlanResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def create_plan(
    request: Request,
    body: CreatePlanRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Create a new plan version (DRAFT state).

    GUARDS:
    - RBAC: portal.approve.write permission
    - CSRF: Origin/Referer check
    - Idempotency: x-idempotency-key required

    AUDIT: Records plan_create event with evidence reference.
    """
    # Check idempotency
    cached = check_idempotency(f"plan_create_{idempotency_key}")
    if cached:
        logger.info(f"Idempotent return for key {idempotency_key}")
        return CreatePlanResponse(**cached)

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Create plan version
        cur.execute(
            """
            INSERT INTO plan_versions (
                tenant_id, site_id, forecast_version_id, seed,
                status, plan_state, created_at
            ) VALUES (%s, %s, %s, %s, 'DRAFT', 'DRAFT', NOW())
            RETURNING id, created_at
            """,
            (ctx.tenant_id, ctx.site_id, body.forecast_version_id, body.seed)
        )
        result = cur.fetchone()
        plan_id = result[0]
        created_at = result[1]

        # Generate evidence reference
        evidence_ref = generate_evidence_ref(
            ctx.tenant_id, ctx.site_id, "plan_create", plan_id
        )

        # Record audit event
        record_audit_event(
            conn,
            event_type="plan_create",
            user=ctx.user,
            details={
                "plan_version_id": plan_id,
                "seed": body.seed,
                "policy_hash": body.policy_hash,
                "idempotency_key": idempotency_key,
                "evidence_ref": evidence_ref,
            },
        )

        # Write evidence file
        write_evidence_file(evidence_ref, {
            "event": "plan_create",
            "plan_version_id": plan_id,
            "tenant_id": ctx.tenant_id,
            "site_id": ctx.site_id,
            "seed": body.seed,
            "policy_hash": body.policy_hash,
            "created_by": ctx.user.email,
            "created_at": created_at.isoformat(),
            "idempotency_key": idempotency_key,
        })

        conn.commit()

    response = {
        "success": True,
        "plan_version_id": plan_id,
        "status": "DRAFT",
        "seed": body.seed,
        "policy_hash": body.policy_hash,
        "evidence_ref": evidence_ref,
        "created_at": created_at,
        "message": f"Plan {plan_id} created successfully",
    }

    # Store for idempotency
    store_idempotency(f"plan_create_{idempotency_key}", response)

    logger.info(
        "plan_created",
        extra={
            "plan_id": plan_id,
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user.user_id,
        }
    )

    return CreatePlanResponse(**response)


@router.get("/plans/{plan_id}", response_model=PlanDetailResponse)
async def get_plan(
    request: Request,
    plan_id: int,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get detailed plan information including snapshots and audit events.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Get plan (with tenant filter for security)
        cur.execute(
            """
            SELECT
                id, status, COALESCE(plan_state, 'DRAFT') as plan_state,
                forecast_version_id, seed, output_hash,
                COALESCE(audit_passed_count, 0), COALESCE(audit_failed_count, 0),
                current_snapshot_id, COALESCE(publish_count, 0), created_at
            FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_id, ctx.tenant_id)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_id} not found",
            )

        plan = PlanSummary(
            id=row[0], status=row[1], plan_state=row[2],
            forecast_version_id=row[3], seed=row[4], output_hash=row[5],
            audit_passed_count=row[6], audit_failed_count=row[7],
            current_snapshot_id=row[8], publish_count=row[9], created_at=row[10],
        )

        # Get assignments count
        cur.execute(
            "SELECT COUNT(*) FROM assignments WHERE plan_version_id = %s",
            (plan_id,)
        )
        assignments_count = cur.fetchone()[0]

        # Get snapshots
        cur.execute(
            """
            SELECT snapshot_id, version_number, snapshot_status, published_at, published_by
            FROM plan_snapshots
            WHERE plan_version_id = %s
            ORDER BY version_number DESC
            """,
            (plan_id,)
        )
        snapshots = [
            {
                "snapshot_id": str(r[0]),
                "version_number": r[1],
                "status": r[2],
                "published_at": r[3].isoformat() if r[3] else None,
                "published_by": r[4],
            }
            for r in cur.fetchall()
        ]

        # Get audit events
        cur.execute(
            """
            SELECT action, from_state, to_state, performed_by, reason, created_at
            FROM plan_approvals
            WHERE plan_version_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (plan_id,)
        )
        audit_events = [
            {
                "action": r[0],
                "from_state": r[1],
                "to_state": r[2],
                "performed_by": r[3],
                "reason": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in cur.fetchall()
        ]

        # Get evidence ref
        cur.execute(
            "SELECT evidence_artifact_uri FROM routing_evidence WHERE plan_version_id = %s",
            (plan_id,)
        )
        evidence_row = cur.fetchone()
        evidence_ref = evidence_row[0] if evidence_row else None

    return PlanDetailResponse(
        plan=plan,
        assignments_count=assignments_count,
        snapshots=snapshots,
        evidence_ref=evidence_ref,
        audit_events=audit_events,
    )


@router.get("/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
):
    """
    List snapshots for the current tenant/site.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        base_query = """
            SELECT
                id, snapshot_id, plan_version_id, version_number,
                snapshot_status, published_at, published_by,
                publish_reason, freeze_until
            FROM plan_snapshots
            WHERE tenant_id = %s
        """
        params = [ctx.tenant_id]

        if ctx.site_id:
            base_query += " AND site_id = %s"
            params.append(ctx.site_id)

        if status_filter:
            base_query += " AND snapshot_status = %s"
            params.append(status_filter)

        base_query += " ORDER BY published_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(base_query, tuple(params))
        rows = cur.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) FROM plan_snapshots WHERE tenant_id = %s"
        count_params = [ctx.tenant_id]
        if ctx.site_id:
            count_query += " AND site_id = %s"
            count_params.append(ctx.site_id)

        cur.execute(count_query, tuple(count_params))
        total = cur.fetchone()[0]

    now = datetime.now(timezone.utc)
    snapshots = [
        SnapshotSummary(
            id=row[0],
            snapshot_id=str(row[1]),
            plan_version_id=row[2],
            version_number=row[3],
            status=row[4],
            published_at=row[5],
            published_by=row[6],
            publish_reason=row[7],
            freeze_until=row[8],
            is_frozen=row[8] > now if row[8] else False,
        )
        for row in rows
    ]

    return SnapshotListResponse(snapshots=snapshots, total=total)


@router.post(
    "/snapshots/publish",
    response_model=PublishSnapshotResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def publish_snapshot(
    request: Request,
    body: PublishSnapshotRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Publish a plan version as an immutable snapshot.

    GUARDS:
    - RBAC: portal.approve.write permission
    - CSRF: Origin/Referer check
    - Idempotency: x-idempotency-key required

    BEHAVIOR:
    - Creates immutable snapshot in plan_snapshots
    - Sets 12h freeze window
    - Previous ACTIVE snapshot becomes SUPERSEDED
    - Records audit event with evidence reference

    IDEMPOTENT: Same idempotency key returns existing snapshot.
    """
    # Check idempotency
    idem_key = f"snapshot_publish_{idempotency_key}"
    cached = check_idempotency(idem_key)
    if cached:
        logger.info(f"Idempotent return for key {idempotency_key}")
        return PublishSnapshotResponse(**cached)

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    performed_by = ctx.user.email or ctx.user.display_name or ctx.user.user_id

    with conn.cursor() as cur:
        # Verify plan belongs to tenant
        cur.execute(
            "SELECT id, tenant_id, site_id, solver_config_json FROM plan_versions WHERE id = %s AND tenant_id = %s",
            (body.plan_version_id, ctx.tenant_id)
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {body.plan_version_id} not found",
            )

        # =================================================================
        # ADR-003: V4 Solver Publish Gate
        # =================================================================
        # V4 solver output cannot be published unless explicitly allowed.
        # This prevents accidental deployment of experimental/regression-prone results.
        solver_config = plan[3] if len(plan) > 3 else {}
        if isinstance(solver_config, str):
            try:
                solver_config = json.loads(solver_config)
            except json.JSONDecodeError:
                solver_config = {}

        solver_engine = solver_config.get("solver_engine", "v3") if solver_config else "v3"

        if solver_engine == "v4":
            # Import config to check feature flag
            from v3.config import config as v3_config

            # Emergency kill switch takes precedence
            if v3_config.V4_PUBLISH_KILL_SWITCH:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error_code": "V4_PUBLISH_BLOCKED_KILL_SWITCH",
                        "message": "V4 solver output publishing is disabled by emergency kill switch",
                        "solver_engine": "v4",
                        "action_required": "Use V3 solver for production plans",
                    },
                )

            if not v3_config.ALLOW_V4_PUBLISH:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error_code": "V4_PUBLISH_NOT_ALLOWED",
                        "message": (
                            "V4 solver output cannot be published. "
                            "V4 is experimental (R&D only) and may produce regression. "
                            "Set ALLOW_V4_PUBLISH=true to override (not recommended for production)."
                        ),
                        "solver_engine": "v4",
                        "action_required": "Re-solve using V3 solver (default) before publishing",
                    },
                )

            # V4 allowed but log warning
            logger.warning(
                f"Publishing V4 solver output for plan {body.plan_version_id} - "
                f"ALLOW_V4_PUBLISH=true (tenant={ctx.tenant_id}, user={performed_by})"
            )

        # Build snapshot payload
        cur.execute(
            "SELECT build_snapshot_payload(%s) AS payload",
            (body.plan_version_id,)
        )
        payload_result = cur.fetchone()
        snapshot_payload = payload_result[0] if payload_result else {}

        assignments_snapshot = snapshot_payload.get("assignments", [])
        routes_snapshot = snapshot_payload.get("routes", {})

        # Call DB function to create immutable snapshot
        kpi_json = json.dumps(body.kpi_snapshot) if body.kpi_snapshot else '{}'
        assignments_json = json.dumps(assignments_snapshot)
        routes_json = json.dumps(routes_snapshot)

        cur.execute(
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
            (body.plan_version_id, performed_by, body.reason, kpi_json,
             assignments_json, routes_json,
             body.force_during_freeze, body.force_reason)
        )
        result = cur.fetchone()
        publish_result = result[0]

        if not publish_result.get("success"):
            error_msg = publish_result.get("error", "Unknown error")

            if "freeze window" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "FREEZE_WINDOW_ACTIVE",
                        "message": error_msg,
                        "freeze_until": str(publish_result.get("freeze_until")),
                        "minutes_remaining": publish_result.get("minutes_remaining"),
                    },
                )

            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_msg,
            )

        # Generate evidence reference
        evidence_ref = generate_evidence_ref(
            ctx.tenant_id, ctx.site_id, "snapshot_publish",
            publish_result.get("snapshot_id")
        )

        # Record audit event
        record_audit_event(
            conn,
            event_type="snapshot_publish",
            user=ctx.user,
            details={
                "plan_version_id": body.plan_version_id,
                "snapshot_id": publish_result.get("snapshot_id"),
                "version_number": publish_result.get("version_number"),
                "reason": body.reason,
                "forced_during_freeze": publish_result.get("forced_during_freeze", False),
                "idempotency_key": idempotency_key,
                "evidence_ref": evidence_ref,
            },
        )

        # Write evidence file
        write_evidence_file(evidence_ref, {
            "event": "snapshot_publish",
            "plan_version_id": body.plan_version_id,
            "snapshot_id": publish_result.get("snapshot_id"),
            "version_number": publish_result.get("version_number"),
            "tenant_id": ctx.tenant_id,
            "site_id": ctx.site_id,
            "published_by": performed_by,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "reason": body.reason,
            "kpi_snapshot": body.kpi_snapshot,
            "assignments_count": len(assignments_snapshot),
            "forced_during_freeze": publish_result.get("forced_during_freeze", False),
            "idempotency_key": idempotency_key,
        })

        conn.commit()

    # Parse freeze_until
    freeze_until_str = publish_result.get("freeze_until")
    if isinstance(freeze_until_str, str):
        freeze_until = datetime.fromisoformat(freeze_until_str.replace('Z', '+00:00'))
    else:
        freeze_until = freeze_until_str or datetime.now(timezone.utc)

    response = {
        "success": True,
        "snapshot_id": publish_result.get("snapshot_id"),
        "snapshot_uuid": str(publish_result.get("snapshot_uuid", "")),
        "version_number": publish_result.get("version_number"),
        "published_by": performed_by,
        "freeze_until": freeze_until,
        "evidence_ref": evidence_ref,
        "forced_during_freeze": publish_result.get("forced_during_freeze", False),
        "message": publish_result.get("message", f"Snapshot v{publish_result.get('version_number')} published"),
    }

    # Store for idempotency
    store_idempotency(idem_key, response)

    logger.info(
        "snapshot_published",
        extra={
            "plan_id": body.plan_version_id,
            "snapshot_id": publish_result.get("snapshot_id"),
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user.user_id,
        }
    )

    return PublishSnapshotResponse(**response)


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetailResponse)
async def get_snapshot(
    request: Request,
    snapshot_id: int,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get detailed snapshot information.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id, snapshot_id, plan_version_id, version_number,
                snapshot_status, published_at, published_by,
                publish_reason, freeze_until, kpi_snapshot,
                input_hash, matrix_hash, output_hash, evidence_hash,
                evidence_artifact_uri, assignments_snapshot
            FROM plan_snapshots
            WHERE id = %s AND tenant_id = %s
            """,
            (snapshot_id, ctx.tenant_id)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Snapshot {snapshot_id} not found",
            )

        now = datetime.now(timezone.utc)

        snapshot = SnapshotSummary(
            id=row[0],
            snapshot_id=str(row[1]),
            plan_version_id=row[2],
            version_number=row[3],
            status=row[4],
            published_at=row[5],
            published_by=row[6],
            publish_reason=row[7],
            freeze_until=row[8],
            is_frozen=row[8] > now if row[8] else False,
        )

        # Count assignments in snapshot
        assignments_snapshot = row[15] or []
        assignments_count = len(assignments_snapshot) if isinstance(assignments_snapshot, list) else 0

        hashes = {
            "input_hash": row[10],
            "matrix_hash": row[11],
            "output_hash": row[12],
            "evidence_hash": row[13],
        }

        return SnapshotDetailResponse(
            snapshot=snapshot,
            kpi_snapshot=row[9],
            assignments_count=assignments_count,
            hashes=hashes,
            evidence_ref=row[14],
        )
