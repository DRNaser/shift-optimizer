# =============================================================================
# SOLVEREIGN Routing Pack - Matrix Generator Tests
# =============================================================================
# Tests for the static matrix generation from OSRM.
#
# Run with:
#   pytest backend_py/packs/routing/tests/test_matrix_generator.py -v
# =============================================================================

import csv
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple
from unittest.mock import Mock, patch, MagicMock

import pytest

from backend_py.packs.routing.services.travel_time.matrix_generator import (
    MatrixGenerator,
    MatrixGeneratorConfig,
    GeneratedMatrix,
    MatrixValidationResult,
    MatrixGeneratorError,
    OSRMConnectionError,
    OSRMResponseError,
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
def mock_osrm_response() -> Dict:
    """Mock OSRM table response for 3 locations."""
    return {
        "code": "Ok",
        "durations": [
            [0.0, 600.5, 720.3],
            [610.2, 0.0, 850.7],
            [730.1, 860.4, 0.0],
        ],
        "distances": [
            [0.0, 5000.5, 6000.3],
            [5100.2, 0.0, 7500.7],
            [6200.1, 7600.4, 0.0],
        ],
    }


@pytest.fixture
def config() -> MatrixGeneratorConfig:
    """Test configuration."""
    return MatrixGeneratorConfig(
        osrm_url="http://localhost:5000",
        output_dir=tempfile.mkdtemp(),
        batch_size=100,
        timeout_seconds=5.0,
    )


@pytest.fixture
def generator(config) -> MatrixGenerator:
    """Generator instance with test config."""
    return MatrixGenerator(config)


# =============================================================================
# UNIT TESTS - OSRM STATUS
# =============================================================================

class TestOSRMStatus:
    """Tests for OSRM status and map hash retrieval."""

    def test_get_osrm_status_success(self, generator):
        """Test successful status retrieval."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data_timestamp": "2024-01-15T10:30:00Z",
            "algorithm": "MLD",
        }
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            status = generator.get_osrm_status()

        assert status["algorithm"] == "MLD"
        assert "data_timestamp" in status

    def test_get_osrm_status_connection_error(self, generator):
        """Test connection error handling."""
        import requests

        with patch.object(
            generator.session, "get",
            side_effect=requests.exceptions.ConnectionError("Connection refused")
        ):
            with pytest.raises(OSRMConnectionError):
                generator.get_osrm_status()

    def test_get_osrm_map_hash_returns_string(self, generator):
        """Test map hash computation."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data_timestamp": "2024-01-15"}
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            hash_value = generator.get_osrm_map_hash()

        assert isinstance(hash_value, str)
        assert len(hash_value) == 16  # Truncated SHA256

    def test_get_osrm_map_hash_on_error_returns_unknown(self, generator):
        """Test fallback hash on error."""
        import requests

        with patch.object(
            generator.session, "get",
            side_effect=requests.exceptions.ConnectionError()
        ):
            hash_value = generator.get_osrm_map_hash()

        assert hash_value == "unknown"


# =============================================================================
# UNIT TESTS - MATRIX GENERATION
# =============================================================================

class TestMatrixGeneration:
    """Tests for matrix generation from OSRM."""

    def test_generate_matrix_success(
        self, generator, sample_locations, mock_osrm_response
    ):
        """Test successful matrix generation."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_osrm_response
        mock_response.raise_for_status = Mock()

        status_response = MagicMock()
        status_response.json.return_value = {"data_timestamp": "2024-01-15"}
        status_response.raise_for_status = Mock()

        def mock_get(url, **kwargs):
            if "/status" in url:
                return status_response
            return mock_response

        with patch.object(generator.session, "get", side_effect=mock_get):
            result = generator.generate_from_locations(
                locations=sample_locations,
                version_id="test_v1",
            )

        assert isinstance(result, GeneratedMatrix)
        assert result.version_id == "test_v1"
        assert result.location_count == 3
        assert result.row_count == 9  # 3x3 matrix
        assert result.total_legs == 9
        assert Path(result.csv_path).exists()

    def test_generate_matrix_creates_valid_csv(
        self, generator, sample_locations, mock_osrm_response
    ):
        """Test that generated CSV has correct format."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_osrm_response
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            result = generator.generate_from_locations(
                locations=sample_locations,
                version_id="test_v1",
            )

        # Read and verify CSV
        with open(result.csv_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 9
        assert "from_lat" in reader.fieldnames
        assert "duration_seconds" in reader.fieldnames
        assert "distance_meters" in reader.fieldnames

        # Check first row values
        row = rows[0]
        assert float(row["from_lat"]) == pytest.approx(48.2082, abs=0.0001)
        assert int(row["duration_seconds"]) == 0  # Self-loop

    def test_generate_matrix_converts_floats_to_int(
        self, generator, sample_locations, mock_osrm_response
    ):
        """Test that durations/distances are converted to integers."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_osrm_response
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            result = generator.generate_from_locations(
                locations=sample_locations,
                version_id="test_v1",
            )

        with open(result.csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Should be integers, not floats
                duration = row["duration_seconds"]
                distance = row["distance_meters"]
                assert "." not in duration
                assert "." not in distance

    def test_generate_matrix_creates_metadata_file(
        self, generator, sample_locations, mock_osrm_response
    ):
        """Test that metadata JSON is created alongside CSV."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_osrm_response
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            result = generator.generate_from_locations(
                locations=sample_locations,
                version_id="test_v1",
            )

        metadata_path = result.csv_path.replace(".csv", "_metadata.json")
        assert Path(metadata_path).exists()

        with open(metadata_path) as f:
            metadata = json.load(f)

        assert metadata["version_id"] == "test_v1"
        assert "content_hash" in metadata
        assert "osrm_map_hash" in metadata

    def test_generate_matrix_deterministic_hash(
        self, generator, sample_locations, mock_osrm_response
    ):
        """Test that same input produces same content hash."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_osrm_response
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            result1 = generator.generate_from_locations(
                locations=sample_locations,
                version_id="test_v1",
            )
            result2 = generator.generate_from_locations(
                locations=sample_locations,
                version_id="test_v2",
            )

        # Same input data should produce same hash
        assert result1.content_hash == result2.content_hash

    def test_generate_matrix_fails_with_one_location(self, generator):
        """Test that generation fails with less than 2 locations."""
        with pytest.raises(MatrixGeneratorError, match="at least 2 locations"):
            generator.generate_from_locations(
                locations=[(48.2082, 16.3738)],
                version_id="test_v1",
            )

    def test_generate_matrix_osrm_error_response(self, generator, sample_locations):
        """Test handling of OSRM error response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "InvalidInput",
            "message": "Coordinate out of bounds",
        }
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            with pytest.raises(OSRMResponseError, match="OSRM error"):
                generator.generate_from_locations(
                    locations=sample_locations,
                    version_id="test_v1",
                )


# =============================================================================
# UNIT TESTS - VALIDATION
# =============================================================================

class TestMatrixValidation:
    """Tests for matrix CSV validation."""

    def test_validate_valid_matrix(self, generator, config, sample_locations):
        """Test validation of a valid matrix."""
        # Create a valid matrix file
        csv_path = Path(config.output_dir) / "valid_matrix.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "from_lat", "from_lng", "to_lat", "to_lng",
                "duration_seconds", "distance_meters"
            ])
            for from_loc in sample_locations:
                for to_loc in sample_locations:
                    writer.writerow([
                        f"{from_loc[0]:.6f}",
                        f"{from_loc[1]:.6f}",
                        f"{to_loc[0]:.6f}",
                        f"{to_loc[1]:.6f}",
                        "600",
                        "5000",
                    ])

        result = generator.validate_matrix(str(csv_path))

        assert result.valid is True
        assert result.row_count == 9
        assert result.location_count == 3
        assert len(result.errors) == 0

    def test_validate_missing_file(self, generator):
        """Test validation of non-existent file."""
        result = generator.validate_matrix("/nonexistent/path.csv")

        assert result.valid is False
        assert "does not exist" in result.errors[0]

    def test_validate_negative_duration(self, generator, config):
        """Test validation catches negative durations."""
        csv_path = Path(config.output_dir) / "invalid_matrix.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "from_lat", "from_lng", "to_lat", "to_lng",
                "duration_seconds", "distance_meters"
            ])
            writer.writerow(["48.2082", "16.3738", "48.2206", "16.4097", "-100", "5000"])

        result = generator.validate_matrix(str(csv_path))

        assert result.valid is False
        assert any("negative duration" in e for e in result.errors)

    def test_validate_missing_columns(self, generator, config):
        """Test validation catches missing columns."""
        csv_path = Path(config.output_dir) / "missing_cols.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["from_lat", "from_lng"])  # Missing columns
            writer.writerow(["48.2082", "16.3738"])

        result = generator.validate_matrix(str(csv_path))

        assert result.valid is False
        assert any("Missing columns" in e for e in result.errors)

    def test_validate_computes_hash(self, generator, config, sample_locations):
        """Test that validation computes content hash."""
        csv_path = Path(config.output_dir) / "hash_test.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "from_lat", "from_lng", "to_lat", "to_lng",
                "duration_seconds", "distance_meters"
            ])
            for from_loc in sample_locations:
                for to_loc in sample_locations:
                    writer.writerow([
                        f"{from_loc[0]:.6f}", f"{from_loc[1]:.6f}",
                        f"{to_loc[0]:.6f}", f"{to_loc[1]:.6f}",
                        "600", "5000"
                    ])

        result = generator.validate_matrix(str(csv_path))

        assert result.content_hash is not None
        assert len(result.content_hash) == 64  # SHA256 hex


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestMatrixGeneratorIntegration:
    """Integration tests requiring actual OSRM server."""

    @pytest.mark.skipif(
        True,  # Skip by default, set to False when OSRM is running
        reason="Requires running OSRM server"
    )
    def test_generate_real_matrix(self, generator, sample_locations):
        """Integration test with real OSRM server."""
        result = generator.generate_from_locations(
            locations=sample_locations,
            version_id="integration_test",
        )

        assert result.location_count == 3
        assert result.row_count == 9
        assert result.osrm_map_hash != "unknown"


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================

class TestContextManager:
    """Tests for context manager functionality."""

    def test_context_manager_closes_session(self, config):
        """Test that context manager closes session."""
        with MatrixGenerator(config) as gen:
            # Access session to create it
            _ = gen.session
            assert gen._session is not None

        assert gen._session is None

    def test_context_manager_on_error(self, config):
        """Test that session closes even on error."""
        gen = MatrixGenerator(config)

        try:
            with gen:
                _ = gen.session
                raise ValueError("Test error")
        except ValueError:
            pass

        assert gen._session is None


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_locations_list(self, generator):
        """Test with empty locations list."""
        with pytest.raises(MatrixGeneratorError):
            generator.generate_from_locations(
                locations=[],
                version_id="test_v1",
            )

    def test_two_locations_minimum(self, generator, mock_osrm_response):
        """Test with minimum 2 locations."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "durations": [[0.0, 600.0], [610.0, 0.0]],
            "distances": [[0.0, 5000.0], [5100.0, 0.0]],
        }
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            result = generator.generate_from_locations(
                locations=[(48.2082, 16.3738), (48.2206, 16.4097)],
                version_id="test_v1",
            )

        assert result.location_count == 2
        assert result.row_count == 4

    def test_null_duration_in_osrm_response(self, generator, sample_locations):
        """Test handling of null values in OSRM response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "durations": [
                [0.0, None, 720.0],  # null value
                [610.0, 0.0, 850.0],
                [730.0, 860.0, 0.0],
            ],
            "distances": [
                [0.0, None, 6000.0],
                [5100.0, 0.0, 7500.0],
                [6200.0, 7600.0, 0.0],
            ],
        }
        mock_response.raise_for_status = Mock()

        with patch.object(generator.session, "get", return_value=mock_response):
            result = generator.generate_from_locations(
                locations=sample_locations,
                version_id="test_v1",
            )

        # Should use max values for null
        with open(result.csv_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Find the row with null duration (should be max)
        null_row = rows[1]  # (0,1) in matrix
        assert int(null_row["duration_seconds"]) == generator.config.max_duration_seconds
