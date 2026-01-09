# =============================================================================
# SOLVEREIGN Routing Pack - Basic Solver Tests
# =============================================================================
# Unit tests for VRPTW solver components.
#
# Run with: python -m pytest packs/routing/tests/test_solver_basic.py -v
# =============================================================================

import pytest
from datetime import datetime, timedelta
from typing import List

# Domain models
from packs.routing.domain.models import (
    Stop, Vehicle, Depot, Geocode, Address,
    StopCategory, Priority, SolverConfig
)

# Services
from packs.routing.services.travel_time.provider import TravelTimeProvider, TravelTimeResult, MatrixResult
from packs.routing.services.travel_time.static_matrix import StaticMatrixProvider, StaticMatrixConfig

# Policies
from packs.routing.policies.job_templates import get_template_for_service_code, JOB_TEMPLATES
from packs.routing.policies.objectives import get_profile_for_vertical, OBJECTIVE_PROFILES


# =============================================================================
# FIXTURES
# =============================================================================

class MockTravelTimeProvider(TravelTimeProvider):
    """Mock provider for testing (uses Haversine distance)."""

    @property
    def provider_name(self) -> str:
        return "mock"

    def health_check(self) -> bool:
        return True

    def get_travel_time(self, origin, destination) -> TravelTimeResult:
        # Simple mock: 1 minute per 0.01 degrees
        lat_diff = abs(origin[0] - destination[0])
        lng_diff = abs(origin[1] - destination[1])
        distance_deg = (lat_diff + lng_diff)
        duration_min = int(distance_deg * 100)  # 1 min per 0.01 deg
        distance_m = int(distance_deg * 111000)  # ~111km per degree

        return TravelTimeResult(
            origin=origin,
            destination=destination,
            duration_seconds=duration_min * 60,
            distance_meters=distance_m
        )

    def get_matrix(self, locations) -> MatrixResult:
        n = len(locations)
        time_matrix = [[0] * n for _ in range(n)]
        distance_matrix = [[0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i != j:
                    result = self.get_travel_time(locations[i], locations[j])
                    time_matrix[i][j] = result.duration_seconds
                    distance_matrix[i][j] = result.distance_meters

        return MatrixResult(
            locations=locations,
            time_matrix=time_matrix,
            distance_matrix=distance_matrix
        )


def create_test_depot(depot_id: str, lat: float, lng: float) -> Depot:
    """Create a test depot."""
    return Depot(
        id=depot_id,
        tenant_id=1,
        site_id=depot_id,
        name=f"Depot {depot_id}",
        geocode=Geocode(lat=lat, lng=lng),
        loading_time_min=10
    )


def create_test_stop(
    stop_id: str,
    lat: float,
    lng: float,
    tw_start: datetime,
    tw_end: datetime,
    service_code: str = "MM_DELIVERY",
    requires_two_person: bool = False,
    required_skills: List[str] = None
) -> Stop:
    """Create a test stop."""
    template = get_template_for_service_code(service_code)

    return Stop(
        id=stop_id,
        order_id=f"ORDER_{stop_id}",
        tenant_id=1,
        scenario_id="test_scenario",
        address=Address(
            street="Test Street",
            house_number="1",
            postal_code="12345",
            city="Berlin"
        ),
        geocode=Geocode(lat=lat, lng=lng),
        geocode_quality=None,
        tw_start=tw_start,
        tw_end=tw_end,
        tw_is_hard=True,
        service_code=service_code,
        category=StopCategory.DELIVERY,
        service_duration_min=template.base_service_min,
        requires_two_person=requires_two_person or template.requires_two_person,
        required_skills=required_skills or template.default_skills or [],
        volume_m3=0.1,
        weight_kg=10.0,
        load_delta=-1,
        priority=Priority.NORMAL
    )


def create_test_vehicle(
    vehicle_id: str,
    depot_id: str,
    shift_start: datetime,
    shift_end: datetime,
    team_size: int = 1,
    skills: List[str] = None
) -> Vehicle:
    """Create a test vehicle."""
    return Vehicle(
        id=vehicle_id,
        tenant_id=1,
        scenario_id="test_scenario",
        external_id=vehicle_id,
        team_id=f"team_{vehicle_id}",
        team_size=team_size,
        skills=skills or [],
        shift_start_at=shift_start,
        shift_end_at=shift_end,
        start_depot_id=depot_id,
        end_depot_id=depot_id,
        capacity_volume_m3=10.0,
        capacity_weight_kg=1000.0
    )


# =============================================================================
# TESTS: Domain Models
# =============================================================================

class TestDomainModels:
    """Test domain model creation and methods."""

    def test_depot_creation(self):
        """Test depot can be created."""
        depot = create_test_depot("D1", 52.52, 13.405)
        assert depot.id == "D1"
        assert depot.geocode.lat == 52.52
        assert depot.geocode.lng == 13.405

    def test_stop_creation(self):
        """Test stop can be created with template."""
        now = datetime.now()
        stop = create_test_stop(
            "S1", 52.53, 13.41,
            tw_start=now,
            tw_end=now + timedelta(hours=2),
            service_code="MM_DELIVERY"
        )
        assert stop.id == "S1"
        assert stop.service_code == "MM_DELIVERY"
        assert stop.service_duration_min == 10  # From template

    def test_vehicle_creation(self):
        """Test vehicle can be created."""
        now = datetime.now()
        vehicle = create_test_vehicle(
            "V1", "D1",
            shift_start=now,
            shift_end=now + timedelta(hours=8),
            team_size=2,
            skills=["MONTAGE_BASIC"]
        )
        assert vehicle.id == "V1"
        assert vehicle.team_size == 2
        assert vehicle.can_do_two_person()
        assert vehicle.has_skill("MONTAGE_BASIC")

    def test_vehicle_skill_check(self):
        """Test vehicle skill matching."""
        now = datetime.now()
        vehicle = create_test_vehicle(
            "V1", "D1",
            shift_start=now,
            shift_end=now + timedelta(hours=8),
            skills=["MONTAGE_BASIC", "HEAVY_LIFT"]
        )
        assert vehicle.has_all_skills(["MONTAGE_BASIC"])
        assert vehicle.has_all_skills(["MONTAGE_BASIC", "HEAVY_LIFT"])
        assert not vehicle.has_all_skills(["ELEKTRO"])


# =============================================================================
# TESTS: Job Templates
# =============================================================================

class TestJobTemplates:
    """Test job template lookup and configuration."""

    def test_known_template_lookup(self):
        """Test lookup of known service codes."""
        template = get_template_for_service_code("MM_DELIVERY")
        assert template.base_service_min == 10
        assert not template.requires_two_person

    def test_montage_template(self):
        """Test montage template has correct settings."""
        template = get_template_for_service_code("MM_DELIVERY_MONTAGE")
        assert template.base_service_min == 60
        assert template.requires_two_person
        assert "MONTAGE_BASIC" in template.default_skills

    def test_unknown_template_fallback(self):
        """Test unknown service code falls back to default."""
        template = get_template_for_service_code("UNKNOWN_SERVICE")
        assert template.service_code == "DEFAULT"
        assert template.base_service_min == 30

    def test_hdl_complex_template(self):
        """Test HDL complex montage template."""
        template = get_template_for_service_code("HDL_MONTAGE_COMPLEX")
        assert template.base_service_min == 150
        assert template.requires_two_person
        assert "ELEKTRO" in template.default_skills


# =============================================================================
# TESTS: Objective Profiles
# =============================================================================

class TestObjectiveProfiles:
    """Test objective profile lookup."""

    def test_mediamarkt_profile(self):
        """Test MediaMarkt profile priorities."""
        profile = get_profile_for_vertical("MEDIAMARKT")
        assert profile.name == "MEDIAMARKT_DELIVERY"
        assert profile.distance_cost_per_km == 100  # High for delivery
        assert profile.slack_bonus == 10  # Low for delivery

    def test_hdl_profile(self):
        """Test HDL profile priorities."""
        profile = get_profile_for_vertical("HDL_PLUS")
        assert profile.name == "HDL_MONTAGE"
        assert profile.time_window_penalty == 500_000  # Very high
        assert profile.slack_bonus == 1_000  # High for montage


# =============================================================================
# TESTS: Travel Time Provider
# =============================================================================

class TestTravelTimeProvider:
    """Test travel time provider."""

    def test_mock_provider(self):
        """Test mock provider returns reasonable values."""
        provider = MockTravelTimeProvider()

        result = provider.get_travel_time((52.52, 13.40), (52.53, 13.41))
        assert result.duration_seconds > 0
        assert result.distance_meters > 0

    def test_static_matrix_config(self):
        """Test static matrix provider configuration."""
        config = StaticMatrixConfig(
            use_haversine_fallback=True,
            average_speed_kmh=30.0
        )
        provider = StaticMatrixProvider(config)

        # Without loading data, should use Haversine fallback
        result = provider.get_travel_time((52.52, 13.40), (52.53, 13.41))
        assert result.duration_seconds > 0

    def test_matrix_generation(self):
        """Test matrix generation."""
        provider = MockTravelTimeProvider()
        locations = [
            (52.52, 13.40),
            (52.53, 13.41),
            (52.54, 13.42)
        ]

        matrix = provider.get_matrix(locations)
        assert matrix.size == 3
        assert len(matrix.time_matrix) == 3
        assert len(matrix.distance_matrix) == 3

        # Diagonal should be zero
        for i in range(3):
            assert matrix.time_matrix[i][i] == 0
            assert matrix.distance_matrix[i][i] == 0


# =============================================================================
# TESTS: Data Model
# =============================================================================

class TestSolverDataModel:
    """Test solver data model construction."""

    def test_data_model_build(self):
        """Test data model can be built."""
        from packs.routing.services.solver.data_model import SolverDataModel

        now = datetime.now()
        provider = MockTravelTimeProvider()

        depot = create_test_depot("D1", 52.52, 13.405)
        stop = create_test_stop(
            "S1", 52.53, 13.41,
            tw_start=now,
            tw_end=now + timedelta(hours=2)
        )
        vehicle = create_test_vehicle(
            "V1", "D1",
            shift_start=now,
            shift_end=now + timedelta(hours=8)
        )

        data = SolverDataModel(
            stops=[stop],
            vehicles=[vehicle],
            depots=[depot],
            travel_time_provider=provider,
            reference_time=now
        )

        data.build()

        assert data.num_nodes == 2  # 1 depot + 1 stop
        assert data.num_vehicles == 1
        assert len(data.vehicle_starts) == 1
        assert len(data.vehicle_ends) == 1

    def test_multi_depot_nodes(self):
        """Test multi-depot node mapping (P0-1)."""
        from packs.routing.services.solver.data_model import SolverDataModel

        now = datetime.now()
        provider = MockTravelTimeProvider()

        depot1 = create_test_depot("D1", 52.52, 13.40)
        depot2 = create_test_depot("D2", 52.54, 13.42)

        stop = create_test_stop(
            "S1", 52.53, 13.41,
            tw_start=now,
            tw_end=now + timedelta(hours=2)
        )

        # Vehicle starts at D1, ends at D2
        vehicle = Vehicle(
            id="V1",
            tenant_id=1,
            scenario_id="test",
            team_size=1,
            skills=[],
            shift_start_at=now,
            shift_end_at=now + timedelta(hours=8),
            start_depot_id="D1",
            end_depot_id="D2"
        )

        data = SolverDataModel(
            stops=[stop],
            vehicles=[vehicle],
            depots=[depot1, depot2],
            travel_time_provider=provider,
            reference_time=now
        )

        data.build()

        # Check node mapping
        assert data.num_depot_nodes == 2
        assert data.num_nodes == 3  # 2 depots + 1 stop

        # Check vehicle start/end nodes are different
        assert data.vehicle_starts[0] == 0  # D1 is first
        assert data.vehicle_ends[0] == 1    # D2 is second


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
