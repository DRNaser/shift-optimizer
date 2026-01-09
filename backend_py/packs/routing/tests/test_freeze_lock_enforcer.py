# =============================================================================
# SOLVEREIGN Routing Pack - Gate 6: Freeze Lock Enforcer Tests
# =============================================================================
# Gate 6 Requirements:
# - freeze scope muss wirklich Stop-Locks erzwingen (nicht nur Empfehlung)
# - Bei Repair: erst aus DB laden welche Stops locked sind
# - Dann die locked_stop_ids HARD an Solver übergeben
# =============================================================================

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from packs.routing.services.repair.freeze_lock_enforcer import (
    FreezeLockLoader,
    FreezeLockEnforcer,
    FreezeLockState,
    FreezeLockRecord,
    FreezeLockViolationError,
    EnforcementResult,
    load_and_enforce_freeze_locks,
    validate_repair_respects_freeze,
)


class TestFreezeLockLoader(unittest.TestCase):
    """Test FreezeLockLoader - loading freeze state from DB."""

    def setUp(self):
        """Set up test fixtures."""
        self.now = datetime.now()
        self.loader = FreezeLockLoader(freeze_horizon_minutes=60)

    def test_load_explicit_locked_stops(self):
        """Test loading stops with is_locked=TRUE from DB."""
        print("\n" + "=" * 60)
        print("GATE 6: Load Explicit Locked Stops (is_locked=TRUE)")
        print("=" * 60)

        assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_01", "sequence_index": 1, "is_locked": True},
            {"stop_id": "STOP_02", "vehicle_id": "VAN_01", "sequence_index": 2, "is_locked": False},
            {"stop_id": "STOP_03", "vehicle_id": "VAN_02", "sequence_index": 1, "is_locked": True},
        ]

        state = self.loader.load_from_assignments(
            plan_id="PLAN_001",
            assignments=assignments,
            reference_time=self.now,
        )

        print(f"    Total frozen stops: {len(state.frozen_stops)}")
        print(f"    Frozen: {list(state.frozen_stop_ids)}")

        self.assertEqual(len(state.frozen_stops), 2)
        self.assertIn("STOP_01", state.frozen_stop_ids)
        self.assertIn("STOP_03", state.frozen_stop_ids)
        self.assertNotIn("STOP_02", state.frozen_stop_ids)

        # Verify lock source is DB_FLAG
        for stop_id in ["STOP_01", "STOP_03"]:
            record = state.get_lock_record(stop_id)
            self.assertEqual(record.lock_source, "DB_FLAG")

        print(f"    [PASS] Explicit locked stops loaded from DB")

    def test_load_time_based_freeze(self):
        """Test loading stops frozen by time horizon."""
        print("\n" + "=" * 60)
        print("GATE 6: Load Time-Based Frozen Stops")
        print("=" * 60)

        # Stops with arrivals at different times
        assignments = [
            {
                "stop_id": "STOP_01", "vehicle_id": "VAN_01", "sequence_index": 1,
                "is_locked": False,
                "arrival_at": (self.now + timedelta(minutes=30)).isoformat(),  # Within 60min horizon
            },
            {
                "stop_id": "STOP_02", "vehicle_id": "VAN_01", "sequence_index": 2,
                "is_locked": False,
                "arrival_at": (self.now + timedelta(minutes=90)).isoformat(),  # Outside horizon
            },
            {
                "stop_id": "STOP_03", "vehicle_id": "VAN_02", "sequence_index": 1,
                "is_locked": False,
                "arrival_at": (self.now + timedelta(minutes=15)).isoformat(),  # Within horizon
            },
        ]

        state = self.loader.load_from_assignments(
            plan_id="PLAN_001",
            assignments=assignments,
            reference_time=self.now,
        )

        print(f"    Freeze horizon: {state.freeze_horizon_minutes} minutes")
        print(f"    Total frozen: {len(state.frozen_stops)}")
        print(f"    Frozen: {list(state.frozen_stop_ids)}")

        # STOP_01 (30min) and STOP_03 (15min) should be frozen
        # STOP_02 (90min) should NOT be frozen
        self.assertEqual(len(state.frozen_stops), 2)
        self.assertIn("STOP_01", state.frozen_stop_ids)
        self.assertIn("STOP_03", state.frozen_stop_ids)
        self.assertNotIn("STOP_02", state.frozen_stop_ids)

        # Verify lock source is TIME_HORIZON
        for stop_id in ["STOP_01", "STOP_03"]:
            record = state.get_lock_record(stop_id)
            self.assertEqual(record.lock_source, "TIME_HORIZON")

        print(f"    [PASS] Time-based frozen stops computed correctly")

    def test_vehicle_map_preserved(self):
        """Test that frozen stops have vehicle mapping preserved."""
        print("\n" + "=" * 60)
        print("GATE 6: Vehicle Mapping Preserved")
        print("=" * 60)

        assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1, "is_locked": True},
            {"stop_id": "STOP_02", "vehicle_id": "VAN_B", "sequence_index": 1, "is_locked": True},
        ]

        state = self.loader.load_from_assignments(
            plan_id="PLAN_001",
            assignments=assignments,
            reference_time=self.now,
        )

        vehicle_map = state.stop_vehicle_map

        print(f"    STOP_01 -> {vehicle_map['STOP_01']}")
        print(f"    STOP_02 -> {vehicle_map['STOP_02']}")

        self.assertEqual(vehicle_map["STOP_01"], "VAN_A")
        self.assertEqual(vehicle_map["STOP_02"], "VAN_B")
        print(f"    [PASS] Vehicle mapping preserved for frozen stops")


class TestFreezeLockEnforcer(unittest.TestCase):
    """Test FreezeLockEnforcer - hard enforcement of freeze-locks."""

    def setUp(self):
        """Set up test fixtures."""
        self.now = datetime.now()
        self.enforcer = FreezeLockEnforcer()

        # Create freeze state with 2 frozen stops
        self.freeze_state = FreezeLockState(
            plan_id="PLAN_001",
            frozen_stops={
                "STOP_01": FreezeLockRecord(
                    stop_id="STOP_01",
                    vehicle_id="VAN_A",
                    sequence_index=1,
                    lock_source="DB_FLAG",
                    lock_reason="Explicitly locked",
                    locked_at=self.now,
                ),
                "STOP_02": FreezeLockRecord(
                    stop_id="STOP_02",
                    vehicle_id="VAN_A",
                    sequence_index=2,
                    lock_source="TIME_HORIZON",
                    lock_reason="Arrival in 30 minutes",
                    locked_at=self.now,
                ),
            },
            frozen_vehicles=set(),
            computed_at=self.now,
        )

    def test_enforcement_passes_when_unchanged(self):
        """Test that enforcement passes when frozen stops are unchanged."""
        print("\n" + "=" * 60)
        print("GATE 6: Enforcement Passes (Unchanged)")
        print("=" * 60)

        new_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1},
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 2},
            {"stop_id": "STOP_03", "vehicle_id": "VAN_A", "sequence_index": 3},  # Movable
        ]

        result = self.enforcer.enforce(
            freeze_state=self.freeze_state,
            new_assignments=new_assignments,
            raise_on_violation=False,
        )

        print(f"    Passed: {result.passed}")
        print(f"    Violations: {len(result.violations)}")
        print(f"    Preserved: {result.frozen_stops_preserved}/{result.total_frozen_stops}")

        self.assertTrue(result.passed)
        self.assertEqual(len(result.violations), 0)
        self.assertEqual(result.frozen_stops_preserved, 2)
        print(f"    [PASS] Enforcement passes when frozen stops unchanged")

    def test_enforcement_fails_vehicle_change(self):
        """Test that enforcement fails when frozen stop changes vehicle."""
        print("\n" + "=" * 60)
        print("GATE 6: Enforcement Fails (Vehicle Changed)")
        print("=" * 60)

        # Move STOP_01 from VAN_A to VAN_B (VIOLATION!)
        new_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_B", "sequence_index": 1},  # VIOLATION
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 2},
        ]

        with self.assertRaises(FreezeLockViolationError) as ctx:
            self.enforcer.enforce(
                freeze_state=self.freeze_state,
                new_assignments=new_assignments,
                raise_on_violation=True,
            )

        print(f"    Exception: {ctx.exception}")
        self.assertEqual(ctx.exception.stop_id, "STOP_01")
        self.assertIn("VAN_A", str(ctx.exception))
        self.assertIn("VAN_B", str(ctx.exception))
        print(f"    [PASS] Vehicle change correctly rejected")

    def test_enforcement_fails_sequence_change(self):
        """Test that enforcement fails when frozen stop changes sequence."""
        print("\n" + "=" * 60)
        print("GATE 6: Enforcement Fails (Sequence Changed)")
        print("=" * 60)

        # Change STOP_02 sequence from 2 to 5 (VIOLATION!)
        new_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1},
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 5},  # VIOLATION
        ]

        with self.assertRaises(FreezeLockViolationError) as ctx:
            self.enforcer.enforce(
                freeze_state=self.freeze_state,
                new_assignments=new_assignments,
                raise_on_violation=True,
            )

        print(f"    Exception: {ctx.exception}")
        self.assertEqual(ctx.exception.stop_id, "STOP_02")
        self.assertIn("RESEQUENCE", ctx.exception.attempted_action)
        print(f"    [PASS] Sequence change correctly rejected")

    def test_enforcement_fails_stop_removed(self):
        """Test that enforcement fails when frozen stop is removed."""
        print("\n" + "=" * 60)
        print("GATE 6: Enforcement Fails (Stop Removed)")
        print("=" * 60)

        # STOP_01 is missing (VIOLATION!)
        new_assignments = [
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 2},
            # STOP_01 is missing!
        ]

        with self.assertRaises(FreezeLockViolationError) as ctx:
            self.enforcer.enforce(
                freeze_state=self.freeze_state,
                new_assignments=new_assignments,
                raise_on_violation=True,
            )

        print(f"    Exception: {ctx.exception}")
        self.assertEqual(ctx.exception.stop_id, "STOP_01")
        self.assertEqual(ctx.exception.attempted_action, "REMOVE")
        print(f"    [PASS] Stop removal correctly rejected")

    def test_enforcement_returns_violations_without_raise(self):
        """Test that enforcement returns violations when raise_on_violation=False."""
        print("\n" + "=" * 60)
        print("GATE 6: Returns Violations Without Raising")
        print("=" * 60)

        # Multiple violations
        new_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_B", "sequence_index": 1},  # Vehicle changed
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 5},  # Sequence changed
        ]

        result = self.enforcer.enforce(
            freeze_state=self.freeze_state,
            new_assignments=new_assignments,
            raise_on_violation=False,  # Don't raise
        )

        print(f"    Passed: {result.passed}")
        print(f"    Violations: {len(result.violations)}")
        for v in result.violations:
            print(f"      - {v['stop_id']}: {v['violation_type']}")

        self.assertFalse(result.passed)
        self.assertEqual(len(result.violations), 2)
        print(f"    [PASS] Violations returned without exception")

    def test_solver_constraints_generated(self):
        """Test that OR-Tools constraints are generated correctly."""
        print("\n" + "=" * 60)
        print("GATE 6: OR-Tools Constraints Generated")
        print("=" * 60)

        # Mappings
        stop_to_node = {"STOP_01": 1, "STOP_02": 2, "STOP_03": 3}
        vehicle_to_idx = {"VAN_A": 0, "VAN_B": 1}

        constraints = self.enforcer.get_solver_constraints(
            freeze_state=self.freeze_state,
            stop_to_node=stop_to_node,
            vehicle_to_idx=vehicle_to_idx,
        )

        print(f"    Constraints generated: {len(constraints)}")
        for node_idx, allowed_vehicles in constraints:
            print(f"      Node {node_idx} -> Vehicles {allowed_vehicles}")

        # Should have 2 constraints (for STOP_01 and STOP_02)
        self.assertEqual(len(constraints), 2)

        # STOP_01 (node 1) should only allow VAN_A (idx 0)
        stop01_constraint = next((c for c in constraints if c[0] == 1), None)
        self.assertIsNotNone(stop01_constraint)
        self.assertEqual(stop01_constraint[1], [0])

        # STOP_02 (node 2) should only allow VAN_A (idx 0)
        stop02_constraint = next((c for c in constraints if c[0] == 2), None)
        self.assertIsNotNone(stop02_constraint)
        self.assertEqual(stop02_constraint[1], [0])

        print(f"    [PASS] OR-Tools constraints generated correctly")


class TestGate6Integration(unittest.TestCase):
    """Gate 6: Full integration tests."""

    def test_load_and_enforce_workflow(self):
        """
        Integration test: Complete Gate 6 workflow.

        1. Load freeze-locks from assignments (simulating DB)
        2. Simulate repair that respects freeze-locks
        3. Enforce -> should PASS
        """
        print("\n" + "=" * 70)
        print("GATE 6 INTEGRATION: Load + Enforce Workflow (Pass)")
        print("=" * 70)

        now = datetime.now()

        # Original assignments with is_locked flags
        original_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1, "is_locked": True},
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 2, "is_locked": True},
            {"stop_id": "STOP_03", "vehicle_id": "VAN_A", "sequence_index": 3, "is_locked": False},
            {"stop_id": "STOP_04", "vehicle_id": "VAN_B", "sequence_index": 1, "is_locked": False},
        ]

        # Repaired assignments - frozen stops unchanged, movable stops resequenced
        new_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1},  # FROZEN - unchanged
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 2},  # FROZEN - unchanged
            {"stop_id": "STOP_03", "vehicle_id": "VAN_B", "sequence_index": 2},  # MOVED (allowed)
            {"stop_id": "STOP_04", "vehicle_id": "VAN_B", "sequence_index": 1},  # MOVED (allowed)
        ]

        print("\n[1] Loading freeze-locks from DB...")
        freeze_state, result = load_and_enforce_freeze_locks(
            plan_id="PLAN_001",
            original_assignments=original_assignments,
            new_assignments=new_assignments,
            reference_time=now,
        )

        print(f"    Frozen stops: {len(freeze_state.frozen_stops)}")
        print(f"    Enforcement passed: {result.passed}")
        print(f"    Preserved: {result.frozen_stops_preserved}/{result.total_frozen_stops}")

        self.assertTrue(result.passed)
        self.assertEqual(result.frozen_stops_preserved, 2)

        print("\n" + "=" * 70)
        print("GATE 6 PASSED: Freeze-locks enforced correctly")
        print("=" * 70)

    def test_load_and_enforce_rejects_violation(self):
        """
        Integration test: Gate 6 rejects freeze-lock violation.
        """
        print("\n" + "=" * 70)
        print("GATE 6 INTEGRATION: Load + Enforce Workflow (Reject)")
        print("=" * 70)

        now = datetime.now()

        original_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1, "is_locked": True},
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 2, "is_locked": False},
        ]

        # BAD repair - moves frozen stop to different vehicle!
        bad_assignments = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_B", "sequence_index": 1},  # VIOLATION!
            {"stop_id": "STOP_02", "vehicle_id": "VAN_A", "sequence_index": 2},
        ]

        print("\n[1] Attempting repair that violates freeze-locks...")

        with self.assertRaises(FreezeLockViolationError) as ctx:
            load_and_enforce_freeze_locks(
                plan_id="PLAN_001",
                original_assignments=original_assignments,
                new_assignments=bad_assignments,
                reference_time=now,
            )

        print(f"    Violation detected: {ctx.exception.stop_id}")
        print(f"    Reason: {ctx.exception.lock_reason}")
        print(f"    Action attempted: {ctx.exception.attempted_action}")

        print("\n" + "=" * 70)
        print("GATE 6 PASSED: Freeze-lock violation correctly REJECTED")
        print("=" * 70)

    def test_validate_repair_respects_freeze_helper(self):
        """Test the convenience validation function."""
        print("\n" + "=" * 70)
        print("GATE 6 INTEGRATION: Validation Helper Function")
        print("=" * 70)

        original = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1, "is_locked": True},
        ]

        # Good repair
        good_repair = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_A", "sequence_index": 1},
        ]

        # Bad repair
        bad_repair = [
            {"stop_id": "STOP_01", "vehicle_id": "VAN_B", "sequence_index": 1},
        ]

        # Good repair should pass
        is_valid = validate_repair_respects_freeze(
            plan_id="PLAN_001",
            original_assignments=original,
            repaired_assignments=good_repair,
        )
        self.assertTrue(is_valid)
        print(f"    Good repair: VALID")

        # Bad repair should raise
        with self.assertRaises(FreezeLockViolationError):
            validate_repair_respects_freeze(
                plan_id="PLAN_001",
                original_assignments=original,
                repaired_assignments=bad_repair,
            )
        print(f"    Bad repair: REJECTED")

        print("\n" + "=" * 70)
        print("GATE 6 PASSED: Validation helper works correctly")
        print("=" * 70)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Gate 6: Freeze Lock Enforcer Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
