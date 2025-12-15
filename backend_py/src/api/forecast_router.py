"""
Forecast API Router
===================
Adapts frontend requests to v4 solver
"""

import uuid
import logging
import traceback
from datetime import time as dt_time
from fastapi import APIRouter, HTTPException

from src.api.models import (
    ScheduleRequest, ScheduleResponse, HealthResponse,
    TourInputFE, TourOutputFE, BlockOutputFE, AssignmentOutputFE,
    StatsOutputFE, ValidationOutputFE, WeekdayFE, WEEKDAY_MAP, WEEKDAY_REVERSE
)
from src.domain.models import Tour, Weekday
from src.services.forecast_solver_v4 import solve_forecast_v4, ConfigV4

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
# SCHEDULE
# =============================================================================

@router.post("/schedule", response_model=ScheduleResponse)
async def create_schedule(request: ScheduleRequest):
    """
    Create optimized schedule.
    
    Converts frontend format to internal Tour objects,
    runs v4 solver, and converts response back.
    """
    logger.info("=" * 60)
    logger.info("SCHEDULE REQUEST RECEIVED")
    logger.info("=" * 60)
    
    # Convert frontend tours to internal Tours
    logger.info(f"Converting {len(request.tours)} tours...")
    tours = _convert_tours(request.tours)
    
    if not tours:
        logger.error("No valid tours after conversion!")
        raise HTTPException(status_code=400, detail="No valid tours provided")
    
    logger.info(f"Successfully converted {len(tours)} tours")
    
    # Build config from request
    config = ConfigV4(
        time_limit_phase1=float(request.time_limit_seconds),
        seed=request.seed or 42,
    )
    logger.info(f"Config: time_limit={config.time_limit_phase1}s, seed={config.seed}")
    logger.info(f"Solver type: {request.solver_type}")
    
    # Run solver
    try:
        logger.info("Starting solver...")
        result = solve_forecast_v4(tours, config)
        logger.info(f"Solver completed! Status: {result.status}")
        logger.info(f"KPI: {result.kpi}")
        
        # Optional LNS refinement for cpsat+lns
        if request.solver_type == "cpsat+lns" and result.assignments:
            logger.info("=" * 40)
            logger.info("Starting LNS Phase 3 refinement...")
            from src.services.lns_refiner_v4 import refine_assignments_v4, LNSConfigV4
            
            lns_config = LNSConfigV4(
                max_iterations=request.lns_iterations,
                seed=config.seed,
            )
            
            refined_assignments = refine_assignments_v4(result.assignments, lns_config)
            
            # Update result with refined assignments
            result.assignments = refined_assignments
            result.kpi["lns_applied"] = True
            result.kpi["lns_iterations"] = request.lns_iterations
            logger.info("LNS refinement complete")
            
    except Exception as e:
        logger.error(f"SOLVER ERROR: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Solver error: {str(e)}")
    
    # Convert response
    logger.info("Converting response...")
    response = _convert_response(result, request, tours)
    
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
