# =============================================================================
# SOLVEREIGN Routing Pack - Drift Detector Tests
# =============================================================================
# Tests for drift detection between matrix and OSRM times.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_drift_detector.py -v
# =============================================================================

import pytest
from datetime import datetime

from backend_py.packs.routing.services.finalize.drift_detector import (
    DriftDetector,
    DriftReport,
    LegDrift,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def detector() -> DriftDetector:
    """Create drift detector instance."""
    return DriftDetector(top_n_worst=3)


@pytest.fixture
def sample_matrix_times():
    """Sample matrix times for testing."""
    return [
        {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 600},
        {'from_stop_id': 'B', 'to_stop_id': 'C', 'duration_seconds': 500},
        {'from_stop_id': 'C', 'to_stop_id': 'D', 'duration_seconds': 700},
    ]


@pytest.fixture
def sample_osrm_times():
    """Sample OSRM times matching matrix times."""
    return [
        {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 660,
         'timed_out': False, 'used_fallback': False},
        {'from_stop_id': 'B', 'to_stop_id': 'C', 'duration_seconds': 550,
         'timed_out': False, 'used_fallback': False},
        {'from_stop_id': 'C', 'to_stop_id': 'D', 'duration_seconds': 770,
         'timed_out': False, 'used_fallback': False},
    ]


# =============================================================================
# LEG DRIFT TESTS
# =============================================================================

class TestLegDrift:
    """Tests for LegDrift dataclass."""

    def test_leg_drift_basic(self):
        """Test basic leg drift creation."""
        leg = LegDrift(
            from_stop_id='A',
            to_stop_id='B',
            t_matrix_seconds=600,
            t_osrm_seconds=660,
            ratio=1.1,
            delta_seconds=60,
        )

        assert leg.from_stop_id == 'A'
        assert leg.to_stop_id == 'B'
        assert leg.ratio == 1.1
        assert leg.delta_seconds == 60

    def test_leg_drift_percent(self):
        """Test drift percentage calculation."""
        leg = LegDrift(
            from_stop_id='A',
            to_stop_id='B',
            t_matrix_seconds=600,
            t_osrm_seconds=720,
            ratio=1.2,
            delta_seconds=120,
        )

        assert leg.drift_percent == pytest.approx(20.0)

    def test_leg_drift_underestimate(self):
        """Test underestimate detection."""
        leg = LegDrift(
            from_stop_id='A',
            to_stop_id='B',
            t_matrix_seconds=600,
            t_osrm_seconds=720,
            ratio=1.2,
            delta_seconds=120,
        )

        assert leg.is_underestimate is True
        assert leg.is_overestimate is False

    def test_leg_drift_overestimate(self):
        """Test overestimate detection."""
        leg = LegDrift(
            from_stop_id='A',
            to_stop_id='B',
            t_matrix_seconds=600,
            t_osrm_seconds=480,
            ratio=0.8,
            delta_seconds=-120,
        )

        assert leg.is_underestimate is False
        assert leg.is_overestimate is True

    def test_leg_drift_to_dict(self):
        """Test serialization to dictionary."""
        leg = LegDrift(
            from_stop_id='A',
            to_stop_id='B',
            t_matrix_seconds=600,
            t_osrm_seconds=660,
            ratio=1.1,
            delta_seconds=60,
        )

        data = leg.to_dict()

        assert data['from_stop_id'] == 'A'
        assert data['to_stop_id'] == 'B'
        assert data['ratio'] == 1.1
        assert data['drift_percent'] == 10.0


# =============================================================================
# DRIFT REPORT TESTS
# =============================================================================

class TestDriftReport:
    """Tests for DriftReport dataclass."""

    def test_drift_report_rates(self):
        """Test rate calculations."""
        report = DriftReport(
            plan_id='plan_1',
            matrix_version='v1',
            osrm_map_hash='abc123',
            computed_at=datetime.now(),
            total_legs=10,
            legs_with_osrm=8,
            legs_with_timeout=1,
            legs_with_fallback=1,
            mean_ratio=1.1,
            median_ratio=1.05,
            p95_ratio=1.2,
            max_ratio=1.3,
            min_ratio=0.9,
            std_ratio=0.1,
        )

        assert report.timeout_rate == 0.1
        assert report.fallback_rate == 0.1
        assert report.osrm_coverage_rate == 0.8

    def test_drift_report_to_dict(self):
        """Test serialization."""
        report = DriftReport(
            plan_id='plan_1',
            matrix_version='v1',
            osrm_map_hash='abc123',
            computed_at=datetime.now(),
            total_legs=10,
            legs_with_osrm=8,
            legs_with_timeout=1,
            legs_with_fallback=1,
            mean_ratio=1.1,
            median_ratio=1.05,
            p95_ratio=1.2,
            max_ratio=1.3,
            min_ratio=0.9,
            std_ratio=0.1,
        )

        data = report.to_dict()

        assert data['plan_id'] == 'plan_1'
        assert data['statistics']['mean_ratio'] == 1.1
        assert data['aggregations']['timeout_rate'] == 0.1


# =============================================================================
# DRIFT DETECTOR TESTS
# =============================================================================

class TestDriftDetector:
    """Tests for DriftDetector class."""

    def test_compute_drift_basic(self, detector, sample_matrix_times, sample_osrm_times):
        """Test basic drift computation."""
        report = detector.compute_drift(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            matrix_times=sample_matrix_times,
            osrm_times=sample_osrm_times,
        )

        assert report.plan_id == 'test_plan'
        assert report.total_legs == 3
        assert report.legs_with_osrm == 3
        assert len(report.legs) == 3

    def test_compute_drift_ratios(self, detector):
        """Test ratio calculations."""
        matrix_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 100},
        ]
        osrm_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 150,
             'timed_out': False, 'used_fallback': False},
        ]

        report = detector.compute_drift(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            matrix_times=matrix_times,
            osrm_times=osrm_times,
        )

        assert report.mean_ratio == 1.5
        assert report.p95_ratio == 1.5
        assert report.legs[0].ratio == 1.5

    def test_compute_drift_with_timeouts(self, detector):
        """Test handling of timeout entries."""
        matrix_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 100},
            {'from_stop_id': 'B', 'to_stop_id': 'C', 'duration_seconds': 200},
        ]
        osrm_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 0,
             'timed_out': True, 'used_fallback': False},
            {'from_stop_id': 'B', 'to_stop_id': 'C', 'duration_seconds': 220,
             'timed_out': False, 'used_fallback': False},
        ]

        report = detector.compute_drift(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            matrix_times=matrix_times,
            osrm_times=osrm_times,
        )

        assert report.legs_with_timeout == 1
        assert report.legs_with_osrm == 1
        assert len(report.legs) == 1  # Only non-timeout leg

    def test_compute_drift_with_fallback(self, detector):
        """Test handling of fallback entries."""
        matrix_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 100},
        ]
        osrm_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 120,
             'timed_out': False, 'used_fallback': True},
        ]

        report = detector.compute_drift(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            matrix_times=matrix_times,
            osrm_times=osrm_times,
        )

        assert report.legs_with_fallback == 1

    def test_compute_drift_worst_offenders(self, detector):
        """Test worst offender tracking."""
        matrix_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 100},
            {'from_stop_id': 'B', 'to_stop_id': 'C', 'duration_seconds': 100},
            {'from_stop_id': 'C', 'to_stop_id': 'D', 'duration_seconds': 100},
            {'from_stop_id': 'D', 'to_stop_id': 'E', 'duration_seconds': 100},
        ]
        osrm_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 200,
             'timed_out': False, 'used_fallback': False},  # ratio 2.0
            {'from_stop_id': 'B', 'to_stop_id': 'C', 'duration_seconds': 150,
             'timed_out': False, 'used_fallback': False},  # ratio 1.5
            {'from_stop_id': 'C', 'to_stop_id': 'D', 'duration_seconds': 50,
             'timed_out': False, 'used_fallback': False},  # ratio 0.5
            {'from_stop_id': 'D', 'to_stop_id': 'E', 'duration_seconds': 80,
             'timed_out': False, 'used_fallback': False},  # ratio 0.8
        ]

        report = detector.compute_drift(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            matrix_times=matrix_times,
            osrm_times=osrm_times,
        )

        # Worst underestimates (ratio > 1)
        assert len(report.worst_underestimates) == 2
        assert report.worst_underestimates[0].ratio == 2.0  # A->B

        # Worst overestimates (ratio < 1)
        assert len(report.worst_overestimates) == 2
        assert report.worst_overestimates[0].ratio == 0.5  # C->D

    def test_compute_drift_from_consecutive(self, detector):
        """Test consecutive times interface."""
        report = detector.compute_drift_from_consecutive(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            route_id='route_1',
            stop_ids=['A', 'B', 'C', 'D'],
            matrix_leg_times=[100, 200, 150],
            osrm_leg_times=[110, 220, 160],
        )

        assert report.total_legs == 3
        assert len(report.legs) == 3

    def test_compute_drift_empty_inputs(self, detector):
        """Test with empty inputs."""
        report = detector.compute_drift(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            matrix_times=[],
            osrm_times=[],
        )

        assert report.total_legs == 0
        assert report.mean_ratio == 1.0

    def test_compute_drift_zero_matrix_time(self, detector):
        """Test handling of zero matrix time (avoid division by zero)."""
        matrix_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 0},
        ]
        osrm_times = [
            {'from_stop_id': 'A', 'to_stop_id': 'B', 'duration_seconds': 100,
             'timed_out': False, 'used_fallback': False},
        ]

        report = detector.compute_drift(
            plan_id='test_plan',
            matrix_version='v1',
            osrm_map_hash='abc123',
            matrix_times=matrix_times,
            osrm_times=osrm_times,
        )

        # Should use max(1, matrix_time) to avoid division by zero
        assert report.legs[0].ratio == 100.0
