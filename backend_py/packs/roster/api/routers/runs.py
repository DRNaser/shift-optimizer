"""
SOLVEREIGN V4.8 - Roster Pack Runs API (Session Auth)
=======================================================

Session-authenticated optimization run management for Roster Workbench.
Uses internal RBAC (not X-API-Key) for browser-based access.

Endpoints:
- POST /api/v1/roster/runs          Create new optimization run
- GET /api/v1/roster/runs/{id}      Get run status
- GET /api/v1/roster/runs/{id}/schedule  Get final schedule

NON-NEGOTIABLES:
- Tenant isolation via session context (NEVER from client headers)
- Permission check: roster.runs.write for create, roster.runs.read for status
"""

import json
import asyncio
import time
import logging
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from api.security.internal_rbac import (
    InternalUserContext,
    TenantContext,
    require_tenant_context_with_permission,
    require_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roster/runs", tags=["roster-runs"])


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
    error_code: Optional[str] = None
    trace_id: Optional[str] = None
    error_detail: Optional[Dict[str, Any]] = None
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
    id: str
    day: str
    block_type: str
    tours: List[TourOutput]
    total_work_hours: float
    span_hours: float


class AssignmentOutput(BaseModel):
    """Driver assignment in schedule."""
    driver_id: str
    driver_name: str
    day: str
    block: BlockOutput
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
# IN-MEMORY RUN STORE (tenant-isolated)
# =============================================================================

class TenantRunStore:
    """In-memory run storage with tenant isolation."""

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

    async def list_for_tenant(self, tenant_id: int, limit: int = 20) -> List[Dict]:
        runs = [r for r in self._runs.values() if r["tenant_id"] == tenant_id]
        runs.sort(key=lambda r: r["created_at"], reverse=True)
        return runs[:limit]


# Global run store
run_store = TenantRunStore()


# =============================================================================
# PERMISSION HELPERS
# =============================================================================

def get_runs_write_permission():
    """Permission check for creating runs."""
    return require_permission("roster.runs.write")


def get_runs_read_permission():
    """Permission check for reading runs."""
    return require_permission("roster.runs.read")


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("", response_model=RunCreateResponse)
async def create_run(
    request: RunCreateRequest,
    user: InternalUserContext = Depends(get_runs_write_permission()),
):
    """
    Create a new optimization run (session authenticated).

    Returns immediately with run_id. Poll /runs/{id} for status.
    """
    run_id = str(uuid4())
    tenant_id = user.tenant_id or 0

    logger.info(f"[Roster Runs] Creating run {run_id} for tenant {tenant_id} with {len(request.tours)} tours")

    # Create run record
    await run_store.create(run_id, tenant_id, request)

    # Start async optimization task
    asyncio.create_task(_execute_run(run_id, tenant_id, request))

    return RunCreateResponse(
        run_id=run_id,
        status="PENDING",
        links={
            "self": f"/api/v1/roster/runs/{run_id}",
            "schedule": f"/api/v1/roster/runs/{run_id}/schedule",
        }
    )


@router.get("/{run_id}", response_model=RunStatusResponse)
async def get_run_status(
    run_id: str,
    user: InternalUserContext = Depends(get_runs_read_permission()),
):
    """Get current status of an optimization run."""
    tenant_id = user.tenant_id or 0
    run = await run_store.get(run_id, tenant_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunStatusResponse(
        run_id=run["run_id"],
        status=run["status"],
        progress=run["progress"],
        message=run.get("message"),
        error_code=run.get("error_code"),
        trace_id=run.get("trace_id"),
        error_detail=run.get("error_detail"),
        created_at=run["created_at"],
        updated_at=run["updated_at"],
        execution_time_ms=run.get("execution_time_ms"),
    )


@router.get("/{run_id}/schedule", response_model=ScheduleResponse)
async def get_run_schedule(
    run_id: str,
    user: InternalUserContext = Depends(get_runs_read_permission()),
):
    """Get the final schedule for a completed run."""
    tenant_id = user.tenant_id or 0
    run = await run_store.get(run_id, tenant_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run["status"] in ("PENDING", "RUNNING"):
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
    user: InternalUserContext = Depends(get_runs_read_permission()),
    limit: int = 20,
):
    """List recent optimization runs for the tenant."""
    tenant_id = user.tenant_id or 0
    runs = await run_store.list_for_tenant(tenant_id, limit)

    return {
        "runs": [
            {
                "run_id": r["run_id"],
                "status": r["status"],
                "progress": r["progress"],
                "created_at": r["created_at"],
            }
            for r in runs
        ],
        "total": len(runs),
    }


# =============================================================================
# BACKGROUND EXECUTION
# =============================================================================

async def _execute_run(run_id: str, tenant_id: int, request: RunCreateRequest):
    """Execute optimization in background."""
    start_time = time.time()
    trace_id = f"run_{run_id[:8]}"

    try:
        await run_store.update(run_id, status="RUNNING", progress=10, message="Parsing input", trace_id=trace_id)
        await asyncio.sleep(0.1)

        # Import solver (V3 Block Heuristic via V2 integration bridge)
        from v3.solver_v2_integration import solve_with_v2_solver

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

        await run_store.update(run_id, progress=40, message="Optimizing assignments")

        # Extract seed from config overrides (default: 94)
        seed = 94
        if request.config_overrides and request.config_overrides.seed is not None:
            seed = request.config_overrides.seed

        logger.info(f"[Roster Runs] {trace_id} - Starting solver with {len(tour_instances)} tours, seed={seed}")

        # Run solver with structured error handling
        try:
            result = solve_with_v2_solver(tour_instances, seed)
        except Exception as solver_error:
            error_type = type(solver_error).__name__
            error_detail = str(solver_error)
            tb = traceback.format_exc()

            # Classify error
            if "infeasible" in error_detail.lower():
                error_code = "SOLVER_INFEASIBLE"
                error_msg = "No feasible solution found - check driver capacity vs tour demand"
            elif "timeout" in error_detail.lower():
                error_code = "SOLVER_TIMEOUT"
                error_msg = "Solver timed out - try reducing problem size or increasing time limit"
            else:
                error_code = "SOLVER_ERROR"
                error_msg = f"{error_type}: {error_detail}"

            logger.error(f"[Roster Runs] {trace_id} - Solver failed: {error_msg}\n{tb}")

            await run_store.update(
                run_id,
                status="FAILED",
                message=error_msg,
                error_code=error_code,
                trace_id=trace_id,
                error_detail={"type": error_type, "message": error_detail, "traceback": tb[:2000]},
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
            return

        await run_store.update(run_id, progress=80, message="Processing results")

        # Convert result to schedule response
        schedule = _build_schedule_response(run_id, request, result)

        execution_time_ms = int((time.time() - start_time) * 1000)
        schedule["execution_time_ms"] = execution_time_ms
        schedule["trace_id"] = trace_id

        await run_store.update(
            run_id,
            status="SUCCESS",
            progress=100,
            message="Optimization complete",
            result=schedule,
            trace_id=trace_id,
            execution_time_ms=execution_time_ms,
        )

        logger.info(f"[Roster Runs] {trace_id} - Completed in {execution_time_ms}ms")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        tb = traceback.format_exc()
        logger.error(f"[Roster Runs] {trace_id} - Failed: {error_msg}\n{tb}")
        await run_store.update(
            run_id,
            status="FAILED",
            message=error_msg,
            error_code="EXECUTION_ERROR",
            trace_id=trace_id,
            error_detail={"type": type(e).__name__, "message": str(e), "traceback": tb[:2000]},
            execution_time_ms=int((time.time() - start_time) * 1000),
        )


def _calculate_duration(start: str, end: str) -> int:
    """Calculate duration in minutes, handling cross-midnight."""
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))

    start_mins = sh * 60 + sm
    end_mins = eh * 60 + em

    if end_mins < start_mins:
        end_mins += 24 * 60

    return end_mins - start_mins


def _is_cross_midnight(start: str, end: str) -> bool:
    """Check if tour crosses midnight."""
    sh, _ = map(int, start.split(":"))
    eh, _ = map(int, end.split(":"))
    return eh < sh


DAY_INT_TO_STR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def _build_schedule_response(run_id: str, request: RunCreateRequest, result) -> dict:
    """Build schedule response from solver result."""
    assignments_out = []

    # Handle both list (V2 solver) and dict (V3 solver) results
    if isinstance(result, list):
        assignments_raw = result
    else:
        assignments_raw = result.get("assignments", [])

    # Group by driver/day
    driver_day_map: Dict[str, Dict[int, List]] = {}

    for assignment in assignments_raw:
        driver_id = str(assignment.get("driver_id", "D_UNKNOWN"))
        day = assignment.get("day", 1)

        if driver_id not in driver_day_map:
            driver_day_map[driver_id] = {}
        if day not in driver_day_map[driver_id]:
            driver_day_map[driver_id][day] = []

        tour_idx = assignment.get("tour_instance_id", 1) - 1
        if 0 <= tour_idx < len(request.tours):
            tour = request.tours[tour_idx]
            driver_day_map[driver_id][day].append({
                "tour": tour,
                "work_hours": assignment.get("work_hours", 0),
            })

    for driver_id, days in driver_day_map.items():
        for day, tour_list in days.items():
            total_hours = 0
            tour_outputs = []

            for t in tour_list:
                tour = t["tour"]
                duration = _calculate_duration(tour.start_time, tour.end_time) / 60
                tour_outputs.append(TourOutput(
                    id=tour.id,
                    day=tour.day,
                    start_time=tour.start_time,
                    end_time=tour.end_time,
                    duration_hours=duration,
                    location=tour.location,
                    required_qualifications=tour.required_qualifications,
                ))
                total_hours += duration

            # Determine block type based on tour count
            block_type = f"{len(tour_outputs)}er" if len(tour_outputs) <= 3 else "3er+"
            day_str = DAY_INT_TO_STR.get(day, "Mon")

            block = BlockOutput(
                id=f"B_{driver_id}_{day}",
                day=day_str,
                block_type=block_type,
                tours=tour_outputs,
                total_work_hours=total_hours,
                span_hours=total_hours,
            )

            assignments_out.append(AssignmentOutput(
                driver_id=driver_id,
                driver_name=f"Driver {driver_id}",
                day=day_str,
                block=block,
                daily_hours=total_hours,
                daily_span=total_hours,
            ))

    total_tours = len(request.tours)
    assigned_tours = len(assignments_raw)

    stats = StatsOutput(
        total_drivers=len(driver_day_map),
        total_tours=total_tours,
        assigned_tours=assigned_tours,
        unassigned_tours=total_tours - assigned_tours,
        coverage=assigned_tours / total_tours if total_tours > 0 else 1.0,
        avg_hours_per_driver=0,
        max_hours_driver=0,
    )

    return {
        "run_id": run_id,
        "status": "SUCCESS",
        "assignments": [a.model_dump() for a in assignments_out],
        "unassigned": [],
        "stats": stats.model_dump(),
        "execution_time_ms": 0,
    }
