"""
SOLVEREIGN V4.6 - Roster Diff API
==================================

Diff and impact preview endpoints for the Roster Pack.

Routes:
- GET /api/v1/roster/plans/{plan_id}/diff - Get diff against published snapshot

PURPOSE:
- Compare current plan draft vs last published snapshot
- Show KPI deltas (coverage, hours, FTE, etc.)
- List assignment changes (added, removed, modified)
- Calculate churn metrics
- Gate publish (BLOCK if BLOCK violations exist)

SECURITY:
- Tenant isolation via user context
- RLS enforced on all queries
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    TenantContext,
    require_tenant_context_with_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roster", tags=["roster-diff"])


# =============================================================================
# SCHEMAS
# =============================================================================

class KPIDelta(BaseModel):
    """KPI delta between current and baseline."""
    metric: str
    label: str
    current: Optional[float] = None
    baseline: Optional[float] = None
    delta: float = 0.0
    delta_pct: Optional[float] = None
    is_positive_good: bool = True


class AssignmentChange(BaseModel):
    """A single assignment change."""
    change_type: str = Field(..., description="added, removed, modified")
    tour_instance_id: int
    day: int
    block_id: Optional[str] = None
    before_driver_id: Optional[str] = None
    before_driver_name: Optional[str] = None
    after_driver_id: Optional[str] = None
    after_driver_name: Optional[str] = None


class DiffSummary(BaseModel):
    """Summary of diff results."""
    churn_count: int = Field(..., description="Number of changed assignments")
    affected_drivers: int = Field(..., description="Number of affected drivers")
    added: int = 0
    removed: int = 0
    modified: int = 0


class BaselineInfo(BaseModel):
    """Information about the baseline used for comparison."""
    type: str = Field(..., description="snapshot or plan")
    id: int
    version_number: Optional[int] = None
    published_at: Optional[str] = None


class PublishGating(BaseModel):
    """Publish gating information."""
    can_publish: bool
    blocked_reasons: List[str] = Field(default_factory=list)
    block_count: int = 0
    warn_count: int = 0


class DiffResponse(BaseModel):
    """Response from diff endpoint."""
    success: bool = True
    plan_version_id: int
    baseline: BaselineInfo
    kpi_deltas: List[KPIDelta]
    changes: List[AssignmentChange]
    summary: DiffSummary
    publish_gating: PublishGating


# =============================================================================
# HELPERS
# =============================================================================

def compute_plan_kpis(
    conn,
    plan_id: int,
    tenant_id: int,
) -> Dict[str, Any]:
    """Compute KPIs for a plan."""
    with conn.cursor() as cur:
        # Get assignment counts
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT driver_id) as driver_count,
                COUNT(*) as assignment_count,
                COUNT(DISTINCT CASE WHEN role = 'PRIMARY' THEN driver_id END) as fte_count,
                COUNT(DISTINCT CASE WHEN role = 'PART_TIME' THEN driver_id END) as pt_count
            FROM assignments
            WHERE plan_version_id = %s
            """,
            (plan_id,)
        )
        counts = cur.fetchone()

        # Get total hours
        cur.execute(
            """
            SELECT COALESCE(SUM(ti.duration_min), 0) / 60.0 as total_hours
            FROM assignments a
            JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = %s
            """,
            (plan_id,)
        )
        hours = cur.fetchone()

        # Get coverage (assigned vs total tours)
        cur.execute(
            """
            SELECT COUNT(*) FROM assignments WHERE plan_version_id = %s
            """,
            (plan_id,)
        )
        assigned = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM tour_instances ti
            JOIN forecast_versions fv ON ti.forecast_version_id = fv.id
            JOIN plan_versions pv ON pv.forecast_version_id = fv.id
            WHERE pv.id = %s
            """,
            (plan_id,)
        )
        total_tours = cur.fetchone()[0]

        coverage_pct = (assigned / total_tours * 100) if total_tours > 0 else 0

    return {
        "driver_count": counts[0] or 0,
        "assignment_count": counts[1] or 0,
        "fte_count": counts[2] or 0,
        "pt_count": counts[3] or 0,
        "total_hours": float(hours[0] or 0),
        "coverage_pct": round(coverage_pct, 1),
        "total_tours": total_tours,
    }


def load_snapshot_assignments(
    conn,
    snapshot_id: int,
) -> Dict[int, Dict]:
    """Load assignments from a snapshot's JSON."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT assignments_snapshot FROM plan_snapshots WHERE id = %s
            """,
            (snapshot_id,)
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return {}

        assignments_json = row[0]
        if isinstance(assignments_json, str):
            assignments_json = json.loads(assignments_json)

        # Build lookup by tour_instance_id
        result = {}
        for asgn in assignments_json:
            tour_id = asgn.get("tour_instance_id")
            if tour_id:
                result[tour_id] = asgn

        return result


def load_plan_assignments(
    conn,
    plan_id: int,
) -> Dict[int, Dict]:
    """Load current assignments from plan."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.tour_instance_id, a.driver_id, a.day, a.block_id
            FROM assignments a
            WHERE a.plan_version_id = %s
            """,
            (plan_id,)
        )
        rows = cur.fetchall()

        result = {}
        for row in rows:
            result[row[0]] = {
                "tour_instance_id": row[0],
                "driver_id": row[1],
                "day": row[2],
                "block_id": row[3],
            }

        return result


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/plans/{plan_id}/diff", response_model=DiffResponse)
async def get_diff(
    request: Request,
    plan_id: int,
    base_snapshot_id: Optional[int] = Query(None, description="Snapshot to compare against (defaults to latest published)"),
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get diff between current plan state and a published snapshot.

    If base_snapshot_id is not provided, uses the most recent published snapshot
    for this plan.

    Returns:
    - KPI deltas (coverage, drivers, hours, etc.)
    - Assignment changes (added, removed, modified)
    - Churn metrics
    - Publish gating (can_publish, blocked_reasons)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Verify plan exists
        cur.execute(
            """
            SELECT id, tenant_id, site_id, current_snapshot_id
            FROM plan_versions
            WHERE id = %s AND tenant_id = %s
            """,
            (plan_id, ctx.tenant_id)
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_id} not found or access denied",
            )

        # Find baseline snapshot
        if base_snapshot_id:
            cur.execute(
                """
                SELECT id, version_number, published_at
                FROM plan_snapshots
                WHERE id = %s AND tenant_id = %s
                """,
                (base_snapshot_id, ctx.tenant_id)
            )
            snapshot = cur.fetchone()
            if not snapshot:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Snapshot {base_snapshot_id} not found",
                )
        else:
            # Get latest published snapshot
            cur.execute(
                """
                SELECT id, version_number, published_at
                FROM plan_snapshots
                WHERE plan_version_id = %s AND tenant_id = %s
                  AND snapshot_status = 'ACTIVE'
                ORDER BY version_number DESC
                LIMIT 1
                """,
                (plan_id, ctx.tenant_id)
            )
            snapshot = cur.fetchone()

        if snapshot:
            baseline = BaselineInfo(
                type="snapshot",
                id=snapshot[0],
                version_number=snapshot[1],
                published_at=snapshot[2].isoformat() if snapshot[2] else None,
            )
            baseline_assignments = load_snapshot_assignments(conn, snapshot[0])
        else:
            # No snapshot - compare against empty baseline
            baseline = BaselineInfo(
                type="plan",
                id=0,
                version_number=None,
                published_at=None,
            )
            baseline_assignments = {}

        # Load current assignments
        current_assignments = load_plan_assignments(conn, plan_id)

        # Load drivers for names
        cur.execute(
            """
            SELECT id, name FROM drivers WHERE tenant_id = %s
            """,
            (ctx.tenant_id,)
        )
        drivers_raw = cur.fetchall()
        drivers_map = {str(row[0]): row[1] for row in drivers_raw}

    # Compute changes
    changes = []
    affected_driver_ids = set()

    # Find added and modified
    for tour_id, current in current_assignments.items():
        baseline_asgn = baseline_assignments.get(tour_id)

        if not baseline_asgn:
            # Added
            changes.append(AssignmentChange(
                change_type="added",
                tour_instance_id=tour_id,
                day=current.get("day", 0),
                block_id=current.get("block_id"),
                before_driver_id=None,
                before_driver_name=None,
                after_driver_id=current.get("driver_id"),
                after_driver_name=drivers_map.get(str(current.get("driver_id")), str(current.get("driver_id"))),
            ))
            if current.get("driver_id"):
                affected_driver_ids.add(current.get("driver_id"))
        elif str(baseline_asgn.get("driver_id")) != str(current.get("driver_id")):
            # Modified
            changes.append(AssignmentChange(
                change_type="modified",
                tour_instance_id=tour_id,
                day=current.get("day", 0),
                block_id=current.get("block_id"),
                before_driver_id=str(baseline_asgn.get("driver_id")),
                before_driver_name=drivers_map.get(str(baseline_asgn.get("driver_id")), str(baseline_asgn.get("driver_id"))),
                after_driver_id=current.get("driver_id"),
                after_driver_name=drivers_map.get(str(current.get("driver_id")), str(current.get("driver_id"))),
            ))
            if baseline_asgn.get("driver_id"):
                affected_driver_ids.add(str(baseline_asgn.get("driver_id")))
            if current.get("driver_id"):
                affected_driver_ids.add(current.get("driver_id"))

    # Find removed
    for tour_id, baseline_asgn in baseline_assignments.items():
        if tour_id not in current_assignments:
            changes.append(AssignmentChange(
                change_type="removed",
                tour_instance_id=tour_id,
                day=baseline_asgn.get("day", 0),
                block_id=baseline_asgn.get("block_id"),
                before_driver_id=str(baseline_asgn.get("driver_id")),
                before_driver_name=drivers_map.get(str(baseline_asgn.get("driver_id")), str(baseline_asgn.get("driver_id"))),
                after_driver_id=None,
                after_driver_name=None,
            ))
            if baseline_asgn.get("driver_id"):
                affected_driver_ids.add(str(baseline_asgn.get("driver_id")))

    # Sort changes by day then tour_id
    changes.sort(key=lambda c: (c.day, c.tour_instance_id))

    # Compute KPIs
    current_kpis = compute_plan_kpis(conn, plan_id, ctx.tenant_id)

    # Baseline KPIs from snapshot or compute
    if snapshot:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kpi_snapshot FROM plan_snapshots WHERE id = %s
                """,
                (snapshot[0],)
            )
            kpi_row = cur.fetchone()
            if kpi_row and kpi_row[0]:
                baseline_kpis = kpi_row[0] if isinstance(kpi_row[0], dict) else json.loads(kpi_row[0])
            else:
                baseline_kpis = {
                    "driver_count": 0,
                    "total_hours": 0,
                    "coverage_pct": 0,
                    "fte_count": 0,
                }
    else:
        baseline_kpis = {
            "driver_count": 0,
            "total_hours": 0,
            "coverage_pct": 0,
            "fte_count": 0,
        }

    # Build KPI deltas
    kpi_deltas = []

    # Coverage
    current_cov = current_kpis.get("coverage_pct", 0)
    baseline_cov = baseline_kpis.get("coverage_pct", 0)
    delta_cov = current_cov - baseline_cov
    kpi_deltas.append(KPIDelta(
        metric="coverage_pct",
        label="Coverage",
        current=current_cov,
        baseline=baseline_cov,
        delta=round(delta_cov, 1),
        delta_pct=round((delta_cov / baseline_cov * 100) if baseline_cov else 0, 1),
        is_positive_good=True,
    ))

    # Total drivers
    current_drivers = current_kpis.get("driver_count", 0)
    baseline_drivers = baseline_kpis.get("driver_count", 0)
    delta_drivers = current_drivers - baseline_drivers
    kpi_deltas.append(KPIDelta(
        metric="driver_count",
        label="Drivers",
        current=current_drivers,
        baseline=baseline_drivers,
        delta=delta_drivers,
        delta_pct=round((delta_drivers / baseline_drivers * 100) if baseline_drivers else 0, 1),
        is_positive_good=True,
    ))

    # Total hours
    current_hours = current_kpis.get("total_hours", 0)
    baseline_hours = baseline_kpis.get("total_hours", 0)
    delta_hours = current_hours - baseline_hours
    kpi_deltas.append(KPIDelta(
        metric="total_hours",
        label="Total Hours",
        current=round(current_hours, 1),
        baseline=round(baseline_hours, 1),
        delta=round(delta_hours, 1),
        delta_pct=round((delta_hours / baseline_hours * 100) if baseline_hours else 0, 1),
        is_positive_good=True,
    ))

    # FTE count
    current_fte = current_kpis.get("fte_count", 0)
    baseline_fte = baseline_kpis.get("fte_count", 0)
    delta_fte = current_fte - baseline_fte
    kpi_deltas.append(KPIDelta(
        metric="fte_count",
        label="FTE Drivers",
        current=current_fte,
        baseline=baseline_fte,
        delta=delta_fte,
        is_positive_good=True,
    ))

    # Churn (always bad - lower is better)
    churn_count = len(changes)
    kpi_deltas.append(KPIDelta(
        metric="churn_count",
        label="Churn",
        current=churn_count,
        baseline=0,
        delta=churn_count,
        is_positive_good=False,
    ))

    # Summary
    added_count = sum(1 for c in changes if c.change_type == "added")
    removed_count = sum(1 for c in changes if c.change_type == "removed")
    modified_count = sum(1 for c in changes if c.change_type == "modified")

    summary = DiffSummary(
        churn_count=churn_count,
        affected_drivers=len(affected_driver_ids),
        added=added_count,
        removed=removed_count,
        modified=modified_count,
    )

    # Publish gating - check violations
    from packs.roster.api.routers.violations import compute_violations

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.driver_id, a.tour_instance_id, a.day, a.block_id,
                   ti.start_ts, ti.end_ts, ti.duration_min
            FROM assignments a
            LEFT JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = %s
            """,
            (plan_id,)
        )
        assignments_raw = cur.fetchall()

    assignments_list = []
    for row in assignments_raw:
        assignments_list.append({
            "driver_id": row[0],
            "tour_instance_id": row[1],
            "day": row[2],
            "block_id": row[3],
            "start_ts": row[4],
            "end_ts": row[5],
            "duration_min": row[6],
        })

    violations = compute_violations(assignments_list, {str(k): {"name": v} for k, v in drivers_map.items()})
    block_count = sum(1 for v in violations if v["severity"] == "BLOCK")
    warn_count = sum(1 for v in violations if v["severity"] == "WARN")

    blocked_reasons = []
    if block_count > 0:
        blocked_reasons.append(f"{block_count} blocking violation(s) exist")

    publish_gating = PublishGating(
        can_publish=block_count == 0,
        blocked_reasons=blocked_reasons,
        block_count=block_count,
        warn_count=warn_count,
    )

    logger.info(
        "diff_computed",
        extra={
            "plan_id": plan_id,
            "baseline_id": baseline.id,
            "changes": len(changes),
            "can_publish": publish_gating.can_publish,
            "tenant_id": ctx.tenant_id,
        }
    )

    return DiffResponse(
        success=True,
        plan_version_id=plan_id,
        baseline=baseline,
        kpi_deltas=kpi_deltas,
        changes=changes,
        summary=summary,
        publish_gating=publish_gating,
    )
