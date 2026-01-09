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
# These imports work because we're in the same package structure
try:
    from ....api.routers.forecasts import router as forecasts_router
    from ....api.routers.plans import router as plans_router
    # Note: simulations, repair, config will be added as they're migrated
    _kernel_routers_available = True
except ImportError:
    _kernel_routers_available = False


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


# Health check for roster pack
@router.get("/health", summary="Roster Pack Health")
async def roster_health():
    """Check roster pack availability."""
    return {
        "pack": "roster",
        "status": "healthy",
        "version": "1.0.0",
        "kernel_routers_available": _kernel_routers_available,
        "migration_phase": 1  # 1=wrapper, 2=moving, 3=complete
    }


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
