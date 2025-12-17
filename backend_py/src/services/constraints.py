"""
Constraints Service
===================
Central logic for validating assignments (Greedy & Validator).
Enforces STRICT 11-hour rest rule + 3-tour recovery (14h rest, max 2 tours next day).
"""

from datetime import time
from dataclasses import dataclass
from typing import List, Optional

from src.domain.models import Block, Weekday

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

MIN_REST_MINUTES = 11 * 60  # 660 minutes = 11 hours
MIN_REST_AFTER_3T_MINUTES = 14 * 60  # 840 minutes = 14 hours after 3-tour day
MAX_NEXT_DAY_TOURS_AFTER_3T = 2  # Max tours allowed after 3-tour day
DAY_MINUTES = 24 * 60

WEEKDAY_ORDER = {
    "MONDAY": 0, "MON": 0,
    "TUESDAY": 1, "TUE": 1,
    "WEDNESDAY": 2, "WED": 2,
    "THURSDAY": 3, "THU": 3,
    "FRIDAY": 4, "FRI": 4,
    "SATURDAY": 5, "SAT": 5,
    "SUNDAY": 6, "SUN": 6,
}

# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def time_to_minutes(t: time) -> int:
    """Convert time object to minutes from midnight."""
    return t.hour * 60 + t.minute

def get_day_index(day: Weekday) -> int:
    """Get 0-6 index for weekday."""
    key = day.value.upper() if hasattr(day, "value") else str(day).upper()
    # Handle "Weekday.MONDAY" string repr if necessary
    if "." in key:
        key = key.split(".")[-1]
    return WEEKDAY_ORDER.get(key, 0)

@dataclass
class TimeBlock:
    """Simplified block representation for validation."""
    block_id: str
    day_idx: int
    start_min: int
    end_min: int
    tour_count: int = 1  # Number of tours in this block

    @property
    def end_timestamp_min(self) -> int:
        """Global minute timestamp for end of block (relative to week start)."""
        return self.day_idx * DAY_MINUTES + self.end_min

    @property
    def start_timestamp_min(self) -> int:
        """Global minute timestamp for start of block (relative to week start)."""
        return self.day_idx * DAY_MINUTES + self.start_min

def to_time_block(block: Block) -> TimeBlock:
    """Convert Domain Block to TimeBlock."""
    return TimeBlock(
        block_id=block.id,
        day_idx=get_day_index(block.day),
        start_min=time_to_minutes(block.first_start),
        end_min=time_to_minutes(block.last_end),
        tour_count=len(block.tours) if hasattr(block, 'tours') else 1,
    )

# -----------------------------------------------------------------------------
# CORE LOGIC
# -----------------------------------------------------------------------------

def can_assign_block(
    existing_blocks: List[Block],
    new_block: Block,
    min_rest_mins: int = MIN_REST_MINUTES,
    min_rest_after_3t_mins: int = MIN_REST_AFTER_3T_MINUTES,
    max_next_day_tours_after_3t: int = MAX_NEXT_DAY_TOURS_AFTER_3T
) -> tuple[bool, str]:
    """
    Check if new_block can be assigned to driver with existing_blocks.
    
    Checks:
    1. No overlap between blocks
    2. Rest time >= 11h (660 min) between any two blocks
    3. 3-tour recovery: After a 3-tour day:
       - 14h rest required to next day
       - Next day limited to max 2 tours
    
    Returns:
        (allowed: bool, reason: str)
    """
    # 1. Convert all to time blocks
    blocks = [to_time_block(b) for b in existing_blocks]
    candidate = to_time_block(new_block)
    
    # Insert candidate into sorted list based on start time
    blocks.append(candidate)
    blocks.sort(key=lambda b: b.start_timestamp_min)
    
    # Helper: count total tours on a specific day
    def tours_for_day(day_idx: int, include_candidate: bool = True) -> int:
        day_blocks = [b for b in existing_blocks if get_day_index(b.day) == day_idx]
        total = sum(len(b.tours) if hasattr(b, 'tours') else 1 for b in day_blocks)
        if include_candidate and get_day_index(new_block.day) == day_idx:
            total += len(new_block.tours) if hasattr(new_block, 'tours') else 1
        return total
    
    # Helper: get last end time for a day
    def get_day_end_min(day_idx: int) -> Optional[int]:
        day_blocks = [b for b in existing_blocks if get_day_index(b.day) == day_idx]
        if not day_blocks:
            return None
        return max(time_to_minutes(b.last_end) for b in day_blocks)
    
    # Helper: get first start time for a day
    def get_day_start_min(day_idx: int) -> Optional[int]:
        day_blocks = [b for b in existing_blocks if get_day_index(b.day) == day_idx]
        if not day_blocks:
            return None
        return min(time_to_minutes(b.first_start) for b in day_blocks)
    
    candidate_day_idx = get_day_index(new_block.day)
    candidate_start_min = time_to_minutes(new_block.first_start)
    candidate_end_min = time_to_minutes(new_block.last_end)
    
    # 2. Iterate and check gaps (overlap + standard 11h rest)
    for i in range(len(blocks) - 1):
        current = blocks[i]
        next_block = blocks[i+1]
        
        # A) Overlap check
        if current.end_timestamp_min > next_block.start_timestamp_min:
            msg = (f"Overlap: Block {current.block_id} ends {current.end_timestamp_min} "
                   f"> {next_block.block_id} starts {next_block.start_timestamp_min}")
            return False, msg
            
        # B) Rest check (standard 11h)
        gap = next_block.start_timestamp_min - current.end_timestamp_min
        if gap < min_rest_mins:
            hours = gap / 60.0
            msg = (f"Rest Violation: {hours:.2f}h < 11h between "
                   f"{current.block_id} (Day {current.day_idx}) and "
                   f"{next_block.block_id} (Day {next_block.day_idx})")
            return False, msg
    
    # 3. 3-Tour Recovery Rule (updated: 14h rest + max 2 tours, not "day off")
    
    # Check A: If PREVIOUS day has 3+ tours, apply stricter rules to TODAY
    if candidate_day_idx > 0:
        prev_day_idx = candidate_day_idx - 1
        prev_day_tours = tours_for_day(prev_day_idx, include_candidate=False)
        
        if prev_day_tours >= 3:
            # HARD: Max 2 tours today after previous 3-tour day
            tours_today = tours_for_day(candidate_day_idx, include_candidate=True)
            if tours_today > max_next_day_tours_after_3t:
                msg = (f"3-Tour Recovery: Previous day (Day {prev_day_idx}) has {prev_day_tours} tours, "
                       f"today (Day {candidate_day_idx}) would have {tours_today} tours > max {max_next_day_tours_after_3t}")
                return False, msg
            
            # HARD: 14h rest from previous day to today
            prev_day_end = get_day_end_min(prev_day_idx)
            if prev_day_end is not None:
                rest_to_today = (candidate_start_min + DAY_MINUTES) - prev_day_end
                if rest_to_today < min_rest_after_3t_mins:
                    hours = rest_to_today / 60.0
                    msg = (f"3-Tour Recovery: Only {hours:.1f}h rest from 3-tour day (Day {prev_day_idx}) "
                           f"to today, need {min_rest_after_3t_mins/60:.0f}h")
                    return False, msg
    
    # Check B: If TODAY becomes 3+ tours, check impact on TOMORROW
    tours_today = tours_for_day(candidate_day_idx, include_candidate=True)
    if tours_today >= 3 and candidate_day_idx < 6:
        next_day_idx = candidate_day_idx + 1
        
        # HARD: Check if tomorrow already has more than allowed tours
        tomorrow_tours = tours_for_day(next_day_idx, include_candidate=False)
        if tomorrow_tours > max_next_day_tours_after_3t:
            msg = (f"3-Tour Recovery: Adding block makes today (Day {candidate_day_idx}) have {tours_today} tours, "
                   f"but tomorrow (Day {next_day_idx}) already has {tomorrow_tours} tours > max {max_next_day_tours_after_3t}")
            return False, msg
        
        # HARD: Check 14h rest from today to tomorrow
        tomorrow_start = get_day_start_min(next_day_idx)
        if tomorrow_start is not None:
            rest_to_tomorrow = (tomorrow_start + DAY_MINUTES) - candidate_end_min
            if rest_to_tomorrow < min_rest_after_3t_mins:
                hours = rest_to_tomorrow / 60.0
                msg = (f"3-Tour Recovery: Only {hours:.1f}h rest from today (3-tour day {candidate_day_idx}) "
                       f"to tomorrow, need {min_rest_after_3t_mins/60:.0f}h")
                return False, msg
    
    return True, "OK"

