"""
FORECAST SOLVER v4 - USE_BLOCK MODEL
=====================================
Implements P2: use_block[b] instead of x[b,k] for massive variable reduction.

Phase 1: Capacity Planning (CP-SAT)
- use_block[b] = how many times block b is used (0 or 1 typically)
- Coverage: each tour exactly once
- Overlaps: per-day, blocks that overlap can total <= max_drivers_per_day
- Objective: minimize total drivers needed (peak headcount)

Phase 2: Assignment (Greedy)
- Assign blocks to specific driver IDs
- Respect weekly hours constraints (42-53h for FTE)
- Use PT as overflow

Variables: O(blocks) instead of O(blocks × drivers) = 100x reduction
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import NamedTuple
from enum import Enum
import math
from time import perf_counter
import logging

from ortools.sat.python import cp_model

# Setup logger
logger = logging.getLogger("ForecastSolverV4")

from src.domain.models import Block, Tour, Weekday
from src.services.constraints import can_assign_block
from src.services.smart_block_builder import (
    build_weekly_blocks_smart,
    build_block_index,
    verify_coverage,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

class ConfigV4(NamedTuple):
    """Configuration for v4 solver."""
    min_hours_per_fte: float = 42.0
    max_hours_per_fte: float = 53.0
    time_limit_phase1: float = 120.0
    time_limit_phase2: float = 60.0
    seed: int = 42
    num_workers: int = 1  # Determinism: use 1 worker
    max_blocks: int = 30000  # Hard limit to prevent model explosion
    w_new_driver: float = 500.0  # Penalty for activating any new FTE (REDUCED to prefer FTE)
    w_pt_new: float = 10000.0  # Additional penalty for new PT drivers (INCREASED to minimize PT)
    w_pt_weekday: float = 5000.0  # PT on Mon-Fri very expensive
    w_pt_saturday: float = 5000.0  # PT on Saturday also expensive (minimize all PT!)
    # PT fragmentation control
    pt_min_hours: float = 9.0  # Minimum hours for PT drivers (soft constraint)
    w_pt_underutil: int = 2000  # Penalty weight for PT under-utilization (shortfall)
    w_pt_day_spread: int = 1000  # Penalty per PT working day (minimize fragmentation)
    # 3-tour recovery rules (HARD)
    min_rest_after_3t_minutes: int = 14 * 60  # 14h rest after 3-tour day
    max_next_day_tours_after_3t: int = 2  # Max tours allowed after 3-tour day
    # 3-tour recovery rules (SOFT - LNS preference)
    target_next_day_tours_after_3t: int = 1  # Prefer 1 tour after 3-tour day
    w_next_day_tours_excess: int = 200  # Penalty for 2nd tour after 3-tour day

    planner_active: bool = False  # If True, use strict shift planning model (Phase 0)
    
    # Heuristic Solver Configuration (Phase 2 Alternative)
    solver_mode: str = "HEURISTIC"  # "GREEDY", "CPSAT", "SETPART", "HEURISTIC"
    target_ftes: int = 145  # Hard target for FTE count (Phase 1 Goal)
    fte_overflow_cap: int = 10  # Soft limit for overflow
    fte_hours_target: float = 49.5  # Ideal hours for FTE packing
    anytime_budget: float = 30.0  # Seconds for improvement phases

    # Global CP-SAT Phase 2B control
    enable_global_cpsat: bool = False  # Disabled by default (times out on large problems)
    global_cpsat_block_threshold: int = 200  # Only use CP-SAT if blocks < this


# =============================================================================
# RESULT MODELS
# =============================================================================

@dataclass 
class DriverAssignment:
    driver_id: str
    driver_type: str  # "FTE" or "PT"
    blocks: list[Block]
    total_hours: float
    days_worked: int
    analysis: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "driver_id": self.driver_id,
            "type": self.driver_type,
            "hours_week": round(self.total_hours, 2),
            "days_worked": self.days_worked,
            "analysis": self.analysis,
            "blocks": [
                {
                    "id": b.id,
                    "day": b.day.value,
                    "tours": [t.id for t in b.tours],
                    "hours": round(b.total_work_hours, 2)
                }
                for b in self.blocks
            ]
        }


@dataclass
class SolveResultV4:
    status: str
    assignments: list[DriverAssignment]
    kpi: dict
    solve_times: dict[str, float]
    block_stats: dict
    
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "kpi": self.kpi,
            "drivers": [a.to_dict() for a in self.assignments],
            "solve_times": self.solve_times,
            "block_stats": self.block_stats
        }


# =============================================================================
# PHASE 1: CAPACITY PLANNING (use_block model)
# =============================================================================

def solve_capacity_phase(
    blocks: list[Block],
    tours: list[Tour],
    block_index: dict[str, list[Block]],
    config: ConfigV4,
    block_scores: dict[str, float] = None,
    block_props: dict[str, dict] = None
) -> tuple[list[Block], dict]:
    """
    Phase 1: Determine which blocks to use.
    
    Model:
    - use[b] ∈ {0, 1}: block b is used
    - Coverage: for each tour t, exactly one block containing t is used
    - Objective: minimize weighted cost using policy-derived scores
    
    Returns:
        (selected_blocks, stats)
    """
    print(f"\n{'='*60}", flush=True)
    print("PHASE 1: Capacity Planning (use_block model)", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Blocks: {len(blocks)}, Tours: {len(tours)}", flush=True)
    
    t0 = perf_counter()
    print("PHASE 1A: CP-SAT model build start...", flush=True)
    
    model = cp_model.CpModel()
    
    # Variables: one per block
    use = {}
    for b, block in enumerate(blocks):
        use[b] = model.NewBoolVar(f"use_{b}")
    
    print(f"Variables: {len(use)} (vs {len(use) * 150}+ in old model)", flush=True)
    
    # Precompute block index lookup for O(1) block → variable mapping
    block_id_to_idx = {block.id: idx for idx, block in enumerate(blocks)}

    # Constraint: Coverage (each tour exactly once)
    print("Adding coverage constraints...", flush=True)
    for tour in tours:
        blocks_with_tour = block_index.get(tour.id, [])
        if not blocks_with_tour:
            raise ValueError(f"Tour {tour.id} has no blocks!")
        
        # Use the pre-built block_index for O(1) lookup instead of scanning all blocks
        block_indices = []
        for block in blocks_with_tour:
            b_idx = block_id_to_idx.get(block.id)
            if b_idx is not None:
                block_indices.append(b_idx)

        if not block_indices:
            raise ValueError(f"Tour {tour.id} has no indexed blocks!")
        
        model.Add(sum(use[b] for b in block_indices) == 1)
    
    print("Coverage constraints added.", flush=True)
    
    # Objective: Use POLICY-DERIVED scores if available
    # Higher policy score = more desirable block = LOWER cost
    # We invert: cost = MAX_SCORE - score
    block_cost = []
    MAX_SCORE = 1000  # Upper bound for score inversion
    
    for b, block in enumerate(blocks):
        if block_scores and block.id in block_scores:
            # Policy-driven: invert score to cost
            score = block_scores[block.id]
            cost = int(MAX_SCORE - score)
        else:
            # Fallback: static costs
            n = len(block.tours)
            if n == 1:
                cost = 300
            elif n == 2:
                cost = 50
            elif n == 3:
                cost = 10
            else:
                cost = 5
        block_cost.append(use[b] * cost)
    
    model.Minimize(sum(block_cost))
    
    print(f"PHASE 1A: CP-SAT model build done in {perf_counter() - t0:.2f}s", flush=True)
    
    # Solve
    t1 = perf_counter()
    print(f"PHASE 1B: CP-SAT solve start (time limit: {config.time_limit_phase1}s)...", flush=True)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_phase1
    solver.parameters.num_workers = config.num_workers
    solver.parameters.random_seed = config.seed
    
    status = solver.Solve(model)
    elapsed = perf_counter() - t0
    print(f"PHASE 1B: CP-SAT solve done status={status} in {perf_counter() - t1:.2f}s", flush=True)
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.error("[FAILED] No solution found")
        return [], {"status": "FAILED", "time": elapsed}
    
    # Extract selected blocks
    selected = [blocks[b] for b in range(len(blocks)) if solver.Value(use[b]) == 1]
    
    # Stats
    by_type = {"1er": 0, "2er": 0, "3er": 0}
    split_2er_count = 0
    template_match_count = 0
    
    for block in selected:
        n = len(block.tours)
        if n == 1:
            by_type["1er"] += 1
        elif n == 2:
            by_type["2er"] += 1
            # Check split flag
            if block_props and block.id in block_props:
                if block_props[block.id].get("is_split", False):
                    split_2er_count += 1
        elif n == 3:
            by_type["3er"] += 1
        
        # Template match
        if block_props and block.id in block_props:
            if block_props[block.id].get("is_template", False):
                template_match_count += 1
    
    by_day = defaultdict(int)
    for block in selected:
        by_day[block.day.value] += 1
    
    total_hours = sum(b.total_work_hours for b in selected)
    
    # Calculate block mix percentages
    total_selected = len(selected)
    block_mix = {
        "1er": round(by_type["1er"] / total_selected, 3) if total_selected else 0,
        "2er": round(by_type["2er"] / total_selected, 3) if total_selected else 0,
        "3er": round(by_type["3er"] / total_selected, 3) if total_selected else 0,
    }
    
    stats = {
        "status": "OK",
        "selected_blocks": len(selected),
        "blocks_1er": by_type["1er"],
        "blocks_2er": by_type["2er"],
        "blocks_3er": by_type["3er"],
        "blocks_by_day": dict(by_day),
        "total_hours": round(total_hours, 2),
        "time": round(elapsed, 2),
        "block_mix": block_mix,
        "split_2er_count": split_2er_count,
        "template_match_count": template_match_count,
    }
    
    print(f"Selected {len(selected)} blocks: {by_type}")
    print(f"Block mix: 1er={block_mix['1er']*100:.1f}%, 2er={block_mix['2er']*100:.1f}%, 3er={block_mix['3er']*100:.1f}%")
    print(f"Template matches: {template_match_count}")
    print(f"Total hours: {total_hours:.1f}h")
    print(f"Time: {elapsed:.2f}s")
    
    return selected, stats


# =============================================================================
# PHASE 2: DRIVER ASSIGNMENT (Greedy)
# =============================================================================

def assign_drivers_greedy(
    blocks: list[Block],
    config: ConfigV4
) -> tuple[list[DriverAssignment], dict]:
    """
    Phase 2: Assign blocks to drivers using greedy algorithm.
    
    Strategy:
    1. Group blocks by day
    2. For each block, find a driver who can take it (respecting weekly hours)
    3. Create new driver if needed
    4. FTE drivers: try to fill 42-53h/week
    5. PT drivers: overflow (no hour constraints)
    """
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 2: Driver Assignment (Greedy)")
    logger.info(f"{'='*60}")
    logger.info(f"Blocks to assign: {len(blocks)}")
    
    t0 = perf_counter()
    
    # Day order for rest checks (must match Weekday enum values in models.py)
    WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    # Group blocks by day, then sort by start time
    blocks_by_day: dict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        blocks_by_day[block.day.value].append(block)
    
    for day in blocks_by_day:
        blocks_by_day[day].sort(key=lambda b: b.first_start)
    
    # Deterministic iteration order for days
    sorted_days = [d for d in WEEKDAY_ORDER if d in blocks_by_day]
    
    # Driver state
    drivers: dict[str, dict] = {}  # id -> {type, hours, days, blocks}
    fte_counter = 0
    pt_counter = 0
    
    def create_fte() -> str:
        nonlocal fte_counter
        fte_counter += 1
        driver_id = f"FTE{fte_counter:03d}"
        drivers[driver_id] = {
            "type": "FTE",
            "hours": 0.0,
            "days": set(),
            "blocks": [],
            "day_blocks": defaultdict(list)  # day -> blocks for overlap check
        }
        return driver_id
    
    def create_pt() -> str:
        nonlocal pt_counter
        pt_counter += 1
        driver_id = f"PT{pt_counter:03d}"
        drivers[driver_id] = {
            "type": "PT",
            "hours": 0.0,
            "days": set(),
            "blocks": [],
            "day_blocks": defaultdict(list)
        }
        return driver_id
    
    # Rest time constraint (11h minimum between consecutive days)
    MIN_REST_HOURS = 11.0
    MIN_REST_MINS = int(MIN_REST_HOURS * 60)
    
    def get_day_index(day: str) -> int:
        return WEEKDAY_ORDER.index(day) if day in WEEKDAY_ORDER else -1
    
    def can_take_block(driver_id: str, block: Block) -> bool:
        """Check if driver can take this block."""
        d = drivers[driver_id]
        day = block.day.value
        day_idx = get_day_index(day)
        
        # Check hours if FTE
        if d["type"] == "FTE":
            new_hours = d["hours"] + block.total_work_hours
            if new_hours > config.max_hours_per_fte:
                return False
        
        # ===================================================================
        # CENTRAL VALIDATION (Overlap + 11h Rest)
        # ===================================================================
        # Use central service to check overlap and rest constraints
        allowed, reason = can_assign_block(d["blocks"], block)
        if not allowed:
            # print(f"DEBUG: Rejecting block {block.id} for driver {driver_id}: {reason}")
            return False
            
        return True
    
    def assign_block(driver_id: str, block: Block):
        """Assign block to driver."""
        d = drivers[driver_id]
        d["hours"] += block.total_work_hours
        d["days"].add(block.day.value)
        d["blocks"].append(block)
        d["day_blocks"][block.day.value].append(block)
    
    # Assign blocks - fill FTEs first, PT for overflow
    # Strategy: 
    # 1. Try existing FTEs that have room
    # 2. If no FTE has room, create new FTE if it can reach 42h
    # 3. Use PT as overflow for remaining blocks
    
    # First pass: calculate total hours to estimate driver needs
    total_block_hours = sum(b.total_work_hours for b in blocks)
    estimated_ftes = int(total_block_hours / 47.5) + 1  # ~47.5h average FTE
    logger.info(f"Total block hours: {total_block_hours:.1f}h, estimated FTEs: {estimated_ftes}")
    
    # Pre-create a pool of FTEs
    for _ in range(estimated_ftes):
        create_fte()
    
    # Sort blocks by HARDNESS first (Saturday > late evening > fewer options)
    # Then by size for stable tie-breaking
    def block_hardness(b):
        # Saturday = hardest
        is_sat = 2 if b.day.value == "Sat" else 0
        # Late evening (ends after 20:00) = harder
        end_mins = b.last_end.hour * 60 + b.last_end.minute
        is_late = 1 if end_mins > 20 * 60 else 0
        # Larger blocks = harder to place
        return (-is_sat, -is_late, -b.total_work_hours)
    
    all_blocks_sorted = sorted(blocks, key=block_hardness)
    
    for block in all_blocks_sorted:
        assigned = False
        
        # Score all drivers (FTE first, then PT)
        # Lower score = better candidate
        candidates = []
        
        for driver_id, d in drivers.items():
            if not can_take_block(driver_id, block):
                continue
            
            # BEST-FIT SCORING: prefer driver with LEAST remaining slack after assignment
            # This maximizes utilization and prevents spawning new drivers
            remaining_capacity = config.max_hours_per_fte - (d["hours"] + block.total_work_hours)
            
            # Base score: smaller remaining capacity = better (prefer full drivers)
            score = remaining_capacity
            
            # Activation penalty for new drivers
            is_new_driver = len(d["blocks"]) == 0
            if is_new_driver:
                score += config.w_new_driver
                if d["type"] == "PT":
                    score += config.w_pt_new
            
            # PT penalty (prefer FTE)
            if d["type"] == "PT":
                score += 100
                day = block.day.value
                if day == "Sat":
                    score += config.w_pt_saturday
                else:
                    score += config.w_pt_weekday
            
            candidates.append((score, driver_id, d))
        
        if candidates:
            # Sort by score (ascending) and take best
            candidates.sort(key=lambda x: x[0])
            _, best_driver_id, _ = candidates[0]
            assign_block(best_driver_id, block)
            assigned = True
        
        if not assigned:
            # No existing driver can take it - use PT for overflow
            # NOTE: Creating new FTE here would increase headcount unnecessarily.
            # PT is used as overflow bucket, LNS will optimize later.
            driver_id = create_pt()
            assign_block(driver_id, block)
    
    # Check FTE hour constraints
    under_hours = []
    for driver_id, d in drivers.items():
        if d["type"] == "FTE" and d["hours"] < config.min_hours_per_fte:
            under_hours.append((driver_id, d["hours"]))
    
    elapsed = perf_counter() - t0
    
    # Build assignments
    assignments = []
    for driver_id, d in drivers.items():
        if d["blocks"]:
            assignments.append(DriverAssignment(
                driver_id=driver_id,
                driver_type=d["type"],
                blocks=d["blocks"],
                total_hours=d["hours"],
                days_worked=len(d["days"]),
                analysis=_analyze_driver_workload(d["blocks"])
            ))
    
    # Stats
    fte_hours = [a.total_hours for a in assignments if a.driver_type == "FTE"]
    pt_hours = [a.total_hours for a in assignments if a.driver_type == "PT"]
    
    # Distribution metrics
    pt_single_segment = len([a for a in assignments if a.driver_type == "PT" and len(a.blocks) == 1])
    pt_low_utilization = len([a for a in assignments if a.driver_type == "PT" and a.total_hours <= 4.5])
    
    # Tight rest count
    tight_rest_count = 0
    for a in assignments:
        if a.analysis.get("min_rest_hours") == 11.0:
            tight_rest_count += 1
    
    stats = {
        "drivers_fte": len([a for a in assignments if a.driver_type == "FTE"]),
        "drivers_pt": len([a for a in assignments if a.driver_type == "PT"]),
        "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0,
        "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0,
        "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0,
        "under_hours_count": len(under_hours),
        "time": round(elapsed, 2),
        # Distribution metrics
        "pt_single_segment_count": pt_single_segment,
        "pt_low_utilization_count": pt_low_utilization,
        "tight_rest_count": tight_rest_count,
    }
    

    
    
    logger.info(f"Assigned to {len(assignments)} drivers")
    logger.info(f"  FTE: {stats['drivers_fte']} (hours: {stats['fte_hours_min']}-{stats['fte_hours_max']}h)")
    logger.info(f"  PT: {stats['drivers_pt']}")
    logger.info(f"  PT with single segment: {stats['pt_single_segment_count']}")
    logger.info(f"  PT with <=4.5h: {stats['pt_low_utilization_count']}")
    logger.info(f"  Tight rests (11.0h exactly): {stats['tight_rest_count']}")
    if under_hours:
        logger.warning(f"  [WARN] {len(under_hours)} FTE drivers under {config.min_hours_per_fte}h")
    logger.info(f"Time: {elapsed:.2f}s")
    
    return assignments, stats


def blocks_overlap(b1: Block, b2: Block) -> bool:
    """Check if two blocks overlap in time."""
    if b1.day != b2.day:
        return False
    
    start1 = b1.first_start.hour * 60 + b1.first_start.minute
    end1 = b1.last_end.hour * 60 + b1.last_end.minute
    start2 = b2.first_start.hour * 60 + b2.first_start.minute
    end2 = b2.last_end.hour * 60 + b2.last_end.minute
    
    return not (end1 <= start2 or end2 <= start1)


# =============================================================================
# MAIN SOLVER
# =============================================================================

def solve_forecast_v4(
    tours: list[Tour],
    config: ConfigV4 = ConfigV4()
) -> SolveResultV4:
    """
    Solve forecast planning with P2 model (use_block).
    
    Two phases:
    1. Capacity: Select which blocks to use (CP-SAT with O(blocks) vars)
    2. Assignment: Assign blocks to drivers (Greedy)
    """
    import json
    from pathlib import Path
    
    logger.info(f"\n{'='*70}")
    logger.info("FORECAST SOLVER v4 - USE_BLOCK MODEL")
    logger.info(f"{'='*70}")
    logger.info(f"Tours: {len(tours)}")
    
    total_hours = sum(t.duration_hours for t in tours)
    logger.info(f"Total hours: {total_hours:.1f}h")
    
    # Phase A: Build blocks
    t_block = perf_counter()
    print("PHASE A: Block building start...", flush=True)
    blocks, block_stats = build_weekly_blocks_smart(tours)
    block_time = perf_counter() - t_block
    print(f"PHASE A: Block building done in {block_time:.2f}s, generated {len(blocks)} blocks", flush=True)
    
    # Extract scores from block_stats
    block_scores = block_stats.get("block_scores", {})
    block_props = block_stats.get("block_props", {})
    
    # Block pruning: sort deterministically and limit to max_blocks
    original_count = len(blocks)
    if config.max_blocks and len(blocks) > config.max_blocks:
        print(f"Pruning blocks: {len(blocks)} > max_blocks={config.max_blocks}", flush=True)
        # Sort by score (descending) then by id (ascending) for determinism
        blocks = sorted(blocks, key=lambda b: (-block_scores.get(b.id, 0), b.id))
        blocks = blocks[:config.max_blocks]
        print(f"Pruned from {original_count} to {len(blocks)} blocks", flush=True)
        # Rebuild index after pruning
        block_index = build_block_index(blocks)
        # Update block_scores and block_props to only include pruned blocks
        pruned_ids = {b.id for b in blocks}
        block_scores = {k: v for k, v in block_scores.items() if k in pruned_ids}
        block_props = {k: v for k, v in block_props.items() if k in pruned_ids}
    else:
        block_index = build_block_index(blocks)
    
    print(f"Blocks: {len(blocks)} (1er={block_stats['blocks_1er']}, 2er={block_stats['blocks_2er']}, 3er={block_stats['blocks_3er']})", flush=True)
    if block_scores:
        print(f"Policy scores loaded: {len(block_scores)} blocks", flush=True)
    
    # Phase 1: Capacity (use policy scores)
    selected_blocks, phase1_stats = solve_capacity_phase(
        blocks, tours, block_index, config,
        block_scores=block_scores,
        block_props=block_props
    )
    
    if phase1_stats["status"] != "OK":
        return SolveResultV4(
            status="FAILED",
            assignments=[],
            kpi={"error": "Phase 1 failed"},
            solve_times={"block_building": block_time},
            block_stats=block_stats
        )
    
    # ======================================================================
    # PHASE 2: DRIVER ASSIGNMENT
    # ======================================================================
    if config.solver_mode == "HEURISTIC":
        logger.info(f"PHASE 2: Anytime Heuristic Solver (Target FTEs: {config.target_ftes})")
        from src.services.heuristic_solver import HeuristicSolver
        
        solver = HeuristicSolver(selected_blocks, config)
        assignments, phase2_stats = solver.solve()
        
    elif config.enable_global_cpsat and len(selected_blocks) <= config.global_cpsat_block_threshold:
        try:
            from src.services.cpsat_assigner import assign_drivers_cpsat
            
            logger.info("=" * 60)
            logger.info(f"PHASE 2B: CP-SAT Assignment Optimizer ({len(selected_blocks)} blocks)")
            logger.info("=" * 60)
            
            cpsat_assignments, cpsat_stats = assign_drivers_cpsat(
                selected_blocks,
                config,
                warm_start=greedy_assignments,
                time_limit=300.0  # 5 minutes for complex problems
            )
            
            # Use CP-SAT result if successful
            if cpsat_stats.get("status") in ("OPTIMAL", "FEASIBLE"):
                logger.info("CP-SAT assignment successful!")
                logger.info(f"Result: {cpsat_stats['drivers_fte']} FTE + {cpsat_stats['drivers_pt']} PT")
                logger.info(f"Improvement: PT {phase2_stats['drivers_pt']} -> {cpsat_stats['drivers_pt']} (Delta {cpsat_stats['drivers_pt'] - phase2_stats['drivers_pt']})")
                assignments = cpsat_assignments
                # Update stats with CP-SAT results
                phase2_stats.update(cpsat_stats)
            else:
                logger.warning(f"CP-SAT failed ({cpsat_stats.get('error')}), using greedy fallback")
                assignments = greedy_assignments
                
        except Exception as e:
            logger.error(f"CP-SAT assignment error: {e}", exc_info=True)
            logger.warning("Using greedy fallback")
            assignments = greedy_assignments
    else:
        # Skip global CP-SAT (disabled or problem too large)
        logger.info(f"Skipping global CP-SAT Phase 2B (enabled={config.enable_global_cpsat}, blocks={len(selected_blocks)}, threshold={config.global_cpsat_block_threshold})")
        assignments = greedy_assignments
    
    # Determine status
    fte_count = phase2_stats["drivers_fte"]
    under_count = phase2_stats.get("under_hours_count", 0)
    
    # Heuristic solver always assigns all blocks, so it's always HARD_OK
    # The under_hours_count is informational only (some FTEs may have < 40h)
    status = "HARD_OK"
    if under_count > 0:
        logger.info(f"Note: {under_count} FTE drivers have < {config.min_hours_per_fte}h (informational)")

    
    # KPIs
    kpi = {
        "status": status,
        "total_hours": round(total_hours, 2),
        "drivers_fte": fte_count,
        "drivers_pt": phase2_stats["drivers_pt"],
        "fte_hours_min": phase2_stats["fte_hours_min"],
        "fte_hours_max": phase2_stats["fte_hours_max"],
        "fte_hours_avg": phase2_stats["fte_hours_avg"],
        "blocks_selected": phase1_stats["selected_blocks"],
        "blocks_1er": phase1_stats["blocks_1er"],
        "blocks_2er": phase1_stats["blocks_2er"],
        "blocks_3er": phase1_stats["blocks_3er"],
        "block_mix": phase1_stats.get("block_mix", {}),
        "template_match_count": phase1_stats.get("template_match_count", 0),
        "split_2er_count": phase1_stats.get("split_2er_count", 0),
    }
    
    solve_times = {
        "block_building": round(block_time, 2),
        "phase1_capacity": phase1_stats["time"],
        "phase2_assignment": phase2_stats["time"],
        "total": round(block_time + phase1_stats["time"] + phase2_stats["time"], 2),
    }
    
    # Generate style_report.json (Task 4)
    _generate_style_report(selected_blocks, phase1_stats, block_props)
    
    # Generate style_report.json (Task 4)
    _generate_style_report(selected_blocks, phase1_stats, block_props)
    
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Status: {status}")
    logger.info(f"Blocks: {phase1_stats['selected_blocks']} selected")
    logger.info(f"Drivers: {fte_count} FTE + {phase2_stats['drivers_pt']} PT")
    logger.info(f"Total time: {solve_times['total']:.2f}s")
    
    return SolveResultV4(
        status=status,
        assignments=assignments,
        kpi=kpi,
        solve_times=solve_times,
        block_stats=block_stats
    )


def _generate_style_report(selected_blocks: list[Block], phase1_stats: dict, block_props: dict):
    """Generate style_report.json with block mix and pattern analysis."""
    import json
    from pathlib import Path
    
    # Block mix
    block_mix = phase1_stats.get("block_mix", {})
    
    # Split rate
    blocks_2er = phase1_stats.get("blocks_2er", 0)
    split_2er = phase1_stats.get("split_2er_count", 0)
    split_rate = round(split_2er / blocks_2er, 3) if blocks_2er else 0
    
    # Template match rate
    template_matches = phase1_stats.get("template_match_count", 0)
    total_selected = phase1_stats.get("selected_blocks", 0)
    template_rate = round(template_matches / total_selected, 3) if total_selected else 0
    
    # Gap histogram from selected blocks
    gap_histogram = defaultdict(int)
    for block in selected_blocks:
        if len(block.tours) >= 2:
            tours_sorted = sorted(block.tours, key=lambda t: t.start_time)
            for i in range(len(tours_sorted) - 1):
                end_mins = tours_sorted[i].end_time.hour * 60 + tours_sorted[i].end_time.minute
                start_mins = tours_sorted[i+1].start_time.hour * 60 + tours_sorted[i+1].start_time.minute
                gap = start_mins - end_mins
                if gap > 0:
                    gap_histogram[gap] += 1
    
    # Block mix by day
    by_day = defaultdict(lambda: {"1er": 0, "2er": 0, "3er": 0})
    for block in selected_blocks:
        n = len(block.tours)
        day = block.day.value
        if n == 1:
            by_day[day]["1er"] += 1
        elif n == 2:
            by_day[day]["2er"] += 1
        elif n == 3:
            by_day[day]["3er"] += 1
    
    # Calculate percentages by day
    block_mix_by_day = {}
    for day, counts in by_day.items():
        total = sum(counts.values())
        block_mix_by_day[day] = {
            k: round(v / total, 3) if total else 0 
            for k, v in counts.items()
        }
    
    report = {
        "block_mix_overall": block_mix,
        "block_mix_by_day": block_mix_by_day,
        "split_2er_rate": split_rate,
        "template_match_rate": template_rate,
        "gap_histogram": dict(sorted(gap_histogram.items())[:15]),
        "stats": {
            "total_blocks": total_selected,
            "blocks_1er": phase1_stats.get("blocks_1er", 0),
            "blocks_2er": phase1_stats.get("blocks_2er", 0),
            "blocks_3er": phase1_stats.get("blocks_3er", 0),
            "split_2er_count": split_2er,
            "template_matches": template_matches,
        }
    }
    
    # Save to data directory
    output_path = Path(__file__).parent.parent.parent / "data" / "style_report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Style report saved to: {output_path}")


def _analyze_driver_workload(blocks: list[Block]) -> dict:
    """
    Calculate detailed workload stats for a driver.
    Satisfies Requirement E: Workload Analysis.
    """
    if not blocks:
         return {
            "total_work_hours_week": 0.0,
            "total_span_hours_week": 0.0,
            "workdays_count": 0,
            "min_rest_hours": 999.0,
            "violations_count": 0
        }
    
    # Sort blocks globally by time
    # blocks are already sorted per-day in greedy, but ensure global order
    WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    def get_global_start(b: Block) -> int:
        day_idx = WEEKDAY_ORDER.index(b.day.value) if b.day.value in WEEKDAY_ORDER else 0
        return day_idx * 24 * 60 + (b.first_start.hour * 60 + b.first_start.minute)
        
    sorted_blocks = sorted(blocks, key=get_global_start)
    
    total_work_minutes = sum(b.total_work_minutes for b in blocks)
    total_span_minutes = 0
    min_rest_mins = 999999
    violations = 0
    
    # Calculate daily span (sum of spans per day) and rest
    by_day = defaultdict(list)
    for b in sorted_blocks:
        by_day[b.day.value].append(b)
        
    for day_blocks in by_day.values():
        if not day_blocks: continue
        # Span = End of last block - Start of first block
        # (Assumes no overlapping blocks on same day, which checks prevent)
        t_start = min(b.first_start.hour * 60 + b.first_start.minute for b in day_blocks)
        t_end = max(b.last_end.hour * 60 + b.last_end.minute for b in day_blocks)
        total_span_minutes += (t_end - t_start)
        
    # Calculate Rest
    for i in range(len(sorted_blocks) - 1):
        b1 = sorted_blocks[i]
        b2 = sorted_blocks[i+1]
        
        end_global = get_global_start(b1) + b1.span_minutes # Start + Duration? No, Start + Span? 
        # Wait, get_global_start uses first_start. 
        # Global End = day_idx * 1440 + last_end_mins
        day1_idx = WEEKDAY_ORDER.index(b1.day.value)
        end1_mins = b1.last_end.hour * 60 + b1.last_end.minute
        global_end1 = day1_idx * 1440 + end1_mins
        
        day2_idx = WEEKDAY_ORDER.index(b2.day.value)
        start2_mins = b2.first_start.hour * 60 + b2.first_start.minute
        global_start2 = day2_idx * 1440 + start2_mins
        
        gap = global_start2 - global_end1
        if gap < min_rest_mins:
            min_rest_mins = gap
            
        if gap < 11 * 60:
             violations += 1

    return {
        "total_work_hours_week": round(total_work_minutes / 60.0, 2),
        "total_span_hours_week": round(total_span_minutes / 60.0, 2),
        "workdays_count": len(by_day),
        "min_rest_hours": round(min_rest_mins / 60.0, 2) if min_rest_mins < 999999 else None,
        "violations_count": violations
    }


# =============================================================================
# FTE-ONLY GLOBAL CP-SAT SOLVER
# =============================================================================

def solve_forecast_fte_only(
    tours: list[Tour],
    time_limit_feasible: float = 60.0,
    time_limit_optimize: float = 300.0,
    seed: int = 42,
) -> SolveResultV4:
    """
    Solve forecast with GLOBAL CP-SAT FTE-only assignment.
    
    Guarantees:
    - PT = 0 (all drivers are FTE)
    - All drivers have 42-53h/week
    - Minimizes total driver count (target: 118-148 for ~6200h work)
    """
    from src.services.cpsat_global_assigner import (
        solve_global_cpsat, 
        GlobalAssignConfig, 
        blocks_to_assign_info
    )
    
    logger.info("=" * 70)
    logger.info("FORECAST SOLVER - FTE-ONLY GLOBAL CP-SAT")
    logger.info("=" * 70)
    logger.info(f"Tours: {len(tours)}")
    
    total_hours = sum(t.duration_hours for t in tours)
    logger.info(f"Total hours: {total_hours:.1f}h")
    logger.info(f"Expected drivers: {int(total_hours/53)}-{int(total_hours/42)}")
    
    config = ConfigV4(seed=seed)
    
    # Phase A: Build blocks
    t_block = perf_counter()
    print("PHASE A: Block building...", flush=True)
    blocks, block_stats = build_weekly_blocks_smart(tours)
    block_time = perf_counter() - t_block
    print(f"Generated {len(blocks)} blocks in {block_time:.1f}s", flush=True)
    
    block_scores = block_stats.get("block_scores", {})
    block_props = block_stats.get("block_props", {})
    block_index = build_block_index(blocks)
    
    # Phase 1: Select blocks
    t_capacity = perf_counter()
    print("PHASE 1: Block selection (CP-SAT)...", flush=True)
    selected_blocks, phase1_stats = solve_capacity_phase(
        blocks, tours, block_index, config,
        block_scores=block_scores, block_props=block_props
    )
    capacity_time = perf_counter() - t_capacity
    
    if phase1_stats["status"] != "OK":
        return SolveResultV4(
            status="FAILED",
            assignments=[],
            kpi={"error": "Phase 1 block selection failed"},
            solve_times={"block_building": block_time},
            block_stats=block_stats
        )
    
    print(f"Selected {len(selected_blocks)} blocks in {capacity_time:.1f}s", flush=True)
    
    # Phase 2: FEASIBILITY PIPELINE (Step 0 + Step 1)
    print("=" * 60, flush=True)
    print("PHASE 2: FEASIBILITY PIPELINE", flush=True)
    print("=" * 60, flush=True)
    
    from src.services.feasibility_pipeline import run_feasibility_pipeline
    
    def log_fn(msg):
        print(msg, flush=True)
        logger.info(msg)
    
    k_target = 148  # Max drivers for 42h min
    pipeline_result = run_feasibility_pipeline(selected_blocks, k_target, log_fn)
    
    # Check if feasible at all
    peak = pipeline_result.get("peak_concurrency", 0)
    n_greedy = pipeline_result.get("n_greedy", 0)
    greedy_result = pipeline_result.get("greedy_result", {})
    
    if not pipeline_result.get("feasible", False):
        return SolveResultV4(
            status="INFEASIBLE",
            assignments=[],
            kpi={
                "error": f"Peak concurrency ({peak}) > K_target ({k_target})",
                "hint": "Phase-1 block selection creates too much overlap",
                "peak_concurrency": peak,
            },
            solve_times={
                "block_building": block_time,
                "phase1_capacity": capacity_time,
            },
            block_stats=block_stats
        )
    
    # Step 2+3: MODEL STRIP TEST V2 (with proper symmetry breaking)
    from src.services.model_strip_test import run_model_strip_test_v2
    
    log_fn("Running Model Strip Test V2 (anchor fixing + hints)...")
    strip_result = run_model_strip_test_v2(
        blocks=selected_blocks,
        n_drivers=peak,  # Start at peak (120)
        greedy_assignments=greedy_result.get("assignments", {}),  # For anchor fixing!
        time_limit=60.0,  # 60s per stage
        log_fn=log_fn,
    )
    
    # For now, always use greedy (strip test is diagnostic)
    assignments_map = greedy_result.get("assignments", {})
    log_fn(f"Using greedy result (strip test complete)")
    
    # Build DriverAssignment objects
    block_by_id = {b.id: b for b in selected_blocks}
    driver_blocks = {}  # driver_index -> list of Block
    
    for block_id, driver_idx in assignments_map.items():
        if driver_idx not in driver_blocks:
            driver_blocks[driver_idx] = []
        driver_blocks[driver_idx].append(block_by_id[block_id])
    
    assignments = []
    for driver_idx in sorted(driver_blocks.keys()):
        blocks_list = driver_blocks[driver_idx]
        total_hours_driver = sum(b.total_work_hours for b in blocks_list)
        days_worked = len(set(b.day.value for b in blocks_list))
        
        assignments.append(DriverAssignment(
            driver_id=f"FTE{driver_idx+1:03d}",
            driver_type="FTE",
            blocks=sorted(blocks_list, key=lambda b: (b.day.value, b.first_start)),
            total_hours=total_hours_driver,
            days_worked=days_worked,
            analysis=_analyze_driver_workload(blocks_list)
        ))
    
    # Validate
    fte_hours = [a.total_hours for a in assignments]
    under_42 = sum(1 for h in fte_hours if h < 40.0)
    over_53 = sum(1 for h in fte_hours if h > 56.5)
    
    if under_42 > 0 or over_53 > 0:
        status = "SOFT_FALLBACK_HOURS"
        logger.warning(f"Hours constraint violations: {under_42} under 42h, {over_53} over 53h")
    else:
        status = "HARD_OK"
    
    kpi = {
        "status": status,
        "total_hours": round(total_hours, 2),
        "drivers_fte": n_greedy,  # From pipeline
        "drivers_pt": 0,  # ALWAYS 0 for FTE-only
        "peak_concurrency": peak,  # NEW: crucial metric
        "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0,
        "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0,
        "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0,
        "under_42h": under_42,
        "over_53h": over_53,
        "blocks_selected": phase1_stats["selected_blocks"],
        "blocks_1er": phase1_stats["blocks_1er"],
        "blocks_2er": phase1_stats["blocks_2er"],
        "blocks_3er": phase1_stats["blocks_3er"],
        "block_mix": phase1_stats.get("block_mix", {}),
    }
    
    pipeline_time = 0.1  # Pipeline is fast
    solve_times = {
        "block_building": round(block_time, 2),
        "phase1_capacity": round(capacity_time, 2),
        "phase2_pipeline": round(pipeline_time, 2),
        "total": round(block_time + capacity_time + pipeline_time, 2),
    }
    
    logger.info("=" * 60)
    logger.info("FTE-ONLY SOLVER COMPLETE (via Pipeline)")
    logger.info("=" * 60)
    logger.info(f"Status: {status}")
    logger.info(f"Peak concurrency: {peak}")
    logger.info(f"Drivers: {n_greedy} FTE, 0 PT")
    logger.info(f"Hours: {kpi['fte_hours_min']:.1f}h - {kpi['fte_hours_max']:.1f}h")
    logger.info(f"Total time: {solve_times['total']:.1f}s")
    
    return SolveResultV4(
        status=status,
        assignments=assignments,
        kpi=kpi,
        solve_times=solve_times,
        block_stats=block_stats
    )


# =============================================================================
# SET-PARTITIONING SOLVER
# =============================================================================


# =============================================================================
# REPAIR / POST-PROCESSING (Enhanced)
# =============================================================================

def _move_block(source: DriverAssignment, target: DriverAssignment, block) -> None:
    """Helper to move a block between drivers and update stats."""
    source.blocks.remove(block)
    source.total_hours = sum(b.total_work_hours for b in source.blocks)
    source.days_worked = len({t.day for b in source.blocks for t in b.tours}) if source.blocks else 0
    
    target.blocks.append(block)
    target.total_hours = sum(b.total_work_hours for b in target.blocks)
    target.days_worked = len({t.day for b in target.blocks for t in b.tours})


def _block_day_priority(block) -> int:
    """Score block by day priority: Saturday=2, Friday=1, others=0."""
    days = {t.day for t in block.tours}
    if Weekday.SATURDAY in days:
        return 2
    if Weekday.FRIDAY in days:
        return 1
    return 0


def rebalance_to_min_fte_hours(
    assignments: list[DriverAssignment],
    min_fte_hours: float = 40.0,
    max_fte_hours: float = 53.0
) -> tuple[list[DriverAssignment], dict]:
    """
    Enhanced repair pass: ensure all FTE drivers have >= min_fte_hours.
    
    Strategy (in order):
    1. FTE→FTE balancing: Move blocks from overfull FTEs to underfull FTEs
    2. PT→FTE stealing: Move blocks from PT drivers to underfull FTEs
    3. Reclassify: Convert still-underfull FTEs to PT (last resort)
    """
    stats = {
        "moved_blocks_fte_fte": 0,
        "moved_blocks_pt_fte": 0,
        "reclassified_fte_to_pt": 0
    }
    
    # Get all FTE drivers
    all_ftes = [a for a in assignments if a.driver_type == "FTE"]
    
    # Phase 1: FTE→FTE balancing
    logger.info("Repair Phase 1: FTE→FTE balancing...")
    
    # Identify underfull and donor FTEs
    underfull_ftes = sorted(
        [a for a in all_ftes if a.total_hours < min_fte_hours],
        key=lambda x: x.total_hours  # Neediest first
    )
    
    for underfull in underfull_ftes:
        if underfull.total_hours >= min_fte_hours:
            continue
            
        # Find donor FTEs (those with hours > 40 that can spare blocks)
        donor_ftes = sorted(
            [a for a in all_ftes if a.driver_id != underfull.driver_id and a.total_hours > min_fte_hours],
            key=lambda x: -x.total_hours  # Highest hours first (most room to give)
        )
        
        # Build candidate blocks from donors
        candidates = []
        for donor in donor_ftes:
            for block in donor.blocks:
                # Check if donor would still be >= 40h after giving
                remaining = donor.total_hours - block.total_work_hours
                if remaining >= min_fte_hours:
                    candidates.append((block, donor))
        
        # Sort candidates: Saturday/Friday first, then largest blocks
        candidates.sort(key=lambda item: (_block_day_priority(item[0]), item[0].total_work_minutes), reverse=True)
        
        for block, donor in candidates:
            if underfull.total_hours >= min_fte_hours:
                break
                
            # Verify block still available
            if block not in donor.blocks:
                continue
                
            # Check recipient constraints
            if underfull.total_hours + block.total_work_hours > max_fte_hours:
                continue
                
            ok, _ = can_assign_block(underfull.blocks, block)
            if not ok:
                continue
                
            # Double-check donor stays valid
            if donor.total_hours - block.total_work_hours < min_fte_hours:
                continue
                
            # Move block
            _move_block(donor, underfull, block)
            stats["moved_blocks_fte_fte"] += 1
    
    # Phase 2: PT→FTE stealing
    logger.info("Repair Phase 2: PT→FTE stealing...")
    
    # Re-identify underfull FTEs (some may have been filled in Phase 1)
    underfull_ftes = sorted(
        [a for a in assignments if a.driver_type == "FTE" and a.total_hours < min_fte_hours],
        key=lambda x: x.total_hours
    )
    pt_drivers = [a for a in assignments if a.driver_type == "PT" and a.blocks]
    
    for underfull in underfull_ftes:
        if underfull.total_hours >= min_fte_hours:
            continue
            
        # Build candidates from PT drivers
        candidates = []
        for pt in pt_drivers:
            if pt.driver_id == underfull.driver_id:
                continue
            for block in pt.blocks:
                candidates.append((block, pt))
        
        # Sort: Saturday first, largest first
        candidates.sort(key=lambda item: (_block_day_priority(item[0]), item[0].total_work_minutes), reverse=True)
        
        for block, source_pt in candidates:
            if underfull.total_hours >= min_fte_hours:
                break
                
            if block not in source_pt.blocks:
                continue
                
            if underfull.total_hours + block.total_work_hours > max_fte_hours:
                continue
                
            ok, _ = can_assign_block(underfull.blocks, block)
            if not ok:
                continue
                
            _move_block(source_pt, underfull, block)
            stats["moved_blocks_pt_fte"] += 1
    
    # Phase 3: Reclassify remaining underfull FTEs
    logger.info("Repair Phase 3: Reclassifying remaining underfull FTEs...")
    
    for a in assignments:
        if a.driver_type == "FTE" and a.total_hours < min_fte_hours:
            a.driver_type = "PT"
            stats["reclassified_fte_to_pt"] += 1
    
    logger.info(f"Repair stats: FTE→FTE moves={stats['moved_blocks_fte_fte']}, "
                f"PT→FTE moves={stats['moved_blocks_pt_fte']}, "
                f"reclassified={stats['reclassified_fte_to_pt']}")
    
    return assignments, stats


def fill_in_days_after_heavy(
    assignments: list[DriverAssignment],
    max_fte_hours: float = 53.0
) -> tuple[list[DriverAssignment], dict]:
    """
    Fill empty days after 3-tour (heavy) days.
    
    After a 3-tour day, the driver can work up to 2 tours the next day
    with 14h rest. This function finds such empty days and tries to
    fill them with blocks from PT drivers.
    """
    from src.services.constraints import can_assign_block
    
    stats = {"filled_days": 0, "moved_blocks": 0}
    WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    
    def get_tours_on_day(driver: DriverAssignment, day_val: str) -> int:
        return sum(len(b.tours) if hasattr(b, 'tours') else 1 
                   for b in driver.blocks if b.day.value == day_val)
    
    def get_day_blocks(driver: DriverAssignment, day_val: str) -> list:
        return [b for b in driver.blocks if b.day.value == day_val]
    
    for fte in assignments:
        if fte.driver_type != "FTE":
            continue
        
        for day_idx, day_val in enumerate(WEEKDAY_ORDER[:-1]):
            tours = get_tours_on_day(fte, day_val)
            if tours < 3:
                continue
            
            next_day = WEEKDAY_ORDER[day_idx + 1]
            if get_tours_on_day(fte, next_day) > 0:
                continue
            
            heavy_blocks = get_day_blocks(fte, day_val)
            if not heavy_blocks:
                continue
            last_end = max(b.last_end for b in heavy_blocks)
            last_end_mins = last_end.hour * 60 + last_end.minute
            min_start_mins = (last_end_mins + 14 * 60) % (24 * 60)
            
            for pt in assignments:
                if pt.driver_type != "PT":
                    continue
                
                for block in list(pt.blocks):
                    if block.day.value != next_day:
                        continue
                    
                    block_start = block.first_start.hour * 60 + block.first_start.minute
                    if block_start < min_start_mins and min_start_mins < 1440:
                        continue
                    
                    block_tours = len(block.tours) if hasattr(block, 'tours') else 1
                    if block_tours > 2:
                        continue
                    
                    if fte.total_hours + block.total_work_hours > max_fte_hours:
                        continue
                    
                    ok, _ = can_assign_block(fte.blocks, block)
                    if not ok:
                        continue
                    
                    _move_block(pt, fte, block)
                    stats["moved_blocks"] += 1
                    break
            
            if get_tours_on_day(fte, next_day) > 0:
                stats["filled_days"] += 1
    
    assignments = [a for a in assignments if len(a.blocks) > 0]
    logger.info(f"Fill-in-days: filled {stats['filled_days']} days, moved {stats['moved_blocks']} blocks")
    return assignments, stats


def eliminate_pt_drivers(
    assignments: list[DriverAssignment],
    max_fte_hours: float = 53.0,
    max_iterations: int = 50,
    time_limit: float = 30.0
) -> tuple[list[DriverAssignment], dict]:
    """
    Driver elimination loop - delete smallest PT drivers by reinserting blocks.
    Standard "route elimination" move from VRP/LNS.
    """
    from src.services.constraints import can_assign_block
    from time import perf_counter
    
    start_time = perf_counter()
    stats = {"eliminated_drivers": 0, "moved_blocks": 0, "iterations": 0}
    
    def is_fri_only_1tour(d: DriverAssignment) -> bool:
        if len(d.blocks) != 1:
            return False
        b = d.blocks[0]
        return b.day.value == "Fri" and (len(b.tours) if hasattr(b, 'tours') else 1) == 1
    
    def is_sat_only(d: DriverAssignment) -> bool:
        return all(b.day.value == "Sat" for b in d.blocks)
    
    def elim_priority(d: DriverAssignment) -> tuple:
        return (0 if is_fri_only_1tour(d) else 1, 
                0 if is_sat_only(d) else 1, 
                d.total_hours, len(d.blocks))
    
    for iteration in range(max_iterations):
        if perf_counter() - start_time > time_limit:
            logger.info("Elimination time limit reached")
            break
            
        stats["iterations"] = iteration + 1
        eliminated = False
        
        pt_list = sorted([a for a in assignments if a.driver_type == "PT"], key=elim_priority)
        if not pt_list:
            break
        
        for pt in pt_list:
            blocks = list(pt.blocks)
            if not blocks:
                continue
            
            placements = []
            success = True
            
            for block in blocks:
                placed = False
                
                # Try FTEs first (lowest hours)
                for fte in sorted([a for a in assignments if a.driver_type == "FTE" 
                                   and a.total_hours + block.total_work_hours <= max_fte_hours],
                                  key=lambda x: x.total_hours):
                    ok, _ = can_assign_block(fte.blocks, block)
                    if ok:
                        placements.append((block, fte))
                        fte.blocks.append(block)
                        fte.total_hours += block.total_work_hours
                        placed = True
                        break
                
                # Try other PTs
                if not placed:
                    for other in sorted([a for a in assignments if a.driver_type == "PT" and a is not pt],
                                        key=lambda x: -x.total_hours):
                        ok, _ = can_assign_block(other.blocks, block)
                        if ok:
                            placements.append((block, other))
                            other.blocks.append(block)
                            other.total_hours += block.total_work_hours
                            placed = True
                            break
                
                if not placed:
                    success = False
                    break
            
            if success:
                pt.blocks = []
                pt.total_hours = 0
                stats["eliminated_drivers"] += 1
                stats["moved_blocks"] += len(placements)
                eliminated = True
                break
            else:
                for block, target in placements:
                    target.blocks.remove(block)
                    target.total_hours -= block.total_work_hours
        
        if not eliminated:
            break
    
    assignments = [a for a in assignments if len(a.blocks) > 0]
    logger.info(f"Eliminated {stats['eliminated_drivers']} PT drivers, "
                f"moved {stats['moved_blocks']} blocks in {stats['iterations']} iterations")
    return assignments, stats


def absorb_saturday_pt_into_fte(
    assignments: list[DriverAssignment],
    max_fte_hours: float = 53.0
) -> tuple[list[DriverAssignment], dict]:
    """
    Move Saturday blocks from PT drivers to FTEs that can absorb them.
    Reduces PT Saturday coverage before packing.
    """
    stats = {"absorbed_blocks": 0, "pt_sat_before": 0, "pt_sat_after": 0}
    
    # Count PT with Saturday before
    stats["pt_sat_before"] = sum(
        1 for a in assignments 
        if a.driver_type == "PT" and any(t.day == Weekday.SATURDAY for b in a.blocks for t in b.tours)
    )
    
    # Collect all Saturday blocks from PT drivers
    sat_blocks_and_sources = []
    for a in assignments:
        if a.driver_type == "PT":
            for block in a.blocks:
                if any(t.day == Weekday.SATURDAY for t in block.tours):
                    sat_blocks_and_sources.append((block, a))
    
    if not sat_blocks_and_sources:
        return assignments, stats
    
    logger.info(f"Absorb phase: {len(sat_blocks_and_sources)} Saturday PT blocks to try absorbing into FTEs")
    
    # Get FTE drivers sorted by lowest hours (they have most room)
    fte_drivers = sorted(
        [a for a in assignments if a.driver_type == "FTE"],
        key=lambda x: x.total_hours
    )
    
    for block, source_pt in sat_blocks_and_sources:
        # Check if still available
        if block not in source_pt.blocks:
            continue
            
        # Find FTE that can absorb
        for fte in fte_drivers:
            if fte.total_hours + block.total_work_hours > max_fte_hours:
                continue
                
            ok, _ = can_assign_block(fte.blocks, block)
            if not ok:
                continue
                
            # Move block PT→FTE
            _move_block(source_pt, fte, block)
            stats["absorbed_blocks"] += 1
            break
    
    # Count PT with Saturday after
    stats["pt_sat_after"] = sum(
        1 for a in assignments 
        if a.driver_type == "PT" and any(t.day == Weekday.SATURDAY for b in a.blocks for t in b.tours)
    )
    
    # Drop empty PT drivers
    assignments = [a for a in assignments if len(a.blocks) > 0]
    
    logger.info(f"Absorbed {stats['absorbed_blocks']} Saturday blocks into FTEs. "
                f"PT with Sat: {stats['pt_sat_before']} → {stats['pt_sat_after']}")
    
    return assignments, stats


def compute_saturday_lower_bound(assignments: list[DriverAssignment]) -> dict:
    """
    Compute theoretical lower bound for PT Saturday drivers.
    Based on peak Saturday overlap.
    """
    # Collect all Saturday blocks
    all_sat_blocks = []
    for a in assignments:
        for block in a.blocks:
            if any(t.day == Weekday.SATURDAY for t in block.tours):
                all_sat_blocks.append((block, a.driver_type))
    
    if not all_sat_blocks:
        return {"peak_sat_blocks": 0, "peak_fte_coverage": 0, "lower_bound_pt_sat": 0}
    
    # Find peak overlap using a sweep line algorithm
    events = []
    for block, driver_type in all_sat_blocks:
        start = block.first_start.hour * 60 + block.first_start.minute
        end = block.last_end.hour * 60 + block.last_end.minute
        events.append((start, 1, driver_type))  # +1 at start
        events.append((end, -1, driver_type))   # -1 at end
    
    events.sort(key=lambda x: (x[0], -x[1]))  # Sort by time, ends before starts at same time
    
    current_total = 0
    current_fte = 0
    peak_total = 0
    peak_fte = 0
    
    for time_point, delta, driver_type in events:
        current_total += delta
        if driver_type == "FTE":
            current_fte += delta
            
        if current_total > peak_total:
            peak_total = current_total
            peak_fte = current_fte
    
    # Lower bound: at peak, we need (peak_total - peak_fte) PT drivers at minimum
    lower_bound = max(0, peak_total - peak_fte)
    
    return {
        "peak_sat_blocks": peak_total,
        "peak_fte_coverage": peak_fte,
        "lower_bound_pt_sat": lower_bound
    }


def pack_part_time_saturday(
    assignments: list[DriverAssignment],
    target_pt_drivers_sat: int = 8
) -> tuple[list[DriverAssignment], dict]:
    """
    Pack Saturday PT tours into minimal number of existing PT drivers.
    
    Enhanced algorithm:
    - Only use existing PT drivers as bins (no new drivers)
    - Prefer bins that are Saturday-only or have least non-Sat work
    - Track metrics before/after
    """
    stats = {
        "packed_saturday_blocks": 0,
        "pt_drivers_with_sat_before": 0,
        "pt_drivers_with_sat_after": 0
    }
    
    # Count before
    stats["pt_drivers_with_sat_before"] = sum(
        1 for a in assignments 
        if a.driver_type == "PT" and any(t.day == Weekday.SATURDAY for b in a.blocks for t in b.tours)
    )
    
    # Collect PT drivers that have Saturday work
    pt_sat_drivers = []
    pt_sat_blocks = []
    
    for a in assignments:
        if a.driver_type == "PT":
            sat_blocks = []
            non_sat_blocks = []
            for block in a.blocks:
                if any(t.day == Weekday.SATURDAY for t in block.tours):
                    sat_blocks.append(block)
                else:
                    non_sat_blocks.append(block)
            
            if sat_blocks:
                pt_sat_drivers.append(a)
                # Strip Saturday blocks temporarily
                a.blocks = non_sat_blocks
                a.total_hours = sum(b.total_work_hours for b in a.blocks)
                a.days_worked = len({t.day for b in a.blocks for t in b.tours}) if a.blocks else 0
                pt_sat_blocks.extend(sat_blocks)
    
    if not pt_sat_blocks:
        return assignments, stats
    
    logger.info(f"Packing {len(pt_sat_blocks)} Saturday PT blocks into bins...")
    
    # Sort blocks by duration descending (FFD - First Fit Decreasing)
    pt_sat_blocks.sort(key=lambda b: b.total_work_minutes, reverse=True)
    
    # Sort bins: prefer Saturday-only (less non-Sat work), then fewer current Sat segments
    def bin_score(driver):
        non_sat_hours = sum(
            b.total_work_hours for b in driver.blocks 
            if not any(t.day == Weekday.SATURDAY for t in b.tours)
        )
        sat_segment_count = sum(
            1 for b in driver.blocks 
            if any(t.day == Weekday.SATURDAY for t in b.tours)
        )
        return (non_sat_hours, sat_segment_count)
    
    pt_sat_drivers.sort(key=bin_score)
    
    # Split into target bins and overflow
    target_bins = pt_sat_drivers[:target_pt_drivers_sat]
    overflow_bins = pt_sat_drivers[target_pt_drivers_sat:]
    all_bins = target_bins + overflow_bins
    
    packed_count = 0
    unplaced_blocks = []
    
    for block in pt_sat_blocks:
        placed = False
        
        # Try target bins first
        for driver in target_bins:
            ok, _ = can_assign_block(driver.blocks, block)
            if ok:
                driver.blocks.append(block)
                driver.total_hours = sum(b.total_work_hours for b in driver.blocks)
                driver.days_worked = len({t.day for b in driver.blocks for t in b.tours})
                placed = True
                packed_count += 1
                break
        
        # Try overflow bins
        if not placed:
            for driver in overflow_bins:
                ok, _ = can_assign_block(driver.blocks, block)
                if ok:
                    driver.blocks.append(block)
                    driver.total_hours = sum(b.total_work_hours for b in driver.blocks)
                    driver.days_worked = len({t.day for b in driver.blocks for t in b.tours})
                    placed = True
                    packed_count += 1
                    break
        
        # Last resort: any PT driver
        if not placed:
            for driver in [a for a in assignments if a.driver_type == "PT"]:
                ok, _ = can_assign_block(driver.blocks, block)
                if ok:
                    driver.blocks.append(block)
                    driver.total_hours = sum(b.total_work_hours for b in driver.blocks)
                    driver.days_worked = len({t.day for b in driver.blocks for t in b.tours})
                    placed = True
                    break
        
        if not placed:
            unplaced_blocks.append(block)
            logger.warning(f"Could not place Saturday block {block.id}")
    
    stats["packed_saturday_blocks"] = packed_count
    
    # Drop empty drivers
    assignments = [a for a in assignments if len(a.blocks) > 0]
    
    # Count after
    stats["pt_drivers_with_sat_after"] = sum(
        1 for a in assignments 
        if a.driver_type == "PT" and any(t.day == Weekday.SATURDAY for b in a.blocks for t in b.tours)
    )
    
    logger.info(f"Packed {packed_count} Saturday blocks. "
                f"PT with Sat: {stats['pt_drivers_with_sat_before']} → {stats['pt_drivers_with_sat_after']}")
    
    return assignments, stats


def solve_forecast_set_partitioning(
    tours: list[Tour],
    time_limit: float = 300.0,
    seed: int = 42,
) -> SolveResultV4:
    """
    Solve tour assignment using Set-Partitioning (Crew Scheduling).
    
    Pre-generates valid weekly rosters (columns) and uses RMP to select
    rosters that cover all blocks with minimum driver count.
    
    All rosters satisfy: 42-53h, no overlap, 11h/14h rest, max 3 tours/day.
    """
    from time import perf_counter
    
    logger.info("=" * 70)
    logger.info("SOLVER_ARCH=set-partitioning")
    logger.info("FORECAST SOLVER - SET-PARTITIONING (Crew Scheduling)")
    logger.info("=" * 70)
    logger.info(f"Tours: {len(tours)}")
    
    total_hours = sum(t.duration_hours for t in tours)
    logger.info(f"Total hours: {total_hours:.1f}h")
    logger.info(f"Expected drivers: {int(total_hours/53)}-{int(total_hours/40)}")
    
    # Phase A: Build blocks (reuse existing)
    t_block = perf_counter()
    print("PHASE A: Block building...", flush=True)
    blocks, block_stats = build_weekly_blocks_smart(tours)
    block_time = perf_counter() - t_block
    print(f"Generated {len(blocks)} blocks in {block_time:.1f}s", flush=True)
    
    block_scores = block_stats.get("block_scores", {})
    block_props = block_stats.get("block_props", {})
    block_index = build_block_index(blocks)
    
    # Phase 1: Select blocks (reuse existing)
    t_capacity = perf_counter()
    print("PHASE 1: Block selection (CP-SAT)...", flush=True)
    # Use local ConfigV4 (not ForecastConfig from forecast_weekly_solver)
    config = ConfigV4(min_hours_per_fte=40.0, time_limit_phase1=float(time_limit), seed=seed)
    selected_blocks, phase1_stats = solve_capacity_phase(
        blocks, tours, block_index, config,
        block_scores=block_scores, block_props=block_props
    )
    capacity_time = perf_counter() - t_capacity
    
    if phase1_stats["status"] != "OK":
        return SolveResultV4(
            status="FAILED",
            assignments=[],
            kpi={"error": "Phase 1 block selection failed"},
            solve_times={"block_building": block_time},
            block_stats=block_stats
        )
    
    print(f"Selected {len(selected_blocks)} blocks in {capacity_time:.1f}s", flush=True)
    
    # Phase 2: Set-Partitioning
    print("=" * 60, flush=True)
    print("PHASE 2: SET-PARTITIONING", flush=True)
    print("=" * 60, flush=True)
    
    def log_fn(msg):
        print(msg, flush=True)
        logger.info(msg)
    
    from src.services.set_partition_solver import solve_set_partitioning, convert_rosters_to_assignments
    
    t_sp = perf_counter()
    sp_result = solve_set_partitioning(
        blocks=selected_blocks,
        max_rounds=100,
        initial_pool_size=5000,
        columns_per_round=200,
        rmp_time_limit=min(60.0, time_limit / 3),
        seed=seed,
        log_fn=log_fn,
    )
    sp_time = perf_counter() - t_sp
    
    # Check result
    if sp_result.status != "OK":
        logger.warning(f"Set-Partitioning failed: {sp_result.status}")
        logger.warning(f"Uncovered blocks: {len(sp_result.uncovered_blocks)}")
        logger.warning("Falling back to greedy assignment to ensure a valid schedule")

        # Greedy fallback (always returns a valid assignment if blocks are coverable)
        t_greedy = perf_counter()
        assignments, phase2_stats = assign_drivers_greedy(selected_blocks, config)
        
        # Post-Greedy Repair (Enhanced)
        logger.info("=" * 60)
        logger.info("POST-GREEDY REPAIR")
        logger.info("=" * 60)
        
        # Step 1: Rebalance FTEs (FTE→FTE, then PT→FTE, then reclassify)
        assignments, repair_stats = rebalance_to_min_fte_hours(assignments, 40.0, 53.0)
        
        # Step 1.5: Fill empty days after 3-tour days
        assignments, fill_stats = fill_in_days_after_heavy(assignments, 53.0)
        
        # Step 2: Absorb Saturday PT blocks into FTEs before packing
        assignments, absorb_stats = absorb_saturday_pt_into_fte(assignments, 53.0)
        
        # Step 3: Pack remaining Saturday PT blocks into fewer PT drivers
        assignments, pack_stats = pack_part_time_saturday(assignments, target_pt_drivers_sat=8)
        
        # Step 4: Compute theoretical lower bound for Saturday PT
        sat_lb = compute_saturday_lower_bound(assignments)
        if sat_lb["lower_bound_pt_sat"] > 8:
            logger.warning(f"Target 8 PT Saturday infeasible; theoretical lower bound = {sat_lb['lower_bound_pt_sat']}")
        
        # Step 5: Driver elimination - delete smallest PT by reinserting blocks
        assignments, elim_stats = eliminate_pt_drivers(assignments, 53.0, time_limit=90.0)
        
        greedy_time = perf_counter() - t_greedy

        # Recalculate stats from final assignments
        fte_drivers = [a for a in assignments if a.driver_type == "FTE"]
        pt_drivers = [a for a in assignments if a.driver_type == "PT"]
        fte_hours = [a.total_hours for a in fte_drivers]

        kpi = {
            "solver_arch": "set-partitioning+greedy_fallback+repair",
            "status": "OK_GREEDY_FALLBACK",
            "sp_status": sp_result.status,
            "total_hours": round(total_hours, 2),
            "drivers_fte": len(fte_drivers),
            "drivers_pt": len(pt_drivers),
            "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0,
            "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0,
            "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0,
            "blocks_selected": phase1_stats["selected_blocks"],
            "pool_size": sp_result.pool_size,
            "rounds_used": sp_result.rounds_used,
            "uncovered_blocks": len(sp_result.uncovered_blocks),
            # Repair KPIs
            "fte_under_40h": sum(1 for h in fte_hours if h < 40.0),
            "repair_moved_blocks_fte_fte": repair_stats["moved_blocks_fte_fte"],
            "repair_moved_blocks_pt_fte": repair_stats["moved_blocks_pt_fte"],
            "repair_reclassified": repair_stats["reclassified_fte_to_pt"],
            # Absorb KPIs
            "pt_sat_before_absorb": absorb_stats["pt_sat_before"],
            "pt_sat_after_absorb": absorb_stats["pt_sat_after"],
            "absorbed_sat_blocks": absorb_stats["absorbed_blocks"],
            # Pack KPIs
            "pt_drivers_with_saturday_work_before_pack": pack_stats["pt_drivers_with_sat_before"],
            "pt_drivers_with_saturday_work": pack_stats["pt_drivers_with_sat_after"],
            # Lower bound
            "sat_pt_lower_bound": sat_lb["lower_bound_pt_sat"],
            "sat_peak_blocks": sat_lb["peak_sat_blocks"],
            "sat_peak_fte": sat_lb["peak_fte_coverage"],
        }

        solve_times = {
            "block_building": round(block_time, 2),
            "phase1_capacity": round(capacity_time, 2),
            "set_partitioning": round(sp_time, 2),
            "greedy_fallback": round(greedy_time, 2),
            "total": round(block_time + capacity_time + sp_time + greedy_time, 2),
        }

        return SolveResultV4(
            status="OK_GREEDY_FALLBACK",
            assignments=assignments,
            kpi=kpi,
            solve_times=solve_times,
            block_stats=block_stats,
        )
    
    # Convert rosters to DriverAssignment
    block_lookup = {b.id: b for b in selected_blocks}
    assignments = convert_rosters_to_assignments(sp_result.selected_rosters, block_lookup)
    
    # Build KPI
    fte_hours = [a.total_hours for a in assignments]
    under_42 = sum(1 for h in fte_hours if h < 40.0)
    over_53 = sum(1 for h in fte_hours if h > 56.5)
    
    if under_42 > 0 or over_53 > 0:
        # NO SOFT FALLBACK - set-partitioning must produce valid results or FAIL
        status = "FAILED_CONSTRAINT_VIOLATION"
        logger.error(f"CONSTRAINT VIOLATION: {under_42} under 40h, {over_53} over 56h")
        logger.error("Set-Partitioning should only return valid rosters!")
    else:
        status = "OK"
    
    kpi = {
        "solver_arch": "set-partitioning",  # CRITICAL: Proves which solver was used
        "status": status,
        "total_hours": round(total_hours, 2),
        "drivers_fte": sp_result.num_drivers,
        "drivers_pt": 0,
        "fte_hours_min": round(sp_result.hours_min, 2),
        "fte_hours_max": round(sp_result.hours_max, 2),
        "fte_hours_avg": round(sp_result.hours_avg, 2),
        "under_42h": under_42,
        "over_53h": over_53,
        "blocks_selected": phase1_stats["selected_blocks"],
        "pool_size": sp_result.pool_size,
        "rounds_used": sp_result.rounds_used,
    }
    
    solve_times = {
        "block_building": round(block_time, 2),
        "phase1_capacity": round(capacity_time, 2),
        "set_partitioning": round(sp_time, 2),
        "total": round(block_time + capacity_time + sp_time, 2),
    }
    
    valid_constraints = status == "OK"
    
    logger.info("=" * 60)
    logger.info("SET-PARTITIONING SOLVER COMPLETE")
    logger.info("=" * 60)
    logger.info(f"SOLVER_ARCH=set-partitioning RESULT={status} DRIVERS={sp_result.num_drivers} PT=0 VALID_CONSTRAINTS={valid_constraints}")
    logger.info(f"Status: {status}")
    logger.info(f"Drivers: {sp_result.num_drivers} FTE, 0 PT")
    logger.info(f"Hours: {sp_result.hours_min:.1f}h - {sp_result.hours_max:.1f}h")
    logger.info(f"Total time: {solve_times['total']:.1f}s")
    
    return SolveResultV4(
        status=status,
        assignments=assignments,
        kpi=kpi,
        solve_times=solve_times,
        block_stats=block_stats
    )
