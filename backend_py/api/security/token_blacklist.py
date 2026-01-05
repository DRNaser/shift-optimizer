"""
SOLVEREIGN V3.3b - Token Blacklist

Implements token revocation with Redis storage.
Supports both individual token revocation and bulk revocation by user/tenant.

=============================================================================
USAGE GUIDANCE: When to check blacklist
=============================================================================

Global blacklist checks (every request) DEFEAT the purpose of stateless JWTs.
Use short-lived access tokens (5-15min) instead of global blacklist.

CHECK BLACKLIST ONLY FOR:
- Critical write operations: /plans/{id}/lock, /plans/{id}/repair
- Data export: /export/*
- Admin operations: /admin/*
- PII access: /drivers/{id}/pii

DO NOT CHECK BLACKLIST FOR:
- Read-only endpoints: /forecasts, /plans (list), /health
- High-frequency endpoints: /metrics, /status

Recommended approach:
1. Access token TTL: 5-15 minutes (short enough that revocation is rare)
2. Refresh handled by IdP (Keycloak/Auth0)
3. Blacklist check only on sensitive endpoints
4. User/tenant disable synced from IdP via webhook

=============================================================================

Security Features:
- JTI (JWT ID) based revocation
- User-level revocation (invalidate all tokens for user)
- Tenant-level revocation (invalidate all tokens for tenant)
- TTL-based automatic cleanup (no stale entries)
- In-memory fallback for development/testing
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class RevocationEntry:
    """Entry in the token blacklist."""

    identifier: str  # JTI, user_id, or tenant_id
    revocation_type: str  # "token", "user", "tenant"
    revoked_at: datetime
    expires_at: datetime
    reason: str
    revoked_by: Optional[str] = None


class TokenBlacklistStorage(ABC):
    """Abstract base class for token blacklist storage."""

    @abstractmethod
    async def add_revocation(self, entry: RevocationEntry) -> None:
        """Add a revocation entry."""
        pass

    @abstractmethod
    async def is_token_revoked(self, jti: str) -> bool:
        """Check if a specific token (by JTI) is revoked."""
        pass

    @abstractmethod
    async def is_user_revoked(self, user_id: str, token_issued_at: datetime) -> bool:
        """Check if user's tokens issued before revocation are invalid."""
        pass

    @abstractmethod
    async def is_tenant_revoked(self, tenant_id: str, token_issued_at: datetime) -> bool:
        """Check if tenant's tokens issued before revocation are invalid."""
        pass

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        pass


class InMemoryBlacklistStorage(TokenBlacklistStorage):
    """
    In-memory token blacklist for development/testing.
    NOT suitable for production (no persistence, no distribution).
    """

    def __init__(self):
        self._token_revocations: dict[str, RevocationEntry] = {}
        self._user_revocations: dict[str, RevocationEntry] = {}
        self._tenant_revocations: dict[str, RevocationEntry] = {}

    async def add_revocation(self, entry: RevocationEntry) -> None:
        now = datetime.utcnow()
        if entry.expires_at < now:
            return  # Already expired, don't add

        if entry.revocation_type == "token":
            self._token_revocations[entry.identifier] = entry
        elif entry.revocation_type == "user":
            self._user_revocations[entry.identifier] = entry
        elif entry.revocation_type == "tenant":
            self._tenant_revocations[entry.identifier] = entry

        logger.info(f"Token blacklist: Added {entry.revocation_type} revocation for {entry.identifier}")

    async def is_token_revoked(self, jti: str) -> bool:
        entry = self._token_revocations.get(jti)
        if not entry:
            return False

        # Check if entry is still valid (not expired)
        if entry.expires_at < datetime.utcnow():
            del self._token_revocations[jti]
            return False

        return True

    async def is_user_revoked(self, user_id: str, token_issued_at: datetime) -> bool:
        entry = self._user_revocations.get(user_id)
        if not entry:
            return False

        # Check if entry is still valid
        if entry.expires_at < datetime.utcnow():
            del self._user_revocations[user_id]
            return False

        # Token is revoked if it was issued before the revocation
        return token_issued_at < entry.revoked_at

    async def is_tenant_revoked(self, tenant_id: str, token_issued_at: datetime) -> bool:
        entry = self._tenant_revocations.get(tenant_id)
        if not entry:
            return False

        # Check if entry is still valid
        if entry.expires_at < datetime.utcnow():
            del self._tenant_revocations[tenant_id]
            return False

        # Token is revoked if it was issued before the revocation
        return token_issued_at < entry.revoked_at

    async def cleanup_expired(self) -> int:
        now = datetime.utcnow()
        count = 0

        for store in [self._token_revocations, self._user_revocations, self._tenant_revocations]:
            expired_keys = [k for k, v in store.items() if v.expires_at < now]
            for key in expired_keys:
                del store[key]
                count += 1

        if count > 0:
            logger.info(f"Token blacklist: Cleaned up {count} expired entries")

        return count


class RedisBlacklistStorage(TokenBlacklistStorage):
    """
    Redis-based token blacklist for production.
    Features:
    - Distributed across multiple API instances
    - Automatic TTL-based cleanup
    - Atomic operations
    """

    # Key prefixes
    TOKEN_PREFIX = "blacklist:token:"
    USER_PREFIX = "blacklist:user:"
    TENANT_PREFIX = "blacklist:tenant:"

    def __init__(self, redis_url: str = "redis://localhost:6379/1"):
        self._redis_url = redis_url
        self._redis = None

    async def _get_redis(self):
        """Lazy initialization of Redis connection."""
        if self._redis is None:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(self._redis_url, decode_responses=True)
                # Test connection
                await self._redis.ping()
                logger.info(f"Redis blacklist storage connected: {self._redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        return self._redis

    async def add_revocation(self, entry: RevocationEntry) -> None:
        redis = await self._get_redis()

        # Calculate TTL in seconds
        ttl = int((entry.expires_at - datetime.utcnow()).total_seconds())
        if ttl <= 0:
            return  # Already expired

        # Determine key based on revocation type
        if entry.revocation_type == "token":
            key = f"{self.TOKEN_PREFIX}{entry.identifier}"
        elif entry.revocation_type == "user":
            key = f"{self.USER_PREFIX}{entry.identifier}"
        elif entry.revocation_type == "tenant":
            key = f"{self.TENANT_PREFIX}{entry.identifier}"
        else:
            raise ValueError(f"Unknown revocation type: {entry.revocation_type}")

        # Store revocation data with TTL
        data = {
            "revoked_at": entry.revoked_at.isoformat(),
            "reason": entry.reason,
            "revoked_by": entry.revoked_by or "",
        }

        await redis.hset(key, mapping=data)
        await redis.expire(key, ttl)

        logger.info(
            f"Token blacklist: Added {entry.revocation_type} revocation for {entry.identifier}, "
            f"TTL={ttl}s"
        )

    async def is_token_revoked(self, jti: str) -> bool:
        redis = await self._get_redis()
        key = f"{self.TOKEN_PREFIX}{jti}"
        return await redis.exists(key) > 0

    async def is_user_revoked(self, user_id: str, token_issued_at: datetime) -> bool:
        redis = await self._get_redis()
        key = f"{self.USER_PREFIX}{user_id}"

        data = await redis.hgetall(key)
        if not data:
            return False

        revoked_at = datetime.fromisoformat(data["revoked_at"])
        return token_issued_at < revoked_at

    async def is_tenant_revoked(self, tenant_id: str, token_issued_at: datetime) -> bool:
        redis = await self._get_redis()
        key = f"{self.TENANT_PREFIX}{tenant_id}"

        data = await redis.hgetall(key)
        if not data:
            return False

        revoked_at = datetime.fromisoformat(data["revoked_at"])
        return token_issued_at < revoked_at

    async def cleanup_expired(self) -> int:
        # Redis handles TTL-based cleanup automatically
        # This method is a no-op for Redis
        return 0


class TokenBlacklist:
    """
    Main token blacklist service.
    Provides high-level API for token revocation.
    """

    def __init__(
        self,
        storage: TokenBlacklistStorage,
        default_ttl: timedelta = timedelta(days=7)
    ):
        self._storage = storage
        self._default_ttl = default_ttl

    async def revoke_token(
        self,
        jti: str,
        reason: str,
        revoked_by: Optional[str] = None,
        ttl: Optional[timedelta] = None
    ) -> None:
        """
        Revoke a specific token by its JTI.

        Args:
            jti: JWT ID of the token to revoke
            reason: Reason for revocation (for audit)
            revoked_by: User/admin who initiated revocation
            ttl: How long to keep the revocation (default: 7 days)
        """
        now = datetime.utcnow()
        entry = RevocationEntry(
            identifier=jti,
            revocation_type="token",
            revoked_at=now,
            expires_at=now + (ttl or self._default_ttl),
            reason=reason,
            revoked_by=revoked_by
        )
        await self._storage.add_revocation(entry)

    async def revoke_user_tokens(
        self,
        user_id: str,
        reason: str,
        revoked_by: Optional[str] = None,
        ttl: Optional[timedelta] = None
    ) -> None:
        """
        Revoke all tokens for a user (issued before now).

        Use cases:
        - Password change
        - Account compromise
        - User deactivation
        - Forced logout
        """
        now = datetime.utcnow()
        entry = RevocationEntry(
            identifier=user_id,
            revocation_type="user",
            revoked_at=now,
            expires_at=now + (ttl or self._default_ttl),
            reason=reason,
            revoked_by=revoked_by
        )
        await self._storage.add_revocation(entry)

    async def revoke_tenant_tokens(
        self,
        tenant_id: str,
        reason: str,
        revoked_by: Optional[str] = None,
        ttl: Optional[timedelta] = None
    ) -> None:
        """
        Revoke all tokens for a tenant (issued before now).

        Use cases:
        - Security incident
        - Tenant suspension
        - Key rotation
        """
        now = datetime.utcnow()
        entry = RevocationEntry(
            identifier=tenant_id,
            revocation_type="tenant",
            revoked_at=now,
            expires_at=now + (ttl or self._default_ttl),
            reason=reason,
            revoked_by=revoked_by
        )
        await self._storage.add_revocation(entry)

    async def is_revoked(
        self,
        jti: str,
        user_id: str,
        tenant_id: str,
        issued_at: datetime
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a token is revoked.

        Returns:
            Tuple of (is_revoked, reason)
        """
        # Check token-level revocation
        if await self._storage.is_token_revoked(jti):
            return True, "Token has been revoked"

        # Check user-level revocation
        if await self._storage.is_user_revoked(user_id, issued_at):
            return True, "All user tokens have been revoked"

        # Check tenant-level revocation
        if await self._storage.is_tenant_revoked(tenant_id, issued_at):
            return True, "All tenant tokens have been revoked"

        return False, None

    async def cleanup(self) -> int:
        """Run cleanup of expired entries."""
        return await self._storage.cleanup_expired()


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_blacklist_instance: Optional[TokenBlacklist] = None


def get_token_blacklist() -> TokenBlacklist:
    """Get or create the singleton TokenBlacklist instance."""
    global _blacklist_instance

    if _blacklist_instance is None:
        import os

        redis_url = os.environ.get("REDIS_URL")

        if redis_url:
            storage = RedisBlacklistStorage(redis_url)
            logger.info("Using Redis for token blacklist")
        else:
            storage = InMemoryBlacklistStorage()
            logger.warning("Using in-memory token blacklist (not suitable for production)")

        _blacklist_instance = TokenBlacklist(storage)

    return _blacklist_instance


# =============================================================================
# FASTAPI DEPENDENCY
# =============================================================================

from fastapi import Depends, HTTPException, status

async def check_token_not_revoked(
    jti: str,
    user_id: str,
    tenant_id: str,
    issued_at: datetime
) -> None:
    """
    FastAPI dependency to check token revocation.
    Raises HTTPException if token is revoked.
    """
    blacklist = get_token_blacklist()
    is_revoked, reason = await blacklist.is_revoked(jti, user_id, tenant_id, issued_at)

    if is_revoked:
        logger.warning(f"Revoked token used: jti={jti}, user={user_id}, reason={reason}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=reason or "Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"}
        )
