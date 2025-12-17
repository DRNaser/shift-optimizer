"""
CP-SAT Assignment Optimizer (Phase 2B) - SCALABLE BIG-M FORMULATION
====================================================================
Global optimization for driver assignment using efficient constraint programming.

Key Features:
- Big-M rest constraints (1K constraints vs 5.95M pairwise)
- Fixed FTE/PT slot groups (no boolean products)
- Linear time expressions for rest calculation
- PT fragmentation penalties (days & under-utilization)
- Deterministic search with fixed branching
"""

from dataclasses import dataclass
from typing import Optional
import logging
from collections import defaultdict
import math

from ortools.sat.python import cp_model

from src.domain.models import Block, Weekday
from src.services.forecast_solver_v4 import ConfigV4, DriverAssignment

logger = logging.getLogger(__name__)

# Weekday mapping
WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def get_day_index(day: Weekday) -> int:
    """Convert Weekday enum to 0-6 index."""
    return WEEKDAY_ORDER.index(day.value)


def assign_drivers_cpsat(
    blocks: list[Block],
    config: ConfigV4,
    warm_start: Optional[list[DriverAssignment]] = None,
    time_limit: float = 60.0
) -> tuple[list[DriverAssignment], dict]:
    """
    Assign blocks to drivers using CP-SAT with Big-M rest constraints.
    
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
    
    # =========================================================================
    # SLOT ALLOCATION (REDUCED FOR PERFORMANCE)
    # =========================================================================
    
    total_hours = sum(b.total_work_hours for b in blocks)
    estimated_fte = math.ceil(total_hours / config.min_hours_per_fte)
    
    K_FTE = estimated_fte + 5  # Tighter buffer for efficiency
    K_PT = 20  # Reduced from 60 to minimize variables
    K_TOTAL = K_FTE + K_PT
    
    FTE_SLOTS = range(K_FTE)
    PT_SLOTS = range(K_FTE, K_TOTAL)
    
    logger.info(f"Slot allocation: {K_FTE} FTE + {K_PT} PT = {K_TOTAL} total")
    
    # =========================================================================
    # PRECOMPUTE BLOCK ARRAYS (for efficiency)
    # =========================================================================
    
    # Sort blocks deterministically
    sorted_blocks = sorted(blocks, key=lambda b: (b.day.value, b.first_start, b.id))
    B = len(sorted_blocks)
    
    # Precompute block properties
    day = [get_day_index(b.day) for b in sorted_blocks]
    start = [b.first_start.hour * 60 + b.first_start.minute for b in sorted_blocks]
    end = [b.last_end.hour * 60 + b.last_end.minute for b in sorted_blocks]
    dur = [b.total_work_minutes for b in sorted_blocks]
    tours = [len(b.tours) for b in sorted_blocks]
    
    # Group blocks by day for efficient iteration
    blocks_by_day = defaultdict(list)
    for i, b in enumerate(sorted_blocks):
        blocks_by_day[day[i]].append(i)
    
    logger.info(f"Preprocessed {B} blocks: {len(blocks_by_day)} active days")
    
    # =========================================================================
    # VARIABLES
    # =========================================================================
    
    # x[i,k] = 1 if block i assigned to slot k
    x = {}
    for i in range(B):
        for k in range(K_TOTAL):
            x[i, k] = model.NewBoolVar(f"x_{i}_{k}")
    
    # assigned[k,d] = 1 if slot k has a block on day d
    assigned = {}
    for k in range(K_TOTAL):
        for d in range(7):
            assigned[k, d] = model.NewBoolVar(f"assigned_{k}_{d}")
    
    # used[k] = 1 if slot k is used in week
    used = {}
    for k in range(K_TOTAL):
        used[k] = model.NewBoolVar(f"used_{k}")
    
    # heavy[k,d] = 1 if slot k has 3-tour block on day d
    heavy = {}
    for k in range(K_TOTAL):
        for d in range(7):
            heavy[k, d] = model.NewBoolVar(f"heavy_{k}_{d}")
    
    logger.info(f"Created {B * K_TOTAL} assignment vars, {K_TOTAL * 14} auxiliary vars")
    
    # =========================================================================
    # CONSTRAINTS
    # =========================================================================
    
    # 1. Each block assigned exactly once
    for i in range(B):
        model.Add(sum(x[i, k] for k in range(K_TOTAL)) == 1)
    
    # 2. At most one block per day per slot + link assigned[k,d]
    for k in range(K_TOTAL):
        for d in range(7):
            day_blocks = blocks_by_day.get(d, [])
            if day_blocks:
                model.Add(sum(x[i, k] for i in day_blocks) <= 1)
                # assigned[k,d] = sum of x[i,k] for blocks on day d
                model.Add(assigned[k, d] == sum(x[i, k] for i in day_blocks))
            else:
                model.Add(assigned[k, d] == 0)
    
    # 3. used[k] linking (efficient)
    for k in range(K_TOTAL):
        # used[k] >= assigned[k,d] for all days
        for d in range(7):
            model.Add(used[k] >= assigned[k, d])
        # used[k] <= sum of assigned (tightening)
        model.Add(used[k] <= sum(assigned[k, d] for d in range(7)))
    
    logger.info(f"Added coverage and slot linkage constraints")
    
    # 4. FTE weekly hour limits (hard max only)
    for k in FTE_SLOTS:
        total_minutes = sum(dur[i] * x[i, k] for i in range(B))
        max_minutes = int(config.max_hours_per_fte * 60)
        model.Add(total_minutes <= max_minutes)
    
    # 5. Big-M Rest Constraint (11h minimum between consecutive days)
    M = 3000  # Big-M constant (safe for minute ranges)
    min_rest_minutes = 11 * 60
    
    # Define start/end expressions for each slot/day
    start_expr = {}
    end_expr = {}
    
    for k in range(K_TOTAL):
        for d in range(7):
            day_blocks = blocks_by_day.get(d, [])
            if day_blocks:
                start_expr[k, d] = sum(start[i] * x[i, k] for i in day_blocks)
                end_expr[k, d] = sum(end[i] * x[i, k] for i in day_blocks)
            else:
                start_expr[k, d] = 0
                end_expr[k, d] = 0
    
    # Enforce 11h rest between consecutive days
    for k in range(K_TOTAL):
        for d in range(6):  # Days 0-5 (Mon-Sat)
            # Rest = (start_next_day + 1440) - end_current_day
            # Must be >= min_rest_minutes when both days are assigned
            # Big-M formulation: rest >= min_rest - M*(2 - assigned[k,d] - assigned[k,d+1])
            model.Add(
                start_expr[k, d+1] + 1440 - end_expr[k, d] >= 
                min_rest_minutes - M * (2 - assigned[k, d] - assigned[k, d+1])
            )
    
    logger.info(f"Added Big-M rest constraints: {K_TOTAL * 6} constraints (vs 5.95M pairwise!)")
    
    # 6. After 3-tour block -> next day off (hard constraint)
    for k in range(K_TOTAL):
        for d in range(7):
            day_blocks = blocks_by_day.get(d, [])
            if day_blocks:
                # heavy[k,d] = 1 if slot k has 3-tour block on day d
                model.Add(heavy[k, d] == sum(x[i, k] for i in day_blocks if tours[i] >= 3))
            else:
                model.Add(heavy[k, d] == 0)
        
        # If heavy on day d, cannot work on day d+1
        for d in range(6):
            model.Add(assigned[k, d+1] <= 1 - heavy[k, d])
    
    logger.info("Added 3-tour recovery constraints")
    
    # =========================================================================
    # PT FRAGMENTATION PENALTIES (Soft Objectives)
    # =========================================================================
    
    # PT days tracking
    pt_days = {}
    for k in PT_SLOTS:
        pt_days[k] = model.NewIntVar(0, 7, f"pt_days_{k}")
        model.Add(pt_days[k] == sum(assigned[k, d] for d in range(7)))
    
    # PT under-utilization penalty (shortfall)
    pt_shortfall = {}
    pt_min_minutes = int(config.pt_min_hours * 60)
    
    for k in PT_SLOTS:
        pt_minutes = sum(dur[i] * x[i, k] for i in range(B))
        pt_shortfall[k] = model.NewIntVar(0, pt_min_minutes, f"shortfall_{k}")
        
        # shortfall[k] >= pt_min_minutes - pt_minutes (when used)
        model.Add(pt_shortfall[k] >= pt_min_minutes - pt_minutes).OnlyEnforceIf(used[k])
        model.Add(pt_shortfall[k] == 0).OnlyEnforceIf(used[k].Not())
        model.Add(pt_shortfall[k] >= 0)
    
    logger.info("Added PT fragmentation tracking")
    
    # =========================================================================
    # OBJECTIVE
    # =========================================================================
    
    # Lexicographic priorities via weight separation
    W_PT = 1_000_000          # Minimize PT drivers (HIGHEST)
    W_TOTAL = 1_000           # Minimize total drivers
    W_PTDAYS = 50             # Minimize PT working days (fragmentation)
    W_PTSHORT = 10            # Minimize PT under-utilization
    
    cost_terms = []
    
    # 1. PT driver count
    for k in PT_SLOTS:
        cost_terms.append(W_PT * used[k])
    
    # 2. Total driver count
    for k in range(K_TOTAL):
        cost_terms.append(W_TOTAL * used[k])
    
    # 3. PT day fragmentation
    for k in PT_SLOTS:
        cost_terms.append(W_PTDAYS * pt_days[k])
    
    # 4. PT under-utilization
    for k in PT_SLOTS:
        cost_terms.append(W_PTSHORT * pt_shortfall[k])
    
    model.Minimize(sum(cost_terms))
    
    logger.info("Objective: Minimize PT count > Total drivers > PT days > PT shortfall")
    
    # =========================================================================
    # WARM START HINTS (if provided)
    # =========================================================================
    
    if warm_start:
        logger.info("Adding warm start hints from greedy assignment")
        
        hinted_slots = set()
        hinted_blocks = set()
        
        fte_idx = 0
        pt_idx = 0
        
        for assignment in sorted(warm_start, key=lambda a: (a.driver_type != "FTE", a.driver_id)):
            if not assignment.blocks:
                continue
            
            if assignment.driver_type == "FTE":
                if fte_idx >= K_FTE:
                    continue
                k = fte_idx
                fte_idx += 1
            else:
                if pt_idx >= K_PT:
                    continue
                k = K_FTE + pt_idx
                pt_idx += 1
            
            if k not in hinted_slots:
                model.AddHint(used[k], 1)
                hinted_slots.add(k)
            
            for block in assignment.blocks:
                # Find block index in sorted_blocks
                try:
                    i = sorted_blocks.index(block)
                    hint_key = (i, k)
                    if hint_key not in hinted_blocks:
                        model.AddHint(x[i, k], 1)
                        hinted_blocks.add(hint_key)
                except ValueError:
                    continue
    
    # =========================================================================
    # SOLVE
    # =========================================================================
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # Deterministic
    solver.parameters.search_branching = cp_model.FIXED_SEARCH
    solver.parameters.random_seed = config.seed
    solver.parameters.log_search_progress = True
    
    # Validate model
    validation_result = model.Validate()
    if validation_result:
        logger.error(f"Model validation failed: {validation_result}")
        return [], {"status": "MODEL_INVALID", "error": validation_result}
    
    logger.info(f"Solving with time limit {time_limit}s...")
    status = solver.Solve(model)
    
    logger.info(f"Status: {solver.StatusName(status)}")
    logger.info(f"Solve time: {solver.WallTime():.2f}s")
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.error(f"CP-SAT failed with status {solver.StatusName(status)}")
        return [], {"status": f"CP-SAT_{solver.StatusName(status)}"}
    
    # =========================================================================
    # EXTRACT SOLUTION
    # =========================================================================
    
    assignments = []
    fte_counter = 1
    pt_counter = 1
    
    for k in range(K_TOTAL):
        if solver.Value(used[k]) == 0:
            continue
        
        is_pt = (k in PT_SLOTS)
        
        # Collect blocks assigned to this slot
        slot_blocks = []
        for i in range(B):
            if solver.Value(x[i, k]) == 1:
                slot_blocks.append(sorted_blocks[i])
        
        if not slot_blocks:
            continue
        
        # Generate driver ID
        if is_pt:
            driver_id = f"PT{pt_counter:03d}"
            pt_counter += 1
        else:
            driver_id = f"FTE{fte_counter:03d}"
            fte_counter += 1
        
        # Calculate days_worked
        days_worked = len(set(b.day.value for b in slot_blocks))
        
        # Import analysis function
        from src.services.forecast_solver_v4 import _analyze_driver_workload
        
        assignment = DriverAssignment(
            driver_id=driver_id,
            driver_type="PT" if is_pt else "FTE",
            blocks=sorted(slot_blocks, key=lambda b: (b.day.value, b.first_start)),
            total_hours=sum(b.total_work_hours for b in slot_blocks),
            days_worked=days_worked,
            analysis=_analyze_driver_workload(slot_blocks)
        )
        assignments.append(assignment)
    
    # =========================================================================
    # CALCULATE STATISTICS
    # =========================================================================
    
    pt_drivers = [a for a in assignments if a.driver_type == "PT"]
    fte_drivers = [a for a in assignments if a.driver_type == "FTE"]
    
    # PT under-utilization stats
    pt_underutil = [a for a in pt_drivers if a.total_hours < config.pt_min_hours]
    pt_underutil_count = len(pt_underutil)
    pt_underutil_total_hours = sum(a.total_hours for a in pt_underutil)
    
    # PT working days stats
    pt_days_list = [a.days_worked for a in pt_drivers]
    pt_days_total = sum(pt_days_list)
    pt_days_avg = pt_days_total / len(pt_drivers) if pt_drivers else 0
    
    stats = {
        "drivers_total": len(assignments),
        "drivers_fte": len(fte_drivers),
        "drivers_pt": len(pt_drivers),
        "solve_time": solver.WallTime(),
        "status": solver.StatusName(status),
        "objective_value": solver.ObjectiveValue(),
        # PT fragmentation metrics
        "pt_underutil_count": pt_underutil_count,
        "pt_underutil_total_hours": round(pt_underutil_total_hours, 2),
        "pt_days_total": pt_days_total,
        "pt_days_avg": round(pt_days_avg, 2),
        # Legacy metrics
        "pt_single_segment_count": len([a for a in pt_drivers if len(a.blocks) == 1]),
        "tight_rest_count": len([a for a in assignments 
                                 if a.analysis.get("min_rest_hours") == 11.0]),
    }
    
    logger.info("=== CP-SAT ASSIGNMENT COMPLETE ===")
    logger.info(f"Drivers: {len(fte_drivers)} FTE + {len(pt_drivers)} PT = {len(assignments)}")
    logger.info(f"PT under-utilization: {pt_underutil_count} drivers, {pt_underutil_total_hours:.1f}h total")
    logger.info(f"PT working days: {pt_days_total} total, {pt_days_avg:.1f} avg")
    logger.info(f"Objective value: {solver.ObjectiveValue()}")
    
    return assignments, stats
