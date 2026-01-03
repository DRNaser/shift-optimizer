"""
Feasibility Pipeline for FTE-Only Assignment
=============================================

This module implements a proper feasibility pipeline based on:
1. Peak Concurrency Check (LB_concurrency)
2. Fixed-K Greedy Builder (warm start)
3. Global CP-SAT with Fixed N + Hints

Key insight: 118-148 is only an HOURS bound. The real constraint is:
LB_concurrency = max blocks running simultaneously.
If peak > K, the problem is infeasible regardless of hours.
"""

import math
import logging
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger("FeasibilityPipeline")


# =============================================================================
# STEP 0: PEAK CONCURRENCY CALCULATION
# =============================================================================

def compute_peak_concurrency(blocks: list, log_fn=None) -> dict:
    """
    Compute peak concurrency (LB_concurrency) using sweep-line algorithm.
    
    This is the MINIMUM number of drivers required regardless of hour constraints.
    If peak > K_target, the 42-53h goal is IMPOSSIBLE with these blocks.
    
    Returns:
        {
            "daily_peaks": {day: peak_count},
            "overall_peak": max peak across all days,
            "peak_day": which day has the highest peak,
            "peak_time": time of day when peak occurs,
        }
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("STEP 0: PEAK CONCURRENCY CHECK")
    log_fn("=" * 60)
    
    # Group blocks by day
    blocks_by_day = defaultdict(list)
    for b in blocks:
        day_idx = get_day_idx(b)
        start = get_start_min(b)
        end = get_end_min(b)
        blocks_by_day[day_idx].append((start, end))
    
    daily_peaks = {}
    peak_times = {}
    
    for day in range(7):
        if day not in blocks_by_day:
            daily_peaks[day] = 0
            peak_times[day] = 0
            continue
        
        # Sweep-line algorithm: (time, +1 for start, -1 for end)
        events = []
        for start, end in blocks_by_day[day]:
            events.append((start, +1))  # Block starts
            events.append((end, -1))    # Block ends
        
        # Sort by time, then by type (starts before ends at same time)
        events.sort(key=lambda x: (x[0], -x[1]))
        
        running = 0
        peak = 0
        peak_time = 0
        
        for time, delta in events:
            running += delta
            if running > peak:
                peak = running
                peak_time = time
        
        daily_peaks[day] = peak
        peak_times[day] = peak_time
    
    overall_peak = max(daily_peaks.values())
    peak_day = max(daily_peaks, key=daily_peaks.get)
    
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    log_fn(f"Daily peaks:")
    for day in range(7):
        if daily_peaks[day] > 0:
            time_str = f"{peak_times[day]//60:02d}:{peak_times[day]%60:02d}"
            log_fn(f"  {day_names[day]}: {daily_peaks[day]} blocks at {time_str}")
    
    log_fn(f"\nOVERALL PEAK: {overall_peak} (on {day_names[peak_day]})")
    log_fn(f"This is the MINIMUM drivers required (LB_concurrency)")
    
    return {
        "daily_peaks": daily_peaks,
        "overall_peak": overall_peak,
        "peak_day": peak_day,
        "peak_time": peak_times[peak_day],
    }


# =============================================================================
# STEP 1: FIXED-K GREEDY BUILDER
# =============================================================================

@dataclass
class DriverSlot:
    """A driver slot for greedy assignment."""
    id: int
    blocks: list = field(default_factory=list)
    day_intervals: dict = field(default_factory=dict)  # day -> [(start, end)]
    total_work_minutes: int = 0


def build_fixed_k_greedy(blocks: list, log_fn=None) -> dict:
    """
    Build a feasible assignment using greedy "first feasible driver" approach.
    
    This provides:
    - The minimum N drivers needed for feasibility
    - A feasible solution as hints for CP-SAT
    
    Returns:
        {
            "n_drivers": number of drivers used,
            "assignments": {block_id: driver_idx},
            "driver_hours": [hours per driver],
            "drivers": list of DriverSlot objects,
        }
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("STEP 1: FIXED-K GREEDY BUILDER")
    log_fn("=" * 60)
    
    # Sort blocks by (day, start_time) for deterministic greedy
    sorted_blocks = sorted(blocks, key=lambda b: (get_day_idx(b), get_start_min(b)))
    
    drivers = []  # List of DriverSlot
    assignments = {}  # block_id -> driver_idx
    
    for block in sorted_blocks:
        day = get_day_idx(block)
        start = get_start_min(block)
        end = get_end_min(block)
        work_min = get_work_min(block)
        block_id = get_block_id(block)
        
        # Try to assign to existing driver (first feasible)
        assigned = False
        for driver in drivers:
            if can_assign(driver, day, start, end):
                assign_block(driver, day, start, end, work_min, block)
                assignments[block_id] = driver.id
                assigned = True
                break
        
        # If no driver can take it, create new driver
        if not assigned:
            new_driver = DriverSlot(id=len(drivers))
            assign_block(new_driver, day, start, end, work_min, block)
            drivers.append(new_driver)
            assignments[block_id] = new_driver.id
    
    n_drivers = len(drivers)
    driver_hours = [d.total_work_minutes / 60.0 for d in drivers]
    
    log_fn(f"Greedy assignment complete:")
    log_fn(f"  Blocks assigned: {len(assignments)}")
    log_fn(f"  Drivers used: {n_drivers}")
    if driver_hours:
        log_fn(f"  Hours range: {min(driver_hours):.1f}h - {max(driver_hours):.1f}h")
        log_fn(f"  Hours avg: {sum(driver_hours)/len(driver_hours):.1f}h")
    
    # Count how many under 42h
    under_42 = sum(1 for h in driver_hours if h < 42.0)
    log_fn(f"  Under 42h: {under_42} drivers")
    
    return {
        "n_drivers": n_drivers,
        "assignments": assignments,
        "driver_hours": driver_hours,
        "drivers": drivers,
    }


def can_assign(driver: DriverSlot, day: int, start: int, end: int) -> bool:
    """Check if block can be assigned to driver (no overlap on day)."""
    if day not in driver.day_intervals:
        return True
    
    for (existing_start, existing_end) in driver.day_intervals[day]:
        # Check overlap: NOT (end <= existing_start OR start >= existing_end)
        if not (end <= existing_start or start >= existing_end):
            return False  # Overlap!
    
    return True


def assign_block(driver: DriverSlot, day: int, start: int, end: int, work_min: int, block):
    """Assign block to driver."""
    if day not in driver.day_intervals:
        driver.day_intervals[day] = []
    driver.day_intervals[day].append((start, end))
    driver.blocks.append(block)
    driver.total_work_minutes += work_min


# =============================================================================
# HELPER FUNCTIONS (work with both Block and BlockAssignInfo)
# =============================================================================

def get_day_idx(block) -> int:
    """Get day index (0=Mon..6=Sun) from block."""
    if hasattr(block, 'day_idx'):
        return block.day_idx
    if hasattr(block, 'day'):
        day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
        if hasattr(block.day, 'value'):
            return day_map.get(block.day.value, 0)
        return day_map.get(str(block.day), 0)
    return 0


def get_start_min(block) -> int:
    """Get start time in minutes from midnight."""
    if hasattr(block, 'start_min'):
        return block.start_min
    if hasattr(block, 'first_start'):
        t = block.first_start
        if hasattr(t, 'hour'):
            return t.hour * 60 + t.minute
    return 0


def get_end_min(block) -> int:
    """Get end time in minutes from midnight."""
    if hasattr(block, 'end_min'):
        return block.end_min
    if hasattr(block, 'last_end'):
        t = block.last_end
        if hasattr(t, 'hour'):
            return t.hour * 60 + t.minute
    return 0


def get_work_min(block) -> int:
    """Get work time in minutes."""
    if hasattr(block, 'work_min'):
        return block.work_min
    if hasattr(block, 'total_work_hours'):
        return int(block.total_work_hours * 60)
    return 0


def get_block_id(block) -> str:
    """Get block ID."""
    if hasattr(block, 'block_id'):
        return block.block_id
    if hasattr(block, 'id'):
        return block.id
    return str(id(block))


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_feasibility_pipeline(blocks: list, k_target: int = 148, log_fn=None) -> dict:
    """
    Run the full feasibility pipeline.
    
    Steps:
    0. Check peak concurrency
    1. Build Fixed-K greedy solution
    2. (Future) CP-SAT feasibility check
    
    Returns pipeline results.
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 70)
    log_fn("FEASIBILITY PIPELINE")
    log_fn("=" * 70)
    log_fn(f"Blocks: {len(blocks)}")
    log_fn(f"Target K: {k_target}")
    
    total_hours = sum(get_work_min(b) / 60.0 for b in blocks)
    log_fn(f"Total work: {total_hours:.1f}h")
    log_fn(f"Hours-based range: {int(total_hours/53)}-{int(total_hours/42)} drivers")
    
    # Step 0: Peak concurrency
    peak_result = compute_peak_concurrency(blocks, log_fn)
    peak = peak_result["overall_peak"]
    
    if peak > k_target:
        log_fn("")
        log_fn("!" * 60)
        log_fn(f"CRITICAL: Peak concurrency ({peak}) > K_target ({k_target})")
        log_fn("The 42-53h goal is IMPOSSIBLE with these blocks!")
        log_fn("You need to change Phase-1 block selection.")
        log_fn("!" * 60)
        return {
            "feasible": False,
            "reason": f"Peak concurrency {peak} > K_target {k_target}",
            "peak_result": peak_result,
        }
    
    log_fn(f"\n✓ Peak concurrency ({peak}) <= K_target ({k_target}) - Potentially feasible")
    
    # Step 1: Greedy builder
    greedy_result = build_fixed_k_greedy(blocks, log_fn)
    n_greedy = greedy_result["n_drivers"]
    
    if n_greedy > k_target:
        log_fn("")
        log_fn("!" * 60)
        log_fn(f"WARNING: Greedy needs {n_greedy} drivers > K_target ({k_target})")
        log_fn("May need more drivers than K_target allows for 42h minimum.")
        log_fn("!" * 60)
    
    # Check hours feasibility
    hours = greedy_result["driver_hours"]
    under_42 = sum(1 for h in hours if h < 42.0)
    over_53 = sum(1 for h in hours if h > 53.0)
    
    log_fn("")
    log_fn("=" * 60)
    log_fn("PIPELINE SUMMARY")
    log_fn("=" * 60)
    log_fn(f"Peak concurrency (LB): {peak}")
    log_fn(f"Greedy drivers: {n_greedy}")
    log_fn(f"K_target: {k_target}")
    log_fn(f"Under 42h: {under_42} drivers")
    log_fn(f"Over 53h: {over_53} drivers")
    
    if peak <= k_target and n_greedy <= k_target:
        log_fn("\n✓ Pipeline indicates problem MAY be feasible")
        log_fn("  Next: Use greedy as hint for CP-SAT with hour constraints")
    else:
        log_fn("\n✗ Pipeline indicates problem is INFEASIBLE as stated")
        log_fn("  Need to adjust block selection or relax constraints")
    
    return {
        "feasible": peak <= k_target,
        "peak_concurrency": peak,
        "peak_result": peak_result,
        "greedy_result": greedy_result,
        "n_greedy": n_greedy,
        "under_42": under_42,
        "over_53": over_53,
    }


# =============================================================================
# STEP 2: CP-SAT WITH FIXED N + CONSTRAINTS + HINTS
# =============================================================================

def solve_cpsat_fixed_n(
    blocks: list,
    n_drivers: int,
    greedy_assignments: dict,
    min_hours: float = 42.0,
    max_hours: float = 53.0,
    time_limit: float = 300.0,
    log_fn=None,
) -> dict:
    """
    Solve CP-SAT with fixed N drivers and full constraints.
    
    Uses drv[b] IntVar (block → driver index) instead of x[b,k] bools
    for dramatically fewer variables (701 instead of 701*N).
    
    Constraints:
    - Hours: min_hours <= hours[k] <= max_hours for used drivers
    - NoOverlap: no two blocks assigned to same driver on same day can overlap
    - Rest: 11h between days, 14h after heavy day
    
    Args:
        blocks: List of Block objects
        n_drivers: Fixed number of drivers (N)
        greedy_assignments: {block_id: driver_idx} from greedy step (for hints)
        min_hours: Minimum hours per driver (default 42)
        max_hours: Maximum hours per driver (default 53)
        time_limit: CP-SAT time limit in seconds
        log_fn: Logging function
    
    Returns:
        {
            "status": "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "UNKNOWN",
            "assignments": {block_id: driver_idx},
            "driver_hours": [hours per driver],
            "solve_time": float,
        }
    """
    from ortools.sat.python import cp_model
    import time
    
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("")
    log_fn("=" * 60)
    log_fn("STEP 2: CP-SAT WITH FIXED N + CONSTRAINTS")
    log_fn("=" * 60)
    log_fn(f"Fixed N: {n_drivers} drivers")
    log_fn(f"Hours: {min_hours}h - {max_hours}h")
    log_fn(f"Time limit: {time_limit}s")
    
    B = len(blocks)
    N = n_drivers
    
    # Group blocks by day
    blocks_by_day = {d: [] for d in range(7)}
    for i, b in enumerate(blocks):
        day = get_day_idx(b)
        blocks_by_day[day].append(i)
    
    # Create block info lookup
    block_info = []
    for b in blocks:
        block_info.append({
            "id": get_block_id(b),
            "day": get_day_idx(b),
            "start": get_start_min(b),
            "end": get_end_min(b),
            "work": get_work_min(b),
            "tours": len(b.tours) if hasattr(b, 'tours') else 1,
        })
    
    # =================================================================
    # BUILD MODEL
    # =================================================================
    model = cp_model.CpModel()
    
    log_fn("Creating variables...")
    
    # drv[b] = which driver is assigned to block b (0..N-1)
    drv = [model.NewIntVar(0, N - 1, f"drv_{i}") for i in range(B)]
    
    # week_minutes[k] = total work minutes for driver k
    max_week_min = int(max_hours * 60)
    week_minutes = [model.NewIntVar(0, max_week_min, f"week_{k}") for k in range(N)]
    
    # Per-driver per-day variables
    # first_start[d,k], last_end[d,k] for rest constraints
    DAY_MINUTES = 24 * 60
    first_start = {}
    last_end = {}
    tours_day = {}
    heavy = {}
    
    for d in range(7):
        for k in range(N):
            first_start[d, k] = model.NewIntVar(0, DAY_MINUTES, f"first_{d}_{k}")
            last_end[d, k] = model.NewIntVar(0, DAY_MINUTES, f"last_{d}_{k}")
            tours_day[d, k] = model.NewIntVar(0, 3, f"tours_{d}_{k}")
            heavy[d, k] = model.NewBoolVar(f"heavy_{d}_{k}")
    
    log_fn(f"Variables: {B} drv[b] + {N} week + {7*N*4} day-level")
    
    # =================================================================
    # CONSTRAINTS
    # =================================================================
    log_fn("Adding constraints...")
    
    # 1. Week minutes = sum of work for assigned blocks
    # Use element constraint: if drv[b] == k, then add work to week_minutes[k]
    # This is tricky with IntVars - use channeling with bool indicators
    
    # Create x[b,k] channeling: x[b,k] = (drv[b] == k)
    x = {}
    for b_idx in range(B):
        for k in range(N):
            x[b_idx, k] = model.NewBoolVar(f"x_{b_idx}_{k}")
            model.Add(drv[b_idx] == k).OnlyEnforceIf(x[b_idx, k])
            model.Add(drv[b_idx] != k).OnlyEnforceIf(x[b_idx, k].Not())
    
    # 2. Week minutes per driver
    for k in range(N):
        model.Add(week_minutes[k] == sum(
            block_info[b_idx]["work"] * x[b_idx, k]
            for b_idx in range(B)
        ))
    
    # 3. Hours constraints: min_hours <= week_minutes <= max_hours
    min_minutes = int(min_hours * 60)
    for k in range(N):
        model.Add(week_minutes[k] >= min_minutes)
        model.Add(week_minutes[k] <= max_week_min)
    
    # 4. NoOverlap per (driver, day)
    log_fn("Adding NoOverlap constraints...")
    for k in range(N):
        for d in range(7):
            if not blocks_by_day[d]:
                continue
            
            intervals = []
            for b_idx in blocks_by_day[d]:
                info = block_info[b_idx]
                span = info["end"] - info["start"]
                interval = model.NewOptionalFixedSizeIntervalVar(
                    start=info["start"],
                    size=span,
                    is_present=x[b_idx, k],
                    name=f"iv_{b_idx}_{k}"
                )
                intervals.append(interval)
            
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)
    
    # 5. Tours per day
    for d in range(7):
        for k in range(N):
            if blocks_by_day[d]:
                model.Add(tours_day[d, k] == sum(
                    block_info[b_idx]["tours"] * x[b_idx, k]
                    for b_idx in blocks_by_day[d]
                ))
            else:
                model.Add(tours_day[d, k] == 0)
    
    # 6. Heavy day: heavy[d,k] = 1 iff tours == 3
    for d in range(7):
        for k in range(N):
            model.Add(tours_day[d, k] >= 3 * heavy[d, k])
            model.Add(tours_day[d, k] <= 2 + heavy[d, k])
    
    # 7. Tours cap after heavy: tours[d+1] <= 3 - heavy[d]
    for d in range(6):
        for k in range(N):
            model.Add(tours_day[d + 1, k] <= 3 - heavy[d, k])
    
    # 8. first_start, last_end channeling
    log_fn("Adding first/last constraints...")
    for d in range(7):
        for k in range(N):
            if not blocks_by_day[d]:
                model.Add(first_start[d, k] == DAY_MINUTES)
                model.Add(last_end[d, k] == 0)
                continue
            
            # first_start <= start if assigned
            for b_idx in blocks_by_day[d]:
                model.Add(first_start[d, k] <= block_info[b_idx]["start"]).OnlyEnforceIf(x[b_idx, k])
            
            # If no blocks assigned, first_start = DAY_MINUTES
            any_assigned = model.NewBoolVar(f"any_{d}_{k}")
            model.Add(sum(x[b_idx, k] for b_idx in blocks_by_day[d]) >= 1).OnlyEnforceIf(any_assigned)
            model.Add(sum(x[b_idx, k] for b_idx in blocks_by_day[d]) == 0).OnlyEnforceIf(any_assigned.Not())
            model.Add(first_start[d, k] == DAY_MINUTES).OnlyEnforceIf(any_assigned.Not())
            
            # last_end >= end if assigned
            for b_idx in blocks_by_day[d]:
                model.Add(last_end[d, k] >= block_info[b_idx]["end"]).OnlyEnforceIf(x[b_idx, k])
            
            model.Add(last_end[d, k] == 0).OnlyEnforceIf(any_assigned.Not())
    
    # 9. Rest constraints: 11h + 3h*heavy between consecutive days
    log_fn("Adding rest constraints...")
    MIN_REST = 660  # 11h
    EXTRA_REST = 180  # +3h for heavy = 14h total
    
    for d in range(6):  # Mon-Sat
        for k in range(N):
            # If working both days: rest >= 11h + 3h*heavy
            both = model.NewBoolVar(f"both_{d}_{k}")
            any_d = model.NewBoolVar(f"anyd_{d}_{k}")
            any_d1 = model.NewBoolVar(f"anyd1_{d}_{k}")
            
            # any_d = any block on day d
            if blocks_by_day[d]:
                model.Add(sum(x[b_idx, k] for b_idx in blocks_by_day[d]) >= 1).OnlyEnforceIf(any_d)
                model.Add(sum(x[b_idx, k] for b_idx in blocks_by_day[d]) == 0).OnlyEnforceIf(any_d.Not())
            else:
                model.Add(any_d == 0)
            
            # any_d1 = any block on day d+1
            if blocks_by_day[d + 1]:
                model.Add(sum(x[b_idx, k] for b_idx in blocks_by_day[d + 1]) >= 1).OnlyEnforceIf(any_d1)
                model.Add(sum(x[b_idx, k] for b_idx in blocks_by_day[d + 1]) == 0).OnlyEnforceIf(any_d1.Not())
            else:
                model.Add(any_d1 == 0)
            
            # both = any_d AND any_d1
            model.AddBoolAnd([any_d, any_d1]).OnlyEnforceIf(both)
            model.AddBoolOr([any_d.Not(), any_d1.Not()]).OnlyEnforceIf(both.Not())
            
            # rest = first_start[d+1] + DAY_MINUTES - last_end[d] >= 660 + 180*heavy
            model.Add(
                first_start[d + 1, k] + DAY_MINUTES - last_end[d, k] >= MIN_REST + EXTRA_REST * heavy[d, k]
            ).OnlyEnforceIf(both)
    
    # 10. Symmetry breaking
    log_fn("Adding symmetry breaking...")
    for k in range(N - 1):
        model.Add(week_minutes[k] >= week_minutes[k + 1])
    
    # =================================================================
    # HINTS from greedy
    # =================================================================
    log_fn("Setting hints from greedy solution...")
    block_id_to_idx = {block_info[i]["id"]: i for i in range(B)}
    hints_set = 0
    for block_id, driver_idx in greedy_assignments.items():
        if block_id in block_id_to_idx and driver_idx < N:
            b_idx = block_id_to_idx[block_id]
            model.AddHint(drv[b_idx], driver_idx)
            hints_set += 1
    log_fn(f"Set {hints_set} hints")
    
    # =================================================================
    # SOLVE
    # =================================================================
    log_fn(f"\nSolving (limit={time_limit}s)...")
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # S0.1: Determinism (CP-SAT correct param)
    solver.parameters.random_seed = 42
    
    start_time = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - start_time
    
    status_name = solver.StatusName(status)
    log_fn(f"Status: {status_name}, Time: {solve_time:.1f}s")
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log_fn("No feasible solution found!")
        return {
            "status": status_name,
            "assignments": {},
            "driver_hours": [],
            "solve_time": solve_time,
        }
    
    # Extract solution
    assignments = {}
    for b_idx in range(B):
        assigned_driver = solver.Value(drv[b_idx])
        assignments[block_info[b_idx]["id"]] = assigned_driver
    
    driver_hours = [solver.Value(week_minutes[k]) / 60.0 for k in range(N)]
    
    # Stats
    under_42 = sum(1 for h in driver_hours if h < min_hours)
    over_53 = sum(1 for h in driver_hours if h > max_hours)
    
    log_fn(f"Solution found!")
    log_fn(f"  Hours range: {min(driver_hours):.1f}h - {max(driver_hours):.1f}h")
    log_fn(f"  Under {min_hours}h: {under_42}")
    log_fn(f"  Over {max_hours}h: {over_53}")
    
    return {
        "status": status_name,
        "assignments": assignments,
        "driver_hours": driver_hours,
        "solve_time": solve_time,
        "under_min": under_42,
        "over_max": over_53,
    }


# =============================================================================
# STEP 3: HOUR CONTINUATION
# =============================================================================

def solve_with_hour_continuation(
    blocks: list,
    n_drivers: int,
    greedy_assignments: dict,
    max_hours: float = 53.0,
    log_fn=None,
) -> dict:
    """
    Solve with staged min_hours continuation.
    
    Stages: 0 → 20 → 30 → 35 → 40 → 42
    Each stage uses previous solution as hints.
    Staged time limits to avoid wasting time on easy steps.
    
    Returns the solution from the highest successful min_hours step.
    """
    from ortools.sat.python import cp_model
    
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("")
    log_fn("=" * 60)
    log_fn("STEP 3: HOUR CONTINUATION")
    log_fn("=" * 60)
    
    # Stages: (min_hours, time_limit)
    stages = [
        (0, 30),    # No min: should be fast
        (20, 60),   # Easy
        (30, 60),   # Moderate
        (35, 120),  # Getting harder
        (40, 120),  # Hard
        (42, 300),  # Target - most time
    ]
    
    current_hints = greedy_assignments.copy()
    best_result = None
    best_min_hours = 0
    
    for min_hours, time_limit in stages:
        log_fn(f"\n--- Stage: min_hours={min_hours}h, limit={time_limit}s ---")
        
        result = solve_cpsat_fixed_n(
            blocks=blocks,
            n_drivers=n_drivers,
            greedy_assignments=current_hints,
            min_hours=float(min_hours),
            max_hours=max_hours,
            time_limit=float(time_limit),
            log_fn=log_fn,
        )
        
        if result.get("status") in ("OPTIMAL", "FEASIBLE"):
            log_fn(f"✓ Stage {min_hours}h: SUCCESS")
            best_result = result
            best_min_hours = min_hours
            # Update hints for next stage
            current_hints = result.get("assignments", {})
        else:
            log_fn(f"✗ Stage {min_hours}h: FAILED ({result.get('status')})")
            log_fn(f"Stopping continuation at min_hours={best_min_hours}h")
            break
    
    log_fn("")
    log_fn("=" * 60)
    log_fn(f"HOUR CONTINUATION COMPLETE")
    log_fn(f"Best achieved: min_hours={best_min_hours}h")
    log_fn("=" * 60)
    
    return {
        "success": best_min_hours >= 42,
        "best_min_hours": best_min_hours,
        "best_result": best_result,
        "n_drivers": n_drivers,
    }


# =============================================================================
# STEP 3B: N-ESCALATION (OUTER LOOP)
# =============================================================================

def solve_with_n_escalation(
    blocks: list,
    peak_concurrency: int,
    k_target: int,
    greedy_assignments: dict,
    log_fn=None,
) -> dict:
    """
    Outer loop: Try increasing N until 42h is achievable.
    
    N starts at peak_concurrency and increases by 2 until k_target.
    For each N, runs full hour continuation.
    Stops when 42h is achieved.
    
    Returns the first successful N and solution.
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("")
    log_fn("=" * 70)
    log_fn("STEP 3: N-ESCALATION + HOUR CONTINUATION")
    log_fn("=" * 70)
    log_fn(f"Peak concurrency (min N): {peak_concurrency}")
    log_fn(f"K_target (max N): {k_target}")
    
    # Try N = peak, peak+2, peak+4, ... up to k_target
    for n in range(peak_concurrency, k_target + 1, 2):
        log_fn(f"\n{'='*60}")
        log_fn(f"TRYING N = {n} DRIVERS")
        log_fn(f"{'='*60}")
        
        result = solve_with_hour_continuation(
            blocks=blocks,
            n_drivers=n,
            greedy_assignments=greedy_assignments,
            log_fn=log_fn,
        )
        
        if result.get("success"):
            log_fn(f"\n✓✓✓ SUCCESS with N={n} drivers at 42h ✓✓✓")
            return {
                "success": True,
                "n_drivers": n,
                "best_result": result.get("best_result"),
                "escalation_steps": (n - peak_concurrency) // 2 + 1,
            }
        else:
            log_fn(f"✗ N={n} failed at min_hours={result.get('best_min_hours')}h")
            # Update hints from best achieved (even if not 42h)
            if result.get("best_result"):
                greedy_assignments = result["best_result"].get("assignments", greedy_assignments)
    
    log_fn("")
    log_fn("=" * 70)
    log_fn("N-ESCALATION FAILED")
    log_fn(f"Could not achieve 42h with any N from {peak_concurrency} to {k_target}")
    log_fn("=" * 70)
    
    return {
        "success": False,
        "n_drivers": k_target,
        "best_result": None,
        "reason": f"42h not achievable with N={peak_concurrency}..{k_target}",
    }
