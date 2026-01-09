# =============================================================================
# SOLVEREIGN Routing Pack - Audit Gate Tests
# =============================================================================
# Tests for Gate 2: Audit-Gating at Lock Endpoint
#
# Requirements:
# - FAIL audit blocks lock (HTTP 409)
# - WARN allowed but recorded
# - Evidence must contain audit outcome
# =============================================================================

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from packs.routing.services.plan_service import (
    PlanService,
    PlanStatus,
    AuditGate,
    AuditGateError,
    PlanAlreadyLockedError,
    PlanInvalidStateError,
    LockResult,
)
from packs.routing.services.audit.route_auditor import (
    AuditResult,
    AuditCheck,
    AuditCheckName,
    AuditStatus,
)


class TestAuditGate(unittest.TestCase):
    """Test the audit gate logic."""

    def _create_audit_result(
        self,
        coverage_status: AuditStatus = AuditStatus.PASS,
        time_window_status: AuditStatus = AuditStatus.PASS,
        shift_status: AuditStatus = AuditStatus.PASS,
        skills_status: AuditStatus = AuditStatus.PASS,
        overlap_status: AuditStatus = AuditStatus.PASS,
    ) -> AuditResult:
        """Helper to create audit results with specified statuses."""
        results = {
            AuditCheckName.COVERAGE: AuditCheck(
                name=AuditCheckName.COVERAGE,
                status=coverage_status,
                violation_count=0 if coverage_status == AuditStatus.PASS else 1,
            ),
            AuditCheckName.TIME_WINDOW: AuditCheck(
                name=AuditCheckName.TIME_WINDOW,
                status=time_window_status,
                violation_count=0 if time_window_status == AuditStatus.PASS else 5,
            ),
            AuditCheckName.SHIFT_FEASIBILITY: AuditCheck(
                name=AuditCheckName.SHIFT_FEASIBILITY,
                status=shift_status,
                violation_count=0 if shift_status == AuditStatus.PASS else 2,
            ),
            AuditCheckName.SKILLS_COMPLIANCE: AuditCheck(
                name=AuditCheckName.SKILLS_COMPLIANCE,
                status=skills_status,
                violation_count=0 if skills_status == AuditStatus.PASS else 3,
            ),
            AuditCheckName.OVERLAP: AuditCheck(
                name=AuditCheckName.OVERLAP,
                status=overlap_status,
                violation_count=0 if overlap_status == AuditStatus.PASS else 1,
            ),
        }

        passed = sum(1 for c in results.values() if c.status == AuditStatus.PASS)
        warned = sum(1 for c in results.values() if c.status == AuditStatus.WARN)
        failed = sum(1 for c in results.values() if c.status == AuditStatus.FAIL)

        return AuditResult(
            plan_id="TEST_PLAN",
            all_passed=(failed == 0),
            checks_run=5,
            checks_passed=passed,
            checks_warned=warned,
            checks_failed=failed,
            results=results,
        )

    # =========================================================================
    # AUDIT GATE UNIT TESTS
    # =========================================================================

    def test_all_pass_allows_lock(self):
        """Test that all PASS allows lock."""
        audit_result = self._create_audit_result()  # All PASS

        allowed, failed, warnings = AuditGate.check_lock_allowed(audit_result)

        self.assertTrue(allowed)
        self.assertEqual(len(failed), 0)
        self.assertEqual(len(warnings), 0)

    def test_single_fail_blocks_lock(self):
        """Test that single FAIL blocks lock."""
        audit_result = self._create_audit_result(
            time_window_status=AuditStatus.FAIL
        )

        allowed, failed, warnings = AuditGate.check_lock_allowed(audit_result)

        self.assertFalse(allowed)
        self.assertIn("TIME_WINDOW", failed)

    def test_multiple_fail_blocks_lock(self):
        """Test that multiple FAILs all reported."""
        audit_result = self._create_audit_result(
            time_window_status=AuditStatus.FAIL,
            shift_status=AuditStatus.FAIL,
        )

        allowed, failed, warnings = AuditGate.check_lock_allowed(audit_result)

        self.assertFalse(allowed)
        self.assertEqual(len(failed), 2)
        self.assertIn("TIME_WINDOW", failed)
        self.assertIn("SHIFT_FEASIBILITY", failed)

    def test_warn_allows_lock_with_warning(self):
        """Test that WARN allows lock but records warning."""
        audit_result = self._create_audit_result(
            coverage_status=AuditStatus.WARN
        )

        allowed, failed, warnings = AuditGate.check_lock_allowed(audit_result)

        self.assertTrue(allowed)  # WARN doesn't block
        self.assertEqual(len(failed), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("COVERAGE", warnings[0])

    def test_missing_check_blocks_lock(self):
        """Test that missing required check blocks lock."""
        # Create result with missing TIME_WINDOW check
        results = {
            AuditCheckName.COVERAGE: AuditCheck(
                name=AuditCheckName.COVERAGE,
                status=AuditStatus.PASS,
                violation_count=0,
            ),
            # TIME_WINDOW missing!
            AuditCheckName.SHIFT_FEASIBILITY: AuditCheck(
                name=AuditCheckName.SHIFT_FEASIBILITY,
                status=AuditStatus.PASS,
                violation_count=0,
            ),
            AuditCheckName.SKILLS_COMPLIANCE: AuditCheck(
                name=AuditCheckName.SKILLS_COMPLIANCE,
                status=AuditStatus.PASS,
                violation_count=0,
            ),
            AuditCheckName.OVERLAP: AuditCheck(
                name=AuditCheckName.OVERLAP,
                status=AuditStatus.PASS,
                violation_count=0,
            ),
        }

        audit_result = AuditResult(
            plan_id="TEST_PLAN",
            all_passed=True,
            checks_run=4,  # Only 4 checks
            checks_passed=4,
            checks_warned=0,
            checks_failed=0,
            results=results,
        )

        allowed, failed, warnings = AuditGate.check_lock_allowed(audit_result)

        self.assertFalse(allowed)
        self.assertIn("TIME_WINDOW_NOT_RUN", failed)

    # =========================================================================
    # PLAN SERVICE TESTS
    # =========================================================================

    def test_service_lock_success(self):
        """Test successful lock through service."""
        service = PlanService()
        audit_result = self._create_audit_result()  # All PASS

        result = service.lock_plan(
            plan_id="PLAN_001",
            audit_result=audit_result,
            locked_by="user@lts.de",
            current_status=PlanStatus.AUDITED,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, PlanStatus.LOCKED)
        self.assertEqual(result.locked_by, "user@lts.de")
        self.assertIsNotNone(result.locked_at)
        self.assertIsNotNone(result.audit_summary)

    def test_service_lock_fail_blocks(self):
        """Test that FAIL audit raises AuditGateError."""
        service = PlanService()
        audit_result = self._create_audit_result(
            overlap_status=AuditStatus.FAIL
        )

        with self.assertRaises(AuditGateError) as ctx:
            service.lock_plan(
                plan_id="PLAN_001",
                audit_result=audit_result,
                locked_by="user@lts.de",
                current_status=PlanStatus.AUDITED,
            )

        self.assertIn("OVERLAP", ctx.exception.failed_checks)
        self.assertIsNotNone(ctx.exception.audit_summary)

    def test_service_lock_already_locked(self):
        """Test that already locked raises PlanAlreadyLockedError."""
        service = PlanService()
        audit_result = self._create_audit_result()

        with self.assertRaises(PlanAlreadyLockedError):
            service.lock_plan(
                plan_id="PLAN_001",
                audit_result=audit_result,
                locked_by="user@lts.de",
                current_status=PlanStatus.LOCKED,  # Already locked!
            )

    def test_service_lock_invalid_state(self):
        """Test that invalid state raises PlanInvalidStateError."""
        service = PlanService()
        audit_result = self._create_audit_result()

        with self.assertRaises(PlanInvalidStateError):
            service.lock_plan(
                plan_id="PLAN_001",
                audit_result=audit_result,
                locked_by="user@lts.de",
                current_status=PlanStatus.SOLVING,  # Can't lock while solving!
            )

    def test_service_can_lock_check(self):
        """Test can_lock pre-check method."""
        service = PlanService()

        # All pass
        audit_pass = self._create_audit_result()
        result = service.can_lock(audit_pass)
        self.assertTrue(result["can_lock"])

        # One fail
        audit_fail = self._create_audit_result(skills_status=AuditStatus.FAIL)
        result = service.can_lock(audit_fail)
        self.assertFalse(result["can_lock"])
        self.assertIn("SKILLS_COMPLIANCE", result["failed_checks"])

    def test_service_lock_records_warnings(self):
        """Test that WARN is recorded in result."""
        service = PlanService()
        audit_result = self._create_audit_result(
            time_window_status=AuditStatus.WARN  # Warning, not fail
        )

        result = service.lock_plan(
            plan_id="PLAN_001",
            audit_result=audit_result,
            locked_by="user@lts.de",
            current_status=PlanStatus.DRAFT,
        )

        self.assertTrue(result.success)  # Lock allowed
        self.assertGreater(len(result.warnings), 0)  # But warning recorded
        self.assertIn("TIME_WINDOW", result.warnings[0])

    def test_audit_summary_in_result(self):
        """Test that audit summary is always in result."""
        service = PlanService()
        audit_result = self._create_audit_result()

        result = service.lock_plan(
            plan_id="PLAN_001",
            audit_result=audit_result,
            locked_by="user@lts.de",
            current_status=PlanStatus.AUDITED,
        )

        # Verify audit summary structure
        summary = result.audit_summary
        self.assertIn("audited_at", summary)
        self.assertIn("all_passed", summary)
        self.assertIn("checks_run", summary)
        self.assertIn("results", summary)

        # Verify each check is in results
        for check_name in AuditGate.REQUIRED_CHECKS:
            self.assertIn(check_name.value, summary["results"])


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Audit Gate Tests (Gate 2)")
    print("=" * 70)
    unittest.main(verbosity=2)
