# =============================================================================
# SOLVEREIGN Routing Pack - TW Validator Tests
# =============================================================================
# Tests for time window forward simulation and violation detection.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_tw_validator.py -v
# =============================================================================

import pytest
from datetime import datetime, timedelta

from backend_py.packs.routing.services.finalize.tw_validator import (
    TWValidator,
    TWValidationResult,
    TWViolation,
    RouteSchedule,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def validator() -> TWValidator:
    """Create TW validator with default service time."""
    return TWValidator(default_service_time=300)


@pytest.fixture
def base_time() -> datetime:
    """Base time for test schedules."""
    return datetime(2026, 1, 7, 8, 0, 0)


@pytest.fixture
def sample_route(base_time) -> RouteSchedule:
    """Sample route for testing."""
    return RouteSchedule(
        route_id='route_1',
        vehicle_id='vehicle_1',
        departure_time=base_time,
        stops=['A', 'B', 'C'],
        time_windows={
            'A': (base_time + timedelta(minutes=10), base_time + timedelta(minutes=30)),
            'B': (base_time + timedelta(minutes=30), base_time + timedelta(minutes=60)),
            'C': (base_time + timedelta(minutes=60), base_time + timedelta(minutes=90)),
        },
        service_times={'A': 300, 'B': 300, 'C': 300},
    )


# =============================================================================
# TW VIOLATION TESTS
# =============================================================================

class TestTWViolation:
    """Tests for TWViolation dataclass."""

    def test_violation_basic(self, base_time):
        """Test basic violation creation."""
        violation = TWViolation(
            stop_id='A',
            vehicle_id='V1',
            route_position=0,
            arrival_at=base_time + timedelta(minutes=35),
            tw_start=base_time + timedelta(minutes=10),
            tw_end=base_time + timedelta(minutes=30),
            violation_seconds=300,
        )

        assert violation.stop_id == 'A'
        assert violation.violation_seconds == 300
        assert violation.violation_minutes == 5.0

    def test_violation_is_severe(self, base_time):
        """Test severe violation detection (>15 min)."""
        # Not severe (5 min late)
        v1 = TWViolation(
            stop_id='A',
            vehicle_id='V1',
            route_position=0,
            arrival_at=base_time,
            tw_start=base_time,
            tw_end=base_time,
            violation_seconds=300,
        )
        assert v1.is_severe is False

        # Severe (20 min late)
        v2 = TWViolation(
            stop_id='A',
            vehicle_id='V1',
            route_position=0,
            arrival_at=base_time,
            tw_start=base_time,
            tw_end=base_time,
            violation_seconds=1200,
        )
        assert v2.is_severe is True

    def test_violation_to_dict(self, base_time):
        """Test serialization."""
        violation = TWViolation(
            stop_id='A',
            vehicle_id='V1',
            route_position=0,
            arrival_at=base_time + timedelta(minutes=35),
            tw_start=base_time + timedelta(minutes=10),
            tw_end=base_time + timedelta(minutes=30),
            violation_seconds=300,
        )

        data = violation.to_dict()

        assert data['stop_id'] == 'A'
        assert data['violation_seconds'] == 300
        assert data['violation_minutes'] == 5.0
        assert data['is_severe'] is False


# =============================================================================
# TW VALIDATION RESULT TESTS
# =============================================================================

class TestTWValidationResult:
    """Tests for TWValidationResult dataclass."""

    def test_result_properties(self):
        """Test result properties."""
        result = TWValidationResult(
            plan_id='plan_1',
            validated_at=datetime.now(),
            total_stops=10,
            total_routes=2,
            routes_validated=2,
            violations_count=2,
            severe_violations_count=1,
        )

        assert result.has_violations is True
        assert result.has_severe_violations is True
        assert result.violation_rate == 0.2

    def test_result_no_violations(self):
        """Test result with no violations."""
        result = TWValidationResult(
            plan_id='plan_1',
            validated_at=datetime.now(),
            total_stops=10,
            total_routes=2,
            routes_validated=2,
            violations_count=0,
            severe_violations_count=0,
        )

        assert result.has_violations is False
        assert result.has_severe_violations is False
        assert result.violation_rate == 0.0

    def test_result_to_dict(self):
        """Test serialization."""
        result = TWValidationResult(
            plan_id='plan_1',
            validated_at=datetime.now(),
            total_stops=10,
            total_routes=2,
            routes_validated=2,
            violations_count=2,
            severe_violations_count=1,
        )

        data = result.to_dict()

        assert data['plan_id'] == 'plan_1'
        assert data['statistics']['violations_count'] == 2


# =============================================================================
# TW VALIDATOR TESTS
# =============================================================================

class TestTWValidator:
    """Tests for TWValidator class."""

    def test_validate_no_violations(self, validator, base_time):
        """Test validation with no TW violations."""
        route = RouteSchedule(
            route_id='route_1',
            vehicle_id='V1',
            departure_time=base_time,
            stops=['A', 'B'],
            time_windows={
                'A': (base_time, base_time + timedelta(hours=2)),
                'B': (base_time, base_time + timedelta(hours=3)),
            },
            service_times={'A': 300, 'B': 300},
        )

        travel_times = {'A': {'B': 600}}  # 10 min travel

        result = validator.validate('plan_1', [route], travel_times)

        assert result.violations_count == 0
        assert not result.has_violations

    def test_validate_with_violation(self, validator, base_time):
        """Test validation detecting TW violation."""
        route = RouteSchedule(
            route_id='route_1',
            vehicle_id='V1',
            departure_time=base_time,
            stops=['A', 'B'],
            time_windows={
                'A': (base_time, base_time + timedelta(minutes=5)),  # Very tight window
                'B': (base_time, base_time + timedelta(hours=3)),
            },
            service_times={'A': 300, 'B': 300},
        )

        travel_times = {'A': {'B': 600}}  # 10 min travel

        result = validator.validate('plan_1', [route], travel_times)

        # Stop A arrival is base_time, which is within window
        # But stop B depends on travel time
        assert result.total_stops == 2

    def test_validate_late_arrival(self, validator, base_time):
        """Test detection of late arrival."""
        route = RouteSchedule(
            route_id='route_1',
            vehicle_id='V1',
            departure_time=base_time,
            stops=['A', 'B'],
            time_windows={
                'A': (base_time, base_time + timedelta(hours=1)),
                # B window ends before we can arrive (travel=1h, TW ends at 30min)
                'B': (base_time, base_time + timedelta(minutes=30)),
            },
            service_times={'A': 300, 'B': 300},
        )

        travel_times = {'A': {'B': 3600}}  # 1 hour travel

        result = validator.validate('plan_1', [route], travel_times)

        # Should have violation at B
        assert result.violations_count == 1
        assert result.violations[0].stop_id == 'B'

    def test_validate_multiple_routes(self, validator, base_time):
        """Test validation of multiple routes."""
        routes = [
            RouteSchedule(
                route_id='route_1',
                vehicle_id='V1',
                departure_time=base_time,
                stops=['A'],
                time_windows={'A': (base_time, base_time + timedelta(hours=1))},
                service_times={'A': 300},
            ),
            RouteSchedule(
                route_id='route_2',
                vehicle_id='V2',
                departure_time=base_time,
                stops=['B'],
                time_windows={'B': (base_time, base_time + timedelta(hours=1))},
                service_times={'B': 300},
            ),
        ]

        result = validator.validate('plan_1', routes, {})

        assert result.total_routes == 2
        assert result.routes_validated == 2
        assert result.violations_count == 0

    def test_validate_empty_route(self, validator):
        """Test validation of empty route."""
        route = RouteSchedule(
            route_id='route_1',
            vehicle_id='V1',
            departure_time=datetime.now(),
            stops=[],
            time_windows={},
            service_times={},
        )

        result = validator.validate('plan_1', [route], {})

        assert result.total_stops == 0
        assert result.violations_count == 0

    def test_validate_consecutive_interface(self, validator, base_time):
        """Test consecutive times interface."""
        result = validator.validate_consecutive(
            plan_id='plan_1',
            route_id='route_1',
            vehicle_id='V1',
            departure_time=base_time,
            stop_ids=['A', 'B', 'C'],
            osrm_leg_times=[600, 600],  # 10 min each
            time_windows={
                'A': (base_time, base_time + timedelta(hours=1)),
                'B': (base_time, base_time + timedelta(hours=1)),
                'C': (base_time, base_time + timedelta(hours=1)),
            },
        )

        assert result.total_stops == 3
        assert result.violations_count == 0

    def test_validate_wait_for_tw_start(self, validator, base_time):
        """Test waiting for TW start (arrive early, wait)."""
        route = RouteSchedule(
            route_id='route_1',
            vehicle_id='V1',
            departure_time=base_time,
            stops=['A', 'B'],
            time_windows={
                # A opens at +30min, vehicle arrives earlier
                'A': (base_time + timedelta(minutes=30), base_time + timedelta(hours=1)),
                # B should still be reachable since we wait at A
                'B': (base_time + timedelta(hours=1), base_time + timedelta(hours=2)),
            },
            service_times={'A': 300, 'B': 300},  # 5 min each
        )

        travel_times = {'A': {'B': 1200}}  # 20 min travel

        result = validator.validate('plan_1', [route], travel_times)

        # Timeline:
        # - Arrive A at base_time (early)
        # - Wait until TW start: base_time + 30min
        # - Service A: 5min → depart A at base_time + 35min
        # - Travel to B: 20min → arrive B at base_time + 55min
        # - B window is 1h-2h → No violation
        assert result.violations_count == 0

    def test_violation_tracks_route(self, validator, base_time):
        """Test that routes with violations are tracked."""
        route = RouteSchedule(
            route_id='route_with_issue',
            vehicle_id='V1',
            departure_time=base_time,
            stops=['A', 'B'],
            time_windows={
                'A': (base_time, base_time + timedelta(hours=1)),
                'B': (base_time, base_time + timedelta(minutes=10)),  # Too tight
            },
            service_times={'A': 300, 'B': 300},
        )

        travel_times = {'A': {'B': 3600}}  # 1 hour travel

        result = validator.validate('plan_1', [route], travel_times)

        assert 'route_with_issue' in result.routes_with_violations
