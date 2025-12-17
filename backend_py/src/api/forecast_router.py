"""
Forecast API Router
===================
Adapts frontend requests to v4 solver
"""

import uuid
import logging
import traceback
from datetime import time as dt_time
from fastapi import APIRouter, HTTPException, Form, Response
from fastapi.responses import StreamingResponse

from src.api.models import (
    ScheduleRequest, ScheduleResponse, HealthResponse,
    TourInputFE, TourOutputFE, BlockOutputFE, AssignmentOutputFE,
    StatsOutputFE, ValidationOutputFE, WeekdayFE, WEEKDAY_MAP, WEEKDAY_REVERSE
)
from src.domain.models import Tour, Weekday
from src.services.forecast_solver_v4 import solve_forecast_v4, ConfigV4
from src.services.log_stream import emit_log, get_log_generator, clear_logs

# Setup logger
logger = logging.getLogger("ForecastRouter")

router = APIRouter(prefix="/api/v1", tags=["forecast"])


# =============================================================================
# HEALTH
# =============================================================================

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        version="4.0",
        constraints={
            "min_hours_per_fte": 42.0,
            "max_hours_per_fte": 53.0,
            "max_daily_span_hours": 14.0,
        }
    )


# =============================================================================
# CONSTRAINTS
# =============================================================================

@router.get("/constraints")
async def get_constraints():
    """Get solver constraints."""
    return {
        "hard": {
            "min_hours_per_fte": 42.0,
            "max_hours_per_fte": 53.0,
            "max_daily_span_hours": 14.0,
            "min_rest_hours": 11.0,
        },
        "soft": {
            "prefer_larger_blocks": True,
            "target_2er_ratio": 0.72,
            "target_3er_ratio": 0.22,
        }
    }


# =============================================================================
# LOG STREAM (SSE)
# =============================================================================

@router.get("/logs/stream")
async def stream_logs():
    """
    Server-Sent Events endpoint for live log streaming.
    
    Connect with EventSource in browser to receive real-time solver logs.
    """
    return StreamingResponse(
        get_log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if present
        }
    )


# =============================================================================
# GLOBAL STATE (Process Local)
# =============================================================================

LAST_RESULT = None  # Cache the last schedule response for export


# =============================================================================
# EXPORT
# =============================================================================

@router.get("/export/roster")
async def export_roster_csv():
    """
    Generate and download Roster CSV from the last result.
    Uses cached state to avoid client-side download issues.
    """
    global LAST_RESULT
    if not LAST_RESULT:
        raise HTTPException(status_code=404, detail="No schedule available. Run optimization first.")
    
    try:
        csv_content = _generate_roster_csv(LAST_RESULT)
        
        # Add BOM for Excel
        if not csv_content.startswith('\ufeff'):
            csv_content = '\ufeff' + csv_content
            
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=roster_matrix.csv"
            }
        )
    except Exception as e:
        logger.error(f"Export error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


def _generate_roster_csv(response: ScheduleResponse) -> str:
    """Generate CSV string from response object."""
    # Data structure: driver_id -> { day: [times] }
    driver_map = {}
    driver_names = {}
    
    # Days order
    days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]
    day_labels = {
        "MONDAY": "Montag",
        "TUESDAY": "Dienstag",
        "WEDNESDAY": "Mittwoch",
        "THURSDAY": "Donnerstag",
        "FRIDAY": "Freitag",
        "SATURDAY": "Samstag",
        "SUNDAY": "Sonntag"
    }

    # Populate map
    for a in response.assignments:
        d_id = a.driver_id
        if d_id not in driver_map:
            driver_map[d_id] = {}
            driver_names[d_id] = a.driver_name
            
        # Ensure day sub-dict exists
        # Note: a.day is a string like "MONDAY"
        day_key = a.day
        if day_key not in driver_map[d_id]:
            driver_map[d_id][day_key] = []
            
        # Add tour times
        for tour in a.block.tours:
            time_str = f"{tour.start_time}-{tour.end_time}"
            driver_map[d_id][day_key].append(time_str)

    # Sort drivers (by ID or name)
    sorted_ids = sorted(driver_map.keys())

    # Build CSV lines
    lines = []
    
    # Header
    header = ["Fahrer"] + [day_labels.get(d, d) for d in days]
    lines.append(";".join(header))
    
    # Rows
    for d_id in sorted_ids:
        name = driver_names.get(d_id, d_id)
        row = [name]
        
        for day in days:
            times = driver_map.get(d_id, {}).get(day, [])
            cell = ", ".join(times)
            row.append(cell)
            
        lines.append(";".join(row))
        
    return "\n".join(lines)


# =============================================================================
# SCHEDULE
# =============================================================================

@router.post("/schedule", response_model=ScheduleResponse)
async def create_schedule(request: ScheduleRequest):
    """
    Create optimized schedule.
    
    Converts frontend format to internal Tour objects,
    runs v4 solver, and converts response back.
    """
    # Clear previous logs for new solve session
    clear_logs()
    emit_log("═" * 40, "INFO")
    
    # ... (existing logging code) ...
    emit_log("SCHEDULE REQUEST RECEIVED", "INFO")
    emit_log("═" * 40, "INFO")
    
    logger.info("=" * 60)
    logger.info("SCHEDULE REQUEST RECEIVED")
    logger.info("=" * 60)
    
    # Convert frontend tours to internal Tours
    emit_log(f"Converting {len(request.tours)} tours...", "INFO")
    logger.info(f"Converting {len(request.tours)} tours...")
    tours = _convert_tours(request.tours)
    
    if not tours:
        logger.error("No valid tours after conversion!")
        emit_log("ERROR: No valid tours after conversion!", "ERROR")
        raise HTTPException(status_code=400, detail="No valid tours provided")
    
    emit_log(f"✓ Converted {len(tours)} tours", "SUCCESS")
    logger.info(f"Successfully converted {len(tours)} tours")
    
    # Build config from request
    config = ConfigV4(
        time_limit_phase1=float(request.time_limit_seconds),
        seed=request.seed or 42,
    )
    emit_log(f"Config: time_limit={config.time_limit_phase1}s, seed={config.seed}", "INFO")
    emit_log(f"Solver type: {request.solver_type}", "INFO")
    logger.info(f"Config: time_limit={config.time_limit_phase1}s, seed={config.seed}")
    logger.info(f"Solver type: {request.solver_type}")
    
    # Run solver
    try:
        emit_log("Starting solver...", "INFO")
        logger.info("Starting solver...")
        
        # Use FTE-only global CP-SAT for cpsat-global solver type
        if request.solver_type == "cpsat-global":
            emit_log("Using GLOBAL CP-SAT FTE-ONLY solver", "INFO")
            from src.services.forecast_solver_v4 import solve_forecast_fte_only
            result = solve_forecast_fte_only(
                tours,
                time_limit_feasible=float(request.time_limit_seconds),  # Use full time
                time_limit_optimize=float(request.time_limit_seconds),
                seed=request.seed or 42,
            )
        elif request.solver_type == "set-partitioning":
            emit_log("Using SET-PARTITIONING (Crew Scheduling) solver", "INFO")
            from src.services.forecast_solver_v4 import solve_forecast_set_partitioning
            result = solve_forecast_set_partitioning(
                tours,
                time_limit=float(request.time_limit_seconds),
                seed=request.seed or 42,
            )
        else:
            result = solve_forecast_v4(tours, config)
        
        emit_log(f"✓ Solver completed! Status: {result.status}", "SUCCESS")
        emit_log(f"Drivers FTE: {result.kpi.get('drivers_fte', 0)}, PT: {result.kpi.get('drivers_pt', 0)}", "INFO")
        logger.info(f"Solver completed! Status: {result.status}")
        logger.info(f"KPI: {result.kpi}")
        
        # Optional LNS refinement for cpsat+lns
        if request.solver_type == "cpsat+lns" and result.assignments:
            print("=" * 60, flush=True)
            print("STARTING LNS PHASE 3 REFINEMENT", flush=True)
            print("=" * 60, flush=True)
            print(f"Input assignments: {len(result.assignments)}", flush=True)
            
            # Log assignment structure before LNS
            for i, a in enumerate(result.assignments[:3]):
                print(f"  Assignment[{i}]: driver={a.driver_id}, type={a.driver_type}, blocks={len(a.blocks)}", flush=True)
                for j, block in enumerate(a.blocks[:2]):
                    print(f"    Block[{j}]: id={block.id}, day={block.day}, tours={len(block.tours)}", flush=True)
                    print(f"      Block type: {type(block).__name__}", flush=True)
                    print(f"      Has first_start: {hasattr(block, 'first_start')}", flush=True)
                    if hasattr(block, 'first_start'):
                        print(f"      first_start = {block.first_start}", flush=True)
                    print(f"      Has start_time: {hasattr(block, 'start_time')}", flush=True)
            
            from src.services.lns_refiner_v4 import refine_assignments_v4, LNSConfigV4
            
            lns_config = LNSConfigV4(
                max_iterations=request.lns_iterations,
                seed=config.seed,
                lns_time_limit=float(request.time_limit_seconds),  # Use frontend time limit
            )
            print(f"LNS Config: iterations={lns_config.max_iterations}, seed={lns_config.seed}, time_limit={lns_config.lns_time_limit}s", flush=True)
            
            try:
                refined_assignments = refine_assignments_v4(result.assignments, lns_config)
                print(f"LNS refinement COMPLETE: {len(refined_assignments)} assignments", flush=True)
                
                # Update result with refined assignments
                result.assignments = refined_assignments
                result.kpi["lns_applied"] = True
                result.kpi["lns_iterations"] = request.lns_iterations
                print("LNS results applied successfully", flush=True)
            except Exception as lns_error:
                print(f"LNS ERROR: {lns_error}", flush=True)
                print(f"LNS TRACEBACK:\n{traceback.format_exc()}", flush=True)
                raise
            
    except Exception as e:
        logger.error(f"SOLVER ERROR: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Solver error: {str(e)}")
    
    # Convert response
    logger.info("Converting response...")
    response = _convert_response(result, request, tours)
    
    # Cache result for export
    global LAST_RESULT
    LAST_RESULT = response
    
    logger.info(f"Response ready: {len(response.assignments)} assignments")
    logger.info("=" * 60)
    
    return response


# =============================================================================
# CONVERTERS
# =============================================================================

def _convert_tours(fe_tours: list[TourInputFE]) -> list[Tour]:
    """Convert frontend tours to internal Tour objects."""
    tours = []
    
    for fe in fe_tours:
        try:
            # Parse times
            start_h, start_m = map(int, fe.start_time.split(":"))
            end_h, end_m = map(int, fe.end_time.split(":"))
            
            # Get internal weekday
            internal_day = WEEKDAY_MAP.get(fe.day, "Mon")
            weekday = Weekday(internal_day)
            
            tour = Tour(
                id=fe.id,
                day=weekday,
                start_time=dt_time(start_h, start_m),
                end_time=dt_time(end_h, end_m),
            )
            tours.append(tour)
        except Exception as e:
            print(f"[API] Failed to parse tour {fe.id}: {e}")
            continue
    
    return tours


def _convert_response(result, request: ScheduleRequest, tours: list[Tour]) -> ScheduleResponse:
    """Convert v4 result to frontend response format."""
    from src.services.forecast_solver_v4 import SolveResultV4
    
    result: SolveResultV4 = result
    
    # Build assignments list
    assignments = []
    total_assigned = 0
    
    for driver in result.assignments:
        for block in driver.blocks:
            # Convert block type
            n = len(block.tours)
            block_type = "single" if n == 1 else "double" if n == 2 else "triple"
            
            # Convert day
            fe_day = block.day.value.upper()
            if len(fe_day) == 3:
                # Mon -> MONDAY
                day_map = {"Mon": "MONDAY", "Tue": "TUESDAY", "Wed": "WEDNESDAY",
                          "Thu": "THURSDAY", "Fri": "FRIDAY", "Sat": "SATURDAY", "Sun": "SUNDAY"}
                fe_day = day_map.get(block.day.value, block.day.value)
            
            # Convert tours
            tour_outputs = []
            for t in block.tours:
                tour_outputs.append(TourOutputFE(
                    id=t.id,
                    day=fe_day,
                    start_time=t.start_time.strftime("%H:%M"),
                    end_time=t.end_time.strftime("%H:%M"),
                    duration_hours=t.duration_hours,
                ))
            
            total_assigned += len(block.tours)
            
            block_output = BlockOutputFE(
                id=block.id,
                day=fe_day,
                block_type=block_type,
                tours=tour_outputs,
                driver_id=driver.driver_id,
                total_work_hours=block.total_work_hours,
                span_hours=block.total_work_hours,  # Simplified
            )
            
            assignments.append(AssignmentOutputFE(
                driver_id=driver.driver_id,
                driver_name=driver.driver_id,  # Same as ID for v4
                day=fe_day,
                block=block_output,
            ))
    
    # Stats
    kpi = result.kpi
    block_counts = {
        "single": kpi.get("blocks_1er", 0),
        "double": kpi.get("blocks_2er", 0),
        "triple": kpi.get("blocks_3er", 0),
    }
    
    total_drivers = kpi.get("drivers_fte", 0) + kpi.get("drivers_pt", 0)
    
    stats = StatsOutputFE(
        total_drivers=total_drivers,
        total_tours_input=len(tours),
        total_tours_assigned=total_assigned,
        total_tours_unassigned=0,
        block_counts=block_counts,
        assignment_rate=1.0 if total_assigned == len(tours) else total_assigned / len(tours),
        average_driver_utilization=kpi.get("fte_hours_avg", 0) / 53.0,
        average_work_hours=kpi.get("fte_hours_avg", 0.0),
        block_mix=kpi.get("block_mix"),
        template_match_count=kpi.get("template_match_count"),
        split_2er_count=kpi.get("split_2er_count"),
    )
    
    # Validation
    validation = ValidationOutputFE(
        is_valid=result.status in ("HARD_OK", "SOFT_FALLBACK_HOURS"),
        hard_violations=[],
        warnings=[] if result.status == "HARD_OK" else [f"Status: {result.status}"],
    )
    
    return ScheduleResponse(
        id=str(uuid.uuid4()),
        week_start=request.week_start,
        assignments=assignments,
        unassigned_tours=[],
        validation=validation,
        stats=stats,
        version="4.0",
        solver_type=request.solver_type,
    )
