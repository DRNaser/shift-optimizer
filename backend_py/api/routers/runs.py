"""
SOLVEREIGN V3.3b API - Runs Router
===================================

Async optimization run management with SSE streaming.
Migrated from legacy routes_v2.py for Enterprise API.

Endpoints:
- POST /runs          Create new optimization run
- GET /runs/{id}      Get run status
- GET /runs/{id}/stream  SSE stream for progress
- GET /runs/{id}/schedule  Get final schedule
"""

import json
import asyncio
import time
from datetime import date, datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_current_tenant, TenantContext
from ..database import DatabaseManager


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class TourInput(BaseModel):
    """Tour input for optimization."""
    id: str
    day: int = Field(..., ge=1, le=7, description="1=Mo, 7=Su")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    location: Optional[str] = None
    required_qualifications: List[str] = Field(default_factory=list)


class DriverInput(BaseModel):
    """Driver input for optimization."""
    id: str
    name: str
    qualifications: List[str] = Field(default_factory=list)
    available_days: List[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    max_weekly_hours: float = 55.0
    max_daily_span_hours: float = 15.5
    max_tours_per_day: int = 3
    min_rest_hours: float = 11.0


class ConfigOverrides(BaseModel):
    """Configuration overrides for solver."""
    max_weekly_hours: Optional[float] = None
    max_daily_span_hours: Optional[float] = None
    max_tours_per_day: Optional[int] = None
    min_rest_hours: Optional[float] = None
    seed: Optional[int] = None
    time_limit_seconds: Optional[int] = None


class RunCreateRequest(BaseModel):
    """Request to create a new optimization run."""
    tours: List[TourInput]
    drivers: Optional[List[DriverInput]] = None
    config_overrides: Optional[ConfigOverrides] = None
    plan_date: Optional[str] = None  # YYYY-MM-DD


class RunCreateResponse(BaseModel):
    """Response after creating a run."""
    run_id: str
    status: str
    links: Dict[str, str]


class RunStatusResponse(BaseModel):
    """Current status of a run."""
    run_id: str
    status: str
    progress: float = 0.0
    message: Optional[str] = None
    created_at: str
    updated_at: str
    execution_time_ms: Optional[int] = None


class TourOutput(BaseModel):
    """Tour in schedule output."""
    id: str
    day: int
    start_time: str
    end_time: str
    duration_hours: float
    location: Optional[str] = None
    required_qualifications: List[str] = []


class BlockOutput(BaseModel):
    """Block of tours for a driver."""
    tours: List[TourOutput]
    total_hours: float
    span_hours: float


class AssignmentOutput(BaseModel):
    """Driver assignment in schedule."""
    driver_id: str
    driver_name: str
    day: int
    blocks: List[BlockOutput]
    daily_hours: float
    daily_span: float


class UnassignedTourOutput(BaseModel):
    """Unassigned tour with reason."""
    tour: TourOutput
    reason: str


class StatsOutput(BaseModel):
    """Schedule statistics."""
    total_drivers: int
    total_tours: int
    assigned_tours: int
    unassigned_tours: int
    coverage: float
    avg_hours_per_driver: float
    max_hours_driver: float


class ScheduleResponse(BaseModel):
    """Final schedule response."""
    run_id: str
    status: str
    assignments: List[AssignmentOutput]
    unassigned: List[UnassignedTourOutput]
    stats: StatsOutput
    execution_time_ms: int


# =============================================================================
# IN-MEMORY RUN STORE (for demo - production uses DB)
# =============================================================================

class RunStore:
    """In-memory run storage. Production should use PostgreSQL."""

    def __init__(self):
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create(self, run_id: str, tenant_id: int, request: RunCreateRequest) -> Dict:
        async with self._lock:
            run = {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "status": "PENDING",
                "progress": 0.0,
                "message": "Run created",
                "request": request.model_dump(),
                "result": None,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "execution_time_ms": None,
            }
            self._runs[run_id] = run
            return run

    async def get(self, run_id: str, tenant_id: int) -> Optional[Dict]:
        run = self._runs.get(run_id)
        if run and run["tenant_id"] == tenant_id:
            return run
        return None

    async def update(self, run_id: str, **updates) -> Optional[Dict]:
        async with self._lock:
            if run_id in self._runs:
                self._runs[run_id].update(updates)
                self._runs[run_id]["updated_at"] = datetime.utcnow().isoformat()
                return self._runs[run_id]
        return None

    async def list_for_tenant(self, tenant_id: int) -> List[Dict]:
        return [r for r in self._runs.values() if r["tenant_id"] == tenant_id]


# Global run store
run_store = RunStore()

# Heartbeat interval for SSE
HEARTBEAT_INTERVAL_SEC = 15


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("", response_model=RunCreateResponse)
async def create_run(
    request: RunCreateRequest,
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Create a new optimization run.

    Returns immediately with run_id. Use /runs/{id}/stream for progress.
    """
    import uuid

    run_id = str(uuid.uuid4())

    # Create run record
    await run_store.create(run_id, tenant.tenant_id, request)

    # Start async optimization task (fire and forget)
    asyncio.create_task(_execute_run(run_id, tenant.tenant_id, request))

    return RunCreateResponse(
        run_id=run_id,
        status="PENDING",
        links={
            "self": f"/api/v1/runs/{run_id}",
            "stream": f"/api/v1/runs/{run_id}/stream",
            "schedule": f"/api/v1/runs/{run_id}/schedule",
        }
    )


@router.get("/{run_id}", response_model=RunStatusResponse)
async def get_run_status(
    run_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
):
    """Get current status of an optimization run."""
    run = await run_store.get(run_id, tenant.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunStatusResponse(
        run_id=run["run_id"],
        status=run["status"],
        progress=run["progress"],
        message=run.get("message"),
        created_at=run["created_at"],
        updated_at=run["updated_at"],
        execution_time_ms=run.get("execution_time_ms"),
    )


@router.get("/{run_id}/stream")
async def stream_run_progress(
    run_id: str,
    request: Request,
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Server-Sent Events stream for run progress.

    Events:
    - progress: {progress: 0-100, message: "..."}
    - complete: {status: "SUCCESS", execution_time_ms: ...}
    - error: {status: "FAILED", message: "..."}
    - heartbeat: {} (every 15s to keep connection alive)
    """
    run = await run_store.get(run_id, tenant.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        last_progress = -1
        last_heartbeat = time.time()

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Get current run state
            current_run = await run_store.get(run_id, tenant.tenant_id)
            if not current_run:
                yield f"event: error\ndata: {json.dumps({'message': 'Run not found'})}\n\n"
                break

            # Send progress update if changed
            progress = int(current_run["progress"])
            if progress != last_progress:
                last_progress = progress
                yield f"event: progress\ndata: {json.dumps({'progress': progress, 'message': current_run.get('message', '')})}\n\n"

            # Check for completion
            if current_run["status"] == "SUCCESS":
                yield f"event: complete\ndata: {json.dumps({'status': 'SUCCESS', 'execution_time_ms': current_run.get('execution_time_ms', 0)})}\n\n"
                break
            elif current_run["status"] == "FAILED":
                yield f"event: error\ndata: {json.dumps({'status': 'FAILED', 'message': current_run.get('message', 'Unknown error')})}\n\n"
                break

            # Send heartbeat every 15 seconds
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                yield f"event: heartbeat\ndata: {{}}\n\n"
                last_heartbeat = time.time()

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.get("/{run_id}/schedule", response_model=ScheduleResponse)
async def get_run_schedule(
    run_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
):
    """Get the final schedule for a completed run."""
    run = await run_store.get(run_id, tenant.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run["status"] == "PENDING" or run["status"] == "RUNNING":
        raise HTTPException(
            status_code=202,
            detail="Run still in progress",
            headers={"Retry-After": "5"}
        )

    if run["status"] == "FAILED":
        raise HTTPException(
            status_code=500,
            detail=f"Run failed: {run.get('message', 'Unknown error')}"
        )

    result = run.get("result")
    if not result:
        raise HTTPException(status_code=500, detail="No result available")

    return ScheduleResponse(**result)


@router.get("")
async def list_runs(
    tenant: TenantContext = Depends(get_current_tenant),
    limit: int = 20,
    offset: int = 0,
):
    """List recent optimization runs for the tenant."""
    runs = await run_store.list_for_tenant(tenant.tenant_id)

    # Sort by created_at descending
    runs.sort(key=lambda r: r["created_at"], reverse=True)

    # Paginate
    paginated = runs[offset:offset + limit]

    return {
        "runs": [
            {
                "run_id": r["run_id"],
                "status": r["status"],
                "progress": r["progress"],
                "created_at": r["created_at"],
            }
            for r in paginated
        ],
        "total": len(runs),
        "limit": limit,
        "offset": offset,
    }


# =============================================================================
# BACKGROUND EXECUTION
# =============================================================================

async def _execute_run(run_id: str, tenant_id: int, request: RunCreateRequest):
    """Execute optimization in background."""
    start_time = time.time()

    try:
        # Update status to RUNNING
        await run_store.update(run_id, status="RUNNING", progress=10, message="Parsing input")
        await asyncio.sleep(0.1)  # Allow SSE to pick up

        # Import solver
        from packs.roster.engine.solver_v2_integration import solve_with_v2_solver

        # Progress: 20% - Converting input
        await run_store.update(run_id, progress=20, message="Preparing tours")

        # Convert tours to solver format
        tour_instances = []
        for i, tour in enumerate(request.tours):
            tour_instances.append({
                "id": i + 1,
                "tour_template_id": i + 1,
                "instance_no": 1,
                "day": tour.day,
                "start_ts": tour.start_time,
                "end_ts": tour.end_time,
                "duration_min": _calculate_duration(tour.start_time, tour.end_time),
                "work_hours": _calculate_duration(tour.start_time, tour.end_time) / 60,
                "crosses_midnight": _is_cross_midnight(tour.start_time, tour.end_time),
                "depot": tour.location or "DEFAULT",
                "skill": tour.required_qualifications[0] if tour.required_qualifications else None,
            })

        # Progress: 40% - Running solver
        await run_store.update(run_id, progress=40, message="Optimizing assignments")

        # Build config
        config = {}
        if request.config_overrides:
            if request.config_overrides.seed is not None:
                config["seed"] = request.config_overrides.seed
            if request.config_overrides.max_weekly_hours is not None:
                config["max_weekly_hours"] = request.config_overrides.max_weekly_hours

        # Run solver
        result = solve_with_v2_solver(tour_instances, config)

        # Progress: 80% - Processing results
        await run_store.update(run_id, progress=80, message="Processing results")

        # Convert result to schedule response format
        schedule = _build_schedule_response(run_id, request, result)

        # Progress: 100% - Complete
        execution_time_ms = int((time.time() - start_time) * 1000)
        schedule["execution_time_ms"] = execution_time_ms

        await run_store.update(
            run_id,
            status="SUCCESS",
            progress=100,
            message="Optimization complete",
            result=schedule,
            execution_time_ms=execution_time_ms,
        )

    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}"
        await run_store.update(
            run_id,
            status="FAILED",
            message=error_msg,
            execution_time_ms=int((time.time() - start_time) * 1000),
        )


def _calculate_duration(start: str, end: str) -> int:
    """Calculate duration in minutes, handling cross-midnight."""
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))

    start_mins = sh * 60 + sm
    end_mins = eh * 60 + em

    if end_mins < start_mins:
        end_mins += 24 * 60  # Cross midnight

    return end_mins - start_mins


def _is_cross_midnight(start: str, end: str) -> bool:
    """Check if tour crosses midnight."""
    sh, _ = map(int, start.split(":"))
    eh, _ = map(int, end.split(":"))
    return eh < sh


def _build_schedule_response(run_id: str, request: RunCreateRequest, result: dict) -> dict:
    """Build schedule response from solver result."""
    assignments_out = []
    tour_map = {t.id: t for t in request.tours}

    # Group assignments by driver and day
    driver_day_map: Dict[str, Dict[int, List]] = {}

    for assignment in result.get("assignments", []):
        driver_id = str(assignment.get("driver_id", "D_UNKNOWN"))
        day = assignment.get("day", 1)

        if driver_id not in driver_day_map:
            driver_day_map[driver_id] = {}
        if day not in driver_day_map[driver_id]:
            driver_day_map[driver_id][day] = []

        # Find tour
        tour_idx = assignment.get("tour_instance_id", 1) - 1
        if 0 <= tour_idx < len(request.tours):
            tour = request.tours[tour_idx]
            driver_day_map[driver_id][day].append({
                "tour": tour,
                "work_hours": assignment.get("work_hours", 0),
            })

    # Build output
    for driver_id, days in driver_day_map.items():
        for day, tours in days.items():
            blocks = []
            total_hours = 0

            for t in tours:
                tour = t["tour"]
                duration = _calculate_duration(tour.start_time, tour.end_time) / 60
                blocks.append(BlockOutput(
                    tours=[TourOutput(
                        id=tour.id,
                        day=tour.day,
                        start_time=tour.start_time,
                        end_time=tour.end_time,
                        duration_hours=duration,
                        location=tour.location,
                        required_qualifications=tour.required_qualifications,
                    )],
                    total_hours=duration,
                    span_hours=duration,
                ))
                total_hours += duration

            assignments_out.append(AssignmentOutput(
                driver_id=driver_id,
                driver_name=f"Driver {driver_id}",
                day=day,
                blocks=blocks,
                daily_hours=total_hours,
                daily_span=total_hours,  # Simplified
            ))

    # Stats
    total_tours = len(request.tours)
    assigned_tours = len(result.get("assignments", []))

    stats = StatsOutput(
        total_drivers=result.get("total_drivers", len(driver_day_map)),
        total_tours=total_tours,
        assigned_tours=assigned_tours,
        unassigned_tours=total_tours - assigned_tours,
        coverage=assigned_tours / total_tours if total_tours > 0 else 1.0,
        avg_hours_per_driver=result.get("avg_hours_per_driver", 0),
        max_hours_driver=result.get("max_hours_driver", 0),
    )

    return {
        "run_id": run_id,
        "status": "SUCCESS",
        "assignments": [a.model_dump() for a in assignments_out],
        "unassigned": [],  # TODO: Track unassigned tours
        "stats": stats.model_dump(),
        "execution_time_ms": 0,  # Will be set by caller
    }
