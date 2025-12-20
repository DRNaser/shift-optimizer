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
# Tour-wise retention keeps critical 3er/2er combinations alive before any
# global cap is applied. Global cap only fills beyond these guarantees.
GLOBAL_TOP_N = 20_000    # Global limit
K1_TOP_1ER = 3           # Top singles per tour (usually only 1 exists)
K2_TOP_2ER = 30          # Top pairs per tour (INCREASED from 15)
K3_TOP_3ER = 50          # Top triples per tour (INCREASED from 30)
K_PER_TOUR = K3_TOP_3ER  # Backwards compatibility with legacy parameter name

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
    
    logger.info(f"[SmartBuilder] Starting with {len(tours)} tours")
    
    # Step 1: Generate ALL blocks
    gen_start = time_module.time()
    logger.info("[SmartBuilder] Step 1: Generating blocks...")
    all_blocks = _generate_all_blocks(tours)
    gen_time = time_module.time() - gen_start
    
    count_1er = sum(1 for b in all_blocks if len(b.tours) == 1)
    count_2er = sum(1 for b in all_blocks if len(b.tours) == 2)
    count_3er = sum(1 for b in all_blocks if len(b.tours) == 3)
    
    logger.info(f"[SmartBuilder] Generated {len(all_blocks)} blocks in {gen_time:.2f}s")
    logger.info(f"[SmartBuilder]   1er={count_1er}, 2er={count_2er}, 3er={count_3er}")
    
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
    # Remove k_per_tour arg, not used anymore inside
    final_blocks, cap_stats = _smart_cap_with_1er_guarantee(
        deduped, tours, global_top_n
    )
    logger.info(f"[SmartBuilder] After capping: {len(final_blocks)} blocks")
    
    # ==== POOL HEALTH CHECK (after capping) ====
    from collections import Counter
    import statistics
    
    cap_1er = sum(1 for b in final_blocks if len(b.tours) == 1)
    cap_2er = sum(1 for b in final_blocks if len(b.tours) == 2)
    cap_3er = sum(1 for b in final_blocks if len(b.tours) == 3)
    logger.info(f"[POOL AFTER CAP] total={len(final_blocks)} mix: 1er={cap_1er}, 2er={cap_2er}, 3er={cap_3er}")
    
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
    
    logger.info(f"[POOL DEGREE 2er] {get_stats(deg2_vals)}")
    logger.info(f"[POOL DEGREE 3er] {get_stats(deg3_vals)}")

    # Step 5: Sanity checks (returns (ok, errors) instead of raising)
    sanity_ok, sanity_errors = _sanity_check(final_blocks, tours)
    if sanity_errors:
        cap_stats["reason_codes"].extend(sanity_errors)
    
    elapsed = time_module.time() - start_time
    print("[SmartBuilder] Step 5: Computing stats...", flush=True)
    stats = _compute_stats(final_blocks, tours, elapsed, cap_stats, deduped) # Pass deduped for stats
    stats["sanity_ok"] = sanity_ok
    
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
    scored: list[ScoredBlock], tours: list[Tour], global_n: int
) -> tuple[list[Block], dict]:
    """
    S0.4: Block Pool Stabilization (Feasibility-Safe + Deterministic).
    
    Invariants (MUST NEVER BREAK):
    1. Every tour has ≥1 block (protected set)
    2. Pool ≤ global_n (no explosion)
    3. Determinism: sorted(..., key=...), tie-break on block.id
    4. True dominance: only prune if SAME coverage set AND worse score
    
    Steps:
    A) Protected set: best 1er per tour (or fallback if no 1er)
    B) Tour richness + Dynamic K: scarce tours get 2*K_PER_TOUR
    C) True dominance pruning: same cov_key, keep best score
    D) Global cap with protected priority
    """
    import statistics
    from collections import defaultdict
    
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
    def get_k_for_tour(tour_id: str) -> int:
        richness = tour_richness.get(tour_id, 0)
        if richness < median_richness / 2:
            return 2 * K_PER_TOUR  # Scarce tour: double K
        else:
            return K_PER_TOUR
    
    # B4: Collect Top-K per tour (deterministic sort, stable tie-break)
    kept_ids: set[str] = set()
    
    for tour in sorted(tours, key=lambda t: t.id):
        tour_blocks = tour_to_blocks.get(tour.id, [])
        k = get_k_for_tour(tour.id)
        
        # S0.4: Sort by (-score, -len(tours), block.id) for determinism
        tour_blocks_sorted = sorted(
            tour_blocks,
            key=lambda sb: (-sb.score, -len(sb.block.tours), sb.block.id)
        )
        
        for sb in tour_blocks_sorted[:k]:
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
    
    # D2: Sort non-protected by score (deterministic)
    non_protected_sorted = sorted(
        non_protected,
        key=lambda sb: (-sb.score, -len(sb.block.tours), sb.block.id)
    )
    
    # D3: Cap
    if len(protected_blocks) >= global_n:
        # Edge case: too many protected (model error, but handle gracefully)
        reason_codes.append("POOL_PROTECTED_EXCEEDS_CAP")
        final_blocks = protected_blocks  # Keep all protected, can't trim
    else:
        remaining_slots = global_n - len(protected_blocks)
        trimmed_non_protected = non_protected_sorted[:remaining_slots]
        final_blocks = protected_blocks + trimmed_non_protected
        if len(non_protected_sorted) > remaining_slots:
            reason_codes.append("POOL_CAPPED")
    
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
    
    cap_stats = {
        "locked_1er": locked_1er_unique,
        "split_2er_count": split_2er,
        "template_match_count": template_match,
        "final_total": len(result_blocks),
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
        logger.info(f"[Sanity] OK. 1er count: {count_1er}")
    else:
        logger.warning(f"[Sanity] FAILED: {errors}")
    
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
