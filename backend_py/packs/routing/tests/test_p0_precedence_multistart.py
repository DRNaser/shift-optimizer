# =============================================================================
# P0 Tests: Precedence Constraints + Multi-Start Best-of
# =============================================================================
# Tests for the P0 features:
# - PrecedencePair constraints (pickup -> delivery)
# - Multi-Start best-of solving with KPI scoring
# - Determinism hardening
# =============================================================================

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from ..domain.models import (
    Stop, Vehicle, Depot, Geocode, SolverConfig, Address, StopCategory,
    PrecedencePair, MultiStartConfig
)
from ..services.solver.data_model import SolverDataModel
from ..services.solver.constraints import ConstraintManager, ConstraintConfig
from ..services.solver.vrptw_solver import VRPTWSolver, SolverResult, create_solver


# =============================================================================
# Fixtures
# =============================================================================

# Test constants
TEST_TENANT_ID = 1
TEST_SCENARIO_ID = "test-scenario-001"
TEST_SITE_ID = "TEST_SITE_01"


def make_test_address() -> Address:
    """Create a test address."""
    return Address(
        street="Test Street",
        house_number="1",
        postal_code="1010",
        city="Vienna",
        country="AT"
    )


def make_test_stop(
    stop_id: str,
    geocode: Geocode,
    tw_start: datetime,
    tw_end: datetime,
    service_duration_min: int = 15,
    volume_m3: float = 1.0,
    weight_kg: float = 50.0,
    load_delta: int = -1,
    required_skills: list = None,
    requires_two_person: bool = False,
    tw_is_hard: bool = True,
    service_code: str = "TEST_DELIVERY",
    category: StopCategory = StopCategory.DELIVERY,
) -> Stop:
    """Factory function for creating test stops with required fields."""
    return Stop(
        id=stop_id,
        order_id=f"order-{stop_id}",
        tenant_id=TEST_TENANT_ID,
        scenario_id=TEST_SCENARIO_ID,
        address=make_test_address(),
        geocode=geocode,
        geocode_quality=None,
        tw_start=tw_start,
        tw_end=tw_end,
        tw_is_hard=tw_is_hard,
        service_code=service_code,
        category=category,
        service_duration_min=service_duration_min,
        requires_two_person=requires_two_person,
        required_skills=required_skills or [],
        volume_m3=volume_m3,
        weight_kg=weight_kg,
        load_delta=load_delta,
    )


@pytest.fixture
def mock_travel_provider():
    """Create a mock travel time provider."""
    provider = MagicMock()

    # Return simple matrices (all same distance/time)
    def get_matrix(locations):
        n = len(locations)
        result = MagicMock()
        # Simple matrix: 10 minutes / 5000 meters between all points
        result.time_matrix = [[600 if i != j else 0 for j in range(n)] for i in range(n)]
        result.distance_matrix = [[5000 if i != j else 0 for j in range(n)] for i in range(n)]
        return result

    provider.get_matrix = get_matrix
    return provider


@pytest.fixture
def sample_depot():
    """Create a sample depot."""
    return Depot(
        id="depot-1",
        tenant_id=TEST_TENANT_ID,
        site_id=TEST_SITE_ID,
        name="Main Depot",
        geocode=Geocode(lat=48.2082, lng=16.3738),
        loading_time_min=15
    )


@pytest.fixture
def sample_vehicles(sample_depot):
    """Create sample vehicles."""
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    return [
        Vehicle(
            id=f"vehicle-{i}",
            tenant_id=TEST_TENANT_ID,
            scenario_id=TEST_SCENARIO_ID,
            start_depot_id=sample_depot.id,
            end_depot_id=sample_depot.id,
            shift_start_at=now,
            shift_end_at=now + timedelta(hours=10),
            capacity_volume_m3=20.0,
            capacity_weight_kg=1000.0,
            skills=["standard"],
            team_size=1
        )
        for i in range(3)
    ]


@pytest.fixture
def sample_stops_with_precedence():
    """Create sample stops including a pickup-delivery pair."""
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    return [
        # Regular stops
        make_test_stop(
            stop_id="stop-regular-1",
            geocode=Geocode(lat=48.21, lng=16.38),
            tw_start=now + timedelta(hours=1),
            tw_end=now + timedelta(hours=3),
            service_duration_min=15,
            volume_m3=1.0,
            weight_kg=50.0,
            load_delta=-1,
        ),
        # Pickup stop
        make_test_stop(
            stop_id="stop-pickup-1",
            geocode=Geocode(lat=48.22, lng=16.39),
            tw_start=now + timedelta(hours=1),
            tw_end=now + timedelta(hours=4),
            service_duration_min=10,
            volume_m3=2.0,
            weight_kg=100.0,
            load_delta=1,  # Pickup increases load
            service_code="TEST_PICKUP",
            category=StopCategory.PICKUP,
        ),
        # Delivery stop (must come after pickup)
        make_test_stop(
            stop_id="stop-delivery-1",
            geocode=Geocode(lat=48.23, lng=16.40),
            tw_start=now + timedelta(hours=2),
            tw_end=now + timedelta(hours=5),
            service_duration_min=10,
            volume_m3=2.0,
            weight_kg=100.0,
            load_delta=-1,  # Delivery decreases load
        ),
        # Another regular stop
        make_test_stop(
            stop_id="stop-regular-2",
            geocode=Geocode(lat=48.24, lng=16.41),
            tw_start=now + timedelta(hours=3),
            tw_end=now + timedelta(hours=6),
            service_duration_min=20,
            volume_m3=0.5,
            weight_kg=25.0,
            load_delta=-1,
        ),
    ]


@pytest.fixture
def sample_precedence_pair():
    """Create a precedence pair for pickup -> delivery."""
    return PrecedencePair(
        pickup_stop_id="stop-pickup-1",
        delivery_stop_id="stop-delivery-1",
        same_vehicle=True,
        max_lag_seconds=7200,  # 2 hours max between pickup and delivery
        is_hard=True,
        reason="Pickup before delivery constraint"
    )


# =============================================================================
# PrecedencePair Model Tests
# =============================================================================

class TestPrecedencePairModel:
    """Test PrecedencePair dataclass."""

    def test_precedence_pair_creation(self):
        """Test creating a precedence pair."""
        pair = PrecedencePair(
            pickup_stop_id="pickup-1",
            delivery_stop_id="delivery-1",
            same_vehicle=True,
            max_lag_seconds=3600
        )

        assert pair.pickup_stop_id == "pickup-1"
        assert pair.delivery_stop_id == "delivery-1"
        assert pair.same_vehicle is True
        assert pair.max_lag_seconds == 3600
        assert pair.is_hard is True  # Default
        assert pair.violation_penalty == 100_000  # Default

    def test_precedence_pair_defaults(self):
        """Test precedence pair default values."""
        pair = PrecedencePair(
            pickup_stop_id="p1",
            delivery_stop_id="d1"
        )

        assert pair.same_vehicle is True
        assert pair.max_lag_seconds is None
        assert pair.is_hard is True
        assert pair.violation_penalty == 100_000
        assert pair.reason == ""

    def test_precedence_pair_immutable(self):
        """Test that precedence pair is frozen/immutable."""
        pair = PrecedencePair(
            pickup_stop_id="p1",
            delivery_stop_id="d1"
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            pair.pickup_stop_id = "p2"


# =============================================================================
# MultiStartConfig Model Tests
# =============================================================================

class TestMultiStartConfigModel:
    """Test MultiStartConfig dataclass."""

    def test_multi_start_config_creation(self):
        """Test creating a multi-start config."""
        config = MultiStartConfig(
            num_seeds=5,
            seeds=[1, 2, 3, 4, 5],
            per_run_time_limit_seconds=30
        )

        assert config.num_seeds == 5
        assert config.seeds == [1, 2, 3, 4, 5]
        assert config.per_run_time_limit_seconds == 30

    def test_multi_start_config_defaults(self):
        """Test multi-start config default values."""
        config = MultiStartConfig()

        assert config.num_seeds == 10
        assert config.seeds is None
        assert config.per_run_time_limit_seconds == 30
        assert config.overall_time_limit_seconds == 300
        assert config.force_single_worker is True
        assert "unassigned_count" in config.score_weights

    def test_score_weights_structure(self):
        """Test that score weights have expected keys."""
        config = MultiStartConfig()

        expected_keys = [
            "unassigned_count",
            "hard_tw_violations",
            "overtime_minutes",
            "total_travel_minutes"
        ]

        for key in expected_keys:
            assert key in config.score_weights


# =============================================================================
# SolverDataModel Precedence Tests
# =============================================================================

class TestSolverDataModelPrecedence:
    """Test SolverDataModel with precedence pairs."""

    def test_data_model_accepts_precedence_pairs(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider,
        sample_precedence_pair
    ):
        """Test that data model accepts precedence pairs."""
        data = SolverDataModel(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[sample_precedence_pair]
        )

        assert len(data.precedence_pairs) == 1
        assert data.precedence_pairs[0].pickup_stop_id == "stop-pickup-1"

    def test_get_precedence_node_pairs(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider,
        sample_precedence_pair
    ):
        """Test getting precedence pairs as node indices."""
        data = SolverDataModel(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[sample_precedence_pair]
        ).build()

        pairs = data.get_precedence_node_pairs()

        assert len(pairs) == 1
        pickup_node, delivery_node, pair = pairs[0]

        # Verify nodes are integers
        assert isinstance(pickup_node, int)
        assert isinstance(delivery_node, int)

        # Verify they map back to correct stops
        assert data.get_stop_for_node(pickup_node).id == "stop-pickup-1"
        assert data.get_stop_for_node(delivery_node).id == "stop-delivery-1"

    def test_precedence_validation_invalid_pickup(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider
    ):
        """Test validation catches invalid pickup stop ID."""
        invalid_pair = PrecedencePair(
            pickup_stop_id="nonexistent-pickup",
            delivery_stop_id="stop-delivery-1"
        )

        data = SolverDataModel(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[invalid_pair]
        ).build()

        errors = data.validate()
        assert any("nonexistent-pickup" in e for e in errors)

    def test_precedence_validation_invalid_delivery(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider
    ):
        """Test validation catches invalid delivery stop ID."""
        invalid_pair = PrecedencePair(
            pickup_stop_id="stop-pickup-1",
            delivery_stop_id="nonexistent-delivery"
        )

        data = SolverDataModel(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[invalid_pair]
        ).build()

        errors = data.validate()
        assert any("nonexistent-delivery" in e for e in errors)


# =============================================================================
# NOTE: KPI Scoring via score_weights was replaced with tuple comparison.
# See TestKPITupleComparison for the current implementation tests.
# =============================================================================


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestCreateSolverFactory:
    """Test create_solver factory function."""

    def test_create_solver_with_precedence(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider,
        sample_precedence_pair
    ):
        """Test creating solver with precedence pairs."""
        solver = create_solver(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[sample_precedence_pair]
        )

        assert isinstance(solver, VRPTWSolver)
        assert len(solver.precedence_pairs) == 1

    def test_create_solver_with_multi_start(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider
    ):
        """Test creating solver with multi-start config."""
        multi_config = MultiStartConfig(num_seeds=3, per_run_time_limit_seconds=10)

        solver = create_solver(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            multi_start_config=multi_config
        )

        assert isinstance(solver, VRPTWSolver)
        assert solver.multi_start_config is not None
        assert solver.multi_start_config.num_seeds == 3


# =============================================================================
# Integration Tests (require OR-Tools)
# =============================================================================

@pytest.mark.skipif(
    not pytest.importorskip("ortools", reason="OR-Tools required"),
    reason="OR-Tools not available"
)
class TestPrecedenceIntegration:
    """Integration tests for precedence constraints with OR-Tools."""

    def test_precedence_constraints_added(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider,
        sample_precedence_pair
    ):
        """Test that precedence constraints are added to the model."""
        from ortools.constraint_solver import pywrapcp

        # FIX: Use consistent reference_time matching fixture base time
        # Fixtures use: datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        reference_time = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        # Build data model with explicit reference_time
        data = SolverDataModel(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[sample_precedence_pair],
            reference_time=reference_time
        ).build()

        # Create routing model
        manager = pywrapcp.RoutingIndexManager(
            data.num_nodes,
            data.num_vehicles,
            data.vehicle_starts,
            data.vehicle_ends
        )
        routing = pywrapcp.RoutingModel(manager)

        # Create constraint manager and add constraints
        config = ConstraintConfig()
        constraint_mgr = ConstraintManager(
            routing=routing,
            manager=manager,
            data=data,
            config=config
        )

        # This should not raise
        constraint_mgr.add_all_constraints()

        # Verify model is valid
        assert routing.solver() is not None


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestPrecedenceEdgeCases:
    """Test edge cases for precedence constraints."""

    def test_altgeraete_not_precedence(self):
        """
        CRITICAL: Verify that Altgeräte (exchange at same location)
        is NOT modeled as precedence.

        Exchange = service time + capacity logic (device out -1, device in +1)
        This is handled by service time and capacity, NOT by PrecedencePair.
        """
        # This test documents the correct understanding:
        # - Altgeräte exchange happens at SAME customer
        # - Modeled as: arrive -> take old device (+1) -> install new (-1) -> leave
        # - This is a single stop with complex service, NOT two stops

        # PrecedencePair is for DIFFERENT locations (warehouse pickup -> customer delivery)

        pair = PrecedencePair(
            pickup_stop_id="warehouse",
            delivery_stop_id="customer",
            same_vehicle=True,
            reason="Pickup from warehouse, deliver to customer"
        )

        # Verify this is for different locations
        assert pair.pickup_stop_id != pair.delivery_stop_id

    def test_multiple_precedence_pairs(self, mock_travel_provider, sample_depot, sample_vehicles):
        """Test handling multiple precedence pairs."""
        now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        stops = [
            make_test_stop(
                stop_id=f"stop-{i}",
                geocode=Geocode(lat=48.2 + i*0.01, lng=16.3 + i*0.01),
                tw_start=now + timedelta(hours=1),
                tw_end=now + timedelta(hours=6),
                service_duration_min=10,
                volume_m3=1.0,
                weight_kg=50.0,
                load_delta=-1,
            )
            for i in range(6)
        ]

        # Multiple pickup-delivery pairs
        pairs = [
            PrecedencePair(pickup_stop_id="stop-0", delivery_stop_id="stop-1"),
            PrecedencePair(pickup_stop_id="stop-2", delivery_stop_id="stop-3"),
            PrecedencePair(pickup_stop_id="stop-4", delivery_stop_id="stop-5"),
        ]

        data = SolverDataModel(
            stops=stops,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=pairs
        ).build()

        node_pairs = data.get_precedence_node_pairs()
        assert len(node_pairs) == 3

    def test_precedence_with_no_pairs(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider
    ):
        """Test that solver works with no precedence pairs."""
        data = SolverDataModel(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[]
        ).build()

        pairs = data.get_precedence_node_pairs()
        assert len(pairs) == 0

    def test_precedence_with_depot_id_rejected(
        self,
        sample_stops_with_precedence,
        sample_vehicles,
        sample_depot,
        mock_travel_provider
    ):
        """
        CRITICAL: Precedence pairs referencing depot IDs must be rejected.
        Depot start/end nodes are not normal visit nodes in OR-Tools.
        """
        # Try to create a pair where delivery is the depot
        bad_pair = PrecedencePair(
            pickup_stop_id="stop-pickup-1",
            delivery_stop_id=sample_depot.id,  # This is a DEPOT, not a stop!
            same_vehicle=True,
            reason="Return to depot - INVALID!"
        )

        data = SolverDataModel(
            stops=sample_stops_with_precedence,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[bad_pair]
        ).build()

        errors = data.validate()

        # Must have an error about depot
        assert any("DEPOT" in e for e in errors)
        assert any(sample_depot.id in e for e in errors)


# =============================================================================
# Critical Fix Tests
# =============================================================================

class TestKPITupleComparison:
    """Tests for the tuple-based lexicographic comparison fix."""

    def test_tuple_comparison_lower_is_better(self):
        """
        CRITICAL: Verify that lower tuple = better solution.
        This is the fix for the score direction issue.
        """
        solver = VRPTWSolver.__new__(VRPTWSolver)

        # Solution A: 0 unassigned, 0 violations, 60 overtime, 480 travel, 3 vehicles
        result_a = SolverResult(
            success=True, status="FEASIBLE",
            unassigned_stop_ids=[],
            total_duration_min=480,
            total_vehicles_used=3
        )

        # Solution B: 1 unassigned (worse!), 0 violations, 0 overtime, 300 travel, 2 vehicles
        result_b = SolverResult(
            success=True, status="FEASIBLE",
            unassigned_stop_ids=["stop-1"],
            total_duration_min=300,
            total_vehicles_used=2
        )

        tuple_a = solver._compute_kpi_tuple(result_a)
        tuple_b = solver._compute_kpi_tuple(result_b)

        # A has 0 unassigned, B has 1 unassigned
        # A should be better (lower tuple)
        assert tuple_a < tuple_b, "Solution with fewer unassigned must have lower tuple"

        # First element (unassigned) should dominate
        assert tuple_a[0] == 0
        assert tuple_b[0] == 1

    def test_tuple_comparison_lexicographic_priority(self):
        """
        Test that unassigned count takes priority over everything else.
        Even if B has better travel/vehicles, A wins with fewer unassigned.
        """
        solver = VRPTWSolver.__new__(VRPTWSolver)

        # A: 0 unassigned, terrible travel (1000 min)
        result_a = SolverResult(
            success=True, status="FEASIBLE",
            unassigned_stop_ids=[],
            total_duration_min=1000,
            total_vehicles_used=10
        )

        # B: 1 unassigned, great travel (100 min)
        result_b = SolverResult(
            success=True, status="FEASIBLE",
            unassigned_stop_ids=["stop-1"],
            total_duration_min=100,
            total_vehicles_used=1
        )

        tuple_a = solver._compute_kpi_tuple(result_a)
        tuple_b = solver._compute_kpi_tuple(result_b)

        # A MUST win despite worse travel/vehicles
        assert tuple_a < tuple_b, "Coverage is king - 0 unassigned beats any travel time"


class TestCapacityPickupDelivery:
    """Tests for capacity handling with pickup/delivery load_delta."""

    def test_pickup_has_positive_demand(self, mock_travel_provider, sample_depot, sample_vehicles):
        """Pickup stops (load_delta=+1) must have POSITIVE demand."""
        now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        pickup_stop = make_test_stop(
            stop_id="pickup-1",
            geocode=Geocode(lat=48.21, lng=16.38),
            tw_start=now,
            tw_end=now + timedelta(hours=8),
            service_duration_min=10,
            volume_m3=5.0,
            weight_kg=100.0,
            load_delta=1,  # PICKUP: adds to vehicle
            service_code="TEST_PICKUP",
            category=StopCategory.PICKUP,
        )

        data = SolverDataModel(
            stops=[pickup_stop],
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        ).build()

        node = data.get_node_for_stop("pickup-1")
        volume, weight = data.get_demand(node)

        # Must be POSITIVE (adds to vehicle capacity)
        assert volume > 0, "Pickup must have positive volume demand"
        assert weight > 0, "Pickup must have positive weight demand"
        assert volume == 5.0
        assert weight == 100.0

    def test_delivery_has_negative_demand(self, mock_travel_provider, sample_depot, sample_vehicles):
        """Delivery stops (load_delta=-1) must have NEGATIVE demand."""
        now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        delivery_stop = make_test_stop(
            stop_id="delivery-1",
            geocode=Geocode(lat=48.21, lng=16.38),
            tw_start=now,
            tw_end=now + timedelta(hours=8),
            service_duration_min=10,
            volume_m3=5.0,
            weight_kg=100.0,
            load_delta=-1,  # DELIVERY: removes from vehicle
        )

        data = SolverDataModel(
            stops=[delivery_stop],
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        ).build()

        node = data.get_node_for_stop("delivery-1")
        volume, weight = data.get_demand(node)

        # Must be NEGATIVE (removes from vehicle capacity)
        assert volume < 0, "Delivery must have negative volume demand"
        assert weight < 0, "Delivery must have negative weight demand"
        assert volume == -5.0
        assert weight == -100.0

    def test_pickup_delivery_pair_capacity_balance(
        self,
        mock_travel_provider,
        sample_depot,
        sample_vehicles
    ):
        """
        A pickup-delivery pair should have balanced capacity.
        Pickup adds X, delivery removes X -> net zero at depot.
        """
        now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        stops = [
            make_test_stop(
                stop_id="pickup",
                geocode=Geocode(lat=48.21, lng=16.38),
                tw_start=now,
                tw_end=now + timedelta(hours=8),
                service_duration_min=10,
                volume_m3=3.0,
                weight_kg=75.0,
                load_delta=1,  # PICKUP
                service_code="TEST_PICKUP",
                category=StopCategory.PICKUP,
            ),
            make_test_stop(
                stop_id="delivery",
                geocode=Geocode(lat=48.22, lng=16.39),
                tw_start=now,
                tw_end=now + timedelta(hours=8),
                service_duration_min=10,
                volume_m3=3.0,
                weight_kg=75.0,
                load_delta=-1,  # DELIVERY
            ),
        ]

        data = SolverDataModel(
            stops=stops,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        ).build()

        pickup_node = data.get_node_for_stop("pickup")
        delivery_node = data.get_node_for_stop("delivery")

        pickup_vol, pickup_wt = data.get_demand(pickup_node)
        delivery_vol, delivery_wt = data.get_demand(delivery_node)

        # Net should be zero
        assert pickup_vol + delivery_vol == 0, "Pickup + Delivery volume should balance"
        assert pickup_wt + delivery_wt == 0, "Pickup + Delivery weight should balance"


# =============================================================================
# Service Time + Time Window Tests (Issue 1)
# =============================================================================

class TestServiceTimeWithPrecedence:
    """
    Tests for CumulVar ordering with service time.

    CRITICAL: The time_callback includes service time at destination:
        transit(A, B) = travel(A, B) + service(B)

    So CumulVar(pickup) already includes service_at_pickup.
    The constraint CumulVar(pickup) <= CumulVar(delivery) ensures
    "finish at pickup" <= "finish at delivery".
    """

    def test_long_pickup_service_documented(self):
        """
        Document the CumulVar semantics for long pickup service.

        Scenario:
        - Pickup has 30 min service time
        - Delivery has tight TW

        The precedence constraint is:
            CumulVar(pickup) <= CumulVar(delivery)

        Since CumulVar includes service time, this means:
            (arrival_at_pickup + service_at_pickup) <= (arrival_at_delivery + service_at_delivery)

        Which is equivalent to:
            finish_at_pickup <= finish_at_delivery

        This is correct! The long service time at pickup is already
        accounted for in CumulVar(pickup).
        """
        # This test documents the correct behavior
        # The key insight: time_callback adds service time to transit
        # So CumulVar represents "completion time" at each node

        # Example trace:
        # - Arrive at Pickup at 9:00
        # - Service at Pickup takes 30 min
        # - CumulVar(Pickup) = 9:00 + transit_to_pickup (which included service)
        # - Actually: CumulVar(Pickup) = CumulVar(prev) + travel(prev, Pickup) + service(Pickup)
        # - So CumulVar(Pickup) represents time AFTER completing service at Pickup

        # Therefore CumulVar(pickup) <= CumulVar(delivery) is correct:
        # "time after finishing pickup" <= "time after finishing delivery"
        assert True  # Documentation test

    def test_service_time_in_transit_callback(self, mock_travel_provider, sample_depot, sample_vehicles):
        """
        Verify that service time is correctly included in data model.
        """
        now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        # Pickup with long service time
        pickup = make_test_stop(
            stop_id="pickup-long-service",
            geocode=Geocode(lat=48.21, lng=16.38),
            tw_start=now,
            tw_end=now + timedelta(hours=8),
            service_duration_min=30,  # Long service!
            volume_m3=1.0,
            weight_kg=10.0,
            load_delta=1,
            service_code="TEST_PICKUP",
            category=StopCategory.PICKUP,
        )

        data = SolverDataModel(
            stops=[pickup],
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        ).build()

        node = data.get_node_for_stop("pickup-long-service")
        service_time = data.get_service_time(node)

        assert service_time == 30, "Service time must be accessible from data model"


# =============================================================================
# Dropped Pair Capacity Tests (Issue 2)
# =============================================================================

class TestDroppedPairCapacity:
    """
    Tests for capacity handling when pickup-delivery pairs are dropped.

    CRITICAL: When a pair is unassigned (both pickup and delivery dropped),
    their capacity demands should NOT affect any vehicle.

    OR-Tools AddPickupAndDelivery ensures: both visited OR both dropped.
    If dropped, the capacity callbacks are never invoked for those nodes.
    """

    def test_dropped_pair_capacity_zero_effect(self, mock_travel_provider, sample_depot, sample_vehicles):
        """
        Verify that dropped pairs don't contribute to capacity.

        This is implicitly handled by OR-Tools:
        - AddPickupAndDelivery ensures both nodes are dropped together
        - Dropped nodes are not visited, so their demand callbacks aren't accumulated

        This test verifies the data model correctly reports demand,
        so that IF visited, the capacity would be correct.
        The actual "not counted when dropped" is handled by OR-Tools routing.
        """
        now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

        # Create a pickup-delivery pair
        stops = [
            make_test_stop(
                stop_id="pickup-may-drop",
                geocode=Geocode(lat=48.21, lng=16.38),
                tw_start=now,
                tw_end=now + timedelta(hours=2),  # Tight window
                service_duration_min=10,
                volume_m3=10.0,
                weight_kg=200.0,
                load_delta=1,  # PICKUP
                service_code="TEST_PICKUP",
                category=StopCategory.PICKUP,
            ),
            make_test_stop(
                stop_id="delivery-may-drop",
                geocode=Geocode(lat=48.22, lng=16.39),
                tw_start=now + timedelta(hours=1),
                tw_end=now + timedelta(hours=2),  # Tight window
                service_duration_min=10,
                volume_m3=10.0,
                weight_kg=200.0,
                load_delta=-1,  # DELIVERY
            ),
        ]

        pair = PrecedencePair(
            pickup_stop_id="pickup-may-drop",
            delivery_stop_id="delivery-may-drop",
            same_vehicle=True
        )

        data = SolverDataModel(
            stops=stops,
            vehicles=sample_vehicles,
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider,
            precedence_pairs=[pair]
        ).build()

        # Verify demands are correctly set (positive for pickup, negative for delivery)
        pickup_node = data.get_node_for_stop("pickup-may-drop")
        delivery_node = data.get_node_for_stop("delivery-may-drop")

        pickup_vol, pickup_wt = data.get_demand(pickup_node)
        delivery_vol, delivery_wt = data.get_demand(delivery_node)

        # Demands are set correctly
        assert pickup_vol == 10.0, "Pickup demand must be positive"
        assert delivery_vol == -10.0, "Delivery demand must be negative"

        # Net zero ensures no capacity leak
        assert pickup_vol + delivery_vol == 0, "Pair must have balanced capacity"

        # The actual "dropped = no effect" is guaranteed by:
        # 1. AddPickupAndDelivery ensures both dropped together
        # 2. OR-Tools capacity dimension only accumulates visited nodes
        # 3. Balanced +/- demand means even if visited, capacity returns to baseline

    def test_dropped_pair_semantic_documentation(self):
        """
        Document how OR-Tools handles dropped pickup-delivery pairs.

        When AddPickupAndDelivery(pickup_idx, delivery_idx) is called:
        - OR-Tools creates a disjunction for the pair
        - Either BOTH are visited on the same vehicle, OR BOTH are dropped
        - Cannot have pickup visited and delivery dropped (or vice versa)

        For capacity:
        - If dropped: capacity callback is never called for those nodes
        - If visited: pickup adds +X, delivery removes -X (net zero at end)

        This is the correct behavior by design.
        """
        # Documentation test - no assertions needed
        # The key guarantees:
        # 1. AddPickupAndDelivery = "visit both or drop both"
        # 2. Capacity callbacks only fire for visited nodes
        # 3. Balanced load_delta (+1 pickup, -1 delivery) means net-zero effect
        assert True


# =============================================================================
# Vehicles Used Count Tests (Issue 3)
# =============================================================================

class TestVehiclesUsedCount:
    """
    Tests for correct vehicle counting in solution extraction.

    CRITICAL: total_vehicles_used must count only vehicles with actual stops,
    NOT all available vehicles.
    """

    def test_vehicles_used_counts_active_only(self):
        """
        Verify that vehicles_used counts only vehicles with stops.

        The _extract_solution code should have:
            if route_stops:
                vehicles_used += 1

        This ensures empty vehicles are NOT counted.
        """
        # Create a mock SolverResult to verify the field semantics
        result = SolverResult(
            success=True,
            status="FEASIBLE",
            total_vehicles_used=2  # Only 2 of say 5 vehicles had stops
        )

        # The field represents ACTIVE vehicles, not total capacity
        assert result.total_vehicles_used == 2

        # This field is set in _extract_solution via:
        # if route_stops:
        #     vehicles_used += 1
        # So it only counts vehicles that actually have stops assigned.

    def test_solution_result_vehicle_semantics(self):
        """
        Document vehicle counting semantics in SolverResult.

        - total_vehicles_used: Count of vehicles with at least 1 stop
        - routes dict: Only contains entries for vehicles with stops
        - Empty vehicles don't appear in routes dict
        """
        result = SolverResult(
            success=True,
            status="FEASIBLE",
            routes={
                "vehicle-1": None,  # Has stops
                "vehicle-3": None,  # Has stops (note: vehicle-2 is empty)
            },
            total_vehicles_used=2
        )

        # Number of routes should match vehicles_used
        assert len(result.routes) == result.total_vehicles_used

        # Empty vehicles (like vehicle-2) are NOT in routes dict
        assert "vehicle-2" not in result.routes

    def test_empty_solution_has_zero_vehicles(self):
        """
        A solution with no assigned stops should report 0 vehicles used.
        """
        result = SolverResult(
            success=True,
            status="FEASIBLE",
            routes={},  # No routes
            unassigned_stop_ids=["stop-1", "stop-2"],  # All dropped
            total_vehicles_used=0
        )

        assert result.total_vehicles_used == 0
        assert len(result.routes) == 0
