# Kernel Boundary Definition

> **Purpose**: Define what belongs in Kernel vs Packs
> **Last Updated**: 2026-01-07

---

## CORE PRINCIPLE

**Kernel = Shared platform infrastructure that all packs depend on.**
**Pack = Domain-specific logic for a particular use case.**

---

## KERNEL COMPONENTS

### What Belongs in Kernel

| Component | Purpose | Location |
|-----------|---------|----------|
| Multi-Tenancy | Tenant management, RLS | `api/database.py`, `api/dependencies.py` |
| Authentication | Entra ID, HMAC, API Key | `api/security/` |
| Plan Lifecycle | State machine, locking | `api/services/plan_service.py` |
| Audit Gating | Block lock on audit fail | `api/services/audit_gate.py` |
| Evidence Storage | Artifact upload/download | `api/services/evidence/` |
| Service Status | Escalations, degraded mode | `api/services/escalation.py` |
| Policy Profiles | Pack configuration | `api/services/policy_service.py` |
| Request Signing | HMAC for internal calls | `api/security/internal_signature.py` |
| Health Probes | /health, /ready, /live | `api/routers/health.py` |
| Idempotency | Request deduplication | `api/dependencies.py` |

### Kernel Code Structure

```
backend_py/api/
├── main.py              # App factory, middleware
├── config.py            # Platform configuration
├── database.py          # Connection pool, RLS context
├── dependencies.py      # DI, auth injection
├── exceptions.py        # Platform exceptions
├── security/
│   ├── entra_auth.py    # Entra ID integration
│   ├── internal_signature.py  # HMAC signing
│   └── rbac.py          # Role-based access
├── services/
│   ├── policy_service.py     # Pack config profiles
│   ├── escalation.py         # Service status
│   └── evidence/
│       └── artifact_store.py # S3/Azure storage
└── routers/
    ├── health.py        # Health probes
    ├── platform.py      # Tenant management
    └── service_status.py # Escalations API
```

---

## PACK COMPONENTS

### What Belongs in Packs

| Component | Purpose | Example |
|-----------|---------|---------|
| Domain Models | Pack-specific entities | Tour, Stop, Vehicle, Route |
| Solver Logic | Optimization algorithm | Block heuristic, OR-Tools VRPTW |
| Domain Audits | Pack-specific validations | 7 roster audits, route audits |
| Pack API | Pack-specific endpoints | /api/v1/routing/scenarios |
| Config Schema | Pack policy schema | RosterConfig, RoutingConfig |

### Pack Code Structure

```
backend_py/packs/
├── roster/
│   ├── api/
│   │   └── routers/
│   │       ├── forecasts.py
│   │       └── plans.py
│   ├── services/
│   │   ├── solver/
│   │   └── audits/
│   ├── models/
│   │   └── tour.py
│   └── config_schema.py
└── routing/
    ├── api/
    │   └── routers/
    │       ├── scenarios.py
    │       └── routes.py
    ├── services/
    │   ├── solver/
    │   ├── repair/
    │   └── evidence/
    ├── models/
    │   └── stop.py
    └── config_schema.py
```

---

## IMPORT RULES

### RULE 1: Kernel Never Imports from Packs

```python
# ❌ FORBIDDEN in Kernel code
from backend_py.packs.roster.services import solver
from backend_py.packs.routing.models import Stop

# ✅ ALLOWED in Kernel code
from backend_py.api.services import policy_service
from backend_py.api.database import get_db_pool
```

### RULE 2: Packs Can Import from Kernel

```python
# ✅ ALLOWED in Pack code
from backend_py.api.services.policy_service import get_policy_service
from backend_py.api.database import get_connection
from backend_py.api.dependencies import get_tenant_context
```

### RULE 3: Packs Never Import from Other Packs

```python
# ❌ FORBIDDEN in routing pack
from backend_py.packs.roster.models import Tour

# ❌ FORBIDDEN in roster pack
from backend_py.packs.routing.services import solver
```

### Shared Logic

If multiple packs need the same logic, extract to Kernel:

```python
# ✅ CORRECT: Shared logic in Kernel
# backend_py/api/services/common/distance_matrix.py

# Both packs import from Kernel
from backend_py.api.services.common.distance_matrix import compute_matrix
```

---

## DATABASE SCHEMA BOUNDARIES

### Kernel Tables

```sql
-- core schema for kernel
CREATE SCHEMA IF NOT EXISTS core;

-- Kernel tables
core.tenants
core.sites
core.organizations
core.policy_profiles
core.tenant_pack_settings
core.used_signatures
core.security_events
```

### Pack Tables

```sql
-- Public schema for packs (legacy) or pack-specific schemas

-- Roster pack
forecast_versions
tours_normalized
tour_instances
plan_versions
assignments

-- Routing pack
routing.scenarios
routing.stops
routing.vehicles
routing.routes
routing.assignments
```

### Cross-Schema Rules

1. Pack tables CAN reference `core.tenants`
2. Pack tables CANNOT reference other pack tables
3. Kernel tables CANNOT reference pack tables

---

## API ROUTE BOUNDARIES

### Kernel Routes

```
/health/*                  # Health probes
/api/v1/platform/*         # Tenant/org management
/api/v1/policies/*         # Policy profiles
/api/v1/service-status/*   # Escalations
```

### Pack Routes

```
# Roster pack
/api/v1/forecasts/*
/api/v1/plans/*

# Routing pack
/api/v1/routing/scenarios/*
/api/v1/routing/routes/*
```

---

## DEPENDENCY INJECTION

### Kernel Services

```python
# Kernel service injection
from backend_py.api.services.policy_service import get_policy_service

@router.get("/config")
async def get_config(
    policy_service: PolicyService = Depends(get_policy_service)
):
    ...
```

### Pack Services

```python
# Pack service uses Kernel DI
from backend_py.api.dependencies import get_tenant_context
from backend_py.packs.routing.services.solver import RoutingSolver

@router.post("/solve")
async def solve(
    tenant: TenantContext = Depends(get_tenant_context),  # From Kernel
    solver: RoutingSolver = Depends(get_solver)  # Pack-specific
):
    ...
```

---

## VERIFICATION

### Check Import Violations

```bash
# Should return no results
grep -r "from backend_py.packs" backend_py/api/

# Should return no cross-pack imports
grep -r "from backend_py.packs.roster" backend_py/packs/routing/
grep -r "from backend_py.packs.routing" backend_py/packs/roster/
```

### CI Check

```yaml
# Add to PR checks
- name: Verify Kernel Boundary
  run: |
    if grep -r "from backend_py.packs" backend_py/api/; then
      echo "ERROR: Kernel imports from Pack detected"
      exit 1
    fi
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Kernel imports from Pack | S2 | Fix immediately. Extract to Kernel if shared. |
| Pack imports from other Pack | S3 | Refactor. Extract shared logic to Kernel. |
| Pack-specific table in core schema | S3 | Move to pack schema. |
| Kernel route serves pack data | S3 | Move to pack router. |
