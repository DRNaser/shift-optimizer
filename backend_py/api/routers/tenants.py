"""
SOLVEREIGN V3.3a API - Tenants Router
=====================================

Tenant management endpoints (internal/admin only).
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..dependencies import get_db, get_current_tenant, TenantContext
from ..database import DatabaseManager


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class TenantResponse(BaseModel):
    """Tenant information response."""
    id: int
    name: str
    is_active: bool
    created_at: datetime
    metadata: Optional[dict] = None


class TenantStatsResponse(BaseModel):
    """Tenant statistics response."""
    tenant_id: int
    tenant_name: str
    forecasts_count: int
    plans_count: int
    locked_plans_count: int
    last_forecast_at: Optional[datetime] = None
    last_solve_at: Optional[datetime] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/me", response_model=TenantResponse)
async def get_current_tenant_info(
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Get current tenant information.

    Returns tenant details based on the API key used.
    """
    return TenantResponse(
        id=tenant.tenant_id,
        name=tenant.tenant_name,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        metadata=tenant.metadata,
    )


@router.get("/me/stats", response_model=TenantStatsResponse)
async def get_tenant_stats(
    tenant: TenantContext = Depends(get_current_tenant),
    db: DatabaseManager = Depends(get_db)
):
    """
    Get tenant usage statistics.

    Includes:
    - Total forecasts and plans
    - Locked plans count
    - Last activity timestamps
    """
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            # Get counts
            await cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM forecast_versions WHERE tenant_id = %s) as forecasts,
                    (SELECT COUNT(*) FROM plan_versions WHERE tenant_id = %s) as plans,
                    (SELECT COUNT(*) FROM plan_versions WHERE tenant_id = %s AND status = 'LOCKED') as locked,
                    (SELECT MAX(created_at) FROM forecast_versions WHERE tenant_id = %s) as last_forecast,
                    (SELECT MAX(completed_at) FROM plan_versions WHERE tenant_id = %s AND status IN ('SOLVED', 'DRAFT', 'LOCKED')) as last_solve
                """,
                (tenant.tenant_id, tenant.tenant_id, tenant.tenant_id, tenant.tenant_id, tenant.tenant_id)
            )
            row = await cur.fetchone()

            return TenantStatsResponse(
                tenant_id=tenant.tenant_id,
                tenant_name=tenant.tenant_name,
                forecasts_count=row["forecasts"] or 0,
                plans_count=row["plans"] or 0,
                locked_plans_count=row["locked"] or 0,
                last_forecast_at=row["last_forecast"],
                last_solve_at=row["last_solve"],
            )
