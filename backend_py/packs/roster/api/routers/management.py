"""
SOLVEREIGN V4.9 - Management Reports API
=========================================

Weekly and daily reporting endpoints for dispatchers and management.

Routes:
- GET /api/v1/roster/management/weekly-summary    - Weekly summary (Mon-Sun)
- GET /api/v1/roster/management/daily-summary     - Daily summary for a date
- GET /api/v1/roster/dispatcher/daily-ops-brief   - Dispatcher operational brief

NON-NEGOTIABLES:
- Tenant isolation via user context
- Frozen days use stored final_stats (no drift)
- Weekly aggregates computed efficiently in SQL
- All reports tenant-scoped via RLS
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List, Literal

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    TenantContext,
    require_tenant_context_with_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/roster/management",
    tags=["roster-management"]
)

dispatcher_router = APIRouter(
    prefix="/api/v1/roster/dispatcher",
    tags=["roster-dispatcher"]
)


# =============================================================================
# SCHEMAS
# =============================================================================

class DayStats(BaseModel):
    """Stats for a single day.

    IMPORTANT: Management reports consume these fields to understand data freshness:
    - is_frozen: True if day is frozen (immutable)
    - is_live: True if stats are computed on-demand (not from stored final_stats)
    - stats_source: "FINAL" if frozen (stored), "LIVE" if computed on-demand
    """
    date: str
    day_name: str
    is_frozen: bool
    total_slots: int = 0
    planned: int = 0
    assigned: int = 0
    executed: int = 0
    aborted: int = 0
    coverage_gaps: int = 0
    is_live: bool = True
    stats_source: Literal["FINAL", "LIVE"] = "LIVE"


class AbortBreakdown(BaseModel):
    """Abort counts by reason."""
    LOW_DEMAND: int = 0
    WEATHER: int = 0
    VEHICLE: int = 0
    OPS_DECISION: int = 0
    OTHER: int = 0


class WeeklyTotals(BaseModel):
    """Weekly aggregated totals."""
    total_slots: int = 0
    planned: int = 0
    assigned: int = 0
    executed: int = 0
    aborted: int = 0
    coverage_gaps: int = 0


class WeeklySummaryResponse(BaseModel):
    """Response for GET /management/weekly-summary."""
    success: bool = True
    tenant_id: int
    site_id: int
    week_start: str
    week_end: str
    daily: List[DayStats]
    totals: WeeklyTotals
    abort_total: int = 0
    abort_by_reason: Optional[AbortBreakdown] = None
    frozen_days: int = 0
    execution_rate: Optional[float] = None
    coverage_rate: Optional[float] = None
    computed_at: str


class DailySummaryResponse(BaseModel):
    """Response for GET /management/daily-summary."""
    success: bool = True
    tenant_id: int
    site_id: int
    date: str
    day_name: str
    is_frozen: bool
    stats: DayStats
    abort_breakdown: Optional[AbortBreakdown] = None
    is_live: bool = True
    stats_source: Literal["FINAL", "LIVE"] = "LIVE"
    computed_at: str = ""


class RiskItem(BaseModel):
    """A risk or attention item for dispatcher."""
    type: str  # UNASSIGNED, REST_RISK, HOURS_RISK, ABORTED
    severity: str  # HIGH, MEDIUM, LOW
    message: str
    slot_id: Optional[str] = None
    driver_id: Optional[str] = None
    suggested_action: Optional[str] = None


class DailyOpsBriefResponse(BaseModel):
    """Response for GET /dispatcher/daily-ops-brief."""
    success: bool = True
    date: str
    site_id: int
    is_frozen: bool
    summary: DayStats
    unassigned_count: int = 0
    aborted_today: int = 0
    risk_items: List[RiskItem] = []
    recommended_actions: List[str] = []


# =============================================================================
# WEEKLY SUMMARY ENDPOINT
# =============================================================================

@router.get("/weekly-summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
    request: Request,
    site_id: int,
    week_start: str,  # YYYY-MM-DD (Monday of the week)
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.reports.read")),
):
    """
    Get weekly summary for management reporting (Mon-Sun).

    Uses stored final_stats for frozen days (no drift).
    Computes live stats for open days.

    Returns:
    - Daily breakdown for 7 days
    - Weekly totals
    - Abort breakdown by reason
    - Coverage and execution rates
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        start_date = date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {week_start}. Expected YYYY-MM-DD (Monday)",
        )

    # Verify it's a Monday
    if start_date.weekday() != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"week_start must be a Monday. Got {start_date.strftime('%A')}",
        )

    # Call SQL function for weekly summary
    result = await conn.fetchrow(
        "SELECT dispatch.get_weekly_summary($1, $2, $3) as summary",
        ctx.tenant_id, site_id, start_date
    )

    if not result or not result["summary"]:
        # Return empty summary
        end_date = start_date + timedelta(days=6)
        return WeeklySummaryResponse(
            success=True,
            tenant_id=ctx.tenant_id,
            site_id=site_id,
            week_start=week_start,
            week_end=end_date.isoformat(),
            daily=[],
            totals=WeeklyTotals(),
            computed_at=date.today().isoformat(),
        )

    summary = result["summary"]

    # Parse daily stats
    daily_stats = []
    for day_data in summary.get("daily", []):
        stats = day_data.get("stats", {})
        day_is_frozen = day_data.get("is_frozen", False)
        day_is_live = stats.get("is_live", not day_is_frozen)
        daily_stats.append(DayStats(
            date=str(day_data.get("date", "")),
            day_name=day_data.get("day_name", ""),
            is_frozen=day_is_frozen,
            total_slots=stats.get("total_slots", 0) or 0,
            planned=stats.get("planned", 0) or 0,
            assigned=stats.get("assigned", 0) or 0,
            executed=stats.get("executed", 0) or 0,
            aborted=stats.get("aborted", 0) or 0,
            coverage_gaps=stats.get("coverage_gaps", 0) or 0,
            is_live=day_is_live,
            stats_source="FINAL" if day_is_frozen else "LIVE",
        ))

    # Parse totals
    totals_data = summary.get("totals", {})
    totals = WeeklyTotals(
        total_slots=totals_data.get("total_slots", 0) or 0,
        planned=totals_data.get("planned", 0) or 0,
        assigned=totals_data.get("assigned", 0) or 0,
        executed=totals_data.get("executed", 0) or 0,
        aborted=totals_data.get("aborted", 0) or 0,
        coverage_gaps=totals_data.get("coverage_gaps", 0) or 0,
    )

    # Parse abort breakdown
    abort_data = summary.get("abort_by_reason", {}) or {}
    abort_breakdown = AbortBreakdown(
        LOW_DEMAND=abort_data.get("LOW_DEMAND", 0) or 0,
        WEATHER=abort_data.get("WEATHER", 0) or 0,
        VEHICLE=abort_data.get("VEHICLE", 0) or 0,
        OPS_DECISION=abort_data.get("OPS_DECISION", 0) or 0,
        OTHER=abort_data.get("OTHER", 0) or 0,
    )

    # Compute rates
    total_slots = totals.total_slots
    execution_rate = None
    coverage_rate = None
    if total_slots > 0:
        executed_count = totals.executed
        assigned_count = totals.assigned
        execution_rate = (executed_count / total_slots) * 100 if executed_count else 0
        coverage_rate = ((total_slots - totals.coverage_gaps) / total_slots) * 100

    return WeeklySummaryResponse(
        success=True,
        tenant_id=ctx.tenant_id,
        site_id=site_id,
        week_start=week_start,
        week_end=summary.get("week_end", ""),
        daily=daily_stats,
        totals=totals,
        abort_total=summary.get("abort_total", 0) or 0,
        abort_by_reason=abort_breakdown,
        frozen_days=summary.get("frozen_days", 0) or 0,
        execution_rate=round(execution_rate, 1) if execution_rate is not None else None,
        coverage_rate=round(coverage_rate, 1) if coverage_rate is not None else None,
        computed_at=str(summary.get("computed_at", "")),
    )


# =============================================================================
# DAILY SUMMARY ENDPOINT
# =============================================================================

@router.get("/daily-summary", response_model=DailySummaryResponse)
async def get_daily_summary(
    request: Request,
    site_id: int,
    date_str: str,  # YYYY-MM-DD
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.reports.read")),
):
    """
    Get daily summary for a specific date.

    If frozen: uses stored final_stats (no recomputation).
    If open: computes live stats marked with is_live=True.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
        )

    # Get day status
    day_row = await conn.fetchrow(
        """
        SELECT status, final_stats FROM dispatch.workbench_days
        WHERE tenant_id = $1 AND site_id = $2 AND day_date = $3
        """,
        ctx.tenant_id, site_id, target_date
    )

    is_frozen = day_row and day_row["status"] == "FROZEN"

    # Get stats (SQL function handles frozen vs live)
    stats_row = await conn.fetchrow(
        "SELECT dispatch.get_daily_stats($1, $2, $3) as stats",
        ctx.tenant_id, site_id, target_date
    )
    stats = stats_row["stats"] if stats_row else {}

    # Get abort breakdown
    abort_data = stats.get("abort_breakdown", {}) or {}
    abort_breakdown = AbortBreakdown(
        LOW_DEMAND=abort_data.get("LOW_DEMAND", 0) or 0,
        WEATHER=abort_data.get("WEATHER", 0) or 0,
        VEHICLE=abort_data.get("VEHICLE", 0) or 0,
        OPS_DECISION=abort_data.get("OPS_DECISION", 0) or 0,
        OTHER=abort_data.get("OTHER", 0) or 0,
    )

    day_name = target_date.strftime("%A")
    stats_source = "FINAL" if is_frozen else "LIVE"
    computed_at = datetime.now(timezone.utc).isoformat()

    return DailySummaryResponse(
        success=True,
        tenant_id=ctx.tenant_id,
        site_id=site_id,
        date=date_str,
        day_name=day_name,
        is_frozen=is_frozen,
        stats=DayStats(
            date=date_str,
            day_name=day_name,
            is_frozen=is_frozen,
            total_slots=stats.get("total_slots", 0) or 0,
            planned=stats.get("planned", 0) or 0,
            assigned=stats.get("assigned", 0) or 0,
            executed=stats.get("executed", 0) or 0,
            aborted=stats.get("aborted", 0) or 0,
            coverage_gaps=stats.get("coverage_gaps", 0) or 0,
            is_live=stats.get("is_live", not is_frozen),
            stats_source=stats_source,
        ),
        abort_breakdown=abort_breakdown,
        is_live=not is_frozen,
        stats_source=stats_source,
        computed_at=computed_at,
    )


# =============================================================================
# DISPATCHER OPS BRIEF ENDPOINT
# =============================================================================

@dispatcher_router.get("/daily-ops-brief", response_model=DailyOpsBriefResponse)
async def get_daily_ops_brief(
    request: Request,
    site_id: int,
    date_str: str,  # YYYY-MM-DD
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.reports.read")),
):
    """
    Get daily operational brief for dispatchers.

    Returns "what needs attention":
    - Unassigned slots
    - Aborted slots today
    - Rest/overlap risks
    - Drivers at hours risk
    - Recommended actions
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
        )

    # Get day status
    day_row = await conn.fetchrow(
        """
        SELECT status FROM dispatch.workbench_days
        WHERE tenant_id = $1 AND site_id = $2 AND day_date = $3
        """,
        ctx.tenant_id, site_id, target_date
    )
    is_frozen = day_row and day_row["status"] == "FROZEN"

    # Get stats
    stats_row = await conn.fetchrow(
        "SELECT dispatch.get_daily_stats($1, $2, $3) as stats",
        ctx.tenant_id, site_id, target_date
    )
    stats = stats_row["stats"] if stats_row else {}

    # Build risk items
    risk_items: List[RiskItem] = []
    recommended_actions: List[str] = []

    # Unassigned slots
    unassigned_count = stats.get("coverage_gaps", 0) or 0
    if unassigned_count > 0:
        risk_items.append(RiskItem(
            type="UNASSIGNED",
            severity="HIGH" if unassigned_count > 5 else "MEDIUM",
            message=f"{unassigned_count} slot(s) without driver assignment",
            suggested_action="Assign drivers to cover these slots",
        ))
        recommended_actions.append(f"Review and assign {unassigned_count} unassigned slot(s)")

    # Aborted slots
    aborted_today = stats.get("aborted", 0) or 0
    if aborted_today > 0:
        risk_items.append(RiskItem(
            type="ABORTED",
            severity="LOW",
            message=f"{aborted_today} slot(s) marked as aborted today",
            suggested_action="Review abort reasons for reporting",
        ))

    # TODO: Add rest/overlap risks from validation
    # TODO: Add hours risks from driver data

    day_name = target_date.strftime("%A")
    stats_source = "FINAL" if is_frozen else "LIVE"

    return DailyOpsBriefResponse(
        success=True,
        date=date_str,
        site_id=site_id,
        is_frozen=is_frozen,
        summary=DayStats(
            date=date_str,
            day_name=day_name,
            is_frozen=is_frozen,
            total_slots=stats.get("total_slots", 0) or 0,
            planned=stats.get("planned", 0) or 0,
            assigned=stats.get("assigned", 0) or 0,
            executed=stats.get("executed", 0) or 0,
            aborted=stats.get("aborted", 0) or 0,
            coverage_gaps=unassigned_count,
            is_live=stats.get("is_live", not is_frozen),
            stats_source=stats_source,
        ),
        unassigned_count=unassigned_count,
        aborted_today=aborted_today,
        risk_items=risk_items,
        recommended_actions=recommended_actions,
    )
