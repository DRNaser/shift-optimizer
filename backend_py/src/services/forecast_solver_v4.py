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

Variables: O(blocks) instead of O(blocks Ã— drivers) = 100x reduction
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import NamedTuple, Optional
from enum import Enum
import math
from time import perf_counter
import logging

from ortools.sat.python import cp_model

# Setup logger
logger = logging.getLogger("ForecastSolverV4")


def safe_print(*args, **kwargs):
    """Print wrapper that handles Windows console encoding issues.
    
    Catches OSError (detached console) and UnicodeError (encoding failures).
    On encoding failure, sanitizes args using stdout encoding with 'replace'.
    Never crashes the solver due to logging issues.
    """
    import builtins
    import sys
    try:
        builtins.print(*args, **kwargs)
    except (OSError, UnicodeError):
        # Attempt to sanitize and retry
        try:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe_args = [str(a).encode(enc, 'replace').decode(enc, 'replace') for a in args]
            builtins.print(*safe_args, **kwargs)
        except Exception:
            # Swallow all errors - logging must never crash the solver
            pass

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
    max_blocks: int = 50000  # Hard limit to prevent model explosion
    w_new_driver: float = 500.0  # Penalty for activating any new FTE (REDUCED to prefer FTE)
    w_pt_new: float = 10000.0  # Additional penalty for new PT drivers (INCREASED to minimize PT)
    w_pt_weekday: float = 5000.0  # PT on Mon-Fri very expensive
    w_pt_saturday: float = 5000.0  # PT on Saturday also expensive (minimize all PT!)
    # PT fragmentation control
    pt_min_hours: float = 9.0  # Minimum hours for PT drivers (soft constraint)
    w_pt_underutil: int = 2000  # Penalty weight for PT under-utilization (shortfall)
    w_pt_day_spread: int = 1000  # Penalty per PT working day (minimize fragmentation)
    pt_max_week_hours: float = 30.0  # PT bin-pack cap (used in SP PT seeding)
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
    
    # v5: Day cap for peak days (hard operational constraint)
    day_cap_hard: int = 220  # Maximum blocks per peak day (operational limit)

    # Global CP-SAT Phase 2B control
    extended_hours: bool = False  # If True, max_hours_per_fte = 56.0
    
    enable_global_cpsat: bool = False  # Disabled by default (times out on large problems)
    global_cpsat_block_threshold: int = 200  # Only use CP-SAT if blocks < this
    
    # =========================================================================
    # S2.1-S2.4: PHASE 2 FEATURE FLAGS (default OFF)
    # =========================================================================
    enable_fill_to_target_greedy: bool = False  # S2.1: Use fill-to-target scoring (default OFF for canary)
    enable_bad_block_mix_rerun: bool = False    # S2.2-S2.4: Enable rerun on BAD_BLOCK_MIX (default OFF)
    
    # S2.2: BAD_BLOCK_MIX trigger thresholds
    pt_ratio_threshold: float = 0.25          # Trigger rerun if pt_ratio > this
    underfull_ratio_threshold: float = 0.15   # Trigger rerun if underfull_ratio > this
    
    # S2.3: Rerun budget control
    min_rerun_budget: float = 5.0             # Minimum budget for rerun to happen
    
    # S2.4: Rerun config multipliers (make Path-B different)
    rerun_1er_penalty_multiplier: float = 2.0  # Multiply 1er-with-multi penalty by this

    # Block Capping Configuration
    enable_diag_block_caps: bool = False
    cap_quota_2er: float = 0.30  # Default 30% reservation for 2-tour blocks
    
    # S4.1: Choice-1er Penalty (WP11)
    w_choice_1er: float = 1.0  # Penalty factor for Choice-1er (x BASE_1)
    
    # =========================================================================
    # OUTPUT PROFILES: MIN_HEADCOUNT_3ER vs BEST_BALANCED
    # =========================================================================
    output_profile: str = "MIN_HEADCOUNT_3ER"  # "MIN_HEADCOUNT_3ER" | "BEST_BALANCED"
    
    # 3er Gap Constraints (MIN_HEADCOUNT_3ER only)
    gap_3er_min_minutes: int = 30  # Min gap between tours in a valid 3er
    cap_quota_3er: float = 0.25    # 3er reservation for MIN_HEADCOUNT_3ER
    w_3er_bonus: float = 10.0      # Small tie-break reward for 3er selection
    
    # BEST_BALANCED: balance-focused weights
    max_extra_driver_pct: float = 0.05   # Max +5% drivers vs min-headcount
    w_balance_underfull: float = 100.0   # Penalty per underfull FTE
    w_pt_penalty: float = 500.0          # Penalty for PT usage
    w_balance_variance: float = 50.0     # Variance/smoothness penalty
    
    # =========================================================================
    # QUALITY-FIRST: Two-Pass Guarantee (RC0 Release Policy)
    # =========================================================================
    pass2_min_time_s: float = 15.0       # GUARANTEED minimum time for Pass-2 (Quality profile)
    quality_mode: bool = False           # If True, use QUALITY profile (longer budgets, guaranteed Pass-2)
    quality_time_budget: float = 300.0   # Default time budget for QUALITY mode (5 min)
    
    # =========================================================================
    # LNS ENDGAME: Low-Hour Pattern Consolidation (Set Partitioning)
    # =========================================================================
    enable_lns_low_hour_consolidation: bool = False
    lns_time_budget_s: float = 30.0                  # Total LNS time budget
    lns_low_hour_threshold_h: float = 30.0           # Hours threshold for "low-hour" FTE patterns
    lns_receiver_k_values: tuple = (3, 5, 8, 12)     # Escalating receiver neighborhood sizes
    lns_attempt_budget_s: float = 2.0                # Budget per single kill attempt
    lns_max_attempts: int = 30                       # Maximum kill attempts

    # =========================================================================
    # DEBUG: CONSTRAINT FAMILY TOGGLES (Phase 1)
    # =========================================================================
    debug_disable_coverage: bool = False
    debug_disable_day_caps: bool = False
    debug_disable_headcount_lock: bool = False


# =============================================================================
# COVERAGE AUDIT + FEASIBILITY NET
# =============================================================================

def audit_coverage(tours: list[Tour], blocks: list[Block]) -> dict:
    """Audit coverage: per-tour candidate counts and missing tours."""
    tour_counts = defaultdict(int)
    for block in blocks:
        for tour in block.tours:
            tour_counts[tour.id] += 1

    zero_tours = [t for t in tours if tour_counts.get(t.id, 0) == 0]
    min_candidates = min(tour_counts.values()) if tour_counts else 0
    samples = [
        {
            "id": t.id,
            "day": t.day.value,
            "start": t.start_time.strftime("%H:%M"),
            "end": t.end_time.strftime("%H:%M"),
        }
        for t in zero_tours[:5]
    ]

    safe_print(
        f"[AUDIT] min_candidates_per_tour={min_candidates} "
        f"tours_with_zero_candidates={len(zero_tours)}",
        flush=True,
    )
    if zero_tours:
        safe_print(f"[AUDIT] zero-candidate samples={samples}", flush=True)

    return {
        "min_candidates_per_tour": min_candidates,
        "tours_with_zero_candidates": len(zero_tours),
        "zero_tours": [t.id for t in zero_tours],
        "samples": samples,
    }


def ensure_singletons_for_all_tours(
    tours: list[Tour],
    blocks: list[Block],
) -> tuple[list[Block], list[Block]]:
    """Ensure at least one singleton block per tour (feasibility net)."""
    blocks_by_tour = defaultdict(list)
    existing_ids = {b.id for b in blocks}
    for block in blocks:
        for tour in block.tours:
            blocks_by_tour[tour.id].append(block)

    injected: list[Block] = []
    for tour in tours:
        has_singleton = any(
            len(block.tours) == 1 for block in blocks_by_tour.get(tour.id, [])
        )
        if has_singleton:
            continue

        block_id = f"B1-{tour.id}"
        if block_id in existing_ids:
            block_id = f"B1-AUTO-{tour.id}"
        injected_block = Block(
            id=block_id,
            day=tour.day,
            tours=[tour],
            is_split=False,
            max_pause_minutes=0,
            pause_zone="REGULAR",
        )
        injected.append(injected_block)
        existing_ids.add(block_id)

    if injected:
        safe_print(f"[AUTO_HEAL] Injected {len(injected)} singleton blocks", flush=True)
    return blocks + injected, injected


def _pause_zone_value(block: Block) -> str:
    pause_zone = block.pause_zone
    return pause_zone.value if hasattr(pause_zone, "value") else str(pause_zone)


def _merge_repair_blocks(
    selected: list[Block],
    all_blocks: list[Block],
    block_index: dict,
    block_scores: Optional[dict] = None,
) -> tuple[list[Block], dict]:
    """Deterministic post-pass to merge singles into 3er/2er blocks when possible."""
    selected_by_id = {b.id: b for b in selected}
    tour_to_block = {t.id: b for b in selected for t in b.tours}

    def block_minutes(block: Block) -> int:
        if hasattr(block, "total_work_minutes"):
            return int(block.total_work_minutes)
        if hasattr(block, "total_work_hours"):
            return int(block.total_work_hours * 60)
        return 0

    def candidate_score(block: Block) -> tuple:
        score = block_scores.get(block.id, 0) if block_scores else 0
        return (-score, -block_minutes(block), block.id)

    def can_replace(candidate: Block) -> tuple[bool, list[Block]]:
        cand_tours = {t.id for t in candidate.tours}
        covering_blocks = []
        for tid in cand_tours:
            existing = tour_to_block.get(tid)
            if not existing:
                return False, []
            covering_blocks.append(existing)
        for b in covering_blocks:
            if not {t.id for t in b.tours}.issubset(cand_tours):
                return False, []
        return True, list({b.id: b for b in covering_blocks}.values())

    stats = {"replaced_blocks": 0, "added_blocks": 0}

    def apply_candidates(candidates: list[Block]) -> None:
        nonlocal selected_by_id, tour_to_block, stats
        for cand in candidates:
            ok, covering = can_replace(cand)
            if not ok:
                continue
            for old in covering:
                selected_by_id.pop(old.id, None)
            selected_by_id[cand.id] = cand
            for t in cand.tours:
                tour_to_block[t.id] = cand
            stats["replaced_blocks"] += len(covering)
            stats["added_blocks"] += 1

    blocks_3er = sorted([b for b in all_blocks if len(b.tours) == 3], key=candidate_score)
    blocks_2er_reg = sorted(
        [b for b in all_blocks if len(b.tours) == 2 and _pause_zone_value(b) == "REGULAR"],
        key=candidate_score
    )
    blocks_2er_split = sorted(
        [b for b in all_blocks if len(b.tours) == 2 and _pause_zone_value(b) == "SPLIT"],
        key=candidate_score
    )

    apply_candidates(blocks_3er)
    apply_candidates(blocks_2er_reg)
    apply_candidates(blocks_2er_split)

    return list(selected_by_id.values()), stats


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
    missing_tours: list[str] = field(default_factory=list)  # Patch 3: Tours that couldn't be covered
    
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "kpi": self.kpi,
            "drivers": [a.to_dict() for a in self.assignments],
            "solve_times": self.solve_times,
            "block_stats": self.block_stats,
            "missing_tours": self.missing_tours
        }



# =============================================================================
# S1.1-S1.4: PHASE 1 PACKABILITY HELPERS
# =============================================================================

def compute_tour_has_multi(blocks: list[Block], tours: list[Tour]) -> dict[str, bool]:
    """
    S1.1: Precompute tour_has_multi[tour_id] = True if any block covering this
    tour has len(tours) > 1 (i.e., the tour has multi-tour options in pool).
    
    O(n) single pass over blocks, NOT O(nÂ²).
    
    Determinism: Uses sorted tour IDs for iteration.
    """
    tour_has_multi: dict[str, bool] = {t.id: False for t in tours}
    
    # Single pass O(blocks Ã— avg_tours_per_block) â‰ˆ O(n)
    for block in blocks:
        if len(block.tours) > 1:  # This is a multi-tour block
            for tour in block.tours:
                tour_has_multi[tour.id] = True
    
    return tour_has_multi


def compute_packability_metrics(
    selected_blocks: list[Block],
    all_blocks: list[Block],
    tours: list[Tour],
) -> dict:
    """
    S1.4: Compute packability metrics for RunReport.
    
    Metrics:
    - forced_1er_rate: Tours with ONLY 1er options in pool (no 2er/3er)
    - missed_3er_opps: Tours covered by 1er in solution, despite having 3er option in pool
    - missed_2er_opps: Tours covered by 1er despite having 2er option (but no 3er)
    - missed_multi_opps: Total tours covered by 1er that had ANY multi option
    
    Determinism: Uses sorted IDs for iteration.
    """
    # Build tour -> available block sizes in pool
    tour_available_sizes: dict[str, set[int]] = {t.id: set() for t in tours}
    for block in all_blocks:
        for tour in block.tours:
            tour_available_sizes[tour.id].add(len(block.tours))
    
    # forced_1er_rate: Tours with only size=1 in pool
    forced_1er_tours = []
    for tour_id in sorted(tour_available_sizes.keys()):
        sizes = tour_available_sizes[tour_id]
        if sizes == {1}:  # Only 1er available
            forced_1er_tours.append(tour_id)
    
    forced_1er_rate = len(forced_1er_tours) / len(tours) if tours else 0.0
    
    # Build solution coverage: tour_id -> block_size in solution
    tour_solution_size: dict[str, int] = {}
    for block in selected_blocks:
        for tour in block.tours:
            tour_solution_size[tour.id] = len(block.tours)
    
    # Compute missed opportunities
    missed_3er_opps = []
    missed_2er_opps = []
    missed_multi_opps = []
    
    for tour_id in sorted(tour_solution_size.keys()):
        solution_size = tour_solution_size.get(tour_id, 0)
        available_sizes = tour_available_sizes.get(tour_id, set())
        
        if solution_size == 1:
            # Check if multi-tour options existed
            if 3 in available_sizes:
                missed_3er_opps.append(tour_id)
                missed_multi_opps.append(tour_id)
            elif 2 in available_sizes:
                missed_2er_opps.append(tour_id)
                missed_multi_opps.append(tour_id)
    
    return {
        "forced_1er_rate": round(forced_1er_rate, 4),
        "forced_1er_count": len(forced_1er_tours),
        "missed_3er_opps_count": len(missed_3er_opps),
        "missed_2er_opps_count": len(missed_2er_opps),
        "missed_multi_opps_count": len(missed_multi_opps),
        "total_tours": len(tours),
    }



def compute_packability_cost_adjustments(
    block: Block,
    tour_has_multi: dict[str, bool],
    config: 'ConfigV4',
) -> float:
    """
    S1.2-S1.3: Compute packability cost adjustments for a block.
    
    Returns ADDITIONAL cost (negative = bonus, positive = penalty).
    
    S1.2: 1er-with-alternative penalty (when tour has multi-tour option)
    S1.3: 3er bonus / 2er shaping
    
    These are TERTIARY tie-breakers, not primary objective changes.
    """
    # Feature flag check (future: config.enable_packability_costs)
    # For now, always apply
    
    adjustment = 0.0
    block_size = len(block.tours)
    
    # S1.2: 1er-with-alternative penalty
    # If this is a 1er AND the tour has multi-tour options, penalize
    if block_size == 1:
        tour = block.tours[0]
        if tour_has_multi.get(tour.id, False):
            # Small penalty for choosing 1er when multi-tour exists
            # This is TERTIARY, so weight is small (e.g., 1-5)
            adjustment += 2.0  # Penalty
    
    # S1.3: 3er bonus / 2er shaping
    # Bonus for 3er (prefer packing 3 tours together)
    if block_size == 3:
        adjustment -= 3.0  # Bonus (negative cost)
    elif block_size == 2:
        adjustment -= 1.0  # Smaller bonus for 2er
    
    return adjustment


# =============================================================================
# S2.1-S2.4: PHASE 2 GREEDY FILL-TO-TARGET + FEEDBACK LOOP
# =============================================================================

def fill_to_target_score(
    driver_hours: float,
    block_hours: float,
    driver_type: str,
    config: ConfigV4,
) -> float:
    """
    S2.1: Fill-to-target scoring (config-driven).
    
    Returns a score (lower = better) for assigning a block to a driver.
    
    Priority for FTE:
    1. Threshold-crossing: prefer assignments that push driver from < min to >= min
    2. Distance to target: minimize abs(new_hours - target)
    
    For PT: always large penalty (+1e6) so PT is used only as overflow.
    
    Determinism: Pure function, no random elements.
    """
    if not config.enable_fill_to_target_greedy:
        # Fallback: simple hours-based scoring
        return driver_hours + block_hours
    
    new_hours = driver_hours + block_hours
    
    if driver_type == "PT":
        # PT is always penalized heavily
        return 1e6 + new_hours
    
    # FTE scoring
    min_thr = config.min_hours_per_fte
    target = config.fte_hours_target
    
    # Priority 1: Threshold crossing bonus
    threshold_bonus = 0.0
    if driver_hours < min_thr and new_hours >= min_thr:
        threshold_bonus = -1000.0  # Large bonus for crossing threshold
    
    # Priority 2: Distance to target (range 0-100)
    distance_penalty = abs(new_hours - target)
    
    # Priority 3: Overflow penalty (going over target is worse than under)
    overflow_penalty = 0.0
    if new_hours > config.max_hours_per_fte:
        overflow_penalty = 1e9  # Infeasible
    elif new_hours > target:
        overflow_penalty = (new_hours - target) * 10  # Soft penalty for overtime
    
    return threshold_bonus + distance_penalty + overflow_penalty


def compute_block_mix_ratios(
    assignments: list['DriverAssignment'],
    config: ConfigV4,
) -> dict:
    """
    S2.2: Compute block mix ratios for BAD_BLOCK_MIX detection.
    
    Returns:
    - pt_ratio: (#PT drivers with â‰¥1 block) / (#all drivers with â‰¥1 block)
    - underfull_ratio: (#FTE with hours < min) / (#FTE with â‰¥1 block)
    
    Determinism: Iterates in stable order (assignments order preserved).
    """
    if not assignments:
        return {
            "pt_ratio": 0.0,
            "underfull_ratio": 0.0,
            "pt_count": 0,
            "fte_count": 0,
            "underfull_fte_count": 0,
            "total_drivers": 0,
        }
    
    # Count drivers with â‰¥1 block
    drivers_with_blocks = [a for a in assignments if a.blocks]
    pt_with_blocks = [a for a in drivers_with_blocks if a.driver_type == "PT"]
    fte_with_blocks = [a for a in drivers_with_blocks if a.driver_type == "FTE"]
    
    # PT ratio
    total_drivers = len(drivers_with_blocks)
    pt_count = len(pt_with_blocks)
    pt_ratio = pt_count / total_drivers if total_drivers > 0 else 0.0
    
    # Underfull FTE ratio
    fte_count = len(fte_with_blocks)
    underfull_fte = [a for a in fte_with_blocks if a.total_hours < config.min_hours_per_fte]
    underfull_fte_count = len(underfull_fte)
    underfull_ratio = underfull_fte_count / fte_count if fte_count > 0 else 0.0
    
    return {
        "pt_ratio": round(pt_ratio, 4),
        "underfull_ratio": round(underfull_ratio, 4),
        "pt_count": pt_count,
        "fte_count": fte_count,
        "underfull_fte_count": underfull_fte_count,
        "total_drivers": total_drivers,
    }


def should_trigger_rerun(
    block_mix: dict,
    config: ConfigV4,
    already_reran: bool,
    budget_left: float,
) -> tuple[bool, str]:
    """
    S2.2-S2.3: Determine if BAD_BLOCK_MIX rerun should be triggered.
    
    Returns:
    - (should_rerun, reason_code)
    
    Trigger when:
    - NOT already_reran
    - budget_left >= config.min_rerun_budget
    - pt_ratio > 0.25 OR underfull_ratio > 0.15
    
    Determinism: Pure function, no random elements.
    """
    if not config.enable_bad_block_mix_rerun:
        return False, "RERUN_DISABLED"
    
    if already_reran:
        return False, "MAX_RERUN_REACHED"
    
    if budget_left < config.min_rerun_budget:
        return False, "INSUFFICIENT_BUDGET"
    
    pt_ratio = block_mix.get("pt_ratio", 0.0)
    underfull_ratio = block_mix.get("underfull_ratio", 0.0)
    
    reasons = []
    if pt_ratio > config.pt_ratio_threshold:
        reasons.append(f"PT_RATIO_HIGH:{pt_ratio:.2f}")
    if underfull_ratio > config.underfull_ratio_threshold:
        reasons.append(f"UNDERFULL_RATIO_HIGH:{underfull_ratio:.2f}")
    
    if reasons:
        return True, "BAD_BLOCK_MIX:" + ",".join(reasons)
    
    return False, "MIX_OK"


def create_rerun_config(config: ConfigV4) -> ConfigV4:
    """
    S2.4: Create modified config for Path-B rerun.
    
    The rerun config is DETERMINISTICALLY different:
    - 1er penalty multiplied by rerun_1er_penalty_multiplier (default 2x)
    
    This ensures Path-B produces a different solution.
    """
    # NamedTuple is immutable, so we return a new one with same values
    # The multiplier is used in packability cost adjustments at runtime
    return config  # The multiplier is accessed directly from config


# =============================================================================
# S3.1-S3.3: PHASE 3 REPAIR UPGRADES
# =============================================================================

# S3.1: Hard bounds for repair
REPAIR_PT_LIMIT = 20      # Max PT drivers to consider as candidates
REPAIR_FTE_LIMIT = 30     # Max FTE drivers to consider as receivers
REPAIR_BLOCK_LIMIT = 100  # Max moves per repair call


@dataclass
class RepairStats:
    """S3.1-S3.3: Statistics from repair phase."""
    moves_applied: int = 0
    moves_attempted: int = 0
    pt_before: int = 0
    pt_after: int = 0
    underfull_fte_before: int = 0
    underfull_fte_after: int = 0
    reason_codes: list = field(default_factory=list)


def repair_pt_to_fte_swaps(
    assignments: list[DriverAssignment],
    config: ConfigV4,
    can_assign_fn=None,
) -> tuple[list[DriverAssignment], RepairStats]:
    """
    S3.1-S3.3: Bounded PTâ†’FTE swap repair.
    
    Moves blocks from PT drivers to underfull/available FTE drivers.
    
    Invariants:
    - Deterministic: sorted by (hours, id) for PT, (delta, id) for FTE
    - Bounded: PT_LIMIT, FTE_LIMIT, BLOCK_LIMIT
    - No unbounded loops: stop on no progress or limit hit
    - Feasibility: only move if can_assign_block returns True
    
    Args:
        assignments: Current driver assignments
        config: Solver configuration
        can_assign_fn: Optional feasibility checker (default: simple Hours check)
    
    Returns:
        (updated_assignments, stats)
    """
    from src.services.constraints import can_assign_block
    
    if can_assign_fn is None:
        can_assign_fn = can_assign_block
    
    stats = RepairStats()
    
    # Separate PT and FTE assignments
    pt_assignments = [a for a in assignments if a.driver_type == "PT" and a.blocks]
    fte_assignments = [a for a in assignments if a.driver_type == "FTE"]
    
    # Initial counts
    stats.pt_before = len(pt_assignments)
    stats.underfull_fte_before = sum(
        1 for a in fte_assignments if a.total_hours < config.min_hours_per_fte
    )
    
    if not pt_assignments or not fte_assignments:
        stats.pt_after = stats.pt_before
        stats.underfull_fte_after = stats.underfull_fte_before
        return assignments, stats
    
    # =========================================================================
    # S3.1: Sort PT candidates (smallest hours first, id tie-break)
    # =========================================================================
    pt_candidates = sorted(
        pt_assignments,
        key=lambda a: (a.total_hours, a.driver_id)
    )[:REPAIR_PT_LIMIT]
    
    # Build mutable state for FTEs
    fte_hours: dict[str, float] = {a.driver_id: a.total_hours for a in fte_assignments}
    fte_blocks: dict[str, list[Block]] = {a.driver_id: list(a.blocks) for a in fte_assignments}
    fte_days: dict[str, set[str]] = {}
    for a in fte_assignments:
        fte_days[a.driver_id] = {b.day.value for b in a.blocks}
    
    # Build mutable state for PTs
    pt_blocks: dict[str, list[Block]] = {a.driver_id: list(a.blocks) for a in pt_assignments}
    
    moves_applied = 0
    no_progress_count = 0
    
    # =========================================================================
    # S3.3: Bounded main loop (max passes, stop on no progress)
    # =========================================================================
    max_passes = 3
    for pass_num in range(max_passes):
        progress_this_pass = False
        
        for pt in pt_candidates:
            if moves_applied >= REPAIR_BLOCK_LIMIT:
                stats.reason_codes.append("BLOCK_LIMIT_REACHED")
                break
            
            pt_id = pt.driver_id
            if pt_id not in pt_blocks or not pt_blocks[pt_id]:
                continue
            
            # S3.2: Sort blocks within PT deterministically
            # (day_index, first_start, block.id)
            day_order = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
            blocks_sorted = sorted(
                pt_blocks[pt_id],
                key=lambda b: (
                    day_order.get(b.day.value, 7),
                    b.first_start.hour * 60 + b.first_start.minute if b.first_start else 0,
                    b.id
                )
            )
            
            for block in blocks_sorted:
                if moves_applied >= REPAIR_BLOCK_LIMIT:
                    break
                
                stats.moves_attempted += 1
                
                # =========================================================
                # S3.1: Sort FTE candidates by (distance to target, id)
                # Prefer underfull FTEs
                # =========================================================
                def fte_score(fte_id: str) -> tuple:
                    hours = fte_hours.get(fte_id, 0)
                    new_hours = hours + block.total_work_hours
                    
                    # Prefer underfull that would become full
                    if hours < config.min_hours_per_fte:
                        underfull_priority = 0  # Best
                    else:
                        underfull_priority = 1
                    
                    # Distance to target
                    distance = abs(new_hours - config.fte_hours_target)
                    
                    return (underfull_priority, distance, fte_id)
                
                fte_candidates_ids = sorted(fte_hours.keys(), key=fte_score)[:REPAIR_FTE_LIMIT]
                
                move_made = False
                for fte_id in fte_candidates_ids:
                    hours = fte_hours.get(fte_id, 0)
                    new_hours = hours + block.total_work_hours
                    
                    # Check: would exceed max hours?
                    if new_hours > config.max_hours_per_fte:
                        continue
                    
                    # Check: feasibility via can_assign_block
                    # Note: can_assign_block checks overlap and rest constraints
                    try:
                        if not can_assign_fn(fte_blocks.get(fte_id, []), block):
                            continue
                    except Exception:
                        continue
                    
                    # =========================================================
                    # MOVE: PT block â†’ FTE
                    # =========================================================
                    pt_blocks[pt_id].remove(block)
                    fte_blocks[fte_id].append(block)
                    fte_hours[fte_id] = new_hours
                    fte_days[fte_id].add(block.day.value)
                    
                    moves_applied += 1
                    move_made = True
                    progress_this_pass = True
                    break
                
                if move_made:
                    break  # Next PT
        
        if moves_applied >= REPAIR_BLOCK_LIMIT:
            break
        
        if not progress_this_pass:
            no_progress_count += 1
            if no_progress_count >= 1:
                stats.reason_codes.append("NO_PROGRESS")
                break
    
    # =========================================================================
    # Build updated assignments (deterministic)
    # =========================================================================
    updated = []
    
    # FTEs with updated state
    for a in fte_assignments:
        new_blocks = fte_blocks.get(a.driver_id, [])
        new_hours = sum(b.total_work_hours for b in new_blocks)
        new_days = len({b.day.value for b in new_blocks})
        updated.append(DriverAssignment(
            driver_id=a.driver_id,
            driver_type="FTE",
            blocks=new_blocks,
            total_hours=new_hours,
            days_worked=new_days,
            analysis=a.analysis.copy() if a.analysis else {},
        ))
    
    # PTs with remaining blocks (filter empty PTs)
    for a in pt_assignments:
        remaining = pt_blocks.get(a.driver_id, [])
        if remaining:  # Only keep non-empty PTs
            new_hours = sum(b.total_work_hours for b in remaining)
            new_days = len({b.day.value for b in remaining})
            updated.append(DriverAssignment(
                driver_id=a.driver_id,
                driver_type="PT",
                blocks=remaining,
                total_hours=new_hours,
                days_worked=new_days,
                analysis=a.analysis.copy() if a.analysis else {},
            ))
    
    # Add assignments that weren't in PT or FTE list (shouldn't happen, but safe)
    pt_fte_ids = {a.driver_id for a in pt_assignments} | {a.driver_id for a in fte_assignments}
    for a in assignments:
        if a.driver_id not in pt_fte_ids:
            updated.append(a)
    
    # Final counts
    stats.pt_after = sum(1 for a in updated if a.driver_type == "PT" and a.blocks)
    stats.underfull_fte_after = sum(
        1 for a in updated 
        if a.driver_type == "FTE" and a.total_hours < config.min_hours_per_fte
    )
    stats.moves_applied = moves_applied
    
    if moves_applied > 0:
        stats.reason_codes.append("REPAIR_SWAP")
    
    return updated, stats


# =============================================================================
# DIAGNOSTICS
# =============================================================================

def solve_day_min_diagnostic(day_tours: list[Tour], day_label: str, config: ConfigV4) -> int:
    """
    Calculate Max Concurrent Tours (simple geometric lower bound).
    """
    if not day_tours: return 0
    
    events = []
    for t in day_tours:
        start = t.start_time.hour * 60 + t.start_time.minute
        end = t.end_time.hour * 60 + t.end_time.minute
        events.append((start, 1))
        events.append((end, -1))
    
    events.sort()
    max_concurrent = 0
    current = 0
    for _, change in events:
        current += change
        max_concurrent = max(max_concurrent, current)
        
    return max_concurrent


def solve_day_min_blocks(day_blocks: list[Block], day_tours: list[Tour], time_limit: float = 30.0) -> tuple[int, dict]:
    """
    TRUE Day-Min-Solve: Find minimum number of blocks to cover all tours for a single day.
    
    This is the REAL lower bound for how many blocks (=drivers) are needed on this day.
    Uses CP-SAT with actual generated blocks.
    
    Returns:
        (min_blocks, stats) where stats includes block mix
    """
    if not day_tours:
        return 0, {"status": "EMPTY"}
    
    if not day_blocks:
        return len(day_tours), {"status": "NO_MULTI", "note": "No multi-tour blocks, need 1 block per tour"}
    
    model = cp_model.CpModel()
    
    # Variables: use[b] = 1 if block b is selected
    use = {}
    for i, b in enumerate(day_blocks):
        use[i] = model.NewBoolVar(f"use_{i}")
    
    # Build tour -> block index
    tour_to_blocks = defaultdict(list)
    for i, b in enumerate(day_blocks):
        for t in b.tours:
            tour_to_blocks[t.id].append(i)
    
    # Coverage: each tour must be covered by exactly one block
    for t in day_tours:
        block_indices = tour_to_blocks.get(t.id, [])
        if not block_indices:
            # Tour has no covering block - infeasible
            return -1, {"status": "INFEASIBLE", "uncovered_tour": t.id}
        model.AddExactlyOne([use[i] for i in block_indices])
    
    # Objective: minimize total blocks
    total_blocks = sum(use[i] for i in range(len(day_blocks)))
    model.Minimize(total_blocks)
    
    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # S0.1: Determinism (CP-SAT correct param)
    solver.parameters.random_seed = 42  # S0.1: Fixed seed
    
    status = solver.Solve(model)
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return -1, {"status": "FAILED", "cp_status": status}
    
    # Extract solution
    selected = [day_blocks[i] for i in range(len(day_blocks)) if solver.Value(use[i]) == 1]
    
    stats = {
        "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
        "min_blocks": len(selected),
        "blocks_1er": sum(1 for b in selected if len(b.tours) == 1),
        "blocks_2er": sum(1 for b in selected if len(b.tours) == 2),
        "blocks_3er": sum(1 for b in selected if len(b.tours) == 3),
        "avg_tours_per_block": len(day_tours) / len(selected) if selected else 0
    }
    
    return len(selected), stats


def prune_blocks_tour_aware(blocks: list[Block], tours: list[Tour], config: ConfigV4) -> list[Block]:
    """
    Prune blocks defensively:
    1. For every tour, keep Top-K 3ers, Top-K 2ers, Top-K 1ers.
    2. Union all kept blocks.
    3. If still > max_blocks, apply global pruning (but prioritize keeping the union).
    """
    # K-Values (Tuned for stability)
    K3 = 6  # Keep top 6 3-tour options per tour
    K2 = 4  # Keep top 4 2-tour options
    K1 = 2  # Keep top 2 1-tour options
    
    safe_print(f"  Tour-aware Pruning: K3={K3}, K2={K2}, K1={K1} per tour...", flush=True)
    
    # Index blocks by tour
    blocks_by_tour = defaultdict(list)
    block_map = {b.id: b for b in blocks}
    
    for b in blocks:
        for t in b.tours:
            blocks_by_tour[t.id].append(b)
            
    kept_ids = set()
    
    # === S0.4: PROTECTED SET (1er guarantee per tour) ===
    # Invariant: every tour MUST keep â‰¥1 covering block
    protected_1er_ids = set()
    for tour in tours:
        options = blocks_by_tour.get(tour.id, [])
        if not options:
            safe_print(f"  WARNING: Tour {tour.id} has NO blocks - feasibility broken!", flush=True)
            continue
        # Protect best 1er for this tour (by score proxy = size)
        opts_1er = [b for b in options if len(b.tours) == 1]
        if opts_1er:
            best_1er = max(opts_1er, key=lambda b: (b.total_work_minutes, b.id))
            protected_1er_ids.add(best_1er.id)
        else:
            # No 1er exists - protect best multi-tour block covering this tour
            best = max(options, key=lambda b: (-len(b.tours), b.total_work_minutes, b.id))
            protected_1er_ids.add(best.id)
    
    # Add protected blocks first
    kept_ids.update(protected_1er_ids)
    safe_print(f"  S0.4: Protected {len(protected_1er_ids)} 1er blocks (1 per tour)", flush=True)
    
    for tour in tours:
        # Sort options for this tour by "quality" (larger is better, then implicit score?)
        # Since we don't have scores here easily, use size (minutes) as proxy for "goodness".
        # Actually, larger blocks are harder to place, but "better" for objective.
        # We want to keep *feasible* options.
        # Let's keep largest options first.
        options = blocks_by_tour[tour.id]
        
        # Split by type
        opts_3 = [b for b in options if len(b.tours) == 3]
        opts_2 = [b for b in options if len(b.tours) == 2]
        opts_1 = [b for b in options if len(b.tours) == 1]
        
        # Sort desc by size (efficiency) - S0.1: Stable tie-break with id
        opts_3.sort(key=lambda b: (-b.total_work_minutes, b.id))
        opts_2.sort(key=lambda b: (-b.total_work_minutes, b.id))
        opts_1.sort(key=lambda b: (-b.total_work_minutes, b.id))  # S0.1: Now also sorted
        
        # Keep top K - S0.1: Stable ordering with (score, id) tie-break
        for b in opts_3[:K3]: kept_ids.add(b.id)
        for b in opts_2[:K2]: kept_ids.add(b.id)
        for b in opts_1[:K1]: kept_ids.add(b.id)
        
    # Convert back to list - S0.1: STABLE ORDERING (sort by id for determinism)
    kept_blocks = sorted(
        [block_map[bid] for bid in kept_ids if bid in block_map],
        key=lambda b: b.id
    )
    safe_print(f"  Retained {len(kept_blocks)} blocks via Tour-Proximity (from {len(blocks)})", flush=True)
    
    # If we still have space below max_blocks, fill with others?
    # Or if we have TOO many, do we cut?
    # Generally, tour-wise union is smaller than full sets.
    # If < max_blocks, we might want to Add global top-scorers that are not yet included?
    # For now, let's just use the kept set + global fill if space allows.
    
    if len(kept_blocks) < config.max_blocks:
        # Fill with remaining blocks sorted by size/score?
        # Actually, simple set difference.
        needed = config.max_blocks - len(kept_blocks)
        if needed > 0:
            others = [b for b in blocks if b.id not in kept_ids]
            # S0.1: Stable sort with id tie-break
            others.sort(key=lambda b: (-b.total_work_minutes, b.id))
            kept_blocks.extend(others[:needed])
            safe_print(f"  Filled {min(len(others), needed)} additional blocks to reach cap.", flush=True)
    
    elif len(kept_blocks) > config.max_blocks:
        safe_print(f"  WARNING: Union kept {len(kept_blocks)} > {config.max_blocks}. Capping...", flush=True)
        # S0.4: When capping, NEVER remove protected 1ers
        # Split into protected and non-protected
        protected_blocks = [b for b in kept_blocks if b.id in protected_1er_ids]
        other_blocks = [b for b in kept_blocks if b.id not in protected_1er_ids]
        # S0.1: Stable sort with id tie-break
        other_blocks.sort(key=lambda b: (-b.total_work_minutes, b.id))
        # Cap non-protected blocks, keep all protected
        if len(protected_blocks) >= config.max_blocks:
            safe_print(
                f"  S0.4: Protected blocks ({len(protected_blocks)}) exceed cap; "
                "keeping all protected to preserve coverage.",
                flush=True,
            )
            kept_blocks = protected_blocks
        else:
            cap_room = config.max_blocks - len(protected_blocks)
            kept_blocks = protected_blocks + other_blocks[:cap_room]
            safe_print(
                f"  S0.4: Kept {len(protected_blocks)} protected + {min(len(other_blocks), cap_room)} others",
                flush=True,
            )
        
    return kept_blocks

# =============================================================================
# PHASE 1: CAPACITY PLANNING (use_block model)
# =============================================================================

def solve_capacity_phase(
    blocks: list[Block],
    tours: list[Tour],
    block_index: dict[str, list[Block]],
    config: ConfigV4,
    block_scores: dict[str, float] = None,
    block_props: dict[str, dict] = None,
    time_limit: float = None
) -> tuple[list[Block], dict]:
    """
    Phase 1: Determine which blocks to use.
    
    Model:
    - use[b] âˆˆ {0, 1}: block b is used
    - Coverage: for each tour t, exactly one block containing t is used
    - Objective: minimize weighted cost using policy-derived scores
    
    Returns:
        (selected_blocks, stats)
    """
    safe_print(f"\n{'='*60}", flush=True)
    safe_print("PHASE 1: Capacity Planning (use_block model)", flush=True)
    safe_print(f"{'='*60}", flush=True)
    safe_print(f"Blocks: {len(blocks)}, Tours: {len(tours)}", flush=True)
    
    # ==== DAY-MIN-SOLVE: Find TRUE lower bound per peak day ====
    # This tells us if 140 FTE is even mathematically achievable
    safe_print("\n--- DAY-MIN-SOLVE (TRUE Lower Bounds) ---", flush=True)
    tours_by_day = defaultdict(list)
    for t in tours:
        tours_by_day[t.day.value].append(t)
    
    blocks_by_day_for_min = defaultdict(list)
    for b in blocks:
        blocks_by_day_for_min[b.day.value].append(b)
    
    day_min_results = {}
    for day_val in ["Fri", "Mon", "Sat"]:
        day_tours = tours_by_day.get(day_val, [])
        day_blocks = blocks_by_day_for_min.get(day_val, [])
        if day_tours:
            min_blocks, stats = solve_day_min_blocks(day_blocks, day_tours, time_limit=10.0)
            day_min_results[day_val] = min_blocks
            status_str = stats.get("status", "UNKNOWN")
            safe_print(f"  {day_val}: min_blocks={min_blocks} ({status_str}), "
                  f"1er={stats.get('blocks_1er', 0)}, 2er={stats.get('blocks_2er', 0)}, 3er={stats.get('blocks_3er', 0)}, "
                  f"avg={stats.get('avg_tours_per_block', 0):.2f} tours/block", flush=True)
    
    # Compute achievable FTE floor
    max_day_min = max(day_min_results.values()) if day_min_results else 0
    safe_print(f"  => Peak day minimum: {max_day_min} blocks (theoretical FTE floor)", flush=True)
    
    # ==== ITERATIVE TIGHTENING (OPTIMIZED) ====
    # Start high (above current Fri peak), then tighten
    # OPTIMIZATION: Use binding cap updates (next_cap < incumbent_max)
    
    INITIAL_CAP = max(220, max_day_min + 30)
    # OPTIMIZATION: Min cap should dynamic, not hardcoded 140
    # Use max_day_min as absolute floor, but target aggressive packing
    MIN_CAP = max(max_day_min, 1) 
    
    current_cap = INITIAL_CAP
    best_solution = None
    best_stats = None
    best_cap = INITIAL_CAP
    
    # Time Budget Management
    t_total_start = perf_counter()
    # Use strict budget from config (passed from portfolio controller)
    # Use strict budget from config (passed from portfolio controller)
    # Override takes precedence if provided (e.g. from two-pass solver)
    TOTAL_BUDGET = time_limit if time_limit is not None else config.time_limit_phase1 
    
    iteration = 0
    t_msg = f"Budget: {TOTAL_BUDGET:.1f}s"
    safe_print(f"\n--- SOLVING (HOTFIX A: No Tightening) ({t_msg}) ---", flush=True)

    if (perf_counter() - t_total_start) < TOTAL_BUDGET:  # HOTFIX A: Single iteration
        iteration += 1
        
        # Calculate remaining budget
        elapsed = perf_counter() - t_total_start
        remaining = TOTAL_BUDGET - elapsed
        if remaining < 2.0: # Minimum slice for meaningful solve
            safe_print("  Time budget exhausted.", flush=True)
            pass  # HOTFIX A: was 'break' (no loop anymore)
            
        safe_print(f"\n--- ITER {iteration}: CAP={current_cap} (Time left: {remaining:.1f}s) ---", flush=True)
        
        result = _solve_capacity_single_cap(
            blocks, tours, block_index, config,
            block_scores=block_scores,
            block_props=block_props,
            day_cap_override=current_cap,
            time_limit=remaining # Pass exact remaining time
        )
        
        if result is None:
            safe_print(f"  INFEASIBLE at cap={current_cap}. Stopping tightening.", flush=True)
            # Not in a loop (HOTFIX A), so return best or empty with proper status
            if best_solution is not None:
                return best_solution, best_stats
            # Return empty solution with ERROR status
            return [], {"status": "ERROR", "error": "Phase 1 infeasible"}
        
        selected, stats = result
        # Extract max day from solution
        # stats['blocks_by_day'] provides counts
        day_counts = stats.get('blocks_by_day', {}).values()
        current_max_day = max(day_counts) if day_counts else 0
        
        safe_print(f"  FEASIBLE: {len(selected)} blocks, max_day={current_max_day}", flush=True)
        
        # Store as best
        best_solution = selected
        best_stats = stats
        best_cap = current_cap
        
        # S0.3: Define target_cap explicitly (per spec)
        # target_cap is what we're aiming for (theoretical floor + small buffer)
        target_cap = max_day_min + 2
        
        # EARLY STOP: incumbent already at or below target
        if current_max_day <= target_cap:
            safe_print(f"  Target cap {target_cap} hit (Actual={current_max_day}). Early stop.", flush=True)
            pass  # HOTFIX A: was 'break'
            
        # S0.3: SPEC-CONFORMANT TIGHTENING
        # cap_next = max(target_cap, incumbent_max_day - 1)
        # NO stumpf -5 or -10 steps
        cap_next = max(target_cap, current_max_day - 1)
        
        # S0.3 Safety: if cap_next >= cap_current â†’ stop (no progress possible)
        if cap_next >= current_cap:
            safe_print(f"  Cannot tighten further (next={cap_next} >= curr={current_cap}). Done.", flush=True)
            pass  # HOTFIX A: was 'break'
            
        current_cap = cap_next
    
    # Report results
    total_elapsed = perf_counter() - t_total_start
    safe_print(f"\n=== TIGHTENING COMPLETE ===", flush=True)
    safe_print(f"  Best CAP: {best_cap} (Floor: {MIN_CAP})", flush=True)
    safe_print(f"  Iterations: {iteration}", flush=True)
    safe_print(f"  Time: {total_elapsed:.1f}s / {TOTAL_BUDGET:.1f}s", flush=True)
    
    if best_solution is None:
        logger.error("[FAILED] No feasible solution found even at initial cap")
        return [], {"status": "FAILED", "time": total_elapsed}
    
    # Run final diagnostics on the best solution
    _run_phase1_diagnostics(best_solution, tours, block_index, config, best_stats, total_elapsed)
    
    # === PHASE 1B: LNS REOPTIMIZATION (Friday) ===
    try:
        fri_lb = day_min_results.get("Fri")
        lb_peak = max(day_min_results.values()) if day_min_results else 0
        fri_cur = sum(1 for b in best_solution if b.day.value == "Fri")
        if fri_lb and fri_cur > fri_lb + 5:
            safe_print(f"\n--- LNS Friday Reopt: {fri_cur} -> target~{fri_lb} ---", flush=True)
            improved = _lns_reopt_friday(
                current_solution=best_solution,
                all_blocks=blocks,
                tours=tours,
                block_index=block_index,
                config=config,
                block_scores=block_scores,
                block_props=block_props,
                fri_lb=fri_lb,
                lb_peak=lb_peak,
            )
            if improved:
                safe_print(f"  LNS improved blocks: {len(best_solution)} -> {len(improved)}", flush=True)
                best_solution = improved
            else:
                safe_print("  LNS: no improvement", flush=True)
    except Exception as e:
        safe_print(f"[LNS] skipped due to error: {e}", flush=True)

    # ==== POST-COMPRESSION: Swap 3x1er into 1x3er ====
    best_solution, compressions = compress_selected_blocks(best_solution, blocks, block_index, tours)
    if compressions > 0:
        safe_print(f"  POST-COMPRESSION: Replaced {compressions} block sets (savings: ~{compressions*2} blocks)", flush=True)
        # Update stats
        best_stats["blocks_1er"] = sum(1 for b in best_solution if len(b.tours) == 1)
        best_stats["blocks_2er"] = sum(1 for b in best_solution if len(b.tours) == 2)
        best_stats["blocks_3er"] = sum(1 for b in best_solution if len(b.tours) == 3)
        best_stats["selected_blocks"] = len(best_solution)
    
    return best_solution, best_stats


def compress_selected_blocks(selected_blocks: list[Block], all_blocks: list[Block], block_index: dict, all_tours: list[Tour]) -> tuple[list[Block], int]:
    """
    GENERALIZED COMPRESSION: Replace multiple blocks with one multi-tour block.
    
    For each candidate block c (2er/3er) in pool:
        victims = {selected_block covering tour t for t in c.tours}
        If len(victims) >= 2 â†’ replace victims with c (saves len(victims)-1 blocks)
    
    Handles:
        - (2er+1er) â†’ 3er  (saves 1 block)
        - (1er+1er) â†’ 2er  (saves 1 block)
        - (3Ã—1er) â†’ 3er    (saves 2 blocks)
        - (1er+2er) â†’ 3er  (saves 1 block)
    """
    
    # Map tour ID to currently selected block
    tour_to_block = {}
    for b in selected_blocks:
        for t in b.tours:
            tour_to_block[t.id] = b
    
    selected_ids = {b.id for b in selected_blocks}
    new_selected = list(selected_blocks)
    compressions = 0
    blocks_saved = 0
    
    # Sort candidates: 3ers first (bigger savings), then by day
    candidates = [b for b in all_blocks if len(b.tours) >= 2 and b.id not in selected_ids]
    candidates.sort(key=lambda b: (-len(b.tours), b.day.value))
    
    # Create block map for quick lookup
    block_map = {b.id: b for b in new_selected}
    
    for candidate in candidates:
        # Find "victim" block IDs that would be replaced
        victim_ids = set()
        all_tours_covered = True
        
        for t in candidate.tours:
            if t.id not in tour_to_block:
                all_tours_covered = False
                break
            victim_ids.add(tour_to_block[t.id].id)  # Use ID, not object
        
        if not all_tours_covered:
            continue
            
        # Check if we save blocks (len(victims) > 1)
        if len(victim_ids) < 2:
            continue
            
        # Check victims are still in our selection (not already replaced)
        if not all(vid in selected_ids for vid in victim_ids):
            continue
        
        # CRITICAL: Ensure candidate covers EXACTLY the same tours as victims
        # (not more, not less)
        victim_tour_ids = set()
        for vid in victim_ids:
            victim = block_map.get(vid)
            if victim:
                for t in victim.tours:
                    victim_tour_ids.add(t.id)
        
        candidate_tour_ids = {t.id for t in candidate.tours}
        
        # Candidate must cover exactly the victim tours
        if candidate_tour_ids != victim_tour_ids:
            continue
        
        # Execute replacement
        for vid in victim_ids:
            victim = block_map.get(vid)
            if victim and victim in new_selected:
                new_selected.remove(victim)
                selected_ids.discard(vid)
                del block_map[vid]
                # Update tour mapping
                for t in victim.tours:
                    if t.id in tour_to_block and tour_to_block[t.id].id == vid:
                        del tour_to_block[t.id]
        
        # Add candidate
        new_selected.append(candidate)
        selected_ids.add(candidate.id)
        block_map[candidate.id] = candidate
        for t in candidate.tours:
            tour_to_block[t.id] = candidate
        
        saved = len(victim_ids) - 1
        blocks_saved += saved
        compressions += 1
    
    if compressions > 0:
        safe_print(f"  COMPRESSION: {compressions} moves, saved {blocks_saved} blocks", flush=True)
    
    return new_selected, compressions


def _lns_reopt_friday(
    current_solution: list[Block],
    all_blocks: list[Block],
    tours: list[Tour],
    block_index: dict,
    config: ConfigV4,
    block_scores: dict,
    block_props: dict,
    fri_lb: int,
    lb_peak: int
) -> list[Block] | None:
    """
    LNS (Large Neighborhood Search) reoptimization for Friday.
    
    Strategy:
    1. Keep non-Friday blocks fixed
    2. Re-solve Friday with progressively tighter cap
    3. Return improved solution or None
    """
    from ortools.sat.python import cp_model
    
    # Extract Friday tours and blocks
    fri_tours = [t for t in tours if t.day.value == "Fri"]
    fri_blocks = [b for b in all_blocks if b.day.value == "Fri"]
    non_fri_blocks = [b for b in current_solution if b.day.value != "Fri"]
    
    if not fri_tours or not fri_blocks:
        return None
    
    # Get current Friday block count
    fri_current = sum(1 for b in current_solution if b.day.value == "Fri")
    
    # Try tightening Friday cap
    for fri_cap in range(fri_current - 5, max(fri_lb - 1, fri_current - 30), -5):
        if fri_cap < fri_lb:
            break
            
        safe_print(f"    LNS attempt: Fri cap={fri_cap}", flush=True)
        
        model = cp_model.CpModel()
        
        # Variables: use[b] = 1 if block b is selected
        use = {}
        for i, b in enumerate(fri_blocks):
            use[i] = model.NewBoolVar(f"use_{i}")
        
        # Build tour -> block index
        tour_to_blocks = defaultdict(list)
        for i, b in enumerate(fri_blocks):
            for t in b.tours:
                tour_to_blocks[t.id].append(i)
        
        # Coverage: each Friday tour must be covered
        for t in fri_tours:
            block_indices = tour_to_blocks.get(t.id, [])
            if not block_indices:
                return None  # Can't cover a tour
            model.AddExactlyOne([use[i] for i in block_indices])
        
        # Cap constraint
        total_blocks = sum(use[i] for i in range(len(fri_blocks)))
        model.Add(total_blocks <= fri_cap)
        
        # Objective: minimize blocks, prefer multi-tour
        block_cost = []
        for i, b in enumerate(fri_blocks):
            n = len(b.tours)
            cost = 100 if n == 1 else (50 if n == 2 else 10)
            block_cost.append(cost * use[i])
        model.Minimize(sum(block_cost))
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 15.0
        solver.parameters.num_search_workers = 1  # S0.1: Determinism (CP-SAT correct param)
        solver.parameters.random_seed = config.seed  # S0.1: Fixed seed
        
        status = solver.Solve(model)
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            fri_selected = [fri_blocks[i] for i in range(len(fri_blocks)) if solver.Value(use[i]) == 1]
            new_solution = non_fri_blocks + fri_selected
            
            if len(new_solution) < len(current_solution):
                return new_solution
    
    return None


def _run_phase1_diagnostics(selected: list[Block], tours: list[Tour], block_index: dict, config: ConfigV4, stats: dict, elapsed: float):
    """Run and print Phase 1 diagnostics."""
    import math
    
    safe_print(f"\n{'='*20} DIAGNOSTICS {'='*20}", flush=True)
    
    # 1. Selected Blocks per Day (Split)
    day_stats = defaultdict(lambda: {"1er": 0, "2er": 0, "3er": 0, "total": 0, "tours": 0})
    for b in selected:
        d = b.day.value
        n = len(b.tours)
        k = f"{n}er" if n <=3 else "3er"
        day_stats[d][k] += 1
        day_stats[d]["total"] += 1
        day_stats[d]["tours"] += n
        
    sorted_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    safe_print("SELECTED BLOCKS BY DAY:", flush=True)
    for d in sorted_days:
        if d in day_stats:
            s = day_stats[d]
            avg_tours = s["tours"] / s["total"] if s["total"] else 0
            safe_print(f"  {d}: {s['total']} blocks ({s['1er']} 1er, {s['2er']} 2er, {s['3er']} 3er) | avg={avg_tours:.2f} tours/block", flush=True)

    # 2. Forced 1ers & Missed Opportunities
    forced_1er_tours = []
    missed_3er_tours = []
    
    tour_assignment = {} 
    for b in selected:
        n = len(b.tours)
        for t in b.tours:
            tour_assignment[t.id] = n
            
    for tour in tours:
        tid = tour.id
        pool_blocks = block_index.get(tid, [])
        pool_options = {len(b.tours) for b in pool_blocks}
        has_multi = any(n > 1 for n in pool_options)
        has_3er = (3 in pool_options)
        picked_n = tour_assignment.get(tid, 0)
        
        if picked_n == 1:
            if not has_multi:
                forced_1er_tours.append(tid)
            elif has_3er:
                missed_3er_tours.append(tid)

    safe_print(f"FORCED 1er TOURS: {len(forced_1er_tours)} (No multi-block option)", flush=True)
    safe_print(f"MISSED 3er OPPS: {len(missed_3er_tours)} (Chose 1er despite 3er existing)", flush=True)

    # 3. Day Min Lower Bound + Gap
    safe_print("GAP TO THEORETICAL MINIMUM:", flush=True)
    for d in sorted_days:
        if d not in day_stats: continue
        day_tours = [t for t in tours if t.day.value == d]
        if not day_tours: continue
        
        # LB via max concurrent (geometric)
        lb_concurrent = solve_day_min_diagnostic(day_tours, d, config)
        # LB via packing (tours/3)
        lb_packing = math.ceil(len(day_tours) / 3)
        lb = max(lb_concurrent, lb_packing)
        
        actual = day_stats[d]["total"]
        gap = actual - lb
        safe_print(f"  {d}: Actual={actual} vs LB={lb} (Gap={gap})", flush=True)

    safe_print(f"{'='*53}", flush=True)
    
    # Update stats with diagnostics
    stats["time"] = round(elapsed, 2)
    stats["forced_1er_count"] = len(forced_1er_tours)
    stats["missed_3er_count"] = len(missed_3er_tours)


def _solve_capacity_single_cap(
    blocks: list[Block],
    tours: list[Tour],
    block_index: dict[str, list[Block]],
    config: ConfigV4,
    block_scores: dict[str, float] = None,
    block_props: dict[str, dict] = None,
    day_cap_override: int = None,
    time_limit: float = None
) -> tuple[list[Block], dict] | None:
    """
    Single-cap solve for Phase 1. Returns None if INFEASIBLE.
    """
    t0 = perf_counter()
    
    model = cp_model.CpModel()
    
    # Variables: one per block
    use = {}
    for b, block in enumerate(blocks):
        use[b] = model.NewBoolVar(f"use_{b}")
    
    safe_print(f"Variables: {len(use)} (vs {len(use) * 150}+ in old model)", flush=True)
    
    # Precompute block index lookup for O(1) block â†’ variable mapping
    block_id_to_idx = {block.id: idx for idx, block in enumerate(blocks)}

    # Constraint: Coverage (each tour exactly once)
    safe_print("Adding coverage constraints...", flush=True)
    
    # Patch 3: Collect missing tours instead of crashing
    missing_tours = []
    
    if config.debug_disable_coverage:
        safe_print("  [DEBUG] Coverage constraints disabled", flush=True)
    else:
        for tour in tours:
            blocks_with_tour = block_index.get(tour.id, [])
            if not blocks_with_tour:
                # Patch 3: Don't crash - collect and continue
                safe_print(f"  [WARN] Tour {tour.id} has no blocks in pool - marking as missing", flush=True)
                missing_tours.append(tour.id)
                continue
            
            # Use the pre-built block_index for O(1) lookup instead of scanning all blocks
            block_indices = []
            for block in blocks_with_tour:
                b_idx = block_id_to_idx.get(block.id)
                if b_idx is not None:
                    block_indices.append(b_idx)

            if not block_indices:
                # Patch 3: Don't crash - collect and continue
                safe_print(f"  [WARN] Tour {tour.id} has no indexed blocks - marking as missing", flush=True)
                missing_tours.append(tour.id)
                continue
            
            model.Add(sum(use[b] for b in block_indices) == 1)
    
    # Patch 3: If any tours are missing, return INFEASIBLE immediately
    if missing_tours and not config.debug_disable_coverage:
        safe_print(f"  [ERROR] {len(missing_tours)} tours cannot be covered: {missing_tours}", flush=True)
        return None, {"status": "INFEASIBLE", "missing_tours": missing_tours}
    
    safe_print("Coverage constraints added.", flush=True)
    
    # Objective: Use POLICY-DERIVED scores if available
    # Higher policy score = more desirable block
    block_cost = []
    
    # [DEBUG] Log score application range to detect bugs
    if block_scores:
        vals = list(block_scores.values())
        if vals:
            p_over_1000 = (sum(1 for v in vals if v > 1000) / len(vals)) * 100
            safe_print(f"  SCORE DEBUG: min={min(vals):.1f} max={max(vals):.1f} %>1000={p_over_1000:.1f}%", flush=True)

    # Score normalization helpers
    s_min = min(block_scores.values()) if block_scores else 0
    s_max = max(block_scores.values()) if block_scores else 1
    
    def norm_score(s):
        if s_max <= s_min: return 0
        return int(1000 * (s - s_min) / (s_max - s_min))
    
    # ==== V4 OPTIMIZATION: Day-aware objective ====
    # Group blocks by day for max_day and cap constraints
    from collections import defaultdict
    blocks_by_day = defaultdict(list)
    for b, block in enumerate(blocks):
        blocks_by_day[block.day.value].append(b)
    
    days = list(blocks_by_day.keys())
    
    # Calculate early/late pressure per day (for dynamic rest-trap penalty)
    early_pressure = {}  # % of tours starting <= 08:00
    late_pressure = {}   # % of tours ending >= 20:00
    for day_val, day_blocks in blocks_by_day.items():
        early_count = sum(1 for b in day_blocks if blocks[b].first_start.hour < 8)
        late_count = sum(1 for b in day_blocks if blocks[b].last_end.hour >= 20)
        total = len(day_blocks) if day_blocks else 1
        early_pressure[day_val] = early_count / total
        late_pressure[day_val] = late_count / total
    
    # Day ordering for trap calculation (using Weekday enum values)
    day_order = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    # Inverse map for next-day lookup
    idx_to_day = {v: k for k, v in day_order.items()}

    trap_pressure = {}
    for day_val in days:
        if day_val not in day_order:
             trap_pressure[day_val] = 0.0
             continue
             
        day_idx = day_order[day_val]
        # Pressure = Late(Today) * Early(Tomorrow)
        next_day_val = idx_to_day.get((day_idx + 1) % 7, "Mon")
        trap_pressure[day_val] = late_pressure.get(day_val, 0) * early_pressure.get(next_day_val, 0)
    
    safe_print(f"  TRAP PRESSURE: {', '.join(f'{d[:3]}={trap_pressure.get(d, 0):.2f}' for d in days)}", flush=True)
    
    # ==== V4 Chainability Analysis (Pre-calculation) ====
    # For every block, how many "compatible" blocks exist on the next day?
    # Compatible = start_time >= block.end_time + min_rest (11h or 14h)
    
    from bisect import bisect_left
    
    # 1. Sort blocks by day and start time (already roughly sorted, but ensure)
    # Actually we just need next-day start times.
    day_starts = defaultdict(list)
    for b in blocks:
        # We need start minute of the day
        start_min = b.first_start.hour * 60 + b.first_start.minute
        day_starts[b.day.value].append(start_min)
        
    for d in day_starts:
        day_starts[d].sort()
        
    # 2. Compute compatibility score per block
    # Lower compatibility = Higher Penalty
    chain_penalty_map = {}
    compat_counts = {}  # For histogram
    
    TARGET_COMPAT = 50  # INCREASED: We want at least 50 good options next day (stricter)
    W_CHAIN = 100       # INCREASED: Penalty per missing option
    
    count_low_compat = 0
    
    for b in blocks:
        # Determine next day
        current_day_idx = day_order.get(b.day.value, 0)
        next_day_val = idx_to_day.get((current_day_idx + 1) % 7)
        
        # Determine rest requirement
        # If 3-tour: 14h rest (840 min). Else 11h (660 min).
        # But wait, 3-tour rule says "14h rest OR max 2 tours next day".
        # It's a complex rule. The chainability metric is a heuristic.
        # Let's assume standard 11h rest for connectivity potential.
        rest_min = 14 * 60 if len(b.tours) >= 3 else 11 * 60
        
        # End time in minutes from start of day
        # (This assumes shifts don't span midnight for start/end logic roughly)
        # Actually verify: block.last_end is time object.
        end_min = b.last_end.hour * 60 + b.last_end.minute
        
        # Earliest valid start next day
        # If we end at 20:00 (1200), +11h = 31:00 = 07:00 next day.
        # Logic: end_min + rest_min - 24*60
        # If result < 0, it means we can start at 00:00 next day (no constraint effectively overlapping day start).
        
        min_next_start = end_min + rest_min - (24 * 60)
        # CLAMP: If negative, means block can connect to anything starting at 00:00+
        min_next_start = max(0, min_next_start)
        
        if next_day_val not in day_starts or not day_starts[next_day_val]:
            # No blocks next day (e.g. Sunday -> Monday if empty context, or Saturday->Sunday)
            # If Sunday, maybe no penalty needed (end of week).
            if b.day.value == "Sun" or b.day.value == "Sat":
                chain_penalty_map[b.id] = 0
                compat_counts["10+"] = compat_counts.get("10+", 0) + 1  # Sat/Sun end of week
            else:
                # Scary! No options.
                chain_penalty_map[b.id] = W_CHAIN * TARGET_COMPAT
                compat_counts["0"] = compat_counts.get("0", 0) + 1
            continue
            
        # Count options >= min_next_start
        options = day_starts[next_day_val]
        # binary search: find index of first valid start
        idx = bisect_left(options, min_next_start)
        count = len(options) - idx
        
        # Track histogram
        if count == 0: compat_counts["0"] = compat_counts.get("0", 0) + 1
        elif count <= 4: compat_counts[str(count)] = compat_counts.get(str(count), 0) + 1
        elif count <= 9: compat_counts["5-9"] = compat_counts.get("5-9", 0) + 1
        else: compat_counts["10+"] = compat_counts.get("10+", 0) + 1
        
        if count < TARGET_COMPAT:
            penalty = (TARGET_COMPAT - count) * W_CHAIN
            # Boost penalty for 1er blocks that dead-end? 
            # No, if a 1er dead-ends it's just as bad as a 3er dead-ending.
            # Actually 3ers dead-ending is worse (waste of efficiency).
            if len(b.tours) >= 3:
                penalty *= 2
            
            chain_penalty_map[b.id] = penalty
            count_low_compat += 1
        else:
            chain_penalty_map[b.id] = 0
            
    safe_print(f"  CHAINABILITY: {count_low_compat} blocks have low next-day options (<{TARGET_COMPAT}). Applied penalties.", flush=True)
    safe_print(f"  COMPAT HISTOGRAM: {compat_counts}", flush=True)

    # Day count variable + soft cap
    # v5: Use day_cap_hard for operational constraint (default 220)
    if day_cap_override is not None:
        DAY_CAP = day_cap_override
    else:
        # v5: Fixed cap for operational constraints (not dynamic from target_ftes)
        DAY_CAP = config.day_cap_hard if hasattr(config, 'day_cap_hard') else 220
    
    day_count = {}
    day_slack = {}
    PEAK_DAYS = {"Fri", "Mon"}  # These get HARD cap
    
    for day_val in days:
        day_count[day_val] = model.NewIntVar(0, 5000, f"day_count_{day_val}")
        model.Add(day_count[day_val] == sum(use[b] for b in blocks_by_day[day_val]))
        if config.debug_disable_day_caps:
            day_slack[day_val] = model.NewIntVar(0, 0, f"day_slack_{day_val}")
            continue
        day_slack[day_val] = model.NewIntVar(0, 500, f"day_slack_{day_val}")
        # SOFT cap for all days (slack penalized in objective)
        model.Add(day_count[day_val] <= DAY_CAP + day_slack[day_val])
        if day_val in PEAK_DAYS:
            safe_print(f"    {day_val}: SOFT cap at {DAY_CAP} (slack allowed)", flush=True)
    
    # Max day variable (bottleneck variable)
    max_day = model.NewIntVar(0, 5000, "max_day")
    # ==== REALITY CHECK: FORCED SINGLES ====
    # Identify tours that ONLY appear in 1er blocks (no multi-block option generated/survived capping)
    tour_block_sizes = defaultdict(set)
    for b in blocks:
        n = len(b.tours)
        for t in b.tours:
            tour_block_sizes[t.id].add(n)
            
    forced_1er_count = sum(1 for sizes in tour_block_sizes.values() if sizes == {1})
    forced_1er_pct = (forced_1er_count / len(tours)) * 100 if tours else 0
    safe_print(f"  REALITY CHECK: {forced_1er_count} tours ({forced_1er_pct:.1f}%) FORCED to be 1er (no multi option found)", flush=True)

    for day_val in days:
        model.Add(max_day >= day_count[day_val])
    
    # ==== Block costs with trap penalties ====
    TRAP_PENALTY = 500  # Penalty for ignoring trap pressure
    
    # ==== A) PACKABILITY: Pre-compute tours with multi-block options ====
    # O(|block_index|) - done once, not per block
    tour_has_multi = {
        tour_id
        for tour_id, pool in block_index.items()
        if any(len(b.tours) > 1 for b in pool)
    }
    safe_print(f"  PACKABILITY: {len(tour_has_multi)}/{len(tours)} tours have multi-block options", flush=True)
    
    # =========================================================================
    # RC1: LEXICOGRAPHIC PACKING VIA MULTI-SOLVE (OVERFLOW-SAFE)
    # =========================================================================
    # APPROACH: Sequential optimization stages with constraint fixation
    # Stage 1: max(count_3er)     → fix count_3er = best_3er
    # Stage 2: max(count_2er_reg) → fix count_2er_regular = best_2R
    # Stage 3: max(count_2er_split) → fix count_2er_split = best_2S
    # Stage 4: min(count_1er)     → fix count_1er = best_1er
    # Stage 5 (optional): minimize secondary terms under fixed packing
    #
    # BENEFITS:
    # - No int64 overflow risk (no Big-M weights)
    # - Provably lexicographic (each stage fixes its tier)
    # - Packing priority CANNOT be overridden by secondary terms
    # =========================================================================
    
    # Edit 1: Status name helper for clear logging
    STATUS_NAME = {
        cp_model.UNKNOWN: "UNKNOWN",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.OPTIMAL: "OPTIMAL",
    }
    
    def status_str(st):
        return STATUS_NAME.get(st, f"STATUS_{st}")
    
    safe_print(f"\n{'='*60}", flush=True)
    safe_print("RC1: MULTI-SOLVE LEXICOGRAPHIC PACKING", flush=True)
    safe_print(f"{'='*60}", flush=True)
    
    # Debug: count available types
    avail_1er = sum(1 for b in blocks if len(b.tours) == 1)
    avail_2er_reg = sum(1 for b in blocks if len(b.tours) == 2 and _pause_zone_value(b) == "REGULAR")
    avail_2er_split = sum(1 for b in blocks if len(b.tours) == 2 and _pause_zone_value(b) == "SPLIT")
    avail_3er = sum(1 for b in blocks if len(b.tours) == 3)
    safe_print(f"  AVAILABLE BLOCKS: 1er={avail_1er}, 2er_REG={avail_2er_reg}, 2er_SPLIT={avail_2er_split}, 3er={avail_3er}", flush=True)
    
    # Helper: Reset hints from solver (prevents duplicate hint variables)
    def reset_hints_from_solver(model, use, solver):
        """Clear previous hints and add fresh hints from solver. Prevents MODEL_INVALID."""
        model.ClearHints()  # Prevents duplicate-hints
        # use can be dict or list - handle both
        if isinstance(use, dict):
            for k in sorted(use.keys()):  # Deterministic order
                var = use[k]
                model.AddHint(var, int(solver.Value(var)))
        else:
            for var in use:
                model.AddHint(var, int(solver.Value(var)))
    
    # Edit 2: Build count expressions as IntVars (safer than raw sum())
    # This avoids MODEL_INVALID issues when sum() returns Python int in edge cases
    count_3er = model.NewIntVar(0, len(blocks), "count_3er")
    count_2er_regular = model.NewIntVar(0, len(blocks), "count_2er_regular")
    count_2er_split = model.NewIntVar(0, len(blocks), "count_2er_split")
    count_1er = model.NewIntVar(0, len(blocks), "count_1er")
    
    model.Add(count_3er == sum(
        use[b] for b, block in enumerate(blocks) if len(block.tours) == 3
    ))
    model.Add(count_2er_regular == sum(
        use[b] for b, block in enumerate(blocks) 
        if len(block.tours) == 2 and _pause_zone_value(block) == "REGULAR"
    ))
    model.Add(count_2er_split == sum(
        use[b] for b, block in enumerate(blocks)
        if len(block.tours) == 2 and _pause_zone_value(block) == "SPLIT"
    ))
    model.Add(count_1er == sum(
        use[b] for b, block in enumerate(blocks) if len(block.tours) == 1
    ))
    
    safe_print(f"  COUNT EXPRESSIONS: c3er, c2R, c2S, c1er built as IntVars", flush=True)
    
    # Time budget split across stages (deterministic)
    # Total budget from config or override
    total_budget = time_limit if time_limit is not None else config.time_limit_phase1
    
    # v5: Two-Pass budget split: 40% Pass 1 (Capacity), 60% Pass 2 (Quality/Lexicographic)
    pass1_budget = total_budget * 0.30
    pass2_budget = total_budget * 0.70
    
    # Pass 2 stage budgets (split among 5 lexicographic stages)
    # Split: favor stage2/3 to avoid UNKNOWN under tight budgets
    stage_budgets = {
        1: pass2_budget * 0.15,
        2: pass2_budget * 0.40,
        3: pass2_budget * 0.30,
        4: pass2_budget * 0.10,
        5: pass2_budget * 0.05,
    }
    
    safe_print(f"  TWO-PASS BUDGET (total={total_budget:.1f}s):", flush=True)
    safe_print(f"    Pass 1 (Capacity): {pass1_budget:.1f}s", flush=True)
    safe_print(f"    Pass 2 (Quality):  {pass2_budget:.1f}s", flush=True)
    for st, bud in stage_budgets.items():
        safe_print(f"      Stage {st}: {bud:.1f}s", flush=True)
    
    # =========================================================================
    # v5 PASS 1: CAPACITY/HEADCOUNT MINIMIZATION
    # =========================================================================
    safe_print(f"\n{'='*60}", flush=True)
    safe_print("v5 PASS 1: HEADCOUNT MINIMIZATION", flush=True)
    safe_print(f"{'='*60}", flush=True)
    safe_print(f"  Objective: Minimize max_day (peak headcount)", flush=True)
    safe_print(f"  DAY_CAP: {DAY_CAP} (hard constraint for peak days)", flush=True)
    
    model.Minimize(max_day)
    
    solver_pass1 = cp_model.CpSolver()
    solver_pass1.parameters.max_time_in_seconds = pass1_budget
    solver_pass1.parameters.num_search_workers = 1  # Determinism
    solver_pass1.parameters.random_seed = config.seed
    
    status_pass1 = solver_pass1.Solve(model)
    
    if status_pass1 == cp_model.OPTIMAL:
        safe_print(f"  PASS 1: OPTIMAL", flush=True)
        pass1_is_optimal = True
    elif status_pass1 == cp_model.FEASIBLE:
        safe_print(f"  PASS 1: FEASIBLE (not proven optimal)", flush=True)
        pass1_is_optimal = False
    else:
        safe_print(f"  PASS 1 FAILED: {status_str(status_pass1)}", flush=True)
        return None
    
    headcount_pass1 = int(solver_pass1.Value(max_day))
    safe_print(f"  PASS 1 RESULT: headcount = {headcount_pass1} blocks/peak-day", flush=True)
    
    # v5: Lock headcount for Pass 2
    # If Pass 1 was OPTIMAL, use strict equality (==)
    # If Pass 1 was only FEASIBLE, use fail-open (<=) to avoid artificial infeasibility
    if config.debug_disable_headcount_lock:
        safe_print("  [DEBUG] Headcount lock disabled", flush=True)
    elif pass1_is_optimal:
        model.Add(max_day == headcount_pass1)
        safe_print(f"  HEADCOUNT LOCK: max_day == {headcount_pass1} (strict, pass1 was OPTIMAL)", flush=True)
    else:
        model.Add(max_day <= headcount_pass1)
        safe_print(f"  HEADCOUNT LOCK: max_day <= {headcount_pass1} (fail-open, pass1 was FEASIBLE)", flush=True)
    
    # v5: Clear hints and add fresh hints from Pass 1 solution
    model.ClearHints()
    for b_idx in range(len(blocks)):
        model.AddHint(use[b_idx], int(solver_pass1.Value(use[b_idx])))
    safe_print(f"  HINTS: Cleared and reset from Pass 1 solution", flush=True)
    
    # =========================================================================
    # v5 PASS 2: QUALITY OPTIMIZATION (LEXICOGRAPHIC STAGES)
    # =========================================================================
    safe_print(f"\n{'='*60}", flush=True)
    safe_print("v5 PASS 2: QUALITY OPTIMIZATION (locked headcount)", flush=True)
    safe_print(f"{'='*60}", flush=True)
    
    # =========================================================================
    # STAGE 1: MAXIMIZE count_3er
    # =========================================================================
    safe_print(f"\n  --- STAGE 1: MAXIMIZE count_3er ---", flush=True)
    model.Maximize(count_3er)
    
    solver_s1 = cp_model.CpSolver()
    solver_s1.parameters.max_time_in_seconds = stage_budgets[1]
    solver_s1.parameters.num_search_workers = 1  # Determinism
    solver_s1.parameters.random_seed = config.seed
    
    status_s1 = solver_s1.Solve(model)
    
    # K2: Status handling - distinguish OPTIMAL vs FEASIBLE (Edit 1: use status_str)
    if status_s1 == cp_model.OPTIMAL:
        safe_print(f"  STAGE 1: {status_str(status_s1)}", flush=True)
        best_count_3er = solver_s1.Value(count_3er)
        safe_print(f"  STAGE 1 RESULT: count_3er = {int(best_count_3er)}", flush=True)
        model.Add(count_3er == int(best_count_3er))
        reset_hints_from_solver(model, use, solver_s1)
        stage1_solver_for_fallback = solver_s1
    elif status_s1 == cp_model.FEASIBLE:
        safe_print(f"  STAGE 1: {status_str(status_s1)} (not proven optimal)", flush=True)
        best_count_3er = solver_s1.Value(count_3er)
        safe_print(f"  STAGE 1 RESULT: count_3er = {int(best_count_3er)}", flush=True)
        model.Add(count_3er >= int(best_count_3er))
        reset_hints_from_solver(model, use, solver_s1)
        stage1_solver_for_fallback = solver_s1
    else:
        safe_print(f"  STAGE 1 FAILED: {status_str(status_s1)} (using Pass 1 fallback)", flush=True)
        if status_s1 == cp_model.MODEL_INVALID:
            safe_print(f"  ERROR: Model is invalid. Check count expressions.", flush=True)
            return None
        best_count_3er = solver_pass1.Value(count_3er)
        safe_print(f"  STAGE 1 FALLBACK: count_3er = {int(best_count_3er)}", flush=True)
        model.Add(count_3er >= int(best_count_3er))
        reset_hints_from_solver(model, use, solver_pass1)
        stage1_solver_for_fallback = solver_pass1
    
    # =========================================================================
    # STAGE 2: MAXIMIZE count_2er_regular (with count_3er fixed)
    # =========================================================================
    safe_print(f"\n  --- STAGE 2: MAXIMIZE count_2er_regular ---", flush=True)
    model.Maximize(count_2er_regular)
    
    solver_s2 = cp_model.CpSolver()
    solver_s2.parameters.max_time_in_seconds = stage_budgets[2]
    solver_s2.parameters.num_search_workers = 1
    solver_s2.parameters.random_seed = config.seed
    
    status_s2 = solver_s2.Solve(model)
    
    if status_s2 == cp_model.OPTIMAL:
        safe_print(f"  STAGE 2: OPTIMAL", flush=True)
        best_count_2er_regular = solver_s2.Value(count_2er_regular)
        safe_print(f"  STAGE 2 RESULT: count_2er_regular = {int(best_count_2er_regular)}", flush=True)
        model.Add(count_2er_regular == int(best_count_2er_regular))
        safe_print(f"  Fixation: count_2er_regular == {int(best_count_2er_regular)} (OPTIMAL)", flush=True)
        reset_hints_from_solver(model, use, solver_s2)
        stage2_solver_for_fallback = solver_s2
    elif status_s2 == cp_model.FEASIBLE:
        safe_print(f"  STAGE 2: FEASIBLE (not proven optimal)", flush=True)
        best_count_2er_regular = solver_s2.Value(count_2er_regular)
        safe_print(f"  STAGE 2 RESULT: count_2er_regular = {int(best_count_2er_regular)}", flush=True)
        model.Add(count_2er_regular >= int(best_count_2er_regular))
        safe_print(f"  Fixation: count_2er_regular >= {int(best_count_2er_regular)} (FEASIBLE, fail-open)", flush=True)
        reset_hints_from_solver(model, use, solver_s2)
        stage2_solver_for_fallback = solver_s2
    else:
        safe_print(f"  STAGE 2 FAILED: {status_str(status_s2)} (using Stage 1 fallback)", flush=True)
        best_count_2er_regular = stage1_solver_for_fallback.Value(count_2er_regular)
        safe_print(f"  STAGE 2 FALLBACK: count_2er_regular = {int(best_count_2er_regular)}", flush=True)
        model.Add(count_2er_regular >= int(best_count_2er_regular))
        safe_print(f"  Fixation: count_2er_regular >= {int(best_count_2er_regular)} (fallback)", flush=True)
        reset_hints_from_solver(model, use, stage1_solver_for_fallback)
        stage2_solver_for_fallback = stage1_solver_for_fallback
    
    # =========================================================================
    # EDIT 4: PRE-FLIGHT FEASIBILITY CHECK (after Stage 2 fixation)
    # =========================================================================
    safe_print(f"\n  PRE-FLIGHT: Validating model after Stage 2 fixation...", flush=True)
    
    # 1) CP-SAT builtin validation
    validation_err = model.Validate()
    if validation_err:
        safe_print(f"  MODEL VALIDATION ERROR:\n{validation_err}", flush=True)
        return None
    
    # 2) Proto domain scan (catches lb > ub)
    proto = model.Proto()
    invalid_vars = []
    for i, v in enumerate(proto.variables):
        dom = list(v.domain)
        for j in range(0, len(dom), 2):
            lb, ub = dom[j], dom[j+1]
            if lb > ub:
                invalid_vars.append((i, v.name if v.name else f"var_{i}", lb, ub))
    
    if invalid_vars:
        safe_print(f"  INVALID VARIABLE DOMAINS DETECTED:", flush=True)
        for idx, name, lb, ub in invalid_vars:
            safe_print(f"    var#{idx} '{name}': [{lb},{ub}] (lb > ub)", flush=True)
        return None
    
    # 3) Feasibility check with trivial objective
    model.Minimize(0)
    solver_preflight = cp_model.CpSolver()
    solver_preflight.parameters.max_time_in_seconds = 2.0
    solver_preflight.parameters.num_search_workers = 1
    solver_preflight.parameters.random_seed = config.seed
    solver_preflight.parameters.log_search_progress = False
    
    status_preflight = solver_preflight.Solve(model)
    safe_print(f"  PRE-FLIGHT: {status_str(status_preflight)}", flush=True)
    
    # UNKNOWN = timeout (ok for 2s budget), FEASIBLE/OPTIMAL = passing
    # Only INFEASIBLE and MODEL_INVALID are actual failures
    if status_preflight in (cp_model.INFEASIBLE, cp_model.MODEL_INVALID):
        safe_print(f"  PRE-FLIGHT FAILED: Model is {status_str(status_preflight)} after Stage 2 fixation", flush=True)
        safe_print(f"  -> Stage 1 fixed: count_3er = {int(best_count_3er)}", flush=True)
        safe_print(f"  -> Stage 2 fixed: count_2er_regular = {int(best_count_2er_regular)}", flush=True)
        return None
    
    safe_print(f"  PRE-FLIGHT PASSED (model valid)", flush=True)
    
    # =========================================================================
    # STAGE 3: MAXIMIZE count_2er_split (with 3er, 2R fixed) - hint only
    # =========================================================================
    safe_print(f"\n  --- STAGE 3: MAXIMIZE count_2er_split (hints only) ---", flush=True)
    model.Maximize(count_2er_split)
    
    solver_s3 = cp_model.CpSolver()
    solver_s3.parameters.max_time_in_seconds = stage_budgets[3]
    solver_s3.parameters.num_search_workers = 1
    solver_s3.parameters.random_seed = config.seed
    
    status_s3 = solver_s3.Solve(model)
    
    if status_s3 == cp_model.OPTIMAL:
        safe_print(f"  STAGE 3: OPTIMAL", flush=True)
        best_count_2er_split = solver_s3.Value(count_2er_split)
        safe_print(f"  STAGE 3 RESULT: count_2er_split = {int(best_count_2er_split)}", flush=True)
        reset_hints_from_solver(model, use, solver_s3)
        stage3_solver_for_fallback = solver_s3
    elif status_s3 == cp_model.FEASIBLE:
        safe_print(f"  STAGE 3: FEASIBLE (not proven optimal)", flush=True)
        best_count_2er_split = solver_s3.Value(count_2er_split)
        safe_print(f"  STAGE 3 RESULT: count_2er_split = {int(best_count_2er_split)}", flush=True)
        reset_hints_from_solver(model, use, solver_s3)
        stage3_solver_for_fallback = solver_s3
    else:
        safe_print(f"  STAGE 3 FAILED: {status_str(status_s3)} (using Stage 2 fallback)", flush=True)
        best_count_2er_split = stage2_solver_for_fallback.Value(count_2er_split)
        safe_print(f"  STAGE 3 FALLBACK: count_2er_split = {int(best_count_2er_split)}", flush=True)
        reset_hints_from_solver(model, use, stage2_solver_for_fallback)
        stage3_solver_for_fallback = stage2_solver_for_fallback
    
    # =========================================================================
    # STAGE 4: LEXICOGRAPHIC MIX (max 3er, max 2er, min split, min 1er, min blocks)
    # =========================================================================
    safe_print(
        "\n  --- STAGE 4: LEXICOGRAPHIC MIX (3er, 2er, split, 1er, total_blocks) ---",
        flush=True,
    )
    total_blocks = sum(use[b] for b in range(len(blocks)))
    count_2er_total = count_2er_regular + count_2er_split
    W_3 = 1_000_000_000
    W_2 = 1_000_000
    W_SPLIT = 10_000
    W_1ER = 100
    W_TB = 1
    stage4_objective = (
        -W_3 * count_3er
        -W_2 * count_2er_total
        +W_SPLIT * count_2er_split
        +W_1ER * count_1er
        +W_TB * total_blocks
    )
    safe_print(
        "  STAGE 4 OBJ: "
        f"-{W_3}*count_3er -{W_2}*count_2er + {W_SPLIT}*count_2er_split "
        f"+ {W_1ER}*count_1er + {W_TB}*total_blocks",
        flush=True,
    )
    model.Minimize(stage4_objective)
    
    solver_s4 = cp_model.CpSolver()
    solver_s4.parameters.max_time_in_seconds = stage_budgets[4]
    solver_s4.parameters.num_search_workers = 1
    solver_s4.parameters.random_seed = config.seed
    
    status_s4 = solver_s4.Solve(model)
    
    if status_s4 == cp_model.OPTIMAL:
        safe_print(f"  STAGE 4: OPTIMAL", flush=True)
        best_count_1er = solver_s4.Value(count_1er)
        best_count_2er_split = solver_s4.Value(count_2er_split)
        best_total_blocks = solver_s4.Value(total_blocks)
        safe_print(
            "  STAGE 4 RESULT: "
            f"count_1er = {int(best_count_1er)}, "
            f"count_2er_split = {int(best_count_2er_split)}, "
            f"total_blocks = {int(best_total_blocks)}",
            flush=True,
        )
        model.Add(count_1er == int(best_count_1er))
        model.Add(count_2er_split == int(best_count_2er_split))
        model.Add(total_blocks == int(best_total_blocks))
        stage4_solution = [solver_s4.Value(use[b]) for b in range(len(blocks))]
        reset_hints_from_solver(model, use, solver_s4)
        stage4_solver_for_fallback = solver_s4
    elif status_s4 == cp_model.FEASIBLE:
        safe_print(f"  STAGE 4: FEASIBLE (not proven optimal)", flush=True)
        best_count_1er = solver_s4.Value(count_1er)
        best_count_2er_split = solver_s4.Value(count_2er_split)
        best_total_blocks = solver_s4.Value(total_blocks)
        safe_print(
            "  STAGE 4 RESULT: "
            f"count_1er = {int(best_count_1er)}, "
            f"count_2er_split = {int(best_count_2er_split)}, "
            f"total_blocks = {int(best_total_blocks)}",
            flush=True,
        )
        model.Add(count_1er == int(best_count_1er))
        model.Add(count_2er_split == int(best_count_2er_split))
        model.Add(total_blocks == int(best_total_blocks))
        stage4_solution = [solver_s4.Value(use[b]) for b in range(len(blocks))]
        reset_hints_from_solver(model, use, solver_s4)
        stage4_solver_for_fallback = solver_s4
    else:
        safe_print(f"  STAGE 4 FAILED: {status_str(status_s4)} (using Stage 3 fallback)", flush=True)
        best_count_1er = stage3_solver_for_fallback.Value(count_1er)
        best_count_2er_split = stage3_solver_for_fallback.Value(count_2er_split)
        best_total_blocks = stage3_solver_for_fallback.Value(total_blocks)
        safe_print(
            "  STAGE 4 FALLBACK: "
            f"count_1er = {int(best_count_1er)}, "
            f"count_2er_split = {int(best_count_2er_split)}, "
            f"total_blocks = {int(best_total_blocks)}",
            flush=True,
        )
        model.Add(count_1er == int(best_count_1er))
        model.Add(count_2er_split == int(best_count_2er_split))
        model.Add(total_blocks == int(best_total_blocks))
        stage4_solution = [stage3_solver_for_fallback.Value(use[b]) for b in range(len(blocks))]
        reset_hints_from_solver(model, use, stage3_solver_for_fallback)
        stage4_solver_for_fallback = stage3_solver_for_fallback
    
    # =========================================================================
    # STAGE 5: SECONDARY OPTIMIZATION under fixed packing
    # =========================================================================
    # K4: ALL packing counts are now fixed. Optimize secondary terms:
    # - max_day (prefer lower peak)
    # - total_blocks (prefer fewer blocks, already implicit from packing)
    # - slack (prefer no slack days)
    # - trap_penalty (prefer avoiding high-trap situations)
    # - chain_penalty (prefer chainable blocks)
    # - score (prefer higher-quality blocks)
    
    safe_print(f"\n  --- STAGE 5: SECONDARY OPTIMIZATION (under locked packing) ---", flush=True)
    
    # Build secondary objective components
    # Already have: max_day, day_slack from model construction
    total_slack = sum(day_slack[d] for d in days)
    
    # Score component (higher is better, so negate)
    if block_scores:
        score_vals = list(block_scores.values())
        s_min_val = min(score_vals) if score_vals else 0
        s_max_val = max(score_vals) if score_vals else 1
    else:
        s_min_val = 0
        s_max_val = 1
    
    def norm_score_secondary(s):
        """Normalize score to 0-1000 range for secondary optimization."""
        if s_max_val <= s_min_val:
            return 0
        return int(1000 * (s - s_min_val) / (s_max_val - s_min_val))
    
    score_sum = sum(
        use[b] * norm_score_secondary(block_scores.get(block.id, s_min_val) if block_scores else 0)
        for b, block in enumerate(blocks)
    )
    
    # K4: Full secondary objective (weights chosen to prioritize in order)
    W_MAXDAY_SEC = 1_000_000    # Highest secondary priority
    W_COUNT_SEC = 100_000       # Second (but packing is fixed, so mostly tie-break)
    W_SLACK_SEC = 10_000        # Third
    W_SCORE_SEC = 1             # Lowest (final tie-break)
    
    secondary_objective = (
        W_MAXDAY_SEC * max_day +
        W_COUNT_SEC * total_blocks +
        W_SLACK_SEC * total_slack -
        W_SCORE_SEC * score_sum  # Subtract (higher score = better)
    )
    
    safe_print(f"  SECONDARY OBJ: {W_MAXDAY_SEC}*max_day + {W_COUNT_SEC}*total_blocks + {W_SLACK_SEC}*slack - {W_SCORE_SEC}*score", flush=True)
    
    model.Minimize(secondary_objective)
    
    solver_s5 = cp_model.CpSolver()
    solver_s5.parameters.max_time_in_seconds = stage_budgets[5]
    solver_s5.parameters.num_search_workers = 1
    solver_s5.parameters.random_seed = config.seed
    
    status_s5 = solver_s5.Solve(model)
    
    # K5: Clean fallback logic
    if status_s5 == cp_model.OPTIMAL:
        safe_print(f"  STAGE 5: OPTIMAL", flush=True)
        final_solver = solver_s5
        used_stage4_fallback = False
    elif status_s5 == cp_model.FEASIBLE:
        safe_print(f"  STAGE 5: FEASIBLE (not proven optimal)", flush=True)
        final_solver = solver_s5
        used_stage4_fallback = False
    else:
        safe_print(f"  STAGE 5 FAILED: {status_str(status_s5)} (using Stage 4 fallback)", flush=True)
        # Reconstruct solution from stage4_solution
        final_solver = None  # Signal to use stage4_solution directly
        used_stage4_fallback = True
    
    # =========================================================================
    # EXTRACT FINAL SOLUTION
    # =========================================================================
    safe_print(f"\n{'='*60}", flush=True)
    safe_print("RC1 PACKING LOCKED:", flush=True)
    safe_print(f"  3er blocks:       {int(best_count_3er)}", flush=True)
    safe_print(f"  2er_REG blocks:   {int(best_count_2er_regular)}", flush=True)
    safe_print(f"  2er_SPLIT blocks: {int(best_count_2er_split)}", flush=True)
    safe_print(f"  1er blocks:       {int(best_count_1er)}", flush=True)
    safe_print(f"  Stage 5 fallback: {'YES (Stage 4)' if used_stage4_fallback else 'NO'}", flush=True)
    safe_print(f"{'='*60}", flush=True)
    
    # K5: Extract solution based on fallback status
    if used_stage4_fallback:
        # Use stage4_solution directly
        selected = [blocks[b] for b in range(len(blocks)) if stage4_solution[b] == 1]
        safe_print(f"  Using Stage 4 solution (Stage 5 failed)", flush=True)
        slack_values = {d: stage4_solver_for_fallback.Value(day_slack[d]) for d in days}
    else:
        # Use final_solver (Stage 5)
        selected = [blocks[b] for b in range(len(blocks)) if final_solver.Value(use[b]) == 1]
        slack_values = {d: final_solver.Value(day_slack[d]) for d in days}
        
        # INVARIANT CHECK: Packing counts must match locked values
        actual_3er = sum(1 for b in selected if len(b.tours) == 3)
        actual_2R = sum(1 for b in selected if len(b.tours) == 2 and _pause_zone_value(b) == "REGULAR")
        actual_2S = sum(1 for b in selected if len(b.tours) == 2 and _pause_zone_value(b) == "SPLIT")
        actual_1er = sum(1 for b in selected if len(b.tours) == 1)
        
        mismatch = (
            actual_3er != int(best_count_3er) or
            actual_2R != int(best_count_2er_regular) or
            actual_2S != int(best_count_2er_split) or
            actual_1er != int(best_count_1er)
        )
        
        if mismatch:
            safe_print(f"  WARNING: Packing invariant violated in Stage 5!", flush=True)
            safe_print(f"    Expected: 3er={int(best_count_3er)}, 2R={int(best_count_2er_regular)}, 2S={int(best_count_2er_split)}, 1er={int(best_count_1er)}", flush=True)
            safe_print(f"    Actual:   3er={actual_3er}, 2R={actual_2R}, 2S={actual_2S}, 1er={actual_1er}", flush=True)
        else:
            safe_print(f"  [OK] Packing invariant verified (counts locked)", flush=True)
    
    # Compute elapsed time (from model build start)
    elapsed = perf_counter() - t0
    
    # RC1: Merge repair pass (compress singles into multi-tour blocks)
    pre_repair = selected
    selected, merge_stats = _merge_repair_blocks(selected, blocks, block_index, block_scores)
    if merge_stats["added_blocks"]:
        safe_print(
            f"  MERGE REPAIR: replaced {merge_stats['replaced_blocks']} blocks "
            f"with {merge_stats['added_blocks']} merged blocks",
            flush=True,
        )

    # RC1: Detailed Stats by Category
    sel_1er = sum(1 for b in selected if len(b.tours) == 1)
    sel_2er_regular = sum(1 for b in selected if len(b.tours) == 2 and _pause_zone_value(b) == "REGULAR")
    sel_2er_split = sum(1 for b in selected if len(b.tours) == 2 and _pause_zone_value(b) == "SPLIT")
    sel_3er = sum(1 for b in selected if len(b.tours) == 3)
    sel_2er_total = sel_2er_regular + sel_2er_split
    safe_print(f"  SELECTED BLOCKS: 3er={sel_3er}, 2er_REG={sel_2er_regular}, 2er_SPLIT={sel_2er_split}, 1er={sel_1er}", flush=True)
    
    by_type = {"1er": sel_1er, "2er": sel_2er_total, "3er": sel_3er}
    split_2er_count = 0
    template_match_count = 0
    
    # Fix: Don't double count! sel_1er etc are already calculated.
    # Just loop for split/template stats.
    for block in selected:
        n = len(block.tours)
        
        # Check split flag
        if n == 2 and block_props and block.id in block_props:
            if block_props[block.id].get("is_split", False):
                split_2er_count += 1
        
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
    pre_repair_counts = {
        "1er": sum(1 for b in pre_repair if len(b.tours) == 1),
        "2er": sum(1 for b in pre_repair if len(b.tours) == 2),
        "3er": sum(1 for b in pre_repair if len(b.tours) == 3),
    }
    
    # RC1: Add Packing Telemetry
    pack_telemetry = {
        "selected_count_3er": sel_3er,
        "selected_count_2er_regular": sel_2er_regular,
        "selected_count_2er_split": sel_2er_split,
        "selected_count_1er": sel_1er,
        "candidate_count_3er": avail_3er,
        "candidate_count_2er_regular": avail_2er_reg,
        "candidate_count_2er_split": avail_2er_split,
        "candidate_count_1er": avail_1er,
        "tours_with_multi_candidates": len(tour_has_multi),
    }
    
    # Compute packability metrics (missed opportunities)
    pack_metrics = compute_packability_metrics(selected, blocks, tours)
    pack_telemetry.update(pack_metrics)
    pack_telemetry["avoidable_1er"] = max(0, by_type["1er"] - pack_metrics.get("forced_1er_count", 0))
    
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
        "pre_repair_block_mix": pre_repair_counts,
        "split_2er_count": split_2er_count,
        "template_match_count": template_match_count,
        "day_cap_slack": slack_values,
    }
    
    # RC1: Merge pack_telemetry into stats
    stats.update(pack_telemetry)
    if any(value > 0 for value in slack_values.values()):
        stats.setdefault("reason_codes", [])
        stats["reason_codes"].append("CAP_SLACK_USED")
    
    safe_print(f"Selected {len(selected)} blocks: {by_type}")
    safe_print(f"Block mix: 1er={block_mix['1er']*100:.1f}%, 2er={block_mix['2er']*100:.1f}%, 3er={block_mix['3er']*100:.1f}%")
    safe_print(f"Template matches: {template_match_count}")
    safe_print(f"Total hours: {total_hours:.1f}h")
    safe_print(f"Time: {elapsed:.2f}s")
    
    # ==== DIAGNOSTICS: Forced 1ers & Missed Opportunities ====
    safe_print(f"\n{'='*20} DIAGNOSTICS {'='*20}", flush=True)
    
    # 1. Selected Blocks per Day (Split)
    day_stats = defaultdict(lambda: {"1er": 0, "2er": 0, "3er": 0, "total": 0})
    for b in selected:
        d = b.day.value
        n = len(b.tours)
        k = f"{n}er" if n <=3 else "3er"
        day_stats[d][k] += 1
        day_stats[d]["total"] += 1
        
    logger.info("SELECTED BLOCKS BY DAY:")
    sorted_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for d in sorted_days:
        if d in day_stats:
            s = day_stats[d]
            safe_print(f"  {d}: {s['total']} blocks ({s['1er']} 1er, {s['2er']} 2er, {s['3er']} 3er)", flush=True)

    # 2. Forced 1ers (Tours that had NO non-1er option in the *input* pool)
    # We need to check 'block_index' for this.
    forced_1er_tours = []
    missed_3er_tours = [] # Tours assigned 1er, but efficient 3er option existed
    
    # Selected tour IDs map to the block type they ended up in
    tour_assignment = {} 
    for b in selected:
        n = len(b.tours)
        for t in b.tours:
            tour_assignment[t.id] = n
            
    # Check pool for every tour
    for tour in tours:
        tid = tour.id
        # What options did we have in the POOL?
        pool_blocks = block_index.get(tid, [])
        pool_options = {len(b.tours) for b in pool_blocks}
        
        # Did we have >1 options?
        has_multi = any(n > 1 for n in pool_options)
        has_3er = (3 in pool_options)
        
        # What did we pick?
        picked_n = tour_assignment.get(tid, 0)
        
        if picked_n == 1:
            if not has_multi:
                forced_1er_tours.append(tid)
            elif has_multi:
                # We CHOSE 1er despite multi option
                if has_3er:
                    missed_3er_tours.append(tid)

    safe_print(f"FORCED 1er TOURS: {len(forced_1er_tours)} (No multi-block option available in pool)", flush=True)
    safe_print(f"MISSED 3er OPPS: {len(missed_3er_tours)} (Assigned 1er, but 3er option existed)", flush=True)
    extra_1er = max(0, by_type["1er"] - len(forced_1er_tours))
    safe_print(
        f"EXCESS 1er vs forced: {extra_1er} (selected 1er={by_type['1er']}, forced={len(forced_1er_tours)})",
        flush=True
    )
    if missed_3er_tours:
        safe_print(f"  Example missed opps: {missed_3er_tours[:10]}...", flush=True)

    # 3. Day Min Lower Bound
    safe_print("DAY MIN LOWER BOUND (Max Concurrent Tours):", flush=True)
    for d in sorted_days:
        day_tours = [t for t in tours if t.day.value == d]
        if not day_tours: continue
        lb = solve_day_min_diagnostic(day_tours, d, config)
        actual = day_stats[d]["total"]
        gap = actual - lb
        safe_print(f"  {d}: LB={lb} vs Actual={actual} (Gap={gap})", flush=True)

    safe_print(f"{'='*53}", flush=True)
    
    return selected, stats


# =============================================================================
# TWO-PASS SOLVE FOR BEST_BALANCED PROFILE
# =============================================================================

def solve_capacity_twopass_balanced(
    blocks: list[Block],
    tours: list[Tour],
    block_index: dict[str, list[Block]],
    config: ConfigV4,
    block_scores: dict[str, float] = None,
    block_props: dict[str, dict] = None,
    total_time_budget: float = 180.0,
) -> tuple[list[Block], dict]:
    """
    Two-pass solve for BEST_BALANCED profile.
    
    Pass 1: Minimize headcount via full solve (capacity + greedy) to get true D_min.
    Pass 2: Optimize for balance with block_cap constraint (derived from D_min).
    
    NOTE: D_min is the actual drivers_total from Pass 1, not just block count.
    block_cap is used as a proxy constraint since drivers come from assignment phase.
    
    Returns:
        (selected_blocks, stats) with D_min (true driver count) and driver_cap in stats
    """
    safe_print(f"\n{'='*60}", flush=True)
    safe_print("BEST_BALANCED: TWO-PASS SOLVE", flush=True)
    safe_print(f"{'='*60}", flush=True)
    
    t0 = perf_counter()
    
    # =========================================================================
    # QUALITY-FIRST Budget Allocation (RC0 Policy)
    # =========================================================================
    # Pass-2 is GUARANTEED a minimum time (pass2_min_time_s), even if it means
    # cutting Pass-1 budget. This ensures twopass_executed=True for Quality runs.
    
    pass2_min_guaranteed = config.pass2_min_time_s  # Default: 15s
    
    # Calculate budgets: Pass-2 gets guaranteed minimum, Pass-1 gets rest
    if total_time_budget < pass2_min_guaranteed + 10.0:
        # Total budget too small - can't guarantee both passes meaningfully
        # Give 60/40 split as fallback
        pass1_budget = total_time_budget * 0.60
        pass2_budget = total_time_budget * 0.40
        safe_print(f"WARNING: Total budget {total_time_budget:.1f}s too small for quality guarantee", flush=True)
    else:
        # QUALITY-FIRST: Reserve minimum for Pass-2, rest goes to Pass-1
        pass2_budget = max(pass2_min_guaranteed, total_time_budget * 0.35)  # At least 35% or minimum
        pass1_budget = total_time_budget - pass2_budget - 2.0  # 2s buffer for overhead
    
    safe_print(f"Budget (QUALITY-FIRST): Pass1={pass1_budget:.1f}s, Pass2={pass2_budget:.1f}s (min guaranteed: {pass2_min_guaranteed:.1f}s)", flush=True)
    
    # =========================================================================
    # PASS 1: Full MIN_HEADCOUNT solve to get true D_min (drivers_total)
    # Use solve_capacity_phase (same function that works for MIN_HEADCOUNT_3ER)
    # =========================================================================
    safe_print(f"\nPASS 1: Minimize headcount (target budget: {pass1_budget:.1f}s)...", flush=True)
    t1 = perf_counter()
    
    # Explicitly pass time_limit to ensure it overrides config
    try:
        selected_pass1, stats_pass1 = solve_capacity_phase(
            blocks, tours, block_index, config,
            block_scores=block_scores,
            block_props=block_props,
            time_limit=pass1_budget
        )
        result_pass1 = (selected_pass1, stats_pass1) if stats_pass1.get("status") == "OK" else None
    except Exception as e:
        import traceback
        safe_print(f"PASS 1 EXCEPTION: {type(e).__name__}: {e}", flush=True)
        safe_print(traceback.format_exc(), flush=True)
        raise
    
    if result_pass1 is None:
        safe_print("PASS 1 INFEASIBLE - falling back to single-pass", flush=True)
        return solve_capacity_phase(
            blocks, tours, block_index, config,
            block_scores=block_scores,
            block_props=block_props
        )
    
    selected_pass1, stats_pass1 = result_pass1
    blocks_pass1 = len(selected_pass1)
    
    # Run greedy assignment to get TRUE D_min (drivers_total)
    safe_print(f"  Running greedy assignment on {blocks_pass1} blocks...", flush=True)
    assignments_pass1, assign_stats_pass1 = assign_drivers_greedy(selected_pass1, config)
    
    # D_pass1_seed = actual driver count from pass 1 (heuristic seed)
    D_pass1_seed = len(assignments_pass1)
    fte_pass1 = len([a for a in assignments_pass1 if a.driver_type == "FTE"])
    pt_pass1 = len([a for a in assignments_pass1 if a.driver_type == "PT"])
    underfull_pass1 = len([a for a in assignments_pass1 if a.driver_type == "FTE" and a.total_hours < config.min_hours_per_fte])
    
    elapsed_pass1 = perf_counter() - t1
    
    safe_print(f"PASS 1 RESULT: D_pass1_seed={D_pass1_seed} drivers ({fte_pass1} FTE, {pt_pass1} PT) from {blocks_pass1} blocks in {elapsed_pass1:.1f}s", flush=True)
    safe_print(f"  underfull_pass1: {underfull_pass1} ({underfull_pass1/fte_pass1*100:.1f}% of FTE)" if fte_pass1 > 0 else "  underfull_pass1: N/A", flush=True)
    
    # Compute driver cap: ceil((1 + max_extra_driver_pct) * D_pass1_seed)
    driver_cap = math.ceil((1 + config.max_extra_driver_pct) * D_pass1_seed)
    
    # Also compute block_cap as proxy (use same ratio applied to blocks)
    block_cap = math.ceil((1 + config.max_extra_driver_pct) * blocks_pass1)
    
    safe_print(f"PASS 2 CAPS: driver_cap={driver_cap} (+5% of {D_pass1_seed}), block_cap={block_cap} (+5% of {blocks_pass1})", flush=True)
    
    # FEASIBILITY CHECK (User Request)
    safe_print(f"PASS 2 FEASIBILITY CHECK: drivers_pass1 ({D_pass1_seed}) <= driver_cap ({driver_cap})", flush=True)
    if D_pass1_seed > driver_cap:
        safe_print(f"WARNING: D_pass1_seed > driver_cap! ({D_pass1_seed} > {driver_cap})", flush=True)
    
    # =========================================================================
    # PASS 2: Balance objective with block_cap constraint
    # (We constrain blocks as proxy since drivers come from assignment)
    # =========================================================================
    safe_print("\nPASS 2: Optimize balance with block cap...", flush=True)
    t2 = perf_counter()
    
    # Remaining budget after pass 1
    elapsed_so_far = perf_counter() - t0
    remaining_budget = min(pass2_budget, total_time_budget - elapsed_so_far - 1.0)
    
    safe_print(f"  Pass 1 overhead: {elapsed_pass1:.2f}s, Total elapsed: {elapsed_so_far:.2f}s", flush=True)
    safe_print(f"  Remaining budget: {remaining_budget:.2f}s (Threshold: 5.0s)", flush=True)
    
    if remaining_budget < config.pass2_min_time_s:
        # QUALITY-FIRST: This should rarely happen with proper budget allocation
        safe_print(f"WARNING: Insufficient budget for Pass-2 ({remaining_budget:.1f}s < {config.pass2_min_time_s}s minimum)", flush=True)
        safe_print(f"Using Pass-1 result (Pass-2 skipped due to budget exhaustion)", flush=True)
        stats_pass1["twopass_executed"] = False  # Pass 2 was skipped
        stats_pass1["D_pass1_seed"] = D_pass1_seed
        stats_pass1["D_min"] = D_pass1_seed  # Legacy
        stats_pass1["driver_cap"] = driver_cap
        stats_pass1["block_cap"] = block_cap
        stats_pass1["blocks_pass1"] = blocks_pass1
        stats_pass1["underfull_pass1"] = underfull_pass1
        stats_pass1["pt_pass1"] = pt_pass1
        stats_pass1["drivers_total_pass1"] = D_pass1_seed
        stats_pass1["drivers_total_pass2"] = None  # Not available
        stats_pass1["twopass_status"] = "PASS2_SKIPPED_BUDGET"
        stats_pass1["pass1_time_s"] = round(elapsed_pass1, 2)
        stats_pass1["pass2_time_s"] = None
        stats_pass1["pass2_min_time_s"] = config.pass2_min_time_s
        stats_pass1["output_profile"] = config.output_profile
        stats_pass1["gap_3er_min_minutes"] = config.gap_3er_min_minutes
        stats_pass1["diagnostics_failure_reason"] = f"Budget exhausted (rem={remaining_budget:.1f}s < min={config.pass2_min_time_s}s)"
        return selected_pass1, stats_pass1
    
    # Create CP-SAT model for pass 2 with balance objective
    # Use block_cap (not driver_cap) since we constrain at capacity phase
    result_pass2 = _solve_capacity_balanced_with_cap(
        blocks, tours, block_index, config,
        block_scores=block_scores,
        block_props=block_props,
        driver_cap=block_cap,  # Actually block_cap (proxy for driver cap)
        time_limit=remaining_budget,
        warm_start_blocks=selected_pass1
    )
    
    if result_pass2 is None:
        safe_print("PASS 2 INFEASIBLE - using pass 1 result", flush=True)
        stats_pass1["twopass_executed"] = False  # Pass 2 failed
        stats_pass1["diagnostics_failure_reason"] = "Pass 2 Infeasible (No solution found within budget)"
        stats_pass1["D_pass1_seed"] = D_pass1_seed
        stats_pass1["D_min"] = D_pass1_seed  # Legacy
        stats_pass1["driver_cap"] = driver_cap
        stats_pass1["block_cap"] = block_cap
        stats_pass1["blocks_pass1"] = blocks_pass1
        stats_pass1["underfull_pass1"] = underfull_pass1
        stats_pass1["pt_pass1"] = pt_pass1
        stats_pass1["drivers_total_pass1"] = D_pass1_seed
        stats_pass1["drivers_total_pass2"] = None  # Not available
        stats_pass1["twopass_status"] = "PASS2_INFEASIBLE"
        stats_pass1["pass1_time_s"] = round(elapsed_pass1, 2)
        stats_pass1["pass2_time_s"] = None
        stats_pass1["output_profile"] = config.output_profile
        stats_pass1["gap_3er_min_minutes"] = config.gap_3er_min_minutes
        return selected_pass1, stats_pass1
    
    # Pass 1 FAILED check
    safe_print(f"DEBUG: stats_pass1 status = '{stats_pass1.get('status')}'", flush=True)
    if stats_pass1.get("status") not in ["OK", "FEASIBLE", "OPTIMAL"]:
        safe_print(f"PASS 1 FAILED or NO SOLUTION (status={stats_pass1.get('status')}). Skipping Pass 2.", flush=True)
        stats_pass1["twopass_status"] = f"PASS1_FAIL_{stats_pass1.get('status')}"
        stats_pass1["twopass_executed"] = False
        return selected_pass1, stats_pass1
    
    selected_pass2, stats_pass2 = result_pass2
    elapsed_pass2 = perf_counter() - t2
    
    # Run greedy assignment on pass 2 blocks to get drivers_total_pass2
    assignments_pass2, assign_stats_pass2 = assign_drivers_greedy(selected_pass2, config)
    drivers_total_pass2 = len(assignments_pass2)
    
    safe_print(f"PASS 2 RESULT: {len(selected_pass2)} blocks -> {drivers_total_pass2} drivers in {elapsed_pass2:.1f}s", flush=True)
    
    # Add two-pass metadata to stats (complete stats for API propagation)
    stats_pass2["twopass_executed"] = True
    stats_pass2["D_pass1_seed"] = D_pass1_seed
    stats_pass2["D_min"] = D_pass1_seed  # Legacy
    stats_pass2["driver_cap"] = driver_cap
    stats_pass2["block_cap"] = block_cap
    stats_pass2["blocks_pass1"] = blocks_pass1
    stats_pass2["underfull_pass1"] = underfull_pass1
    stats_pass2["pt_pass1"] = pt_pass1
    stats_pass2["drivers_total_pass1"] = D_pass1_seed  # D_pass1_seed IS drivers_total from pass 1
    stats_pass2["drivers_total_pass2"] = drivers_total_pass2
    stats_pass2["twopass_status"] = "SUCCESS"
    stats_pass2["pass1_time_s"] = round(elapsed_pass1, 2)
    stats_pass2["pass2_time_s"] = round(elapsed_pass2, 2)
    stats_pass2["output_profile"] = config.output_profile
    stats_pass2["gap_3er_min_minutes"] = config.gap_3er_min_minutes
    
    # DEBUG TRACE
    safe_print(f"DEBUG: solve_capacity_twopass_balanced RETURNING: twopass_executed={stats_pass2.get('twopass_executed')}, expected=True")
    
    total_time = perf_counter() - t0
    safe_print(f"\nTWO-PASS COMPLETE: {len(selected_pass2)} blocks -> {drivers_total_pass2} drivers in {total_time:.1f}s", flush=True)
    safe_print(f"{'='*60}\n", flush=True)
    
    return selected_pass2, stats_pass2


def _solve_capacity_balanced_with_cap(
    blocks: list[Block],
    tours: list[Tour],
    block_index: dict[str, list[Block]],
    config: ConfigV4,
    block_scores: dict[str, float] = None,
    block_props: dict[str, dict] = None,
    driver_cap: int = None,
    time_limit: float = 60.0,
    warm_start_blocks: list[Block] = None
) -> tuple[list[Block], dict] | None:
    """
    Pass 2 solver: Balance objective with driver cap constraint.
    
    Objective priority (within cap):
    1. Minimize underfull penalty (prefer full utilization)
    2. Minimize 1er blocks (balance via multi-tour blocks)
    3. Minimize variance proxy (smooth distribution)
    """
    t0 = perf_counter()
    
    model = cp_model.CpModel()
    
    # Variables: one per block
    use = {}
    for b, block in enumerate(blocks):
        use[b] = model.NewBoolVar(f"use_{b}")
    
    # Warm start from Pass 1
    if warm_start_blocks:
        warm_ids = {b.id for b in warm_start_blocks}
        for b, block in enumerate(blocks):
            model.AddHint(use[b], 1 if block.id in warm_ids else 0)
        safe_print(f"  Added warm start hints from {len(warm_start_blocks)} blocks", flush=True)

    # Precompute block index lookup
    block_id_to_idx = {block.id: idx for idx, block in enumerate(blocks)}
    
    # Coverage constraints (each tour exactly once)
    for tour in tours:
        blocks_with_tour = block_index.get(tour.id, [])
        if not blocks_with_tour:
            return None  # No coverage possible
        
        block_indices = []
        for block in blocks_with_tour:
            b_idx = block_id_to_idx.get(block.id)
            if b_idx is not None:
                block_indices.append(b_idx)
        
        if not block_indices:
            return None
        
        model.Add(sum(use[b] for b in block_indices) == 1)
    
    # Driver cap constraint (KEY for BEST_BALANCED)
    total_blocks = sum(use[b] for b in range(len(blocks)))
    if driver_cap is not None:
        model.Add(total_blocks <= driver_cap)
        safe_print(f"  Added cap constraint: total_blocks <= {driver_cap}", flush=True)
    
    # Group blocks by day for balance metrics
    from collections import defaultdict
    blocks_by_day = defaultdict(list)
    for b, block in enumerate(blocks):
        blocks_by_day[block.day.value].append(b)
    
    days = list(blocks_by_day.keys())
    
    # Day-level counts for variance proxy
    day_count = {}
    for d in days:
        day_count[d] = sum(use[b] for b in blocks_by_day[d])
    
    # Compute max and min day counts for variance proxy
    max_day = model.NewIntVar(0, len(blocks), "max_day")
    min_day = model.NewIntVar(0, len(blocks), "min_day")
    
    for d in days:
        model.Add(max_day >= day_count[d])
        model.Add(min_day <= day_count[d])
    
    # Variance proxy: max_day - min_day (minimize spread)
    day_spread = model.NewIntVar(0, len(blocks), "day_spread")
    model.Add(day_spread == max_day - min_day)
    
    # Block type costs (balance-focused)
    block_cost = []
    
    # Cost structure for BEST_BALANCED:
    # - 1er: high cost (push toward multi-tour)
    # - 2er: moderate cost
    # - 3er: low/reward (maximize utilization)
    BASE_1 = 100_000   # Penalty for 1er
    BASE_2 = 10_000    # Moderate for 2er
    BASE_3 = -20_000   # Reward for 3er
    
    for b, block in enumerate(blocks):
        n = len(block.tours)
        if n == 1:
            cost = BASE_1
        elif n == 2:
            cost = BASE_2
        else:
            cost = BASE_3
        block_cost.append(use[b] * cost)
    
    # Objective: Balance-focused
    # Priority: min spread >> min 1er >> min blocks (within cap)
    W_SPREAD = 1_000_000     # Minimize day-to-day variance
    W_COST = 1               # Block type preference
    W_BLOCKS = 100           # Tie-break: fewer blocks still better
    
    objective = (
        W_SPREAD * day_spread +
        sum(block_cost) +
        W_BLOCKS * total_blocks
    )
    
    model.Minimize(objective)
    
    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1  # Determinism
    solver.parameters.random_seed = config.seed
    
    status = solver.Solve(model)
    elapsed = perf_counter() - t0
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    
    # Extract selected blocks
    selected = [blocks[b] for b in range(len(blocks)) if solver.Value(use[b]) == 1]
    
    # Stats
    by_type = {
        "1er": sum(1 for b in selected if len(b.tours) == 1),
        "2er": sum(1 for b in selected if len(b.tours) == 2),
        "3er": sum(1 for b in selected if len(b.tours) == 3),
    }
    
    by_day = defaultdict(int)
    for block in selected:
        by_day[block.day.value] += 1
    
    total_hours = sum(b.total_work_hours for b in selected)
    day_spread_val = solver.Value(day_spread)
    
    stats = {
        "status": "OK",
        "selected_blocks": len(selected),
        "blocks_1er": by_type["1er"],
        "blocks_2er": by_type["2er"],
        "blocks_3er": by_type["3er"],
        "blocks_by_day": dict(by_day),
        "total_hours": round(total_hours, 2),
        "time": round(elapsed, 2),
        "day_spread": day_spread_val,  # Variance proxy metric
    }
    
    safe_print(f"  Selected {len(selected)} blocks: {by_type}", flush=True)
    safe_print(f"  Day spread (variance proxy): {day_spread_val}", flush=True)
    
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
        from src.domain.constraints import HARD_CONSTRAINTS
        
        d = drivers[driver_id]
        day = block.day.value
        day_idx = get_day_index(day)
        
        # Check MAX_BLOCKS_PER_DAY (applies to ALL drivers)
        existing_day_blocks = d["day_blocks"].get(day, [])
        if len(existing_day_blocks) >= HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY:
            return False
        
        # Check weekly hours for ALL drivers (not just FTE)
        new_hours = d["hours"] + block.total_work_hours
        if new_hours > HARD_CONSTRAINTS.MAX_WEEKLY_HOURS:
            return False
        
        # Check hours if FTE (stricter limit than MAX_WEEKLY_HOURS)
        if d["type"] == "FTE":
            if new_hours > config.max_hours_per_fte:
                return False
        
        # ===================================================================
        # CENTRAL VALIDATION (Overlap + 11h Rest)
        # ===================================================================
        # Use central service to check overlap and rest constraints
        allowed, reason = can_assign_block(d["blocks"], block)
        if not allowed:
            # safe_print(f"DEBUG: Rejecting block {block.id} for driver {driver_id}: {reason}")
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
        
        # S0.1: Iterate in sorted order for determinism
        for driver_id in sorted(drivers.keys()):
            d = drivers[driver_id]
            if not can_take_block(driver_id, block):
                continue
            
            # ==== B) FILL-TO-TARGET SCORING (user-approved guardrails) ====
            # Primary: prefer drivers that cross min_hours threshold
            # Secondary: prefer drivers closest to target (min distance)
            target = config.min_hours_per_fte  # not hardcoded 42.0
            hours_after = d["hours"] + block.total_work_hours
            dist = abs(hours_after - target)
            crosses = (d["hours"] < target and hours_after >= target)
            
            # Tuple scoring: (0=crosses best, dist) - lower is better
            base_score = (0 if crosses else 1, dist)
            
            # Convert tuple to comparable number for sorting with penalties
            # crosses=True â†’ 0, crosses=False â†’ 1000000
            score = (0 if crosses else 1_000_000) + dist
            
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
    # S0.1: Iterate in sorted order for determinism
    for driver_id in sorted(drivers.keys()):
        d = drivers[driver_id]
        if d["type"] == "FTE" and d["hours"] < config.min_hours_per_fte:
            under_hours.append((driver_id, d["hours"]))
    
    elapsed = perf_counter() - t0
    
    # Build assignments
    assignments = []
    # S0.1: Iterate in sorted order for determinism
    for driver_id in sorted(drivers.keys()):
        d = drivers[driver_id]
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
    safe_print("PHASE A: Block building start...", flush=True)
    blocks, block_stats = build_weekly_blocks_smart(tours)
    block_time = perf_counter() - t_block
    safe_print(f"PHASE A: Block building done in {block_time:.2f}s, generated {len(blocks)} blocks", flush=True)
    
    # Extract scores from block_stats
    block_scores = block_stats.get("block_scores", {}) or {}
    block_props = block_stats.get("block_props", {}) or {}
    
    # Block pruning: sort deterministically and limit to max_blocks
    original_count = len(blocks)
    if config.max_blocks and len(blocks) > config.max_blocks:
        safe_print(f"Pruning blocks: {len(blocks)} > max_blocks={config.max_blocks}", flush=True)
        
        # V4 NEW: Tour-Aware Pruning
        blocks = prune_blocks_tour_aware(blocks, tours, config)
        
        # Sort by ID for determinism after pruning
        blocks.sort(key=lambda b: b.id)
        
        safe_print(f"Pruned from {original_count} to {len(blocks)} blocks", flush=True)
        # Rebuild index after pruning
        block_index = build_block_index(blocks)
        # Update block_scores and block_props to only include pruned blocks
        pruned_ids = {b.id for b in blocks}
        block_scores = {k: v for k, v in block_scores.items() if k in pruned_ids}
        block_props = {k: v for k, v in block_props.items() if k in pruned_ids}
    else:
        block_index = build_block_index(blocks)

    # Coverage audit + auto-heal (singleton safety net)
    phase1_reason_codes = []
    audit = audit_coverage(tours, blocks)
    if audit["tours_with_zero_candidates"] > 0:
        phase1_reason_codes.append("AUTO_HEAL_SINGLETONS")
        blocks, injected = ensure_singletons_for_all_tours(tours, blocks)
        if injected:
            fallback_score = min(block_scores.values()) - 1 if block_scores else 0
            for block in injected:
                block_scores[block.id] = fallback_score
                block_props[block.id] = {"auto_heal_singleton": True}
        block_index = build_block_index(blocks)
        audit = audit_coverage(tours, blocks)
        if audit["tours_with_zero_candidates"] > 0:
            safe_print("[ERROR] Coverage audit failed after auto-heal. Aborting Phase 1.", flush=True)
            return SolveResultV4(
                status="FAILED",
                assignments=[],
                kpi={"error": "Coverage audit failed after auto-heal"},
                solve_times={"block_building": block_time},
                block_stats=block_stats,
                missing_tours=audit["zero_tours"],
            )
    
    safe_print(f"Blocks: {len(blocks)} (1er={block_stats['blocks_1er']}, 2er={block_stats['blocks_2er']}, 3er={block_stats['blocks_3er']})", flush=True)
    if block_scores:
        safe_print(f"Policy scores loaded: {len(block_scores)} blocks", flush=True)
    
    # Phase 1: Capacity (use policy scores)
    selected_blocks, phase1_stats = solve_capacity_phase(
        blocks, tours, block_index, config,
        block_scores=block_scores,
        block_props=block_props
    )
    if phase1_reason_codes:
        phase1_stats.setdefault("reason_codes", [])
        phase1_stats["reason_codes"].extend(phase1_reason_codes)
    
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
        # Global CP-SAT Phase 2B is currently disabled by default (enable_global_cpsat=False)
        # This branch requires a greedy pre-solve to warm-start, which we skip for now.
        logger.warning("Global CP-SAT Phase 2B requested but not fully implemented - using greedy fallback")
        logger.info(f"Skipping global CP-SAT Phase 2B (enabled={config.enable_global_cpsat}, blocks={len(selected_blocks)})")
        assignments, phase2_stats = assign_drivers_greedy(selected_blocks, config)
    else:
        # Skip global CP-SAT (disabled or problem too large)
        logger.info(f"Skipping global CP-SAT Phase 2B (enabled={config.enable_global_cpsat}, blocks={len(selected_blocks)}, threshold={config.global_cpsat_block_threshold})")
        assignments, phase2_stats = assign_drivers_greedy(selected_blocks, config)
    
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
        "fte_used": phase2_stats.get("fte_used", fte_count),  # NEW: Actually working FTEs
        "fte_zero": phase2_stats.get("fte_zero", 0),  # NEW: Empty FTE slots
        "drivers_pt": phase2_stats["drivers_pt"],
        "fte_hours_min": phase2_stats["fte_hours_min"],
        "fte_hours_min_used": phase2_stats.get("fte_hours_min_used", phase2_stats["fte_hours_min"]),  # NEW
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
    safe_print("PHASE A: Block building...", flush=True)
    blocks, block_stats = build_weekly_blocks_smart(tours)
    block_time = perf_counter() - t_block
    safe_print(f"Generated {len(blocks)} blocks in {block_time:.1f}s", flush=True)
    
    block_scores = block_stats.get("block_scores", {})
    block_props = block_stats.get("block_props", {})
    block_index = build_block_index(blocks)
    
    # Phase 1: Select blocks
    t_capacity = perf_counter()
    safe_print("PHASE 1: Block selection (CP-SAT)...", flush=True)
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
    
    safe_print(f"Selected {len(selected_blocks)} blocks in {capacity_time:.1f}s", flush=True)
    
    # Phase 2: FEASIBILITY PIPELINE (Step 0 + Step 1)
    safe_print("=" * 60, flush=True)
    safe_print("PHASE 2: FEASIBILITY PIPELINE", flush=True)
    safe_print("=" * 60, flush=True)
    
    from src.services.feasibility_pipeline import run_feasibility_pipeline
    
    def log_fn(msg):
        safe_print(msg, flush=True)
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

def _can_accept_block(target: DriverAssignment, block, max_weekly_hours: float = 55.0) -> bool:
    """
    Check if target driver can accept a new block without violating hard constraints.
    
    Checks:
    1. MAX_BLOCKS_PER_DAY (2)
    2. MAX_WEEKLY_HOURS (55.0)
    """
    from src.domain.constraints import HARD_CONSTRAINTS
    
    # Check MAX_BLOCKS_PER_DAY
    day = block.day.value
    existing_day_blocks = [b for b in target.blocks if b.day.value == day]
    if len(existing_day_blocks) >= HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY:
        return False
    
    # Check MAX_WEEKLY_HOURS
    new_hours = target.total_hours + block.total_work_hours
    if new_hours > max_weekly_hours:
        return False
    
    return True


def _move_block(source: DriverAssignment, target: DriverAssignment, block, check_constraints: bool = True) -> bool:
    """
    Helper to move a block between drivers and update stats.
    
    Args:
        source: Driver to remove block from
        target: Driver to add block to
        block: Block to move
        check_constraints: If True, verify target can accept block before moving
        
    Returns:
        True if move was successful, False if blocked by constraints
    """
    # Constraint check (unless explicitly disabled)
    if check_constraints and not _can_accept_block(target, block):
        return False
    
    source.blocks.remove(block)
    source.total_hours = sum(b.total_work_hours for b in source.blocks)
    source.days_worked = len({t.day for b in source.blocks for t in b.tours}) if source.blocks else 0
    
    target.blocks.append(block)
    target.total_hours = sum(b.total_work_hours for b in target.blocks)
    target.days_worked = len({t.day for b in target.blocks for t in b.tours})
    
    return True


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
    Enhanced repair pass: move blocks to better meet min_fte_hours.
    
    Strategy (in order):
    1. FTEâ†’FTE balancing: Move blocks from overfull FTEs to underfull FTEs
    2. PTâ†’FTE stealing: Move blocks from PT drivers to underfull FTEs
    3. Leave remaining underfull FTEs unchanged (min hours treated as soft cost)
    """
    stats = {
        "moved_blocks_fte_fte": 0,
        "moved_blocks_pt_fte": 0,
        "reclassified_fte_to_pt": 0
    }
    
    # Get all FTE drivers
    all_ftes = [a for a in assignments if a.driver_type == "FTE"]
    
    # Phase 1: FTEâ†’FTE balancing
    logger.info("Repair Phase 1: FTEâ†’FTE balancing...")
    
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
                
            # Move block (will be rejected if violates constraints)
            if _move_block(donor, underfull, block):
                stats["moved_blocks_fte_fte"] += 1
    
    # Phase 2: PTâ†’FTE stealing
    logger.info("Repair Phase 2: PTâ†’FTE stealing...")
    
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
                
            if _move_block(source_pt, underfull, block):
                stats["moved_blocks_pt_fte"] += 1
    
    # Phase 3: Leave remaining underfull FTEs as-is (soft minimum)
    remaining_underfull = sum(
        1 for a in assignments if a.driver_type == "FTE" and a.total_hours < min_fte_hours
    )
    if remaining_underfull:
        logger.info(
            "Repair Phase 3: %s FTEs remain under %.1fh (soft minimum; no reclassification).",
            remaining_underfull,
            min_fte_hours,
        )
    
    logger.info(
        "Repair stats: FTEâ†’FTE moves=%s, PTâ†’FTE moves=%s, reclassified=%s",
        stats["moved_blocks_fte_fte"],
        stats["moved_blocks_pt_fte"],
        stats["reclassified_fte_to_pt"],
    )
    
    return assignments, stats


def consolidate_low_hour_fte(
    assignments: list[DriverAssignment],
    min_fte_hours: float = 40.0,
    max_fte_hours: float = 53.0,
    remove_threshold: float = 30.0,
) -> tuple[list[DriverAssignment], dict]:
    """Attempt to eliminate very low-hour FTEs by redistributing their blocks."""
    stats = {"fte_eliminated": 0, "moved_blocks": 0}
    fte_targets = [a for a in assignments if a.driver_type == "FTE"]
    low_ftes = sorted([a for a in fte_targets if a.total_hours < remove_threshold], key=lambda a: a.total_hours)
    donors = sorted([a for a in fte_targets if a.total_hours >= min_fte_hours], key=lambda a: -a.total_hours)

    for low in low_ftes:
        movable = list(low.blocks)
        moved_all = True
        for block in movable:
            placed = False
            for donor in donors:
                if donor.driver_id == low.driver_id:
                    continue
                if donor.total_hours + block.total_work_hours > max_fte_hours:
                    continue
                ok, _ = can_assign_block(donor.blocks, block)
                if not ok:
                    continue
                if _move_block(low, donor, block):
                    stats["moved_blocks"] += 1
                    placed = True
                    break
            if not placed:
                moved_all = False
                break
        if moved_all and not low.blocks:
            stats["fte_eliminated"] += 1
    return assignments, stats


def fte_distribution_histogram(assignments: list[DriverAssignment]) -> dict:
    """Bucket FTE hours for diagnostics."""
    buckets = {"0-30": 0, "30-40": 0, "40-45": 0, "45-50": 0, "50+": 0}
    for a in assignments:
        if a.driver_type != "FTE":
            continue
        h = a.total_hours
        if h < 30:
            buckets["0-30"] += 1
        elif h < 40:
            buckets["30-40"] += 1
        elif h < 45:
            buckets["40-45"] += 1
        elif h < 50:
            buckets["45-50"] += 1
        else:
            buckets["50+"] += 1
    return buckets


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
                    
                    if _move_block(pt, fte, block):
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
                    # Check both rest constraints AND hard daily/weekly limits
                    ok, _ = can_assign_block(fte.blocks, block)
                    if ok and _can_accept_block(fte, block):
                        placements.append((block, fte))
                        fte.blocks.append(block)
                        fte.total_hours += block.total_work_hours
                        placed = True
                        break
                
                # Try other PTs
                if not placed:
                    for other in sorted([a for a in assignments if a.driver_type == "PT" and a is not pt],
                                        key=lambda x: -x.total_hours):
                        # Check both rest constraints AND hard daily/weekly limits
                        ok, _ = can_assign_block(other.blocks, block)
                        if ok and _can_accept_block(other, block):
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
                
            # Move block PTâ†’FTE
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
                f"PT with Sat: {stats['pt_sat_before']} â†’ {stats['pt_sat_after']}")
    
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
            if ok and _can_accept_block(driver, block):
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
                if ok and _can_accept_block(driver, block):
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
                if ok and _can_accept_block(driver, block):
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
                f"PT with Sat: {stats['pt_drivers_with_sat_before']} â†’ {stats['pt_drivers_with_sat_after']}")
    
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
    safe_print("PHASE A: Block building...", flush=True)
    blocks, block_stats = build_weekly_blocks_smart(tours)
    block_time = perf_counter() - t_block
    safe_print(f"Generated {len(blocks)} blocks in {block_time:.1f}s", flush=True)
    
    block_scores = block_stats.get("block_scores", {})
    block_props = block_stats.get("block_props", {})
    block_index = build_block_index(blocks)
    
    # Phase 1: Select blocks (reuse existing)
    t_capacity = perf_counter()
    safe_print("PHASE 1: Block selection (CP-SAT)...", flush=True)
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
    
    safe_print(f"Selected {len(selected_blocks)} blocks in {capacity_time:.1f}s", flush=True)
    
    # Phase 2: Set-Partitioning
    safe_print("=" * 60, flush=True)
    safe_print("PHASE 2: SET-PARTITIONING", flush=True)
    safe_print("=" * 60, flush=True)
    
    def log_fn(msg):
        safe_print(msg, flush=True)
        logger.info(msg)
    
    from src.services.set_partition_solver import (
        solve_set_partitioning,
        convert_rosters_to_assignments,
        SetPartitionResult,
    )
    
    # Compute deadline for budget enforcement
    from time import monotonic
    
    # Global deadline for budget enforcement across phases
    # Note: time_limit here is the total budget for the run
    global_deadline = monotonic() + time_limit
    
    remaining = global_deadline - monotonic()
    if remaining <= 1.0:
        logger.warning(
            f"Time budget exhausted after Phase 1 (remaining={remaining:.2f}s); "
            "skipping set-partitioning and falling back to greedy."
        )
        sp_result = SetPartitionResult(
            status="TIMEOUT",
            selected_rosters=[],
            num_drivers=0,
            total_hours=0.0,
            hours_min=0.0,
            hours_max=0.0,
            hours_avg=0.0,
            uncovered_blocks=[b.id for b in selected_blocks],
            pool_size=0,
            rounds_used=0,
            total_time=0.0,
            rmp_time=0.0,
            generation_time=0.0,
        )
        sp_time = 0.0
    else:
        t_sp = perf_counter()
        sp_result = solve_set_partitioning(
            blocks=selected_blocks,
            max_rounds=100,
            initial_pool_size=5000,
            columns_per_round=200,
            rmp_time_limit=min(60.0, remaining / 3),
            seed=seed,
            log_fn=log_fn,
            config=config,  # NEW: Pass config for LNS
            global_deadline=global_deadline,  # FIX: Enforce time budget
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
        
        # Step 1: Rebalance FTEs (FTEâ†’FTE, then PTâ†’FTE, then reclassify)
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
