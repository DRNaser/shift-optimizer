"""
SOLVEREIGN V4.4 - Internal Authentication API
==============================================

Endpoints for internal RBAC authentication:
- POST /api/auth/login     - Login with email/password
- POST /api/auth/logout    - Logout (revoke session)
- GET  /api/auth/me        - Get current user info

NON-NEGOTIABLES:
- No secrets/passwords in responses or logs
- Tenant isolation via user bindings only
- Rate limiting on login endpoint
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, Response, HTTPException, status, Depends
from pydantic import BaseModel, Field, EmailStr

from ..security.internal_rbac import (
    InternalUserContext,
    AuthService,
    RBACRepository,
    get_rbac_repository,
    require_session,
    set_session_cookie,
    clear_session_cookie,
    get_session_token_from_request,
    check_login_rate_limit,
    record_login_attempt_rate_limit,
    SESSION_COOKIE_NAME,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class LoginRequest(BaseModel):
    """Login request body."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password")
    tenant_id: Optional[int] = Field(None, description="Optional tenant ID if user has multiple bindings")


class TenantBinding(BaseModel):
    """Tenant binding info for user."""
    tenant_id: int
    site_id: Optional[int]
    role_name: str


class LoginResponse(BaseModel):
    """Login success response."""
    success: bool = True
    user_id: str
    email: str
    display_name: Optional[str]
    tenant_id: Optional[int]  # V4.6: NULL for platform_admin
    site_id: Optional[int]
    role_name: str
    permissions: List[str]
    expires_at: datetime
    available_tenants: List[TenantBinding] = Field(
        default_factory=list,
        description="Other tenant bindings for tenant switching"
    )
    is_platform_admin: bool = False  # V4.6


class LoginErrorResponse(BaseModel):
    """Login error response."""
    success: bool = False
    error_code: str
    message: str


class EnabledPacks(BaseModel):
    """Packs enabled for the active tenant."""
    roster: bool = False
    routing: bool = False
    masterdata: bool = False
    portal: bool = False


class MeResponse(BaseModel):
    """Current user info response."""
    user_id: str
    email: str
    display_name: Optional[str]
    tenant_id: Optional[int]  # V4.6: NULL for platform_admin
    site_id: Optional[int]
    role_name: str
    permissions: List[str]
    session_id: Optional[str]
    expires_at: Optional[datetime]
    # V4.6: Platform admin context fields
    is_platform_admin: bool = False
    active_tenant_id: Optional[int] = None
    active_site_id: Optional[int] = None
    active_tenant_name: Optional[str] = None
    active_site_name: Optional[str] = None
    # V4.7: Enabled packs for active tenant (for dynamic nav)
    enabled_packs: EnabledPacks = Field(default_factory=EnabledPacks)


class LogoutResponse(BaseModel):
    """Logout response."""
    success: bool = True
    message: str = "Logged out successfully"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_client_ip(request: Request) -> Optional[str]:
    """Get client IP from request, handling proxies."""
    # Check X-Forwarded-For header (from proxy)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take first IP in chain (original client)
        return forwarded.split(",")[0].strip()
    # Fall back to direct connection
    if request.client:
        return request.client.host
    return None


def get_user_agent(request: Request) -> Optional[str]:
    """Get user agent from request."""
    return request.headers.get("user-agent")


ERROR_MESSAGES = {
    "INVALID_CREDENTIALS": "Invalid email or password",
    "ACCOUNT_LOCKED": "Account is locked. Please contact an administrator.",
    "ACCOUNT_INACTIVE": "Account is inactive. Please contact an administrator.",
    "NO_TENANT_ACCESS": "User has no tenant access configured",
    "TENANT_NOT_ALLOWED": "User does not have access to the specified tenant",
}


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"model": LoginErrorResponse, "description": "Invalid credentials"},
        403: {"model": LoginErrorResponse, "description": "Account locked or inactive"},
        429: {"description": "Too many login attempts"},
    },
)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
):
    """
    Authenticate with email and password.

    On success:
    - Sets HttpOnly session cookie (`admin_session`)
    - Returns user info and permissions

    On failure:
    - Returns error code and message
    - Does NOT set cookie

    Rate limited: 5 attempts per IP per 15 minutes.
    """
    client_ip = get_client_ip(request)

    # Check rate limit BEFORE processing
    if not check_login_rate_limit(client_ip):
        logger.warning(
            "login_rate_limited",
            extra={"ip_prefix": client_ip[:8] if client_ip else None}
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "success": False,
                "error_code": "RATE_LIMITED",
                "message": "Too many login attempts. Please try again later.",
            },
        )

    # Record this attempt for rate limiting
    record_login_attempt_rate_limit(client_ip)

    repo = get_rbac_repository(request)
    auth_service = AuthService(repo)

    session_token, user_context, error_code = auth_service.login(
        email=body.email,
        password=body.password,
        tenant_id=body.tenant_id,
        ip=client_ip,
        user_agent=get_user_agent(request),
    )

    if error_code:
        # Determine status code
        if error_code in ("ACCOUNT_LOCKED", "ACCOUNT_INACTIVE"):
            status_code = status.HTTP_403_FORBIDDEN
        else:
            status_code = status.HTTP_401_UNAUTHORIZED

        logger.warning(
            "login_failed",
            extra={
                "email": body.email,
                "error_code": error_code,
                # Don't log password or full email
            }
        )

        raise HTTPException(
            status_code=status_code,
            detail={
                "success": False,
                "error_code": error_code,
                "message": ERROR_MESSAGES.get(error_code, "Login failed"),
            },
        )

    # Success - set cookie
    set_session_cookie(response, session_token)

    # Get all bindings for tenant switching
    all_bindings = repo.get_user_bindings(user_context.user_id)
    available_tenants = [
        TenantBinding(
            tenant_id=b["tenant_id"],
            site_id=b["site_id"],
            role_name=b["role_name"],
        )
        for b in all_bindings
        if b["tenant_id"] != user_context.tenant_id
    ]

    logger.info(
        "login_success",
        extra={
            "user_id": user_context.user_id,
            "tenant_id": user_context.tenant_id,
            "role": user_context.role_name,
        }
    )

    return LoginResponse(
        user_id=user_context.user_id,
        email=user_context.email,
        display_name=user_context.display_name,
        tenant_id=user_context.tenant_id,
        site_id=user_context.site_id,
        role_name=user_context.role_name,
        permissions=list(user_context.permissions),
        expires_at=user_context.expires_at,
        available_tenants=available_tenants,
        is_platform_admin=user_context.is_platform_admin,  # V4.6
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
)
async def logout(
    request: Request,
    response: Response,
):
    """
    Logout current user.

    - Revokes server-side session
    - Clears session cookie
    - Always succeeds (even if no session)
    """
    session_token = get_session_token_from_request(request)

    if session_token:
        repo = get_rbac_repository(request)
        auth_service = AuthService(repo)
        auth_service.logout(session_token)

        logger.info(
            "logout",
            extra={
                # Don't log session token
            }
        )

    # Always clear cookie
    clear_session_cookie(response)

    return LogoutResponse()


@router.get(
    "/me",
    response_model=MeResponse,
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def get_current_user(
    request: Request,
    user: InternalUserContext = Depends(require_session),
):
    """
    Get current authenticated user info.

    Returns user identity, current tenant/site scope, role, and permissions.
    V4.6: Also returns active context for platform admins.
    V4.7: Also returns enabled_packs for dynamic nav.
    """
    active_tenant_name = None
    active_site_name = None
    enabled_packs = EnabledPacks()

    # Determine effective tenant for pack lookup
    effective_tenant_id = None
    if user.is_platform_admin:
        effective_tenant_id = user.active_tenant_id
    else:
        effective_tenant_id = user.tenant_id

    conn = getattr(request.state, "conn", None)
    if conn:
        with conn.cursor() as cur:
            # Fetch tenant/site names if active context is set
            if user.is_platform_admin and user.active_tenant_id:
                cur.execute("SELECT name FROM tenants WHERE id = %s", (user.active_tenant_id,))
                row = cur.fetchone()
                if row:
                    active_tenant_name = row[0]

                if user.active_site_id:
                    cur.execute("SELECT name FROM sites WHERE id = %s", (user.active_site_id,))
                    row = cur.fetchone()
                    if row:
                        active_site_name = row[0]

            # V4.7: Fetch enabled packs for effective tenant
            if effective_tenant_id:
                cur.execute("""
                    SELECT
                        COALESCE(pack_roster, true) as roster,
                        COALESCE(pack_routing, false) as routing,
                        COALESCE(pack_masterdata, true) as masterdata,
                        COALESCE(pack_portal, true) as portal
                    FROM tenants
                    WHERE id = %s
                """, (effective_tenant_id,))
                row = cur.fetchone()
                if row:
                    enabled_packs = EnabledPacks(
                        roster=row[0],
                        routing=row[1],
                        masterdata=row[2],
                        portal=row[3],
                    )

    return MeResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        site_id=user.site_id,
        role_name=user.role_name,
        permissions=list(user.permissions),
        session_id=user.session_id,
        expires_at=user.expires_at,
        # V4.6: Platform admin context
        is_platform_admin=user.is_platform_admin,
        active_tenant_id=user.active_tenant_id,
        active_site_id=user.active_site_id,
        active_tenant_name=active_tenant_name,
        active_site_name=active_site_name,
        # V4.7: Enabled packs
        enabled_packs=enabled_packs,
    )


@router.get("/health")
async def auth_health():
    """Health check for auth service."""
    return {
        "status": "ok",
        "service": "auth",
        "session_cookie_name": SESSION_COOKIE_NAME,
    }
