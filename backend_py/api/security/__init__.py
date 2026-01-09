"""
SOLVEREIGN V3.7 Security Module
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

V3.7 Auth Separation:
- Platform Auth: Session cookies + CSRF (platform_auth.py)
- Tenant Auth: API Key + HMAC + Nonce (tenant_auth.py)
- Internal Auth: BFF HMAC signatures (internal_signature.py)
"""

from .jwt import JWTValidator, JWTClaims, get_jwt_claims
from .rbac import Permission, Role, PermissionChecker, require_permissions
from .headers import SecurityHeadersMiddleware
from .rate_limit import RateLimiter, RateLimitExceeded
from .audit import SecurityAuditLogger, AuditEvent
from .token_blacklist import TokenBlacklist, get_token_blacklist, check_token_not_revoked
from .token_refresh import TokenRefreshService, TokenPair, get_token_refresh_service
from .encryption import PIIEncryptor, KeyManager, get_pii_encryptor, PIIFields, DriverPII

# V3.7 Auth Separation
from .platform_auth import (
    PlatformUser,
    PlatformRole,
    SessionStore,
    require_platform_session,
    get_optional_platform_session,
    create_session,
    destroy_session,
    dev_login,
    is_dev_login_blocked,
    session_store,
)
from .tenant_auth import (
    TenantHMACContext,
    require_tenant_hmac,
    get_optional_tenant_hmac,
    compute_tenant_signature,
    generate_client_headers,
    save_idempotency_response,
)
from .internal_signature import (
    InternalContext,
    require_internal_signature,
    get_trusted_context,
    require_platform_admin,
    generate_signature_v2,
    verify_internal_request,
    InternalSignatureMiddleware,
)

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
    # V3.7 Platform Auth
    "PlatformUser",
    "PlatformRole",
    "SessionStore",
    "require_platform_session",
    "get_optional_platform_session",
    "create_session",
    "destroy_session",
    "dev_login",
    "is_dev_login_blocked",
    "session_store",
    # V3.7 Tenant HMAC Auth
    "TenantHMACContext",
    "require_tenant_hmac",
    "get_optional_tenant_hmac",
    "compute_tenant_signature",
    "generate_client_headers",
    "save_idempotency_response",
    # V3.7 Internal Auth
    "InternalContext",
    "require_internal_signature",
    "get_trusted_context",
    "require_platform_admin",
    "generate_signature_v2",
    "verify_internal_request",
    "InternalSignatureMiddleware",
]
