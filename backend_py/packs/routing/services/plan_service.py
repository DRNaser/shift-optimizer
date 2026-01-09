# =============================================================================
# SOLVEREIGN Routing Pack - Plan Service
# =============================================================================
# Business logic for plan operations with audit gating.
#
# Gate 2: Audit-Gating at Lock Endpoint
# - FAIL audit blocks lock (HTTP 409)
# - WARN allowed but recorded in evidence
# - Evidence must contain audit outcome
# =============================================================================

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from .audit.route_auditor import AuditResult, AuditStatus, AuditCheckName
from .finalize.drift_gate import (
    DriftGate,
    DriftGatePolicy,
    DriftGateResult,
    DriftGateError,
)
from .finalize.drift_detector import DriftReport
from .finalize.tw_validator import TWValidationResult
from .finalize.fallback_tracker import FallbackReport

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PlanServiceError(Exception):
    """Base exception for plan service errors."""
    pass


class PlanNotFoundError(PlanServiceError):
    """Plan not found."""
    pass


class PlanAlreadyLockedError(PlanServiceError):
    """Plan is already locked."""
    pass


class PlanInvalidStateError(PlanServiceError):
    """Plan is in invalid state for operation."""
    pass


class AuditGateError(PlanServiceError):
    """Audit gate blocked the operation."""

    def __init__(
        self,
        message: str,
        failed_checks: List[str],
        audit_summary: Dict[str, Any]
    ):
        super().__init__(message)
        self.failed_checks = failed_checks
        self.audit_summary = audit_summary


# =============================================================================
# DATA CLASSES
# =============================================================================

class PlanStatus(str, Enum):
    """Plan status states."""
    QUEUED = "QUEUED"
    SOLVING = "SOLVING"
    SOLVED = "SOLVED"
    AUDITED = "AUDITED"
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class LockResult:
    """Result of a lock operation."""
    success: bool
    plan_id: str
    status: PlanStatus
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    audit_summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "plan_id": self.plan_id,
            "status": self.status.value,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "locked_by": self.locked_by,
            "audit_summary": self.audit_summary,
            "error_message": self.error_message,
            "warnings": self.warnings,
        }


# =============================================================================
# AUDIT GATE
# =============================================================================

class AuditGate:
    """
    Enforces audit requirements for plan operations.

    Gate 2: Lock Endpoint Audit Requirements
    - All 5 audit checks must have been run
    - No FAIL status allowed (blocks lock)
    - WARN status allowed but recorded
    """

    # Checks that MUST pass for lock
    REQUIRED_CHECKS = [
        AuditCheckName.COVERAGE,
        AuditCheckName.TIME_WINDOW,
        AuditCheckName.SHIFT_FEASIBILITY,
        AuditCheckName.SKILLS_COMPLIANCE,
        AuditCheckName.OVERLAP,
    ]

    @classmethod
    def check_lock_allowed(cls, audit_result: AuditResult) -> tuple:
        """
        Check if plan can be locked based on audit results.

        Args:
            audit_result: The audit results for the plan

        Returns:
            (allowed: bool, failed_checks: List[str], warnings: List[str])
        """
        failed_checks = []
        warnings = []

        # Check all required audits were run
        for check_name in cls.REQUIRED_CHECKS:
            if check_name not in audit_result.results:
                failed_checks.append(f"{check_name.value}_NOT_RUN")

        # Check for FAIL status
        for check_name, check in audit_result.results.items():
            if check.status == AuditStatus.FAIL:
                failed_checks.append(check_name.value)
            elif check.status == AuditStatus.WARN:
                warnings.append(f"{check_name.value}: {check.violation_count} warnings")

        allowed = len(failed_checks) == 0
        return allowed, failed_checks, warnings

    @classmethod
    def build_audit_summary(cls, audit_result: AuditResult) -> Dict[str, Any]:
        """Build audit summary for evidence/response."""
        return {
            "audited_at": audit_result.audited_at.isoformat(),
            "all_passed": audit_result.all_passed,
            "checks_run": audit_result.checks_run,
            "checks_passed": audit_result.checks_passed,
            "checks_warned": audit_result.checks_warned,
            "checks_failed": audit_result.checks_failed,
            "results": {
                name.value: {
                    "status": check.status.value,
                    "violation_count": check.violation_count,
                }
                for name, check in audit_result.results.items()
            }
        }


# =============================================================================
# PLAN SERVICE
# =============================================================================

class PlanService:
    """
    Service for plan operations with audit gating.

    This service enforces:
    - Audit gate before lock (FAIL blocks)
    - Status transitions (only AUDITED/DRAFT can lock)
    - Evidence generation with audit outcome
    """

    def __init__(self, db_connection=None):
        """
        Initialize plan service.

        Args:
            db_connection: Database connection (for production use)
        """
        self.db = db_connection
        self.audit_gate = AuditGate()

    def lock_plan(
        self,
        plan_id: str,
        audit_result: AuditResult,
        locked_by: str,
        current_status: PlanStatus,
    ) -> LockResult:
        """
        Lock a plan with audit gating.

        Gate 2 Implementation:
        1. Verify plan is in lockable state (AUDITED or DRAFT)
        2. Check audit gate (FAIL blocks)
        3. If allowed, update status to LOCKED
        4. Return result with audit summary

        Args:
            plan_id: The plan to lock
            audit_result: The audit results for the plan
            locked_by: User performing the lock
            current_status: Current plan status

        Returns:
            LockResult with success/failure info

        Raises:
            PlanAlreadyLockedError: If plan already locked
            PlanInvalidStateError: If plan in wrong state
            AuditGateError: If audit gate blocks (FAIL checks)
        """
        # Step 1: Check current status
        if current_status == PlanStatus.LOCKED:
            raise PlanAlreadyLockedError(f"Plan {plan_id} is already locked")

        if current_status not in (PlanStatus.AUDITED, PlanStatus.DRAFT):
            raise PlanInvalidStateError(
                f"Plan {plan_id} is in {current_status.value} state. "
                f"Only AUDITED or DRAFT plans can be locked."
            )

        # Step 2: Check audit gate
        allowed, failed_checks, warnings = self.audit_gate.check_lock_allowed(audit_result)
        audit_summary = self.audit_gate.build_audit_summary(audit_result)

        if not allowed:
            logger.warning(
                f"Lock blocked for plan {plan_id}: failed checks {failed_checks}",
                extra={"plan_id": plan_id, "failed_checks": failed_checks}
            )
            raise AuditGateError(
                message=f"Lock blocked: {len(failed_checks)} audit check(s) failed",
                failed_checks=failed_checks,
                audit_summary=audit_summary
            )

        # Step 3: Perform lock (would update DB in production)
        locked_at = datetime.now()

        logger.info(
            f"Plan {plan_id} locked by {locked_by}",
            extra={
                "plan_id": plan_id,
                "locked_by": locked_by,
                "warnings": warnings
            }
        )

        # Step 4: Return result
        return LockResult(
            success=True,
            plan_id=plan_id,
            status=PlanStatus.LOCKED,
            locked_at=locked_at,
            locked_by=locked_by,
            audit_summary=audit_summary,
            warnings=warnings,
        )

    def can_lock(self, audit_result: AuditResult) -> Dict[str, Any]:
        """
        Check if a plan can be locked (pre-check without side effects).

        Returns dict with:
        - can_lock: bool
        - failed_checks: List of failed check names
        - warnings: List of warning messages
        """
        allowed, failed_checks, warnings = self.audit_gate.check_lock_allowed(audit_result)
        return {
            "can_lock": allowed,
            "failed_checks": failed_checks,
            "warnings": warnings,
        }

    def lock_plan_with_drift_check(
        self,
        plan_id: str,
        audit_result: AuditResult,
        locked_by: str,
        current_status: PlanStatus,
        drift_report: Optional[DriftReport] = None,
        tw_validation: Optional[TWValidationResult] = None,
        fallback_report: Optional[FallbackReport] = None,
        drift_policy: Optional[DriftGatePolicy] = None,
    ) -> LockResult:
        """
        Lock a plan with both audit gating AND drift gate checks.

        This extends lock_plan() to include Gate 7 (Drift Gate) validation:
        1. Run audit gate (Gate 2) - FAIL blocks
        2. Run drift gate (Gate 7) - BLOCK verdict blocks
        3. If both pass, lock the plan
        4. Return result with combined evidence

        Args:
            plan_id: The plan to lock
            audit_result: The audit results for the plan
            locked_by: User performing the lock
            current_status: Current plan status
            drift_report: Optional drift detection results
            tw_validation: Optional TW validation results
            fallback_report: Optional fallback usage report
            drift_policy: Optional custom drift policy

        Returns:
            LockResult with success/failure info and drift gate evidence

        Raises:
            PlanAlreadyLockedError: If plan already locked
            PlanInvalidStateError: If plan in wrong state
            AuditGateError: If audit gate blocks (FAIL checks)
            DriftGateError: If drift gate blocks (BLOCK verdict)
        """
        # Step 1: Check current status
        if current_status == PlanStatus.LOCKED:
            raise PlanAlreadyLockedError(f"Plan {plan_id} is already locked")

        if current_status not in (PlanStatus.AUDITED, PlanStatus.DRAFT):
            raise PlanInvalidStateError(
                f"Plan {plan_id} is in {current_status.value} state. "
                f"Only AUDITED or DRAFT plans can be locked."
            )

        # Step 2: Check audit gate (Gate 2)
        allowed, failed_checks, warnings = self.audit_gate.check_lock_allowed(audit_result)
        audit_summary = self.audit_gate.build_audit_summary(audit_result)

        if not allowed:
            logger.warning(
                f"Lock blocked for plan {plan_id}: audit failed {failed_checks}",
                extra={"plan_id": plan_id, "failed_checks": failed_checks}
            )
            raise AuditGateError(
                message=f"Lock blocked: {len(failed_checks)} audit check(s) failed",
                failed_checks=failed_checks,
                audit_summary=audit_summary
            )

        # Step 3: Check drift gate (Gate 7)
        drift_gate = DriftGate(policy=drift_policy)
        drift_result = drift_gate.evaluate(
            drift_report=drift_report,
            tw_validation=tw_validation,
            fallback_report=fallback_report,
        )

        if drift_result.is_blocked:
            logger.warning(
                f"Lock blocked for plan {plan_id}: drift gate blocked",
                extra={
                    "plan_id": plan_id,
                    "verdict": drift_result.verdict,
                    "reasons": drift_result.reasons,
                    "p95_ratio": drift_result.p95_ratio,
                    "tw_violations": drift_result.tw_violations_count,
                }
            )
            raise DriftGateError(
                message=f"Drift gate blocked: {', '.join(drift_result.reasons)}",
                verdict=drift_result.verdict,
                reasons=drift_result.reasons,
                drift_report=drift_report,
                tw_validation=tw_validation,
                fallback_report=fallback_report,
            )

        # Step 4: Combine warnings
        all_warnings = list(warnings)
        if drift_result.verdict == "WARN":
            all_warnings.extend([f"[Drift] {w}" for w in drift_result.warnings])

        # Step 5: Perform lock
        locked_at = datetime.now()

        logger.info(
            f"Plan {plan_id} locked by {locked_by} (with drift check)",
            extra={
                "plan_id": plan_id,
                "locked_by": locked_by,
                "drift_verdict": drift_result.verdict,
                "warnings": all_warnings,
            }
        )

        # Step 6: Build combined summary
        combined_summary = {
            "audit": audit_summary,
            "drift_gate": drift_result.to_dict(),
        }

        return LockResult(
            success=True,
            plan_id=plan_id,
            status=PlanStatus.LOCKED,
            locked_at=locked_at,
            locked_by=locked_by,
            audit_summary=combined_summary,
            warnings=all_warnings,
        )

    def can_lock_with_drift(
        self,
        audit_result: AuditResult,
        drift_report: Optional[DriftReport] = None,
        tw_validation: Optional[TWValidationResult] = None,
        fallback_report: Optional[FallbackReport] = None,
        drift_policy: Optional[DriftGatePolicy] = None,
    ) -> Dict[str, Any]:
        """
        Check if a plan can be locked with drift validation (pre-check).

        Combines audit gate and drift gate checks.

        Returns dict with:
        - can_lock: bool
        - audit_gate: dict with audit check results
        - drift_gate: dict with drift gate results
        """
        # Audit gate check
        audit_allowed, failed_checks, audit_warnings = (
            self.audit_gate.check_lock_allowed(audit_result)
        )

        # Drift gate check
        drift_gate = DriftGate(policy=drift_policy)
        drift_result = drift_gate.evaluate(
            drift_report=drift_report,
            tw_validation=tw_validation,
            fallback_report=fallback_report,
        )

        return {
            "can_lock": audit_allowed and drift_result.is_allowed,
            "audit_gate": {
                "allowed": audit_allowed,
                "failed_checks": failed_checks,
                "warnings": audit_warnings,
            },
            "drift_gate": {
                "verdict": drift_result.verdict,
                "allowed": drift_result.is_allowed,
                "reasons": drift_result.reasons,
                "warnings": drift_result.warnings,
                "metrics": {
                    "p95_ratio": drift_result.p95_ratio,
                    "tw_violations_count": drift_result.tw_violations_count,
                    "timeout_rate": drift_result.timeout_rate,
                    "fallback_rate": drift_result.fallback_rate,
                },
            },
        }
