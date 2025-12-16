"""
LNS REFINER v4 - Assignment Phase Optimization
==============================================
Minimal destroy/repair for v4 solver's assignment phase.

Strategy:
- Phase 1 (block selection) stays untouched
- Phase 2 (greedy assignment) output is refined via LNS
- Destroy: Remove 20-35% of drivers' blocks
- Repair: Small CP-SAT to reassign those blocks optimally

Determinism:
- All randomness seeded
- Sorted iteration over sets
- CP-SAT with fixed search strategy
"""

import random
import logging
from dataclasses import dataclass, field
from ortools.sat.python import cp_model

from src.domain.models import Block, Weekday

logger = logging.getLogger("LNS_V4")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class LNSConfigV4:
    """Configuration for v4 LNS refiner."""
    max_iterations: int = 10
    destroy_fraction: float = 0.30  # 20-35% of drivers
    repair_time_limit: float = 5.0  # seconds per repair
    seed: int = 42
    min_hours_per_fte: float = 42.0
    max_hours_per_fte: float = 53.0
    max_daily_span_minutes: int = 14 * 60  # 14 hours
    min_rest_minutes: int = 11 * 60  # 11 hours
    max_tours_per_day: int = 3


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class BlockInfo:
    """Block info for LNS repair model."""
    block_id: str
    day_idx: int  # 0..6
    start_min: int  # minutes from midnight
    end_min: int
    duration_min: int
    tour_count: int


@dataclass 
class DriverState:
    """Driver state for LNS repair model."""
    driver_id: str
    driver_type: str  # "FTE" or "PT"
    fixed_blocks: list[BlockInfo] = field(default_factory=list)
    destroyed_blocks: list[BlockInfo] = field(default_factory=list)
    
    @property
    def fixed_minutes(self) -> int:
        return sum(b.duration_min for b in self.fixed_blocks)
    
    def fixed_minutes_on_day(self, day_idx: int) -> int:
        return sum(b.duration_min for b in self.fixed_blocks if b.day_idx == day_idx)
    
    def fixed_tours_on_day(self, day_idx: int) -> int:
        return sum(b.tour_count for b in self.fixed_blocks if b.day_idx == day_idx)


# =============================================================================
# HELPERS
# =============================================================================

def time_to_minutes(t) -> int:
    """Convert time object to minutes from midnight."""
    return t.hour * 60 + t.minute


def block_to_info(block: Block, day_idx: int) -> BlockInfo:
    """Convert v4 Block to BlockInfo for LNS."""
    start_min = time_to_minutes(block.first_start)
    end_min = time_to_minutes(block.last_end)
    duration_min = int(block.total_work_hours * 60)
    return BlockInfo(
        block_id=block.id,
        day_idx=day_idx,
        start_min=start_min,
        end_min=end_min,
        duration_min=duration_min,
        tour_count=len(block.tours),
    )


def blocks_overlap(b1: BlockInfo, b2: BlockInfo) -> bool:
    """Check if two blocks overlap in time (same day assumed)."""
    return not (b1.end_min <= b2.start_min or b2.end_min <= b1.start_min)


DAY_MAP = {
    "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6,
    "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
    "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6,
}


def get_day_idx(day) -> int:
    """Get day index from Weekday or string."""
    if isinstance(day, Weekday):
        return DAY_MAP.get(day.value, 0)
    return DAY_MAP.get(str(day), 0)


# =============================================================================
# DESTROY OPERATOR
# =============================================================================

def destroy_drivers(
    assignments: list,  # list[DriverAssignment]
    fraction: float,
    rng: random.Random,
) -> tuple[list[DriverState], list[BlockInfo]]:
    """
    Destroy a fraction of drivers by removing their blocks.
    
    Returns:
        - driver_states: List of DriverState with fixed/destroyed blocks
        - blocks_to_repair: List of BlockInfo that need reassignment
    """
    # Sort for determinism
    sorted_assignments = sorted(assignments, key=lambda a: a.driver_id)
    
    # Select drivers to destroy
    num_to_destroy = max(1, int(len(sorted_assignments) * fraction))
    destroy_indices = rng.sample(range(len(sorted_assignments)), min(num_to_destroy, len(sorted_assignments)))
    destroy_set = set(destroy_indices)
    
    driver_states = []
    blocks_to_repair = []
    
    for idx, assignment in enumerate(sorted_assignments):
        driver = DriverState(
            driver_id=assignment.driver_id,
            driver_type=assignment.driver_type,
        )
        
        for block in sorted(assignment.blocks, key=lambda b: b.id):
            day_idx = get_day_idx(block.day)
            block_info = block_to_info(block, day_idx)
            
            if idx in destroy_set:
                driver.destroyed_blocks.append(block_info)
                blocks_to_repair.append(block_info)
            else:
                driver.fixed_blocks.append(block_info)
        
        driver_states.append(driver)
    
    logger.info(f"Destroyed {len(blocks_to_repair)} blocks from {num_to_destroy} drivers")
    return driver_states, blocks_to_repair


# =============================================================================
# REPAIR OPERATOR (CP-SAT)
# =============================================================================

def repair_assignments(
    driver_states: list[DriverState],
    blocks_to_repair: list[BlockInfo],
    config: LNSConfigV4,
    seed: int,
) -> dict[str, str]:
    """
    Repair by reassigning blocks using small CP-SAT.
    
    Returns:
        block_id -> driver_id mapping
    """
    if not blocks_to_repair:
        return {}
    
    model = cp_model.CpModel()
    
    # Sort for determinism
    blocks = sorted(blocks_to_repair, key=lambda b: b.block_id)
    drivers = sorted(driver_states, key=lambda d: d.driver_id)
    
    # Only consider drivers who had blocks (candidates)
    candidate_drivers = [d for d in drivers if d.fixed_blocks or d.destroyed_blocks]
    
    logger.info(f"Repair: {len(blocks)} blocks, {len(candidate_drivers)} candidate drivers")
    
    # Variables
    # x[b,d] = 1 if block b assigned to driver d
    x = {}
    for b in blocks:
        for d in candidate_drivers:
            x[b.block_id, d.driver_id] = model.NewBoolVar(f"x_{b.block_id}_{d.driver_id}")
    
    # used[d] = 1 if driver d has at least one repair block
    used = {}
    for d in candidate_drivers:
        used[d.driver_id] = model.NewBoolVar(f"used_{d.driver_id}")
    
    # ==========================================================================
    # Constraints
    # ==========================================================================
    
    # 1. Each block assigned to exactly one driver
    for b in blocks:
        model.Add(sum(x[b.block_id, d.driver_id] for d in candidate_drivers) == 1)
    
    # 2. Link used[d] >= x[b,d]
    for d in candidate_drivers:
        for b in blocks:
            model.Add(used[d.driver_id] >= x[b.block_id, d.driver_id])
    
    # 3. No overlap on same day
    for d in candidate_drivers:
        for day_idx in range(7):
            day_blocks = [b for b in blocks if b.day_idx == day_idx]
            # Add fixed blocks for this driver on this day
            fixed_on_day = [fb for fb in d.fixed_blocks if fb.day_idx == day_idx]
            
            # Check conflicts between repair blocks
            for i, b1 in enumerate(day_blocks):
                for b2 in day_blocks[i+1:]:
                    if blocks_overlap(b1, b2):
                        model.Add(x[b1.block_id, d.driver_id] + x[b2.block_id, d.driver_id] <= 1)
                
                # Check conflicts with fixed blocks
                for fb in fixed_on_day:
                    if blocks_overlap(b1, fb):
                        model.Add(x[b1.block_id, d.driver_id] == 0)
    
    # 4. Weekly hours constraint (FTE only)
    for d in candidate_drivers:
        if d.driver_type == "FTE":
            max_minutes = int(config.max_hours_per_fte * 60)
            repair_minutes = sum(
                b.duration_min * x[b.block_id, d.driver_id] for b in blocks
            )
            model.Add(repair_minutes + d.fixed_minutes <= max_minutes)
    
    # 5. Max tours per day
    for d in candidate_drivers:
        for day_idx in range(7):
            day_blocks = [b for b in blocks if b.day_idx == day_idx]
            if day_blocks:
                repair_tours = sum(b.tour_count * x[b.block_id, d.driver_id] for b in day_blocks)
                fixed_tours = d.fixed_tours_on_day(day_idx)
                model.Add(repair_tours + fixed_tours <= config.max_tours_per_day)
    
    # 6. Daily span constraint (simplified: check if any block would exceed span)
    # Full constraint with start_min_var/end_max_var is expensive; using simplified version
    for d in candidate_drivers:
        for day_idx in range(7):
            day_blocks = [b for b in blocks if b.day_idx == day_idx]
            fixed_on_day = [fb for fb in d.fixed_blocks if fb.day_idx == day_idx]
            
            if fixed_on_day:
                fixed_start = min(fb.start_min for fb in fixed_on_day)
                fixed_end = max(fb.end_min for fb in fixed_on_day)
                
                for b in day_blocks:
                    combined_start = min(fixed_start, b.start_min)
                    combined_end = max(fixed_end, b.end_min)
                    if combined_end - combined_start > config.max_daily_span_minutes:
                        # This block would violate span with fixed blocks
                        model.Add(x[b.block_id, d.driver_id] == 0)
    
    # ==========================================================================
    # Objective: minimize number of drivers used
    # ==========================================================================
    model.Minimize(sum(used[d.driver_id] for d in candidate_drivers))
    
    # ==========================================================================
    # Solve
    # ==========================================================================
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = config.repair_time_limit
    solver.parameters.search_branching = cp_model.FIXED_SEARCH
    solver.parameters.num_workers = 1  # Determinism
    
    status = solver.Solve(model)
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning(f"Repair failed with status {status}, keeping original")
        return {}
    
    # Extract solution
    result = {}
    for b in blocks:
        for d in candidate_drivers:
            if solver.Value(x[b.block_id, d.driver_id]):
                result[b.block_id] = d.driver_id
                break
    
    drivers_used = sum(1 for d in candidate_drivers if solver.Value(used[d.driver_id]))
    logger.info(f"Repair complete: {len(result)} blocks assigned to {drivers_used} drivers")
    
    return result


# =============================================================================
# APPLY REPAIR
# =============================================================================

def apply_repair(
    original_assignments: list,  # list[DriverAssignment]
    block_mapping: dict[str, str],  # block_id -> driver_id
) -> list:
    """
    Apply repair result to create new assignments.
    """
    from src.services.forecast_solver_v4 import DriverAssignment
    
    if not block_mapping:
        return original_assignments
    
    # Build driver -> blocks map
    driver_blocks = {}
    for assignment in original_assignments:
        driver_blocks[assignment.driver_id] = {
            "driver_type": assignment.driver_type,
            "blocks": [],
        }
    
    # Assign blocks based on repair mapping
    for assignment in original_assignments:
        for block in assignment.blocks:
            if block.id in block_mapping:
                target_driver = block_mapping[block.id]
            else:
                target_driver = assignment.driver_id
            
            if target_driver not in driver_blocks:
                driver_blocks[target_driver] = {
                    "driver_type": "FTE" if target_driver.startswith("FTE") else "PT",
                    "blocks": [],
                }
            driver_blocks[target_driver]["blocks"].append(block)
    
    # Build new assignments
    new_assignments = []
    for driver_id in sorted(driver_blocks.keys()):
        data = driver_blocks[driver_id]
        if data["blocks"]:
            total_hours = sum(b.total_work_hours for b in data["blocks"])
            days = len(set(b.day.value for b in data["blocks"]))
            new_assignments.append(DriverAssignment(
                driver_id=driver_id,
                driver_type=data["driver_type"],
                blocks=sorted(data["blocks"], key=lambda b: (b.day.value, b.first_start)),
                total_hours=total_hours,
                days_worked=days,
            ))
    
    return new_assignments


# =============================================================================
# MAIN LNS REFINER
# =============================================================================

def refine_assignments_v4(
    assignments: list,  # list[DriverAssignment]
    config: LNSConfigV4 = None,
) -> list:
    """
    Refine v4 driver assignments using LNS.
    
    Iteratively destroys part of the assignment and repairs with CP-SAT.
    """
    if config is None:
        config = LNSConfigV4()
    
    if not assignments:
        return assignments
    
    logger.info("=" * 60)
    logger.info("LNS V4 REFINEMENT START")
    logger.info(f"Config: iterations={config.max_iterations}, destroy={config.destroy_fraction}")
    logger.info("=" * 60)
    
    best_assignments = assignments
    best_driver_count = len([a for a in assignments if a.blocks])
    
    rng = random.Random(config.seed)
    
    for iteration in range(config.max_iterations):
        iter_seed = config.seed + iteration
        iter_rng = random.Random(iter_seed)
        
        logger.info(f"Iteration {iteration + 1}/{config.max_iterations}")
        
        # Destroy
        driver_states, blocks_to_repair = destroy_drivers(
            best_assignments,
            config.destroy_fraction,
            iter_rng,
        )
        
        if not blocks_to_repair:
            logger.info("No blocks to repair, skipping iteration")
            continue
        
        # Repair
        block_mapping = repair_assignments(
            driver_states,
            blocks_to_repair,
            config,
            iter_seed,
        )
        
        if not block_mapping:
            logger.info("Repair failed, keeping best")
            continue
        
        # Apply and evaluate
        new_assignments = apply_repair(best_assignments, block_mapping)
        new_driver_count = len([a for a in new_assignments if a.blocks])
        
        # Accept if strictly better
        if new_driver_count < best_driver_count:
            logger.info(f"Accepted: {new_driver_count} drivers (was {best_driver_count})")
            best_assignments = new_assignments
            best_driver_count = new_driver_count
        else:
            logger.info(f"Rejected: {new_driver_count} drivers (best {best_driver_count})")
    
    logger.info("=" * 60)
    logger.info(f"LNS V4 COMPLETE: {best_driver_count} drivers")
    logger.info("=" * 60)
    
    return best_assignments
