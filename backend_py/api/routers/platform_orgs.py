"""
SOLVEREIGN Platform API - Organization Management
===================================================

Platform-level endpoints for managing organizations (customers) and their tenants.
Requires verified internal signature with platform admin flag.

Endpoints:
- GET /api/v1/platform/orgs - List all organizations
- POST /api/v1/platform/orgs - Create organization
- GET /api/v1/platform/orgs/{org_code} - Get organization details
- GET /api/v1/platform/orgs/{org_code}/tenants - List tenants in organization
- POST /api/v1/platform/orgs/{org_code}/tenants - Create tenant in organization
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..dependencies import get_db
from ..database import DatabaseManager
from ..security.internal_signature import (
    require_platform_admin,
    InternalContext
)

router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class OrganizationResponse(BaseModel):
    """Organization details."""
    id: str
    org_code: str
    name: str
    is_active: bool
    tenant_count: int
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class OrganizationListResponse(BaseModel):
    """List of organizations."""
    organizations: List[OrganizationResponse]
    total: int


class CreateOrganizationRequest(BaseModel):
    """Request to create a new organization."""
    org_code: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    name: str = Field(..., min_length=1, max_length=255)
    metadata: Optional[dict] = None


class TenantInOrgResponse(BaseModel):
    """Tenant belonging to an organization."""
    id: str
    tenant_code: str
    name: str
    is_active: bool
    site_count: int
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class TenantListInOrgResponse(BaseModel):
    """List of tenants in an organization."""
    org_code: str
    org_name: str
    tenants: List[TenantInOrgResponse]
    total: int


class CreateTenantInOrgRequest(BaseModel):
    """Request to create a tenant within an organization."""
    tenant_code: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    name: str = Field(..., min_length=1, max_length=255)
    metadata: Optional[dict] = None
    # Optional: Auto-enable core pack
    enable_core: bool = True
    # Optional: Enable routing pack
    enable_routing: bool = False
    routing_config: Optional[dict] = None


class SiteInOrgResponse(BaseModel):
    """Site within a tenant."""
    id: str
    site_code: str
    name: str
    timezone: str
    is_active: bool


class CreateSiteRequest(BaseModel):
    """Request to create a site for a tenant."""
    site_code: str = Field(..., min_length=2, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    name: str = Field(..., min_length=1, max_length=255)
    timezone: str = Field(default="Europe/Berlin", max_length=50)
    metadata: Optional[dict] = None


# =============================================================================
# ORGANIZATION ENDPOINTS
# =============================================================================

@router.get("/orgs", response_model=OrganizationListResponse)
async def list_organizations(
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    List all organizations.

    Requires: Platform admin (verified internal signature)
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Set platform admin context
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            await cur.execute("""
                SELECT
                    o.id, o.org_code, o.name, o.is_active, o.metadata,
                    o.created_at, o.updated_at,
                    COALESCE(core.get_org_tenant_count(o.id), 0) as tenant_count
                FROM core.organizations o
                ORDER BY o.org_code
            """)
            rows = await cur.fetchall()

            organizations = [
                OrganizationResponse(
                    id=str(row["id"]),
                    org_code=row["org_code"],
                    name=row["name"],
                    is_active=row["is_active"],
                    tenant_count=row["tenant_count"],
                    metadata=row.get("metadata"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]

            return OrganizationListResponse(
                organizations=organizations,
                total=len(organizations)
            )


@router.post("/orgs", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    request: CreateOrganizationRequest,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Create a new organization (customer).

    Requires: Platform admin (verified internal signature)
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            # Set platform admin context
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Check if org_code already exists
            await cur.execute(
                "SELECT id FROM core.organizations WHERE org_code = %s",
                (request.org_code,)
            )
            if await cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Organization code '{request.org_code}' already exists"
                )

            # Create organization
            await cur.execute("""
                INSERT INTO core.organizations (org_code, name, metadata)
                VALUES (%s, %s, %s)
                RETURNING id, org_code, name, is_active, metadata, created_at, updated_at
            """, (request.org_code, request.name, request.metadata or {}))

            row = await cur.fetchone()
            return OrganizationResponse(
                id=str(row["id"]),
                org_code=row["org_code"],
                name=row["name"],
                is_active=row["is_active"],
                tenant_count=0,
                metadata=row.get("metadata"),
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )


@router.get("/orgs/{org_code}", response_model=OrganizationResponse)
async def get_organization(
    org_code: str,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Get organization by code.

    Requires: Platform admin (verified internal signature)
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            await cur.execute("""
                SELECT
                    o.id, o.org_code, o.name, o.is_active, o.metadata,
                    o.created_at, o.updated_at,
                    COALESCE(core.get_org_tenant_count(o.id), 0) as tenant_count
                FROM core.organizations o
                WHERE o.org_code = %s
            """, (org_code,))

            row = await cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Organization '{org_code}' not found"
                )

            return OrganizationResponse(
                id=str(row["id"]),
                org_code=row["org_code"],
                name=row["name"],
                is_active=row["is_active"],
                tenant_count=row["tenant_count"],
                metadata=row.get("metadata"),
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )


# =============================================================================
# TENANTS IN ORGANIZATION ENDPOINTS
# =============================================================================

@router.get("/orgs/{org_code}/tenants", response_model=TenantListInOrgResponse)
async def list_tenants_in_org(
    org_code: str,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    List all tenants in an organization.

    Requires: Platform admin (verified internal signature)
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Get organization
            await cur.execute(
                "SELECT id, name FROM core.organizations WHERE org_code = %s",
                (org_code,)
            )
            org = await cur.fetchone()
            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Organization '{org_code}' not found"
                )

            # Get tenants with site count
            await cur.execute("""
                SELECT
                    t.id, t.tenant_code, t.name, t.is_active, t.metadata,
                    t.created_at, t.updated_at,
                    (SELECT COUNT(*) FROM core.sites s WHERE s.tenant_id = t.id) as site_count
                FROM core.tenants t
                WHERE t.owner_org_id = %s
                ORDER BY t.tenant_code
            """, (org["id"],))

            rows = await cur.fetchall()

            tenants = [
                TenantInOrgResponse(
                    id=str(row["id"]),
                    tenant_code=row["tenant_code"],
                    name=row["name"],
                    is_active=row["is_active"],
                    site_count=row["site_count"],
                    metadata=row.get("metadata"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]

            return TenantListInOrgResponse(
                org_code=org_code,
                org_name=org["name"],
                tenants=tenants,
                total=len(tenants)
            )


@router.post("/orgs/{org_code}/tenants", response_model=TenantInOrgResponse, status_code=201)
async def create_tenant_in_org(
    org_code: str,
    request: CreateTenantInOrgRequest,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Create a new tenant within an organization.

    Automatically enables 'core' pack (can be disabled via enable_core=False).
    Optionally enables 'routing' pack.

    Requires: Platform admin (verified internal signature)
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Get organization
            await cur.execute(
                "SELECT id FROM core.organizations WHERE org_code = %s",
                (org_code,)
            )
            org = await cur.fetchone()
            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Organization '{org_code}' not found"
                )

            # Check if tenant_code already exists globally
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
            await cur.execute("""
                INSERT INTO core.tenants (tenant_code, name, owner_org_id, metadata)
                VALUES (%s, %s, %s, %s)
                RETURNING id, tenant_code, name, is_active, metadata, created_at, updated_at
            """, (request.tenant_code, request.name, org["id"], request.metadata or {}))

            tenant_row = await cur.fetchone()
            tenant_id = tenant_row["id"]

            # Enable core pack by default
            if request.enable_core:
                await cur.execute("""
                    INSERT INTO core.tenant_entitlements (tenant_id, pack_id, is_enabled, config)
                    VALUES (%s, 'core', TRUE, '{}')
                """, (tenant_id,))

            # Enable routing pack if requested
            if request.enable_routing:
                await cur.execute("""
                    INSERT INTO core.tenant_entitlements (tenant_id, pack_id, is_enabled, config)
                    VALUES (%s, 'routing', TRUE, %s)
                """, (tenant_id, request.routing_config or {}))

            return TenantInOrgResponse(
                id=str(tenant_row["id"]),
                tenant_code=tenant_row["tenant_code"],
                name=tenant_row["name"],
                is_active=tenant_row["is_active"],
                site_count=0,
                metadata=tenant_row.get("metadata"),
                created_at=tenant_row["created_at"],
                updated_at=tenant_row["updated_at"]
            )


# =============================================================================
# SITE MANAGEMENT (Convenience endpoints under org/tenant)
# =============================================================================

@router.get("/orgs/{org_code}/tenants/{tenant_code}/sites")
async def list_sites_in_tenant(
    org_code: str,
    tenant_code: str,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    List all sites for a tenant within an organization.

    Requires: Platform admin (verified internal signature)
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Verify org exists
            await cur.execute(
                "SELECT id FROM core.organizations WHERE org_code = %s",
                (org_code,)
            )
            org = await cur.fetchone()
            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Organization '{org_code}' not found"
                )

            # Verify tenant belongs to org
            await cur.execute("""
                SELECT id FROM core.tenants
                WHERE tenant_code = %s AND owner_org_id = %s
            """, (tenant_code, org["id"]))
            tenant = await cur.fetchone()
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_code}' not found in organization '{org_code}'"
                )

            # Get sites
            await cur.execute("""
                SELECT id, site_code, name, timezone, is_active
                FROM core.sites
                WHERE tenant_id = %s
                ORDER BY site_code
            """, (tenant["id"],))

            rows = await cur.fetchall()

            return {
                "org_code": org_code,
                "tenant_code": tenant_code,
                "sites": [
                    SiteInOrgResponse(
                        id=str(row["id"]),
                        site_code=row["site_code"],
                        name=row["name"],
                        timezone=row["timezone"],
                        is_active=row["is_active"]
                    )
                    for row in rows
                ],
                "total": len(rows)
            }


@router.post("/orgs/{org_code}/tenants/{tenant_code}/sites", status_code=201)
async def create_site_in_tenant(
    org_code: str,
    tenant_code: str,
    request: CreateSiteRequest,
    db: DatabaseManager = Depends(get_db),
    _: InternalContext = Depends(require_platform_admin)
):
    """
    Create a new site for a tenant within an organization.

    Requires: Platform admin (verified internal signature)
    """
    async with db.transaction() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT core.set_tenant_context(NULL, NULL, TRUE)"
            )

            # Verify org exists
            await cur.execute(
                "SELECT id FROM core.organizations WHERE org_code = %s",
                (org_code,)
            )
            org = await cur.fetchone()
            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Organization '{org_code}' not found"
                )

            # Verify tenant belongs to org
            await cur.execute("""
                SELECT id FROM core.tenants
                WHERE tenant_code = %s AND owner_org_id = %s
            """, (tenant_code, org["id"]))
            tenant = await cur.fetchone()
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_code}' not found in organization '{org_code}'"
                )

            # Check if site_code exists for tenant
            await cur.execute("""
                SELECT id FROM core.sites
                WHERE tenant_id = %s AND site_code = %s
            """, (tenant["id"], request.site_code))
            if await cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Site code '{request.site_code}' already exists for tenant"
                )

            # Create site
            await cur.execute("""
                INSERT INTO core.sites (tenant_id, site_code, name, timezone, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, site_code, name, timezone, is_active
            """, (tenant["id"], request.site_code, request.name, request.timezone, request.metadata or {}))

            row = await cur.fetchone()

            return SiteInOrgResponse(
                id=str(row["id"]),
                site_code=row["site_code"],
                name=row["name"],
                timezone=row["timezone"],
                is_active=row["is_active"]
            )
