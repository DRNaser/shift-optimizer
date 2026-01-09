"""
SOLVEREIGN V3.3b API - Routers
==============================

API endpoint routers:
- health: Health check endpoints
- tenants: Tenant management (legacy, integer ID)
- core_tenant: Core tenant self-service (UUID-based, X-Tenant-Code)
- platform: Platform admin operations (X-Platform-Admin)
- platform_orgs: Organization/customer management (platform admin)
- service_status: Service health and escalation management
- dispatcher_platform: Dispatcher cockpit endpoints (platform session auth)
- forecasts: Forecast ingest and status
- plans: Solve, audit, lock, export
- simulations: What-If scenarios
- runs: Async optimization with SSE streaming
- repair: Driver absence handling
- config: Configuration schema and validation
"""

from . import health
from . import tenants
from . import core_tenant
from . import platform
from . import platform_orgs
from . import service_status
from . import dispatcher_platform
from . import forecasts
from . import plans
from . import simulations
from . import runs
from . import repair
from . import config

__all__ = [
    "health",
    "tenants",
    "core_tenant",
    "platform",
    "platform_orgs",
    "service_status",
    "dispatcher_platform",
    "forecasts",
    "plans",
    "simulations",
    "runs",
    "repair",
    "config",
]
