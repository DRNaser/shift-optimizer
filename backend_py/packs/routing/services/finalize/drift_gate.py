# =============================================================================
# SOLVEREIGN Routing Pack - Drift Gate
# =============================================================================
# Gate 7: Drift Gate - Enforces routing drift thresholds at plan lock.
#
# Similar to Gate 2 (AuditGate), but for routing-specific validation:
# - P95 drift ratio thresholds
# - TW violation limits
# - Timeout rate limits
#
# Verdicts:
# - OK: All thresholds passed
# - WARN: OK thresholds exceeded, within WARN thresholds
# - BLOCK: WARN thresholds exceeded (raises DriftGateError)
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Literal

from .drift_detector import DriftReport
from .tw_validator import TWValidationResult
from .fallback_tracker import FallbackReport


logger = logging.getLogger(__name__)


Verdict = Literal["OK", "WARN", "BLOCK"]


# =============================================================================
# EXCEPTIONS
# =============================================================================

class DriftGateError(Exception):
    """
    Raised when drift gate blocks plan lock.

    Contains all drift validation information for debugging/evidence.
    """

    def __init__(
        self,
        message: str,
        verdict: Verdict,
        reasons: List[str],
        drift_report: Optional[DriftReport] = None,
        tw_validation: Optional[TWValidationResult] = None,
        fallback_report: Optional[FallbackReport] = None,
    ):
        super().__init__(message)
        self.verdict = verdict
        self.reasons = reasons
        self.drift_report = drift_report
        self.tw_validation = tw_validation
        self.fallback_report = fallback_report

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API response."""
        return {
            "error": "DriftGateError",
            "message": str(self),
            "verdict": self.verdict,
            "reasons": self.reasons,
            "drift_report": self.drift_report.to_dict() if self.drift_report else None,
            "tw_validation": self.tw_validation.to_dict() if self.tw_validation else None,
            "fallback_report": self.fallback_report.to_dict() if self.fallback_report else None,
        }


# =============================================================================
# POLICY CONFIGURATION
# =============================================================================

@dataclass
class DriftGatePolicy:
    """
    Policy configuration for drift gate evaluation.

    Defines thresholds for OK and WARN verdicts.
    Exceeding WARN thresholds results in BLOCK.
    """

    # =========================================================================
    # OK Thresholds (stricter)
    # =========================================================================
    # P95 drift ratio: OSRM_time / Matrix_time
    # 1.15 = 15% longer than matrix estimates
    ok_p95_ratio_max: float = 1.15

    # TW violations allowed for OK verdict
    ok_tw_violations_max: int = 0

    # OSRM timeout rate (0.0 - 1.0)
    ok_timeout_rate_max: float = 0.02  # 2%

    # Fallback rate (0.0 - 1.0)
    ok_fallback_rate_max: float = 0.05  # 5%

    # =========================================================================
    # WARN Thresholds (looser, but still acceptable)
    # =========================================================================
    warn_p95_ratio_max: float = 1.30  # 30%
    warn_tw_violations_max: int = 3
    warn_timeout_rate_max: float = 0.10  # 10%
    warn_fallback_rate_max: float = 0.15  # 15%

    # =========================================================================
    # Maximum absolute values (hard limits)
    # =========================================================================
    max_ratio_hard_limit: float = 3.0  # Any leg with 3x drift = BLOCK
    max_tw_violation_seconds: int = 3600  # Any violation > 1h = BLOCK

    # =========================================================================
    # Feature flags
    # =========================================================================
    # If True, missing drift report = BLOCK
    require_drift_report: bool = True

    # If True, missing TW validation = BLOCK
    require_tw_validation: bool = True

    # If True, WARN verdict raises DriftGateError with warning info
    raise_on_warn: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert policy to dictionary for evidence."""
        return {
            "ok_thresholds": {
                "p95_ratio_max": self.ok_p95_ratio_max,
                "tw_violations_max": self.ok_tw_violations_max,
                "timeout_rate_max": self.ok_timeout_rate_max,
                "fallback_rate_max": self.ok_fallback_rate_max,
            },
            "warn_thresholds": {
                "p95_ratio_max": self.warn_p95_ratio_max,
                "tw_violations_max": self.warn_tw_violations_max,
                "timeout_rate_max": self.warn_timeout_rate_max,
                "fallback_rate_max": self.warn_fallback_rate_max,
            },
            "hard_limits": {
                "max_ratio": self.max_ratio_hard_limit,
                "max_tw_violation_seconds": self.max_tw_violation_seconds,
            },
            "feature_flags": {
                "require_drift_report": self.require_drift_report,
                "require_tw_validation": self.require_tw_validation,
                "raise_on_warn": self.raise_on_warn,
            },
        }


# =============================================================================
# EVALUATION RESULT
# =============================================================================

@dataclass
class DriftGateResult:
    """
    Result of drift gate evaluation.

    Contains verdict, reasons, and all validation data.
    """
    verdict: Verdict
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=datetime.now)

    # Input data references
    drift_report: Optional[DriftReport] = None
    tw_validation: Optional[TWValidationResult] = None
    fallback_report: Optional[FallbackReport] = None

    # Policy used for evaluation
    policy: Optional[DriftGatePolicy] = None

    # Computed metrics (for evidence)
    p95_ratio: Optional[float] = None
    tw_violations_count: Optional[int] = None
    timeout_rate: Optional[float] = None
    fallback_rate: Optional[float] = None

    @property
    def is_allowed(self) -> bool:
        """Whether the plan can be locked (OK or WARN)."""
        return self.verdict in ("OK", "WARN")

    @property
    def is_blocked(self) -> bool:
        """Whether the plan is blocked from locking."""
        return self.verdict == "BLOCK"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "verdict": self.verdict,
            "is_allowed": self.is_allowed,
            "is_blocked": self.is_blocked,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "evaluated_at": self.evaluated_at.isoformat(),
            "metrics": {
                "p95_ratio": self.p95_ratio,
                "tw_violations_count": self.tw_violations_count,
                "timeout_rate": self.timeout_rate,
                "fallback_rate": self.fallback_rate,
            },
            "policy": self.policy.to_dict() if self.policy else None,
        }


# =============================================================================
# DRIFT GATE
# =============================================================================

class DriftGate:
    """
    Gate 7: Drift Gate - Enforces routing drift thresholds.

    Evaluates drift reports and TW validation results against policy.
    Returns OK/WARN/BLOCK verdict.

    Usage:
        gate = DriftGate(policy)
        result = gate.evaluate(drift_report, tw_validation, fallback_report)
        if result.is_blocked:
            raise DriftGateError(...)
    """

    def __init__(self, policy: Optional[DriftGatePolicy] = None):
        """
        Initialize drift gate with policy.

        Args:
            policy: Drift gate policy (defaults to DriftGatePolicy())
        """
        self.policy = policy or DriftGatePolicy()

    def evaluate(
        self,
        drift_report: Optional[DriftReport] = None,
        tw_validation: Optional[TWValidationResult] = None,
        fallback_report: Optional[FallbackReport] = None,
    ) -> DriftGateResult:
        """
        Evaluate drift metrics against policy.

        Args:
            drift_report: Drift detection results
            tw_validation: Time window validation results
            fallback_report: Fallback usage report

        Returns:
            DriftGateResult with verdict and reasons
        """
        block_reasons: List[str] = []
        warn_reasons: List[str] = []

        # Extract metrics
        p95_ratio = drift_report.p95_ratio if drift_report else None
        max_ratio = drift_report.max_ratio if drift_report else None
        tw_violations_count = tw_validation.violations_count if tw_validation else None
        max_violation_seconds = (
            tw_validation.max_violation_seconds if tw_validation else None
        )
        timeout_rate = fallback_report.timeout_rate if fallback_report else 0.0
        fallback_rate = fallback_report.fallback_rate if fallback_report else 0.0

        # =====================================================================
        # Check for missing required data
        # =====================================================================
        if self.policy.require_drift_report and drift_report is None:
            block_reasons.append("Drift report is required but missing")

        if self.policy.require_tw_validation and tw_validation is None:
            block_reasons.append("TW validation is required but missing")

        # =====================================================================
        # Check hard limits (instant BLOCK)
        # =====================================================================
        if max_ratio is not None and max_ratio > self.policy.max_ratio_hard_limit:
            block_reasons.append(
                f"Max drift ratio {max_ratio:.2f} exceeds hard limit "
                f"{self.policy.max_ratio_hard_limit}"
            )

        if (max_violation_seconds is not None and
                max_violation_seconds > self.policy.max_tw_violation_seconds):
            block_reasons.append(
                f"Max TW violation {max_violation_seconds}s exceeds hard limit "
                f"{self.policy.max_tw_violation_seconds}s"
            )

        # =====================================================================
        # Check BLOCK thresholds (exceeding WARN thresholds)
        # =====================================================================
        if p95_ratio is not None and p95_ratio > self.policy.warn_p95_ratio_max:
            block_reasons.append(
                f"P95 drift ratio {p95_ratio:.2f} exceeds BLOCK threshold "
                f"{self.policy.warn_p95_ratio_max}"
            )

        if (tw_violations_count is not None and
                tw_violations_count > self.policy.warn_tw_violations_max):
            block_reasons.append(
                f"TW violations {tw_violations_count} exceed BLOCK threshold "
                f"{self.policy.warn_tw_violations_max}"
            )

        if timeout_rate > self.policy.warn_timeout_rate_max:
            block_reasons.append(
                f"Timeout rate {timeout_rate:.2%} exceeds BLOCK threshold "
                f"{self.policy.warn_timeout_rate_max:.2%}"
            )

        if fallback_rate > self.policy.warn_fallback_rate_max:
            block_reasons.append(
                f"Fallback rate {fallback_rate:.2%} exceeds BLOCK threshold "
                f"{self.policy.warn_fallback_rate_max:.2%}"
            )

        # If any BLOCK reasons, return BLOCK verdict
        if block_reasons:
            return DriftGateResult(
                verdict="BLOCK",
                reasons=block_reasons,
                warnings=[],
                drift_report=drift_report,
                tw_validation=tw_validation,
                fallback_report=fallback_report,
                policy=self.policy,
                p95_ratio=p95_ratio,
                tw_violations_count=tw_violations_count,
                timeout_rate=timeout_rate,
                fallback_rate=fallback_rate,
            )

        # =====================================================================
        # Check WARN thresholds (exceeding OK thresholds)
        # =====================================================================
        if p95_ratio is not None and p95_ratio > self.policy.ok_p95_ratio_max:
            warn_reasons.append(
                f"P95 drift ratio {p95_ratio:.2f} exceeds OK threshold "
                f"{self.policy.ok_p95_ratio_max}"
            )

        if (tw_violations_count is not None and
                tw_violations_count > self.policy.ok_tw_violations_max):
            warn_reasons.append(
                f"TW violations {tw_violations_count} exceed OK threshold "
                f"{self.policy.ok_tw_violations_max}"
            )

        if timeout_rate > self.policy.ok_timeout_rate_max:
            warn_reasons.append(
                f"Timeout rate {timeout_rate:.2%} exceeds OK threshold "
                f"{self.policy.ok_timeout_rate_max:.2%}"
            )

        if fallback_rate > self.policy.ok_fallback_rate_max:
            warn_reasons.append(
                f"Fallback rate {fallback_rate:.2%} exceeds OK threshold "
                f"{self.policy.ok_fallback_rate_max:.2%}"
            )

        # If any WARN reasons, return WARN verdict
        if warn_reasons:
            return DriftGateResult(
                verdict="WARN",
                reasons=["Exceeded OK thresholds but within WARN limits"],
                warnings=warn_reasons,
                drift_report=drift_report,
                tw_validation=tw_validation,
                fallback_report=fallback_report,
                policy=self.policy,
                p95_ratio=p95_ratio,
                tw_violations_count=tw_violations_count,
                timeout_rate=timeout_rate,
                fallback_rate=fallback_rate,
            )

        # All checks passed
        return DriftGateResult(
            verdict="OK",
            reasons=["All drift checks passed"],
            warnings=[],
            drift_report=drift_report,
            tw_validation=tw_validation,
            fallback_report=fallback_report,
            policy=self.policy,
            p95_ratio=p95_ratio,
            tw_violations_count=tw_violations_count,
            timeout_rate=timeout_rate,
            fallback_rate=fallback_rate,
        )

    def check_and_raise(
        self,
        drift_report: Optional[DriftReport] = None,
        tw_validation: Optional[TWValidationResult] = None,
        fallback_report: Optional[FallbackReport] = None,
    ) -> DriftGateResult:
        """
        Evaluate and raise DriftGateError if blocked.

        Convenience method that combines evaluate() and exception raising.

        Args:
            drift_report: Drift detection results
            tw_validation: Time window validation results
            fallback_report: Fallback usage report

        Returns:
            DriftGateResult if allowed (OK or WARN)

        Raises:
            DriftGateError: If verdict is BLOCK
            DriftGateError: If verdict is WARN and policy.raise_on_warn is True
        """
        result = self.evaluate(drift_report, tw_validation, fallback_report)

        if result.is_blocked:
            logger.warning(
                f"Drift gate blocked: {result.reasons}",
                extra={
                    "verdict": result.verdict,
                    "reasons": result.reasons,
                    "p95_ratio": result.p95_ratio,
                    "tw_violations": result.tw_violations_count,
                }
            )
            raise DriftGateError(
                message=f"Drift gate blocked: {', '.join(result.reasons)}",
                verdict=result.verdict,
                reasons=result.reasons,
                drift_report=drift_report,
                tw_validation=tw_validation,
                fallback_report=fallback_report,
            )

        if result.verdict == "WARN" and self.policy.raise_on_warn:
            logger.warning(
                f"Drift gate warned (raise_on_warn=True): {result.warnings}",
                extra={
                    "verdict": result.verdict,
                    "warnings": result.warnings,
                    "p95_ratio": result.p95_ratio,
                }
            )
            raise DriftGateError(
                message=f"Drift gate warned: {', '.join(result.warnings)}",
                verdict=result.verdict,
                reasons=result.warnings,
                drift_report=drift_report,
                tw_validation=tw_validation,
                fallback_report=fallback_report,
            )

        return result

    def get_policy_summary(self) -> Dict[str, Any]:
        """Get policy summary for evidence/logging."""
        return self.policy.to_dict()
