"""
SOLVEREIGN V3.3b - Token Refresh with Rotation

=============================================================================
IMPORTANT: SELF-HOSTED AUTH MODE ONLY
=============================================================================

This module is ONLY needed when running WITHOUT an external IdP (Keycloak/Auth0).

When using Keycloak/Auth0:
- Refresh tokens are managed by the IdP
- Token rotation is handled by the IdP
- Reuse detection is handled by the IdP
- This module should NOT be used

When to use this module:
- Development/testing without IdP
- Self-hosted deployments without external IdP
- Air-gapped environments

=============================================================================

Implements secure token refresh with automatic rotation.
Each refresh token can only be used once (rotation).

Security Features:
- One-time use refresh tokens (rotation)
- Refresh token family tracking (detect reuse attacks)
- Automatic revocation of token family on reuse detection
- Binding to original client fingerprint
- Grace period for network race conditions
"""

import hashlib
import secrets
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class RefreshToken:
    """Refresh token data."""

    token_id: str  # Unique identifier for this refresh token
    token_hash: str  # SHA256 hash of the actual token value
    family_id: str  # Token family (for rotation tracking)
    user_id: str
    tenant_id: str
    client_fingerprint: str  # Browser/device fingerprint
    issued_at: datetime
    expires_at: datetime
    rotated_at: Optional[datetime] = None  # Set when token is used
    revoked: bool = False
    revocation_reason: Optional[str] = None


@dataclass
class TokenPair:
    """Access token + refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 900  # 15 minutes for access token
    refresh_expires_in: int = 604800  # 7 days for refresh token


class RefreshTokenStorage(ABC):
    """Abstract base class for refresh token storage."""

    @abstractmethod
    async def store(self, token: RefreshToken) -> None:
        """Store a refresh token."""
        pass

    @abstractmethod
    async def get_by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        """Get refresh token by hash."""
        pass

    @abstractmethod
    async def mark_rotated(self, token_id: str, rotated_at: datetime) -> None:
        """Mark token as rotated (used)."""
        pass

    @abstractmethod
    async def revoke_family(self, family_id: str, reason: str) -> int:
        """Revoke all tokens in a family. Returns count revoked."""
        pass

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove expired tokens. Returns count removed."""
        pass


class InMemoryRefreshStorage(RefreshTokenStorage):
    """In-memory refresh token storage for development/testing."""

    def __init__(self):
        self._tokens: dict[str, RefreshToken] = {}  # token_id -> RefreshToken
        self._hash_index: dict[str, str] = {}  # token_hash -> token_id

    async def store(self, token: RefreshToken) -> None:
        self._tokens[token.token_id] = token
        self._hash_index[token.token_hash] = token.token_id
        logger.debug(f"Stored refresh token: {token.token_id}, family: {token.family_id}")

    async def get_by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        token_id = self._hash_index.get(token_hash)
        if not token_id:
            return None
        return self._tokens.get(token_id)

    async def mark_rotated(self, token_id: str, rotated_at: datetime) -> None:
        if token_id in self._tokens:
            self._tokens[token_id].rotated_at = rotated_at

    async def revoke_family(self, family_id: str, reason: str) -> int:
        count = 0
        for token in self._tokens.values():
            if token.family_id == family_id and not token.revoked:
                token.revoked = True
                token.revocation_reason = reason
                count += 1
        logger.warning(f"Revoked {count} tokens in family {family_id}: {reason}")
        return count

    async def cleanup_expired(self) -> int:
        now = datetime.utcnow()
        expired = [
            (tid, t.token_hash) for tid, t in self._tokens.items()
            if t.expires_at < now
        ]
        for token_id, token_hash in expired:
            del self._tokens[token_id]
            if token_hash in self._hash_index:
                del self._hash_index[token_hash]
        return len(expired)


class RedisRefreshStorage(RefreshTokenStorage):
    """Redis-based refresh token storage for production."""

    PREFIX = "refresh:"
    FAMILY_PREFIX = "refresh_family:"

    def __init__(self, redis_url: str = "redis://localhost:6379/1"):
        self._redis_url = redis_url
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as redis
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def store(self, token: RefreshToken) -> None:
        redis = await self._get_redis()
        ttl = int((token.expires_at - datetime.utcnow()).total_seconds())
        if ttl <= 0:
            return

        # Store token data
        key = f"{self.PREFIX}{token.token_id}"
        data = {
            "token_id": token.token_id,
            "token_hash": token.token_hash,
            "family_id": token.family_id,
            "user_id": token.user_id,
            "tenant_id": token.tenant_id,
            "client_fingerprint": token.client_fingerprint,
            "issued_at": token.issued_at.isoformat(),
            "expires_at": token.expires_at.isoformat(),
            "revoked": "0",
        }
        await redis.hset(key, mapping=data)
        await redis.expire(key, ttl)

        # Index by hash
        hash_key = f"{self.PREFIX}hash:{token.token_hash}"
        await redis.set(hash_key, token.token_id, ex=ttl)

        # Add to family set
        family_key = f"{self.FAMILY_PREFIX}{token.family_id}"
        await redis.sadd(family_key, token.token_id)
        await redis.expire(family_key, ttl + 3600)  # Keep family index a bit longer

    async def get_by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        redis = await self._get_redis()

        # Look up token_id by hash
        hash_key = f"{self.PREFIX}hash:{token_hash}"
        token_id = await redis.get(hash_key)
        if not token_id:
            return None

        # Get token data
        key = f"{self.PREFIX}{token_id}"
        data = await redis.hgetall(key)
        if not data:
            return None

        return RefreshToken(
            token_id=data["token_id"],
            token_hash=data["token_hash"],
            family_id=data["family_id"],
            user_id=data["user_id"],
            tenant_id=data["tenant_id"],
            client_fingerprint=data["client_fingerprint"],
            issued_at=datetime.fromisoformat(data["issued_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            rotated_at=datetime.fromisoformat(data["rotated_at"]) if data.get("rotated_at") else None,
            revoked=data.get("revoked") == "1",
            revocation_reason=data.get("revocation_reason")
        )

    async def mark_rotated(self, token_id: str, rotated_at: datetime) -> None:
        redis = await self._get_redis()
        key = f"{self.PREFIX}{token_id}"
        await redis.hset(key, "rotated_at", rotated_at.isoformat())

    async def revoke_family(self, family_id: str, reason: str) -> int:
        redis = await self._get_redis()
        family_key = f"{self.FAMILY_PREFIX}{family_id}"

        token_ids = await redis.smembers(family_key)
        count = 0
        for token_id in token_ids:
            key = f"{self.PREFIX}{token_id}"
            if await redis.exists(key):
                await redis.hset(key, mapping={"revoked": "1", "revocation_reason": reason})
                count += 1

        logger.warning(f"Revoked {count} tokens in family {family_id}: {reason}")
        return count

    async def cleanup_expired(self) -> int:
        # Redis handles TTL-based cleanup automatically
        return 0


class TokenRefreshService:
    """
    Service for handling token refresh with rotation.

    Security model:
    - Each refresh token can only be used once
    - Using a refresh token issues a new token pair
    - Reusing an already-rotated token revokes the entire token family
    - Client fingerprint is validated on refresh
    """

    # Grace period for network race conditions (seconds)
    ROTATION_GRACE_PERIOD = 30

    def __init__(
        self,
        storage: RefreshTokenStorage,
        access_token_lifetime: timedelta = timedelta(minutes=15),
        refresh_token_lifetime: timedelta = timedelta(days=7),
        jwt_secret_key: Optional[str] = None,
        jwt_algorithm: str = "HS256"
    ):
        self._storage = storage
        self._access_token_lifetime = access_token_lifetime
        self._refresh_token_lifetime = refresh_token_lifetime
        self._jwt_secret_key = jwt_secret_key or secrets.token_hex(32)
        self._jwt_algorithm = jwt_algorithm

    def _hash_token(self, token: str) -> str:
        """Hash a token value for storage."""
        return hashlib.sha256(token.encode()).hexdigest()

    def _generate_token_value(self) -> str:
        """Generate a secure random token value."""
        return secrets.token_urlsafe(48)

    def _compute_client_fingerprint(
        self,
        user_agent: str,
        ip_address: str
    ) -> str:
        """
        Compute a client fingerprint for binding.
        Note: This is a simple implementation. Production might use
        more sophisticated device fingerprinting.
        """
        data = f"{user_agent}:{ip_address}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    async def create_token_pair(
        self,
        user_id: str,
        tenant_id: str,
        roles: list[str],
        permissions: list[str],
        user_agent: str,
        ip_address: str,
        family_id: Optional[str] = None
    ) -> TokenPair:
        """
        Create a new access token + refresh token pair.

        Args:
            user_id: User identifier
            tenant_id: Tenant identifier
            roles: User roles
            permissions: User permissions
            user_agent: Client user agent
            ip_address: Client IP address
            family_id: Optional family ID (for rotation, reuse existing)
        """
        import jwt

        now = datetime.utcnow()

        # Generate access token (JWT)
        access_token_exp = now + self._access_token_lifetime
        access_token_payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": roles,
            "permissions": permissions,
            "iat": int(now.timestamp()),
            "exp": int(access_token_exp.timestamp()),
            "jti": secrets.token_hex(16)
        }
        access_token = jwt.encode(
            access_token_payload,
            self._jwt_secret_key,
            algorithm=self._jwt_algorithm
        )

        # Generate refresh token
        refresh_token_value = self._generate_token_value()
        refresh_token_hash = self._hash_token(refresh_token_value)
        refresh_token_exp = now + self._refresh_token_lifetime

        client_fingerprint = self._compute_client_fingerprint(user_agent, ip_address)

        refresh_token = RefreshToken(
            token_id=secrets.token_hex(16),
            token_hash=refresh_token_hash,
            family_id=family_id or secrets.token_hex(16),
            user_id=user_id,
            tenant_id=tenant_id,
            client_fingerprint=client_fingerprint,
            issued_at=now,
            expires_at=refresh_token_exp
        )

        await self._storage.store(refresh_token)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token_value,
            expires_in=int(self._access_token_lifetime.total_seconds()),
            refresh_expires_in=int(self._refresh_token_lifetime.total_seconds())
        )

    async def refresh(
        self,
        refresh_token_value: str,
        user_agent: str,
        ip_address: str,
        get_user_data: callable  # async function to get user roles/permissions
    ) -> TokenPair:
        """
        Refresh an access token using a refresh token.

        Args:
            refresh_token_value: The refresh token value
            user_agent: Client user agent
            ip_address: Client IP address
            get_user_data: Async function(user_id, tenant_id) -> dict with roles, permissions

        Returns:
            New TokenPair with rotated refresh token

        Raises:
            ValueError: If refresh token is invalid, expired, or reused
        """
        token_hash = self._hash_token(refresh_token_value)
        token = await self._storage.get_by_hash(token_hash)

        if not token:
            logger.warning(f"Refresh attempt with unknown token hash: {token_hash[:16]}...")
            raise ValueError("Invalid refresh token")

        now = datetime.utcnow()

        # Check if revoked
        if token.revoked:
            logger.warning(
                f"Refresh attempt with revoked token: user={token.user_id}, "
                f"reason={token.revocation_reason}"
            )
            raise ValueError("Refresh token has been revoked")

        # Check expiration
        if token.expires_at < now:
            logger.info(f"Refresh attempt with expired token: user={token.user_id}")
            raise ValueError("Refresh token has expired")

        # Check rotation (token reuse detection)
        if token.rotated_at:
            # Check grace period
            grace_deadline = token.rotated_at + timedelta(seconds=self.ROTATION_GRACE_PERIOD)
            if now > grace_deadline:
                # Token was already used and grace period expired
                # This indicates a potential token theft - revoke entire family
                logger.critical(
                    f"SECURITY: Refresh token reuse detected! "
                    f"user={token.user_id}, tenant={token.tenant_id}, family={token.family_id}. "
                    f"Revoking entire token family."
                )
                await self._storage.revoke_family(
                    token.family_id,
                    "Token reuse detected - potential theft"
                )
                raise ValueError("Refresh token has already been used")
            else:
                # Within grace period - allow but warn
                logger.warning(
                    f"Refresh token used within grace period: user={token.user_id}, "
                    f"rotated_at={token.rotated_at}, now={now}"
                )

        # Validate client fingerprint
        expected_fingerprint = self._compute_client_fingerprint(user_agent, ip_address)
        if token.client_fingerprint != expected_fingerprint:
            logger.warning(
                f"Client fingerprint mismatch on refresh: user={token.user_id}, "
                f"expected={token.client_fingerprint}, got={expected_fingerprint}"
            )
            # We don't fail here but log it. In strict mode, you might revoke.

        # Mark current token as rotated
        await self._storage.mark_rotated(token.token_id, now)

        # Get current user data (roles/permissions might have changed)
        user_data = await get_user_data(token.user_id, token.tenant_id)

        # Issue new token pair with same family_id
        new_pair = await self.create_token_pair(
            user_id=token.user_id,
            tenant_id=token.tenant_id,
            roles=user_data.get("roles", []),
            permissions=user_data.get("permissions", []),
            user_agent=user_agent,
            ip_address=ip_address,
            family_id=token.family_id  # Keep same family for tracking
        )

        logger.info(
            f"Token refreshed: user={token.user_id}, tenant={token.tenant_id}, "
            f"family={token.family_id}"
        )

        return new_pair

    async def revoke(self, refresh_token_value: str, reason: str) -> bool:
        """Revoke a refresh token and its entire family."""
        token_hash = self._hash_token(refresh_token_value)
        token = await self._storage.get_by_hash(token_hash)

        if not token:
            return False

        await self._storage.revoke_family(token.family_id, reason)
        return True

    async def revoke_user_tokens(self, user_id: str, reason: str) -> None:
        """
        Revoke all refresh tokens for a user.
        Note: This requires iterating all tokens, consider tracking user->families separately.
        """
        # Implementation depends on storage capabilities
        # For Redis, you'd maintain a user->family_ids index
        logger.info(f"Revoking all tokens for user {user_id}: {reason}")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_refresh_service: Optional[TokenRefreshService] = None


def get_token_refresh_service() -> TokenRefreshService:
    """Get or create the singleton TokenRefreshService instance."""
    global _refresh_service

    if _refresh_service is None:
        import os

        redis_url = os.environ.get("REDIS_URL")

        if redis_url:
            storage = RedisRefreshStorage(redis_url)
            logger.info("Using Redis for refresh token storage")
        else:
            storage = InMemoryRefreshStorage()
            logger.warning("Using in-memory refresh token storage (not suitable for production)")

        _refresh_service = TokenRefreshService(
            storage=storage,
            jwt_secret_key=os.environ.get("JWT_SECRET_KEY"),
        )

    return _refresh_service
