"""
Set-Partition Master Problem (RMP) Solver

Solves the Restricted Master Problem for crew scheduling:
- Variables: y[r] ∈ {0,1} for each roster (column) in pool
- Constraint: For each block b, Σ_{r contains b} y[r] == 1 (exact coverage)
- Objective: Minimize Σ y[r] (minimize number of drivers)

The RMP only selects from pre-validated columns (all constraints already satisfied).
"""

import time
import logging
from typing import Optional
from ortools.sat.python import cp_model

from src.services.roster_column import RosterColumn

logger = logging.getLogger("SetPartitionMaster")

# Weight constants for relaxed RMP objective (lexicographic via weights)
W_UNDER = 1_000_000  # Penalty for undercovered block (highest priority)
W_OVER = 10_000      # Penalty for overcovered block
W_DRIVER = 1         # Minimize driver count (lowest priority)


def solve_relaxed_rmp(
    columns: list[RosterColumn],
    all_block_ids: set[str],
    time_limit: float = 30.0,
    log_fn=None,
) -> dict:
    """
    Solve a RELAXED RMP that is always feasible for diagnosis.
    
    For each block b:
    - under[b] ∈ {0,1}: block is undercovered (not in any selected column)
    - over[b] ∈ {0..C}: block overcoverage count (how many extra times covered)
    
    Constraint: Σ_{r∋b} y[r] + under[b] - over[b] == 1
    
    Objective (lexicographic via weights):
    - min Σ W_under * under[b]   (W_under = 1,000,000)
    - min Σ W_over * over[b]     (W_over = 10,000)
    - min Σ y[r]                 (W_driver = 1)
    
    Returns:
        {
            "status": "OPTIMAL" | "FEASIBLE" | "UNKNOWN",
            "under_blocks": list of block IDs with under=1,
            "over_blocks": list of block IDs with over>0,
            "under_count": int,
            "over_count": int (sum of overcoverage),
            "selected_count": int,
            "solve_time": float,
            "coverage_freq": dict block_id -> column count,
            "top_rare_blocks": list of (block_id, freq) with low coverage,
            "top_over_blocks": list of (block_id, over_value),
        }
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("RELAXED RMP (Diagnostic)")
    log_fn("=" * 60)
    log_fn(f"Columns in pool: {len(columns)}")
    log_fn(f"Total blocks (Target): {len(all_block_ids)}")
    
    if not columns:
        log_fn("ERROR: Empty column pool!")
        return {
            "status": "INFEASIBLE",
            "under_blocks": list(all_block_ids),
            "over_blocks": [],
            "under_count": len(all_block_ids),
            "over_count": 0,
            "selected_count": 0,
            "solve_time": 0,
            "coverage_freq": {},
            "top_rare_blocks": [],
            "top_over_blocks": [],
        }
    
    # Build coverage index: block_id -> list of column indices
    coverage_index: dict[str, list[int]] = {bid: [] for bid in all_block_ids}
    for i, col in enumerate(columns):
        for block_id in col.block_ids:
            if block_id in coverage_index:
                coverage_index[block_id].append(i)
    
    # Coverage frequency stats
    coverage_freq = {bid: len(cols) for bid, cols in coverage_index.items()}
    
    # Find rare blocks (low coverage frequency)
    sorted_by_freq = sorted(coverage_freq.items(), key=lambda x: x[1])
    top_rare_blocks = sorted_by_freq[:20]
    
    log_fn(f"Rare blocks (lowest coverage): {[f'{bid}:{cnt}' for bid, cnt in top_rare_blocks[:5]]}")
    
    # =========================================================================
    # BUILD RELAXED MODEL
    # =========================================================================
    model = cp_model.CpModel()
    
    C = len(columns)
    B = len(all_block_ids)
    block_ids_list = list(all_block_ids)
    block_to_idx = {bid: i for i, bid in enumerate(block_ids_list)}
    
    # Variables
    y = [model.NewBoolVar(f"y_{i}") for i in range(C)]           # Column selection
    under = [model.NewBoolVar(f"under_{i}") for i in range(B)]   # Block undercovered
    over = [model.NewIntVar(0, C, f"over_{i}") for i in range(B)] # Block overcoverage (IntVar!)
    
    # =========================================================================
    # CONSTRAINTS: Elastic coverage for each block
    # Σ y[r] + under[b] - over[b] == 1
    # =========================================================================
    for bid in all_block_ids:
        b_idx = block_to_idx[bid]
        col_indices = coverage_index[bid]
        
        if not col_indices:
            # Block has no coverage at all - must use under slack
            model.Add(under[b_idx] == 1)
            model.Add(over[b_idx] == 0)
        else:
            # Elastic: sum(y[cols]) + under - over == 1
            model.Add(
                sum(y[i] for i in col_indices) + under[b_idx] - over[b_idx] == 1
            )
    
    # =========================================================================
    # OBJECTIVE: Minimize weighted sum (lexicographic via large weights)
    # =========================================================================
    objective = (
        W_UNDER * sum(under) +    # Minimize undercovered (highest priority)
        W_OVER * sum(over) +      # Minimize overcovered
        W_DRIVER * sum(y)         # Minimize drivers
    )
    model.Minimize(objective)
    
    # =========================================================================
    # SOLVE
    # =========================================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # S0.1: Determinism (CP-SAT correct param)
    solver.parameters.random_seed = 42
    
    log_fn(f"Solving relaxed RMP...")
    start_time = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - start_time
    
    status_name = solver.StatusName(status)
    log_fn(f"Relaxed RMP Status: {status_name} in {solve_time:.2f}s")
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log_fn(f"WARNING: Relaxed RMP not solved! Status: {status_name}")
        return {
            "status": status_name,
            "under_blocks": list(all_block_ids),
            "over_blocks": [],
            "under_count": len(all_block_ids),
            "over_count": 0,
            "selected_count": 0,
            "solve_time": solve_time,
            "coverage_freq": coverage_freq,
            "top_rare_blocks": top_rare_blocks,
            "top_over_blocks": [],
        }
    
    # =========================================================================
    # EXTRACT SOLUTION
    # =========================================================================
    under_blocks = []
    over_blocks = []
    total_over = 0
    
    for i, bid in enumerate(block_ids_list):
        if solver.Value(under[i]) == 1:
            under_blocks.append(bid)
        over_val = solver.Value(over[i])
        if over_val > 0:
            over_blocks.append((bid, over_val))
            total_over += over_val
    
    selected_count = sum(solver.Value(y[i]) for i in range(C))
    
    # Sort over_blocks by overcoverage (descending)
    over_blocks_sorted = sorted(over_blocks, key=lambda x: -x[1])
    
    log_fn(f"Under-covered blocks: {len(under_blocks)}")
    log_fn(f"Over-covered blocks: {len(over_blocks)} (total over: {total_over})")
    log_fn(f"Selected columns: {selected_count}")
    
    if under_blocks:
        log_fn(f"Top under blocks: {under_blocks[:10]}")
    if over_blocks_sorted:
        log_fn(f"Top over blocks: {over_blocks_sorted[:10]}")
    
    return {
        "status": status_name,
        "under_blocks": under_blocks,
        "over_blocks": [bid for bid, _ in over_blocks_sorted],
        "under_count": len(under_blocks),
        "over_count": total_over,
        "selected_count": selected_count,
        "solve_time": solve_time,
        "coverage_freq": coverage_freq,
        "top_rare_blocks": top_rare_blocks,
        "top_over_blocks": over_blocks_sorted[:20],
    }


def solve_rmp(
    columns: list[RosterColumn],
    all_block_ids: set[str],
    time_limit: float = 60.0,
    log_fn=None,
) -> dict:
    """
    Solve the Restricted Master Problem (Set-Partitioning).
    
    Args:
        columns: List of valid RosterColumns in the pool
        all_block_ids: Set of all block IDs that need coverage
        time_limit: Solver time limit in seconds
        log_fn: Logging function
    
    Returns:
        {
            "status": "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "UNKNOWN",
            "selected_rosters": list of selected RosterColumn objects,
            "uncovered_blocks": list of block IDs not covered,
            "num_drivers": number of drivers (selected columns),
            "num_fte": number of FTE drivers selected,
            "num_pt": number of PT drivers selected,
            "solve_time": float,
            "coverage_freq": dict block_id -> number of columns containing it,
        }
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("RESTRICTED MASTER PROBLEM (RMP)")
    log_fn("=" * 60)
    log_fn(f"Columns in pool: {len(columns)}")
    log_fn(f"Total blocks (Target): {len(all_block_ids)}")
    log_fn(f"Time limit: {time_limit}s")
    
    if not columns:
        log_fn("ERROR: Empty column pool!")
        return {
            "status": "INFEASIBLE",
            "selected_rosters": [],
            "uncovered_blocks": list(all_block_ids),
            "num_drivers": 0,
            "solve_time": 0,
            "coverage_freq": {},
        }
    
    # Build coverage index: block_id -> list of column indices
    coverage_index: dict[str, list[int]] = {bid: [] for bid in all_block_ids}
    for i, col in enumerate(columns):
        for block_id in col.block_ids:
            if block_id in coverage_index:
                coverage_index[block_id].append(i)
    
    # Check for uncoverable blocks (no column contains them)
    uncoverable = [bid for bid, cols in coverage_index.items() if len(cols) == 0]
    if uncoverable:
        log_fn(f"WARNING: {len(uncoverable)} blocks have no column coverage!")
        for bid in uncoverable[:10]:  # Log first 10
            log_fn(f"  Uncoverable: {bid}")
        if len(uncoverable) > 10:
            log_fn(f"  ... and {len(uncoverable) - 10} more")
    
    # Coverage frequency stats
    coverage_freq = {bid: len(cols) for bid, cols in coverage_index.items()}
    rare_blocks = [bid for bid, cnt in coverage_freq.items() if cnt > 0 and cnt <= 3]
    log_fn(f"Rare-covered blocks (1-3 columns): {len(rare_blocks)}")
    
    # =========================================================================
    # BUILD MODEL
    # =========================================================================
    model = cp_model.CpModel()
    
    # Variables: y[i] = 1 if column i is selected
    C = len(columns)
    y = [model.NewBoolVar(f"y_{i}") for i in range(C)]
    
    # =========================================================================
    # CONSTRAINTS: Exact coverage for each block
    # =========================================================================
    for block_id in all_block_ids:
        col_indices = coverage_index[block_id]
        
        if not col_indices:
            # Block has no coverage - problem is infeasible
            # Add unsatisfiable constraint to force INFEASIBLE
            model.Add(0 == 1)  # This makes the model infeasible
            continue
        
        # Cover this block exactly once: Σ y[i] == 1
        # Strict Set Partitioning to force no overlaps and lower driver count
        model.Add(sum(y[i] for i in col_indices) == 1)
    
    # =========================================================================
    # OBJECTIVE: Minimize drivers with PT penalty + Overtime penalty (>53h)
    # FTE columns cost 1.0, PT columns cost 3.0
    # Overtime (>53h) adds 0.5 per hour to discourage overuse unless needed
    # =========================================================================
    PT_PENALTY = 3.0
    OVERTIME_THRESHOLD = 53.0
    OVERTIME_COST_PER_HOUR = 0.5
    
    costs = []
    for i, col in enumerate(columns):
        # Base cost
        cost = 1.0
        if hasattr(col, 'roster_type') and col.roster_type == "PT":
            cost = PT_PENALTY
        
        # Overtime penalty
        if col.total_hours > OVERTIME_THRESHOLD:
            excess = col.total_hours - OVERTIME_THRESHOLD
            cost += excess * OVERTIME_COST_PER_HOUR
            
        costs.append(cost * y[i])
    
    model.Minimize(sum(costs))
    
    # =========================================================================
    # SOLVE
    # =========================================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # S0.1: Determinism (CP-SAT correct param)
    solver.parameters.random_seed = 42
    
    log_fn(f"Solving RMP...")
    start_time = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - start_time
    
    status_name = solver.StatusName(status)
    log_fn(f"RMP Status: {status_name} in {solve_time:.2f}s")
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": status_name,
            "selected_rosters": [],
            "uncovered_blocks": uncoverable,
            "num_drivers": 0,
            "solve_time": solve_time,
            "coverage_freq": coverage_freq,
        }
    
    # =========================================================================
    # EXTRACT SOLUTION
    # =========================================================================
    selected = [columns[i] for i in range(C) if solver.Value(y[i]) == 1]
    num_drivers = len(selected)
    
    log_fn(f"Selected {num_drivers} rosters (drivers)")
    
    # Verify coverage
    covered_blocks = set()
    for roster in selected:
        covered_blocks.update(roster.block_ids)
    
    uncovered = [bid for bid in all_block_ids if bid not in covered_blocks]
    
    if uncovered:
        log_fn(f"WARNING: {len(uncovered)} blocks still uncovered after solve!")
    else:
        log_fn(f"[OK] All {len(all_block_ids)} blocks covered exactly once")
    
    # Hours stats
    if selected:
        hours = [r.total_hours for r in selected]
        log_fn(f"Hours range: {min(hours):.1f}h - {max(hours):.1f}h (avg: {sum(hours)/len(hours):.1f}h)")
    
    # Count FTE vs PT
    num_fte = sum(1 for r in selected if not hasattr(r, 'roster_type') or r.roster_type == "FTE")
    num_pt = sum(1 for r in selected if hasattr(r, 'roster_type') and r.roster_type == "PT")
    
    if num_pt > 0:
        log_fn(f"Driver mix: {num_fte} FTE + {num_pt} PT")
    
    return {
        "status": status_name,
        "selected_rosters": selected,
        "uncovered_blocks": uncovered,
        "num_drivers": num_drivers,
        "num_fte": num_fte,
        "num_pt": num_pt,
        "solve_time": solve_time,
        "coverage_freq": coverage_freq,
    }


def analyze_uncovered(
    columns: list[RosterColumn],
    uncovered_blocks: list[str],
    log_fn=None,
) -> dict:
    """
    Analyze why blocks are uncovered.
    
    Returns:
        {
            "truly_uncovered": blocks in no column at all,
            "sparse_coverage": blocks in very few columns,
            "conflict_hotspots": blocks that frequently conflict,
        }
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("")
    log_fn("=" * 60)
    log_fn("UNCOVERED BLOCK ANALYSIS")
    log_fn("=" * 60)
    
    # Coverage count
    coverage = {}
    for col in columns:
        for bid in col.block_ids:
            coverage[bid] = coverage.get(bid, 0) + 1
    
    truly_uncovered = [bid for bid in uncovered_blocks if coverage.get(bid, 0) == 0]
    sparse = [bid for bid in uncovered_blocks if 0 < coverage.get(bid, 0) <= 3]
    
    log_fn(f"Truly uncovered (no column contains them): {len(truly_uncovered)}")
    for bid in truly_uncovered[:5]:
        log_fn(f"  - {bid}")
    
    log_fn(f"Sparse coverage (1-3 columns): {len(sparse)}")
    
    return {
        "truly_uncovered": truly_uncovered,
        "sparse_coverage": sparse,
    }
