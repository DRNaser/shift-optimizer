"""
SOLVEREIGN V4.6 API - Routers
==============================

API endpoint routers:
- health: Health check endpoints
- tenants: Tenant management (legacy, integer ID)
- core_tenant: Core tenant self-service (UUID-based, X-Tenant-Code)
- platform: Platform admin operations (X-Platform-Admin)
- platform_orgs: Organization/customer management (platform admin)
- platform_admin: Platform administration API (V4.5 SaaS Admin Core)
- service_status: Service health and escalation management
- dispatcher_platform: Dispatcher cockpit endpoints (platform session auth)
- forecasts: Forecast ingest and status
- plans: Solve, audit, lock, export
- simulations: What-If scenarios
- runs: Async optimization with SSE streaming
- repair: Driver absence handling
- config: Configuration schema and validation
- policies: Policy profile management
- masterdata: Master data layer
- auth: Internal authentication (V4.5)
- portal_admin: Portal admin endpoints
- portal_public: Portal public endpoints
- notifications: Notification pipeline
- consent: GDPR consent management (P2.3)
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
from . import policies
from . import masterdata
from . import auth
from . import portal_admin
from . import portal_public
from . import notifications
from . import platform_admin
from . import tenant_dashboard
from . import evidence_viewer
from . import audit_viewer
from . import consent

__all__ = [
    "health",
    "tenants",
    "core_tenant",
    "platform",
    "platform_orgs",
    "platform_admin",
    "service_status",
    "dispatcher_platform",
    "forecasts",
    "plans",
    "simulations",
    "runs",
    "repair",
    "config",
    "policies",
    "masterdata",
    "auth",
    "portal_admin",
    "portal_public",
    "notifications",
    "tenant_dashboard",
    "evidence_viewer",
    "audit_viewer",
    "consent",
]
