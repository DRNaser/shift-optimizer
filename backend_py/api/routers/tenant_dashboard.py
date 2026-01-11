"""
SOLVEREIGN V4.7 - Tenant Dashboard API
======================================

Dashboard API for tenant-scoped operational overview.

Route:
- GET /api/v1/tenant/dashboard

NON-NEGOTIABLES:
- Tenant isolation via user context
- Empty states handled honestly
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from ..security.internal_rbac import (
    TenantContext,
    require_tenant_context_with_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenant", tags=["tenant-dashboard"])


# =============================================================================
# SCHEMAS
# =============================================================================

class SnapshotSummary(BaseModel):
    """Last published snapshot info."""
    snapshot_id: Optional[int]
    version_number: Optional[int]
    published_at: Optional[datetime]
    published_by: Optional[str]
    age_hours: Optional[float]
    is_frozen: bool = False


class PlanSummary(BaseModel):
    """Last plan version info."""
    plan_version_id: Optional[int]
    status: Optional[str]
    plan_state: Optional[str]
    created_at: Optional[datetime]


class RunSummary(BaseModel):
    """Last solver run info."""
    run_id: Optional[str]
    verdict: Optional[str]
    runtime_seconds: Optional[float]
    completed_at: Optional[datetime]


class OpenItemsCount(BaseModel):
    """Counts of open items requiring attention."""
    uncovered_shifts: int = 0
    rest_violations: int = 0
    pending_acknowledgements: int = 0


class DashboardLinks(BaseModel):
    """Links to related resources."""
    evidence_viewer: str = "/platform-admin/evidence"
    audit_log: str = "/platform-admin/audit"
    grafana: Optional[str] = None


class TenantDashboardResponse(BaseModel):
    """Tenant dashboard response."""
    success: bool = True
    tenant_id: int
    tenant_name: Optional[str]
    site_id: Optional[int]
    site_name: Optional[str]

    # Snapshot info
    last_published_snapshot: SnapshotSummary

    # Plan info
    last_plan_version: PlanSummary

    # Run info (placeholder for now)
    last_run: RunSummary

    # Open items
    open_items: OpenItemsCount

    # Links
    links: DashboardLinks

    # Timestamps
    generated_at: datetime


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/dashboard", response_model=TenantDashboardResponse)
async def get_tenant_dashboard(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get tenant dashboard with operational overview.

    Returns:
    - Last published snapshot info
    - Last plan version info
    - Last solver run info
    - Open items counts
    - Links to evidence/audit viewers
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # Get tenant name
        tenant_name = None
        cur.execute("SELECT name FROM tenants WHERE id = %s", (ctx.tenant_id,))
        row = cur.fetchone()
        if row:
            tenant_name = row[0]

        # Get site name
        site_name = None
        if ctx.site_id:
            cur.execute("SELECT name FROM sites WHERE id = %s", (ctx.site_id,))
            row = cur.fetchone()
            if row:
                site_name = row[0]

        # Get last published snapshot
        snapshot_query = """
            SELECT id, version_number, published_at, published_by, freeze_until
            FROM plan_snapshots
            WHERE tenant_id = %s AND snapshot_status = 'ACTIVE'
        """
        params = [ctx.tenant_id]
        if ctx.site_id:
            snapshot_query += " AND site_id = %s"
            params.append(ctx.site_id)
        snapshot_query += " ORDER BY published_at DESC LIMIT 1"

        cur.execute(snapshot_query, tuple(params))
        snapshot_row = cur.fetchone()

        if snapshot_row:
            age_hours = (now - snapshot_row[2]).total_seconds() / 3600 if snapshot_row[2] else None
            is_frozen = snapshot_row[4] > now if snapshot_row[4] else False
            last_snapshot = SnapshotSummary(
                snapshot_id=snapshot_row[0],
                version_number=snapshot_row[1],
                published_at=snapshot_row[2],
                published_by=snapshot_row[3],
                age_hours=round(age_hours, 1) if age_hours else None,
                is_frozen=is_frozen,
            )
        else:
            last_snapshot = SnapshotSummary()

        # Get last plan version
        plan_query = """
            SELECT id, status, COALESCE(plan_state, 'DRAFT'), created_at
            FROM plan_versions
            WHERE tenant_id = %s
        """
        params = [ctx.tenant_id]
        if ctx.site_id:
            plan_query += " AND site_id = %s"
            params.append(ctx.site_id)
        plan_query += " ORDER BY created_at DESC LIMIT 1"

        cur.execute(plan_query, tuple(params))
        plan_row = cur.fetchone()

        if plan_row:
            last_plan = PlanSummary(
                plan_version_id=plan_row[0],
                status=plan_row[1],
                plan_state=plan_row[2],
                created_at=plan_row[3],
            )
        else:
            last_plan = PlanSummary()

        # Get last solver run (from solver_runs table if exists)
        last_run = RunSummary()
        try:
            cur.execute("""
                SELECT run_id::text, verdict, runtime_seconds, completed_at
                FROM solver_runs
                WHERE tenant_id = %s
                ORDER BY completed_at DESC NULLS LAST
                LIMIT 1
            """, (ctx.tenant_id,))
            run_row = cur.fetchone()
            if run_row:
                last_run = RunSummary(
                    run_id=run_row[0],
                    verdict=run_row[1],
                    runtime_seconds=run_row[2],
                    completed_at=run_row[3],
                )
        except Exception:
            # solver_runs table may not exist in all environments
            pass

        # Get open items counts (placeholders - implement based on actual schema)
        open_items = OpenItemsCount()

        # Try to get uncovered shifts from dispatch schema
        try:
            cur.execute("""
                SELECT COUNT(*)
                FROM dispatch.dispatch_open_shifts
                WHERE tenant_id = %s AND status = 'DETECTED'
            """, (ctx.tenant_id,))
            open_items.uncovered_shifts = cur.fetchone()[0]
        except Exception:
            pass

        # Try to get pending portal acknowledgements
        try:
            cur.execute("""
                SELECT COUNT(*)
                FROM portal.portal_sessions
                WHERE tenant_id = %s AND ack_status = 'PENDING'
            """, (ctx.tenant_id,))
            open_items.pending_acknowledgements = cur.fetchone()[0]
        except Exception:
            pass

        # Build links
        links = DashboardLinks(
            evidence_viewer=f"/platform-admin/evidence?tenant_id={ctx.tenant_id}",
            audit_log=f"/platform-admin/audit?tenant_id={ctx.tenant_id}",
            grafana=None,  # Configure via env var
        )

    return TenantDashboardResponse(
        tenant_id=ctx.tenant_id,
        tenant_name=tenant_name,
        site_id=ctx.site_id,
        site_name=site_name,
        last_published_snapshot=last_snapshot,
        last_plan_version=last_plan,
        last_run=last_run,
        open_items=open_items,
        links=links,
        generated_at=now,
    )
