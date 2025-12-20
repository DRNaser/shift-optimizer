"""
SHIFT OPTIMIZER - API Routes
==============================
FastAPI route definitions.
"""

from datetime import date, time, datetime
from fastapi import APIRouter, HTTPException

from src.domain.models import (
    Tour,
    Driver,
    DailyAvailability,
    Weekday,
)
from src.domain.constraints import HARD_CONSTRAINTS
from src.services.scheduler import create_schedule, SchedulerConfig
from src.services.cpsat_solver import create_cpsat_schedule, CPSATConfig
from src.services.lns_refiner import refine_schedule, LNSConfig
from src.api.schemas import (
    ScheduleRequest,
    ScheduleResponse,
    HealthResponse,
    ErrorResponse,
    TourInput,
    DriverInput,
    TourOutput,
    BlockOutput,
    AssignmentOutput,
    UnassignedTourOutput,
    StatsOutput,
    ValidationOutput,
)


router = APIRouter()


# =============================================================================
# HELPERS
# =============================================================================

def parse_time(time_str: str) -> time:
    """Parse HH:MM string to time object."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]))


def parse_date(date_str: str) -> date:
    """Parse YYYY-MM-DD string to date object."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def tour_input_to_domain(tour_input: TourInput) -> Tour:
    """Convert API tour input to domain model."""
    return Tour(
        id=tour_input.id,
        day=tour_input.day,
        start_time=parse_time(tour_input.start_time),
        end_time=parse_time(tour_input.end_time),
        location=tour_input.location,
        required_qualifications=tour_input.required_qualifications
    )


def driver_input_to_domain(driver_input: DriverInput) -> Driver:
    """Convert API driver input to domain model."""
    # Build availability from available_days
    availability = []
    for day in Weekday:
        availability.append(DailyAvailability(
            day=day,
            available=day in driver_input.available_days
        ))
    
    return Driver(
        id=driver_input.id,
        name=driver_input.name,
        qualifications=driver_input.qualifications,
        max_weekly_hours=driver_input.max_weekly_hours,
        max_daily_span_hours=driver_input.max_daily_span_hours,
        max_tours_per_day=driver_input.max_tours_per_day,
        min_rest_hours=driver_input.min_rest_hours,
        weekly_availability=availability
    )


def tour_to_output(tour: Tour) -> TourOutput:
    """Convert domain tour to API output."""
    return TourOutput(
        id=tour.id,
        day=tour.day.value,
        start_time=tour.start_time.strftime("%H:%M"),
        end_time=tour.end_time.strftime("%H:%M"),
        duration_hours=tour.duration_hours,
        location=tour.location,
        required_qualifications=tour.required_qualifications
    )


# =============================================================================
# ROUTES
# =============================================================================

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        constraints={
            "max_weekly_hours": HARD_CONSTRAINTS.MAX_WEEKLY_HOURS,
            "max_daily_span_hours": HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS,
            "min_rest_hours": HARD_CONSTRAINTS.MIN_REST_HOURS,
            "max_tours_per_day": HARD_CONSTRAINTS.MAX_TOURS_PER_DAY,
        }
    )


@router.post("/schedule", response_model=ScheduleResponse)
async def create_weekly_schedule(request: ScheduleRequest):
    """
    Create a weekly schedule from tours and drivers.
    
    Supports three solvers:
    - 'greedy': Fast baseline scheduler (feasible-first)
    - 'cpsat': Optimal CP-SAT solver
    - 'cpsat+lns': CP-SAT with LNS refinement (best quality)
    """
    try:
        # DEBUG: Entry probe
        with open("entry_probe.txt", "w") as f:
            f.write(f"Entry reached! Request: {request.solver_type}\n")

        # Convert inputs to domain models
        tours = [tour_input_to_domain(t) for t in request.tours]
        drivers = [driver_input_to_domain(d) for d in request.drivers]
        week_start = parse_date(request.week_start)
        
        # Choose solver
        solver_type = request.solver_type.lower()
        locked_blocks = set(request.locked_block_ids) if request.locked_block_ids else None
        
        if solver_type == "cpsat+lns":
            # CP-SAT + LNS refinement
            cpsat_config = CPSATConfig(
                time_limit_seconds=request.time_limit_seconds,
                seed=request.seed,
                prefer_larger_blocks=request.prefer_larger_blocks,
                optimize=True
            )
            initial_plan = create_cpsat_schedule(tours, drivers, week_start, cpsat_config)
            
            # Refine with LNS
            lns_config = LNSConfig(
                max_iterations=request.lns_iterations,
                seed=request.seed
            )
            plan = refine_schedule(initial_plan, tours, drivers, lns_config, locked_blocks)
            
        elif solver_type == "cpsat":
            # Use CP-SAT solver only
            # DEBUG: Write route probe
            with open("route_probe.txt", "w") as f:
                f.write(f"Route reached! Algo={solver_type}\n")

            config = CPSATConfig(
                time_limit_seconds=request.time_limit_seconds,
                seed=request.seed,
                prefer_larger_blocks=request.prefer_larger_blocks,
                optimize=True
            )
            plan = create_cpsat_schedule(tours, drivers, week_start, config)
        else:
            # Use greedy baseline
            config = SchedulerConfig(
                prefer_larger_blocks=request.prefer_larger_blocks,
                seed=request.seed
            )
            plan = create_schedule(tours, drivers, week_start, config)
        
        # Build driver lookup for names
        driver_lookup = {d.id: d.name for d in drivers}
        
        # Convert to response format
        assignments = []
        for assignment in plan.assignments:
            block = assignment.block
            tours_output = [tour_to_output(t) for t in block.tours]
            
            assignments.append(AssignmentOutput(
                driver_id=assignment.driver_id,
                driver_name=driver_lookup.get(assignment.driver_id, "Unknown"),
                day=assignment.day.value,
                block=BlockOutput(
                    id=block.id,
                    day=block.day.value,
                    block_type=block.block_type.value,
                    tours=tours_output,
                    driver_id=block.driver_id,
                    total_work_hours=block.total_work_hours,
                    span_hours=block.span_hours
                )
            ))
        
        unassigned = []
        for item in plan.unassigned_tours:
            unassigned.append(UnassignedTourOutput(
                tour=tour_to_output(item.tour),
                reason_codes=[r.value for r in item.reason_codes],
                details=item.details
            ))
        
        # Compute average work hours per driver
        driver_hours: dict[str, float] = {}
        for assignment in plan.assignments:
            driver_id = assignment.driver_id
            hours = assignment.block.total_work_hours
            driver_hours[driver_id] = driver_hours.get(driver_id, 0.0) + hours
        avg_work_hours = sum(driver_hours.values()) / len(driver_hours) if driver_hours else 0.0
        
        stats = StatsOutput(
            total_drivers=plan.stats.total_drivers,
            total_tours_input=plan.stats.total_tours_input,
            total_tours_assigned=plan.stats.total_tours_assigned,
            total_tours_unassigned=plan.stats.total_tours_unassigned,
            block_counts={k.value: v for k, v in plan.stats.block_counts.items()},
            assignment_rate=plan.stats.assignment_rate,
            average_driver_utilization=plan.stats.average_driver_utilization,
            average_work_hours=avg_work_hours
        )
        
        validation = ValidationOutput(
            is_valid=plan.validation.is_valid,
            hard_violations=plan.validation.hard_violations,
            warnings=plan.validation.warnings
        )
        
        return ScheduleResponse(
            id=plan.id,
            week_start=plan.week_start.isoformat(),
            assignments=assignments,
            unassigned_tours=unassigned,
            validation=validation,
            stats=stats,
            version=plan.version,
            solver_type=solver_type
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/constraints")
async def get_constraints():
    """Get all hard constraints and their values."""
    return {
        "hard_constraints": {
            "MAX_WEEKLY_HOURS": HARD_CONSTRAINTS.MAX_WEEKLY_HOURS,
            "MAX_DAILY_SPAN_HOURS": HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS,
            "MIN_REST_HOURS": HARD_CONSTRAINTS.MIN_REST_HOURS,
            "MAX_TOURS_PER_DAY": HARD_CONSTRAINTS.MAX_TOURS_PER_DAY,
            "MAX_BLOCKS_PER_DRIVER_PER_DAY": HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY,
            "NO_TOUR_OVERLAP": HARD_CONSTRAINTS.NO_TOUR_OVERLAP,
            "QUALIFICATION_REQUIRED": HARD_CONSTRAINTS.QUALIFICATION_REQUIRED,
            "AVAILABILITY_REQUIRED": HARD_CONSTRAINTS.AVAILABILITY_REQUIRED,
            "MIN_TOURS_PER_BLOCK": HARD_CONSTRAINTS.MIN_TOURS_PER_BLOCK,
            "MAX_TOURS_PER_BLOCK": HARD_CONSTRAINTS.MAX_TOURS_PER_BLOCK,
        }
    }


@router.post("/unassigned-diagnostics")
async def get_unassigned_diagnostics(request: ScheduleRequest):
    """
    Get detailed diagnostics for unassigned tours.
    
    Returns enhanced information for each unassigned tour including:
    - reason_code: Primary blocking reason
    - candidate_blocks_total: Number of blocks containing this tour
    - candidate_drivers_total: Number of feasible (block, driver) pairs
    - top_blockers: List of blocking reasons with counts
    - has_any_blocks: Whether at least one block includes this tour
    - has_any_feasible_driver: Whether at least one driver can take a block with this tour
    - is_globally_conflicting: Whether tour was feasible but lost in global optimization
    """
    from src.services.cpsat_solver import CPSATSchedulerModel, CPSATConfig, BlockingReason
    from collections import defaultdict
    
    try:
        # Convert inputs
        tours = [tour_input_to_domain(t) for t in request.tours]
        drivers = [driver_input_to_domain(d) for d in request.drivers]
        week_start = parse_date(request.week_start)
        
        # Build model to get pre-solve analysis
        config = CPSATConfig(
            time_limit_seconds=min(request.time_limit_seconds, 30),
            seed=request.seed or 42
        )
        model = CPSATSchedulerModel(tours, drivers, config)
        
        # Build diagnostics
        diagnostics = []
        reason_summary = defaultdict(int)
        
        for tour in tours:
            report = model.pre_solve_report.tour_reports.get(tour.id) if model.pre_solve_report else None
            
            # Count candidates
            blocks_for_tour = model.tour_to_blocks.get(tour.id, [])
            candidate_blocks = len(blocks_for_tour)
            
            # Count feasible drivers
            feasible_driver_count = 0
            top_blockers: dict[str, int] = {}
            
            for block in blocks_for_tour:
                for driver in drivers:
                    ok, reason = model._check_assignment(block, driver)
                    if ok:
                        feasible_driver_count += 1
                    elif reason:
                        top_blockers[reason] = top_blockers.get(reason, 0) + 1
            
            # Determine flags
            has_any_blocks = candidate_blocks > 0
            has_any_feasible_driver = feasible_driver_count > 0
            is_feasible = report.is_feasible if report else has_any_feasible_driver
            
            # Determine reason code
            if not has_any_blocks:
                reason_code = BlockingReason.NO_BLOCK_GENERATED
            elif not has_any_feasible_driver:
                reason_code = max(top_blockers.keys(), key=lambda r: top_blockers[r]) if top_blockers else BlockingReason.DRIVER_UNAVAILABLE
            else:
                reason_code = "coverable"
            
            reason_summary[reason_code] += 1
            
            diagnostics.append({
                "tour_id": tour.id,
                "day": tour.day.value,
                "time": f"{tour.start_time.strftime('%H:%M')}-{tour.end_time.strftime('%H:%M')}",
                "is_feasible": is_feasible,
                "reason_code": reason_code,
                "candidate_blocks_total": candidate_blocks,
                "candidate_drivers_total": feasible_driver_count,
                "top_blockers": [{"code": k, "count": v} for k, v in sorted(top_blockers.items(), key=lambda x: -x[1])[:5]],
                "has_any_blocks": has_any_blocks,
                "has_any_feasible_driver": has_any_feasible_driver,
                "is_globally_conflicting": False  # Will be set after solve
            })
        
        return {
            "total_tours": len(tours),
            "coverable_tours": model.pre_solve_report.coverable_tours if model.pre_solve_report else 0,
            "infeasible_tours": model.pre_solve_report.infeasible_tours if model.pre_solve_report else 0,
            "reason_summary": dict(reason_summary),
            "diagnostics": diagnostics
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Diagnostics error: {str(e)}")
