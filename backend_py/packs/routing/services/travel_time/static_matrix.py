# =============================================================================
# SOLVEREIGN Routing Pack - Static Matrix Provider
# =============================================================================
# CSV/DB-based static travel time matrix for V1 Pilot.
#
# Features:
# - Load from CSV file
# - Load from database
# - Haversine fallback for missing pairs
# - Zone-based grouping for large matrices
# - Version tracking for reproducibility (V3.5)
# - TTMeta provenance tracking (V3.5)
# =============================================================================

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple, List, Dict, Optional
from pathlib import Path

from .provider import (
    TravelTimeProvider,
    TravelTimeResult,
    MatrixResult,
    TravelTimeError,
    TravelTimeProviderFactory,
)
from .tt_meta import (
    TTMeta,
    StaticMatrixVersion,
    TravelTimeResultWithMeta,
    MatrixResultWithMeta,
    create_static_matrix_meta,
    create_haversine_meta,
    compute_file_hash,
)


@dataclass
class StaticMatrixConfig:
    """Configuration for StaticMatrixProvider."""
    # Data source
    csv_path: Optional[str] = None       # Path to CSV file
    db_table: Optional[str] = None       # Database table name

    # Fallback settings
    use_haversine_fallback: bool = True  # Use Haversine for missing pairs
    average_speed_kmh: float = 30.0      # Average speed for Haversine fallback

    # Coordinate matching
    coordinate_precision: int = 4        # Decimal places for matching
    max_distance_tolerance_km: float = 0.5  # Max distance to consider "same" point


class StaticMatrixProvider(TravelTimeProvider):
    """
    Static matrix-based travel time provider.

    Loads travel times from CSV or database. Uses Haversine distance
    as fallback for coordinate pairs not in the matrix.

    V3.5 Features:
    - Version tracking with content hash
    - TTMeta provenance for each travel time result
    - Fallback level tracking (HAVERSINE)
    """

    def __init__(self, config: StaticMatrixConfig):
        self.config = config
        self._matrix: Dict[Tuple[str, str], Tuple[int, int]] = {}  # (from, to) -> (seconds, meters)
        self._coord_to_key: Dict[Tuple[float, float], str] = {}    # rounded coord -> key
        self._is_loaded = False
        self._version: Optional[StaticMatrixVersion] = None
        self._source_path: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return "static_matrix"

    @property
    def matrix_version(self) -> Optional[StaticMatrixVersion]:
        """Get the current matrix version information."""
        return self._version

    @property
    def version_id(self) -> str:
        """Get the version ID or 'unknown' if not loaded."""
        return self._version.version_id if self._version else "unknown"

    def health_check(self) -> bool:
        return self._is_loaded and len(self._matrix) > 0

    def load_from_csv(
        self,
        csv_path: str,
        version_id: Optional[str] = None,
        osrm_map_hash: Optional[str] = None
    ) -> int:
        """
        Load matrix from CSV file with version tracking.

        Expected CSV format:
        from_lat,from_lng,to_lat,to_lng,duration_seconds,distance_meters

        Args:
            csv_path: Path to CSV file
            version_id: Optional version identifier (defaults to filename without extension)
            osrm_map_hash: Optional hash of OSRM map used to generate this matrix

        Returns:
            Number of entries loaded
        """
        path = Path(csv_path)
        if not path.exists():
            raise TravelTimeError(
                f"CSV file not found: {csv_path}",
                provider=self.provider_name,
                is_retryable=False
            )

        # Store source path for tracking
        self._source_path = str(path.absolute())

        # Compute content hash before loading
        content_hash = compute_file_hash(str(path))

        # Generate version_id from filename if not provided
        if version_id is None:
            version_id = path.stem  # filename without extension

        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                from_key = self._coord_to_key_str(
                    float(row['from_lat']),
                    float(row['from_lng'])
                )
                to_key = self._coord_to_key_str(
                    float(row['to_lat']),
                    float(row['to_lng'])
                )

                duration = int(row['duration_seconds'])
                distance = int(row['distance_meters'])

                self._matrix[(from_key, to_key)] = (duration, distance)

                # Store coordinate -> key mapping
                self._coord_to_key[(
                    round(float(row['from_lat']), self.config.coordinate_precision),
                    round(float(row['from_lng']), self.config.coordinate_precision)
                )] = from_key
                self._coord_to_key[(
                    round(float(row['to_lat']), self.config.coordinate_precision),
                    round(float(row['to_lng']), self.config.coordinate_precision)
                )] = to_key

                count += 1

        # Create version information
        self._version = StaticMatrixVersion(
            version_id=version_id,
            content_hash=content_hash,
            loaded_at=datetime.now(),
            row_count=count,
            source_path=self._source_path,
            osrm_map_hash=osrm_map_hash,
        )

        self._is_loaded = True
        return count

    def load_from_entries(
        self,
        entries: List[Dict],
        version_id: str = "memory",
        osrm_map_hash: Optional[str] = None
    ) -> int:
        """
        Load matrix from list of entries with version tracking.

        Each entry should have:
        - from_lat, from_lng: Origin coordinates
        - to_lat, to_lng: Destination coordinates
        - duration_seconds: Travel time
        - distance_meters: Distance

        Args:
            entries: List of travel time entries
            version_id: Version identifier (defaults to "memory")
            osrm_map_hash: Optional hash of OSRM map used to generate entries

        Returns:
            Number of entries loaded
        """
        count = 0
        # Build content for hash computation
        hash_content = []

        for entry in entries:
            from_key = self._coord_to_key_str(
                entry['from_lat'],
                entry['from_lng']
            )
            to_key = self._coord_to_key_str(
                entry['to_lat'],
                entry['to_lng']
            )

            self._matrix[(from_key, to_key)] = (
                entry['duration_seconds'],
                entry['distance_meters']
            )

            # Store coordinate -> key mapping
            self._coord_to_key[(
                round(entry['from_lat'], self.config.coordinate_precision),
                round(entry['from_lng'], self.config.coordinate_precision)
            )] = from_key
            self._coord_to_key[(
                round(entry['to_lat'], self.config.coordinate_precision),
                round(entry['to_lng'], self.config.coordinate_precision)
            )] = to_key

            # Build hash content
            hash_content.append(
                f"{from_key}|{to_key}|{entry['duration_seconds']}|{entry['distance_meters']}"
            )
            count += 1

        # Compute content hash from entries
        content_hash = hashlib.sha256(
            "\n".join(sorted(hash_content)).encode()
        ).hexdigest()

        # Create version information
        self._version = StaticMatrixVersion(
            version_id=version_id,
            content_hash=content_hash,
            loaded_at=datetime.now(),
            row_count=count,
            source_path=None,  # No file source
            osrm_map_hash=osrm_map_hash,
        )

        self._is_loaded = True
        return count

    def get_travel_time(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> TravelTimeResult:
        """Get travel time between two points."""

        # Same point check
        if self._is_same_point(origin, destination):
            return TravelTimeResult(
                origin=origin,
                destination=destination,
                duration_seconds=0,
                distance_meters=0
            )

        # Try to find in matrix
        from_key = self._find_key_for_coord(origin)
        to_key = self._find_key_for_coord(destination)

        if from_key and to_key:
            key = (from_key, to_key)
            if key in self._matrix:
                duration, distance = self._matrix[key]
                return TravelTimeResult(
                    origin=origin,
                    destination=destination,
                    duration_seconds=duration,
                    distance_meters=distance
                )

        # Fallback to Haversine
        if self.config.use_haversine_fallback:
            return self._haversine_fallback(origin, destination)

        raise TravelTimeError(
            f"No travel time data for route",
            provider=self.provider_name,
            origin=origin,
            destination=destination,
            is_retryable=False
        )

    def get_travel_time_with_meta(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> TravelTimeResultWithMeta:
        """
        Get travel time between two points with provenance metadata.

        Returns:
            TravelTimeResultWithMeta including TTMeta with provider info,
            version, and fallback level if applicable.
        """
        import time
        start_time = time.perf_counter()

        # Same point check
        if self._is_same_point(origin, destination):
            meta = create_static_matrix_meta(
                version=self._version or StaticMatrixVersion(
                    version_id="unknown",
                    content_hash="unknown",
                    loaded_at=datetime.now(),
                    row_count=0,
                ),
                request_time_ms=(time.perf_counter() - start_time) * 1000,
            )
            return TravelTimeResultWithMeta(
                origin=origin,
                destination=destination,
                duration_seconds=0,
                distance_meters=0,
                meta=meta,
            )

        # Try to find in matrix
        from_key = self._find_key_for_coord(origin)
        to_key = self._find_key_for_coord(destination)

        if from_key and to_key:
            key = (from_key, to_key)
            if key in self._matrix:
                duration, distance = self._matrix[key]
                meta = create_static_matrix_meta(
                    version=self._version or StaticMatrixVersion(
                        version_id="unknown",
                        content_hash="unknown",
                        loaded_at=datetime.now(),
                        row_count=0,
                    ),
                    request_time_ms=(time.perf_counter() - start_time) * 1000,
                )
                return TravelTimeResultWithMeta(
                    origin=origin,
                    destination=destination,
                    duration_seconds=duration,
                    distance_meters=distance,
                    meta=meta,
                )

        # Fallback to Haversine
        if self.config.use_haversine_fallback:
            return self._haversine_fallback_with_meta(origin, destination, start_time)

        raise TravelTimeError(
            f"No travel time data for route",
            provider=self.provider_name,
            origin=origin,
            destination=destination,
            is_retryable=False
        )

    def get_matrix(
        self,
        locations: List[Tuple[float, float]]
    ) -> MatrixResult:
        """Get travel time matrix for multiple locations."""
        n = len(locations)
        time_matrix = [[0] * n for _ in range(n)]
        distance_matrix = [[0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue

                result = self.get_travel_time(locations[i], locations[j])
                time_matrix[i][j] = result.duration_seconds
                distance_matrix[i][j] = result.distance_meters

        return MatrixResult(
            locations=locations,
            time_matrix=time_matrix,
            distance_matrix=distance_matrix,
            is_symmetric=False  # Matrix may not be symmetric (one-way streets)
        )

    def get_matrix_with_meta(
        self,
        locations: List[Tuple[float, float]]
    ) -> MatrixResultWithMeta:
        """
        Get travel time matrix for multiple locations with per-leg metadata.

        Returns:
            MatrixResultWithMeta including TTMeta for each leg, tracking
            which legs used fallback.
        """
        n = len(locations)
        time_matrix = [[0] * n for _ in range(n)]
        distance_matrix = [[0] * n for _ in range(n)]
        meta_matrix: List[List[TTMeta]] = []

        # Create default meta for self-loops
        default_meta = create_static_matrix_meta(
            version=self._version or StaticMatrixVersion(
                version_id="unknown",
                content_hash="unknown",
                loaded_at=datetime.now(),
                row_count=0,
            ),
        )

        for i in range(n):
            meta_row: List[TTMeta] = []
            for j in range(n):
                if i == j:
                    meta_row.append(default_meta)
                    continue

                result = self.get_travel_time_with_meta(locations[i], locations[j])
                time_matrix[i][j] = result.duration_seconds
                distance_matrix[i][j] = result.distance_meters
                meta_row.append(result.meta)

            meta_matrix.append(meta_row)

        return MatrixResultWithMeta(
            locations=locations,
            time_matrix=time_matrix,
            distance_matrix=distance_matrix,
            meta_matrix=meta_matrix,
            matrix_version=self._version or StaticMatrixVersion(
                version_id="unknown",
                content_hash="unknown",
                loaded_at=datetime.now(),
                row_count=0,
            ),
            is_symmetric=False,
        )

    def _coord_to_key_str(self, lat: float, lng: float) -> str:
        """Convert coordinates to string key."""
        return f"{round(lat, self.config.coordinate_precision)}:{round(lng, self.config.coordinate_precision)}"

    def _find_key_for_coord(self, coord: Tuple[float, float]) -> Optional[str]:
        """Find matrix key for a coordinate."""
        rounded = (
            round(coord[0], self.config.coordinate_precision),
            round(coord[1], self.config.coordinate_precision)
        )
        return self._coord_to_key.get(rounded)

    def _is_same_point(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float]
    ) -> bool:
        """Check if two points are the same (within tolerance)."""
        distance_km = self._haversine_distance_km(p1, p2)
        return distance_km < self.config.max_distance_tolerance_km

    def _haversine_fallback(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> TravelTimeResult:
        """Calculate travel time using Haversine distance."""
        distance_km = self._haversine_distance_km(origin, destination)
        distance_meters = int(distance_km * 1000)

        # Time = Distance / Speed
        hours = distance_km / self.config.average_speed_kmh
        duration_seconds = int(hours * 3600)

        return TravelTimeResult(
            origin=origin,
            destination=destination,
            duration_seconds=duration_seconds,
            distance_meters=distance_meters
        )

    def _haversine_fallback_with_meta(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        start_time: float
    ) -> TravelTimeResultWithMeta:
        """
        Calculate travel time using Haversine distance with metadata.

        Returns:
            TravelTimeResultWithMeta with fallback_level="HAVERSINE"
        """
        import time

        distance_km = self._haversine_distance_km(origin, destination)
        distance_meters = int(distance_km * 1000)

        # Time = Distance / Speed
        hours = distance_km / self.config.average_speed_kmh
        duration_seconds = int(hours * 3600)

        # Create haversine fallback metadata
        meta = create_haversine_meta(
            reason="MATRIX_MISS",
            version=self.version_id,
        )
        # Update request_time_ms manually since create_haversine_meta doesn't include it
        meta = TTMeta(
            provider="haversine",
            version=self.version_id,
            profile=None,
            timed_out=False,
            fallback_level="HAVERSINE",
            fallback_reason="MATRIX_MISS",
            request_time_ms=(time.perf_counter() - start_time) * 1000,
            cache_hit=False,
        )

        return TravelTimeResultWithMeta(
            origin=origin,
            destination=destination,
            duration_seconds=duration_seconds,
            distance_meters=distance_meters,
            meta=meta,
        )

    def _haversine_distance_km(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float]
    ) -> float:
        """
        Calculate Haversine distance between two points.

        Returns:
            Distance in kilometers
        """
        R = 6371.0  # Earth radius in km

        lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
        lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])

        dlat = lat2 - lat1
        dlng = lng2 - lng1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        return R * c

    def matrix_size(self) -> int:
        """Number of entries in the matrix."""
        return len(self._matrix)


# Register with factory
TravelTimeProviderFactory.register("static_matrix", StaticMatrixProvider)
