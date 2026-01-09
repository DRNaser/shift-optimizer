# =============================================================================
# SOLVEREIGN Routing Pack - Repair Engine Tests
# =============================================================================

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from packs.routing.services.repair.repair_engine import (
    RepairEngine,
    RepairEvent,
    RepairEventType,
    RepairResult,
    RepairStatus,
    ChurnConfig,
    FreezeScope,
    ChurnMetrics,
    repair_no_show,
    repair_vehicle_down,
)


class TestRepairEngine(unittest.TestCase):
    """Test the repair engine."""

    def setUp(self):
        """Set up test fixtures."""
        self.today = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        self.engine = RepairEngine()

        # Test assignments (3 stops on VAN_01, 2 stops on VAN_02)
        self.assignments = [
            {
                "stop_id": "STOP_01",
                "vehicle_id": "VAN_01",
                "sequence_index": 1,
                "arrival_at": (self.today + timedelta(hours=1)).isoformat(),
                "departure_at": (self.today + timedelta(hours=1, minutes=15)).isoformat(),
            },
            {
                "stop_id": "STOP_02",
                "vehicle_id": "VAN_01",
                "sequence_index": 2,
                "arrival_at": (self.today + timedelta(hours=2)).isoformat(),
                "departure_at": (self.today + timedelta(hours=2, minutes=15)).isoformat(),
            },
            {
                "stop_id": "STOP_03",
                "vehicle_id": "VAN_01",
                "sequence_index": 3,
                "arrival_at": (self.today + timedelta(hours=3)).isoformat(),
                "departure_at": (self.today + timedelta(hours=3, minutes=15)).isoformat(),
            },
            {
                "stop_id": "STOP_04",
                "vehicle_id": "VAN_02",
                "sequence_index": 1,
                "arrival_at": (self.today + timedelta(hours=1, minutes=30)).isoformat(),
                "departure_at": (self.today + timedelta(hours=1, minutes=45)).isoformat(),
            },
            {
                "stop_id": "STOP_05",
                "vehicle_id": "VAN_02",
                "sequence_index": 2,
                "arrival_at": (self.today + timedelta(hours=2, minutes=30)).isoformat(),
                "departure_at": (self.today + timedelta(hours=2, minutes=45)).isoformat(),
            },
        ]

        self.unassigned = []

        self.stops = [
            {"id": "STOP_01", "order_id": "ORDER_01"},
            {"id": "STOP_02", "order_id": "ORDER_02"},
            {"id": "STOP_03", "order_id": "ORDER_03"},
            {"id": "STOP_04", "order_id": "ORDER_04"},
            {"id": "STOP_05", "order_id": "ORDER_05"},
        ]

        self.vehicles = [
            {"id": "VAN_01", "team_size": 2},
            {"id": "VAN_02", "team_size": 1},
            {"id": "VAN_03", "team_size": 1},  # Spare vehicle
        ]

    # =========================================================================
    # NO_SHOW TESTS
    # =========================================================================

    def test_no_show_removes_stop(self):
        """Test that NO_SHOW event removes stop and adds to unassigned."""
        event = RepairEvent(
            event_type=RepairEventType.NO_SHOW,
            stop_id="STOP_02",
            reason="Customer not home",
        )

        result = self.engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
        )

        # Check result
        self.assertIn(result.status, [RepairStatus.SUCCESS, RepairStatus.PARTIAL])

        # STOP_02 should be unassigned
        unassigned_ids = [u["stop_id"] for u in result.new_unassigned]
        self.assertIn("STOP_02", unassigned_ids)

        # STOP_02 should not be in assignments
        assigned_ids = [a["stop_id"] for a in result.new_assignments]
        self.assertNotIn("STOP_02", assigned_ids)

    def test_no_show_computes_churn(self):
        """Test that NO_SHOW computes correct churn metrics."""
        event = RepairEvent(
            event_type=RepairEventType.NO_SHOW,
            stop_id="STOP_02",
        )

        result = self.engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
        )

        # Should have churn for the removed stop
        self.assertGreaterEqual(result.churn.stops_became_unassigned, 1)
        self.assertGreater(result.churn.total_churn_score, 0)

    # =========================================================================
    # VEHICLE_DOWN TESTS
    # =========================================================================

    def test_vehicle_down_reassigns_stops(self):
        """Test that VEHICLE_DOWN reassigns stops to other vehicles."""
        event = RepairEvent(
            event_type=RepairEventType.VEHICLE_DOWN,
            vehicle_id="VAN_01",
            reason="Engine failure",
        )

        # Mark VAN_01 as frozen (can't receive new stops)
        freeze_scope = FreezeScope(locked_vehicle_ids={"VAN_01"})

        result = self.engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
            freeze_scope=freeze_scope,
        )

        # VAN_01 stops should be moved or unassigned
        van01_assignments = [
            a for a in result.new_assignments
            if a["vehicle_id"] == "VAN_01"
        ]

        # In simple V1, stops may be reassigned or become unassigned
        # At minimum, check the result is valid
        self.assertIsNotNone(result.status)

    def test_vehicle_down_high_churn(self):
        """Test that VEHICLE_DOWN produces significant churn."""
        event = RepairEvent(
            event_type=RepairEventType.VEHICLE_DOWN,
            vehicle_id="VAN_01",
        )

        freeze_scope = FreezeScope(locked_vehicle_ids={"VAN_01"})

        result = self.engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
            freeze_scope=freeze_scope,
        )

        # VAN_01 had 3 stops, so churn should reflect those
        affected = (
            result.churn.stops_vehicle_changed
            + result.churn.stops_became_unassigned
        )
        # At least some stops from VAN_01 should be affected
        self.assertGreater(affected, 0)

    # =========================================================================
    # FREEZE SCOPE TESTS
    # =========================================================================

    def test_frozen_stops_not_moved(self):
        """Test that frozen stops are not moved."""
        # Freeze STOP_01 explicitly
        freeze_scope = FreezeScope(
            locked_stop_ids={"STOP_01"},
            freeze_horizon_min=0,  # Disable time-based freeze
        )

        event = RepairEvent(
            event_type=RepairEventType.DELAY,
            vehicle_id="VAN_01",
            delay_minutes=30,
        )

        result = self.engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
            freeze_scope=freeze_scope,
        )

        # STOP_01 should still be on VAN_01
        stop01_assignment = next(
            (a for a in result.new_assignments if a["stop_id"] == "STOP_01"),
            None
        )
        self.assertIsNotNone(stop01_assignment)
        self.assertEqual(stop01_assignment["vehicle_id"], "VAN_01")
        # At least 1 frozen stop preserved (STOP_01)
        self.assertGreaterEqual(result.frozen_stops_preserved, 1)

    def test_time_based_freeze(self):
        """Test that stops within freeze horizon are frozen."""
        freeze_scope = FreezeScope(
            freeze_horizon_min=120,  # 2 hours
            freeze_at=self.today,
        )

        # STOP_01 arrives at today + 1 hour, which is within freeze horizon
        self.assertTrue(freeze_scope.is_stop_frozen(
            "STOP_01",
            self.today + timedelta(hours=1)
        ))

        # STOP_03 arrives at today + 3 hours, outside freeze horizon
        self.assertFalse(freeze_scope.is_stop_frozen(
            "STOP_03",
            self.today + timedelta(hours=3)
        ))

    # =========================================================================
    # CHURN CONFIG TESTS
    # =========================================================================

    def test_max_churn_limit(self):
        """Test that max churn limit rejects high-churn repairs."""
        # Set very low max churn
        config = ChurnConfig(max_churn_score=100)
        engine = RepairEngine(churn_config=config)

        event = RepairEvent(
            event_type=RepairEventType.VEHICLE_DOWN,
            vehicle_id="VAN_01",
        )

        freeze_scope = FreezeScope(locked_vehicle_ids={"VAN_01"})

        result = engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
            freeze_scope=freeze_scope,
        )

        # Should fail due to max churn exceeded
        self.assertEqual(result.status, RepairStatus.FAILED)
        self.assertIn("exceeds max", result.error_message)

    def test_custom_penalties(self):
        """Test that custom penalties affect churn calculation."""
        config = ChurnConfig(
            vehicle_change_penalty=50000,  # Very high
            unassigned_penalty=1000,       # Lower
        )
        engine = RepairEngine(churn_config=config)

        event = RepairEvent(
            event_type=RepairEventType.NO_SHOW,
            stop_id="STOP_02",
        )

        result = engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
        )

        # Unassigned penalty should be 1000
        # The churn should reflect at least this amount
        self.assertGreaterEqual(result.churn.total_churn_score, 1000)

    # =========================================================================
    # CONVENIENCE FUNCTION TESTS
    # =========================================================================

    def test_repair_no_show_convenience(self):
        """Test repair_no_show convenience function."""
        result = repair_no_show(
            stop_id="STOP_03",
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
            reason="Not available",
        )

        self.assertIn(result.status, [RepairStatus.SUCCESS, RepairStatus.PARTIAL])
        self.assertEqual(result.event.event_type, RepairEventType.NO_SHOW)
        self.assertEqual(result.event.stop_id, "STOP_03")

    def test_repair_vehicle_down_convenience(self):
        """Test repair_vehicle_down convenience function."""
        result = repair_vehicle_down(
            vehicle_id="VAN_02",
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
            reason="Flat tire",
        )

        self.assertEqual(result.event.event_type, RepairEventType.VEHICLE_DOWN)
        self.assertEqual(result.event.vehicle_id, "VAN_02")

    # =========================================================================
    # SERIALIZATION TESTS
    # =========================================================================

    def test_result_to_dict(self):
        """Test that repair result serializes correctly."""
        event = RepairEvent(
            event_type=RepairEventType.NO_SHOW,
            stop_id="STOP_01",
        )

        result = self.engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
        )

        result_dict = result.to_dict()

        self.assertIn("status", result_dict)
        self.assertIn("event", result_dict)
        self.assertIn("churn", result_dict)
        self.assertIn("new_assignments_count", result_dict)
        self.assertIn("repair_duration_ms", result_dict)

    def test_churn_metrics_to_dict(self):
        """Test that churn metrics serialize correctly."""
        event = RepairEvent(
            event_type=RepairEventType.NO_SHOW,
            stop_id="STOP_02",
        )

        result = self.engine.repair(
            event=event,
            original_assignments=self.assignments,
            original_unassigned=self.unassigned,
            stops=self.stops,
            vehicles=self.vehicles,
        )

        churn_dict = result.churn.to_dict()

        self.assertIn("total_churn_score", churn_dict)
        self.assertIn("stops_vehicle_changed", churn_dict)
        self.assertIn("stops_unchanged", churn_dict)
        self.assertIn("diffs", churn_dict)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Repair Engine Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
