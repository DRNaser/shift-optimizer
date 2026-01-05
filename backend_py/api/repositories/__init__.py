"""
SOLVEREIGN V3.3a API - Repositories
===================================

Tenant-scoped data access layer.

All repositories:
- Automatically filter by tenant_id
- Handle database transactions
- Return typed results
"""

from .forecasts import ForecastRepository
from .plans import PlanRepository
from .tenants import TenantRepository

__all__ = [
    "ForecastRepository",
    "PlanRepository",
    "TenantRepository",
]
