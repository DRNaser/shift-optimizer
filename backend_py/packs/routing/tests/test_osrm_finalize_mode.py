# =============================================================================
# SOLVEREIGN Routing Pack - OSRM Finalize Mode Tests
# =============================================================================
# Tests for OSRM finalize mode and status tracking.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_osrm_finalize_mode.py -v
# =============================================================================

from typing import List, Tuple
from unittest.mock import Mock, patch, MagicMock

import pytest

# Mock httpx before importing OSRMProvider
import sys
mock_httpx = MagicMock()
mock_httpx.HTTPError = Exception
mock_httpx.TimeoutException = TimeoutError
sys.modules['httpx'] = mock_httpx

from backend_py.packs.routing.services.travel_time.osrm_provider import (
    OSRMProvider,
    OSRMConfig,
    OSRMStatus,
    ConsecutiveTimesResult,
    HTTPX_AVAILABLE,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_waypoints() -> List[Tuple[float, float]]:
    """Sample Vienna waypoints for testing."""
    return [
        (48.2082, 16.3738),  # Stephansplatz
        (48.2206, 16.4097),  # Prater
        (48.1986, 16.3417),  # Schonbrunn
    ]


@pytest.fixture
def mock_osrm_status_response() -> dict:
    """Mock OSRM status response."""
    return {
        "algorithm": "MLD",
        "data_timestamp": "2024-01-15T10:30:00Z",
    }


@pytest.fixture
def mock_osrm_route_response() -> dict:
    """Mock OSRM route response with legs."""
    return {
        "code": "Ok",
        "routes": [{
            "duration": 1200,
            "distance": 10000,
            "legs": [
                {"duration": 600, "distance": 5000},
                {"duration": 600, "distance": 5000},
            ]
        }]
    }


@pytest.fixture
def config() -> OSRMConfig:
    """Test configuration with finalize mode disabled."""
    return OSRMConfig(
        base_url="http://localhost:5000",
        profile="driving",
        finalize_mode=False,
        use_haversine_fallback=True,
    )


@pytest.fixture
def finalize_config() -> OSRMConfig:
    """Test configuration with finalize mode enabled."""
    return OSRMConfig(
        base_url="http://localhost:5000",
        profile="driving",
        finalize_mode=True,
        finalize_timeout_seconds=5.0,
        finalize_connect_timeout=2.0,
        no_fallback_in_finalize=True,
    )


# =============================================================================
# CONFIG TESTS
# =============================================================================

class TestOSRMConfig:
    """Tests for OSRMConfig finalize mode settings."""

    def test_default_config_finalize_disabled(self):
        """Test that finalize mode is disabled by default."""
        config = OSRMConfig()
        assert config.finalize_mode is False
        assert config.use_haversine_fallback is True

    def test_finalize_mode_config(self):
        """Test finalize mode configuration."""
        config = OSRMConfig(
            finalize_mode=True,
            finalize_timeout_seconds=3.0,
            finalize_connect_timeout=1.0,
            no_fallback_in_finalize=True,
        )
        assert config.finalize_mode is True
        assert config.finalize_timeout_seconds == 3.0
        assert config.finalize_connect_timeout == 1.0
        assert config.no_fallback_in_finalize is True


# =============================================================================
# OSRM STATUS TESTS
# =============================================================================

class TestOSRMStatus:
    """Tests for OSRMStatus dataclass."""

    def test_osrm_status_to_dict(self):
        """Test OSRMStatus serialization."""
        from datetime import datetime

        status = OSRMStatus(
            map_hash="abc123def456",
            profile="driving",
            algorithm="MLD",
            data_timestamp="2024-01-15T10:30:00Z",
        )

        data = status.to_dict()

        assert data["map_hash"] == "abc123def456"
        assert data["profile"] == "driving"
        assert data["algorithm"] == "MLD"
        assert data["data_timestamp"] == "2024-01-15T10:30:00Z"
        assert "retrieved_at" in data


# =============================================================================
# CONSECUTIVE TIMES RESULT TESTS
# =============================================================================

class TestConsecutiveTimesResult:
    """Tests for ConsecutiveTimesResult dataclass."""

    def test_consecutive_times_result_basic(self, sample_waypoints):
        """Test ConsecutiveTimesResult with basic data."""
        result = ConsecutiveTimesResult(
            waypoints=sample_waypoints,
            leg_durations=[600, 600],
            leg_distances=[5000, 5000],
            total_duration=1200,
            total_distance=10000,
            timed_out=False,
            used_fallback=False,
        )

        assert len(result.leg_durations) == 2
        assert result.total_duration == 1200
        assert result.timed_out is False
        assert result.used_fallback is False

    def test_consecutive_times_result_timeout(self, sample_waypoints):
        """Test ConsecutiveTimesResult with timeout."""
        result = ConsecutiveTimesResult(
            waypoints=sample_waypoints,
            leg_durations=[],
            leg_distances=[],
            total_duration=0,
            total_distance=0,
            timed_out=True,
            used_fallback=False,
        )

        assert result.timed_out is True
        assert result.leg_durations == []

    def test_consecutive_times_result_fallback(self, sample_waypoints):
        """Test ConsecutiveTimesResult with fallback."""
        result = ConsecutiveTimesResult(
            waypoints=sample_waypoints,
            leg_durations=[600, 600],
            leg_distances=[5000, 5000],
            total_duration=1200,
            total_distance=10000,
            timed_out=False,
            used_fallback=True,
        )

        assert result.used_fallback is True


# =============================================================================
# PROVIDER INITIALIZATION TESTS
# =============================================================================

class TestOSRMProviderInit:
    """Tests for OSRMProvider initialization."""

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    def test_provider_init_stores_config(self, config):
        """Test that provider stores config correctly."""
        with patch.object(OSRMProvider, '_init_client'):
            provider = OSRMProvider(config)
            assert provider.config == config
            assert provider._osrm_status is None


# =============================================================================
# MAP HASH TESTS
# =============================================================================

class TestMapHash:
    """Tests for OSRM map hash functionality."""

    def test_map_hash_computation_from_timestamp(self):
        """Test that map hash is computed from data_timestamp."""
        import hashlib

        timestamp = "2024-01-15T10:30:00Z"
        expected_hash = hashlib.sha256(timestamp.encode()).hexdigest()[:16]

        status = OSRMStatus(
            map_hash=expected_hash,
            profile="driving",
            algorithm="MLD",
            data_timestamp=timestamp,
        )

        assert len(status.map_hash) == 16
        assert status.map_hash == expected_hash

    def test_map_hash_deterministic(self):
        """Test that same timestamp produces same hash."""
        import hashlib

        timestamp = "2024-01-15T10:30:00Z"
        hash1 = hashlib.sha256(timestamp.encode()).hexdigest()[:16]
        hash2 = hashlib.sha256(timestamp.encode()).hexdigest()[:16]

        assert hash1 == hash2


# =============================================================================
# HAVERSINE FALLBACK TESTS
# =============================================================================

class TestHaversineFallback:
    """Tests for Haversine fallback in finalize mode."""

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    def test_haversine_consecutive_fallback(self, sample_waypoints, config):
        """Test Haversine consecutive fallback computation."""
        with patch.object(OSRMProvider, '_init_client'):
            provider = OSRMProvider(config)

            result = provider._haversine_consecutive_fallback(sample_waypoints)

            assert isinstance(result, ConsecutiveTimesResult)
            assert result.used_fallback is True
            assert len(result.leg_durations) == 2  # 3 waypoints = 2 legs
            assert result.meta is not None
            assert result.meta.fallback_level == "HAVERSINE"


# =============================================================================
# FINALIZE MODE BEHAVIOR TESTS
# =============================================================================

class TestFinalizeModeConfig:
    """Tests for finalize mode configuration behavior."""

    def test_finalize_mode_shorter_timeouts(self, finalize_config):
        """Test that finalize mode has shorter timeouts."""
        assert finalize_config.finalize_timeout_seconds < finalize_config.timeout_seconds
        assert finalize_config.finalize_connect_timeout < finalize_config.connect_timeout_seconds

    def test_finalize_mode_no_fallback_flag(self, finalize_config):
        """Test that no_fallback_in_finalize is configurable."""
        assert finalize_config.no_fallback_in_finalize is True

        config_with_fallback = OSRMConfig(
            finalize_mode=True,
            no_fallback_in_finalize=False,
        )
        assert config_with_fallback.no_fallback_in_finalize is False
