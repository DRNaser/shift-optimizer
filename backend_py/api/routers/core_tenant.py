"""
SOLVEREIGN Core Tenant API - Self-Service Operations
=====================================================

Tenant self-service endpoints using core.tenants (UUID-based).
Requires X-Tenant-Code header (injected by BFF).
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..dependencies import get_db, get_core_tenant, CoreTenantContext
from ..database import DatabaseManager, get_core_sites_for_tenant, get_core_entitlements_for_tenant

router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class TenantMeResponse(BaseModel):
    """Current tenant information (self-service)."""
    tenant_id: str
    tenant_code: str
    name: str
    current_site: Optional[dict] = None
    entitlements: dict
    metadata: Optional[dict] = None


class SiteResponse(BaseModel):
    """Site information."""
    id: str
    site_code: str
    name: str
    timezone: str
    is_active: bool
    metadata: Optional[dict] = None


class SiteListResponse(BaseModel):
    """List of sites for tenant."""
    sites: List[SiteResponse]
    total: int


class EntitlementSummary(BaseModel):
    """Entitlement summary."""
    pack_id: str
    is_enabled: bool
    config: Optional[dict] = None


class EntitlementListResponse(BaseModel):
    """List of entitlements for tenant."""
    entitlements: List[EntitlementSummary]
    total: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/me", response_model=TenantMeResponse)
async def get_current_tenant_info(
    tenant: CoreTenantContext = Depends(get_core_tenant)
):
    """
    Get current tenant information.

    Returns tenant details based on X-Tenant-Code header.
    Includes current site info if X-Site-Code was provided.
    """
    current_site = None
    if tenant.site_id:
        current_site = {
            "id": tenant.site_id,
            "site_code": tenant.site_code,
            "timezone": tenant.site_timezone
        }

    return TenantMeResponse(
        tenant_id=tenant.tenant_id,
        tenant_code=tenant.tenant_code,
        name=tenant.tenant_name,
        current_site=current_site,
        entitlements=tenant.entitlements or {},
        metadata=tenant.metadata,
    )


@router.get("/me/sites", response_model=SiteListResponse)
async def list_my_sites(
    tenant: CoreTenantContext = Depends(get_core_tenant),
    db: DatabaseManager = Depends(get_db)
):
    """
    List all sites for current tenant.

    Returns all active sites belonging to the authenticated tenant.
    """
    sites = await get_core_sites_for_tenant(db, tenant.tenant_id)

    return SiteListResponse(
        sites=[
            SiteResponse(
                id=str(site["id"]),
                site_code=site["site_code"],
                name=site["name"],
                timezone=site["timezone"],
                is_active=site["is_active"],
                metadata=site.get("metadata")
            )
            for site in sites
        ],
        total=len(sites)
    )


@router.get("/me/sites/{site_code}", response_model=SiteResponse)
async def get_my_site(
    site_code: str,
    tenant: CoreTenantContext = Depends(get_core_tenant),
    db: DatabaseManager = Depends(get_db)
):
    """
    Get a specific site for current tenant.
    """
    from ..database import get_core_site_by_code

    site = await get_core_site_by_code(db, tenant.tenant_id, site_code)
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Site '{site_code}' not found"
        )

    return SiteResponse(
        id=str(site["id"]),
        site_code=site["site_code"],
        name=site["name"],
        timezone=site["timezone"],
        is_active=site["is_active"],
        metadata=site.get("metadata")
    )


@router.get("/me/entitlements", response_model=EntitlementListResponse)
async def list_my_entitlements(
    tenant: CoreTenantContext = Depends(get_core_tenant),
    db: DatabaseManager = Depends(get_db)
):
    """
    List all entitlements for current tenant.

    Returns all pack entitlements and their status.
    """
    entitlements = await get_core_entitlements_for_tenant(db, tenant.tenant_id)

    return EntitlementListResponse(
        entitlements=[
            EntitlementSummary(
                pack_id=e["pack_id"],
                is_enabled=e["is_enabled"],
                config=e.get("config")
            )
            for e in entitlements
        ],
        total=len(entitlements)
    )


@router.get("/me/entitlements/{pack_id}")
async def check_my_entitlement(
    pack_id: str,
    tenant: CoreTenantContext = Depends(get_core_tenant)
):
    """
    Check if current tenant has entitlement for a specific pack.

    Returns:
    - is_enabled: bool
    - config: pack-specific configuration
    """
    if not tenant.entitlements:
        return {
            "pack_id": pack_id,
            "is_enabled": False,
            "config": None
        }

    entitlement = tenant.entitlements.get(pack_id, {})
    return {
        "pack_id": pack_id,
        "is_enabled": entitlement.get("is_enabled", False),
        "config": entitlement.get("config")
    }
