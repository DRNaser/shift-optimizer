"""
SOLVEREIGN V4.4 - Internal RBAC Authentication
===============================================

Internal Role-Based Access Control replacing Entra ID for Portal-Admin:
- Argon2id password hashing
- Server-side session storage with HttpOnly cookies
- Tenant/site isolation via user bindings
- Permission-based authorization

NON-NEGOTIABLES:
- Tenant ID comes from user binding, NEVER from client headers
- Sessions stored server-side, cookie contains only session ID hash
- No secrets/passwords in logs
"""

import os
import hashlib
import secrets
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Set, Any

import psycopg
from psycopg.rows import tuple_row
from fastapi import Request, Response, HTTPException, status, Depends, Cookie
from fastapi.responses import JSONResponse

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError
except ImportError:
    PasswordHasher = None  # Will fail at runtime with helpful message
    VerifyMismatchError = Exception
    VerificationError = Exception

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Session cookie configuration
# Production: __Host-sv_platform_session (requires Secure, HTTPS)
# Development: sv_platform_session (works on HTTP localhost)
def _get_session_cookie_name() -> str:
    """Get cookie name based on environment."""
    import os
    env = os.environ.get("SOLVEREIGN_ENVIRONMENT", "development").lower()
    if env in ("production", "staging"):
        # __Host- prefix enforces: Secure=true, Path=/, no Domain attribute
        return "__Host-sv_platform_session"
    else:
        # Development: no __Host- prefix (works on HTTP localhost)
        return "sv_platform_session"

SESSION_COOKIE_NAME = _get_session_cookie_name()
SESSION_COOKIE_MAX_AGE = 8 * 60 * 60  # 8 hours sliding window
SESSION_ABSOLUTE_MAX_AGE = 24 * 60 * 60  # 24 hours absolute cap
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "strict"  # Strict for CSRF protection on admin ops
SESSION_COOKIE_PATH = "/"  # Global path - different name from portal_session avoids collision

# Repair session TTL configuration
REPAIR_SESSION_SLIDING_TTL_MINUTES = 30  # 30 minutes sliding window
REPAIR_SESSION_ABSOLUTE_CAP_MINUTES = 120  # 2 hours absolute cap


def _get_cookie_secure_flag() -> bool:
    """
    Determine Secure flag based on environment.

    Returns True for production/staging (__Host- requires Secure),
    False for development (HTTP localhost).
    """
    import os
    env = os.environ.get("SOLVEREIGN_ENVIRONMENT", "development").lower()
    # Also check for explicit override
    explicit = os.environ.get("SOLVEREIGN_COOKIE_SECURE", "").lower()
    if explicit in ("true", "1", "yes"):
        return True
    if explicit in ("false", "0", "no"):
        return False
    # Default: secure in production/staging, not in development
    return env in ("production", "staging")

# Password policy
MAX_FAILED_ATTEMPTS = 10  # Lock account after this many failures

# Rate limiting
# E2E_BYPASS_RATE_LIMIT can be set to disable rate limiting during E2E tests
E2E_BYPASS_RATE_LIMIT = os.environ.get("E2E_BYPASS_RATE_LIMIT", "").lower() in ("1", "true", "yes")
LOGIN_RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes
LOGIN_RATE_LIMIT_MAX = 5 if not E2E_BYPASS_RATE_LIMIT else 1000  # Max attempts per IP in window


# =============================================================================
# PASSWORD HASHING
# =============================================================================

def get_password_hasher() -> PasswordHasher:
    """Get Argon2id password hasher with OWASP-recommended parameters."""
    if PasswordHasher is None:
        raise ImportError(
            "argon2-cffi is required for internal RBAC. "
            "Install with: pip install argon2-cffi>=23.1.0"
        )
    return PasswordHasher(
        time_cost=3,        # Iterations
        memory_cost=65536,  # 64MB memory
        parallelism=4,      # Threads
        hash_len=32,        # Output hash length
        salt_len=16,        # Salt length
    )


def hash_password(password: str) -> str:
    """
    Hash a password using Argon2id.

    Args:
        password: Plain text password

    Returns:
        Argon2id hash string
    """
    return get_password_hasher().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its Argon2id hash.

    Args:
        password: Plain text password to verify
        password_hash: Stored Argon2id hash

    Returns:
        True if password matches, False otherwise
    """
    try:
        get_password_hasher().verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Check if password hash needs to be rehashed with current parameters."""
    try:
        return get_password_hasher().check_needs_rehash(password_hash)
    except Exception:
        return False


# =============================================================================
# SESSION TOKEN GENERATION
# =============================================================================

def generate_session_token() -> str:
    """
    Generate a cryptographically secure session token.

    Returns:
        64-character hex token (32 bytes entropy)
    """
    return secrets.token_hex(32)


def hash_session_token(token: str) -> str:
    """
    Hash a session token for storage.

    Args:
        token: Plain session token

    Returns:
        SHA-256 hash of token (64 hex chars)
    """
    return hashlib.sha256(token.encode()).hexdigest()


def hash_ip(ip: Optional[str]) -> Optional[str]:
    """Hash an IP address for privacy-safe storage."""
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()


def hash_user_agent(user_agent: Optional[str]) -> Optional[str]:
    """Hash a user agent for privacy-safe storage."""
    if not user_agent:
        return None
    return hashlib.sha256(user_agent.encode()).hexdigest()


# =============================================================================
# USER CONTEXT
# =============================================================================

@dataclass
class InternalUserContext:
    """
    Authenticated user context from internal RBAC.

    This is the source of tenant_id and permissions for portal-admin.

    Platform Admin Scoping (Role-Based):
    - Platform admins identified by role_name="platform_admin" ONLY
    - tenant_id=None means platform-wide access (no tenant restriction)
    - Platform admins can access any tenant's data via target_tenant_id parameter
    - Regular users are bound to their tenant_id and cannot access other tenants

    Active Context (Platform Admin Only):
    - active_tenant_id/active_site_id track the platform admin's current working context
    - When set, allows platform admin to use tenant-scoped UIs without bindings
    - Context can be switched via POST /api/platform/context
    """
    # User identity
    user_id: str                              # UUID from auth.users
    email: str
    display_name: Optional[str] = None

    # Tenant/site scope (from user_binding)
    # tenant_id=None for platform admin (platform-wide access)
    tenant_id: Optional[int] = None
    site_id: Optional[int] = None

    # RBAC
    role_id: int = 0
    role_name: str = ""
    permissions: Set[str] = field(default_factory=set)

    # Session metadata
    session_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_platform_scope: bool = False  # Explicit flag from session

    # Active context (platform admin only)
    active_tenant_id: Optional[int] = None
    active_site_id: Optional[int] = None

    @property
    def is_platform_admin(self) -> bool:
        """
        Check if user is a platform admin.

        Platform admins identified by role_name ONLY, not tenant_id.
        """
        return self.role_name == "platform_admin"

    @property
    def has_active_context(self) -> bool:
        """Check if platform admin has set an active tenant context."""
        return self.is_platform_admin and self.active_tenant_id is not None

    def has_permission(self, permission: str) -> bool:
        """Check if user has specific permission."""
        return permission in self.permissions

    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if user has any of the specified permissions."""
        return bool(self.permissions & set(permissions))

    def can_access_tenant(self, target_tenant_id: int) -> bool:
        """
        Check if user can access the specified tenant.

        Platform admins can access any tenant.
        Regular users can only access their bound tenant.
        """
        if self.is_platform_admin:
            return True
        return self.tenant_id is not None and self.tenant_id == target_tenant_id

    def get_effective_tenant_id(self, target_tenant_id: Optional[int] = None) -> Optional[int]:
        """
        Get the effective tenant ID for data access.

        Priority:
        1. Explicit target_tenant_id parameter (for platform admin API calls)
        2. Active context (for platform admin using tenant UIs)
        3. Binding context (for regular users)

        Args:
            target_tenant_id: Optional target tenant for platform admins

        Returns:
            Effective tenant ID for RLS context, or None for platform-wide access
        """
        if self.is_platform_admin:
            # Explicit target takes priority
            if target_tenant_id is not None:
                return target_tenant_id
            # Then active context
            if self.active_tenant_id is not None:
                return self.active_tenant_id
        return self.tenant_id

    def get_effective_site_id(self, target_site_id: Optional[int] = None) -> Optional[int]:
        """
        Get the effective site ID for data access.

        Args:
            target_site_id: Optional target site for platform admins

        Returns:
            Effective site ID, or None for tenant-wide access
        """
        if self.is_platform_admin:
            if target_site_id is not None:
                return target_site_id
            if self.active_site_id is not None:
                return self.active_site_id
        return self.site_id


# =============================================================================
# SESSION COOKIE HANDLING
# =============================================================================

def set_session_cookie(response: Response, token: str, max_age: int = SESSION_COOKIE_MAX_AGE) -> None:
    """
    Set the session cookie on a response.

    Args:
        response: FastAPI response object
        token: Session token (plain, not hashed)
        max_age: Cookie max age in seconds
    """
    secure = _get_cookie_secure_flag()
    logger.debug(f"Setting session cookie with secure={secure}")
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=SESSION_COOKIE_HTTPONLY,
        secure=secure,
        samesite=SESSION_COOKIE_SAMESITE,
        path=SESSION_COOKIE_PATH,
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the session cookie from a response."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
    )
    # Also clear legacy cookie name for backward compatibility
    response.delete_cookie(
        key="admin_session",
        path=SESSION_COOKIE_PATH,
    )


def get_session_token_from_request(request: Request) -> Optional[str]:
    """
    Extract session token from request cookie.

    Args:
        request: FastAPI request object

    Returns:
        Session token or None if not present
    """
    return request.cookies.get(SESSION_COOKIE_NAME)


# =============================================================================
# DATABASE OPERATIONS (sync wrapper for async-friendly patterns)
# =============================================================================

class RBACRepository:
    """
    Repository for RBAC database operations.

    Uses connection from request.state.conn set by middleware.
    """

    def __init__(self, conn):
        self.conn = conn

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email (case-insensitive)."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM auth.get_user_by_email(%s)",
                (email.lower(),)
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "email": row[1],
                    "display_name": row[2],
                    "password_hash": row[3],
                    "is_active": row[4],
                    "is_locked": row[5],
                    "failed_login_count": row[6],
                }
            return None

    def get_user_bindings(self, user_id: str) -> List[dict]:
        """Get all active bindings for a user."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM auth.get_user_bindings(%s)",
                (user_id,)
            )
            rows = cur.fetchall()
            return [
                {
                    "binding_id": row[0],
                    "tenant_id": row[1],
                    "site_id": row[2],
                    "role_id": row[3],
                    "role_name": row[4],
                }
                for row in rows
            ]

    def get_role_permissions(self, role_id: int) -> Set[str]:
        """Get all permissions for a role."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM auth.get_role_permissions(%s)",
                (role_id,)
            )
            return {row[0] for row in cur.fetchall()}

    def create_session(
        self,
        user_id: str,
        tenant_id: Optional[int],
        site_id: Optional[int],
        role_id: int,
        session_hash: str,
        expires_at: datetime,
        ip_hash: Optional[str] = None,
        user_agent_hash: Optional[str] = None,
        is_platform_scope: bool = False,
    ) -> str:
        """Create a new session."""
        with self.conn.cursor() as cur:
            # Use different function for platform admin sessions
            if is_platform_scope:
                cur.execute(
                    """
                    SELECT auth.create_platform_session(
                        %s::uuid, %s, %s, %s, %s, %s
                    )
                    """,
                    (user_id, role_id, session_hash, expires_at, ip_hash, user_agent_hash)
                )
            else:
                cur.execute(
                    """
                    SELECT auth.create_session(
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (user_id, tenant_id, site_id, role_id,
                     session_hash, expires_at, ip_hash, user_agent_hash)
                )
            return str(cur.fetchone()[0])

    def validate_session(self, session_hash: str) -> Optional[dict]:
        """Validate a session and return user context if valid."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM auth.validate_session(%s)",
                (session_hash,)
            )
            row = cur.fetchone()
            if row:
                return {
                    "session_id": str(row[0]),
                    "user_id": str(row[1]),
                    "user_email": row[2],
                    "user_display_name": row[3],
                    "tenant_id": row[4],  # Can be NULL for platform admin
                    "site_id": row[5],
                    "role_id": row[6],
                    "role_name": row[7],
                    "expires_at": row[8],
                    "is_platform_scope": row[9] if len(row) > 9 else False,
                    "active_tenant_id": row[10] if len(row) > 10 else None,
                    "active_site_id": row[11] if len(row) > 11 else None,
                }
            return None

    def set_platform_context(
        self,
        session_hash: str,
        tenant_id: int,
        site_id: Optional[int] = None
    ) -> dict:
        """
        Set active tenant/site context for a platform admin session.

        Returns dict with 'success' boolean and optional 'error' or context info.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT auth.set_platform_context(%s, %s, %s)",
                (session_hash, tenant_id, site_id)
            )
            result = cur.fetchone()[0]
            return result

    def clear_platform_context(self, session_hash: str) -> dict:
        """
        Clear active tenant/site context for a platform admin session.

        Returns dict with 'success' boolean and optional 'error'.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT auth.clear_platform_context(%s)",
                (session_hash,)
            )
            result = cur.fetchone()[0]
            return result

    def revoke_session(self, session_hash: str, reason: str = "logout") -> bool:
        """Revoke a session."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT auth.revoke_session(%s, %s)",
                (session_hash, reason)
            )
            return cur.fetchone()[0]

    def record_login_attempt(
        self,
        success: bool,
        user_id: Optional[str],
        email: str,
        tenant_id: Optional[int] = None,
        session_id: Optional[str] = None,
        error_code: Optional[str] = None,
        ip_hash: Optional[str] = None,
        user_agent_hash: Optional[str] = None,
    ) -> None:
        """Record a login attempt in audit log."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT auth.record_login_attempt(
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (success, user_id, email, tenant_id, session_id,
                 error_code, ip_hash, user_agent_hash)
            )


# =============================================================================
# FASTAPI DEPENDENCIES
# =============================================================================

def get_rbac_repository(request: Request) -> RBACRepository:
    """
    Get RBAC repository with a sync database connection.

    Creates a sync psycopg connection for auth operations.
    The connection is stored on request.state for reuse within the request.
    """
    # Check if we already have a connection for this request
    conn = getattr(request.state, "rbac_conn", None)
    if conn:
        return RBACRepository(conn)

    # Get database URL from app settings
    try:
        from ..config import settings
        database_url = settings.database_url
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database configuration not available"
        )

    # Create sync connection for auth operations
    # CRITICAL: Use autocommit=True so session inserts are immediately persisted
    try:
        conn = psycopg.connect(database_url, row_factory=tuple_row, autocommit=True)
        request.state.rbac_conn = conn
        return RBACRepository(conn)
    except Exception as e:
        logger.error(f"Failed to create RBAC database connection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection failed"
        )


async def get_current_session(
    request: Request,
    admin_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Optional[InternalUserContext]:
    """
    Get current user from session cookie (optional).

    Returns None if no valid session, does NOT raise exception.
    Use require_session() for protected endpoints.
    """
    if not admin_session:
        return None

    repo = get_rbac_repository(request)
    session_hash = hash_session_token(admin_session)
    session_data = repo.validate_session(session_hash)

    if not session_data:
        return None

    # Get permissions for role
    permissions = repo.get_role_permissions(session_data["role_id"])

    # Build context (includes active context for platform admins)
    return InternalUserContext(
        user_id=session_data["user_id"],
        email=session_data["user_email"],
        display_name=session_data["user_display_name"],
        tenant_id=session_data["tenant_id"],  # Can be None for platform admin
        site_id=session_data["site_id"],
        role_id=session_data["role_id"],
        role_name=session_data["role_name"],
        permissions=permissions,
        session_id=session_data["session_id"],
        expires_at=session_data["expires_at"],
        is_platform_scope=session_data.get("is_platform_scope", False),
        active_tenant_id=session_data.get("active_tenant_id"),
        active_site_id=session_data.get("active_site_id"),
    )


async def require_session(
    request: Request,
    user: Optional[InternalUserContext] = Depends(get_current_session),
) -> InternalUserContext:
    """
    Require a valid session. Raises 401 if not authenticated.

    Usage:
        @router.get("/protected")
        async def protected(user: InternalUserContext = Depends(require_session)):
            ...
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Cookie"},
        )

    # Ensure conn is available for downstream handlers (platform_admin, etc.)
    # get_rbac_repository sets rbac_conn, but other handlers expect conn
    if not hasattr(request.state, "conn") and hasattr(request.state, "rbac_conn"):
        request.state.conn = request.state.rbac_conn

    # Set RLS context for this request
    conn = getattr(request.state, "conn", None)
    if conn:
        with conn.cursor() as cur:
            # Set current user ID for audit
            cur.execute(
                "SELECT set_config('app.current_user_id', %s, TRUE)",
                (str(user.user_id),)
            )
            # Set platform admin flag for SQL functions
            cur.execute(
                "SELECT set_config('app.is_platform_admin', %s, TRUE)",
                ('true' if user.is_platform_admin else 'false',)
            )
            # Set tenant context (NULL for platform admin binding)
            if user.tenant_id is not None:
                cur.execute(
                    "SELECT set_config('app.current_tenant_id', %s, TRUE)",
                    (str(user.tenant_id),)
                )
            if user.site_id:
                cur.execute(
                    "SELECT set_config('app.current_site_id', %s, TRUE)",
                    (str(user.site_id),)
                )

            # Set active context for platform admin (allows them to work in tenant UIs)
            if user.active_tenant_id is not None:
                cur.execute(
                    "SELECT set_config('app.active_tenant_id', %s, TRUE)",
                    (str(user.active_tenant_id),)
                )
            if user.active_site_id is not None:
                cur.execute(
                    "SELECT set_config('app.active_site_id', %s, TRUE)",
                    (str(user.active_site_id),)
                )

    return user


def require_permission(permission: str):
    """
    Factory for permission check dependency.

    Platform admins bypass all permission checks (superuser access).

    Usage:
        @router.post("/resend")
        async def resend(user: InternalUserContext = Depends(require_permission("portal.resend.write"))):
            ...
    """
    async def _check_permission(
        user: InternalUserContext = Depends(require_session),
    ) -> InternalUserContext:
        # Platform admins bypass all permission checks
        if user.is_platform_admin:
            logger.debug(
                "platform_admin_bypass",
                extra={
                    "user_id": user.user_id,
                    "permission": permission,
                }
            )
            return user

        if not user.has_permission(permission):
            logger.warning(
                "permission_denied",
                extra={
                    "user_id": user.user_id,
                    "permission": permission,
                    "has_permissions": list(user.permissions),
                }
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}",
            )
        return user

    return _check_permission


def require_platform_admin():
    """
    Require platform admin access.

    Usage:
        @router.get("/tenants")
        async def list_tenants(user: InternalUserContext = Depends(require_platform_admin())):
            ...
    """
    async def _check_platform_admin(
        user: InternalUserContext = Depends(require_session),
    ) -> InternalUserContext:
        if not user.is_platform_admin:
            logger.warning(
                "platform_admin_required",
                extra={
                    "user_id": user.user_id,
                    "role_name": user.role_name,
                    "tenant_id": user.tenant_id,
                }
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform admin access required",
            )
        return user

    return _check_platform_admin


def set_rls_context_for_tenant(
    request: Request,
    tenant_id: int,
    site_id: Optional[int] = None,
    user: Optional[InternalUserContext] = None
) -> None:
    """
    Set RLS context for a specific tenant.

    Used by platform admins to access a specific tenant's data.

    Args:
        request: FastAPI request object
        tenant_id: Target tenant ID to set in RLS context
        site_id: Optional site ID to set in RLS context
        user: Optional user context (to preserve platform admin flag)
    """
    conn = getattr(request.state, "conn", None)
    if conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, TRUE)",
                (str(tenant_id),)
            )
            if site_id:
                cur.execute(
                    "SELECT set_config('app.current_site_id', %s, TRUE)",
                    (str(site_id),)
                )
            # Preserve platform admin flag if user context provided
            if user and user.is_platform_admin:
                cur.execute(
                    "SELECT set_config('app.is_platform_admin', 'true', TRUE)"
                )


def require_any_permission(*permissions: str):
    """
    Factory for permission check dependency (any of the listed permissions).

    Platform admins bypass all permission checks (superuser access).

    Usage:
        @router.get("/data")
        async def data(user: InternalUserContext = Depends(require_any_permission("portal.summary.read", "portal.details.read"))):
            ...
    """
    async def _check_permissions(
        user: InternalUserContext = Depends(require_session),
    ) -> InternalUserContext:
        # Platform admins bypass all permission checks
        if user.is_platform_admin:
            logger.debug(
                "platform_admin_bypass",
                extra={
                    "user_id": user.user_id,
                    "permissions": list(permissions),
                }
            )
            return user

        if not user.has_any_permission(list(permissions)):
            logger.warning(
                "permission_denied",
                extra={
                    "user_id": user.user_id,
                    "required_permissions": list(permissions),
                    "has_permissions": list(user.permissions),
                }
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these permissions required: {', '.join(permissions)}",
            )
        return user

    return _check_permissions


# =============================================================================
# TENANT CONTEXT REQUIREMENT (V4.6)
# =============================================================================

@dataclass
class TenantContext:
    """
    Result of require_tenant_context() dependency.

    Contains the user context plus the effective tenant/site IDs.
    """
    user: InternalUserContext
    tenant_id: int
    site_id: Optional[int]


async def require_tenant_context(
    user: InternalUserContext = Depends(require_session),
) -> TenantContext:
    """
    Require a valid tenant context for pack/portal endpoints.

    For regular users: Uses their bound tenant_id (always set).
    For platform admins: Requires active_tenant_id to be set via context switching.

    Returns TenantContext with effective tenant_id and site_id.

    Raises:
        403 CONTEXT_REQUIRED if platform admin hasn't set active context.

    Usage:
        @router.get("/pack-data")
        async def pack_data(ctx: TenantContext = Depends(require_tenant_context)):
            tenant_id = ctx.tenant_id
            user = ctx.user
            ...
    """
    effective_tenant = user.get_effective_tenant_id()

    if effective_tenant is None:
        # This only happens for platform_admin without active context
        logger.warning(
            "context_required",
            extra={
                "user_id": user.user_id,
                "is_platform_admin": user.is_platform_admin,
                "active_tenant_id": user.active_tenant_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "CONTEXT_REQUIRED",
                "message": "Platform admin must set active tenant context to access this resource"
            },
        )

    return TenantContext(
        user=user,
        tenant_id=effective_tenant,
        site_id=user.get_effective_site_id(),
    )


def require_tenant_context_with_permission(permission: str):
    """
    Factory for combined permission + tenant context check.

    Usage:
        @router.get("/pack-data")
        async def pack_data(ctx: TenantContext = Depends(require_tenant_context_with_permission("portal.summary.read"))):
            ...
    """
    async def _check(
        user: InternalUserContext = Depends(require_permission(permission)),
    ) -> TenantContext:
        return await require_tenant_context(user)

    return _check


# =============================================================================
# LOGIN / LOGOUT SERVICE
# =============================================================================

class AuthService:
    """
    Authentication service for login/logout operations.
    """

    def __init__(self, repo: RBACRepository):
        self.repo = repo

    def login(
        self,
        email: str,
        password: str,
        tenant_id: Optional[int] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[InternalUserContext], Optional[str]]:
        """
        Authenticate user and create session.

        Args:
            email: User email
            password: Plain text password
            tenant_id: Optional tenant ID to login to (if user has multiple bindings)
            ip: Client IP (will be hashed)
            user_agent: Client user agent (will be hashed)

        Returns:
            Tuple of (session_token, user_context, error_code)
            On success: (token, context, None)
            On failure: (None, None, error_code)
        """
        ip_hash = hash_ip(ip)
        ua_hash = hash_user_agent(user_agent)

        # Get user
        user = self.repo.get_user_by_email(email)
        if not user:
            self.repo.record_login_attempt(
                success=False,
                user_id=None,
                email=email,
                error_code="USER_NOT_FOUND",
                ip_hash=ip_hash,
                user_agent_hash=ua_hash,
            )
            return None, None, "INVALID_CREDENTIALS"

        # Check if locked
        if user["is_locked"]:
            self.repo.record_login_attempt(
                success=False,
                user_id=user["id"],
                email=email,
                error_code="ACCOUNT_LOCKED",
                ip_hash=ip_hash,
                user_agent_hash=ua_hash,
            )
            return None, None, "ACCOUNT_LOCKED"

        # Check if active
        if not user["is_active"]:
            self.repo.record_login_attempt(
                success=False,
                user_id=user["id"],
                email=email,
                error_code="ACCOUNT_INACTIVE",
                ip_hash=ip_hash,
                user_agent_hash=ua_hash,
            )
            return None, None, "ACCOUNT_INACTIVE"

        # Verify password
        if not verify_password(password, user["password_hash"]):
            self.repo.record_login_attempt(
                success=False,
                user_id=user["id"],
                email=email,
                error_code="INVALID_PASSWORD",
                ip_hash=ip_hash,
                user_agent_hash=ua_hash,
            )
            return None, None, "INVALID_CREDENTIALS"

        # Get bindings
        bindings = self.repo.get_user_bindings(user["id"])
        if not bindings:
            self.repo.record_login_attempt(
                success=False,
                user_id=user["id"],
                email=email,
                error_code="NO_BINDINGS",
                ip_hash=ip_hash,
                user_agent_hash=ua_hash,
            )
            return None, None, "NO_TENANT_ACCESS"

        # Select binding
        # Platform admins have tenant_id=NULL in their binding
        if tenant_id:
            binding = next((b for b in bindings if b["tenant_id"] == tenant_id), None)
            if not binding:
                self.repo.record_login_attempt(
                    success=False,
                    user_id=user["id"],
                    email=email,
                    error_code="TENANT_NOT_ALLOWED",
                    ip_hash=ip_hash,
                    user_agent_hash=ua_hash,
                )
                return None, None, "TENANT_NOT_ALLOWED"
        else:
            # Default to first binding (may be platform admin with NULL tenant)
            binding = bindings[0]

        # Determine if this is a platform admin session
        is_platform_scope = binding["role_name"] == "platform_admin"

        # Get permissions
        permissions = self.repo.get_role_permissions(binding["role_id"])

        # Generate session token
        session_token = generate_session_token()
        session_hash = hash_session_token(session_token)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_COOKIE_MAX_AGE)

        # Create session (with is_platform_scope flag)
        session_id = self.repo.create_session(
            user_id=user["id"],
            tenant_id=binding["tenant_id"],  # NULL for platform admin
            site_id=binding["site_id"],
            role_id=binding["role_id"],
            session_hash=session_hash,
            expires_at=expires_at,
            ip_hash=ip_hash,
            user_agent_hash=ua_hash,
            is_platform_scope=is_platform_scope,
        )

        # Record success
        self.repo.record_login_attempt(
            success=True,
            user_id=user["id"],
            email=email,
            tenant_id=binding["tenant_id"],
            session_id=session_id,
            ip_hash=ip_hash,
            user_agent_hash=ua_hash,
        )

        # Build context
        context = InternalUserContext(
            user_id=user["id"],
            email=user["email"],
            display_name=user["display_name"],
            tenant_id=binding["tenant_id"],  # NULL for platform admin
            site_id=binding["site_id"],
            role_id=binding["role_id"],
            role_name=binding["role_name"],
            permissions=permissions,
            session_id=session_id,
            expires_at=expires_at,
            is_platform_scope=is_platform_scope,
        )

        return session_token, context, None

    def logout(self, session_token: str) -> bool:
        """
        Logout by revoking session.

        Args:
            session_token: Plain session token

        Returns:
            True if session was revoked, False if not found
        """
        session_hash = hash_session_token(session_token)
        return self.repo.revoke_session(session_hash, reason="logout")


# =============================================================================
# CSRF PROTECTION
# =============================================================================

def verify_csrf_origin(request: Request) -> None:
    """
    Verify Origin/Referer header for CSRF protection on mutating requests.

    Should be called on POST/PUT/DELETE/PATCH endpoints.
    Raises HTTPException if Origin doesn't match.
    """
    # Skip for non-browser clients (no Origin header = API client)
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    if not origin and not referer:
        # Could be non-browser client - allow if SameSite=Strict is set
        # SameSite=Strict already prevents CSRF from cross-site requests
        return

    # Get expected origin from request
    expected_host = request.headers.get("host", "")

    # Check Origin header (preferred)
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        origin_host = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
        if origin_host and origin_host != expected_host.split(":")[0]:
            # Also check without port for localhost
            if not (origin_host.split(":")[0] == expected_host.split(":")[0]):
                logger.warning(
                    "csrf_origin_mismatch",
                    extra={"origin": origin, "expected": expected_host}
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid request origin",
                )
        return

    # Fall back to Referer header
    if referer:
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        referer_host = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
        if referer_host and referer_host != expected_host.split(":")[0]:
            if not (referer_host.split(":")[0] == expected_host.split(":")[0]):
                logger.warning(
                    "csrf_referer_mismatch",
                    extra={"referer": referer, "expected": expected_host}
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid request referer",
                )


async def require_csrf_check(request: Request) -> None:
    """
    Dependency to require CSRF check on mutating endpoints.

    Usage:
        @router.post("/action", dependencies=[Depends(require_csrf_check)])
        async def action():
            ...
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        verify_csrf_origin(request)


# =============================================================================
# LOGIN RATE LIMITING
# =============================================================================

# In-memory rate limit store (replace with Redis in production)
_login_rate_limit_store: dict[str, list[float]] = {}


def check_login_rate_limit(ip: Optional[str]) -> bool:
    """
    Check if IP is rate limited for login attempts.

    Returns True if allowed, False if rate limited.
    """
    import time

    if not ip:
        return True  # Can't rate limit without IP

    ip_hash = hash_ip(ip)
    current_time = time.time()
    window_start = current_time - LOGIN_RATE_LIMIT_WINDOW

    # Clean old entries
    if ip_hash in _login_rate_limit_store:
        _login_rate_limit_store[ip_hash] = [
            t for t in _login_rate_limit_store[ip_hash]
            if t > window_start
        ]
    else:
        _login_rate_limit_store[ip_hash] = []

    # Check limit
    if len(_login_rate_limit_store[ip_hash]) >= LOGIN_RATE_LIMIT_MAX:
        return False

    return True


def record_login_attempt_rate_limit(ip: Optional[str]) -> None:
    """Record a login attempt for rate limiting."""
    import time

    if not ip:
        return

    ip_hash = hash_ip(ip)
    if ip_hash not in _login_rate_limit_store:
        _login_rate_limit_store[ip_hash] = []

    _login_rate_limit_store[ip_hash].append(time.time())


# =============================================================================
# MOCK REPOSITORY FOR TESTING
# =============================================================================

class MockRBACRepository:
    """
    Mock repository for testing without database.

    NOTE: Uses generic test emails only. No production/demo credentials.
    """

    # Test password - only used in unit tests, never in production
    TEST_PASSWORD = "TestPassword123!"

    def __init__(self):
        # Pre-seed with generic test users (NOT production credentials)
        self._mock_users = {
            "test-dispatcher@example.com": {
                "id": "user-dispatcher",
                "email": "test-dispatcher@example.com",
                "display_name": "Test Dispatcher",
                "password_hash": hash_password(self.TEST_PASSWORD),
                "is_active": True,
                "is_locked": False,
                "failed_login_count": 0,
            },
            "test-admin@example.com": {
                "id": "user-admin",
                "email": "test-admin@example.com",
                "display_name": "Test Admin",
                "password_hash": hash_password(self.TEST_PASSWORD),
                "is_active": True,
                "is_locked": False,
                "failed_login_count": 0,
            },
        }

        self._mock_bindings = {
            "user-dispatcher": [
                {
                    "binding_id": 1,
                    "tenant_id": 1,
                    "site_id": 10,
                    "role_id": 3,
                    "role_name": "dispatcher",
                }
            ],
            "user-admin": [
                {
                    "binding_id": 2,
                    "tenant_id": 1,
                    "site_id": None,
                    "role_id": 2,
                    "role_name": "operator_admin",
                }
            ],
        }

        self._mock_permissions = {
            "dispatcher": {
                "portal.summary.read",
                "portal.details.read",
                "portal.resend.write",
                "portal.export.read",
            },
            "operator_admin": {
                "portal.summary.read",
                "portal.details.read",
                "portal.resend.write",
                "portal.approve.write",
                "portal.export.read",
                "users.read",
                "users.write",
            },
            "ops_readonly": {
                "portal.summary.read",
                "portal.details.read",
                "portal.export.read",
            },
        }

        self._mock_sessions: dict[str, dict] = {}

    def get_user_by_email(self, email: str) -> Optional[dict]:
        return self._mock_users.get(email.lower())

    def get_user_bindings(self, user_id: str) -> List[dict]:
        return self._mock_bindings.get(user_id, [])

    def get_role_permissions(self, role_name_or_id) -> Set[str]:
        # Handle both role name and role ID
        if isinstance(role_name_or_id, str):
            return self._mock_permissions.get(role_name_or_id, set())
        # Map role IDs to names
        role_map = {1: "platform_admin", 2: "operator_admin", 3: "dispatcher", 4: "ops_readonly"}
        role_name = role_map.get(role_name_or_id, "")
        return self._mock_permissions.get(role_name, set())

    def create_session(
        self,
        token_hash: str = None,
        user_id: str = None,
        tenant_id: Optional[int] = None,
        site_id: Optional[int] = None,
        role_id: int = None,
        session_hash: str = None,
        expires_at: datetime = None,
        ip_hash: Optional[str] = None,
        user_agent_hash: Optional[str] = None,
        is_platform_scope: bool = False,
    ) -> str:
        # Support both old and new parameter names
        hash_key = token_hash or session_hash
        session_id = f"session-{len(self._mock_sessions) + 1}"
        session = {
            "session_id": session_id,
            "token_hash": hash_key,
            "user_id": user_id,
            "tenant_id": tenant_id,  # Can be NULL for platform admin
            "site_id": site_id,
            "role_id": role_id,
            "expires_at": expires_at or datetime.now(timezone.utc) + timedelta(hours=8),
            "created_at": datetime.now(timezone.utc),
            "revoked_at": None,
            "is_platform_scope": is_platform_scope,
        }
        self._mock_sessions[hash_key] = session
        return session_id

    def validate_session(self, token_hash: str) -> Optional[dict]:
        session = self._mock_sessions.get(token_hash)
        if not session:
            return None
        if session.get("revoked_at"):
            return None
        if session["expires_at"] < datetime.now(timezone.utc):
            return None

        # Get user info
        user = None
        for u in self._mock_users.values():
            if u["id"] == session["user_id"]:
                user = u
                break

        if not user:
            return None

        # Get role name
        bindings = self.get_user_bindings(session["user_id"])
        role_name = ""
        for b in bindings:
            if b["role_id"] == session.get("role_id"):
                role_name = b["role_name"]
                break

        return {
            "session_id": session["session_id"],
            "user_id": session["user_id"],
            "user_email": user["email"],
            "user_display_name": user["display_name"],
            "tenant_id": session["tenant_id"],  # Can be NULL for platform admin
            "site_id": session["site_id"],
            "role_id": session.get("role_id", 3),
            "role_name": role_name or "dispatcher",
            "expires_at": session["expires_at"],
            "is_platform_scope": session.get("is_platform_scope", False),
        }

    def revoke_session(self, token_hash: str, reason: str = "logout") -> bool:
        if token_hash in self._mock_sessions:
            self._mock_sessions[token_hash]["revoked_at"] = datetime.now(timezone.utc)
            return True
        return False

    def record_login_attempt(self, **kwargs) -> None:
        # No-op for mock
        pass
