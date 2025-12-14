"""
SHIFT OPTIMIZER - Weekly Pattern Templates
============================================
Pre-defined weekly work patterns for drivers.

Patterns define:
- Which days a driver works
- How many blocks per day (1 or 2 for split shifts)
- Maximum tours per block
- Required rest days
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from .models import Weekday


# =============================================================================
# PATTERN DEFINITIONS
# =============================================================================

class PatternType(str, Enum):
    """Types of weekly patterns."""
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    SPLIT_SHIFT = "SPLIT_SHIFT"
    THREE_BY_THREE = "THREE_BY_THREE"
    WEEKEND = "WEEKEND"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class DaySlot:
    """Definition for a single day in a pattern."""
    blocks: int = 1        # Number of blocks (1 or 2 for split)
    max_tours: int = 3     # Max tours per day (across all blocks)
    is_rest: bool = False  # If True, this is a mandatory rest day
    
    def __post_init__(self):
        if self.is_rest and self.blocks > 0:
            object.__setattr__(self, 'blocks', 0)


@dataclass(frozen=True)
class WeeklyPattern:
    """
    A weekly work pattern template.
    
    Defines how a driver can be scheduled throughout the week.
    """
    id: str
    name: str
    description: str
    pattern_type: PatternType
    
    # Day-by-day definition
    monday: DaySlot = field(default_factory=lambda: DaySlot())
    tuesday: DaySlot = field(default_factory=lambda: DaySlot())
    wednesday: DaySlot = field(default_factory=lambda: DaySlot())
    thursday: DaySlot = field(default_factory=lambda: DaySlot())
    friday: DaySlot = field(default_factory=lambda: DaySlot())
    saturday: DaySlot = field(default_factory=lambda: DaySlot())
    sunday: DaySlot = field(default_factory=lambda: DaySlot(is_rest=True))
    
    # Pattern-level constraints  
    min_weekly_hours: float = 0.0
    max_weekly_hours: float = 55.0
    min_work_days: int = 0
    max_work_days: int = 6
    
    @property
    def days(self) -> dict[Weekday, DaySlot]:
        """Get all day slots as a dict."""
        return {
            Weekday.MONDAY: self.monday,
            Weekday.TUESDAY: self.tuesday,
            Weekday.WEDNESDAY: self.wednesday,
            Weekday.THURSDAY: self.thursday,
            Weekday.FRIDAY: self.friday,
            Weekday.SATURDAY: self.saturday,
            Weekday.SUNDAY: self.sunday,
        }
    
    @property
    def work_days(self) -> list[Weekday]:
        """Get list of work days (non-rest days)."""
        return [day for day, slot in self.days.items() if not slot.is_rest]
    
    @property
    def rest_days(self) -> list[Weekday]:
        """Get list of rest days."""
        return [day for day, slot in self.days.items() if slot.is_rest]
    
    @property
    def total_blocks(self) -> int:
        """Total blocks in the week."""
        return sum(slot.blocks for slot in self.days.values())
    
    @property
    def max_total_tours(self) -> int:
        """Maximum tours this pattern can cover."""
        return sum(slot.max_tours for slot in self.days.values() if not slot.is_rest)


# =============================================================================
# STANDARD PATTERNS
# =============================================================================

# Rest day slots for reuse
REST = DaySlot(is_rest=True)
SINGLE = DaySlot(blocks=1, max_tours=3)
DOUBLE = DaySlot(blocks=2, max_tours=4)  # Split shift: 2 blocks, up to 4 tours
LIGHT = DaySlot(blocks=1, max_tours=2)
HEAVY = DaySlot(blocks=1, max_tours=3)


PATTERN_3X3_REST = WeeklyPattern(
    id="3x3_rest",
    name="3er mit Ruhetag",
    description="3 Tage mit 3er-Schichten, jeweils 1 Tag Pause dazwischen",
    pattern_type=PatternType.THREE_BY_THREE,
    monday=HEAVY,
    tuesday=REST,
    wednesday=HEAVY, 
    thursday=REST,
    friday=HEAVY,
    saturday=REST,
    sunday=REST,
    max_work_days=3,
)

PATTERN_3X3_CONSECUTIVE = WeeklyPattern(
    id="3x3_consecutive",
    name="3er Block",
    description="3 aufeinanderfolgende Tage mit 3er-Schichten",
    pattern_type=PatternType.THREE_BY_THREE,
    monday=HEAVY,
    tuesday=HEAVY,
    wednesday=HEAVY,
    thursday=REST,
    friday=REST,
    saturday=REST,
    sunday=REST,
    max_work_days=3,
)

PATTERN_SPLIT_DAILY = WeeklyPattern(
    id="split_daily",
    name="Split Schicht",
    description="Geteilte Schicht: Morgen + Nachmittag",
    pattern_type=PatternType.SPLIT_SHIFT,
    monday=DOUBLE,
    tuesday=DOUBLE,
    wednesday=DOUBLE,
    thursday=DOUBLE,
    friday=DOUBLE,
    saturday=REST,
    sunday=REST,
    max_work_days=5,
)

PATTERN_FULL_TIME = WeeklyPattern(
    id="full_time",
    name="Vollzeit",
    description="Standard Vollzeit Mo-Sa",
    pattern_type=PatternType.FULL_TIME,
    monday=SINGLE,
    tuesday=SINGLE,
    wednesday=SINGLE,
    thursday=SINGLE,
    friday=SINGLE,
    saturday=SINGLE,
    sunday=REST,
    min_weekly_hours=35.0,
    max_work_days=6,
)

PATTERN_PART_TIME = WeeklyPattern(
    id="part_time",
    name="Teilzeit",
    description="Teilzeit 3 Tage/Woche",
    pattern_type=PatternType.PART_TIME,
    monday=LIGHT,
    tuesday=REST,
    wednesday=LIGHT,
    thursday=REST,
    friday=LIGHT,
    saturday=REST,
    sunday=REST,
    max_weekly_hours=25.0,
    max_work_days=3,
)

PATTERN_WEEKEND = WeeklyPattern(
    id="weekend",
    name="Wochenende",
    description="Schwerpunkt Freitag-Samstag",
    pattern_type=PatternType.WEEKEND,
    monday=REST,
    tuesday=REST,
    wednesday=REST,
    thursday=LIGHT,
    friday=HEAVY,
    saturday=HEAVY,
    sunday=REST,
    max_work_days=3,
)

PATTERN_MIXED = WeeklyPattern(
    id="mixed",
    name="Gemischt",
    description="Flexible Mischung aus 1-2 Blöcken/Tag",
    pattern_type=PatternType.CUSTOM,
    monday=SINGLE,
    tuesday=DOUBLE,  # Split
    wednesday=SINGLE,
    thursday=DOUBLE,  # Split
    friday=SINGLE,
    saturday=LIGHT,
    sunday=REST,
    max_work_days=6,
)


# =============================================================================
# PATTERN REGISTRY
# =============================================================================

# All available patterns
AVAILABLE_PATTERNS: Final[dict[str, WeeklyPattern]] = {
    p.id: p for p in [
        PATTERN_3X3_REST,
        PATTERN_3X3_CONSECUTIVE,
        PATTERN_SPLIT_DAILY,
        PATTERN_FULL_TIME,
        PATTERN_PART_TIME,
        PATTERN_WEEKEND,
        PATTERN_MIXED,
    ]
}


def get_pattern(pattern_id: str) -> WeeklyPattern | None:
    """Get pattern by ID."""
    return AVAILABLE_PATTERNS.get(pattern_id)


def get_patterns_by_type(pattern_type: PatternType) -> list[WeeklyPattern]:
    """Get all patterns of a given type."""
    return [p for p in AVAILABLE_PATTERNS.values() if p.pattern_type == pattern_type]


def get_compatible_patterns(
    max_weekly_hours: float,
    available_days: list[Weekday] | None = None
) -> list[WeeklyPattern]:
    """
    Get patterns compatible with driver constraints.
    
    Args:
        max_weekly_hours: Driver's max weekly hours
        available_days: Days the driver is available (None = all days)
    
    Returns:
        List of compatible patterns
    """
    compatible = []
    
    for pattern in AVAILABLE_PATTERNS.values():
        # Check weekly hours
        if pattern.min_weekly_hours > max_weekly_hours:
            continue
        
        # Check day availability if specified
        if available_days is not None:
            if not all(d in available_days for d in pattern.work_days):
                continue
        
        compatible.append(pattern)
    
    return compatible


# =============================================================================
# ROSTER SLOT (for two-phase optimization)
# =============================================================================

@dataclass
class RosterSlot:
    """
    A time slot in a driver's weekly roster.
    
    Used in two-phase optimization:
    Phase 1: Generate roster slots from patterns
    Phase 2: Match tours to slots
    """
    driver_id: str
    pattern_id: str
    day: Weekday
    block_index: int  # 0 for first block, 1 for second (split shift)
    
    # Time window (flexible, to be filled with tours)
    earliest_start: str  # HH:MM
    latest_end: str      # HH:MM
    
    # Capacity
    max_tours: int = 3
    
    # Assigned tours (filled in Phase 2)
    tour_ids: list[str] = field(default_factory=list)
    
    @property
    def slot_id(self) -> str:
        """Unique slot identifier."""
        return f"{self.driver_id}_{self.day.value}_{self.block_index}"
