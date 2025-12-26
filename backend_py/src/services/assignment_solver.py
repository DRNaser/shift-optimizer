"""
Phase2 Assignment Solver - Headcount-First CP-SAT
==================================================

Optimizes driver assignment to blocks with lexicographic objectives:
1. Minimize number of drivers (headcount)
2. Minimize under-40h shortfall
3. Minimize over-50h excess
4. Minimize 6th day usage

Hard Constraints:
- Each block assigned exactly once
- Max 55h per driver per week
- Max 1 block per day per driver
- 11h minimum rest between consecutive days
- Optional driver_cap (fixed max drivers)

NO PT DRIVERS - Only FTE with 40-50h target utilization.
"""

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

from ortools.sat.python import cp_model

from src.domain.models import Block, Weekday

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class AssignmentConfig:
    """Configuration for Phase2 Assignment Solver."""
    
    # Driver cap (None = minimize headcount)
    driver_cap: Optional[int] = None
    
    # Hour targets (soft, in minutes)
    min_hours_target: int = 40 * 60  # 40h = 2400 min
    max_hours_target: int = 50 * 60  # 50h = 3000 min
    
    # Hard limits (in minutes)
    max_hours_hard: int = 55 * 60    # 55h = 3300 min
    
    # Rest constraints (standard)
    min_rest_minutes: int = 11 * 60  # 11h = 660 min
    
    # 3-Tour Recovery Rule (12h rest + max 2 tours next day)
    min_rest_after_3t_minutes: int = 12 * 60  # 12h = 720 min
    max_next_day_tours_after_3t: int = 2      # Max 2 tours next day
    
    # Block limits
    max_blocks_per_day: int = 1  # Conservative: 1 block/day
    
    # 6th day penalty
    penalize_sixth_day: bool = True
    max_days_soft: int = 5
    
    # Solver settings
    time_limit: float = 120.0
    time_limit_s: float = None  # Alias for time_limit (for portfolio_controller compatibility)
    seed: int = 42
    num_workers: int = 1  # Determinism
    
    def __post_init__(self):
        # Use time_limit_s if provided, otherwise use time_limit
        if self.time_limit_s is not None:
            self.time_limit = self.time_limit_s


@dataclass
class AssignmentResult:
    """Result from Phase2 Assignment Solver."""
    
    status: str = "UNKNOWN"
    
    # Headcount
    drivers_used: int = 0
    
    # Hour distribution
    total_hours: float = 0.0
    avg_hours: float = 0.0
    min_hours: float = 0.0
    max_hours: float = 0.0
    
    # Soft constraint violations
    under40_count: int = 0
    under40_sum_minutes: int = 0
    over50_count: int = 0
    over50_sum_minutes: int = 0
    sixth_day_count: int = 0
    
    # Assignments: driver_id -> list of block_ids
    assignments: dict[int, list[str]] = field(default_factory=dict)
    
    # Per-driver hours
    driver_hours: dict[int, float] = field(default_factory=dict)
    
    # Timing
    solve_time_s: float = 0.0
    
    # Feasibility
    feasible: bool = False
    driver_cap_tested: Optional[int] = None
    
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "drivers_used": self.drivers_used,
            "total_hours": round(self.total_hours, 1),
            "avg_hours": round(self.avg_hours, 1),
            "min_hours": round(self.min_hours, 1),
            "max_hours": round(self.max_hours, 1),
            "under40_count": self.under40_count,
            "under40_sum_minutes": self.under40_sum_minutes,
            "over50_count": self.over50_count,
            "over50_sum_minutes": self.over50_sum_minutes,
            "sixth_day_count": self.sixth_day_count,
            "feasible": self.feasible,
            "driver_cap_tested": self.driver_cap_tested,
            "solve_time_s": round(self.solve_time_s, 2),
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

WEEKDAY_ORDER = {
    Weekday.MONDAY: 0,
    Weekday.TUESDAY: 1,
    Weekday.WEDNESDAY: 2,
    Weekday.THURSDAY: 3,
    Weekday.FRIDAY: 4,
    Weekday.SATURDAY: 5,
    Weekday.SUNDAY: 6,
}


def get_block_end_minutes(block: Block) -> int:
    """Get block end time as minutes from midnight."""
    return block.last_end.hour * 60 + block.last_end.minute


def get_block_start_minutes(block: Block) -> int:
    """Get block start time as minutes from midnight."""
    return block.first_start.hour * 60 + block.first_start.minute


def get_block_work_minutes(block: Block) -> int:
    """Get block work duration in minutes."""
    return block.total_work_minutes


def compute_rest_minutes(b1: Block, b2: Block) -> int:
    """
    Compute rest minutes between b1 (day i) and b2 (day i+1).
    Rest = (24h - end(b1)) + start(b2)
    """
    end_b1 = get_block_end_minutes(b1)
    start_b2 = get_block_start_minutes(b2)
    
    # Rest from end of b1 to midnight + midnight to start of b2
    rest = (24 * 60 - end_b1) + start_b2
    return rest


def compute_incompatible_pairs(
    blocks: list[Block],
    min_rest_minutes: int = 660,  # 11h
) -> set[tuple[str, str]]:
    """
    Precompute block pairs where rest < min_rest_minutes.
    Returns set of (b1.id, b2.id) tuples.
    """
    incompatible = set()
    
    # Group blocks by day
    blocks_by_day: dict[int, list[Block]] = {}
    for b in blocks:
        day_idx = WEEKDAY_ORDER.get(b.day, 0)
        if day_idx not in blocks_by_day:
            blocks_by_day[day_idx] = []
        blocks_by_day[day_idx].append(b)
    
    # Check consecutive day pairs (Mon-Sat → Tue-Sun)
    for day_idx in range(6):  # Mon-Sat (0-5)
        if day_idx not in blocks_by_day:
            continue
        next_day_idx = day_idx + 1
        if next_day_idx not in blocks_by_day:
            continue
        
        for b1 in blocks_by_day[day_idx]:
            for b2 in blocks_by_day[next_day_idx]:
                rest = compute_rest_minutes(b1, b2)
                if rest < min_rest_minutes:
                    incompatible.add((b1.id, b2.id))
    
    # Check Sunday→Monday wrap-around (day 6 → day 0)
    if 6 in blocks_by_day and 0 in blocks_by_day:
        for b1 in blocks_by_day[6]:  # Sunday
            for b2 in blocks_by_day[0]:  # Monday
                rest = compute_rest_minutes(b1, b2)
                if rest < min_rest_minutes:
                    incompatible.add((b1.id, b2.id))
    
    return incompatible


# =============================================================================
# MAIN SOLVER
# =============================================================================

def solve_phase2_assignment(
    blocks: list[Block],
    config: AssignmentConfig = None,
    log_fn=None,
) -> AssignmentResult:
    """
    Solve Phase2 Assignment using CP-SAT with lexicographic objectives.
    
    Stages:
    A: Minimize drivers_used (if no fixed driver_cap)
    B: Minimize under40_sum (shortfall below 40h)
    C: Minimize over50_sum (excess above 50h)
    D: Minimize sixth_day_count
    
    Args:
        blocks: Selected blocks from Phase1
        config: Assignment configuration
        log_fn: Optional logging callback
    
    Returns:
        AssignmentResult with assignments and statistics
    """
    if config is None:
        config = AssignmentConfig()
    
    def log(msg: str):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    
    start = perf_counter()
    result = AssignmentResult(driver_cap_tested=config.driver_cap)
    
    if not blocks:
        log("[Phase2] No blocks to assign")
        result.status = "NO_BLOCKS"
        result.solve_time_s = perf_counter() - start
        return result
    
    log("=" * 70)
    log("PHASE 2: HEADCOUNT-FIRST CP-SAT ASSIGNMENT")
    log("=" * 70)
    log(f"Blocks: {len(blocks)}")
    
    total_work_minutes = sum(get_block_work_minutes(b) for b in blocks)
    total_hours = total_work_minutes / 60.0
    result.total_hours = total_hours
    
    log(f"Total work: {total_hours:.1f}h")
    
    # Estimate driver count
    min_drivers_theoretical = int(total_work_minutes / config.max_hours_hard) + 1
    target_drivers = int(total_work_minutes / ((config.min_hours_target + config.max_hours_target) / 2)) + 1
    
    log(f"Theoretical min drivers (55h): {min_drivers_theoretical}")
    log(f"Target drivers (45h avg): {target_drivers}")
    
    # Determine driver count to use
    if config.driver_cap:
        num_drivers = config.driver_cap
        log(f"Using fixed driver_cap: {num_drivers}")
    else:
        # Start with target + buffer for feasibility
        num_drivers = max(target_drivers + 10, min_drivers_theoretical + 5)
        log(f"Initial driver pool: {num_drivers}")
    
    # Precompute incompatible pairs (11h rest)
    log("Precomputing rest-incompatible pairs...")
    incompatible = compute_incompatible_pairs(blocks, config.min_rest_minutes)
    log(f"Found {len(incompatible)} incompatible block pairs (rest < 11h)")
    
    # Group blocks by day
    blocks_by_day: dict[int, list[Block]] = {}
    for b in blocks:
        day_idx = WEEKDAY_ORDER.get(b.day, 0)
        if day_idx not in blocks_by_day:
            blocks_by_day[day_idx] = []
        blocks_by_day[day_idx].append(b)
    
    log(f"Blocks per day: {', '.join(f'{WEEKDAY_NAMES[d]}={len(bs)}' for d, bs in sorted(blocks_by_day.items()))}")
    
    # ==========================================================================
    # BUILD CP-SAT MODEL
    # ==========================================================================
    log("\nBuilding CP-SAT model...")
    
    model = cp_model.CpModel()
    
    # Block index
    block_idx = {b.id: i for i, b in enumerate(blocks)}
    
    # Variables
    # x[d, b] = 1 if driver d is assigned block b
    x = {}
    for d in range(num_drivers):
        for b in blocks:
            x[d, b.id] = model.NewBoolVar(f"x_{d}_{b.id}")
    
    # use[d] = 1 if driver d is used (has at least one block)
    use = [model.NewBoolVar(f"use_{d}") for d in range(num_drivers)]
    
    # work[d] = total work minutes for driver d
    work = [model.NewIntVar(0, config.max_hours_hard, f"work_{d}") for d in range(num_drivers)]
    
    # under[d] = max(0, 40h - work[d]) shortfall
    under = [model.NewIntVar(0, config.min_hours_target, f"under_{d}") for d in range(num_drivers)]
    
    # over[d] = max(0, work[d] - 50h) excess
    over = [model.NewIntVar(0, config.max_hours_hard - config.max_hours_target, f"over_{d}") for d in range(num_drivers)]
    
    # days_worked[d] = number of days driver d works
    days_worked = [model.NewIntVar(0, 7, f"days_{d}") for d in range(num_drivers)]
    
    # sixth[d] = max(0, days_worked - 5)
    sixth = [model.NewIntVar(0, 7, f"sixth_{d}") for d in range(num_drivers)]
    
    # works_day[d, day] = 1 if driver d works on this day
    works_day = {}
    for d in range(num_drivers):
        for day_idx in range(7):
            works_day[d, day_idx] = model.NewBoolVar(f"works_day_{d}_{day_idx}")
    
    # ==========================================================================
    # HARD CONSTRAINTS
    # ==========================================================================
    log("Adding constraints...")
    
    # C1: Each block assigned exactly once
    for b in blocks:
        model.Add(sum(x[d, b.id] for d in range(num_drivers)) == 1)
    
    # C2: Driver usage linking
    for d in range(num_drivers):
        # use[d] = 1 if any x[d,b] = 1
        model.AddMaxEquality(use[d], [x[d, b.id] for b in blocks])
    
    # C3: Work calculation + max 55h
    for d in range(num_drivers):
        model.Add(work[d] == sum(x[d, b.id] * get_block_work_minutes(b) for b in blocks))
        # Max 55h is implicit via work domain
    
    # C4: Max 1 block per day per driver
    for d in range(num_drivers):
        for day_idx, day_blocks in blocks_by_day.items():
            if day_blocks:
                model.Add(sum(x[d, b.id] for b in day_blocks) <= config.max_blocks_per_day)
    
    # C5: 11h rest between consecutive days (incompatible pairs)
    for b1_id, b2_id in incompatible:
        for d in range(num_drivers):
            model.Add(x[d, b1_id] + x[d, b2_id] <= 1)
    
    # C6: works_day linking
    for d in range(num_drivers):
        for day_idx, day_blocks in blocks_by_day.items():
            if day_blocks:
                model.AddMaxEquality(works_day[d, day_idx], [x[d, b.id] for b in day_blocks])
            else:
                model.Add(works_day[d, day_idx] == 0)
    
    # Days worked calculation
    for d in range(num_drivers):
        model.Add(days_worked[d] == sum(works_day[d, day_idx] for day_idx in range(7)))
    
    # Under/over calculation
    for d in range(num_drivers):
        # under[d] >= min_target - work[d]
        model.Add(under[d] >= config.min_hours_target - work[d])
        # over[d] >= work[d] - max_target
        model.Add(over[d] >= work[d] - config.max_hours_target)
    
    # Sixth day calculation
    for d in range(num_drivers):
        model.Add(sixth[d] >= days_worked[d] - config.max_days_soft)
    
    # Symmetry breaking: drivers assigned in order
    for d in range(num_drivers - 1):
        model.Add(use[d] >= use[d + 1])
    
    log(f"Model built: {len(blocks)} blocks, {num_drivers} drivers")
    log(f"Variables: {len(x)} x + {num_drivers} use + {num_drivers} work + ...")
    log(f"Rest constraints: {len(incompatible)} incompatible pairs")
    
    # ==========================================================================
    # LEXICOGRAPHIC SOLVING
    # ==========================================================================
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit
    solver.parameters.random_seed = config.seed
    solver.parameters.num_search_workers = config.num_workers
    
    # Stage A: Minimize drivers used
    log("\n--- STAGE A: Minimize drivers ---")
    total_use = sum(use)
    model.Minimize(total_use)
    
    status = solver.Solve(model)
    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        drivers_a = int(solver.ObjectiveValue())
        log(f"  Stage A: {status_map[status]}, drivers = {drivers_a}")
        
        # Lock driver count
        model.Add(total_use <= drivers_a)
        result.drivers_used = drivers_a
        result.feasible = True
        
        # Stage B: Minimize under40 sum
        log("\n--- STAGE B: Minimize under-40h shortfall ---")
        total_under = sum(under)
        model.Minimize(total_under)
        
        status = solver.Solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            under_b = int(solver.ObjectiveValue())
            log(f"  Stage B: {status_map[status]}, under40_sum = {under_b} min ({under_b/60:.1f}h)")
            
            # Lock under
            model.Add(total_under <= under_b)
            result.under40_sum_minutes = under_b
            
            # Stage C: Minimize over50 sum
            log("\n--- STAGE C: Minimize over-50h excess ---")
            total_over = sum(over)
            model.Minimize(total_over)
            
            status = solver.Solve(model)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                over_c = int(solver.ObjectiveValue())
                log(f"  Stage C: {status_map[status]}, over50_sum = {over_c} min ({over_c/60:.1f}h)")
                
                # Lock over
                model.Add(total_over <= over_c)
                result.over50_sum_minutes = over_c
                
                # Stage D: Minimize sixth day
                log("\n--- STAGE D: Minimize 6th day usage ---")
                total_sixth = sum(sixth)
                model.Minimize(total_sixth)
                
                status = solver.Solve(model)
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    sixth_d = int(solver.ObjectiveValue())
                    log(f"  Stage D: {status_map[status]}, sixth_days = {sixth_d}")
                    result.sixth_day_count = sixth_d
    else:
        log(f"  Stage A FAILED: {status_map.get(status, 'UNKNOWN')}")
        result.status = status_map.get(status, "UNKNOWN")
        result.feasible = False
        result.solve_time_s = perf_counter() - start
        return result
    
    # ==========================================================================
    # EXTRACT SOLUTION
    # ==========================================================================
    log("\n--- Extracting solution ---")
    
    final_status = status_map.get(status, "UNKNOWN")
    result.status = final_status
    
    # Extract assignments
    for d in range(num_drivers):
        if solver.Value(use[d]) == 1:
            driver_blocks = []
            for b in blocks:
                if solver.Value(x[d, b.id]) == 1:
                    driver_blocks.append(b.id)
            if driver_blocks:
                result.assignments[d] = driver_blocks
                driver_work = solver.Value(work[d]) / 60.0
                result.driver_hours[d] = driver_work
    
    # Compute statistics
    all_hours = list(result.driver_hours.values())
    if all_hours:
        result.avg_hours = sum(all_hours) / len(all_hours)
        result.min_hours = min(all_hours)
        result.max_hours = max(all_hours)
        result.under40_count = sum(1 for h in all_hours if h < 40)
        result.over50_count = sum(1 for h in all_hours if h > 50)
    
    result.solve_time_s = perf_counter() - start
    
    log("=" * 70)
    log("PHASE 2 COMPLETE")
    log("=" * 70)
    log(f"Status: {result.status}")
    log(f"Drivers: {result.drivers_used}")
    log(f"Hours: min={result.min_hours:.1f}h, max={result.max_hours:.1f}h, avg={result.avg_hours:.1f}h")
    log(f"Under 40h: {result.under40_count} drivers ({result.under40_sum_minutes/60:.1f}h total shortfall)")
    log(f"Over 50h: {result.over50_count} drivers ({result.over50_sum_minutes/60:.1f}h total excess)")
    log(f"6th day: {result.sixth_day_count} driver-days")
    log(f"Time: {result.solve_time_s:.1f}s")
    
    return result


# =============================================================================
# FEASIBILITY SEARCH
# =============================================================================

def find_min_feasible_cap(
    blocks: list[Block],
    start_cap: int = 150,
    step: int = 5,
    max_attempts: int = 20,
    config: AssignmentConfig = None,
    log_fn=None,
) -> AssignmentResult:
    """
    Find minimum feasible driver_cap using stepwise search.
    
    Args:
        blocks: Selected blocks
        start_cap: Starting driver cap to test
        step: Step size for search
        max_attempts: Maximum iterations
        config: Base config (driver_cap will be overwritten)
        log_fn: Logging callback
    
    Returns:
        AssignmentResult for the minimum feasible cap
    """
    if config is None:
        config = AssignmentConfig()
    
    def log(msg: str):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    
    log("=" * 70)
    log("DRIVER CAP FEASIBILITY SEARCH")
    log("=" * 70)
    log(f"Starting cap: {start_cap}, step: {step}")
    
    best_result = None
    current_cap = start_cap
    
    for attempt in range(max_attempts):
        log(f"\n--- Attempt {attempt + 1}: Testing cap = {current_cap} ---")
        
        test_config = AssignmentConfig(
            driver_cap=current_cap,
            min_hours_target=config.min_hours_target,
            max_hours_target=config.max_hours_target,
            max_hours_hard=config.max_hours_hard,
            min_rest_minutes=config.min_rest_minutes,
            max_blocks_per_day=config.max_blocks_per_day,
            penalize_sixth_day=config.penalize_sixth_day,
            time_limit=config.time_limit / 2,  # Shorter per attempt
            seed=config.seed,
        )
        
        result = solve_phase2_assignment(blocks, test_config, log_fn)
        
        if result.feasible:
            log(f"  FEASIBLE at cap = {current_cap}")
            best_result = result
            
            # Try lower
            current_cap -= step
            if current_cap < result.drivers_used:
                log(f"  Cannot go lower than {result.drivers_used} (actual usage)")
                break
        else:
            log(f"  INFEASIBLE at cap = {current_cap}")
            # Try higher
            current_cap += step
    
    if best_result:
        log(f"\n=== MINIMUM FEASIBLE: {best_result.drivers_used} drivers ===")
    else:
        log("\n=== NO FEASIBLE SOLUTION FOUND ===")
    
    return best_result or AssignmentResult(status="INFEASIBLE", feasible=False)


# Weekday names for logging
WEEKDAY_NAMES = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"
}
