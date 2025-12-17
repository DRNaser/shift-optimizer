"""
Global CP-SAT FTE-Only Assignment (V3 - NO REST CONSTRAINTS)
====================================================================

V3: Removed all rest constraints to test if base model is feasible.
If this works, we add rest back incrementally.
"""

import math
import logging
from dataclasses import dataclass, field
from ortools.sat.python import cp_model

logger = logging.getLogger("GlobalCPSAT")

DAY_MINUTES = 24 * 60  # 1440


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class GlobalAssignConfig:
    """Configuration for global CP-SAT assignment."""
    min_hours_per_driver: float = 42.0
    max_hours_per_driver: float = 53.0
    
    max_tours_per_day: int = 3
    
    # Rest constraints (in minutes)
    min_rest_minutes: int = 660       # 11h (always)
    min_rest_after_heavy: int = 840   # 14h (after 3-tour day)
    max_tours_after_heavy: int = 2    # Max 2 tours day after heavy
    
    # Solve time
    time_limit_feasible: float = 300.0   # Phase A: find feasible
    time_limit_optimize: float = 1800.0  # Phase B: optimize
    
    seed: int = 42
    num_workers: int = 1


# =============================================================================
# BLOCK INFO FOR ASSIGNMENT
# =============================================================================

@dataclass
class BlockAssignInfo:
    """Block information for CP-SAT assignment."""
    block_id: str
    day_idx: int          # 0=Mon, 1=Tue, ..., 6=Sun
    start_min: int        # Minutes from midnight
    end_min: int          # Minutes from midnight
    span_min: int         # end - start (for overlap) - MUST BE SPAN!
    work_min: int         # Actual work time (for hours calculation)
    tour_count: int       # Number of tours in block


# =============================================================================
# RESULT
# =============================================================================

@dataclass
class GlobalAssignResult:
    """Result from global CP-SAT assignment."""
    status: str
    assignments: dict     # block_id -> driver_index
    drivers_used: int
    driver_hours: list
    solve_time_a: float
    solve_time_b: float


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def time_to_minutes(t) -> int:
    if hasattr(t, 'hour'):
        return t.hour * 60 + t.minute
    return 0

def get_day_index(day) -> int:
    day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    if hasattr(day, 'value'):
        return day_map.get(day.value, 0)
    return day_map.get(str(day), 0)


def blocks_to_assign_info(blocks: list) -> list[BlockAssignInfo]:
    """Convert Block objects to BlockAssignInfo list."""
    result = []
    for block in blocks:
        day_idx = get_day_index(block.day)
        start_min = time_to_minutes(block.first_start)
        end_min = time_to_minutes(block.last_end)
        span = end_min - start_min  # SPAN, not duration!
        work = int(block.total_work_hours * 60)
        tours = len(block.tours) if hasattr(block, 'tours') else 1
        
        result.append(BlockAssignInfo(
            block_id=block.id,
            day_idx=day_idx,
            start_min=start_min,
            end_min=end_min,
            span_min=span,
            work_min=work,
            tour_count=tours,
        ))
    return result


# =============================================================================
# MAIN SOLVER (V2 - Day-Level Rest Constraints)
# =============================================================================

def solve_global_cpsat(
    blocks: list[BlockAssignInfo],
    config: GlobalAssignConfig = None,
    log_fn = None,
) -> GlobalAssignResult:
    """
    Solve global FTE-only assignment using CP-SAT.
    
    V2: Uses day-level rest constraints (O(K×Days)) instead of 
    pair-level (O(Pairs×K)) for massive speedup.
    """
    if config is None:
        config = GlobalAssignConfig()
    
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("GLOBAL CP-SAT FTE-ONLY ASSIGNMENT (V2 - Day-Level)")
    log_fn("=" * 60)
    
    # Compute K = max possible drivers
    total_work_hours = sum(b.work_min for b in blocks) / 60.0
    K = math.floor(total_work_hours / config.min_hours_per_driver)
    
    log_fn(f"Total work: {total_work_hours:.1f}h")
    
    # CAP K at 135 for performance (symmetry breaking helps)
    K = min(135, math.floor(total_work_hours / config.min_hours_per_driver))
    
    log_fn(f"Driver slots K = {K} (capped at 135)")
    log_fn(f"Blocks: {len(blocks)}")
    
    if K < 1:
        return GlobalAssignResult("INFEASIBLE", {}, 0, [], 0, 0)
    
    # Group blocks by day
    blocks_by_day = {d: [] for d in range(7)}
    for i, b in enumerate(blocks):
        blocks_by_day[b.day_idx].append(i)
    
    B = len(blocks)
    
    # =========================================================================
    # BUILD MODEL
    # =========================================================================
    model = cp_model.CpModel()
    
    log_fn("Creating variables...")
    
    # ----- Core decision variables -----
    # x[b, k] = block b assigned to driver k
    x = {}
    for b_idx in range(B):
        for k in range(K):
            x[b_idx, k] = model.NewBoolVar(f"x_{b_idx}_{k}")
    
    # used[k] = driver k is used
    used = [model.NewBoolVar(f"used_{k}") for k in range(K)]
    
    # week_minutes[k] = total work minutes for driver k
    max_week_min = int(config.max_hours_per_driver * 60)
    week_minutes = [model.NewIntVar(0, max_week_min, f"week_{k}") for k in range(K)]
    
    # ----- Per-driver-day variables (V2 optimization) -----
    # work[d, k] = driver k works on day d (has any block)
    work = {}
    for d in range(7):
        for k in range(K):
            work[d, k] = model.NewBoolVar(f"work_{d}_{k}")
    
    # tours_day[d, k] = total tours on day d for driver k
    tours_day = {}
    for d in range(7):
        for k in range(K):
            tours_day[d, k] = model.NewIntVar(0, config.max_tours_per_day, f"tours_{d}_{k}")
    
    # heavy[d, k] = day d is heavy (exactly 3 tours) for driver k
    heavy = {}
    for d in range(7):
        for k in range(K):
            heavy[d, k] = model.NewBoolVar(f"heavy_{d}_{k}")
    
    # NOTE: first_start and last_end REMOVED in V3 for testing
    # Will add back if base model is feasible
    
    log_fn(f"Variables: {B*K} x[b,k] + {K} used + {7*K*5} day-level")
    
    # =========================================================================
    # CONSTRAINTS
    # =========================================================================
    log_fn("Adding constraints...")
    
    # 1. Each block assigned exactly once
    for b_idx in range(B):
        model.Add(sum(x[b_idx, k] for k in range(K)) == 1)
    
    # 2. used[k] link
    M = B
    for k in range(K):
        block_sum = sum(x[b_idx, k] for b_idx in range(B))
        model.Add(block_sum <= M * used[k])
        model.Add(block_sum >= used[k])
    
    # 3. week_minutes[k] = sum of work minutes
    for k in range(K):
        model.Add(week_minutes[k] == sum(blocks[b_idx].work_min * x[b_idx, k] for b_idx in range(B)))
    
    # 4. Hours constraints: 42h <= week_minutes <= 53h (only if used)
    min_minutes = int(config.min_hours_per_driver * 60)
    for k in range(K):
        model.Add(week_minutes[k] >= min_minutes * used[k])
        model.Add(week_minutes[k] <= max_week_min * used[k])
    
    # 5. NoOverlap per (driver, day) - CRITICAL: use span!
    log_fn("Adding NoOverlap intervals...")
    for k in range(K):
        for d in range(7):
            if not blocks_by_day[d]:
                continue
            
            intervals = []
            for b_idx in blocks_by_day[d]:
                b = blocks[b_idx]
                interval = model.NewOptionalFixedSizeIntervalVar(
                    start=b.start_min,
                    size=b.span_min,  # SPAN = end - start
                    is_present=x[b_idx, k],
                    name=f"iv_{b_idx}_{k}"
                )
                intervals.append(interval)
            
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)
    
    # 6. tours_day[d,k] = sum of tour counts
    for d in range(7):
        for k in range(K):
            if blocks_by_day[d]:
                model.Add(tours_day[d, k] == sum(
                    blocks[b_idx].tour_count * x[b_idx, k] 
                    for b_idx in blocks_by_day[d]
                ))
            else:
                model.Add(tours_day[d, k] == 0)
    
    # 7. work[d,k] = 1 iff any block assigned on day d
    for d in range(7):
        for k in range(K):
            if blocks_by_day[d]:
                day_blocks_sum = sum(x[b_idx, k] for b_idx in blocks_by_day[d])
                model.Add(day_blocks_sum >= 1).OnlyEnforceIf(work[d, k])
                model.Add(day_blocks_sum == 0).OnlyEnforceIf(work[d, k].Not())
            else:
                model.Add(work[d, k] == 0)
    
    # 8. Heavy day logic: heavy = 1 iff tours == 3
    for d in range(7):
        for k in range(K):
            # tours >= 3 * heavy
            model.Add(tours_day[d, k] >= 3 * heavy[d, k])
            # tours <= 2 + heavy
            model.Add(tours_day[d, k] <= 2 + heavy[d, k])
    
    # 9. Next day tours cap: tours[d+1] <= 3 - heavy[d]
    for d in range(6):  # Mon-Sat
        for k in range(K):
            model.Add(tours_day[d + 1, k] <= 3 - heavy[d, k])
    
    # V3: REST CONSTRAINTS COMPLETELY REMOVED FOR TESTING
    log_fn("V3: NO rest constraints (testing base feasibility)")
    
    # 12. Symmetry breaking
    log_fn("Adding symmetry breaking...")
    for k in range(K - 1):
        model.Add(used[k] >= used[k + 1])
        model.Add(week_minutes[k] >= week_minutes[k + 1])
    
    # =========================================================================
    # OBJECTIVE: Minimize used drivers
    # =========================================================================
    model.Minimize(sum(used))
    
    # =========================================================================
    # PHASE A: Find feasible solution
    # =========================================================================
    log_fn(f"\nPHASE A: Finding feasible solution (limit={config.time_limit_feasible}s)...")
    
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = config.seed
    solver.parameters.num_workers = config.num_workers
    solver.parameters.max_time_in_seconds = config.time_limit_feasible
    solver.parameters.stop_after_first_solution = True
    
    import time
    start_a = time.time()
    status_a = solver.Solve(model)
    solve_time_a = time.time() - start_a
    
    log_fn(f"Phase A: status={solver.StatusName(status_a)}, time={solve_time_a:.1f}s")
    
    if status_a not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log_fn("ERROR: No feasible solution found!")
        return GlobalAssignResult("INFEASIBLE", {}, 0, [], solve_time_a, 0)
    
    feasible_drivers = sum(solver.Value(used[k]) for k in range(K))
    log_fn(f"Feasible solution: {feasible_drivers} drivers")
    
    # =========================================================================
    # PHASE B: Optimize (minimize drivers)
    # =========================================================================
    log_fn(f"\nPHASE B: Optimizing (limit={config.time_limit_optimize}s)...")
    
    solver2 = cp_model.CpSolver()
    solver2.parameters.random_seed = config.seed
    solver2.parameters.num_workers = config.num_workers
    solver2.parameters.max_time_in_seconds = config.time_limit_optimize
    solver2.parameters.stop_after_first_solution = False
    
    # Use Phase A solution as hint
    for b_idx in range(B):
        for k in range(K):
            model.AddHint(x[b_idx, k], solver.Value(x[b_idx, k]))
    for k in range(K):
        model.AddHint(used[k], solver.Value(used[k]))
    
    start_b = time.time()
    status_b = solver2.Solve(model)
    solve_time_b = time.time() - start_b
    
    log_fn(f"Phase B: status={solver2.StatusName(status_b)}, time={solve_time_b:.1f}s")
    
    # Use best solver result
    final_solver = solver2 if status_b in (cp_model.OPTIMAL, cp_model.FEASIBLE) else solver
    
    # =========================================================================
    # EXTRACT SOLUTION
    # =========================================================================
    assignments = {}
    driver_hours = []
    drivers_used = 0
    
    for k in range(K):
        if final_solver.Value(used[k]):
            drivers_used += 1
            hours = final_solver.Value(week_minutes[k]) / 60.0
            driver_hours.append(hours)
            
            for b_idx in range(B):
                if final_solver.Value(x[b_idx, k]):
                    assignments[blocks[b_idx].block_id] = k
    
    log_fn("=" * 60)
    log_fn("GLOBAL CP-SAT V2 COMPLETE")
    log_fn("=" * 60)
    log_fn(f"Drivers used: {drivers_used}")
    if driver_hours:
        log_fn(f"Hours range: {min(driver_hours):.1f}h - {max(driver_hours):.1f}h")
    log_fn(f"Total time: {solve_time_a + solve_time_b:.1f}s")
    
    return GlobalAssignResult(
        status="OPTIMAL" if status_b == cp_model.OPTIMAL else "FEASIBLE",
        assignments=assignments,
        drivers_used=drivers_used,
        driver_hours=driver_hours,
        solve_time_a=solve_time_a,
        solve_time_b=solve_time_b,
    )
