"""
SHIFT OPTIMIZER - Domain Models
================================
Core business entities for the Last-Mile-Delivery shift optimization system.

All models are immutable Pydantic models to ensure determinism and data integrity.
These models are the SINGLE SOURCE OF TRUTH for data structure.
"""

from datetime import date, time, timedelta
from enum import Enum
from typing import Annotated
from pydantic import BaseModel, Field, field_validator, model_validator

# Import constraints for default values (avoids drift between constraint and model)
from src.domain.constraints import HARD_CONSTRAINTS


# =============================================================================
# ENUMS
# =============================================================================

class Weekday(str, Enum):
    """Days of the week for scheduling."""
    MONDAY = "Mon"
    TUESDAY = "Tue"
    WEDNESDAY = "Wed"
    THURSDAY = "Thu"
    FRIDAY = "Fri"
    SATURDAY = "Sat"
    SUNDAY = "Sun"


class ReasonCode(str, Enum):
    """Reason codes for unassigned tours - required for explainability."""
    NO_AVAILABLE_DRIVER = "NO_AVAILABLE_DRIVER"
    DRIVER_WEEKLY_LIMIT = "DRIVER_WEEKLY_LIMIT"
    DRIVER_DAILY_SPAN_LIMIT = "DRIVER_DAILY_SPAN_LIMIT"
    DRIVER_MAX_TOURS_PER_DAY = "DRIVER_MAX_TOURS_PER_DAY"
    DRIVER_REST_VIOLATION = "DRIVER_REST_VIOLATION"
    DRIVER_QUALIFICATION_MISSING = "DRIVER_QUALIFICATION_MISSING"
    DRIVER_NOT_AVAILABLE = "DRIVER_NOT_AVAILABLE"
    TOUR_OVERLAP = "TOUR_OVERLAP"
    BLOCK_ALREADY_ASSIGNED = "BLOCK_ALREADY_ASSIGNED"
    INFEASIBLE = "INFEASIBLE"


class BlockType(str, Enum):
    """Block types based on number of tours."""
    SINGLE = "1er"
    DOUBLE = "2er"
    TRIPLE = "3er"


class PauseZone(str, Enum):
    """Pause zone classification for blocks (Contract v2.0).
    
    REGULAR: Standard consecutive tours with 30-120min gaps
    SPLIT: Split-shift with 240-360min gaps
    
    No other values allowed. No lowercase variants. No nulls.
    """
    REGULAR = "REGULAR"
    SPLIT = "SPLIT"


# =============================================================================
# TIME UTILITIES
# =============================================================================

class TimeSlot(BaseModel):
    """A time window with start and end times."""
    model_config = {"frozen": True}
    
    start: time
    end: time
    
    # Note: No validation that start < end - allows cross-midnight windows (e.g., 22:00-06:00)
    # Cross-midnight windows are valid in shift planning scenarios
    
    @property
    def crosses_midnight(self) -> bool:
        """Check if this time slot crosses midnight."""
        return self.end < self.start
    
    @property
    def duration_minutes(self) -> int:
        """Calculate duration in minutes, handling cross-midnight correctly."""
        start_mins = self.start.hour * 60 + self.start.minute
        end_mins = self.end.hour * 60 + self.end.minute
        if end_mins < start_mins:  # Cross-midnight
            end_mins += 24 * 60
        return end_mins - start_mins
    
    @property
    def duration_hours(self) -> float:
        """Calculate duration in hours."""
        return self.duration_minutes / 60.0
    
    def overlaps(self, other: "TimeSlot") -> bool:
        """Check if this time slot overlaps with another."""
        # Simplified overlap check - doesn't handle cross-midnight overlap
        return self.start < other.end and other.start < self.end


# =============================================================================
# TOUR MODEL
# =============================================================================

class Tour(BaseModel):
    """
    A Tour represents a single delivery shift from the forecast.
    Tours are the atomic unit of work - they cannot be split.
    Typical duration: 4-5 hours.

    Cross-midnight tours: Tours that start on one day and end on the next
    (e.g., 22:00-06:00). For these, end_time < start_time and crosses_midnight=True.
    """
    model_config = {"frozen": True}

    id: str = Field(..., description="Unique tour identifier")
    day: Weekday = Field(..., description="Day of the week")
    start_time: time = Field(..., description="Tour start time")
    end_time: time = Field(..., description="Tour end time (on next day if crosses_midnight=True)")
    location: str = Field(default="DEFAULT", description="Delivery zone/location")
    required_qualifications: list[str] = Field(
        default_factory=list,
        description="Required driver qualifications"
    )
    crosses_midnight: bool = Field(
        default=False,
        description="True if tour ends on next day (e.g., 22:00-06:00)"
    )

    @model_validator(mode="after")
    def validate_tour(self) -> "Tour":
        """Validate tour timing."""
        # For cross-midnight tours, end_time < start_time is expected
        if not self.crosses_midnight:
            if self.start_time >= self.end_time:
                raise ValueError(
                    f"Tour {self.id}: start_time {self.start_time} must be before end_time {self.end_time} (or set crosses_midnight=True)"
                )
        else:
            # For cross-midnight tours, end_time should be < start_time
            if self.start_time <= self.end_time:
                raise ValueError(
                    f"Tour {self.id}: crosses_midnight=True but end_time {self.end_time} >= start_time {self.start_time}"
                )
        return self

    @property
    def duration_minutes(self) -> int:
        """Tour duration in minutes (handles cross-midnight)."""
        start_mins = self.start_time.hour * 60 + self.start_time.minute
        end_mins = self.end_time.hour * 60 + self.end_time.minute

        if self.crosses_midnight:
            # Tour ends next day: duration = (24h - start) + end
            return (24 * 60 - start_mins) + end_mins
        else:
            return end_mins - start_mins
    
    @property
    def duration_hours(self) -> float:
        """Tour duration in hours."""
        return self.duration_minutes / 60.0
    
    @property
    def time_slot(self) -> TimeSlot:
        """Get tour as a TimeSlot."""
        return TimeSlot(start=self.start_time, end=self.end_time)
    
    def overlaps(self, other: "Tour") -> bool:
        """Check if this tour overlaps with another on the same day."""
        if self.day != other.day:
            return False
        return self.time_slot.overlaps(other.time_slot)


# =============================================================================
# DRIVER MODEL
# =============================================================================

class DailyAvailability(BaseModel):
    """Driver availability for a specific day."""
    model_config = {"frozen": True}
    
    day: Weekday
    available: bool = True
    time_slots: list[TimeSlot] = Field(
        default_factory=list,
        description="Available time windows. Empty = all day if available=True"
    )


class Driver(BaseModel):
    """
    A Driver who can be assigned to tours/blocks.
    Contains availability, qualifications, and constraint limits.
    """
    model_config = {"frozen": True}
    
    id: str = Field(..., description="Unique driver identifier")
    name: str = Field(..., description="Driver name")
    qualifications: list[str] = Field(
        default_factory=list,
        description="Driver qualifications/certifications"
    )
    weekly_availability: list[DailyAvailability] = Field(
        default_factory=list,
        description="Availability per day"
    )
    
    # Constraint limits (can be driver-specific, defaults from HARD_CONSTRAINTS)
    max_weekly_hours: float = Field(default=55.0, ge=0, le=168)
    max_daily_span_hours: float = Field(default=HARD_CONSTRAINTS.MAX_DAILY_SPAN_HOURS, ge=0, le=24)
    max_tours_per_day: int = Field(default=3, ge=1, le=10)
    min_rest_hours: float = Field(default=11.0, ge=0, le=24)
    
    def is_available_on(self, day: Weekday) -> bool:
        """Check if driver is available on a given day."""
        for avail in self.weekly_availability:
            if avail.day == day:
                return avail.available
        # If no availability defined, assume available
        return True
    
    def has_qualification(self, qualification: str) -> bool:
        """Check if driver has a specific qualification."""
        return qualification in self.qualifications
    
    def has_all_qualifications(self, required: list[str]) -> bool:
        """Check if driver has all required qualifications."""
        return all(self.has_qualification(q) for q in required)


# =============================================================================
# BLOCK MODEL
# =============================================================================

class Block(BaseModel):
    """
    A Block is a group of 1-3 consecutive tours assigned to one driver on one day.
    Blocks are the unit of assignment - drivers are assigned blocks, not tours.
    """
    model_config = {"frozen": True}
    
    id: str = Field(..., description="Unique block identifier")
    day: Weekday = Field(..., description="Day of the week")
    tours: list[Tour] = Field(..., min_length=1, max_length=3)
    driver_id: str | None = Field(default=None, description="Assigned driver ID")
    
    # Split-shift metadata (explicit in JSON schema - Contract v2.0)
    is_split: bool = Field(default=False, description="True if block has split-shift gap (240-360 min)")
    max_pause_minutes: int = Field(default=0, description="Largest gap between consecutive tours in minutes")
    pause_zone: PauseZone = Field(default=PauseZone.REGULAR, description="Pause zone: REGULAR or SPLIT")
    
    @field_validator("pause_zone", mode="before")
    @classmethod
    def normalize_pause_zone(cls, v):
        """Backward-compatible parser: accept str, normalize to PauseZone enum."""
        if v is None:
            return PauseZone.REGULAR
        if isinstance(v, PauseZone):
            return v
        if isinstance(v, str):
            # Normalize: uppercase, strip whitespace
            normalized = v.strip().upper()
            if normalized in ("REGULAR", "SPLIT"):
                return PauseZone(normalized)
            # Invalid value - default to REGULAR for backward compat
            return PauseZone.REGULAR
        return PauseZone.REGULAR
    
    @model_validator(mode="after")
    def validate_block(self) -> "Block":
        """Validate block structure."""
        # All tours must be on same day
        for tour in self.tours:
            if tour.day != self.day:
                raise ValueError(
                    f"Block {self.id}: Tour {tour.id} is on {tour.day}, "
                    f"but block is for {self.day}"
                )
        
        # Tours should be sorted by start time
        sorted_tours = sorted(self.tours, key=lambda t: t.start_time)
        if self.tours != sorted_tours:
            raise ValueError(f"Block {self.id}: Tours must be sorted by start time")
        
        return self
    
    @property
    def block_type(self) -> BlockType:
        """Get block type based on number of tours."""
        count = len(self.tours)
        if count == 1:
            return BlockType.SINGLE
        elif count == 2:
            return BlockType.DOUBLE
        else:
            return BlockType.TRIPLE
    
    @property
    def first_start(self) -> time:
        """Start time of first tour."""
        return self.tours[0].start_time
    
    @property
    def last_end(self) -> time:
        """End time of last tour."""
        return self.tours[-1].end_time
    
    @property
    def span_minutes(self) -> int:
        """Total span from first start to last end in minutes."""
        start_mins = self.first_start.hour * 60 + self.first_start.minute
        end_mins = self.last_end.hour * 60 + self.last_end.minute
        if end_mins < start_mins:  # Cross-midnight
            end_mins += 24 * 60
        return end_mins - start_mins
    
    @property
    def span_hours(self) -> float:
        """Total span in hours."""
        return self.span_minutes / 60.0
    
    @property
    def total_work_minutes(self) -> int:
        """Total working time (sum of tour durations) in minutes."""
        return sum(tour.duration_minutes for tour in self.tours)
    
    @property
    def total_work_hours(self) -> float:
        """Total working time in hours."""
        return self.total_work_minutes / 60.0
    
    @property
    def required_qualifications(self) -> set[str]:
        """All qualifications required for this block."""
        quals: set[str] = set()
        for tour in self.tours:
            quals.update(tour.required_qualifications)
        return quals
    
    @property
    def is_assigned(self) -> bool:
        """Check if block has a driver assigned."""
        return self.driver_id is not None


# =============================================================================
# ASSIGNMENT & PLAN MODELS
# =============================================================================

class DriverAssignment(BaseModel):
    """A driver's complete assignment for one day."""
    model_config = {"frozen": True}
    
    driver_id: str
    day: Weekday
    block: Block
    
    @model_validator(mode="after")
    def validate_assignment(self) -> "DriverAssignment":
        """Validate assignment consistency."""
        if self.block.day != self.day:
            raise ValueError(
                f"Assignment day {self.day} doesn't match block day {self.block.day}"
            )
        if self.block.driver_id is not None and self.block.driver_id != self.driver_id:
            raise ValueError(
                f"Block driver_id {self.block.driver_id} doesn't match "
                f"assignment driver_id {self.driver_id}"
            )
        return self


class UnassignedTour(BaseModel):
    """A tour that could not be assigned, with explanation."""
    model_config = {"frozen": True}
    
    tour: Tour
    reason_codes: list[ReasonCode] = Field(
        ..., min_length=1,
        description="Why this tour couldn't be assigned"
    )
    details: str = Field(default="", description="Human-readable explanation")


class WeeklyPlanStats(BaseModel):
    """Statistics for a weekly plan - KPIs."""
    model_config = {"frozen": True}
    
    total_drivers: int = Field(..., ge=0)
    total_tours_input: int = Field(..., ge=0)
    total_tours_assigned: int = Field(..., ge=0)
    total_tours_unassigned: int = Field(..., ge=0)
    block_counts: dict[BlockType, int] = Field(default_factory=dict)
    average_driver_utilization: float = Field(default=0.0, ge=0, le=1)
    
    @property
    def assignment_rate(self) -> float:
        """Percentage of tours successfully assigned."""
        if self.total_tours_input == 0:
            return 1.0
        return self.total_tours_assigned / self.total_tours_input


class ValidationResult(BaseModel):
    """Result of validating a plan against all constraints."""
    model_config = {"frozen": True}
    
    is_valid: bool
    hard_violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    
    @property
    def violation_count(self) -> int:
        """Total number of hard constraint violations."""
        return len(self.hard_violations)


class WeeklyPlan(BaseModel):
    """
    A complete weekly schedule - the final output of the optimizer.
    Contains all assignments and unassigned tours with explanations.
    """
    model_config = {"frozen": True}
    
    id: str = Field(..., description="Unique plan identifier")
    week_start: date = Field(..., description="Monday of the plan week")
    assignments: list[DriverAssignment] = Field(default_factory=list)
    unassigned_tours: list[UnassignedTour] = Field(default_factory=list)
    validation: ValidationResult = Field(
        default_factory=lambda: ValidationResult(is_valid=False)
    )
    stats: WeeklyPlanStats | None = None
    
    # Metadata for snapshots (Contract v2.0)
    schema_version: str = Field(default="2.0", description="JSON schema version for contract compliance")
    version: str = Field(default="2.0", description="Plan version (legacy compatibility)")
    created_at: str = Field(default="")  # ISO timestamp
    solver_seed: int | None = Field(default=None, description="Seed for reproducibility")
    
    def get_driver_assignments(self, driver_id: str) -> list[DriverAssignment]:
        """Get all assignments for a specific driver."""
        return [a for a in self.assignments if a.driver_id == driver_id]
    
    def get_day_assignments(self, day: Weekday) -> list[DriverAssignment]:
        """Get all assignments for a specific day."""
        return [a for a in self.assignments if a.day == day]
    
    def get_driver_weekly_hours(self, driver_id: str) -> float:
        """Calculate total hours assigned to a driver for the week."""
        driver_assignments = self.get_driver_assignments(driver_id)
        return sum(a.block.total_work_hours for a in driver_assignments)
