"""
CP-SAT Assignment Optimizer (Phase 2B)
======================================
Global optimization for driver assignment using slot-based modeling.

Replaces greedy assignment to minimize PT drivers through global decision-making.
"""

from dataclasses import dataclass
from typing import Optional
import logging
from collections import defaultdict

from ortools.sat.python import cp_model

from src.domain.models import Block, Weekday
from src.services.forecast_solver_v4 import ConfigV4, DriverAssignment

logger = logging.getLogger(__name__)

# Weekday mapping for constraints
WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def get_day_index(day: Weekday) -> int:
    """Convert Weekday enum to 0-6 index."""
    return WEEKDAY_ORDER.index(day.value)


def precompute_incompatible_pairs(
    blocks: list[Block],
    min_rest_minutes: int = 660
) -> list[tuple[str, str]]:
    """
    Precompute pairs of blocks that cannot be assigned to same driver (conflict graph).
    
    Blocks are incompatible if:
    1. They're on consecutive days AND rest < 11h
    2. One has 3 tours and the other is next day
    
    Returns:
        List of (block_id1, block_id2) tuples
    """
    incompatible = []
    
    # Sort blocks by day for efficiency
    blocks_by_day = defaultdict(list)
    for b in blocks:
        blocks_by_day[get_day_index(b.day)].append(b)
    
    # Check consecutive day pairs
    for day_idx in range(7):
        if day_idx + 1 not in blocks_by_day:
            continue
            
        today_blocks = blocks_by_day[day_idx]
        tomorrow_blocks = blocks_by_day[day_idx + 1]
        
        for b1 in today_blocks:
            for b2 in tomorrow_blocks:
                # Calculate rest time (end of b1 to start of b2 + 24h)
                b1_end_min = b1.last_end.hour * 60 + b1.last_end.minute
                b2_start_min = b2.first_start.hour * 60 + b2.first_start.minute
                rest = (1440 - b1_end_min) + b2_start_min  # Rest over midnight
                
                if rest < min_rest_minutes:
                    incompatible.append((b1.id, b2.id))
                
                # 3-tour recovery: if b1 has 3 tours, b2 (next day) is incompatible
                if len(b1.tours) >= 3:
                    incompatible.append((b1.id, b2.id))
    
    logger.info(f"Precomputed {len(incompatible)} incompatible block pairs")
    return incompatible


def assign_drivers_cpsat(
    blocks: list[Block],
    config: ConfigV4,
    warm_start: Optional[list[DriverAssignment]] = None,
    time_limit: float = 60.0
) -> tuple[list[DriverAssignment], dict]:
    """
    Assign blocks to drivers using CP-SAT global optimization.
    
    Uses slot-based modeling: drivers are abstract slots k=0..K-1
    
    Args:
        blocks: List of blocks to assign
        config: Solver configuration
        warm_start: Optional greedy assignment for hints
        time_limit: Solve time limit in seconds
    
    Returns:
        (assignments, stats)
    """
    logger.info(f"=== CP-SAT ASSIGNMENT START: {len(blocks)} blocks ===")
    
    if not blocks:
        return [], {"drivers_total": 0, "drivers_pt": 0}
    
    model = cp_model.CpModel()
    
    # Determine number of slots needed
    blocks_per_day = defaultdict(int)
    for b in blocks:
        blocks_per_day[get_day_index(b.day)] += 1
    max_blocks_day = max(blocks_per_day.values())
    K = max_blocks_day + 40  # Buffer for flexibility
    
    logger.info(f"Using {K} driver slots (max {max_blocks_day} blocks/day)")
    
    # ==========================================================================
    # VARIABLES
    # ==========================================================================
    
    x = {}  # x[block_id, slot_k] = 1 if block assigned to slot k
    used = {}  # used[slot_k] = 1 if slot k is used
    is_pt = {}  # is_pt[slot_k] = 1 if slot k is PT
    
    # Create assignment variables
    for b in blocks:
        for k in range(K):
            x[b.id, k] = model.NewBoolVar(f"x_{b.id}_{k}")
    
    # Create slot usage variables
    for k in range(K):
        used[k] = model.NewBoolVar(f"used_{k}")
        is_pt[k] = model.NewBoolVar(f"is_pt_{k}")
    
    logger.info(f"Created {len(blocks) * K} assignment variables, {2 * K} slot variables")
    
    # ==========================================================================
    # CONSTRAINTS
    # ==========================================================================
    
    # 1. Coverage: Each block assigned exactly once
    for b in blocks:
        model.Add(sum(x[b.id, k] for k in range(K)) == 1)
    
    # 2. Slot usage definition
    for k in range(K):
        # used[k] = 1 if any block assigned to slot k
        model.Add(sum(x[b.id, k] for b in blocks) > 0).OnlyEnforceIf(used[k])
        model.Add(sum(x[b.id, k] for b in blocks) == 0).OnlyEnforceIf(used[k].Not())
    
    # 3. One block per driver per day (simplifies overlap)
    for k in range(K):
        for day_idx in range(7):
            day_blocks = [b for b in blocks if get_day_index(b.day) == day_idx]
            if day_blocks:
                model.Add(sum(x[b.id, k] for b in day_blocks) <= 1)
    
    # 4. Incompatibility constraints (11h rest + 3-tour recovery)
    incompatible_pairs = precompute_incompatible_pairs(blocks)
    for b1_id, b2_id in incompatible_pairs:
        for k in range(K):
            model.Add(x[b1_id, k] + x[b2_id, k] <= 1)
    
    logger.info(f"Added {len(incompatible_pairs) * K} incompatibility constraints")
    
    # 5. FTE hour limits (42-53h weekly)
    for k in range(K):
        # Calculate total hours for this slot
        total_minutes = sum(
            b.total_work_minutes * x[b.id, k]
            for b in blocks
        )
        
        # If slot is FTE (not PT), enforce hour limits
        # min_hours constraint: total_minutes >= 42*60 OR slot is PT or slot is unused
        model.Add(total_minutes >= int(config.min_hours_per_fte * 60)).OnlyEnforceIf([used[k], is_pt[k].Not()])
        
        # max_hours constraint: total_minutes <= 53*60 OR slot is PT or slot is unused
        model.Add(total_minutes <= int(config.max_hours_per_fte * 60)).OnlyEnforceIf([used[k], is_pt[k].Not()])
    
    # ==========================================================================
    # OBJECTIVE
    # ==========================================================================
    
    # Lexicographic via large weight differences
    W_PT_DRIVER = 1_000_000  # Minimize PT drivers (HIGHEST PRIORITY)
    W_TOTAL_DRIVER = 1_000  # Minimize total drivers
    W_WEEKDAY_PT = 10  # Push PT to Saturday
    
    cost_terms = []
    
    # PT driver cost: need intermediate variable for is_pt[k] AND used[k]
    for k in range(K):
        # Create intermediate: pt_used[k] = is_pt[k] AND used[k]
        pt_used_k = model.NewBoolVar(f"pt_used_{k}")
        model.AddBoolAnd([is_pt[k], used[k]]).OnlyEnforceIf(pt_used_k)
        model.AddBoolOr([is_pt[k].Not(), used[k].Not()]).OnlyEnforceIf(pt_used_k.Not())
        cost_terms.append(W_PT_DRIVER * pt_used_k)
    
    # Total driver cost
    for k in range(K):
        cost_terms.append(W_TOTAL_DRIVER * used[k])
    
    # Weekday PT assignment cost
    for b in blocks:
        day_idx = get_day_index(b.day)
        if day_idx < 5:  # Mon-Fri
            for k in range(K):
                # pt_weekday_assignment[b,k] = is_pt[k] AND x[b.id,k]
                pt_weekday_bk = model.NewBoolVar(f"pt_weekday_{b.id}_{k}")
                model.AddBoolAnd([is_pt[k], x[b.id, k]]).OnlyEnforceIf(pt_weekday_bk)
                model.AddBoolOr([is_pt[k].Not(), x[b.id, k].Not()]).OnlyEnforceIf(pt_weekday_bk.Not())
                cost_terms.append(W_WEEKDAY_PT * pt_weekday_bk)
    
    model.Minimize(sum(cost_terms))
    
    logger.info("Objective: Minimize PT drivers > total drivers > weekday PT")
    
    # ==========================================================================
    # WARM START (if provided)
    # ==========================================================================
    
    if warm_start:
        logger.info("Adding warm start hints from greedy assignment")
        slot_map = {}
        for idx, assignment in enumerate(warm_start):
            if assignment.blocks:
                k = idx
                slot_map[assignment.driver_id] = k
                model.AddHint(used[k], 1)
                model.AddHint(is_pt[k], 1 if assignment.driver_type == "PT" else 0)
                
                for block in assignment.blocks:
                    model.AddHint(x[block.id, k], 1)
    
    # ==========================================================================
    # SOLVE
    # ==========================================================================
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # Deterministic
    solver.parameters.log_search_progress = True
    
    logger.info(f"Solving with time limit {time_limit}s...")
    status = solver.Solve(model)
    
    logger.info(f"Status: {solver.StatusName(status)}")
    logger.info(f"Solve time: {solver.WallTime():.2f}s")
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.error(f"CP-SAT failed with status {solver.StatusName(status)}")
        return [], {"error": f"CP-SAT status: {solver.StatusName(status)}"}
    
    # ==========================================================================
    # EXTRACT SOLUTION
    # ==========================================================================
    
    assignments = convert_solution_to_assignments(
        blocks, x, used, is_pt, solver, K
    )
    
    # Calculate stats
    pt_count = sum(1 for a in assignments if a.driver_type == "PT")
    fte_count = sum(1 for a in assignments if a.driver_type == "FTE")
    
    stats = {
        "drivers_total": len(assignments),
        "drivers_fte": fte_count,
        "drivers_pt": pt_count,
        "solve_time": solver.WallTime(),
        "status": solver.StatusName(status),
    }
    
    logger.info(f"=== CP-SAT ASSIGNMENT COMPLETE ===")
    logger.info(f"Drivers: {fte_count} FTE + {pt_count} PT = {len(assignments)}")
    logger.info(f"Objective value: {solver.ObjectiveValue()}")
    
    return assignments, stats


def convert_solution_to_assignments(
    blocks: list[Block],
    x: dict,
    used: dict,
    is_pt: dict,
    solver: cp_model.CpSolver,
    K: int
) -> list[DriverAssignment]:
    """
    Convert CP-SAT solution (slots) to DriverAssignment objects.
    
    Assigns concrete driver IDs: FTE001, FTE002, ..., PT001, PT002, ...
    """
    # Group blocks by assigned slot
    slot_blocks = defaultdict(list)
    for b in blocks:
        for k in range(K):
            if solver.Value(x[b.id, k]) == 1:
                slot_blocks[k].append(b)
                break
    
    # Create assignments
    assignments = []
    fte_counter = 1
    pt_counter = 1
    
    # Sort slots by: FTE first, then by total hours (deterministic)
    slot_keys = sorted(
        slot_blocks.keys(),
        key=lambda k: (
            solver.Value(is_pt[k]),  # FTE first (0 < 1)
            sum(b.total_work_hours for b in slot_blocks[k]),  # Hours
            k  # Slot index (deterministic)
        )
    )
    
    for k in slot_keys:
        blocks_assigned = slot_blocks[k]
        is_pt_slot = solver.Value(is_pt[k]) == 1
        
        if is_pt_slot:
            driver_id = f"PT{pt_counter:03d}"
            pt_counter += 1
        else:
            driver_id = f"FTE{fte_counter:03d}"
            fte_counter += 1
        
        assignment = DriverAssignment(
            driver_id=driver_id,
            driver_type="PT" if is_pt_slot else "FTE",
            blocks=list(blocks_assigned),
            total_hours=sum(b.total_work_hours for b in blocks_assigned),
        )
        assignments.append(assignment)
    
    return assignments
