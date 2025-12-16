"""
SHIFT OPTIMIZER - Hard Constraints
===================================
Machine-readable constraint definitions.
These are the ABSOLUTE rules that may NEVER be violated.

The Validator is the sole arbiter of constraint compliance.
The Solver respects these - it does not define them.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Final


# =============================================================================
# CONSTRAINT DEFINITIONS (IMMUTABLE)
# =============================================================================

@dataclass(frozen=True)
class HardConstraints:
    """
    Hard constraints that must NEVER be violated.
    These are non-negotiable business rules.
    
    Values are defaults - individual drivers may have stricter personal limits.
    """
    
    # Time-based constraints
    MAX_WEEKLY_HOURS: float = 55.0
    """Maximum working hours per driver per week."""
    
    MAX_DAILY_SPAN_HOURS: float = 14.5
    """Maximum span from first tour start to last tour end on any day."""
    
    MIN_REST_HOURS: float = 11.0
    """Minimum rest time between end of last tour one day and start of first tour next day."""
    
    # Count-based constraints
    MAX_TOURS_PER_DAY: int = 3
    """Maximum number of tours a driver can do in one day."""
    
    MAX_BLOCKS_PER_DRIVER_PER_DAY: int = 2
    """A driver can be assigned up to 2 blocks per day (split shift)."""
    
    MIN_GAP_BETWEEN_BLOCKS_HOURS: float = 6.0
    """Minimum gap between blocks on the same day for split shifts."""
    
    # Logical constraints
    NO_TOUR_OVERLAP: bool = True
    """Tours within a block cannot overlap in time."""
    
    QUALIFICATION_REQUIRED: bool = True
    """Driver must have all qualifications required by each tour."""
    
    AVAILABILITY_REQUIRED: bool = True
    """Driver must be available during tour times."""
    
    # Block constraints
    MIN_TOURS_PER_BLOCK: int = 1
    """Minimum tours in a block."""
    
    MAX_TOURS_PER_BLOCK: int = 3
    """Maximum tours in a block."""
    
    # Pause between tours (in minutes)
    MIN_PAUSE_BETWEEN_TOURS: int = 30
    """Minimum break between consecutive tours in a block."""
    
    MAX_PAUSE_BETWEEN_TOURS: int = 120
    """Maximum gap between consecutive tours to still form a block (2 hours)."""


# Global singleton instance - THE source of truth
HARD_CONSTRAINTS: Final[HardConstraints] = HardConstraints()


# =============================================================================
# CONSTRAINT METADATA (for explainability)
# =============================================================================

class ConstraintType(str, Enum):
    """Categories of constraints for reporting."""
    TIME = "TIME"
    QUALIFICATION = "QUALIFICATION"
    AVAILABILITY = "AVAILABILITY"
    OVERLAP = "OVERLAP"
    COUNT = "COUNT"


@dataclass(frozen=True)
class ConstraintMeta:
    """Metadata about a constraint for explainability."""
    name: str
    type: ConstraintType
    description: str
    value: float | int | bool
    unit: str = ""


# Constraint metadata registry for explainability
CONSTRAINT_METADATA: Final[dict[str, ConstraintMeta]] = {
    "MAX_WEEKLY_HOURS": ConstraintMeta(
        name="Maximum Weekly Hours",
        type=ConstraintType.TIME,
        description="Maximum working hours per driver per week",
        value=HARD_CONSTRAINTS.MAX_WEEKLY_HOURS,
        unit="hours"
    ),
    "MAX_DAILY_SPAN_HOURS": ConstraintMeta(
        name="Maximum Daily Span",
        type=ConstraintType.TIME,
        description="Maximum span from first tour start to last tour end on any day",
        value=HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS,
        unit="hours"
    ),
    "MIN_REST_HOURS": ConstraintMeta(
        name="Minimum Rest Time",
        type=ConstraintType.TIME,
        description="Minimum rest between last tour of one day and first tour of next day",
        value=HARD_CONSTRAINTS.MIN_REST_HOURS,
        unit="hours"
    ),
    "MAX_TOURS_PER_DAY": ConstraintMeta(
        name="Maximum Tours Per Day",
        type=ConstraintType.COUNT,
        description="Maximum number of tours a driver can do in one day",
        value=HARD_CONSTRAINTS.MAX_TOURS_PER_DAY,
        unit="tours"
    ),
    "MAX_BLOCKS_PER_DRIVER_PER_DAY": ConstraintMeta(
        name="Max Blocks Per Day",
        type=ConstraintType.COUNT,
        description="Maximum blocks per day (for split shifts)",
        value=HARD_CONSTRAINTS.MAX_BLOCKS_PER_DRIVER_PER_DAY,
        unit="blocks"
    ),
    "MIN_GAP_BETWEEN_BLOCKS": ConstraintMeta(
        name="Minimum Gap Between Blocks",
        type=ConstraintType.TIME,
        description="Minimum break between blocks for split shifts",
        value=HARD_CONSTRAINTS.MIN_GAP_BETWEEN_BLOCKS_HOURS,
        unit="hours"
    ),
    "NO_TOUR_OVERLAP": ConstraintMeta(
        name="No Tour Overlap",
        type=ConstraintType.OVERLAP,
        description="Tours cannot overlap in time",
        value=HARD_CONSTRAINTS.NO_TOUR_OVERLAP
    ),
    "QUALIFICATION_REQUIRED": ConstraintMeta(
        name="Qualification Required",
        type=ConstraintType.QUALIFICATION,
        description="Driver must have all qualifications required by tours",
        value=HARD_CONSTRAINTS.QUALIFICATION_REQUIRED
    ),
    "AVAILABILITY_REQUIRED": ConstraintMeta(
        name="Availability Required",
        type=ConstraintType.AVAILABILITY,
        description="Driver must be available during tour times",
        value=HARD_CONSTRAINTS.AVAILABILITY_REQUIRED
    ),
}


# =============================================================================
# SOFT OBJECTIVES (for Phase 2 - informational only in Phase 1)
# =============================================================================

@dataclass(frozen=True)
class SoftObjectives:
    """
    Soft objectives for optimization.
    These are goals to optimize toward, not hard constraints.
    
    Phase 1: Documentation only
    Phase 2: Implemented in CP-SAT
    """
    
    MINIMIZE_TOTAL_DRIVERS: bool = True
    """Primary objective: Use as few drivers as possible."""
    
    MAXIMIZE_BLOCK_SIZE: bool = True
    """Prefer 3er blocks over 2er, 2er over 1er."""
    
    MAXIMIZE_DRIVER_UTILIZATION: bool = True
    """Prefer fuller schedules per driver."""
    
    MINIMIZE_DRIVER_VARIANCE: bool = False
    """(Future) Balance hours across drivers."""


SOFT_OBJECTIVES: Final[SoftObjectives] = SoftObjectives()


# =============================================================================
# SOFT PENALTY CONFIGURATION (Fatigue Prevention)
# =============================================================================

@dataclass(frozen=True)
class SoftPenaltyConfig:
    """
    Configurable soft penalty weights for fatigue prevention.
    Negative weights discourage patterns, higher magnitude = stronger penalty.
    """
    
    # Triple block penalty (3 tours in one block)
    TRIPLE_BLOCK_PENALTY: int = 50
    """Penalty for assigning a 3-tour block (discourages physically demanding blocks)."""
    
    # Early/Late shift penalties
    EARLY_START_PENALTY: int = 30
    """Penalty for blocks starting before EARLY_THRESHOLD_HOUR."""
    
    LATE_END_PENALTY: int = 30
    """Penalty for blocks ending at or after LATE_THRESHOLD_HOUR."""
    
    # Thresholds
    EARLY_THRESHOLD_HOUR: int = 6
    """Hour before which starts are considered 'early' (default: 06:00)."""
    
    LATE_THRESHOLD_HOUR: int = 21
    """Hour at or after which ends are considered 'late' (default: 21:00)."""
    
    # Comfort rest penalty (legal but tight)
    SHORT_REST_PENALTY: int = 20
    """Penalty for rest periods that are legal (≥11h) but below comfort threshold."""
    
    COMFORT_REST_HOURS: float = 13.0
    """Rest periods below this but ≥MIN_REST_HOURS get a soft penalty."""


SOFT_PENALTY_CONFIG: Final[SoftPenaltyConfig] = SoftPenaltyConfig()

