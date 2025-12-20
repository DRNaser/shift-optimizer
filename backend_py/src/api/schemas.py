"""
SHIFT OPTIMIZER - API Schemas
==============================
Pydantic schemas for FastAPI request/response models.
"""

from datetime import date, time
from pydantic import BaseModel, Field

from src.domain.models import (
    BlockType,
    ReasonCode,
    Weekday,
)


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class TourInput(BaseModel):
    """Input schema for a tour."""
    id: str = Field(..., description="Unique tour identifier")
    day: Weekday
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="HH:MM format")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="HH:MM format")
    location: str = Field(default="DEFAULT")
    required_qualifications: list[str] = Field(default_factory=list)


class DriverInput(BaseModel):
    """Input schema for a driver."""
    id: str
    name: str
    qualifications: list[str] = Field(default_factory=list)
    max_weekly_hours: float = Field(default=55.0, ge=0, le=168)
    max_daily_span_hours: float = Field(default=16.5, ge=0, le=24)
    max_tours_per_day: int = Field(default=3, ge=1, le=10)
    min_rest_hours: float = Field(default=11.0, ge=0, le=24)
    # Simplified availability: list of available days
    available_days: list[Weekday] = Field(
        default_factory=lambda: list(Weekday),
        description="Days when driver is available"
    )


class ScheduleRequest(BaseModel):
    """Request to create a schedule."""
    tours: list[TourInput]
    drivers: list[DriverInput] = Field(default_factory=list, description="Optional - virtual drivers created if empty")
    week_start: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")
    prefer_larger_blocks: bool = Field(default=True)
    seed: int | None = Field(default=None, description="Seed for reproducibility")
    solver_type: str = Field(
        default="cpsat",
        description="Solver: 'greedy', 'cpsat', or 'cpsat+lns'"
    )
    time_limit_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Time limit for CP-SAT solver (seconds)"
    )
    extended_hours: bool = Field(
        default=False,
        description="If True, allows up to 56h/week. If False, caps at 53h/week."
    )
    lns_iterations: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of LNS refinement iterations (if solver_type='cpsat+lns')"
    )
    locked_block_ids: list[str] = Field(
        default_factory=list,
        description="Block IDs that should not be changed during optimization"
    )


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class TourOutput(BaseModel):
    """Output schema for a tour."""
    id: str
    day: str
    start_time: str
    end_time: str
    duration_hours: float
    location: str
    required_qualifications: list[str]


class BlockOutput(BaseModel):
    """Output schema for a block."""
    id: str
    day: str
    block_type: str
    tours: list[TourOutput]
    driver_id: str | None
    total_work_hours: float
    span_hours: float


class AssignmentOutput(BaseModel):
    """Output schema for a driver assignment."""
    driver_id: str
    driver_name: str
    day: str
    block: BlockOutput


class UnassignedTourOutput(BaseModel):
    """Output schema for an unassigned tour."""
    tour: TourOutput
    reason_codes: list[str]
    details: str


class StatsOutput(BaseModel):
    """Output schema for plan statistics."""
    total_drivers: int
    total_tours_input: int
    total_tours_assigned: int
    total_tours_unassigned: int
    block_counts: dict[str, int]
    assignment_rate: float
    average_driver_utilization: float
    average_work_hours: float = Field(default=0.0, description="Average work hours per driver")


class ValidationOutput(BaseModel):
    """Output schema for validation result."""
    is_valid: bool
    hard_violations: list[str]
    warnings: list[str]


class ScheduleResponse(BaseModel):
    """Response containing the complete schedule."""
    id: str
    week_start: str
    assignments: list[AssignmentOutput]
    unassigned_tours: list[UnassignedTourOutput]
    validation: ValidationOutput
    stats: StatsOutput
    version: str
    solver_type: str = Field(default="greedy", description="Solver used: 'greedy' or 'cpsat'")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    constraints: dict[str, float | int | bool]


class ErrorResponse(BaseModel):
    """Error response."""
    status: str = "error"
    message: str
    details: list[str] = Field(default_factory=list)
