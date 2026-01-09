# =============================================================================
# SOLVEREIGN Routing Pack - API Schemas
# =============================================================================
# Pydantic models for request/response validation.
# =============================================================================

from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from uuid import UUID


# =============================================================================
# ENUMS
# =============================================================================

class VerticalType(str, Enum):
    """Supported verticals."""
    MEDIAMARKT = "MEDIAMARKT"
    HDL_PLUS = "HDL_PLUS"


class StopCategoryType(str, Enum):
    """Stop categories."""
    DELIVERY = "DELIVERY"
    MONTAGE = "MONTAGE"
    PICKUP = "PICKUP"
    ENTSORGUNG = "ENTSORGUNG"


class PriorityType(str, Enum):
    """Stop priority levels."""
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PlanStatusType(str, Enum):
    """Plan status values."""
    QUEUED = "QUEUED"
    SOLVING = "SOLVING"
    SOLVED = "SOLVED"
    AUDITED = "AUDITED"
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class RepairEventTypeEnum(str, Enum):
    """Repair event types."""
    NO_SHOW = "NO_SHOW"
    DELAY = "DELAY"
    VEHICLE_DOWN = "VEHICLE_DOWN"
    NEW_ORDER = "NEW_ORDER"
    CANCEL = "CANCEL"


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class AddressInput(BaseModel):
    """Address input for geocoding."""
    street: str = Field(..., min_length=1, max_length=255)
    house_number: str = Field(..., min_length=1, max_length=20)
    postal_code: str = Field(..., min_length=4, max_length=10)
    city: str = Field(..., min_length=1, max_length=100)
    country: str = Field(default="DE", max_length=2)
    additional_info: Optional[str] = None


class StopInput(BaseModel):
    """Stop input for scenario creation."""
    order_id: str = Field(..., min_length=1, max_length=100)
    service_code: str = Field(..., min_length=1, max_length=100)

    # Address (optional if lat/lng provided)
    address: Optional[AddressInput] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)

    # Time Window (P0-5: datetime, not TIME)
    tw_start: datetime
    tw_end: datetime
    tw_is_hard: bool = True

    # Service
    service_duration_min: int = Field(..., ge=0, le=480)
    requires_two_person: bool = False
    required_skills: List[str] = Field(default_factory=list)
    floor: Optional[int] = None

    # Capacity
    volume_m3: float = Field(default=0.0, ge=0)
    weight_kg: float = Field(default=0.0, ge=0)
    load_delta: int = Field(default=-1)  # -1 = Delivery, +1 = Pickup

    # Priority
    priority: PriorityType = PriorityType.NORMAL

    @field_validator('tw_end')
    @classmethod
    def validate_time_window(cls, v, info):
        if 'tw_start' in info.data and v <= info.data['tw_start']:
            raise ValueError('tw_end must be after tw_start')
        return v


class DepotInput(BaseModel):
    """Depot input for scenario creation."""
    site_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    loading_time_min: int = Field(default=15, ge=0, le=120)


class VehicleInput(BaseModel):
    """Vehicle input for scenario creation."""
    external_id: Optional[str] = None
    team_id: Optional[str] = None
    team_size: int = Field(default=1, ge=1, le=2)
    skills: List[str] = Field(default_factory=list)

    # Shift (P0-5: datetime, not TIME)
    shift_start_at: datetime
    shift_end_at: datetime

    # Depots (P0-1: Multi-Depot)
    start_depot_id: str  # References depot.site_id
    end_depot_id: str    # References depot.site_id

    # Capacity
    capacity_volume_m3: Optional[float] = None
    capacity_weight_kg: Optional[float] = None

    @field_validator('shift_end_at')
    @classmethod
    def validate_shift(cls, v, info):
        if 'shift_start_at' in info.data and v <= info.data['shift_start_at']:
            raise ValueError('shift_end_at must be after shift_start_at')
        return v


class CreateScenarioRequest(BaseModel):
    """Request to create a new routing scenario."""
    vertical: VerticalType
    plan_date: date
    timezone: str = Field(default="Europe/Berlin")

    # Data
    depots: List[DepotInput] = Field(..., min_length=1)
    stops: List[StopInput] = Field(..., min_length=1)
    vehicles: List[VehicleInput] = Field(..., min_length=1)


class SolverConfigInput(BaseModel):
    """Solver configuration."""
    time_limit_seconds: int = Field(default=300, ge=10, le=3600)
    seed: Optional[int] = None
    first_solution_strategy: str = "PATH_CHEAPEST_ARC"
    local_search_metaheuristic: str = "GUIDED_LOCAL_SEARCH"
    allow_unassigned: bool = True


class SolveRequest(BaseModel):
    """Request to solve a scenario."""
    solver_config: SolverConfigInput = Field(default_factory=SolverConfigInput)


class RepairEventInput(BaseModel):
    """Repair event input."""
    event_type: RepairEventTypeEnum
    timestamp: datetime
    affected_stop_ids: List[str] = Field(default_factory=list)
    affected_vehicle_ids: List[str] = Field(default_factory=list)
    delay_minutes: int = Field(default=0, ge=0)
    reason: Optional[str] = None


class FreezeScopeInput(BaseModel):
    """Freeze scope for repair."""
    locked_stop_ids: List[str] = Field(default_factory=list)
    freeze_horizon_minutes: int = Field(default=60, ge=0)


class RepairRequest(BaseModel):
    """Request to repair a plan."""
    event: RepairEventInput
    freeze_scope: FreezeScopeInput = Field(default_factory=FreezeScopeInput)


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class DepotResponse(BaseModel):
    """Depot in response."""
    id: UUID
    site_id: str
    name: str
    lat: float
    lng: float
    loading_time_min: int


class StopResponse(BaseModel):
    """Stop in response."""
    id: UUID
    order_id: str
    service_code: str
    category: StopCategoryType
    lat: Optional[float]
    lng: Optional[float]
    geocode_quality: Optional[str]
    tw_start: datetime
    tw_end: datetime
    tw_is_hard: bool
    service_duration_min: int
    requires_two_person: bool
    required_skills: List[str]
    priority: PriorityType


class VehicleResponse(BaseModel):
    """Vehicle in response."""
    id: UUID
    external_id: Optional[str]
    team_id: Optional[str]
    team_size: int
    skills: List[str]
    shift_start_at: datetime
    shift_end_at: datetime
    start_depot_id: UUID
    end_depot_id: UUID


class RouteStopResponse(BaseModel):
    """Stop within a route."""
    stop_id: UUID
    order_id: str
    sequence_index: int
    arrival_at: Optional[datetime]
    departure_at: Optional[datetime]
    slack_minutes: Optional[int]
    is_locked: bool
    assignment_reason: Optional[str]


class RouteResponse(BaseModel):
    """Route in response."""
    vehicle_id: UUID
    stops: List[RouteStopResponse]
    total_distance_km: float
    total_duration_min: int
    total_service_min: int
    total_travel_min: int


class UnassignedStopResponse(BaseModel):
    """Unassigned stop with reason."""
    stop_id: UUID
    order_id: str
    reason_code: str
    reason_details: Optional[str]


class PlanKPIsResponse(BaseModel):
    """Plan KPIs."""
    total_vehicles: int
    total_stops: int
    total_distance_km: float
    total_duration_min: int
    unassigned_count: int
    on_time_percentage: float
    average_stops_per_vehicle: float
    utilization_percentage: float


class ScenarioResponse(BaseModel):
    """Scenario creation response."""
    scenario_id: UUID
    vertical: VerticalType
    plan_date: date
    status: str
    stops_count: int
    vehicles_count: int
    depots_count: int
    input_hash: str
    created_at: datetime


class SolveResponse(BaseModel):
    """Solve initiation response."""
    job_id: str
    status: str
    poll_url: str


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None


class PlanResponse(BaseModel):
    """Full plan response."""
    plan_id: UUID
    scenario_id: UUID
    status: PlanStatusType
    seed: Optional[int]
    routes: List[RouteResponse]
    unassigned: List[UnassignedStopResponse]
    kpis: PlanKPIsResponse
    created_at: datetime
    completed_at: Optional[datetime]
    locked_at: Optional[datetime]
    locked_by: Optional[str]


class RepairResponse(BaseModel):
    """Repair initiation response."""
    job_id: str
    status: str
    original_plan_id: UUID
    poll_url: str


class RepairResultResponse(BaseModel):
    """Repair result response."""
    new_plan_id: UUID
    original_plan_id: UUID
    stops_moved: int
    vehicles_changed: int
    churn_score: float
    diff: dict
