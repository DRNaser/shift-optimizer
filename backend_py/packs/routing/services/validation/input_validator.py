# =============================================================================
# SOLVEREIGN Routing Pack - Input Validator
# =============================================================================
# Validates routing scenario input data with structured reject reasons.
#
# This is critical for production quality - 80% of routing failures are
# caused by bad input data. Validate early, fail fast, provide clear reasons.
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Dict, Set, Optional, Any

from ...domain.models import Stop, Vehicle, Depot

logger = logging.getLogger(__name__)


# =============================================================================
# REJECT REASON CODES
# =============================================================================

class RejectReason(str, Enum):
    """
    Structured reject reason codes.

    Format: ENTITY_ISSUE
    These codes are stable API contracts - don't rename without versioning.
    """
    # Geocode issues
    STOP_MISSING_GEOCODE = "STOP_MISSING_GEOCODE"
    STOP_INVALID_LATITUDE = "STOP_INVALID_LATITUDE"
    STOP_INVALID_LONGITUDE = "STOP_INVALID_LONGITUDE"
    DEPOT_MISSING_GEOCODE = "DEPOT_MISSING_GEOCODE"
    DEPOT_INVALID_GEOCODE = "DEPOT_INVALID_GEOCODE"

    # Time window issues
    STOP_TW_START_AFTER_END = "STOP_TW_START_AFTER_END"
    STOP_TW_ZERO_DURATION = "STOP_TW_ZERO_DURATION"
    STOP_TW_OUTSIDE_PLAN_DAY = "STOP_TW_OUTSIDE_PLAN_DAY"
    STOP_TW_TOO_NARROW = "STOP_TW_TOO_NARROW"

    # Service duration issues
    STOP_SERVICE_DURATION_ZERO = "STOP_SERVICE_DURATION_ZERO"
    STOP_SERVICE_DURATION_NEGATIVE = "STOP_SERVICE_DURATION_NEGATIVE"
    STOP_SERVICE_DURATION_TOO_LONG = "STOP_SERVICE_DURATION_TOO_LONG"

    # Skill issues
    STOP_UNKNOWN_SKILL = "STOP_UNKNOWN_SKILL"
    VEHICLE_UNKNOWN_SKILL = "VEHICLE_UNKNOWN_SKILL"
    STOP_NO_ELIGIBLE_VEHICLE_SKILLS = "STOP_NO_ELIGIBLE_VEHICLE_SKILLS"

    # 2-Person issues
    STOP_NO_ELIGIBLE_TWO_PERSON = "STOP_NO_ELIGIBLE_TWO_PERSON"

    # Vehicle shift issues
    VEHICLE_SHIFT_START_AFTER_END = "VEHICLE_SHIFT_START_AFTER_END"
    VEHICLE_SHIFT_TOO_SHORT = "VEHICLE_SHIFT_TOO_SHORT"
    VEHICLE_SHIFT_TOO_LONG = "VEHICLE_SHIFT_TOO_LONG"

    # Depot issues
    VEHICLE_UNKNOWN_START_DEPOT = "VEHICLE_UNKNOWN_START_DEPOT"
    VEHICLE_UNKNOWN_END_DEPOT = "VEHICLE_UNKNOWN_END_DEPOT"

    # Capacity issues
    STOP_VOLUME_NEGATIVE = "STOP_VOLUME_NEGATIVE"
    STOP_WEIGHT_NEGATIVE = "STOP_WEIGHT_NEGATIVE"
    STOP_EXCEEDS_ALL_VEHICLE_CAPACITY = "STOP_EXCEEDS_ALL_VEHICLE_CAPACITY"

    # Scenario issues
    SCENARIO_NO_STOPS = "SCENARIO_NO_STOPS"
    SCENARIO_NO_VEHICLES = "SCENARIO_NO_VEHICLES"
    SCENARIO_NO_DEPOTS = "SCENARIO_NO_DEPOTS"


# =============================================================================
# VALIDATION RESULT MODELS
# =============================================================================

@dataclass
class ValidationError:
    """
    Single validation error with context.

    Designed for API responses and debugging.
    """
    reason: RejectReason
    entity_type: str           # "stop", "vehicle", "depot", "scenario"
    entity_id: Optional[str]   # ID of the problematic entity
    field: Optional[str]       # Field that failed validation
    message: str               # Human-readable description
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API-friendly dict."""
        return {
            "reason": self.reason.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "field": self.field,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ValidationResult:
    """
    Complete validation result.

    Includes all errors, warnings, and summary statistics.
    """
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    # Summary counts
    stops_validated: int = 0
    stops_failed: int = 0
    vehicles_validated: int = 0
    vehicles_failed: int = 0
    depots_validated: int = 0
    depots_failed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API-friendly dict."""
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "summary": {
                "stops": {"validated": self.stops_validated, "failed": self.stops_failed},
                "vehicles": {"validated": self.vehicles_validated, "failed": self.vehicles_failed},
                "depots": {"validated": self.depots_validated, "failed": self.depots_failed},
            }
        }


# =============================================================================
# VALIDATION CONFIG
# =============================================================================

@dataclass
class ValidationConfig:
    """Configuration for validation rules."""
    # Geocode bounds (Germany + buffer)
    min_latitude: float = 47.0
    max_latitude: float = 56.0
    min_longitude: float = 5.0
    max_longitude: float = 16.0

    # Time window constraints
    min_tw_duration_minutes: int = 30       # Minimum time window duration
    max_service_duration_minutes: int = 360  # 6 hours max

    # Shift constraints
    min_shift_duration_minutes: int = 60     # 1 hour minimum
    max_shift_duration_minutes: int = 720    # 12 hours maximum

    # Known skills catalog
    valid_skills: Set[str] = field(default_factory=lambda: {
        "MONTAGE_BASIC",
        "MONTAGE_ADVANCED",
        "HEAVY_LIFT",
        "ELEKTRO",
        "ENTSORGUNG",
        "FRAGILE",
        "HAZMAT",
    })


# =============================================================================
# INPUT VALIDATOR
# =============================================================================

class InputValidator:
    """
    Validates routing scenario input data.

    Usage:
        validator = InputValidator()
        result = validator.validate(stops, vehicles, depots)

        if not result.is_valid:
            for error in result.errors:
                print(f"{error.reason}: {error.message}")
    """

    def __init__(self, config: ValidationConfig = None):
        self.config = config or ValidationConfig()

    def validate(
        self,
        stops: List[Stop],
        vehicles: List[Vehicle],
        depots: List[Depot],
        plan_date: Optional[datetime] = None
    ) -> ValidationResult:
        """
        Validate complete scenario.

        Args:
            stops: List of stops to validate
            vehicles: List of vehicles to validate
            depots: List of depots to validate
            plan_date: Optional plan date for time window validation

        Returns:
            ValidationResult with all errors and warnings
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # Scenario-level validation
        if not stops:
            errors.append(ValidationError(
                reason=RejectReason.SCENARIO_NO_STOPS,
                entity_type="scenario",
                entity_id=None,
                field=None,
                message="No stops provided in scenario"
            ))

        if not vehicles:
            errors.append(ValidationError(
                reason=RejectReason.SCENARIO_NO_VEHICLES,
                entity_type="scenario",
                entity_id=None,
                field=None,
                message="No vehicles provided in scenario"
            ))

        if not depots:
            errors.append(ValidationError(
                reason=RejectReason.SCENARIO_NO_DEPOTS,
                entity_type="scenario",
                entity_id=None,
                field=None,
                message="No depots provided in scenario"
            ))

        # Build lookup structures
        depot_ids = {d.id for d in depots}
        vehicle_skills = self._collect_vehicle_skills(vehicles)
        two_person_available = any(v.team_size >= 2 for v in vehicles)
        max_vehicle_volume = max((v.capacity_volume_m3 or float('inf') for v in vehicles), default=0)
        max_vehicle_weight = max((v.capacity_weight_kg or float('inf') for v in vehicles), default=0)

        # Validate depots
        depot_errors = []
        for depot in depots:
            depot_errors.extend(self._validate_depot(depot))
        errors.extend(depot_errors)

        # Validate vehicles
        vehicle_errors = []
        vehicles_failed = 0
        for vehicle in vehicles:
            vehicle_errs = self._validate_vehicle(vehicle, depot_ids)
            vehicle_errors.extend(vehicle_errs)
            if vehicle_errs:
                vehicles_failed += 1
        errors.extend(vehicle_errors)

        # Validate stops
        stop_errors = []
        stop_warnings = []
        stops_failed = 0
        for stop in stops:
            stop_errs, stop_warns = self._validate_stop(
                stop,
                vehicle_skills=vehicle_skills,
                two_person_available=two_person_available,
                max_volume=max_vehicle_volume,
                max_weight=max_vehicle_weight,
                plan_date=plan_date
            )
            stop_errors.extend(stop_errs)
            stop_warnings.extend(stop_warns)
            if stop_errs:
                stops_failed += 1
        errors.extend(stop_errors)
        warnings.extend(stop_warnings)

        # Build result
        result = ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            stops_validated=len(stops),
            stops_failed=stops_failed,
            vehicles_validated=len(vehicles),
            vehicles_failed=vehicles_failed,
            depots_validated=len(depots),
            depots_failed=len(depot_errors),
        )

        # Log summary
        if result.is_valid:
            logger.info(
                f"Validation passed: {len(stops)} stops, {len(vehicles)} vehicles, {len(depots)} depots"
            )
        else:
            logger.warning(
                f"Validation failed: {len(errors)} errors, {len(warnings)} warnings"
            )

        return result

    def _validate_depot(self, depot: Depot) -> List[ValidationError]:
        """Validate a single depot."""
        errors = []

        # Geocode validation
        if not depot.geocode:
            errors.append(ValidationError(
                reason=RejectReason.DEPOT_MISSING_GEOCODE,
                entity_type="depot",
                entity_id=depot.id,
                field="geocode",
                message=f"Depot {depot.id} is missing geocode"
            ))
        else:
            if not self._is_valid_latitude(depot.geocode.lat):
                errors.append(ValidationError(
                    reason=RejectReason.DEPOT_INVALID_GEOCODE,
                    entity_type="depot",
                    entity_id=depot.id,
                    field="geocode.lat",
                    message=f"Depot {depot.id} has invalid latitude: {depot.geocode.lat}",
                    details={"lat": depot.geocode.lat}
                ))
            if not self._is_valid_longitude(depot.geocode.lng):
                errors.append(ValidationError(
                    reason=RejectReason.DEPOT_INVALID_GEOCODE,
                    entity_type="depot",
                    entity_id=depot.id,
                    field="geocode.lng",
                    message=f"Depot {depot.id} has invalid longitude: {depot.geocode.lng}",
                    details={"lng": depot.geocode.lng}
                ))

        return errors

    def _validate_vehicle(
        self,
        vehicle: Vehicle,
        depot_ids: Set[str]
    ) -> List[ValidationError]:
        """Validate a single vehicle."""
        errors = []

        # Shift validation
        if vehicle.shift_start_at >= vehicle.shift_end_at:
            errors.append(ValidationError(
                reason=RejectReason.VEHICLE_SHIFT_START_AFTER_END,
                entity_type="vehicle",
                entity_id=vehicle.id,
                field="shift_start_at",
                message=f"Vehicle {vehicle.id} shift starts after end",
                details={
                    "shift_start_at": vehicle.shift_start_at.isoformat(),
                    "shift_end_at": vehicle.shift_end_at.isoformat()
                }
            ))
        else:
            shift_duration = (vehicle.shift_end_at - vehicle.shift_start_at).total_seconds() / 60
            if shift_duration < self.config.min_shift_duration_minutes:
                errors.append(ValidationError(
                    reason=RejectReason.VEHICLE_SHIFT_TOO_SHORT,
                    entity_type="vehicle",
                    entity_id=vehicle.id,
                    field="shift_duration",
                    message=f"Vehicle {vehicle.id} shift too short: {shift_duration:.0f}min",
                    details={"shift_duration_min": shift_duration}
                ))
            if shift_duration > self.config.max_shift_duration_minutes:
                errors.append(ValidationError(
                    reason=RejectReason.VEHICLE_SHIFT_TOO_LONG,
                    entity_type="vehicle",
                    entity_id=vehicle.id,
                    field="shift_duration",
                    message=f"Vehicle {vehicle.id} shift too long: {shift_duration:.0f}min",
                    details={"shift_duration_min": shift_duration}
                ))

        # Depot validation
        if vehicle.start_depot_id not in depot_ids:
            errors.append(ValidationError(
                reason=RejectReason.VEHICLE_UNKNOWN_START_DEPOT,
                entity_type="vehicle",
                entity_id=vehicle.id,
                field="start_depot_id",
                message=f"Vehicle {vehicle.id} references unknown start depot: {vehicle.start_depot_id}",
                details={"start_depot_id": vehicle.start_depot_id}
            ))

        if vehicle.end_depot_id not in depot_ids:
            errors.append(ValidationError(
                reason=RejectReason.VEHICLE_UNKNOWN_END_DEPOT,
                entity_type="vehicle",
                entity_id=vehicle.id,
                field="end_depot_id",
                message=f"Vehicle {vehicle.id} references unknown end depot: {vehicle.end_depot_id}",
                details={"end_depot_id": vehicle.end_depot_id}
            ))

        # Skills validation
        for skill in vehicle.skills:
            if skill not in self.config.valid_skills:
                errors.append(ValidationError(
                    reason=RejectReason.VEHICLE_UNKNOWN_SKILL,
                    entity_type="vehicle",
                    entity_id=vehicle.id,
                    field="skills",
                    message=f"Vehicle {vehicle.id} has unknown skill: {skill}",
                    details={"skill": skill, "valid_skills": list(self.config.valid_skills)}
                ))

        return errors

    def _validate_stop(
        self,
        stop: Stop,
        vehicle_skills: Set[str],
        two_person_available: bool,
        max_volume: float,
        max_weight: float,
        plan_date: Optional[datetime] = None
    ) -> tuple[List[ValidationError], List[ValidationError]]:
        """Validate a single stop. Returns (errors, warnings)."""
        errors = []
        warnings = []

        # Geocode validation
        if not stop.geocode:
            errors.append(ValidationError(
                reason=RejectReason.STOP_MISSING_GEOCODE,
                entity_type="stop",
                entity_id=stop.id,
                field="geocode",
                message=f"Stop {stop.id} is missing geocode"
            ))
        else:
            if not self._is_valid_latitude(stop.geocode.lat):
                errors.append(ValidationError(
                    reason=RejectReason.STOP_INVALID_LATITUDE,
                    entity_type="stop",
                    entity_id=stop.id,
                    field="geocode.lat",
                    message=f"Stop {stop.id} has invalid latitude: {stop.geocode.lat}",
                    details={"lat": stop.geocode.lat}
                ))
            if not self._is_valid_longitude(stop.geocode.lng):
                errors.append(ValidationError(
                    reason=RejectReason.STOP_INVALID_LONGITUDE,
                    entity_type="stop",
                    entity_id=stop.id,
                    field="geocode.lng",
                    message=f"Stop {stop.id} has invalid longitude: {stop.geocode.lng}",
                    details={"lng": stop.geocode.lng}
                ))

        # Time window validation
        if stop.tw_start >= stop.tw_end:
            errors.append(ValidationError(
                reason=RejectReason.STOP_TW_START_AFTER_END,
                entity_type="stop",
                entity_id=stop.id,
                field="tw_start",
                message=f"Stop {stop.id} time window starts after end",
                details={
                    "tw_start": stop.tw_start.isoformat(),
                    "tw_end": stop.tw_end.isoformat()
                }
            ))
        else:
            tw_duration = (stop.tw_end - stop.tw_start).total_seconds() / 60
            if tw_duration < self.config.min_tw_duration_minutes:
                warnings.append(ValidationError(
                    reason=RejectReason.STOP_TW_TOO_NARROW,
                    entity_type="stop",
                    entity_id=stop.id,
                    field="tw_duration",
                    message=f"Stop {stop.id} time window too narrow: {tw_duration:.0f}min",
                    details={"tw_duration_min": tw_duration}
                ))

        # Service duration validation
        if stop.service_duration_min <= 0:
            errors.append(ValidationError(
                reason=RejectReason.STOP_SERVICE_DURATION_ZERO if stop.service_duration_min == 0
                    else RejectReason.STOP_SERVICE_DURATION_NEGATIVE,
                entity_type="stop",
                entity_id=stop.id,
                field="service_duration_min",
                message=f"Stop {stop.id} has invalid service duration: {stop.service_duration_min}",
                details={"service_duration_min": stop.service_duration_min}
            ))
        elif stop.service_duration_min > self.config.max_service_duration_minutes:
            errors.append(ValidationError(
                reason=RejectReason.STOP_SERVICE_DURATION_TOO_LONG,
                entity_type="stop",
                entity_id=stop.id,
                field="service_duration_min",
                message=f"Stop {stop.id} service duration too long: {stop.service_duration_min}min",
                details={"service_duration_min": stop.service_duration_min}
            ))

        # Skills validation
        for skill in stop.required_skills:
            if skill not in self.config.valid_skills:
                errors.append(ValidationError(
                    reason=RejectReason.STOP_UNKNOWN_SKILL,
                    entity_type="stop",
                    entity_id=stop.id,
                    field="required_skills",
                    message=f"Stop {stop.id} requires unknown skill: {skill}",
                    details={"skill": skill}
                ))

        # Check if any vehicle can serve this stop (skills)
        if stop.required_skills:
            required_set = set(stop.required_skills)
            if not required_set.issubset(vehicle_skills):
                missing = required_set - vehicle_skills
                errors.append(ValidationError(
                    reason=RejectReason.STOP_NO_ELIGIBLE_VEHICLE_SKILLS,
                    entity_type="stop",
                    entity_id=stop.id,
                    field="required_skills",
                    message=f"Stop {stop.id} requires skills no vehicle has: {missing}",
                    details={"required": list(stop.required_skills), "missing": list(missing)}
                ))

        # 2-person validation
        if stop.requires_two_person and not two_person_available:
            errors.append(ValidationError(
                reason=RejectReason.STOP_NO_ELIGIBLE_TWO_PERSON,
                entity_type="stop",
                entity_id=stop.id,
                field="requires_two_person",
                message=f"Stop {stop.id} requires 2-person team but none available"
            ))

        # Capacity validation
        if stop.volume_m3 < 0:
            errors.append(ValidationError(
                reason=RejectReason.STOP_VOLUME_NEGATIVE,
                entity_type="stop",
                entity_id=stop.id,
                field="volume_m3",
                message=f"Stop {stop.id} has negative volume",
                details={"volume_m3": stop.volume_m3}
            ))
        elif stop.volume_m3 > max_volume:
            errors.append(ValidationError(
                reason=RejectReason.STOP_EXCEEDS_ALL_VEHICLE_CAPACITY,
                entity_type="stop",
                entity_id=stop.id,
                field="volume_m3",
                message=f"Stop {stop.id} volume exceeds all vehicle capacity",
                details={"volume_m3": stop.volume_m3, "max_vehicle_volume": max_volume}
            ))

        if stop.weight_kg < 0:
            errors.append(ValidationError(
                reason=RejectReason.STOP_WEIGHT_NEGATIVE,
                entity_type="stop",
                entity_id=stop.id,
                field="weight_kg",
                message=f"Stop {stop.id} has negative weight",
                details={"weight_kg": stop.weight_kg}
            ))
        elif stop.weight_kg > max_weight:
            errors.append(ValidationError(
                reason=RejectReason.STOP_EXCEEDS_ALL_VEHICLE_CAPACITY,
                entity_type="stop",
                entity_id=stop.id,
                field="weight_kg",
                message=f"Stop {stop.id} weight exceeds all vehicle capacity",
                details={"weight_kg": stop.weight_kg, "max_vehicle_weight": max_weight}
            ))

        return errors, warnings

    def _collect_vehicle_skills(self, vehicles: List[Vehicle]) -> Set[str]:
        """Collect all skills available across all vehicles."""
        skills = set()
        for v in vehicles:
            skills.update(v.skills)
        return skills

    def _is_valid_latitude(self, lat: float) -> bool:
        """Check if latitude is within valid bounds."""
        return self.config.min_latitude <= lat <= self.config.max_latitude

    def _is_valid_longitude(self, lng: float) -> bool:
        """Check if longitude is within valid bounds."""
        return self.config.min_longitude <= lng <= self.config.max_longitude
