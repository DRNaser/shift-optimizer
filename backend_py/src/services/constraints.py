"""
Constraints Service
===================
Central logic for validating assignments (Greedy & Validator).
Enforces STRICT 11-hour rest rule.
"""

from datetime import time
from dataclasses import dataclass
from typing import List, Optional

from src.domain.models import Block, Weekday

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

MIN_REST_MINUTES = 11 * 60  # 660 minutes = 11 hours
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
    )

# -----------------------------------------------------------------------------
# CORE LOGIC
# -----------------------------------------------------------------------------

def can_assign_block(
    existing_blocks: List[Block],
    new_block: Block,
    min_rest_mins: int = MIN_REST_MINUTES
) -> tuple[bool, str]:
    """
    Check if new_block can be assigned to driver with existing_blocks.
    
    Checks:
    1. No overlap via boolean array or interval check? 
       Using Global Timestamp check for simplicity and robustness.
    2. Rest time >= 11h (660 min) between any two blocks.
    
    Returns:
        (allowed: bool, reason: str)
    """
    # 1. Convert all to linear time blocks
    blocks = [to_time_block(b) for b in existing_blocks]
    candidate = to_time_block(new_block)
    
    # Insert candidate into sorted list based on start time
    blocks.append(candidate)
    blocks.sort(key=lambda b: b.start_timestamp_min)
    
    # 2. Iterate and check gaps
    for i in range(len(blocks) - 1):
        current = blocks[i]
        next_block = blocks[i+1]
        
        # A) Overlap check
        # If current ends after next starts -> Overlap
        if current.end_timestamp_min > next_block.start_timestamp_min:
            msg = (f"Overlap: Block {current.block_id} ends {current.end_timestamp_min} "
                   f"> {next_block.block_id} starts {next_block.start_timestamp_min}")
            return False, msg
            
        # B) Rest check
        gap = next_block.start_timestamp_min - current.end_timestamp_min
        if gap < min_rest_mins:
            hours = gap / 60.0
            msg = (f"Rest Violation: {hours:.2f}h < 11h between "
                   f"{current.block_id} (Day {current.day_idx}) and "
                   f"{next_block.block_id} (Day {next_block.day_idx})")
            return False, msg
            
    return True, "OK"
