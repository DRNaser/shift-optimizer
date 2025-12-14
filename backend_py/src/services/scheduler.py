"""
SHIFT OPTIMIZER - Baseline Scheduler
=====================================
Greedy feasible-first assignment of blocks to drivers.

This is the BASELINE scheduler - simple but correct.
The Validator is the SINGLE SOURCE OF TRUTH for validity.
The Scheduler respects Validator decisions.

Phase 2 will add CP-SAT for better optimization.
Phase 3 will add LNS for refinement.
"""

from collections import defaultdict
from datetime import date
from typing import NamedTuple
import uuid

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
from src.domain.validator import Validator
from src.services.block_builder import BlockBuilder, build_blocks_greedy


class SchedulerConfig(NamedTuple):
    """Configuration for scheduler behavior."""
    prefer_larger_blocks: bool = True  # Prefer 3er > 2er > 1er
    seed: int | None = None  # For reproducibility
    max_iterations: int = 1000  # Safety limit


def generate_plan_id() -> str:
    """Generate a unique plan ID."""
    return f"P-{uuid.uuid4().hex[:8]}"


class BaselineScheduler:
    """
    Greedy baseline scheduler.
    
    Strategy:
    1. Build blocks from tours (greedy: prefer larger)
    2. Sort blocks by priority (day, then size descending, then start time)
    3. For each block, find first available driver
    4. Assign using Validator (which enforces all constraints)
    5. Unassigned blocks get reason codes
    
    This is NOT optimal. It's correct and deterministic.
    Better solutions in Phase 2 (CP-SAT).
    """
    
    def __init__(
        self,
        tours: list[Tour],
        drivers: list[Driver],
        config: SchedulerConfig = SchedulerConfig()
    ):
        self.tours = tours
        self.drivers = drivers
        self.config = config
        
        # Build blocks
        self.blocks = build_blocks_greedy(tours, prefer_larger=config.prefer_larger_blocks)
        
        # Initialize validator
        self.validator = Validator(drivers)
    
    def schedule(self, week_start: date) -> WeeklyPlan:
        """
        Create a weekly schedule.
        
        Returns a complete WeeklyPlan with:
        - All valid assignments
        - All unassigned tours with reasons
        - Validation result
        - Statistics
        """
        assignments: list[DriverAssignment] = []
        assigned_tour_ids: set[str] = set()
        block_failures: dict[str, tuple[list[ReasonCode], str]] = {}  # block_id -> (reasons, details)
        
        # Reset validator state
        self.validator.reset()
        
        # Sort blocks for assignment priority
        # Priority: larger blocks first, then by day and start time
        sorted_blocks = sorted(
            self.blocks,
            key=lambda b: (
                -len(b.tours),  # Larger blocks first
                list(Weekday).index(b.day),  # Earlier days first
                b.first_start  # Earlier start times first
            )
        )
        
        # Try to assign each block
        for block in sorted_blocks:
            # Check if all tours in this block are still unassigned
            if any(t.id in assigned_tour_ids for t in block.tours):
                continue  # Skip - some tours already used
            
            # Try each driver
            assigned = False
            all_reasons: list[tuple[str, list[ReasonCode], str]] = []
            
            for driver in self.drivers:
                can, reasons, explanation = self.validator.can_assign(driver.id, block)
                
                if can:
                    # Assign this block
                    result = self.validator.validate_and_commit(driver.id, block)
                    
                    if result.is_valid:
                        # Create assignment
                        assigned_block = Block(
                            id=block.id,
                            day=block.day,
                            tours=block.tours,
                            driver_id=driver.id
                        )
                        assignments.append(DriverAssignment(
                            driver_id=driver.id,
                            day=block.day,
                            block=assigned_block
                        ))
                        
                        # Mark tours as used
                        for tour in block.tours:
                            assigned_tour_ids.add(tour.id)
                        
                        assigned = True
                        break
                else:
                    all_reasons.append((driver.id, reasons, explanation))
            
            if not assigned:
                # Aggregate failure reasons
                if all_reasons:
                    # Get the most common reason across all drivers
                    reason_counts: dict[ReasonCode, int] = defaultdict(int)
                    for _, reasons, _ in all_reasons:
                        for r in reasons:
                            reason_counts[r] += 1
                    
                    top_reasons = sorted(reason_counts.keys(), key=lambda r: -reason_counts[r])[:3]
                    details = "; ".join(f"{d}: {e}" for d, _, e in all_reasons[:2])
                    block_failures[block.id] = (top_reasons, details)
                else:
                    block_failures[block.id] = ([ReasonCode.NO_AVAILABLE_DRIVER], "No drivers available")
        
        # Build unassigned tours list
        unassigned_tours: list[UnassignedTour] = []
        for tour in self.tours:
            if tour.id not in assigned_tour_ids:
                # Find why this tour wasn't assigned
                # Look at blocks containing this tour
                relevant_failures = []
                for block in self.blocks:
                    if any(t.id == tour.id for t in block.tours):
                        if block.id in block_failures:
                            relevant_failures.append(block_failures[block.id])
                
                if relevant_failures:
                    # Aggregate reasons from all failed blocks
                    all_reasons_set: set[ReasonCode] = set()
                    all_details: list[str] = []
                    for reasons, details in relevant_failures:
                        all_reasons_set.update(reasons)
                        if details:
                            all_details.append(details)
                    
                    unassigned_tours.append(UnassignedTour(
                        tour=tour,
                        reason_codes=list(all_reasons_set) or [ReasonCode.INFEASIBLE],
                        details="; ".join(all_details[:2]) if all_details else "No valid assignment found"
                    ))
                else:
                    unassigned_tours.append(UnassignedTour(
                        tour=tour,
                        reason_codes=[ReasonCode.INFEASIBLE],
                        details="Tour could not be assigned to any block or driver"
                    ))
        
        # Calculate statistics
        block_counts = {
            BlockType.SINGLE: sum(1 for a in assignments if len(a.block.tours) == 1),
            BlockType.DOUBLE: sum(1 for a in assignments if len(a.block.tours) == 2),
            BlockType.TRIPLE: sum(1 for a in assignments if len(a.block.tours) == 3),
        }
        
        # Calculate utilization
        unique_drivers = set(a.driver_id for a in assignments)
        total_hours_assigned = sum(a.block.total_work_hours for a in assignments)
        max_possible_hours = len(unique_drivers) * 55.0  # Max weekly hours per driver
        utilization = total_hours_assigned / max_possible_hours if max_possible_hours > 0 else 0.0
        
        stats = WeeklyPlanStats(
            total_drivers=len(unique_drivers),
            total_tours_input=len(self.tours),
            total_tours_assigned=len(assigned_tour_ids),
            total_tours_unassigned=len(unassigned_tours),
            block_counts=block_counts,
            average_driver_utilization=utilization
        )
        
        # Create and validate final plan
        plan = WeeklyPlan(
            id=generate_plan_id(),
            week_start=week_start,
            assignments=assignments,
            unassigned_tours=unassigned_tours,
            validation=ValidationResult(is_valid=True),  # Will be updated
            stats=stats,
            version="1.0.0",
            solver_seed=self.config.seed
        )
        
        # Final validation
        validation = self.validator.validate_plan(plan)
        
        # Return plan with final validation
        return WeeklyPlan(
            id=plan.id,
            week_start=plan.week_start,
            assignments=plan.assignments,
            unassigned_tours=plan.unassigned_tours,
            validation=validation,
            stats=plan.stats,
            version=plan.version,
            solver_seed=plan.solver_seed
        )


def create_schedule(
    tours: list[Tour],
    drivers: list[Driver],
    week_start: date,
    config: SchedulerConfig = SchedulerConfig()
) -> WeeklyPlan:
    """
    Convenience function to create a schedule.
    
    This is the main entry point for scheduling.
    """
    scheduler = BaselineScheduler(tours, drivers, config)
    return scheduler.schedule(week_start)
