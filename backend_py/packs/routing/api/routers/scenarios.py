# =============================================================================
# SOLVEREIGN Routing Pack - Scenarios Router
# =============================================================================
# API endpoints for routing scenarios.
# =============================================================================

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from pydantic import BaseModel, Field

from ..schemas import (
    CreateScenarioRequest,
    ScenarioResponse,
    SolveRequest,
    SolveResponse,
    JobStatusResponse,
)
from ...services.scenario_snapshot import (
    AsyncScenarioSnapshotService,
    NoTeamsFoundError,
    TenantMismatchError,
    SiteMismatchError,
    DriverNotAvailableError,
    SnapshotError,
)

router = APIRouter(prefix="/routing", tags=["routing-scenarios"])


# =============================================================================
# DEPENDENCY STUBS (to be implemented with actual auth/db)
# =============================================================================

async def get_current_tenant():
    """Get current tenant from auth context."""
    # TODO: Implement with actual auth
    return {"id": 1, "name": "LTS"}


async def get_db_connection():
    """Get database connection."""
    # TODO: Implement with actual database pool
    return None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/scenarios",
    response_model=ScenarioResponse,
    status_code=201,
    summary="Create a new routing scenario",
    description="Import and validate a routing scenario with stops, vehicles, and depots."
)
async def create_scenario(
    request: CreateScenarioRequest,
    x_idempotency_key: Optional[str] = Header(None),
    tenant: dict = Depends(get_current_tenant),
    db = Depends(get_db_connection)
):
    """
    Create a new routing scenario.

    Steps:
    1. Validate input (time windows, depot references, skills)
    2. Compute input_hash for deduplication
    3. Create scenario and related entities
    4. Return scenario_id for tracking

    Returns 409 if scenario with same input_hash already exists.
    """
    # 1. Compute input hash for deduplication
    canonical_input = _compute_canonical_input(request)
    input_hash = hashlib.sha256(canonical_input.encode()).hexdigest()

    # 2. Check for duplicate (would be DB lookup in real impl)
    # TODO: Check if scenario with input_hash exists

    # 3. Validate depot references in vehicles
    depot_ids = {d.site_id for d in request.depots}
    for v in request.vehicles:
        if v.start_depot_id not in depot_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Vehicle references unknown start_depot_id: {v.start_depot_id}"
            )
        if v.end_depot_id not in depot_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Vehicle references unknown end_depot_id: {v.end_depot_id}"
            )

    # 4. Create scenario (placeholder - would be DB insert)
    scenario_id = UUID("00000000-0000-0000-0000-000000000001")  # Placeholder

    return ScenarioResponse(
        scenario_id=scenario_id,
        vertical=request.vertical,
        plan_date=request.plan_date,
        status="INGESTED",
        stops_count=len(request.stops),
        vehicles_count=len(request.vehicles),
        depots_count=len(request.depots),
        input_hash=input_hash[:16],
        created_at=datetime.now()
    )


@router.post(
    "/scenarios/{scenario_id}/solve",
    response_model=SolveResponse,
    summary="Start async solve job",
    description="Enqueue the scenario for async solving. Poll job status for result."
)
async def solve_scenario(
    scenario_id: UUID,
    request: SolveRequest,
    tenant: dict = Depends(get_current_tenant),
    db = Depends(get_db_connection)
):
    """
    Start async solve job for a scenario.

    Steps:
    1. Verify scenario exists and belongs to tenant
    2. Check for existing solve with same config (idempotency)
    3. Enqueue Celery job
    4. Return job_id for status polling

    Returns 404 if scenario not found.
    Returns 409 if solve with same config already exists.
    """
    # TODO: Verify scenario exists in DB

    # TODO: Check for idempotency (same scenario + config = same plan)
    config_hash = request.solver_config.seed or "default"

    # TODO: Enqueue Celery job
    # job = solve_routing_scenario.delay(str(scenario_id), request.solver_config.dict())
    job_id = f"job_{scenario_id}_{datetime.now().timestamp()}"

    return SolveResponse(
        job_id=job_id,
        status="QUEUED",
        poll_url=f"/api/v1/routing/jobs/{job_id}"
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Poll job status to check if solving is complete."
)
async def get_job_status(
    job_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get status of an async solve job.

    Returns job status:
    - QUEUED: Job waiting in queue
    - SOLVING: Job is running
    - SUCCESS: Job completed, result available
    - FAILED: Job failed, error message available

    When status is SUCCESS, result contains plan_id.
    """
    # TODO: Get job status from Celery
    # result = AsyncResult(job_id)

    # Placeholder response
    return JobStatusResponse(
        job_id=job_id,
        status="QUEUED",
        result=None,
        error=None
    )


@router.get(
    "/scenarios/{scenario_id}",
    summary="Get scenario details",
    description="Get details of a routing scenario including metadata."
)
async def get_scenario(
    scenario_id: UUID,
    tenant: dict = Depends(get_current_tenant),
    db = Depends(get_db_connection)
):
    """
    Get scenario details.

    Returns scenario metadata, counts, and available plans.
    """
    # TODO: Fetch scenario from DB
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get(
    "/scenarios",
    summary="List scenarios",
    description="List routing scenarios with optional filtering."
)
async def list_scenarios(
    plan_date: Optional[str] = Query(None, description="Filter by plan date (YYYY-MM-DD)"),
    vertical: Optional[str] = Query(None, description="Filter by vertical"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant: dict = Depends(get_current_tenant),
    db = Depends(get_db_connection)
):
    """
    List scenarios for the current tenant.

    Supports filtering by plan_date and vertical.
    """
    # TODO: Fetch scenarios from DB
    return {
        "scenarios": [],
        "total": 0,
        "limit": limit,
        "offset": offset
    }


# =============================================================================
# SNAPSHOT ENDPOINT (P0 FIX: Returns 409/422 on no teams)
# =============================================================================

class SnapshotTeamsRequest(BaseModel):
    """Request to snapshot teams_daily into routing_vehicles."""
    site_id: str = Field(..., description="Site UUID")
    plan_date: date = Field(..., description="Plan date")
    validate_availability: bool = Field(default=True, description="Validate driver availability")


class SnapshotTeamsResponse(BaseModel):
    """Response from snapshot operation."""
    scenario_id: str
    vehicles_created: int
    teams_snapshotted: list[str]
    snapshot_hash: str
    warnings: list[str]


@router.post(
    "/scenarios/{scenario_id}/snapshot-teams",
    response_model=SnapshotTeamsResponse,
    status_code=201,
    summary="Snapshot teams_daily to routing_vehicles",
    description="Copy teams from teams_daily to routing_vehicles for a scenario. This creates an immutable snapshot."
)
async def snapshot_teams_to_scenario(
    scenario_id: UUID,
    request: SnapshotTeamsRequest,
    tenant: dict = Depends(get_current_tenant),
    db = Depends(get_db_connection)
):
    """
    Snapshot teams_daily into routing_vehicles for a scenario.

    This operation:
    1. Validates scenario matches tenant/site/date
    2. Loads active teams from teams_daily
    3. Validates driver availability (if enabled)
    4. Creates routing_vehicles (immutable snapshot)
    5. Records team_history for V2 stability

    Returns:
    - 201: Snapshot created successfully
    - 404: Scenario not found
    - 409: Scenario already has vehicles (conflict)
    - 422: No teams found or validation failed

    Raises HTTPException with structured error for:
    - NoTeamsFoundError → 422 UNPROCESSABLE_ENTITY
    - TenantMismatchError → 403 FORBIDDEN
    - SiteMismatchError → 422 UNPROCESSABLE_ENTITY
    - DriverNotAvailableError → 422 UNPROCESSABLE_ENTITY
    """
    try:
        # Initialize snapshot service
        snapshot_service = AsyncScenarioSnapshotService(db)

        # Perform snapshot
        result = await snapshot_service.snapshot_teams_to_vehicles(
            tenant_id=tenant['id'],
            site_id=request.site_id,
            plan_date=request.plan_date,
            scenario_id=str(scenario_id),
            validate_availability=request.validate_availability,
        )

        return SnapshotTeamsResponse(
            scenario_id=result.scenario_id,
            vehicles_created=result.vehicles_created,
            teams_snapshotted=result.teams_snapshotted,
            snapshot_hash=result.snapshot_hash,
            warnings=result.warnings,
        )

    except NoTeamsFoundError as e:
        # P0 FIX: Return 422 when no teams exist
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "NO_TEAMS_FOUND",
                "message": str(e),
                "hint": "Import teams via POST /teams_daily/import before creating scenario snapshot"
            }
        )

    except TenantMismatchError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "TENANT_MISMATCH",
                "message": str(e)
            }
        )

    except SiteMismatchError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "SITE_MISMATCH",
                "message": str(e)
            }
        )

    except DriverNotAvailableError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "DRIVER_NOT_AVAILABLE",
                "message": str(e),
                "hint": "Check driver availability records for the plan date"
            }
        )

    except SnapshotError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "SNAPSHOT_ERROR",
                "message": str(e)
            }
        )


# =============================================================================
# HELPERS
# =============================================================================

def _compute_canonical_input(request: CreateScenarioRequest) -> str:
    """
    Compute canonical string representation of input for hashing.

    Ensures same input produces same hash regardless of field order.
    """
    # Sort stops by order_id
    stops_data = sorted(
        [
            {
                "order_id": s.order_id,
                "service_code": s.service_code,
                "tw_start": s.tw_start.isoformat(),
                "tw_end": s.tw_end.isoformat(),
                "lat": s.lat,
                "lng": s.lng,
            }
            for s in request.stops
        ],
        key=lambda x: x["order_id"]
    )

    # Sort vehicles by external_id or shift_start
    vehicles_data = sorted(
        [
            {
                "external_id": v.external_id,
                "team_size": v.team_size,
                "shift_start_at": v.shift_start_at.isoformat(),
                "shift_end_at": v.shift_end_at.isoformat(),
                "start_depot_id": v.start_depot_id,
            }
            for v in request.vehicles
        ],
        key=lambda x: x["external_id"] or x["shift_start_at"]
    )

    # Sort depots by site_id
    depots_data = sorted(
        [
            {
                "site_id": d.site_id,
                "lat": d.lat,
                "lng": d.lng,
            }
            for d in request.depots
        ],
        key=lambda x: x["site_id"]
    )

    canonical = {
        "vertical": request.vertical.value,
        "plan_date": request.plan_date.isoformat(),
        "stops": stops_data,
        "vehicles": vehicles_data,
        "depots": depots_data,
    }

    return json.dumps(canonical, sort_keys=True)
