"""
Stage0 Set-Packing Solver for 3er Blocks
=========================================
Solves a maximum weighted independent set problem to find the
maximum number of disjoint 3er blocks.

This provides:
- stage0_raw_obj: Maximum 3er on raw pool (before capping)
- stage0_capped_obj: Maximum 3er on capped pool (used in Phase1)

The equality constraint in Phase1 uses stage0_capped_obj.
"""

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

from ortools.sat.python import cp_model

from src.domain.models import Block, Tour

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class Stage0Result:
    """Result from Stage0 3er Set-Packing."""
    
    # Raw pool results (before capping)
    raw_3er_count: int = 0
    raw_3er_obj: int = 0
    raw_bound: int = 0
    raw_status: str = "UNKNOWN"
    raw_gap: float = 0.0
    
    # Capped pool results (after capping)
    capped_3er_obj: int = 0
    capped_bound: int = 0
    capped_status: str = "UNKNOWN"
    capped_gap: float = 0.0
    
    # Delta
    delta_raw_vs_capped: int = 0
    
    # Selected 3er block IDs (from capped solve)
    selected_3er_ids: list[str] = field(default_factory=list)
    
    # Overlap diagnostics
    deg3_max: int = 0
    deg3_p95: float = 0.0
    hot_tour_count: int = 0
    
    # Timing
    solve_time_s: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "raw_3er_count": self.raw_3er_count,
            "raw_3er_obj": self.raw_3er_obj,
            "raw_bound": self.raw_bound,
            "raw_status": self.raw_status,
            "raw_gap": round(self.raw_gap, 4),
            "capped_3er_obj": self.capped_3er_obj,
            "capped_bound": self.capped_bound,
            "capped_status": self.capped_status,
            "capped_gap": round(self.capped_gap, 4),
            "delta_raw_vs_capped": self.delta_raw_vs_capped,
            "selected_3er_count": len(self.selected_3er_ids),
            "deg3_max": self.deg3_max,
            "deg3_p95": round(self.deg3_p95, 2),
            "hot_tour_count": self.hot_tour_count,
            "solve_time_s": round(self.solve_time_s, 3),
        }


# =============================================================================
# OVERLAP DIAGNOSTICS
# =============================================================================

def compute_deg3_metrics(blocks_3er: list[Block], tours: list[Tour]) -> dict:
    """
    Compute 3er-degree metrics for overlap diagnostics.
    
    deg3[tour] = number of 3er blocks containing this tour
    """
    import statistics
    
    tour_ids = {t.id for t in tours}
    deg3 = {tid: 0 for tid in tour_ids}
    
    for block in blocks_3er:
        for tour in block.tours:
            if tour.id in deg3:
                deg3[tour.id] += 1
    
    # Filter to tours with deg3 > 0
    deg3_values = [v for v in deg3.values() if v > 0]
    
    if not deg3_values:
        return {"deg3_max": 0, "deg3_p95": 1.0, "hot_tour_count": 0}
    
    deg3_max = max(deg3_values)
    
    # P95 with guardrail
    if len(deg3_values) >= 20:
        p95 = statistics.quantiles(deg3_values, n=20)[18]
    else:
        p95 = max(deg3_values)
    
    # Hot tours: tours in more 3er blocks than median
    median = statistics.median(deg3_values)
    hot_tour_count = sum(1 for v in deg3_values if v > median)
    
    return {
        "deg3_max": deg3_max,
        "deg3_p95": p95,
        "hot_tour_count": hot_tour_count,
    }


# =============================================================================
# STAGE0 SOLVER
# =============================================================================

def solve_stage0_3er_packing(
    blocks_3er: list[Block],
    tours: list[Tour],
    time_limit: float = 10.0,
    seed: int = 42,
    log_fn=None,
) -> Stage0Result:
    """
    Solve Stage0: Maximum disjoint 3er packing.
    
    This is a Set-Packing problem:
    - Variables: use[b] ∈ {0,1} for each 3er block b
    - Constraint: For each tour t, Σ_{b contains t} use[b] <= 1 (disjoint)
    - Objective: Maximize Σ use[b]
    
    Args:
        blocks_3er: List of 3er blocks (len(b.tours) == 3)
        tours: List of all tours
        time_limit: Time limit in seconds
        seed: Random seed for determinism
        log_fn: Optional logging callback
    
    Returns:
        Stage0Result with objective, bound, status, and selected blocks
    """
    def log(msg: str):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    
    start = perf_counter()
    result = Stage0Result()
    
    # Count raw 3er
    result.raw_3er_count = len(blocks_3er)
    
    if not blocks_3er:
        log("[Stage0] No 3er blocks to pack")
        result.raw_status = "NO_BLOCKS"
        result.capped_status = "NO_BLOCKS"
        result.solve_time_s = perf_counter() - start
        return result
    
    log(f"[Stage0] Packing {len(blocks_3er)} 3er blocks over {len(tours)} tours")
    
    # Compute deg3 metrics
    deg3_metrics = compute_deg3_metrics(blocks_3er, tours)
    result.deg3_max = deg3_metrics["deg3_max"]
    result.deg3_p95 = deg3_metrics["deg3_p95"]
    result.hot_tour_count = deg3_metrics["hot_tour_count"]
    
    log(f"[Stage0] deg3_max={result.deg3_max}, deg3_p95={result.deg3_p95:.1f}, hot_tours={result.hot_tour_count}")
    
    # Build tour -> block indices mapping
    tour_to_blocks: dict[str, list[int]] = {}
    for idx, block in enumerate(blocks_3er):
        for tour in block.tours:
            if tour.id not in tour_to_blocks:
                tour_to_blocks[tour.id] = []
            tour_to_blocks[tour.id].append(idx)
    
    # Create CP-SAT model
    model = cp_model.CpModel()
    
    # Variables: use[b] = 1 if block b is selected
    use_block = [model.NewBoolVar(f"use_{b.id}") for b in blocks_3er]
    
    # Constraints: Each tour can be in at most 1 selected 3er block
    for tour_id, block_indices in tour_to_blocks.items():
        if len(block_indices) > 1:
            model.Add(sum(use_block[idx] for idx in block_indices) <= 1)
    
    # Objective: Maximize selected 3er blocks
    model.Maximize(sum(use_block))
    
    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 1  # Determinism
    
    status = solver.Solve(model)
    
    # Map status
    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    result.raw_status = status_map.get(status, "UNKNOWN")
    result.capped_status = result.raw_status  # Same for now (no separate capped solve)
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result.raw_3er_obj = int(solver.ObjectiveValue())
        result.raw_bound = int(solver.BestObjectiveBound())
        result.capped_3er_obj = result.raw_3er_obj  # Same pool
        result.capped_bound = result.raw_bound
        
        # Compute gap
        if result.raw_bound > 0:
            result.raw_gap = (result.raw_bound - result.raw_3er_obj) / result.raw_bound
            result.capped_gap = result.raw_gap
        
        # Extract selected blocks
        for idx, block in enumerate(blocks_3er):
            if solver.Value(use_block[idx]) == 1:
                result.selected_3er_ids.append(block.id)
        
        log(f"[Stage0] SOLVED: obj={result.raw_3er_obj}, bound={result.raw_bound}, "
            f"status={result.raw_status}, gap={result.raw_gap:.2%}")
    else:
        log(f"[Stage0] FAILED: status={result.raw_status}")
    
    result.solve_time_s = perf_counter() - start
    return result


def solve_stage0_dual(
    blocks_raw: list[Block],
    blocks_capped: list[Block],
    tours: list[Tour],
    time_limit: float = 20.0,
    seed: int = 42,
    log_fn=None,
) -> Stage0Result:
    """
    Solve Stage0 twice: once on raw pool, once on capped pool.
    
    This provides the comparison metrics for capping impact analysis.
    
    Args:
        blocks_raw: All 3er blocks before capping
        blocks_capped: 3er blocks after capping (subset of raw)
        tours: List of all tours
        time_limit: Total time limit (split between both solves)
        seed: Random seed
        log_fn: Logging callback
    
    Returns:
        Stage0Result with both raw and capped objectives
    """
    def log(msg: str):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    
    start = perf_counter()
    
    # Filter to 3er only
    raw_3er = [b for b in blocks_raw if len(b.tours) == 3]
    capped_3er = [b for b in blocks_capped if len(b.tours) == 3]
    
    log(f"[Stage0 Dual] Raw 3er: {len(raw_3er)}, Capped 3er: {len(capped_3er)}")
    
    # Solve on raw pool
    half_limit = time_limit / 2
    raw_result = solve_stage0_3er_packing(raw_3er, tours, half_limit, seed, log_fn)
    
    # Solve on capped pool
    capped_result = solve_stage0_3er_packing(capped_3er, tours, half_limit, seed, log_fn)
    
    # Combine results
    result = Stage0Result(
        raw_3er_count=len(raw_3er),
        raw_3er_obj=raw_result.raw_3er_obj,
        raw_bound=raw_result.raw_bound,
        raw_status=raw_result.raw_status,
        raw_gap=raw_result.raw_gap,
        capped_3er_obj=capped_result.raw_3er_obj,
        capped_bound=capped_result.raw_bound,
        capped_status=capped_result.raw_status,
        capped_gap=capped_result.raw_gap,
        delta_raw_vs_capped=raw_result.raw_3er_obj - capped_result.raw_3er_obj,
        selected_3er_ids=capped_result.selected_3er_ids,
        deg3_max=raw_result.deg3_max,
        deg3_p95=raw_result.deg3_p95,
        hot_tour_count=raw_result.hot_tour_count,
        solve_time_s=perf_counter() - start,
    )
    
    log(f"[Stage0 Dual] Delta: raw_obj={result.raw_3er_obj} - capped_obj={result.capped_3er_obj} = {result.delta_raw_vs_capped}")
    
    return result
