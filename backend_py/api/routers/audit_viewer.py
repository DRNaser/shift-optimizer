"""
SOLVEREIGN V4.7 - Audit Log Viewer API
======================================

Audit log viewing endpoints for compliance/security review.

Routes:
- GET /api/v1/audit           - List audit log entries
- GET /api/v1/audit/{id}      - Get audit entry detail
- GET /api/v1/audit/plan/{id} - Get plan lifecycle audit trail

NON-NEGOTIABLES:
- Tenant isolation via user context
- Read-only (audit logs are immutable)
- No PII exposure beyond what's necessary
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from ..security.internal_rbac import (
    InternalUserContext,
    TenantContext,
    require_tenant_context_with_permission,
    require_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["audit-viewer"])


# =============================================================================
# SCHEMAS
# =============================================================================

class AuditEntrySummary(BaseModel):
    """Audit entry summary for list view."""
    id: int
    event_type: str
    user_email: Optional[str]
    tenant_id: Optional[int]
    site_id: Optional[int]
    created_at: datetime
    has_details: bool


class AuditListResponse(BaseModel):
    """List of audit entries."""
    success: bool = True
    entries: List[AuditEntrySummary]
    total: int
    filters_applied: dict


class AuditEntryDetail(BaseModel):
    """Detailed audit entry."""
    id: int
    event_type: str
    user_id: Optional[str]
    user_email: Optional[str]
    tenant_id: Optional[int]
    site_id: Optional[int]
    session_id: Optional[str]
    details: Optional[dict]
    error_code: Optional[str]
    target_tenant_id: Optional[int]
    created_at: datetime


class AuditDetailResponse(BaseModel):
    """Single audit entry response."""
    success: bool = True
    entry: AuditEntryDetail


class PlanApprovalEntry(BaseModel):
    """Plan approval audit entry."""
    id: int
    plan_version_id: int
    action: Optional[str]
    from_state: Optional[str]
    to_state: Optional[str]
    performed_by: str
    reason: Optional[str]
    created_at: datetime


class PlanAuditTrailResponse(BaseModel):
    """Plan lifecycle audit trail."""
    success: bool = True
    plan_version_id: int
    approvals: List[PlanApprovalEntry]
    auth_events: List[AuditEntrySummary]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("", response_model=AuditListResponse)
async def list_audit_entries(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
    limit: int = Query(50, le=200),
    offset: int = 0,
    event_type: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    user_email: Optional[str] = None,
):
    """
    List audit log entries for the current tenant.

    Filters:
    - event_type: Filter by event type (login_success, plan_create, etc.)
    - from_date: Start of date range (ISO format)
    - to_date: End of date range (ISO format)
    - user_email: Filter by user email (partial match)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Build query with tenant filter
        base_query = """
            SELECT
                id, event_type, user_email, tenant_id, site_id,
                created_at, details IS NOT NULL as has_details
            FROM auth.audit_log
            WHERE (tenant_id = %s OR target_tenant_id = %s)
        """
        params = [ctx.tenant_id, ctx.tenant_id]

        if event_type:
            base_query += " AND event_type = %s"
            params.append(event_type)

        if from_date:
            base_query += " AND created_at >= %s"
            params.append(from_date)

        if to_date:
            base_query += " AND created_at <= %s"
            params.append(to_date)

        if user_email:
            base_query += " AND user_email ILIKE %s"
            params.append(f"%{user_email}%")

        base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(base_query, tuple(params))
        rows = cur.fetchall()

        # Get total count
        count_query = """
            SELECT COUNT(*)
            FROM auth.audit_log
            WHERE (tenant_id = %s OR target_tenant_id = %s)
        """
        count_params = [ctx.tenant_id, ctx.tenant_id]

        if event_type:
            count_query += " AND event_type = %s"
            count_params.append(event_type)
        if from_date:
            count_query += " AND created_at >= %s"
            count_params.append(from_date)
        if to_date:
            count_query += " AND created_at <= %s"
            count_params.append(to_date)
        if user_email:
            count_query += " AND user_email ILIKE %s"
            count_params.append(f"%{user_email}%")

        cur.execute(count_query, tuple(count_params))
        total = cur.fetchone()[0]

    entries = [
        AuditEntrySummary(
            id=row[0],
            event_type=row[1],
            user_email=row[2],
            tenant_id=row[3],
            site_id=row[4],
            created_at=row[5],
            has_details=row[6],
        )
        for row in rows
    ]

    filters_applied = {
        "event_type": event_type,
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "user_email": user_email,
    }

    return AuditListResponse(
        entries=entries,
        total=total,
        filters_applied=filters_applied,
    )


@router.get("/event-types")
async def list_event_types(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    List distinct event types in audit log for filter dropdown.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT event_type
            FROM auth.audit_log
            WHERE (tenant_id = %s OR target_tenant_id = %s)
            ORDER BY event_type
        """, (ctx.tenant_id, ctx.tenant_id))

        event_types = [row[0] for row in cur.fetchall()]

    return {"success": True, "event_types": event_types}


@router.get("/{entry_id}", response_model=AuditDetailResponse)
async def get_audit_entry(
    request: Request,
    entry_id: int,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.details.read")),
):
    """
    Get detailed audit entry.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id, event_type, user_id::text, user_email, tenant_id, site_id,
                session_id::text, details, error_code, target_tenant_id, created_at
            FROM auth.audit_log
            WHERE id = %s AND (tenant_id = %s OR target_tenant_id = %s)
            """,
            (entry_id, ctx.tenant_id, ctx.tenant_id)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Audit entry {entry_id} not found",
            )

        details = row[7]
        if isinstance(details, str):
            details = json.loads(details)

        entry = AuditEntryDetail(
            id=row[0],
            event_type=row[1],
            user_id=row[2],
            user_email=row[3],
            tenant_id=row[4],
            site_id=row[5],
            session_id=row[6],
            details=details,
            error_code=row[8],
            target_tenant_id=row[9],
            created_at=row[10],
        )

        return AuditDetailResponse(entry=entry)


@router.get("/plan/{plan_version_id}", response_model=PlanAuditTrailResponse)
async def get_plan_audit_trail(
    request: Request,
    plan_version_id: int,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get complete audit trail for a plan version.

    Includes:
    - Plan approvals (state transitions)
    - Related auth events (from auth.audit_log)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Verify plan belongs to tenant
        cur.execute(
            "SELECT id FROM plan_versions WHERE id = %s AND tenant_id = %s",
            (plan_version_id, ctx.tenant_id)
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_version_id} not found",
            )

        # Get plan approvals
        cur.execute(
            """
            SELECT id, plan_version_id, action, from_state, to_state,
                   performed_by, reason, created_at
            FROM plan_approvals
            WHERE plan_version_id = %s
            ORDER BY created_at DESC
            """,
            (plan_version_id,)
        )

        approvals = [
            PlanApprovalEntry(
                id=row[0],
                plan_version_id=row[1],
                action=row[2],
                from_state=row[3],
                to_state=row[4],
                performed_by=row[5],
                reason=row[6],
                created_at=row[7],
            )
            for row in cur.fetchall()
        ]

        # Get related auth events (events mentioning this plan_version_id in details)
        cur.execute(
            """
            SELECT id, event_type, user_email, tenant_id, site_id,
                   created_at, details IS NOT NULL as has_details
            FROM auth.audit_log
            WHERE (tenant_id = %s OR target_tenant_id = %s)
              AND details::text LIKE %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (ctx.tenant_id, ctx.tenant_id, f'%"plan_version_id": {plan_version_id}%')
        )

        auth_events = [
            AuditEntrySummary(
                id=row[0],
                event_type=row[1],
                user_email=row[2],
                tenant_id=row[3],
                site_id=row[4],
                created_at=row[5],
                has_details=row[6],
            )
            for row in cur.fetchall()
        ]

        return PlanAuditTrailResponse(
            plan_version_id=plan_version_id,
            approvals=approvals,
            auth_events=auth_events,
        )
