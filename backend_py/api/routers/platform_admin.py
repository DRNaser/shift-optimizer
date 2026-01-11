"""
SOLVEREIGN V4.5 - Platform Administration API
==============================================

Endpoints for platform-level administration (platform_admin only):
- Tenant management (CRUD)
- Site management (CRUD)
- User management (CRUD + bindings)
- Role and permission queries

NON-NEGOTIABLES:
- Platform admin only (role_name="platform_admin")
- All actions write audit events with target_tenant_id
- No secrets in responses
- Role assignment boundaries enforced

ROLE ASSIGNMENT RULES:
- Only platform_admin can assign platform_admin role
- tenant_admin cannot assign roles above tenant_admin
- Platform admin uses target_tenant_id for cross-tenant ops (audited)
"""

import hashlib
import json
import logging
import re
import secrets
import uuid
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, EmailStr
from psycopg.errors import UniqueViolation

from ..exceptions import (
    PlatformAdminError,
    TenantNameInvalidError,
    TenantAlreadyExistsError,
    SiteAlreadyExistsError,
    UserAlreadyExistsError,
    ResourceNotFoundError,
    InternalServerError,
    InsufficientPermissionsError,
)


def make_error_response(error: PlatformAdminError) -> JSONResponse:
    """
    Create a JSONResponse with the standard error contract.

    Response format:
    {
        "error": {
            "code": "<STABLE_CODE>",
            "message": "<HUMAN_MESSAGE>",
            "field": "<optional>",
            "details": {...optional...}
        }
    }
    """
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_response(),
    )
from ..security.internal_rbac import (
    InternalUserContext,
    require_platform_admin,
    require_permission,
    set_rls_context_for_tenant,
    hash_password,
    hash_session_token,
    get_rbac_repository,
    SESSION_COOKIE_NAME,
)

# Role hierarchy: higher number = higher privilege
ROLE_HIERARCHY = {
    "ops_readonly": 1,
    "dispatcher": 2,
    "operator_admin": 3,
    "tenant_admin": 4,
    "platform_admin": 5,
}

def validate_role_assignment(assigner_role: str, target_role: str) -> bool:
    """
    Validate that assigner can assign the target role.

    Rules:
    - platform_admin can assign any role
    - tenant_admin can assign tenant_admin or below
    - Others cannot assign roles
    """
    target_level = ROLE_HIERARCHY.get(target_role, 0)

    if assigner_role == "platform_admin":
        return True  # Platform admin can assign any role

    if assigner_role == "tenant_admin":
        return target_level <= ROLE_HIERARCHY["tenant_admin"]

    return False  # Others cannot assign roles


def validate_target_tenant(conn, tenant_id: int) -> bool:
    """Validate that a target tenant exists and is active."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM tenants WHERE id = %s AND is_active = true)",
            (tenant_id,)
        )
        return cur.fetchone()[0]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/platform", tags=["platform-admin"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class TenantCreate(BaseModel):
    """Create tenant request."""
    name: str = Field(..., min_length=2, max_length=100, description="Tenant name")
    owner_display_name: Optional[str] = Field(None, description="Owner display name for reference")


class TenantResponse(BaseModel):
    """Tenant response."""
    id: int
    name: str
    is_active: bool
    created_at: datetime
    user_count: Optional[int] = None
    site_count: Optional[int] = None
    api_key: Optional[str] = Field(
        None,
        description="API key for external integrations. Only returned on create (shown once)."
    )


class SiteCreate(BaseModel):
    """Create site request."""
    name: str = Field(..., min_length=2, max_length=100, description="Site name")
    code: Optional[str] = Field(None, max_length=10, description="Site code (auto-generated if not provided)")


class SiteResponse(BaseModel):
    """Site response."""
    id: int
    tenant_id: int
    name: str
    code: Optional[str]
    created_at: datetime


class UserCreate(BaseModel):
    """Create user request."""
    email: EmailStr = Field(..., description="User email address")
    display_name: Optional[str] = Field(None, max_length=100, description="Display name")
    password: str = Field(..., min_length=8, description="Initial password")
    tenant_id: int = Field(..., description="Tenant ID for binding")
    site_id: Optional[int] = Field(None, description="Site ID for binding (optional)")
    role_name: str = Field(..., description="Role name (e.g., tenant_admin, dispatcher)")


class UserResponse(BaseModel):
    """User response."""
    id: str
    email: str
    display_name: Optional[str]
    is_active: bool
    is_locked: bool
    created_at: datetime
    last_login_at: Optional[datetime]
    bindings: List[dict] = Field(default_factory=list)


class BindingCreate(BaseModel):
    """Create binding request."""
    user_id: str = Field(..., description="User ID")
    tenant_id: int = Field(..., description="Tenant ID")
    site_id: Optional[int] = Field(None, description="Site ID (optional)")
    role_name: str = Field(..., description="Role name")


class BindingResponse(BaseModel):
    """Binding response."""
    id: int
    user_id: str
    tenant_id: int
    site_id: Optional[int]
    role_id: int
    role_name: str
    is_active: bool


class RoleResponse(BaseModel):
    """Role response."""
    id: int
    name: str
    display_name: str
    description: Optional[str]
    is_system: bool


class PermissionResponse(BaseModel):
    """Permission response."""
    id: int
    key: str
    display_name: str
    description: Optional[str]
    category: Optional[str]


class PasswordResetRequest(BaseModel):
    """Request password reset token."""
    send_email: bool = Field(False, description="Send reset link via email (requires notify setup)")


class PasswordResetResponse(BaseModel):
    """Password reset response (pilot mode: returns link to admin)."""
    reset_token: str = Field(..., description="Reset token (pilot only - shown to admin)")
    reset_link: str = Field(..., description="Full reset link")
    expires_in_minutes: int = Field(60, description="Token validity in minutes")
    message: str


class PasswordResetComplete(BaseModel):
    """Complete password reset with token."""
    token: str = Field(..., description="Reset token")
    new_password: str = Field(..., min_length=8, description="New password")


class ContextSetRequest(BaseModel):
    """Set active tenant/site context for platform admin."""
    tenant_id: int = Field(..., description="Target tenant ID")
    site_id: Optional[int] = Field(None, description="Target site ID (optional)")


class ContextResponse(BaseModel):
    """Active context response."""
    active_tenant_id: Optional[int] = None
    active_site_id: Optional[int] = None
    tenant_name: Optional[str] = None
    site_name: Optional[str] = None


class RolePermissionsUpdate(BaseModel):
    """Bulk update permissions for a role."""
    permission_keys: List[str] = Field(..., description="List of permission keys to assign")


class UserLockRequest(BaseModel):
    """Lock user request."""
    reason: str = Field(..., min_length=1, max_length=500, description="Reason for locking")


class SessionResponse(BaseModel):
    """Session response."""
    id: str
    user_id: str
    user_email: str
    tenant_id: Optional[int]
    site_id: Optional[int]
    role_name: str
    created_at: datetime
    expires_at: datetime
    last_activity_at: Optional[datetime]
    is_platform_scope: bool


class SessionRevokeRequest(BaseModel):
    """Revoke sessions request."""
    user_id: Optional[str] = Field(None, description="Revoke all sessions for user")
    tenant_id: Optional[int] = Field(None, description="Revoke all sessions for tenant")
    all: bool = Field(False, description="Revoke ALL sessions (emergency)")
    reason: str = Field("admin_revoke", description="Reason for revocation")


# =============================================================================
# TENANT ENDPOINTS
# =============================================================================

@router.get(
    "/tenants",
    response_model=List[TenantResponse],
    dependencies=[Depends(require_platform_admin())],
)
async def list_tenants(
    request: Request,
    include_counts: bool = Query(False, description="Include user/site counts"),
):
    """List all tenants."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        if include_counts:
            cur.execute(
                """
                SELECT t.id, t.name, t.is_active, t.created_at,
                       (SELECT COUNT(*) FROM auth.user_bindings ub WHERE ub.tenant_id = t.id AND ub.is_active = true) as user_count,
                       (SELECT COUNT(*) FROM sites s WHERE s.tenant_id = t.id) as site_count
                FROM tenants t
                WHERE t.id > 0
                ORDER BY t.name
                """
            )
        else:
            cur.execute(
                """
                SELECT id, name, is_active, created_at, NULL as user_count, NULL as site_count
                FROM tenants
                WHERE id > 0
                ORDER BY name
                """
            )
        rows = cur.fetchall()

    return [
        TenantResponse(
            id=row[0],
            name=row[1],
            is_active=row[2],
            created_at=row[3],
            user_count=row[4],
            site_count=row[5],
        )
        for row in rows
    ]


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    request: Request,
    body: TenantCreate,
    user: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Create a new tenant.

    Error Codes:
    - TENANT_NAME_INVALID (400): Name format validation failed
    - TENANT_ALREADY_EXISTS (409): Duplicate tenant name
    - INTERNAL_ERROR (500): Unexpected server error
    """
    correlation_id = str(uuid.uuid4())[:8]

    # Get connection from RBAC (set by require_platform_admin dependency)
    conn = getattr(request.state, "rbac_conn", None)
    if not conn:
        logger.error("db_connection_missing", extra={"correlation_id": correlation_id})
        return make_error_response(InternalServerError(correlation_id))

    # Validate tenant name format (alphanumeric, spaces, hyphens, underscores)
    name_pattern = re.compile(r'^[\w\s\-\.]+$', re.UNICODE)
    if not name_pattern.match(body.name):
        return make_error_response(TenantNameInvalidError(
            "Name can only contain letters, numbers, spaces, hyphens, underscores, and dots"
        ))

    try:
        with conn.cursor() as cur:
            # Check for duplicate name first (case-insensitive)
            cur.execute(
                "SELECT id FROM tenants WHERE LOWER(name) = LOWER(%s) AND is_active = true",
                (body.name,)
            )
            if cur.fetchone():
                conn.rollback()
                return make_error_response(TenantAlreadyExistsError(body.name))

            # Generate API key for tenant (32 bytes = 64 hex chars when hashed)
            api_key = secrets.token_urlsafe(32)
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            # Create tenant
            cur.execute(
                """
                INSERT INTO tenants (name, api_key_hash, is_active, created_at)
                VALUES (%s, %s, true, NOW())
                RETURNING id, name, is_active, created_at
                """,
                (body.name, api_key_hash)
            )
            row = cur.fetchone()
            tenant_id = row[0]

            # Audit log with target_tenant_id (the newly created tenant)
            try:
                cur.execute(
                    """
                    INSERT INTO auth.audit_log (event_type, user_id, tenant_id, target_tenant_id, details)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        "TENANT_CREATED",
                        user.user_id,
                        user.tenant_id,  # Admin's tenant (NULL for platform admin)
                        tenant_id,  # The newly created tenant
                        json.dumps({
                            "name": body.name,
                            "owner_display_name": body.owner_display_name,
                            "created_by": user.email,
                            "correlation_id": correlation_id,
                        })
                    )
                )
            except Exception as audit_err:
                # Audit log failure should not block tenant creation
                logger.warning("audit_log_failed", extra={
                    "correlation_id": correlation_id,
                    "error": str(audit_err),
                    "tenant_id": tenant_id,
                })

            conn.commit()

    except UniqueViolation:
        conn.rollback()
        # Race condition: name was inserted between check and insert
        return make_error_response(TenantAlreadyExistsError(body.name))

    except Exception as e:
        conn.rollback()
        logger.exception("tenant_creation_failed", extra={
            "correlation_id": correlation_id,
            "tenant_name": body.name,  # 'name' is reserved in LogRecord
            "error": str(e),
            "error_type": type(e).__name__,
        })
        return make_error_response(InternalServerError(correlation_id))

    logger.info("tenant_created", extra={
        "tenant_id": tenant_id,
        "tenant_name": body.name,  # 'name' is reserved in LogRecord
        "created_by": user.email,
        "correlation_id": correlation_id,
    })

    return TenantResponse(
        id=row[0],
        name=row[1],
        is_active=row[2],
        created_at=row[3],
        api_key=api_key,  # Only shown once during creation
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(require_platform_admin())],
)
async def get_tenant(
    request: Request,
    tenant_id: int,
):
    """Get tenant details."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.name, t.is_active, t.created_at,
                   (SELECT COUNT(*) FROM auth.user_bindings ub WHERE ub.tenant_id = t.id AND ub.is_active = true) as user_count,
                   (SELECT COUNT(*) FROM sites s WHERE s.tenant_id = t.id) as site_count
            FROM tenants t
            WHERE t.id = %s AND t.id > 0
            """,
            (tenant_id,)
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return TenantResponse(
        id=row[0],
        name=row[1],
        is_active=row[2],
        created_at=row[3],
        user_count=row[4],
        site_count=row[5],
    )


# =============================================================================
# SITE ENDPOINTS
# =============================================================================

@router.get(
    "/tenants/{tenant_id}/sites",
    response_model=List[SiteResponse],
    dependencies=[Depends(require_platform_admin())],
)
async def list_sites(
    request: Request,
    tenant_id: int,
):
    """List sites for a tenant."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, name, code, created_at
            FROM sites
            WHERE tenant_id = %s
            ORDER BY name
            """,
            (tenant_id,)
        )
        rows = cur.fetchall()

    return [
        SiteResponse(
            id=row[0],
            tenant_id=row[1],
            name=row[2],
            code=row[3],
            created_at=row[4],
        )
        for row in rows
    ]


@router.post(
    "/tenants/{tenant_id}/sites",
    response_model=SiteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_site(
    request: Request,
    tenant_id: int,
    body: SiteCreate,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Create a new site for a tenant."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Validate target tenant exists and is active
    if not validate_target_tenant(conn, tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found or inactive")

    # Generate code if not provided
    code = body.code or body.name[:3].upper()

    with conn.cursor() as cur:
        # Create site
        cur.execute(
            """
            INSERT INTO sites (tenant_id, name, code, created_at)
            VALUES (%s, %s, %s, NOW())
            RETURNING id, tenant_id, name, code, created_at
            """,
            (tenant_id, body.name, code)
        )
        row = cur.fetchone()
        site_id = row[0]

        # Audit log with target_tenant_id
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, target_tenant_id, site_id, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                "SITE_CREATED",
                admin.user_id,
                admin.tenant_id,  # Admin's tenant (NULL for platform admin)
                tenant_id,  # Target tenant
                site_id,
                json.dumps({"name": body.name, "code": code, "created_by": admin.email})
            )
        )
        conn.commit()

    logger.info("site_created", extra={
        "site_id": site_id,
        "tenant_id": tenant_id,
        "created_by": admin.email,
    })

    return SiteResponse(
        id=row[0],
        tenant_id=row[1],
        name=row[2],
        code=row[3],
        created_at=row[4],
    )


# =============================================================================
# USER ENDPOINTS
# =============================================================================

@router.get(
    "/users",
    response_model=List[UserResponse],
    dependencies=[Depends(require_platform_admin())],
)
async def list_users(
    request: Request,
    tenant_id: Optional[int] = Query(None, description="Filter by tenant ID"),
):
    """List all users (optionally filtered by tenant)."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        if tenant_id:
            cur.execute(
                """
                SELECT DISTINCT u.id, u.email, u.display_name, u.is_active, u.is_locked, u.created_at, u.last_login_at
                FROM auth.users u
                JOIN auth.user_bindings ub ON u.id = ub.user_id
                WHERE ub.tenant_id = %s
                ORDER BY u.email
                """,
                (tenant_id,)
            )
        else:
            cur.execute(
                """
                SELECT id, email, display_name, is_active, is_locked, created_at, last_login_at
                FROM auth.users
                ORDER BY email
                """
            )
        users = cur.fetchall()

        # Get bindings for each user
        result = []
        for user_row in users:
            user_id = str(user_row[0])
            cur.execute(
                """
                SELECT ub.id, ub.tenant_id, ub.site_id, ub.role_id, r.name as role_name, ub.is_active
                FROM auth.user_bindings ub
                JOIN auth.roles r ON r.id = ub.role_id
                WHERE ub.user_id = %s
                """,
                (user_id,)
            )
            bindings = [
                {
                    "id": b[0],
                    "tenant_id": b[1],
                    "site_id": b[2],
                    "role_id": b[3],
                    "role_name": b[4],
                    "is_active": b[5],
                }
                for b in cur.fetchall()
            ]

            result.append(UserResponse(
                id=user_id,
                email=user_row[1],
                display_name=user_row[2],
                is_active=user_row[3],
                is_locked=user_row[4],
                created_at=user_row[5],
                last_login_at=user_row[6],
                bindings=bindings,
            ))

    return result


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    request: Request,
    body: UserCreate,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Create a new user with initial binding.

    Role assignment rules:
    - platform_admin can assign any role
    - Only platform_admin can create platform_admin users
    """
    import uuid

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # PRIVILEGE BOUNDARY: Validate role assignment
    if not validate_role_assignment(admin.role_name, body.role_name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot assign role '{body.role_name}': insufficient privileges"
        )

    # Special case: platform_admin role requires NULL tenant (platform-wide)
    if body.role_name == "platform_admin" and body.tenant_id is not None:
        # For platform_admin, we ignore tenant_id and use NULL
        logger.warning(
            "platform_admin_tenant_ignored",
            extra={"requested_tenant": body.tenant_id, "created_by": admin.email}
        )

    with conn.cursor() as cur:
        # Check email uniqueness
        cur.execute(
            "SELECT id FROM auth.users WHERE LOWER(email) = LOWER(%s)",
            (body.email,)
        )
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="User with this email already exists")

        # Validate target tenant (unless creating platform_admin)
        if body.role_name != "platform_admin":
            if not validate_target_tenant(conn, body.tenant_id):
                raise HTTPException(status_code=400, detail="Tenant not found or inactive")

            # Verify site exists (if provided)
            if body.site_id:
                cur.execute(
                    "SELECT id FROM sites WHERE id = %s AND tenant_id = %s",
                    (body.site_id, body.tenant_id)
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail="Site not found in tenant")

        # Get role ID
        cur.execute("SELECT id FROM auth.roles WHERE name = %s", (body.role_name,))
        role_row = cur.fetchone()
        if not role_row:
            raise HTTPException(status_code=400, detail=f"Invalid role: {body.role_name}")
        role_id = role_row[0]

        # Hash password
        password_hash = hash_password(body.password)

        # Create user
        new_user_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO auth.users (id, email, password_hash, display_name, is_active)
            VALUES (%s, %s, %s, %s, true)
            RETURNING id, email, display_name, is_active, is_locked, created_at, last_login_at
            """,
            (new_user_id, body.email.lower(), password_hash, body.display_name)
        )
        user_row = cur.fetchone()

        # Create binding (NULL tenant for platform_admin)
        effective_tenant_id = None if body.role_name == "platform_admin" else body.tenant_id
        effective_site_id = None if body.role_name == "platform_admin" else body.site_id

        cur.execute(
            """
            INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
            VALUES (%s, %s, %s, %s, true)
            RETURNING id
            """,
            (new_user_id, effective_tenant_id, effective_site_id, role_id)
        )
        binding_id = cur.fetchone()[0]

        # Audit log with target_tenant_id
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, target_tenant_id, site_id, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                "USER_CREATED",
                admin.user_id,  # The admin who created the user
                admin.tenant_id,  # Admin's tenant (NULL for platform admin)
                effective_tenant_id,  # Target tenant for the new user
                effective_site_id,
                json.dumps({
                    "new_user_id": new_user_id,
                    "email": body.email.lower(),
                    "role": body.role_name,
                    "created_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("user_created", extra={
        "user_id": new_user_id,
        "email": body.email,
        "role": body.role_name,
        "target_tenant": effective_tenant_id,
        "created_by": admin.email,
    })

    return UserResponse(
        id=str(user_row[0]),
        email=user_row[1],
        display_name=user_row[2],
        is_active=user_row[3],
        is_locked=user_row[4],
        created_at=user_row[5],
        last_login_at=user_row[6],
        bindings=[{
            "id": binding_id,
            "tenant_id": effective_tenant_id,
            "site_id": effective_site_id,
            "role_id": role_id,
            "role_name": body.role_name,
            "is_active": True,
        }],
    )


@router.post(
    "/users/{user_id}/request-password-reset",
    response_model=PasswordResetResponse,
)
async def request_password_reset(
    request: Request,
    user_id: str,
    body: PasswordResetRequest,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Request a password reset token for a user.

    PILOT MODE: Returns reset link to platform_admin.
    PRODUCTION: Should send via email/notification.

    NO PLAINTEXT PASSWORD is ever returned or stored.
    """
    import secrets
    import hashlib
    from datetime import timedelta, timezone

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Generate secure reset token
    reset_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(reset_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=60)

    with conn.cursor() as cur:
        # Verify user exists and get email
        cur.execute(
            "SELECT id, email FROM auth.users WHERE id = %s",
            (user_id,)
        )
        user_row = cur.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        user_email = user_row[1]

        # Store reset token (hashed) - use password_reset_token column or create temp table
        # For pilot: store in a simple way using password_changed_at as marker
        cur.execute(
            """
            UPDATE auth.users
            SET password_reset_token = %s, password_reset_expires = %s
            WHERE id = %s
            """,
            (token_hash, expires_at, user_id)
        )

        # Revoke all existing sessions for security
        cur.execute(
            """
            UPDATE auth.sessions
            SET revoked_at = NOW(), revoked_reason = 'password_reset_requested'
            WHERE user_id = %s AND revoked_at IS NULL
            """,
            (user_id,)
        )

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "PASSWORD_RESET_REQUESTED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "target_user_id": user_id,
                    "target_email": user_email,
                    "requested_by": admin.email,
                    "send_email": body.send_email,
                })
            )
        )
        conn.commit()

    # Build reset link (frontend will handle this route)
    # In production, this would be sent via email
    base_url = request.headers.get("origin", "http://localhost:3000")
    reset_link = f"{base_url}/platform/reset-password?token={reset_token}"

    logger.info("password_reset_requested", extra={
        "user_id": user_id,
        "requested_by": admin.email,
        "send_email": body.send_email,
    })

    if body.send_email:
        # TODO: Send via notification pipeline
        # For now, still return to admin
        message = "Reset link would be sent via email (not implemented in pilot). Showing to admin instead."
    else:
        message = "PILOT MODE: Securely share this link with the user. Link expires in 60 minutes."

    return PasswordResetResponse(
        reset_token=reset_token,
        reset_link=reset_link,
        expires_in_minutes=60,
        message=message,
    )


@router.post(
    "/complete-password-reset",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_password_reset(
    request: Request,
    body: PasswordResetComplete,
):
    """
    Complete password reset using token.

    This endpoint is PUBLIC (no auth required) - user has the reset token.
    """
    import hashlib
    from datetime import timezone

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    password_hash = hash_password(body.new_password)

    with conn.cursor() as cur:
        # Find user with valid reset token
        cur.execute(
            """
            SELECT id, email FROM auth.users
            WHERE password_reset_token = %s
              AND password_reset_expires > NOW()
            """,
            (token_hash,)
        )
        user_row = cur.fetchone()
        if not user_row:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired reset token"
            )

        user_id = str(user_row[0])
        user_email = user_row[1]

        # Update password and clear reset token
        cur.execute(
            """
            UPDATE auth.users
            SET password_hash = %s,
                password_changed_at = NOW(),
                password_reset_token = NULL,
                password_reset_expires = NULL
            WHERE id = %s
            """,
            (password_hash, user_id)
        )

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, details)
            VALUES (%s, %s, %s)
            """,
            (
                "PASSWORD_RESET_COMPLETED",
                user_id,
                json.dumps({"email": user_email})
            )
        )
        conn.commit()

    logger.info("password_reset_completed", extra={"user_id": user_id})


# =============================================================================
# BINDING ENDPOINTS
# =============================================================================

@router.post(
    "/bindings",
    response_model=BindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_binding(
    request: Request,
    body: BindingCreate,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Create a new user binding.

    Role assignment rules:
    - platform_admin can assign any role
    - Only platform_admin can assign platform_admin role
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # PRIVILEGE BOUNDARY: Validate role assignment
    if not validate_role_assignment(admin.role_name, body.role_name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot assign role '{body.role_name}': insufficient privileges"
        )

    # Validate target tenant (unless assigning platform_admin)
    effective_tenant_id = None if body.role_name == "platform_admin" else body.tenant_id
    effective_site_id = None if body.role_name == "platform_admin" else body.site_id

    if body.role_name != "platform_admin":
        if not validate_target_tenant(conn, body.tenant_id):
            raise HTTPException(status_code=400, detail="Tenant not found or inactive")

    with conn.cursor() as cur:
        # Verify user exists
        cur.execute("SELECT id FROM auth.users WHERE id = %s", (body.user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail="User not found")

        # Get role ID
        cur.execute("SELECT id FROM auth.roles WHERE name = %s", (body.role_name,))
        role_row = cur.fetchone()
        if not role_row:
            raise HTTPException(status_code=400, detail=f"Invalid role: {body.role_name}")
        role_id = role_row[0]

        # Check for existing binding (handle NULL tenant_id for platform_admin)
        if effective_tenant_id is None:
            cur.execute(
                """
                SELECT id FROM auth.user_bindings
                WHERE user_id = %s AND tenant_id IS NULL AND role_id = %s
                """,
                (body.user_id, role_id)
            )
        else:
            cur.execute(
                """
                SELECT id FROM auth.user_bindings
                WHERE user_id = %s AND tenant_id = %s AND (site_id = %s OR (site_id IS NULL AND %s IS NULL))
                """,
                (body.user_id, effective_tenant_id, effective_site_id, effective_site_id)
            )
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Binding already exists")

        # Create binding
        cur.execute(
            """
            INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
            VALUES (%s, %s, %s, %s, true)
            RETURNING id, user_id, tenant_id, site_id, role_id, is_active
            """,
            (body.user_id, effective_tenant_id, effective_site_id, role_id)
        )
        row = cur.fetchone()

        # Audit log with target_tenant_id
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, target_tenant_id, site_id, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                "BINDING_CREATED",
                admin.user_id,
                admin.tenant_id,
                effective_tenant_id,
                effective_site_id,
                json.dumps({
                    "target_user_id": body.user_id,
                    "role": body.role_name,
                    "created_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("binding_created", extra={
        "user_id": body.user_id,
        "role": body.role_name,
        "target_tenant": effective_tenant_id,
        "created_by": admin.email,
    })

    return BindingResponse(
        id=row[0],
        user_id=str(row[1]),
        tenant_id=row[2],
        site_id=row[3],
        role_id=row[4],
        role_name=body.role_name,
        is_active=row[5],
    )


@router.delete(
    "/bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_binding(
    request: Request,
    binding_id: int,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Delete (deactivate) a user binding."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth.user_bindings
            SET is_active = false, updated_at = NOW()
            WHERE id = %s
            RETURNING user_id, tenant_id, site_id
            """,
            (binding_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Binding not found")

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, site_id, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                "BINDING_DELETED",
                str(row[0]),
                row[1],
                row[2],
                json.dumps({"deleted_by": admin.email})
            )
        )
        conn.commit()


# =============================================================================
# ROLE & PERMISSION ENDPOINTS
# =============================================================================

@router.get(
    "/roles",
    response_model=List[RoleResponse],
    dependencies=[Depends(require_platform_admin())],
)
async def list_roles(request: Request):
    """List all roles."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, display_name, description, is_system
            FROM auth.roles
            ORDER BY id
            """
        )
        rows = cur.fetchall()

    return [
        RoleResponse(
            id=row[0],
            name=row[1],
            display_name=row[2],
            description=row[3],
            is_system=row[4],
        )
        for row in rows
    ]


@router.get(
    "/permissions",
    response_model=List[PermissionResponse],
    dependencies=[Depends(require_platform_admin())],
)
async def list_permissions(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """List all permissions."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        if category:
            cur.execute(
                """
                SELECT id, key, display_name, description, category
                FROM auth.permissions
                WHERE category = %s
                ORDER BY key
                """,
                (category,)
            )
        else:
            cur.execute(
                """
                SELECT id, key, display_name, description, category
                FROM auth.permissions
                ORDER BY category, key
                """
            )
        rows = cur.fetchall()

    return [
        PermissionResponse(
            id=row[0],
            key=row[1],
            display_name=row[2],
            description=row[3],
            category=row[4],
        )
        for row in rows
    ]


@router.get(
    "/roles/{role_name}/permissions",
    response_model=List[str],
    dependencies=[Depends(require_platform_admin())],
)
async def get_role_permissions(request: Request, role_name: str):
    """Get permissions for a role."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.key
            FROM auth.role_permissions rp
            JOIN auth.roles r ON r.id = rp.role_id
            JOIN auth.permissions p ON p.id = rp.permission_id
            WHERE r.name = %s
            ORDER BY p.key
            """,
            (role_name,)
        )
        rows = cur.fetchall()

    return [row[0] for row in rows]


# =============================================================================
# CONTEXT SWITCHING ENDPOINTS
# =============================================================================

@router.get(
    "/context",
    response_model=ContextResponse,
)
async def get_context(
    request: Request,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Get current active tenant/site context for platform admin.

    Returns the active context set via POST /api/platform/context.
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    tenant_name = None
    site_name = None

    # Get tenant/site names if context is set
    if admin.active_tenant_id:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM tenants WHERE id = %s",
                (admin.active_tenant_id,)
            )
            row = cur.fetchone()
            if row:
                tenant_name = row[0]

            if admin.active_site_id:
                cur.execute(
                    "SELECT name FROM sites WHERE id = %s",
                    (admin.active_site_id,)
                )
                row = cur.fetchone()
                if row:
                    site_name = row[0]

    return ContextResponse(
        active_tenant_id=admin.active_tenant_id,
        active_site_id=admin.active_site_id,
        tenant_name=tenant_name,
        site_name=site_name,
    )


@router.post(
    "/context",
    response_model=ContextResponse,
)
async def set_context(
    request: Request,
    body: ContextSetRequest,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Set active tenant/site context for platform admin session.

    This allows platform admins to use tenant-scoped UIs (pack, portal)
    without needing actual bindings to those tenants.

    The context is stored in the session and persists until cleared or
    changed. All operations performed while context is set will use
    this tenant's data scope.

    AUDITED: All context switches are logged with target_tenant_id.

    HARDENING (V4.6):
    - Validates tenant exists and is active
    - Validates site belongs to tenant (if provided)
    """
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # V4.6: Validate tenant exists and is active
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM tenants WHERE id = %s AND is_active = true",
            (body.tenant_id,)
        )
        tenant_row = cur.fetchone()
        if not tenant_row:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "TENANT_NOT_FOUND", "message": "Tenant not found or inactive"}
            )

        # V4.6: Validate site belongs to tenant (if provided)
        if body.site_id:
            cur.execute(
                "SELECT id, name FROM sites WHERE id = %s AND tenant_id = %s",
                (body.site_id, body.tenant_id)
            )
            site_row = cur.fetchone()
            if not site_row:
                raise HTTPException(
                    status_code=400,
                    detail={"error_code": "SITE_TENANT_MISMATCH", "message": "Site does not belong to tenant"}
                )

    # Get session token from cookie
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(status_code=401, detail="Session cookie not found")

    session_hash = hash_session_token(session_token)
    repo = get_rbac_repository(request)

    # Call SQL function to set context
    result = repo.set_platform_context(session_hash, body.tenant_id, body.site_id)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Failed to set context")
        )

    # Get tenant/site names for response
    conn = getattr(request.state, "conn", None)
    tenant_name = None
    site_name = None

    if conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM tenants WHERE id = %s", (body.tenant_id,))
            row = cur.fetchone()
            if row:
                tenant_name = row[0]

            if body.site_id:
                cur.execute("SELECT name FROM sites WHERE id = %s", (body.site_id,))
                row = cur.fetchone()
                if row:
                    site_name = row[0]

    logger.info("context_set", extra={
        "admin_email": admin.email,
        "tenant_id": body.tenant_id,
        "site_id": body.site_id,
    })

    return ContextResponse(
        active_tenant_id=body.tenant_id,
        active_site_id=body.site_id,
        tenant_name=tenant_name,
        site_name=site_name,
    )


@router.delete(
    "/context",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_context(
    request: Request,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Clear active tenant/site context for platform admin session.

    Returns the session to platform-wide scope (no specific tenant).
    """
    # Get session token from cookie
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(status_code=401, detail="Session cookie not found")

    session_hash = hash_session_token(session_token)
    repo = get_rbac_repository(request)

    # Call SQL function to clear context
    result = repo.clear_platform_context(session_hash)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Failed to clear context")
        )

    logger.info("context_cleared", extra={"admin_email": admin.email})


# =============================================================================
# ROLE PERMISSION MANAGEMENT ENDPOINTS (V4.6)
# =============================================================================

@router.put(
    "/roles/{role_name}/permissions",
    response_model=List[str],
)
async def update_role_permissions(
    request: Request,
    role_name: str,
    body: RolePermissionsUpdate,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Bulk update permissions for a system role.

    Replaces all existing permissions with the provided list.
    Cannot modify platform_admin permissions.
    """
    # Cannot modify platform_admin role
    if role_name == "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify platform_admin permissions"
        )

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Get role ID
        cur.execute("SELECT id FROM auth.roles WHERE name = %s", (role_name,))
        role_row = cur.fetchone()
        if not role_row:
            raise HTTPException(status_code=404, detail=f"Role not found: {role_name}")
        role_id = role_row[0]

        # Validate all permission keys exist
        if body.permission_keys:
            cur.execute(
                "SELECT key FROM auth.permissions WHERE key = ANY(%s)",
                (body.permission_keys,)
            )
            valid_keys = {row[0] for row in cur.fetchall()}
            invalid_keys = set(body.permission_keys) - valid_keys
            if invalid_keys:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid permission keys: {', '.join(invalid_keys)}"
                )

        # Get old permissions for audit
        cur.execute(
            """
            SELECT p.key FROM auth.role_permissions rp
            JOIN auth.permissions p ON p.id = rp.permission_id
            WHERE rp.role_id = %s
            """,
            (role_id,)
        )
        old_permissions = [row[0] for row in cur.fetchall()]

        # Clear existing permissions
        cur.execute("DELETE FROM auth.role_permissions WHERE role_id = %s", (role_id,))

        # Add new permissions
        if body.permission_keys:
            cur.execute(
                """
                INSERT INTO auth.role_permissions (role_id, permission_id)
                SELECT %s, id FROM auth.permissions WHERE key = ANY(%s)
                """,
                (role_id, body.permission_keys)
            )

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "ROLE_PERMISSIONS_UPDATED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "role_name": role_name,
                    "old_permissions": old_permissions,
                    "new_permissions": body.permission_keys,
                    "updated_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("role_permissions_updated", extra={
        "role_name": role_name,
        "permission_count": len(body.permission_keys),
        "updated_by": admin.email,
    })

    return body.permission_keys


@router.post(
    "/roles/{role_name}/permissions/{perm_key}",
    status_code=status.HTTP_201_CREATED,
)
async def add_role_permission(
    request: Request,
    role_name: str,
    perm_key: str,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Add a single permission to a role."""
    if role_name == "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify platform_admin permissions"
        )

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Get role ID
        cur.execute("SELECT id FROM auth.roles WHERE name = %s", (role_name,))
        role_row = cur.fetchone()
        if not role_row:
            raise HTTPException(status_code=404, detail=f"Role not found: {role_name}")
        role_id = role_row[0]

        # Get permission ID
        cur.execute("SELECT id FROM auth.permissions WHERE key = %s", (perm_key,))
        perm_row = cur.fetchone()
        if not perm_row:
            raise HTTPException(status_code=404, detail=f"Permission not found: {perm_key}")
        perm_id = perm_row[0]

        # Check if already assigned
        cur.execute(
            "SELECT 1 FROM auth.role_permissions WHERE role_id = %s AND permission_id = %s",
            (role_id, perm_id)
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Permission already assigned")

        # Add permission
        cur.execute(
            "INSERT INTO auth.role_permissions (role_id, permission_id) VALUES (%s, %s)",
            (role_id, perm_id)
        )

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "ROLE_PERMISSION_ADDED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "role_name": role_name,
                    "permission_key": perm_key,
                    "added_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("role_permission_added", extra={
        "role_name": role_name,
        "permission_key": perm_key,
        "added_by": admin.email,
    })

    return {"success": True, "role": role_name, "permission": perm_key}


@router.delete(
    "/roles/{role_name}/permissions/{perm_key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_role_permission(
    request: Request,
    role_name: str,
    perm_key: str,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Remove a single permission from a role."""
    if role_name == "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify platform_admin permissions"
        )

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Get role ID
        cur.execute("SELECT id FROM auth.roles WHERE name = %s", (role_name,))
        role_row = cur.fetchone()
        if not role_row:
            raise HTTPException(status_code=404, detail=f"Role not found: {role_name}")
        role_id = role_row[0]

        # Get permission ID
        cur.execute("SELECT id FROM auth.permissions WHERE key = %s", (perm_key,))
        perm_row = cur.fetchone()
        if not perm_row:
            raise HTTPException(status_code=404, detail=f"Permission not found: {perm_key}")
        perm_id = perm_row[0]

        # Remove permission
        cur.execute(
            "DELETE FROM auth.role_permissions WHERE role_id = %s AND permission_id = %s RETURNING 1",
            (role_id, perm_id)
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Permission not assigned to role")

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "ROLE_PERMISSION_REMOVED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "role_name": role_name,
                    "permission_key": perm_key,
                    "removed_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("role_permission_removed", extra={
        "role_name": role_name,
        "permission_key": perm_key,
        "removed_by": admin.email,
    })


# =============================================================================
# USER MANAGEMENT ENDPOINTS (V4.6)
# =============================================================================

@router.get(
    "/users/{user_id}/bindings",
    response_model=List[BindingResponse],
    dependencies=[Depends(require_platform_admin())],
)
async def get_user_bindings(
    request: Request,
    user_id: str,
):
    """Get all bindings for a user."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        # Verify user exists
        cur.execute("SELECT id FROM auth.users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        cur.execute(
            """
            SELECT ub.id, ub.user_id, ub.tenant_id, ub.site_id, ub.role_id, r.name as role_name, ub.is_active
            FROM auth.user_bindings ub
            JOIN auth.roles r ON r.id = ub.role_id
            WHERE ub.user_id = %s
            ORDER BY ub.created_at
            """,
            (user_id,)
        )
        rows = cur.fetchall()

    return [
        BindingResponse(
            id=row[0],
            user_id=str(row[1]),
            tenant_id=row[2],
            site_id=row[3],
            role_id=row[4],
            role_name=row[5],
            is_active=row[6],
        )
        for row in rows
    ]


@router.post(
    "/users/{user_id}/disable",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disable_user(
    request: Request,
    user_id: str,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Disable a user (set is_active=FALSE)."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Cannot disable yourself
    if str(admin.user_id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot disable your own account")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth.users SET is_active = FALSE, updated_at = NOW()
            WHERE id = %s
            RETURNING email
            """,
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        user_email = row[0]

        # Revoke all sessions
        cur.execute(
            """
            UPDATE auth.sessions
            SET revoked_at = NOW(), revoked_reason = 'user_disabled'
            WHERE user_id = %s AND revoked_at IS NULL
            """,
            (user_id,)
        )

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "USER_DISABLED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "target_user_id": user_id,
                    "target_email": user_email,
                    "disabled_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("user_disabled", extra={
        "target_user_id": user_id,
        "disabled_by": admin.email,
    })


@router.post(
    "/users/{user_id}/enable",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def enable_user(
    request: Request,
    user_id: str,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Enable a user (set is_active=TRUE)."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth.users SET is_active = TRUE, updated_at = NOW()
            WHERE id = %s
            RETURNING email
            """,
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        user_email = row[0]

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "USER_ENABLED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "target_user_id": user_id,
                    "target_email": user_email,
                    "enabled_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("user_enabled", extra={
        "target_user_id": user_id,
        "enabled_by": admin.email,
    })


@router.post(
    "/users/{user_id}/lock",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def lock_user(
    request: Request,
    user_id: str,
    body: UserLockRequest,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Lock a user account with reason."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Cannot lock yourself
    if str(admin.user_id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot lock your own account")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth.users
            SET is_locked = TRUE, lock_reason = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING email
            """,
            (body.reason, user_id)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        user_email = row[0]

        # Revoke all sessions
        cur.execute(
            """
            UPDATE auth.sessions
            SET revoked_at = NOW(), revoked_reason = 'user_locked'
            WHERE user_id = %s AND revoked_at IS NULL
            """,
            (user_id,)
        )

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "USER_LOCKED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "target_user_id": user_id,
                    "target_email": user_email,
                    "reason": body.reason,
                    "locked_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("user_locked", extra={
        "target_user_id": user_id,
        "reason": body.reason,
        "locked_by": admin.email,
    })


@router.post(
    "/users/{user_id}/unlock",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlock_user(
    request: Request,
    user_id: str,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """Unlock a user account."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE auth.users
            SET is_locked = FALSE, lock_reason = NULL, failed_login_count = 0, updated_at = NOW()
            WHERE id = %s
            RETURNING email
            """,
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        user_email = row[0]

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "USER_UNLOCKED",
                admin.user_id,
                admin.tenant_id,
                json.dumps({
                    "target_user_id": user_id,
                    "target_email": user_email,
                    "unlocked_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("user_unlocked", extra={
        "target_user_id": user_id,
        "unlocked_by": admin.email,
    })


# =============================================================================
# SESSION MANAGEMENT ENDPOINTS (V4.6)
# =============================================================================

@router.get(
    "/sessions",
    response_model=List[SessionResponse],
    dependencies=[Depends(require_platform_admin())],
)
async def list_sessions(
    request: Request,
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    tenant_id: Optional[int] = Query(None, description="Filter by tenant ID"),
    active_only: bool = Query(True, description="Only show active sessions"),
):
    """List sessions with optional filters."""
    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        query = """
            SELECT s.id, s.user_id, u.email, s.tenant_id, s.site_id, r.name as role_name,
                   s.created_at, s.expires_at, s.last_activity_at, s.is_platform_scope
            FROM auth.sessions s
            JOIN auth.users u ON u.id = s.user_id
            JOIN auth.roles r ON r.id = s.role_id
            WHERE 1=1
        """
        params = []

        if active_only:
            query += " AND s.revoked_at IS NULL AND s.expires_at > NOW()"

        if user_id:
            query += " AND s.user_id = %s"
            params.append(user_id)

        if tenant_id:
            query += " AND s.tenant_id = %s"
            params.append(tenant_id)

        query += " ORDER BY s.created_at DESC LIMIT 100"

        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        SessionResponse(
            id=str(row[0]),
            user_id=str(row[1]),
            user_email=row[2],
            tenant_id=row[3],
            site_id=row[4],
            role_name=row[5],
            created_at=row[6],
            expires_at=row[7],
            last_activity_at=row[8],
            is_platform_scope=row[9],
        )
        for row in rows
    ]


@router.post(
    "/sessions/revoke",
    status_code=status.HTTP_200_OK,
)
async def revoke_sessions(
    request: Request,
    body: SessionRevokeRequest,
    admin: InternalUserContext = Depends(require_platform_admin()),
):
    """
    Revoke sessions by criteria.

    Must specify exactly one of: user_id, tenant_id, or all=true
    """
    # Validate exactly one criteria specified
    criteria_count = sum([
        body.user_id is not None,
        body.tenant_id is not None,
        body.all,
    ])
    if criteria_count != 1:
        raise HTTPException(
            status_code=400,
            detail="Must specify exactly one of: user_id, tenant_id, or all"
        )

    conn = getattr(request.state, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection not available")

    with conn.cursor() as cur:
        if body.user_id:
            # Revoke by user
            cur.execute(
                """
                UPDATE auth.sessions
                SET revoked_at = NOW(), revoked_reason = %s
                WHERE user_id = %s AND revoked_at IS NULL
                RETURNING id
                """,
                (body.reason, body.user_id)
            )
            revoked_count = len(cur.fetchall())
            target_desc = f"user_id={body.user_id}"

        elif body.tenant_id:
            # Revoke by tenant
            cur.execute(
                """
                UPDATE auth.sessions
                SET revoked_at = NOW(), revoked_reason = %s
                WHERE tenant_id = %s AND revoked_at IS NULL
                RETURNING id
                """,
                (body.reason, body.tenant_id)
            )
            revoked_count = len(cur.fetchall())
            target_desc = f"tenant_id={body.tenant_id}"

        else:
            # Revoke all (excluding current session)
            session_token = request.cookies.get(SESSION_COOKIE_NAME)
            current_hash = hash_session_token(session_token) if session_token else None

            cur.execute(
                """
                UPDATE auth.sessions
                SET revoked_at = NOW(), revoked_reason = %s
                WHERE revoked_at IS NULL AND session_hash != COALESCE(%s, '')
                RETURNING id
                """,
                (body.reason, current_hash)
            )
            revoked_count = len(cur.fetchall())
            target_desc = "all_sessions"

        # Audit log
        cur.execute(
            """
            INSERT INTO auth.audit_log (event_type, user_id, tenant_id, target_tenant_id, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                "SESSIONS_BULK_REVOKED",
                admin.user_id,
                admin.tenant_id,
                body.tenant_id,
                json.dumps({
                    "target": target_desc,
                    "revoked_count": revoked_count,
                    "reason": body.reason,
                    "revoked_by": admin.email,
                })
            )
        )
        conn.commit()

    logger.info("sessions_revoked", extra={
        "target": target_desc,
        "revoked_count": revoked_count,
        "revoked_by": admin.email,
    })

    return {"success": True, "revoked_count": revoked_count}
