# =============================================================================
# SOLVEREIGN Routing Pack - Input Validator Tests
# =============================================================================

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from packs.routing.domain.models import (
    Stop, Vehicle, Depot, Geocode, Address,
    StopCategory, Priority
)
from packs.routing.services.validation.input_validator import (
    InputValidator, RejectReason, ValidationConfig
)


class TestInputValidator(unittest.TestCase):
    """Test the input validator."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = InputValidator()
        self.today = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        # Valid depot
        self.valid_depot = Depot(
            id="DEPOT_01",
            tenant_id=1,
            site_id="SITE_01",
            name="Test Depot",
            geocode=Geocode(lat=52.52, lng=13.405),
            loading_time_min=15
        )

        # Valid vehicle
        self.valid_vehicle = Vehicle(
            id="VAN_01",
            tenant_id=1,
            scenario_id="TEST",
            external_id="V-001",
            team_id="TEAM_A",
            team_size=1,
            skills=["MONTAGE_BASIC"],
            shift_start_at=self.today,
            shift_end_at=self.today + timedelta(hours=8),
            start_depot_id="DEPOT_01",
            end_depot_id="DEPOT_01",
            capacity_volume_m3=10.0,
            capacity_weight_kg=800.0
        )

        # Valid stop
        self.valid_stop = Stop(
            id="STOP_01",
            order_id="ORDER_01",
            tenant_id=1,
            scenario_id="TEST",
            address=Address(
                street="Test Street",
                house_number="1",
                postal_code="10115",
                city="Berlin"
            ),
            geocode=Geocode(lat=52.53, lng=13.42),
            geocode_quality=None,
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            service_code="MM_DELIVERY",
            category=StopCategory.DELIVERY,
            service_duration_min=15,
        )

    def test_valid_scenario_passes(self):
        """Test that a valid scenario passes validation."""
        result = self.validator.validate(
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            depots=[self.valid_depot]
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.stops_validated, 1)
        self.assertEqual(result.vehicles_validated, 1)
        self.assertEqual(result.depots_validated, 1)

    def test_missing_geocode_fails(self):
        """Test that a stop without geocode fails."""
        stop = Stop(
            id="STOP_NO_GEO",
            order_id="ORDER_02",
            tenant_id=1,
            scenario_id="TEST",
            address=Address(
                street="No Geo Street",
                house_number="1",
                postal_code="10115",
                city="Berlin"
            ),
            geocode=None,  # Missing!
            geocode_quality=None,
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            service_code="MM_DELIVERY",
            category=StopCategory.DELIVERY,
            service_duration_min=15,
        )

        result = self.validator.validate(
            stops=[stop],
            vehicles=[self.valid_vehicle],
            depots=[self.valid_depot]
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].reason, RejectReason.STOP_MISSING_GEOCODE)
        self.assertEqual(result.errors[0].entity_id, "STOP_NO_GEO")

    def test_invalid_time_window_fails(self):
        """Test that a stop with start > end time window fails."""
        stop = Stop(
            id="STOP_BAD_TW",
            order_id="ORDER_03",
            tenant_id=1,
            scenario_id="TEST",
            address=Address(
                street="Bad TW Street",
                house_number="1",
                postal_code="10115",
                city="Berlin"
            ),
            geocode=Geocode(lat=52.53, lng=13.42),
            geocode_quality=None,
            tw_start=self.today + timedelta(hours=5),  # Start AFTER end
            tw_end=self.today + timedelta(hours=3),
            service_code="MM_DELIVERY",
            category=StopCategory.DELIVERY,
            service_duration_min=15,
        )

        result = self.validator.validate(
            stops=[stop],
            vehicles=[self.valid_vehicle],
            depots=[self.valid_depot]
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any(e.reason == RejectReason.STOP_TW_START_AFTER_END for e in result.errors))

    def test_unknown_skill_fails(self):
        """Test that a stop requiring unknown skill fails."""
        stop = Stop(
            id="STOP_UNKNOWN_SKILL",
            order_id="ORDER_04",
            tenant_id=1,
            scenario_id="TEST",
            address=Address(
                street="Skill Street",
                house_number="1",
                postal_code="10115",
                city="Berlin"
            ),
            geocode=Geocode(lat=52.53, lng=13.42),
            geocode_quality=None,
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            service_code="MM_DELIVERY",
            category=StopCategory.DELIVERY,
            service_duration_min=15,
            required_skills=["UNKNOWN_SKILL_XYZ"],  # Unknown!
        )

        result = self.validator.validate(
            stops=[stop],
            vehicles=[self.valid_vehicle],
            depots=[self.valid_depot]
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any(e.reason == RejectReason.STOP_UNKNOWN_SKILL for e in result.errors))

    def test_no_eligible_vehicle_for_skill(self):
        """Test that a stop requiring skill no vehicle has fails."""
        stop = Stop(
            id="STOP_NEED_ELEKTRO",
            order_id="ORDER_05",
            tenant_id=1,
            scenario_id="TEST",
            address=Address(
                street="Elektro Street",
                house_number="1",
                postal_code="10115",
                city="Berlin"
            ),
            geocode=Geocode(lat=52.53, lng=13.42),
            geocode_quality=None,
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            service_code="MM_DELIVERY",
            category=StopCategory.DELIVERY,
            service_duration_min=15,
            required_skills=["ELEKTRO"],  # Vehicle only has MONTAGE_BASIC
        )

        result = self.validator.validate(
            stops=[stop],
            vehicles=[self.valid_vehicle],
            depots=[self.valid_depot]
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any(e.reason == RejectReason.STOP_NO_ELIGIBLE_VEHICLE_SKILLS for e in result.errors))

    def test_two_person_no_team_fails(self):
        """Test that 2-person stop with no 2-person vehicle fails."""
        stop = Stop(
            id="STOP_2PERSON",
            order_id="ORDER_06",
            tenant_id=1,
            scenario_id="TEST",
            address=Address(
                street="2Person Street",
                house_number="1",
                postal_code="10115",
                city="Berlin"
            ),
            geocode=Geocode(lat=52.53, lng=13.42),
            geocode_quality=None,
            tw_start=self.today + timedelta(hours=1),
            tw_end=self.today + timedelta(hours=3),
            service_code="MM_DELIVERY",
            category=StopCategory.DELIVERY,
            service_duration_min=15,
            requires_two_person=True,  # Needs 2-person team
        )

        result = self.validator.validate(
            stops=[stop],
            vehicles=[self.valid_vehicle],  # Only team_size=1
            depots=[self.valid_depot]
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any(e.reason == RejectReason.STOP_NO_ELIGIBLE_TWO_PERSON for e in result.errors))

    def test_unknown_depot_fails(self):
        """Test that vehicle with unknown depot fails."""
        vehicle = Vehicle(
            id="VAN_BAD_DEPOT",
            tenant_id=1,
            scenario_id="TEST",
            external_id="V-002",
            team_id="TEAM_B",
            team_size=1,
            skills=[],
            shift_start_at=self.today,
            shift_end_at=self.today + timedelta(hours=8),
            start_depot_id="UNKNOWN_DEPOT",  # Unknown!
            end_depot_id="DEPOT_01",
            capacity_volume_m3=10.0,
            capacity_weight_kg=800.0
        )

        result = self.validator.validate(
            stops=[self.valid_stop],
            vehicles=[vehicle],
            depots=[self.valid_depot]
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any(e.reason == RejectReason.VEHICLE_UNKNOWN_START_DEPOT for e in result.errors))

    def test_invalid_shift_fails(self):
        """Test that vehicle with start > end shift fails."""
        vehicle = Vehicle(
            id="VAN_BAD_SHIFT",
            tenant_id=1,
            scenario_id="TEST",
            external_id="V-003",
            team_id="TEAM_C",
            team_size=1,
            skills=[],
            shift_start_at=self.today + timedelta(hours=10),  # Start after end
            shift_end_at=self.today + timedelta(hours=8),
            start_depot_id="DEPOT_01",
            end_depot_id="DEPOT_01",
            capacity_volume_m3=10.0,
            capacity_weight_kg=800.0
        )

        result = self.validator.validate(
            stops=[self.valid_stop],
            vehicles=[vehicle],
            depots=[self.valid_depot]
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any(e.reason == RejectReason.VEHICLE_SHIFT_START_AFTER_END for e in result.errors))

    def test_empty_scenario_fails(self):
        """Test that empty scenario fails."""
        result = self.validator.validate(
            stops=[],
            vehicles=[],
            depots=[]
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any(e.reason == RejectReason.SCENARIO_NO_STOPS for e in result.errors))
        self.assertTrue(any(e.reason == RejectReason.SCENARIO_NO_VEHICLES for e in result.errors))
        self.assertTrue(any(e.reason == RejectReason.SCENARIO_NO_DEPOTS for e in result.errors))

    def test_validation_result_to_dict(self):
        """Test that validation result converts to dict correctly."""
        result = self.validator.validate(
            stops=[self.valid_stop],
            vehicles=[self.valid_vehicle],
            depots=[self.valid_depot]
        )

        result_dict = result.to_dict()

        self.assertIn("is_valid", result_dict)
        self.assertIn("error_count", result_dict)
        self.assertIn("errors", result_dict)
        self.assertIn("summary", result_dict)
        self.assertTrue(result_dict["is_valid"])


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Input Validator Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
