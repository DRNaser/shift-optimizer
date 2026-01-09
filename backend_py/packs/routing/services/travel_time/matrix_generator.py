# =============================================================================
# SOLVEREIGN Routing Pack - Matrix Generator
# =============================================================================
# Generates static travel time matrices from OSRM for deterministic solving.
#
# Usage:
#   generator = MatrixGenerator(config)
#   result = generator.generate_from_locations(locations, "wien_2026w02_v1")
#
# The generated matrix is used by StaticMatrixProvider during solve phase.
# =============================================================================

from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class MatrixGeneratorConfig:
    """Configuration for matrix generation."""

    # OSRM server settings
    osrm_url: str = "http://localhost:5000"
    osrm_profile: str = "driving"

    # Output settings
    output_dir: str = "data/matrices"

    # Performance settings
    batch_size: int = 100  # Max locations per OSRM table request
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0

    # Validation settings
    max_duration_seconds: int = 86400  # 24 hours max travel time
    max_distance_meters: int = 1000000  # 1000 km max distance


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class GeneratedMatrix:
    """Result of matrix generation."""

    version_id: str  # e.g., "wien_2026w02_v1"
    content_hash: str  # SHA256 of CSV content
    created_at: datetime
    row_count: int
    location_count: int
    csv_path: str

    # Source tracking
    osrm_map_hash: str
    osrm_profile: str
    osrm_url: str

    # Generation stats
    generation_time_seconds: float
    osrm_requests: int
    total_legs: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
            "row_count": self.row_count,
            "location_count": self.location_count,
            "csv_path": self.csv_path,
            "osrm_map_hash": self.osrm_map_hash,
            "osrm_profile": self.osrm_profile,
            "osrm_url": self.osrm_url,
            "generation_time_seconds": self.generation_time_seconds,
            "osrm_requests": self.osrm_requests,
            "total_legs": self.total_legs,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class MatrixValidationResult:
    """Result of matrix validation."""

    valid: bool
    csv_path: str
    row_count: int
    location_count: int
    content_hash: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class MatrixGeneratorError(Exception):
    """Base exception for matrix generation errors."""
    pass


class OSRMConnectionError(MatrixGeneratorError):
    """Failed to connect to OSRM server."""
    pass


class OSRMResponseError(MatrixGeneratorError):
    """Invalid response from OSRM server."""
    pass


class MatrixValidationError(MatrixGeneratorError):
    """Matrix validation failed."""
    pass


# =============================================================================
# MATRIX GENERATOR
# =============================================================================

class MatrixGenerator:
    """
    Generates static travel time matrices from OSRM.

    The generated matrices are used by StaticMatrixProvider for deterministic
    solving. OSRM is only used at matrix generation time, not during solve.

    Matrix CSV format:
        from_lat,from_lng,to_lat,to_lng,duration_seconds,distance_meters

    Example:
        generator = MatrixGenerator(config)
        result = generator.generate_from_locations(locations, "wien_2026w02_v1")
    """

    def __init__(self, config: Optional[MatrixGeneratorConfig] = None):
        self.config = config or MatrixGeneratorConfig()
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        """Lazy-initialized HTTP session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers["User-Agent"] = "SOLVEREIGN-MatrixGenerator/1.0"
        return self._session

    def close(self):
        """Close HTTP session."""
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # =========================================================================
    # OSRM API
    # =========================================================================

    def get_osrm_status(self) -> Dict[str, Any]:
        """
        Get OSRM server status including map version hash.

        Returns:
            Dict with map_hash, profile, algorithm info
        """
        try:
            response = self.session.get(
                f"{self.config.osrm_url}/status",
                timeout=self.config.timeout_seconds
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError as e:
            raise OSRMConnectionError(f"Cannot connect to OSRM at {self.config.osrm_url}: {e}")
        except requests.exceptions.RequestException as e:
            raise OSRMResponseError(f"OSRM status request failed: {e}")

    def get_osrm_map_hash(self) -> str:
        """
        Get OSRM map data hash for evidence tracking.

        Returns:
            SHA256 hash or 'unknown' if not available
        """
        try:
            status = self.get_osrm_status()
            # OSRM status returns data_timestamp or similar
            if "data_timestamp" in status:
                return hashlib.sha256(status["data_timestamp"].encode()).hexdigest()[:16]
            # Fallback: hash the full status response
            return hashlib.sha256(json.dumps(status, sort_keys=True).encode()).hexdigest()[:16]
        except MatrixGeneratorError:
            return "unknown"

    def _query_osrm_table(
        self,
        locations: List[Tuple[float, float]]
    ) -> Tuple[List[List[int]], List[List[int]]]:
        """
        Query OSRM table service for NxN matrix.

        Args:
            locations: List of (lat, lng) coordinates

        Returns:
            (durations_matrix, distances_matrix) both in int
        """
        if len(locations) < 2:
            return [[0]], [[0]]

        # OSRM expects lng,lat format
        coords = ";".join(f"{lng},{lat}" for lat, lng in locations)

        url = f"{self.config.osrm_url}/table/v1/{self.config.osrm_profile}/{coords}"
        params = {
            "annotations": "duration,distance",
        }

        for attempt in range(self.config.max_retries):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.config.timeout_seconds
                )
                response.raise_for_status()
                data = response.json()

                if data.get("code") != "Ok":
                    raise OSRMResponseError(f"OSRM error: {data.get('message', 'Unknown error')}")

                # Extract matrices and convert to int seconds/meters
                durations = data.get("durations", [])
                distances = data.get("distances", [])

                # Convert to integers (OSRM returns floats)
                int_durations = [
                    [int(round(d)) if d is not None else self.config.max_duration_seconds for d in row]
                    for row in durations
                ]
                int_distances = [
                    [int(round(d)) if d is not None else self.config.max_distance_meters for d in row]
                    for row in distances
                ]

                return int_durations, int_distances

            except requests.exceptions.Timeout:
                logger.warning(f"OSRM timeout (attempt {attempt + 1}/{self.config.max_retries})")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay_seconds)
                else:
                    raise OSRMResponseError(f"OSRM timeout after {self.config.max_retries} attempts")

            except requests.exceptions.ConnectionError as e:
                raise OSRMConnectionError(f"Cannot connect to OSRM: {e}")

    # =========================================================================
    # MATRIX GENERATION
    # =========================================================================

    def generate_from_locations(
        self,
        locations: List[Tuple[float, float]],
        version_id: str,
        output_path: Optional[str] = None
    ) -> GeneratedMatrix:
        """
        Generate NxN travel time matrix from OSRM.

        Args:
            locations: List of (lat, lng) coordinates
            version_id: Version identifier (e.g., "wien_2026w02_v1")
            output_path: Override output path (default: config.output_dir/version_id.csv)

        Returns:
            GeneratedMatrix with metadata and file path
        """
        start_time = time.time()
        logger.info(f"Generating matrix for {len(locations)} locations, version={version_id}")

        # Validate inputs
        if len(locations) < 2:
            raise MatrixGeneratorError("Need at least 2 locations for matrix generation")

        # Get OSRM map hash for evidence
        osrm_map_hash = self.get_osrm_map_hash()
        logger.info(f"OSRM map hash: {osrm_map_hash}")

        # Determine output path
        if output_path is None:
            output_dir = Path(self.config.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"{version_id}.csv")

        # Generate matrix in batches if needed
        n = len(locations)
        osrm_requests = 0

        if n <= self.config.batch_size:
            # Single request for small matrices
            durations, distances = self._query_osrm_table(locations)
            osrm_requests = 1
        else:
            # Batch processing for large matrices
            durations = [[0] * n for _ in range(n)]
            distances = [[0] * n for _ in range(n)]

            # Process in batches
            batch_size = self.config.batch_size
            for i in range(0, n, batch_size):
                batch_end = min(i + batch_size, n)
                batch_locations = locations[i:batch_end]

                # Get matrix for this batch against all locations
                # Note: OSRM table can handle sources/destinations separately
                batch_dur, batch_dist = self._query_osrm_table(batch_locations + locations)
                osrm_requests += 1

                # Extract the relevant portion
                for bi, gi in enumerate(range(i, batch_end)):
                    for j in range(n):
                        # Offset by batch size to get to "destinations" part
                        durations[gi][j] = batch_dur[bi][len(batch_locations) + j]
                        distances[gi][j] = batch_dist[bi][len(batch_locations) + j]

                logger.debug(f"Processed batch {i//batch_size + 1}, locations {i}-{batch_end}")

        # Write CSV
        row_count = 0
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "from_lat", "from_lng", "to_lat", "to_lng",
                "duration_seconds", "distance_meters"
            ])

            for i, (from_lat, from_lng) in enumerate(locations):
                for j, (to_lat, to_lng) in enumerate(locations):
                    writer.writerow([
                        f"{from_lat:.6f}",
                        f"{from_lng:.6f}",
                        f"{to_lat:.6f}",
                        f"{to_lng:.6f}",
                        durations[i][j],
                        distances[i][j],
                    ])
                    row_count += 1

        # Compute content hash
        content_hash = self._compute_file_hash(output_path)

        # Write metadata sidecar
        generation_time = time.time() - start_time

        result = GeneratedMatrix(
            version_id=version_id,
            content_hash=content_hash,
            created_at=datetime.now(),
            row_count=row_count,
            location_count=n,
            csv_path=output_path,
            osrm_map_hash=osrm_map_hash,
            osrm_profile=self.config.osrm_profile,
            osrm_url=self.config.osrm_url,
            generation_time_seconds=generation_time,
            osrm_requests=osrm_requests,
            total_legs=n * n,
        )

        # Write metadata JSON
        metadata_path = output_path.replace(".csv", "_metadata.json")
        with open(metadata_path, "w") as f:
            f.write(result.to_json())

        logger.info(
            f"Matrix generated: {row_count} rows, hash={content_hash[:16]}..., "
            f"time={generation_time:.2f}s"
        )

        return result

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def validate_matrix(self, csv_path: str) -> MatrixValidationResult:
        """
        Validate a matrix CSV file.

        Checks:
        - File exists and is readable
        - Has correct header
        - All values are valid numbers
        - Durations and distances are within bounds
        - Matrix is complete (N*N rows for N locations)

        Args:
            csv_path: Path to CSV file

        Returns:
            MatrixValidationResult
        """
        errors: List[str] = []
        warnings: List[str] = []

        path = Path(csv_path)
        if not path.exists():
            return MatrixValidationResult(
                valid=False,
                csv_path=csv_path,
                row_count=0,
                location_count=0,
                content_hash="",
                errors=["File does not exist"],
            )

        # Read and validate
        locations_seen = set()
        row_count = 0

        try:
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)

                # Check header
                expected_cols = {"from_lat", "from_lng", "to_lat", "to_lng",
                                "duration_seconds", "distance_meters"}
                if not expected_cols.issubset(set(reader.fieldnames or [])):
                    errors.append(f"Missing columns. Expected: {expected_cols}")

                for row in reader:
                    row_count += 1

                    try:
                        from_lat = float(row["from_lat"])
                        from_lng = float(row["from_lng"])
                        to_lat = float(row["to_lat"])
                        to_lng = float(row["to_lng"])
                        duration = int(row["duration_seconds"])
                        distance = int(row["distance_meters"])

                        locations_seen.add((from_lat, from_lng))
                        locations_seen.add((to_lat, to_lng))

                        # Validate bounds
                        if duration < 0:
                            errors.append(f"Row {row_count}: negative duration")
                        if duration > self.config.max_duration_seconds:
                            warnings.append(f"Row {row_count}: duration exceeds 24h")

                        if distance < 0:
                            errors.append(f"Row {row_count}: negative distance")
                        if distance > self.config.max_distance_meters:
                            warnings.append(f"Row {row_count}: distance exceeds 1000km")

                    except (ValueError, KeyError) as e:
                        errors.append(f"Row {row_count}: invalid data - {e}")

        except Exception as e:
            errors.append(f"Failed to read CSV: {e}")
            return MatrixValidationResult(
                valid=False,
                csv_path=csv_path,
                row_count=0,
                location_count=0,
                content_hash="",
                errors=errors,
            )

        # Check completeness
        n = len(locations_seen)
        expected_rows = n * n
        if row_count != expected_rows:
            warnings.append(
                f"Row count mismatch: got {row_count}, expected {expected_rows} for {n} locations"
            )

        # Compute hash
        content_hash = self._compute_file_hash(csv_path)

        return MatrixValidationResult(
            valid=len(errors) == 0,
            csv_path=csv_path,
            row_count=row_count,
            location_count=n,
            content_hash=content_hash,
            errors=errors,
            warnings=warnings,
        )

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of file content."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
