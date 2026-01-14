"""
Repair Sessions Router - V4.6 Roster Pack

Provides session-based repair workflow:
- Create session → Preview actions → Apply (idempotent)

All operations require audit notes and respect pins.

CRITICAL INVARIANTS:
- Session expiry is ENFORCED server-side (HTTP 410 on expired)
- Idempotency hash includes tenant_id + site_id + session_id + payload
- Plan ownership validated beyond RLS (belt + suspenders)
- All mutations logged with duration + counts for observability
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timedelta
import hashlib
import json
import time
import logging

# Import TTL configuration from central location
try:
    from api.security.internal_rbac import (
        REPAIR_SESSION_SLIDING_TTL_MINUTES,
        REPAIR_SESSION_ABSOLUTE_CAP_MINUTES,
    )
except ImportError:
    # Fallback defaults if import fails
    REPAIR_SESSION_SLIDING_TTL_MINUTES = 30
    REPAIR_SESSION_ABSOLUTE_CAP_MINUTES = 120

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repairs", tags=["roster-repairs"])


# ============================================================================
# Feature Flag Checks
# ============================================================================

def get_roster_config() -> dict:
    """Get roster pack configuration with feature flags."""
    try:
        from packs.roster.config_schema import DEFAULT_ROSTER_POLICY
        return DEFAULT_ROSTER_POLICY.dict()
    except ImportError:
        # Fallback: all features enabled
        return {
            "enable_repairs": True,
            "enable_pins": True,
            "enable_audit_notes": True,
            "repair_session_timeout_minutes": 30,
            "max_repair_actions_per_session": 100,
        }


def require_feature_enabled(feature_name: str) -> None:
    """
    Check if a feature is enabled. Raises 403 if disabled.

    Args:
        feature_name: Name of the feature flag (e.g., "enable_repairs")

    Raises:
        HTTPException 403 with FEATURE_DISABLED error code
    """
    config = get_roster_config()

    if not config.get(feature_name, True):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "FEATURE_DISABLED",
                "message": f"Feature '{feature_name}' is disabled for this tenant",
                "feature": feature_name,
                "action_required": "Contact administrator to enable this feature",
            }
        )


# ============================================================================
# Models
# ============================================================================

class CreateSessionRequest(BaseModel):
    """Create a new repair session for a plan."""
    plan_version_id: int
    reason_code: str = Field(..., min_length=1, max_length=50)
    note: str = Field(..., min_length=1, max_length=500)


class CreateSessionResponse(BaseModel):
    """Response after creating a repair session."""
    session_id: str
    plan_version_id: int
    status: str
    expires_at: str
    created_at: str


class RepairAction(BaseModel):
    """A single repair action to preview or apply."""
    action_type: Literal["SWAP", "MOVE", "FILL", "CLEAR"]
    driver_id: str
    day: str
    tour_instance_id: Optional[int] = None
    target_driver_id: Optional[str] = None  # For SWAP
    target_day: Optional[str] = None  # For MOVE
    target_tour_instance_id: Optional[int] = None  # For FILL


class PreviewRequest(BaseModel):
    """Request to preview a repair action."""
    action: RepairAction
    reason_code: str = Field(..., min_length=1, max_length=50)
    note: str = Field(..., min_length=1, max_length=500)


class ViolationDelta(BaseModel):
    """Change in violations after an action."""
    type: str
    severity: str
    driver_id: str
    day: Optional[str]
    message: str
    change: Literal["ADDED", "REMOVED", "UNCHANGED"]


class PreviewResponse(BaseModel):
    """Response after previewing an action."""
    session_id: str
    action_seq: int
    action: RepairAction
    is_valid: bool
    pin_conflicts: List[str]
    violations_before: int
    violations_after: int
    violation_deltas: List[ViolationDelta]
    affected_drivers: List[str]
    preview_delta: Dict[str, Any]


class ApplyRequest(BaseModel):
    """Request to apply previewed actions."""
    action_seqs: Optional[List[int]] = None  # None = apply all
    reason_code: str = Field(..., min_length=1, max_length=50)
    note: str = Field(..., min_length=1, max_length=500)


class ApplyResponse(BaseModel):
    """Response after applying actions."""
    session_id: str
    applied_count: int
    skipped_count: int
    status: str
    violations_remaining: int
    audit_event_id: str


class UndoResponse(BaseModel):
    """Response after undoing the last action."""
    session_id: str
    undone_action_seq: int
    undone_action_type: str
    can_undo_more: bool
    violations_remaining: int
    audit_event_id: str


class SessionStatusResponse(BaseModel):
    """Current status of a repair session."""
    session_id: str
    plan_version_id: int
    status: str
    action_count: int
    applied_count: int
    expires_at: str
    created_at: str
    created_by: str


# ============================================================================
# Helpers
# ============================================================================

def get_db_manager(request: Request):
    """Get database manager from app state."""
    db_manager = request.app.state.db
    if not db_manager or not db_manager.pool:
        raise HTTPException(status_code=503, detail="Database not available")
    return db_manager


async def get_db_connection(request: Request):
    """
    FastAPI dependency that provides a database connection.

    This is an async generator that properly acquires and releases
    the connection from the pool.

    Usage as Depends:
        async def endpoint(conn = Depends(get_db_connection)):
            ...

    Legacy usage (direct call - wraps in context manager):
        db = get_db_manager(request)
        async with db.connection() as conn:
            ...
    """
    db_manager = get_db_manager(request)
    async with db_manager.pool.connection() as conn:
        yield conn


async def get_current_user(request: Request) -> dict:
    """Get current user from request state."""
    return getattr(request.state, "user", {"user_id": "system", "email": "system@solvereign.com"})


async def get_tenant_context(request: Request) -> dict:
    """Get tenant context from request state."""
    return {
        "tenant_id": getattr(request.state, "tenant_id", None),
        "site_id": getattr(request.state, "site_id", None),
    }


def generate_session_id() -> str:
    """Generate a unique session ID."""
    import uuid
    return str(uuid.uuid4())


def compute_idempotency_hash(
    tenant_id: int,
    site_id: int,
    session_id: str,
    action: RepairAction
) -> str:
    """
    Compute hash for idempotency checking.

    CRITICAL: Hash includes tenant_id + site_id to prevent collisions
    across tenants with identical payloads.
    """
    content = f"{tenant_id}:{site_id}:{session_id}:{action.action_type}:{action.driver_id}:{action.day}"
    if action.target_driver_id:
        content += f":{action.target_driver_id}"
    if action.target_day:
        content += f":{action.target_day}"
    if action.tour_instance_id:
        content += f":{action.tour_instance_id}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


async def validate_session_active(
    conn,
    session_id: str,
    tenant_id: int,
    site_id: int
) -> dict:
    """
    Validate session exists, belongs to tenant, and is not expired.

    Returns session row if valid, raises HTTPException otherwise.

    CRITICAL: This enforces expiry server-side - lazy expiration pattern.
    Also enforces absolute cap of 2 hours from session creation.
    """
    session = await conn.fetchrow("""
        SELECT *,
            CASE WHEN expires_at < NOW() THEN TRUE ELSE FALSE END as is_expired,
            CASE WHEN created_at + INTERVAL '%s minutes' < NOW() THEN TRUE ELSE FALSE END as is_capped
        FROM roster.repairs
        WHERE id = $1 AND tenant_id = $2 AND site_id = $3
    """ % REPAIR_SESSION_ABSOLUTE_CAP_MINUTES, session_id, tenant_id, site_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Absolute cap: 2 hours from creation
    if session.get("is_capped") and session["status"] == "OPEN":
        await conn.execute("""
            UPDATE roster.repairs
            SET status = 'EXPIRED', updated_at = NOW(), closed_reason = 'Absolute cap reached (2h)'
            WHERE id = $1 AND status = 'OPEN'
        """, session_id)

        raise HTTPException(
            status_code=410,
            detail={
                "error_code": "SESSION_ABSOLUTE_CAP",
                "message": "Repair session reached 2-hour absolute cap",
                "created_at": session["created_at"].isoformat() if session.get("created_at") else "",
                "action_required": "Create a new repair session",
            }
        )

    # Lazy expiration: mark as EXPIRED if past expiry time
    if session["is_expired"] and session["status"] == "OPEN":
        await conn.execute("""
            UPDATE roster.repairs
            SET status = 'EXPIRED', updated_at = NOW()
            WHERE id = $1 AND status = 'OPEN'
        """, session_id)

        raise HTTPException(
            status_code=410,
            detail={
                "error_code": "SESSION_EXPIRED",
                "message": "Repair session has expired",
                "expired_at": session["expires_at"].isoformat(),
                "action_required": "Create a new repair session",
            }
        )

    if session["status"] != "OPEN":
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SESSION_NOT_OPEN",
                "message": f"Session is {session['status']}, not OPEN",
                "status": session["status"],
            }
        )

    return session


async def validate_plan_ownership(
    conn,
    plan_version_id: int,
    tenant_id: int,
    site_id: int
) -> dict:
    """
    Belt+suspenders: Validate plan belongs to tenant/site beyond RLS.

    Returns plan row if valid, raises HTTPException otherwise.
    """
    plan = await conn.fetchrow("""
        SELECT id, tenant_id, site_id, status
        FROM plan_versions
        WHERE id = $1
    """, plan_version_id)

    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan {plan_version_id} not found")

    # Explicit ownership check (beyond RLS)
    if plan["tenant_id"] != tenant_id:
        logger.warning(
            f"Cross-tenant access attempt: user tenant={tenant_id} tried to access "
            f"plan {plan_version_id} owned by tenant={plan['tenant_id']}"
        )
        raise HTTPException(status_code=404, detail=f"Plan {plan_version_id} not found")

    if site_id and plan["site_id"] != site_id:
        logger.warning(
            f"Cross-site access attempt: user site={site_id} tried to access "
            f"plan {plan_version_id} owned by site={plan['site_id']}"
        )
        raise HTTPException(status_code=404, detail=f"Plan {plan_version_id} not found")

    return plan


async def check_pin_conflicts(
    conn, tenant_id: int, site_id: int, plan_id: int, action: RepairAction
) -> List[str]:
    """Check if action conflicts with any pins."""
    conflicts = []

    # Check source assignment
    result = await conn.fetchrow("""
        SELECT id, reason_code
        FROM roster.pins
        WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
          AND driver_id = $4 AND day = $5
          AND deleted_at IS NULL
    """, tenant_id, site_id, plan_id, action.driver_id, action.day)

    if result:
        conflicts.append(f"Source assignment pinned: {action.driver_id}/{action.day} ({result['reason_code']})")

    # Check target assignment for SWAP
    if action.action_type == "SWAP" and action.target_driver_id:
        target_day = action.target_day or action.day
        result = await conn.fetchrow("""
            SELECT id, reason_code
            FROM roster.pins
            WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
              AND driver_id = $4 AND day = $5
              AND deleted_at IS NULL
        """, tenant_id, site_id, plan_id, action.target_driver_id, target_day)

        if result:
            conflicts.append(f"Target assignment pinned: {action.target_driver_id}/{target_day} ({result['reason_code']})")

    return conflicts


async def invalidate_violations_cache(conn, tenant_id: int, site_id: int, plan_id: int):
    """Invalidate violations cache after mutation."""
    await conn.execute("""
        UPDATE roster.violations_cache
        SET invalidated_at = NOW()
        WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
          AND invalidated_at IS NULL
    """, tenant_id, site_id, plan_id)


async def record_audit_note(
    conn, tenant_id: int, site_id: int, entity_type: str, entity_id: str,
    reason_code: str, note: str, user_id: str
):
    """Record an audit note for any mutation."""
    await conn.execute("""
        INSERT INTO roster.audit_notes
        (tenant_id, site_id, entity_type, entity_id, reason_code, note, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, tenant_id, site_id, entity_type, entity_id, reason_code, note, user_id)


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_repair_session(
    body: CreateSessionRequest,
    request: Request,
    conn = Depends(get_db_connection),
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
):
    """
    Create a new repair session for a plan.

    Sessions expire after 30 minutes of inactivity.
    Only one active session per plan is allowed.

    GUARDS:
    - Feature flag check (enable_repairs)
    - Belt+suspenders plan ownership validation
    - One OPEN session per plan (DB unique index)
    - Idempotency key for safe retries
    """
    # Check feature is enabled
    require_feature_enabled("enable_repairs")

    start_time = time.time()
    user = await get_current_user(request)
    ctx = await get_tenant_context(request)

    tenant_id = ctx["tenant_id"]
    site_id = ctx["site_id"]

    if not tenant_id or not site_id:
        raise HTTPException(status_code=400, detail="Tenant/site context required")

    # Belt+suspenders: Validate plan ownership beyond RLS
    await validate_plan_ownership(conn, body.plan_version_id, tenant_id, site_id)

    # Check idempotency first (before any DB mutations)
    if x_idempotency_key:
        cached = await conn.fetchrow("""
            SELECT response_body FROM core.idempotency_keys
            WHERE idempotency_key = $1 AND created_at > NOW() - INTERVAL '24 hours'
        """, x_idempotency_key)
        if cached:
            logger.info(f"Idempotent return for session create key={x_idempotency_key}")
            return CreateSessionResponse(**json.loads(cached["response_body"]))

    session_id = generate_session_id()
    # Sliding window TTL, capped at absolute max
    expires_at = datetime.utcnow() + timedelta(minutes=REPAIR_SESSION_SLIDING_TTL_MINUTES)
    absolute_cap_at = datetime.utcnow() + timedelta(minutes=REPAIR_SESSION_ABSOLUTE_CAP_MINUTES)
    user_id = user.get("user_id", "unknown")

    # =================================================================
    # ATOMIC SESSION CREATION (Race-Safe)
    # =================================================================
    # Uses pg_advisory_xact_lock to serialize session creation per plan.
    # This prevents race conditions when two UI clicks happen simultaneously.
    #
    # Lock key derived from (tenant_id, site_id, plan_id) to avoid
    # cross-tenant/cross-env serialization when plan_ids could collide.
    #
    # Pattern: Lock → Lazy-expire old → Insert → Unlock (auto on commit)
    async with conn.transaction():
        # Advisory lock on (tenant_id XOR site_id, plan_id) - released at transaction end
        # Using two int8 locks for proper scoping
        lock_key_1 = tenant_id ^ (site_id << 16)  # Combine tenant + site
        lock_key_2 = body.plan_version_id
        await conn.execute(
            "SELECT pg_advisory_xact_lock($1, $2)",
            lock_key_1, lock_key_2
        )

        # Lazy expire any stale OPEN sessions
        await conn.execute("""
            UPDATE roster.repairs
            SET status = 'EXPIRED', updated_at = NOW()
            WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
              AND status = 'OPEN' AND expires_at < NOW()
        """, tenant_id, site_id, body.plan_version_id)

        # Check for non-expired OPEN session
        existing = await conn.fetchrow("""
            SELECT id, expires_at, created_by
            FROM roster.repairs
            WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
              AND status = 'OPEN'
        """, tenant_id, site_id, body.plan_version_id)

        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "REPAIR_SESSION_ALREADY_OPEN",
                    "message": "Active repair session already exists for this plan",
                    "existing_session_id": existing["id"],
                    "existing_created_by": existing["created_by"] or "unknown",
                    "expires_at": existing["expires_at"].isoformat(),
                    "action_required": "Wait for session to expire or request takeover from approver",
                }
            )

        # Create new session (guaranteed unique by advisory lock)
        await conn.execute("""
            INSERT INTO roster.repairs
            (id, tenant_id, site_id, plan_version_id, status, expires_at, created_by)
            VALUES ($1, $2, $3, $4, 'OPEN', $5, $6)
        """, session_id, tenant_id, site_id, body.plan_version_id, expires_at, user_id)

    # Record audit note
    await record_audit_note(
        conn, tenant_id, site_id, "repair_session", session_id,
        body.reason_code, body.note, user_id
    )

    response = CreateSessionResponse(
        session_id=session_id,
        plan_version_id=body.plan_version_id,
        status="OPEN",
        expires_at=expires_at.isoformat(),
        created_at=datetime.utcnow().isoformat(),
    )

    # Cache idempotency response
    if x_idempotency_key:
        await conn.execute("""
            INSERT INTO core.idempotency_keys (idempotency_key, response_body)
            VALUES ($1, $2)
            ON CONFLICT (idempotency_key) DO NOTHING
        """, x_idempotency_key, json.dumps(response.dict()))

    # Observability
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "repair_session_created",
        extra={
            "session_id": session_id,
            "plan_version_id": body.plan_version_id,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "user_id": user_id,
            "duration_ms": round(duration_ms, 2),
        }
    )

    return response


@router.get("/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(session_id: str, request: Request, conn = Depends(get_db_connection)):
    """Get current status of a repair session."""
    ctx = await get_tenant_context(request)

    session = await conn.fetchrow("""
        SELECT r.*,
               (SELECT COUNT(*) FROM roster.repair_actions WHERE repair_session_id = r.id) as action_count,
               (SELECT COUNT(*) FROM roster.repair_actions WHERE repair_session_id = r.id AND applied_at IS NOT NULL) as applied_count
        FROM roster.repairs r
        WHERE r.id = $1 AND r.tenant_id = $2 AND r.site_id = $3
    """, session_id, ctx["tenant_id"], ctx["site_id"])

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionStatusResponse(
        session_id=session["id"],
        plan_version_id=session["plan_version_id"],
        status=session["status"],
        action_count=session["action_count"],
        applied_count=session["applied_count"],
        expires_at=session["expires_at"].isoformat() if session["expires_at"] else "",
        created_at=session["created_at"].isoformat() if session["created_at"] else "",
        created_by=session["created_by"] or "unknown",
    )


@router.post("/{session_id}/preview", response_model=PreviewResponse)
async def preview_repair_action(
    session_id: str,
    body: PreviewRequest,
    request: Request,
    conn = Depends(get_db_connection),
):
    """
    Preview a repair action without applying it.

    Returns:
    - Pin conflicts (if any)
    - Violation changes (what would be resolved/created)
    - Affected drivers

    GUARDS:
    - Feature flag check (enable_repairs)
    - Session must be OPEN and not expired (HTTP 410 if expired)
    - Plan ownership validated
    """
    # Check feature is enabled
    require_feature_enabled("enable_repairs")

    start_time = time.time()
    user = await get_current_user(request)
    ctx = await get_tenant_context(request)

    tenant_id = ctx["tenant_id"]
    site_id = ctx["site_id"]

    # Validate session is active (enforces expiry with HTTP 410)
    session = await validate_session_active(conn, session_id, tenant_id, site_id)
    plan_id = session["plan_version_id"]
    user_id = user.get("user_id", "unknown")

    # Check pin conflicts
    pin_conflicts = await check_pin_conflicts(conn, tenant_id, site_id, plan_id, body.action)

    # Get current violations count
    violations_before = await conn.fetchval("""
        SELECT COALESCE(block_count + warn_count, 0)
        FROM roster.violations_cache
        WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
          AND invalidated_at IS NULL
        ORDER BY computed_at DESC LIMIT 1
    """, tenant_id, site_id, plan_id) or 0

    # Compute preview delta (simplified - real implementation would simulate the change)
    violations_after = violations_before
    violation_deltas = []
    affected_drivers = [body.action.driver_id]

    if body.action.target_driver_id:
        affected_drivers.append(body.action.target_driver_id)

    # Simulate violation changes based on action type
    if body.action.action_type == "CLEAR":
        # Clearing usually removes violations on that cell
        violations_after = max(0, violations_before - 1)
        violation_deltas.append(ViolationDelta(
            type="UNASSIGNED",
            severity="BLOCK",
            driver_id=body.action.driver_id,
            day=body.action.day,
            message=f"Tour cleared for {body.action.driver_id} on {body.action.day}",
            change="ADDED"
        ))
    elif body.action.action_type == "FILL":
        # Filling resolves UNASSIGNED
        violations_after = max(0, violations_before - 1)
        violation_deltas.append(ViolationDelta(
            type="UNASSIGNED",
            severity="BLOCK",
            driver_id=body.action.driver_id,
            day=body.action.day,
            message=f"Assignment filled for {body.action.driver_id} on {body.action.day}",
            change="REMOVED"
        ))

    # Get next action sequence
    action_seq = await conn.fetchval("""
        SELECT COALESCE(MAX(action_seq), 0) + 1
        FROM roster.repair_actions
        WHERE repair_session_id = $1
    """, session_id)

    # Store preview (not applied yet)
    # CRITICAL: Hash includes tenant_id + site_id to prevent cross-tenant collisions
    idempotency_hash = compute_idempotency_hash(tenant_id, site_id, session_id, body.action)

    await conn.execute("""
        INSERT INTO roster.repair_actions
        (repair_session_id, action_seq, action_type, payload, preview_delta,
         idempotency_hash, reason_code, note, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (repair_session_id, idempotency_hash) DO UPDATE
        SET preview_delta = $5, updated_at = NOW()
    """, session_id, action_seq, body.action.action_type,
        json.dumps(body.action.dict()),
        json.dumps({"violations_before": violations_before, "violations_after": violations_after}),
        idempotency_hash, body.reason_code, body.note, user_id)

    # Extend session expiry
    await conn.execute("""
        UPDATE roster.repairs SET expires_at = NOW() + INTERVAL '30 minutes'
        WHERE id = $1
    """, session_id)

    # Observability
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "repair_preview_computed",
        extra={
            "session_id": session_id,
            "action_type": body.action.action_type,
            "action_seq": action_seq,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "user_id": user_id,
            "pin_conflict_count": len(pin_conflicts),
            "violations_before": violations_before,
            "violations_after": violations_after,
            "duration_ms": round(duration_ms, 2),
        }
    )

    return PreviewResponse(
        session_id=session_id,
        action_seq=action_seq,
        action=body.action,
        is_valid=len(pin_conflicts) == 0,
        pin_conflicts=pin_conflicts,
        violations_before=violations_before,
        violations_after=violations_after,
        violation_deltas=violation_deltas,
        affected_drivers=affected_drivers,
        preview_delta={"violations_before": violations_before, "violations_after": violations_after},
    )


@router.post("/{session_id}/apply", response_model=ApplyResponse)
async def apply_repair_actions(
    session_id: str,
    body: ApplyRequest,
    request: Request,
    conn = Depends(get_db_connection),
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
):
    """
    Apply previewed repair actions to the plan.

    This operation is idempotent - repeated calls with the same
    idempotency key return the cached result.

    GUARDS:
    - Feature flag check (enable_repairs)
    - Session must be OPEN and not expired (HTTP 410 if expired)
    - Pin conflicts block application (HTTP 409)
    - Idempotency key prevents double-apply
    """
    # Check feature is enabled
    require_feature_enabled("enable_repairs")

    start_time = time.time()
    user = await get_current_user(request)
    ctx = await get_tenant_context(request)

    tenant_id = ctx["tenant_id"]
    site_id = ctx["site_id"]
    user_id = user.get("user_id", "unknown")

    # Check idempotency first (before any validation)
    if x_idempotency_key:
        cached = await conn.fetchrow("""
            SELECT response_body FROM core.idempotency_keys
            WHERE idempotency_key = $1 AND created_at > NOW() - INTERVAL '24 hours'
        """, x_idempotency_key)
        if cached:
            logger.info(f"Idempotent return for apply key={x_idempotency_key}")
            return ApplyResponse(**json.loads(cached["response_body"]))

    # Validate session is active (enforces expiry with HTTP 410)
    session = await validate_session_active(conn, session_id, tenant_id, site_id)
    plan_id = session["plan_version_id"]

    # LOCKED PLAN GUARD: Cannot apply if plan is locked
    plan_status = await conn.fetchrow("""
        SELECT status, locked_at FROM plan_versions WHERE id = $1
    """, plan_id)

    if plan_status and plan_status["status"] == "LOCKED":
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "PLAN_LOCKED",
                "message": "Cannot apply: plan is locked",
                "locked_at": plan_status["locked_at"].isoformat() if plan_status["locked_at"] else None,
                "action_required": "Plan must be unlocked before repairs can be applied",
            }
        )

    # Get actions to apply
    if body.action_seqs:
        actions = await conn.fetch("""
            SELECT * FROM roster.repair_actions
            WHERE repair_session_id = $1 AND action_seq = ANY($2)
              AND applied_at IS NULL
            ORDER BY action_seq
        """, session_id, body.action_seqs)
    else:
        actions = await conn.fetch("""
            SELECT * FROM roster.repair_actions
            WHERE repair_session_id = $1 AND applied_at IS NULL
            ORDER BY action_seq
        """, session_id)

    if not actions:
        raise HTTPException(status_code=400, detail="No actions to apply")

    # Check all pin conflicts before applying any
    all_conflicts = []
    for action_row in actions:
        action_data = json.loads(action_row["payload"])
        action = RepairAction(**action_data)
        conflicts = await check_pin_conflicts(conn, tenant_id, site_id, plan_id, action)
        if conflicts:
            all_conflicts.extend(conflicts)

    if all_conflicts:
        raise HTTPException(
            status_code=409,
            detail=f"Pin conflicts prevent apply: {'; '.join(all_conflicts)}"
        )

    # Apply actions in transaction
    applied_count = 0
    skipped_count = 0
    import uuid
    audit_event_id = str(uuid.uuid4())

    async with conn.transaction():
        for action_row in actions:
            action_data = json.loads(action_row["payload"])
            action = RepairAction(**action_data)

            # Apply the action (simplified - real implementation modifies plan_assignments)
            # For now, we just mark it as applied
            try:
                # TODO: Actually modify plan_assignments table based on action_type
                # This is a placeholder - real implementation would:
                # - SWAP: Exchange assignments between two drivers
                # - MOVE: Move assignment to different day/driver
                # - FILL: Assign a tour to a driver
                # - CLEAR: Remove assignment from driver

                await conn.execute("""
                    UPDATE roster.repair_actions
                    SET applied_at = NOW(), applied_by = $2
                    WHERE id = $1
                """, action_row["id"], user_id)

                applied_count += 1
            except Exception:
                skipped_count += 1

        # Invalidate violations cache
        await invalidate_violations_cache(conn, tenant_id, site_id, plan_id)

        # Update session status
        await conn.execute("""
            UPDATE roster.repairs
            SET status = CASE WHEN $2 > 0 THEN 'APPLIED' ELSE status END,
                updated_at = NOW()
            WHERE id = $1
        """, session_id, applied_count)

        # Record audit note
        await record_audit_note(
            conn, tenant_id, site_id, "repair_apply", audit_event_id,
            body.reason_code, f"{body.note} | Applied {applied_count} actions",
            user_id
        )

    # Get remaining violations
    violations_remaining = await conn.fetchval("""
        SELECT COALESCE(block_count + warn_count, 0)
        FROM roster.violations_cache
        WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
          AND invalidated_at IS NULL
        ORDER BY computed_at DESC LIMIT 1
    """, tenant_id, site_id, plan_id) or 0

    response = ApplyResponse(
        session_id=session_id,
        applied_count=applied_count,
        skipped_count=skipped_count,
        status="APPLIED" if applied_count > 0 else "OPEN",
        violations_remaining=violations_remaining,
        audit_event_id=audit_event_id,
    )

    # Cache idempotency response
    if x_idempotency_key:
        await conn.execute("""
            INSERT INTO core.idempotency_keys (idempotency_key, response_body)
            VALUES ($1, $2)
            ON CONFLICT (idempotency_key) DO NOTHING
        """, x_idempotency_key, json.dumps(response.dict()))

    # Observability
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "repair_actions_applied",
        extra={
            "session_id": session_id,
            "plan_version_id": plan_id,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "user_id": user_id,
            "applied_count": applied_count,
            "skipped_count": skipped_count,
            "violations_remaining": violations_remaining,
            "audit_event_id": audit_event_id,
            "duration_ms": round(duration_ms, 2),
        }
    )

    return response


@router.post("/{session_id}/abort")
async def abort_repair_session(session_id: str, request: Request, conn = Depends(get_db_connection)):
    """Abort a repair session, discarding all unapplied actions."""
    user = await get_current_user(request)
    ctx = await get_tenant_context(request)

    result = await conn.execute("""
        UPDATE roster.repairs
        SET status = 'ABORTED', updated_at = NOW()
        WHERE id = $1 AND tenant_id = $2 AND site_id = $3
          AND status = 'OPEN'
    """, session_id, ctx["tenant_id"], ctx["site_id"])

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Session not found or already closed")

    return {"session_id": session_id, "status": "ABORTED"}


@router.post("/{session_id}/undo", response_model=UndoResponse)
async def undo_last_repair_action(
    session_id: str,
    request: Request,
    conn = Depends(get_db_connection),
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
):
    """
    Undo the last applied repair action (1-step undo).

    This reverts the most recently applied action in the session.
    Only one action can be undone at a time, and only the most recent.

    CRITICAL: Reduces dispatcher anxiety during pilot - allows quick recovery
    from accidental changes without aborting the entire session.

    GUARDS:
    - Idempotency key prevents double-undo on retry/double-click
    - Session must be OPEN and not expired (HTTP 410 if expired)
    - Plan must not have been published since session start (HTTP 409)
    - Must have at least one applied action to undo (HTTP 400)
    - Action is marked as undone (not deleted - audit trail preserved)

    Returns:
    - The action sequence that was undone
    - Whether more actions can be undone
    - Updated violation count
    """
    # Check feature is enabled
    require_feature_enabled("enable_repairs")

    start_time = time.time()
    user = await get_current_user(request)
    ctx = await get_tenant_context(request)

    tenant_id = ctx["tenant_id"]
    site_id = ctx["site_id"]
    user_id = user.get("user_id", "unknown")

    # =================================================================
    # IDEMPOTENCY CHECK (Critical: prevent double-undo)
    # =================================================================
    if x_idempotency_key:
        cached = await conn.fetchrow("""
            SELECT response_body FROM core.idempotency_keys
            WHERE idempotency_key = $1 AND created_at > NOW() - INTERVAL '24 hours'
        """, x_idempotency_key)
        if cached:
            logger.info(f"Idempotent return for undo key={x_idempotency_key}")
            return UndoResponse(**json.loads(cached["response_body"]))

    # Validate session is active (enforces expiry with HTTP 410)
    session = await validate_session_active(conn, session_id, tenant_id, site_id)
    plan_id = session["plan_version_id"]

    # =================================================================
    # PUBLISH GUARD: Cannot undo if plan was published after session start
    # =================================================================
    published_snapshot = await conn.fetchrow("""
        SELECT ps.id, ps.published_at
        FROM plan_snapshots ps
        WHERE ps.plan_version_id = $1
          AND ps.published_at > $2
          AND ps.status = 'PUBLISHED'
        ORDER BY ps.published_at DESC
        LIMIT 1
    """, plan_id, session["created_at"])

    if published_snapshot:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SNAPSHOT_ALREADY_PUBLISHED",
                "message": "Cannot undo: plan was published after this session started",
                "snapshot_id": published_snapshot["id"],
                "published_at": published_snapshot["published_at"].isoformat(),
                "action_required": "Create a new repair session to make further changes",
            }
        )

    # =================================================================
    # LOCKED PLAN GUARD: Cannot undo if plan is locked
    # =================================================================
    plan_status = await conn.fetchrow("""
        SELECT status, locked_at
        FROM plan_versions
        WHERE id = $1
    """, plan_id)

    if plan_status and plan_status["status"] == "LOCKED":
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "PLAN_LOCKED_NO_UNDO",
                "message": "Cannot undo: plan is locked",
                "locked_at": plan_status["locked_at"].isoformat() if plan_status["locked_at"] else None,
                "action_required": "Plan must be unlocked before repairs can be modified",
            }
        )

    # =================================================================
    # GET LAST APPLIED ACTION
    # Sort by action_seq DESC (not applied_at) to avoid clock skew issues
    # =================================================================
    last_action = await conn.fetchrow("""
        SELECT id, action_seq, action_type, payload, applied_at
        FROM roster.repair_actions
        WHERE repair_session_id = $1
          AND applied_at IS NOT NULL
          AND undone_at IS NULL
        ORDER BY action_seq DESC
        LIMIT 1
    """, session_id)

    if not last_action:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "NOTHING_TO_UNDO",
                "message": "No applied actions to undo in this session",
                "action_required": "Apply an action first before undoing",
            }
        )

    import uuid
    audit_event_id = str(uuid.uuid4())

    # Mark action as undone (preserving audit trail - don't delete)
    async with conn.transaction():
        # Use idempotent update: only update if not already undone
        result = await conn.execute("""
            UPDATE roster.repair_actions
            SET undone_at = NOW(), undone_by = $2
            WHERE id = $1 AND undone_at IS NULL
        """, last_action["id"], user_id)

        # Check if we actually updated (idempotency - concurrent request may have won)
        if result == "UPDATE 0":
            # Another request already undid this action, return current state
            logger.info(f"Undo already completed by concurrent request for action {last_action['id']}")

        # Invalidate violations cache (state changed)
        await invalidate_violations_cache(conn, tenant_id, site_id, plan_id)

        # Reset session status back to OPEN if it was APPLIED
        await conn.execute("""
            UPDATE roster.repairs
            SET status = 'OPEN', updated_at = NOW()
            WHERE id = $1 AND status = 'APPLIED'
        """, session_id)

        # Record audit note
        action_data = json.loads(last_action["payload"])
        await record_audit_note(
            conn, tenant_id, site_id, "repair_undo", audit_event_id,
            "UNDO", f"Undone action #{last_action['action_seq']} ({last_action['action_type']}): {action_data.get('driver_id', '?')}/{action_data.get('day', '?')}",
            user_id
        )

    # Check if there are more actions that can be undone
    remaining_applied = await conn.fetchval("""
        SELECT COUNT(*)
        FROM roster.repair_actions
        WHERE repair_session_id = $1
          AND applied_at IS NOT NULL
          AND undone_at IS NULL
    """, session_id)

    # Get updated violations count
    violations_remaining = await conn.fetchval("""
        SELECT COALESCE(block_count + warn_count, 0)
        FROM roster.violations_cache
        WHERE tenant_id = $1 AND site_id = $2 AND plan_version_id = $3
          AND invalidated_at IS NULL
        ORDER BY computed_at DESC LIMIT 1
    """, tenant_id, site_id, plan_id) or 0

    # Extend session expiry (activity keeps session alive)
    await conn.execute("""
        UPDATE roster.repairs SET expires_at = NOW() + INTERVAL '30 minutes'
        WHERE id = $1
    """, session_id)

    response = UndoResponse(
        session_id=session_id,
        undone_action_seq=last_action["action_seq"],
        undone_action_type=last_action["action_type"],
        can_undo_more=remaining_applied > 0,
        violations_remaining=violations_remaining,
        audit_event_id=audit_event_id,
    )

    # Cache idempotency response
    if x_idempotency_key:
        await conn.execute("""
            INSERT INTO core.idempotency_keys (idempotency_key, response_body)
            VALUES ($1, $2)
            ON CONFLICT (idempotency_key) DO NOTHING
        """, x_idempotency_key, json.dumps(response.dict()))

    # Observability
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "repair_action_undone",
        extra={
            "session_id": session_id,
            "plan_version_id": plan_id,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "user_id": user_id,
            "undone_action_seq": last_action["action_seq"],
            "undone_action_type": last_action["action_type"],
            "can_undo_more": remaining_applied > 0,
            "audit_event_id": audit_event_id,
            "idempotency_key": x_idempotency_key,
            "duration_ms": round(duration_ms, 2),
        }
    )

    return response


# ============================================================================
# Takeover Endpoint (Approver/Management Only)
# ============================================================================

class TakeoverRequest(BaseModel):
    """Request to take over an existing repair session."""
    reason: str = Field(..., min_length=10, max_length=500)


class TakeoverResponse(BaseModel):
    """Response after taking over a session."""
    new_session_id: str
    previous_session_id: str
    previous_created_by: str
    plan_version_id: int
    status: str
    expires_at: str
    takeover_reason: str


@router.post("/{session_id}/takeover", response_model=TakeoverResponse)
async def takeover_repair_session(
    session_id: str,
    body: TakeoverRequest,
    request: Request,
    conn = Depends(get_db_connection),
):
    """
    Take over an existing repair session (approver/management only).

    This endpoint allows operator_admin or tenant_admin to forcibly close
    an existing OPEN session and create a new one for themselves.

    GUARDS:
    - Only operator_admin, tenant_admin, platform_admin can takeover
    - Requires reason >= 10 characters
    - Previous session is marked CLOSED_BY_TAKEOVER
    - Full audit trail with takeover_by, takeover_reason, previous_session_id

    Returns 403 if user is dispatcher or lower.
    Returns 404 if session not found or not OPEN.
    """
    require_feature_enabled("enable_repairs")

    start_time = time.time()
    user = await get_current_user(request)
    ctx = await get_tenant_context(request)

    tenant_id = ctx["tenant_id"]
    site_id = ctx["site_id"]
    user_id = user.get("user_id", "unknown")
    user_email = user.get("email", "unknown")
    role_name = user.get("role_name", "")

    if not tenant_id or not site_id:
        raise HTTPException(status_code=400, detail="Tenant/site context required")

    # RBAC: Only approver+ can takeover
    allowed_roles = {"platform_admin", "tenant_admin", "operator_admin"}
    if role_name not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "TAKEOVER_NOT_ALLOWED",
                "message": "Only approvers (operator_admin) or management (tenant_admin) can take over sessions",
                "your_role": role_name,
                "required_roles": list(allowed_roles),
            }
        )

    async with conn.transaction():
        # Find existing session
        existing = await conn.fetchrow("""
            SELECT id, plan_version_id, created_by, expires_at, status
            FROM roster.repairs
            WHERE id = $1 AND tenant_id = $2 AND site_id = $3
        """, session_id, tenant_id, site_id)

        if not existing:
            raise HTTPException(status_code=404, detail="Session not found")

        if existing["status"] != "OPEN":
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "SESSION_NOT_OPEN",
                    "message": f"Cannot take over session in status {existing['status']}",
                    "current_status": existing["status"],
                }
            )

        previous_created_by = existing["created_by"] or "unknown"
        plan_version_id = existing["plan_version_id"]

        # Close the existing session
        await conn.execute("""
            UPDATE roster.repairs
            SET status = 'CLOSED_BY_TAKEOVER',
                updated_at = NOW(),
                closed_reason = $2
            WHERE id = $1
        """, session_id, f"Taken over by {user_email}: {body.reason}")

        # Create new session
        new_session_id = generate_session_id()
        expires_at = datetime.utcnow() + timedelta(minutes=30)

        await conn.execute("""
            INSERT INTO roster.repairs
            (id, tenant_id, site_id, plan_version_id, status, expires_at, created_by)
            VALUES ($1, $2, $3, $4, 'OPEN', $5, $6)
        """, new_session_id, tenant_id, site_id, plan_version_id, expires_at, user_id)

    # Record audit note for takeover
    await record_audit_note(
        conn, tenant_id, site_id, "repair_session_takeover", new_session_id,
        "TAKEOVER", f"Took over session {session_id} from {previous_created_by}. Reason: {body.reason}",
        user_id
    )

    # Observability
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "repair_session_takeover",
        extra={
            "new_session_id": new_session_id,
            "previous_session_id": session_id,
            "previous_created_by": previous_created_by,
            "takeover_by": user_id,
            "takeover_reason": body.reason,
            "plan_version_id": plan_version_id,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "duration_ms": round(duration_ms, 2),
        }
    )

    return TakeoverResponse(
        new_session_id=new_session_id,
        previous_session_id=session_id,
        previous_created_by=previous_created_by,
        plan_version_id=plan_version_id,
        status="OPEN",
        expires_at=expires_at.isoformat(),
        takeover_reason=body.reason,
    )
