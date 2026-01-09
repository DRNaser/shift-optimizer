# =============================================================================
# SOLVEREIGN Routing Pack - OSRM Provider
# =============================================================================
# Open Source Routing Machine (OSRM) travel time provider.
#
# Features:
# - HTTP API integration with OSRM backend
# - Redis caching for matrix results
# - Batch matrix requests (table service)
# - Fallback to Haversine on API failure
# - Health check with circuit breaker
#
# V3.5 Features:
# - Finalize mode for post-solve validation (strict timeouts, no fallback)
# - OSRMStatus for map version tracking
# - get_consecutive_times() for per-leg timing
# - TTMeta provenance tracking
# =============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Tuple, List, Optional, Dict, Any
from urllib.parse import urljoin
import math

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from .provider import (
    TravelTimeProvider,
    TravelTimeResult,
    MatrixResult,
    TravelTimeError,
    TravelTimeProviderFactory,
)
from .tt_meta import (
    TTMeta,
    TravelTimeResultWithMeta,
    create_osrm_meta,
    create_haversine_meta,
)

logger = logging.getLogger(__name__)


@dataclass
class OSRMConfig:
    """Configuration for OSRM provider."""
    # OSRM Server
    base_url: str = "http://localhost:5000"
    profile: str = "driving"              # driving, cycling, walking

    # Timeouts
    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0

    # Caching
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600 * 24    # 24 hours
    redis_url: Optional[str] = None       # redis://localhost:6379/0

    # Fallback
    use_haversine_fallback: bool = True
    average_speed_kmh: float = 30.0       # Fallback speed

    # Circuit breaker
    circuit_breaker_threshold: int = 5    # Failures before opening
    circuit_breaker_timeout: int = 60     # Seconds before retry

    # Batch settings
    max_batch_size: int = 100             # Max locations per matrix request

    # V3.5: Finalize mode settings
    finalize_mode: bool = False           # Enable strict finalize mode
    finalize_timeout_seconds: float = 5.0 # Shorter timeout for finalize
    finalize_connect_timeout: float = 2.0 # Shorter connect timeout for finalize
    no_fallback_in_finalize: bool = True  # Disable fallback in finalize mode


@dataclass
class OSRMStatus:
    """
    OSRM server status information for evidence tracking.

    Used to pin the exact OSRM map version in evidence packs.
    """
    map_hash: str           # Hash derived from data_timestamp or status
    profile: str            # "driving", "cycling", etc.
    algorithm: str          # "MLD" or "CH"
    data_timestamp: Optional[str] = None  # OSRM data timestamp if available
    status_json: Optional[Dict[str, Any]] = None  # Full status response
    retrieved_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "map_hash": self.map_hash,
            "profile": self.profile,
            "algorithm": self.algorithm,
            "data_timestamp": self.data_timestamp,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


@dataclass
class ConsecutiveTimesResult:
    """
    Result of get_consecutive_times() for route validation.

    Contains per-leg travel times for a sequence of waypoints.
    """
    waypoints: List[Tuple[float, float]]
    leg_durations: List[int]      # Duration in seconds for each leg
    leg_distances: List[int]      # Distance in meters for each leg
    total_duration: int           # Total route duration
    total_distance: int           # Total route distance
    timed_out: bool = False       # True if request timed out
    used_fallback: bool = False   # True if any leg used fallback
    meta: Optional[TTMeta] = None # Provenance metadata


@dataclass
class CircuitBreakerState:
    """Circuit breaker state for OSRM API."""
    failures: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False


class OSRMProvider(TravelTimeProvider):
    """
    OSRM-based travel time provider.

    Uses OSRM HTTP API for accurate road-based travel times.
    Includes Redis caching and circuit breaker for resilience.

    V3.5 Features:
    - Finalize mode with strict timeouts (no fallback)
    - OSRMStatus for map version tracking
    - get_consecutive_times() for per-leg timing
    """

    def __init__(self, config: OSRMConfig):
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx is required for OSRMProvider. Install with: pip install httpx")

        self.config = config
        self._client: Optional[httpx.Client] = None
        self._redis: Optional[Any] = None
        self._circuit_breaker = CircuitBreakerState()
        self._osrm_status: Optional[OSRMStatus] = None

        # Initialize HTTP client
        self._init_client()

        # Initialize Redis if enabled
        if config.cache_enabled and config.redis_url and REDIS_AVAILABLE:
            self._init_redis()

    def _init_client(self):
        """Initialize HTTP client."""
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(
                self.config.timeout_seconds,
                connect=self.config.connect_timeout_seconds
            ),
        )

    def _init_redis(self):
        """Initialize Redis connection."""
        try:
            self._redis = redis.from_url(self.config.redis_url)
            self._redis.ping()
            logger.info(f"Redis cache connected: {self.config.redis_url}")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Caching disabled.")
            self._redis = None

    @property
    def provider_name(self) -> str:
        return "osrm"

    def health_check(self) -> bool:
        """Check OSRM server health."""
        if self._circuit_breaker.is_open:
            # Check if timeout has elapsed
            if time.time() - self._circuit_breaker.last_failure_time > self.config.circuit_breaker_timeout:
                self._circuit_breaker.is_open = False
                self._circuit_breaker.failures = 0
            else:
                return False

        try:
            response = self._client.get(
                f"/route/v1/{self.config.profile}/13.388860,52.517037;13.397634,52.529407",
                params={"overview": "false"}
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"OSRM health check failed: {e}")
            return False

    # =========================================================================
    # V3.5: Status and Finalize Mode Methods
    # =========================================================================

    def get_osrm_status(self, force_refresh: bool = False) -> OSRMStatus:
        """
        Get OSRM server status for evidence tracking.

        Retrieves map version information from OSRM status endpoint.
        Caches the result unless force_refresh is True.

        Returns:
            OSRMStatus with map_hash, profile, algorithm info

        Raises:
            TravelTimeError if OSRM is unreachable
        """
        if self._osrm_status and not force_refresh:
            return self._osrm_status

        try:
            response = self._client.get("/status")
            response.raise_for_status()
            data = response.json()

            # Extract data_timestamp if available
            data_timestamp = data.get("data_timestamp")

            # Compute map hash from status
            if data_timestamp:
                map_hash = hashlib.sha256(data_timestamp.encode()).hexdigest()[:16]
            else:
                # Fallback: hash the entire status response
                map_hash = hashlib.sha256(
                    json.dumps(data, sort_keys=True).encode()
                ).hexdigest()[:16]

            self._osrm_status = OSRMStatus(
                map_hash=map_hash,
                profile=self.config.profile,
                algorithm=data.get("algorithm", "unknown"),
                data_timestamp=data_timestamp,
                status_json=data,
                retrieved_at=datetime.now(),
            )

            return self._osrm_status

        except httpx.HTTPError as e:
            raise TravelTimeError(
                f"Failed to get OSRM status: {e}",
                provider=self.provider_name,
                is_retryable=True,
            )

    @property
    def map_hash(self) -> str:
        """Get OSRM map hash (fetches status if not cached)."""
        try:
            status = self.get_osrm_status()
            return status.map_hash
        except TravelTimeError:
            return "unknown"

    def get_consecutive_times(
        self,
        waypoints: List[Tuple[float, float]],
        timeout_override: Optional[float] = None
    ) -> ConsecutiveTimesResult:
        """
        Get travel times for consecutive legs of a route.

        Used for OSRM-Finalize to validate routes. Returns per-leg
        durations/distances for drift analysis.

        Args:
            waypoints: List of (lat, lng) coordinates in route order
            timeout_override: Override timeout (for finalize mode)

        Returns:
            ConsecutiveTimesResult with per-leg times and distances
        """
        if len(waypoints) < 2:
            return ConsecutiveTimesResult(
                waypoints=waypoints,
                leg_durations=[],
                leg_distances=[],
                total_duration=0,
                total_distance=0,
                timed_out=False,
                used_fallback=False,
            )

        start_time = time.perf_counter()

        # Use finalize timeouts if in finalize mode or override provided
        effective_timeout = timeout_override
        if effective_timeout is None:
            if self.config.finalize_mode:
                effective_timeout = self.config.finalize_timeout_seconds
            else:
                effective_timeout = self.config.timeout_seconds

        # Build coordinates string (OSRM uses lng,lat!)
        coords_str = ";".join(f"{loc[1]},{loc[0]}" for loc in waypoints)

        try:
            # Create client with specific timeout for this request
            with httpx.Client(
                base_url=self.config.base_url,
                timeout=httpx.Timeout(effective_timeout, connect=self.config.finalize_connect_timeout)
            ) as client:
                response = client.get(
                    f"/route/v1/{self.config.profile}/{coords_str}",
                    params={
                        "overview": "false",
                        "steps": "false",
                        "annotations": "duration,distance"
                    }
                )
                response.raise_for_status()

            data = response.json()
            if data.get("code") != "Ok":
                raise TravelTimeError(
                    f"OSRM route error: {data.get('code')}",
                    provider=self.provider_name,
                    is_retryable=True
                )

            # Extract leg durations and distances
            route = data["routes"][0]
            legs = route.get("legs", [])

            leg_durations = [int(leg["duration"]) for leg in legs]
            leg_distances = [int(leg["distance"]) for leg in legs]

            # Create metadata
            request_time_ms = (time.perf_counter() - start_time) * 1000
            meta = create_osrm_meta(
                osrm_map_hash=self.map_hash,
                profile=self.config.profile,
                timed_out=False,
                request_time_ms=request_time_ms,
                cache_hit=False,
            )

            return ConsecutiveTimesResult(
                waypoints=waypoints,
                leg_durations=leg_durations,
                leg_distances=leg_distances,
                total_duration=int(route["duration"]),
                total_distance=int(route["distance"]),
                timed_out=False,
                used_fallback=False,
                meta=meta,
            )

        except httpx.TimeoutException:
            request_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"OSRM consecutive times timed out after {request_time_ms:.1f}ms")

            # In finalize mode with no_fallback, return timeout result
            if self.config.finalize_mode and self.config.no_fallback_in_finalize:
                meta = create_osrm_meta(
                    osrm_map_hash=self.map_hash,
                    profile=self.config.profile,
                    timed_out=True,
                    request_time_ms=request_time_ms,
                    cache_hit=False,
                )
                return ConsecutiveTimesResult(
                    waypoints=waypoints,
                    leg_durations=[],
                    leg_distances=[],
                    total_duration=0,
                    total_distance=0,
                    timed_out=True,
                    used_fallback=False,
                    meta=meta,
                )

            # Fall back to Haversine
            return self._haversine_consecutive_fallback(waypoints)

        except httpx.HTTPError as e:
            self._record_failure()
            logger.error(f"OSRM consecutive times failed: {e}")

            # In finalize mode with no_fallback, raise error
            if self.config.finalize_mode and self.config.no_fallback_in_finalize:
                raise TravelTimeError(
                    f"OSRM request failed in finalize mode: {e}",
                    provider=self.provider_name,
                    is_retryable=True,
                )

            # Fall back to Haversine
            return self._haversine_consecutive_fallback(waypoints)

    def _haversine_consecutive_fallback(
        self,
        waypoints: List[Tuple[float, float]]
    ) -> ConsecutiveTimesResult:
        """Build consecutive times using Haversine fallback."""
        leg_durations = []
        leg_distances = []

        for i in range(len(waypoints) - 1):
            distance_km = self._haversine_distance_km(waypoints[i], waypoints[i + 1])
            distance_meters = int(distance_km * 1000)
            hours = distance_km / self.config.average_speed_kmh
            duration_seconds = int(hours * 3600)

            leg_durations.append(duration_seconds)
            leg_distances.append(distance_meters)

        meta = create_haversine_meta(
            reason="OSRM_FALLBACK",
            version=self.map_hash,
        )

        return ConsecutiveTimesResult(
            waypoints=waypoints,
            leg_durations=leg_durations,
            leg_distances=leg_distances,
            total_duration=sum(leg_durations),
            total_distance=sum(leg_distances),
            timed_out=False,
            used_fallback=True,
            meta=meta,
        )

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

        # Check cache
        cache_key = self._cache_key_route(origin, destination)
        cached = self._get_cached(cache_key)
        if cached:
            return TravelTimeResult(
                origin=origin,
                destination=destination,
                duration_seconds=cached["duration"],
                distance_meters=cached["distance"]
            )

        # Check circuit breaker
        if self._circuit_breaker.is_open:
            if self.config.use_haversine_fallback:
                return self._haversine_fallback(origin, destination)
            raise TravelTimeError(
                "OSRM circuit breaker open",
                provider=self.provider_name,
                origin=origin,
                destination=destination,
                is_retryable=True
            )

        # Call OSRM route service
        try:
            # OSRM uses lng,lat order!
            coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
            response = self._client.get(
                f"/route/v1/{self.config.profile}/{coords}",
                params={"overview": "false"}
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") != "Ok":
                raise TravelTimeError(
                    f"OSRM error: {data.get('code')}",
                    provider=self.provider_name,
                    origin=origin,
                    destination=destination,
                    is_retryable=True
                )

            route = data["routes"][0]
            duration = int(route["duration"])
            distance = int(route["distance"])

            # Cache result
            self._set_cached(cache_key, {"duration": duration, "distance": distance})

            # Reset circuit breaker on success
            self._circuit_breaker.failures = 0

            return TravelTimeResult(
                origin=origin,
                destination=destination,
                duration_seconds=duration,
                distance_meters=distance
            )

        except httpx.HTTPError as e:
            self._record_failure()
            logger.error(f"OSRM request failed: {e}")

            if self.config.use_haversine_fallback:
                return self._haversine_fallback(origin, destination)

            raise TravelTimeError(
                f"OSRM request failed: {e}",
                provider=self.provider_name,
                origin=origin,
                destination=destination,
                is_retryable=True
            )

    def get_matrix(
        self,
        locations: List[Tuple[float, float]]
    ) -> MatrixResult:
        """Get travel time matrix using OSRM table service."""
        n = len(locations)

        if n == 0:
            return MatrixResult(
                locations=[],
                time_matrix=[],
                distance_matrix=[],
                is_symmetric=True
            )

        # Check cache for full matrix
        cache_key = self._cache_key_matrix(locations)
        cached = self._get_cached(cache_key)
        if cached:
            return MatrixResult(
                locations=locations,
                time_matrix=cached["time_matrix"],
                distance_matrix=cached["distance_matrix"],
                is_symmetric=False
            )

        # Check circuit breaker
        if self._circuit_breaker.is_open:
            if self.config.use_haversine_fallback:
                return self._haversine_matrix(locations)
            raise TravelTimeError(
                "OSRM circuit breaker open",
                provider=self.provider_name,
                is_retryable=True
            )

        # Build coordinates string (OSRM uses lng,lat!)
        coords_str = ";".join(f"{loc[1]},{loc[0]}" for loc in locations)

        try:
            response = self._client.get(
                f"/table/v1/{self.config.profile}/{coords_str}",
                params={
                    "annotations": "duration,distance"
                }
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") != "Ok":
                raise TravelTimeError(
                    f"OSRM table error: {data.get('code')}",
                    provider=self.provider_name,
                    is_retryable=True
                )

            # Extract matrices
            time_matrix = [
                [int(d) if d is not None else 0 for d in row]
                for row in data["durations"]
            ]

            # OSRM may not return distances in table, handle gracefully
            if "distances" in data:
                distance_matrix = [
                    [int(d) if d is not None else 0 for d in row]
                    for row in data["distances"]
                ]
            else:
                # Estimate from time (assume average speed)
                distance_matrix = [
                    [int(t * self.config.average_speed_kmh * 1000 / 3600) for t in row]
                    for row in time_matrix
                ]

            # Cache result
            self._set_cached(cache_key, {
                "time_matrix": time_matrix,
                "distance_matrix": distance_matrix
            })

            # Reset circuit breaker
            self._circuit_breaker.failures = 0

            return MatrixResult(
                locations=locations,
                time_matrix=time_matrix,
                distance_matrix=distance_matrix,
                is_symmetric=False
            )

        except httpx.HTTPError as e:
            self._record_failure()
            logger.error(f"OSRM table request failed: {e}")

            if self.config.use_haversine_fallback:
                return self._haversine_matrix(locations)

            raise TravelTimeError(
                f"OSRM table request failed: {e}",
                provider=self.provider_name,
                is_retryable=True
            )

    # =========================================================================
    # Caching
    # =========================================================================

    def _cache_key_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> str:
        """Generate cache key for a route."""
        data = f"{origin[0]:.6f},{origin[1]:.6f}|{destination[0]:.6f},{destination[1]:.6f}"
        return f"osrm:route:{hashlib.md5(data.encode()).hexdigest()}"

    def _cache_key_matrix(self, locations: List[Tuple[float, float]]) -> str:
        """Generate cache key for a matrix."""
        data = "|".join(f"{loc[0]:.6f},{loc[1]:.6f}" for loc in locations)
        return f"osrm:matrix:{hashlib.md5(data.encode()).hexdigest()}"

    def _get_cached(self, key: str) -> Optional[Dict]:
        """Get cached value."""
        if not self._redis:
            return None

        try:
            data = self._redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")

        return None

    def _set_cached(self, key: str, value: Dict):
        """Set cached value."""
        if not self._redis:
            return

        try:
            self._redis.setex(
                key,
                self.config.cache_ttl_seconds,
                json.dumps(value)
            )
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")

    # =========================================================================
    # Circuit Breaker
    # =========================================================================

    def _record_failure(self):
        """Record API failure for circuit breaker."""
        self._circuit_breaker.failures += 1
        self._circuit_breaker.last_failure_time = time.time()

        if self._circuit_breaker.failures >= self.config.circuit_breaker_threshold:
            self._circuit_breaker.is_open = True
            logger.warning(
                f"OSRM circuit breaker opened after {self._circuit_breaker.failures} failures"
            )

    # =========================================================================
    # Fallback
    # =========================================================================

    def _is_same_point(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        tolerance_km: float = 0.05
    ) -> bool:
        """Check if two points are the same."""
        return self._haversine_distance_km(p1, p2) < tolerance_km

    def _haversine_fallback(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> TravelTimeResult:
        """Calculate travel time using Haversine."""
        distance_km = self._haversine_distance_km(origin, destination)
        distance_meters = int(distance_km * 1000)
        hours = distance_km / self.config.average_speed_kmh
        duration_seconds = int(hours * 3600)

        return TravelTimeResult(
            origin=origin,
            destination=destination,
            duration_seconds=duration_seconds,
            distance_meters=distance_meters
        )

    def _haversine_matrix(
        self,
        locations: List[Tuple[float, float]]
    ) -> MatrixResult:
        """Build matrix using Haversine."""
        n = len(locations)
        time_matrix = [[0] * n for _ in range(n)]
        distance_matrix = [[0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                result = self._haversine_fallback(locations[i], locations[j])
                time_matrix[i][j] = result.duration_seconds
                distance_matrix[i][j] = result.distance_meters

        return MatrixResult(
            locations=locations,
            time_matrix=time_matrix,
            distance_matrix=distance_matrix,
            is_symmetric=True
        )

    def _haversine_distance_km(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float]
    ) -> float:
        """Calculate Haversine distance in km."""
        R = 6371.0
        lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
        lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    def close(self):
        """Close HTTP client."""
        if self._client:
            self._client.close()


# Register with factory
TravelTimeProviderFactory.register("osrm", OSRMProvider)
