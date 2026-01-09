# SOLVEREIGN Architecture Correctness Report

> **Generated**: 2026-01-07
> **Scope**: Kernel vs Pack Boundaries + Multi-Tenant Configuration
> **Status**: Analysis Complete - Action Items Identified

---

## Executive Summary

The current SOLVEREIGN architecture has **good foundations** but requires **targeted refactoring** to achieve clean Kernel/Pack boundaries necessary for SaaS scaling (multiple tenants, same code, different configurations).

| Area | Current State | Required State | Gap |
|------|---------------|----------------|-----|
| Kernel Routers | Mixed (domain + platform) | Platform-generic only | MEDIUM |
| Roster Pack | Scattered (v3/, src/) | backend_py/packs/roster/ | HIGH |
| Routing Pack | Clean separation | Maintain | NONE |
| Tenant ID | Dual (INT + UUID) | UUID canonical | MEDIUM |
| Policy Profiles | Not implemented | Data-driven config | HIGH |

---

## 1. ROSTER CODE LEAKAGE ANALYSIS

### Problem: Roster Logic in Kernel Namespace

The following kernel routers contain **roster-specific domain logic**:

| Router | Lines | Roster-Specific Content |
|--------|-------|------------------------|
| `api/routers/forecasts.py` | 270+ | Tour parsing, Gurkerl forecast format |
| `api/routers/plans.py` | 450+ | Solver invocation, 7 roster audits |
| `api/routers/simulations.py` | 330 | What-if scenarios (roster-focused) |
| `api/routers/repair.py` | 352 | Driver absence handling |
| `api/routers/config.py` | 457 | German labor law constraints |

### Evidence: Roster-Specific Imports in Kernel

```python
# In api/routers/plans.py (KERNEL router)
from ...v3.solver_wrapper import solve_forecast, solve_and_audit  # ROSTER logic
from ...v3.audit_fixed import audit_plan_fixed  # ROSTER 7-audit system

# In api/routers/forecasts.py (KERNEL router)
from ...v3.parser import parse_forecast_text  # ROSTER-specific parser
```

### Current Backend Structure

```
backend_py/
├── api/                    # KERNEL (but contains roster routes)
│   ├── routers/
│   │   ├── health.py       # KERNEL - OK
│   │   ├── tenants.py      # KERNEL - OK (legacy)
│   │   ├── core_tenant.py  # KERNEL - OK
│   │   ├── platform.py     # KERNEL - OK
│   │   ├── platform_orgs.py # KERNEL - OK
│   │   ├── service_status.py # KERNEL - OK
│   │   ├── runs.py         # KERNEL - OK (generic job runner)
│   │   ├── forecasts.py    # ❌ ROSTER - should move
│   │   ├── plans.py        # ❌ ROSTER - should move
│   │   ├── simulations.py  # ❌ ROSTER - should move
│   │   ├── repair.py       # ❌ ROSTER - should move
│   │   └── config.py       # ❌ ROSTER - should move
│   └── security/           # KERNEL - OK
├── v3/                     # ROSTER logic (parser, solver, audit)
├── src/                    # ROSTER logic (block heuristic)
└── packs/
    └── routing/            # ROUTING PACK - OK (clean separation)
```

### Required Backend Structure

```
backend_py/
├── api/                    # KERNEL ONLY
│   ├── routers/
│   │   ├── health.py       # KERNEL
│   │   ├── tenants.py      # KERNEL (legacy)
│   │   ├── core_tenant.py  # KERNEL
│   │   ├── platform.py     # KERNEL
│   │   ├── platform_orgs.py # KERNEL
│   │   ├── service_status.py # KERNEL
│   │   ├── runs.py         # KERNEL
│   │   └── evidence.py     # KERNEL (artifact access) - NEW
│   └── security/           # KERNEL
├── v3/                     # ROSTER internal (called by pack)
├── src/                    # ROSTER internal (called by pack)
└── packs/
    ├── routing/            # ROUTING PACK - unchanged
    │   └── api/routers/
    └── roster/             # ROSTER PACK - NEW
        ├── __init__.py
        └── api/
            └── routers/
                ├── forecasts.py    # Moved from kernel
                ├── plans.py        # Moved from kernel
                ├── simulations.py  # Moved from kernel
                ├── repair.py       # Moved from kernel
                └── config.py       # Moved from kernel
```

---

## 2. TENANT ID INCONSISTENCY ANALYSIS

### Problem: Dual Primary Key Systems

| System | PK Type | Table | Auth Method | Usage |
|--------|---------|-------|-------------|-------|
| Legacy | INTEGER | `tenants` | X-API-Key | v3 solver, forecasts |
| Modern | UUID | `core.tenants` | X-Tenant-Code | platform admin, entitlements |

### Evidence: Mixed Usage in Code

```python
# Pattern A: INTEGER (legacy)
class TenantContext:
    tenant_id: int  # INTEGER

# Pattern B: UUID (modern)
class CoreTenantContext:
    tenant_id: str  # UUID

# Pattern C: Routing pack uses INTEGER
@dataclass(frozen=True)
class Depot:
    tenant_id: int  # INTEGER for V2 solver compatibility
```

### Recommended Canonical Model

**UUID as canonical tenant identifier** (core.tenants.id):

```
core.tenants (UUID) ← canonical
    │
    ├── core.sites (UUID FK)
    ├── core.tenant_entitlements (UUID FK)
    └── tenant_identity_mappings (UUID FK)
            │
            └── maps to: tenants.id (INTEGER) for legacy compatibility
```

### Migration Path (Non-Breaking)

1. Add `core_tenant_id UUID` column to legacy tables
2. Backfill via tenant code lookup
3. Use `core_tenant_id` for new code, `tenant_id` for legacy
4. Deprecate INTEGER tenant_id in new endpoints

---

## 3. HMAC CANONICALIZATION ASSESSMENT

### Current State: SECURE (V2 Format)

The V2 HMAC implementation in `internal_signature.py` is well-designed:

```python
# Canonical string format (V2):
canonical = f"{method}|{canonical_path}|{timestamp}|{nonce}|{tenant_code}|{site_code}|{is_admin}|{body_hash}"
```

### Security Features (ALL PRESENT)

| Feature | Status | Implementation |
|---------|--------|----------------|
| Replay Protection | ✅ | Nonce in DB with 5min TTL |
| Timestamp Window | ✅ | ±120 seconds |
| Body Binding | ✅ | SHA256 of request body |
| Constant-Time Compare | ✅ | `hmac.compare_digest()` |
| Query Normalization | ✅ | `canonicalize_path()` sorts params |

### Potential Improvement: Server-Asserted Values

**Current (SAFE but could be clearer):**
```python
# Tenant/site from headers (but only trusted after signature verification)
tenant_code = request.headers.get("X-Tenant-Code")
```

**Recommendation:**
- Document that tenant/site values are **only trusted after signature verification**
- Add explicit comment in code: "Client cannot spoof these - signature verification required first"

---

## 4. POLICY PROFILES GAP

### Problem: No Data-Driven Configuration

Currently, tenant-specific settings are either:
1. **Hardcoded** in solver code
2. **Missing** (all tenants use same defaults)

### Required: Policy Profile System

```sql
-- Per-tenant, per-pack configuration
CREATE TABLE core.policy_profiles (
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES core.tenants(id),
    pack_id TEXT NOT NULL,  -- 'routing', 'roster'
    name TEXT NOT NULL,
    version INT NOT NULL,
    status TEXT DEFAULT 'draft',  -- draft, active, archived
    config_json JSONB NOT NULL,
    config_hash TEXT GENERATED ALWAYS AS (encode(sha256(config_json::bytea), 'hex')) STORED,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT
);

-- Which profile is active for a tenant/pack
CREATE TABLE core.tenant_pack_settings (
    tenant_id UUID REFERENCES core.tenants(id),
    pack_id TEXT NOT NULL,
    active_profile_id UUID REFERENCES core.policy_profiles(id),
    PRIMARY KEY (tenant_id, pack_id)
);
```

### Snapshot Requirement

Every Scenario/PlanVersion must store:
- `policy_profile_id` - which profile was used
- `policy_config_hash` - hash of config at time of run

This ensures determinism: same inputs + same policy = same outputs.

---

## 5. ACTION ITEMS

### Phase 1: Roster Pack Boundary (PRIORITY: HIGH)

| Task | Effort | Risk |
|------|--------|------|
| Create `packs/roster/` skeleton | 1 day | Low |
| Move forecasts.py to roster pack | 1 day | Medium |
| Move plans.py to roster pack | 1 day | Medium |
| Move simulations/repair/config.py | 1 day | Low |
| Update app factory router registration | 1 hour | Low |
| Add /api/v1/roster/* route prefix | 1 hour | Low |

### Phase 2: Policy Profiles (PRIORITY: HIGH)

| Task | Effort | Risk |
|------|--------|------|
| DB migration for policy tables | 1 day | Low |
| Policy service (get_active_policy) | 1 day | Low |
| Snapshot policy_hash in PlanVersion | 1 day | Medium |
| JSON schema validation per pack | 1 day | Low |

### Phase 3: Tenant ID Canonicalization (PRIORITY: MEDIUM)

| Task | Effort | Risk |
|------|--------|------|
| Add core_tenant_id to legacy tables | 1 day | Medium |
| Backfill via tenant code lookup | 1 day | Medium |
| Update roster pack to use UUID | 2 days | High |
| Deprecate INTEGER tenant_id | 1 week | High |

---

## 6. SUCCESS CRITERIA

After refactoring, the API should expose:

```
# KERNEL (platform-generic)
/api/v1/platform/*        # Tenant/site/user management
/api/v1/evidence/*        # Artifact access
/api/v1/runs/*            # Job status
/health, /metrics         # Observability

# PACKS (domain-specific)
/api/v1/routing/*         # Routing pack (already exists)
/api/v1/roster/*          # Roster pack (NEW)
```

**Multi-Tenant Scaling Test:**
- Onboard second company to roster pack
- Company selects active policy profile
- Solver runs reference policy_config_hash
- No code forks required

**Determinism Test:**
- Re-run same scenario + same policy hash
- Produces identical outputs
- Evidence pack contains policy snapshot

---

## Appendix: File References

| File | Lines | Current Role | Target Role |
|------|-------|--------------|-------------|
| api/routers/forecasts.py | 270+ | Kernel | Roster Pack |
| api/routers/plans.py | 450+ | Kernel | Roster Pack |
| api/routers/simulations.py | 330 | Kernel | Roster Pack |
| api/routers/repair.py | 352 | Kernel | Roster Pack |
| api/routers/config.py | 457 | Kernel | Roster Pack |
| packs/routing/api/routers/* | 756 | Routing Pack | Unchanged |
| v3/*.py | 4500+ | Roster Logic | Roster Pack Internal |
| src/services/*.py | 18000+ | Roster Logic | Roster Pack Internal |
