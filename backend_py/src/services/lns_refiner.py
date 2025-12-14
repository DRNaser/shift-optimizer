"""
SHIFT OPTIMIZER - LNS Refiner
==============================
Large Neighborhood Search for iterative solution improvement.

LNS Strategy:
1. Start with CP-SAT solution
2. Destroy: Remove some blocks from solution
3. Repair: Re-optimize removed blocks using CP-SAT
4. Accept if better, repeat

Key principle: RESPECT USER LOCKS
"""

from collections import defaultdict
from datetime import date
from enum import Enum
from typing import NamedTuple
import random

from ortools.sat.python import cp_model

from src.domain.models import (
    Block,
    BlockType,
    Driver,
    DriverAssignment,
    ReasonCode,
    Tour,
    UnassignedTour,
    ValidationResult,
    Weekday,
    WeeklyPlan,
    WeeklyPlanStats,
)
from src.domain.constraints import HARD_CONSTRAINTS
from src.domain.validator import Validator
from src.services.block_builder import build_blocks_greedy
from src.services.cpsat_solver import (
    CPSATConfig,
    CPSATSchedulerModel,
    create_cpsat_schedule,
    generate_plan_id,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

class DestroyStrategy(Enum):
    """Destroy strategy for LNS."""
    RANDOM = "random"  # Random blocks
    DAY = "day"  # All blocks on a random day
    DRIVER = "driver"  # All blocks for a random driver
    WORST = "worst"  # Blocks with lowest utilization
    SHAW = "shaw"  # Related blocks (same day/driver neighborhood)


class LNSConfig(NamedTuple):
    """Configuration for LNS refiner."""
    max_iterations: int = 10
    destroy_fraction: float = 0.3  # Fraction of blocks to destroy
    destroy_strategy: DestroyStrategy = DestroyStrategy.RANDOM
    repair_time_limit: float = 5.0  # Time limit for repair CP-SAT
    seed: int | None = None
    accept_equal: bool = True  # Accept solutions with equal objective


# =============================================================================
# DESTROY OPERATORS
# =============================================================================

class DestroyResult(NamedTuple):
    """Result of destroy operation."""
    kept_assignments: list[DriverAssignment]
    destroyed_blocks: list[Block]
    freed_tours: list[Tour]


def destroy_random(
    assignments: list[DriverAssignment],
    fraction: float,
    rng: random.Random,
    locked_blocks: set[str] | None = None
) -> DestroyResult:
    """
    Destroy random blocks.
    
    Respects locked blocks.
    """
    locked = locked_blocks or set()
    
    # Separate locked and unlocked
    unlocked = [a for a in assignments if a.block.id not in locked]
    locked_assignments = [a for a in assignments if a.block.id in locked]
    
    # Calculate how many to destroy
    num_destroy = max(1, int(len(unlocked) * fraction))
    
    # Random selection
    to_destroy = rng.sample(unlocked, min(num_destroy, len(unlocked)))
    to_destroy_ids = {a.block.id for a in to_destroy}
    
    kept = locked_assignments + [a for a in unlocked if a.block.id not in to_destroy_ids]
    destroyed_blocks = [a.block for a in to_destroy]
    freed_tours = [t for block in destroyed_blocks for t in block.tours]
    
    return DestroyResult(kept, destroyed_blocks, freed_tours)


def destroy_by_day(
    assignments: list[DriverAssignment],
    rng: random.Random,
    locked_blocks: set[str] | None = None
) -> DestroyResult:
    """
    Destroy all blocks on a random day.
    """
    locked = locked_blocks or set()
    
    # Group by day
    by_day: dict[Weekday, list[DriverAssignment]] = defaultdict(list)
    for a in assignments:
        by_day[a.day].append(a)
    
    # Find days with unlocked blocks
    days_with_unlocked = [
        day for day, assigns in by_day.items()
        if any(a.block.id not in locked for a in assigns)
    ]
    
    if not days_with_unlocked:
        # Nothing to destroy
        return DestroyResult(assignments, [], [])
    
    # Pick random day
    target_day = rng.choice(days_with_unlocked)
    
    kept = []
    destroyed_blocks = []
    
    for a in assignments:
        if a.day == target_day and a.block.id not in locked:
            destroyed_blocks.append(a.block)
        else:
            kept.append(a)
    
    freed_tours = [t for block in destroyed_blocks for t in block.tours]
    
    return DestroyResult(kept, destroyed_blocks, freed_tours)


def destroy_by_driver(
    assignments: list[DriverAssignment],
    rng: random.Random,
    locked_blocks: set[str] | None = None
) -> DestroyResult:
    """
    Destroy all blocks for a random driver.
    """
    locked = locked_blocks or set()
    
    # Group by driver
    by_driver: dict[str, list[DriverAssignment]] = defaultdict(list)
    for a in assignments:
        by_driver[a.driver_id].append(a)
    
    # Find drivers with unlocked blocks
    drivers_with_unlocked = [
        driver_id for driver_id, assigns in by_driver.items()
        if any(a.block.id not in locked for a in assigns)
    ]
    
    if not drivers_with_unlocked:
        return DestroyResult(assignments, [], [])
    
    # Pick random driver
    target_driver = rng.choice(drivers_with_unlocked)
    
    kept = []
    destroyed_blocks = []
    
    for a in assignments:
        if a.driver_id == target_driver and a.block.id not in locked:
            destroyed_blocks.append(a.block)
        else:
            kept.append(a)
    
    freed_tours = [t for block in destroyed_blocks for t in block.tours]
    
    return DestroyResult(kept, destroyed_blocks, freed_tours)


def destroy_worst(
    assignments: list[DriverAssignment],
    fraction: float,
    locked_blocks: set[str] | None = None
) -> DestroyResult:
    """
    Destroy blocks with worst utilization (smallest blocks first).
    """
    locked = locked_blocks or set()
    
    # Separate locked and unlocked
    unlocked = [a for a in assignments if a.block.id not in locked]
    locked_assignments = [a for a in assignments if a.block.id in locked]
    
    # Sort by block size (ascending - worst first)
    unlocked.sort(key=lambda a: len(a.block.tours))
    
    # Calculate how many to destroy
    num_destroy = max(1, int(len(unlocked) * fraction))
    
    to_destroy = unlocked[:num_destroy]
    to_destroy_ids = {a.block.id for a in to_destroy}
    
    kept = locked_assignments + [a for a in unlocked if a.block.id not in to_destroy_ids]
    destroyed_blocks = [a.block for a in to_destroy]
    freed_tours = [t for block in destroyed_blocks for t in block.tours]
    
    return DestroyResult(kept, destroyed_blocks, freed_tours)


def destroy(
    assignments: list[DriverAssignment],
    strategy: DestroyStrategy,
    fraction: float,
    rng: random.Random,
    locked_blocks: set[str] | None = None
) -> DestroyResult:
    """
    Destroy blocks using specified strategy.
    """
    if strategy == DestroyStrategy.RANDOM:
        return destroy_random(assignments, fraction, rng, locked_blocks)
    elif strategy == DestroyStrategy.DAY:
        return destroy_by_day(assignments, rng, locked_blocks)
    elif strategy == DestroyStrategy.DRIVER:
        return destroy_by_driver(assignments, rng, locked_blocks)
    elif strategy == DestroyStrategy.WORST:
        return destroy_worst(assignments, fraction, locked_blocks)
    else:
        # Default to random
        return destroy_random(assignments, fraction, rng, locked_blocks)


# =============================================================================
# REPAIR OPERATOR
# =============================================================================

def repair(
    freed_tours: list[Tour],
    existing_assignments: list[DriverAssignment],
    all_tours: list[Tour],
    drivers: list[Driver],
    config: CPSATConfig
) -> list[DriverAssignment]:
    """
    Repair by re-optimizing freed tours with CP-SAT.
    
    Respects existing assignments by pre-committing them to validator.
    """
    if not freed_tours:
        return []
    
    # Build partial model for freed tours only
    validator = Validator(drivers)
    
    # Pre-commit existing assignments to validator
    for assignment in existing_assignments:
        validator.validate_and_commit(assignment.driver_id, assignment.block)
    
    # Build blocks from freed tours
    blocks = build_blocks_greedy(freed_tours, prefer_larger=config.prefer_larger_blocks)
    
    # Create mini CP-SAT model
    model = cp_model.CpModel()
    
    # Index tours by block
    tour_to_blocks: dict[str, list[int]] = defaultdict(list)
    for b_idx, block in enumerate(blocks):
        for tour in block.tours:
            tour_to_blocks[tour.id].append(b_idx)
    
    # Variables
    assignment_vars: dict[tuple[int, int], cp_model.IntVar] = {}
    
    for b_idx, block in enumerate(blocks):
        for d_idx, driver in enumerate(drivers):
            # Check if assignment is feasible given existing commitment
            can_assign, _, _ = validator.can_assign(driver.id, block)
            if can_assign:
                var_name = f"repair_b{b_idx}_d{d_idx}"
                assignment_vars[(b_idx, d_idx)] = model.NewBoolVar(var_name)
    
    # Constraints: each block to at most one driver
    for b_idx in range(len(blocks)):
        vars_for_block = [
            assignment_vars[(b_idx, d_idx)]
            for d_idx in range(len(drivers))
            if (b_idx, d_idx) in assignment_vars
        ]
        if vars_for_block:
            model.Add(sum(vars_for_block) <= 1)
    
    # Each tour in at most one assigned block
    for tour in freed_tours:
        blocks_with_tour = tour_to_blocks[tour.id]
        vars_for_tour = []
        for b_idx in blocks_with_tour:
            for d_idx in range(len(drivers)):
                if (b_idx, d_idx) in assignment_vars:
                    vars_for_tour.append(assignment_vars[(b_idx, d_idx)])
        if vars_for_tour:
            model.Add(sum(vars_for_tour) <= 1)
    
    # Objective: maximize tours + prefer larger blocks
    objective_terms = []
    for b_idx, block in enumerate(blocks):
        num_tours = len(block.tours)
        for d_idx in range(len(drivers)):
            if (b_idx, d_idx) in assignment_vars:
                objective_terms.append(assignment_vars[(b_idx, d_idx)] * num_tours * 1000)
                objective_terms.append(assignment_vars[(b_idx, d_idx)] * num_tours ** 2 * 10)
    
    if objective_terms:
        model.Maximize(sum(objective_terms))
    
    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_seconds
    if config.seed is not None:
        solver.parameters.random_seed = config.seed
    
    status = solver.Solve(model)
    
    # Extract new assignments
    new_assignments: list[DriverAssignment] = []
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (b_idx, d_idx), var in assignment_vars.items():
            if solver.Value(var) == 1:
                block = blocks[b_idx]
                driver = drivers[d_idx]
                
                assigned_block = Block(
                    id=block.id,
                    day=block.day,
                    tours=block.tours,
                    driver_id=driver.id
                )
                
                new_assignments.append(DriverAssignment(
                    driver_id=driver.id,
                    day=block.day,
                    block=assigned_block
                ))
    
    return new_assignments


# =============================================================================
# LNS REFINER
# =============================================================================

def calculate_objective(plan: WeeklyPlan) -> float:
    """
    Calculate objective value for comparison.
    
    Higher is better:
    - +1000 per tour assigned
    - +10 * block_size^2 for larger blocks
    - -1 per driver used
    """
    tours_assigned = plan.stats.total_tours_assigned * 1000
    
    block_bonus = 0
    for a in plan.assignments:
        block_bonus += len(a.block.tours) ** 2 * 10
    
    driver_penalty = plan.stats.total_drivers
    
    return tours_assigned + block_bonus - driver_penalty


class LNSRefiner:
    """
    Large Neighborhood Search refiner.
    
    Iteratively improves a solution by:
    1. Destroying part of the solution
    2. Repairing with CP-SAT
    3. Accepting if improved
    """
    
    def __init__(
        self,
        initial_plan: WeeklyPlan,
        tours: list[Tour],
        drivers: list[Driver],
        config: LNSConfig = LNSConfig(),
        locked_blocks: set[str] | None = None
    ):
        self.current_plan = initial_plan
        self.best_plan = initial_plan
        self.tours = tours
        self.drivers = drivers
        self.config = config
        self.locked_blocks = locked_blocks or set()
        
        # Initialize RNG
        self.rng = random.Random(config.seed)
        
        # Track objective
        self.current_objective = calculate_objective(initial_plan)
        self.best_objective = self.current_objective
        
        # Iteration history
        self.history: list[dict] = []
    
    def refine(self) -> WeeklyPlan:
        """
        Run LNS refinement loop.
        
        Returns the best plan found.
        """
        for iteration in range(self.config.max_iterations):
            # Destroy
            destroy_result = destroy(
                self.current_plan.assignments,
                self.config.destroy_strategy,
                self.config.destroy_fraction,
                self.rng,
                self.locked_blocks
            )
            
            if not destroy_result.freed_tours:
                # Nothing to repair
                self.history.append({
                    "iteration": iteration,
                    "action": "skip",
                    "reason": "no_freed_tours"
                })
                continue
            
            # Repair
            cpsat_config = CPSATConfig(
                time_limit_seconds=self.config.repair_time_limit,
                seed=self.config.seed,
                prefer_larger_blocks=True
            )
            
            new_assignments = repair(
                destroy_result.freed_tours,
                destroy_result.kept_assignments,
                self.tours,
                self.drivers,
                cpsat_config
            )
            
            # Build candidate solution
            candidate_assignments = destroy_result.kept_assignments + new_assignments
            
            # Build unassigned tours
            assigned_tour_ids = set()
            for a in candidate_assignments:
                for t in a.block.tours:
                    assigned_tour_ids.add(t.id)
            
            unassigned = []
            for tour in self.tours:
                if tour.id not in assigned_tour_ids:
                    unassigned.append(UnassignedTour(
                        tour=tour,
                        reason_codes=[ReasonCode.INFEASIBLE],
                        details="Not assigned during LNS refinement"
                    ))
            
            # Calculate stats
            block_counts = {
                BlockType.SINGLE: sum(1 for a in candidate_assignments if len(a.block.tours) == 1),
                BlockType.DOUBLE: sum(1 for a in candidate_assignments if len(a.block.tours) == 2),
                BlockType.TRIPLE: sum(1 for a in candidate_assignments if len(a.block.tours) == 3),
            }
            
            unique_drivers = set(a.driver_id for a in candidate_assignments)
            total_hours = sum(a.block.total_work_hours for a in candidate_assignments)
            max_possible = len(unique_drivers) * HARD_CONSTRAINTS.MAX_WEEKLY_HOURS
            utilization = total_hours / max_possible if max_possible > 0 else 0.0
            
            candidate_plan = WeeklyPlan(
                id=generate_plan_id(),
                week_start=self.current_plan.week_start,
                assignments=candidate_assignments,
                unassigned_tours=unassigned,
                validation=ValidationResult(is_valid=True),
                stats=WeeklyPlanStats(
                    total_drivers=len(unique_drivers),
                    total_tours_input=len(self.tours),
                    total_tours_assigned=len(assigned_tour_ids),
                    total_tours_unassigned=len(unassigned),
                    block_counts=block_counts,
                    average_driver_utilization=utilization
                ),
                version="1.0.0",
                solver_seed=self.config.seed
            )
            
            # Calculate objective
            candidate_objective = calculate_objective(candidate_plan)
            
            # Accept?
            accept = False
            if candidate_objective > self.current_objective:
                accept = True
            elif candidate_objective == self.current_objective and self.config.accept_equal:
                accept = True
            
            if accept:
                self.current_plan = candidate_plan
                self.current_objective = candidate_objective
                
                if candidate_objective > self.best_objective:
                    self.best_plan = candidate_plan
                    self.best_objective = candidate_objective
            
            self.history.append({
                "iteration": iteration,
                "destroyed": len(destroy_result.destroyed_blocks),
                "repaired": len(new_assignments),
                "candidate_objective": candidate_objective,
                "accepted": accept,
                "best_objective": self.best_objective
            })
        
        return self.best_plan


def refine_schedule(
    plan: WeeklyPlan,
    tours: list[Tour],
    drivers: list[Driver],
    config: LNSConfig = LNSConfig(),
    locked_blocks: set[str] | None = None
) -> WeeklyPlan:
    """
    Convenience function to refine a schedule using LNS.
    """
    refiner = LNSRefiner(plan, tours, drivers, config, locked_blocks)
    return refiner.refine()
