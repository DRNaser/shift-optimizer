"""
SOLVEREIGN V3.3b Security Module
================================

Defense-in-depth security implementation:
- JWT authentication (RS256)
- RBAC authorization
- Security headers
- Rate limiting
- Audit logging
- Token blacklist (Redis)
- Token refresh with rotation
- PII encryption (AES-256-GCM)
"""

from .jwt import JWTValidator, JWTClaims, get_jwt_claims
from .rbac import Permission, Role, PermissionChecker, require_permissions
from .headers import SecurityHeadersMiddleware
from .rate_limit import RateLimiter, RateLimitExceeded
from .audit import SecurityAuditLogger, AuditEvent
from .token_blacklist import TokenBlacklist, get_token_blacklist, check_token_not_revoked
from .token_refresh import TokenRefreshService, TokenPair, get_token_refresh_service
from .encryption import PIIEncryptor, KeyManager, get_pii_encryptor, PIIFields, DriverPII

__all__ = [
    # JWT
    "JWTValidator",
    "JWTClaims",
    "get_jwt_claims",
    # RBAC
    "Permission",
    "Role",
    "PermissionChecker",
    "require_permissions",
    # Headers
    "SecurityHeadersMiddleware",
    # Rate Limiting
    "RateLimiter",
    "RateLimitExceeded",
    # Audit
    "SecurityAuditLogger",
    "AuditEvent",
    # Token Blacklist
    "TokenBlacklist",
    "get_token_blacklist",
    "check_token_not_revoked",
    # Token Refresh
    "TokenRefreshService",
    "TokenPair",
    "get_token_refresh_service",
    # PII Encryption
    "PIIEncryptor",
    "KeyManager",
    "get_pii_encryptor",
    "PIIFields",
    "DriverPII",
]
