# =============================================================================
# SOLVEREIGN Routing Pack - Finalize Stage
# =============================================================================
# Post-solve validation using OSRM for drift detection and TW validation.
#
# Components:
# - OSRMFinalizeStage: Main orchestrator for finalize validation
# - DriftDetector: Computes drift between matrix and OSRM times
# - TWValidator: Forward simulation for time window violations
# - FallbackTracker: Tracks fallback usage statistics
# - DriftGate: Policy enforcement (OK/WARN/BLOCK verdicts)
# =============================================================================

from .drift_detector import DriftDetector, DriftReport, LegDrift
from .tw_validator import TWValidator, TWValidationResult, TWViolation
from .fallback_tracker import FallbackTracker, FallbackReport, FallbackEvent
from .osrm_finalize import (
    OSRMFinalizeStage,
    FinalizeConfig,
    FinalizeResult,
)
from .drift_gate import (
    DriftGate,
    DriftGatePolicy,
    DriftGateResult,
    DriftGateError,
)
from .coords_quality_gate import (
    CoordsQualityGate,
    CoordsQualityPolicy,
    CoordsQualityResult,
    CoordsQualityError,
    CoordsVerdict,
    ResolutionMethod,
)

__all__ = [
    # Main orchestrator
    "OSRMFinalizeStage",
    "FinalizeConfig",
    "FinalizeResult",
    # Drift detection
    "DriftDetector",
    "DriftReport",
    "LegDrift",
    # TW validation
    "TWValidator",
    "TWValidationResult",
    "TWViolation",
    # Fallback tracking
    "FallbackTracker",
    "FallbackReport",
    "FallbackEvent",
    # Drift gate
    "DriftGate",
    "DriftGatePolicy",
    "DriftGateResult",
    "DriftGateError",
    # Coords quality gate (STOP-5)
    "CoordsQualityGate",
    "CoordsQualityPolicy",
    "CoordsQualityResult",
    "CoordsQualityError",
    "CoordsVerdict",
    "ResolutionMethod",
]
