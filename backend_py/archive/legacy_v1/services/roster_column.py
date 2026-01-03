"""
RosterColumn - Valid Weekly Driver Roster for Set-Partitioning

A RosterColumn represents a complete, valid weekly schedule for one driver.
It contains a set of blocks and is guaranteed to satisfy all hard constraints
BEFORE entering the column pool.

Hard Constraints (checked in validate_roster):
- No overlap on same day (span-based: start_min to end_min)
- Max 3 tours per day
- Min 11h rest between consecutive working days
- Heavy day (3 tours): 14h rest + next day max 2 tours
- Week hours: 42h <= total_hours <= 53h
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger("RosterColumn")

# Constants
MIN_WEEK_HOURS = 40.0  # Soft target for FTE hours (penalized in objective, not hard)
MAX_WEEK_HOURS = 55.0
MIN_REST_MINUTES = 660  # 11h
HEAVY_REST_MINUTES = 660  # 11h (relaxed from 14h as per tuning request)
DAY_MINUTES = 1440  # 24h
MAX_TOURS_PER_DAY = 3
MAX_TOURS_AFTER_HEAVY = 2


@dataclass(frozen=True)
class RosterColumn:
    """
    Immutable representation of a valid weekly driver roster.
    
    Attributes:
        roster_id: Unique identifier (e.g., "R001")
        block_ids: Frozen set of block IDs in this roster
        total_minutes: Total work minutes for the week
        day_stats: Dict[day_idx] -> {tours, first_start, last_end}
        is_valid: Whether roster passes all hard constraints
        violations: Tuple of violation descriptions (for debugging)
        signature: Canonical tuple for deduplication
        roster_type: "FTE" (40-53h) or "PT" (0-40h)
        covered_tour_ids: frozenset = frozenset()
    """
    roster_id: str
    block_ids: frozenset
    total_minutes: int
    day_stats: tuple  # Immutable: ((day, tours, first_start, last_end), ...)
    is_valid: bool
    violations: tuple
    signature: tuple
    roster_type: str = "FTE"  # "FTE" or "PT"
    covered_tour_ids: frozenset = frozenset()
    
    @property
    def total_hours(self) -> float:
        return self.total_minutes / 60.0
    
    @property
    def num_blocks(self) -> int:
        return len(self.block_ids)
    
    def get_day_stat(self, day: int) -> dict:
        """Get stats for a specific day."""
        for d, tours, first, last in self.day_stats:
            if d == day:
                return {"tours": tours, "first_start": first, "last_end": last}
        return {"tours": 0, "first_start": None, "last_end": None}
    
    def contains_block(self, block_id: str) -> bool:
        return block_id in self.block_ids
    
    def __repr__(self):
        hours = self.total_hours
        blocks = len(self.block_ids)
        valid = "✓" if self.is_valid else "✗"
        return f"RosterColumn({self.roster_id}, {blocks} blocks, {hours:.1f}h, {valid})"


@dataclass
class BlockInfo:
    """Cached block metadata for fast validation."""
    block_id: str
    day: int  # 0=Mon, 6=Sun
    start_min: int  # Minutes from midnight
    end_min: int  # Minutes from midnight
    work_min: int  # Actual work duration
    tours: int  # Number of tours in this block
    tour_ids: tuple = ()  # Tuple of tour IDs covered by this block


def create_roster_from_blocks(
    roster_id: str,
    block_infos: list[BlockInfo],
) -> RosterColumn:
    """
    Create a RosterColumn from a list of BlockInfo objects.
    
    Validates all hard constraints and sets is_valid/violations accordingly.
    """
    if not block_infos:
        return RosterColumn(
            roster_id=roster_id,
            block_ids=frozenset(),
            total_minutes=0,
            day_stats=(),
            is_valid=False,
            violations=("Empty roster",),
            signature=(frozenset(), 0),
        )
    
    # Extract block IDs
    # Extract block IDs
    block_ids = frozenset(b.block_id for b in block_infos)
    
    # Extract Tour IDs
    tour_ids = set()
    for b in block_infos:
        if b.tour_ids:
            tour_ids.update(b.tour_ids)
    covered_tour_ids = frozenset(tour_ids)
    
    # Calculate total work minutes
    total_minutes = sum(b.work_min for b in block_infos)
    
    # Build day stats
    day_blocks = {d: [] for d in range(7)}
    for b in block_infos:
        day_blocks[b.day].append(b)
    
    day_stats_list = []
    for d in range(7):
        blocks = day_blocks[d]
        if not blocks:
            continue
        
        tours = sum(b.tours for b in blocks)
        first_start = min(b.start_min for b in blocks)
        last_end = max(b.end_min for b in blocks)
        day_stats_list.append((d, tours, first_start, last_end))
    
    day_stats = tuple(day_stats_list)
    
    # Validate and collect violations
    violations = validate_roster_constraints(block_infos, total_minutes, day_stats)
    is_valid = len(violations) == 0
    
    # Create signature for deduplication
    # Canonical: sorted block IDs + total minutes + day tours pattern
    sorted_ids = tuple(sorted(block_ids))
    day_tours = tuple((d, t) for d, t, _, _ in day_stats)
    signature = (sorted_ids, total_minutes, day_tours)
    
    return RosterColumn(
        roster_id=roster_id,
        block_ids=block_ids,
        total_minutes=total_minutes,
        day_stats=day_stats,
        is_valid=is_valid,
        violations=tuple(violations),
        signature=signature,
        roster_type="FTE",
        covered_tour_ids=covered_tour_ids,
    )


def validate_roster_constraints(
    block_infos: list[BlockInfo],
    total_minutes: int,
    day_stats: tuple,
    allow_pt: bool = False,
) -> list[str]:
    """
    Validate all hard constraints.
    Returns list of violation descriptions (empty = valid).
    
    Constraints:
    1. No overlap on same day (span-based)
    2. Max 3 tours per day
    3. Min 11h rest between consecutive working days
    4. Heavy day: 14h rest + next day max 2 tours
    5. Week hours: 42-53h (or 0-53h if allow_pt=True)
    
    Args:
        allow_pt: If True, skip minimum hours check (allow 0-40h PT rosters)
    """
    violations = []
    
    # Group blocks by day
    day_blocks = {d: [] for d in range(7)}
    for b in block_infos:
        day_blocks[b.day].append(b)
    
    # Build day stats dict for easier access
    day_info = {}
    for d, tours, first_start, last_end in day_stats:
        day_info[d] = {"tours": tours, "first_start": first_start, "last_end": last_end}
    
    # =========================================================================
    # 1. NO OVERLAP (span-based: start_min to end_min)
    # =========================================================================
    for d in range(7):
        blocks = day_blocks[d]
        if len(blocks) < 2:
            continue
        
        # Sort by start time
        sorted_blocks = sorted(blocks, key=lambda b: b.start_min)
        for i in range(len(sorted_blocks) - 1):
            b1 = sorted_blocks[i]
            b2 = sorted_blocks[i + 1]
            
            # Overlap if b1.end > b2.start
            if b1.end_min > b2.start_min:
                violations.append(
                    f"Overlap on day {d}: {b1.block_id} ends at {b1.end_min} "
                    f"but {b2.block_id} starts at {b2.start_min}"
                )
    
    # =========================================================================
    # 2. MAX TOURS PER DAY (<=3)
    # =========================================================================
    for d, info in day_info.items():
        if info["tours"] > MAX_TOURS_PER_DAY:
            violations.append(
                f"Day {d} has {info['tours']} tours > max {MAX_TOURS_PER_DAY}"
            )
    
    # =========================================================================
    # 3. MIN REST 11h BETWEEN CONSECUTIVE DAYS
    # =========================================================================
    for d in range(6):  # Mon-Sat
        if d not in day_info or (d + 1) not in day_info:
            continue  # One of the days is off
        
        last_end = day_info[d]["last_end"]
        next_first = day_info[d + 1]["first_start"]
        
        # Rest = next_first + DAY_MINUTES - last_end
        rest = next_first + DAY_MINUTES - last_end
        
        if rest < MIN_REST_MINUTES:
            violations.append(
                f"Rest between day {d} and {d+1}: {rest} min < {MIN_REST_MINUTES} min (11h)"
            )
    
    # =========================================================================
    # 4. HEAVY DAY: 14h REST + NEXT DAY MAX 2 TOURS
    # =========================================================================
    for d in range(6):  # Mon-Sat (can have next day)
        if d not in day_info:
            continue
        
        if day_info[d]["tours"] == 3:  # Heavy day
            # Check 14h rest to next day (if working)
            if (d + 1) in day_info:
                last_end = day_info[d]["last_end"]
                next_first = day_info[d + 1]["first_start"]
                rest = next_first + DAY_MINUTES - last_end
                
                if rest < HEAVY_REST_MINUTES:
                    violations.append(
                        f"Heavy day {d}: rest to day {d+1} is {rest} min < {HEAVY_REST_MINUTES} min (14h)"
                    )
                
                # Check next day max 2 tours
                next_tours = day_info[d + 1]["tours"]
                if next_tours > MAX_TOURS_AFTER_HEAVY:
                    violations.append(
                        f"Heavy day {d}: next day {d+1} has {next_tours} tours > max {MAX_TOURS_AFTER_HEAVY}"
                    )
    
    # =========================================================================
    # 5. WEEK HOURS: enforce max hours only (min handled in objective)
    # =========================================================================
    total_hours = total_minutes / 60.0
    
    # Note: Minimum hours are now a soft cost, not a hard constraint
    # This allows the solver to use slightly under-filled FTEs when optimal
    
    if total_hours > MAX_WEEK_HOURS:
        violations.append(
            f"Week hours {total_hours:.1f}h > max {MAX_WEEK_HOURS}h"
        )
    
    return violations


def create_roster_from_blocks_pt(
    roster_id: str,
    block_infos: list[BlockInfo],
) -> RosterColumn:
    """
    Create a PT (Part-Time) RosterColumn from a list of BlockInfo objects.
    
    Allows 0-40h rosters. Validates all constraints except minimum hours.
    """
    if not block_infos:
        return RosterColumn(
            roster_id=roster_id,
            block_ids=frozenset(),
            total_minutes=0,
            day_stats=(),
            is_valid=False,
            violations=("Empty roster",),
            signature=(frozenset(), 0),
            roster_type="PT",
        )
    
    # Extract block IDs
    # Extract block IDs
    block_ids = frozenset(b.block_id for b in block_infos)
    
    # Extract Tour IDs
    tour_ids = set()
    for b in block_infos:
        if b.tour_ids:
            tour_ids.update(b.tour_ids)
    covered_tour_ids = frozenset(tour_ids)
    
    # Calculate total work minutes
    total_minutes = sum(b.work_min for b in block_infos)
    
    # Build day stats
    day_blocks = {d: [] for d in range(7)}
    for b in block_infos:
        day_blocks[b.day].append(b)
    
    day_stats_list = []
    for d in range(7):
        blocks = day_blocks[d]
        if not blocks:
            continue
        
        tours = sum(b.tours for b in blocks)
        first_start = min(b.start_min for b in blocks)
        last_end = max(b.end_min for b in blocks)
        day_stats_list.append((d, tours, first_start, last_end))
    
    day_stats = tuple(day_stats_list)
    
    # Validate with PT allowed (skip min hours check)
    violations = validate_roster_constraints(block_infos, total_minutes, day_stats, allow_pt=True)
    is_valid = len(violations) == 0
    
    # Create signature for deduplication
    sorted_ids = tuple(sorted(block_ids))
    day_tours = tuple((d, t) for d, t, _, _ in day_stats)
    signature = (sorted_ids, total_minutes, day_tours, "PT")  # Include type in signature
    
    return RosterColumn(
        roster_id=roster_id,
        block_ids=block_ids,
        total_minutes=total_minutes,
        day_stats=day_stats,
        is_valid=is_valid,
        violations=tuple(violations),
        signature=signature,
        roster_type="PT",
        covered_tour_ids=covered_tour_ids,
    )


def can_add_block_to_roster(
    existing_blocks: list[BlockInfo],
    new_block: BlockInfo,
    current_minutes: int,
) -> tuple[bool, str]:
    """
    Fast check if adding a block to a roster would violate constraints.
    
    Returns (can_add, reason) - reason is empty if can_add=True.
    
    This is an incremental check for performance during roster building.
    It checks:
    - Overlap with existing blocks on the same day
    - Tours count on the day (<=3)
    - Rest constraints with adjacent days
    - Week hours not exceeding max (53h)
    
    Note: Does NOT check if hours will reach min (42h) - that's the builder's job.
    """
    # Group existing blocks by day
    day_blocks = {d: [] for d in range(7)}
    for b in existing_blocks:
        day_blocks[b.day].append(b)
    
    new_day = new_block.day
    
    # =========================================================================
    # CHECK 1: Overlap with existing blocks on same day
    # =========================================================================
    for b in day_blocks[new_day]:
        # Overlap if NOT (new.end <= b.start OR new.start >= b.end)
        if not (new_block.end_min <= b.start_min or new_block.start_min >= b.end_min):
            return False, f"Overlap with {b.block_id} on day {new_day}"
    
    # =========================================================================
    # CHECK 2: Tours count on new day
    # =========================================================================
    day_tours = sum(b.tours for b in day_blocks[new_day]) + new_block.tours
    if day_tours > MAX_TOURS_PER_DAY:
        return False, f"Day {new_day} would have {day_tours} tours > {MAX_TOURS_PER_DAY}"
    
    # =========================================================================
    # CHECK 3: Week hours not exceeding max
    # =========================================================================
    new_total_minutes = current_minutes + new_block.work_min
    if new_total_minutes > MAX_WEEK_HOURS * 60:
        return False, f"Would exceed {MAX_WEEK_HOURS}h"
    
    # =========================================================================
    # CHECK 4: Rest constraints (11h basic, 14h after heavy)
    # =========================================================================
    
    # Get day stats for adjacent days
    def get_day_stats(day: int) -> tuple[int, int, int]:
        """Returns (tours, first_start, last_end) for a day."""
        blocks = day_blocks[day]
        if not blocks:
            return (0, None, None)
        tours = sum(b.tours for b in blocks)
        first = min(b.start_min for b in blocks)
        last = max(b.end_min for b in blocks)
        return (tours, first, last)
    
    # Get stats including new block
    def get_day_stats_with_new(day: int) -> tuple[int, int, int]:
        blks = day_blocks[day].copy()
        if day == new_day:
            blks.append(new_block)
        if not blks:
            return (0, None, None)
        tours = sum(b.tours for b in blks)
        first = min(b.start_min for b in blks)
        last = max(b.end_min for b in blks)
        return (tours, first, last)
    
    # Check rest with previous day
    if new_day > 0:
        prev_tours, prev_first, prev_last = get_day_stats(new_day - 1)
        if prev_last is not None:
            cur_tours, cur_first, cur_last = get_day_stats_with_new(new_day)
            rest = cur_first + DAY_MINUTES - prev_last
            
            min_required = HEAVY_REST_MINUTES if prev_tours == 3 else MIN_REST_MINUTES
            if rest < min_required:
                return False, f"Rest from day {new_day-1}: {rest} min < {min_required} min"
            
            # Check heavy-day next-day tours limit
            if prev_tours == 3 and cur_tours > MAX_TOURS_AFTER_HEAVY:
                return False, f"After heavy day {new_day-1}: {cur_tours} tours > {MAX_TOURS_AFTER_HEAVY}"
    
    # Check rest with next day
    if new_day < 6:
        next_tours, next_first, next_last = get_day_stats(new_day + 1)
        if next_first is not None:
            cur_tours, cur_first, cur_last = get_day_stats_with_new(new_day)
            rest = next_first + DAY_MINUTES - cur_last
            
            min_required = HEAVY_REST_MINUTES if cur_tours == 3 else MIN_REST_MINUTES
            if rest < min_required:
                return False, f"Rest to day {new_day+1}: {rest} min < {min_required} min"
            
            # Check heavy-day next-day tours limit
            if cur_tours == 3 and next_tours > MAX_TOURS_AFTER_HEAVY:
                return False, f"Heavy day {new_day}: next has {next_tours} tours > {MAX_TOURS_AFTER_HEAVY}"
    
    return True, ""
