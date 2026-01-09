# =============================================================================
# SOLVEREIGN Routing Pack - Static Matrix Version Tracking Tests
# =============================================================================
# Tests for version tracking and TTMeta in StaticMatrixProvider.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_static_matrix_version.py -v
# =============================================================================

import csv
import tempfile
from pathlib import Path
from typing import List, Tuple

import pytest

from backend_py.packs.routing.services.travel_time.static_matrix import (
    StaticMatrixProvider,
    StaticMatrixConfig,
)
from backend_py.packs.routing.services.travel_time.tt_meta import (
    TTMeta,
    StaticMatrixVersion,
    TravelTimeResultWithMeta,
    MatrixResultWithMeta,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_locations() -> List[Tuple[float, float]]:
    """Sample Vienna locations for testing."""
    return [
        (48.2082, 16.3738),  # Stephansplatz
        (48.2206, 16.4097),  # Prater
        (48.1986, 16.3417),  # Schonbrunn
    ]


@pytest.fixture
def sample_csv_path(sample_locations) -> str:
    """Create a temporary CSV file with sample travel times."""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.csv', delete=False, newline=''
    ) as f:
        writer = csv.writer(f)
        writer.writerow([
            'from_lat', 'from_lng', 'to_lat', 'to_lng',
            'duration_seconds', 'distance_meters'
        ])

        # Write travel times for all pairs
        travel_times = [
            # Stephansplatz -> Prater
            (48.2082, 16.3738, 48.2206, 16.4097, 600, 5000),
            # Stephansplatz -> Schonbrunn
            (48.2082, 16.3738, 48.1986, 16.3417, 720, 6000),
            # Prater -> Stephansplatz
            (48.2206, 16.4097, 48.2082, 16.3738, 610, 5100),
            # Prater -> Schonbrunn
            (48.2206, 16.4097, 48.1986, 16.3417, 850, 7500),
            # Schonbrunn -> Stephansplatz
            (48.1986, 16.3417, 48.2082, 16.3738, 730, 6200),
            # Schonbrunn -> Prater
            (48.1986, 16.3417, 48.2206, 16.4097, 860, 7600),
        ]

        for tt in travel_times:
            writer.writerow([f"{tt[0]:.6f}", f"{tt[1]:.6f}",
                           f"{tt[2]:.6f}", f"{tt[3]:.6f}",
                           tt[4], tt[5]])

        return f.name


@pytest.fixture
def provider() -> StaticMatrixProvider:
    """Create provider with default config."""
    return StaticMatrixProvider(StaticMatrixConfig())


# =============================================================================
# VERSION TRACKING TESTS
# =============================================================================

class TestVersionTracking:
    """Tests for matrix version tracking."""

    def test_load_csv_creates_version(self, provider, sample_csv_path):
        """Test that loading CSV creates version information."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        assert provider.matrix_version is not None
        assert provider.matrix_version.version_id == "test_v1"
        assert provider.matrix_version.row_count == 6
        assert len(provider.matrix_version.content_hash) == 64  # SHA256

    def test_load_csv_default_version_id(self, provider, sample_csv_path):
        """Test that version_id defaults to filename."""
        provider.load_from_csv(sample_csv_path)

        assert provider.matrix_version is not None
        # Version ID should be filename without extension
        expected_stem = Path(sample_csv_path).stem
        assert provider.matrix_version.version_id == expected_stem

    def test_version_id_property(self, provider, sample_csv_path):
        """Test version_id property shortcut."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        assert provider.version_id == "test_v1"

    def test_version_id_unknown_when_not_loaded(self, provider):
        """Test version_id returns 'unknown' when not loaded."""
        assert provider.version_id == "unknown"

    def test_content_hash_deterministic(self, sample_csv_path):
        """Test that same CSV produces same content hash."""
        provider1 = StaticMatrixProvider(StaticMatrixConfig())
        provider2 = StaticMatrixProvider(StaticMatrixConfig())

        provider1.load_from_csv(sample_csv_path, version_id="v1")
        provider2.load_from_csv(sample_csv_path, version_id="v2")

        # Same content should produce same hash regardless of version_id
        assert provider1.matrix_version.content_hash == provider2.matrix_version.content_hash

    def test_osrm_map_hash_tracked(self, provider, sample_csv_path):
        """Test that OSRM map hash is tracked when provided."""
        provider.load_from_csv(
            sample_csv_path,
            version_id="test_v1",
            osrm_map_hash="abc123def456"
        )

        assert provider.matrix_version.osrm_map_hash == "abc123def456"

    def test_load_from_entries_creates_version(self, provider):
        """Test that loading from entries creates version."""
        entries = [
            {'from_lat': 48.2082, 'from_lng': 16.3738,
             'to_lat': 48.2206, 'to_lng': 16.4097,
             'duration_seconds': 600, 'distance_meters': 5000},
        ]

        provider.load_from_entries(
            entries,
            version_id="memory_v1",
            osrm_map_hash="xyz789"
        )

        assert provider.matrix_version is not None
        assert provider.matrix_version.version_id == "memory_v1"
        assert provider.matrix_version.row_count == 1
        assert provider.matrix_version.osrm_map_hash == "xyz789"
        assert provider.matrix_version.source_path is None  # No file source


# =============================================================================
# METADATA TRACKING TESTS
# =============================================================================

class TestMetadataTracking:
    """Tests for TTMeta provenance tracking."""

    def test_get_travel_time_with_meta_returns_metadata(
        self, provider, sample_csv_path
    ):
        """Test that get_travel_time_with_meta returns metadata."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        result = provider.get_travel_time_with_meta(
            (48.2082, 16.3738),  # Stephansplatz
            (48.2206, 16.4097),  # Prater
        )

        assert isinstance(result, TravelTimeResultWithMeta)
        assert result.duration_seconds == 600
        assert result.distance_meters == 5000
        assert result.meta.provider == "static_matrix"
        assert result.meta.version == "test_v1"
        assert result.meta.fallback_level is None

    def test_haversine_fallback_tracked_in_meta(self, provider, sample_csv_path):
        """Test that Haversine fallback is tracked in metadata."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        # Query for coordinates not in the matrix
        result = provider.get_travel_time_with_meta(
            (48.0000, 16.0000),  # Not in matrix
            (48.1000, 16.1000),  # Not in matrix
        )

        assert isinstance(result, TravelTimeResultWithMeta)
        assert result.meta.provider == "haversine"
        assert result.meta.fallback_level == "HAVERSINE"
        assert result.meta.fallback_reason == "MATRIX_MISS"

    def test_same_point_returns_zero_with_meta(self, provider, sample_csv_path):
        """Test that same point returns zero duration with metadata."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        result = provider.get_travel_time_with_meta(
            (48.2082, 16.3738),
            (48.2082, 16.3738),  # Same point
        )

        assert result.duration_seconds == 0
        assert result.distance_meters == 0
        assert result.meta.provider == "static_matrix"


# =============================================================================
# MATRIX WITH METADATA TESTS
# =============================================================================

class TestMatrixWithMetadata:
    """Tests for matrix retrieval with metadata."""

    def test_get_matrix_with_meta_returns_metadata_matrix(
        self, provider, sample_csv_path, sample_locations
    ):
        """Test that get_matrix_with_meta returns per-leg metadata."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        result = provider.get_matrix_with_meta(sample_locations)

        assert isinstance(result, MatrixResultWithMeta)
        assert len(result.meta_matrix) == 3  # 3x3 matrix
        assert len(result.meta_matrix[0]) == 3

        # Check non-diagonal entries have metadata
        assert result.meta_matrix[0][1].provider == "static_matrix"
        assert result.meta_matrix[0][1].version == "test_v1"

    def test_matrix_fallback_count(self, provider, sample_csv_path):
        """Test fallback count in matrix result."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        # Include location not in matrix to trigger fallback
        locations = [
            (48.2082, 16.3738),  # Stephansplatz (in matrix)
            (48.0000, 16.0000),  # Not in matrix
        ]

        result = provider.get_matrix_with_meta(locations)

        # Should have some fallbacks (coords not in matrix)
        assert result.fallback_count > 0
        assert result.fallback_rate > 0

    def test_matrix_version_included(self, provider, sample_csv_path, sample_locations):
        """Test that matrix version is included in result."""
        provider.load_from_csv(sample_csv_path, version_id="test_v1")

        result = provider.get_matrix_with_meta(sample_locations)

        assert result.matrix_version.version_id == "test_v1"
        assert len(result.matrix_version.content_hash) == 64


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_unloaded_provider_returns_unknown_version(self):
        """Test that unloaded provider has unknown version."""
        provider = StaticMatrixProvider(StaticMatrixConfig())

        assert provider.version_id == "unknown"
        assert provider.matrix_version is None

    def test_provider_health_check(self, provider, sample_csv_path):
        """Test provider health check after loading."""
        assert not provider.health_check()  # Not loaded yet

        provider.load_from_csv(sample_csv_path)

        assert provider.health_check()  # Now loaded

    def test_matrix_size_tracking(self, provider, sample_csv_path):
        """Test matrix_size method."""
        provider.load_from_csv(sample_csv_path)

        assert provider.matrix_size() == 6  # 6 entries in test CSV
