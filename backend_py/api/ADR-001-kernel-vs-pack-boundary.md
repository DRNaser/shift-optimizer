# ADR-001: Kernel vs Pack Boundary

> **Status**: Accepted
> **Date**: 2026-01-07
> **Decision Makers**: Platform Team
> **Supersedes**: None

---

## Context

SOLVEREIGN is a multi-tenant platform with multiple domain packs (routing, roster, future packs). Currently, roster-specific routers (`forecasts.py`, `plans.py`, `simulations.py`, `repair.py`, `config.py`) live in the kernel namespace (`api/routers/`), violating the principle of clean pack boundaries.

This creates problems:
1. **SaaS Scaling**: Cannot deploy packs independently
2. **Code Clarity**: Unclear which code belongs to which domain
3. **Entitlement Enforcement**: Pack-specific routes not gated by pack entitlements
4. **Testing**: Cannot test roster pack in isolation

---

## Decision

**Kernel hosts ONLY platform-generic routers. Packs own their domain-specific routers.**

### Kernel Routers (Platform-Generic)

| Router | Prefix | Purpose |
|--------|--------|---------|
| health.py | `/health` | Readiness/liveness probes |
| tenants.py | `/api/v1/tenants` | Legacy tenant management |
| core_tenant.py | `/api/v1/tenant` | Modern tenant context |
| platform.py | `/api/v1/platform` | Platform admin operations |
| platform_orgs.py | `/api/v1/platform/orgs` | Organization management |
| service_status.py | `/api/v1/service-status` | Incident management |
| runs.py | `/api/v1/runs` | Generic job runner |
| evidence.py | `/api/v1/evidence` | Artifact access (NEW) |

### Pack Routers (Domain-Specific)

| Pack | Prefix | Routers |
|------|--------|---------|
| routing | `/api/v1/routing` | scenarios.py, routes.py, teams.py |
| roster | `/api/v1/roster` | forecasts.py, plans.py, simulations.py, repair.py, config.py |

---

## Implementation

### Directory Structure

```
backend_py/
├── api/                          # KERNEL
│   ├── routers/                  # Platform-generic only
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── tenants.py
│   │   ├── core_tenant.py
│   │   ├── platform.py
│   │   ├── platform_orgs.py
│   │   ├── service_status.py
│   │   ├── runs.py
│   │   └── evidence.py           # NEW
│   └── security/
└── packs/
    ├── routing/                  # ROUTING PACK
    │   └── api/routers/
    │       ├── scenarios.py
    │       ├── routes.py
    │       └── teams.py
    └── roster/                   # ROSTER PACK (NEW)
        ├── __init__.py
        └── api/
            ├── __init__.py
            └── routers/
                ├── __init__.py
                ├── forecasts.py  # Moved from kernel
                ├── plans.py      # Moved from kernel
                ├── simulations.py
                ├── repair.py
                └── config.py
```

### Router Registration (main.py)

```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="SOLVEREIGN API")

    # KERNEL routers (always registered)
    from .routers import (
        health, tenants, core_tenant, platform,
        platform_orgs, service_status, runs, evidence
    )
    app.include_router(health.router)
    app.include_router(tenants.router, prefix="/api/v1/tenants")
    app.include_router(core_tenant.router, prefix="/api/v1/tenant")
    app.include_router(platform.router, prefix="/api/v1/platform")
    app.include_router(platform_orgs.router, prefix="/api/v1/platform/orgs")
    app.include_router(service_status.router, prefix="/api/v1/service-status")
    app.include_router(runs.router, prefix="/api/v1/runs")
    app.include_router(evidence.router, prefix="/api/v1/evidence")

    # PACK routers (registered based on configuration)
    if config.ROUTING_PACK_ENABLED:
        from ..packs.routing.api.routers import router as routing_router
        app.include_router(routing_router, prefix="/api/v1/routing")

    if config.ROSTER_PACK_ENABLED:
        from ..packs.roster.api.routers import router as roster_router
        app.include_router(roster_router, prefix="/api/v1/roster")

    return app
```

### Entitlement Gating

Pack routers must verify tenant entitlements:

```python
# In packs/roster/api/routers/forecasts.py

from ....api.dependencies import require_pack_entitlement

@router.post("/forecasts")
async def create_forecast(
    request: CreateForecastRequest,
    tenant: CoreTenantContext = Depends(require_pack_entitlement("roster"))
):
    # Only accessible if tenant has roster pack enabled
    ...
```

---

## Migration Strategy

### Phase 1: Create Roster Pack Skeleton (Non-Breaking)

1. Create `packs/roster/` directory structure
2. Create `packs/roster/api/routers/__init__.py` with empty router
3. Register roster router in app factory (prefix `/api/v1/roster`)
4. Verify no conflicts with existing routes

### Phase 2: Move Routers (Gradual)

For each router (forecasts, plans, simulations, repair, config):

1. Copy router file to `packs/roster/api/routers/`
2. Update imports to use relative paths
3. Add route to roster pack's `__init__.py`
4. Add deprecation warning to kernel router
5. Update frontend/BFF to use new prefix
6. Remove kernel router after transition period

### Phase 3: Remove Kernel Roster Routes

1. Delete deprecated kernel routers
2. Update documentation
3. Remove deprecation warnings

---

## Consequences

### Positive

- **Clear Boundaries**: Each pack owns its domain logic
- **Independent Deployment**: Packs can be enabled/disabled per tenant
- **Testability**: Roster pack can be tested in isolation
- **SaaS Ready**: Multiple tenants can use same code with different configs

### Negative

- **Migration Effort**: Existing clients need route updates
- **Temporary Duplication**: During transition, routes exist in both places

### Neutral

- **Route Prefixes Change**: `/api/v1/forecasts` → `/api/v1/roster/forecasts`

---

## Alternatives Considered

### 1. Keep Roster Routes in Kernel

**Rejected**: Violates pack boundaries, prevents independent deployment, makes entitlement enforcement complex.

### 2. Symlink Approach

**Rejected**: Adds complexity, doesn't solve the architectural problem.

### 3. Big-Bang Migration

**Rejected**: Too risky. Gradual migration with deprecation period is safer.

---

## References

- [Architecture Correctness Report](../../docs/ARCHITECTURE_CORRECTNESS_REPORT.md)
- [ADR-002: Policy Profiles](./ADR-002-policy-profiles.md)
