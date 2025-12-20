"""
Model Strip Test V2 - With Proper Symmetry Breaking
====================================================

Stage 1: drv[b] IntVar-only + Anchor Fixing + Greedy Hints
Stage 2+: Minimal Presence Bools for NoOverlap + Rest

Key fixes:
- No x[b,k] bools in Stage 1 (only drv IntVars)
- Anchor Fixing: drv[anchor[k]] == k for each driver
- Greedy hints for all drv[b]
- stop_after_first_solution = True
"""

import time
import logging
from ortools.sat.python import cp_model
from collections import defaultdict

logger = logging.getLogger("ModelStripTestV2")

DAY_MINUTES = 24 * 60  # 1440


def run_model_strip_test_v2(
    blocks: list,
    n_drivers: int,
    greedy_assignments: dict,
    time_limit: float = 60.0,
    log_fn=None,
) -> dict:
    """
    Run 5-stage model strip test with proper symmetry breaking.
    
    Key improvements:
    - Stage 1 uses drv[b] IntVar-only (no bools!)
    - Anchor fixing from greedy solution
    - Greedy hints for all blocks
    """
    if log_fn is None:
        log_fn = lambda msg: logger.info(msg)
    
    log_fn("=" * 70)
    log_fn("MODEL STRIP TEST V2 - With Proper Symmetry Breaking")
    log_fn("=" * 70)
    log_fn(f"Blocks: {len(blocks)}")
    log_fn(f"N_drivers: {n_drivers}")
    log_fn(f"Time limit per stage: {time_limit}s")
    log_fn(f"Greedy hints available: {len(greedy_assignments)}")
    
    # Prepare block info
    B = len(blocks)
    N = n_drivers
    
    block_info = []
    blocks_by_day = {d: [] for d in range(7)}
    block_id_to_idx = {}
    
    for i, b in enumerate(blocks):
        day = get_day_idx(b)
        start = get_start_min(b)
        end = get_end_min(b)
        span = end - start
        work = get_work_min(b)
        tours = len(b.tours) if hasattr(b, 'tours') else 1
        block_id = get_block_id(b)
        
        block_info.append({
            "id": block_id,
            "day": day,
            "start": start,
            "end": end,
            "span": span,
            "work": work,
            "tours": tours,
        })
        blocks_by_day[day].append(i)
        block_id_to_idx[block_id] = i
    
    # Build anchor map from greedy: for each driver, pick smallest block_idx as anchor
    driver_blocks = defaultdict(list)
    for block_id, driver_idx in greedy_assignments.items():
        if block_id in block_id_to_idx:
            b_idx = block_id_to_idx[block_id]
            driver_blocks[driver_idx].append(b_idx)
    
    anchor_map = {}  # driver_idx -> anchor block_idx
    for driver_idx in sorted(driver_blocks.keys()):
        if driver_idx < N and driver_blocks[driver_idx]:
            anchor_map[driver_idx] = min(driver_blocks[driver_idx])
    
    log_fn(f"Anchor blocks: {len(anchor_map)} drivers have anchors")
    
    results = {}
    
    # =========================================================================
    # STAGE 1: drv[b] IntVar-only + Anchor Fixing + Hints
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("STAGE 1: drv[b] IntVar + Anchor Fixing + Hints (NO BOOLS!)")
    log_fn("=" * 60)
    
    model = cp_model.CpModel()
    
    # drv[b] = driver index for block b (0..N-1)
    drv = [model.NewIntVar(0, N - 1, f"drv_{i}") for i in range(B)]
    
    # ANCHOR FIXING: For each driver k with anchor, fix drv[anchor[k]] == k
    # This destroys factorial symmetry without restricting feasibility
    for driver_idx, anchor_idx in anchor_map.items():
        model.Add(drv[anchor_idx] == driver_idx)
        log_fn(f"  Anchor: drv[{anchor_idx}] == {driver_idx}")
    
    # Add hints for ALL blocks from greedy
    for block_id, driver_idx in greedy_assignments.items():
        if block_id in block_id_to_idx and driver_idx < N:
            b_idx = block_id_to_idx[block_id]
            model.AddHint(drv[b_idx], driver_idx)
    
    log_fn(f"  Set {len(greedy_assignments)} hints")
    
    results["stage1"] = solve_stage(model, time_limit, log_fn, "Stage 1")
    
    if results["stage1"]["status"] != "OK":
        log_fn("STAGE 1 FAILED - check anchor fixing and hints!")
        return results
    
    # =========================================================================
    # STAGE 2: + NoOverlap per driver/day (needs Presence Bools)
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("STAGE 2: + NoOverlap per Driver/Day (with Presence Bools)")
    log_fn("=" * 60)
    
    # Now we need presence bools for NoOverlap intervals
    # Create p[b,k] = (drv[b] == k) only for this stage
    p = {}
    for b_idx in range(B):
        for k in range(N):
            p[b_idx, k] = model.NewBoolVar(f"p_{b_idx}_{k}")
            model.Add(drv[b_idx] == k).OnlyEnforceIf(p[b_idx, k])
            model.Add(drv[b_idx] != k).OnlyEnforceIf(p[b_idx, k].Not())
    
    # NoOverlap per driver per day
    for k in range(N):
        for d in range(7):
            if not blocks_by_day[d]:
                continue
            
            intervals = []
            for b_idx in blocks_by_day[d]:
                info = block_info[b_idx]
                interval = model.NewOptionalFixedSizeIntervalVar(
                    start=info["start"],
                    size=info["span"],
                    is_present=p[b_idx, k],
                    name=f"iv_{b_idx}_{k}"
                )
                intervals.append(interval)
            
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)
    
    results["stage2"] = solve_stage(model, time_limit, log_fn, "Stage 2")
    
    if results["stage2"]["status"] != "OK":
        log_fn("STAGE 2 FAILED - NoOverlap is the problem!")
        return results
    
    # =========================================================================
    # STAGE 3: + max 3 tours per day
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("STAGE 3: + Max 3 Tours per Day")
    log_fn("=" * 60)
    
    tours_day = {}
    for d in range(7):
        for k in range(N):
            tours_day[d, k] = model.NewIntVar(0, 3, f"tours_{d}_{k}")
            if blocks_by_day[d]:
                model.Add(tours_day[d, k] == sum(
                    block_info[b_idx]["tours"] * p[b_idx, k]
                    for b_idx in blocks_by_day[d]
                ))
            else:
                model.Add(tours_day[d, k] == 0)
    
    results["stage3"] = solve_stage(model, time_limit, log_fn, "Stage 3")
    
    if results["stage3"]["status"] != "OK":
        log_fn("STAGE 3 FAILED - tours_day constraint is the problem!")
        return results
    
    # =========================================================================
    # STAGE 4: + 11h day-level rest
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("STAGE 4: + 11h Day-Level Rest")
    log_fn("=" * 60)
    
    # work[d,k] = driver k works on day d
    work = {}
    for d in range(7):
        for k in range(N):
            work[d, k] = model.NewBoolVar(f"work_{d}_{k}")
            if blocks_by_day[d]:
                model.Add(sum(p[b_idx, k] for b_idx in blocks_by_day[d]) >= 1).OnlyEnforceIf(work[d, k])
                model.Add(sum(p[b_idx, k] for b_idx in blocks_by_day[d]) == 0).OnlyEnforceIf(work[d, k].Not())
            else:
                model.Add(work[d, k] == 0)
    
    # first_start[d,k], last_end[d,k]
    first_start = {}
    last_end = {}
    
    for d in range(7):
        for k in range(N):
            first_start[d, k] = model.NewIntVar(0, DAY_MINUTES, f"fs_{d}_{k}")
            last_end[d, k] = model.NewIntVar(0, DAY_MINUTES, f"le_{d}_{k}")
            
            if not blocks_by_day[d]:
                model.Add(first_start[d, k] == DAY_MINUTES)
                model.Add(last_end[d, k] == 0)
                continue
            
            # Sentinel values when not working
            model.Add(first_start[d, k] == DAY_MINUTES).OnlyEnforceIf(work[d, k].Not())
            model.Add(last_end[d, k] == 0).OnlyEnforceIf(work[d, k].Not())
            
            # Bounds when working
            for b_idx in blocks_by_day[d]:
                model.Add(first_start[d, k] <= block_info[b_idx]["start"]).OnlyEnforceIf(p[b_idx, k])
                model.Add(last_end[d, k] >= block_info[b_idx]["end"]).OnlyEnforceIf(p[b_idx, k])
    
    # Rest constraint: 11h between consecutive days
    BIG_M = 2880
    MIN_REST = 660  # 11h
    
    for d in range(6):
        for k in range(N):
            both = model.NewBoolVar(f"both_{d}_{k}")
            model.AddBoolAnd([work[d, k], work[d + 1, k]]).OnlyEnforceIf(both)
            model.AddBoolOr([work[d, k].Not(), work[d + 1, k].Not()]).OnlyEnforceIf(both.Not())
            
            model.Add(
                first_start[d + 1, k] + DAY_MINUTES - last_end[d, k] >= MIN_REST - BIG_M * (1 - both)
            )
    
    results["stage4"] = solve_stage(model, time_limit, log_fn, "Stage 4")
    
    if results["stage4"]["status"] != "OK":
        log_fn("STAGE 4 FAILED - 11h rest constraint is the problem!")
        return results
    
    # =========================================================================
    # STAGE 5: + heavy → 14h + next-day ≤2
    # =========================================================================
    log_fn("\n" + "=" * 60)
    log_fn("STAGE 5: + Heavy Day → 14h Rest + Next-Day ≤2 Tours")
    log_fn("=" * 60)
    
    heavy = {}
    for d in range(7):
        for k in range(N):
            heavy[d, k] = model.NewBoolVar(f"heavy_{d}_{k}")
            model.Add(tours_day[d, k] >= 3 * heavy[d, k])
            model.Add(tours_day[d, k] <= 2 + heavy[d, k])
    
    for d in range(6):
        for k in range(N):
            model.Add(tours_day[d + 1, k] <= 3 - heavy[d, k])
    
    EXTRA_REST = 180
    for d in range(6):
        for k in range(N):
            both = model.NewBoolVar(f"bothH_{d}_{k}")
            model.AddBoolAnd([work[d, k], work[d + 1, k]]).OnlyEnforceIf(both)
            model.AddBoolOr([work[d, k].Not(), work[d + 1, k].Not()]).OnlyEnforceIf(both.Not())
            
            model.Add(
                first_start[d + 1, k] + DAY_MINUTES - last_end[d, k] >= 
                MIN_REST + EXTRA_REST * heavy[d, k] - BIG_M * (1 - both)
            )
    
    results["stage5"] = solve_stage(model, time_limit, log_fn, "Stage 5")
    
    if results["stage5"]["status"] != "OK":
        log_fn("STAGE 5 FAILED - Heavy/14h constraint is the problem!")
        return results
    
    # =========================================================================
    # ALL STAGES PASSED
    # =========================================================================
    log_fn("\n" + "=" * 70)
    log_fn("ALL 5 STAGES PASSED!")
    log_fn("=" * 70)
    
    return results


def solve_stage(model, time_limit, log_fn, stage_name):
    """Solve a stage with stop_after_first_solution."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.stop_after_first_solution = True  # CRITICAL!
    solver.parameters.num_search_workers = 1  # S0.1: Determinism
    solver.parameters.random_seed = 42
    
    start = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - start
    
    status_name = solver.StatusName(status)
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log_fn(f"✓ {stage_name}: FEASIBLE in {solve_time:.1f}s")
        return {"status": "OK", "time": solve_time, "cp_status": status_name}
    else:
        log_fn(f"✗ {stage_name}: {status_name} after {solve_time:.1f}s")
        return {"status": "FAILED", "time": solve_time, "cp_status": status_name}


# =============================================================================
# HELPERS
# =============================================================================

def get_day_idx(block) -> int:
    if hasattr(block, 'day_idx'):
        return block.day_idx
    if hasattr(block, 'day'):
        day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
        if hasattr(block.day, 'value'):
            return day_map.get(block.day.value, 0)
        return day_map.get(str(block.day), 0)
    return 0

def get_start_min(block) -> int:
    if hasattr(block, 'start_min'):
        return block.start_min
    if hasattr(block, 'first_start'):
        t = block.first_start
        if hasattr(t, 'hour'):
            return t.hour * 60 + t.minute
    return 0

def get_end_min(block) -> int:
    if hasattr(block, 'end_min'):
        return block.end_min
    if hasattr(block, 'last_end'):
        t = block.last_end
        if hasattr(t, 'hour'):
            return t.hour * 60 + t.minute
    return 0

def get_work_min(block) -> int:
    if hasattr(block, 'work_min'):
        return block.work_min
    if hasattr(block, 'total_work_hours'):
        return int(block.total_work_hours * 60)
    return 0

def get_block_id(block) -> str:
    if hasattr(block, 'block_id'):
        return block.block_id
    if hasattr(block, 'id'):
        return block.id
    return str(id(block))
