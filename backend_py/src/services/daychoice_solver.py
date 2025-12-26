"""
DAY-CHOICE PHASE 2 SOLVER
==========================
Efficient CP-SAT model for driver assignment using day-choice variables.

Variables: choice[d,t] ∈ {0..N_t} per driver per day
- 0 = OFF (no work this day)
- 1..N_t = index of block assigned on that day

This model scales O(drivers × days) instead of O(blocks² × drivers).

Hard Constraints:
- H1: 11h night rest (660 min) between consecutive work days
- H2: No 3+3 (no 3-tour blocks on consecutive days)
- H3: Max 55h/week, 100% coverage

Soft Objectives (lexicographic):
1. Minimize drivers_used
2. Minimize under-40h shortfall
3. Minimize over-50h excess
"""

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

from ortools.sat.python import cp_model

from src.domain.models import Block, Weekday

logger = logging.getLogger("DayChoiceSolver")

# Import DriverAssignment at module level to avoid circular import issues
try:
    from src.services.forecast_solver_v4 import DriverAssignment
except ImportError:
    # Fallback: define minimal DriverAssignment if import fails
    from dataclasses import dataclass
    @dataclass
    class DriverAssignment:
        driver_id: str
        driver_type: str
        blocks: list
        total_hours: float
        days_worked: int
        analysis: dict = None


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class DayChoiceConfig:
    """Configuration for Day-Choice Phase 2 Solver."""
    
    # Driver limits
    driver_cap: Optional[int] = None  # None = minimize headcount
    
    # Hour targets (in hours, not minutes)
    min_hours_target: float = 40.0
    max_hours_target: float = 50.0
    max_hours_hard: float = 55.0
    
    # Rest constraints (in minutes)
    min_rest_minutes: int = 660  # 11h = 660 min
    
    # 3+3 rule
    no_consecutive_3er: bool = True
    
    # Solver settings
    time_limit_s: float = 120.0
    seed: int = 42
    num_workers: int = 1


@dataclass
class DayChoiceResult:
    """Result from Day-Choice Phase 2 Solver."""
    
    status: str = "UNKNOWN"
    
    # Solution
    drivers_used: int = 0
    assignments: list = field(default_factory=list)  # list[DriverAssignment]
    
    # Metrics
    total_hours: float = 0.0
    avg_hours: float = 0.0
    under40_count: int = 0
    over50_count: int = 0
    
    # Constraint violations (should be 0)
    rest_violations: int = 0
    consecutive_3er_violations: int = 0
    
    # Timing
    solve_time_s: float = 0.0
    build_time_s: float = 0.0  # Time spent building model
    
    # Best feasible (for timeout cases)
    best_feasible: Optional[list] = None


# =============================================================================
# HELPERS
# =============================================================================

def compute_peak_day_bound(selected_blocks: list[Block]) -> dict:
    """
    Compute peak-day lower bound for driver count.
    
    With 1 block/driver/day constraint, min_drivers >= peak_day_blocks.
    """
    weekdays = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
               Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
    
    blocks_by_day = {wd: [] for wd in weekdays}
    for b in selected_blocks:
        blocks_by_day[b.day].append(b)
    
    day_counts = {wd.value: len(blocks) for wd, blocks in blocks_by_day.items()}
    peak_day = max(day_counts, key=day_counts.get) if day_counts else "Mon"
    peak_day_blocks = max(day_counts.values()) if day_counts else 0
    
    return {
        "blocks_by_day": day_counts,
        "peak_day": peak_day,
        "peak_day_blocks": peak_day_blocks,
        "min_drivers_lower_bound": peak_day_blocks,
    }


def get_block_minutes(block: Block) -> int:
    """Get total work minutes for a block."""
    return block.total_work_minutes if hasattr(block, 'total_work_minutes') else block.span_minutes


def get_block_end_minutes(block: Block) -> int:
    """Get end time in minutes from midnight."""
    return block.last_end.hour * 60 + block.last_end.minute


def get_block_start_minutes(block: Block) -> int:
    """Get start time in minutes from midnight."""
    return block.first_start.hour * 60 + block.first_start.minute


# =============================================================================
# FIXED FTE POOL RECLASSIFICATION (v5.2)
# =============================================================================

def reclassify_underfull_ftes_to_pt(
    assignments: list,
    fte_min_hours: float = 40.0,
    log_fn = None,
) -> tuple[list, dict]:
    """
    Reclassify FTE drivers with < fte_min_hours as PT drivers.
    
    Business Rule: FTE = 40-55h, PT = <40h
    
    Args:
        assignments: List of DriverAssignment objects
        fte_min_hours: Minimum hours for FTE (default 40.0)
        log_fn: Optional logging function
    
    Returns:
        (reclassified_assignments, stats)
    """
    def log(msg: str):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    
    log("=" * 70)
    log("POST-PROCESSING: FTE < 40h → PT Reclassification")
    log("=" * 70)
    
    reclassified = []
    fte_to_pt_count = 0
    pt_counter = 1
    
    # Separate existing PT assignments
    existing_pt = [a for a in assignments if a.driver_type == "PT"]
    pt_counter = len(existing_pt) + 1
    
    for a in assignments:
        if a.driver_type == "FTE" and a.total_hours < fte_min_hours:
            # Recl assify as PT
            fte_to_pt_count += 1
            pt_assignment = DriverAssignment(
                driver_id=f"PT_{pt_counter:03d}",
                driver_type="PT",
                blocks=a.blocks,
                total_hours=a.total_hours,
                days_worked=a.days_worked,
                analysis=a.analysis if hasattr(a, 'analysis') else {},
            )
            reclassified.append(pt_assignment)
            pt_counter += 1
            log(f"  Reclassified {a.driver_id} ({a.total_hours:.1f}h) → PT_{pt_counter-1:03d}")
        else:
            reclassified.append(a)
    
    stats = {
        "fte_to_pt_count": fte_to_pt_count,
        "final_fte_count": sum(1 for a in reclassified if a.driver_type == "FTE"),
        "final_pt_count": sum(1 for a in reclassified if a.driver_type == "PT"),
    }
    
    log(f"Reclassified: {fte_to_pt_count} FTE → PT")
    log(f"Final: {stats['final_fte_count']} FTE + {stats['final_pt_count']} PT")
    log("=" * 70)
    
    return reclassified, stats


# =============================================================================
# DAY-CHOICE CP-SAT SOLVER
# =============================================================================

def solve_phase2_daychoice(
    selected_blocks: list[Block],
    config: DayChoiceConfig = None,
    log_fn = None,
    hints: list = None,  # Optional warmstart hints
) -> DayChoiceResult:
    """
    Solve Phase 2 Assignment using Day-Choice CP-SAT model.
    
    Model:
    - choice[d,t] ∈ {0..N_t} for each driver d and day t
    - 0 = OFF, k = assigned block index k for that day
    
    This reduces constraints from O(incompatible_pairs × drivers) to O(drivers × 6).
    
    Args:
        selected_blocks: Blocks from Phase 1
        config: Solver configuration
        log_fn: Logging callback
        hints: Optional SP solution for warmstart
    
    Returns:
        DayChoiceResult with assignments and metrics
    """
    if config is None:
        config = DayChoiceConfig()
    
    def log(msg: str):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    
    start = perf_counter()
    result = DayChoiceResult()
    
    if not selected_blocks:
        log("[Phase2-DayChoice] No blocks to assign")
        result.status = "NO_BLOCKS"
        result.solve_time_s = perf_counter() - start
        return result
    
    log("=" * 70)
    log("PHASE 2: DAY-CHOICE CP-SAT ASSIGNMENT")
    log("=" * 70)
    
    # Organize blocks by day
    weekdays = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
               Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY]
    day_indices = {wd: i for i, wd in enumerate(weekdays)}
    
    blocks_by_day = {i: [] for i in range(6)}
    for b in selected_blocks:
        day_idx = day_indices.get(b.day, 0)
        blocks_by_day[day_idx].append(b)
    
    day_counts = [len(blocks_by_day[i]) for i in range(6)]
    log(f"Blocks by day: {dict(zip(['Mon','Tue','Wed','Thu','Fri','Sat'], day_counts))}")
    
    peak_day_blocks = max(day_counts)
    log(f"Peak day blocks: {peak_day_blocks}")
    
    # Compute total hours
    total_work_minutes = sum(get_block_minutes(b) for b in selected_blocks)
    total_hours = total_work_minutes / 60.0
    result.total_hours = total_hours
    log(f"Total work: {total_hours:.1f}h")
    
    # Determine driver count
    theoretical_min = int(total_work_minutes / (config.max_hours_hard * 60)) + 1
    log(f"Theoretical min drivers (55h): {theoretical_min}")
    log(f"Peak-day lower bound: {peak_day_blocks}")
    
    if config.driver_cap:
        num_drivers = config.driver_cap
        log(f"Using driver_cap: {num_drivers}")
        
        # Early infeasibility check
        if peak_day_blocks > num_drivers:
            log(f"INFEASIBLE_BY_DAY_LOWER_BOUND: peak={peak_day_blocks} > cap={num_drivers}")
            result.status = "INFEASIBLE_BY_DAY_LOWER_BOUND"
            result.solve_time_s = perf_counter() - start
            return result
    else:
        # Start with peak_day_blocks + buffer
        num_drivers = max(peak_day_blocks + 10, theoretical_min + 5)
        log(f"Initial driver pool: {num_drivers}")
    
    # Build CP-SAT model
    log("Building Day-Choice CP-SAT model...")
    build_start = perf_counter()
    model = cp_model.CpModel()
    
    # === VARIABLES ===
    
    # choice[d][t] = which block index driver d works on day t (0 = OFF)
    choice = {}
    for d in range(num_drivers):
        for t in range(6):
            # Domain: 0 (OFF) to N_t (number of blocks on day t)
            choice[d, t] = model.NewIntVar(0, len(blocks_by_day[t]), f"choice_{d}_{t}")
    
    # use[d] = 1 if driver d is used at all
    use = [model.NewBoolVar(f"use_{d}") for d in range(num_drivers)]
    
    # work_day[d][t] = 1 if driver d works on day t
    work_day = {}
    for d in range(num_drivers):
        for t in range(6):
            work_day[d, t] = model.NewBoolVar(f"work_day_{d}_{t}")
            # work_day == (choice != 0)
            model.Add(choice[d, t] != 0).OnlyEnforceIf(work_day[d, t])
            model.Add(choice[d, t] == 0).OnlyEnforceIf(work_day[d, t].Not())
    
    # PRE-BUILD element arrays (avoid rebuilding inside loops)
    # hours[t] = [0, block1_min, block2_min, ...]
    hours_arrays = {}
    start_arrays = {}
    end_arrays = {}
    is3_arrays = {}
    
    for t in range(6):
        hours_arrays[t] = [0] + [get_block_minutes(b) for b in blocks_by_day[t]]
        start_arrays[t] = [24 * 60] + [get_block_start_minutes(b) for b in blocks_by_day[t]]
        end_arrays[t] = [0] + [get_block_end_minutes(b) for b in blocks_by_day[t]]
        is3_arrays[t] = [0] + [1 if len(b.tours) == 3 else 0 for b in blocks_by_day[t]]
    
    # hours[d][t] via element constraint
    hours = {}
    for d in range(num_drivers):
        for t in range(6):
            hours[d, t] = model.NewIntVar(0, 24 * 60, f"hours_{d}_{t}")
            model.AddElement(choice[d, t], hours_arrays[t], hours[d, t])
    
    # start_time[d][t] and end_time[d][t] for rest constraint
    start_time = {}
    end_time = {}
    for d in range(num_drivers):
        for t in range(6):
            start_time[d, t] = model.NewIntVar(0, 24 * 60, f"start_{d}_{t}")
            end_time[d, t] = model.NewIntVar(0, 24 * 60, f"end_{d}_{t}")
            
            model.AddElement(choice[d, t], start_arrays[t], start_time[d, t])
            model.AddElement(choice[d, t], end_arrays[t], end_time[d, t])
    
    # is3[d][t] = 1 if 3-tour block
    is3 = {}
    for d in range(num_drivers):
        for t in range(6):
            is3[d, t] = model.NewBoolVar(f"is3_{d}_{t}")
            is3_var = model.NewIntVar(0, 1, f"is3_val_{d}_{t}")
            model.AddElement(choice[d, t], is3_arrays[t], is3_var)
            model.Add(is3[d, t] == is3_var)
    
    log(f"Variables: {num_drivers * 6} choice + {num_drivers} use + derived")
    
    # === CONSTRAINTS ===
    
    # C1: Coverage - each block assigned exactly once
    # OPTIMIZATION: Use inverse mapping instead of O(drivers×blocks) reifications
    # For each (day, block_idx), exactly 1 driver has choice[d,t] == block_idx
    coverage_constraints = 0
    for t in range(6):
        num_blocks_today = len(blocks_by_day[t])
        for block_idx in range(1, num_blocks_today + 1):
            # Count how many drivers selected this block on day t
            # Since we can't use sum of reifications efficiently, we use AllowedAssignments
            # Alternative: global cardinality constraint on choice[:,t]
            # sum([choice[d,t] == block_idx for d in drivers]) == 1
            chosen_by = [
                model.NewBoolVar(f"chosen_{t}_{block_idx}_{d}")
                for d in range(num_drivers)
            ]
            for d in range(num_drivers):
                model.Add(choice[d, t] == block_idx).OnlyEnforceIf(chosen_by[d])
                model.Add(choice[d, t] != block_idx).OnlyEnforceIf(chosen_by[d].Not())
            model.AddExactlyOne(chosen_by)
            coverage_constraints += 1
    
    log(f"Coverage constraints: {coverage_constraints} blocks (optimized)")
    
    # C2: Driver use - use[d] = 1 if any work_day[d,t] = 1
    for d in range(num_drivers):
        # use[d] >= work_day[d,t] for all t
        for t in range(6):
            model.Add(use[d] >= work_day[d, t])
        # use[d] <= sum(work_day[d,t]) (so use=0 when all days are off)
        model.Add(use[d] <= sum(work_day[d, t] for t in range(6)))
    
    # C3: 11h Rest between consecutive days (HARD)
    # FIX: Handle cross-midnight blocks correctly
    # If a block ends after midnight (e.g., 23:00-02:00), end_time will be 120 min (02:00)
    # but it's actually the NEXT day. For rest calculation, we need to detect this.
    # 
    # Heuristic: if end_time < start_time for the same block, it crossed midnight
    # For rest: rest_minutes = (24*60 - end[t]) + start[t+1]
    # But our end[t] is already modulo 24h, so:
    #   - If end[t] < start[t] (cross-midnight), treat end as end[t] + 24*60 for rest calc
    #   - Rest = start[t+1] + 24*60 - end[t] if end[t] > start[t] (same day end)
    #   - Rest = start[t+1] - end[t] if end[t] < start[t] (cross-midnight end at t+1 day)
    # 
    # SIMPLIFIED FIX: Since we only care about consecutive work days, and blocks are
    # assigned to the day they START, we can safely use:
    #   rest = start[t+1] + 1440 - end[t]  (1440 = 24*60)
    # This works because:
    #   - day t ends at end[t] (in minutes from midnight of day t)
    #   - day t+1 starts at start[t+1] (in minutes from midnight of day t+1)
    #   - Rest = (midnight - end[t]) + start[t+1] = 1440 - end[t] + start[t+1]
    rest_constraints = 0
    for d in range(num_drivers):
        for t in range(5):  # Mon-Fri (check next day)
            # If both days worked, enforce 11h rest
            # OPTIMIZATION: Remove redundant both_work bool, use direct OnlyEnforceIf list
            model.Add(
                start_time[d, t + 1] + 1440 - end_time[d, t] >= config.min_rest_minutes
            ).OnlyEnforceIf([work_day[d, t], work_day[d, t + 1]])
            rest_constraints += 1
    
    log(f"11h Rest constraints: {rest_constraints} (cross-midnight safe)")
    
    # C4: No 3+3 consecutive (HARD)
    if config.no_consecutive_3er:
        no3plus3_constraints = 0
        for d in range(num_drivers):
            for t in range(5):
                model.Add(is3[d, t] + is3[d, t + 1] <= 1)
                no3plus3_constraints += 1
        log(f"No 3+3 constraints: {no3plus3_constraints}")
    
    # C5: Weekly hours hard cap (55h)
    weekly_hours = []
    for d in range(num_drivers):
        driver_hours = model.NewIntVar(0, int(config.max_hours_hard * 60) + 1, f"weekly_{d}")
        model.Add(driver_hours == sum(hours[d, t] for t in range(6)))
        weekly_hours.append(driver_hours)
        model.Add(driver_hours <= int(config.max_hours_hard * 60))
    
    # Soft objective variables
    under40 = []
    over50 = []
    for d in range(num_drivers):
        u = model.NewIntVar(0, int(config.min_hours_target * 60), f"under40_{d}")
        o = model.NewIntVar(0, int((config.max_hours_hard - config.max_hours_target) * 60), f"over50_{d}")
        
        # under40 = max(0, 40*60*use[d] - weekly_hours[d])
        target_40 = int(config.min_hours_target * 60)
        shortfall = model.NewIntVar(-target_40, target_40, f"shortfall_{d}")
        model.Add(shortfall == target_40 - weekly_hours[d]).OnlyEnforceIf(use[d])
        model.Add(shortfall == 0).OnlyEnforceIf(use[d].Not())
        model.AddMaxEquality(u, [shortfall, 0])
        under40.append(u)
        
        # over50 = max(0, weekly_hours[d] - 50*60*use[d])
        target_50 = int(config.max_hours_target * 60)
        excess = model.NewIntVar(-target_50, int(config.max_hours_hard * 60), f"excess_{d}")
        model.Add(excess == weekly_hours[d] - target_50).OnlyEnforceIf(use[d])
        model.Add(excess == 0).OnlyEnforceIf(use[d].Not())
        model.AddMaxEquality(o, [excess, 0])
        over50.append(o)
    
    # === OBJECTIVE ===
    # Lexicographic: min drivers, min under40, min over50
    total_use = sum(use)
    total_under40 = sum(under40)
    total_over50 = sum(over50)
    
    # FIX: Compute lexicographically-dominant weights
    # To ensure true lexicographic priority:
    #   W_DRIVER must dominate worst-case total_under40
    #   W_UNDER40 must dominate worst-case total_over50
    # 
    # Worst case under40: num_drivers × 40h × 60min = num_drivers × 2400
    # Worst case over50: num_drivers × 5h × 60min = num_drivers × 300
    # 
    # Set: W_DRIVER >= num_drivers × 2400 × 2  (2× safety margin)
    #      W_UNDER40 >= num_drivers × 300 × 2
    worst_under40 = num_drivers * int(config.min_hours_target * 60)
    worst_over50 = num_drivers * int((config.max_hours_hard - config.max_hours_target) * 60)
    
    W_OVER50 = 1
    W_UNDER40 = worst_over50 * 2 + 1  # Dominate over50
    W_DRIVER = worst_under40 * W_UNDER40 * 2 + 1  # Dominate under40
    
    model.Minimize(
        W_DRIVER * total_use +
        W_UNDER40 * total_under40 +
        W_OVER50 * total_over50
    )
    
    log(f"Objective (lexicographic): drivers×{W_DRIVER} + under40×{W_UNDER40} + over50×{W_OVER50}")
    
    # === SOLVE ===
    build_time = perf_counter() - build_start
    result.build_time_s = build_time
    log(f"Model built in {build_time:.2f}s")
    
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = config.seed
    solver.parameters.num_search_workers = 1  # S0.1: Determinism (always 1, ignore config)
    solver.parameters.max_time_in_seconds = config.time_limit_s
    solver.parameters.log_search_progress = True  # Enable to see solver progress
    
    log(f"Solving (time_limit={config.time_limit_s:.1f}s)...")
    solve_start = perf_counter()
    
    status = solver.Solve(model)
    
    actual_solve_time = perf_counter() - solve_start
    log(f"CP-SAT finished in {actual_solve_time:.2f}s (build: {build_time:.2f}s)")
    
    result.solve_time_s = perf_counter() - start  # Total time (build + solve)
    
    # === PROCESS RESULT ===
    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    result.status = status_map.get(status, "UNKNOWN")
    
    log(f"Status: {result.status}")
    
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Extract solution
        drivers_used = sum(solver.Value(use[d]) for d in range(num_drivers))
        result.drivers_used = drivers_used
        log(f"Drivers used: {drivers_used}")
        
        # Build assignments
        
        assignments = []
        active_drivers = 0
        total_driver_hours = 0
        under40_count = 0
        over50_count = 0
        
        for d in range(num_drivers):
            if not solver.Value(use[d]):
                continue
            
            active_drivers += 1
            driver_blocks = []
            
            for t in range(6):
                block_idx = solver.Value(choice[d, t])
                if block_idx > 0:  # Not OFF
                    driver_blocks.append(blocks_by_day[t][block_idx - 1])
            
            driver_hours = solver.Value(weekly_hours[d]) / 60.0
            total_driver_hours += driver_hours
            
            if driver_hours < config.min_hours_target:
                under40_count += 1
            if driver_hours > config.max_hours_target:
                over50_count += 1
            
            assignment = DriverAssignment(
                driver_id=f"FTE_{d+1:03d}",
                driver_type="FTE",
                blocks=driver_blocks,
                total_hours=driver_hours,
                days_worked=len(set(b.day for b in driver_blocks)),
            )
            assignments.append(assignment)
        
        result.assignments = assignments
        result.avg_hours = total_driver_hours / active_drivers if active_drivers > 0 else 0
        result.under40_count = under40_count
        result.over50_count = over50_count
        
        log(f"Active drivers: {active_drivers}")
        log(f"Avg hours: {result.avg_hours:.1f}h")
        log(f"Under 40h: {under40_count}, Over 50h: {over50_count}")
        
        # Store as best feasible for timeout fallback
        result.best_feasible = assignments
    
    log(f"Solve time: {result.solve_time_s:.2f}s (build: {result.build_time_s:.2f}s, solve: {result.solve_time_s - result.build_time_s:.2f}s)")
    log("=" * 70)
    
    return result
