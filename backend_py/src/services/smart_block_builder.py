"""
SMART BLOCK BUILDER v5 - Policy-Driven
======================================
Uses learned manual policy (manual_policy.json) to guide block generation.

Key features:
1. 1er blocks ALWAYS included (coverage guarantee)
2. 2er/3er generation guided by canonical windows & templates
3. Scoring based on template matching (high bonus)
4. Split detection using policy threshold (180min)
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


# =============================================================================
# CONFIGURATION
# =============================================================================

# Block generation - Use HARD_CONSTRAINTS for tour pauses within a block.
# For split-shift candidates (multi-block per day), we allow larger gaps
# but apply scoring penalties. 8h is the safety cap.
MIN_PAUSE_MINUTES = HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS  # 30 min (standard pause)
MAX_PAUSE_MINUTES = 480  # 8h max gap - intentional for split-shift candidates

# Split-gap scoring policy (in minutes)
# Gaps in this range are considered "ideal" for split shifts
SPLIT_GAP_IDEAL_MIN = 315   # 5h 15m - min of ideal split gap
SPLIT_GAP_IDEAL_MAX = 405   # 6h 45m - max of ideal split gap  
SPLIT_GAP_ACCEPTABLE_MAX = 480  # 8h - absolute max, heavy penalty above ideal

# Capping
K_PER_TOUR = 30          # Coverage guarantee
GLOBAL_TOP_N = 20_000    # Global limit

# Scoring - POLICY DRIVEN
SCORE_TEMPLATE_MATCH = 500  # Huge bonus for exact template match
SCORE_CANONICAL_WIN = 50    # Bonus per canonical window
SCORE_3ER_BASE = 150
SCORE_2ER_BASE = 100
SCORE_1ER_BASE = 10

# Penalties
PENALTY_SPLIT_2ER = -30          # General split penalty
PENALTY_SPLIT_3ER = -20          # General split penalty
PENALTY_LONG_SPAN = -40          # Span > 12h
PENALTY_SPLIT_GAP_PER_15MIN = -5 # Penalty per 15min above ideal gap


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
        logger.warning(f"[SmartBuilder] WARN: Policy file not found at {path}, using defaults")
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
        print(f"[SmartBuilder] Loaded policy: {len(policy.top_pair_templates)} pair templates, "
              f"{len(policy.top_triple_templates)} triple templates")
        return policy
        
    except Exception as e:
        print(f"[SmartBuilder] ERROR loading policy: {e}")
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
    
    def __hash__(self):
        return hash(self.block.id)


# =============================================================================
# MAIN BUILDER
# =============================================================================

def build_weekly_blocks_smart(
    tours: list[Tour],
    k_per_tour: int = K_PER_TOUR,
    global_top_n: int = GLOBAL_TOP_N,
) -> tuple[list[Block], dict]:
    """
    Build blocks with manual-like quality using learned policy.
    """
    start_time = time_module.time()
    policy = load_policy()
    
    print(f"[SmartBuilder] Starting with {len(tours)} tours", flush=True)
    
    # Step 1: Generate ALL blocks
    gen_start = time_module.time()
    print("[SmartBuilder] Step 1: Generating blocks...", flush=True)
    all_blocks = _generate_all_blocks(tours)
    gen_time = time_module.time() - gen_start
    
    count_1er = sum(1 for b in all_blocks if len(b.tours) == 1)
    count_2er = sum(1 for b in all_blocks if len(b.tours) == 2)
    count_3er = sum(1 for b in all_blocks if len(b.tours) == 3)
    
    print(f"[SmartBuilder] Generated {len(all_blocks)} blocks in {gen_time:.2f}s", flush=True)
    print(f"[SmartBuilder]   1er={count_1er}, 2er={count_2er}, 3er={count_3er}", flush=True)
    
    # Step 2: Score blocks using policy
    print("[SmartBuilder] Step 2: Scoring blocks with policy...", flush=True)
    scored = _score_all_blocks(all_blocks, policy)
    print(f"[SmartBuilder] Scored {len(scored)} blocks", flush=True)
    
    # Step 3: Dedupe
    print("[SmartBuilder] Step 3: Deduplicating...", flush=True)
    deduped = _dedupe_blocks(scored)
    print(f"[SmartBuilder] After dedupe: {len(deduped)} blocks", flush=True)
    
    # Step 4: Smart capping (Guarantee 1er)
    print("[SmartBuilder] Step 4: Smart capping...", flush=True)
    final_blocks, cap_stats = _smart_cap_with_1er_guarantee(
        deduped, tours, k_per_tour, global_top_n
    )
    print(f"[SmartBuilder] After capping: {len(final_blocks)} blocks", flush=True)
    
    # Step 5: Sanity checks
    _sanity_check(final_blocks, tours)
    
    elapsed = time_module.time() - start_time
    print("[SmartBuilder] Step 5: Computing stats...", flush=True)
    stats = _compute_stats(final_blocks, tours, elapsed, cap_stats, deduped) # Pass deduped for stats
    
    print(f"[SmartBuilder] Final: {len(final_blocks)} blocks in {elapsed:.2f}s", flush=True)
    return final_blocks, stats


# Renamed and adapted from _score_all_blocks to score a single block
def _score_single_block(block: Block, policy: ManualPolicy) -> ScoredBlock:
    """Score a single block based on policy."""
    n = len(block.tours)
    score = 0.0
    is_split = False
    is_template = False
    
    # Base Score
    if n == 3: score += SCORE_3ER_BASE
    elif n == 2: score += SCORE_2ER_BASE
    else: score += SCORE_1ER_BASE
    
    # Gap / Split analysis with graduated scoring
    if n >= 2:
        max_gap = _max_gap_in_block(block)
        if max_gap >= policy.split_gap_min:
            is_split = True
            score += PENALTY_SPLIT_2ER if n == 2 else PENALTY_SPLIT_3ER
            
            # Graduated split-gap penalty: ideal is 315-405 min
            # Gaps above SPLIT_GAP_IDEAL_MAX get additional penalty
            if max_gap > SPLIT_GAP_IDEAL_MAX:
                # Penalty per 15 min above ideal max
                extra_minutes = max_gap - SPLIT_GAP_IDEAL_MAX
                chunks = extra_minutes // 15
                score += chunks * PENALTY_SPLIT_GAP_PER_15MIN
        
        # Policy: Template match
        template = _get_block_template(block)
        if n == 2 and template in policy.top_pair_templates:
            score += SCORE_TEMPLATE_MATCH
            is_template = True
        elif n == 3 and template in policy.top_triple_templates:
            score += SCORE_TEMPLATE_MATCH
            is_template = True
    
    # Canonical Window Bonus (per window)
    # We need to check if individual tours match canonical windows for that weekday
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
        tour_ids_hash=hash(tour_ids)
    )


def _generate_all_blocks(tours: list[Tour]) -> list[Block]:
    """Generate 1er, 2er, and 3er blocks."""
    # This function is now effectively replaced by the inlined generation in build_weekly_blocks_smart
    # but kept for completeness if other parts of the code still call it.
    # The new build_weekly_blocks_smart directly generates ScoredBlocks.
    # For now, this function is not called by the new build_weekly_blocks_smart.
    tours_by_day: dict[Weekday, list[Tour]] = defaultdict(list)
    for tour in tours:
        tours_by_day[tour.day].append(tour)
    
    for day in tours_by_day:
        tours_by_day[day].sort(key=lambda t: t.start_time)
    
    all_blocks: list[Block] = []
    
    for day, day_tours in tours_by_day.items():
        can_follow = _build_adjacency(day_tours)
        
        # 1er - ALWAYS
        for tour in day_tours:
            all_blocks.append(Block(id=f"B1-{tour.id}", day=day, tours=[tour]))
        
        # 2er
        for i, t1 in enumerate(day_tours):
            for j in can_follow[i]:
                t2 = day_tours[j]
                if _span_ok([t1, t2]):
                    all_blocks.append(Block(
                        id=f"B2-{t1.id}-{t2.id}", day=day, tours=[t1, t2]
                    ))
        
        # 3er
        for i, t1 in enumerate(day_tours):
            for j in can_follow[i]:
                t2 = day_tours[j]
                # Optimization: check span of first 2 to fail fast
                if not _span_ok([t1, t2]): 
                     continue
                     
                for k in can_follow[j]:
                    if k == i: continue
                    t3 = day_tours[k]
                    if _span_ok([t1, t2, t3]):
                        all_blocks.append(Block(
                            id=f"B3-{t1.id}-{t2.id}-{t3.id}", day=day, tours=[t1, t2, t3]
                        ))
    
    return all_blocks


def _build_adjacency(tours: list[Tour]) -> dict[int, list[int]]:
    can_follow = defaultdict(list)
    for i, t1 in enumerate(tours):
        t1_end = t1.end_time.hour * 60 + t1.end_time.minute
        for j, t2 in enumerate(tours):
            if i == j: continue
            t2_start = t2.start_time.hour * 60 + t2.start_time.minute
            
            gap = t2_start - t1_end
            if MIN_PAUSE_MINUTES <= gap <= MAX_PAUSE_MINUTES:
                can_follow[i].append(j)
    return can_follow


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
    scored: list[ScoredBlock], tours: list[Tour], k: int, global_n: int
) -> tuple[list[Block], dict]:
    # 1. Lock ALL 1er
    blocks_1er = [sb for sb in scored if len(sb.block.tours) == 1]
    locked_ids = {sb.block.id for sb in blocks_1er}
    
    # 2. Lock top-K multi per tour
    blocks_multi = [sb for sb in scored if len(sb.block.tours) >= 2]
    tour_to_blocks = defaultdict(list)
    for sb in blocks_multi:
        for t in sb.block.tours:
            tour_to_blocks[t.id].append(sb)
            
    for t_id in tour_to_blocks:
        tour_to_blocks[t_id].sort(key=lambda sb: sb.score, reverse=True)
        for sb in tour_to_blocks[t_id][:k]:
            locked_ids.add(sb.block.id)
            
    # 3. Global top-N
    rest = [sb for sb in scored if sb.block.id not in locked_ids]
    rest.sort(key=lambda sb: sb.score, reverse=True)
    
    needed = max(0, global_n - len(locked_ids))
    for sb in rest[:needed]:
        locked_ids.add(sb.block.id)
        
    final = [sb.block for sb in scored if sb.block.id in locked_ids]
    
    # Stats
    split_2er = sum(1 for sb in scored if sb.block.id in locked_ids 
                    and len(sb.block.tours)==2 and sb.is_split)
    template_match = sum(1 for sb in scored if sb.block.id in locked_ids and sb.is_template)
    
    return final, {
        "locked_1er": len(blocks_1er),
        "split_2er_count": split_2er,
        "template_match_count": template_match
    }


def _sanity_check(blocks: list[Block], tours: list[Tour]):
    count_1er = sum(1 for b in blocks if len(b.tours) == 1)
    if len(tours) % 2 == 1 and count_1er == 0:
        raise ValueError("PARITY ERROR: Odd tours but no 1er blocks!")
    
    tour_coverage = defaultdict(int)
    for b in blocks:
        for t in b.tours:
            tour_coverage[t.id] += 1
            
    missing = [t.id for t in tours if tour_coverage[t.id] == 0]
    if missing:
        raise ValueError(f"COVERAGE ERROR: {len(missing)} tours missing blocks")
    print(f"[Sanity] OK. 1er count: {count_1er}")


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
