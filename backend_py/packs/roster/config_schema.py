"""
Roster Pack Configuration Schema

Defines the policy profile configuration for the roster pack.
Used by PolicyService to validate tenant-specific configurations.

Configuration Fields:
- TUNABLE: Can be adjusted per tenant (within bounds)
- LOCKED: German labor law constraints (cannot be changed)

See ADR-002: Policy Profiles for architecture details.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from enum import Enum


class OptimizationGoal(str, Enum):
    """Primary optimization objective."""
    MINIMIZE_DRIVERS = "minimize_drivers"
    MINIMIZE_SPLITS = "minimize_splits"
    BALANCE_WORKLOAD = "balance_workload"


class SolverEngine(str, Enum):
    """
    Solver engine selection.

    V3 = Original BlockHeuristicSolver (Min-Cost Max-Flow) - PRODUCTION DEFAULT
    V4 = Experimental FeasibilityPipeline (Lexicographic) - R&D ONLY

    IMPORTANT: V3 is the canonical solver that produces 145 FTE / 0 PT.
    V4 is experimental and must be explicitly opted-in.
    """
    V3 = "v3"  # Default: Greedy Partitioning + Min-Cost Max-Flow + PT Elimination
    V4 = "v4"  # Experimental: Complex lexicographic phase (may timeout/produce PT overflow)


class RosterPolicyConfig(BaseModel):
    """
    Configuration schema for roster pack (v1.0).

    All fields have default values that match current production behavior.
    Tenants can override these within the specified bounds.
    """

    # === DRIVER CONSTRAINTS (TUNABLE) ===

    max_weekly_hours: int = Field(
        55,
        ge=40,
        le=60,
        description="Maximum weekly hours per driver (German law allows up to 60 with exceptions)"
    )

    min_rest_hours: int = Field(
        11,
        ge=9,
        le=12,
        description="Minimum rest between consecutive work days"
    )

    max_span_regular_hours: int = Field(
        14,
        ge=12,
        le=16,
        description="Maximum span for 1er/2er-regular blocks"
    )

    max_span_split_hours: int = Field(
        16,
        ge=14,
        le=18,
        description="Maximum span for 3er/split blocks"
    )

    # === SPLIT BREAK CONSTRAINTS (TUNABLE) ===

    min_split_break_minutes: int = Field(
        240,
        ge=180,
        le=300,
        description="Minimum break in split shift (4-5 hours)"
    )

    max_split_break_minutes: int = Field(
        360,
        ge=300,
        le=420,
        description="Maximum break in split shift (5-7 hours)"
    )

    # === BLOCK CONSTRUCTION (TUNABLE) ===

    min_gap_between_tours_minutes: int = Field(
        30,
        ge=15,
        le=60,
        description="Minimum gap between tours in a 2er/3er block"
    )

    max_gap_between_tours_minutes: int = Field(
        60,
        ge=45,
        le=90,
        description="Maximum gap between tours in a 2er/3er block"
    )

    # === OPTIMIZATION PREFERENCES (TUNABLE) ===

    optimization_goal: OptimizationGoal = Field(
        OptimizationGoal.MINIMIZE_DRIVERS,
        description="Primary optimization objective"
    )

    prefer_fte_over_pt: bool = Field(
        True,
        description="Prefer full-time over part-time drivers in assignments"
    )

    minimize_splits: bool = Field(
        True,
        description="Minimize split shifts when possible"
    )

    allow_3er_consecutive: bool = Field(
        False,
        description="Allow 3er blocks on consecutive days (fatigue risk)"
    )

    # === SOLVER SETTINGS (TUNABLE) ===

    solver_engine: SolverEngine = Field(
        SolverEngine.V3,
        description="Solver engine: 'v3' (production default) or 'v4' (experimental R&D only)"
    )

    solver_time_limit_seconds: int = Field(
        300,
        ge=60,
        le=3600,
        description="Maximum solver time in seconds"
    )

    seed: Optional[int] = Field(
        94,
        ge=1,
        le=10000,
        description="Solver seed for reproducibility (None for random)"
    )

    refinement_passes: int = Field(
        3,
        ge=1,
        le=10,
        description="Number of LNS refinement passes"
    )

    # === AUDIT SETTINGS (TUNABLE) ===

    fail_on_audit_warning: bool = Field(
        False,
        description="Treat audit warnings as failures (strict mode)"
    )

    required_coverage_percent: float = Field(
        100.0,
        ge=95.0,
        le=100.0,
        description="Minimum coverage percentage to pass audit"
    )

    # === FEATURE CAPABILITY FLAGS (P0 WIEN PILOT) ===
    # These flags control which roster pack features are available.
    # All P0 features default to True for Wien Pilot.

    enable_pins: bool = Field(
        True,
        description="Enable pin/lock feature for anti-churn (prevents solver changes to pinned assignments)"
    )

    enable_repairs: bool = Field(
        True,
        description="Enable repair workflow (SWAP/MOVE/FILL/CLEAR actions with preview and apply)"
    )

    enable_violations_overlay: bool = Field(
        True,
        description="Enable violations overlay in matrix view (BLOCK/WARN badges on cells)"
    )

    enable_diff_preview: bool = Field(
        True,
        description="Enable diff preview before publish (KPI delta, churn count, change list)"
    )

    enable_publish_gate: bool = Field(
        True,
        description="Enable server-side publish gate (blocks publish when BLOCK violations exist)"
    )

    enable_audit_notes: bool = Field(
        True,
        description="Require audit notes (reason_code + note) on all mutations"
    )

    repair_session_timeout_minutes: int = Field(
        30,
        ge=5,
        le=120,
        description="Repair session expiry timeout in minutes"
    )

    max_repair_actions_per_session: int = Field(
        100,
        ge=10,
        le=500,
        description="Maximum number of repair actions allowed per session"
    )

    # === VALIDATORS ===

    @validator('max_split_break_minutes')
    def split_break_range_valid(cls, v, values):
        """Ensure max > min for split break."""
        min_break = values.get('min_split_break_minutes', 240)
        if v <= min_break:
            raise ValueError(f'max_split_break_minutes ({v}) must be > min_split_break_minutes ({min_break})')
        return v

    @validator('max_gap_between_tours_minutes')
    def gap_range_valid(cls, v, values):
        """Ensure max > min for tour gaps."""
        min_gap = values.get('min_gap_between_tours_minutes', 30)
        if v <= min_gap:
            raise ValueError(f'max_gap ({v}) must be > min_gap ({min_gap})')
        return v

    # === LOCKED CONSTRAINTS (German Labor Law) ===

    @classmethod
    def locked_constraints(cls) -> dict:
        """
        Constraints that CANNOT be overridden by policy profiles.
        These are enforced by the solver regardless of configuration.

        Reference: Arbeitszeitgesetz (ArbZG)
        """
        return {
            # ArbZG §3: Maximum daily working time
            "absolute_max_daily_hours": 10,

            # ArbZG §3: Maximum weekly working time (exceptional)
            "absolute_max_weekly_hours": 60,

            # ArbZG §5: Minimum rest period (gesetzl. 11h, keine Branchenausnahme für Logistik)
            "absolute_min_rest_hours": 11,

            # Not configurable: Coverage must always be 100% attempted
            "coverage_target": 100,

            # Audit checks always run (cannot be disabled)
            "mandatory_audits": [
                "coverage",
                "overlap",
                "rest",
                "span_regular",
                "span_split",
                "fatigue",
                "max_hours"
            ],

            # P0 Wien Pilot: These features MUST remain enabled
            # (cannot be disabled for compliance/safety)
            "mandatory_features": [
                "enable_publish_gate",  # Server-side violation gate (safety)
                "enable_audit_notes",   # Audit trail (compliance)
            ]
        }

    class Config:
        """Pydantic config."""
        extra = "forbid"  # No unknown fields allowed
        use_enum_values = True


# === DEFAULT POLICY ===

DEFAULT_ROSTER_POLICY = RosterPolicyConfig()


# === SCHEMA VERSION ===

ROSTER_SCHEMA_VERSION = "1.1"  # Added feature capability flags for Wien Pilot


def validate_roster_config(config: dict) -> RosterPolicyConfig:
    """
    Validate a configuration dictionary against the roster schema.

    Args:
        config: Dictionary of configuration values

    Returns:
        Validated RosterPolicyConfig instance

    Raises:
        pydantic.ValidationError: If config is invalid
    """
    return RosterPolicyConfig(**config)


def get_config_with_defaults(overrides: dict) -> RosterPolicyConfig:
    """
    Create a config with defaults filled in for missing fields.

    Args:
        overrides: Partial configuration dictionary

    Returns:
        Complete RosterPolicyConfig with defaults for missing fields
    """
    defaults = DEFAULT_ROSTER_POLICY.dict()
    defaults.update(overrides)
    return RosterPolicyConfig(**defaults)
