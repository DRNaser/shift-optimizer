# =============================================================================
# SOLVEREIGN Routing Pack - Travel Time Cache
# =============================================================================
# Caching layer for travel time providers.
#
# Supports:
# - In-memory cache (for single instance)
# - Redis cache (for distributed workers)
# =============================================================================

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict
import threading


@dataclass
class CacheEntry:
    """Cached travel time entry."""
    duration_seconds: int
    distance_meters: int
    cached_at: datetime
    ttl_seconds: int

    def is_expired(self) -> bool:
        """Check if entry is expired."""
        age = (datetime.now() - self.cached_at).total_seconds()
        return age > self.ttl_seconds


class TravelTimeCache(ABC):
    """Abstract cache interface for travel times."""

    @abstractmethod
    def get(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> Optional[CacheEntry]:
        """Get cached entry if exists and not expired."""
        pass

    @abstractmethod
    def set(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        duration_seconds: int,
        distance_meters: int,
        ttl_seconds: int = 86400  # 24 hours default
    ) -> None:
        """Cache a travel time entry."""
        pass

    @abstractmethod
    def invalidate(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> None:
        """Invalidate a cached entry."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all cached entries."""
        pass

    @staticmethod
    def make_key(
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        precision: int = 4
    ) -> str:
        """Create cache key from coordinates."""
        key_data = f"{round(origin[0], precision)}:{round(origin[1], precision)}->{round(destination[0], precision)}:{round(destination[1], precision)}"
        return hashlib.md5(key_data.encode()).hexdigest()


class InMemoryCache(TravelTimeCache):
    """
    In-memory cache for single-instance deployments.

    Thread-safe using RLock.
    """

    def __init__(self, max_size: int = 100_000):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._max_size = max_size

    def get(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> Optional[CacheEntry]:
        key = self.make_key(origin, destination)

        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_expired():
                return entry
            elif entry:
                # Remove expired entry
                del self._cache[key]
            return None

    def set(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        duration_seconds: int,
        distance_meters: int,
        ttl_seconds: int = 86400
    ) -> None:
        key = self.make_key(origin, destination)

        with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self._max_size:
                self._evict_oldest()

            self._cache[key] = CacheEntry(
                duration_seconds=duration_seconds,
                distance_meters=distance_meters,
                cached_at=datetime.now(),
                ttl_seconds=ttl_seconds
            )

    def invalidate(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> None:
        key = self.make_key(origin, destination)
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def _evict_oldest(self) -> None:
        """Evict oldest entries when at capacity."""
        if not self._cache:
            return

        # Sort by cached_at and remove oldest 10%
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k].cached_at
        )
        evict_count = max(1, len(sorted_keys) // 10)

        for key in sorted_keys[:evict_count]:
            del self._cache[key]

    def size(self) -> int:
        return len(self._cache)

    def hit_rate(self) -> float:
        """Return cache hit rate (stub - would need hit/miss tracking)."""
        return 0.0  # TODO: Implement hit tracking


class RedisCache(TravelTimeCache):
    """
    Redis-based cache for distributed deployments.

    Requires redis-py package.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        prefix: str = "solvereign:travel:",
        password: Optional[str] = None
    ):
        self._prefix = prefix
        self._redis = None

        # Lazy import to avoid dependency if not using Redis
        try:
            import redis
            self._redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True
            )
        except ImportError:
            raise ImportError("redis package required for RedisCache. Install with: pip install redis")

    def _make_redis_key(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> str:
        """Create Redis key with prefix."""
        return f"{self._prefix}{self.make_key(origin, destination)}"

    def get(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> Optional[CacheEntry]:
        key = self._make_redis_key(origin, destination)
        data = self._redis.get(key)

        if data:
            entry_dict = json.loads(data)
            return CacheEntry(
                duration_seconds=entry_dict["duration_seconds"],
                distance_meters=entry_dict["distance_meters"],
                cached_at=datetime.fromisoformat(entry_dict["cached_at"]),
                ttl_seconds=entry_dict["ttl_seconds"]
            )
        return None

    def set(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        duration_seconds: int,
        distance_meters: int,
        ttl_seconds: int = 86400
    ) -> None:
        key = self._make_redis_key(origin, destination)
        entry = {
            "duration_seconds": duration_seconds,
            "distance_meters": distance_meters,
            "cached_at": datetime.now().isoformat(),
            "ttl_seconds": ttl_seconds
        }
        self._redis.setex(key, ttl_seconds, json.dumps(entry))

    def invalidate(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> None:
        key = self._make_redis_key(origin, destination)
        self._redis.delete(key)

    def clear(self) -> None:
        """Clear all travel time entries (by prefix)."""
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor, match=f"{self._prefix}*", count=1000)
            if keys:
                self._redis.delete(*keys)
            if cursor == 0:
                break

    def health_check(self) -> bool:
        """Check Redis connection."""
        try:
            return self._redis.ping()
        except Exception:
            return False
