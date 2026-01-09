# =============================================================================
# SOLVEREIGN Routing Pack - Domain Models
# =============================================================================
# Core domain entities for VRP/VRPTW optimization.
#
# P0 FIXES INTEGRATED:
# - P0-1: Depot as separate entity with Multi-Depot support
# - P0-4: service_code instead of job_type for deterministic template lookup
# - P0-5: All time fields use datetime (TIMESTAMPTZ in DB)
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List
from uuid import UUID


# =============================================================================
# ENUMS
# =============================================================================

class StopCategory(str, Enum):
    """Category derived from service_code."""
    DELIVERY = "DELIVERY"
    MONTAGE = "MONTAGE"
    PICKUP = "PICKUP"
    ENTSORGUNG = "ENTSORGUNG"


class Priority(str, Enum):
    """Stop priority levels."""
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PlanStatus(str, Enum):
    """
    Unified state machine for routing plans.
    P0-3: Single status field on routing_plans (not scenario).

    State transitions:
    QUEUED -> SOLVING -> SOLVED -> AUDITED -> DRAFT -> LOCKED
                     |-> FAILED
    LOCKED -> SUPERSEDED (when replaced by repair)
    """
    QUEUED = "QUEUED"
    SOLVING = "SOLVING"
    SOLVED = "SOLVED"
    AUDITED = "AUDITED"
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class GeoCodeQuality(str, Enum):
    """Geocoding quality levels."""
    HIGH = "HIGH"          # Exact address match
    MEDIUM = "MEDIUM"      # Street-level match
    LOW = "LOW"            # City/postal code only
    MANUAL = "MANUAL"      # Manually entered coordinates
    MISSING = "MISSING"    # Not geocoded yet


class RepairEventType(str, Enum):
    """Types of events triggering route repair."""
    NO_SHOW = "NO_SHOW"              # Customer not available
    DELAY = "DELAY"                  # Vehicle/stop delay
    VEHICLE_DOWN = "VEHICLE_DOWN"    # Vehicle breakdown
    NEW_ORDER = "NEW_ORDER"          # Late-added order
    CANCEL = "CANCEL"                # Order cancelled


# =============================================================================
# VALUE OBJECTS
# =============================================================================

@dataclass(frozen=True)
class Address:
    """Delivery address (raw, for geocoding)."""
    street: str
    house_number: str
    postal_code: str
    city: str
    country: str = "DE"
    additional_info: Optional[str] = None

    def to_single_line(self) -> str:
        """Format for geocoding API."""
        parts = [self.street, self.house_number, self.postal_code, self.city]
        if self.country != "DE":
            parts.append(self.country)
        return ", ".join(parts)


@dataclass(frozen=True)
class Geocode:
    """Geographic coordinates."""
    lat: float
    lng: float

    def to_tuple(self) -> tuple[float, float]:
        return (self.lat, self.lng)


@dataclass(frozen=True)
class BreakPolicy:
    """
    Break rules for a vehicle/driver.
    Based on German labor law (ArbZG).
    """
    min_break_minutes: int = 30          # Minimum break duration
    required_after_minutes: int = 360    # Break required after 6h work
    max_work_before_break: int = 360     # Max 6h before first break
    break_window_start: Optional[int] = None  # Earliest break time (minutes from shift start)
    break_window_end: Optional[int] = None    # Latest break time (minutes from shift start)


@dataclass(frozen=True)
class TimeWindow:
    """
    P1.1: A single time window option for a stop.

    Stops can have multiple TimeWindows; the solver picks exactly one
    (or drops the stop if optional). Used for flexible delivery windows
    like "10:00-12:00 OR 14:00-16:00".
    """
    start: datetime
    end: datetime
    is_hard: bool = True          # Hard constraint or soft (penalty)
    label: Optional[str] = None   # Optional label: "morning", "afternoon" for UI

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "is_hard": self.is_hard,
            "label": self.label,
        }


# =============================================================================
# CORE ENTITIES
# =============================================================================

@dataclass(frozen=True)
class Depot:
    """
    P0-1: Depot as explicit entity for Multi-Depot support.

    Each vehicle has start_depot_id and end_depot_id (can be same or different).
    """
    id: str
    tenant_id: int
    site_id: str                     # External site code (e.g., "MM_BERLIN_01")
    name: str
    geocode: Geocode
    loading_time_min: int = 15       # Default loading time at depot
    is_active: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "site_id": self.site_id,
            "name": self.name,
            "lat": self.geocode.lat,
            "lng": self.geocode.lng,
            "loading_time_min": self.loading_time_min,
            "is_active": self.is_active,
        }


@dataclass(frozen=True)
class Stop:
    """
    Delivery/Montage/Pickup stop.

    P0-4: Uses service_code for deterministic template lookup.
    P0-5: All time fields are datetime (TIMESTAMPTZ).
    """
    # Required fields (no defaults) - must come first
    id: str
    order_id: str
    tenant_id: int
    scenario_id: str

    # Location
    address: Address
    geocode: Optional[Geocode]           # None = needs geocoding
    geocode_quality: Optional[GeoCodeQuality]

    # Time Window (P0-5: datetime, not TIME)
    tw_start: datetime
    tw_end: datetime

    # Service Type (P0-4: service_code for template lookup)
    service_code: str                    # MM_DELIVERY, HDL_MONTAGE_COMPLEX, etc.
    category: StopCategory               # Derived from service_code
    service_duration_min: int            # From template or override

    # Fields with defaults - must come after required fields
    tw_is_hard: bool = True              # Hard constraint or soft (penalty)

    # Requirements
    requires_two_person: bool = False
    required_skills: list[str] = field(default_factory=list)
    floor: Optional[int] = None          # Floor number (for time estimation)

    # Capacity (P1-8: load_delta for Pickup/Delivery dynamics)
    volume_m3: float = 0.0
    weight_kg: float = 0.0
    load_delta: int = -1                 # -1 = Delivery (decreases load), +1 = Pickup (increases)

    # Priority & Risk
    priority: Priority = Priority.NORMAL
    no_show_risk: float = 0.0            # 0.0-1.0, from historical data

    # P1.1: Multiple Time Windows (optional, backwards compatible)
    # If populated, overrides tw_start/tw_end/tw_is_hard for solver
    time_windows: Optional[List["TimeWindow"]] = None

    def is_geocoded(self) -> bool:
        return self.geocode is not None and self.geocode_quality != GeoCodeQuality.MISSING

    def get_time_windows(self) -> List["TimeWindow"]:
        """
        P1.1: Get all time windows for this stop.

        Returns single-element list if using legacy tw_start/tw_end,
        or full list if time_windows is populated.
        """
        if self.time_windows:
            return self.time_windows
        # Legacy mode: wrap single TW in list
        return [TimeWindow(
            start=self.tw_start,
            end=self.tw_end,
            is_hard=self.tw_is_hard,
            label="default"
        )]

    def has_multiple_time_windows(self) -> bool:
        """P1.1: Check if stop has multiple time window options."""
        return self.time_windows is not None and len(self.time_windows) > 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "tenant_id": self.tenant_id,
            "scenario_id": self.scenario_id,
            "address_raw": self.address.to_single_line(),
            "lat": self.geocode.lat if self.geocode else None,
            "lng": self.geocode.lng if self.geocode else None,
            "geocode_quality": self.geocode_quality.value if self.geocode_quality else None,
            "tw_start": self.tw_start.isoformat(),
            "tw_end": self.tw_end.isoformat(),
            "tw_is_hard": self.tw_is_hard,
            "service_code": self.service_code,
            "category": self.category.value,
            "service_duration_min": self.service_duration_min,
            "requires_two_person": self.requires_two_person,
            "required_skills": self.required_skills,
            "floor": self.floor,
            "volume_m3": self.volume_m3,
            "weight_kg": self.weight_kg,
            "load_delta": self.load_delta,
            "priority": self.priority.value,
            "no_show_risk": self.no_show_risk,
        }


@dataclass(frozen=True)
class Vehicle:
    """
    Vehicle/Team for routing.

    P0-1: Has FK to start_depot and end_depot (Multi-Depot).
    P0-5: Shift times are datetime (TIMESTAMPTZ).
    """
    id: str
    tenant_id: int
    scenario_id: str
    external_id: Optional[str] = None    # External reference (e.g., plate number)

    # Team
    team_id: str = ""
    team_size: int = 1                   # 1 or 2 (2-Mann team)
    skills: list[str] = field(default_factory=list)

    # Shift (P0-5: datetime, not TIME)
    shift_start_at: datetime = field(default_factory=datetime.now)
    shift_end_at: datetime = field(default_factory=datetime.now)
    break_rules: BreakPolicy = field(default_factory=BreakPolicy)

    # Capacity
    capacity_volume_m3: float = 0.0
    capacity_weight_kg: float = 0.0

    # Depots (P0-1: Multi-Depot)
    start_depot_id: str = ""
    end_depot_id: str = ""               # Can be same as start or different

    @property
    def shift_duration_minutes(self) -> int:
        """Total shift duration in minutes."""
        delta = self.shift_end_at - self.shift_start_at
        return int(delta.total_seconds() / 60)

    def has_skill(self, skill: str) -> bool:
        return skill in self.skills

    def has_all_skills(self, required: list[str]) -> bool:
        return all(self.has_skill(s) for s in required)

    def can_do_two_person(self) -> bool:
        return self.team_size >= 2

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "scenario_id": self.scenario_id,
            "external_id": self.external_id,
            "team_id": self.team_id,
            "team_size": self.team_size,
            "skills": self.skills,
            "shift_start_at": self.shift_start_at.isoformat(),
            "shift_end_at": self.shift_end_at.isoformat(),
            "capacity_volume_m3": self.capacity_volume_m3,
            "capacity_weight_kg": self.capacity_weight_kg,
            "start_depot_id": self.start_depot_id,
            "end_depot_id": self.end_depot_id,
        }


@dataclass
class RouteStop:
    """A stop within a route, with computed arrival/departure times."""
    stop_id: str
    sequence_index: int
    arrival_time: datetime
    departure_time: datetime
    slack_minutes: int = 0               # Buffer before time window end

    # Status
    is_locked: bool = False              # Frozen (cannot be reassigned)
    assignment_reason: str = ""          # Explainability: why this vehicle?

    # P1.1: Which time window was selected (None for single-TW stops)
    selected_window_index: Optional[int] = None

    @property
    def wait_time_minutes(self) -> int:
        """Time waiting at stop before service starts."""
        # Wait time = service start - arrival (if early)
        return max(0, self.slack_minutes)


@dataclass
class Route:
    """
    A vehicle's route for a day.
    Contains ordered sequence of stops.
    """
    id: str
    plan_id: str
    vehicle_id: str
    stops: list[RouteStop] = field(default_factory=list)

    # Computed metrics (populated after solve)
    total_distance_km: float = 0.0
    total_duration_min: int = 0
    total_service_min: int = 0
    total_travel_min: int = 0
    eta_risk_score: float = 0.0          # Risk of missing time windows

    def is_empty(self) -> bool:
        return len(self.stops) == 0

    def stop_count(self) -> int:
        return len(self.stops)

    def get_stop_ids(self) -> list[str]:
        return [s.stop_id for s in self.stops]


@dataclass
class RoutePlan:
    """
    Complete routing plan for a scenario.
    P0-3: Unified status (not on scenario).
    """
    id: str
    scenario_id: str
    tenant_id: int

    # Status (P0-3: single source of truth)
    status: PlanStatus = PlanStatus.QUEUED

    # Solver config
    seed: Optional[int] = None
    solver_config_hash: str = ""
    output_hash: Optional[str] = None

    # Job tracking
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    # Routes
    routes: dict[str, Route] = field(default_factory=dict)  # vehicle_id -> Route
    unassigned_stop_ids: list[str] = field(default_factory=list)

    # Metrics
    total_vehicles: int = 0
    total_distance_km: float = 0.0
    total_duration_min: int = 0
    unassigned_count: int = 0
    on_time_percentage: float = 0.0

    # Lock info
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None

    def is_locked(self) -> bool:
        return self.status == PlanStatus.LOCKED

    def can_modify(self) -> bool:
        return self.status not in (PlanStatus.LOCKED, PlanStatus.SUPERSEDED)


# =============================================================================
# REPAIR ENTITIES
# =============================================================================

@dataclass
class RepairEvent:
    """Event that triggers route repair."""
    event_type: RepairEventType
    timestamp: datetime
    affected_stop_ids: list[str] = field(default_factory=list)
    affected_vehicle_ids: list[str] = field(default_factory=list)
    delay_minutes: int = 0               # For DELAY events
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "affected_stop_ids": self.affected_stop_ids,
            "affected_vehicle_ids": self.affected_vehicle_ids,
            "delay_minutes": self.delay_minutes,
            "reason": self.reason,
        }


@dataclass
class FreezeScope:
    """Defines which stops are locked (cannot be reassigned)."""
    locked_stop_ids: list[str] = field(default_factory=list)
    freeze_horizon_minutes: int = 60     # Stops within this time are frozen

    def is_locked(self, stop_id: str) -> bool:
        return stop_id in self.locked_stop_ids


# =============================================================================
# CONFIG OBJECTS
# =============================================================================

@dataclass
class SolverConfig:
    """Configuration for the VRP solver."""
    time_limit_seconds: int = 300        # Solver time limit
    solution_limit: int = 0              # Max solutions (0 = unlimited)
    seed: Optional[int] = None           # Random seed for reproducibility

    # First solution strategy
    first_solution_strategy: str = "PATH_CHEAPEST_ARC"

    # Local search metaheuristic
    local_search_metaheuristic: str = "GUIDED_LOCAL_SEARCH"

    # Penalties
    allow_unassigned: bool = True        # Allow dropping stops
    unassigned_penalty: int = 1_000_000  # Cost for unassigned stop

    def config_hash(self) -> str:
        """Generate hash for idempotency."""
        import hashlib
        config_str = f"{self.time_limit_seconds}:{self.seed}:{self.first_solution_strategy}:{self.local_search_metaheuristic}"
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]


@dataclass
class ChurnConfig:
    """Configuration for churn-aware repair."""
    reassignment_penalty: int = 10_000   # Cost for moving stop to different vehicle
    resequence_penalty: int = 1_000      # Cost for changing stop sequence
    max_churn: int = 100_000             # Maximum accumulated churn cost
    freeze_horizon_minutes: int = 60     # Auto-freeze stops within this time

    # Thresholds
    max_stops_moved: int = 10            # Alert if more stops moved
    max_vehicles_changed: int = 5        # Alert if more vehicles affected


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# =============================================================================
# PRECEDENCE CONSTRAINTS (P0)
# =============================================================================

@dataclass(frozen=True)
class PrecedencePair:
    """
    P0: Precedence constraint between two stops.

    Use Cases:
    - Pickup → Delivery (part pickup before installation)
    - Altgerät return to depot (pickup at customer → delivery at depot)

    IMPORTANT: "Exchange at same customer" (new device in, old device out)
    is NOT a precedence pair - it's service time + capacity logic.
    Only use this for true "A must happen before B" dependencies.
    """
    # Stop IDs (NOT node indices - conversion happens in constraints.py)
    pickup_stop_id: str
    delivery_stop_id: str

    # Same vehicle constraint (almost always True for real precedence)
    same_vehicle: bool = True

    # Optional: Maximum time lag between pickup and delivery (seconds)
    # None = no limit
    max_lag_seconds: Optional[int] = None

    # Hard constraint or soft (with penalty)
    is_hard: bool = True

    # Penalty if soft constraint is violated (only used if is_hard=False)
    violation_penalty: int = 100_000

    # Descriptive reason for this constraint (for debugging/evidence)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "pickup_stop_id": self.pickup_stop_id,
            "delivery_stop_id": self.delivery_stop_id,
            "same_vehicle": self.same_vehicle,
            "max_lag_seconds": self.max_lag_seconds,
            "is_hard": self.is_hard,
            "violation_penalty": self.violation_penalty,
            "reason": self.reason,
        }


@dataclass
class MultiStartConfig:
    """
    P0: Configuration for multi-start best-of solving.

    Strategy: Run solver multiple times with different seeds,
    pick the best solution based on lexicographic scoring.
    """
    # Number of seeds to try
    num_seeds: int = 10

    # Seed values (if None, uses range(num_seeds))
    seeds: Optional[list[int]] = None

    # Time limit per run (total time = num_seeds * per_run_time_limit)
    per_run_time_limit_seconds: int = 30

    # Overall time cap (stops early if exceeded)
    overall_time_limit_seconds: int = 300

    # Determinism: force single worker per run
    force_single_worker: bool = True

    # Score weights for lexicographic comparison (higher = more important)
    # Negative penalty means "minimize this"
    score_weights: dict = field(default_factory=lambda: {
        "unassigned_count": -1_000_000,      # P1: Minimize unassigned (Coverage)
        "hard_tw_violations": -500_000,       # P2: Minimize hard TW violations
        "overtime_minutes": -1_000,           # P3: Minimize overtime
        "total_travel_minutes": -1,           # P4: Minimize travel time
    })

    def get_seeds(self) -> list[int]:
        """Get list of seeds to try."""
        if self.seeds:
            return self.seeds
        return list(range(self.num_seeds))

    def to_dict(self) -> dict:
        return {
            "num_seeds": self.num_seeds,
            "seeds": self.get_seeds(),
            "per_run_time_limit_seconds": self.per_run_time_limit_seconds,
            "overall_time_limit_seconds": self.overall_time_limit_seconds,
            "force_single_worker": self.force_single_worker,
            "score_weights": self.score_weights,
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def derive_category_from_service_code(service_code: str) -> StopCategory:
    """
    P0-4: Derive stop category from service_code.

    Mapping:
    - MM_DELIVERY -> DELIVERY
    - MM_DELIVERY_MONTAGE -> MONTAGE
    - MM_ENTSORGUNG -> ENTSORGUNG
    - HDL_MONTAGE_* -> MONTAGE
    - *_PICKUP -> PICKUP
    """
    code_upper = service_code.upper()

    if "PICKUP" in code_upper:
        return StopCategory.PICKUP
    elif "ENTSORGUNG" in code_upper:
        return StopCategory.ENTSORGUNG
    elif "MONTAGE" in code_upper:
        return StopCategory.MONTAGE
    else:
        return StopCategory.DELIVERY
