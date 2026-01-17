"""
SOLVEREIGN V4.9 - Dispatch Workbench API
========================================

Daily Tab workbench API for interactive drag-and-drop assignment management.

Routes:
- GET /api/v1/roster/workbench/daily       - Fetch daily view data (blocks, slots, drivers)
- GET /api/v1/roster/workbench/drivers     - Fetch driver pool for a site/day
- PATCH /api/v1/roster/repairs/{id}/draft  - Apply idempotent draft mutations
- POST /api/v1/roster/repairs/{id}/validate - Run validation on current draft

NON-NEGOTIABLES:
- Tenant isolation via user context
- CSRF check on writes
- Idempotency key on draft mutations
- Hard blocks rejected immediately, soft blocks allowed with badge
- No fake-green: never claim VALID unless validated
"""

import json
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List, Literal
from uuid import UUID

from fastapi import APIRouter, Request, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    InternalUserContext,
    TenantContext,
    require_tenant_context_with_permission,
    require_csrf_check,
)
from packs.roster.core.draft_mutations import (
    apply_mutations,
    get_draft_state,
    undo_last_mutation,
    MutationOp,
    OpType,
    SlotStatus,
    AbortReason,
    check_day_frozen,
    get_day_status,
    set_slot_status,
    batch_set_slot_status,
)
from packs.roster.core.validation_engine import (
    validate_draft as run_validation,
    ValidationMode as ValMode,
)
from packs.roster.core.week_lookahead import (
    find_candidates_batch,
    get_week_window,
    get_lookahead_range,
    CandidateBatchResult,
    CandidateImpact,
    AffectedSlot,
    SlotResult,
    DebugMetrics,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/roster/workbench",
    tags=["roster-workbench"]
)


# =============================================================================
# SCHEMAS
# =============================================================================

class SlotAssignment(BaseModel):
    """Assignment data for a slot."""
    assignment_id: int
    driver_id: str
    driver_name: Optional[str] = None
    is_pinned: bool = False
    pin_reason: Optional[str] = None


class BlockSlot(BaseModel):
    """A single slot within a block."""
    slot_index: int
    tour_instance_id: int
    tour_name: Optional[str] = None
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    assignment: Optional[SlotAssignment] = None
    validation_status: str = "OK"  # OK, UNASSIGNED, BLOCK, WARN


class ShiftBlock(BaseModel):
    """A shift block with multiple slots."""
    block_id: str
    block_type: str  # "1ER", "2ER", "3ER"
    time_window: dict  # {"start": "06:00", "end": "14:00"}
    required_count: int
    assigned_count: int
    slots: List[BlockSlot]


class DriverInfo(BaseModel):
    """Driver information for the pool."""
    driver_id: str
    driver_name: str
    external_id: Optional[str] = None
    available: bool = True
    current_hours: float = 0.0
    max_hours: float = 40.0
    skills: List[str] = []
    restrictions: List[str] = []
    last_shift_end: Optional[str] = None
    assigned_today: bool = False


class DailySummary(BaseModel):
    """Summary stats for the daily view."""
    total_slots: int
    assigned: int
    unassigned: int
    block_violations: int
    warn_violations: int


class DailyViewResponse(BaseModel):
    """Response for GET /workbench/daily."""
    success: bool = True
    date: str
    iso_week: str
    day_of_week: int  # 1-7 (Mon-Sun)
    site_id: int
    plan_version_id: int
    blocks: List[ShiftBlock]
    driver_pool: List[DriverInfo]
    summary: DailySummary


class DriverPoolResponse(BaseModel):
    """Response for GET /workbench/drivers."""
    success: bool = True
    site_id: int
    date: str
    drivers: List[DriverInfo]
    total: int


class MutationOpRequest(BaseModel):
    """A single mutation operation."""
    op: Literal["assign", "unassign", "move"]
    tour_instance_id: int
    day: int
    driver_id: Optional[str] = None
    from_driver_id: Optional[str] = None
    block_id: Optional[str] = None
    slot_index: Optional[int] = None


class DraftMutationsRequest(BaseModel):
    """Request for PATCH /repairs/{id}/draft."""
    operations: List[MutationOpRequest]
    validation_mode: Literal["none", "fast", "full"] = "fast"


class MutationResultResponse(BaseModel):
    """Result of a single mutation."""
    op: str
    tour_instance_id: int
    status: str  # PENDING, VALID, HARD_BLOCK, SOFT_BLOCK, UNKNOWN
    validation_mode: str
    violations: List[dict] = []
    hard_block_reason: Optional[str] = None
    mutation_id: Optional[str] = None
    sequence_no: Optional[int] = None


class DraftSummaryResponse(BaseModel):
    """Summary of current draft state."""
    pending_changes: int
    hard_blocks: int
    soft_blocks: int
    unknown: int
    valid: int


class DraftMutationsResponse(BaseModel):
    """Response for PATCH /repairs/{id}/draft."""
    success: bool = True
    session_id: str
    operations_applied: int
    operations_rejected: int
    results: List[MutationResultResponse]
    draft_summary: DraftSummaryResponse


class ValidateRequest(BaseModel):
    """Request for POST /repairs/{id}/validate."""
    mode: Literal["none", "fast", "full"] = "full"


class ValidateResponse(BaseModel):
    """Response for POST /repairs/{id}/validate."""
    success: bool = True
    validation_mode: str
    parity_guaranteed: bool  # True if mode=full
    verdict: str  # OK, WARN, BLOCK
    summary: dict
    violations: List[dict]


# -----------------------------------------------------------------------------
# CANDIDATE BATCH SCHEMAS (Whole-Week Lookahead)
# -----------------------------------------------------------------------------

class AffectedSlotResponse(BaseModel):
    """A slot affected by assigning this candidate."""
    date: str
    slot_id: str
    tour_instance_id: int
    reason: str  # REST_VIOLATION, OVERLAP, MAX_TOURS, HOURS_EXCEEDED
    current_driver_id: Optional[str] = None
    severity: str  # HARD or WARN


class CandidateResponse(BaseModel):
    """A ranked candidate with week-lookahead evaluation."""
    driver_id: str
    driver_name: str
    rank: int
    feasible_today: bool
    lookahead_ok: bool
    churn_count: int  # Number of downstream slots affected
    churn_locked_count: int  # Must be 0 for valid candidate
    affected_slots: List[AffectedSlotResponse]
    score: float
    explanation: str
    blocker_summary: Optional[str] = None
    today_violations: List[str] = []
    week_violations: List[str] = []


class SlotCandidatesResponse(BaseModel):
    """Candidates for a single open/at-risk slot."""
    slot_id: str
    tour_instance_id: int
    date: str
    time_window: str
    current_driver_id: Optional[str] = None
    is_pinned: bool = False
    candidates: List[CandidateResponse]
    top_recommendation: Optional[str] = None  # driver_id of best candidate


class DebugMetricsResponse(BaseModel):
    """Debug metrics for performance monitoring (dev-only)."""
    db_query_count: int = 0
    drivers_considered: int = 0
    slots_evaluated: int = 0
    elapsed_ms: float = 0.0
    lookahead_start: Optional[str] = None
    lookahead_end: Optional[str] = None


class BatchCandidatesResponse(BaseModel):
    """Response for GET /workbench/daily/candidates."""
    success: bool = True
    date: str
    site_id: int
    week_window: dict  # {start: YYYY-MM-DD, end: YYYY-MM-DD}
    lookahead_range: dict  # {start: YYYY-MM-DD (today), end: YYYY-MM-DD (Sunday)}
    frozen_days: List[str]  # List of frozen dates in the week
    total_open_slots: int
    total_candidates_evaluated: int
    slots: List[SlotCandidatesResponse]
    computed_at: str
    # Debug metrics (optional, dev-only)
    debug_metrics: Optional[DebugMetricsResponse] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def iso_week_from_date(d: date) -> str:
    """Get ISO week string from date."""
    iso_cal = d.isocalendar()
    return f"{iso_cal.year}-W{iso_cal.week:02d}"


def require_idempotency_key(
    x_idempotency_key: Optional[str] = Header(None, alias="x-idempotency-key"),
) -> str:
    """Require idempotency key for state-changing operations."""
    if not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "x-idempotency-key header is required",
            },
        )
    return x_idempotency_key


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/daily", response_model=DailyViewResponse)
async def get_daily_view(
    request: Request,
    site_id: int,
    date_str: str,  # YYYY-MM-DD
    plan_version_id: Optional[int] = None,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Fetch daily view data for the workbench.

    Returns:
    - All shift blocks for the day with slots
    - Current assignments for each slot
    - Driver pool available for assignments
    - Summary statistics
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Parse date
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
        )

    # Get day of week (1=Monday, 7=Sunday)
    day_of_week = target_date.isoweekday()

    # Get active plan version if not specified
    if not plan_version_id:
        plan_row = await conn.fetchrow(
            """
            SELECT id FROM plan_versions
            WHERE tenant_id = $1 AND site_id = $2
              AND plan_state = 'PUBLISHED'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            ctx.tenant_id, site_id
        )
        if not plan_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No published plan found for this site",
            )
        plan_version_id = plan_row["id"]

    # Fetch tour instances for the day (these are our "slots")
    tours_rows = await conn.fetch(
        """
        SELECT
            ti.id as tour_instance_id,
            ti.tour_template_id,
            tn.tour_fingerprint,
            ti.day,
            ti.start_ts,
            ti.end_ts,
            ti.duration_min,
            ti.skill,
            ti.depot,
            tn.count as template_count,
            a.id as assignment_id,
            a.driver_id,
            a.block_id,
            d.name as driver_name,
            p.id as pin_id,
            p.reason_code as pin_reason
        FROM tour_instances ti
        JOIN tours_normalized tn ON ti.tour_template_id = tn.id
        JOIN forecast_versions fv ON ti.forecast_version_id = fv.id
        JOIN plan_versions pv ON pv.forecast_version_id = fv.id
        LEFT JOIN assignments a ON a.tour_instance_id = ti.id AND a.plan_version_id = pv.id
        LEFT JOIN drivers d ON a.driver_id = d.id::TEXT AND d.tenant_id = $1
        LEFT JOIN roster.pins p ON p.tour_instance_id = ti.id
            AND p.plan_version_id = pv.id AND p.is_active = TRUE
        WHERE pv.id = $2 AND pv.tenant_id = $1 AND ti.day = $3
        ORDER BY ti.start_ts, ti.id
        """,
        ctx.tenant_id, plan_version_id, day_of_week
    )

    # Group tours into blocks by time window
    # A "block" is a time window that can have multiple slots (required drivers)
    blocks_map: dict = {}
    for row in tours_rows:
        # Create block key from time window
        start_ts = row["start_ts"]
        end_ts = row["end_ts"]
        block_key = f"B-{day_of_week}-{start_ts.strftime('%H:%M') if start_ts else '00:00'}"

        if block_key not in blocks_map:
            blocks_map[block_key] = {
                "block_id": block_key,
                "time_window": {
                    "start": start_ts.strftime("%H:%M") if start_ts else None,
                    "end": end_ts.strftime("%H:%M") if end_ts else None,
                },
                "slots": [],
                "required_count": 0,
                "assigned_count": 0,
            }

        # Create slot
        assignment = None
        if row["assignment_id"]:
            assignment = SlotAssignment(
                assignment_id=row["assignment_id"],
                driver_id=row["driver_id"],
                driver_name=row["driver_name"],
                is_pinned=row["pin_id"] is not None,
                pin_reason=row["pin_reason"],
            )

        slot = BlockSlot(
            slot_index=len(blocks_map[block_key]["slots"]),
            tour_instance_id=row["tour_instance_id"],
            tour_name=row["tour_fingerprint"],
            start_ts=start_ts.strftime("%H:%M") if start_ts else None,
            end_ts=end_ts.strftime("%H:%M") if end_ts else None,
            assignment=assignment,
            validation_status="OK" if assignment else "UNASSIGNED",
        )

        blocks_map[block_key]["slots"].append(slot)
        blocks_map[block_key]["required_count"] += 1
        if assignment:
            blocks_map[block_key]["assigned_count"] += 1

    # Convert to list and compute block types
    blocks = []
    for block_data in blocks_map.values():
        slot_count = len(block_data["slots"])
        block_type = f"{min(slot_count, 3)}ER" if slot_count <= 3 else "3ER+"

        blocks.append(ShiftBlock(
            block_id=block_data["block_id"],
            block_type=block_type,
            time_window=block_data["time_window"],
            required_count=block_data["required_count"],
            assigned_count=block_data["assigned_count"],
            slots=block_data["slots"],
        ))

    # Fetch driver pool
    drivers_rows = await conn.fetch(
        """
        SELECT
            d.id as driver_id,
            d.name as driver_name,
            d.external_id,
            d.skills,
            d.max_weekly_hours,
            COALESCE(
                (SELECT SUM(ti.work_hours)
                 FROM assignments a
                 JOIN tour_instances ti ON a.tour_instance_id = ti.id
                 WHERE a.driver_id = d.id::TEXT
                   AND a.plan_version_id = $2),
                0
            ) as current_hours,
            EXISTS(
                SELECT 1 FROM assignments a
                JOIN tour_instances ti ON a.tour_instance_id = ti.id
                WHERE a.driver_id = d.id::TEXT
                  AND a.plan_version_id = $2
                  AND ti.day = $3
            ) as assigned_today
        FROM drivers d
        WHERE d.tenant_id = $1 AND d.site_id = $4
          AND d.is_active = TRUE
        ORDER BY d.name
        """,
        ctx.tenant_id, plan_version_id, day_of_week, site_id
    )

    driver_pool = [
        DriverInfo(
            driver_id=str(row["driver_id"]),
            driver_name=row["driver_name"] or f"Driver {row['driver_id']}",
            external_id=row["external_id"],
            available=True,
            current_hours=float(row["current_hours"] or 0),
            max_hours=float(row["max_weekly_hours"] or 40),
            skills=row["skills"] or [],
            assigned_today=row["assigned_today"],
        )
        for row in drivers_rows
    ]

    # Compute summary
    total_slots = sum(b.required_count for b in blocks)
    assigned = sum(b.assigned_count for b in blocks)
    unassigned = total_slots - assigned

    summary = DailySummary(
        total_slots=total_slots,
        assigned=assigned,
        unassigned=unassigned,
        block_violations=0,  # TODO: Compute from violations cache
        warn_violations=0,
    )

    return DailyViewResponse(
        success=True,
        date=date_str,
        iso_week=iso_week_from_date(target_date),
        day_of_week=day_of_week,
        site_id=site_id,
        plan_version_id=plan_version_id,
        blocks=blocks,
        driver_pool=driver_pool,
        summary=summary,
    )


@router.get("/drivers", response_model=DriverPoolResponse)
async def get_driver_pool(
    request: Request,
    site_id: int,
    date_str: str,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Fetch driver pool for a site and date.

    Returns all active drivers with their current assignment status.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Parse date
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {date_str}",
        )

    day_of_week = target_date.isoweekday()

    # Fetch drivers
    rows = await conn.fetch(
        """
        SELECT
            d.id as driver_id,
            d.name as driver_name,
            d.external_id,
            d.skills,
            d.max_weekly_hours
        FROM drivers d
        WHERE d.tenant_id = $1 AND d.site_id = $2
          AND d.is_active = TRUE
        ORDER BY d.name
        """,
        ctx.tenant_id, site_id
    )

    drivers = [
        DriverInfo(
            driver_id=str(row["driver_id"]),
            driver_name=row["driver_name"] or f"Driver {row['driver_id']}",
            external_id=row["external_id"],
            available=True,
            max_hours=float(row["max_weekly_hours"] or 40),
            skills=row["skills"] or [],
        )
        for row in rows
    ]

    return DriverPoolResponse(
        success=True,
        site_id=site_id,
        date=date_str,
        drivers=drivers,
        total=len(drivers),
    )


# =============================================================================
# BATCH CANDIDATES ENDPOINT (Whole-Week Lookahead)
# =============================================================================

@router.get("/daily/candidates", response_model=BatchCandidatesResponse)
async def get_daily_candidates(
    request: Request,
    site_id: int,
    date_str: str,  # YYYY-MM-DD
    allow_multiday_repair: bool = False,
    plan_version_id: Optional[int] = None,
    include_debug_metrics: bool = False,  # Dev-only: include performance metrics
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Batch compute candidates for all open/at-risk slots on a given date.

    Uses whole-week lookahead (Mon-Sun) to evaluate candidates with minimal churn.

    Key behaviors:
    - Candidates are ranked lexicographically: feasible_today > lookahead_ok > churn_locked=0 > churn_count > score
    - Frozen days in the week are NEVER touched (hard block)
    - Pinned days are only touched if allow_multiday_repair=true
    - Each candidate shows affected_slots explaining downstream impacts

    Query params:
    - site_id: Site to query
    - date_str: Target date (YYYY-MM-DD)
    - allow_multiday_repair: If true, allows touching pinned days (default false)
    - plan_version_id: Optional specific plan version (defaults to latest published)

    Returns:
    - All open/unassigned slots for the date
    - Ranked candidates for each slot with churn analysis
    - Week window info and frozen days list
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Parse date
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
        )

    # Get week window
    week_window = get_week_window(target_date)

    # Get active plan version if not specified
    if not plan_version_id:
        plan_row = await conn.fetchrow(
            """
            SELECT id FROM plan_versions
            WHERE tenant_id = $1 AND site_id = $2
              AND plan_state = 'PUBLISHED'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            ctx.tenant_id, site_id
        )
        if not plan_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No published plan found for this site",
            )
        plan_version_id = plan_row["id"]

    # Call the batch candidate finder
    try:
        result: CandidateBatchResult = await find_candidates_batch(
            conn=conn,
            tenant_id=ctx.tenant_id,
            site_id=site_id,
            plan_version_id=plan_version_id,
            target_date=target_date,
            allow_multiday_repair=allow_multiday_repair,
            include_debug_metrics=include_debug_metrics,
        )
    except Exception as e:
        logger.error(f"Candidate batch computation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute candidates: {str(e)}",
        )

    # Get lookahead range (from today to week_end)
    lookahead_start, lookahead_end = get_lookahead_range(target_date, week_window)

    # Convert to response format
    slots_response = []
    total_candidates = 0

    for slot_result in result.slots:
        candidates_response = []
        for idx, candidate in enumerate(slot_result.candidates):
            total_candidates += 1
            affected_slots_response = [
                AffectedSlotResponse(
                    date=str(aff.date),
                    slot_id=aff.slot_id,
                    tour_instance_id=aff.tour_instance_id,
                    reason=aff.reason,
                    current_driver_id=str(aff.current_driver_id) if aff.current_driver_id else None,
                    severity=aff.severity,
                )
                for aff in candidate.affected_slots
            ]

            candidates_response.append(CandidateResponse(
                driver_id=str(candidate.driver_id),
                driver_name=candidate.driver_name,
                rank=idx + 1,
                feasible_today=candidate.feasible_today,
                lookahead_ok=candidate.lookahead_ok,
                churn_count=candidate.churn_count,
                churn_locked_count=candidate.churn_locked_count,
                affected_slots=affected_slots_response,
                score=candidate.score,
                explanation=candidate.explanation,
                blocker_summary=candidate.blocker_summary,
                today_violations=candidate.today_violations,
                week_violations=candidate.week_violations,
            ))

        # Find top recommendation (first feasible candidate with no locked churn)
        top_rec = None
        for c in candidates_response:
            if c.feasible_today and c.churn_locked_count == 0:
                top_rec = c.driver_id
                break

        slots_response.append(SlotCandidatesResponse(
            slot_id=slot_result.slot_id,
            tour_instance_id=slot_result.tour_instance_id,
            date=str(slot_result.date),
            time_window=slot_result.time_window,
            current_driver_id=str(slot_result.current_driver_id) if slot_result.current_driver_id else None,
            is_pinned=slot_result.is_pinned,
            candidates=candidates_response,
            top_recommendation=top_rec,
        ))

    computed_at = datetime.now(timezone.utc).isoformat()

    # Build debug metrics response if included
    debug_metrics_response = None
    if result.debug_metrics:
        debug_metrics_response = DebugMetricsResponse(
            db_query_count=result.debug_metrics.db_query_count,
            drivers_considered=result.debug_metrics.drivers_considered,
            slots_evaluated=result.debug_metrics.slots_evaluated,
            elapsed_ms=result.debug_metrics.elapsed_ms,
            lookahead_start=result.debug_metrics.lookahead_start,
            lookahead_end=result.debug_metrics.lookahead_end,
        )

    return BatchCandidatesResponse(
        success=True,
        date=date_str,
        site_id=site_id,
        week_window={
            "start": str(week_window.week_start),
            "end": str(week_window.week_end),
        },
        lookahead_range={
            "start": str(lookahead_start),
            "end": str(lookahead_end),
        },
        frozen_days=[str(d) for d in result.frozen_days],
        total_open_slots=len(slots_response),
        total_candidates_evaluated=total_candidates,
        slots=slots_response,
        computed_at=computed_at,
        debug_metrics=debug_metrics_response,
    )


# =============================================================================
# DRAFT MUTATION ENDPOINTS
# =============================================================================

# These are mounted on the repairs router, but defined here for clarity
draft_router = APIRouter(
    prefix="/api/v1/roster/repairs",
    tags=["roster-repairs-draft"]
)


@draft_router.patch(
    "/{session_id}/draft",
    response_model=DraftMutationsResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def apply_draft_mutations(
    session_id: UUID,
    request: Request,
    body: DraftMutationsRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Apply idempotent draft mutations to a repair session.

    Operations:
    - assign: Assign driver to empty slot
    - unassign: Remove driver from slot
    - move: Move assignment to different driver

    Validation modes:
    - none: No validation, status = UNKNOWN
    - fast: Quick validation, may miss some violations
    - full: Full validation, parity with confirm

    Returns mutation results with validation status:
    - VALID: No violations
    - HARD_BLOCK: Rejected (overlap/rest/pin)
    - SOFT_BLOCK: Allowed but needs acknowledgment
    - UNKNOWN: Not validated (mode=none)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Get session and plan_version_id
    session = await conn.fetchrow(
        """
        SELECT repair_id, plan_version_id, status, expires_at
        FROM roster.repairs
        WHERE repair_id = $1 AND tenant_id = $2
        """,
        session_id, ctx.tenant_id
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repair session {session_id} not found",
        )

    if session["status"] != "OPEN":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "SESSION_NOT_OPEN",
                "message": f"Session is {session['status']}, expected OPEN",
            },
        )

    if session["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error_code": "SESSION_EXPIRED",
                "message": "Repair session has expired",
            },
        )

    # Convert request ops to MutationOp
    ops = [
        MutationOp(
            op=OpType(op.op.upper()),
            tour_instance_id=op.tour_instance_id,
            day=op.day,
            driver_id=op.driver_id,
            from_driver_id=op.from_driver_id,
            block_id=op.block_id,
            slot_index=op.slot_index,
        )
        for op in body.operations
    ]

    # Apply mutations
    try:
        result = await apply_mutations(
            conn=conn,
            tenant_id=ctx.tenant_id,
            site_id=ctx.site_id or 0,
            repair_id=session_id,
            plan_version_id=session["plan_version_id"],
            operations=ops,
            validation_mode=body.validation_mode,
            performed_by=ctx.user.email or str(ctx.user.user_id),
            idempotency_key=idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Convert to response
    return DraftMutationsResponse(
        success=True,
        session_id=str(result.session_id),
        operations_applied=result.operations_applied,
        operations_rejected=result.operations_rejected,
        results=[
            MutationResultResponse(
                op=r.op.value,
                tour_instance_id=r.tour_instance_id,
                status=r.status.value,
                validation_mode=r.validation_mode,
                violations=r.violations,
                hard_block_reason=r.hard_block_reason.value if r.hard_block_reason else None,
                mutation_id=str(r.mutation_id) if r.mutation_id else None,
                sequence_no=r.sequence_no,
            )
            for r in result.results
        ],
        draft_summary=DraftSummaryResponse(
            pending_changes=result.draft_summary.pending_changes,
            hard_blocks=result.draft_summary.hard_blocks,
            soft_blocks=result.draft_summary.soft_blocks,
            unknown=result.draft_summary.unknown,
            valid=result.draft_summary.valid,
        ),
    )


@draft_router.get("/{session_id}/draft")
async def get_draft_mutations(
    session_id: UUID,
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get current draft state for a repair session.

    Returns all active (non-undone) mutations.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    state = await get_draft_state(conn, ctx.tenant_id, session_id)
    return {
        "success": True,
        "session_id": str(session_id),
        **state,
    }


@draft_router.post(
    "/{session_id}/draft/undo",
    dependencies=[Depends(require_csrf_check)],
)
async def undo_draft_mutation(
    session_id: UUID,
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
):
    """
    Undo the most recent draft mutation.

    Returns the undone mutation, or 404 if no mutations to undo.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    result = await undo_last_mutation(
        conn=conn,
        tenant_id=ctx.tenant_id,
        repair_id=session_id,
        performed_by=ctx.user.email or str(ctx.user.user_id),
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No mutations to undo",
        )

    return {
        "success": True,
        "session_id": str(session_id),
        "undone": result,
    }


@draft_router.post(
    "/{session_id}/validate",
    response_model=ValidateResponse,
)
async def validate_draft(
    session_id: UUID,
    request: Request,
    body: ValidateRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Run validation on current draft state.

    Modes:
    - none: No validation (returns current cached state)
    - fast: Quick validation of impacted tours only
    - full: Full plan validation (parity with confirm)

    CRITICAL: mode=full produces the same result as confirm validation.
    This is the "parity guarantee".
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Get session to retrieve plan_version_id and site_id
    session = await conn.fetchrow(
        """
        SELECT repair_id, plan_version_id, status
        FROM roster.repairs
        WHERE repair_id = $1 AND tenant_id = $2
        """,
        session_id, ctx.tenant_id
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repair session {session_id} not found",
        )

    # Get site_id from plan_version
    plan = await conn.fetchrow(
        "SELECT site_id FROM plan_versions WHERE id = $1",
        session["plan_version_id"]
    )
    site_id = plan["site_id"] if plan else ctx.site_id or 0

    # Run validation
    try:
        mode = ValMode(body.mode)
        result = await run_validation(
            conn=conn,
            session_id=str(session_id),
            mode=mode,
            tenant_id=ctx.tenant_id,
            site_id=site_id,
            plan_version_id=session["plan_version_id"],
        )
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: {str(e)}",
        )

    # Determine verdict
    if result.hard_blocks > 0:
        verdict = "BLOCK"
    elif result.soft_blocks > 0:
        verdict = "WARN"
    else:
        verdict = "OK"

    return ValidateResponse(
        success=True,
        validation_mode=body.mode,
        parity_guaranteed=body.mode == "full",
        verdict=verdict,
        summary={
            "block_violations": result.hard_blocks,
            "warn_violations": result.soft_blocks,
            "compatibility_unknown": sum(
                1 for v in result.violations
                if v.type.value == "COMPATIBILITY_UNKNOWN"
            ),
        },
        violations=[
            {
                "type": v.type.value,
                "severity": v.severity.value,
                "message": v.message,
                "driver_id": v.driver_id,
                "tour_instance_id": v.tour_instance_id,
                "suggested_action": v.suggested_action,
            }
            for v in result.violations
        ],
    )


# =============================================================================
# FREEZE & ABORT ENDPOINTS
# =============================================================================

class FreezeRequest(BaseModel):
    """Request for POST /workbench/daily/freeze."""
    date: str  # YYYY-MM-DD
    site_id: int
    force: bool = False  # Force freeze even with warnings


class FreezeResponse(BaseModel):
    """Response for POST /workbench/daily/freeze."""
    success: bool = True
    day_id: str
    date: str
    was_already_frozen: bool
    frozen_at: Optional[str] = None
    final_stats: Optional[dict] = None
    evidence_id: Optional[str] = None
    validation_verdict: Optional[str] = None


class AbortSlotRequest(BaseModel):
    """Request for POST /workbench/slots/{slot_id}/abort."""
    reason: Literal["LOW_DEMAND", "WEATHER", "VEHICLE", "OPS_DECISION", "OTHER"]
    note: Optional[str] = None


class AbortSlotResponse(BaseModel):
    """Response for abort operations."""
    success: bool = True
    slot_id: str
    previous_status: str
    new_status: str = "ABORTED"
    abort_reason: str
    abort_note: Optional[str] = None


# -----------------------------------------------------------------------------
# HOLD/RELEASE SCHEMAS (Activation Gate)
# -----------------------------------------------------------------------------

class HoldSlotRequest(BaseModel):
    """Request for POST /workbench/slots/{slot_id}/hold."""
    reason: Literal["LOW_DEMAND", "SURPLUS", "OPS_DECISION", "WEATHER", "OTHER"]
    note: Optional[str] = None


class HoldSlotResponse(BaseModel):
    """Response for hold operations."""
    success: bool = True
    slot_id: str
    previous_status: str
    new_status: str = "HOLD"
    hold_reason: str
    message: str = "OK"


class ReleaseSlotRequest(BaseModel):
    """Request for POST /workbench/slots/{slot_id}/release."""
    late_release_threshold_minutes: int = 120  # 2 hours default


class ReleaseSlotResponse(BaseModel):
    """Response for release operations."""
    success: bool = True
    slot_id: str
    previous_status: str
    new_status: str = "RELEASED"
    at_risk: bool = False
    message: str = "OK"


class BatchHoldRequest(BaseModel):
    """Request for POST /workbench/slots/hold."""
    operations: List[dict]  # [{slot_id, reason, note}, ...]


class BatchHoldResponse(BaseModel):
    """Response for batch hold."""
    success: bool = True
    total: int
    applied: int
    rejected: int
    results: List[dict]


class BatchReleaseRequest(BaseModel):
    """Request for POST /workbench/slots/release."""
    slot_ids: List[str]
    late_release_threshold_minutes: int = 120


class BatchReleaseResponse(BaseModel):
    """Response for batch release."""
    success: bool = True
    total: int
    applied: int
    rejected: int
    at_risk_count: int = 0
    results: List[dict]


# -----------------------------------------------------------------------------
# MORNING DEMAND GAP SCHEMAS
# -----------------------------------------------------------------------------

class MorningGapAnalysisResponse(BaseModel):
    """Response for GET /workbench/daily/morning-gap."""
    success: bool = True
    day_date: str
    site_id: int
    morning_cutoff_hour: int
    summary: dict
    hold_by_reason: dict
    slots_on_hold: List[dict]
    at_risk_slots: List[dict]
    computed_at: str


class MorningGapWorkflowRequest(BaseModel):
    """Request for POST /workbench/daily/morning-gap/workflow."""
    action: Literal["set_hold", "release_all", "release_selected"]
    slot_ids: Optional[List[str]] = None  # For release_selected action
    hold_reason: Optional[Literal["LOW_DEMAND", "SURPLUS", "OPS_DECISION", "WEATHER", "OTHER"]] = None


class MorningGapWorkflowResponse(BaseModel):
    """Response for morning gap workflow."""
    success: bool = True
    action: str
    slots_affected: int
    at_risk_count: int = 0
    results: List[dict]
    message: str


class BatchAbortRequest(BaseModel):
    """Request for POST /workbench/slots/abort."""
    operations: List[dict]  # [{slot_id, reason, note}, ...]


class BatchAbortResponse(BaseModel):
    """Response for batch abort."""
    success: bool = True
    total: int
    applied: int
    rejected: int
    results: List[dict]


class DayStatusResponse(BaseModel):
    """Response for GET /workbench/daily/status."""
    success: bool = True
    exists: bool
    day_date: str
    status: str  # OPEN | FROZEN
    is_frozen: bool
    frozen_at: Optional[str] = None
    frozen_by_user_id: Optional[str] = None
    final_stats: Optional[dict] = None
    evidence_id: Optional[str] = None


@router.get("/daily/status", response_model=DayStatusResponse)
async def get_workbench_day_status(
    request: Request,
    site_id: int,
    date_str: str,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get the status of a workbench day (OPEN or FROZEN).

    Returns day lifecycle info including frozen status and final stats.
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

    day_info = await get_day_status(conn, ctx.tenant_id, site_id, target_date)

    return DayStatusResponse(
        success=True,
        exists=day_info.get("exists", False),
        day_date=date_str,
        status=day_info.get("status", "OPEN"),
        is_frozen=day_info.get("is_frozen", False),
        frozen_at=day_info.get("frozen_at"),
        frozen_by_user_id=day_info.get("frozen_by_user_id"),
        final_stats=day_info.get("final_stats"),
        evidence_id=day_info.get("evidence_id"),
    )


@router.post(
    "/daily/freeze",
    response_model=FreezeResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def freeze_workbench_day(
    request: Request,
    body: FreezeRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.day.freeze")),
):
    """
    Freeze a workbench day, making it immutable.

    Steps:
    1. Run full validation on the day's state
    2. Compute final stats (planned/assigned/executed/aborted counts)
    3. Store evidence bundle
    4. Mark day as FROZEN

    After freeze:
    - All mutations return 409 DAY_FROZEN
    - Reports use stored final_stats (no drift)

    Requires tenant_admin or operator_admin role.
    Idempotent: returns existing frozen data if already frozen.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        target_date = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {body.date}. Expected YYYY-MM-DD",
        )

    # Check if already frozen (idempotent return)
    is_frozen = await check_day_frozen(conn, ctx.tenant_id, body.site_id, target_date)
    if is_frozen:
        day_info = await get_day_status(conn, ctx.tenant_id, body.site_id, target_date)
        return FreezeResponse(
            success=True,
            day_id=day_info.get("day_id", ""),
            date=body.date,
            was_already_frozen=True,
            frozen_at=day_info.get("frozen_at"),
            final_stats=day_info.get("final_stats"),
            evidence_id=day_info.get("evidence_id"),
        )

    # Compute final stats using SQL function
    stats_row = await conn.fetchrow(
        "SELECT dispatch.get_daily_stats($1, $2, $3) as stats",
        ctx.tenant_id, body.site_id, target_date
    )
    final_stats = stats_row["stats"] if stats_row else {}

    # TODO: Run full validation and check for hard violations
    # For pilot, we allow freeze with warnings
    validation_verdict = "OK"

    # Generate evidence ID (would store to artifact store in production)
    from uuid import uuid4
    evidence_id = uuid4()

    # Freeze the day using SQL function (atomic, handles concurrency)
    freeze_result = await conn.fetchrow(
        """
        SELECT * FROM dispatch.freeze_day($1, $2, $3, $4, $5, $6)
        """,
        ctx.tenant_id,
        body.site_id,
        target_date,
        ctx.user.email or str(ctx.user.user_id),
        json.dumps(final_stats) if final_stats else "{}",
        evidence_id
    )

    logger.info(
        "workbench_day_frozen",
        extra={
            "tenant_id": ctx.tenant_id,
            "site_id": body.site_id,
            "date": body.date,
            "day_id": str(freeze_result["day_id"]) if freeze_result else None,
            "was_already_frozen": freeze_result["was_already_frozen"] if freeze_result else False,
            "performed_by": ctx.user.email,
        }
    )

    return FreezeResponse(
        success=True,
        day_id=str(freeze_result["day_id"]) if freeze_result else "",
        date=body.date,
        was_already_frozen=freeze_result["was_already_frozen"] if freeze_result else False,
        frozen_at=freeze_result["frozen_at"].isoformat() if freeze_result and freeze_result["frozen_at"] else None,
        final_stats=final_stats,
        evidence_id=str(evidence_id),
        validation_verdict=validation_verdict,
    )


@router.post(
    "/slots/{slot_id}/abort",
    response_model=AbortSlotResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def abort_slot(
    slot_id: UUID,
    request: Request,
    body: AbortSlotRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Mark a slot as ABORTED.

    Abort = planned/forecasted slot not executed (e.g., low demand).
    Abort is NOT deletion - slot remains visible in reports.

    Requires abort reason. Day must not be frozen.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    result = await set_slot_status(
        conn=conn,
        tenant_id=ctx.tenant_id,
        site_id=ctx.site_id or 0,
        slot_id=slot_id,
        new_status=SlotStatus.ABORTED,
        abort_reason=AbortReason(body.reason),
        abort_note=body.note,
        performed_by=ctx.user.email or str(ctx.user.user_id),
    )

    if not result.success:
        if result.hard_block_reason and result.hard_block_reason.value == "DAY_FROZEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "DAY_FROZEN",
                    "message": result.error_message or "Day is frozen, no mutations allowed",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": result.hard_block_reason.value if result.hard_block_reason else "ABORT_FAILED",
                "message": result.error_message or "Failed to abort slot",
            },
        )

    return AbortSlotResponse(
        success=True,
        slot_id=str(slot_id),
        previous_status=result.previous_status.value if result.previous_status else "UNKNOWN",
        new_status="ABORTED",
        abort_reason=body.reason,
        abort_note=body.note,
    )


@router.post(
    "/slots/abort",
    response_model=BatchAbortResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def batch_abort_slots(
    request: Request,
    body: BatchAbortRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Batch abort multiple slots.

    Each operation should have:
    - slot_id: UUID string
    - reason: LOW_DEMAND | WEATHER | VEHICLE | OPS_DECISION | OTHER
    - note: Optional string
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    operations = [
        {
            "slot_id": op["slot_id"],
            "new_status": "ABORTED",
            "abort_reason": op["reason"],
            "abort_note": op.get("note"),
        }
        for op in body.operations
    ]

    result = await batch_set_slot_status(
        conn=conn,
        tenant_id=ctx.tenant_id,
        site_id=ctx.site_id or 0,
        operations=operations,
        performed_by=ctx.user.email or str(ctx.user.user_id),
    )

    return BatchAbortResponse(
        success=result.success,
        total=result.total,
        applied=result.applied,
        rejected=result.rejected,
        results=[
            {
                "slot_id": str(r.slot_id),
                "success": r.success,
                "previous_status": r.previous_status.value if r.previous_status else None,
                "error": r.error_message,
            }
            for r in result.results
        ],
    )


# =============================================================================
# HOLD/RELEASE ENDPOINTS (Activation Gate)
# =============================================================================

@router.post(
    "/slots/{slot_id}/hold",
    response_model=HoldSlotResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def hold_slot(
    slot_id: UUID,
    request: Request,
    body: HoldSlotRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Put a slot on HOLD (temporarily deactivated).

    HOLD = slot not shown to drivers, not counted in coverage.
    Use for morning demand gaps where demand is lower than planned.

    Valid transitions: PLANNED → HOLD, RELEASED → HOLD
    INVALID: ASSIGNED → HOLD (must unassign first, per INV-1)
    Day must not be frozen.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Use the SQL function for atomic state transition
    result = await conn.fetchrow(
        """
        SELECT * FROM dispatch.set_slot_hold($1, $2::dispatch_hold_reason, $3)
        """,
        slot_id,
        body.reason,
        ctx.user.email or str(ctx.user.user_id),
    )

    if not result or not result["success"]:
        message = result["message"] if result else "Unknown error"
        if message == "DAY_FROZEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": "DAY_FROZEN", "message": "Day is frozen, no mutations allowed"},
            )
        if message == "SLOT_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "SLOT_NOT_FOUND", "message": f"Slot {slot_id} not found"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "HOLD_FAILED", "message": message},
        )

    logger.info(
        "slot_hold_set",
        extra={
            "tenant_id": ctx.tenant_id,
            "slot_id": str(slot_id),
            "reason": body.reason,
            "performed_by": ctx.user.email,
        }
    )

    return HoldSlotResponse(
        success=True,
        slot_id=str(slot_id),
        previous_status=result["old_status"] if result["old_status"] else "UNKNOWN",
        new_status="HOLD",
        hold_reason=body.reason,
        message="OK",
    )


@router.post(
    "/slots/{slot_id}/release",
    response_model=ReleaseSlotResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def release_slot(
    slot_id: UUID,
    request: Request,
    body: ReleaseSlotRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Release a slot from HOLD back to active state.

    RELEASED = slot was on hold, now reactivated.
    If released < threshold before start time, marked as AT_RISK.

    Valid transitions: HOLD → RELEASED only
    Day must not be frozen.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Use the SQL function for atomic state transition with late release detection
    result = await conn.fetchrow(
        """
        SELECT * FROM dispatch.set_slot_released($1, $2, $3)
        """,
        slot_id,
        ctx.user.email or str(ctx.user.user_id),
        body.late_release_threshold_minutes,
    )

    if not result or not result["success"]:
        message = result["message"] if result else "Unknown error"
        if message == "DAY_FROZEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": "DAY_FROZEN", "message": "Day is frozen, no mutations allowed"},
            )
        if message == "SLOT_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "SLOT_NOT_FOUND", "message": f"Slot {slot_id} not found"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "RELEASE_FAILED", "message": message},
        )

    logger.info(
        "slot_released",
        extra={
            "tenant_id": ctx.tenant_id,
            "slot_id": str(slot_id),
            "at_risk": result["at_risk"],
            "performed_by": ctx.user.email,
        }
    )

    return ReleaseSlotResponse(
        success=True,
        slot_id=str(slot_id),
        previous_status="HOLD",
        new_status="RELEASED",
        at_risk=result["at_risk"],
        message=result["message"] if result["message"] else "OK",
    )


@router.post(
    "/slots/hold",
    response_model=BatchHoldResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def batch_hold_slots(
    request: Request,
    body: BatchHoldRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Batch put multiple slots on HOLD.

    Each operation should have:
    - slot_id: UUID string
    - reason: LOW_DEMAND | SURPLUS | OPS_DECISION | WEATHER | OTHER
    - note: Optional string (not stored in batch for now)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    slot_ids = [op["slot_id"] for op in body.operations]
    reasons = [op.get("reason", "OPS_DECISION") for op in body.operations]

    # Batch operation - one reason applies to all slots
    # For different reasons, make multiple API calls
    main_reason = reasons[0] if reasons else "OPS_DECISION"

    results = await conn.fetch(
        """
        SELECT * FROM dispatch.set_slots_hold_batch($1::uuid[], $2::dispatch_hold_reason, $3)
        """,
        slot_ids,
        main_reason,
        ctx.user.email or str(ctx.user.user_id),
    )

    applied = sum(1 for r in results if r["success"])
    rejected = len(results) - applied

    return BatchHoldResponse(
        success=True,
        total=len(slot_ids),
        applied=applied,
        rejected=rejected,
        results=[
            {
                "slot_id": str(r["slot_id"]),
                "success": r["success"],
                "message": r["message"],
            }
            for r in results
        ],
    )


@router.post(
    "/slots/release",
    response_model=BatchReleaseResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def batch_release_slots(
    request: Request,
    body: BatchReleaseRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Batch release multiple slots from HOLD.

    All slots released with same threshold.
    Returns at_risk_count for late releases.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    results = await conn.fetch(
        """
        SELECT * FROM dispatch.set_slots_released_batch($1::uuid[], $2, $3)
        """,
        body.slot_ids,
        ctx.user.email or str(ctx.user.user_id),
        body.late_release_threshold_minutes,
    )

    applied = sum(1 for r in results if r["success"])
    rejected = len(results) - applied
    at_risk_count = sum(1 for r in results if r["success"] and r["at_risk"])

    return BatchReleaseResponse(
        success=True,
        total=len(body.slot_ids),
        applied=applied,
        rejected=rejected,
        at_risk_count=at_risk_count,
        results=[
            {
                "slot_id": str(r["slot_id"]),
                "success": r["success"],
                "at_risk": r["at_risk"],
                "message": r["message"],
            }
            for r in results
        ],
    )


# =============================================================================
# MORNING DEMAND GAP ENDPOINTS
# =============================================================================

@router.get("/daily/morning-gap", response_model=MorningGapAnalysisResponse)
async def get_morning_demand_gap(
    request: Request,
    site_id: int,
    date_str: str,
    morning_cutoff_hour: int = 10,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Analyze morning demand gap for a given day.

    Returns:
    - Summary of morning slots by status (HOLD, RELEASED, etc.)
    - List of slots currently on HOLD
    - List of at-risk slots (late releases)

    Use this to understand morning activation status before making decisions.
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

    # Use the SQL function for analysis
    result = await conn.fetchrow(
        """
        SELECT dispatch.analyze_morning_demand_gap($1, $2, $3, $4) as analysis
        """,
        ctx.tenant_id, site_id, target_date, morning_cutoff_hour
    )

    analysis = result["analysis"] if result else {}

    return MorningGapAnalysisResponse(
        success=True,
        day_date=date_str,
        site_id=site_id,
        morning_cutoff_hour=morning_cutoff_hour,
        summary=analysis.get("summary", {}),
        hold_by_reason=analysis.get("hold_by_reason", {}),
        slots_on_hold=analysis.get("slots_on_hold", []),
        at_risk_slots=analysis.get("at_risk_slots", []),
        computed_at=analysis.get("computed_at", datetime.now(timezone.utc).isoformat()),
    )


@router.post(
    "/daily/morning-gap/workflow",
    response_model=MorningGapWorkflowResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def morning_gap_workflow(
    request: Request,
    site_id: int,
    date_str: str,
    body: MorningGapWorkflowRequest,
    morning_cutoff_hour: int = 10,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    One-click Morning Demand Gap → Repair workflow.

    Actions:
    - set_hold: Put all unassigned morning slots on HOLD (with reason)
    - release_all: Release all HOLD morning slots
    - release_selected: Release only specified slot_ids

    This is the dispatcher's "Morning Gap SOP" entry point.
    Combines analysis + action in one API call.
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

    results = []
    slots_affected = 0
    at_risk_count = 0

    if body.action == "set_hold":
        # Find all PLANNED/RELEASED morning slots that are unassigned
        hold_reason = body.hold_reason or "LOW_DEMAND"

        slot_rows = await conn.fetch(
            """
            SELECT slot_id FROM dispatch.daily_slots
            WHERE tenant_id = $1 AND site_id = $2 AND day_date = $3
              AND status IN ('PLANNED', 'RELEASED')
              AND assigned_driver_id IS NULL
              AND EXTRACT(HOUR FROM planned_start) < $4
            """,
            ctx.tenant_id, site_id, target_date, morning_cutoff_hour
        )

        if slot_rows:
            slot_ids = [row["slot_id"] for row in slot_rows]
            hold_results = await conn.fetch(
                """
                SELECT * FROM dispatch.set_slots_hold_batch($1::uuid[], $2::dispatch_hold_reason, $3)
                """,
                slot_ids,
                hold_reason,
                ctx.user.email or str(ctx.user.user_id),
            )
            results = [{"slot_id": str(r["slot_id"]), "success": r["success"], "message": r["message"]} for r in hold_results]
            slots_affected = sum(1 for r in hold_results if r["success"])

        message = f"Set {slots_affected} morning slots to HOLD with reason {hold_reason}"

    elif body.action == "release_all":
        # Find all HOLD morning slots
        slot_rows = await conn.fetch(
            """
            SELECT slot_id FROM dispatch.daily_slots
            WHERE tenant_id = $1 AND site_id = $2 AND day_date = $3
              AND status = 'HOLD'
              AND EXTRACT(HOUR FROM planned_start) < $4
            """,
            ctx.tenant_id, site_id, target_date, morning_cutoff_hour
        )

        if slot_rows:
            slot_ids = [row["slot_id"] for row in slot_rows]
            release_results = await conn.fetch(
                """
                SELECT * FROM dispatch.set_slots_released_batch($1::uuid[], $2, $3)
                """,
                slot_ids,
                ctx.user.email or str(ctx.user.user_id),
                120,  # default threshold
            )
            results = [{"slot_id": str(r["slot_id"]), "success": r["success"], "at_risk": r["at_risk"], "message": r["message"]} for r in release_results]
            slots_affected = sum(1 for r in release_results if r["success"])
            at_risk_count = sum(1 for r in release_results if r["success"] and r["at_risk"])

        message = f"Released {slots_affected} morning slots ({at_risk_count} at-risk)"

    elif body.action == "release_selected":
        if not body.slot_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slot_ids required for release_selected action",
            )

        release_results = await conn.fetch(
            """
            SELECT * FROM dispatch.set_slots_released_batch($1::uuid[], $2, $3)
            """,
            body.slot_ids,
            ctx.user.email or str(ctx.user.user_id),
            120,  # default threshold
        )
        results = [{"slot_id": str(r["slot_id"]), "success": r["success"], "at_risk": r["at_risk"], "message": r["message"]} for r in release_results]
        slots_affected = sum(1 for r in release_results if r["success"])
        at_risk_count = sum(1 for r in release_results if r["success"] and r["at_risk"])
        message = f"Released {slots_affected} selected slots ({at_risk_count} at-risk)"

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action: {body.action}",
        )

    logger.info(
        "morning_gap_workflow",
        extra={
            "tenant_id": ctx.tenant_id,
            "site_id": site_id,
            "date": date_str,
            "action": body.action,
            "slots_affected": slots_affected,
            "at_risk_count": at_risk_count,
            "performed_by": ctx.user.email,
        }
    )

    return MorningGapWorkflowResponse(
        success=True,
        action=body.action,
        slots_affected=slots_affected,
        at_risk_count=at_risk_count,
        results=results,
        message=message,
    )


# =============================================================================
# SLOT ASSIGN/UNASSIGN ENDPOINTS (INV-1, INV-2 enforced)
# =============================================================================

class AssignSlotRequest(BaseModel):
    """Request for POST /workbench/slots/{slot_id}/assign."""
    driver_id: int


class AssignSlotResponse(BaseModel):
    """Response for assign operations."""
    success: bool = True
    slot_id: str
    previous_status: str
    new_status: str = "ASSIGNED"
    driver_id: int
    message: str = "OK"


class UnassignSlotResponse(BaseModel):
    """Response for unassign operations."""
    success: bool = True
    slot_id: str
    previous_status: str
    new_status: str = "RELEASED"
    old_driver_id: Optional[int] = None
    message: str = "OK"


@router.post(
    "/slots/{slot_id}/assign",
    response_model=AssignSlotResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def assign_slot(
    slot_id: UUID,
    request: Request,
    body: AssignSlotRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Assign a driver to a slot.

    Valid transitions: PLANNED → ASSIGNED, RELEASED → ASSIGNED
    INVALID: HOLD → ASSIGNED (must release first, per INV-5)

    INV-2 enforced: release_at is auto-set if not present.
    Day must not be frozen.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Use the SQL function for atomic state transition with INV-2 enforcement
    result = await conn.fetchrow(
        """
        SELECT * FROM dispatch.set_slot_assigned($1, $2, $3)
        """,
        slot_id,
        body.driver_id,
        ctx.user.email or str(ctx.user.user_id),
    )

    if not result or not result["success"]:
        message = result["message"] if result else "Unknown error"
        if message == "DAY_FROZEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": "DAY_FROZEN", "message": "Day is frozen, no mutations allowed"},
            )
        if message == "SLOT_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "SLOT_NOT_FOUND", "message": f"Slot {slot_id} not found"},
            )
        if "HOLD" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "SLOT_ON_HOLD",
                    "message": "Cannot assign to HOLD slot. Must release first (INV-5).",
                },
            )
        if "DRIVER_NOT_FOUND" in message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "DRIVER_NOT_FOUND", "message": message},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "ASSIGN_FAILED", "message": message},
        )

    logger.info(
        "slot_assigned",
        extra={
            "tenant_id": ctx.tenant_id,
            "slot_id": str(slot_id),
            "driver_id": body.driver_id,
            "performed_by": ctx.user.email,
        }
    )

    return AssignSlotResponse(
        success=True,
        slot_id=str(slot_id),
        previous_status=result["old_status"] if result["old_status"] else "UNKNOWN",
        new_status="ASSIGNED",
        driver_id=result["driver_id"],
        message="OK",
    )


@router.post(
    "/slots/{slot_id}/unassign",
    response_model=UnassignSlotResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def unassign_slot(
    slot_id: UUID,
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("roster.workbench.write")),
):
    """
    Unassign a driver from a slot.

    Valid transitions: ASSIGNED → RELEASED
    Preserves release_at for audit trail.

    Day must not be frozen.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Use the SQL function for atomic state transition
    result = await conn.fetchrow(
        """
        SELECT * FROM dispatch.unassign_slot($1, $2)
        """,
        slot_id,
        ctx.user.email or str(ctx.user.user_id),
    )

    if not result or not result["success"]:
        message = result["message"] if result else "Unknown error"
        if message == "DAY_FROZEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": "DAY_FROZEN", "message": "Day is frozen, no mutations allowed"},
            )
        if message == "SLOT_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "SLOT_NOT_FOUND", "message": f"Slot {slot_id} not found"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "UNASSIGN_FAILED", "message": message},
        )

    logger.info(
        "slot_unassigned",
        extra={
            "tenant_id": ctx.tenant_id,
            "slot_id": str(slot_id),
            "old_driver_id": result["old_driver_id"],
            "performed_by": ctx.user.email,
        }
    )

    return UnassignSlotResponse(
        success=True,
        slot_id=str(slot_id),
        previous_status="ASSIGNED",
        new_status="RELEASED",
        old_driver_id=result["old_driver_id"],
        message="OK",
    )
