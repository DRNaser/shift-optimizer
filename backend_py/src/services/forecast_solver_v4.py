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
    
    # Sort all blocks by hours descending (assign larger blocks first for better packing)
    all_blocks_sorted = sorted(blocks, key=lambda b: b.total_work_hours, reverse=True)
    
    for block in all_blocks_sorted:
        assigned = False
        
        # Sort FTE drivers by hours ascending (fill emptier drivers first)
        fte_drivers = [(did, d) for did, d in drivers.items() if d["type"] == "FTE"]
        fte_drivers.sort(key=lambda x: x[1]["hours"])
        
        for driver_id, d in fte_drivers:
            if can_take_block(driver_id, block):
                assign_block(driver_id, block)
                assigned = True
                break
        
        if not assigned:
            # No FTE can take it - use PT
            # Try existing PT first
            for driver_id in list(drivers.keys()):
                if drivers[driver_id]["type"] == "PT" and can_take_block(driver_id, block):
                    assign_block(driver_id, block)
                    assigned = True
                    break
            
            if not assigned:
                # Create new PT
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
    
    stats = {
        "drivers_fte": len([a for a in assignments if a.driver_type == "FTE"]),
        "drivers_pt": len([a for a in assignments if a.driver_type == "PT"]),
        "fte_hours_min": round(min(fte_hours), 2) if fte_hours else 0,
        "fte_hours_max": round(max(fte_hours), 2) if fte_hours else 0,
        "fte_hours_avg": round(sum(fte_hours) / len(fte_hours), 2) if fte_hours else 0,
        "under_hours_count": len(under_hours),
        "time": round(elapsed, 2),
    }
    

    
    logger.info(f"Assigned to {len(assignments)} drivers")
    logger.info(f"  FTE: {stats['drivers_fte']} (hours: {stats['fte_hours_min']}-{stats['fte_hours_max']}h)")
    logger.info(f"  PT: {stats['drivers_pt']}")
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
    
    # Phase 2: Assignment
    t_greedy = perf_counter()
    logger.info("PHASE C: Greedy assignment start")
    assignments, phase2_stats = assign_drivers_greedy(selected_blocks, config)
    logger.info("PHASE C: Greedy assignment done in %.2fs", perf_counter() - t_greedy)
    
    # Determine status
    fte_count = phase2_stats["drivers_fte"]
    under_count = phase2_stats.get("under_hours_count", 0)
    
    if under_count == 0:
        status = "HARD_OK"
    else:
        status = "SOFT_FALLBACK_HOURS"
    
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

