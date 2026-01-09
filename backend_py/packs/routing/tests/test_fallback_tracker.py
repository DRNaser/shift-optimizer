# =============================================================================
# SOLVEREIGN Routing Pack - Fallback Tracker Tests
# =============================================================================
# Tests for fallback event tracking during finalize.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_fallback_tracker.py -v
# =============================================================================

import pytest
from datetime import datetime

from backend_py.packs.routing.services.finalize.fallback_tracker import (
    FallbackTracker,
    FallbackReport,
    FallbackEvent,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def tracker() -> FallbackTracker:
    """Create fallback tracker instance."""
    return FallbackTracker(max_sample_events=5)


# =============================================================================
# FALLBACK EVENT TESTS
# =============================================================================

class TestFallbackEvent:
    """Tests for FallbackEvent dataclass."""

    def test_event_basic(self):
        """Test basic event creation."""
        event = FallbackEvent(
            from_stop_id='A',
            to_stop_id='B',
            fallback_level='HAVERSINE',
            reason='OSRM_TIMEOUT',
            occurred_at=datetime.now(),
            duration_computed=600,
            distance_computed=5000,
            request_time_ms=4500.0,
        )

        assert event.from_stop_id == 'A'
        assert event.to_stop_id == 'B'
        assert event.fallback_level == 'HAVERSINE'
        assert event.reason == 'OSRM_TIMEOUT'

    def test_event_to_dict(self):
        """Test serialization."""
        event = FallbackEvent(
            from_stop_id='A',
            to_stop_id='B',
            fallback_level='HAVERSINE',
            reason='OSRM_TIMEOUT',
            occurred_at=datetime.now(),
            duration_computed=600,
            distance_computed=5000,
            request_time_ms=4500.0,
        )

        data = event.to_dict()

        assert data['from_stop_id'] == 'A'
        assert data['fallback_level'] == 'HAVERSINE'
        assert data['request_time_ms'] == 4500.0


# =============================================================================
# FALLBACK REPORT TESTS
# =============================================================================

class TestFallbackReport:
    """Tests for FallbackReport dataclass."""

    def test_report_rates(self):
        """Test rate calculations."""
        report = FallbackReport(
            plan_id='plan_1',
            generated_at=datetime.now(),
            total_legs=100,
            fallback_count=10,
            timeout_count=5,
            error_count=3,
        )

        assert report.fallback_rate == 0.1
        assert report.timeout_rate == 0.05
        assert report.error_rate == 0.03
        assert report.has_fallbacks is True

    def test_report_no_fallbacks(self):
        """Test report with no fallbacks."""
        report = FallbackReport(
            plan_id='plan_1',
            generated_at=datetime.now(),
            total_legs=100,
            fallback_count=0,
            timeout_count=0,
            error_count=0,
        )

        assert report.fallback_rate == 0.0
        assert report.has_fallbacks is False

    def test_report_zero_legs(self):
        """Test report with zero legs (avoid division by zero)."""
        report = FallbackReport(
            plan_id='plan_1',
            generated_at=datetime.now(),
            total_legs=0,
            fallback_count=0,
            timeout_count=0,
            error_count=0,
        )

        assert report.fallback_rate == 0.0
        assert report.timeout_rate == 0.0

    def test_report_to_dict(self):
        """Test serialization."""
        report = FallbackReport(
            plan_id='plan_1',
            generated_at=datetime.now(),
            total_legs=100,
            fallback_count=10,
            timeout_count=5,
            error_count=3,
            fallback_by_level={'HAVERSINE': 10},
            fallback_by_reason={'OSRM_TIMEOUT': 5, 'OSRM_ERROR': 3, 'MATRIX_MISS': 2},
        )

        data = report.to_dict()

        assert data['plan_id'] == 'plan_1'
        assert data['statistics']['fallback_count'] == 10
        assert data['fallback_by_level']['HAVERSINE'] == 10


# =============================================================================
# FALLBACK TRACKER TESTS
# =============================================================================

class TestFallbackTracker:
    """Tests for FallbackTracker class."""

    def test_record_event(self, tracker):
        """Test recording a fallback event."""
        tracker.record_event(
            from_stop_id='A',
            to_stop_id='B',
            fallback_level='HAVERSINE',
            reason='OSRM_TIMEOUT',
            duration_computed=600,
            distance_computed=5000,
        )

        assert tracker.event_count == 1
        assert tracker.has_events is True

    def test_record_timeout(self, tracker):
        """Test recording a timeout event."""
        tracker.record_timeout(
            from_stop_id='A',
            to_stop_id='B',
            duration_computed=600,
            distance_computed=5000,
            request_time_ms=4500.0,
        )

        report = tracker.get_report('plan_1')

        assert report.timeout_count == 1
        assert report.fallback_by_reason.get('OSRM_TIMEOUT') == 1

    def test_record_error(self, tracker):
        """Test recording an error event."""
        tracker.record_error(
            from_stop_id='A',
            to_stop_id='B',
            duration_computed=600,
            distance_computed=5000,
        )

        report = tracker.get_report('plan_1')

        assert report.error_count == 1
        assert report.fallback_by_reason.get('OSRM_ERROR') == 1

    def test_record_matrix_miss(self, tracker):
        """Test recording a matrix miss event."""
        tracker.record_matrix_miss(
            from_stop_id='A',
            to_stop_id='B',
            duration_computed=600,
            distance_computed=5000,
        )

        report = tracker.get_report('plan_1')

        assert report.fallback_by_reason.get('MATRIX_MISS') == 1

    def test_set_total_legs(self, tracker):
        """Test setting total legs."""
        tracker.set_total_legs(100)
        tracker.record_timeout('A', 'B', 600, 5000, 4500.0)

        report = tracker.get_report('plan_1')

        assert report.total_legs == 100
        assert report.fallback_rate == 0.01

    def test_get_report(self, tracker):
        """Test generating a report."""
        tracker.set_total_legs(10)
        tracker.record_timeout('A', 'B', 600, 5000, 4500.0)
        tracker.record_error('B', 'C', 500, 4000)
        tracker.record_matrix_miss('C', 'D', 400, 3000)

        report = tracker.get_report('plan_1')

        assert report.plan_id == 'plan_1'
        assert report.total_legs == 10
        assert report.fallback_count == 3
        assert report.timeout_count == 1
        assert report.error_count == 1

    def test_sample_events_limited(self, tracker):
        """Test that sample events are limited."""
        tracker.set_total_legs(20)

        # Record more events than max_sample_events
        for i in range(10):
            tracker.record_timeout(f'A{i}', f'B{i}', 600, 5000, 4500.0)

        report = tracker.get_report('plan_1')

        # Should have all events in .events but limited in .sample_events
        assert len(report.sample_events) == 5  # max_sample_events
        assert len(report.events) == 10  # all events

    def test_reset(self, tracker):
        """Test resetting the tracker."""
        tracker.set_total_legs(10)
        tracker.record_timeout('A', 'B', 600, 5000, 4500.0)

        assert tracker.event_count == 1

        tracker.reset()

        assert tracker.event_count == 0
        assert tracker.has_events is False

    def test_event_count_property(self, tracker):
        """Test event_count property."""
        assert tracker.event_count == 0

        tracker.record_timeout('A', 'B', 600, 5000, 4500.0)
        assert tracker.event_count == 1

        tracker.record_error('B', 'C', 500, 4000)
        assert tracker.event_count == 2

    def test_fallback_by_level_aggregation(self, tracker):
        """Test aggregation by fallback level."""
        tracker.set_total_legs(5)
        tracker.record_event('A', 'B', 'HAVERSINE', 'OSRM_TIMEOUT', 600, 5000)
        tracker.record_event('B', 'C', 'HAVERSINE', 'OSRM_ERROR', 500, 4000)
        tracker.record_event('C', 'D', 'H3', 'MATRIX_MISS', 400, 3000)

        report = tracker.get_report('plan_1')

        assert report.fallback_by_level.get('HAVERSINE') == 2
        assert report.fallback_by_level.get('H3') == 1
