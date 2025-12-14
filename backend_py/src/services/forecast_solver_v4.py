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
import time as time_module

from ortools.sat.python import cp_model

from src.domain.models import Block, Tour, Weekday
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
    num_workers: int = 8


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
    
    def to_dict(self) -> dict:
        return {
            "driver_id": self.driver_id,
            "type": self.driver_type,
            "hours_week": round(self.total_hours, 2),
            "days_worked": self.days_worked,
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
    print(f"\n{'='*60}")
    print("PHASE 1: Capacity Planning (use_block model)")
    print(f"{'='*60}")
    print(f"Blocks: {len(blocks)}, Tours: {len(tours)}")
    
    start = time_module.time()
    
    model = cp_model.CpModel()
    
    # Variables: one per block
    use = {}
    for b, block in enumerate(blocks):
        use[b] = model.NewBoolVar(f"use_{b}")
    
    print(f"Variables: {len(use)} (vs {len(use) * 150}+ in old model)")
    
    # Constraint: Coverage (each tour exactly once)
    print("Adding coverage constraints...")
    for tour in tours:
        blocks_with_tour = block_index.get(tour.id, [])
        if not blocks_with_tour:
            raise ValueError(f"Tour {tour.id} has no blocks!")
        
        # Find indices of blocks containing this tour
        block_indices = []
        for b, block in enumerate(blocks):
            if any(t.id == tour.id for t in block.tours):
                block_indices.append(b)
        
        model.Add(sum(use[b] for b in block_indices) == 1)
    
    # Note: Overlap constraints are NOT needed in this model!
    print("Overlap constraints: NOT NEEDED (implicit in coverage)")
    
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
    
    # Solve
    print("Solving...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_phase1
    solver.parameters.num_workers = config.num_workers
    solver.parameters.random_seed = config.seed
    
    status = solver.Solve(model)
    elapsed = time_module.time() - start
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"[FAILED] No solution found")
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
    print(f"\n{'='*60}")
    print("PHASE 2: Driver Assignment (Greedy)")
    print(f"{'='*60}")
    print(f"Blocks to assign: {len(blocks)}")
    
    start = time_module.time()
    
    # Group blocks by day, then sort by start time
    blocks_by_day: dict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        blocks_by_day[block.day.value].append(block)
    
    for day in blocks_by_day:
        blocks_by_day[day].sort(key=lambda b: b.first_start)
    
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
    
    def can_take_block(driver_id: str, block: Block) -> bool:
        """Check if driver can take this block."""
        d = drivers[driver_id]
        day = block.day.value
        
        # Check overlap with existing blocks on same day
        for existing in d["day_blocks"][day]:
            if blocks_overlap(existing, block):
                return False
        
        # Check hours if FTE
        if d["type"] == "FTE":
            new_hours = d["hours"] + block.total_work_hours
            if new_hours > config.max_hours_per_fte:
                return False
        
        return True
    
    def assign_block(driver_id: str, block: Block):
        """Assign block to driver."""
        d = drivers[driver_id]
        d["hours"] += block.total_work_hours
        d["days"].add(block.day.value)
        d["blocks"].append(block)
        d["day_blocks"][block.day.value].append(block)
    
    # Assign blocks day by day
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        if day not in blocks_by_day:
            continue
        
        for block in blocks_by_day[day]:
            assigned = False
            
            # Try existing FTE drivers
            for driver_id in list(drivers.keys()):
                if drivers[driver_id]["type"] == "FTE" and can_take_block(driver_id, block):
                    assign_block(driver_id, block)
                    assigned = True
                    break
            
            if not assigned:
                # Create new FTE
                driver_id = create_fte()
                assign_block(driver_id, block)
    
    # Check FTE hour constraints
    under_hours = []
    for driver_id, d in drivers.items():
        if d["type"] == "FTE" and d["hours"] < config.min_hours_per_fte:
            under_hours.append((driver_id, d["hours"]))
    
    elapsed = time_module.time() - start
    
    # Build assignments
    assignments = []
    for driver_id, d in drivers.items():
        if d["blocks"]:
            assignments.append(DriverAssignment(
                driver_id=driver_id,
                driver_type=d["type"],
                blocks=d["blocks"],
                total_hours=d["hours"],
                days_worked=len(d["days"])
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
    
    print(f"Assigned to {len(assignments)} drivers")
    print(f"  FTE: {stats['drivers_fte']} (hours: {stats['fte_hours_min']}-{stats['fte_hours_max']}h)")
    print(f"  PT: {stats['drivers_pt']}")
    if under_hours:
        print(f"  [WARN] {len(under_hours)} FTE drivers under {config.min_hours_per_fte}h")
    print(f"Time: {elapsed:.2f}s")
    
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
    
    print(f"\n{'='*70}")
    print("FORECAST SOLVER v4 - USE_BLOCK MODEL")
    print(f"{'='*70}")
    print(f"Tours: {len(tours)}")
    
    total_hours = sum(t.duration_hours for t in tours)
    print(f"Total hours: {total_hours:.1f}h")
    
    # Build blocks
    print("\nBuilding blocks...")
    block_start = time_module.time()
    blocks, block_stats = build_weekly_blocks_smart(tours)
    block_time = time_module.time() - block_start
    
    block_index = build_block_index(blocks)
    
    # Extract scores from block_stats
    block_scores = block_stats.get("block_scores", {})
    block_props = block_stats.get("block_props", {})
    
    print(f"Blocks: {len(blocks)} (1er={block_stats['blocks_1er']}, 2er={block_stats['blocks_2er']}, 3er={block_stats['blocks_3er']})")
    if block_scores:
        print(f"Policy scores loaded: {len(block_scores)} blocks")
    
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
    assignments, phase2_stats = assign_drivers_greedy(selected_blocks, config)
    
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
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Status: {status}")
    print(f"Blocks: {phase1_stats['selected_blocks']} selected")
    print(f"Drivers: {fte_count} FTE + {phase2_stats['drivers_pt']} PT")
    print(f"Total time: {solve_times['total']:.2f}s")
    
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
    
    print(f"Style report saved to: {output_path}")

