"""
Pydantic Models for API
=======================
Matches frontend types.ts structure
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


# =============================================================================
# ENUMS
# =============================================================================

class WeekdayFE(str, Enum):
    """Frontend weekday format."""
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


WEEKDAY_MAP = {
    WeekdayFE.MONDAY: "Mon",
    WeekdayFE.TUESDAY: "Tue",
    WeekdayFE.WEDNESDAY: "Wed",
    WeekdayFE.THURSDAY: "Thu",
    WeekdayFE.FRIDAY: "Fri",
    WeekdayFE.SATURDAY: "Sat",
    WeekdayFE.SUNDAY: "Sun",
}

WEEKDAY_REVERSE = {v: k for k, v in WEEKDAY_MAP.items()}


# =============================================================================
# INPUT MODELS (from frontend)
# =============================================================================

class TourInputFE(BaseModel):
    """Tour input from frontend."""
    id: str
    day: WeekdayFE
    start_time: str  # HH:MM
    end_time: str    # HH:MM
    location: Optional[str] = None
    required_qualifications: Optional[list[str]] = None


class DriverInputFE(BaseModel):
    """Driver input from frontend (optional in v4)."""
    id: str
    name: str
    qualifications: Optional[list[str]] = None
    max_weekly_hours: Optional[float] = 53.0
    max_daily_span_hours: Optional[float] = 14.0
    max_tours_per_day: Optional[int] = 3
    min_rest_hours: Optional[float] = 11.0
    available_days: Optional[list[WeekdayFE]] = None


class ScheduleRequest(BaseModel):
    """Request from frontend."""
    tours: list[TourInputFE]
    drivers: list[DriverInputFE] = []  # Optional in v4
    week_start: str  # YYYY-MM-DD
    prefer_larger_blocks: bool = True
    seed: Optional[int] = None
    solver_type: Literal["greedy", "cpsat", "cpsat+lns", "cpsat-global", "set-partitioning"] = "cpsat"
    time_limit_seconds: int = 60
    lns_iterations: int = 10
    locked_block_ids: Optional[list[str]] = None


# =============================================================================
# OUTPUT MODELS (to frontend)
# =============================================================================

class TourOutputFE(BaseModel):
    """Tour in response."""
    id: str
    day: str
    start_time: str
    end_time: str
    duration_hours: float
    location: str = ""
    required_qualifications: list[str] = []


class BlockOutputFE(BaseModel):
    """Block in response."""
    id: str
    day: str
    block_type: Literal["single", "double", "triple"]
    tours: list[TourOutputFE]
    driver_id: Optional[str] = None
    total_work_hours: float
    span_hours: float


class AssignmentOutputFE(BaseModel):
    """Assignment in response."""
    driver_id: str
    driver_name: str
    day: str
    block: BlockOutputFE


class UnassignedTourFE(BaseModel):
    """Unassigned tour info."""
    tour: TourOutputFE
    reason_codes: list[str]
    details: str


class StatsOutputFE(BaseModel):
    """Statistics in response."""
    total_drivers: int
    total_tours_input: int
    total_tours_assigned: int
    total_tours_unassigned: int = 0
    block_counts: dict[str, int]
    assignment_rate: float
    average_driver_utilization: float
    average_work_hours: float = 0.0
    # v4 additions
    block_mix: Optional[dict[str, float]] = None
    template_match_count: Optional[int] = None
    split_2er_count: Optional[int] = None


class ValidationOutputFE(BaseModel):
    """Validation result."""
    is_valid: bool
    hard_violations: list[str] = []
    warnings: list[str] = []


class ScheduleResponse(BaseModel):
    """Full response to frontend."""
    id: str
    week_start: str
    assignments: list[AssignmentOutputFE]
    unassigned_tours: list[UnassignedTourFE] = []
    validation: ValidationOutputFE
    stats: StatsOutputFE
    version: str = "4.0"
    solver_type: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    constraints: dict[str, float | bool | int]
