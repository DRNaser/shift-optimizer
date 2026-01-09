"""
SOLVEREIGN Service Status API
==============================

Endpoints for service health status and escalation management.

Platform View:
- GET /api/v1/platform/status - All active escalations
- GET /api/v1/platform/orgs/{org_code}/status - Org-specific status
- POST /api/v1/platform/escalations - Record new escalation
- POST /api/v1/platform/escalations/{id}/resolve - Resolve escalation

Tenant View:
- GET /api/v1/tenant/status - Status for current tenant context
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_core_tenant, CoreTenantContext
from ..database import DatabaseManager
from ..security.internal_signature import (
    require_platform_admin,
    InternalContext
)

router = APIRouter()


# =============================================================================
# ENUMS
# =============================================================================

class SeverityLevel(str, Enum):
    S0 = "S0"  # Security/Data Leak
    S1 = "S1"  # Integrity
    S2 = "S2"  # Operational Degraded
    S3 = "S3"  # Minor/UX


class ServiceStatusEnum(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class ScopeType(str, Enum):
    PLATFORM = "platform"
    ORG = "org"
    TENANT = "tenant"
    SITE = "site"


# =============================================================================
# SCHEMAS
# =============================================================================

class EscalationResponse(BaseModel):
    """Single escalation event."""
    id: str
    scope_type: ScopeType
    scope_id: Optional[str]
    status: ServiceStatusEnum
    severity: SeverityLevel
    reason_code: str
    reason_message: Optional[str]
    fix_steps: Optional[List[str]]
    runbook_link: Optional[str]
    details: Optional[dict]
    started_at: datetime
    updated_at: datetime
    ended_at: Optional[datetime]
    resolved_by: Optional[str]


class ServiceStatusResponse(BaseModel):
    """Aggregated service status."""
    overall_status: ServiceStatusEnum
    highest_severity: Optional[SeverityLevel]
    active_escalations: List[EscalationResponse]
    total_active: int
    blocked_count: int
    degraded_count: int


class RecordEscalationRequest(BaseModel):
    """Request to record a new escalation."""
    scope_type: ScopeType
    scope_id: Optional[str] = None  # Required for non-platform scopes
    reason_code: str = Field(..., min_length=3, max_length=100)
    details: Optional[dict] = None


class ResolveEscalationRequest(BaseModel):
    """Request to resolve an escalation."""
    resolved_by: str = Field(default="operator", max_length=255)


# =============================================================================
# PLATFORM STATUS ENDPOINTS
# =============================================================================

@router.get("/platform/status", response_model=ServiceStatusResponse)
async def get_platform_status(
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Get platform-wide service status.

    Returns all active escalations across all scopes.
    Requires: Platform admin (verified internal signature)
    """
    return await _get_status_for_scope(db, scope_type=None, scope_id=None)


@router.get("/platform/orgs/{org_code}/status", response_model=ServiceStatusResponse)
async def get_org_status(
    org_code: str,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Get service status for a specific organization.

    Returns platform-wide + org-specific + tenant/site escalations.
    Requires: Platform admin (verified internal signature)
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Get org ID
            await cur.execute(
                "SELECT id FROM core.organizations WHERE org_code = %s",
                (org_code,)
            )
            org = await cur.fetchone()
            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Organization '{org_code}' not found"
                )

            return await _get_status_for_scope(
                db, scope_type="org", scope_id=str(org["id"]), include_platform=True
            )


@router.post("/platform/escalations", response_model=EscalationResponse, status_code=201)
async def record_escalation(
    request: RecordEscalationRequest,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Record a new escalation event.

    Requires: Platform admin (verified internal signature)
    """
    # Validate scope_id requirement
    if request.scope_type != ScopeType.PLATFORM and not request.scope_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"scope_id is required for scope_type '{request.scope_type}'"
        )

    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Record escalation using helper function
            await cur.execute("""
                SELECT core.record_escalation(%s::core.scope_type, %s, %s, %s)
            """, (
                request.scope_type.value,
                request.scope_id,
                request.reason_code,
                request.details or {}
            ))

            result = await cur.fetchone()
            escalation_id = result["record_escalation"]

            # Fetch the created escalation
            await cur.execute("""
                SELECT * FROM core.service_status WHERE id = %s
            """, (escalation_id,))

            row = await cur.fetchone()
            return _row_to_escalation(row)


@router.post("/platform/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: str,
    request: ResolveEscalationRequest,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Resolve an active escalation.

    Requires: Platform admin (verified internal signature)
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Update escalation
            await cur.execute("""
                UPDATE core.service_status
                SET ended_at = NOW(),
                    resolved_by = %s,
                    status = 'healthy'
                WHERE id = %s AND ended_at IS NULL
                RETURNING id
            """, (request.resolved_by, escalation_id))

            result = await cur.fetchone()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Active escalation '{escalation_id}' not found"
                )

            return {"status": "resolved", "escalation_id": escalation_id}


@router.get("/platform/escalations", response_model=List[EscalationResponse])
async def list_escalations(
    active_only: bool = True,
    severity: Optional[SeverityLevel] = None,
    scope_type: Optional[ScopeType] = None,
    limit: int = 100,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    List escalations with optional filters.

    Requires: Platform admin (verified internal signature)
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Build query
            conditions = []
            params = []

            if active_only:
                conditions.append("ended_at IS NULL")

            if severity:
                conditions.append("severity = %s")
                params.append(severity.value)

            if scope_type:
                conditions.append("scope_type = %s")
                params.append(scope_type.value)

            where_clause = " AND ".join(conditions) if conditions else "TRUE"

            await cur.execute(f"""
                SELECT * FROM core.service_status
                WHERE {where_clause}
                ORDER BY
                    CASE severity
                        WHEN 'S0' THEN 0
                        WHEN 'S1' THEN 1
                        WHEN 'S2' THEN 2
                        WHEN 'S3' THEN 3
                    END,
                    started_at DESC
                LIMIT %s
            """, (*params, limit))

            rows = await cur.fetchall()
            return [_row_to_escalation(row) for row in rows]


# =============================================================================
# TENANT STATUS ENDPOINT
# =============================================================================

@router.get("/tenant/status", response_model=ServiceStatusResponse)
async def get_tenant_status(
    tenant: CoreTenantContext = Depends(get_core_tenant),
    db: DatabaseManager = Depends(get_db)
):
    """
    Get service status for current tenant.

    Returns platform-wide + org + tenant + site-specific escalations.
    Uses RLS to ensure tenant can only see relevant status.
    """
    # Get org ID for tenant
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(%s, %s, FALSE)",
                (tenant.tenant_id, tenant.site_id)
            )

            # Get tenant's org
            await cur.execute("""
                SELECT owner_org_id FROM core.tenants WHERE id = %s
            """, (tenant.tenant_id,))
            tenant_row = await cur.fetchone()
            org_id = str(tenant_row["owner_org_id"]) if tenant_row else None

            # Get escalations visible to this tenant
            await cur.execute("""
                SELECT * FROM core.service_status
                WHERE ended_at IS NULL
                ORDER BY
                    CASE severity
                        WHEN 'S0' THEN 0
                        WHEN 'S1' THEN 1
                        WHEN 'S2' THEN 2
                        WHEN 'S3' THEN 3
                    END,
                    started_at DESC
            """)

            rows = await cur.fetchall()

            return _build_status_response(rows)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def _get_status_for_scope(
    db: DatabaseManager,
    scope_type: Optional[str],
    scope_id: Optional[str],
    include_platform: bool = False
) -> ServiceStatusResponse:
    """Get service status for a specific scope."""
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            if scope_type is None:
                # Platform-wide: get all active
                await cur.execute("""
                    SELECT * FROM core.service_status
                    WHERE ended_at IS NULL
                    ORDER BY
                        CASE severity
                            WHEN 'S0' THEN 0
                            WHEN 'S1' THEN 1
                            WHEN 'S2' THEN 2
                            WHEN 'S3' THEN 3
                        END,
                        started_at DESC
                """)
            elif include_platform:
                # Include platform-wide + specific scope
                await cur.execute("""
                    SELECT * FROM core.service_status
                    WHERE ended_at IS NULL
                      AND (
                          scope_type = 'platform'
                          OR (scope_type = %s AND scope_id = %s)
                      )
                    ORDER BY
                        CASE severity
                            WHEN 'S0' THEN 0
                            WHEN 'S1' THEN 1
                            WHEN 'S2' THEN 2
                            WHEN 'S3' THEN 3
                        END,
                        started_at DESC
                """, (scope_type, scope_id))
            else:
                # Specific scope only
                await cur.execute("""
                    SELECT * FROM core.service_status
                    WHERE ended_at IS NULL
                      AND scope_type = %s
                      AND (scope_id = %s OR (scope_id IS NULL AND %s IS NULL))
                    ORDER BY
                        CASE severity
                            WHEN 'S0' THEN 0
                            WHEN 'S1' THEN 1
                            WHEN 'S2' THEN 2
                            WHEN 'S3' THEN 3
                        END,
                        started_at DESC
                """, (scope_type, scope_id, scope_id))

            rows = await cur.fetchall()
            return _build_status_response(rows)


def _build_status_response(rows: list) -> ServiceStatusResponse:
    """Build ServiceStatusResponse from database rows."""
    escalations = [_row_to_escalation(row) for row in rows]

    blocked_count = sum(1 for e in escalations if e.status == ServiceStatusEnum.BLOCKED)
    degraded_count = sum(1 for e in escalations if e.status == ServiceStatusEnum.DEGRADED)

    # Determine overall status
    if blocked_count > 0:
        overall_status = ServiceStatusEnum.BLOCKED
    elif degraded_count > 0:
        overall_status = ServiceStatusEnum.DEGRADED
    else:
        overall_status = ServiceStatusEnum.HEALTHY

    # Get highest severity
    highest_severity = None
    if escalations:
        severity_order = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
        highest_severity = min(
            escalations,
            key=lambda e: severity_order.get(e.severity.value, 4)
        ).severity

    return ServiceStatusResponse(
        overall_status=overall_status,
        highest_severity=highest_severity,
        active_escalations=escalations,
        total_active=len(escalations),
        blocked_count=blocked_count,
        degraded_count=degraded_count
    )


def _row_to_escalation(row: dict) -> EscalationResponse:
    """Convert database row to EscalationResponse."""
    return EscalationResponse(
        id=str(row["id"]),
        scope_type=ScopeType(row["scope_type"]),
        scope_id=str(row["scope_id"]) if row.get("scope_id") else None,
        status=ServiceStatusEnum(row["status"]),
        severity=SeverityLevel(row["severity"]),
        reason_code=row["reason_code"],
        reason_message=row.get("reason_message"),
        fix_steps=row.get("fix_steps"),
        runbook_link=row.get("runbook_link"),
        details=row.get("details"),
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        ended_at=row.get("ended_at"),
        resolved_by=row.get("resolved_by")
    )
