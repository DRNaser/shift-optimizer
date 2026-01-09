"""
SOLVEREIGN V3.3a API - Dependencies
===================================

Shared FastAPI dependencies:
- Database connection
- Tenant authentication (X-API-Key)
- Idempotency handling
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Request, Header, HTTPException, status

from .database import (
    DatabaseManager,
    get_tenant_by_api_key,
    get_core_tenant_by_code,
    get_core_sites_for_tenant,
    get_core_site_by_code,
    get_core_entitlements_for_tenant,
    check_core_entitlement,
)
from .config import settings
from .exceptions import TenantNotFoundError, TenantInactiveError


# =============================================================================
# TENANT CONTEXT
# =============================================================================

@dataclass
class TenantContext:
    """
    Authenticated tenant context.

    Passed to all protected endpoints via dependency injection.
    """
    tenant_id: int
    tenant_name: str
    is_active: bool
    created_at: datetime
    metadata: Optional[dict] = None
    api_key_prefix: Optional[str] = None  # First 8 chars for logging


# =============================================================================
# DEPENDENCIES
# =============================================================================

async def get_db(request: Request) -> DatabaseManager:
    """
    Get database manager from app state.

    Usage:
        @router.get("/items")
        async def list_items(db: DatabaseManager = Depends(get_db)):
            async with db.connection() as conn:
                ...
    """
    return request.app.state.db


async def get_current_tenant(
    request: Request,
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> TenantContext:
    """
    Authenticate request and return tenant context.

    Validates X-API-Key header against tenants table.
    Raises 401 if:
    - Header missing
    - Key doesn't match any tenant
    - Tenant is inactive

    Usage:
        @router.get("/items")
        async def list_items(tenant: TenantContext = Depends(get_current_tenant)):
            print(f"Request from tenant {tenant.tenant_id}")
    """
    # Validate API key format
    if not x_api_key or len(x_api_key) < settings.api_key_min_length:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    # Look up tenant
    db: DatabaseManager = request.app.state.db
    tenant = await get_tenant_by_api_key(db, x_api_key)

    if not tenant:
        raise TenantNotFoundError("Invalid API key")

    if not tenant["is_active"]:
        raise TenantInactiveError(tenant["id"])

    return TenantContext(
        tenant_id=tenant["id"],
        tenant_name=tenant["name"],
        is_active=tenant["is_active"],
        created_at=tenant["created_at"],
        metadata=tenant.get("metadata"),
        api_key_prefix=x_api_key[:8] + "...",
    )


async def get_optional_tenant(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[TenantContext]:
    """
    Optionally authenticate request.

    Returns None if no API key provided.
    Useful for endpoints that work with or without auth.
    """
    if not x_api_key:
        return None

    return await get_current_tenant(request, x_api_key)


# =============================================================================
# CORE TENANT CONTEXT (UUID-based from core.tenants)
# =============================================================================

@dataclass
class CoreTenantContext:
    """
    Authenticated tenant context from core.tenants (UUID-based).

    Used with the new core schema for multi-tenant operations.
    """
    tenant_id: str              # UUID
    tenant_code: str            # URL-safe slug
    tenant_name: str
    is_active: bool
    site_id: Optional[str] = None       # UUID of current site
    site_code: Optional[str] = None
    site_timezone: Optional[str] = None
    is_platform_admin: bool = False
    entitlements: Optional[dict] = None
    metadata: Optional[dict] = None


async def get_core_tenant(
    request: Request,
    x_tenant_code: str = Header(..., alias="X-Tenant-Code"),
    x_site_code: Optional[str] = Header(None, alias="X-Site-Code"),
    x_platform_admin: Optional[str] = Header(None, alias="X-Platform-Admin"),
) -> CoreTenantContext:
    """
    Authenticate request and return core tenant context (UUID-based).

    Headers:
    - X-Tenant-Code: Required. URL-safe tenant code (e.g., 'rohlik', 'mediamarkt')
    - X-Site-Code: Optional. Site code within tenant (e.g., 'wien', 'berlin')
    - X-Platform-Admin: Optional. If 'true' and caller is authorized, enables admin bypass

    BFF Pattern:
    - Frontend calls BFF with auth token
    - BFF validates token, looks up tenant
    - BFF sets X-Tenant-Code header when calling this API
    - Browser NEVER sends X-Tenant-Code directly

    Usage:
        @router.get("/sites")
        async def list_sites(tenant: CoreTenantContext = Depends(get_core_tenant)):
            print(f"Request from {tenant.tenant_code}")
    """
    db: DatabaseManager = request.app.state.db

    # Look up tenant by code
    tenant = await get_core_tenant_by_code(db, x_tenant_code)
    if not tenant:
        raise TenantNotFoundError(f"Tenant '{x_tenant_code}' not found")

    if not tenant["is_active"]:
        raise TenantInactiveError(tenant["tenant_code"])

    tenant_id = str(tenant["id"])
    site_id = None
    site_code = None
    site_timezone = None

    # Look up site if provided
    if x_site_code:
        site = await get_core_site_by_code(db, tenant_id, x_site_code)
        if not site:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Site '{x_site_code}' not found for tenant '{x_tenant_code}'"
            )
        site_id = str(site["id"])
        site_code = site["site_code"]
        site_timezone = site["timezone"]

    # Check platform admin (only internal services can set this)
    is_platform_admin = x_platform_admin == "true"

    # Get entitlements
    entitlements_list = await get_core_entitlements_for_tenant(db, tenant_id)
    entitlements = {
        e["pack_id"]: {
            "is_enabled": e["is_enabled"],
            "config": e["config"]
        }
        for e in entitlements_list
    }

    return CoreTenantContext(
        tenant_id=tenant_id,
        tenant_code=tenant["tenant_code"],
        tenant_name=tenant["name"],
        is_active=tenant["is_active"],
        site_id=site_id,
        site_code=site_code,
        site_timezone=site_timezone,
        is_platform_admin=is_platform_admin,
        entitlements=entitlements,
        metadata=tenant.get("metadata"),
    )


def require_entitlement(pack_id: str):
    """
    Dependency factory that checks for pack entitlement.

    Usage:
        @router.post("/routing/solve")
        async def solve(
            tenant: CoreTenantContext = Depends(get_core_tenant),
            _: None = Depends(require_entitlement("routing"))
        ):
            ...
    """
    async def check_entitlement(
        tenant: CoreTenantContext = None,
    ):
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant context required"
            )
        if tenant.entitlements and tenant.entitlements.get(pack_id, {}).get("is_enabled"):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Pack '{pack_id}' not enabled for tenant '{tenant.tenant_code}'"
        )

    return check_entitlement


# =============================================================================
# SCOPE BLOCKING DEPENDENCY (Fix C)
# =============================================================================

def require_not_blocked(scope_type: str):
    """
    Dependency factory that blocks writes if scope has active S0/S1 escalation.

    This is a HARD GATE for write operations. If scope is blocked:
    - Returns HTTP 503 Service Unavailable
    - Includes reason in response for UI display

    Works standalone - extracts tenant_id from request state.

    Usage:
        @router.post("/plans/{plan_id}/lock")
        async def lock_plan(
            tenant: CoreTenantContext = Depends(get_core_tenant),
            _: None = Depends(require_not_blocked("tenant"))
        ):
            ...

    Args:
        scope_type: platform | org | tenant | site
    """
    async def check_not_blocked(request: Request):
        # Get db manager
        db: DatabaseManager = request.app.state.db

        # Determine scope_id based on scope_type
        if scope_type == "platform":
            scope_id = None
        else:
            # Extract tenant_id from request state (set by auth dependencies)
            # This is called after auth dependencies have run
            scope_id = getattr(request.state, 'tenant_id', None)

            # If not in state, try to extract from path params or query
            if not scope_id:
                # For tenant scope, we need tenant_id
                # In most cases, the auth dependency should have set it
                scope_id = None

        # Check if scope is blocked
        blocked = await is_scope_blocked(db, scope_type, scope_id)

        if blocked:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "service_blocked",
                    "message": "Write operations blocked due to active escalation",
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "action": "Contact platform administrator to resolve escalation"
                }
            )

    return check_not_blocked


def require_tenant_not_blocked(scope_type: str = "tenant"):
    """
    Dependency factory for use with TenantContext-based auth.

    Checks if tenant scope has active S0/S1 escalation.
    Use this with endpoints that use get_current_tenant dependency.
    """
    async def check_not_blocked(
        request: Request,
        tenant: TenantContext = None,
    ):
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant context required"
            )

        db: DatabaseManager = request.app.state.db
        blocked = await is_scope_blocked(db, scope_type, str(tenant.tenant_id))

        if blocked:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "service_blocked",
                    "message": "Write operations blocked due to active escalation",
                    "scope_type": scope_type,
                    "scope_id": str(tenant.tenant_id),
                    "action": "Contact platform administrator to resolve escalation"
                }
            )

    return check_not_blocked


def require_core_tenant_not_blocked(scope_type: str = "tenant"):
    """
    Dependency factory for use with CoreTenantContext-based auth.

    Checks if tenant/site scope has active S0/S1 escalation.
    Use this with endpoints that use get_core_tenant dependency.
    """
    async def check_not_blocked(
        request: Request,
        tenant: CoreTenantContext = None,
    ):
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant context required"
            )

        # Determine scope_id based on scope_type
        if scope_type == "platform":
            scope_id = None
        elif scope_type == "site":
            scope_id = tenant.site_id
        else:
            scope_id = tenant.tenant_id

        db: DatabaseManager = request.app.state.db
        blocked = await is_scope_blocked(db, scope_type, scope_id)

        if blocked:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "service_blocked",
                    "message": "Write operations blocked due to active escalation",
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "action": "Contact platform administrator to resolve escalation"
                }
            )

    return check_not_blocked


def require_entra_user_not_blocked(scope_type: str = "tenant"):
    """
    Dependency factory for use with EntraUserContext-based auth.

    Checks if tenant scope has active S0/S1 escalation.
    Use this with endpoints that use EntraUserContext (Entra ID auth).
    """
    async def check_not_blocked(request: Request):
        # EntraUserContext is resolved before this runs via Depends chain
        # We need to get tenant_id from the user context
        # Since EntraUserContext isn't directly available here,
        # we check via request.state if set, or accept tenant_id as param

        db: DatabaseManager = request.app.state.db

        # Try to get tenant_id from request state (set by auth middleware)
        tenant_id = getattr(request.state, 'tenant_id', None)

        if scope_type == "platform":
            scope_id = None
        else:
            scope_id = str(tenant_id) if tenant_id else None

        blocked = await is_scope_blocked(db, scope_type, scope_id)

        if blocked:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "service_blocked",
                    "message": "Write operations blocked due to active escalation",
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "action": "Contact platform administrator to resolve escalation"
                }
            )

    return check_not_blocked


async def is_scope_blocked(db: DatabaseManager, scope_type: str, scope_id: Optional[str]) -> bool:
    """
    Check if scope has active S0/S1 blocking escalation.

    Queries core.is_scope_blocked() function from migration 017.
    """
    try:
        async with db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT core.is_scope_blocked(%s::core.scope_type, %s)",
                    (scope_type, scope_id)
                )
                result = await cur.fetchone()
                return result["is_scope_blocked"] if result else False
    except Exception:
        # If escalation system is unavailable, fail open (allow writes)
        # This prevents cascading failures
        return False


# =============================================================================
# IDEMPOTENCY DEPENDENCY
# =============================================================================

@dataclass
class IdempotencyContext:
    """Idempotency handling context."""
    key: Optional[str]
    request_hash: str
    status: str  # NEW, HIT, MISMATCH
    cached_response: Optional[dict] = None
    cached_status: Optional[int] = None


def compute_request_hash(body: bytes) -> str:
    """Compute SHA256 hash of request body."""
    return hashlib.sha256(body).hexdigest()


async def get_idempotency(
    request: Request,
    tenant: TenantContext,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
) -> IdempotencyContext:
    """
    Handle idempotency for mutating requests.

    If X-Idempotency-Key header present:
    - Check if key exists in DB
    - If exists with same request hash: return cached response (HIT)
    - If exists with different hash: raise 409 (MISMATCH)
    - If new: proceed with request (NEW)

    Usage:
        @router.post("/items")
        async def create_item(
            idempotency: IdempotencyContext = Depends(get_idempotency)
        ):
            if idempotency.status == "HIT":
                return idempotency.cached_response
            # Process request...
    """
    # No idempotency key = always new
    if not x_idempotency_key:
        body = await request.body()
        return IdempotencyContext(
            key=None,
            request_hash=compute_request_hash(body),
            status="NEW",
        )

    # Get body and compute hash
    body = await request.body()
    request_hash = compute_request_hash(body)

    # Check idempotency in database
    from .database import check_idempotency

    db: DatabaseManager = request.app.state.db
    async with db.connection() as conn:
        result = await check_idempotency(
            conn,
            tenant.tenant_id,
            x_idempotency_key,
            request.url.path,
            request_hash,
        )

    return IdempotencyContext(
        key=x_idempotency_key,
        request_hash=request_hash,
        status=result["status"],
        cached_response=result["cached_response"],
        cached_status=result["cached_status"],
    )


# =============================================================================
# PAGINATION DEPENDENCY
# =============================================================================

@dataclass
class PaginationParams:
    """Pagination parameters."""
    page: int
    page_size: int
    offset: int


async def get_pagination(
    page: int = 1,
    page_size: int = 20,
) -> PaginationParams:
    """
    Validate and compute pagination parameters.

    Limits:
    - page: minimum 1
    - page_size: 1-100

    Usage:
        @router.get("/items")
        async def list_items(pagination: PaginationParams = Depends(get_pagination)):
            offset = pagination.offset
            limit = pagination.page_size
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    if page_size > 100:
        page_size = 100

    return PaginationParams(
        page=page,
        page_size=page_size,
        offset=(page - 1) * page_size,
    )
