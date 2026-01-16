"""
SOLVEREIGN V4.9 - Master Orchestrator API

REST API for event ingestion and orchestrator management.

Routes:
- POST /api/v1/roster/ops/events       - Ingest a new event
- GET /api/v1/roster/ops/events        - List events (with filters)
- POST /api/v1/roster/ops/process      - Trigger queue processing
- GET /api/v1/roster/ops/policies      - List workflow policies
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Literal
from uuid import UUID

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    TenantContext,
    require_tenant_context_with_permission,
    require_csrf_check,
)
from packs.roster.core.master_orchestrator import (
    ingest_event,
    process_queue_batch,
    EventType,
    RiskTier,
    EventStatus,
    ActionType,
)
from packs.roster.core.simulation_engine import (
    ScenarioSpec,
    ScenarioType,
    create_simulation_run,
    run_simulation,
    get_simulation_run,
    list_simulation_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/roster/ops",
    tags=["roster-ops-orchestrator"]
)


# =============================================================================
# SCHEMAS
# =============================================================================

class IngestEventRequest(BaseModel):
    """Request to ingest a new event."""
    event_type: str = Field(..., description="Event type (e.g., DRIVER_SICK_CALL)")
    payload: dict = Field(default_factory=dict, description="Event payload")
    idempotency_key: Optional[str] = Field(None, description="Optional idempotency key")


class IngestEventResponse(BaseModel):
    """Response after ingesting an event."""
    success: bool = True
    event_id: str
    event_type: str
    risk_tier: str
    status: str


class EventListItem(BaseModel):
    """An event in the list."""
    event_id: str
    event_type: str
    risk_tier: str
    status: str
    created_at: str
    processed_at: Optional[str] = None
    error_message: Optional[str] = None


class EventListResponse(BaseModel):
    """Response for listing events."""
    success: bool = True
    events: List[EventListItem]
    total: int


class ProcessQueueRequest(BaseModel):
    """Request to trigger queue processing."""
    risk_tier: Optional[str] = Field(None, description="Filter by risk tier")
    batch_size: int = Field(10, ge=1, le=100, description="Number of events to process")


class ProcessResultItem(BaseModel):
    """Result of processing a single event."""
    event_id: str
    success: bool
    action_taken: str
    repair_session_id: Optional[str] = None
    error: Optional[str] = None


class ProcessQueueResponse(BaseModel):
    """Response after processing queue."""
    success: bool = True
    processed: int
    results: List[ProcessResultItem]


class PolicyItem(BaseModel):
    """A workflow policy."""
    policy_id: int
    policy_name: str
    event_type: str
    action: str
    priority: int
    is_active: bool


class PolicyListResponse(BaseModel):
    """Response for listing policies."""
    success: bool = True
    policies: List[PolicyItem]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/events",
    response_model=IngestEventResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def api_ingest_event(
    request: Request,
    body: IngestEventRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
):
    """
    Ingest a new event into the operations queue.

    The event will be classified by risk tier and processed according to policies.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Validate event type
    try:
        event_type = EventType(body.event_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event type: {body.event_type}. Valid types: {[e.value for e in EventType]}",
        )

    # Ingest event
    event = await ingest_event(
        conn=conn,
        event_type=event_type,
        tenant_id=ctx.tenant_id,
        site_id=ctx.site_id or 0,
        payload=body.payload,
        idempotency_key=body.idempotency_key,
    )

    return IngestEventResponse(
        success=True,
        event_id=str(event.event_id),
        event_type=event.event_type.value,
        risk_tier=event.risk_tier.value,
        status=event.status.value,
    )


@router.get("/events", response_model=EventListResponse)
async def list_events(
    request: Request,
    status_filter: Optional[str] = None,
    risk_tier: Optional[str] = None,
    limit: int = 50,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    List events in the operations queue.

    Filters:
    - status: PENDING, PROCESSING, COMPLETED, FAILED
    - risk_tier: HOT, WARM, COLD
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Build query
    query = """
        SELECT
            event_id, event_type, risk_tier, status,
            created_at, processed_at, error_message
        FROM ops.event_queue
        WHERE tenant_id = $1
    """
    params = [ctx.tenant_id]

    if status_filter:
        params.append(status_filter)
        query += f" AND status = ${len(params)}"

    if risk_tier:
        params.append(risk_tier)
        query += f" AND risk_tier = ${len(params)}"

    query += f" ORDER BY created_at DESC LIMIT ${len(params) + 1}"
    params.append(limit)

    rows = await conn.fetch(query, *params)

    events = [
        EventListItem(
            event_id=str(row["event_id"]),
            event_type=row["event_type"],
            risk_tier=row["risk_tier"],
            status=row["status"],
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
            processed_at=row["processed_at"].isoformat() if row["processed_at"] else None,
            error_message=row["error_message"],
        )
        for row in rows
    ]

    return EventListResponse(
        success=True,
        events=events,
        total=len(events),
    )


@router.post(
    "/process",
    response_model=ProcessQueueResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def process_queue(
    request: Request,
    body: ProcessQueueRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
):
    """
    Trigger processing of events in the queue.

    Events are processed in priority order (HOT > WARM > COLD).
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Parse risk tier filter
    risk_tier_enum = None
    if body.risk_tier:
        try:
            risk_tier_enum = RiskTier(body.risk_tier)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid risk tier: {body.risk_tier}",
            )

    # Process batch
    results = await process_queue_batch(
        conn=conn,
        tenant_id=ctx.tenant_id,
        risk_tier=risk_tier_enum,
        batch_size=body.batch_size,
    )

    return ProcessQueueResponse(
        success=True,
        processed=len(results),
        results=[
            ProcessResultItem(
                event_id=str(r.event_id),
                success=r.success,
                action_taken=r.action_taken.value,
                repair_session_id=str(r.repair_session_id) if r.repair_session_id else None,
                error=r.error,
            )
            for r in results
        ],
    )


@router.get("/policies", response_model=PolicyListResponse)
async def list_policies(
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    List workflow policies for this tenant.

    Returns both tenant-specific and default (tenant=NULL) policies.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    rows = await conn.fetch("""
        SELECT
            policy_id, policy_name, event_type, action,
            priority, is_active
        FROM ops.workflow_policies
        WHERE tenant_id IS NULL OR tenant_id = $1
        ORDER BY priority DESC, policy_name
    """, ctx.tenant_id)

    policies = [
        PolicyItem(
            policy_id=row["policy_id"],
            policy_name=row["policy_name"],
            event_type=row["event_type"],
            action=row["action"],
            priority=row["priority"],
            is_active=row["is_active"],
        )
        for row in rows
    ]

    return PolicyListResponse(
        success=True,
        policies=policies,
    )


# =============================================================================
# SIMULATION ENDPOINTS
# =============================================================================

class SimulationScenarioRequest(BaseModel):
    """Request to run a simulation."""
    scenario_type: str = Field(..., description="Type: DRIVER_ABSENCE, DEMAND_CHANGE, etc.")
    site_id: int
    date_start: str  # YYYY-MM-DD
    date_end: str    # YYYY-MM-DD
    remove_driver_ids: List[int] = Field(default_factory=list)
    demand_multiplier: float = Field(1.0, ge=0.1, le=5.0)
    description: str = ""


class SimulationKPIDelta(BaseModel):
    """KPI delta in simulation results."""
    metric: str
    baseline: float
    simulated: float
    delta: float
    delta_percent: Optional[float] = None
    direction: str


class SimulationResponse(BaseModel):
    """Response for simulation run."""
    success: bool = True
    run_id: str
    status: str
    risk_tier: str
    risk_factors: List[str] = []
    kpi_deltas: List[SimulationKPIDelta] = []
    proposed_mutations_count: int = 0
    evidence_id: Optional[str] = None
    error_message: Optional[str] = None


class SimulationListItem(BaseModel):
    """Item in simulation list."""
    run_id: str
    site_id: int
    status: str
    scenario_type: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    date_start: str
    date_end: str


class SimulationListResponse(BaseModel):
    """Response for listing simulations."""
    success: bool = True
    simulations: List[SimulationListItem]
    total: int


@router.post(
    "/simulate",
    response_model=SimulationResponse,
    dependencies=[Depends(require_csrf_check)],
)
async def run_simulation_api(
    request: Request,
    body: SimulationScenarioRequest,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.approve.write")),
):
    """
    Run a what-if simulation.

    CRITICAL: Simulations have ZERO side-effects on production data.
    All changes are computed in-memory and stored as evidence only.

    Scenario types:
    - DRIVER_ABSENCE: Remove drivers from pool
    - DEMAND_CHANGE: Multiply demand by factor
    - POLICY_TOGGLE: Change validation rules
    - COMPOSITE: Multiple changes
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Parse dates
    from datetime import date as date_type
    try:
        date_start = date_type.fromisoformat(body.date_start)
        date_end = date_type.fromisoformat(body.date_end)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {e}",
        )

    if date_end < date_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_end must be >= date_start",
        )

    # Parse scenario type
    try:
        scenario_type = ScenarioType(body.scenario_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scenario type: {body.scenario_type}. Valid: {[t.value for t in ScenarioType]}",
        )

    # Build scenario spec
    spec = ScenarioSpec(
        scenario_type=scenario_type,
        date_start=date_start,
        date_end=date_end,
        remove_driver_ids=body.remove_driver_ids,
        demand_multiplier=body.demand_multiplier,
        description=body.description,
        no_commit=True,  # Always enforced
    )

    # Create run record
    run_id = await create_simulation_run(
        conn=conn,
        tenant_id=ctx.tenant_id,
        site_id=body.site_id,
        scenario_spec=spec,
        created_by=ctx.user.email or str(ctx.user.user_id),
    )

    # Execute simulation
    output = await run_simulation(
        conn=conn,
        tenant_id=ctx.tenant_id,
        site_id=body.site_id,
        run_id=run_id,
        scenario_spec=spec,
    )

    return SimulationResponse(
        success=output.status.value == "DONE",
        run_id=str(output.run_id),
        status=output.status.value,
        risk_tier=output.risk_tier,
        risk_factors=output.risk_factors,
        kpi_deltas=[
            SimulationKPIDelta(
                metric=kpi.metric,
                baseline=kpi.baseline_value,
                simulated=kpi.simulated_value,
                delta=kpi.delta,
                delta_percent=kpi.delta_percent,
                direction=kpi.direction,
            )
            for kpi in output.kpi_deltas
        ],
        proposed_mutations_count=len(output.proposed_mutations),
        evidence_id=str(output.output_evidence_id) if output.output_evidence_id else None,
        error_message=output.error_message,
    )


@router.get("/simulate/{run_id}", response_model=SimulationResponse)
async def get_simulation_api(
    run_id: UUID,
    request: Request,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    Get simulation run by ID.

    Returns the full simulation results including KPI deltas and risk assessment.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    run = await get_simulation_run(conn, ctx.tenant_id, run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation run {run_id} not found",
        )

    summary = run.get("output_summary", {}) or {}

    return SimulationResponse(
        success=run["status"] == "DONE",
        run_id=run["run_id"],
        status=run["status"],
        risk_tier=summary.get("risk_tier", "UNKNOWN"),
        risk_factors=summary.get("risk_factors", []),
        kpi_deltas=[
            SimulationKPIDelta(
                metric=kpi["metric"],
                baseline=kpi["baseline"],
                simulated=kpi["simulated"],
                delta=kpi["delta"],
                delta_percent=kpi.get("delta_percent"),
                direction=kpi["direction"],
            )
            for kpi in summary.get("kpi_deltas", [])
        ],
        proposed_mutations_count=summary.get("proposed_mutations_count", 0),
        evidence_id=run.get("evidence_id"),
        error_message=run.get("error_message"),
    )


@router.get("/simulations", response_model=SimulationListResponse)
async def list_simulations_api(
    request: Request,
    site_id: Optional[int] = None,
    limit: int = 20,
    ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read")),
):
    """
    List simulation runs for the tenant.

    Optionally filter by site_id.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    runs = await list_simulation_runs(
        conn=conn,
        tenant_id=ctx.tenant_id,
        site_id=site_id,
        limit=limit,
    )

    return SimulationListResponse(
        success=True,
        simulations=[
            SimulationListItem(
                run_id=r["run_id"],
                site_id=r["site_id"],
                status=r["status"],
                scenario_type=r.get("scenario_type"),
                created_at=r["created_at"] or "",
                completed_at=r.get("completed_at"),
                date_start=r["date_start"],
                date_end=r["date_end"],
            )
            for r in runs
        ],
        total=len(runs),
    )
