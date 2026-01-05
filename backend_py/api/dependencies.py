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
from typing import Optional, Any

from fastapi import Request, Header, HTTPException, status

from .database import DatabaseManager, get_tenant_by_api_key
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
