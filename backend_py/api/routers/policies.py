"""
Policy Profiles Router (Kernel)

Manages policy profiles for tenant pack configuration.
See ADR-002: Policy Profiles for architecture details.

Endpoints:
- GET  /policies           - List profiles for current tenant
- POST /policies           - Create new profile (draft)
- GET  /policies/{id}      - Get profile details
- PUT  /policies/{id}      - Update profile config
- POST /policies/{id}/activate - Activate a profile
- POST /policies/{id}/archive  - Archive a profile
- GET  /policies/active    - Get active policy for a pack
- PUT  /policies/active    - Set active profile for a pack
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..dependencies import get_core_tenant, CoreTenantContext
from ..services.policy_service import (
    PolicyService, get_policy_service,
    ActivePolicy, PolicyNotFound, PolicyProfile, PolicyStatus
)

# Alias for consistency - policies use UUID-based core tenants
get_tenant_context = get_core_tenant
TenantContext = CoreTenantContext

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class CreateProfileRequest(BaseModel):
    """Request to create a new policy profile."""
    pack_id: str = Field(..., description="Pack identifier (roster, routing)")
    name: str = Field(..., min_length=1, max_length=100, description="Profile name")
    description: Optional[str] = Field(None, max_length=500)
    config: Dict[str, Any] = Field(..., description="Configuration JSON")
    schema_version: str = Field("1.0", description="Config schema version")


class UpdateProfileRequest(BaseModel):
    """Request to update a profile's configuration."""
    config: Dict[str, Any] = Field(..., description="New configuration JSON")
    description: Optional[str] = Field(None, max_length=500)


class SetActiveProfileRequest(BaseModel):
    """Request to set the active profile for a pack."""
    pack_id: str = Field(..., description="Pack identifier")
    profile_id: Optional[str] = Field(None, description="Profile ID (None = use defaults)")


class ProfileResponse(BaseModel):
    """Policy profile response."""
    id: str
    tenant_id: str
    pack_id: str
    name: str
    description: Optional[str]
    version: int
    status: str
    config: Dict[str, Any]
    config_hash: str
    schema_version: str
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


class ActivePolicyResponse(BaseModel):
    """Active policy response."""
    profile_id: Optional[str]
    config: Optional[Dict[str, Any]]
    config_hash: Optional[str]
    schema_version: Optional[str]
    using_defaults: bool


class ProfileListResponse(BaseModel):
    """List of profiles response."""
    profiles: List[ProfileResponse]
    total: int


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def profile_to_response(profile: PolicyProfile) -> ProfileResponse:
    """Convert PolicyProfile to response model."""
    return ProfileResponse(
        id=profile.id,
        tenant_id=profile.tenant_id,
        pack_id=profile.pack_id,
        name=profile.name,
        description=profile.description,
        version=profile.version,
        status=profile.status.value,
        config=profile.config_json,
        config_hash=profile.config_hash,
        schema_version=profile.schema_version,
        created_at=profile.created_at,
        created_by=profile.created_by,
        updated_at=profile.updated_at,
        updated_by=profile.updated_by,
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("", response_model=ProfileListResponse, summary="List Policy Profiles")
async def list_profiles(
    pack_id: Optional[str] = Query(None, description="Filter by pack"),
    status: Optional[str] = Query(None, description="Filter by status"),
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """
    List policy profiles for the current tenant.

    Optionally filter by pack_id and/or status.
    """
    status_enum = PolicyStatus(status) if status else None
    profiles = await policy_service.list_profiles(
        tenant_id=str(tenant.tenant_id),
        pack_id=pack_id,
        status=status_enum,
    )
    return ProfileListResponse(
        profiles=[profile_to_response(p) for p in profiles],
        total=len(profiles),
    )


@router.post("", response_model=ProfileResponse, status_code=201, summary="Create Policy Profile")
async def create_profile(
    request: CreateProfileRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """
    Create a new policy profile (draft status).

    The profile must be activated before it can be used.
    Configuration is validated against the pack's schema.
    """
    try:
        profile_id = await policy_service.create_profile(
            tenant_id=str(tenant.tenant_id),
            pack_id=request.pack_id,
            name=request.name,
            config=request.config,
            created_by=tenant.tenant_name or "unknown",
            description=request.description,
            schema_version=request.schema_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Fetch and return the created profile
    profiles = await policy_service.list_profiles(
        tenant_id=str(tenant.tenant_id),
        pack_id=request.pack_id,
    )
    profile = next((p for p in profiles if p.id == profile_id), None)
    if not profile:
        raise HTTPException(status_code=500, detail="Profile created but not found")

    return profile_to_response(profile)


@router.get("/active", response_model=ActivePolicyResponse, summary="Get Active Policy")
async def get_active_policy(
    pack_id: str = Query(..., description="Pack identifier"),
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """
    Get the active policy configuration for a pack.

    Returns the config and hash that will be used for new runs.
    If no profile is configured, returns using_defaults=true.
    """
    result = await policy_service.get_active_policy(
        tenant_id=str(tenant.tenant_id),
        pack_id=pack_id,
    )

    if isinstance(result, PolicyNotFound):
        return ActivePolicyResponse(
            profile_id=None,
            config=None,
            config_hash=None,
            schema_version=None,
            using_defaults=True,
        )

    return ActivePolicyResponse(
        profile_id=result.profile_id,
        config=result.config,
        config_hash=result.config_hash,
        schema_version=result.schema_version,
        using_defaults=False,
    )


@router.put("/active", summary="Set Active Profile")
async def set_active_profile(
    request: SetActiveProfileRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """
    Set the active profile for a pack.

    Pass profile_id=null to reset to pack defaults.
    """
    await policy_service.set_active_profile(
        tenant_id=str(tenant.tenant_id),
        pack_id=request.pack_id,
        profile_id=request.profile_id,
        updated_by=tenant.tenant_name or "unknown",
    )
    return {"status": "updated", "pack_id": request.pack_id, "profile_id": request.profile_id}


@router.get("/{profile_id}", response_model=ProfileResponse, summary="Get Policy Profile")
async def get_profile(
    profile_id: str,
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """Get a specific policy profile by ID."""
    profiles = await policy_service.list_profiles(tenant_id=str(tenant.tenant_id))
    profile = next((p for p in profiles if p.id == profile_id), None)

    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")

    return profile_to_response(profile)


@router.put("/{profile_id}", response_model=ProfileResponse, summary="Update Policy Profile")
async def update_profile(
    profile_id: str,
    request: UpdateProfileRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """
    Update a profile's configuration.

    Only draft profiles can be updated. Active profiles must be
    archived first, then a new version created.
    """
    try:
        await policy_service.update_profile(
            profile_id=profile_id,
            config=request.config,
            updated_by=tenant.tenant_name or "unknown",
            description=request.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Return updated profile
    profiles = await policy_service.list_profiles(tenant_id=str(tenant.tenant_id))
    profile = next((p for p in profiles if p.id == profile_id), None)

    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")

    return profile_to_response(profile)


@router.post("/{profile_id}/activate", summary="Activate Policy Profile")
async def activate_profile(
    profile_id: str,
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """
    Activate a policy profile.

    This archives any previously active profile with the same name.
    """
    await policy_service.activate_profile(
        profile_id=profile_id,
        activated_by=tenant.tenant_name or "unknown",
    )
    return {"status": "activated", "profile_id": profile_id}


@router.post("/{profile_id}/archive", summary="Archive Policy Profile")
async def archive_profile(
    profile_id: str,
    tenant: TenantContext = Depends(get_tenant_context),
    policy_service: PolicyService = Depends(get_policy_service),
):
    """Archive a policy profile."""
    await policy_service.archive_profile(
        profile_id=profile_id,
        archived_by=tenant.tenant_name or "unknown",
    )
    return {"status": "archived", "profile_id": profile_id}
