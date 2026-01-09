# =============================================================================
# SOLVEREIGN Routing Pack - Route Auditor Tests
# =============================================================================

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from packs.routing.services.audit.route_auditor import (
    RouteAuditor,
    AuditResult,
    AuditCheck,
    AuditCheckName,
    AuditStatus,
    AuditStop,
    AuditVehicle,
    AuditAssignment,
    AuditUnassigned,
    audit_plan,
)


class TestRouteAuditor(unittest.TestCase):
    """Test the route auditor."""

    def setUp(self):
        """Set up test fixtures."""
        self.auditor = RouteAuditor()
        self.today = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        # Valid stop
        self.valid_stop = AuditStop(
            id="STOP_01",
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            tw_is_hard=True,
            required_skills=["MONTAGE_BASIC"],
            requires_two_person=False,
        )

        # Valid vehicle
        self.valid_vehicle = AuditVehicle(
            id="VAN_01",
            shift_start_at=self.today,
            shift_end_at=self.today + timedelta(hours=8),
            skills=["MONTAGE_BASIC", "ELEKTRO"],
            team_size=2,
        )

        # Valid assignment
        self.valid_assignment = AuditAssignment(
            stop_id="STOP_01",
            vehicle_id="VAN_01",
            arrival_at=self.today + timedelta(hours=1, minutes=30),
            departure_at=self.today + timedelta(hours=2),
            sequence_index=1,
        )

    # =========================================================================
    # ALL PASS TESTS
    # =========================================================================

    def test_valid_plan_passes_all_checks(self):
        """Test that a valid plan passes all audit checks."""
        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[self.valid_assignment],
            unassigned=[],
        )

        self.assertTrue(result.all_passed)
        self.assertEqual(result.checks_run, 5)
        self.assertEqual(result.checks_passed, 5)
        self.assertEqual(result.checks_failed, 0)

    # =========================================================================
    # COVERAGE TESTS
    # =========================================================================

    def test_coverage_missing_stop_fails(self):
        """Test that unaccounted stop fails coverage check."""
        # Stop exists but no assignment and no unassigned reason
        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[],  # No assignments!
            unassigned=[],   # No unassigned reasons!
        )

        self.assertFalse(result.all_passed)
        coverage = result.results[AuditCheckName.COVERAGE]
        self.assertEqual(coverage.status, AuditStatus.FAIL)
        self.assertEqual(coverage.violation_count, 1)
        self.assertEqual(coverage.details["missing_count"], 1)

    def test_coverage_with_unassigned_reason_warns(self):
        """Test that unassigned stop with reason is WARN (not FAIL)."""
        unassigned = AuditUnassigned(
            stop_id="STOP_01",
            reason_code="STOP_NO_ELIGIBLE_VEHICLE_SKILLS",
            reason_details="No vehicle has required skill SPECIAL"
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[],
            unassigned=[unassigned],
        )

        coverage = result.results[AuditCheckName.COVERAGE]
        self.assertEqual(coverage.status, AuditStatus.WARN)  # WARN, not FAIL
        self.assertEqual(coverage.details["unassigned_count"], 1)
        self.assertEqual(coverage.details["assigned_count"], 0)

    def test_coverage_duplicate_fails(self):
        """Test that stop both assigned and unassigned fails."""
        unassigned = AuditUnassigned(
            stop_id="STOP_01",  # Same as assigned stop
            reason_code="SOME_REASON",
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[self.valid_assignment],
            unassigned=[unassigned],  # Also in unassigned!
        )

        coverage = result.results[AuditCheckName.COVERAGE]
        self.assertEqual(coverage.status, AuditStatus.FAIL)
        self.assertEqual(coverage.details["duplicate_count"], 1)

    # =========================================================================
    # TIME WINDOW TESTS
    # =========================================================================

    def test_time_window_hard_late_fails(self):
        """Test that late arrival on hard TW fails."""
        late_assignment = AuditAssignment(
            stop_id="STOP_01",
            vehicle_id="VAN_01",
            arrival_at=self.today + timedelta(hours=4),  # After tw_end (3 hours)
            departure_at=self.today + timedelta(hours=4, minutes=30),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[late_assignment],
            unassigned=[],
        )

        tw_check = result.results[AuditCheckName.TIME_WINDOW]
        self.assertEqual(tw_check.status, AuditStatus.FAIL)
        self.assertEqual(tw_check.details["hard_violations"], 1)

    def test_time_window_hard_early_fails(self):
        """Test that early arrival on hard TW fails."""
        early_assignment = AuditAssignment(
            stop_id="STOP_01",
            vehicle_id="VAN_01",
            arrival_at=self.today + timedelta(minutes=30),  # Before tw_start (1 hour)
            departure_at=self.today + timedelta(hours=1),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[early_assignment],
            unassigned=[],
        )

        tw_check = result.results[AuditCheckName.TIME_WINDOW]
        self.assertEqual(tw_check.status, AuditStatus.FAIL)
        self.assertEqual(tw_check.details["hard_violations"], 1)

    def test_time_window_soft_late_warns(self):
        """Test that late arrival on soft TW warns (not fails)."""
        soft_stop = AuditStop(
            id="STOP_SOFT",
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            tw_is_hard=False,  # Soft TW
            required_skills=[],
            requires_two_person=False,
        )

        late_assignment = AuditAssignment(
            stop_id="STOP_SOFT",
            vehicle_id="VAN_01",
            arrival_at=self.today + timedelta(hours=4),  # After tw_end
            departure_at=self.today + timedelta(hours=4, minutes=30),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[soft_stop],
            vehicles=[self.valid_vehicle],
            assignments=[late_assignment],
            unassigned=[],
        )

        tw_check = result.results[AuditCheckName.TIME_WINDOW]
        self.assertEqual(tw_check.status, AuditStatus.WARN)  # WARN, not FAIL
        self.assertEqual(tw_check.details["soft_violations"], 1)
        self.assertEqual(tw_check.details["hard_violations"], 0)

    # =========================================================================
    # SHIFT FEASIBILITY TESTS
    # =========================================================================

    def test_shift_route_before_shift_fails(self):
        """Test that route starting before shift fails."""
        early_assignment = AuditAssignment(
            stop_id="STOP_01",
            vehicle_id="VAN_01",
            arrival_at=self.today - timedelta(hours=1),  # Before shift start
            departure_at=self.today - timedelta(minutes=30),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[early_assignment],
            unassigned=[],
        )

        shift_check = result.results[AuditCheckName.SHIFT_FEASIBILITY]
        self.assertEqual(shift_check.status, AuditStatus.FAIL)
        self.assertEqual(shift_check.details["vehicles_with_violations"], 1)

    def test_shift_route_after_shift_fails(self):
        """Test that route ending after shift fails."""
        late_assignment = AuditAssignment(
            stop_id="STOP_01",
            vehicle_id="VAN_01",
            arrival_at=self.today + timedelta(hours=9),  # After shift end (8 hours)
            departure_at=self.today + timedelta(hours=10),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[late_assignment],
            unassigned=[],
        )

        shift_check = result.results[AuditCheckName.SHIFT_FEASIBILITY]
        self.assertEqual(shift_check.status, AuditStatus.FAIL)

    # =========================================================================
    # SKILLS COMPLIANCE TESTS
    # =========================================================================

    def test_skills_missing_skill_fails(self):
        """Test that missing required skill fails."""
        stop_needs_skill = AuditStop(
            id="STOP_SKILL",
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            tw_is_hard=True,
            required_skills=["SPECIAL_SKILL"],  # Vehicle doesn't have this
            requires_two_person=False,
        )

        assignment = AuditAssignment(
            stop_id="STOP_SKILL",
            vehicle_id="VAN_01",
            arrival_at=self.today + timedelta(hours=1, minutes=30),
            departure_at=self.today + timedelta(hours=2),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[stop_needs_skill],
            vehicles=[self.valid_vehicle],  # Has MONTAGE_BASIC, ELEKTRO - not SPECIAL_SKILL
            assignments=[assignment],
            unassigned=[],
        )

        skills_check = result.results[AuditCheckName.SKILLS_COMPLIANCE]
        self.assertEqual(skills_check.status, AuditStatus.FAIL)
        self.assertEqual(skills_check.details["skill_violations"], 1)

    def test_skills_two_person_violation_fails(self):
        """Test that 2-person requirement with 1-person team fails."""
        stop_needs_two = AuditStop(
            id="STOP_2P",
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            tw_is_hard=True,
            required_skills=[],
            requires_two_person=True,  # Needs 2-person
        )

        single_vehicle = AuditVehicle(
            id="VAN_SINGLE",
            shift_start_at=self.today,
            shift_end_at=self.today + timedelta(hours=8),
            skills=[],
            team_size=1,  # Only 1 person
        )

        assignment = AuditAssignment(
            stop_id="STOP_2P",
            vehicle_id="VAN_SINGLE",
            arrival_at=self.today + timedelta(hours=1, minutes=30),
            departure_at=self.today + timedelta(hours=2),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[stop_needs_two],
            vehicles=[single_vehicle],
            assignments=[assignment],
            unassigned=[],
        )

        skills_check = result.results[AuditCheckName.SKILLS_COMPLIANCE]
        self.assertEqual(skills_check.status, AuditStatus.FAIL)
        self.assertEqual(skills_check.details["two_person_violations"], 1)

    # =========================================================================
    # OVERLAP TESTS
    # =========================================================================

    def test_overlap_duplicate_assignment_fails(self):
        """Test that stop assigned to multiple vehicles fails."""
        vehicle2 = AuditVehicle(
            id="VAN_02",
            shift_start_at=self.today,
            shift_end_at=self.today + timedelta(hours=8),
            skills=["MONTAGE_BASIC"],
            team_size=1,
        )

        assignment1 = AuditAssignment(
            stop_id="STOP_01",  # Same stop
            vehicle_id="VAN_01",
            arrival_at=self.today + timedelta(hours=1, minutes=30),
            departure_at=self.today + timedelta(hours=2),
            sequence_index=1,
        )

        assignment2 = AuditAssignment(
            stop_id="STOP_01",  # Same stop - DUPLICATE!
            vehicle_id="VAN_02",
            arrival_at=self.today + timedelta(hours=2, minutes=30),
            departure_at=self.today + timedelta(hours=3),
            sequence_index=1,
        )

        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle, vehicle2],
            assignments=[assignment1, assignment2],
            unassigned=[],
        )

        overlap_check = result.results[AuditCheckName.OVERLAP]
        self.assertEqual(overlap_check.status, AuditStatus.FAIL)
        self.assertEqual(overlap_check.details["duplicate_assignments"], 1)

    # =========================================================================
    # RESULT SERIALIZATION TESTS
    # =========================================================================

    def test_result_to_dict(self):
        """Test that audit result converts to dict correctly."""
        result = self.auditor.audit(
            plan_id="PLAN_01",
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            assignments=[self.valid_assignment],
            unassigned=[],
        )

        result_dict = result.to_dict()

        self.assertIn("plan_id", result_dict)
        self.assertIn("all_passed", result_dict)
        self.assertIn("checks_run", result_dict)
        self.assertIn("results", result_dict)
        self.assertIn("audited_at", result_dict)

        # Check nested structure
        self.assertIn("COVERAGE", result_dict["results"])
        self.assertIn("status", result_dict["results"]["COVERAGE"])

    # =========================================================================
    # CONVENIENCE FUNCTION TESTS
    # =========================================================================

    def test_audit_plan_from_dicts(self):
        """Test the audit_plan convenience function with dict data."""
        stops = [{
            "id": "STOP_01",
            "tw_start": (self.today + timedelta(hours=1)).isoformat(),
            "tw_end": (self.today + timedelta(hours=3)).isoformat(),
            "tw_is_hard": True,
            "required_skills": [],
            "requires_two_person": False,
        }]

        vehicles = [{
            "id": "VAN_01",
            "shift_start_at": self.today.isoformat(),
            "shift_end_at": (self.today + timedelta(hours=8)).isoformat(),
            "skills": [],
            "team_size": 1,
        }]

        assignments = [{
            "stop_id": "STOP_01",
            "vehicle_id": "VAN_01",
            "arrival_at": (self.today + timedelta(hours=1, minutes=30)).isoformat(),
            "departure_at": (self.today + timedelta(hours=2)).isoformat(),
            "sequence_index": 1,
        }]

        result = audit_plan(
            plan_id="PLAN_01",
            stops=stops,
            vehicles=vehicles,
            assignments=assignments,
            unassigned=[],
        )

        self.assertTrue(result.all_passed)
        self.assertEqual(result.checks_run, 5)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Route Auditor Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
