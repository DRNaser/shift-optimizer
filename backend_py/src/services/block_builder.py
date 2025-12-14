"""
SHIFT OPTIMIZER - Block Builder
================================
Transforms Tours into possible Blocks.

This is a GENERATION component - it creates candidate blocks.
The Validator decides which are valid.
The Scheduler decides which to assign.
"""

from collections import defaultdict
from itertools import combinations
from typing import Iterator
import uuid

from src.domain.models import Tour, Block, Weekday
from src.domain.constraints import HARD_CONSTRAINTS


def generate_block_id() -> str:
    """Generate a unique block ID."""
    return f"B-{uuid.uuid4().hex[:8]}"


def tours_can_combine(tour1: Tour, tour2: Tour) -> bool:
    """
    Check if two tours can be combined into a block.
    
    Rules:
    - Must be on same day
    - Must not overlap
    - Gap must be within allowed pause range
    - tour1 must end before tour2 starts
    """
    # Must be same day
    if tour1.day != tour2.day:
        return False
    
    # tour1 must end before tour2 starts
    t1_end = tour1.end_time.hour * 60 + tour1.end_time.minute
    t2_start = tour2.start_time.hour * 60 + tour2.start_time.minute
    
    gap_minutes = t2_start - t1_end
    
    # Must not overlap (gap must be non-negative)
    if gap_minutes < HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS:
        return False
    
    # Gap must not be too large
    if gap_minutes > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS:
        return False
    
    return True


# =============================================================================
# SPAN HELPERS (for MAX_DAILY_SPAN enforcement)
# =============================================================================

def _minutes(t) -> int:
    """Convert time to minutes since midnight."""
    return t.hour * 60 + t.minute


def _tour_start_end_minutes(tour: Tour) -> tuple[int, int]:
    """Get tour start/end in minutes, handling cross-midnight."""
    s = _minutes(tour.start_time)
    e = _minutes(tour.end_time)
    if e < s:
        e += 24 * 60  # crosses midnight
    return s, e


def _span_hours(tours: list[Tour]) -> float:
    """Calculate span from first start to last end in hours."""
    starts, ends = [], []
    for t in tours:
        s, e = _tour_start_end_minutes(t)
        starts.append(s)
        ends.append(e)
    return (max(ends) - min(starts)) / 60.0


def build_all_possible_blocks(tours: list[Tour]) -> list[Block]:
    """
    Generate ALL possible blocks from a list of tours.
    
    Creates:
    - All single-tour blocks (1er)
    - All valid two-tour blocks (2er)
    - All valid three-tour blocks (3er)
    
    Returns blocks sorted by day, then by start time.
    Note: Some blocks may be invalid due to span constraints,
    but that's for the Validator to decide.
    """
    blocks: list[Block] = []
    
    # Group tours by day
    tours_by_day: dict[Weekday, list[Tour]] = defaultdict(list)
    for tour in tours:
        tours_by_day[tour.day].append(tour)
    
    # Sort tours within each day by start time
    for day in tours_by_day:
        tours_by_day[day].sort(key=lambda t: t.start_time)
    
    # Process each day
    for day, day_tours in tours_by_day.items():
        # Generate all block sizes
        blocks.extend(_generate_single_blocks(day, day_tours))
        blocks.extend(_generate_double_blocks(day, day_tours))
        blocks.extend(_generate_triple_blocks(day, day_tours))
    
    # Sort blocks by day, then by start time
    blocks.sort(key=lambda b: (list(Weekday).index(b.day), b.first_start))
    
    return blocks


def _generate_single_blocks(day: Weekday, tours: list[Tour]) -> Iterator[Block]:
    """Generate all single-tour blocks."""
    for tour in tours:
        yield Block(
            id=generate_block_id(),
            day=day,
            tours=[tour]
        )


def _generate_double_blocks(day: Weekday, tours: list[Tour]) -> Iterator[Block]:
    """Generate all valid two-tour blocks."""
    for i, t1 in enumerate(tours):
        for t2 in tours[i + 1:]:
            if tours_can_combine(t1, t2):
                yield Block(
                    id=generate_block_id(),
                    day=day,
                    tours=[t1, t2]
                )


def _generate_triple_blocks(day: Weekday, tours: list[Tour]) -> Iterator[Block]:
    """Generate all valid three-tour blocks."""
    for i, t1 in enumerate(tours):
        for j, t2 in enumerate(tours[i + 1:], start=i + 1):
            if not tours_can_combine(t1, t2):
                continue
            for t3 in tours[j + 1:]:
                if tours_can_combine(t2, t3):
                    yield Block(
                        id=generate_block_id(),
                        day=day,
                        tours=[t1, t2, t3]
                    )


def build_blocks_greedy(
    tours: list[Tour],
    prefer_larger: bool = True
) -> list[Block]:
    """
    Build blocks greedily, prioritizing larger blocks.
    
    This is a simple heuristic - not optimal, but fast.
    Each tour is used in exactly one block.
    
    Strategy:
    1. Sort tours by day, then start time
    2. If prefer_larger: try to form 3er blocks first, then 2er, then 1er
    3. Mark tours as used when assigned to a block
    
    Returns: List of blocks covering all tours
    """
    # Group and sort tours by day
    tours_by_day: dict[Weekday, list[Tour]] = defaultdict(list)
    for tour in tours:
        tours_by_day[tour.day].append(tour)
    
    for day in tours_by_day:
        tours_by_day[day].sort(key=lambda t: t.start_time)
    
    blocks: list[Block] = []
    
    for day, day_tours in tours_by_day.items():
        used = [False] * len(day_tours)
        
        if prefer_larger:
            # Try 3er blocks first
            for i in range(len(day_tours)):
                if used[i]:
                    continue
                for j in range(i + 1, len(day_tours)):
                    if used[j]:
                        continue
                    if not tours_can_combine(day_tours[i], day_tours[j]):
                        continue
                    for k in range(j + 1, len(day_tours)):
                        if used[k]:
                            continue
                        if tours_can_combine(day_tours[j], day_tours[k]):
                            # CHECK: Block span must not exceed MAX_DAILY_SPAN
                            candidate_tours = [day_tours[i], day_tours[j], day_tours[k]]
                            if _span_hours(candidate_tours) <= HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS:
                                blocks.append(Block(
                                    id=generate_block_id(),
                                    day=day,
                                    tours=candidate_tours
                                ))
                                used[i] = used[j] = used[k] = True
                                break
                            # else: span too large -> keep searching for another k
                    if used[i]:
                        break
            
            # Try 2er blocks
            for i in range(len(day_tours)):
                if used[i]:
                    continue
                for j in range(i + 1, len(day_tours)):
                    if used[j]:
                        continue
                    if tours_can_combine(day_tours[i], day_tours[j]):
                        # CHECK: Block span must not exceed MAX_DAILY_SPAN
                        candidate_tours = [day_tours[i], day_tours[j]]
                        if _span_hours(candidate_tours) <= HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS:
                            blocks.append(Block(
                                id=generate_block_id(),
                                day=day,
                                tours=candidate_tours
                            ))
                            used[i] = used[j] = True
                            break
                        # else: span too large -> keep searching for another j
        
        # Remaining tours become 1er blocks
        for i, tour in enumerate(day_tours):
            if not used[i]:
                blocks.append(Block(
                    id=generate_block_id(),
                    day=day,
                    tours=[tour]
                ))
    
    # Sort blocks
    blocks.sort(key=lambda b: (list(Weekday).index(b.day), b.first_start))
    
    return blocks


class BlockBuilder:
    """
    Main Block Builder service.
    
    Provides methods for building blocks from tours.
    """
    
    def __init__(self, tours: list[Tour]):
        self.tours = tours
        self._all_blocks: list[Block] | None = None
        self._greedy_blocks: list[Block] | None = None
    
    @property
    def all_possible_blocks(self) -> list[Block]:
        """Get all possible blocks (cached)."""
        if self._all_blocks is None:
            self._all_blocks = build_all_possible_blocks(self.tours)
        return self._all_blocks
    
    @property
    def greedy_blocks(self) -> list[Block]:
        """Get greedy block assignment (cached)."""
        if self._greedy_blocks is None:
            self._greedy_blocks = build_blocks_greedy(self.tours)
        return self._greedy_blocks
    
    def get_blocks_by_day(self, day: Weekday) -> list[Block]:
        """Get all possible blocks for a specific day."""
        return [b for b in self.all_possible_blocks if b.day == day]
    
    def get_blocks_containing_tour(self, tour_id: str) -> list[Block]:
        """Get all blocks containing a specific tour."""
        return [
            b for b in self.all_possible_blocks
            if any(t.id == tour_id for t in b.tours)
        ]
    
    def get_stats(self) -> dict:
        """Get statistics about generated blocks."""
        all_blocks = self.all_possible_blocks
        
        # Count tours per day
        tours_per_day = {}
        for tour in self.tours:
            tours_per_day[tour.day.value] = tours_per_day.get(tour.day.value, 0) + 1
        
        return {
            "total_tours": len(self.tours),
            "tours_per_day": tours_per_day,
            "total_possible_blocks": len(all_blocks),
            "blocks_by_type": {
                "1er": sum(1 for b in all_blocks if len(b.tours) == 1),
                "2er": sum(1 for b in all_blocks if len(b.tours) == 2),
                "3er": sum(1 for b in all_blocks if len(b.tours) == 3),
            },
            "greedy_solution": {
                "total_blocks": len(self.greedy_blocks),
                "blocks_by_type": {
                    "1er": sum(1 for b in self.greedy_blocks if len(b.tours) == 1),
                    "2er": sum(1 for b in self.greedy_blocks if len(b.tours) == 2),
                    "3er": sum(1 for b in self.greedy_blocks if len(b.tours) == 3),
                }
            }
        }
    
    def analyze_combination_failures(self, sample_size: int = 50) -> dict:
        """
        Analyze why tours cannot be combined.
        
        Returns:
            dict with:
            - rejection_reasons: Counter of why tour pairs were rejected
            - sample_near_misses: Sample of tours that almost combined
            - total_pairs_analyzed: Total number of tour pairs checked
        """
        from collections import Counter
        import random
        
        rejection_reasons = Counter()
        near_misses = []  # Pairs that were close (e.g. gap 25-35 or 115-125)
        total_pairs = 0
        
        # Analyze all tour pairs within same day
        tours_by_day = defaultdict(list)
        for tour in self.tours:
            tours_by_day[tour.day].append(tour)
        
        for day, day_tours in tours_by_day.items():
            # Sort by start time
            day_tours.sort(key=lambda t: t.start_time)
            
            for i, t1 in enumerate(day_tours):
                for t2 in day_tours[i + 1:]:
                    total_pairs += 1
                    
                    # Calculate gap
                    t1_end = t1.end_time.hour * 60 + t1.end_time.minute
                    t2_start = t2.start_time.hour * 60 + t2.start_time.minute
                    gap_minutes = t2_start - t1_end
                    
                    # Check rejection reasons
                    if gap_minutes < HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS:
                        if gap_minutes < 0:
                            rejection_reasons["overlap"] += 1
                        else:
                            rejection_reasons["gap_too_small"] += 1
                            
                        # Near miss: gap is 25-35 min (close to MIN_PAUSE=30)
                        if 25 <= gap_minutes < HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS:
                            near_misses.append({
                                "tour1": t1.id,
                                "tour1_time": f"{t1.start_time}-{t1.end_time}",
                                "tour2": t2.id,
                                "tour2_time": f"{t2.start_time}-{t2.end_time}",
                                "gap_minutes": gap_minutes,
                                "reason": "gap_too_small",
                                "note": f"Only {HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS - gap_minutes} min short"
                            })
                    
                    elif gap_minutes > HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS:
                        rejection_reasons["gap_too_large"] += 1
                        
                        # Near miss: gap is 115-125 min (close to MAX_PAUSE=120)
                        if gap_minutes <= 125:
                            near_misses.append({
                                "tour1": t1.id,
                                "tour1_time": f"{t1.start_time}-{t1.end_time}",
                                "tour2": t2.id,
                                "tour2_time": f"{t2.start_time}-{t2.end_time}",
                                "gap_minutes": gap_minutes,
                                "reason": "gap_too_large",
                                "note": f"Only {gap_minutes - HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS} min over"
                            })
        
        # Sample near misses
        sampled_near_misses = random.sample(
            near_misses, 
            min(sample_size, len(near_misses))
        ) if near_misses else []
        
        return {
            "total_pairs_analyzed": total_pairs,
            "rejection_reasons": dict(rejection_reasons),
            "total_rejections": sum(rejection_reasons.values()),
            "successful_combinations": total_pairs - sum(rejection_reasons.values()),
            "sample_near_misses": sampled_near_misses,
            "constraints": {
                "MIN_PAUSE_MINUTES": HARD_CONSTRAINTS.MIN_PAUSE_BETWEEN_TOURS,
                "MAX_PAUSE_MINUTES": HARD_CONSTRAINTS.MAX_PAUSE_BETWEEN_TOURS,
            }
        }
