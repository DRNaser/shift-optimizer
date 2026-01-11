"""
Roster Pack Routers

MIGRATION NOTE:
During the migration period, this module wraps existing kernel routers.
After migration is complete, the router files will live here directly.

Current State (Phase 1 - Wrapper):
- Imports from kernel routers (api/routers/forecasts.py, plans.py, etc.)
- Re-exports under roster pack namespace
- Adds pack entitlement checks

Target State (Phase 3 - Complete):
- Router files moved to this directory
- Direct implementations with pack-specific dependencies
- Kernel routers removed

See ADR-001: Kernel vs Pack Boundary for migration details.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

# Create the roster pack router
router = APIRouter(tags=["roster"])

# Import kernel routers (TEMPORARY - will be moved here in Phase 2)
# Using absolute imports for Docker compatibility (PYTHONPATH=/app)
_kernel_import_error = None
try:
    from api.routers.forecasts import router as forecasts_router
    from api.routers.plans import router as plans_router
    # Note: simulations, repair, config will be added as they're migrated
    _kernel_routers_available = True
except ImportError as e:
    _kernel_routers_available = False
    _kernel_import_error = f"{type(e).__name__}: {e}"


def require_roster_entitlement():
    """
    Dependency to verify tenant has roster pack enabled.

    TEMPORARY: For migration, we allow access if kernel routers are used directly.
    FUTURE: Will integrate with PolicyService to check entitlements.
    """
    async def _check_entitlement():
        # TODO: Integrate with PolicyService
        # For now, allow all requests during migration
        return True
    return Depends(_check_entitlement)


# Include sub-routers with roster pack prefix
if _kernel_routers_available:
    # Phase 1: Wrap kernel routers
    router.include_router(
        forecasts_router,
        prefix="/forecasts",
        dependencies=[require_roster_entitlement()]
    )
    router.include_router(
        plans_router,
        prefix="/plans",
        dependencies=[require_roster_entitlement()]
    )

# Include Dispatch Assist router (Gurkerl MVP)
# Using absolute import for Docker compatibility
_dispatch_import_error = None
try:
    from packs.roster.api.dispatch import router as dispatch_router
    router.include_router(
        dispatch_router,
        dependencies=[require_roster_entitlement()]
    )
    _dispatch_available = True
except ImportError as e:
    _dispatch_available = False
    _dispatch_import_error = f"{type(e).__name__}: {e}"

# Include Lifecycle router (Plans, Snapshots)
_lifecycle_import_error = None
try:
    from packs.roster.api.routers.lifecycle import router as lifecycle_router
    router.include_router(lifecycle_router)
    _lifecycle_available = True
except ImportError as e:
    _lifecycle_available = False
    _lifecycle_import_error = f"{type(e).__name__}: {e}"

# Include Repair router (Preview + Commit)
_repair_import_error = None
try:
    from packs.roster.api.routers.repair import router as repair_router
    router.include_router(repair_router)
    _repair_available = True
except ImportError as e:
    _repair_available = False
    _repair_import_error = f"{type(e).__name__}: {e}"


# Health check for roster pack
@router.get("/health", summary="Roster Pack Health")
async def roster_health():
    """Check roster pack availability."""
    # Determine overall status
    status = "healthy" if _kernel_routers_available else "degraded"

    response = {
        "pack": "roster",
        "status": status,
        "version": "1.2.0",  # V1.2 = Repair MVP
        "kernel_routers_available": _kernel_routers_available,
        "dispatch_assist_available": _dispatch_available,
        "lifecycle_available": _lifecycle_available,
        "repair_available": _repair_available,
        "migration_phase": 1  # 1=wrapper, 2=moving, 3=complete
    }

    # Add error reasons if components failed to load
    if not _kernel_routers_available and _kernel_import_error:
        response["kernel_error"] = _kernel_import_error
    if not _dispatch_available and _dispatch_import_error:
        response["dispatch_error"] = _dispatch_import_error
    if not _lifecycle_available and _lifecycle_import_error:
        response["lifecycle_error"] = _lifecycle_import_error
    if not _repair_available and _repair_import_error:
        response["repair_error"] = _repair_import_error

    return response


# Pack info endpoint
@router.get("/info", summary="Roster Pack Info")
async def roster_info():
    """Get roster pack information."""
    return {
        "pack_id": "roster",
        "name": "Roster Pack",
        "description": "Weekly shift/roster scheduling for logistics drivers",
        "version": "1.0.0",
        "constraints": {
            "german_labor_law": True,
            "max_weekly_hours": 55,
            "min_rest_hours": 11,
            "max_span_regular": 14,
            "max_span_split": 16
        },
        "solver": {
            "type": "block_heuristic",
            "lp_backend": "highs"
        }
    }
