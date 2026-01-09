# =============================================================================
# SOLVEREIGN Routing Pack - Travel Time Metadata
# =============================================================================
# Metadata tracking for travel time provenance and version control.
#
# Purpose:
# - Track which provider returned each travel time
# - Track version/hash of underlying data (matrix or OSRM map)
# - Track fallback usage for drift analysis
# - Enable reproducibility verification
# =============================================================================

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional, Dict, Any, List, Tuple


# =============================================================================
# TYPES
# =============================================================================

ProviderType = Literal["static_matrix", "osrm", "haversine", "fallback"]
FallbackLevel = Literal["H3", "ZONE", "GEOHASH", "PLZ", "HAVERSINE"]


# =============================================================================
# TRAVEL TIME METADATA
# =============================================================================

@dataclass(frozen=True)
class TTMeta:
    """
    Metadata for a single travel time result.

    Tracks provenance of the travel time data:
    - Which provider returned the result
    - Version/hash of the underlying data
    - Whether fallback was used
    - Performance metrics (timing, cache)

    This metadata is critical for:
    - Drift detection (comparing matrix vs OSRM)
    - Evidence tracking (which data version was used)
    - Debug/troubleshooting (why was fallback used?)
    """

    # Provider identification
    provider: ProviderType
    version: str  # matrix_version for static, osrm_map_hash for OSRM

    # OSRM-specific
    profile: Optional[str] = None  # "car", "truck", etc.

    # Timeout/fallback tracking
    timed_out: bool = False
    fallback_level: Optional[FallbackLevel] = None
    fallback_reason: Optional[str] = None

    # Performance tracking
    request_time_ms: float = 0.0
    cache_hit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "provider": self.provider,
            "version": self.version,
            "profile": self.profile,
            "timed_out": self.timed_out,
            "fallback_level": self.fallback_level,
            "fallback_reason": self.fallback_reason,
            "request_time_ms": self.request_time_ms,
            "cache_hit": self.cache_hit,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TTMeta:
        """Create from dictionary."""
        return cls(
            provider=data.get("provider", "static_matrix"),
            version=data.get("version", "unknown"),
            profile=data.get("profile"),
            timed_out=data.get("timed_out", False),
            fallback_level=data.get("fallback_level"),
            fallback_reason=data.get("fallback_reason"),
            request_time_ms=data.get("request_time_ms", 0.0),
            cache_hit=data.get("cache_hit", False),
        )


# =============================================================================
# STATIC MATRIX VERSION
# =============================================================================

@dataclass
class StaticMatrixVersion:
    """
    Version information for a static matrix.

    Used for:
    - Evidence tracking (which matrix version was used)
    - Reproducibility (same version = same results)
    - Audit trail (when was this matrix loaded?)
    """

    version_id: str  # e.g., "wien_2026w02_v1"
    content_hash: str  # SHA256 of CSV content
    loaded_at: datetime
    row_count: int

    # Source tracking
    source_path: Optional[str] = None  # CSV file path
    osrm_map_hash: Optional[str] = None  # OSRM map used to generate matrix

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version_id": self.version_id,
            "content_hash": self.content_hash,
            "loaded_at": self.loaded_at.isoformat(),
            "row_count": self.row_count,
            "source_path": self.source_path,
            "osrm_map_hash": self.osrm_map_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StaticMatrixVersion:
        """Create from dictionary."""
        return cls(
            version_id=data["version_id"],
            content_hash=data["content_hash"],
            loaded_at=datetime.fromisoformat(data["loaded_at"]),
            row_count=data["row_count"],
            source_path=data.get("source_path"),
            osrm_map_hash=data.get("osrm_map_hash"),
        )

    @property
    def short_hash(self) -> str:
        """First 16 characters of content hash."""
        return self.content_hash[:16]


# =============================================================================
# EXTENDED RESULT TYPES
# =============================================================================

@dataclass
class TravelTimeResultWithMeta:
    """
    Travel time result with provenance metadata.

    Extends the basic TravelTimeResult with TTMeta for tracking.
    """

    origin: Tuple[float, float]
    destination: Tuple[float, float]
    duration_seconds: int
    distance_meters: int
    meta: TTMeta

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0

    @property
    def distance_km(self) -> float:
        return self.distance_meters / 1000.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "origin": list(self.origin),
            "destination": list(self.destination),
            "duration_seconds": self.duration_seconds,
            "distance_meters": self.distance_meters,
            "meta": self.meta.to_dict(),
        }


@dataclass
class MatrixResultWithMeta:
    """
    Matrix result with per-leg metadata.

    Extends the basic MatrixResult with TTMeta for each leg.
    """

    locations: List[Tuple[float, float]]
    time_matrix: List[List[int]]  # [from][to] in seconds
    distance_matrix: List[List[int]]  # [from][to] in meters
    meta_matrix: List[List[TTMeta]]  # [from][to] metadata
    matrix_version: StaticMatrixVersion
    is_symmetric: bool = False

    @property
    def size(self) -> int:
        return len(self.locations)

    @property
    def total_legs(self) -> int:
        return self.size * self.size

    @property
    def fallback_count(self) -> int:
        """Count of legs that used fallback."""
        count = 0
        for row in self.meta_matrix:
            for meta in row:
                if meta.fallback_level is not None:
                    count += 1
        return count

    @property
    def fallback_rate(self) -> float:
        """Percentage of legs using fallback."""
        if self.total_legs == 0:
            return 0.0
        return self.fallback_count / self.total_legs

    def get_time(self, from_idx: int, to_idx: int) -> int:
        """Get travel time between two locations by index."""
        return self.time_matrix[from_idx][to_idx]

    def get_distance(self, from_idx: int, to_idx: int) -> int:
        """Get distance between two locations by index."""
        return self.distance_matrix[from_idx][to_idx]

    def get_meta(self, from_idx: int, to_idx: int) -> TTMeta:
        """Get metadata for a specific leg."""
        return self.meta_matrix[from_idx][to_idx]


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_static_matrix_meta(
    version: StaticMatrixVersion,
    fallback_level: Optional[FallbackLevel] = None,
    fallback_reason: Optional[str] = None,
    request_time_ms: float = 0.0,
) -> TTMeta:
    """Create TTMeta for static matrix provider."""
    return TTMeta(
        provider="static_matrix",
        version=version.version_id,
        profile=None,
        timed_out=False,
        fallback_level=fallback_level,
        fallback_reason=fallback_reason,
        request_time_ms=request_time_ms,
        cache_hit=True,  # Static matrix is always "cached" in memory
    )


def create_osrm_meta(
    osrm_map_hash: str,
    profile: str = "car",
    timed_out: bool = False,
    request_time_ms: float = 0.0,
    cache_hit: bool = False,
) -> TTMeta:
    """Create TTMeta for OSRM provider."""
    return TTMeta(
        provider="osrm",
        version=osrm_map_hash,
        profile=profile,
        timed_out=timed_out,
        fallback_level=None,
        fallback_reason=None,
        request_time_ms=request_time_ms,
        cache_hit=cache_hit,
    )


def create_haversine_meta(
    reason: str = "MATRIX_MISS",
    version: str = "haversine_v1",
) -> TTMeta:
    """Create TTMeta for Haversine fallback."""
    return TTMeta(
        provider="haversine",
        version=version,
        profile=None,
        timed_out=False,
        fallback_level="HAVERSINE",
        fallback_reason=reason,
        request_time_ms=0.0,
        cache_hit=False,
    )


# =============================================================================
# VERSION HASH UTILITIES
# =============================================================================

def compute_content_hash(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of file content."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_matrix_hash(time_matrix: List[List[int]], distance_matrix: List[List[int]]) -> str:
    """Compute SHA256 hash of matrix data."""
    data = json.dumps({
        "time": time_matrix,
        "distance": distance_matrix,
    }, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()
