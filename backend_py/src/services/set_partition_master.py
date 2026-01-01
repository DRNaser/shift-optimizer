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

from src.services.roster_column import RosterColumn, MIN_WEEK_HOURS

logger = logging.getLogger("SetPartitionMaster")

# Weight constants for relaxed RMP objective (lexicographic via weights)
W_UNDER = 1_000_000  # Penalty for undercovered block (highest priority)
W_OVER = 10_000      # Penalty for overcovered block
W_DRIVER = 1         # Minimize driver count (lowest priority)

# =============================================================================
# UTILIZATION COST CONSTANTS (Fix for Mogelpackung / Singletons)
# =============================================================================
# Week-type targets for underutil calculation
UNDERUTIL_TARGET_HOURS = {
    "NORMAL": 40.0,      # 5-6 day week: target 40h
    "COMPRESSED": 33.0,  # 4 day week (like KW51): target 33h
    "SHORT": 25.0,       # <=3 day week: relaxed target
}

# Cost penalties (used in Stage 2-5 of lexiko)
COST_UNDERUTIL_PER_HOUR = 100    # Cost per hour under target
COST_SINGLETON_PENALTY = 500    # Extra cost for 1-block columns
COST_SUPERLOW_PENALTY = 2000    # Extra cost for <15h columns (4.5h/9h useless)
COST_LOW_PENALTY = 300          # Extra cost for <20h columns


def compute_column_cost(
    col: RosterColumn,
    target_hours: float = 33.0,
    week_type: str = "COMPRESSED"
) -> int:
    """
    Compute utilization-aware cost for a column.
    
    This makes low-hour columns EXPENSIVE, solving the Mogelpackung problem.
    Stage 1 (headcount) ignores this; Stages 2-5 use it for selection.
    
    Cost components:
    - Base: 1 per driver (W_DRIVER)
    - Underutil: (target - hours) * COST_UNDERUTIL_PER_HOUR if hours < target
    - Singleton: COST_SINGLETON_PENALTY if len(block_ids) == 1
    - Superlow: COST_SUPERLOW_PENALTY if hours < 15
    - Low: COST_LOW_PENALTY if hours < 20
    
    Args:
        col: RosterColumn to cost
        target_hours: Target hours for underutil (week-type dependent)
        week_type: "NORMAL", "COMPRESSED", or "SHORT"
    
    Returns:
        Integer cost (higher = less preferred)
    """
    hours = col.total_minutes / 60.0
    
    # Base cost: 1 per driver
    base_cost = W_DRIVER
    
    # Underutil penalty: proportional to missing hours
    underutil = max(0, target_hours - hours)
    underutil_penalty = int(underutil * COST_UNDERUTIL_PER_HOUR)
    
    # Singleton penalty: 1-block columns are cheap but operationally useless
    singleton_penalty = COST_SINGLETON_PENALTY if len(col.block_ids) == 1 else 0
    
    # Superlow penalty: 4.5h/9h columns are essentially worthless
    superlow_penalty = COST_SUPERLOW_PENALTY if hours < 15 else 0
    
    # Low penalty: <20h columns are still problematic
    low_penalty = COST_LOW_PENALTY if 15 <= hours < 20 else 0
    
    return base_cost + underutil_penalty + singleton_penalty + superlow_penalty + low_penalty


def get_target_hours_for_week(active_days_count: int) -> tuple[float, str]:
    """
    Determine target hours and week_type based on active days.
    
    Returns:
        (target_hours, week_type)
    """
    if active_days_count <= 3:
        return UNDERUTIL_TARGET_HOURS["SHORT"], "SHORT"
    elif active_days_count == 4:
        return UNDERUTIL_TARGET_HOURS["COMPRESSED"], "COMPRESSED"
    else:  # 5-6 days
        return UNDERUTIL_TARGET_HOURS["NORMAL"], "NORMAL"


def solve_relaxed_rmp(
    columns: list[RosterColumn],
    all_block_ids: set[str],
    time_limit: float = 30.0,
    log_fn=None,
    coverage_attr: str = "block_ids",
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
        col_items = getattr(col, coverage_attr, col.block_ids)
        for item_id in col_items:
            if item_id in coverage_index:
                coverage_index[item_id].append(i)
    
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
    hint_columns: Optional[list[RosterColumn]] = None,
    is_compressed_week: bool = False,
    coverage_attr: str = "block_ids",
) -> dict:
    """
    Solve the Restricted Master Problem (Set-Partitioning).
    
    Args:
        columns: List of valid RosterColumns in the pool
        all_block_ids: Set of all block IDs that need coverage
        time_limit: Solver time limit in seconds
        log_fn: Logging function
        hint_columns: Optional warm-start columns (e.g. from greedy solution)
    
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
    num_columns = len(columns)
    num_blocks = len(all_block_ids)
    log_fn(f"Columns in pool: {num_columns}")
    log_fn(f"Total blocks (Target): {num_blocks}")
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
        col_items = getattr(col, coverage_attr, col.block_ids)
        for item_id in col_items:
            if item_id in coverage_index:
                coverage_index[item_id].append(i)
    
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

    
    # Coverage constraint: sum(y[i] for i in covering) == 1 (Partitioning)
    # Using Soft-Constraint formulation (minimize deviation) to guarantee feasibility
    # uncov_j + sum(y_i) - overcov_j == 1
    
    under = {}
    over = {}
    for block_id in all_block_ids:
        # Slack variables
        u = model.NewBoolVar(f"u_{block_id}")
        o = model.NewIntVar(0, num_columns, f"o_{block_id}")
        
        under[block_id] = u
        over[block_id] = o
        
        col_vars = [y[idx] for idx in coverage_index[block_id]]
        model.Add(u + sum(col_vars) - o == 1)

    # =========================================================================
    # STEP 3: FORMALLY DOMINANT OBJECTIVE
    # =========================================================================
    
    # --- Bounded Secondary Penalties (per driver) ---
    MAX_HOURS_PEN = 200_000        # Max hours deviation penalty per driver
    MAX_SHORT_ROSTER_PEN = 200_000 # Penalty for short rosters (flex-like)
    MAX_SINGLETON_PEN = 200_000    # Max singleton penalty per driver
    
    # Step 6 Tuning: Aggressive penalties for compressed weeks
    MAX_SINGLETON_PEN = 200_000    # Max singleton penalty per driver
    
    # Step 6 Tuning: Aggressive penalties for compressed weeks
    MAX_COMPRESSED_PEN = 500_000 if is_compressed_week else 0
    
    # Upper bound on drivers (theoretical max = one driver per block)
    D_MAX = len(all_block_ids)
    
    # M_DRIVER must exceed max possible secondary sum
    # If all drivers have max penalties: D_MAX * (sum of all per-driver penalties)
    MAX_SECONDARY_PER_DRIVER = MAX_HOURS_PEN + MAX_SHORT_ROSTER_PEN + MAX_SINGLETON_PEN + MAX_COMPRESSED_PEN
    MAX_SECONDARY_TOTAL = D_MAX * MAX_SECONDARY_PER_DRIVER
    M_DRIVER = MAX_SECONDARY_TOTAL + 1  # +1 ensures strict dominance
    
    # W_UNDER must dominate all driver-based costs
    # Worst case: D_MAX drivers with max secondary each
    W_UNDER = M_DRIVER * (D_MAX + 1) + 1  # Ensures feasibility >> headcount
    
    log_fn(f"OBJECTIVE (D*M Dominance): M_DRIVER={M_DRIVER:,}, W_UNDER={W_UNDER:,}")
    log_fn(f"  MAX_SECONDARY_PER_DRIVER={MAX_SECONDARY_PER_DRIVER:,}")
    
    # --- Penalty Rate Constants ---
    HOURS_DEV_RATE = 5_000         # Per-hour deviation from target
    HOURS_TARGET = 47.5            # Target utilization (for secondary penalty only)
    SHORT_ROSTER_THRESHOLD = 20.0  # Hours below which flex penalty applies
    SHORT_ROSTER_PENALTY = 100_000 # Base penalty for short rosters
    SINGLETON_BASE_PENALTY = 50_000 # Base penalty for singletons
    
    # Compressed Week Constants (Step 6)
    CW_SINGLETON_PENALTY = 400_000
    CW_LOW_DENSITY_PENALTY = 150_000
    
    # --- Check which blocks have multi-block coverage ---
    has_complex_coverage = {}
    for block_id in all_block_ids:
        col_indices = coverage_index[block_id]
        has_complex_coverage[block_id] = any(
            getattr(columns[idx], "num_blocks", len(columns[idx].block_ids)) > 1
            for idx in col_indices
        )
    
    # =========================================================================
    # BUILD OBJECTIVE: Min(D * M_DRIVER + secondary + under * W_UNDER)
    # =========================================================================
    
    # D = sum(y) is driver count (will be multiplied by M_DRIVER)
    D = sum(y)
    
    # Secondary costs (bounded per driver)
    secondary_costs = []
    for i, col in enumerate(columns):
        if hasattr(col, "total_minutes"):
            total_hours = col.total_minutes / 60.0
        else:
            total_hours = getattr(col, "total_hours", 0.0)
        sec = 0
        if hasattr(col, "day_stats"):
            tours_count = sum(t for _, t, _, _ in col.day_stats)
        else:
            tours_count = len(getattr(col, "block_ids", []))
        
        # 1. Hours Deviation Penalty (bounded)
        # Target is 47.5h for optimal utilization, but any hours are accepted
        hour_diff = abs(total_hours - HOURS_TARGET)
        hours_pen = min(int(hour_diff * HOURS_DEV_RATE), MAX_HOURS_PEN)
        sec += hours_pen
        
        # 2. Short Roster Penalty (flex-like, bounded)
        # Short rosters (< 20h) are less efficient, penalize mildly
        if total_hours < SHORT_ROSTER_THRESHOLD:
            short_pen = min(SHORT_ROSTER_PENALTY, MAX_SHORT_ROSTER_PEN)
            sec += short_pen
        
        # 3. Singleton Penalty (bounded)
        if getattr(col, "num_blocks", len(getattr(col, "block_ids", []))) == 1:
            block_id = list(col.block_ids)[0]
            if has_complex_coverage.get(block_id, False):
                # Avoidable singleton
                if is_compressed_week:
                    singleton_pen = CW_SINGLETON_PENALTY
                else:
                    singleton_pen = min(SINGLETON_BASE_PENALTY * 2, MAX_SINGLETON_PEN)
            else:
                # Forced singleton
                singleton_pen = min(SINGLETON_BASE_PENALTY // 2, MAX_SINGLETON_PEN)
            sec += singleton_pen
        
        # 4. Low Density Penalty (Compressed Week)
        if is_compressed_week and col.num_blocks > 1 and tours_count <= 3:
            sec += CW_LOW_DENSITY_PENALTY

        secondary_costs.append(y[i] * sec)
    
    secondary_sum = sum(secondary_costs)
    
    # Undercoverage penalty (highest priority)
    under_sum = sum(under[block_id] for block_id in all_block_ids)
    
    # Overcoverage penalty (Conflict - must be avoided)
    # W_OVER should be high enough to dominate driver count but maybe less than undercoverage
    # If we have to choose between Uncovered (missed service) vs Overcovered (redundant driver),
    # usually missed service is worse.
    over_sum = sum(over[block_id] for block_id in all_block_ids)
    W_OVER_PENALTY = W_UNDER // 10  # Still very high, but < W_UNDER
    
    # FINAL OBJECTIVE: D * M_DRIVER + secondary_sum + under_sum * W_UNDER + over_sum * W_OVER
    # This guarantees: feasibility > conflicts > headcount > secondary
    model.Minimize(D * M_DRIVER + secondary_sum + under_sum * W_UNDER + over_sum * W_OVER_PENALTY)
    
    # =========================================================================
    # SOLVE
    # =========================================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # S0.1: Determinism (CP-SAT correct param)
    solver.parameters.random_seed = 42
    
    log_fn(f"Solving RMP...")
    
    # QUALITY: Add warm-start hints from greedy/previous solution
    if hint_columns:
        hint_ids = {col.roster_id for col in hint_columns}
        hints_added = 0
        for i, col in enumerate(columns):
            if col.roster_id in hint_ids:
                model.AddHint(y[i], 1)
                hints_added += 1
        log_fn(f"Added {hints_added} solver hints from warm-start")
    
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
    
    # Calculate slack totals
    u_sum = sum(solver.Value(under[block_id]) for block_id in all_block_ids)
    o_sum = sum(solver.Value(over[block_id]) for block_id in all_block_ids)
    
    log_fn(f"Selected {num_drivers} rosters (drivers)")
    
    # Verify coverage using the specified coverage attribute
    covered_items = set()
    for roster in selected:
        items = getattr(roster, coverage_attr, roster.block_ids)
        covered_items.update(items)
    
    uncovered = [item_id for item_id in all_block_ids if item_id not in covered_items]
    
    coverage_element_name = "tours" if coverage_attr == "covered_tour_ids" else "blocks"
    
    if uncovered or u_sum > 0 or o_sum > 0:
        log_fn(
            f"WARNING: Coverage slack detected for {coverage_element_name} "
            f"(uncovered={len(uncovered)}, u_sum={u_sum}, o_sum={o_sum})"
        )
    else:
        log_fn(f"[OK] All {len(all_block_ids)} {coverage_element_name} covered exactly once (u_sum={u_sum})")
    
    # =========================================================================
    # UTILIZATION STATISTICS (No FTE/PT Classification - that's contract-based)
    # =========================================================================
    hours = [r.total_hours for r in selected] if selected else [0]
    
    # 1. Selected Singletons
    selected_singletons = [
        r for r in selected if getattr(r, "num_blocks", len(getattr(r, "block_ids", []))) == 1
    ]
    selected_singletons_count = len(selected_singletons)
    
    # 2. Hours Statistics (for utilization reporting, NOT classification)
    # These are informational only - FTE/PT label is determined by contract pool
    HOURS_THRESHOLD_FOR_STATS = 40.0  # For utilization reporting only
    high_util_rosters = [r for r in selected if r.total_hours >= HOURS_THRESHOLD_FOR_STATS]
    low_util_rosters = [r for r in selected if r.total_hours < HOURS_THRESHOLD_FOR_STATS]
    
    hours_stats = "N/A"
    if hours:
        import statistics
        avg_h = statistics.mean(hours)
        min_h = min(hours)
        max_h = max(hours)
        try:
            std_h = statistics.stdev(hours) if len(hours) > 1 else 0
        except:
            std_h = 0
        hours_stats = f"min={min_h:.1f}, avg={avg_h:.1f}, max={max_h:.1f}, std={std_h:.1f}"
    
    # 3. Low Utilization Share (Hours) - for diagnostics
    low_util_hours_sum = sum(r.total_hours for r in low_util_rosters)
    total_hours_sum = sum(hours)
    low_util_share = (low_util_hours_sum / total_hours_sum * 100) if total_hours_sum > 0 else 0
    
    log_fn(f"METRICS:")
    log_fn(f"  Drivers: {num_drivers} Total (FTE/PT label is contract-based, not hours-based)")
    log_fn(f"  Selected Singletons: {selected_singletons_count}")
    log_fn(f"  Hours: {hours_stats}")
    log_fn(f"  Low Utilization Share (<40h): {low_util_share:.1f}%")
    log_fn(f"  u_sum: {u_sum}, o_sum: {o_sum}")

    return {
        "status": "INFEASIBLE" if (u_sum > 0 or o_sum > 0) else status_name,
        "selected_rosters": selected,
        "uncovered_blocks": uncovered,
        "num_drivers": num_drivers,
        # Note: num_fte/num_pt based on hours for backward compatibility
        # Real FTE/PT is determined post-solve by contract pool size
        "num_fte": len(high_util_rosters),  # >= 40h (for stats only)
        "num_pt": len(low_util_rosters),    # < 40h (for stats only)
        "pt_share_hours": low_util_share,
        "selected_singletons_count": selected_singletons_count,
        "u_sum": u_sum,
        "o_sum": o_sum,
        "solve_time": solve_time,
        "coverage_freq": coverage_freq,
    }


def _verify_solution_exact(
    selected: list[RosterColumn],
    target_ids: set[str],
    coverage_attr: str,
    D_star: int,
    log_fn,
) -> dict:
    """
    Verify solution is watertight: exact coverage, no duplicates, correct headcount.
    
    Returns:
        {
            "valid": bool,
            "issues": list[str],  # First 20 issues
            "missing_targets": list[str],
            "duplicate_targets": list[str],
            "headcount_mismatch": bool,
        }
    """
    issues = []
    
    # 1. Check headcount matches D*
    if len(selected) != D_star:
        issues.append(f"HEADCOUNT_MISMATCH: len(selected)={len(selected)} != D*={D_star}")
    
    # 2. Build coverage map and check for duplicates
    coverage_count: dict[str, int] = {}
    for roster in selected:
        items = getattr(roster, coverage_attr, roster.block_ids)
        for tid in items:
            coverage_count[tid] = coverage_count.get(tid, 0) + 1
    
    # 3. Check for missing targets (under-coverage)
    missing = [tid for tid in target_ids if coverage_count.get(tid, 0) == 0]
    if missing:
        issues.append(f"MISSING_TARGETS: {len(missing)} targets have 0 coverage")
        for tid in missing[:10]:
            issues.append(f"  - Missing: {tid}")
    
    # 4. Check for duplicates (over-coverage)
    duplicates = [(tid, cnt) for tid, cnt in coverage_count.items() if cnt > 1 and tid in target_ids]
    if duplicates:
        issues.append(f"DUPLICATE_TARGETS: {len(duplicates)} targets covered multiple times")
        for tid, cnt in duplicates[:10]:
            issues.append(f"  - Duplicate: {tid} (covered {cnt}x)")
    
    # 5. Check for extra coverage (targets not in target_ids but covered)
    extra = [tid for tid in coverage_count.keys() if tid not in target_ids]
    if extra:
        issues.append(f"EXTRA_TARGETS: {len(extra)} covered items not in target set")
    
    is_valid = len(missing) == 0 and len(duplicates) == 0 and len(selected) == D_star
    
    # Log issues (first 20)
    if issues:
        log_fn(f"[VERIFY] SOLUTION INVALID: {len(issues)} issues found")
        for issue in issues[:20]:
            log_fn(f"  {issue}")
    else:
        log_fn(f"[VERIFY] SOLUTION VALID: D*={D_star}, {len(target_ids)} targets covered exactly once")
    
    return {
        "valid": is_valid,
        "issues": issues[:20],
        "missing_targets": missing,
        "duplicate_targets": [t for t, _ in duplicates],
        "headcount_mismatch": len(selected) != D_star,
    }


def _filter_valid_hint_columns(
    hint_columns: list[RosterColumn],
    target_ids: set[str],
    coverage_attr: str,
    log_fn,
) -> list[RosterColumn]:
    """
    Filter hint columns to only those whose coverage is a subset of target_ids.
    This prevents CP-SAT from wasting time on invalid hints.
    """
    if not hint_columns:
        return []
    
    valid_hints = []
    rejected = 0
    
    for col in hint_columns:
        col_items = getattr(col, coverage_attr, col.block_ids)
        # Check if all items are in target_ids
        if all(tid in target_ids for tid in col_items):
            valid_hints.append(col)
        else:
            rejected += 1
    
    if rejected > 0:
        log_fn(f"[HINT FILTER] Rejected {rejected} hint columns (coverage outside target set)")
    log_fn(f"[HINT FILTER] Accepted {len(valid_hints)} valid hint columns")
    
    return valid_hints


def solve_rmp_feasible_under_cap(
    columns: list[RosterColumn],
    target_ids: set[str],
    coverage_attr: str = "covered_tour_ids",
    driver_cap: int = 999,
    time_limit: float = 30.0,
    log_fn=None,
    hint_columns: Optional[list[RosterColumn]] = None,
    objective_mode: str = "FEASIBILITY",  # "FEASIBILITY" or "MAX_DENSITY"
    banned_roster_ids: Optional[set[str]] = None,
) -> dict:
    """
    Solve RMP with driver cap constraint (feasibility check).
    
    Used by D-search outer loop to test if D_try is feasible.
    
    Key features (Step 13):
    - Zero-support check BEFORE solve (Fix 4)
    - Objective: Minimize(0) for pure feasibility (Fix 1)
    - Constraint: sum(y) <= driver_cap
    - Uses hint filtering and solution verification
    
    Returns:
        {
            "status": "FEASIBLE" | "INFEASIBLE" | "ZERO_SUPPORT" | "TIMEOUT",
            "num_drivers": int,
            "selected_rosters": list[RosterColumn],
            "zero_support_tours": list[str],  # Tours with no column support
            "solve_time": float,
        }
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn(f"[CAP-SOLVE] driver_cap={driver_cap}, pool={len(columns)}, time={time_limit}s")
    
    if not columns:
        return {
            "status": "ZERO_SUPPORT",
            "num_drivers": 0,
            "selected_rosters": [],
            "zero_support_tours": list(target_ids),
            "solve_time": 0,
        }
    
    # =========================================================================
    # STAGE 0: ZERO-SUPPORT CHECK (Fix 4 - before solve)
    # =========================================================================
    columns = sorted(columns, key=lambda c: c.roster_id)  # Determinism
    
    coverage_index: dict[str, list[int]] = {tid: [] for tid in target_ids}
    for i, col in enumerate(columns):
        col_items = getattr(col, coverage_attr, col.block_ids)
        for tid in col_items:
            if tid in coverage_index:
                coverage_index[tid].append(i)
    
    # Check zero-support tours
    zero_support = [tid for tid, cols in coverage_index.items() if len(cols) == 0]
    if zero_support:
        log_fn(f"[CAP-SOLVE] ZERO_SUPPORT: {len(zero_support)} tours have no column coverage")
        log_fn(f"  Sample: {zero_support[:10]}")
        return {
            "status": "ZERO_SUPPORT",
            "num_drivers": 0,
            "selected_rosters": [],
            "zero_support_tours": zero_support,
            "solve_time": 0,
        }
    
    C = len(columns)
    target_list = sorted(target_ids)
    
    # =========================================================================
    # BUILD MODEL
    # =========================================================================
    model = cp_model.CpModel()
    
    # Variables
    y = [model.NewBoolVar(f"y_{i}") for i in range(C)]
    
    # Exact TOUR coverage constraints
    for tid in target_list:
        col_indices = coverage_index[tid]
        model.Add(sum(y[i] for i in col_indices) == 1)
    
    # Driver cap constraint
    model.Add(sum(y) <= driver_cap)
    
    # Banned rosters constraint
    if banned_roster_ids:
        banned_count = 0
        for i, col in enumerate(columns):
            if col.roster_id in banned_roster_ids:
                model.Add(y[i] == 0)
                banned_count += 1
        if banned_count > 0:
            log_fn(f"[CAP-SOLVE] Banned {banned_count} rosters from solution")

    # Objective
    if objective_mode == "MAX_DENSITY":
        # Maximize total work minutes (encourage dense packing)
        # Using int matching ensures CP-SAT compatibility
        coeffs = [int(col.total_minutes) for col in columns]
        model.Maximize(cp_model.LinearExpr.WeightedSum(y, coeffs))
        log_fn("[CAP-SOLVE] Objective: MAX_DENSITY (maximize total work minutes)")
    else:
        # Feasibility-only (Fix 1 - Minimize(0) for speed)
        model.Minimize(0)
        # log_fn("[CAP-SOLVE] Objective: FEASIBILITY (Minimize 0)")
    
    # Warm-start hints (filtered for safety)
    if hint_columns:
        valid_hints = _filter_valid_hint_columns(hint_columns, target_ids, coverage_attr, log_fn)
        hint_ids = {col.roster_id for col in valid_hints}
        for i, col in enumerate(columns):
            if col.roster_id in hint_ids:
                model.AddHint(y[i], 1)
    
    # =========================================================================
    # SOLVE
    # =========================================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # Determinism
    solver.parameters.random_seed = 42
    
    start_time = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - start_time
    
    status_name = solver.StatusName(status)
    log_fn(f"[CAP-SOLVE] Status: {status_name} in {solve_time:.2f}s")
    
    # =========================================================================
    # EXTRACT RESULT
    # =========================================================================
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        selected = [columns[i] for i in range(C) if solver.Value(y[i]) == 1]
        num_drivers = len(selected)
        
        # Verify solution (watertight)
        verification = _verify_solution_exact(
            selected=selected,
            target_ids=target_ids,
            coverage_attr=coverage_attr,
            D_star=num_drivers,
            log_fn=log_fn,
        )
        
        if not verification["valid"]:
            log_fn(f"[CAP-SOLVE] VERIFICATION FAILED despite feasible status")
            return {
                "status": "INFEASIBLE",
                "num_drivers": num_drivers,
                "selected_rosters": selected,
                "zero_support_tours": verification["missing_targets"],
                "solve_time": solve_time,
            }
        
        log_fn(f"[CAP-SOLVE] FEASIBLE: D={num_drivers} (cap={driver_cap})")
        return {
            "status": "FEASIBLE",
            "num_drivers": num_drivers,
            "selected_rosters": selected,
            "zero_support_tours": [],
            "solve_time": solve_time,
        }
    
    elif status == cp_model.INFEASIBLE:
        log_fn(f"[CAP-SOLVE] INFEASIBLE under cap={driver_cap}")
        return {
            "status": "INFEASIBLE",
            "num_drivers": 0,
            "selected_rosters": [],
            "zero_support_tours": [],
            "solve_time": solve_time,
        }
    
    else:  # UNKNOWN, MODEL_INVALID, etc.
        log_fn(f"[CAP-SOLVE] TIMEOUT/UNKNOWN: {status_name}")
        return {
            "status": "TIMEOUT",
            "num_drivers": 0,
            "selected_rosters": [],
            "zero_support_tours": [],
            "solve_time": solve_time,
        }


def solve_rmp_lexico(
    columns: list[RosterColumn],
    target_ids: set[str],
    coverage_attr: str = "covered_tour_ids",
    time_limit_total: float = 60.0,
    log_fn=None,
    hint_columns: Optional[list[RosterColumn]] = None,
    is_compressed_week: bool = False,
    driver_cap: Optional[int] = None,  # NEW: Cap from D-search
) -> dict:
    """
    Solve RMP with TRUE lexicographic optimization (two-stage).
    
    Stage 1: Minimize headcount D = sum(y) - pure driver minimization
    Stage 2: Fix sum(y) == D*, minimize fragmentation/quality penalties
    
    This guarantees fewer drivers ALWAYS wins, regardless of penalty scaling.
    
    Args:
        columns: List of valid RosterColumns in the pool
        target_ids: Set of tour IDs (or block IDs) that need exact coverage
        coverage_attr: Attribute name for coverage ("covered_tour_ids" or "block_ids")
        time_limit_total: Total solver time budget for both stages
        log_fn: Logging function
        hint_columns: Optional warm-start columns
        is_compressed_week: Whether this is a compressed week (affects quality weights)
    
    Returns:
        {
            "status": "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "STAGE1_FAILED",
            "status_stage1": str,
            "status_stage2": str,
            "D_star": int,  # Optimal headcount from Stage 1
            "selected_rosters": list[RosterColumn],
            "singleton_selected": int,
            "short_roster_selected": int,
            "avg_tours_per_roster": float,
            "avg_hours": float,
            "zero_support_target_ids": list[str],
            "solve_time_stage1": float,
            "solve_time_stage2": float,
        }
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("LEXICOGRAPHIC RMP (2-Stage Headcount-First)")
    log_fn("=" * 60)
    log_fn(f"Columns in pool: {len(columns)}")
    log_fn(f"Target items: {len(target_ids)} ({coverage_attr})")
    log_fn(f"Time budget: {time_limit_total}s total")
    if driver_cap is not None:
        log_fn(f"Driver CAP: {driver_cap} (from D-search)")
    
    if not columns:
        log_fn("ERROR: Empty column pool!")
        return {
            "status": "INFEASIBLE",
            "status_stage1": "EMPTY_POOL",
            "status_stage2": "SKIPPED",
            "D_star": 0,
            "selected_rosters": [],
            "singleton_selected": 0,
            "short_roster_selected": 0,
            "avg_tours_per_roster": 0,
            "avg_hours": 0,
            "zero_support_target_ids": list(target_ids),
            "solve_time_stage1": 0,
            "solve_time_stage2": 0,
        }
    
    # =========================================================================
    # STAGE 0: FEASIBILITY CHECK - Build coverage index
    # =========================================================================
    # Sort columns by roster_id for determinism
    columns = sorted(columns, key=lambda c: c.roster_id)
    
    coverage_index: dict[str, list[int]] = {tid: [] for tid in target_ids}
    for i, col in enumerate(columns):
        col_items = getattr(col, coverage_attr, col.block_ids)
        for tid in col_items:
            if tid in coverage_index:
                coverage_index[tid].append(i)
    
    # Check for zero-support targets
    zero_support = [tid for tid, cols in coverage_index.items() if len(cols) == 0]
    if zero_support:
        log_fn(f"INFEASIBLE: {len(zero_support)} targets have zero column support!")
        log_fn(f"  First 10: {zero_support[:10]}")
        return {
            "status": "INFEASIBLE",
            "status_stage1": "ZERO_SUPPORT",
            "status_stage2": "SKIPPED",
            "D_star": 0,
            "selected_rosters": [],
            "singleton_selected": 0,
            "short_roster_selected": 0,
            "avg_tours_per_roster": 0,
            "avg_hours": 0,
            "zero_support_target_ids": zero_support,
            "solve_time_stage1": 0,
            "solve_time_stage2": 0,
        }
    
    C = len(columns)
    target_list = sorted(target_ids)  # Deterministic ordering
    
    # Time allocation: 40% Stage 1, 60% Stage 2
    time_stage1 = min(time_limit_total * 0.4, 30.0)  # Cap at 30s
    time_stage2 = time_limit_total - time_stage1
    
    log_fn(f"Time allocation: Stage1={time_stage1:.1f}s, Stage2={time_stage2:.1f}s")
    
    # =========================================================================
    # STAGE 1: MINIMIZE HEADCOUNT (Pure D = sum(y))
    # =========================================================================
    log_fn("")
    log_fn("-" * 40)
    log_fn("STAGE 1: Minimize Headcount")
    log_fn("-" * 40)
    
    model1 = cp_model.CpModel()
    
    # Variables
    y1 = [model1.NewBoolVar(f"y1_{i}") for i in range(C)]
    
    # Exact coverage constraints
    for tid in target_list:
        col_indices = coverage_index[tid]
        model1.Add(sum(y1[i] for i in col_indices) == 1)
    
    # NEW: Driver cap constraint if provided (from D-search)
    if driver_cap is not None:
        model1.Add(sum(y1) <= driver_cap)
        log_fn(f"Stage 1: Added sum(y) <= {driver_cap} constraint")
    
    # Objective: Minimize driver count
    model1.Minimize(sum(y1))
    
    # Warm-start hints (filtered for safety)
    if hint_columns:
        valid_hints = _filter_valid_hint_columns(hint_columns, target_ids, coverage_attr, log_fn)
        hint_ids = {col.roster_id for col in valid_hints}
        hints_added = 0
        for i, col in enumerate(columns):
            if col.roster_id in hint_ids:
                # Only hint y=1 (selected), never y=0 to avoid constraining search
                model1.AddHint(y1[i], 1)
                hints_added += 1
        log_fn(f"Added {hints_added} warm-start hints (y=1 only)")
    
    # Solve Stage 1
    solver1 = cp_model.CpSolver()
    solver1.parameters.max_time_in_seconds = time_stage1
    solver1.parameters.num_search_workers = 1  # Determinism
    solver1.parameters.random_seed = 42
    
    start1 = time.time()
    status1 = solver1.Solve(model1)
    solve_time1 = time.time() - start1
    
    status1_name = solver1.StatusName(status1)
    log_fn(f"Stage 1 Status: {status1_name} in {solve_time1:.2f}s")
    
    if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log_fn("STAGE 1 FAILED: No feasible partition found")
        return {
            "status": "STAGE1_FAILED",
            "status_stage1": status1_name,
            "status_stage2": "SKIPPED",
            "D_star": 0,
            "selected_rosters": [],
            "singleton_selected": 0,
            "short_roster_selected": 0,
            "avg_tours_per_roster": 0,
            "avg_hours": 0,
            "zero_support_target_ids": [],
            "solve_time_stage1": solve_time1,
            "solve_time_stage2": 0,
        }
    
    # Extract D*
    D_star = sum(solver1.Value(y1[i]) for i in range(C))
    log_fn(f"D* (Optimal Headcount) = {D_star}")
    
    # =========================================================================
    # STAGE 2: OPTIMIZE QUALITY WITH D FIXED
    # =========================================================================
    log_fn("")
    log_fn("-" * 40)
    log_fn("STAGE 2: Optimize Quality (D fixed)")
    log_fn("-" * 40)
    
    model2 = cp_model.CpModel()
    
    # Variables
    y2 = [model2.NewBoolVar(f"y2_{i}") for i in range(C)]
    
    # Exact coverage constraints (same as Stage 1)
    for tid in target_list:
        col_indices = coverage_index[tid]
        model2.Add(sum(y2[i] for i in col_indices) == 1)
    
    # CRITICAL: Fix headcount to D*
    model2.Add(sum(y2) == D_star)
    
    # Warm-start from Stage 1 solution
    for i in range(C):
        model2.AddHint(y2[i], solver1.Value(y1[i]))
    
    # -------------------------------------------------------------------------
    # SECONDARY OBJECTIVE: Minimize fragmentation
    # -------------------------------------------------------------------------
    # All penalties are ADDITIVE (headcount already fixed, no tradeoff possible)
    
    # Pre-compute column metrics
    singleton_penalty = []
    short_roster_penalty = []
    density_penalty = []
    
    SHORT_ROSTER_THRESHOLD = 13.5  # Hours
    max_tours_in_any_col = max(len(getattr(c, coverage_attr, c.block_ids)) for c in columns)
    
    for i, col in enumerate(columns):
        col_items = getattr(col, coverage_attr, col.block_ids)
        num_items = len(col_items)
        total_hours = col.total_minutes / 60.0
        
        # 1. Singleton penalty (covers only 1 item)
        if num_items == 1:
            singleton_penalty.append(y2[i] * 1000)
        else:
            singleton_penalty.append(y2[i] * 0)
        
        # 2. Short roster penalty (< 13.5h)
        if total_hours < SHORT_ROSTER_THRESHOLD:
            short_roster_penalty.append(y2[i] * 500)
        else:
            short_roster_penalty.append(y2[i] * 0)
        
        # 3. Density penalty: prefer more items per roster
        # Invert: penalize low density (max_tours - actual_tours)
        density_gap = max_tours_in_any_col - num_items
        density_penalty.append(y2[i] * density_gap)
    
    # Total secondary objective
    secondary_obj = sum(singleton_penalty) + sum(short_roster_penalty) + sum(density_penalty)
    model2.Minimize(secondary_obj)
    
    # Solve Stage 2
    solver2 = cp_model.CpSolver()
    solver2.parameters.max_time_in_seconds = time_stage2
    solver2.parameters.num_search_workers = 1  # Determinism
    solver2.parameters.random_seed = 42
    
    start2 = time.time()
    status2 = solver2.Solve(model2)
    solve_time2 = time.time() - start2
    
    status2_name = solver2.StatusName(status2)
    log_fn(f"Stage 2 Status: {status2_name} in {solve_time2:.2f}s")
    
    # =========================================================================
    # EXTRACT FINAL SOLUTION
    # =========================================================================
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        selected = [columns[i] for i in range(C) if solver2.Value(y2[i]) == 1]
        final_status = "OPTIMAL" if status2 == cp_model.OPTIMAL else "FEASIBLE"
        source_stage = "STAGE2"
    else:
        # Stage 2 failed - fall back to Stage 1 solution
        log_fn("Stage 2 failed - using Stage 1 solution")
        selected = [columns[i] for i in range(C) if solver1.Value(y1[i]) == 1]
        final_status = "FEASIBLE"
        status2_name = f"{status2_name}_FALLBACK_S1"
        source_stage = "STAGE1_FALLBACK"
    
    # =========================================================================
    # WATERTIGHT VERIFICATION (Step 12b)
    # =========================================================================
    verification = _verify_solution_exact(
        selected=selected,
        target_ids=target_ids,
        coverage_attr=coverage_attr,
        D_star=D_star,
        log_fn=log_fn,
    )
    
    if not verification["valid"]:
        log_fn(f"[VERIFY] SOLUTION FAILED VERIFICATION from {source_stage}")
        # Return INFEASIBLE with details - this should trigger pool repair upstream
        return {
            "status": "VERIFICATION_FAILED",
            "status_stage1": status1_name,
            "status_stage2": status2_name,
            "D_star": D_star,
            "selected_rosters": selected,  # Return anyway for debugging
            "singleton_selected": 0,
            "short_roster_selected": 0,
            "avg_tours_per_roster": 0,
            "avg_hours": 0,
            "zero_support_target_ids": verification["missing_targets"],
            "duplicate_targets": verification["duplicate_targets"],
            "verification_issues": verification["issues"],
            "solve_time_stage1": solve_time1,
            "solve_time_stage2": solve_time2,
        }
    
    # Compute metrics
    num_selected = len(selected)
    singleton_count = sum(1 for r in selected if len(getattr(r, coverage_attr, r.block_ids)) == 1)
    short_count = sum(1 for r in selected if r.total_minutes / 60.0 < SHORT_ROSTER_THRESHOLD)
    
    if selected:
        avg_tours = sum(len(getattr(r, coverage_attr, r.block_ids)) for r in selected) / num_selected
        avg_hours = sum(r.total_minutes / 60.0 for r in selected) / num_selected
    else:
        avg_tours = 0
        avg_hours = 0
    
    log_fn("")
    log_fn("=" * 40)
    log_fn("LEXIKO RESULT:")
    log_fn(f"  D* = {D_star} drivers")
    log_fn(f"  Singletons: {singleton_count}")
    log_fn(f"  Short rosters (<{SHORT_ROSTER_THRESHOLD}h): {short_count}")
    log_fn(f"  Avg tours/driver: {avg_tours:.1f}")
    log_fn(f"  Avg hours/driver: {avg_hours:.1f}")
    log_fn("=" * 40)
    
    return {
        "status": final_status,
        "status_stage1": status1_name,
        "status_stage2": status2_name,
        "D_star": D_star,
        "selected_rosters": selected,
        "singleton_selected": singleton_count,
        "short_roster_selected": short_count,
        "avg_tours_per_roster": avg_tours,
        "avg_hours": avg_hours,
        "zero_support_target_ids": [],
        "solve_time_stage1": solve_time1,
        "solve_time_stage2": solve_time2,
        "verification_valid": True,
    }


def solve_rmp_lexico_5stage(
    columns: list[RosterColumn],
    target_ids: set[str],
    coverage_attr: str = "covered_tour_ids",
    time_limit_total: float = 90.0,
    log_fn=None,
    hint_columns: Optional[list[RosterColumn]] = None,
    driver_cap: Optional[int] = None,
    underutil_target_hours: float = 33.0,  # T for compressed weeks (33h realistic)
) -> dict:
    """
    5-Stage Lexicographic RMP for Balanced Utilization.
    
    Optimizes in strict lexicographic order:
      Stage 1: min(drivers_total)           - Headcount
      Stage 2: min(count(hours < 30))       - Kill worst underutil
      Stage 3: min(count(hours < 35))       - Further reduce underutil
      Stage 4: min(sum_underutil)           - Soft glättung toward target
      Stage 5: max(count(hours >= 40))      - Optional FTE boost
    
    This fixes the "227 drivers @ 25h avg" problem by penalizing low-hour rosters.
    
    Args:
        columns: Pool of valid RosterColumns
        target_ids: Set of tour IDs requiring exact coverage
        coverage_attr: Attribute for coverage ("covered_tour_ids" or "block_ids")
        time_limit_total: Total solver time budget for all stages
        log_fn: Logging function
        hint_columns: Optional warm-start columns
        driver_cap: Optional hard cap on driver count
        underutil_target_hours: Target hours for underutil calculation (default 33h for compressed)
    
    Returns:
        Same structure as solve_rmp_lexico, with additional utilization metrics.
    """
    import time as time_module
    
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("5-STAGE LEXICOGRAPHIC RMP (Balanced Utilization)")
    log_fn("=" * 60)
    log_fn(f"Columns in pool: {len(columns)}")
    log_fn(f"Target items: {len(target_ids)} ({coverage_attr})")
    log_fn(f"Time budget: {time_limit_total}s total")
    log_fn(f"Underutil target: {underutil_target_hours}h")
    if driver_cap is not None:
        log_fn(f"Driver CAP: {driver_cap}")
    
    if not columns:
        log_fn("ERROR: Empty column pool!")
        return {
            "status": "INFEASIBLE",
            "D_star": 0,
            "selected_rosters": [],
            "count_under_30": 0,
            "count_under_35": 0,
            "count_gte_40": 0,
            "sum_underutil": 0,
            "avg_hours": 0,
            "zero_support_target_ids": list(target_ids),
        }
    
    # =========================================================================
    # BUILD COVERAGE INDEX
    # =========================================================================
    columns = sorted(columns, key=lambda c: c.roster_id)
    
    coverage_index: dict[str, list[int]] = {tid: [] for tid in target_ids}
    for i, col in enumerate(columns):
        col_items = getattr(col, coverage_attr, col.block_ids)
        for tid in col_items:
            if tid in coverage_index:
                coverage_index[tid].append(i)
    
    # Zero-support check
    zero_support = [tid for tid, cols in coverage_index.items() if len(cols) == 0]
    if zero_support:
        log_fn(f"INFEASIBLE: {len(zero_support)} targets have zero column support!")
        return {
            "status": "INFEASIBLE",
            "D_star": 0,
            "selected_rosters": [],
            "count_under_30": 0,
            "count_under_35": 0,
            "count_gte_40": 0,
            "sum_underutil": 0,
            "avg_hours": 0,
            "zero_support_target_ids": zero_support,
        }
    
    C = len(columns)
    target_list = sorted(target_ids)
    
    # Pre-compute column metrics for stages 2-5
    col_hours = []
    col_under_30 = []  # 1 if <30h, else 0
    col_under_35 = []  # 1 if <35h, else 0
    col_gte_40 = []    # 1 if >=40h, else 0
    col_underutil = [] # max(0, T - hours)
    col_cost = []      # Utilization-aware cost (higher = worse)
    
    for col in columns:
        hours = col.total_minutes / 60.0
        col_hours.append(hours)
        col_under_30.append(1 if hours < 30 else 0)
        col_under_35.append(1 if hours < 35 else 0)
        col_gte_40.append(1 if hours >= 40 else 0)
        col_underutil.append(max(0, underutil_target_hours - hours))
        col_cost.append(compute_column_cost(col, underutil_target_hours, "COMPRESSED"))
    
    # Max cost for scaling tie-breaker (must not overwhelm primary objective)
    max_cost = max(col_cost) if col_cost else 1
    W_TIEBREAKER = 1  # Weight for cost tie-breaker (1 ensures it doesn't affect primary obj)
    
    # Time allocation: 30% S1, 20% S2, 15% S3, 20% S4, 15% S5
    time_stages = [
        time_limit_total * 0.30,  # Stage 1
        time_limit_total * 0.20,  # Stage 2
        time_limit_total * 0.15,  # Stage 3
        time_limit_total * 0.20,  # Stage 4
        time_limit_total * 0.15,  # Stage 5
    ]
    log_fn(f"Time allocation: S1={time_stages[0]:.1f}s, S2={time_stages[1]:.1f}s, S3={time_stages[2]:.1f}s, S4={time_stages[3]:.1f}s, S5={time_stages[4]:.1f}s")
    
    # Track best solution across all stages for fallback
    best_solution = None
    best_D = None
    stage_results = {}
    
    # =========================================================================
    # STAGE 1: MINIMIZE DRIVERS
    # =========================================================================
    log_fn("\n--- STAGE 1: min(drivers_total) ---")
    
    model1 = cp_model.CpModel()
    y1 = [model1.NewBoolVar(f"y1_{i}") for i in range(C)]
    
    # Exact coverage
    for tid in target_list:
        model1.Add(sum(y1[i] for i in coverage_index[tid]) == 1)
    
    # Driver cap if provided
    if driver_cap is not None:
        model1.Add(sum(y1) <= driver_cap)
    
    model1.Minimize(sum(y1))
    
    # Hints
    if hint_columns:
        valid_hints = _filter_valid_hint_columns(hint_columns, target_ids, coverage_attr, log_fn)
        hint_ids = {col.roster_id for col in valid_hints}
        for i, col in enumerate(columns):
            if col.roster_id in hint_ids:
                model1.AddHint(y1[i], 1)
    
    solver1 = cp_model.CpSolver()
    solver1.parameters.max_time_in_seconds = time_stages[0]
    solver1.parameters.num_search_workers = 1
    solver1.parameters.random_seed = 42
    
    start1 = time_module.time()
    status1 = solver1.Solve(model1)
    solve_time1 = time_module.time() - start1
    
    if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log_fn(f"STAGE 1 FAILED: {solver1.StatusName(status1)}")
        return {
            "status": "STAGE1_FAILED",
            "D_star": 0,
            "selected_rosters": [],
            "count_under_30": 0,
            "count_under_35": 0,
            "count_gte_40": 0,
            "sum_underutil": 0,
            "avg_hours": 0,
            "zero_support_target_ids": [],
        }
    
    D_star = sum(solver1.Value(y1[i]) for i in range(C))
    log_fn(f"STAGE 1: D* = {D_star} ({solver1.StatusName(status1)} in {solve_time1:.1f}s)")
    best_solution = [solver1.Value(y1[i]) for i in range(C)]
    best_D = D_star
    stage_results["D_star"] = D_star
    
    # =========================================================================
    # STAGE 2: MINIMIZE count(hours < 30)
    # =========================================================================
    log_fn("\n--- STAGE 2: min(count(hours < 30)) ---")
    
    model2 = cp_model.CpModel()
    y2 = [model2.NewBoolVar(f"y2_{i}") for i in range(C)]
    
    for tid in target_list:
        model2.Add(sum(y2[i] for i in coverage_index[tid]) == 1)
    
    # Fix headcount
    model2.Add(sum(y2) == D_star)
    
    # Warm-start from Stage 1
    for i in range(C):
        model2.AddHint(y2[i], best_solution[i])
    
    # Objective: minimize count of columns with hours < 30
    # Add cost tie-breaker: when count is equal, prefer high-hour columns
    W_PRIMARY = (max_cost + 1) * C  # Ensures primary obj dominates
    count_under_30_expr = sum(y2[i] * col_under_30[i] for i in range(C))
    cost_tiebreaker = sum(y2[i] * col_cost[i] for i in range(C))
    model2.Minimize(count_under_30_expr * W_PRIMARY + cost_tiebreaker)
    
    solver2 = cp_model.CpSolver()
    solver2.parameters.max_time_in_seconds = time_stages[1]
    solver2.parameters.num_search_workers = 1
    solver2.parameters.random_seed = 42
    
    start2 = time_module.time()
    status2 = solver2.Solve(model2)
    solve_time2 = time_module.time() - start2
    
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        count_under_30_result = sum(solver2.Value(y2[i]) * col_under_30[i] for i in range(C))
        log_fn(f"STAGE 2: count(<30h) = {count_under_30_result} ({solver2.StatusName(status2)} in {solve_time2:.1f}s)")
        best_solution = [solver2.Value(y2[i]) for i in range(C)]
        stage_results["count_under_30"] = count_under_30_result
    else:
        log_fn(f"STAGE 2 FAILED: {solver2.StatusName(status2)} - using Stage 1 fallback")
        stage_results["count_under_30"] = sum(best_solution[i] * col_under_30[i] for i in range(C))
    
    # =========================================================================
    # STAGE 3: MINIMIZE count(hours < 35)
    # =========================================================================
    log_fn("\n--- STAGE 3: min(count(hours < 35)) ---")
    
    model3 = cp_model.CpModel()
    y3 = [model3.NewBoolVar(f"y3_{i}") for i in range(C)]
    
    for tid in target_list:
        model3.Add(sum(y3[i] for i in coverage_index[tid]) == 1)
    
    model3.Add(sum(y3) == D_star)
    
    # Fix count_under_30 if Stage 2 succeeded
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model3.Add(sum(y3[i] * col_under_30[i] for i in range(C)) <= stage_results["count_under_30"])
    
    for i in range(C):
        model3.AddHint(y3[i], best_solution[i])
    
    # Objective with cost tie-breaker
    W_PRIMARY = (max_cost + 1) * C
    count_under_35_expr = sum(y3[i] * col_under_35[i] for i in range(C))
    cost_tiebreaker = sum(y3[i] * col_cost[i] for i in range(C))
    model3.Minimize(count_under_35_expr * W_PRIMARY + cost_tiebreaker)
    
    solver3 = cp_model.CpSolver()
    solver3.parameters.max_time_in_seconds = time_stages[2]
    solver3.parameters.num_search_workers = 1
    solver3.parameters.random_seed = 42
    
    start3 = time_module.time()
    status3 = solver3.Solve(model3)
    solve_time3 = time_module.time() - start3
    
    if status3 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        count_under_35_result = sum(solver3.Value(y3[i]) * col_under_35[i] for i in range(C))
        log_fn(f"STAGE 3: count(<35h) = {count_under_35_result} ({solver3.StatusName(status3)} in {solve_time3:.1f}s)")
        best_solution = [solver3.Value(y3[i]) for i in range(C)]
        stage_results["count_under_35"] = count_under_35_result
    else:
        log_fn(f"STAGE 3 FAILED: {solver3.StatusName(status3)} - using fallback")
        stage_results["count_under_35"] = sum(best_solution[i] * col_under_35[i] for i in range(C))
    
    # =========================================================================
    # STAGE 4: MINIMIZE sum_underutil (soft glättung)
    # =========================================================================
    log_fn("\n--- STAGE 4: min(sum_underutil) ---")
    
    model4 = cp_model.CpModel()
    y4 = [model4.NewBoolVar(f"y4_{i}") for i in range(C)]
    
    for tid in target_list:
        model4.Add(sum(y4[i] for i in coverage_index[tid]) == 1)
    
    model4.Add(sum(y4) == D_star)
    
    # Fix previous objectives
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model4.Add(sum(y4[i] * col_under_30[i] for i in range(C)) <= stage_results["count_under_30"])
    if status3 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model4.Add(sum(y4[i] * col_under_35[i] for i in range(C)) <= stage_results["count_under_35"])
    
    for i in range(C):
        model4.AddHint(y4[i], best_solution[i])
    
    # Underutil penalty (scaled to integer for CP-SAT)
    # Add cost tie-breaker for same underutil sum
    underutil_scaled = [int(u * 10) for u in col_underutil]  # 0.1h precision
    W_PRIMARY = (max_cost + 1) * C
    sum_underutil_expr = sum(y4[i] * underutil_scaled[i] for i in range(C))
    cost_tiebreaker = sum(y4[i] * col_cost[i] for i in range(C))
    model4.Minimize(sum_underutil_expr * W_PRIMARY + cost_tiebreaker)
    
    solver4 = cp_model.CpSolver()
    solver4.parameters.max_time_in_seconds = time_stages[3]
    solver4.parameters.num_search_workers = 1
    solver4.parameters.random_seed = 42
    
    start4 = time_module.time()
    status4 = solver4.Solve(model4)
    solve_time4 = time_module.time() - start4
    
    if status4 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sum_underutil_result = sum(solver4.Value(y4[i]) * col_underutil[i] for i in range(C))
        log_fn(f"STAGE 4: sum_underutil = {sum_underutil_result:.1f}h ({solver4.StatusName(status4)} in {solve_time4:.1f}s)")
        best_solution = [solver4.Value(y4[i]) for i in range(C)]
        stage_results["sum_underutil"] = sum_underutil_result
    else:
        log_fn(f"STAGE 4 FAILED: {solver4.StatusName(status4)} - using fallback")
        stage_results["sum_underutil"] = sum(best_solution[i] * col_underutil[i] for i in range(C))
    
    # =========================================================================
    # STAGE 5: MAXIMIZE count(hours >= 40) - Optional FTE boost
    # =========================================================================
    log_fn("\n--- STAGE 5: max(count(hours >= 40)) ---")
    
    model5 = cp_model.CpModel()
    y5 = [model5.NewBoolVar(f"y5_{i}") for i in range(C)]
    
    for tid in target_list:
        model5.Add(sum(y5[i] for i in coverage_index[tid]) == 1)
    
    model5.Add(sum(y5) == D_star)
    
    # Fix previous objectives (use <= to allow flexibility)
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model5.Add(sum(y5[i] * col_under_30[i] for i in range(C)) <= stage_results["count_under_30"])
    if status3 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model5.Add(sum(y5[i] * col_under_35[i] for i in range(C)) <= stage_results["count_under_35"])
    # Don't fix underutil strictly - allow tradeoff for >=40h
    
    for i in range(C):
        model5.AddHint(y5[i], best_solution[i])
    
    # Objective: maximize count >= 40h, with cost tie-breaker (inverted for max)
    W_PRIMARY = (max_cost + 1) * C
    count_gte_40_expr = sum(y5[i] * col_gte_40[i] for i in range(C))
    # For maximization, use negative cost as tie-breaker (lower cost = better)
    neg_cost_tiebreaker = sum(y5[i] * (max_cost - col_cost[i]) for i in range(C))
    model5.Maximize(count_gte_40_expr * W_PRIMARY + neg_cost_tiebreaker)
    
    solver5 = cp_model.CpSolver()
    solver5.parameters.max_time_in_seconds = time_stages[4]
    solver5.parameters.num_search_workers = 1
    solver5.parameters.random_seed = 42
    
    start5 = time_module.time()
    status5 = solver5.Solve(model5)
    solve_time5 = time_module.time() - start5
    
    if status5 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        count_gte_40_result = sum(solver5.Value(y5[i]) * col_gte_40[i] for i in range(C))
        log_fn(f"STAGE 5: count(>=40h) = {count_gte_40_result} ({solver5.StatusName(status5)} in {solve_time5:.1f}s)")
        best_solution = [solver5.Value(y5[i]) for i in range(C)]
        stage_results["count_gte_40"] = count_gte_40_result
    else:
        log_fn(f"STAGE 5 FAILED: {solver5.StatusName(status5)} - using fallback")
        stage_results["count_gte_40"] = sum(best_solution[i] * col_gte_40[i] for i in range(C))
    
    # =========================================================================
    # EXTRACT FINAL SOLUTION
    # =========================================================================
    selected = [columns[i] for i in range(C) if best_solution[i] == 1]
    
    # Compute final metrics
    hours_list = [col.total_minutes / 60.0 for col in selected]
    final_count_under_30 = sum(1 for h in hours_list if h < 30)
    final_count_under_35 = sum(1 for h in hours_list if h < 35)
    final_count_gte_40 = sum(1 for h in hours_list if h >= 40)
    avg_hours = sum(hours_list) / len(hours_list) if hours_list else 0
    
    # Verification
    verification = _verify_solution_exact(
        selected=selected,
        target_ids=target_ids,
        coverage_attr=coverage_attr,
        D_star=D_star,
        log_fn=log_fn,
    )
    
    log_fn("\n" + "=" * 60)
    log_fn("5-STAGE LEXIKO RESULT:")
    log_fn(f"  D* = {D_star} drivers")
    log_fn(f"  count(<30h) = {final_count_under_30} ({final_count_under_30/D_star*100:.1f}%)")
    log_fn(f"  count(<35h) = {final_count_under_35} ({final_count_under_35/D_star*100:.1f}%)")
    log_fn(f"  count(>=40h) = {final_count_gte_40} ({final_count_gte_40/D_star*100:.1f}%)")
    log_fn(f"  Avg hours = {avg_hours:.1f}h")
    log_fn("=" * 60)
    
    return {
        "status": "FEASIBLE" if verification["valid"] else "VERIFICATION_FAILED",
        "D_star": D_star,
        "selected_rosters": selected,
        "count_under_30": final_count_under_30,
        "count_under_35": final_count_under_35,
        "count_gte_40": final_count_gte_40,
        "pct_under_30": final_count_under_30 / D_star * 100 if D_star > 0 else 0,
        "pct_gte_40": final_count_gte_40 / D_star * 100 if D_star > 0 else 0,
        "sum_underutil": stage_results.get("sum_underutil", 0),
        "avg_hours": avg_hours,
        "zero_support_target_ids": [],
        "verification_valid": verification["valid"],
        "stage_times": {
            "stage1": solve_time1,
            "stage2": solve_time2,
            "stage3": solve_time3,
            "stage4": solve_time4,
            "stage5": solve_time5,
        }
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
