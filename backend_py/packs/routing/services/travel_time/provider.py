# =============================================================================
# SOLVEREIGN Routing Pack - Travel Time Provider Interface
# =============================================================================
# Abstract interface for travel time data sources.
#
# Implementations:
# - StaticMatrixProvider: CSV/DB-based static matrix (V1 Pilot)
# - OSRMProvider: OSRM API Integration (Production)
# - GoogleProvider: Google Maps API (Premium)
# =============================================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Tuple, List, Optional


@dataclass
class TravelTimeResult:
    """Result of a travel time query."""
    origin: Tuple[float, float]          # (lat, lng)
    destination: Tuple[float, float]     # (lat, lng)
    duration_seconds: int                # Travel time in seconds
    distance_meters: int                 # Distance in meters

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0

    @property
    def distance_km(self) -> float:
        return self.distance_meters / 1000.0


@dataclass
class MatrixResult:
    """Result of a matrix query."""
    locations: List[Tuple[float, float]]
    time_matrix: List[List[int]]         # [from][to] in seconds
    distance_matrix: List[List[int]]     # [from][to] in meters
    is_symmetric: bool = True            # Symmetric matrix (A->B == B->A)

    @property
    def size(self) -> int:
        return len(self.locations)

    def get_time(self, from_idx: int, to_idx: int) -> int:
        """Get travel time between two locations by index."""
        return self.time_matrix[from_idx][to_idx]

    def get_distance(self, from_idx: int, to_idx: int) -> int:
        """Get distance between two locations by index."""
        return self.distance_matrix[from_idx][to_idx]


class TravelTimeProvider(ABC):
    """
    Abstract interface for travel time data sources.

    Implementations must be:
    - Thread-safe (for concurrent solver access)
    - Cacheable (provider manages its own cache or uses external cache)
    - Fail-graceful (return estimates on API failure)
    """

    @abstractmethod
    def get_travel_time(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> TravelTimeResult:
        """
        Get travel time and distance between two points.

        Args:
            origin: (lat, lng) of origin
            destination: (lat, lng) of destination

        Returns:
            TravelTimeResult with duration and distance

        Raises:
            TravelTimeError: On unrecoverable errors
        """
        pass

    @abstractmethod
    def get_matrix(
        self,
        locations: List[Tuple[float, float]]
    ) -> MatrixResult:
        """
        Get travel time and distance matrix for multiple locations.

        Args:
            locations: List of (lat, lng) coordinates

        Returns:
            MatrixResult with time_matrix and distance_matrix

        Raises:
            TravelTimeError: On unrecoverable errors
        """
        pass

    def get_travel_time_minutes(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> int:
        """Convenience method: get travel time in minutes (rounded)."""
        result = self.get_travel_time(origin, destination)
        return round(result.duration_seconds / 60)

    def get_distance_km(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> float:
        """Convenience method: get distance in kilometers."""
        result = self.get_travel_time(origin, destination)
        return result.distance_meters / 1000.0

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the provider is healthy and ready."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider for logging."""
        pass


class TravelTimeError(Exception):
    """Error from travel time provider."""

    def __init__(
        self,
        message: str,
        provider: str,
        origin: Optional[Tuple[float, float]] = None,
        destination: Optional[Tuple[float, float]] = None,
        is_retryable: bool = False
    ):
        super().__init__(message)
        self.provider = provider
        self.origin = origin
        self.destination = destination
        self.is_retryable = is_retryable


class TravelTimeProviderFactory:
    """Factory for creating travel time providers."""

    _providers: dict[str, type] = {}

    @classmethod
    def register(cls, name: str, provider_class: type):
        """Register a provider class."""
        cls._providers[name] = provider_class

    @classmethod
    def create(cls, name: str, **kwargs) -> TravelTimeProvider:
        """Create a provider by name."""
        if name not in cls._providers:
            raise ValueError(f"Unknown provider: {name}. Available: {list(cls._providers.keys())}")
        return cls._providers[name](**kwargs)

    @classmethod
    def available_providers(cls) -> List[str]:
        """List available provider names."""
        return list(cls._providers.keys())
