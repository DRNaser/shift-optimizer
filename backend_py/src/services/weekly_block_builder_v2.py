"""
OPTIMIZED WEEKLY BLOCK BUILDER - Scalable to 2000+ Tours
=========================================================
Uses adjacency-based generation instead of O(n³) exhaustive enumeration.

Key optimizations:
1. Pre-compute adjacency matrix (which tours can follow which)
2. Only enumerate valid chains, not all combinations
3. Early termination with block limits
4. Parallel processing per day

Complexity: O(n × k²) where k = average combinable tours per tour
For typical forecasts: k ≈ 5-15, so effective complexity ≈ O(n × 100)
"""

from collections import defaultdict
from datetime import time
from typing import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid

from src.domain.models import Block, Tour, Weekday
from src.domain.constraints import HARD_CONSTRAINTS


# =============================================================================
# CONFIGURATION
# =============================================================================

MAX_BLOCKS_PER_DAY = 20_000  # Reduced for scalability
MAX_PAUSE_MINUTES = 45  # REDUCED: 45 min max gap (was 120)
MIN_PAUSE_MINUTES = 0   # No minimum gap (can be back-to-back)
MAX_3ER_PER_DAY = 3_000  # Hard limit on 3er blocks per day
MAX_2ER_PER_DAY = 8_000  # Hard limit on 2er blocks per day


# =============================================================================
# OPTIMIZED BLOCK BUILDER
# =============================================================================

def build_weekly_blocks_optimized(
    tours: list[Tour],
    max_blocks_per_day: int = MAX_BLOCKS_PER_DAY,
    parallel: bool = True
) -> list[Block]:
    """
    Build blocks using adjacency-based algorithm - O(n × k²) instead of O(n³).
    
    Args:
        tours: List of tours to build blocks from
        max_blocks_per_day: Safety limit per day
        parallel: Use parallel processing for days
        
    Returns:
        List of all valid blocks (1er, 2er, 3er)
    """
    # Group tours by day
    tours_by_day: dict[Weekday, list[Tour]] = defaultdict(list)
    for tour in tours:
        tours_by_day[tour.day].append(tour)
    
    # Sort tours by start time within each day
    for day in tours_by_day:
        tours_by_day[day].sort(key=lambda t: t.start_time)
    
    all_blocks: list[Block] = []
    
    if parallel and len(tours_by_day) > 1:
        # Parallel processing per day
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(
                    _build_day_blocks_optimized, 
                    day, 
                    day_tours, 
                    max_blocks_per_day
                ): day 
                for day, day_tours in tours_by_day.items()
            }
            for future in as_completed(futures):
                day_blocks = future.result()
                all_blocks.extend(day_blocks)
    else:
        # Sequential processing
        for day, day_tours in tours_by_day.items():
            day_blocks = _build_day_blocks_optimized(day, day_tours, max_blocks_per_day)
            all_blocks.extend(day_blocks)
    
    return all_blocks


def _build_day_blocks_optimized(
    day: Weekday, 
    tours: list[Tour],
    max_blocks: int
) -> list[Block]:
    """
    Build blocks for a single day using adjacency-based approach.
    
    Algorithm:
    1. Build adjacency list: for each tour, which tours can directly follow it
    2. Generate 1er blocks (always, for coverage guarantee)
    3. Generate 2er blocks by following adjacency links (limited)
    4. Generate 3er blocks by extending valid 2er blocks (limited)
    """
    if not tours:
        return []
    
    blocks: list[Block] = []
    blocks_2er_count = 0
    blocks_3er_count = 0
    
    # Create tour index for quick lookup
    tour_idx = {t.id: i for i, t in enumerate(tours)}
    
    # Step 1: Build adjacency list - O(n²) but with early filtering
    # can_follow[i] = list of tour indices that can directly follow tour i
    can_follow: dict[int, list[int]] = defaultdict(list)
    
    for i, t1 in enumerate(tours):
        t1_end_mins = t1.end_time.hour * 60 + t1.end_time.minute
        
        for j, t2 in enumerate(tours):
            if i == j:
                continue
            
            t2_start_mins = t2.start_time.hour * 60 + t2.start_time.minute
            gap = t2_start_mins - t1_end_mins
            
            # Only tours that start after t1 ends with valid gap
            if MIN_PAUSE_MINUTES <= gap <= MAX_PAUSE_MINUTES:
                can_follow[i].append(j)
    
    # Step 2: Generate 1er blocks (always - coverage guarantee)
    for tour in tours:
        blocks.append(Block(
            id=f"B1-{tour.id}",
            day=day,
            tours=[tour]
        ))
    
    # Step 3: Generate 2er blocks - O(n × k) where k = avg followers
    for i, t1 in enumerate(tours):
        if blocks_2er_count >= MAX_2ER_PER_DAY:
            break
            
        for j in can_follow[i]:
            if blocks_2er_count >= MAX_2ER_PER_DAY:
                break
                
            t2 = tours[j]
            
            # Check span
            if _span_ok([t1, t2]):
                blocks.append(Block(
                    id=f"B2-{t1.id}-{t2.id}",
                    day=day,
                    tours=[t1, t2]
                ))
                blocks_2er_count += 1
    
    if blocks_2er_count >= MAX_2ER_PER_DAY:
        print(f"  [INFO] {day.value}: Hit 2er limit {MAX_2ER_PER_DAY}")
    
    # Step 4: Generate 3er blocks - O(n × k²) where k = avg followers
    for i, t1 in enumerate(tours):
        if blocks_3er_count >= MAX_3ER_PER_DAY:
            break
            
        for j in can_follow[i]:
            if blocks_3er_count >= MAX_3ER_PER_DAY:
                break
                
            t2 = tours[j]
            
            # Check if t1-t2 span is already too long for adding t3
            t1_start = t1.start_time.hour * 60 + t1.start_time.minute
            t2_end = t2.end_time.hour * 60 + t2.end_time.minute
            current_span = (t2_end - t1_start) / 60.0
            
            if current_span > HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS - 4:
                # Can't fit another 4h tour, skip
                continue
            
            for k in can_follow[j]:
                if blocks_3er_count >= MAX_3ER_PER_DAY:
                    break
                    
                if k == i:  # Avoid cycles
                    continue
                    
                t3 = tours[k]
                
                if _span_ok([t1, t2, t3]):
                    blocks.append(Block(
                        id=f"B3-{t1.id}-{t2.id}-{t3.id}",
                        day=day,
                        tours=[t1, t2, t3]
                    ))
                    blocks_3er_count += 1
    
    if blocks_3er_count >= MAX_3ER_PER_DAY:
        print(f"  [INFO] {day.value}: Hit 3er limit {MAX_3ER_PER_DAY}")
    
    return blocks


def _span_ok(tours: list[Tour]) -> bool:
    """Check if block span is within limits."""
    if not tours:
        return True
    
    starts = [t.start_time.hour * 60 + t.start_time.minute for t in tours]
    ends = [t.end_time.hour * 60 + t.end_time.minute for t in tours]
    
    span_minutes = max(ends) - min(starts)
    span_hours = span_minutes / 60.0
    
    return span_hours <= HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS


# =============================================================================
# WRAPPER WITH STATS
# =============================================================================

def build_weekly_blocks_with_stats(
    tours: list[Tour],
    max_blocks_per_day: int = MAX_BLOCKS_PER_DAY
) -> tuple[list[Block], dict]:
    """
    Build blocks and return statistics.
    
    Returns:
        (blocks, stats_dict)
    """
    import time as time_module
    
    start_time = time_module.time()
    blocks = build_weekly_blocks_optimized(tours, max_blocks_per_day)
    elapsed = time_module.time() - start_time
    
    # Count by type
    by_type = {"1er": 0, "2er": 0, "3er": 0}
    by_day: dict[str, int] = defaultdict(int)
    
    for b in blocks:
        n = len(b.tours)
        if n == 1:
            by_type["1er"] += 1
        elif n == 2:
            by_type["2er"] += 1
        elif n == 3:
            by_type["3er"] += 1
        by_day[b.day.value] += 1
    
    stats = {
        "total_blocks": len(blocks),
        "blocks_1er": by_type["1er"],
        "blocks_2er": by_type["2er"],
        "blocks_3er": by_type["3er"],
        "blocks_by_day": dict(by_day),
        "build_time_seconds": round(elapsed, 2),
        "tours_input": len(tours),
    }
    
    return blocks, stats


# =============================================================================
# BLOCK INDEX AND VERIFICATION
# =============================================================================

def build_block_index_optimized(blocks: list[Block]) -> dict[str, list[Block]]:
    """
    Build index mapping tour_id → list of blocks containing that tour.
    """
    index: dict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        for tour in block.tours:
            index[tour.id].append(block)
    return dict(index)


def verify_coverage_optimized(tours: list[Tour], blocks: list[Block]) -> tuple[bool, list[str]]:
    """
    Verify that every tour has at least one block.
    """
    index = build_block_index_optimized(blocks)
    missing = [t.id for t in tours if t.id not in index or len(index[t.id]) == 0]
    return (len(missing) == 0, missing)


def get_block_pool_stats_optimized(blocks: list[Block]) -> dict:
    """Get statistics about the block pool."""
    by_type = {"1er": 0, "2er": 0, "3er": 0}
    for b in blocks:
        n = len(b.tours)
        if n == 1:
            by_type["1er"] += 1
        elif n == 2:
            by_type["2er"] += 1
        elif n == 3:
            by_type["3er"] += 1
    
    return {
        "total_blocks": len(blocks),
        "blocks_by_type": by_type,
        "blocks_1er": by_type["1er"],
        "blocks_2er": by_type["2er"],
        "blocks_3er": by_type["3er"],
    }


# =============================================================================
# COMPATIBILITY LAYER
# =============================================================================

# Drop-in replacement for original function
def build_weekly_blocks(tours: list[Tour], include_singles: bool = True) -> list[Block]:
    """
    Drop-in replacement for original build_weekly_blocks.
    Uses optimized algorithm for large tour counts.
    """
    if len(tours) > 100:
        # Use optimized version for large datasets
        return build_weekly_blocks_optimized(tours)
    else:
        # Use original for small datasets (maintains exact behavior)
        from src.services.weekly_block_builder import build_weekly_blocks as original_build
        return original_build(tours, include_singles)


# Re-export for compatibility
build_block_index = build_block_index_optimized
verify_coverage = verify_coverage_optimized
get_block_pool_stats = get_block_pool_stats_optimized
