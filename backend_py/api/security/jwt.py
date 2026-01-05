"""
SOLVEREIGN V3.3b - JWT Authentication
======================================

RS256 JWT validation with:
- Public key verification (asymmetric)
- Claims extraction
- Token expiry handling
- Issuer/audience validation
- MFA verification flag

Supports both:
- External IdP (Keycloak, Auth0)
- Internal JWT generation (for migration)
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from functools import lru_cache

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# =============================================================================
# JWT CLAIMS
# =============================================================================

@dataclass
class JWTClaims:
    """
    Validated JWT claims.

    Mapped from standard OIDC claims:
    - sub: User ID
    - tenant_id: Custom claim for tenant isolation
    - roles: User roles for RBAC
    - permissions: Fine-grained permissions
    """
    sub: str                          # User ID (subject)
    tenant_id: str                    # Tenant UUID (custom claim)
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    email: Optional[str] = None
    name: Optional[str] = None
    mfa_verified: bool = False        # MFA status
    iss: Optional[str] = None         # Issuer
    aud: Optional[str] = None         # Audience
    exp: int = 0                      # Expiry timestamp
    iat: int = 0                      # Issued at timestamp

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return time.time() > self.exp

    @property
    def user_id(self) -> str:
        """Alias for sub."""
        return self.sub

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions

    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if user has any of the given permissions."""
        return bool(set(permissions) & set(self.permissions))

    def has_all_permissions(self, permissions: List[str]) -> bool:
        """Check if user has all of the given permissions."""
        return set(permissions).issubset(set(self.permissions))


# =============================================================================
# JWT VALIDATOR
# =============================================================================

class JWTValidator:
    """
    JWT validation using RS256 (asymmetric).

    Security features:
    - Public key verification (private key never leaves IdP)
    - Issuer whitelist validation
    - Audience validation
    - Expiry check with clock skew tolerance
    - Required claims validation

    Configuration:
    - JWKS URL for key rotation support
    - Or static public key for simpler setup
    """

    def __init__(
        self,
        jwks_url: Optional[str] = None,
        public_key: Optional[str] = None,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        clock_skew_seconds: int = 30,
    ):
        self.jwks_url = jwks_url
        self.public_key = public_key
        self.issuer = issuer
        self.audience = audience
        self.clock_skew = clock_skew_seconds
        self._jwks_cache: Dict[str, Any] = {}
        self._cache_time: float = 0
        self._cache_ttl: int = 3600  # 1 hour

    async def validate(self, token: str) -> JWTClaims:
        """
        Validate JWT and return claims.

        Raises HTTPException on validation failure.
        """
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT library not installed. Run: pip install PyJWT[crypto]"
            )

        try:
            # Get signing key
            if self.jwks_url:
                signing_key = await self._get_signing_key_from_jwks(token)
            elif self.public_key:
                signing_key = self.public_key
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="JWT validator not configured with key source"
                )

            # Decode and validate
            options = {
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "require": ["sub", "exp", "iat"],
            }

            # Add issuer/audience validation if configured
            decode_kwargs = {
                "algorithms": ["RS256", "ES256"],  # Allow RSA and ECDSA
                "options": options,
                "leeway": self.clock_skew,
            }

            if self.issuer:
                decode_kwargs["issuer"] = self.issuer
                options["verify_iss"] = True

            if self.audience:
                decode_kwargs["audience"] = self.audience
                options["verify_aud"] = True

            # Decode token
            payload = jwt.decode(token, signing_key, **decode_kwargs)

            # Extract claims
            claims = JWTClaims(
                sub=payload["sub"],
                tenant_id=payload.get("tenant_id", payload.get("tid", "")),
                roles=payload.get("roles", payload.get("realm_access", {}).get("roles", [])),
                permissions=payload.get("permissions", payload.get("scope", "").split()),
                email=payload.get("email"),
                name=payload.get("name", payload.get("preferred_username")),
                mfa_verified=payload.get("mfa_verified", payload.get("amr", []) != []),
                iss=payload.get("iss"),
                aud=payload.get("aud"),
                exp=payload.get("exp", 0),
                iat=payload.get("iat", 0),
            )

            # Validate tenant_id is present
            if not claims.tenant_id:
                logger.warning(
                    "jwt_missing_tenant_id",
                    extra={"sub": claims.sub}
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token missing tenant_id claim"
                )

            return claims

        except jwt.ExpiredSignatureError:
            logger.info("jwt_expired", extra={"token_prefix": token[:20]})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.InvalidIssuerError:
            logger.warning("jwt_invalid_issuer", extra={"token_prefix": token[:20]})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token issuer",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.InvalidAudienceError:
            logger.warning("jwt_invalid_audience", extra={"token_prefix": token[:20]})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token audience",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.InvalidSignatureError:
            logger.warning("jwt_invalid_signature", extra={"token_prefix": token[:20]})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signature",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.DecodeError as e:
            logger.warning("jwt_decode_error", extra={"error": str(e)})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except Exception as e:
            logger.error("jwt_validation_error", extra={"error": str(e)})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token validation failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def _get_signing_key_from_jwks(self, token: str) -> str:
        """
        Get signing key from JWKS endpoint.

        Caches JWKS for performance, refreshes on cache miss.
        """
        import jwt
        from jwt import PyJWKClient

        # Check cache freshness
        now = time.time()
        if now - self._cache_time > self._cache_ttl:
            self._jwks_cache = {}
            self._cache_time = now

        # Get key ID from token header
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token header"
            )

        # Check cache
        if kid in self._jwks_cache:
            return self._jwks_cache[kid]

        # Fetch from JWKS
        try:
            jwks_client = PyJWKClient(self.jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            # Cache the key
            if kid:
                self._jwks_cache[kid] = signing_key.key

            return signing_key.key

        except Exception as e:
            logger.error("jwks_fetch_error", extra={
                "jwks_url": self.jwks_url,
                "error": str(e)
            })
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to validate token (IdP unavailable)"
            )


# =============================================================================
# FASTAPI DEPENDENCIES
# =============================================================================

# HTTP Bearer security scheme
bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache()
def get_jwt_validator() -> JWTValidator:
    """
    Get configured JWT validator.

    Configuration via environment variables:
    - SOLVEREIGN_JWT_JWKS_URL: JWKS endpoint URL
    - SOLVEREIGN_JWT_PUBLIC_KEY: Static public key (PEM)
    - SOLVEREIGN_JWT_ISSUER: Expected issuer
    - SOLVEREIGN_JWT_AUDIENCE: Expected audience
    """
    import os

    return JWTValidator(
        jwks_url=os.getenv("SOLVEREIGN_JWT_JWKS_URL"),
        public_key=os.getenv("SOLVEREIGN_JWT_PUBLIC_KEY"),
        issuer=os.getenv("SOLVEREIGN_JWT_ISSUER"),
        audience=os.getenv("SOLVEREIGN_JWT_AUDIENCE", "solvereign-api"),
    )


async def get_jwt_claims(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[JWTClaims]:
    """
    Extract and validate JWT claims from Authorization header.

    Returns None if no Bearer token provided.
    Raises HTTPException on validation failure.

    Usage:
        @router.get("/protected")
        async def protected_route(claims: JWTClaims = Depends(get_jwt_claims)):
            if not claims:
                raise HTTPException(401, "Authentication required")
            return {"user": claims.sub}
    """
    if not credentials:
        return None

    validator = get_jwt_validator()
    return await validator.validate(credentials.credentials)


async def require_jwt(
    claims: Optional[JWTClaims] = Depends(get_jwt_claims),
) -> JWTClaims:
    """
    Require valid JWT token.

    Raises 401 if no token or invalid token.

    Usage:
        @router.get("/protected")
        async def protected_route(claims: JWTClaims = Depends(require_jwt)):
            return {"user": claims.sub}
    """
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


async def require_mfa(
    claims: JWTClaims = Depends(require_jwt),
) -> JWTClaims:
    """
    Require valid JWT with MFA verification.

    Raises 403 if MFA not verified.

    Usage:
        @router.post("/sensitive-action")
        async def sensitive_action(claims: JWTClaims = Depends(require_mfa)):
            return {"approved": True}
    """
    if not claims.mfa_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA verification required",
        )
    return claims
