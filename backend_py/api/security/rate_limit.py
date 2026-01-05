"""
SOLVEREIGN V3.3b - Rate Limiting
================================

Multi-level rate limiting:
- Per-tenant (prevent one tenant from DoS'ing others)
- Per-user (prevent abuse within tenant)
- Per-IP (prevent brute force)
- Per-endpoint (protect expensive operations)

Storage backends:
- Redis (production)
- In-memory (development/testing)
"""

import time
import logging
import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from collections import defaultdict

from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================

class RateLimitExceeded(HTTPException):
    """Rate limit exceeded exception."""

    def __init__(
        self,
        limit: int,
        window: int,
        retry_after: int,
        limit_type: str = "default",
    ):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Too many requests. Limit: {limit} per {window}s",
                "limit": limit,
                "window_seconds": window,
                "retry_after_seconds": retry_after,
                "limit_type": limit_type,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + retry_after),
            },
        )


# =============================================================================
# RATE LIMIT CONFIGURATION
# =============================================================================

@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    requests: int           # Max requests
    window: int             # Window in seconds
    by: str = "tenant"      # tenant, user, ip
    burst: int = 0          # Burst allowance (above limit)


# Default rate limits by endpoint pattern
DEFAULT_LIMITS: Dict[str, RateLimitConfig] = {
    # Authentication: Strict IP-based (brute force protection)
    "/auth/login": RateLimitConfig(requests=10, window=60, by="ip"),
    "/auth/refresh": RateLimitConfig(requests=30, window=60, by="user"),
    "/auth/logout": RateLimitConfig(requests=10, window=60, by="user"),

    # API: Per-tenant limits
    "default": RateLimitConfig(requests=1000, window=60, by="tenant"),

    # Expensive operations: Stricter limits
    "/api/v1/plans/*/solve": RateLimitConfig(requests=10, window=60, by="tenant"),
    "/api/v1/forecasts/ingest": RateLimitConfig(requests=20, window=60, by="tenant"),
    "/api/v1/simulations/run": RateLimitConfig(requests=30, window=60, by="tenant"),

    # Export: Very strict (data exfiltration prevention)
    "/api/v1/export/*": RateLimitConfig(requests=5, window=3600, by="tenant"),  # 5/hour
    "/api/v1/drivers/export": RateLimitConfig(requests=3, window=3600, by="tenant"),  # 3/hour

    # Admin: Moderate limits
    "/api/v1/tenants/*": RateLimitConfig(requests=100, window=60, by="tenant"),
    "/api/v1/users/*": RateLimitConfig(requests=100, window=60, by="tenant"),
}


# =============================================================================
# STORAGE BACKENDS
# =============================================================================

class RateLimitStorage:
    """Abstract rate limit storage."""

    async def get_count(self, key: str) -> Tuple[int, int]:
        """Get current count and TTL for key."""
        raise NotImplementedError

    async def increment(self, key: str, window: int) -> Tuple[int, int]:
        """Increment counter and return (count, ttl)."""
        raise NotImplementedError

    async def reset(self, key: str):
        """Reset counter for key."""
        raise NotImplementedError


class InMemoryStorage(RateLimitStorage):
    """
    In-memory rate limit storage.

    Suitable for development and single-instance deployments.
    NOT suitable for multi-instance production.
    """

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._expiry: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get_count(self, key: str) -> Tuple[int, int]:
        async with self._lock:
            # Check expiry
            if key in self._expiry and time.time() > self._expiry[key]:
                del self._counters[key]
                del self._expiry[key]
                return 0, 0

            count = self._counters.get(key, 0)
            ttl = int(self._expiry.get(key, 0) - time.time())
            return count, max(0, ttl)

    async def increment(self, key: str, window: int) -> Tuple[int, int]:
        async with self._lock:
            now = time.time()

            # Check expiry
            if key in self._expiry and now > self._expiry[key]:
                self._counters[key] = 0
                del self._expiry[key]

            # Increment
            self._counters[key] += 1
            count = self._counters[key]

            # Set expiry if new key
            if key not in self._expiry:
                self._expiry[key] = now + window

            ttl = int(self._expiry[key] - now)
            return count, max(0, ttl)

    async def reset(self, key: str):
        async with self._lock:
            if key in self._counters:
                del self._counters[key]
            if key in self._expiry:
                del self._expiry[key]


class RedisStorage(RateLimitStorage):
    """
    Redis-based rate limit storage.

    Production-ready, supports multi-instance deployments.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(self.redis_url)
            except ImportError:
                raise RuntimeError("redis package not installed. Run: pip install redis")
        return self._redis

    async def get_count(self, key: str) -> Tuple[int, int]:
        r = await self._get_redis()
        pipe = r.pipeline()
        pipe.get(f"ratelimit:{key}")
        pipe.ttl(f"ratelimit:{key}")
        results = await pipe.execute()

        count = int(results[0] or 0)
        ttl = int(results[1] if results[1] > 0 else 0)
        return count, ttl

    async def increment(self, key: str, window: int) -> Tuple[int, int]:
        r = await self._get_redis()
        full_key = f"ratelimit:{key}"

        pipe = r.pipeline()
        pipe.incr(full_key)
        pipe.expire(full_key, window, nx=True)  # Only set if not exists
        pipe.ttl(full_key)
        results = await pipe.execute()

        count = int(results[0])
        ttl = int(results[2] if results[2] > 0 else window)
        return count, ttl

    async def reset(self, key: str):
        r = await self._get_redis()
        await r.delete(f"ratelimit:{key}")


# =============================================================================
# RATE LIMITER
# =============================================================================

class RateLimiter:
    """
    Multi-level rate limiter.

    Usage:
        limiter = RateLimiter()

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            await limiter.check(request, tenant_id, user_id)
            return await call_next(request)
    """

    def __init__(
        self,
        storage: Optional[RateLimitStorage] = None,
        limits: Optional[Dict[str, RateLimitConfig]] = None,
        enabled: bool = True,
    ):
        self.storage = storage or InMemoryStorage()
        self.limits = limits or DEFAULT_LIMITS
        self.enabled = enabled

    def get_limit_config(self, path: str) -> RateLimitConfig:
        """Get rate limit config for path."""
        # Check exact match
        if path in self.limits:
            return self.limits[path]

        # Check pattern match (with wildcards)
        for pattern, config in self.limits.items():
            if self._path_matches(path, pattern):
                return config

        # Default
        return self.limits.get("default", RateLimitConfig(
            requests=1000,
            window=60,
            by="tenant"
        ))

    def _path_matches(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern with wildcards."""
        if "*" not in pattern:
            return path == pattern

        # Simple wildcard matching
        parts = pattern.split("*")
        if len(parts) == 2:
            return path.startswith(parts[0]) and path.endswith(parts[1])

        return False

    def _build_key(
        self,
        path: str,
        config: RateLimitConfig,
        tenant_id: Optional[str],
        user_id: Optional[str],
        ip: str,
    ) -> str:
        """Build rate limit key based on configuration."""
        if config.by == "ip":
            return f"ip:{ip}:{path}"
        elif config.by == "user":
            return f"user:{user_id or 'anonymous'}:{path}"
        else:  # tenant (default)
            return f"tenant:{tenant_id or 'anonymous'}:{path}"

    async def check(
        self,
        request: Request,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[int, int, int]:
        """
        Check rate limit for request.

        Returns: (remaining, limit, reset_seconds)
        Raises: RateLimitExceeded if limit exceeded
        """
        if not self.enabled:
            return (1000, 1000, 60)

        path = request.url.path
        config = self.get_limit_config(path)
        ip = self._get_client_ip(request)

        key = self._build_key(path, config, tenant_id, user_id, ip)

        # Increment counter
        count, ttl = await self.storage.increment(key, config.window)

        # Calculate remaining
        limit = config.requests + config.burst
        remaining = max(0, limit - count)

        # Check if exceeded
        if count > limit:
            # Log rate limit hit
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "path": path,
                    "limit_type": config.by,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "ip": ip,
                    "count": count,
                    "limit": limit,
                }
            )

            # Audit log for security
            from .audit import SecurityAuditLogger
            await SecurityAuditLogger.log(
                event_type="RATE_LIMIT_EXCEEDED",
                tenant_id=tenant_id,
                user_id=user_id,
                severity="WARNING",
                ip_address=ip,
                details={
                    "path": path,
                    "method": request.method,
                    "count": count,
                    "limit": limit,
                    "limit_type": config.by,
                },
            )

            raise RateLimitExceeded(
                limit=config.requests,
                window=config.window,
                retry_after=ttl,
                limit_type=config.by,
            )

        return remaining, limit, ttl

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP, respecting X-Forwarded-For."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def add_headers(
        self,
        response,
        remaining: int,
        limit: int,
        reset: int,
    ):
        """Add rate limit headers to response."""
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + reset)


# =============================================================================
# MIDDLEWARE
# =============================================================================

class RateLimitMiddleware:
    """
    Rate limiting middleware.

    Usage:
        from api.security.rate_limit import RateLimitMiddleware

        app.add_middleware(RateLimitMiddleware, enabled=True)
    """

    def __init__(
        self,
        app,
        enabled: bool = True,
        storage: Optional[RateLimitStorage] = None,
    ):
        self.app = app
        self.limiter = RateLimiter(storage=storage, enabled=enabled)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/metrics"]:
            await self.app(scope, receive, send)
            return

        # Extract tenant/user from request state (set by auth middleware)
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = getattr(request.state, "user_id", None)

        try:
            remaining, limit, reset = await self.limiter.check(
                request, tenant_id, user_id
            )

            # Process request
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    # Add rate limit headers
                    headers = list(message.get("headers", []))
                    headers.extend([
                        (b"x-ratelimit-limit", str(limit).encode()),
                        (b"x-ratelimit-remaining", str(remaining).encode()),
                        (b"x-ratelimit-reset", str(int(time.time()) + reset).encode()),
                    ])
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_wrapper)

        except RateLimitExceeded as e:
            # Return 429 response
            from starlette.responses import JSONResponse
            response = JSONResponse(
                status_code=e.status_code,
                content=e.detail,
                headers=dict(e.headers) if e.headers else {},
            )
            await response(scope, receive, send)
