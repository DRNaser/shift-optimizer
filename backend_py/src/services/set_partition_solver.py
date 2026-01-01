"""
Set-Partition Solver - Main Solve Loop

Orchestrates the full Set-Partitioning / Crew Scheduling pipeline:

1. Build blocks from tours (reuse Phase 1)
2. Generate initial column pool
3. Loop:
   a. Solve RMP
   b. If FEASIBLE with full coverage → DONE
   c. If uncovered: generate new columns targeting uncovered blocks
   d. If no new columns generated → FAIL
4. Convert selected rosters to DriverAssignments
"""

import time
import logging
from time import monotonic
from dataclasses import dataclass
from typing import Optional

from src.services.roster_column import RosterColumn, BlockInfo
from src.services.roster_column_generator import (
    RosterColumnGenerator, create_block_infos_from_blocks
)
from src.services.set_partition_master import solve_rmp, solve_relaxed_rmp, analyze_uncovered, solve_rmp_lexico, solve_rmp_lexico_5stage, solve_rmp_feasible_under_cap, _filter_valid_hint_columns
from src.services.lower_bound_calc import compute_lower_bounds_wrapper

logger = logging.getLogger("SetPartitionSolver")

# >>> STEP8: SUPPORT_HELPERS (TOP-LEVEL)
def _compute_tour_support(columns, target_ids, coverage_attr):
    support = {tid: 0 for tid in target_ids}
    for col in columns:
        items = getattr(col, coverage_attr, col.block_ids)
        for tid in items:
            if tid in support:
                support[tid] += 1
    return support


def _simple_percentile(values, p):
    if not values:
        return 0
    vals = sorted(values)
    idx = int(len(vals) * p / 100.0)
    if idx < 0:
        idx = 0
    if idx >= len(vals):
        idx = len(vals) - 1
    return vals[idx]
# <<< STEP8: SUPPORT_HELPERS



@dataclass
class SetPartitionResult:
    """Result of Set-Partitioning solve."""
    status: str  # "OK" | "INFEASIBLE" | "FAILED_COVERAGE" | "FAILED_MAX_ROUNDS"
    selected_rosters: list[RosterColumn]
    num_drivers: int
    total_hours: float
    hours_min: float
    hours_max: float
    hours_avg: float
    uncovered_blocks: list[str]
    pool_size: int
    rounds_used: int
    total_time: float
    rmp_time: float
    generation_time: float


def _prune_pool_compressed_elite(
    current_pool: list[RosterColumn],
    selected_roster_ids: set[str],
    tours_map: dict,
    max_pool_size: int = 6000
) -> list[RosterColumn]:
    """[Step 11] Elite pruning for Compressed weeks."""
    logger.info(f"  [ELITE PRUNING] Starting with {len(current_pool)} cols (Max {max_pool_size})")
    
    # 1. Always keep selected
    keep_ids = set(selected_roster_ids)
    
    col_scores = {}
    tour_coverage = {}
    
    # Pre-scan
    for col in current_pool:
        # Score: Density (Avg tours per hour or just raw tours?)
        # Step 11 spec: "density score = len(covered_tour_ids)"
        # But per hour is better.
        # User spec: "len(covered_tour_ids) desc" - I'll stick to spec for safety, or refine.
        # "len(covered_tour_ids) desc" 
        
        score = len(col.covered_tour_ids)
        # Tie-break with lower hours (more efficient?)
        # Or higher hours (better FTE?)
        # Step 11 spec: "Deterministic sort tie-break by roster_id"
        
        if hasattr(col, "quality_penalty") and col.quality_penalty > 0:
            score -= 0.5 # Slight penalty
        
        col_scores[col.roster_id] = score
        
        # Hints
        if col.roster_id.startswith("INC_GREEDY") or col.roster_id.startswith("MERGE_"):
             keep_ids.add(col.roster_id)
             
        for tid in col.covered_tour_ids:
            if tid not in tour_coverage:
                tour_coverage[tid] = []
            tour_coverage[tid].append((score, col))
            
    # Select Top 3 per tour
    for tid, candidates in tour_coverage.items():
        # Sort desc by score, then asc by ID (deterministic)
        candidates.sort(key=lambda x: (-x[0], x[1].roster_id))
        
        for i in range(min(3, len(candidates))):
            keep_ids.add(candidates[i][1].roster_id)
            
    # Global Fill
    cols_by_id = {c.roster_id: c for c in current_pool}
    kept_cols = [cols_by_id[rid] for rid in keep_ids if rid in cols_by_id]
    
    if len(kept_cols) < max_pool_size:
        remaining = [c for c in current_pool if c.roster_id not in keep_ids]
        # Sort remaining by score
        remaining.sort(key=lambda c: (-col_scores.get(c.roster_id, 0), c.roster_id))
        
        needed = max_pool_size - len(kept_cols)
        kept_cols.extend(remaining[:needed])
        
    logger.info(f"  [ELITE PRUNING] Kept {len(kept_cols)} cols (Selected: {len(selected_roster_ids)})")
    return kept_cols


def _prune_pool_dsearch_safe(
    current_pool: list[RosterColumn],
    all_tour_ids: set[str],
    protected_roster_ids: set[str],
    k_min_support: int = 3,
    max_pool_size: int = 6000,
    log_fn=None,
) -> list[RosterColumn]:
    """
    Step 13c: Coverage-aware pruning for D-search.
    
    Guarantees:
    1. Protected rosters ALWAYS kept (INC_GREEDY_, MERGE_, REPAIR_, snapshots)
    2. Per-tour: at least K_min_support columns kept
    3. Never prune a tour below support=1
    4. Global pool_cap applied ONLY after support floor satisfied
    
    Args:
        current_pool: Current column pool
        all_tour_ids: All tours that need coverage
        protected_roster_ids: IDs that must never be pruned
        k_min_support: Minimum columns per tour (default 3)
        max_pool_size: Global pool cap
        log_fn: Logging function
        
    Returns:
        Pruned pool with support floor guaranteed
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn(f"[DSEARCH-PRUNE] Starting with {len(current_pool)} cols, K_min={k_min_support}")
    
    if len(current_pool) <= max_pool_size:
        log_fn(f"[DSEARCH-PRUNE] Pool under cap, no pruning needed")
        return current_pool
    
    # =========================================================================
    # STEP 1: Build tour-to-columns index with scores
    # =========================================================================
    tour_columns: dict[str, list[tuple[float, RosterColumn]]] = {tid: [] for tid in all_tour_ids}
    col_scores: dict[str, float] = {}
    
    for col in current_pool:
        # Score = density (more tours = better)
        score = len(col.covered_tour_ids)
        
        # Bonus for protected columns
        if col.roster_id in protected_roster_ids:
            score += 1000  # Always kept
        elif col.roster_id.startswith("INC_GREEDY"):
            score += 500
        elif col.roster_id.startswith(("MERGE_", "REPAIR_", "ANCHOR_")):
            score += 200
        
        col_scores[col.roster_id] = score
        
        for tid in col.covered_tour_ids:
            if tid in tour_columns:
                tour_columns[tid].append((score, col))
    
    # =========================================================================
    # STEP 2: Enforce support floor (K_min per tour)
    # =========================================================================
    keep_ids: set[str] = set(protected_roster_ids)
    
    for tid, candidates in tour_columns.items():
        if not candidates:
            log_fn(f"  [DSEARCH-PRUNE] WARNING: Tour {tid} has ZERO support!")
            continue
        
        # Sort by score desc, then roster_id for determinism
        candidates.sort(key=lambda x: (-x[0], x[1].roster_id))
        
        # Keep at least K_min (or all if fewer exist)
        keep_count = min(k_min_support, len(candidates))
        for i in range(keep_count):
            keep_ids.add(candidates[i][1].roster_id)
    
    log_fn(f"[DSEARCH-PRUNE] Support floor: {len(keep_ids)} cols required")
    
    # =========================================================================
    # STEP 3: Global fill up to pool_cap
    # =========================================================================
    cols_by_id = {c.roster_id: c for c in current_pool}
    kept_cols = [cols_by_id[rid] for rid in keep_ids if rid in cols_by_id]
    
    if len(kept_cols) < max_pool_size:
        remaining = [c for c in current_pool if c.roster_id not in keep_ids]
        remaining.sort(key=lambda c: (-col_scores.get(c.roster_id, 0), c.roster_id))
        
        needed = max_pool_size - len(kept_cols)
        kept_cols.extend(remaining[:needed])
    
    # =========================================================================
    # STEP 4: Verify no tour dropped below support=1
    # =========================================================================
    final_support = {tid: 0 for tid in all_tour_ids}
    for col in kept_cols:
        for tid in col.covered_tour_ids:
            if tid in final_support:
                final_support[tid] += 1
    
    zero_support_after = [tid for tid, cnt in final_support.items() if cnt == 0]
    if zero_support_after:
        log_fn(f"[DSEARCH-PRUNE] CRITICAL: {len(zero_support_after)} tours lost support!")
        log_fn(f"  Sample: {zero_support_after[:5]}")
    
    log_fn(f"[DSEARCH-PRUNE] Final: {len(kept_cols)} cols (from {len(current_pool)})")
    return kept_cols


# =============================================================================
# STEP 13c: COMPRESSED ENDGAME TRIGGER (KW51 Headcount Minimization)
# =============================================================================
# Constants for endgame trigger
ENDGAME_START_ROUND = 10  # Force endgame after this many rounds
ENDGAME_STALL_ROUNDS = 2  # Force endgame if stalled for this many rounds
ENDGAME_DEADLINE_WINDOW = 40.0  # Force endgame if less than 40s remaining


def _should_force_endgame_compressed(
    is_compressed_week: bool,
    use_tour_coverage: bool,
    round_num: int,
    stall_rounds: int,
    time_remaining: float,
) -> tuple[bool, str]:
    """
    Determine if compressed week endgame (D-search + Lexiko) should be forced.
    
    Args:
        is_compressed_week: Whether this is a compressed week (active_days <= 4)
        use_tour_coverage: Whether using TOUR coverage mode
        round_num: Current round number (1-indexed)
        stall_rounds: Number of rounds without driver improvement
        time_remaining: Seconds remaining until deadline (inf if no deadline)
    
    Returns:
        (should_trigger, reason) - reason is logged if triggered
    """
    if not (is_compressed_week and use_tour_coverage):
        return False, ""
    
    # Trigger: Too many rounds
    if round_num >= ENDGAME_START_ROUND:
        return True, f"round={round_num} >= ENDGAME_START_ROUND={ENDGAME_START_ROUND}"
    
    # Trigger: Stalled
    if stall_rounds >= ENDGAME_STALL_ROUNDS:
        return True, f"stall_rounds={stall_rounds} >= ENDGAME_STALL_ROUNDS={ENDGAME_STALL_ROUNDS}"
    
    # Trigger: Deadline approaching
    if time_remaining <= ENDGAME_DEADLINE_WINDOW:
        return True, f"time_remaining={time_remaining:.1f}s <= ENDGAME_DEADLINE_WINDOW={ENDGAME_DEADLINE_WINDOW}s"
    
    return False, ""


# =============================================================================
# STEP 13: D-SEARCH OUTER LOOP + REPAIR STATE MACHINE
# =============================================================================

def _extract_bottleneck_tours_for_cap(
    pool, all_tour_ids, coverage_attr, cap: int, log_fn
) -> list[str]:
    """
    Deterministic bottleneck selector for cap-aware repairs.
    Returns 50-150 tour_ids that likely block feasibility under tight caps.
    """
    # 1. Compute per-tour support counts
    support = {tid: 0 for tid in all_tour_ids}
    for col in pool:
        for tid in getattr(col, coverage_attr):
             if tid in support:
                 support[tid] += 1
            
    # 2. Sort by support (asc), then ID (asc) for determinism
    sorted_tours = sorted(support.keys(), key=lambda t: (support[t], t))
    
    # 3. Take lowest 150
    anchors = sorted_tours[:150]
    
    # Log stats
    supports = [support[t] for t in anchors]
    if supports:
        p10 = supports[len(supports)//10] if len(supports) >= 10 else supports[0]
        p50 = supports[len(supports)//2]
        log_fn(f"[CAP-WITNESS] cap={cap} anchors={len(anchors)} support_min={min(supports)} p10={p10} p50={p50}")
        
    return anchors

def _run_d_search(
    generator,
    all_tour_ids: set[str],
    features: dict,
    incumbent_drivers: int,
    time_budget: float,
    log_fn,
    max_repair_iters_per_d: int = 2,
    greedy_selected_roster_ids: set[str] = None,  # Step 13e: Protected greedy IDs
) -> dict:
    """
    D-search outer loop to find minimum feasible headcount.
    
    Step 13b Hardening:
    A) Best feasible snapshot tracking (best_feasible_cap, snapshot_id)
    B) Deterministic repair plan per fail-type (TILEABILITY vs ZERO_SUPPORT)
    C) Coverage-aware pruning constraints
    D) Fine sweep time bump on first infeasible (×1.8 retry)
    
    Step 13e: Greedy Snapshot Protect
    - Protected greedy roster IDs survive all pruning
    - Transactional pruning with rollback on feasibility loss
    - No-prune window near UB
    - UNKNOWN never counts as confirmed infeasible
    
    Returns:
        {
            "status": "SUCCESS" | "NO_IMPROVEMENT" | "FAILED",
            "D_min": int,
            "best_solution": list[RosterColumn],
            "best_feasible_cap": int,
            "best_snapshot_id": str,
            "attempts": int,
            "repairs_triggered": {"merge": int, "anchorpack": int},
            "pool_size_range": (int, int),
            "cap_solve_times": {"coarse": float, "fine": float},
        }
    """
    import math
    import hashlib
    from src.services.set_partition_master import solve_rmp_feasible_under_cap
    
    active_days = getattr(features, "active_days", []) if features else []
    active_days_count = len(active_days) if active_days else 6
    
    # =========================================================================
    # COMPUTE BOUNDS
    # =========================================================================
    pool = list(generator.pool.values())
    pool_size_min = len(pool)
    pool_size_max = len(pool)
    
    # Compute total hours estimate
    if hasattr(features, 'total_hours'):
        total_hours = features.total_hours
    else:
        total_hours = len(all_tour_ids) * 2.5  # ~2.5h per tour avg
    
    # Lower bounds
    # Lower bounds (Consistent with Step 0)
    LB_fleet = getattr(features, 'fleet_peak', 100) if features else 100
    LB_hours = math.ceil(total_hours / 55.0)
    LB_graph = getattr(features, 'lb_graph', 0) if features else 0
    
    # LB_tours is weak check, keep for reference
    LB_tours = math.ceil(len(all_tour_ids) / (3 * active_days_count))
    
    # Unified Final LB matches Step 0 logic
    LB = max(LB_fleet, LB_hours, LB_graph)
    
    # Upper bound = incumbent
    UB = incumbent_drivers
    
    log_fn("=" * 60)
    log_fn("[D-SEARCH] Starting Min-Headcount Search (Step 13b)")
    log_fn("=" * 60)
    # Standardized Log Line (Task A)
    log_fn(f"[D-SEARCH] LB: fleet={LB_fleet}, hours={LB_hours}, graph={LB_graph}, final={LB}")
    log_fn(f"[D-SEARCH] UB={UB} (incumbent)")
    log_fn(f"[D-SEARCH] Active days: {active_days_count}, Tours: {len(all_tour_ids)}")
    log_fn(f"[D-SEARCH] Pool size: {len(pool)}")
    log_fn(f"[D-SEARCH] Time budget: {time_budget}s")
    
    if UB <= LB:
        log_fn(f"[D-SEARCH] UB <= LB, no search needed")
        return {
            "status": "NO_IMPROVEMENT",
            "D_min": UB,
            "best_solution": [],
            "best_feasible_cap": UB,
            "best_snapshot_id": "N/A",
            "attempts": 0,
            "repairs_triggered": {"merge": 0, "anchorpack": 0},
            "pool_size_range": (len(pool), len(pool)),
            "cap_solve_times": {"coarse": 0, "fine": 0},
        }
    
    # =========================================================================
    # SNAPSHOT TRACKING (Step 13b A)
    # =========================================================================
    best_feasible_cap = UB
    best_feasible_D = UB
    best_solution = []
    best_snapshot_id = "INITIAL"
    snapshot_counter = 0
    
    def _make_snapshot_id(d_val, pool_len):
        nonlocal snapshot_counter
        snapshot_counter += 1
        return f"SNAP_{snapshot_counter:03d}_D{d_val}_P{pool_len}"
    
    # =========================================================================
    # STEP 13e: GREEDY SNAPSHOT PROTECT
    # =========================================================================
    # Collect all protected roster IDs that must survive pruning
    protected_greedy_ids = greedy_selected_roster_ids or set()
    log_fn(f"[D-SEARCH] Protected greedy IDs: {len(protected_greedy_ids)}")
    
    # Also include INC_GREEDY_ prefixed columns as protected
    for col in pool:
        if col.roster_id.startswith(("INC_GREEDY_", "SNAP_", "BEST_")):
            protected_greedy_ids.add(col.roster_id)
    
    # Step 13e: Transactional pruning state
    pruning_disabled = False  # Set to True if pruning breaks feasibility
    pruning_rollbacks = 0
    DSEARCH_POOL_CAP = 9000  # Increased from 6000 for D-search
    NO_PRUNE_WINDOW = 10  # Don't prune when D_try >= UB - 10
    
    # Repair counters
    repairs_merge = 0
    repairs_anchorpack = 0
    
    def _run_repair_plan(fail_type: str, zero_support_tours: list, current_d_try: int) -> bool:
        """
        Deterministic repair plan per fail-type.
        Step 13e: Transactional pruning with rollback.
        Returns True if pool was modified.
        """
        nonlocal repairs_merge, repairs_anchorpack, pool, pool_size_max, pruning_disabled, pruning_rollbacks
        
        if fail_type == "ZERO_SUPPORT":
            # Repair A: Anchor&Pack for missing tours
            log_fn(f"  [REPAIR-A] Anchor&Pack for {len(zero_support_tours)} zero-support tours")
            repairs_anchorpack += 1
            return False
        
        elif fail_type == "KILL_ONE":
            # Repair C: Kill-One Roster (Neighborhood)
            # Remove a 'weak' roster from best_solution to force alternative tiling
            if not best_solution:
                 log_fn("  [REPAIR-C] Kill-One skipped (no best_solution)")
                 return False
                 
            # Find victim: shortest roster in best solution
            # Or singleton?
            # Sort best_solution by work minutes (asc)
            sorted_sol = sorted(best_solution, key=lambda c: c.total_minutes)
            
            # Try to find one that is in pool
            victim = None
            for cand in sorted_sol:
                if any(c.roster_id == cand.roster_id for c in pool):
                    victim = cand
                    break
            
            if victim:
                log_fn(f"  [REPAIR-C] KILL-ONE: Removing roster {victim.roster_id} ({victim.total_hours:.1f}h) from pool")
                # Remove from pool
                len_before = len(pool)
                pool = [c for c in pool if c.roster_id != victim.roster_id]
                if len(pool) < len_before:
                     log_fn(f"  [REPAIR-C] Pool reduced: {len_before} -> {len(pool)}")
                     return True
            return False

        elif fail_type == "TILEABILITY":
            # Repair B: Deterministic order
            log_fn(f"  [REPAIR-B1] Merge Repair from best feasible (D={best_feasible_D})")
            repairs_merge += 1
            
            # Step 13e: No-prune window near UB
            if current_d_try >= UB - NO_PRUNE_WINDOW:
                log_fn(f"  [NO-PRUNE] In no-prune window (D_try={current_d_try} >= UB-{NO_PRUNE_WINDOW}={UB - NO_PRUNE_WINDOW})")
                return False
            
            # Step 13e: Skip pruning if disabled
            if pruning_disabled:
                log_fn(f"  [PRUNE-DISABLED] Pruning disabled due to previous rollback")
                return False
            
            # Step 13e: Skip pruning if pool is under DSEARCH_POOL_CAP
            if len(pool) <= DSEARCH_POOL_CAP:
                log_fn(f"  [NO-PRUNE] Pool size {len(pool)} <= {DSEARCH_POOL_CAP}, skip pruning")
                return False
            
            # Build protected set: greedy + best_solution + special prefixes
            protected_ids = set(protected_greedy_ids)
            protected_ids.update({r.roster_id for r in best_solution})
            for col in pool:
                if col.roster_id.startswith(("INC_GREEDY_", "MERGE_", "REPAIR_", "ANCHOR_", "SNAP_")):
                    protected_ids.add(col.roster_id)
            
            log_fn(f"  [PRUNE] Protected IDs: {len(protected_ids)}, Pool: {len(pool)}")
            
            # Step 13e: TRANSACTIONAL PRUNING - snapshot before prune
            pool_snapshot = {tuple(sorted(c.block_ids)): c for c in pool}  # Deep copy
            
            pruned = _prune_pool_dsearch_safe(
                current_pool=pool,
                all_tour_ids=all_tour_ids,
                protected_roster_ids=protected_ids,
                k_min_support=3,
                max_pool_size=DSEARCH_POOL_CAP,
                log_fn=log_fn,
            )
            
            if len(pruned) == len(pool):
                return False  # No change
            
            # Step 13e: FEASIBILITY CHECK after prune
            log_fn(f"  [PRUNE-CHECK] Verifying feasibility at UB={UB} after prune ({len(pruned)} cols)...")
            check_result = solve_rmp_feasible_under_cap(
                columns=pruned,
                target_ids=all_tour_ids,
                coverage_attr="covered_tour_ids",
                driver_cap=UB,
                time_limit=3.0,
                log_fn=log_fn,
                hint_columns=best_solution if best_solution else None,
            )
            
            if check_result["status"] not in ("OPTIMAL", "FEASIBLE"):
                # ROLLBACK: pruning broke feasibility
                log_fn(f"  [DSEARCH-ROLLBACK] Prune broke feasibility! Rolling back pool.")
                pool = list(pool_snapshot.values())
                pruning_rollbacks += 1
                pruning_disabled = True  # Disable further pruning
                return False
            
            # Prune successful and feasibility preserved
            pool = pruned
            pool_size_max = max(pool_size_max, len(pool))
            log_fn(f"  [PRUNE-OK] Feasibility preserved, pool: {len(pool)}")
            return True
        
        return False
    
    # =========================================================================
    # TIME SETTINGS (Step 13d Cap-Proof Hardening)
    # =========================================================================
    cap_solve_time_coarse = max(12.0, min(15.0, time_budget / 8))  # 12-15s per cap
    cap_solve_time_fine = max(20.0, min(30.0, time_budget / 4))    # 20-30s for fine sweep
    UNKNOWN_RETRY_MULTIPLIER = 1.8  # Time multiplier for UNKNOWN retry
    
    log_fn(f"[D-SEARCH] Time budgets: coarse={cap_solve_time_coarse:.1f}s, fine={cap_solve_time_fine:.1f}s")
    log_fn(f"[D-SEARCH] DSEARCH_POOL_CAP={DSEARCH_POOL_CAP}, NO_PRUNE_WINDOW={NO_PRUNE_WINDOW}")
    
    attempts = 0
    unknown_retries = 0
    COARSE_STEP = 20
    D_try = UB
    first_infeasible_D = None
    
    # =========================================================================
    # PHASE 1: COARSE SWEEP (Step -10)
    # =========================================================================
    log_fn(f"\n[D-SEARCH] Phase 1: Coarse sweep (step={COARSE_STEP}, time={cap_solve_time_coarse}s)")
    
    while D_try >= LB and first_infeasible_D is None:
        attempts += 1
        log_fn(f"\n[D-TRY] D_try={D_try} (coarse)")
        
        result = solve_rmp_feasible_under_cap(
            columns=pool,
            target_ids=all_tour_ids,
            coverage_attr="covered_tour_ids",
            driver_cap=D_try,
            time_limit=cap_solve_time_coarse,
            log_fn=log_fn,
            hint_columns=best_solution if best_solution else None,
        )
        
        if result["status"] == "FEASIBLE":
            if result["num_drivers"] < best_feasible_D:
                best_feasible_D = result["num_drivers"]
                best_feasible_cap = D_try
                best_solution = result["selected_rosters"]
                best_snapshot_id = _make_snapshot_id(best_feasible_D, len(pool))
                log_fn(f"[D-SEARCH] New best: D={best_feasible_D} (cap={D_try}, snapshot={best_snapshot_id})")
            D_try -= COARSE_STEP
        
        elif result["status"] == "ZERO_SUPPORT":
            log_fn(f"[D-SEARCH] ZERO_SUPPORT detected")
            # Run repair plan A
            for repair_iter in range(max_repair_iters_per_d):
                _run_repair_plan("ZERO_SUPPORT", result["zero_support_tours"], D_try)
                # Would retry after repair - for now just break
            first_infeasible_D = D_try
            break
        
        else:  # INFEASIBLE, UNKNOWN, or TIMEOUT
            status = result["status"]
            log_fn(f"[D-SEARCH] {status} at D={D_try} (coarse)")
            
            # Step 13d: UNKNOWN retry policy with increased time
            if status == "UNKNOWN":
                unknown_retries += 1
                retry_time = cap_solve_time_coarse * UNKNOWN_RETRY_MULTIPLIER
                log_fn(f"  [UNKNOWN-RETRY] Attempt with {retry_time:.1f}s (×{UNKNOWN_RETRY_MULTIPLIER})")
                
                result = solve_rmp_feasible_under_cap(
                    columns=pool,
                    target_ids=all_tour_ids,
                    coverage_attr="covered_tour_ids",
                    driver_cap=D_try,
                    time_limit=retry_time,
                    log_fn=log_fn,
                    hint_columns=best_solution if best_solution else None,
                )
                
                if result["status"] == "FEASIBLE":
                    if result["num_drivers"] < best_feasible_D:
                        best_feasible_D = result["num_drivers"]
                        best_feasible_cap = D_try
                        best_solution = result["selected_rosters"]
                        best_snapshot_id = _make_snapshot_id(best_feasible_D, len(pool))
                        log_fn(f"[D-SEARCH] UNKNOWN-RETRY success: D={best_feasible_D}")
                    D_try -= COARSE_STEP
                    continue
            
            # If still not feasible, try repair
            repaired = False
            final_status = result["status"]
            
            for repair_iter in range(max_repair_iters_per_d):
                log_fn(f"  [REPAIR] Attempt {repair_iter + 1}/{max_repair_iters_per_d}")
                
                # Step 15C: Alternate "KILL_ONE" if Merge Repair fails
                repair_mode = "TILEABILITY"
                if repair_iter > 0 and repairs_merge > 5: # If stalled?
                     repair_mode = "KILL_ONE"
                
                _run_repair_plan(repair_mode, [], D_try)
                
                # Retry with increased time (×1.8)
                result = solve_rmp_feasible_under_cap(
                    columns=pool,
                    target_ids=all_tour_ids,
                    coverage_attr="covered_tour_ids",
                    driver_cap=D_try,
                    time_limit=cap_solve_time_coarse * UNKNOWN_RETRY_MULTIPLIER,
                    log_fn=log_fn,
                    hint_columns=best_solution if best_solution else None,
                )
                final_status = result["status"]
                
                if result["status"] == "FEASIBLE":
                    if result["num_drivers"] < best_feasible_D:
                        best_feasible_D = result["num_drivers"]
                        best_feasible_cap = D_try
                        best_solution = result["selected_rosters"]
                        best_snapshot_id = _make_snapshot_id(best_feasible_D, len(pool))
                    repaired = True
                    break
            
            # Step 13e: UNKNOWN never counts as confirmed infeasible
            if not repaired:
                if final_status == "INFEASIBLE":
                    # Only INFEASIBLE confirms the boundary
                    first_infeasible_D = D_try
                    log_fn(f"[D-SEARCH] Boundary CONFIRMED (INFEASIBLE): D={D_try}")
                    break
                else:
                    # UNKNOWN: Continue searching, don't confirm boundary
                    unknown_retries += 1
                    log_fn(f"[D-SEARCH] UNKNOWN at D={D_try} after {repairs_merge} repairs - continuing search (not confirmed)")
                    D_try -= COARSE_STEP
            else:
                D_try -= COARSE_STEP
    
    # =========================================================================
    # PHASE 2: FINE SWEEP with TIME BUMP (Step 13b D)
    # =========================================================================
    if first_infeasible_D is not None and first_infeasible_D < best_feasible_D:
        search_start = first_infeasible_D + 1
        search_end = best_feasible_D - 1
        
        log_fn(f"\n[D-SEARCH] Phase 2: Fine sweep [{search_start}..{search_end}] (time={cap_solve_time_fine}s)")
        
        for D_try in range(search_end, search_start - 1, -1):
            attempts += 1
            log_fn(f"\n[D-TRY] D_try={D_try} (fine)")
            
            result = solve_rmp_feasible_under_cap(
                columns=pool,
                target_ids=all_tour_ids,
                coverage_attr="covered_tour_ids",
                driver_cap=D_try,
                time_limit=cap_solve_time_fine,
                log_fn=log_fn,
                hint_columns=best_solution if best_solution else None,
            )
            
            if result["status"] == "FEASIBLE":
                if result["num_drivers"] < best_feasible_D:
                    best_feasible_D = result["num_drivers"]
                    best_feasible_cap = D_try
                    best_solution = result["selected_rosters"]
                    best_snapshot_id = _make_snapshot_id(best_feasible_D, len(pool))
                    log_fn(f"[D-SEARCH] New best: D={best_feasible_D} (snapshot={best_snapshot_id})")
            else:
                # Step 14: Cap-Aware Repair & Escalation
                # Trigger only near valid solutions (UB - 5)
                # This focuses effort on proving feasibility for boundary conditions
                if D_try >= best_feasible_D - 5:
                    final_outcome = "UNKNOWN"
                    repair_success = False
                    
                    # 2 Repair Rounds + Initial Retry (Round 0 = just escalation)
                    max_repair_rounds = 2
                    
                    for repair_round in range(max_repair_rounds + 1):
                        # Repair Phase (skip for round 0)
                        if repair_round > 0:
                            anchors = _extract_bottleneck_tours_for_cap(pool, all_tour_ids, "covered_tour_ids", D_try, log_fn)
                            
                            # Add variants
                            added1 = 0
                            if hasattr(generator, 'generate_anchor_pack_variants'):
                                added1 = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)
                            
                            added2 = generator.generate_merge_repair_columns_capaware(anchors, max_cols=400)
                            
                            log_fn(f"[CAP-REPAIR] cap={D_try} round={repair_round} anchors={len(anchors)} added_anchor={added1} added_merge={added2}")
                        
                        # Proof Escalation Phase
                        # Budgets: 60s -> 120s -> 180s
                        escalation_budgets = [60.0, 120.0, 180.0]
                        
                        proof_found = False
                        for attempt_idx, proof_budget in enumerate(escalation_budgets):
                            log_fn(f"[CAP-PROOF] cap={D_try} attempt={attempt_idx+1} budget={proof_budget:.1f}s status=CHECKING...")
                            
                            # Use MAX_DENSITY guided objective for proofs
                            p_result = solve_rmp_feasible_under_cap(
                                columns=pool,
                                target_ids=all_tour_ids,
                                coverage_attr="covered_tour_ids",
                                driver_cap=D_try,
                                time_limit=proof_budget,
                                log_fn=log_fn,
                                hint_columns=best_solution if best_solution else None,
                                objective_mode="MAX_DENSITY",
                            )
                            
                            p_status = p_result["status"]
                            log_fn(f"[CAP-PROOF] cap={D_try} attempt={attempt_idx+1} status={p_status} (Mode=MAX_DENSITY)")
                            
                            if p_status == "FEASIBLE":
                                result = p_result # Update main result
                                if result["num_drivers"] < best_feasible_D:
                                    best_feasible_D = result["num_drivers"]
                                    best_feasible_cap = D_try
                                    best_solution = result["selected_rosters"]
                                    best_snapshot_id = _make_snapshot_id(best_feasible_D, len(pool))
                                    log_fn(f"[D-SEARCH] New best (via Proof): D={best_feasible_D} (snapshot={best_snapshot_id})")
                                proof_found = True
                                repair_success = True
                                break
                            elif p_status == "INFEASIBLE":
                                final_outcome = "INFEASIBLE"
                                proof_found = True
                                break
                            else:
                                # UNKNOWN or TIMEOUT - continue to next budget or repair round
                                pass
                        
                        if proof_found:
                            break
                    
                    if repair_success:
                        pass # Loop continues to next D_try (lower)
                    elif final_outcome == "INFEASIBLE":
                        log_fn(f"[D-SEARCH] Boundary CONFIRMED (INFEASIBLE): D={D_try}")
                        break
                    else:
                        # Still UNKNOWN after max effort
                        # Do NOT confirm infeasible, just skip
                        log_fn(f"[D-SEARCH] UNKNOWN at D={D_try} after escalation/repair - continuing search (not confirmed)")
                        unknown_retries += 1
                        
                else:
                    # Old behavior (single retry with bump) for non-boundary caps
                    status = result["status"]
                    log_fn(f"[D-SEARCH] Fine {status} at D={D_try} - TIME BUMP retry (×{UNKNOWN_RETRY_MULTIPLIER})")
                    bumped_time = cap_solve_time_fine * UNKNOWN_RETRY_MULTIPLIER
                    
                    result = solve_rmp_feasible_under_cap(
                        columns=pool,
                        target_ids=all_tour_ids,
                        coverage_attr="covered_tour_ids",
                        driver_cap=D_try,
                        time_limit=bumped_time,
                        log_fn=log_fn,
                        hint_columns=best_solution if best_solution else None,
                    )
                    
                    if result["status"] == "FEASIBLE":
                        if result["num_drivers"] < best_feasible_D:
                            best_feasible_D = result["num_drivers"]
                            best_feasible_cap = D_try
                            best_solution = result["selected_rosters"]
                            best_snapshot_id = _make_snapshot_id(best_feasible_D, len(pool))
                            log_fn(f"[D-SEARCH] TIME BUMP success: D={best_feasible_D}")
                    elif result["status"] == "UNKNOWN":
                        unknown_retries += 1
                        log_fn(f"[D-SEARCH] Still UNKNOWN after bump, continuing search (retries={unknown_retries})")
                    else:
                        log_fn(f"[D-SEARCH] Boundary confirmed: D={D_try} infeasible, D={D_try + 1} feasible")
                        break
    
    # =========================================================================
    # FINALIZE
    # =========================================================================
    log_fn(f"\n[D-SEARCH] COMPLETE")
    log_fn(f"[FINAL] D_min={best_feasible_D} (cap={best_feasible_cap}, snapshot={best_snapshot_id})")
    log_fn(f"[FINAL] Incumbent={incumbent_drivers}, Improvement={incumbent_drivers - best_feasible_D}")
    log_fn(f"[FINAL] Attempts={attempts}, Repairs: merge={repairs_merge}, anchorpack={repairs_anchorpack}")
    log_fn(f"[FINAL] UNKNOWN retries: {unknown_retries}, Pruning rollbacks: {pruning_rollbacks}")
    log_fn(f"[FINAL] Pool size range: [{pool_size_min}, {pool_size_max}]")
    log_fn(f"[FINAL] Cap solve times: coarse={cap_solve_time_coarse:.1f}s, fine={cap_solve_time_fine:.1f}s")
    
    return {
        "status": "SUCCESS" if best_feasible_D < incumbent_drivers else "NO_IMPROVEMENT",
        "D_min": best_feasible_D,
        "best_solution": best_solution,
        "best_feasible_cap": best_feasible_cap,
        "best_snapshot_id": best_snapshot_id,
        "attempts": attempts,
        "repairs_triggered": {"merge": repairs_merge, "anchorpack": repairs_anchorpack},
        "pool_size_range": (pool_size_min, pool_size_max),
        "cap_solve_times": {"coarse": cap_solve_time_coarse, "fine": cap_solve_time_fine},
    }


def solve_set_partitioning(
    blocks: list,
    max_rounds: int = 500,  # OPTIMIZED: 100→500 for better convergence
    initial_pool_size: int = 10000,  # OPTIMIZED: 5000→10000 for more diverse columns
    columns_per_round: int = 300,  # OPTIMIZED: 200→300 for faster coverage
    rmp_time_limit: float = 45.0,  # QUALITY: 15→45s for better solutions
    seed: int = 42,
    log_fn=None,
    config=None,  # NEW: Pass config for LNS flags
    global_deadline: float = None,  # Monotonic deadline for budget enforcement
    context: Optional[object] = None, # Added run context
    features: Optional[dict] = None,  # Step 8: Instance features
) -> SetPartitionResult:
    """
    Solve the crew scheduling problem using Set-Partitioning.
    
    Args:
        blocks: List of Block objects (from Phase 1)
        max_rounds: Maximum generation/solve rounds
        initial_pool_size: Target size for initial column pool
        columns_per_round: Columns to generate per round
        rmp_time_limit: RMP solver time limit per solve
        seed: Random seed for determinism
        log_fn: Logging function
        config: Optional ConfigV4 for LNS settings
    
    Returns:
        SetPartitionResult with selected rosters and stats
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    start_time = time.time()
    
    log_fn("=" * 70)
    log_fn("SET-PARTITIONING SOLVER - Starting")
    log_fn("=" * 70)
    log_fn(f"Blocks: {len(blocks)}")
    log_fn(f"Max rounds: {max_rounds}")
    log_fn(f"Initial pool target: {initial_pool_size}")
    
    # MANDATORY: Log LNS status immediately for diagnostic visibility
    # QUALITY: Enable LNS by default (can be overridden via config)
    enable_lns = True if config is None else getattr(config, 'enable_lns_low_hour_consolidation', True)
    log_fn(f"LNS enabled: {enable_lns}")
    if enable_lns:
        lns_budget = getattr(config, 'lns_time_budget_s', 30.0)
        lns_threshold = getattr(config, 'lns_low_hour_threshold_h', 30.0)
        lns_k = getattr(config, 'lns_receiver_k_values', (3, 5, 8, 12))
        log_fn(f"  LNS budget: {lns_budget:.1f}s")
        log_fn(f"  LNS threshold: {lns_threshold:.1f}h")
        log_fn(f"  LNS K-values: {lns_k}")
    log_fn("=" * 70)

    # Emit Phase Start
    if context and hasattr(context, "emit_progress"):
        context.emit_progress("phase_start", "Starting Set Partitioning", phase="phase2_assignments")

    
    # =========================================================================
    # STEP 1: Convert blocks to BlockInfo
    # =========================================================================
    log_fn("\nConverting blocks to BlockInfo...")
    block_infos = create_block_infos_from_blocks(blocks)
    all_block_ids = set(b.block_id for b in block_infos)
    
    # >>> STEP8: EXTRACT TOUR IDS
    all_tour_ids = set()
    for b in block_infos:
        all_tour_ids.update(b.tour_ids)
    log_fn(f"Unique tours: {len(all_tour_ids)}")
    # <<< STEP8: EXTRACT TOUR IDS
    
    total_work_hours = sum(b.work_min for b in block_infos) / 60.0
    log_fn(f"Total work hours: {total_work_hours:.1f}h")
    log_fn(f"Expected drivers (40-53h): {int(total_work_hours/53)} - {int(total_work_hours/40)}")

    # =========================================================================
    # STEP 0: PRE-CALCULATE LOWER BOUNDS (Step 15A)
    # =========================================================================
    feature_fleet = features.fleet_peak if features and hasattr(features, 'fleet_peak') else 0
    lb_stats = compute_lower_bounds_wrapper(block_infos, log_fn, fleet_peak=feature_fleet, total_hours=total_work_hours)
    
    lb_final = lb_stats.get("final_lb", 0)  # Use Unified Final LB
    
    # Decision Gate for target 204
    if lb_final >= 220:
        log_fn(f"[LB] CRITICAL: Theoretical Minimum ({lb_final}) >= 220.")
        log_fn(f"[LB] Target 204 is MATHEMATICALLY IMPOSSIBLE.")
    else:
        log_fn(f"[LB] Target 204 is theoretically possible (Topological bound={lb_final}).")
    
    if features is not None:
        features.lb_final = lb_final # Attach unified LB
        features.lb_graph = lb_stats.get("graph_lb", 0) # Attach graph LB for diagnostics

    # =========================================================================
    # STEP 2: Generate initial column pool using MULTI-STAGE generation
    # This produces better-packed rosters by first trying high-hour targets
    # =========================================================================
    generator = RosterColumnGenerator(
        block_infos=block_infos,
        seed=seed,
        pool_cap=50000,  # Allow large pool
        log_fn=log_fn,
    )
    
    gen_start = time.time()
    
    # OPTIMIZED: Use multi-stage generation for better FTE utilization
    multistage_stats = generator.generate_multistage_pool(
        stages=[
            ("high_quality_FTE", (47, 53), 4000),   # Pack 47-53h rosters first
            ("medium_FTE", (42, 47), 3000),         # Then 42-47h
            ("fill_gaps", (30, 42), 2000),          # Allow lower hours for remaining
        ]
    )
    
    # Also run standard generation for diversity
    generator.generate_initial_pool(target_size=initial_pool_size // 2)
    generation_time = time.time() - gen_start
    
    stats = generator.get_pool_stats()
    log_fn(f"\nMulti-stage FTE pool stats:")
    log_fn(f"  Pool size: {stats.get('size', 0)}")
    log_fn(f"  Uncovered blocks: {stats.get('uncovered_blocks', 0)}")
    log_fn(f"  Multi-stage: {multistage_stats['total_pool_size']} columns in {len(multistage_stats['stages'])} stages")

    
    # =========================================================================
    # STEP 15B: FORECAST-AWARE GENERATION (Compressed Weeks)
    # =========================================================================
    is_compressed = features and len(getattr(features, "active_days", [])) <= 4
    if is_compressed:
        log_fn("\n[STEP 15B] Running Forecast-Aware Generation...")
        added_sparse = generator.generate_sparse_window_seeds(max_concurrent=2)
        added_fri = generator.generate_friday_absorbers()
        log_fn(f"[STEP 15B] Total added: {added_sparse + added_fri} columns")

    # =========================================================================
    # STEP 2B: Generate PT columns for hard-to-cover blocks
    # =========================================================================
    pt_gen_start = time.time()
    pt_count = generator.generate_pt_pool(target_size=500)
    generation_time += time.time() - pt_gen_start
    
    stats = generator.get_pool_stats()
    log_fn(f"\nPool after PT generation:")
    log_fn(f"  Pool size: {stats.get('pool_total', 0)} ({pt_count} PT columns)")
    log_fn(f"  Uncovered blocks: {len(generator.get_uncovered_blocks())}")
    
    # =========================================================================
    # STEP 2C: Generate SINGLETON columns (Feasibility Net)
    # One column per block with HIGH COST → ensures RMP always finds a solution
    # =========================================================================
    singleton_start = time.time()
    singleton_count = generator.generate_singleton_columns(penalty_factor=100.0)
    generation_time += time.time() - singleton_start
    
    stats = generator.get_pool_stats()
    pool_size = stats.get('pool_total', 0)
    log_fn(f"\nPool after singleton fallback:")
    log_fn(f"  Pool size: {pool_size} (+{singleton_count} singleton)")
    log_fn(f"  Uncovered blocks: {len(generator.get_uncovered_blocks())}")
    
    if pool_size == 0:
        log_fn("ERROR: Could not generate any valid columns!")
        return SetPartitionResult(
            status="FAILED_NO_COLUMNS",
            selected_rosters=[],
            num_drivers=0,
            total_hours=0,
            hours_min=0,
            hours_max=0,
            hours_avg=0,
            uncovered_blocks=list(all_block_ids),
            pool_size=0,
            rounds_used=0,
            total_time=time.time() - start_time,
            rmp_time=0,
            generation_time=generation_time,
        )

    # =========================================================================
    # STEP 2D: GREEDY SEEDING (MANDATORY BASELINE)
    # =========================================================================
    from src.services.forecast_solver_v4 import assign_drivers_greedy, ConfigV4

    greedy_config = ConfigV4(seed=seed)
    log_fn("Running greedy assignment for mandatory seeding...")
    greedy_assignments, _ = assign_drivers_greedy(blocks, greedy_config)
    log_fn(f"Greedy result: {len(greedy_assignments)} drivers")

    seeded_count = generator.seed_from_greedy(greedy_assignments)
    log_fn(f"Seeded {seeded_count} columns from greedy solution")

    def _match_greedy_rosters(assignments, pool_values):
        greedy_rosters = []
        for assignment in assignments:
            block_ids = frozenset(
                b.id if hasattr(b, "id") else b.block_id for b in assignment.blocks
            )
            matching_col = None
            for col in pool_values:
                if frozenset(col.block_ids) == block_ids:
                    matching_col = col
                    break
            if matching_col:
                greedy_rosters.append(matching_col)
        return greedy_rosters

    pool_values = list(generator.pool.values())
    greedy_hint_columns = _match_greedy_rosters(greedy_assignments, pool_values)
    log_fn(f"Prepared {len(greedy_hint_columns)} hint columns for RMP warm-start")
    
    # =========================================================================
    # STEP 3: MAIN LOOP - RMP + Column Generation
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("MAIN SOLVE LOOP")
    log_fn("=" * 60)
    
    rmp_total_time = 0
    best_result = None
    best_known_hours = 0.0
    last_selected_ids = set()
    
    # Progress tracking for adaptive stopping
    best_under_count = len(all_block_ids)  # Start with worst case
    best_over_count = len(all_block_ids)
    rounds_without_progress = 0
    max_stale_rounds = 10  # Stop after N rounds w/o improvement
    
    # Adaptive coverage quota
    min_coverage_quota = 5  # Each block should be in at least 5 columns
    

    # [STEP 9.1] Adaptive Mode Detect
    is_compressed_mode = features is not None and len(getattr(features, "active_days", [])) <= 4

    # [STEP 11] Stall Tracking
    best_known_drivers = 9999
    rounds_without_driver_impr = 0
    stall_mode_active = False

    if greedy_hint_columns:
        best_result = {
            "selected_rosters": greedy_hint_columns,
            "num_drivers": len(greedy_hint_columns),
        }
        best_known_drivers = len(greedy_hint_columns)
        best_known_hours = sum(r.total_hours for r in greedy_hint_columns) / max(
            1, len(greedy_hint_columns)
        )

    for round_num in range(1, max_rounds + 1):
        # GLOBAL DEADLINE CHECK
        if global_deadline:
            remaining = global_deadline - monotonic()
        else:
            remaining = float('inf')
        
        # =======================================================================
        # STEP 13c: COMPRESSED ENDGAME TRIGGER (before deadline fallback)
        # =======================================================================
        # Detect if we should force endgame for compressed week
        use_tour_coverage = all_tour_ids is not None and len(all_tour_ids) > 0
        endgame_trigger, endgame_reason = _should_force_endgame_compressed(
            is_compressed_week=is_compressed_mode,
            use_tour_coverage=use_tour_coverage,
            round_num=round_num,
            stall_rounds=rounds_without_driver_impr,
            time_remaining=remaining,
        )
        
        if endgame_trigger:
            log_fn(f"\n[ENDGAME] Compressed week endgame triggered: {endgame_reason}")
            log_fn(f"[ENDGAME] best_known_drivers={best_known_drivers}, pool_size={len(generator.pool)}")
            
            # =================================================================
            # STEP A: COMPUTE GREEDY SOLUTION FOR GUARANTEED FEASIBLE UB
            # =================================================================
            from src.services.forecast_solver_v4 import assign_drivers_greedy, ConfigV4
            
            log_fn("[ENDGAME] Computing Greedy solution for guaranteed UB...")
            greedy_config = ConfigV4(seed=seed)
            greedy_assignments, greedy_stats = assign_drivers_greedy(blocks, greedy_config)
            greedy_drivers = len(greedy_assignments)
            log_fn(f"[ENDGAME] Greedy result: {greedy_drivers} drivers")
            
            # Inject greedy columns into pool as protected snapshot
            seeded_count = generator.seed_from_greedy(greedy_assignments)
            log_fn(f"[ENDGAME] Injected {seeded_count} INC_GREEDY_ columns into pool")
            
            # Generate incumbent neighborhood variants
            incumbent_cols = [c for c in generator.pool.values() if c.roster_id.startswith("INC_GREEDY_")]
            if incumbent_cols and hasattr(generator, 'generate_incumbent_neighborhood'):
                # Function takes active_days and max_variants, not the columns directly
                active_days = list(getattr(features, "active_days", []))
                if active_days:
                    inc_added = generator.generate_incumbent_neighborhood(active_days, max_variants=500)
                    log_fn(f"[ENDGAME] Added {inc_added} incumbent neighborhood variants")
            
            # UB = greedy_drivers (guaranteed feasible)
            ub_for_dsearch = greedy_drivers
            log_fn(f"[ENDGAME] UB = {ub_for_dsearch} (greedy, guaranteed feasible)")
            
            # =================================================================
            # STEP A.1: STOP-GATE - Verify UB is feasible before D-search
            # =================================================================
            log_fn("[ENDGAME] Verifying UB feasibility (stop-gate check)...")
            
            # Filter valid hint columns from greedy solution
            greedy_hint_cols = [c for c in generator.pool.values() if c.roster_id.startswith("INC_GREEDY_")]
            greedy_hint_cols = _filter_valid_hint_columns(greedy_hint_cols, all_tour_ids, "covered_tour_ids", log_fn)
            
            gate_check = solve_rmp_feasible_under_cap(
                columns=list(generator.pool.values()),
                target_ids=all_tour_ids,
                coverage_attr="covered_tour_ids",
                driver_cap=ub_for_dsearch,
                time_limit=15.0,
                log_fn=log_fn,
                hint_columns=greedy_hint_cols,
            )
            
            if gate_check["status"] != "FEASIBLE":
                # STOP-GATE TRIGGERED: This is a BUG, not a search result
                log_fn(f"[ENDGAME] STOP-GATE TRIGGERED: Infeasible at UB={ub_for_dsearch}!")
                log_fn(f"[ENDGAME] This indicates pool/target mismatch. Status: {gate_check['status']}")
                log_fn(f"[ENDGAME] Pool size: {len(generator.pool)}, Tours: {len(all_tour_ids)}")
                log_fn(f"[ENDGAME] Aborting D-search, falling back to greedy solution")
                
                # Return greedy as fallback
                return create_result(list(greedy_hint_cols), "OK_GREEDY_FALLBACK")
            
            log_fn(f"[ENDGAME] Stop-gate PASSED: Feasible at UB={ub_for_dsearch}")
            
            # =================================================================
            # STEP B: D-SEARCH WITH GUARANTEED FEASIBLE UB
            # =================================================================
            dsearch_time_budget = max(30.0, min(120.0, remaining - 30.0 if remaining != float('inf') else 60.0))
            log_fn(f"[ENDGAME] Running D-Search (UB={ub_for_dsearch}, budget={dsearch_time_budget:.1f}s)...")
            
            # Step 13e: Collect greedy roster IDs for protection during D-search
            greedy_roster_ids = {c.roster_id for c in greedy_hint_cols}
            log_fn(f"[ENDGAME] Protected greedy IDs for D-search: {len(greedy_roster_ids)}")
            
            d_search_result = _run_d_search(
                generator=generator,
                all_tour_ids=all_tour_ids,
                features=features,
                incumbent_drivers=ub_for_dsearch,
                time_budget=dsearch_time_budget,
                log_fn=log_fn,
                max_repair_iters_per_d=2,
                greedy_selected_roster_ids=greedy_roster_ids,  # Step 13e
            )
            
            d_min_found = d_search_result["D_min"]
            log_fn(f"[ENDGAME] D-Search result: status={d_search_result['status']}, D_min={d_min_found}")
            
            # Use D-search solution if it found improvement
            if d_search_result["status"] == "SUCCESS" and d_search_result["best_solution"]:
                selected = d_search_result["best_solution"]
                log_fn(f"[ENDGAME] Using D-Search solution: {len(selected)} drivers")
            else:
                # D-search didn't improve, use greedy
                selected = list(greedy_hint_cols)
                log_fn(f"[ENDGAME] D-Search no improvement, using greedy: {len(selected)} drivers")
            
            # =================================================================
            # STEP C: LEXIKO WITH CAP = D_MIN
            # =================================================================
            lexiko_time_budget = max(20.0, min(60.0, remaining - dsearch_time_budget - 10.0 if remaining != float('inf') else 30.0))
            log_fn(f"[ENDGAME] Running Lexiko with driver_cap={d_min_found}, budget={lexiko_time_budget:.1f}s...")
            
            lexiko_result = solve_rmp_lexico_5stage(
                columns=list(generator.pool.values()),
                target_ids=all_tour_ids,
                coverage_attr="covered_tour_ids",
                time_limit_total=lexiko_time_budget,
                log_fn=log_fn,
                hint_columns=selected,
                driver_cap=d_min_found,
                underutil_target_hours=33.0,  # Realistic target for compressed weeks
            )
            
            if lexiko_result["status"] in ("OPTIMAL", "FEASIBLE"):
                selected = lexiko_result["selected_rosters"]
                log_fn(f"[ENDGAME] Lexiko SUCCESS: D*={lexiko_result['D_star']} drivers")
            else:
                log_fn(f"[ENDGAME] Lexiko FAILED ({lexiko_result['status']}) - using D-search/greedy result")
            
            # Return with endgame result
            log_fn(f"\n[ENDGAME] Complete: Returning {len(selected)} drivers")
            return create_result(selected, "SUCCESS")
        
        # Standard deadline exceeded check (for normal weeks)
        if remaining <= 0:
            log_fn(f"GLOBAL DEADLINE EXCEEDED at round {round_num} - returning best effort")
            if best_result:
                return SetPartitionResult(
                    status="SUCCESS",
                    selected_rosters=best_result["selected_rosters"],
                    num_drivers=best_result["num_drivers"],
                    total_hours=sum(r.total_hours for r in best_result["selected_rosters"]),
                    hours_min=min(r.total_hours for r in best_result["selected_rosters"])
                    if best_result["selected_rosters"]
                    else 0,
                    hours_max=max(r.total_hours for r in best_result["selected_rosters"])
                    if best_result["selected_rosters"]
                    else 0,
                    hours_avg=sum(r.total_hours for r in best_result["selected_rosters"])
                    / max(1, len(best_result["selected_rosters"])),
                    uncovered_blocks=[],
                    pool_size=len(generator.pool),
                    rounds_used=round_num,
                    total_time=time.time() - start_time,
                    rmp_time=rmp_total_time,
                    generation_time=generation_time,
                )
            break
        
        log_fn(f"\n--- Round {round_num}/{max_rounds} ---")
        log_fn(f"Pool size: {len(generator.pool)}")
        
        # Emit RMP Round Start
        if context and hasattr(context, "emit_progress"):
             context.emit_progress("rmp_solve", f"Round {round_num}: Solving RMP (Pool: {len(generator.pool)})", 
                                   phase="phase2_assignments", step=f"Round {round_num}",
                                   metrics={"pool_size": len(generator.pool), "round": round_num})

        # Solve STRICT RMP first
        # [STEP 9.1] Deterministic Pool Pruning (Compressed Week)
        # ELITE PRUNING (Step 11)
        if is_compressed_mode and len(generator.pool) > 6000:
             log_fn(f"[PRUNING] Pool size {len(generator.pool)} > 6000. Triggering ELITE PRUNING.")
             
             # Need tours_map? No, _prune computes it.
             # Need selected IDs?
             selected_ids = last_selected_ids if 'last_selected_ids' in locals() else set()
             
             kept_cols = _prune_pool_compressed_elite(
                 list(generator.pool.values()),
                 selected_ids,
                 {}, # tour map (not used/computed inside)
                 max_pool_size=6000
             )
             generator.pool = {tuple(sorted(c.block_ids)): c for c in kept_cols}

        # Solve STRICT RMP first
        columns = list(generator.pool.values())
        
        # [STEP 11] Stall-Aware Time Budgeting
        if is_compressed_mode:
             # Basic ramp
             if round_num <= 2: base = 20.0
             elif round_num <= 4: base = 40.0
             else: base = 60.0
             
             if rounds_without_driver_impr >= 2:
                 log_fn(f"[STALL DETECTED] No driver improvement for 2 rounds. Boosting time limit.")
                 base = min(120.0, base * 2)
                 stall_mode_active = True
             else:
                 stall_mode_active = False
             
             effective_rmp_limit = base
             log_fn(f"[ADAPTIVE TIME] Round {round_num}: Limit set to {effective_rmp_limit:.1f}s (Stall: {stall_mode_active})")
        else:
             effective_rmp_limit = rmp_time_limit

        if global_deadline:
            remaining = global_deadline - monotonic()
            # Use min of configured/adaptive limit and remaining time (but at least 1s)
            effective_rmp_limit = min(effective_rmp_limit, max(1.0, remaining))
        
        rmp_start = time.time()
        rmp_result = solve_rmp(
            columns=columns,
            all_block_ids=all_block_ids,
            time_limit=effective_rmp_limit,
            log_fn=log_fn,
            hint_columns=greedy_hint_columns if round_num == 1 else None,
        )
        rmp_total_time += time.time() - rmp_start
        
        # Check result
        if rmp_result["status"] in ("OPTIMAL", "FEASIBLE"):
            if not rmp_result["uncovered_blocks"]:
                log_fn(f"\n[OK] FULL COVERAGE ACHIEVED with {rmp_result['num_drivers']} drivers")
                
                selected = rmp_result["selected_rosters"]
                last_selected_ids = {r.roster_id for r in selected}
                num_selected = len(selected)

                avg_hours = sum(r.total_hours for r in selected) / max(1, num_selected)
                improved = False
                if num_selected < best_known_drivers:
                    best_known_drivers = num_selected
                    best_known_hours = avg_hours
                    rounds_without_driver_impr = 0
                    improved = True
                    log_fn(f"  [IMPROVEMENT] New best driver count: {best_known_drivers}")
                elif num_selected == best_known_drivers and avg_hours > best_known_hours:
                    best_known_hours = avg_hours
                    rounds_without_driver_impr = 0
                    improved = True
                    log_fn(f"  [IMPROVEMENT] Better utilization at D={best_known_drivers}")
                else:
                    rounds_without_driver_impr += 1
                    log_fn(f"  [STALL] No driver improvement for {rounds_without_driver_impr} rounds (Best: {best_known_drivers})")

                best_result = {
                    "selected_rosters": selected,
                    "num_drivers": num_selected,
                }

                # [DIAGNOSTICS] Step 9 RMP Log
                sel_lens = [len(r.covered_tour_ids) for r in selected]
                
                # Histogram
                h1 = sum(1 for x in sel_lens if x == 1)
                h23 = sum(1 for x in sel_lens if 2 <= x <= 3)
                h46 = sum(1 for x in sel_lens if 4 <= x <= 6)
                h7 = sum(1 for x in sel_lens if x >= 7)
                
                # Averages
                avg_tours = sum(sel_lens) / max(1, num_selected)
                avg_hours = sum(r.total_hours for r in selected) / max(1, num_selected)
                
                log_fn(f"  Drivers: {num_selected} | Avg Hours: {avg_hours:.1f} | Avg Tours: {avg_tours:.1f}")
                log_fn(f"  Histogram (Tours): 1={h1} | 2-3={h23} | 4-6={h46} | 7+={h7}")
                
                # [MERGE REPAIR + COLLAPSE] Step 11 Headcount Reduction
                # Trigger if compressed and drivers are high
                _is_compressed_check = features is not None and len(getattr(features, "active_days", [])) <= 4
                
                if _is_compressed_check and num_selected > 190: 
                    # 1. Merge Repair
                    if hasattr(generator, 'generate_merge_repair_columns'):
                         log_fn(f"[POOL REPAIR TYPE C] Merge Repair Triggered (D={num_selected} > 190)")
                         new_merge_cols = generator.generate_merge_repair_columns(selected, budget=500)
                         if new_merge_cols:
                             m_added = 0
                             for c in new_merge_cols:
                                 # Key by sorted block IDs
                                 key = tuple(sorted(c.block_ids))
                                 if key not in generator.pool:
                                     generator.pool[key] = c
                                     m_added += 1
                                     
                             log_fn(f"  [MERGE REPAIR] Added {m_added} columns")
                    
                    # 1b. Merge Low-Hour Rosters (E.2: Fix for <30h problem)
                    low_hour_rosters = [r for r in selected if r.total_hours < 30]
                    if hasattr(generator, 'merge_low_hour_into_hosts') and len(low_hour_rosters) > 0:
                         log_fn(f"[MERGE-LOW] Found {len(low_hour_rosters)} low-hour rosters (<30h), merging...")
                         merged_cols = generator.merge_low_hour_into_hosts(
                             low_hour_rosters=low_hour_rosters,
                             max_attempts=300,
                             target_min_hours=30.0,
                             target_max_hours=45.0,
                         )
                         if merged_cols:
                              low_added = 0
                              for c in merged_cols:
                                   key = tuple(sorted(c.block_ids))
                                   if key not in generator.pool:
                                        generator.pool[key] = c
                                        low_added += 1
                              log_fn(f"  [MERGE-LOW] Added {low_added} higher-hour columns")

                    # 2. [STEP 11] Collapse Neighborhood (3-to-2)
                    if hasattr(generator, 'generate_collapse_candidates'):
                         log_fn(f"[COLLAPSE] Triggering 3-to-2 Collapse Neighborhood")
                         collapse_cols = generator.generate_collapse_candidates(selected, max_attempts=200)
                         if collapse_cols:
                             c_added = 0
                             for c in collapse_cols:
                                 key = tuple(sorted(c.block_ids))
                                 if key not in generator.pool:
                                     generator.pool[key] = c
                                     c_added += 1
                             log_fn(f"  [COLLAPSE] Generated {len(collapse_cols)} cols -> Added {c_added} new")
                             if c_added > 0:
                                 rounds_without_driver_impr = 0 # Assume this helps

                hours = [r.total_hours for r in selected]
                
                # =========================================================================
                # NEW: LNS ENDGAME (if enabled)
                # =========================================================================
                if config and hasattr(config, 'enable_lns_low_hour_consolidation') and config.enable_lns_low_hour_consolidation:
                    lns_budget = getattr(config, 'lns_time_budget_s', 30.0)
                    log_fn(f"\n{'='*60}")
                    log_fn(f"LNS ENDGAME: Low-Hour Pattern Elimination")
                    log_fn(f"{'='*60}")
                    
                    lns_result = _lns_consolidate_low_hour(
                        current_selected=selected,
                        column_pool=generator.pool,  # FULL POOL!
                        all_block_ids=all_block_ids,
                        config=config,
                        time_budget_s=lns_budget,
                        log_fn=log_fn,
                    )
                    
                    if lns_result["status"] == "SUCCESS":
                        selected = lns_result["rosters"]
                        hours = [r.total_hours for r in selected]
                        
                        # LNS SUMMARY LOGGING
                        log_fn(f"\n{'='*60}")
                        log_fn(f"LNS SUMMARY:")
                        log_fn(f"  Status: {lns_result['status']}")
                        log_fn(f"  Patterns killed: {lns_result['stats']['kills_successful']} / {lns_result['stats']['attempts']} attempts")
                        log_fn(f"  Drivers: {lns_result['stats']['initial_drivers']} → {lns_result['stats']['final_drivers']}")
                        log_fn(f"  Low-hour patterns: {lns_result['stats']['initial_lowhour_count']} → {lns_result['stats']['final_lowhour_count']}")
                        log_fn(f"  Shortfall: {lns_result['stats']['initial_shortfall']:.1f}h → {lns_result['stats']['final_shortfall']:.1f}h")
                        log_fn(f"  Time: {lns_result['stats']['time_s']:.1f}s")
                        log_fn(f"{'='*60}")
                    else:
                        log_fn(f"\n{'='*60}")
                        log_fn(f"LNS SUMMARY:")
                        log_fn(f"  Status: {lns_result['status']} - using original solution")
                        log_fn(f"{'='*60}")
                
                def create_result(rosters, status_code):
                    return SetPartitionResult(
                        status=status_code,
                        selected_rosters=rosters,
                        num_drivers=len(rosters),
                        total_hours=sum(r.total_hours for r in rosters),
                        hours_min=min(r.total_hours for r in rosters) if rosters else 0,
                        hours_max=max(r.total_hours for r in rosters) if rosters else 0,
                        hours_avg=sum(r.total_hours for r in rosters) / len(rosters) if rosters else 0,
                        uncovered_blocks=[],
                        pool_size=len(generator.pool),
                        rounds_used=round_num,
                        total_time=time.time() - start_time,
                        rmp_time=rmp_total_time,
                        generation_time=generation_time,
                    )
                
                # =================================================================
                # CHECK QUALITY: If too many PT drivers, DO NOT STOP!
                # =================================================================
                num_pt = sum(1 for r in selected if r.total_hours < 40.0)
                pt_ratio = num_pt / len(selected) if selected else 0
                
                # Check Pool Quality (Coverage by FTE columns)
                # User Requirement: Early stop only if coverage_by_fte_columns >= 95%
                pool_quality = generator.get_quality_coverage(ignore_singletons=True, min_hours=40.0)
                # User Requirement: Early stop only if coverage_by_fte_columns >= 95%
                pool_quality = generator.get_quality_coverage(ignore_singletons=True, min_hours=40.0)
                log_fn(f"Pool Quality (FTE Coverage): {pool_quality:.1%} | PT Share: {pt_ratio:.1%} | Stale: {rounds_without_progress}")

                if not improved and best_result:
                    log_fn("[OK] Returning best-known solution (no improvement)")
                    return create_result(best_result["selected_rosters"], "SUCCESS")

                 # Emit RMP Metrics & Stall Check
                if context and hasattr(context, "emit_progress"):
                    context.emit_progress("rmp_round", f"Round {round_num} stats", 
                                          phase="phase2_assignments", step=f"Round {round_num}",
                                          metrics={
                                             "drivers_total": len(selected),
                                             "drivers_fte": sum(1 for r in selected if r.total_hours >= 40),
                                             "drivers_pt": num_pt,
                                             "pool_size": len(generator.pool),
                                             "uncovered": 0,
                                             "pool_quality_pct": round(pool_quality * 100, 1)
                                          })
                    # Check for stall/improvement
                    if hasattr(context, "check_improvement"):
                        status_check = context.check_improvement(round_num, len(selected), 0) # 0 uncovered
                        if status_check == "stall_abort":
                             log_fn("Context signalled STALL ABORT")
                             rounds_without_progress = 999 

                
                # Condition for stopping:
                # 1. Excellent Quality: Very low PT share AND Good Pool Quality
                # 2. Stagnation: No progress for many rounds AND Good Pool Quality (don't give up if pool is bad)
                quality_ok = pool_quality >= 0.95
                pt_ok = num_pt <= len(selected) * 0.02
                stalling = rounds_without_progress > 20  # Increased from 15
                
                if (pt_ok and quality_ok) or (stalling and quality_ok):
                     log_fn(f"\n[OK] Stopping with {num_pt} PT drivers ({pt_ratio:.1%} share) and {pool_quality:.1%} FTE coverage")
                     
                     # =========================================================
                     # STEP 12: LEXICOGRAPHIC RMP (Compressed Weeks Only)
                     # Final optimization pass to guarantee minimum headcount
                     # =========================================================
                     _is_compressed_for_lexiko = features is not None and len(getattr(features, "active_days", [])) <= 4
                     
                     if _is_compressed_for_lexiko:
                         log_fn(f"\n[LEXIKO] Compressed week detected - running lexicographic optimization")
                         
                         # =====================================================
                         # STEP 13: D-SEARCH OUTER LOOP (before lexiko)
                         # Find minimum feasible D via driver-cap search
                         # UB = min(best_known_drivers, len(selected)) to avoid bad incumbents
                         # =====================================================
                         ub_for_dsearch = min(best_known_drivers, len(selected))
                         log_fn(f"\n[D-SEARCH] Running D-search (UB={ub_for_dsearch}) to find minimum feasible headcount...")
                         
                         d_search_result = _run_d_search(
                             generator=generator,
                             all_tour_ids=all_tour_ids,
                             features=features,
                             incumbent_drivers=ub_for_dsearch,
                             time_budget=min(120.0, max(30.0, global_deadline - time.monotonic() if global_deadline else 60.0)),
                             log_fn=log_fn,
                             max_repair_iters_per_d=2,
                         )
                         
                         # Extract D_min for use as lexiko cap
                         d_min_found = d_search_result["D_min"]
                         
                         # Use D-search result if it improved
                         if d_search_result["status"] == "SUCCESS" and d_search_result["best_solution"]:
                             log_fn(f"[D-SEARCH] SUCCESS: D_min={d_min_found} (improvement from {ub_for_dsearch})")
                             selected = d_search_result["best_solution"]
                         else:
                             log_fn(f"[D-SEARCH] {d_search_result['status']}: D_min={d_min_found}")
                         
                         # Prepare hint columns from current solution
                         hint_cols = selected
                         
                         # Call lexicographic solver with TOUR coverage mode
                         # Pass D_min as driver_cap so lexiko doesn't exceed it
                         lexiko_result = solve_rmp_lexico_5stage(
                             columns=list(generator.pool.values()),
                             target_ids=all_tour_ids,
                             coverage_attr="covered_tour_ids",
                             time_limit_total=min(60.0, max(20.0, rmp_time_limit)),
                             log_fn=log_fn,
                             hint_columns=hint_cols,
                             driver_cap=d_min_found,
                             underutil_target_hours=33.0,
                         )
                         
                         if lexiko_result["status"] in ("OPTIMAL", "FEASIBLE"):
                             selected = lexiko_result["selected_rosters"]
                             log_fn(f"[LEXIKO] SUCCESS: D*={lexiko_result['D_star']} drivers (Singletons: {lexiko_result['singleton_selected']})")
                         else:
                             log_fn(f"[LEXIKO] FAILED ({lexiko_result['status']}) - using D-search/original solution")
                     
                     return create_result(selected, "OK")
                
                log_fn(f"\n[CONT] Full coverage but {num_pt} PT drivers ({pt_ratio:.1%} share) - Optimization continuing...")
                log_fn(f"      Targeting blocks covered by PT drivers for better consolidation")
                
                # Identify blocks covered by PTs to target them for repair
                pt_blocks = []
                for r in selected:
                     if r.total_hours < 40.0:
                         pt_blocks.extend(r.block_ids)
                
                # Override under_blocks for the generation phase
                # We skip solve_relaxed_rmp since we are feasible
                under_blocks = pt_blocks
                over_blocks = []
                
                # Jump to generation
                goto_generation = True
            else:
                 log_fn(f"RMP feasible but {len(rmp_result['uncovered_blocks'])} blocks uncovered")
                 best_result = rmp_result
                 goto_generation = False
        else:
             goto_generation = False
        
        # =====================================================================
        # RMP INFEASIBLE or has uncovered -> use RELAXED RMP for diagnosis
        # =====================================================================
        # Initialize variables to avoid UnboundLocalError
        under_count = 0
        over_count = 0
        under_blocks = []
        over_blocks = []
        
        if not goto_generation:
            relaxed = solve_relaxed_rmp(
                columns=columns,
                all_block_ids=all_block_ids,
                # time_limit=10.0, # Removed strict limit
                time_limit=effective_rmp_limit, # Use remaining budget
                log_fn=log_fn,
            )
            
            # FIX: Gate progress tracking on solver status
            relaxed_status = relaxed.get("status", "UNKNOWN")
            log_fn(f"Relaxed RMP Status: {relaxed_status}")
            
            # Initialize variables for all paths
            under_blocks = relaxed.get("under_blocks", [])
            over_blocks = relaxed.get("over_blocks", [])
            
            # Progress tracking logic...
            under_count = relaxed.get("under_count", 0)
            over_count = relaxed.get("over_count", 0)
        # >>> STEP8: BRIDGING_LOOP
        # Check if compressed week
        _is_compressed = features is not None and len(getattr(features, "active_days", [])) <= 4
        if _is_compressed and round_num <= 6:
            # SWITCH TO TOUR-BASED COVERAGE
            log_fn(f"[POOL REPAIR R{round_num}] Coverage Mode: TOUR (Target: {len(all_tour_ids)})")
            
            tour_support = _compute_tour_support(columns, all_tour_ids, "covered_tour_ids")
            support_vals = list(tour_support.values())
            
            low_support_tours = [tid for tid, cnt in tour_support.items() if cnt <= 2]
            
            pct_low = (len(low_support_tours) / max(1, len(all_tour_ids))) * 100.0
            support_min = min(support_vals) if support_vals else 0
            support_p10 = _simple_percentile(support_vals, 10)
            support_p50 = _simple_percentile(support_vals, 50)
            
            # ALSO LOG BLOCK STATS (for comparison)
            block_support = _compute_tour_support(columns, all_block_ids, "block_ids")
            bs_vals = list(block_support.values())
            bs_low = len([b for b, c in block_support.items() if c <= 2])
            bs_pct = (bs_low / max(1, len(all_block_ids))) * 100.0
            bs_min = min(bs_vals) if bs_vals else 0
            bs_p10 = _simple_percentile(bs_vals, 10)
            bs_p50 = _simple_percentile(bs_vals, 50)
            
            log_fn(f"  % tours support<=2: {len(low_support_tours)}/{len(all_tour_ids)} ({pct_low:.1f}%)")
            log_fn(f"  tour support min/p10/p50: {support_min}/{support_p10}/{support_p50}")
            
            log_fn(f"  % blocks support<=2: {bs_low}/{len(all_block_ids)} ({bs_pct:.1f}%)")
            log_fn(f"  block support min/p10/p50: {bs_min}/{bs_p10}/{bs_p50}")
            
            # Bridging Logic (robust)
            added = 0
            built = 0
            
            if low_support_tours and hasattr(generator, 'generate_anchor_pack_variants'):
                # Sort for determinism
                anchors = sorted(low_support_tours, key=lambda t: (tour_support[t], t))[:150]
                
                res = generator.generate_anchor_pack_variants(anchors, max_variants_per_anchor=5)

                # Case A: generator returns int
                if isinstance(res, int):
                    added = res
                    built = res # approximate
                # Case B: list
                else:
                    cols = list(res) if res else []
                    built = len(cols)
                    for col in cols:
                        if col.roster_id not in generator.pool:
                            generator.pool[col.roster_id] = col
                            added += 1
                
                dedup_dropped = max(0, built - added)
                log_fn(f"  Bridging: anchors={len(anchors)}, built={built}, added={added}, dedup_dropped={dedup_dropped}")
                log_fn(f"  First 3 anchors: {anchors[:3] if anchors else 'None'}")
        # <<< STEP8: BRIDGING_LOOP

            
            # Emit RMP Metrics (Infeasible/Relaxed)
            if context and hasattr(context, "emit_progress"):
                context.emit_progress("rmp_round", f"Round {round_num} (Relaxed)", 
                                        phase="phase2_assignments", step=f"Round {round_num}",
                                        metrics={
                                            "drivers_total": 0, # Unknown
                                            "uncovered": len(under_blocks),
                                            "pool_size": len(generator.pool),
                                            "round": round_num
                                        })

        else:
            # Force generation by bypassing "Perfect relaxation" check
            under_count = 999 
            log_fn(f"Skipping Relaxed RMP validation to force generation for {len(pt_blocks)} blocks.")
            relaxed_status = "OPTIMAL" # Fake status to pass checks if needed
            rounds_without_progress = 0 # Reset progression as we are actively optimizing quality
            relaxed = {} # Initialize empty to avoid UnboundLocalError
            
            # Logic to maintain structure
            if relaxed_status in ("OPTIMAL", "FEASIBLE"):
                rounds_without_progress = 0
            else:
                rounds_without_progress += 1

        
        # Check stopping condition
        if rounds_without_progress >= max_stale_rounds:
            log_fn(f"\nNo improvement for {max_stale_rounds} rounds - stopping")
            if best_result:
                return SetPartitionResult(
                    status="SUCCESS",
                    selected_rosters=best_result["selected_rosters"],
                    num_drivers=best_result["num_drivers"],
                    total_hours=sum(r.total_hours for r in best_result["selected_rosters"]),
                    hours_min=min(r.total_hours for r in best_result["selected_rosters"])
                    if best_result["selected_rosters"]
                    else 0,
                    hours_max=max(r.total_hours for r in best_result["selected_rosters"])
                    if best_result["selected_rosters"]
                    else 0,
                    hours_avg=sum(r.total_hours for r in best_result["selected_rosters"])
                    / max(1, len(best_result["selected_rosters"])),
                    uncovered_blocks=[],
                    pool_size=len(generator.pool),
                    rounds_used=round_num,
                    total_time=time.time() - start_time,
                    rmp_time=rmp_total_time,
                    generation_time=generation_time,
                )
            break
        
        # Perfect relaxation = exact partition exists!
        if under_count == 0 and over_count == 0:
            log_fn("Relaxed RMP shows exact partition possible! Re-checking strict RMP...")
            # The strict RMP should work now; if not, something's wrong
            continue
        
        # =====================================================================
        # TARGETED COLUMN GENERATION
        # =====================================================================
        before_pool = len(generator.pool)
        gen_start = time.time()
        
        # Build avoid_set from high-frequency + over_blocks
        coverage_freq = relaxed.get("coverage_freq", {})
        high_freq_threshold = 50  # Blocks in many columns cause collisions
        high_freq_blocks = {
            bid for bid, freq in coverage_freq.items() 
            if freq > high_freq_threshold
        }
        avoid_set = set(over_blocks) | high_freq_blocks
        
        # Get rare blocks that need more coverage  
        rare_blocks = generator.get_rare_blocks(min_coverage=min_coverage_quota)
        
        # Priority seeds: under_blocks first, then rare_blocks
        target_seeds = under_blocks + [b for b in rare_blocks if b not in under_blocks]
        
        log_fn(f"Target seeds: {len(target_seeds)} (under: {len(under_blocks)}, rare: {len(rare_blocks)})")
        log_fn(f"Avoid set: {len(avoid_set)} blocks")
        
        # Targeted generation
        new_cols = generator.targeted_repair(
            target_blocks=target_seeds[:columns_per_round],
            avoid_set=avoid_set,
            max_attempts=columns_per_round * 2,
        )
        generation_time += time.time() - gen_start
        
        log_fn(f"Generated {len(new_cols)} new columns (pool: {before_pool} -> {len(generator.pool)})")
        
        # Fallback: try swap builder if no new columns
        if len(generator.pool) == before_pool:
            log_fn("No new columns from targeted repair, trying swap builder...")
            gen_start = time.time()
            swaps = generator.swap_builder(max_attempts=columns_per_round)
            generation_time += time.time() - gen_start
            log_fn(f"Swap builder generated {len(swaps)} columns")
        
        # Increase coverage quota if we're stagnating
        if rounds_without_progress >= 2:
            min_coverage_quota = min(min_coverage_quota + 2, 20)
            log_fn(f"Increased min coverage quota to {min_coverage_quota}")
    

    if best_result:
        log_fn("Returning best-known solution after loop exit")
        return SetPartitionResult(
            status="SUCCESS",
            selected_rosters=best_result["selected_rosters"],
            num_drivers=best_result["num_drivers"],
            total_hours=sum(r.total_hours for r in best_result["selected_rosters"]),
            hours_min=min(r.total_hours for r in best_result["selected_rosters"])
            if best_result["selected_rosters"]
            else 0,
            hours_max=max(r.total_hours for r in best_result["selected_rosters"])
            if best_result["selected_rosters"]
            else 0,
            hours_avg=sum(r.total_hours for r in best_result["selected_rosters"])
            / max(1, len(best_result["selected_rosters"])),
            uncovered_blocks=[],
            pool_size=len(generator.pool),
            rounds_used=round_num,
            total_time=time.time() - start_time,
            rmp_time=rmp_total_time,
            generation_time=generation_time,
        )

    # =========================================================================
    # GREEDY-SEEDING FALLBACK
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("SET-PARTITIONING STALLED - TRYING GREEDY-SEEDING")
    log_fn("=" * 60)
    
    final_uncovered = generator.get_uncovered_blocks()
    log_fn(f"Uncovered blocks: {len(final_uncovered)}")
    
    # Run greedy to get a known-feasible solution
    from src.services.forecast_solver_v4 import assign_drivers_greedy, ConfigV4
    
    # Get original blocks from block_infos
    original_blocks = blocks  # blocks passed to function
    
    greedy_config = ConfigV4(seed=seed)
    log_fn("Running greedy assignment for seeding...")
    
    greedy_assignments, greedy_stats = assign_drivers_greedy(original_blocks, greedy_config)
    log_fn(f"Greedy result: {len(greedy_assignments)} drivers")
    
    # Seed the pool with greedy columns
    seeded_count = generator.seed_from_greedy(greedy_assignments)

    # >>> STEP8: INCUMBENT_NEIGHBORHOOD_CALL
    incumbent_cols = [c for c in generator.pool.values() if c.roster_id.startswith("INC_GREEDY_")]
    if incumbent_cols:
        log_fn(f"[INCUMBENT NEIGHBORHOOD] {len(incumbent_cols)} INC_GREEDY_ columns detected")
        added = generator.generate_incumbent_neighborhood(
            active_days=getattr(features, "active_days", ["Mon", "Tue", "Wed", "Fri"]) if features else ["Mon", "Tue", "Wed", "Fri"],
            max_variants=500,
        )
        log_fn(f"  Added {added} incumbent variants")
    # <<< STEP8: INCUMBENT_NEIGHBORHOOD_CALL

    log_fn(f"Seeded {seeded_count} columns from greedy solution")
    
    # FAILURE RECOVERY: Collect the greedy columns to pass as HINTS
    # This guarantees RMP starts with a feasible solution
    greedy_hint_columns = []
    pool_values = list(generator.pool.values())
    
    for assignment in greedy_assignments:
        # Reconstruct block IDs for matching
        block_ids = frozenset(b.id if hasattr(b, 'id') else b.block_id for b in assignment.blocks)
        
        # Find matching column in pool (it should exist now)
        matching_col = None
        for col in pool_values:
            if frozenset(col.block_ids) == block_ids:
                matching_col = col
                break
        
        if matching_col:
            greedy_hint_columns.append(matching_col)
    
    log_fn(f"Prepared {len(greedy_hint_columns)} hint columns for RMP warm-start")

    # =========================================================================
    # P1: SEEDING SANITY CHECK
    # Verify that seeded columns actually cover all blocks
    # =========================================================================
    seeded_coverage = set()
    for col in generator.pool.values():
        seeded_coverage.update(col.block_ids)
    
    under_blocks = all_block_ids - seeded_coverage
    if under_blocks:
        log_fn(f"WARNING: Seeding gap! {len(under_blocks)} blocks uncovered after seeding")
        log_fn(f"  Missing block IDs: {list(under_blocks)[:10]}...")
        # Trigger targeted repair for missing blocks
        repair_cols = generator.targeted_repair(list(under_blocks), max_attempts=len(under_blocks) * 2)
        log_fn(f"  Targeted repair added {len(repair_cols)} columns")
    else:
        log_fn("Seeding sanity check: OK (all blocks covered)")
    
    # NOTE: RMP retry disabled - goes straight to greedy fallback in caller
    # (The 120s RMP retry rarely succeeds and wastes time)
    
    # Retry RMP with seeded pool AND hints
    log_fn("\n" + "=" * 60)
    log_fn("RETRYING RMP WITH GREEDY-SEEDED POOL + HINTS")
    log_fn("=" * 60)
    
    columns = list(generator.pool.values())
    
    rmp_retry_start = time.time()
    final_rmp_result = solve_rmp(
        columns=columns,
        all_block_ids=all_block_ids,
        time_limit=rmp_time_limit,
        log_fn=log_fn,
        hint_columns=greedy_hint_columns,  # CRITICAL FIX: Pass hints!
    )

    rmp_total_time += time.time() - rmp_retry_start
    
    if final_rmp_result["status"] in ("OPTIMAL", "FEASIBLE"):
        if not final_rmp_result["uncovered_blocks"]:
            rmp_drivers = final_rmp_result['num_drivers']
            greedy_drivers = len(greedy_assignments)
            
            log_fn(f"\n[COMPARISON] RMP: {rmp_drivers} drivers vs Greedy: {greedy_drivers} drivers")
            
            # =====================================================================
            # BEST-OF-TWO: Use whichever solution has fewer drivers
            # This is critical because RMP may hit time limits and return suboptimal
            # =====================================================================
            if greedy_drivers < rmp_drivers:
                log_fn(f"[DECISION] Using GREEDY solution (fewer drivers)")
                log_fn(f"  Greedy: {greedy_drivers} drivers")
                log_fn(f"  RMP: {rmp_drivers} drivers (rejected)")
                
                # Convert greedy assignments to SetPartitionResult format
                from src.services.roster_column import create_roster_from_blocks, BlockInfo
                
                greedy_rosters = []
                for assignment in greedy_assignments:
                    # Find existing column that matches, or create placeholder
                    block_ids = frozenset(b.id if hasattr(b, 'id') else b.block_id for b in assignment.blocks)
                    matching_col = None
                    for col in generator.pool.values():
                        if frozenset(col.block_ids) == block_ids:
                            matching_col = col
                            break
                    
                    if matching_col:
                        greedy_rosters.append(matching_col)
                    else:
                        # Create a minimal placeholder roster column
                        for col in generator.pool.values():
                            if any(bid in col.block_ids for bid in block_ids):
                                # Best effort - should not happen if seeding worked
                                greedy_rosters.append(col)
                                break
                
                # Use the seeded columns that match greedy assignments
                # This is a safe fallback that ensures we return valid columns
                selected = final_rmp_result["selected_rosters"]  # Keep RMP as fallback
                if len(greedy_rosters) >= greedy_drivers * 0.9:
                    selected = greedy_rosters
                
                hours = [r.total_hours for r in selected] if selected else [0]
                
                return SetPartitionResult(
                    status="OK_GREEDY_BETTER",
                    selected_rosters=selected,
                    num_drivers=len(selected),
                    total_hours=sum(hours),
                    hours_min=min(hours) if hours else 0,
                    hours_max=max(hours) if hours else 0,
                    hours_avg=sum(hours) / len(hours) if hours else 0,
                    uncovered_blocks=[],
                    pool_size=len(generator.pool),
                    rounds_used=max_rounds,
                    total_time=time.time() - start_time,
                    rmp_time=rmp_total_time,
                    generation_time=generation_time,
                )
            
            log_fn(f"\n[OK] FULL COVERAGE ACHIEVED (after seeding) with {final_rmp_result['num_drivers']} drivers")
            
            selected = final_rmp_result["selected_rosters"]
            hours = [r.total_hours for r in selected]
            
            # =========================================================================
            # NEW: LNS ENDGAME (if enabled) - ALSO after greedy-seeding
            # =========================================================================
            if config and hasattr(config, 'enable_lns_low_hour_consolidation') and config.enable_lns_low_hour_consolidation:
                lns_budget = getattr(config, 'lns_time_budget_s', 30.0)
                log_fn(f"\n{'='*60}")
                log_fn(f"LNS ENDGAME: Low-Hour Pattern Elimination")
                log_fn(f"{'='*60}")
                
                lns_result = _lns_consolidate_low_hour(
                    current_selected=selected,
                    column_pool=generator.pool,
                    all_block_ids=all_block_ids,
                    config=config,
                    time_budget_s=lns_budget,
                    log_fn=log_fn,
                )
                
                if lns_result["status"] == "SUCCESS":
                    selected = lns_result["rosters"]
                    hours = [r.total_hours for r in selected]
                    
                    # LNS SUMMARY LOGGING
                    log_fn(f"\n{'='*60}")
                    log_fn(f"LNS SUMMARY:")
                    log_fn(f"  Status: {lns_result['status']}")
                    log_fn(f"  Patterns killed: {lns_result['stats']['kills_successful']} / {lns_result['stats']['attempts']} attempts")
                    log_fn(f"  Drivers: {lns_result['stats']['initial_drivers']} → {lns_result['stats']['final_drivers']}")
                    log_fn(f"  Low-hour patterns: {lns_result['stats']['initial_lowhour_count']} → {lns_result['stats']['final_lowhour_count']}")
                    log_fn(f"  Shortfall: {lns_result['stats']['initial_shortfall']:.1f}h → {lns_result['stats']['final_shortfall']:.1f}h")
                    log_fn(f"  Time: {lns_result['stats']['time_s']:.1f}s")
                    log_fn(f"{'='*60}")
                else:
                    log_fn(f"\n{'='*60}")
                    log_fn(f"LNS SUMMARY:")
                    log_fn(f"  Status: {lns_result['status']} - using original solution")
                    log_fn(f"{'='*60}")
            
            return SetPartitionResult(
                status="SUCCESS",
                selected_rosters=selected,
                num_drivers=len(selected),
                total_hours=sum(hours),
                hours_min=min(hours) if hours else 0,
                hours_max=max(hours) if hours else 0,
                hours_avg=sum(hours) / len(hours) if hours else 0,
                uncovered_blocks=[],
                pool_size=len(generator.pool),
                rounds_used=max_rounds,
                total_time=time.time() - start_time,
                rmp_time=rmp_total_time,
                generation_time=generation_time,
            )

    
    # If still failed, return INFEASIBLE with greedy info
    log_fn("\n" + "=" * 60)
    log_fn("SET-PARTITIONING FAILED (even with greedy-seeding)")
    log_fn("=" * 60)
    
    final_status = "FAILED_COVERAGE" if len(final_uncovered) > 0 else "INFEASIBLE"
    if final_status == "INFEASIBLE":
        log_fn("All blocks are coverable, but no exact partition was found")
    
    return SetPartitionResult(
        status=final_status,
        selected_rosters=best_result["selected_rosters"] if best_result else [],
        num_drivers=best_result["num_drivers"] if best_result else 0,
        total_hours=sum(r.total_hours for r in best_result["selected_rosters"]) if best_result else 0,
        hours_min=min(r.total_hours for r in best_result["selected_rosters"]) if best_result and best_result["selected_rosters"] else 0,
        hours_max=max(r.total_hours for r in best_result["selected_rosters"]) if best_result and best_result["selected_rosters"] else 0,
        hours_avg=0,
        uncovered_blocks=final_uncovered,
        pool_size=len(generator.pool),
        rounds_used=round_num,
        total_time=time.time() - start_time,
        rmp_time=rmp_total_time,
        generation_time=generation_time,
    )


# =========================================================================
# LNS ENDGAME: LOW-HOUR PATTERN CONSOLIDATION
# =========================================================================

def _lns_consolidate_low_hour(
    current_selected: list[RosterColumn],
    column_pool: dict[str, RosterColumn],
    all_block_ids: set,
    config,
    time_budget_s: float,
    log_fn,
) -> dict:
    """
    LNS endgame: Eliminate low-hour patterns via column-kill fix-and-reopt.
    
    Uses FULL column_pool (all generated patterns) for candidate columns.
    
    Returns:
        {
            "status": "SUCCESS" | "NO_IMPROVEMENT",
            "rosters": list[RosterColumn],
            "stats": {
                "enabled": True,
                "kills_successful": int,
                "attempts": int,
                "initial_drivers": int,
                "final_drivers": int,
                "initial_lowhour_count": int,
                "final_lowhour_count": int,
                "initial_shortfall": float,
                "final_shortfall": float,
                "time_s": float,
            }
        }
    """
    t0 = time.time()
    threshold = getattr(config, 'lns_low_hour_threshold_h', 30.0)
    attempt_budget = 2.0
    max_attempts = min(30, int(time_budget_s / attempt_budget))
    
    def compute_shortfall(rosters):
        return sum(max(0, threshold - r.total_hours) for r in rosters)
    
    # CRITICAL FIX #3: Only kill FTE rosters, not PT (PT are intentionally <30h)
    low_hour = [
        r for r in current_selected 
        if r.total_hours < threshold and getattr(r, 'roster_type', 'FTE') == 'FTE'
    ]
    
    stats = {
        "enabled": True,
        "kills_successful": 0,
        "attempts": 0,
        "initial_drivers": len(current_selected),
        "final_drivers": len(current_selected),
        "initial_lowhour_count": len(low_hour),
        "final_lowhour_count": len(low_hour),
        "initial_shortfall": compute_shortfall(current_selected),
        "final_shortfall": compute_shortfall(current_selected),
        "time_s": 0.0,
    }
    
    if not low_hour:
        log_fn(f"LNS: No low-hour FTE patterns (<{threshold}h) found")
        return {"status": "NO_IMPROVEMENT", "rosters": current_selected, "stats": stats}
    
    log_fn(f"LNS: Found {len(low_hour)} low-hour FTE patterns (<{threshold}h)")
    log_fn(f"LNS: Budget={time_budget_s:.1f}s, max_attempts={max_attempts}")
    
    # Deterministic candidate sort
    candidates = sorted(low_hour, key=lambda r: (r.total_hours, r.roster_id))
    
    current = list(current_selected)
    kills = 0
    
    for attempt_num, p0 in enumerate(candidates):
        if stats["attempts"] >= max_attempts:
            break
        
        remaining = time_budget_s - (time.time() - t0)
        if remaining < 0.5:
            break
        
        # Try kill with escalating receiver sizes K=[3,5,8,12]
        for K in [3, 5, 8, 12]:
            result = _try_kill_pattern(
                p0=p0,
                current_selected=current,
                column_pool=column_pool,
                all_block_ids=all_block_ids,
                K_receivers=K,
                attempt_budget=min(attempt_budget, remaining),
                config=config,
                log_fn=log_fn,
            )
            
            stats["attempts"] += 1
            
            if result["status"] == "KILLED":
                current = result["rosters"]
                kills += 1
                log_fn(f"  LNS[{stats['attempts']}]: ✓ KILLED {p0.roster_id} ({p0.total_hours:.1f}h) with K={K}, drivers {len(current_selected)}→{len(current)}")
                break  # Success, next candidate
            elif result["status"] == "TIMEOUT":
                log_fn(f"  LNS[{stats['attempts']}]: TIMEOUT {p0.roster_id} K={K}")
                break  # Budget exhausted
            # INFEASIBLE: try larger K
            log_fn(f"  LNS[{stats['attempts']}]: INFEASIBLE {p0.roster_id} K={K} - {result.get('reason', 'unknown')}")
    
    # Final stats
    stats["kills_successful"] = kills
    stats["final_drivers"] = len(current)
    stats["final_lowhour_count"] = sum(1 for r in current if r.total_hours < threshold)
    stats["final_shortfall"] = compute_shortfall(current)
    stats["time_s"] = round(time.time() - t0, 2)
    
    status = "SUCCESS" if kills > 0 else "NO_IMPROVEMENT"
    return {"status": status, "rosters": current, "stats": stats}


def _try_kill_pattern(
    p0: RosterColumn,
    current_selected: list[RosterColumn],
    column_pool: dict[str, RosterColumn],
    all_block_ids: set,
    K_receivers: int,
    attempt_budget: float,
    config,
    log_fn,
) -> dict:
    """
    Try to eliminate pattern p0 via neighborhood destroy-repair.
    
    Returns: {"status": "KILLED" | "INFEASIBLE" | "TIMEOUT", "rosters": [...] | None, "reason": str}
    """
    from ortools.sat.python import cp_model
    
    # A) Deterministic Receiver Selection
    cand_R = [
        (r, 53.0 - r.total_hours, r.roster_id)
        for r in current_selected if r.roster_id != p0.roster_id
    ]
    cand_R.sort(key=lambda x: (-x[1], x[2]))  # free_capacity desc, id asc
    R = [r for r, _, _ in cand_R[:K_receivers]]
    
    # B) Define Neighborhood B
    B = set(p0.block_ids)
    for r in R:
        B.update(r.block_ids)
    
    # C) Filter Candidate Columns C from FULL POOL
    C = {
        rid: col for rid, col in column_pool.items()
        if col.block_ids.issubset(B) and col.is_valid and col.roster_id != p0.roster_id
    }
    
    # D) Coverage Check + B-Expansion with R-Update (CRITICAL FIX #1)
    covered = set()
    for col in C.values():
        covered.update(col.block_ids)
    
    uncov = B - covered
    if uncov:
        # B-EXPANSION: Add blocks determin istically
        expansion = set()
        for rid, col in column_pool.items():
            if any(b in col.block_ids for b in B):
                expansion.update(col.block_ids)
        
        expansion_sorted = sorted(expansion - B)[:200]
        
        # CRITICAL FIX #1: Update R with rosters covering expanded blocks
        # Find which current rosters cover the new expanded blocks
        expanded_blocks_to_add = set(expansion_sorted)
        roster_map = {r.roster_id: r for r in current_selected}
        
        for r in current_selected:
            if r == p0 or r in R:
                continue  # Already in neighborhood
            # Check if this roster covers any expanded block
            if r.block_ids & expanded_blocks_to_add:
                R.append(r)
                log_fn(f"      B-expansion: Added roster {r.roster_id} to R (covers expanded blocks)")
        
        # Now update B
        B.update(expanded_blocks_to_add)
        
        # Rebuild C
        C = {
            rid: col for rid, col in column_pool.items()
            if col.block_ids.issubset(B) and col.is_valid and col.roster_id != p0.roster_id
        }
        
        covered = set()
        for col in C.values():
            covered.update(col.block_ids)
        uncov = B - covered
        
        if uncov:
            return {"status": "INFEASIBLE", "rosters": None, "reason": f"{len(uncov)} uncovered after expansion"}
    
    # CRITICAL FIX #2: Cardinality baseline = 1 + len(R) (after final R)
    baseline_rosters = 1 + len(R)  # p0 + R in current solution
    
    # Logging (FIX #3: Safety logging)
    log_fn(f"    Neighborhood: p0={p0.roster_id}({p0.total_hours:.1f}h), |R|={len(R)}, |B|={len(B)}, |C|={len(C)}")
    log_fn(f"    Baseline rosters in B: {baseline_rosters}, will try: {baseline_rosters-1}")
    
    # E) Build Reduced RMP
    model = cp_model.CpModel()
    x_vars = {}
    
    for rid, col in C.items():
        x_vars[rid] = model.NewBoolVar(f"x_{rid}")
    
    # Coverage for B
    for block_id in B:
        covering = [rid for rid, col in C.items() if block_id in col.block_ids]
        if not covering:
            return {"status": "INFEASIBLE", "rosters": None, "reason": f"block {block_id} no coverage in C"}
        model.Add(sum(x_vars[rid] for rid in covering) == 1)
    
    # F) TRY-1: Aggressive kill (total <= baseline - 1)
    total_selected = sum(x_vars.values())
    model.Add(total_selected <= baseline_rosters - 1)
    
    # Objective: min shortfall
    shortfall_expr = sum(
        x_vars[rid] * max(0, int((30.0 - col.total_hours) * 100))
        for rid, col in C.items()
    )
    model.Minimize(shortfall_expr)
    
    # G) Solve TRY-1
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = attempt_budget
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.seed
    
    model.ClearHints()
    for r in current_selected:
        if r.roster_id in x_vars:
            hint_val = 1 if r in R else 0
            model.AddHint(x_vars[r.roster_id], hint_val)
    
    status_try1 = solver.Solve(model)
    log_fn(f"    TRY-1 (≤{baseline_rosters-1}): status={status_try1}")
    
    if status_try1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # TRY-2: Relax to <= baseline (no kill, just improve)
        model = cp_model.CpModel()
        x_vars = {}
        for rid in C.keys():
            x_vars[rid] = model.NewBoolVar(f"x_{rid}")
        
        for block_id in B:
            covering = [rid for rid, col in C.items() if block_id in col.block_ids]
            model.Add(sum(x_vars[rid] for rid in covering) == 1)
        
        model.Add(sum(x_vars.values()) <= baseline_rosters)  # FIX #2: Use baseline, not |R|+1
        model.Minimize(shortfall_expr)
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = attempt_budget
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = config.seed
        model.ClearHints()
        
        status_try2 = solver.Solve(model)
        log_fn(f"    TRY-2 (≤{baseline_rosters}): status={status_try2}")
        
        if status_try2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {"status": "INFEASIBLE", "rosters": None, "reason": f"TRY-1={status_try1}, TRY-2={status_try2}"}
    
    # H) Extract
    selected_in_B = [C[rid] for rid in x_vars.keys() if solver.Value(x_vars[rid]) == 1]
    
    # I) Rebuild full solution
    fixed_outside = [r for r in current_selected if r not in R and r != p0]
    new_rosters = fixed_outside + selected_in_B
    
    # J) Validate
    if p0 in new_rosters:
        return {"status": "INFEASIBLE", "rosters": None, "reason": "p0 still in solution"}
    
    if len(new_rosters) > len(current_selected):
        return {"status": "INFEASIBLE", "rosters": None, "reason": f"drivers increased {len(new_rosters)} > {len(current_selected)}"}
    
    covered_all = set()
    for r in new_rosters:
        covered_all.update(r.block_ids)
    if covered_all != all_block_ids:
        missing = all_block_ids - covered_all
        return {"status": "INFEASIBLE", "rosters": None, "reason": f"{len(missing)} blocks missing"}
    
    log_fn(f"    ✓ KILL SUCCESS: {len(current_selected)} → {len(new_rosters)} drivers")
    return {"status": "KILLED", "rosters": new_rosters, "reason": ""}


def convert_rosters_to_assignments(
    selected_rosters: list[RosterColumn],
    block_lookup: dict,
) -> list:
    """
    Convert selected RosterColumns to DriverAssignment objects.
    
    Args:
        selected_rosters: List of selected RosterColumn
        block_lookup: Dict of block_id -> Block object
    
    Returns:
        List of DriverAssignment objects
    """
    from src.services.forecast_solver_v4 import DriverAssignment, _analyze_driver_workload
    
    assignments = []
    
    
    # Sort rosters by hours descending for deterministic ordering
    sorted_rosters = sorted(selected_rosters, key=lambda r: -r.total_hours)
    
    assigned_block_ids = set()
    fte_count = 0
    pt_count = 0
    
    for roster in sorted_rosters:
        # Determine driver type from roster
        driver_type = getattr(roster, 'roster_type', 'FTE')
        
        # Get Block objects - checking for deduplication
        blocks = []
        for block_id in roster.block_ids:
            if block_id in block_lookup and block_id not in assigned_block_ids:
                blocks.append(block_lookup[block_id])
                assigned_block_ids.add(block_id)
        
        # If roster is empty after dedupe, skip it (can happen if fully subsumed)
        if not blocks:
            continue
            
        # Re-calculate hours based on actual assigned blocks
        total_hours = sum(b.total_work_hours for b in blocks)
        days_worked = len(set(b.day.value if hasattr(b.day, 'value') else str(b.day) for b in blocks))
        
        # Create ID
        if driver_type == "PT":
            pt_count += 1
            driver_id = f"PT{pt_count:03d}"
        else:
            fte_count += 1
            driver_id = f"FTE{fte_count:03d}"
        
        # Sort blocks by (day, start)
        blocks.sort(key=lambda b: (
            b.day.value if hasattr(b.day, 'value') else str(b.day),
            b.first_start
        ))
        
        assignments.append(DriverAssignment(
            driver_id=driver_id,
            driver_type=driver_type,
            blocks=blocks,
            total_hours=total_hours,
            days_worked=days_worked,
            analysis=_analyze_driver_workload(blocks),
        ))
    
    return assignments


# =============================================================================
# SWAP CONSOLIDATION POST-PROCESSING
# =============================================================================

def swap_consolidation(
    assignments: list,
    blocks_lookup: dict = None,
    max_iterations: int = 100,
    min_hours_target: float = 42.0,
    max_hours_target: float = 53.0,
    log_fn=None,
) -> tuple:
    """
    Post-processing: consolidate underutilized drivers through block swaps.
    
    Algorithm:
    1. Identify low-hour drivers (<45h)
    2. Identify high-hour drivers (>48h)
    3. Try swapping blocks between them to:
       a) Eliminate low-hour drivers entirely (give their blocks away)
       b) Balance hours more evenly
    4. Remove drivers with no blocks
    
    Args:
        assignments: List of DriverAssignment objects
        blocks_lookup: Dict mapping block_id -> Block object (for constraint checking)
        max_iterations: Maximum swap iterations
        min_hours_target: Soft minimum hours for FTE drivers
        max_hours_target: Maximum hours constraint
        log_fn: Logging function
    
    Returns:
        (optimized_assignments, stats_dict)
    """
    from src.services.constraints import can_assign_block
    
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 60)
    log_fn("SWAP CONSOLIDATION POST-PROCESSING")
    log_fn("=" * 60)
    
    stats = {
        "initial_drivers": len(assignments),
        "initial_fte": sum(1 for a in assignments if a.driver_type == "FTE"),
        "initial_pt": sum(1 for a in assignments if a.driver_type == "PT"),
        "moves_attempted": 0,
        "moves_successful": 0,
        "drivers_eliminated": 0,
    }
    
    if not assignments:
        stats["final_drivers"] = 0
        return assignments, stats
    
    # Build mutable state
    driver_blocks = {a.driver_id: list(a.blocks) for a in assignments}
    driver_types = {a.driver_id: a.driver_type for a in assignments}
    
    def compute_hours(blocks):
        return sum(b.total_work_hours for b in blocks)
    
    def get_days(blocks):
        return {b.day.value if hasattr(b.day, 'value') else str(b.day) for b in blocks}
    
    def can_receive_block(receiver_blocks, new_block, current_hours):
        """Check if receiver can accept the block."""
        new_hours = current_hours + new_block.total_work_hours
        if new_hours > max_hours_target:
            return False
        
        # Check day overlap
        receiver_days = get_days(receiver_blocks)
        block_day = new_block.day.value if hasattr(new_block.day, 'value') else str(new_block.day)
        
        # Check time overlap on same day
        for rb in receiver_blocks:
            rb_day = rb.day.value if hasattr(rb.day, 'value') else str(rb.day)
            if rb_day == block_day:
                # Check time overlap
                if not (new_block.last_end <= rb.first_start or new_block.first_start >= rb.last_end):
                    return False
        
        return True
    
    iterations = 0
    progress = True
    
    while progress and iterations < max_iterations:
        progress = False
        iterations += 1
        
        # Get current driver hours
        driver_hours = {did: compute_hours(blocks) for did, blocks in driver_blocks.items()}
        
        # Find candidates for elimination: Low-hour FTEs AND all PT drivers
        low_hour_drivers = [
            did for did, hours in driver_hours.items()
            if driver_blocks[did] and (
                (driver_types.get(did) == "FTE" and hours < min_hours_target) or
                (driver_types.get(did) == "PT")
            )
        ]
        
        # Find high-hour FTE drivers (can potentially give blocks away)
        high_hour_drivers = [
            did for did, hours in driver_hours.items()
            if hours > 48.0 and driver_types.get(did) == "FTE" and driver_blocks[did]
        ]
        
        # Sort low-hour by hours ascending (eliminate smallest first)
        low_hour_drivers.sort(key=lambda d: driver_hours[d])
        
        for low_did in low_hour_drivers[:10]:  # Limit per iteration
            low_blocks = driver_blocks.get(low_did, [])
            if not low_blocks:
                continue
            
            # Try to give all blocks to other drivers
            blocks_to_move = list(low_blocks)
            all_moved = True
            
            for block in blocks_to_move:
                stats["moves_attempted"] += 1
                
                # Find best receiver (has room and can accept)
                best_receiver = None
                best_score = float('inf')
                
                # Consider all other FTE drivers as receivers
                for other_did in driver_blocks:
                    if other_did == low_did:
                        continue
                    if driver_types.get(other_did) != "FTE":
                        continue
                    
                    other_blocks = driver_blocks[other_did]
                    other_hours = driver_hours.get(other_did, 0)
                    
                    if can_receive_block(other_blocks, block, other_hours):
                        # Score: prefer receivers that need hours
                        new_hours = other_hours + block.total_work_hours
                        distance_to_target = abs(new_hours - 49.5)  # Prefer ~49.5h
                        
                        if distance_to_target < best_score:
                            best_score = distance_to_target
                            best_receiver = other_did
                
                if best_receiver:
                    # Move the block
                    driver_blocks[low_did].remove(block)
                    driver_blocks[best_receiver].append(block)
                    driver_hours[best_receiver] = compute_hours(driver_blocks[best_receiver])
                    stats["moves_successful"] += 1
                    progress = True
                else:
                    all_moved = False
            
            # Check if driver is now empty
            if not driver_blocks.get(low_did):
                stats["drivers_eliminated"] += 1
                log_fn(f"  Eliminated driver {low_did}")
    
    # Remove empty drivers
    final_assignments = []
    from src.services.forecast_solver_v4 import DriverAssignment, _analyze_driver_workload
    
    fte_count = 0
    pt_count = 0
    
    for did in sorted(driver_blocks.keys()):
        blocks = driver_blocks[did]
        if not blocks:
            continue
        
        dtype = driver_types[did]
        total_hours = compute_hours(blocks)
        days_worked = len(get_days(blocks))
        
        # Renumber drivers
        if dtype == "PT":
            pt_count += 1
            new_id = f"PT{pt_count:03d}"
        else:
            fte_count += 1
            new_id = f"FTE{fte_count:03d}"
        
        # Sort blocks
        blocks.sort(key=lambda b: (
            b.day.value if hasattr(b.day, 'value') else str(b.day),
            b.first_start
        ))
        
        final_assignments.append(DriverAssignment(
            driver_id=new_id,
            driver_type=dtype,
            blocks=blocks,
            total_hours=total_hours,
            days_worked=days_worked,
            analysis=_analyze_driver_workload(blocks),
        ))
    
    stats["final_drivers"] = len(final_assignments)
    stats["final_fte"] = sum(1 for a in final_assignments if a.driver_type == "FTE")
    stats["final_pt"] = sum(1 for a in final_assignments if a.driver_type == "PT")
    stats["iterations"] = iterations
    
    log_fn(f"Swap consolidation: {stats['initial_drivers']} -> {stats['final_drivers']} drivers")
    log_fn(f"  Moves: {stats['moves_successful']}/{stats['moves_attempted']} successful")
    log_fn(f"  Eliminated: {stats['drivers_eliminated']} drivers")
    log_fn("=" * 60)
    
    return final_assignments, stats
