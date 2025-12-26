"""
SHIFT OPTIMIZER - API Schemas
==============================
Pydantic schemas for FastAPI request/response models.
"""

from datetime import date, time
from pydantic import BaseModel, ConfigDict, Field

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
    pause_zone: str = Field(..., description="Pause zone: REGULAR or SPLIT")


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

    # Driver metrics (Patch 2 - Reporting Sync)
    drivers_fte: int | None = Field(default=None, description="Number of FTE drivers")
    drivers_pt: int | None = Field(default=None, description="Number of PT drivers")
    total_hours: float | None = Field(default=None, description="Total work hours across all drivers")
    fte_hours_avg: float | None = Field(default=None, description="Average hours per FTE driver")

    # Packability Diagnostics
    forced_1er_rate: float | None = None
    forced_1er_count: int | None = None
    missed_3er_opps_count: int | None = None
    missed_2er_opps_count: int | None = None
    missed_multi_opps_count: int | None = None
    
    # Output Profile Info
    output_profile: str | None = None
    gap_3er_min_minutes: int | None = None
    
    # Tour Share Metrics (by tours, not blocks)
    tour_share_1er: float | None = None
    tour_share_2er: float | None = None
    tour_share_3er: float | None = None
    
    # BEST_BALANCED two-pass metrics
    D_min: int | None = None  # Minimum headcount from pass 1
    driver_cap: int | None = None  # Cap = ceil(1.05 * D_min)
    day_spread: int | None = None  # Variance proxy (max_day - min_day)
    
    # Two-pass execution proof fields
    twopass_executed: bool | None = None  # True if pass 2 ran successfully
    pass1_time_s: float | None = None  # Pass 1 execution time
    pass2_time_s: float | None = None  # Pass 2 execution time
    drivers_total_pass1: int | None = None  # D_min = drivers from pass 1
    drivers_total_pass2: int | None = None  # Drivers from pass 2 (may differ)
    
    # =========================================================================
    # STAGE0 / PHASE1 TELEMETRY
    # =========================================================================
    stage0_raw_obj: int | None = None      # Stage0 objective on raw pool (before capping)
    stage0_raw_bound: int | None = None    # Stage0 bound on raw pool
    stage0_raw_status: str | None = None   # Stage0 status on raw pool
    stage0_capped_obj: int | None = None   # Stage0 objective on capped pool (Source of Truth)
    stage0_capped_bound: int | None = None # Stage0 bound on capped pool
    stage0_capped_status: str | None = None # Stage0 status on capped pool
    delta_raw_vs_capped: int | None = None # Difference: raw_obj - capped_obj (capping impact)
    n3_selected: int | None = None         # Number of 3er blocks selected in Phase1
    
    # =========================================================================
    # OVERLAP DIAGNOSTICS
    # =========================================================================
    deg3_max: int | None = None            # Max 3er-degree of any tour
    deg3_p95: float | None = None          # 95th percentile of 3er-degree
    hot_block_share: float | None = None   # Share of blocks covering hot tours
    
    # =========================================================================
    # OVERRIDE AUDIT
    # =========================================================================
    overrides_applied: dict | None = None  # Keys and values that were applied
    overrides_clamped: dict | None = None  # Keys that were clamped (original -> clamped)


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
    schema_version: str = Field(..., description="JSON schema version for contract compliance")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    constraints: dict[str, float | int | bool]


class ErrorResponse(BaseModel):
    """Error response."""
    status: str = "error"

# =============================================================================
# v2.0 SCHEMAS
# =============================================================================

class ConfigOverrides(BaseModel):
    """
    Client-provided configuration overrides.
    Only allows specific tunable fields. Locked fields are server-enforced.
    Unknown fields are accepted but tracked in overrides_rejected.
    """
    # Allow unknown fields to pass through (tracked in validator as rejected)
    model_config = ConfigDict(extra="allow")
    
    enable_fill_to_target_greedy: bool | None = None
    enable_bad_block_mix_rerun: bool | None = None
    enable_packability_costs: bool | None = None
    enable_bounded_swaps: bool | None = None
    
    # Penalties
    penalty_1er_with_multi: float | None = Field(default=None, ge=0.0, le=100.0)
    bonus_3er: float | None = Field(default=None, ge=-100.0, le=0.0)
    bonus_2er: float | None = Field(default=None, ge=-100.0, le=0.0)
    
    # Thresholds
    pt_ratio_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    underfull_ratio_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    
    # Rerun
    rerun_1er_penalty_multiplier: float | None = Field(default=None, ge=1.0, le=10.0)
    min_rerun_budget: float | None = Field(default=None, ge=1.0)
    
    # Repair (Bounded)
    repair_pt_limit: int | None = Field(default=None, ge=0, le=50)
    repair_fte_limit: int | None = Field(default=None, ge=0, le=50)
    repair_block_limit: int | None = Field(default=None, ge=0, le=500)
    
    # Advanced
    max_hours_per_fte: float | None = Field(default=None, ge=40.0, le=55.0)
    
    # Block Generation Controls
    enable_diag_block_caps: bool | None = None
    cap_quota_2er: float | None = Field(default=None, ge=0.0, le=1.0)
    
    # Output Profile Selection
    output_profile: str | None = Field(default=None, description="MIN_HEADCOUNT_3ER or BEST_BALANCED")
    gap_3er_min_minutes: int | None = Field(default=None, ge=15, le=90)
    cap_quota_3er: float | None = Field(default=None, ge=0.0, le=1.0)
    pass2_min_time_s: float | None = Field(default=None, ge=1.0, description="Minimum time guarantee for Pass-2 optimization")

    # DIAGNOSTIC: Solver Mode Override
    solver_mode: str | None = Field(default=None, description="Force specific solver path: GREEDY, CPSAT, SETPART, HEURISTIC")
    
    # LNS ENDGAME: Low-Hour Pattern Consolidation
    enable_lns_low_hour_consolidation: bool | None = None
    lns_time_budget_s: float | None = Field(default=None, ge=1.0)
    lns_low_hour_threshold_h: float | None = Field(default=None, ge=10.0)
    
    # v5: Day Cap (Operational Constraint)
    day_cap_hard: int | None = Field(default=None, ge=100, le=500, description="Max blocks per peak day (default: 220)")
    
    # =========================================================================
    # BLOCKGEN OVERRIDES (with safety caps)
    # =========================================================================
    block_gen_min_pause_minutes: int | None = Field(default=None, ge=15, le=60, description="Min pause between tours (default: 30)")
    block_gen_max_pause_regular_minutes: int | None = Field(default=None, ge=30, le=90, description="Max pause for regular blocks (default: 60)")
    block_gen_split_pause_min_minutes: int | None = Field(default=None, ge=180, le=480, description="Min split pause (default: 360)")
    block_gen_split_pause_max_minutes: int | None = Field(default=None, ge=180, le=480, description="Max split pause (default: 360)")
    block_gen_max_daily_span_hours: float | None = Field(default=None, ge=12.0, le=16.0, description="Max daily span hours (default: 15.5)")
    block_gen_max_spread_split_minutes: int | None = Field(default=None, ge=600, le=960, description="Max spread for split blocks (default: 840)")
    hot_tour_penalty_alpha: float | None = Field(default=None, ge=0.0, le=1.0, description="Anti-overlap penalty alpha (default: 0.0 = disabled)")


class RunConfig(BaseModel):
    """Run execution configuration."""
    seed: int | None = Field(default=42, description="Seed for reproducibility")
    time_budget_seconds: float = Field(default=180.0, ge=5.0, le=36000.0, description="Time budget: 120=FAST, 180=QUALITY (default), 300=PREMIUM, >3600=UNBOUNDED")
    preset_id: str = Field(default="default", description="Configuration preset")
    config_overrides: ConfigOverrides = Field(default_factory=ConfigOverrides)


class RunCreateRequest(BaseModel):
    """Request to start a v2 optimization run."""
    instance_id: str | None = None  # Optional ref
    tours: list[TourInput]
    drivers: list[DriverInput] = Field(default_factory=list)
    week_start: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    run: RunConfig = Field(default_factory=RunConfig)


class RunCreateResponse(BaseModel):
    """Response for run creation."""
    run_id: str
    status: str
    events_url: str
    run_url: str


class RunLinks(BaseModel):
    """HATEOAS links for a run."""
    events: str
    report: str
    plan: str
    canonical_report: str
    cancel: str


class RunStatusResponse(BaseModel):
    """Status of a run."""
    run_id: str
    status: str
    phase: str | None
    budget: dict
    links: RunLinks
    created_at: str


class ConfigFieldSchema(BaseModel):
    """Schema metadata for a config field."""
    key: str
    type: str
    default: bool | float | int | str | None
    editable: bool
    description: str
    locked_reason: str | None = None
    min: float | int | None = None
    max: float | int | None = None


class ConfigGroupSchema(BaseModel):
    """Group of config fields."""
    id: str
    label: str
    fields: list[ConfigFieldSchema]


class ConfigSchemaResponse(BaseModel):
    """Response for configuration UI schema."""
    version: str
    groups: list[ConfigGroupSchema]
