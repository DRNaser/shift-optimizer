"""
WEEKLY BLOCK BUILDER
====================
Block builder for forecast-only planning with guaranteed 1er fallback.
Every tour ALWAYS has at least one block (the 1er), ensuring 100% coverage.
"""

from collections import defaultdict
from datetime import time
from typing import Iterator
import uuid

from src.domain.models import Block, Tour, Weekday
from src.domain.constraints import HARD_CONSTRAINTS


def build_weekly_blocks(tours: list[Tour], include_singles: bool = True) -> list[Block]:
    """
    Build all possible blocks from tours with guaranteed 1er fallback.
    
    CRITICAL: Every tour appears in at least one block (its 1er fallback).
    This ensures the model is ALWAYS feasible for coverage.
    
    Args:
        tours: List of tours to build blocks from
        include_singles: Always True for forecast mode (guarantees coverage)
        
    Returns:
        List of all possible blocks (1er, 2er, 3er)
    """
    all_blocks: list[Block] = []
    
    # Group tours by day
    tours_by_day: dict[Weekday, list[Tour]] = defaultdict(list)
    for tour in tours:
        tours_by_day[tour.day].append(tour)
    
    # Sort tours by start time within each day
    for day in tours_by_day:
        tours_by_day[day].sort(key=lambda t: t.start_time)
    
    # Generate blocks for each day
    for day, day_tours in tours_by_day.items():
        # Always generate 1er blocks (fallback guarantee)
        for tour in day_tours:
            all_blocks.append(Block(
                id=f"B1-{tour.id}",
                day=day,
                tours=[tour]
            ))
        
        # Generate 2er blocks
        for i, t1 in enumerate(day_tours):
            for t2 in day_tours[i + 1:]:
                if _can_combine_tours(t1, t2):
                    all_blocks.append(Block(
                        id=f"B2-{t1.id}-{t2.id}",
                        day=day,
                        tours=[t1, t2]
                    ))
        
        # Generate 3er blocks
        for i, t1 in enumerate(day_tours):
            for j, t2 in enumerate(day_tours[i + 1:], start=i + 1):
                if not _can_combine_tours(t1, t2):
                    continue
                for t3 in day_tours[j + 1:]:
                    if _can_combine_tours(t2, t3) and _span_ok([t1, t2, t3]):
                        all_blocks.append(Block(
                            id=f"B3-{t1.id}-{t2.id}-{t3.id}",
                            day=day,
                            tours=[t1, t2, t3]
                        ))
    
    return all_blocks


def _can_combine_tours(t1: Tour, t2: Tour) -> bool:
    """Check if two tours can be combined into a block."""
    if t1.day != t2.day:
        return False
    
    # Ensure t1 is before t2
    if t1.start_time > t2.start_time:
        t1, t2 = t2, t1
    
    # Calculate gap
    t1_end = t1.end_time.hour * 60 + t1.end_time.minute
    t2_start = t2.start_time.hour * 60 + t2.start_time.minute
    gap_minutes = t2_start - t1_end
    
    # Check gap constraints
    if gap_minutes < HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS:
        return False
    if gap_minutes > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS:
        return False
    
    return True


def _span_ok(tours: list[Tour]) -> bool:
    """Check if block span is within limits."""
    if not tours:
        return True
    
    starts = [t.start_time.hour * 60 + t.start_time.minute for t in tours]
    ends = [t.end_time.hour * 60 + t.end_time.minute for t in tours]
    
    span_minutes = max(ends) - min(starts)
    span_hours = span_minutes / 60.0
    
    return span_hours <= HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS


def build_block_index(blocks: list[Block]) -> dict[str, list[Block]]:
    """
    Build index mapping tour_id → list of blocks containing that tour.
    
    Returns:
        Dictionary where keys are tour IDs and values are lists of blocks
    """
    index: dict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        for tour in block.tours:
            index[tour.id].append(block)
    return dict(index)


def verify_coverage(tours: list[Tour], blocks: list[Block]) -> tuple[bool, list[str]]:
    """
    Verify that every tour has at least one block.
    
    Returns:
        (is_complete, list of tour_ids with zero blocks)
    """
    index = build_block_index(blocks)
    missing = [t.id for t in tours if t.id not in index or len(index[t.id]) == 0]
    return (len(missing) == 0, missing)


def get_block_pool_stats(blocks: list[Block]) -> dict:
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
