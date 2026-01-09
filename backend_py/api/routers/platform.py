"""
SOLVEREIGN Platform API - Admin Operations
==========================================

Platform-level administrative endpoints for managing tenants, sites, and entitlements.
Requires X-Platform-Admin: true header (enforced by BFF/API Gateway).
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_core_tenant, CoreTenantContext
from ..database import DatabaseManager

router = APIRouter()


# =============================================================================
# PLATFORM ADMIN CHECK
# =============================================================================

async def require_platform_admin(
    x_platform_admin: Optional[str] = Header(None, alias="X-Platform-Admin"),
):
    """
    Require platform admin access for endpoint.

    In production, this header should only be set by internal services
    or API Gateway after validating admin credentials.
    """
    if x_platform_admin != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required"
        )


# =============================================================================
# SCHEMAS
# =============================================================================

class TenantResponse(BaseModel):
    """Core tenant information."""
    id: str
    tenant_code: str
    name: str
    is_active: bool
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class TenantListResponse(BaseModel):
    """List of tenants."""
    tenants: List[TenantResponse]
    total: int


class SiteResponse(BaseModel):
    """Site information."""
    id: str
    tenant_id: str
    site_code: str
    name: str
    timezone: str
    is_active: bool
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class SiteListResponse(BaseModel):
    """List of sites."""
    sites: List[SiteResponse]
    total: int


class EntitlementResponse(BaseModel):
    """Entitlement information."""
    id: str
    tenant_id: str
    pack_id: str
    is_enabled: bool
    config: Optional[dict] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class EntitlementListResponse(BaseModel):
    """List of entitlements."""
    entitlements: List[EntitlementResponse]
    total: int


class CreateTenantRequest(BaseModel):
    """Request to create a new tenant."""
    tenant_code: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    name: str = Field(..., min_length=1, max_length=255)
    metadata: Optional[dict] = None


class CreateSiteRequest(BaseModel):
    """Request to create a new site."""
    site_code: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    name: str = Field(..., min_length=1, max_length=255)
    timezone: str = Field(default="Europe/Berlin", max_length=50)
    metadata: Optional[dict] = None


class SetEntitlementRequest(BaseModel):
    """Request to set entitlement for a tenant."""
    pack_id: str = Field(..., pattern=r'^(core|routing|roster|analytics)$')
    is_enabled: bool = True
    config: Optional[dict] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


# =============================================================================
# TENANT ENDPOINTS
# =============================================================================

@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_platform_admin)
):
    """
    List all tenants.

    Requires: X-Platform-Admin: true
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Set platform admin context to bypass RLS
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )
            await cur.execute(
                """
                SELECT id, tenant_code, name, is_active, metadata, created_at, updated_at
                FROM core.tenants
                ORDER BY tenant_code
                """
            )
            rows = await cur.fetchall()

            return TenantListResponse(
                tenants=[TenantResponse(**row) for row in rows],
                total=len(rows)
            )


@router.post("/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(
    request: CreateTenantRequest,
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_platform_admin)
):
    """
    Create a new tenant.

    Requires: X-Platform-Admin: true
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            # Set platform admin context
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Check if tenant_code already exists
            await cur.execute(
                "SELECT id FROM core.tenants WHERE tenant_code = %s",
                (request.tenant_code,)
            )
            if await cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant code '{request.tenant_code}' already exists"
                )

            # Create tenant
            await cur.execute(
                """
                INSERT INTO core.tenants (tenant_code, name, metadata)
                VALUES (%s, %s, %s)
                RETURNING id, tenant_code, name, is_active, metadata, created_at, updated_at
                """,
                (request.tenant_code, request.name, request.metadata or {})
            )
            row = await cur.fetchone()
            return TenantResponse(**row)


@router.get("/tenants/{tenant_code}", response_model=TenantResponse)
async def get_tenant(
    tenant_code: str,
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_platform_admin)
):
    """
    Get tenant by code.

    Requires: X-Platform-Admin: true
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )
            await cur.execute(
                """
                SELECT id, tenant_code, name, is_active, metadata, created_at, updated_at
                FROM core.tenants
                WHERE tenant_code = %s
                """,
                (tenant_code,)
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_code}' not found"
                )
            return TenantResponse(**row)


# =============================================================================
# SITE ENDPOINTS
# =============================================================================

@router.get("/tenants/{tenant_code}/sites", response_model=SiteListResponse)
async def list_sites_for_tenant(
    tenant_code: str,
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_platform_admin)
):
    """
    List all sites for a tenant.

    Requires: X-Platform-Admin: true
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Get tenant
            await cur.execute(
                "SELECT id FROM core.tenants WHERE tenant_code = %s",
                (tenant_code,)
            )
            tenant = await cur.fetchone()
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_code}' not found"
                )

            # Get sites
            await cur.execute(
                """
                SELECT id, tenant_id, site_code, name, timezone, is_active,
                       metadata, created_at, updated_at
                FROM core.sites
                WHERE tenant_id = %s
                ORDER BY site_code
                """,
                (tenant["id"],)
            )
            rows = await cur.fetchall()

            return SiteListResponse(
                sites=[SiteResponse(**row) for row in rows],
                total=len(rows)
            )


@router.post("/tenants/{tenant_code}/sites", response_model=SiteResponse, status_code=201)
async def create_site(
    tenant_code: str,
    request: CreateSiteRequest,
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_platform_admin)
):
    """
    Create a new site for a tenant.

    Requires: X-Platform-Admin: true
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Get tenant
            await cur.execute(
                "SELECT id FROM core.tenants WHERE tenant_code = %s",
                (tenant_code,)
            )
            tenant = await cur.fetchone()
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_code}' not found"
                )

            # Check if site_code already exists for tenant
            await cur.execute(
                "SELECT id FROM core.sites WHERE tenant_id = %s AND site_code = %s",
                (tenant["id"], request.site_code)
            )
            if await cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Site code '{request.site_code}' already exists for tenant"
                )

            # Create site
            await cur.execute(
                """
                INSERT INTO core.sites (tenant_id, site_code, name, timezone, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, tenant_id, site_code, name, timezone, is_active,
                          metadata, created_at, updated_at
                """,
                (tenant["id"], request.site_code, request.name, request.timezone, request.metadata or {})
            )
            row = await cur.fetchone()
            return SiteResponse(**row)


# =============================================================================
# ENTITLEMENT ENDPOINTS
# =============================================================================

@router.get("/tenants/{tenant_code}/entitlements", response_model=EntitlementListResponse)
async def list_entitlements_for_tenant(
    tenant_code: str,
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_platform_admin)
):
    """
    List all entitlements for a tenant.

    Requires: X-Platform-Admin: true
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Get tenant
            await cur.execute(
                "SELECT id FROM core.tenants WHERE tenant_code = %s",
                (tenant_code,)
            )
            tenant = await cur.fetchone()
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_code}' not found"
                )

            # Get entitlements
            await cur.execute(
                """
                SELECT id, tenant_id, pack_id, is_enabled, config,
                       valid_from, valid_until, created_at, updated_at
                FROM core.tenant_entitlements
                WHERE tenant_id = %s
                ORDER BY pack_id
                """,
                (tenant["id"],)
            )
            rows = await cur.fetchall()

            return EntitlementListResponse(
                entitlements=[EntitlementResponse(**row) for row in rows],
                total=len(rows)
            )


@router.put("/tenants/{tenant_code}/entitlements/{pack_id}", response_model=EntitlementResponse)
async def set_entitlement(
    tenant_code: str,
    pack_id: str,
    request: SetEntitlementRequest,
    db: DatabaseManager = Depends(get_db),
    _: None = Depends(require_platform_admin)
):
    """
    Set or update entitlement for a tenant.

    Requires: X-Platform-Admin: true
    """
    if pack_id != request.pack_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pack_id in URL must match pack_id in request body"
        )

    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Get tenant
            await cur.execute(
                "SELECT id FROM core.tenants WHERE tenant_code = %s",
                (tenant_code,)
            )
            tenant = await cur.fetchone()
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_code}' not found"
                )

            # Upsert entitlement
            await cur.execute(
                """
                INSERT INTO core.tenant_entitlements
                    (tenant_id, pack_id, is_enabled, config, valid_from, valid_until)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, pack_id) DO UPDATE SET
                    is_enabled = EXCLUDED.is_enabled,
                    config = EXCLUDED.config,
                    valid_from = EXCLUDED.valid_from,
                    valid_until = EXCLUDED.valid_until,
                    updated_at = NOW()
                RETURNING id, tenant_id, pack_id, is_enabled, config,
                          valid_from, valid_until, created_at, updated_at
                """,
                (
                    tenant["id"],
                    request.pack_id,
                    request.is_enabled,
                    request.config or {},
                    request.valid_from,
                    request.valid_until
                )
            )
            row = await cur.fetchone()
            return EntitlementResponse(**row)
