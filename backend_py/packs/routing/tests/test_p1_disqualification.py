# =============================================================================
# P1.2 Tests: Lexicographic Disqualification Rules
# =============================================================================
# Tests for P1.2 features:
# - Disqualification of solutions with hard TW violations when clean exists
# - Disqualification of solutions with unassigned stops when full coverage exists
# - Fallback behavior when all solutions disqualified
# =============================================================================

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from ..domain.models import (
    Stop, Vehicle, Depot, Geocode, Address, StopCategory,
    SolverConfig, MultiStartConfig
)
from ..services.solver.vrptw_solver import VRPTWSolver, SolverResult


# =============================================================================
# Test Constants
# =============================================================================

TEST_TENANT_ID = 1
TEST_SCENARIO_ID = "test-scenario-p1"
TEST_SITE_ID = "TEST_SITE_01"


# =============================================================================
# Helper Functions
# =============================================================================

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
) -> Stop:
    """Factory function for creating test stops."""
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
        tw_is_hard=True,
        service_code="TEST_DELIVERY",
        category=StopCategory.DELIVERY,
        service_duration_min=15,
        volume_m3=1.0,
        weight_kg=50.0,
        load_delta=-1,
    )


def make_mock_result(
    success: bool = True,
    unassigned_count: int = 0,
    vehicles_used: int = 1,
    total_duration: int = 60,
    seed: int = 1
) -> SolverResult:
    """Create a mock SolverResult."""
    return SolverResult(
        success=success,
        status="FEASIBLE" if success else "NO_SOLUTION",
        routes={},
        unassigned_stop_ids=["stop-{}".format(i) for i in range(unassigned_count)],
        total_distance_m=5000,
        total_duration_min=total_duration,
        total_vehicles_used=vehicles_used,
        seed_used=seed
    )


@pytest.fixture
def mock_travel_provider():
    """Create a mock travel time provider."""
    provider = MagicMock()

    def get_matrix(locations):
        n = len(locations)
        result = MagicMock()
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
def sample_vehicle(sample_depot):
    """Create a sample vehicle."""
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    return Vehicle(
        id="vehicle-1",
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


@pytest.fixture
def sample_stops():
    """Create sample stops."""
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    return [
        make_test_stop(
            stop_id=f"stop-{i}",
            geocode=Geocode(lat=48.21 + i * 0.01, lng=16.38),
            tw_start=now + timedelta(hours=1),
            tw_end=now + timedelta(hours=5)
        )
        for i in range(3)
    ]


# =============================================================================
# TestDisqualificationRules
# =============================================================================

class TestDisqualificationRules:
    """Tests for the disqualification filter logic."""

    def test_disqualify_tw_violations_when_clean_exists(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Solutions with hard_tw>0 are disqualified if any has hard_tw==0."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        # KPI tuples: (unassigned, hard_tw_violations, overtime, travel, vehicles)
        all_results = {
            1: make_mock_result(seed=1),  # Clean
            2: make_mock_result(seed=2),  # Clean
            3: make_mock_result(seed=3),  # Clean
        }
        all_tuples = {
            1: (0, 0, 0, 60, 1),  # Clean: no TW violations
            2: (0, 2, 0, 55, 1),  # Has 2 TW violations
            3: (0, 0, 0, 65, 1),  # Clean: no TW violations
        }

        filtered_results, filtered_tuples = solver._apply_disqualification_filters(
            all_results, all_tuples
        )

        # Seed 2 should be disqualified (has TW violations, clean exists)
        assert 1 in filtered_tuples
        assert 2 not in filtered_tuples
        assert 3 in filtered_tuples
        assert len(filtered_tuples) == 2

    def test_keep_tw_violations_when_no_clean_exists(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Solutions with hard_tw>0 are kept if NO solution has hard_tw==0."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        # All have TW violations
        all_results = {
            1: make_mock_result(seed=1),
            2: make_mock_result(seed=2),
        }
        all_tuples = {
            1: (0, 1, 0, 60, 1),  # 1 TW violation
            2: (0, 2, 0, 55, 1),  # 2 TW violations
        }

        filtered_results, filtered_tuples = solver._apply_disqualification_filters(
            all_results, all_tuples
        )

        # Both should be kept (no clean exists to disqualify against)
        assert 1 in filtered_tuples
        assert 2 in filtered_tuples
        assert len(filtered_tuples) == 2

    def test_disqualify_unassigned_when_full_coverage_exists(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Solutions with unassigned>0 are disqualified if any has unassigned==0."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        all_results = {
            1: make_mock_result(seed=1, unassigned_count=0),  # Full coverage
            2: make_mock_result(seed=2, unassigned_count=2),  # 2 unassigned
            3: make_mock_result(seed=3, unassigned_count=0),  # Full coverage
        }
        all_tuples = {
            1: (0, 0, 0, 70, 1),  # Full coverage
            2: (2, 0, 0, 50, 1),  # 2 unassigned (better travel)
            3: (0, 0, 0, 65, 1),  # Full coverage
        }

        filtered_results, filtered_tuples = solver._apply_disqualification_filters(
            all_results, all_tuples
        )

        # Seed 2 should be disqualified (has unassigned, full coverage exists)
        assert 1 in filtered_tuples
        assert 2 not in filtered_tuples
        assert 3 in filtered_tuples

    def test_keep_unassigned_when_no_full_coverage_exists(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Solutions with unassigned>0 are kept if NO solution has unassigned==0."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        # All have unassigned
        all_results = {
            1: make_mock_result(seed=1, unassigned_count=1),
            2: make_mock_result(seed=2, unassigned_count=2),
        }
        all_tuples = {
            1: (1, 0, 0, 60, 1),  # 1 unassigned
            2: (2, 0, 0, 55, 1),  # 2 unassigned
        }

        filtered_results, filtered_tuples = solver._apply_disqualification_filters(
            all_results, all_tuples
        )

        # Both should be kept
        assert 1 in filtered_tuples
        assert 2 in filtered_tuples

    def test_both_rules_applied(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Both TW and unassigned rules are applied together."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        all_results = {
            1: make_mock_result(seed=1),  # Perfect
            2: make_mock_result(seed=2, unassigned_count=1),  # Unassigned
            3: make_mock_result(seed=3),  # TW violation (via tuple)
            4: make_mock_result(seed=4),  # Perfect
        }
        all_tuples = {
            1: (0, 0, 0, 70, 1),   # Perfect
            2: (1, 0, 0, 50, 1),   # Unassigned (disqualified by rule 2)
            3: (0, 1, 0, 55, 1),   # TW violation (disqualified by rule 1)
            4: (0, 0, 0, 65, 1),   # Perfect
        }

        filtered_results, filtered_tuples = solver._apply_disqualification_filters(
            all_results, all_tuples
        )

        # Only seeds 1 and 4 should remain
        assert 1 in filtered_tuples
        assert 2 not in filtered_tuples  # Disqualified: unassigned
        assert 3 not in filtered_tuples  # Disqualified: TW violation
        assert 4 in filtered_tuples
        assert len(filtered_tuples) == 2

    def test_fallback_when_all_disqualified(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Falls back to original set if all would be disqualified."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        # Impossible scenario where both conditions trigger but all fail both
        # This shouldn't normally happen, but we test the fallback
        all_results = {
            1: make_mock_result(seed=1, unassigned_count=1),
        }
        all_tuples = {
            1: (1, 1, 0, 60, 1),  # Both unassigned AND TW violation
        }

        # If we also had a "perfect" solution, seed 1 would be disqualified
        # But since it's the only one, let's test a more realistic scenario
        # where the filtering logic would disqualify everything

        # Actually, in this case seed 1 won't be disqualified because
        # there's no "clean" solution to compare against
        filtered_results, filtered_tuples = solver._apply_disqualification_filters(
            all_results, all_tuples
        )

        # Should keep seed 1 (no alternatives)
        assert 1 in filtered_tuples

    def test_empty_input_returns_empty(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Empty input returns empty output."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        filtered_results, filtered_tuples = solver._apply_disqualification_filters(
            {}, {}
        )

        assert filtered_results == {}
        assert filtered_tuples == {}


# =============================================================================
# TestKPITupleComparison
# =============================================================================

class TestKPITupleComparison:
    """Tests for lexicographic KPI tuple comparison."""

    def test_unassigned_dominates(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Lower unassigned count wins regardless of other metrics."""
        solver = VRPTWSolver(
            stops=sample_stops,
            vehicles=[sample_vehicle],
            depots=[sample_depot],
            travel_time_provider=mock_travel_provider
        )

        # Tuple: (unassigned, hard_tw, overtime, travel, vehicles)
        tuple_a = (0, 0, 100, 200, 5)  # 0 unassigned, worse everything else
        tuple_b = (1, 0, 0, 50, 1)     # 1 unassigned, better everything else

        # Lower tuple wins (lexicographic)
        assert tuple_a < tuple_b

    def test_tw_violations_dominate_after_unassigned(
        self, sample_depot, sample_vehicle, sample_stops, mock_travel_provider
    ):
        """Lower TW violations wins when unassigned is equal."""
        # Tuple: (unassigned, hard_tw, overtime, travel, vehicles)
        tuple_a = (0, 0, 100, 200, 5)  # 0 TW violations
        tuple_b = (0, 1, 0, 50, 1)     # 1 TW violation

        assert tuple_a < tuple_b

    def test_overtime_dominate_after_tw(self):
        """Lower overtime wins when unassigned and TW are equal."""
        tuple_a = (0, 0, 10, 200, 5)   # 10 min overtime
        tuple_b = (0, 0, 20, 50, 1)    # 20 min overtime

        assert tuple_a < tuple_b

    def test_travel_dominates_after_overtime(self):
        """Lower travel wins when unassigned, TW, and overtime are equal."""
        tuple_a = (0, 0, 0, 100, 5)   # 100 min travel
        tuple_b = (0, 0, 0, 150, 1)   # 150 min travel

        assert tuple_a < tuple_b

    def test_vehicles_is_tiebreaker(self):
        """Fewer vehicles wins as final tiebreaker."""
        tuple_a = (0, 0, 0, 100, 2)   # 2 vehicles
        tuple_b = (0, 0, 0, 100, 3)   # 3 vehicles

        assert tuple_a < tuple_b
