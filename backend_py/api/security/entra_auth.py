"""
SOLVEREIGN V3.3b - Microsoft Entra ID Authentication
=====================================================

!!! DEPRECATED (V4.4.0) !!!
===========================
This module is DEPRECATED as of V4.4.0 (2026-01-09).
Internal RBAC (backend_py/api/security/internal_rbac.py) is now the default.

REASON: Microsoft Entra ID was replaced with internal email/password authentication
to simplify deployment and reduce external dependencies for the Wien Pilot.

MIGRATION: Use internal_rbac.py instead:
- require_session() instead of get_current_user()
- require_permission() instead of RequireRole()
- Session cookies instead of Bearer tokens

This file is kept for reference and potential future multi-tenant SSO integration.
DO NOT USE for new development.

---

Original documentation (historical):

OIDC/JWT authentication with:
- RS256 JWT validation via JWKS
- Tenant mapping: Entra tid -> internal tenant_id via tenant_identities table
- RBAC via Entra App Roles (roles claim)
- RLS context setting per transaction

NON-NEGOTIABLES:
- Tenant ID comes from JWT tid claim, NEVER from client headers in production
- Roles come from Entra App Roles, NEVER from client headers
- RLS (app.current_tenant_id) set per transaction
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from functools import lru_cache

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)


# =============================================================================
# AUTHENTICATED USER CONTEXT
# =============================================================================

@dataclass
class EntraUserContext:
    """
    Authenticated user context from Entra ID token.

    This is the ONLY source of tenant_id and roles in production.
    """
    # User identity
    user_id: str                          # sub claim (Azure AD Object ID)
    email: Optional[str] = None           # email or preferred_username
    name: Optional[str] = None            # name claim

    # Tenant (mapped from Entra tid)
    tenant_id: int = 0                    # Internal tenant_id (from tenant_identities)
    entra_tenant_id: str = ""             # Original Entra tid claim

    # RBAC
    roles: List[str] = field(default_factory=list)        # From roles claim (App Roles)
    permissions: Set[str] = field(default_factory=set)    # Expanded from roles

    # Token metadata
    issuer: str = ""                      # iss claim
    audience: str = ""                    # aud claim
    token_type: str = "user"              # "user" or "app" (client credentials)
    expires_at: int = 0                   # exp claim

    # App-only tokens (client credentials)
    app_id: Optional[str] = None          # azp or appid claim

    @property
    def is_app_token(self) -> bool:
        """Check if this is an app-only token (client credentials flow)."""
        return self.token_type == "app"

    def has_role(self, role: str) -> bool:
        """Check if user has specific role (case-insensitive)."""
        return role.lower() in [r.lower() for r in self.roles]

    def has_any_role(self, roles: List[str]) -> bool:
        """Check if user has any of the specified roles."""
        user_roles_lower = {r.lower() for r in self.roles}
        return bool(user_roles_lower & {r.lower() for r in roles})


# =============================================================================
# ENTRA ROLE MAPPING
# =============================================================================

# Entra App Roles -> Internal Role Names
# Configure these in Azure AD App Registration > App Roles
ENTRA_ROLE_MAPPING = {
    # Entra App Role Value -> Internal Role
    "TENANT_ADMIN": "tenant_admin",
    "TenantAdmin": "tenant_admin",
    "PLANNER": "dispatcher",
    "Planner": "dispatcher",
    "APPROVER": "plan_approver",
    "Approver": "plan_approver",
    "VIEWER": "viewer",
    "Viewer": "viewer",
    "DISPATCHER": "dispatcher",
    "Dispatcher": "dispatcher",
}

# M2M (app-only) tokens cannot have APPROVER role
# This prevents automation from locking plans without human approval
RESTRICTED_APP_ROLES = {"plan_approver", "tenant_admin"}


def map_entra_roles(entra_roles: List[str], is_app_token: bool = False) -> List[str]:
    """
    Map Entra App Roles to internal role names.

    Args:
        entra_roles: Roles from Entra token (roles claim)
        is_app_token: True if client credentials (app-only) token

    Returns:
        List of internal role names
    """
    internal_roles = []

    for entra_role in entra_roles:
        internal_role = ENTRA_ROLE_MAPPING.get(entra_role)
        if internal_role:
            # M2M tokens cannot have restricted roles
            if is_app_token and internal_role in RESTRICTED_APP_ROLES:
                logger.warning(
                    "app_token_restricted_role_blocked",
                    extra={
                        "entra_role": entra_role,
                        "internal_role": internal_role,
                        "reason": "M2M tokens cannot have APPROVER or TENANT_ADMIN roles"
                    }
                )
                continue
            internal_roles.append(internal_role)

    return internal_roles


# =============================================================================
# JWT VALIDATION WITH ENTRA ID
# =============================================================================

class EntraJWTValidator:
    """
    JWT validation specifically for Microsoft Entra ID (Azure AD).

    Features:
    - JWKS caching with kid rotation handling
    - v2.0 endpoint support
    - Multi-tenant issuer validation
    - Clock skew tolerance
    """

    def __init__(
        self,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        allowed_issuers: Optional[List[str]] = None,
        clock_skew_seconds: int = 60,
    ):
        self.issuer = issuer
        self.audience = audience
        self.allowed_issuers = allowed_issuers or []
        self.clock_skew = clock_skew_seconds
        self._jwks_clients: Dict[str, Any] = {}
        self._cache_time: float = 0
        self._cache_ttl: int = 3600  # 1 hour JWKS cache

    async def validate(self, token: str) -> Dict[str, Any]:
        """
        Validate Entra ID JWT and return claims.

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
            # Decode header to get issuer hint and kid
            header = jwt.get_unverified_header(token)
            unverified = jwt.decode(token, options={"verify_signature": False})
            token_issuer = unverified.get("iss", "")
            kid = header.get("kid")

            # Validate issuer is allowed
            if not self._is_issuer_allowed(token_issuer):
                logger.warning(
                    "entra_invalid_issuer",
                    extra={"issuer": token_issuer, "allowed": self.allowed_issuers}
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token issuer",
                    headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
                )

            # Get signing key from JWKS
            signing_key = await self._get_signing_key(token_issuer, token)

            # Validate token
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=token_issuer,
                leeway=self.clock_skew,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "require": ["sub", "exp", "iat", "aud", "iss"],
                }
            )

            # Ensure tid is present (required for tenant mapping)
            if "tid" not in payload:
                logger.warning("entra_missing_tid", extra={"sub": payload.get("sub")})
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "MISSING_TID",
                        "message": "Token missing tid claim. Ensure correct Entra app configuration."
                    }
                )

            return payload

        except jwt.ExpiredSignatureError:
            logger.info("entra_token_expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.InvalidAudienceError:
            logger.warning("entra_invalid_audience")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token audience",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.InvalidIssuerError:
            logger.warning("entra_invalid_issuer")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token issuer",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.InvalidSignatureError:
            logger.warning("entra_invalid_signature")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signature",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except jwt.DecodeError as e:
            logger.warning("entra_decode_error", extra={"error": str(e)})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
                headers={"WWW-Authenticate": "Bearer error='invalid_token'"},
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("entra_validation_error", extra={"error": str(e)})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token validation failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def _is_issuer_allowed(self, issuer: str) -> bool:
        """Check if issuer is in allowed list."""
        # If specific issuer configured, use it
        if self.issuer and issuer == self.issuer:
            return True

        # Check allowed issuers list
        if self.allowed_issuers:
            # Support wildcard for multi-tenant: https://login.microsoftonline.com/*/v2.0
            for allowed in self.allowed_issuers:
                if allowed.endswith("/*"):
                    # Wildcard match
                    prefix = allowed[:-1]  # Remove *
                    if issuer.startswith(prefix):
                        return True
                elif issuer == allowed:
                    return True
            return False

        # If no restrictions, allow common Entra issuers
        return issuer.startswith("https://login.microsoftonline.com/")

    async def _get_signing_key(self, issuer: str, token: str):
        """Get signing key from JWKS endpoint."""
        import jwt
        from jwt import PyJWKClient

        # Build JWKS URL from issuer
        # Entra v2.0: https://login.microsoftonline.com/{tid}/v2.0 ->
        #            https://login.microsoftonline.com/{tid}/discovery/v2.0/keys
        jwks_url = issuer.replace("/v2.0", "/discovery/v2.0/keys")
        if not jwks_url.endswith("/keys"):
            jwks_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

        # Get or create JWKS client (cached)
        now = time.time()
        if now - self._cache_time > self._cache_ttl:
            self._jwks_clients = {}
            self._cache_time = now

        if issuer not in self._jwks_clients:
            try:
                self._jwks_clients[issuer] = PyJWKClient(jwks_url)
            except Exception as e:
                logger.error("jwks_client_error", extra={
                    "jwks_url": jwks_url,
                    "error": str(e)
                })
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch signing keys (IdP unavailable)"
                )

        try:
            signing_key = self._jwks_clients[issuer].get_signing_key_from_jwt(token)
            return signing_key.key
        except Exception as e:
            logger.error("jwks_key_error", extra={"error": str(e)})
            # Invalidate cache and retry once
            del self._jwks_clients[issuer]
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to validate token (key fetch failed)"
            )


# =============================================================================
# FASTAPI DEPENDENCIES
# =============================================================================

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache()
def get_entra_validator() -> EntraJWTValidator:
    """Get configured Entra JWT validator from settings."""
    from ..config import settings

    # Build allowed issuers
    allowed_issuers = list(settings.oidc_allowed_issuers) if settings.oidc_allowed_issuers else []

    # Add explicit issuer if configured
    if settings.oidc_issuer and settings.oidc_issuer not in allowed_issuers:
        allowed_issuers.append(settings.oidc_issuer)

    # Add Entra tenant-specific issuer if configured
    if settings.entra_tenant_id:
        entra_issuer = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0"
        if entra_issuer not in allowed_issuers:
            allowed_issuers.append(entra_issuer)

    return EntraJWTValidator(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        allowed_issuers=allowed_issuers,
        clock_skew_seconds=settings.oidc_clock_skew_seconds,
    )


async def get_tenant_id_from_tid(
    request: Request,
    issuer: str,
    entra_tid: str,
) -> int:
    """
    Map Entra tid to internal tenant_id via tenant_identities table.

    Raises 403 TENANT_NOT_MAPPED if no mapping exists.
    """
    # Get DB from app state
    db = request.app.state.db

    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT ti.tenant_id
                FROM tenant_identities ti
                JOIN tenants t ON ti.tenant_id = t.id
                WHERE ti.issuer = %s
                  AND ti.external_tid = %s
                  AND ti.is_active = TRUE
                  AND t.is_active = TRUE
                """,
                (issuer, entra_tid)
            )
            row = await cur.fetchone()

            if not row:
                logger.warning(
                    "tenant_not_mapped",
                    extra={"issuer": issuer, "entra_tid": entra_tid}
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "TENANT_NOT_MAPPED",
                        "message": "No tenant mapping found for this Entra tenant. Contact administrator.",
                        "entra_tid": entra_tid,
                    }
                )

            return row["tenant_id"]


async def set_rls_context(request: Request, tenant_id: int) -> None:
    """
    Store tenant_id in request state for later use with tenant_connection().

    NOTE: This does NOT set RLS on a database connection directly.
    Request handlers MUST use db.tenant_connection(tenant_id) or
    db.tenant_transaction(tenant_id) to get a properly RLS-scoped connection.

    The old implementation opened a new connection, set RLS, then that
    connection went back to the pool - causing RLS leakage between requests.
    """
    # Store in request state - actual RLS is set by db.tenant_connection()
    request.state.tenant_id = tenant_id
    logger.debug(
        "rls_tenant_stored",
        extra={"tenant_id": tenant_id}
    )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> EntraUserContext:
    """
    Main authentication dependency for Entra ID.

    Validates JWT, maps tenant, extracts roles, sets RLS context.

    Usage:
        @router.get("/protected")
        async def protected_route(user: EntraUserContext = Depends(get_current_user)):
            # tenant_id and roles already validated
            return {"user": user.user_id, "tenant": user.tenant_id}
    """
    from ..config import settings

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate JWT
    validator = get_entra_validator()
    claims = await validator.validate(credentials.credentials)

    # Extract Entra-specific claims
    entra_tid = claims.get("tid", "")
    issuer = claims.get("iss", "")
    sub = claims.get("sub", "")

    # Detect app-only token (client credentials)
    # App tokens have azp (authorized party) or roles directly assigned to service principal
    is_app_token = "azp" in claims or claims.get("idtyp") == "app"

    # Map Entra tid -> internal tenant_id
    tenant_id = await get_tenant_id_from_tid(request, issuer, entra_tid)

    # Extract and map roles from Entra App Roles
    entra_roles = claims.get("roles", [])
    internal_roles = map_entra_roles(entra_roles, is_app_token=is_app_token)

    # Build user context
    user = EntraUserContext(
        user_id=sub,
        email=claims.get("email") or claims.get("preferred_username"),
        name=claims.get("name"),
        tenant_id=tenant_id,
        entra_tenant_id=entra_tid,
        roles=internal_roles,
        issuer=issuer,
        audience=claims.get("aud", ""),
        token_type="app" if is_app_token else "user",
        expires_at=claims.get("exp", 0),
        app_id=claims.get("azp") or claims.get("appid"),
    )

    # Set RLS context for this request
    await set_rls_context(request, tenant_id)

    # Store in request state for middleware access
    request.state.user = user
    request.state.tenant_id = tenant_id

    logger.info(
        "auth_success",
        extra={
            "user_id": user.user_id,
            "tenant_id": tenant_id,
            "roles": internal_roles,
            "token_type": user.token_type,
        }
    )

    return user


async def require_role(
    required_roles: List[str],
    user: EntraUserContext = Depends(get_current_user),
) -> EntraUserContext:
    """
    Require user to have at least one of the specified roles.

    Usage:
        @router.post("/plans/{id}/lock")
        async def lock_plan(
            plan_id: int,
            user: EntraUserContext = Depends(lambda: require_role(["plan_approver", "tenant_admin"]))
        ):
            ...
    """
    if not user.has_any_role(required_roles):
        logger.warning(
            "insufficient_role",
            extra={
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "required_roles": required_roles,
                "user_roles": user.roles,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "INSUFFICIENT_ROLE",
                "message": f"This action requires one of: {', '.join(required_roles)}",
                "required_roles": required_roles,
            }
        )
    return user


def RequireRole(*roles: str):
    """
    Dependency factory for role requirement.

    Usage:
        @router.post("/plans/{id}/lock")
        async def lock_plan(
            plan_id: int,
            user: EntraUserContext = Depends(RequireRole("plan_approver", "tenant_admin"))
        ):
            ...
    """
    async def dependency(user: EntraUserContext = Depends(get_current_user)) -> EntraUserContext:
        return await require_role(list(roles), user)
    return dependency


# Convenience dependencies
RequireApprover = RequireRole("plan_approver", "tenant_admin")
RequireDispatcher = RequireRole("dispatcher", "plan_approver", "tenant_admin")
RequireViewer = RequireRole("viewer", "dispatcher", "plan_approver", "tenant_admin")
RequireTenantAdmin = RequireRole("tenant_admin")
