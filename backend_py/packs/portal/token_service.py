"""
SOLVEREIGN V4.1 - Portal Token Service
========================================

JWT-based magic link token generation and validation.

Security:
    - Tokens are signed with HMAC-SHA256 (configurable to asymmetric)
    - Only jti_hash is stored in DB - NEVER store raw token
    - Tokens are single-use for ACK operations
    - Rate limiting per jti_hash
    - NEVER log raw tokens - only jti_hash and trace_id

Environment Variables:
    - PORTAL_JWT_SECRET: Secret key for HMAC signing (required)
    - PORTAL_TOKEN_READ_TTL_DAYS: TTL for READ tokens (default 14)
    - PORTAL_TOKEN_ACK_TTL_DAYS: TTL for ACK tokens (default 7)
    - PORTAL_RATE_LIMIT_MAX: Max requests per hour (default 100)
"""

import os
import logging
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from .models import (
    TokenScope,
    TokenStatus,
    PortalToken,
    TokenValidationResult,
    RateLimitResult,
    generate_jti,
    hash_jti,
    hash_ip,
    DeliveryChannel,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class TokenConfig:
    """
    Configuration for token service.

    KEY ROTATION:
        - jwt_secret: Primary key (used for signing new tokens)
        - jwt_secret_secondary: Previous key (used for validation during rotation)

    Rotation process:
        1. Set PORTAL_JWT_SECRET_SECONDARY to current PORTAL_JWT_SECRET value
        2. Generate new PORTAL_JWT_SECRET
        3. Deploy (new tokens use primary, old tokens validate with secondary)
        4. After old tokens expire (ttl_days), remove secondary
    """
    jwt_secret: str
    jwt_secret_secondary: Optional[str] = None  # For key rotation
    jwt_algorithm: str = "HS256"

    # TTL defaults
    read_ttl_days: int = 14
    ack_ttl_days: int = 7

    # Rate limiting
    rate_limit_max: int = 100
    rate_limit_window_seconds: int = 3600

    # Single-use ACK
    revoke_after_ack: bool = True

    @classmethod
    def from_env(cls) -> "TokenConfig":
        """Load configuration from environment."""
        secret = os.environ.get("PORTAL_JWT_SECRET", "")
        if not secret:
            logger.warning("PORTAL_JWT_SECRET not set, using insecure default")
            secret = "INSECURE_DEFAULT_DO_NOT_USE_IN_PRODUCTION"

        # Secondary key for rotation (optional)
        secondary = os.environ.get("PORTAL_JWT_SECRET_SECONDARY", None)
        if secondary:
            logger.info("JWT key rotation enabled: secondary key configured")

        return cls(
            jwt_secret=secret,
            jwt_secret_secondary=secondary,
            read_ttl_days=int(os.environ.get("PORTAL_TOKEN_READ_TTL_DAYS", "14")),
            ack_ttl_days=int(os.environ.get("PORTAL_TOKEN_ACK_TTL_DAYS", "7")),
            rate_limit_max=int(os.environ.get("PORTAL_RATE_LIMIT_MAX", "100")),
        )


# =============================================================================
# TOKEN SERVICE
# =============================================================================

class PortalTokenService:
    """
    Service for generating and validating portal magic link tokens.

    Security features:
    - JWT with HMAC-SHA256 signing
    - jti_hash storage (never raw token)
    - Single-use ACK tokens
    - Rate limiting per jti_hash
    - Audit trail for all operations
    """

    def __init__(self, config: Optional[TokenConfig] = None):
        """
        Initialize token service.

        Args:
            config: Token configuration. If None, loads from environment.
        """
        self.config = config or TokenConfig.from_env()

    def generate_token(
        self,
        tenant_id: int,
        site_id: int,
        snapshot_id: str,
        driver_id: str,
        scope: TokenScope = TokenScope.READ_ACK,
        ttl_days: Optional[int] = None,
        delivery_channel: Optional[DeliveryChannel] = None,
    ) -> Tuple[str, PortalToken]:
        """
        Generate a new portal magic link token.

        Args:
            tenant_id: Tenant ID
            site_id: Site ID
            snapshot_id: Snapshot UUID
            driver_id: Driver ID
            scope: Token scope (READ, ACK, READ_ACK)
            ttl_days: Custom TTL in days (defaults based on scope)
            delivery_channel: How token will be delivered

        Returns:
            Tuple of (raw_token_string, PortalToken_for_db)

        Security:
            - The raw token should be sent to user ONCE
            - Only the PortalToken (with jti_hash) is stored in DB
            - NEVER log the raw token
        """
        # Generate JTI
        jti = generate_jti()
        jti_hash_value = hash_jti(jti)

        # Calculate expiry
        if ttl_days is None:
            if scope == TokenScope.READ:
                ttl_days = self.config.read_ttl_days
            else:
                ttl_days = self.config.ack_ttl_days

        issued_at = datetime.utcnow()
        expires_at = issued_at + timedelta(days=ttl_days)

        # Build JWT claims
        claims = {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "snapshot_id": snapshot_id,
            "driver_id": driver_id,
            "scope": scope.value,
            "jti": jti,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "iss": "solvereign_portal",
        }

        # Sign token
        raw_token = jwt.encode(
            claims,
            self.config.jwt_secret,
            algorithm=self.config.jwt_algorithm,
        )

        # Create DB model (with jti_hash, NOT raw jti)
        portal_token = PortalToken(
            tenant_id=tenant_id,
            site_id=site_id,
            snapshot_id=snapshot_id,
            driver_id=driver_id,
            scope=scope,
            jti_hash=jti_hash_value,
            issued_at=issued_at,
            expires_at=expires_at,
            delivery_channel=delivery_channel,
        )

        # Log issuance (NEVER log raw token)
        logger.info(
            f"Token issued: jti_hash={jti_hash_value[:16]}..., "
            f"tenant={tenant_id}, driver={driver_id}, scope={scope.value}"
        )

        return raw_token, portal_token

    def validate_token(
        self,
        raw_token: str,
        ip_address: Optional[str] = None,
    ) -> TokenValidationResult:
        """
        Validate a portal token.

        Args:
            raw_token: The raw JWT token string
            ip_address: Optional IP for rate limiting

        Returns:
            TokenValidationResult with validation status and token data

        Security:
            - Validates signature and expiry
            - Supports key rotation: tries primary, then secondary key
            - Does NOT check DB (call validate_with_db for full validation)
            - NEVER logs raw token
        """
        result = TokenValidationResult()

        # Build list of keys to try (primary first, then secondary if configured)
        keys_to_try = [self.config.jwt_secret]
        if self.config.jwt_secret_secondary:
            keys_to_try.append(self.config.jwt_secret_secondary)

        claims = None
        used_secondary = False

        for i, secret in enumerate(keys_to_try):
            try:
                # Decode and verify signature
                claims = jwt.decode(
                    raw_token,
                    secret,
                    algorithms=[self.config.jwt_algorithm],
                    options={"require": ["exp", "iat", "jti", "tenant_id", "driver_id", "snapshot_id", "scope"]},
                )
                used_secondary = (i == 1)
                break  # Success, exit loop

            except jwt.ExpiredSignatureError:
                # Token expired - don't try other keys
                result.status = TokenStatus.EXPIRED
                result.error_code = "TOKEN_EXPIRED"
                result.error_message = "Token has expired"
                logger.debug("Token validation failed: expired")
                return result

            except jwt.InvalidSignatureError:
                # Wrong key - try next key if available
                if i < len(keys_to_try) - 1:
                    continue  # Try next key
                # All keys failed
                result.status = TokenStatus.INVALID
                result.error_code = "TOKEN_INVALID"
                result.error_message = "Invalid token signature"
                logger.debug("Token validation failed: invalid signature (all keys tried)")
                return result

            except jwt.InvalidTokenError as e:
                result.status = TokenStatus.INVALID
                result.error_code = "TOKEN_INVALID"
                result.error_message = str(e)
                logger.debug(f"Token validation failed: {e}")
                return result

            except Exception as e:
                result.status = TokenStatus.INVALID
                result.error_code = "VALIDATION_ERROR"
                result.error_message = "Token validation failed"
                logger.error(f"Unexpected token validation error: {e}")
                return result

        if claims is None:
            result.status = TokenStatus.INVALID
            result.error_code = "TOKEN_INVALID"
            result.error_message = "Token validation failed"
            return result

        try:
            # Extract claims
            jti = claims.get("jti", "")
            jti_hash_value = hash_jti(jti)

            # Build token model
            result.token = PortalToken(
                tenant_id=claims.get("tenant_id"),
                site_id=claims.get("site_id", 0),
                snapshot_id=claims.get("snapshot_id"),
                driver_id=claims.get("driver_id"),
                scope=TokenScope(claims.get("scope", "READ")),
                jti_hash=jti_hash_value,
                issued_at=datetime.fromtimestamp(claims.get("iat")),
                expires_at=datetime.fromtimestamp(claims.get("exp")),
            )

            # Update IP hash if provided
            if ip_address:
                result.token.ip_hash = hash_ip(ip_address)

            result.is_valid = True
            result.status = TokenStatus.VALID

            if used_secondary:
                logger.debug(f"Token validated with SECONDARY key: jti_hash={jti_hash_value[:16]}...")
            else:
                logger.debug(f"Token validated: jti_hash={jti_hash_value[:16]}...")

        except Exception as e:
            result.status = TokenStatus.INVALID
            result.error_code = "VALIDATION_ERROR"
            result.error_message = "Token validation failed"
            logger.error(f"Unexpected token validation error: {e}")

        return result

    def get_jti_hash_from_token(self, raw_token: str) -> Optional[str]:
        """
        Extract jti_hash from a token WITHOUT full validation.

        Useful for logging and rate limiting before full validation.

        Args:
            raw_token: The raw JWT token string

        Returns:
            jti_hash if extractable, None otherwise

        Security:
            - Does NOT verify signature
            - Use only for pre-validation logging/rate-limiting
        """
        try:
            # Decode without verification to extract jti
            claims = jwt.decode(
                raw_token,
                options={"verify_signature": False},
            )
            jti = claims.get("jti", "")
            if jti:
                return hash_jti(jti)
        except Exception:
            pass
        return None

    def build_portal_url(
        self,
        base_url: str,
        raw_token: str,
    ) -> str:
        """
        Build the full portal URL with token.

        Args:
            base_url: Base URL of portal (e.g., https://portal.solvereign.com)
            raw_token: The raw JWT token

        Returns:
            Full URL like https://portal.solvereign.com/my-plan?t=...
        """
        # URL-safe the token
        return f"{base_url.rstrip('/')}/my-plan?t={raw_token}"


# =============================================================================
# REPOSITORY INTERFACE
# =============================================================================

class PortalTokenRepository:
    """
    Repository interface for portal token storage.

    Implementations:
    - PostgreSQL (production)
    - Mock (testing)
    """

    async def save_token(self, token: PortalToken) -> PortalToken:
        """Save a new token to storage."""
        raise NotImplementedError

    async def get_by_jti_hash(self, jti_hash: str) -> Optional[PortalToken]:
        """Get token by jti_hash."""
        raise NotImplementedError

    async def revoke_token(self, jti_hash: str) -> bool:
        """Revoke a token (set revoked_at)."""
        raise NotImplementedError

    async def update_last_seen(self, jti_hash: str) -> bool:
        """Update last_seen_at timestamp."""
        raise NotImplementedError

    async def check_rate_limit(
        self,
        jti_hash: str,
        max_requests: int = 100,
        window_seconds: int = 3600,
    ) -> RateLimitResult:
        """Check and update rate limit for a token."""
        raise NotImplementedError


class MockTokenRepository(PortalTokenRepository):
    """
    Mock repository for testing.
    """

    def __init__(self):
        self._tokens: Dict[str, PortalToken] = {}
        self._rate_counts: Dict[str, int] = {}

    async def save_token(self, token: PortalToken) -> PortalToken:
        """Save token to in-memory storage."""
        token.id = len(self._tokens) + 1
        self._tokens[token.jti_hash] = token
        return token

    async def get_by_jti_hash(self, jti_hash: str) -> Optional[PortalToken]:
        """Get token by jti_hash."""
        return self._tokens.get(jti_hash)

    async def revoke_token(self, jti_hash: str) -> bool:
        """Revoke a token."""
        if jti_hash in self._tokens:
            self._tokens[jti_hash].revoked_at = datetime.utcnow()
            return True
        return False

    async def update_last_seen(self, jti_hash: str) -> bool:
        """Update last_seen_at."""
        if jti_hash in self._tokens:
            self._tokens[jti_hash].last_seen_at = datetime.utcnow()
            return True
        return False

    async def check_rate_limit(
        self,
        jti_hash: str,
        max_requests: int = 100,
        window_seconds: int = 3600,
    ) -> RateLimitResult:
        """Check rate limit."""
        count = self._rate_counts.get(jti_hash, 0) + 1
        self._rate_counts[jti_hash] = count

        return RateLimitResult(
            is_allowed=(count <= max_requests),
            current_count=count,
            max_requests=max_requests,
            window_resets_at=datetime.utcnow() + timedelta(seconds=window_seconds),
        )


# =============================================================================
# COMPOSITE SERVICE (with DB validation)
# =============================================================================

class PortalAuthService:
    """
    High-level authentication service combining token validation with DB checks.

    This is the main service used by API endpoints.
    """

    def __init__(
        self,
        token_service: PortalTokenService,
        repository: PortalTokenRepository,
    ):
        """
        Initialize auth service.

        Args:
            token_service: Token generation/validation service
            repository: Token storage repository
        """
        self.token_service = token_service
        self.repository = repository

    async def validate_and_authorize(
        self,
        raw_token: str,
        required_scope: Optional[TokenScope] = None,
        ip_address: Optional[str] = None,
    ) -> TokenValidationResult:
        """
        Full validation with DB check.

        Args:
            raw_token: The raw JWT token
            required_scope: Required scope (None = any)
            ip_address: Optional IP for rate limiting

        Returns:
            TokenValidationResult with full validation status

        Flow:
            1. Validate JWT signature and expiry
            2. Check DB for token existence and revocation
            3. Check rate limit
            4. Verify scope if required
            5. Update last_seen_at
        """
        # Step 1: Validate JWT
        result = self.token_service.validate_token(raw_token, ip_address)
        if not result.is_valid:
            return result

        token = result.token
        jti_hash = token.jti_hash

        # Step 2: Check DB
        db_token = await self.repository.get_by_jti_hash(jti_hash)
        if db_token is None:
            result.is_valid = False
            result.status = TokenStatus.INVALID
            result.error_code = "TOKEN_NOT_FOUND"
            result.error_message = "Token not found in database"
            logger.warning(f"Token not in DB: jti_hash={jti_hash[:16]}...")
            return result

        # Check revocation
        if db_token.is_revoked:
            result.is_valid = False
            result.status = TokenStatus.REVOKED
            result.error_code = "TOKEN_REVOKED"
            result.error_message = "Token has been revoked"
            logger.info(f"Revoked token used: jti_hash={jti_hash[:16]}...")
            return result

        # Step 3: Rate limit check
        rate_result = await self.repository.check_rate_limit(
            jti_hash,
            self.token_service.config.rate_limit_max,
            self.token_service.config.rate_limit_window_seconds,
        )
        if not rate_result.is_allowed:
            result.is_valid = False
            result.status = TokenStatus.RATE_LIMITED
            result.rate_limited = True
            result.retry_after_seconds = rate_result.retry_after_seconds
            result.error_code = "RATE_LIMITED"
            result.error_message = f"Too many requests. Retry after {rate_result.retry_after_seconds}s"
            logger.warning(f"Rate limited: jti_hash={jti_hash[:16]}...")
            return result

        # Step 4: Check scope
        if required_scope:
            if required_scope == TokenScope.READ and not token.can_read:
                result.is_valid = False
                result.status = TokenStatus.INVALID
                result.error_code = "INSUFFICIENT_SCOPE"
                result.error_message = "Token does not have READ permission"
                return result
            if required_scope == TokenScope.ACK and not token.can_ack:
                result.is_valid = False
                result.status = TokenStatus.INVALID
                result.error_code = "INSUFFICIENT_SCOPE"
                result.error_message = "Token does not have ACK permission"
                return result

        # Step 5: Update last_seen
        await self.repository.update_last_seen(jti_hash)

        # Use DB token data (more authoritative)
        result.token = db_token
        result.token.last_seen_at = datetime.utcnow()

        return result

    async def revoke_token_after_ack(self, jti_hash: str) -> bool:
        """
        Revoke a token after successful ACK (single-use).

        Args:
            jti_hash: The token's jti_hash

        Returns:
            True if revoked successfully
        """
        if not self.token_service.config.revoke_after_ack:
            return False

        success = await self.repository.revoke_token(jti_hash)
        if success:
            logger.info(f"Token revoked after ACK: jti_hash={jti_hash[:16]}...")
        return success


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_token_service(config: Optional[TokenConfig] = None) -> PortalTokenService:
    """Create a token service with optional custom config."""
    return PortalTokenService(config)


def create_mock_auth_service() -> Tuple[PortalAuthService, MockTokenRepository]:
    """Create an auth service with mock repository for testing."""
    token_service = create_token_service()
    repository = MockTokenRepository()
    auth_service = PortalAuthService(token_service, repository)
    return auth_service, repository
