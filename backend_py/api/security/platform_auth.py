"""
SOLVEREIGN V3.7 - Platform Admin Session Auth
==============================================

Platform-only authentication for /api/v1/platform/* endpoints.
Uses session cookies + CSRF protection + RBAC.

SECURITY MODEL:
- Platform endpoints ONLY accept session-based auth
- Tenant API keys / HMAC are REJECTED on platform endpoints
- dev-login is HARD BLOCKED in production

HEADERS:
- Cookie: session=<encrypted_session>
- X-CSRF-Token: <csrf_token> (required for POST/PUT/PATCH/DELETE)

RBAC ROLES:
- platform_admin: Full platform access
- platform_viewer: Read-only platform access
- org_admin: Organization-scoped admin
- tenant_admin: Tenant-scoped admin (NOT for platform endpoints)

Usage:
    from .security.platform_auth import require_platform_session

    @router.get("/platform/tenants")
    async def list_tenants(
        user: PlatformUser = Depends(require_platform_session(roles=["platform_admin"]))
    ):
        ...
"""

import hashlib
import hmac
import time
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any

from fastapi import Request, Response, HTTPException, status, Depends
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from ..logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

SESSION_COOKIE_NAME = "sv_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_TTL_HOURS = 8
CSRF_TTL_MINUTES = 30


class PlatformRole(str, Enum):
    """Platform RBAC roles."""
    PLATFORM_ADMIN = "platform_admin"      # Full platform access
    PLATFORM_VIEWER = "platform_viewer"    # Read-only platform
    ORG_ADMIN = "org_admin"                # Organization admin
    TENANT_ADMIN = "tenant_admin"          # Tenant admin (not for platform)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class PlatformUser:
    """
    Authenticated platform user context.

    Only populated after successful session validation.
    """
    user_id: str
    email: str
    display_name: str
    roles: List[str]
    org_id: Optional[str] = None        # For org-scoped users
    tenant_ids: List[str] = field(default_factory=list)  # For tenant-scoped
    session_id: str = ""
    authenticated_at: datetime = field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    def has_role(self, role: str) -> bool:
        """Check if user has specific role."""
        return role in self.roles

    def has_any_role(self, roles: List[str]) -> bool:
        """Check if user has any of the specified roles."""
        return any(r in self.roles for r in roles)

    def is_platform_admin(self) -> bool:
        """Check if user is platform admin."""
        return PlatformRole.PLATFORM_ADMIN.value in self.roles


@dataclass
class SessionData:
    """Session storage data."""
    user_id: str
    email: str
    display_name: str
    roles: List[str]
    org_id: Optional[str]
    tenant_ids: List[str]
    created_at: datetime
    expires_at: datetime
    ip_address: str
    user_agent: str
    csrf_token: str


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================

def generate_session_id() -> str:
    """Generate cryptographically secure session ID."""
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    """Generate CSRF token."""
    return secrets.token_urlsafe(32)


def encrypt_session(session_id: str) -> str:
    """
    Encrypt session ID for cookie storage.

    Uses HMAC to sign the session ID, preventing tampering.
    """
    signature = hmac.new(
        settings.secret_key.encode(),
        session_id.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{session_id}.{signature}"


def decrypt_session(cookie_value: str) -> Optional[str]:
    """
    Decrypt and verify session cookie.

    Returns session ID if valid, None if tampered.
    """
    try:
        if "." not in cookie_value:
            return None

        session_id, signature = cookie_value.rsplit(".", 1)

        expected_signature = hmac.new(
            settings.secret_key.encode(),
            session_id.encode(),
            hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(signature, expected_signature):
            return session_id
        return None
    except Exception:
        return None


class SessionStore:
    """
    In-memory session store (for development).

    In production, use Redis or database-backed sessions.
    """

    def __init__(self):
        self._sessions: Dict[str, SessionData] = {}

    async def create(self, user: "PlatformUser", ip_address: str, user_agent: str) -> str:
        """Create new session, return session ID."""
        session_id = generate_session_id()
        csrf_token = generate_csrf_token()

        self._sessions[session_id] = SessionData(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            roles=user.roles,
            org_id=user.org_id,
            tenant_ids=user.tenant_ids,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS),
            ip_address=ip_address,
            user_agent=user_agent,
            csrf_token=csrf_token
        )

        return session_id

    async def get(self, session_id: str) -> Optional[SessionData]:
        """Get session data if valid and not expired."""
        session = self._sessions.get(session_id)
        if not session:
            return None

        if session.expires_at < datetime.utcnow():
            await self.delete(session_id)
            return None

        return session

    async def delete(self, session_id: str) -> None:
        """Delete session."""
        self._sessions.pop(session_id, None)

    async def cleanup_expired(self) -> int:
        """Cleanup expired sessions, return count deleted."""
        now = datetime.utcnow()
        expired = [
            sid for sid, data in self._sessions.items()
            if data.expires_at < now
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)


# Global session store (replace with Redis in production)
session_store = SessionStore()


# =============================================================================
# PRODUCTION GUARDS
# =============================================================================

def is_dev_login_blocked() -> bool:
    """
    Check if dev-login should be blocked.

    HARD BLOCK in production to prevent security bypass.
    """
    return settings.is_production


def reject_tenant_auth_headers(request: Request) -> None:
    """
    Reject requests with tenant auth headers on platform endpoints.

    Platform endpoints MUST NOT accept:
    - X-API-Key
    - X-Tenant-Code
    - HMAC signatures
    """
    rejected_headers = [
        "X-API-Key",
        "X-Tenant-Code",
        "X-SV-Signature",  # HMAC signature
    ]

    found_headers = [h for h in rejected_headers if request.headers.get(h)]

    if found_headers:
        logger.warning(
            "platform_auth_rejected_tenant_headers",
            extra={
                "path": request.url.path,
                "rejected_headers": found_headers,
                "source_ip": _get_client_ip(request)
            }
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_auth_method",
                "message": "Platform endpoints require session auth, not API keys or HMAC",
                "rejected_headers": found_headers
            }
        )


def validate_csrf_token(request: Request, session: SessionData) -> None:
    """
    Validate CSRF token for state-changing requests.

    Required for: POST, PUT, PATCH, DELETE
    """
    if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
        csrf_token = request.headers.get(CSRF_HEADER_NAME)

        if not csrf_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "csrf_missing",
                    "message": f"CSRF token required in {CSRF_HEADER_NAME} header"
                }
            )

        if not hmac.compare_digest(csrf_token, session.csrf_token):
            logger.warning(
                "platform_auth_csrf_invalid",
                extra={
                    "path": request.url.path,
                    "user_id": session.user_id,
                    "source_ip": _get_client_ip(request)
                }
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "csrf_invalid",
                    "message": "Invalid CSRF token"
                }
            )


# =============================================================================
# DEPENDENCY FACTORIES
# =============================================================================

def require_platform_session(
    roles: Optional[List[str]] = None,
    require_csrf: bool = True
):
    """
    FastAPI dependency that requires valid platform session.

    Args:
        roles: Required roles (any match = allowed). None = any authenticated user.
        require_csrf: Whether to require CSRF token (default True)

    Usage:
        @router.get("/platform/tenants")
        async def list_tenants(
            user: PlatformUser = Depends(require_platform_session(roles=["platform_admin"]))
        ):
            ...
    """
    async def dependency(request: Request) -> PlatformUser:
        # SECURITY: Reject tenant auth headers
        reject_tenant_auth_headers(request)

        # Get session cookie
        session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if not session_cookie:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "session_missing",
                    "message": "Session cookie required for platform endpoints"
                }
            )

        # Decrypt and verify session
        session_id = decrypt_session(session_cookie)
        if not session_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "session_invalid",
                    "message": "Invalid or tampered session cookie"
                }
            )

        # Get session data
        session = await session_store.get(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "session_expired",
                    "message": "Session expired or not found"
                }
            )

        # Validate CSRF token for state-changing requests
        if require_csrf:
            validate_csrf_token(request, session)

        # Check roles if specified
        if roles:
            if not any(r in session.roles for r in roles):
                logger.warning(
                    "platform_auth_role_denied",
                    extra={
                        "path": request.url.path,
                        "user_id": session.user_id,
                        "user_roles": session.roles,
                        "required_roles": roles
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "insufficient_role",
                        "message": f"Requires one of: {roles}",
                        "user_roles": session.roles
                    }
                )

        return PlatformUser(
            user_id=session.user_id,
            email=session.email,
            display_name=session.display_name,
            roles=session.roles,
            org_id=session.org_id,
            tenant_ids=session.tenant_ids,
            session_id=session_id,
            authenticated_at=session.created_at,
            ip_address=session.ip_address,
            user_agent=session.user_agent
        )

    return dependency


async def get_optional_platform_session(request: Request) -> Optional[PlatformUser]:
    """
    Get platform session if present, without requiring it.

    Useful for endpoints that work with or without auth.
    """
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        return None

    session_id = decrypt_session(session_cookie)
    if not session_id:
        return None

    session = await session_store.get(session_id)
    if not session:
        return None

    return PlatformUser(
        user_id=session.user_id,
        email=session.email,
        display_name=session.display_name,
        roles=session.roles,
        org_id=session.org_id,
        tenant_ids=session.tenant_ids,
        session_id=session_id,
        authenticated_at=session.created_at
    )


# =============================================================================
# SESSION MANAGEMENT FUNCTIONS
# =============================================================================

async def create_session(
    response: Response,
    user: PlatformUser,
    ip_address: str,
    user_agent: str
) -> str:
    """
    Create session and set cookie.

    Returns the CSRF token (client should store this for API calls).
    """
    session_id = await session_store.create(user, ip_address, user_agent)
    session = await session_store.get(session_id)

    # Set encrypted session cookie
    encrypted = encrypt_session(session_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=encrypted,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=SESSION_TTL_HOURS * 3600
    )

    logger.info(
        "platform_session_created",
        extra={
            "user_id": user.user_id,
            "email": user.email,
            "roles": user.roles,
            "ip_address": ip_address
        }
    )

    return session.csrf_token


async def destroy_session(request: Request, response: Response) -> None:
    """
    Destroy current session and clear cookie.
    """
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if session_cookie:
        session_id = decrypt_session(session_cookie)
        if session_id:
            await session_store.delete(session_id)

    response.delete_cookie(SESSION_COOKIE_NAME)
    logger.info("platform_session_destroyed")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_client_ip(request: Request) -> str:
    """Get client IP from request, handling proxies."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    if request.client:
        return request.client.host

    return "unknown"


# =============================================================================
# DEV LOGIN (BLOCKED IN PRODUCTION)
# =============================================================================

async def dev_login(
    request: Request,
    response: Response,
    user_id: str = "dev-admin",
    email: str = "admin@localhost",
    display_name: str = "Dev Admin",
    roles: List[str] = None
) -> dict:
    """
    Development-only login endpoint.

    HARD BLOCKED in production - returns 403.

    Usage:
        POST /api/v1/platform/dev-login
        Body: {"user_id": "test", "roles": ["platform_admin"]}
    """
    if is_dev_login_blocked():
        logger.error(
            "platform_auth_dev_login_blocked",
            extra={
                "source_ip": _get_client_ip(request),
                "attempted_user_id": user_id
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "dev_login_blocked",
                "message": "dev-login is HARD BLOCKED in production",
                "hint": "Use proper authentication (OIDC/Entra ID)"
            }
        )

    if roles is None:
        roles = [PlatformRole.PLATFORM_ADMIN.value]

    user = PlatformUser(
        user_id=user_id,
        email=email,
        display_name=display_name,
        roles=roles
    )

    csrf_token = await create_session(
        response,
        user,
        _get_client_ip(request),
        request.headers.get("User-Agent", "unknown")
    )

    return {
        "status": "ok",
        "user_id": user_id,
        "roles": roles,
        "csrf_token": csrf_token,
        "message": "DEV LOGIN - Not available in production"
    }
