"""
SMART BLOCK BUILDER v5 - Policy-Driven (Pipeline v5)
======================================
Uses learned manual policy (manual_policy.json) to guide block generation.

v5 Priority Rules (4.5h tour optimized):
1. 3er blocks: 30-60 min pause between tours (Prio 1)
2. 2er blocks REG: 30 min pause exactly (Prio 2)
3. 2er blocks SPLIT: ≥360 min (6h) pause (Prio 3)

Key features:
1. 1er blocks ALWAYS included (coverage guarantee)
2. 2er/3er generation guided by canonical windows & templates
3. Scoring based on template matching (high bonus)
4. Split detection using 6h threshold (v5)
"""

import json
import time as time_module
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import time
from typing import Iterator, Optional
import logging

from src.domain.models import Block, Tour, Weekday
from src.domain.constraints import HARD_CONSTRAINTS

# Setup logger
logger = logging.getLogger("SmartBlockBuilder")


def safe_log(msg: str) -> None:
    """
    Safe logging that handles Windows console encoding errors.
    The [Errno 22] Invalid argument error occurs when Windows console
    cannot handle certain output operations during uvicorn reload.
    This function silently ignores such errors to prevent crashes.
    """
    try:
        logger.info(msg)
    except OSError:
        pass  # Silently ignore - message lost but solver continues


def safe_print(msg: str) -> None:
    """
    Safe print that handles Windows console encoding errors.
    Falls back to safe_log if print fails.
    """
    try:
        print(msg, flush=True)
    except OSError:
        # Windows console encoding error - try logger
        safe_log(msg)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Two-Zone Pause Model for Block Generation (v5)
# Zone 1 (Regular): 30-60 min - standard consecutive tours (tight packing)
# Zone 2 (Split):  360 min exactly - legal split-shift gap (2er only, 6h mandatory)
# Forbidden Zone:  61-359 and 361+ min - explicitly banned

# Regular pause limits (Zone 1)
MIN_PAUSE_MINUTES = HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS  # 30 min
MAX_PAUSE_REGULAR = HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS  # 60 min

# Split pause limits (Zone 2)
SPLIT_PAUSE_MIN = HARD_CONSTRAINTS.SPLIT_PAUSE_MIN   # 360 min (6h)
SPLIT_PAUSE_MAX = HARD_CONSTRAINTS.SPLIT_PAUSE_MAX   # 360 min (6h)
MAX_SPREAD_SPLIT = HARD_CONSTRAINTS.MAX_SPREAD_SPLIT_MINUTES  # 840 min (14h)

# Feature flag for split-shift generation
ENABLE_SPLIT_SHIFTS = True  # Can be overridden via config

# RC1: CLASS-AWARE CAPPING (Per-Tour Guarantees)
# Each tour retains its own Top-K per class to prevent multi-option starvation
# Values chosen for N≈1385 tours to stay under GLOBAL_TOP_N=40k:
# Worst case: (6+8+4+2) × 1385 = ~27,700 before dedup (safe under 40k)
K_3ER_PER_TOUR = 6       # Top 6 3er blocks per tour
K_2ER_REG_PER_TOUR = 8   # Top 8 regular 2er blocks per tour  
K_2ER_SPLIT_PER_TOUR = 4 # Top 4 split 2er blocks per tour (MUST survive pruning)
K_1ER_PER_TOUR = 2       # Top 2 1er blocks per tour
GLOBAL_TOP_N = 40_000    # Global limit (increased for class diversity)

# Legacy compatibility
K1_TOP_1ER = K_1ER_PER_TOUR
K2_TOP_2ER = K_2ER_REG_PER_TOUR
K3_TOP_3ER = K_3ER_PER_TOUR
K_PER_TOUR = K_3ER_PER_TOUR

# COMBI-PRIO RANKING (lower = higher priority)
# 3er > 2er_reg > 2er_split > 1er
RANK_3ER = 0
RANK_2ER_REG = 1
RANK_2ER_SPLIT = 2
RANK_1ER = 3

# Scoring - POLICY DRIVEN
SCORE_TEMPLATE_MATCH = 500  # Huge bonus for exact template match
SCORE_CANONICAL_WIN = 50    # Bonus per canonical window
SCORE_3ER_BASE = 150
SCORE_2ER_BASE = 100
SCORE_2ER_SPLIT_BASE = 90   # Slightly below regular 2er but still high
SCORE_1ER_BASE = 10

# Penalties (NEUTRALIZED for split to enable selection)
PENALTY_SPLIT_2ER = 0       # DISABLED - splits must be selectable
PENALTY_SPLIT_3ER = 0       # DISABLED - no split 3er anyway
PENALTY_LONG_SPAN = -40     # Span > 12h still penalized


# =============================================================================
# 3ER GAP VALIDATION (MIN_HEADCOUNT_3ER profile)
# =============================================================================

def gaps_3er_valid_min(block, gap_min: int = 30) -> bool:
    """
    Check if BOTH gaps in a 3er block are >= gap_min minutes.
    
    Used only by MIN_HEADCOUNT_3ER profile to filter valid 3er blocks.
    
    Args:
        block: Block object with .tours list
        gap_min: Minimum required gap between consecutive tours (default 30)
    
    Returns:
        True if block is valid (not a 3er OR all gaps >= gap_min)
        False if 3er with at least one gap < gap_min
    """
    if len(block.tours) != 3:
        return True  # Not a 3er, no filtering
    
    # Sort tours by start time (deterministic)
    tours = sorted(block.tours, key=lambda t: t.start_time)
    
    for i in range(2):  # Check gap1 (tour1→tour2) and gap2 (tour2→tour3)
        end_mins = tours[i].end_time.hour * 60 + tours[i].end_time.minute
        start_mins = tours[i+1].start_time.hour * 60 + tours[i+1].start_time.minute
        gap = start_mins - end_mins
        
        if gap < gap_min:
            return False  # Gap too small
    
    return True


# =============================================================================
# POLICY LOADING
# =============================================================================

@dataclass
class ManualPolicy:
    top_pair_templates: set[str]
    top_triple_templates: set[str]
    canonical_windows: dict[str, set[str]]  # usage by weekday
    split_gap_min: int = 180

_POLICY_CACHE: Optional[ManualPolicy] = None

def load_policy() -> ManualPolicy:
    global _POLICY_CACHE
    if _POLICY_CACHE:
        return _POLICY_CACHE
    
    # Locate policy file
    path = Path(__file__).parent.parent.parent / "data" / "manual_policy.json"
    if not path.exists():
        safe_log(f"[SmartBuilder] WARN: Policy file not found at {path}, using defaults")
        return ManualPolicy(set(), set(), defaultdict(set))
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Parse canonical windows by weekday
        canonical = {}
        if "canonical_windows_by_weekday" in data:
            for wd, wins in data["canonical_windows_by_weekday"].items():
                short_wd = wd[:3]  # Ensure Mon/Tue format
                canonical[short_wd] = set(wins)
        
        # Parse split threshold
        split_min = 180
        if "split_gap_cluster" in data:
             split_min = data["split_gap_cluster"].get("min", 180)

        policy = ManualPolicy(
            top_pair_templates=set(data.get("top_pair_templates", [])),
            top_triple_templates=set(data.get("top_triple_templates", [])),
            canonical_windows=canonical,
            split_gap_min=split_min
        )
        _POLICY_CACHE = policy
        safe_print(f"[SmartBuilder] Loaded policy: {len(policy.top_pair_templates)} pair templates, "
              f"{len(policy.top_triple_templates)} triple templates")
        return policy
        
    except Exception as e:
        safe_print(f"[SmartBuilder] ERROR loading policy: {e}")
        return ManualPolicy(set(), set(), defaultdict(set))


# =============================================================================
# SCORED BLOCK
# =============================================================================

@dataclass
class ScoredBlock:
    block: Block
    score: float
    is_split: bool = False
    is_template: bool = False
    tour_ids_hash: int = 0
    combi_rank: int = 3  # Combi-Prio: 0=3er, 1=2er_reg, 2=2er_split, 3=1er
    
    def __hash__(self):
        return hash(self.block.id)
    
    def sort_key(self):
        """Sort key for combi-prio ordering: (rank, -score, spread, pause)"""
        return (self.combi_rank, -self.score, self.block.span_minutes, 
                self.block.max_pause_minutes if hasattr(self.block, 'max_pause_minutes') else 0)


# =============================================================================
# MAIN BUILDER
# =============================================================================

def build_weekly_blocks_smart(
    tours: list[Tour],
    k_per_tour: int = K_PER_TOUR,
    global_top_n: int = GLOBAL_TOP_N,
    cap_quota_2er: float = 0.30,  # S0.8: Reserved quota for 2-tour blocks
    enable_diag: bool = False,    # S0.8: Gate diagnostic logs
    output_profile: str = "BEST_BALANCED",  # Profile selection
    gap_3er_min_minutes: int = 30,  # Min gap for 3er in MIN_HEADCOUNT_3ER
    cap_quota_3er: float = 0.25,  # 3er quota for MIN_HEADCOUNT_3ER
) -> tuple[list[Block], dict]:
    """
    Build blocks with manual-like quality using learned policy.
    
    Args:
        output_profile: "MIN_HEADCOUNT_3ER" or "BEST_BALANCED"
        gap_3er_min_minutes: Min gap between tours in 3er (MIN_HEADCOUNT_3ER only)
        cap_quota_3er: 3er reservation quota (MIN_HEADCOUNT_3ER only)
    """
    start_time = time_module.time()
    policy = load_policy()
    
    safe_log(f"[SmartBuilder] Starting with {len(tours)} tours, profile={output_profile}")
    
    # Step 1: Generate ALL blocks
    gen_start = time_module.time()
    safe_log("[SmartBuilder] Step 1: Generating blocks...")
    all_blocks = _generate_all_blocks(tours)
    gen_time = time_module.time() - gen_start
    
    count_1er = sum(1 for b in all_blocks if len(b.tours) == 1)
    count_2er = sum(1 for b in all_blocks if len(b.tours) == 2)
    count_3er = sum(1 for b in all_blocks if len(b.tours) == 3)
    
    safe_log(f"[SmartBuilder] Generated {len(all_blocks)} blocks in {gen_time:.2f}s")
    if enable_diag:
        safe_print(f"[DIAG] candidates_raw{{size=1}}: {count_1er}")
        safe_print(f"[DIAG] candidates_raw{{size=2}}: {count_2er}")
        safe_print(f"[DIAG] candidates_raw{{size=3}}: {count_3er}")
    
    # Step 1.5: Apply 3er gap filter for MIN_HEADCOUNT_3ER profile
    if output_profile == "MIN_HEADCOUNT_3ER":
        filtered_3er_count = 0
        kept_blocks = []
        for b in all_blocks:
            if len(b.tours) == 3:
                if gaps_3er_valid_min(b, gap_3er_min_minutes):
                    kept_blocks.append(b)
                else:
                    filtered_3er_count += 1
            else:
                kept_blocks.append(b)
        all_blocks = kept_blocks
        safe_log(f"[SmartBuilder] MIN_HEADCOUNT_3ER: Filtered {filtered_3er_count} invalid 3er blocks (gap < {gap_3er_min_minutes}min)")
        if enable_diag:
            new_3er = sum(1 for b in all_blocks if len(b.tours) == 3)
            safe_print(f"[DIAG] candidates_3er_after_gap_filter: {new_3er}")
    
    # Step 2: Score blocks using policy
    safe_print("[SmartBuilder] Step 2: Scoring blocks with policy...")
    scored = _score_all_blocks(all_blocks, policy)
    safe_print(f"[SmartBuilder] Scored {len(scored)} blocks")
    
    # Step 3: Dedupe
    safe_print("[SmartBuilder] Step 3: Deduplicating...")
    deduped = _dedupe_blocks(scored)
    safe_print(f"[SmartBuilder] After dedupe: {len(deduped)} blocks")
    dedup_1er = sum(1 for sb in deduped if len(sb.block.tours) == 1)
    dedup_2er = sum(1 for sb in deduped if len(sb.block.tours) == 2)
    dedup_3er = sum(1 for sb in deduped if len(sb.block.tours) == 3)
    if enable_diag:
        safe_print(f"[DIAG] candidates_deduped{{size=1}}: {dedup_1er}")
        safe_print(f"[DIAG] candidates_deduped{{size=2}}: {dedup_2er}")
        safe_print(f"[DIAG] candidates_deduped{{size=3}}: {dedup_3er}")
    
    # Step 4: Smart capping (Guarantee 1er)
    safe_print("[SmartBuilder] Step 4: Smart capping...")
    # Pass profile-specific quota parameters
    final_blocks, cap_stats = _smart_cap_with_1er_guarantee(
        deduped, tours, global_top_n, cap_quota_2er,
        cap_quota_3er=cap_quota_3er if output_profile == "MIN_HEADCOUNT_3ER" else 0.0
    )
    safe_log(f"[SmartBuilder] After capping: {len(final_blocks)} blocks")
    
    # ==== POOL HEALTH CHECK (after capping) ====
    from collections import Counter
    import statistics
    
    if enable_diag:
        cap_1er = sum(1 for b in final_blocks if len(b.tours) == 1)
        cap_2er = sum(1 for b in final_blocks if len(b.tours) == 2)
        cap_3er = sum(1 for b in final_blocks if len(b.tours) == 3)
        safe_print(f"[DIAG] candidates_kept{{size=1}}: {cap_1er}")
        safe_print(f"[DIAG] candidates_kept{{size=2}}: {cap_2er}")
        safe_print(f"[DIAG] candidates_kept{{size=3}}: {cap_3er}")
    
    # Calculate degrees per block type
    tour_deg_2er = defaultdict(int)
    tour_deg_3er = defaultdict(int)
    for b in final_blocks:
        n = len(b.tours)
        if n == 2:
            for t in b.tours: tour_deg_2er[t.id] += 1
        elif n == 3:
            for t in b.tours: tour_deg_3er[t.id] += 1
            
    # Helper for stats
    def get_stats(vals):
        if not vals: return "min=0 p10=0 med=0 max=0"
        vals.sort()
        n = len(vals)
        return (f"min={vals[0]} "
                f"p10={vals[int(n*0.1)]} "
                f"med={statistics.median(vals):.1f} "
                f"max={vals[-1]}")
                
    deg2_vals = [tour_deg_2er[t.id] for t in tours]
    deg3_vals = [tour_deg_3er[t.id] for t in tours]
    
    safe_log(f"[POOL DEGREE 2er] {get_stats(deg2_vals)}")
    safe_log(f"[POOL DEGREE 3er] {get_stats(deg3_vals)}")

    # Step 5: Sanity checks (returns (ok, errors) instead of raising)
    sanity_ok, sanity_errors = _sanity_check(final_blocks, tours)
    if sanity_errors:
        cap_stats["reason_codes"].extend(sanity_errors)
    
    elapsed = time_module.time() - start_time
    safe_print("[SmartBuilder] Step 5: Computing stats...")
    stats = _compute_stats(final_blocks, tours, elapsed, cap_stats, deduped) # Pass deduped for stats
    stats["sanity_ok"] = sanity_ok
    
    # Add raw counts for metrics
    stats["raw_1er"] = count_1er
    stats["raw_2er"] = count_2er
    stats["raw_3er"] = count_3er
    stats["candidates_3er_pre_cap"] = cap_stats.get("pre_cap_3er", 0)
    
    safe_print(f"[SmartBuilder] Final: {len(final_blocks)} blocks in {elapsed:.2f}s")
    if enable_diag:
        safe_print(f"[DIAG] candidates_3er_pre_cap: {stats['candidates_3er_pre_cap']}")
    return final_blocks, stats


# Renamed and adapted from _score_all_blocks to score a single block
def _score_single_block(block: Block, policy: ManualPolicy) -> ScoredBlock:
    """Score a single block based on policy and assign combi-prio rank."""
    n = len(block.tours)
    score = 0.0
    is_split = False
    is_template = False
    
    # Determine combi_rank and base score based on block type
    if n == 3:
        combi_rank = RANK_3ER  # 0 = highest priority
        score += SCORE_3ER_BASE
    elif n == 2:
        # Check if split 2er
        block_is_split = getattr(block, 'is_split', False)
        if block_is_split:
            combi_rank = RANK_2ER_SPLIT  # 2
            score += SCORE_2ER_SPLIT_BASE
            is_split = True
        else:
            combi_rank = RANK_2ER_REG  # 1
            score += SCORE_2ER_BASE
    else:
        combi_rank = RANK_1ER  # 3 = lowest priority
        score += SCORE_1ER_BASE
    
    # Gap / Split analysis (for non-tagged blocks, detect via gap zone)
    if n >= 2 and not is_split:
        max_gap = _max_gap_in_block(block)
        
        # Check if block should be split (gap in split zone)
        if max_gap >= SPLIT_PAUSE_MIN:
            is_split = True
            combi_rank = RANK_2ER_SPLIT  # Reclassify
            # No penalty applied (PENALTY_SPLIT_2ER = 0)
        
        # Policy: Template match
        template = _get_block_template(block)
        if n == 2 and template in policy.top_pair_templates:
            score += SCORE_TEMPLATE_MATCH
            is_template = True
        elif n == 3 and template in policy.top_triple_templates:
            score += SCORE_TEMPLATE_MATCH
            is_template = True
    
    # Canonical Window Bonus (per window)
    day_str = block.day.value  # Mon, Tue...
    if day_str in policy.canonical_windows:
        canonical_set = policy.canonical_windows[day_str]
        for t in block.tours:
            w_str = f"{t.start_time.hour:02d}:{t.start_time.minute:02d}-{t.end_time.hour:02d}:{t.end_time.minute:02d}"
            if w_str in canonical_set:
                score += SCORE_CANONICAL_WIN

    # Long span penalty
    if block.total_work_hours > 12:
        score += PENALTY_LONG_SPAN
        
    # Hash for dedupe
    tour_ids = tuple(sorted(t.id for t in block.tours))
    
    return ScoredBlock(
        block=block, 
        score=score, 
        is_split=is_split,
        is_template=is_template,
        tour_ids_hash=hash(tour_ids),
        combi_rank=combi_rank
    )


def _generate_all_blocks(tours: list[Tour], enable_splits: bool = True) -> list[Block]:
    """
    Generate 1er, 2er, and 3er blocks using two-zone pause logic.
    
    - 1er: Always created for every tour
    - 2er: Created from BOTH regular (30-120min) AND split (240-360min) adjacency
    - 3er: Created from regular adjacency ONLY (no splits to avoid complexity)
    
    Split blocks are tagged with is_split=True and max_pause_minutes.
    """
    tours_by_day: dict[Weekday, list[Tour]] = defaultdict(list)
    for tour in tours:
        tours_by_day[tour.day].append(tour)
    
    for day in tours_by_day:
        tours_by_day[day].sort(key=lambda t: t.start_time)
    
    all_blocks: list[Block] = []
    
    for day, day_tours in tours_by_day.items():
        can_follow_regular, can_follow_split = _build_adjacency(day_tours, enable_splits)
        
        # 1er - ALWAYS (no gaps)
        for tour in day_tours:
            all_blocks.append(Block(
                id=f"B1-{tour.id}", 
                day=day, 
                tours=[tour],
                is_split=False,
                max_pause_minutes=0,
                pause_zone="REGULAR"
            ))
        
        # 2er - Regular (30-120 min gap)
        for i, t1 in enumerate(day_tours):
            for j in can_follow_regular[i]:
                t2 = day_tours[j]
                if _span_ok([t1, t2]):
                    gap = _calc_gap(t1, t2)
                    all_blocks.append(Block(
                        id=f"B2-{t1.id}-{t2.id}", 
                        day=day, 
                        tours=[t1, t2],
                        is_split=False,
                        max_pause_minutes=gap,
                        pause_zone="REGULAR"
                    ))
        
        # 2er - Split (240-360 min gap) - ONLY for 2er
        if enable_splits:
            for i, t1 in enumerate(day_tours):
                for j in can_follow_split[i]:
                    t2 = day_tours[j]
                    # Check spread constraint for split blocks
                    span = _calc_span([t1, t2])
                    if span <= MAX_SPREAD_SPLIT:
                        gap = _calc_gap(t1, t2)
                        all_blocks.append(Block(
                            id=f"B2S-{t1.id}-{t2.id}",  # S suffix for split
                            day=day, 
                            tours=[t1, t2],
                            is_split=True,
                            max_pause_minutes=gap,
                            pause_zone="SPLIT"
                        ))
        
        # 3er - Regular adjacency ONLY (no splits allowed)
        for i, t1 in enumerate(day_tours):
            for j in can_follow_regular[i]:
                t2 = day_tours[j]
                if not _span_ok([t1, t2]): 
                    continue
                     
                for k in can_follow_regular[j]:
                    if k == i: continue
                    t3 = day_tours[k]
                    if _span_ok([t1, t2, t3]):
                        gap1 = _calc_gap(t1, t2)
                        gap2 = _calc_gap(t2, t3)
                        all_blocks.append(Block(
                            id=f"B3-{t1.id}-{t2.id}-{t3.id}", 
                            day=day, 
                            tours=[t1, t2, t3],
                            is_split=False,
                            max_pause_minutes=max(gap1, gap2),
                            pause_zone="REGULAR"
                        ))
    
    return all_blocks


def _calc_gap(t1: Tour, t2: Tour) -> int:
    """Calculate gap in minutes between end of t1 and start of t2."""
    t1_end = t1.end_time.hour * 60 + t1.end_time.minute
    t2_start = t2.start_time.hour * 60 + t2.start_time.minute
    return t2_start - t1_end


def _calc_span(tours: list[Tour]) -> int:
    """Calculate span in minutes from first start to last end."""
    first_start = tours[0].start_time.hour * 60 + tours[0].start_time.minute
    last_end = tours[-1].end_time.hour * 60 + tours[-1].end_time.minute
    return last_end - first_start


def _build_adjacency(tours: list[Tour], enable_splits: bool = True) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """
    Build two adjacency mappings for tours:
    - can_follow_regular: tours reachable with regular pause (30-120 min)
    - can_follow_split: tours reachable with split pause (240-360 min)
    
    Returns: (regular_adjacency, split_adjacency)
    """
    can_follow_regular = defaultdict(list)
    can_follow_split = defaultdict(list)
    
    for i, t1 in enumerate(tours):
        t1_end = t1.end_time.hour * 60 + t1.end_time.minute
        for j, t2 in enumerate(tours):
            if i == j: 
                continue
            t2_start = t2.start_time.hour * 60 + t2.start_time.minute
            
            gap = t2_start - t1_end
            
            # Zone 1: Regular pause (30-120 min)
            if MIN_PAUSE_MINUTES <= gap <= MAX_PAUSE_REGULAR:
                can_follow_regular[i].append(j)
            
            # Zone 2: Split pause (240-360 min) - only if enabled
            elif enable_splits and SPLIT_PAUSE_MIN <= gap <= SPLIT_PAUSE_MAX:
                can_follow_split[i].append(j)
            
            # Gaps 121-239 or >360 are forbidden - no entry
            
    return can_follow_regular, can_follow_split


def _get_block_template(block: Block) -> str:
    """Get HH:MM-HH:MM/... template string for block."""
    parts = []
    for t in block.tours:
        sh, sm = t.start_time.hour, t.start_time.minute
        eh, em = t.end_time.hour, t.end_time.minute
        # Logic to handle day overflow if needed, but for now assuming within day
        parts.append(f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}")
    return "/".join(parts)


# This function is now replaced by _score_single_block and inlined generation
def _score_all_blocks(blocks: list[Block], policy: ManualPolicy) -> list[ScoredBlock]:
    """
    This function is deprecated by the new inlined generation and _score_single_block.
    It's kept for compatibility if other parts of the code still call it,
    but it's no longer used by build_weekly_blocks_smart.
    """
    scored = []
    for block in blocks:
        scored.append(_score_single_block(block, policy))
    return scored


def _max_gap_in_block(block: Block) -> int:
    if len(block.tours) < 2: return 0
    tours = sorted(block.tours, key=lambda t: t.start_time)
    max_gap = 0
    for i in range(len(tours) - 1):
        end_mins = tours[i].end_time.hour * 60 + tours[i].end_time.minute
        start_mins = tours[i+1].start_time.hour * 60 + tours[i+1].start_time.minute
        gap = start_mins - end_mins
        max_gap = max(max_gap, gap)
    return max_gap


def _dedupe_blocks(scored: list[ScoredBlock]) -> list[ScoredBlock]:
    best_by_hash = {}
    for sb in scored:
        h = sb.tour_ids_hash
        if h not in best_by_hash or sb.score > best_by_hash[h].score:
            best_by_hash[h] = sb
    return list(best_by_hash.values())


def _smart_cap_with_1er_guarantee(
    scored: list[ScoredBlock], tours: list[Tour], global_n: int, 
    quota_2er: float = 0.30, cap_quota_3er: float = 0.0
) -> tuple[list[Block], dict]:
    """
    S0.4: Block Pool Stabilization (Feasibility-Safe + Deterministic).
    
    Invariants (MUST NEVER BREAK):
    1. Every tour has ≥1 block (protected set)
    2. Pool ≤ global_n (no explosion)
    3. Determinism: sorted(..., key=...), tie-break on block.id
    4. True dominance: only prune if SAME coverage set AND worse score
    
    Args:
        cap_quota_3er: 3er reservation quota for MIN_HEADCOUNT_3ER (default 0 = off)
    
    Steps:
    A) Protected set: best 1er per tour (or fallback if no 1er)
    B) Tour richness + Dynamic K: scarce tours get 2*K_PER_TOUR
    C) True dominance pruning: same cov_key, keep best score
    D) Global cap with protected priority + quota logic
    """
    import statistics
    from collections import defaultdict
    
    # S0.8: Debug Stats - Raw counts by class entering capping
    pre_cap_3er = sum(1 for sb in scored if len(sb.block.tours) == 3)
    pre_cap_2er_reg = sum(1 for sb in scored if len(sb.block.tours) == 2 and not sb.is_split)
    pre_cap_2er_split = sum(1 for sb in scored if len(sb.block.tours) == 2 and sb.is_split)
    pre_cap_1er = sum(1 for sb in scored if len(sb.block.tours) == 1)
    
    safe_log(f"[CAPPING] Pre-prune: 3er={pre_cap_3er}, 2er_reg={pre_cap_2er_reg}, "
             f"2er_split={pre_cap_2er_split}, 1er={pre_cap_1er}")

    # =========================================================================
    # A) PROTECTED SET: Ensure every tour has at least 1 block
    # =========================================================================
    protected_ids: set[str] = set()
    reason_codes: list[str] = []
    
    # Build tour -> blocks index (deterministic: sorted tours)
    tour_to_blocks: dict[str, list[ScoredBlock]] = defaultdict(list)
    for sb in scored:
        for t in sb.block.tours:
            tour_to_blocks[t.id].append(sb)
    
    # S0.4: For each tour (deterministic order), find best 1er or fallback
    for tour in sorted(tours, key=lambda t: t.id):
        tour_blocks = tour_to_blocks.get(tour.id, [])
        
        # Find 1er blocks for this tour
        ones = [sb for sb in tour_blocks if len(sb.block.tours) == 1]
        
        if ones:
            # S0.4: Best 1er by (score desc, id asc) for determinism
            best_1er = max(ones, key=lambda sb: (sb.score, -hash(sb.block.id)))
            # Stable deterministic: use actual key not hash
            ones_sorted = sorted(ones, key=lambda sb: (-sb.score, sb.block.id))
            best_1er = ones_sorted[0]
            protected_ids.add(best_1er.block.id)
        else:
            # No 1er: fallback to best covering block
            if tour_blocks:
                tour_blocks_sorted = sorted(tour_blocks, key=lambda sb: (-sb.score, sb.block.id))
                fallback = tour_blocks_sorted[0]
                protected_ids.add(fallback.block.id)
                reason_codes.append(f"MISSING_1ER_FOR_TOUR:{tour.id}")
            else:
                reason_codes.append(f"NO_BLOCKS_FOR_TOUR:{tour.id}")
    
    # =========================================================================
    # B) DYNAMIC K: Scarce tours get more slots
    # =========================================================================
    # B1: Compute tour_richness (number of blocks covering each tour, BEFORE dominance)
    tour_richness: dict[str, int] = {}
    for tour in tours:
        tour_richness[tour.id] = len(tour_to_blocks.get(tour.id, []))
    
    # B2: Compute median richness (stable)
    richness_values = sorted(tour_richness.values())
    if richness_values:
        median_richness = statistics.median(richness_values)
    else:
        median_richness = 1.0
    
    # B3: Dynamic K per tour
    # B1: Dynamic K values based on global_top_n
    # If global_top_n is small, clamp K values to prevent exceeding the limit
    num_tours = len(tours)
    num_classes = 4  # 3er, 2er_reg, 2er_split, 1er
    
    # Worst-case per-tour minima
    base_k_sum = K_3ER_PER_TOUR + K_2ER_REG_PER_TOUR + K_2ER_SPLIT_PER_TOUR + K_1ER_PER_TOUR
    worst_case_total = base_k_sum * num_tours
    
    if worst_case_total > global_n:
        # Scale down K values proportionally
        scale_factor = global_n / worst_case_total
        k_3er_actual = max(1, int(K_3ER_PER_TOUR * scale_factor))
        k_2er_reg_actual = max(1, int(K_2ER_REG_PER_TOUR * scale_factor))
        k_2er_split_actual = max(1, int(K_2ER_SPLIT_PER_TOUR * scale_factor))
        k_1er_actual = max(1, int(K_1ER_PER_TOUR * scale_factor))
        safe_log(f"[CAPPING] B1: global_top_n={global_n} small, scaling K down by {scale_factor:.2f}")
        safe_log(f"  K_actual: 3er={k_3er_actual}, 2R={k_2er_reg_actual}, 2S={k_2er_split_actual}, 1er={k_1er_actual}")
    else:
        k_3er_actual = K_3ER_PER_TOUR
        k_2er_reg_actual = K_2ER_REG_PER_TOUR
        k_2er_split_actual = K_2ER_SPLIT_PER_TOUR
        k_1er_actual = K_1ER_PER_TOUR
    
    # RC1: initialize kept set before per-tour guarantees
    kept_ids = set()
    
    # RC1: Per-Tour Guarantees by Class (deterministic)
    # Ensure EVERY tour has minimum multi-candidates if they exist
    # Priority within each class: higher score first, then ID tie-break
    
    for tour in sorted(tours, key=lambda t: t.id):
        tour_blocks = tour_to_blocks.get(tour.id, [])
        
        # B2: Consistent split classification - use pause_zone.value consistently
        # Separate blocks by class
        blocks_3er = [sb for sb in tour_blocks if len(sb.block.tours) == 3]
        blocks_2er_reg = [sb for sb in tour_blocks if len(sb.block.tours) == 2 and sb.block.pause_zone.value == "REGULAR"]
        blocks_2er_split = [sb for sb in tour_blocks if len(sb.block.tours) == 2 and sb.block.pause_zone.value == "SPLIT"]
        blocks_1er = [sb for sb in tour_blocks if len(sb.block.tours) == 1]
        
        # Deterministic sort: (-score, block.id) for stability
        sort_key = lambda sb: (-sb.score, sb.block.id)
        blocks_3er.sort(key=sort_key)
        blocks_2er_reg.sort(key=sort_key)
        blocks_2er_split.sort(key=sort_key)
        blocks_1er.sort(key=sort_key)
        
        # Keep Top-K per class (using dynamically adjusted K values)
        for sb in blocks_3er[:k_3er_actual]:
            kept_ids.add(sb.block.id)
        for sb in blocks_2er_reg[:k_2er_reg_actual]:
            kept_ids.add(sb.block.id)
        for sb in blocks_2er_split[:k_2er_split_actual]:
            kept_ids.add(sb.block.id)
        for sb in blocks_1er[:k_1er_actual]:
            kept_ids.add(sb.block.id)
    
    # Union with protected_ids
    kept_ids = kept_ids | protected_ids
    
    # =========================================================================
    # C) TRUE DOMINANCE PRUNING: Same coverage = same cov_key, best score wins
    # =========================================================================
    # C1: Build coverage key for each block
    # cov_key = tuple(sorted(tour_ids)) - hashable & deterministic
    cov_to_best: dict[tuple, ScoredBlock] = {}
    
    # Only consider blocks in kept_ids for dominance
    kept_blocks = [sb for sb in scored if sb.block.id in kept_ids]
    
    for sb in kept_blocks:
        cov_key = tuple(sorted(t.id for t in sb.block.tours))
        
        if cov_key in cov_to_best:
            existing = cov_to_best[cov_key]
            # S0.4: Keep best (higher score, deterministic tie-break on id)
            if (sb.score, sb.block.id) > (existing.score, existing.block.id):
                # Only replace if strictly better or same score with earlier ID
                if sb.score > existing.score:
                    cov_to_best[cov_key] = sb
                elif sb.score == existing.score and sb.block.id < existing.block.id:
                    cov_to_best[cov_key] = sb
        else:
            cov_to_best[cov_key] = sb
    
    # C2: Dominance-pruned IDs (only blocks that survived dominance)
    dominance_kept_ids = {sb.block.id for sb in cov_to_best.values()}
    
    # C3: Ensure protected ALWAYS survive (even if dominated)
    dominance_kept_ids = dominance_kept_ids | protected_ids
    
    # =========================================================================
    # D) GLOBAL CAP: ≤ global_n, protected never removed
    # =========================================================================
    # D1: Separate protected vs non-protected
    protected_blocks = [sb for sb in scored if sb.block.id in protected_ids]
    non_protected = [sb for sb in scored if sb.block.id in dominance_kept_ids and sb.block.id not in protected_ids]
    
    # D2: Sort non-protected by score (deterministic) and SPLIT for QUOTA
    np_2er = [sb for sb in non_protected if len(sb.block.tours) == 2]
    np_3er = [sb for sb in non_protected if len(sb.block.tours) == 3]
    np_other = [sb for sb in non_protected if len(sb.block.tours) not in (2, 3)]

    # Sort each pool
    # Key: (-score, id) - simple, deterministic
    sort_key = lambda sb: (-sb.score, sb.block.id)
    np_2er.sort(key=sort_key)
    np_3er.sort(key=sort_key)
    np_other.sort(key=sort_key)

    # D3: Apply Quota-Based Cap (30% 2er reservation)
    if len(protected_blocks) >= global_n:
        reason_codes.append("POOL_PROTECTED_EXCEEDS_CAP")
        final_blocks = protected_blocks
    else:
        remaining_slots = global_n - len(protected_blocks)
        
        # S0.8: Adaptive Quota Logic
        raw_total = len(np_2er) + len(np_3er) + len(np_other)
        avail_2er_ratio = len(np_2er) / raw_total if raw_total > 0 else 0.0
        avail_3er_ratio = len(np_3er) / raw_total if raw_total > 0 else 0.0
        
        # Effective 2er quota: min(configured, max(available, 0.05))
        effective_quota_2er = min(quota_2er, max(avail_2er_ratio, 0.05))
        
        # Effective 3er quota (only if cap_quota_3er > 0, i.e., MIN_HEADCOUNT_3ER)
        if cap_quota_3er > 0:
            effective_quota_3er = min(cap_quota_3er, max(avail_3er_ratio, 0.05))
        else:
            effective_quota_3er = 0.0
        
        # Allocate slots: Priority = 2er > 3er > other
        # Ensure 2er + 3er quotas don't exceed remaining_slots
        total_quota = effective_quota_2er + effective_quota_3er
        if total_quota > 0.95:  # Cap to leave room for flexibility
            scale = 0.95 / total_quota
            effective_quota_2er *= scale
            effective_quota_3er *= scale
        
        target_2er = int(remaining_slots * effective_quota_2er)
        target_3er = int(remaining_slots * effective_quota_3er) if cap_quota_3er > 0 else remaining_slots - target_2er

        # Select top items per quota
        taken_2er = np_2er[:target_2er]
        taken_3er = np_3er[:target_3er]
        
        # Fill slack if one pool ran dry (release unused quota to other)
        slack_2er = target_2er - len(taken_2er)
        slack_3er = target_3er - len(taken_3er)
        
        # If 3er has slack, give to 2er (and vice versa)
        if slack_3er > 0 and len(np_2er) > len(taken_2er):
             extra = np_2er[len(taken_2er) : len(taken_2er) + slack_3er]
             taken_2er.extend(extra)
        
        if slack_2er > 0 and len(np_3er) > len(taken_3er):
             extra = np_3er[len(taken_3er) : len(taken_3er) + slack_2er]
             taken_3er.extend(extra)

        # Merge
        trimmed = taken_2er + taken_3er
        
        # Add np_other if we have space left (unlikely but safe)
        if len(trimmed) < remaining_slots and np_other:
             needed = remaining_slots - len(trimmed)
             trimmed.extend(np_other[:needed])

        final_blocks = protected_blocks + trimmed
        
        if len(non_protected) > len(trimmed):
            reason_codes.append("POOL_CAPPED_QUOTA")
    
    # =========================================================================
    # BUILD RESULT
    # =========================================================================
    final_ids = {sb.block.id for sb in final_blocks}
    result_blocks = [sb.block for sb in final_blocks]
    
    # S0.4: Stats for RunReport
    locked_1er_unique = sum(1 for sb in final_blocks if len(sb.block.tours) == 1)
    split_2er = sum(1 for sb in final_blocks if len(sb.block.tours) == 2 and sb.is_split)
    template_match = sum(1 for sb in final_blocks if sb.is_template)
    scarce_tours_count = sum(1 for tid, r in tour_richness.items() if r < median_richness / 2)
    
    # Post-prune class counts
    post_3er = sum(1 for sb in final_blocks if len(sb.block.tours) == 3)
    post_2er_reg = sum(1 for sb in final_blocks if len(sb.block.tours) == 2 and not sb.is_split)
    post_2er_split = sum(1 for sb in final_blocks if len(sb.block.tours) == 2 and sb.is_split)
    post_1er = sum(1 for sb in final_blocks if len(sb.block.tours) == 1)
    
    safe_log(f"[CAPPING] Post-prune: 3er={post_3er}, 2er_reg={post_2er_reg}, "
             f"2er_split={post_2er_split}, 1er={post_1er}")
    
    cap_stats = {
        "locked_1er": locked_1er_unique,
        "split_2er_count": split_2er,
        "template_match_count": template_match,
        "final_total": len(result_blocks),
        "pre_cap_3er": pre_cap_3er,
        "pre_cap_2er_split": pre_cap_2er_split,  # NEW: Track split candidates pre-prune
        "post_cap_2er_split": post_2er_split,     # NEW: Track split candidates post-prune
        # S0.4 new stats
        "protected_count": len(protected_ids),
        "dominance_pruned": len(kept_ids) - len(dominance_kept_ids),
        "scarce_tours_count": scarce_tours_count,
        "median_richness": round(median_richness, 1),
        "reason_codes": reason_codes,
    }
    
    return result_blocks, cap_stats


def _sanity_check(blocks: list[Block], tours: list[Tour]) -> tuple[bool, list[str]]:
    """
    Check block pool sanity. Returns (ok, error_codes) instead of raising.
    Issue 5: No uncaught ValueError in production path.
    """
    errors = []
    
    count_1er = sum(1 for b in blocks if len(b.tours) == 1)
    if len(tours) % 2 == 1 and count_1er == 0:
        errors.append("PARITY_ERROR:ODD_TOURS_NO_1ER")
    
    tour_coverage = defaultdict(int)
    for b in blocks:
        for t in b.tours:
            tour_coverage[t.id] += 1
            
    missing = [t.id for t in tours if tour_coverage[t.id] == 0]
    if missing:
        errors.append(f"COVERAGE_ERROR:{len(missing)}_TOURS_MISSING")
        for tid in sorted(missing)[:5]:  # Log first 5
            errors.append(f"MISSING_TOUR:{tid}")
    
    if not errors:
        safe_log(f"[Sanity] OK. 1er count: {count_1er}")
    else:
        safe_log(f"[Sanity] FAILED: {errors}")
    
    return (len(errors) == 0, errors)


def _span_ok(tours: list[Tour]) -> bool:
    if not tours: return True
    starts = [t.start_time.hour * 60 + t.start_time.minute for t in tours]
    ends = [t.end_time.hour * 60 + t.end_time.minute for t in tours]
    return (max(ends) - min(starts)) / 60.0 <= HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS


def _compute_stats(blocks: list[Block], tours: list[Tour], elapsed: float, cap_stats: dict, scored: list[ScoredBlock]) -> dict:
    by_type = {"1er": 0, "2er": 0, "3er": 0}
    for b in blocks:
        n = len(b.tours)
        k = f"{n}er" if n <= 3 else "other"
        if k in by_type: by_type[k] += 1
        
    # Template match stats
    template_ids = {sb.block.id for sb in scored if sb.is_template}
    matches = sum(1 for b in blocks if b.id in template_ids)

    # Degree stats
    degrees = defaultdict(int)
    for block in blocks:
        for tour in block.tours:
            degrees[tour.id] += 1
    deg_values = list(degrees.values()) if degrees else [0]

    # Export scores for solver - use set for O(1) lookup instead of O(n) list membership
    block_ids = {b.id for b in blocks}
    block_scores = {sb.block.id: sb.score for sb in scored if sb.block.id in block_ids}
    # Export flags for style report
    block_props = {
        sb.block.id: {"is_split": sb.is_split, "is_template": sb.is_template}
        for sb in scored if sb.block.id in block_ids
    }

    return {
        "total_blocks": len(blocks),
        "blocks_1er": by_type["1er"],
        "blocks_2er": by_type["2er"],
        "blocks_3er": by_type["3er"],
        "build_time_seconds": round(elapsed, 2),
        "split_2er_count": cap_stats.get("split_2er_count", 0),
        "template_match_count": matches,
        "min_degree": min(deg_values),
        "max_degree": max(deg_values),
        "avg_degree": round(sum(deg_values) / len(deg_values), 1),
        "block_scores": block_scores,
        "block_props": block_props
    }


# =============================================================================
# EXPORTS
# =============================================================================

def build_block_index(blocks: list[Block]) -> dict[str, list[Block]]:
    index = defaultdict(list)
    for b in blocks:
        for t in b.tours:
            index[t.id].append(b)
    return dict(index)

def verify_coverage(tours: list[Tour], blocks: list[Block]) -> tuple[bool, list[str]]:
    index = build_block_index(blocks)
    missing = [t.id for t in tours if t.id not in index]
    return (len(missing) == 0, missing)
