"""
SOLVEREIGN V3.3b API - Config Router
=====================================

Configuration schema and validation endpoints.
Migrated from legacy routes_v2.py for Enterprise API.

Endpoints:
- GET  /config/schema     Get configuration schema
- POST /config/validate   Validate configuration overrides
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..dependencies import get_current_tenant, TenantContext


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class ConfigFieldSchema(BaseModel):
    """Schema for a single configuration field."""
    name: str
    type: str
    default: Any
    description: str
    description_de: str
    min: Optional[float] = None
    max: Optional[float] = None
    unit: Optional[str] = None
    tunable: bool = True
    locked: bool = False


class ConfigGroupSchema(BaseModel):
    """Schema for a configuration group."""
    name: str
    name_de: str
    description: str
    fields: List[ConfigFieldSchema]


class ConfigSchemaResponse(BaseModel):
    """Full configuration schema."""
    version: str
    groups: List[ConfigGroupSchema]


class ConfigOverrides(BaseModel):
    """Configuration overrides to validate."""
    max_weekly_hours: Optional[float] = Field(None, ge=40, le=60)
    max_daily_span_hours: Optional[float] = Field(None, ge=10, le=18)
    max_tours_per_day: Optional[int] = Field(None, ge=1, le=5)
    min_rest_hours: Optional[float] = Field(None, ge=8, le=14)
    seed: Optional[int] = Field(None, ge=0)
    time_limit_seconds: Optional[int] = Field(None, ge=10, le=3600)
    freeze_window_hours: Optional[float] = Field(None, ge=0, le=48)
    gap_3er_min_minutes: Optional[int] = Field(None, ge=15, le=120)
    gap_3er_max_minutes: Optional[int] = Field(None, ge=30, le=180)


class ValidationResult(BaseModel):
    """Result of configuration validation."""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    applied_config: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# CONFIG DEFINITIONS
# =============================================================================

# Tunable fields (can be changed by user)
TUNABLE_FIELDS = {
    "max_weekly_hours": {
        "type": "float",
        "default": 55.0,
        "min": 40.0,
        "max": 60.0,
        "unit": "hours",
        "description": "Maximum weekly working hours per driver",
        "description_de": "Maximale Wochenarbeitszeit pro Fahrer",
    },
    "max_daily_span_hours": {
        "type": "float",
        "default": 15.5,
        "min": 10.0,
        "max": 18.0,
        "unit": "hours",
        "description": "Maximum daily span (first tour start to last tour end)",
        "description_de": "Maximale Tagesspanne (Start erste Tour bis Ende letzte Tour)",
    },
    "max_tours_per_day": {
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 5,
        "unit": "tours",
        "description": "Maximum tours assigned to one driver per day",
        "description_de": "Maximale Touren pro Fahrer pro Tag",
    },
    "min_rest_hours": {
        "type": "float",
        "default": 11.0,
        "min": 8.0,
        "max": 14.0,
        "unit": "hours",
        "description": "Minimum rest between consecutive working days",
        "description_de": "Minimale Ruhezeit zwischen aufeinanderfolgenden Arbeitstagen",
    },
    "seed": {
        "type": "int",
        "default": 94,
        "min": 0,
        "max": None,
        "unit": None,
        "description": "Random seed for reproducibility",
        "description_de": "Seed für Reproduzierbarkeit",
    },
    "time_limit_seconds": {
        "type": "int",
        "default": 300,
        "min": 10,
        "max": 3600,
        "unit": "seconds",
        "description": "Solver time limit",
        "description_de": "Zeitlimit für Solver",
    },
    "freeze_window_hours": {
        "type": "float",
        "default": 12.0,
        "min": 0.0,
        "max": 48.0,
        "unit": "hours",
        "description": "Hours before tour start when it becomes frozen",
        "description_de": "Stunden vor Tourstart ab denen Tour eingefroren ist",
    },
    "gap_3er_min_minutes": {
        "type": "int",
        "default": 30,
        "min": 15,
        "max": 120,
        "unit": "minutes",
        "description": "Minimum gap between tours in 3er blocks",
        "description_de": "Minimaler Abstand zwischen Touren in 3er-Blöcken",
    },
    "gap_3er_max_minutes": {
        "type": "int",
        "default": 60,
        "min": 30,
        "max": 180,
        "unit": "minutes",
        "description": "Maximum gap between tours in 3er blocks",
        "description_de": "Maximaler Abstand zwischen Touren in 3er-Blöcken",
    },
}

# Locked fields (cannot be changed - legal requirements)
LOCKED_FIELDS = {
    "min_rest_between_days_hours": {
        "type": "float",
        "value": 11.0,
        "description": "Minimum rest between working days (ArbZG)",
        "description_de": "Minimale Ruhezeit zwischen Arbeitstagen (ArbZG)",
        "legal_reference": "ArbZG §5",
    },
    "max_daily_working_hours": {
        "type": "float",
        "value": 10.0,
        "description": "Maximum daily working hours (ArbZG)",
        "description_de": "Maximale tägliche Arbeitszeit (ArbZG)",
        "legal_reference": "ArbZG §3",
    },
    "max_weekly_hours_legal": {
        "type": "float",
        "value": 60.0,
        "description": "Maximum weekly hours (absolute legal limit)",
        "description_de": "Maximale Wochenstunden (gesetzliches Maximum)",
        "legal_reference": "ArbZG §3",
    },
}


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/schema", response_model=ConfigSchemaResponse)
async def get_config_schema(
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Get the configuration schema.

    Returns all tunable and locked configuration fields with
    their types, defaults, ranges, and descriptions.
    """
    groups = [
        ConfigGroupSchema(
            name="solver",
            name_de="Solver-Einstellungen",
            description="Core optimization settings",
            fields=[
                ConfigFieldSchema(
                    name="seed",
                    type=TUNABLE_FIELDS["seed"]["type"],
                    default=TUNABLE_FIELDS["seed"]["default"],
                    description=TUNABLE_FIELDS["seed"]["description"],
                    description_de=TUNABLE_FIELDS["seed"]["description_de"],
                    min=TUNABLE_FIELDS["seed"]["min"],
                    max=TUNABLE_FIELDS["seed"]["max"],
                    unit=TUNABLE_FIELDS["seed"]["unit"],
                    tunable=True,
                    locked=False,
                ),
                ConfigFieldSchema(
                    name="time_limit_seconds",
                    type=TUNABLE_FIELDS["time_limit_seconds"]["type"],
                    default=TUNABLE_FIELDS["time_limit_seconds"]["default"],
                    description=TUNABLE_FIELDS["time_limit_seconds"]["description"],
                    description_de=TUNABLE_FIELDS["time_limit_seconds"]["description_de"],
                    min=TUNABLE_FIELDS["time_limit_seconds"]["min"],
                    max=TUNABLE_FIELDS["time_limit_seconds"]["max"],
                    unit=TUNABLE_FIELDS["time_limit_seconds"]["unit"],
                    tunable=True,
                    locked=False,
                ),
            ],
        ),
        ConfigGroupSchema(
            name="constraints",
            name_de="Constraints",
            description="Working time and tour constraints",
            fields=[
                ConfigFieldSchema(
                    name="max_weekly_hours",
                    type=TUNABLE_FIELDS["max_weekly_hours"]["type"],
                    default=TUNABLE_FIELDS["max_weekly_hours"]["default"],
                    description=TUNABLE_FIELDS["max_weekly_hours"]["description"],
                    description_de=TUNABLE_FIELDS["max_weekly_hours"]["description_de"],
                    min=TUNABLE_FIELDS["max_weekly_hours"]["min"],
                    max=TUNABLE_FIELDS["max_weekly_hours"]["max"],
                    unit=TUNABLE_FIELDS["max_weekly_hours"]["unit"],
                    tunable=True,
                    locked=False,
                ),
                ConfigFieldSchema(
                    name="max_daily_span_hours",
                    type=TUNABLE_FIELDS["max_daily_span_hours"]["type"],
                    default=TUNABLE_FIELDS["max_daily_span_hours"]["default"],
                    description=TUNABLE_FIELDS["max_daily_span_hours"]["description"],
                    description_de=TUNABLE_FIELDS["max_daily_span_hours"]["description_de"],
                    min=TUNABLE_FIELDS["max_daily_span_hours"]["min"],
                    max=TUNABLE_FIELDS["max_daily_span_hours"]["max"],
                    unit=TUNABLE_FIELDS["max_daily_span_hours"]["unit"],
                    tunable=True,
                    locked=False,
                ),
                ConfigFieldSchema(
                    name="max_tours_per_day",
                    type=TUNABLE_FIELDS["max_tours_per_day"]["type"],
                    default=TUNABLE_FIELDS["max_tours_per_day"]["default"],
                    description=TUNABLE_FIELDS["max_tours_per_day"]["description"],
                    description_de=TUNABLE_FIELDS["max_tours_per_day"]["description_de"],
                    min=TUNABLE_FIELDS["max_tours_per_day"]["min"],
                    max=TUNABLE_FIELDS["max_tours_per_day"]["max"],
                    unit=TUNABLE_FIELDS["max_tours_per_day"]["unit"],
                    tunable=True,
                    locked=False,
                ),
                ConfigFieldSchema(
                    name="min_rest_hours",
                    type=TUNABLE_FIELDS["min_rest_hours"]["type"],
                    default=TUNABLE_FIELDS["min_rest_hours"]["default"],
                    description=TUNABLE_FIELDS["min_rest_hours"]["description"],
                    description_de=TUNABLE_FIELDS["min_rest_hours"]["description_de"],
                    min=TUNABLE_FIELDS["min_rest_hours"]["min"],
                    max=TUNABLE_FIELDS["min_rest_hours"]["max"],
                    unit=TUNABLE_FIELDS["min_rest_hours"]["unit"],
                    tunable=True,
                    locked=False,
                ),
            ],
        ),
        ConfigGroupSchema(
            name="freeze",
            name_de="Freeze-Einstellungen",
            description="Freeze window and stability settings",
            fields=[
                ConfigFieldSchema(
                    name="freeze_window_hours",
                    type=TUNABLE_FIELDS["freeze_window_hours"]["type"],
                    default=TUNABLE_FIELDS["freeze_window_hours"]["default"],
                    description=TUNABLE_FIELDS["freeze_window_hours"]["description"],
                    description_de=TUNABLE_FIELDS["freeze_window_hours"]["description_de"],
                    min=TUNABLE_FIELDS["freeze_window_hours"]["min"],
                    max=TUNABLE_FIELDS["freeze_window_hours"]["max"],
                    unit=TUNABLE_FIELDS["freeze_window_hours"]["unit"],
                    tunable=True,
                    locked=False,
                ),
            ],
        ),
        ConfigGroupSchema(
            name="quality",
            name_de="Qualitäts-Einstellungen",
            description="3er block gap requirements",
            fields=[
                ConfigFieldSchema(
                    name="gap_3er_min_minutes",
                    type=TUNABLE_FIELDS["gap_3er_min_minutes"]["type"],
                    default=TUNABLE_FIELDS["gap_3er_min_minutes"]["default"],
                    description=TUNABLE_FIELDS["gap_3er_min_minutes"]["description"],
                    description_de=TUNABLE_FIELDS["gap_3er_min_minutes"]["description_de"],
                    min=TUNABLE_FIELDS["gap_3er_min_minutes"]["min"],
                    max=TUNABLE_FIELDS["gap_3er_min_minutes"]["max"],
                    unit=TUNABLE_FIELDS["gap_3er_min_minutes"]["unit"],
                    tunable=True,
                    locked=False,
                ),
                ConfigFieldSchema(
                    name="gap_3er_max_minutes",
                    type=TUNABLE_FIELDS["gap_3er_max_minutes"]["type"],
                    default=TUNABLE_FIELDS["gap_3er_max_minutes"]["default"],
                    description=TUNABLE_FIELDS["gap_3er_max_minutes"]["description"],
                    description_de=TUNABLE_FIELDS["gap_3er_max_minutes"]["description_de"],
                    min=TUNABLE_FIELDS["gap_3er_max_minutes"]["min"],
                    max=TUNABLE_FIELDS["gap_3er_max_minutes"]["max"],
                    unit=TUNABLE_FIELDS["gap_3er_max_minutes"]["unit"],
                    tunable=True,
                    locked=False,
                ),
            ],
        ),
        ConfigGroupSchema(
            name="legal",
            name_de="Gesetzliche Vorgaben",
            description="Locked legal requirements (ArbZG)",
            fields=[
                ConfigFieldSchema(
                    name="min_rest_between_days_hours",
                    type=LOCKED_FIELDS["min_rest_between_days_hours"]["type"],
                    default=LOCKED_FIELDS["min_rest_between_days_hours"]["value"],
                    description=LOCKED_FIELDS["min_rest_between_days_hours"]["description"],
                    description_de=LOCKED_FIELDS["min_rest_between_days_hours"]["description_de"],
                    tunable=False,
                    locked=True,
                ),
                ConfigFieldSchema(
                    name="max_daily_working_hours",
                    type=LOCKED_FIELDS["max_daily_working_hours"]["type"],
                    default=LOCKED_FIELDS["max_daily_working_hours"]["value"],
                    description=LOCKED_FIELDS["max_daily_working_hours"]["description"],
                    description_de=LOCKED_FIELDS["max_daily_working_hours"]["description_de"],
                    tunable=False,
                    locked=True,
                ),
                ConfigFieldSchema(
                    name="max_weekly_hours_legal",
                    type=LOCKED_FIELDS["max_weekly_hours_legal"]["type"],
                    default=LOCKED_FIELDS["max_weekly_hours_legal"]["value"],
                    description=LOCKED_FIELDS["max_weekly_hours_legal"]["description"],
                    description_de=LOCKED_FIELDS["max_weekly_hours_legal"]["description_de"],
                    tunable=False,
                    locked=True,
                ),
            ],
        ),
    ]

    return ConfigSchemaResponse(version="3.3b", groups=groups)


@router.post("/validate", response_model=ValidationResult)
async def validate_config(
    overrides: ConfigOverrides,
    tenant: TenantContext = Depends(get_current_tenant),
):
    """
    Validate configuration overrides.

    Checks that:
    - All values are within allowed ranges
    - No locked fields are modified
    - Values are logically consistent

    Returns validation result with applied config.
    """
    errors = []
    warnings = []
    applied = {}

    # Get default config
    defaults = {name: field["default"] for name, field in TUNABLE_FIELDS.items()}

    # Apply overrides
    override_dict = overrides.model_dump(exclude_none=True)

    for name, value in override_dict.items():
        if name in TUNABLE_FIELDS:
            field = TUNABLE_FIELDS[name]

            # Check min
            if field["min"] is not None and value < field["min"]:
                errors.append(f"{name}: {value} is below minimum {field['min']}")
                continue

            # Check max
            if field["max"] is not None and value > field["max"]:
                errors.append(f"{name}: {value} is above maximum {field['max']}")
                continue

            applied[name] = value

        elif name in LOCKED_FIELDS:
            errors.append(f"{name} is locked and cannot be modified (legal requirement)")

        else:
            warnings.append(f"Unknown field: {name}")

    # Merge with defaults
    final_config = {**defaults, **applied}

    # Logical consistency checks
    if "gap_3er_min_minutes" in applied and "gap_3er_max_minutes" in applied:
        if applied["gap_3er_min_minutes"] > applied["gap_3er_max_minutes"]:
            errors.append("gap_3er_min_minutes cannot be greater than gap_3er_max_minutes")

    if "max_weekly_hours" in applied:
        if applied["max_weekly_hours"] > LOCKED_FIELDS["max_weekly_hours_legal"]["value"]:
            errors.append(
                f"max_weekly_hours cannot exceed legal limit of "
                f"{LOCKED_FIELDS['max_weekly_hours_legal']['value']}h"
            )

    # Add warnings for edge cases
    if applied.get("max_weekly_hours", 55) > 50:
        warnings.append("max_weekly_hours > 50h may increase driver fatigue")

    if applied.get("freeze_window_hours", 12) < 6:
        warnings.append("freeze_window_hours < 6h may cause operational instability")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        applied_config=final_config,
    )
