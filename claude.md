# SOLVEREIGN V3 - Agent Context Handoff

> **Last Updated**: 2026-01-08
> **Status**: V3.7.2 COMPLETE | Plan Versioning + Snapshot Fixes | SaaS Ready
> **Next Milestone**: Wien Pilot Production Go-Live

---

## Big Picture: What is SOLVEREIGN?

**SOLVEREIGN** is an enterprise multi-tenant shift scheduling platform for logistics companies.

**End Product Vision**:
```
┌─────────────────────────────────────────────────────────────────┐
│                    SOLVEREIGN PLATFORM                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   IMPORT                SOLVE                 PUBLISH            │
│   ├─ FLS/CSV            ├─ OR-Tools VRPTW     ├─ Audit Gates    │
│   ├─ Canonicalize       ├─ 145 drivers        ├─ Evidence Pack  │
│   └─ Validate           └─ 100% coverage      └─ Lock + Export  │
│                                                                  │
│   MULTI-TENANT          SECURITY              ENTERPRISE         │
│   ├─ RLS per tenant     ├─ 7 migrations       ├─ KPI Drift      │
│   ├─ Advisory Locks     ├─ 50+ tests          ├─ Golden Sets    │
│   └─ Site Partitioning  └─ Audit-gated        └─ Impact Preview │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Current Tenant**: LTS Transport (pilot: Wien)
**Target Verticals**: MediaMarkt, HDL Plus, Gurkerl

---

## Critical Context (Read This First)

### 1. Security Stack (7 Migrations - ALL COMPLETE)

| Migration | Purpose | Key Feature |
|-----------|---------|-------------|
| **025** | RLS on tenants | FORCE ROW LEVEL SECURITY |
| **025a** | Hardening | search_path, is_active filter |
| **025b** | Role lockdown | Least-privilege EXECUTE |
| **025c** | Boundary fix | pg_has_role() replaces session vars |
| **025d** | Definer hardening | NO BYPASSRLS, dedicated role |
| **025e** | Final hardening | ALTER DEFAULT PRIVILEGES, 17 SQL tests |
| **025f** | ACL fix | Retroactive REVOKE PUBLIC (idempotent) |

**Source of Truth**: `SELECT * FROM verify_final_hardening();` - All 17 tests must PASS.

**Critical Pattern** - SECURITY DEFINER functions:
```sql
-- ALWAYS use session_user, NOT current_user
IF NOT pg_has_role(session_user, 'solvereign_platform', 'MEMBER') THEN
    RAISE EXCEPTION 'Permission denied';
END IF;
```

### 2. Role Hierarchy

| Role | Purpose | Restrictions |
|------|---------|--------------|
| `solvereign_admin` | Migrations only | Superuser-like, NO runtime use |
| `solvereign_platform` | Admin operations | CAN access tenants table |
| `solvereign_api` | Tenant operations | CANNOT access tenants, CANNOT escalate |
| `solvereign_definer` | Function owner | NO BYPASSRLS, NO CREATE |

### 3. Key Solver Results (V2 Integration Done)

- **145 drivers** (100% FTE, 0 PT)
- **1385/1385 tours** covered (100%)
- **Max 54h** per driver (55h hard limit)
- **Seed 94** for reproducibility
- **7/7 audits PASS** (Coverage, Overlap, Rest, Span, Fatigue, Freeze, 55h Max)

---

## Completed Milestones Summary

| Version | Milestone | Status |
|---------|-----------|--------|
| V3.3a | Multi-tenant API (FastAPI + PostgreSQL) | COMPLETE |
| V3.3b | Routing-Pack (6 Gates, 68 tests) | COMPLETE |
| V3.4 | Enterprise Extensions (Skills 113-116, 88 tests) | COMPLETE |
| V3.5 | Guardian Context Tree (10-point hardening) | COMPLETE |
| V3.6 | Wien Pilot Pipeline (10 deliverables, 18 OSRM tests) | COMPLETE |
| V3.6.3 | session_user fix in SECURITY DEFINER | COMPLETE |
| V3.6.4 | Final Hardening (025e + 025f) | COMPLETE |
| V3.6.5 | P0 Precedence + Multi-Start (28 tests) | COMPLETE |
| V3.7.0 | P1 Multi-TW + Lexicographic Disqualification | COMPLETE |
| V3.7.1 | Plan Versioning (plan_snapshots + repair flow) | COMPLETE |
| V3.7.2 | Snapshot Fixes (race-safe, payload, freeze audit) | COMPLETE |

---

## Next Steps: Wien Pilot Production

### Immediate Actions

1. **Production DB Migration**
   - Apply migrations 025-027a to production DB
   - Run `SELECT * FROM verify_final_hardening();` - all 17 PASS required
   - Run `SELECT * FROM verify_snapshot_integrity();` - all checks PASS
   - Run `SELECT acl_scan_report_json();` - upload as CI artifact

2. **Wien Pilot Smoke Test**
   ```bash
   python scripts/wien_pilot_smoke_test.py --env production
   ```
   - Tests: Auth → Solve → Approve → Publish → Snapshot → Repair

3. **CI Pipeline Verification**
   - `pytest backend_py/tests/test_final_hardening.py -v` (13 Python tests)
   - SQL `verify_final_hardening()` + `verify_snapshot_integrity()` in CI job

### Pending Work Items

| Priority | Task | Status |
|----------|------|--------|
| P1 | Production DB migration (025-027a) | Ready to apply |
| P1 | Frontend Auth (remove mocks, real RBAC) | In Progress |
| P2 | ArtifactStore Production Mode (KeyVault) | Planned |
| P2 | Ops Runbook + Incident Drill | Planned |
| P3 | Messaging integration (SMS/WhatsApp) | Backlog |

---

## V3.7: Plan Versioning + SaaS Readiness (Jan 8, 2026)

### Overview

Complete SaaS infrastructure for production deployment with immutable audit trails.

| Component | V3.7.0 | V3.7.1 | V3.7.2 |
|-----------|--------|--------|--------|
| Multi-TW Routing | COMPLETE | - | - |
| Lexicographic Disqualification | COMPLETE | - | - |
| Plan Snapshots | - | COMPLETE | - |
| Repair Flow | - | COMPLETE | - |
| Race-Safe Versioning | - | - | COMPLETE |
| Snapshot Payload Population | - | - | COMPLETE |
| Freeze Audit Trail | - | - | COMPLETE |

### Plan Versioning Model

```
┌─────────────────────────────────────────────────────────────────┐
│                    PLAN LIFECYCLE                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   plan_versions (Working)          plan_snapshots (Immutable)   │
│   ├─ DRAFT                         ├─ version_number = 1        │
│   ├─ SOLVING                       ├─ assignments_snapshot      │
│   ├─ SOLVED                        ├─ routes_snapshot           │
│   ├─ APPROVED ──────────PUBLISH───►├─ kpi_snapshot              │
│   │                                └─ is_legacy flag            │
│   └─ Working plan NOT blocked!                                   │
│                                                                  │
│   REPAIR: snapshot → new DRAFT plan_version → re-solve          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Technical Details

**Race-Safe Versioning** (027a_snapshot_fixes.sql):
```sql
-- Lock parent row FIRST, then calculate next version
SELECT id INTO v_plan_id FROM plan_versions WHERE id = p_plan_version_id FOR UPDATE OF pv;
SELECT COALESCE(MAX(version_number), 0) + 1 INTO v_next_version FROM plan_snapshots WHERE plan_version_id = p_plan_version_id;
-- Unique constraint prevents duplicates even if lock fails
ALTER TABLE plan_snapshots ADD CONSTRAINT plan_snapshots_unique_version_per_plan UNIQUE (plan_version_id, version_number);
```

**Snapshot Payload** (build_snapshot_payload function):
```sql
-- Fetches real data from plan_assignments table
SELECT json_build_object(
    'assignments', (SELECT json_agg(...) FROM plan_assignments WHERE plan_version_id = p_plan_version_id),
    'routes', (SELECT json_object_agg(...) FROM plan_routes WHERE plan_version_id = p_plan_version_id)
)
```

**Freeze Window Enforcement**:
- Default: HTTP 409 blocks publish during freeze
- Override: `force_during_freeze=true` + `force_reason` (min 10 chars)
- Audit: `forced_during_freeze` + `force_reason` columns in `plan_approvals`

### New Migrations (V3.7)

| Migration | Purpose |
|-----------|---------|
| **027** | Plan versioning tables + repair flow |
| **027a** | Snapshot fixes (race-safe, payload, freeze audit) |

### Verification Functions

```sql
-- V3.7.2 integrity check
SELECT * FROM verify_snapshot_integrity();
-- Expected: unique_version_numbers, payload_populated, one_active_per_plan, sequential_versions, valid_freeze_timestamps

-- Legacy backfill (dry run first!)
SELECT * FROM backfill_snapshot_payloads(TRUE);  -- dry run
SELECT * FROM backfill_snapshot_payloads(FALSE); -- execute
```

---

## V3.6.5: P0 Precedence + Multi-Start Fixes (Jan 8, 2026)

### Overview

Quality improvements for "Service-VRP" routing pack with precedence constraints:

| Fix | Issue | Resolution |
|-----|-------|------------|
| **CumulVar Semantics** | Misleading comment about service time | `time_callback(from,to) = travel + service(to)` - automatic inclusion |
| **Dropped Pairs** | Capacity effect of unassigned pairs | OR-Tools `AddPickupAndDelivery` guarantees net-zero via balanced `load_delta` |
| **vehicles_used** | Counting only active vehicles | Verified: `if route_stops: vehicles_used += 1` (correct) |

### Key Technical Details

**CumulVar Ordering** (constraints.py:420-436):
```python
# CumulVar(pickup) = arrival_at_pickup + service_at_pickup (automatic via time_callback)
# Constraint: finish_pickup <= finish_delivery
solver.Add(time_dimension.CumulVar(pickup_index) <= time_dimension.CumulVar(delivery_index))
```

**Dropped Pair Guarantees** (OR-Tools built-in):
- `AddPickupAndDelivery(pickup, delivery)` ensures both visited or both dropped
- Capacity callbacks only fire for visited nodes
- Balanced `load_delta` (+1 pickup, -1 delivery) = net-zero capacity effect

**KPI Tuple Comparison** (vrptw_solver.py):
```python
# Lower = better (lexicographic)
kpi_tuple = (unassigned_count, tw_violations, overtime_min, travel_km, vehicles_used)
```

### Tests Added (28 total, 1 xfail)

| Test Class | Tests | Purpose |
|------------|-------|---------|
| `TestServiceTimeWithPrecedence` | 2 | CumulVar + service time correctness |
| `TestDroppedPairCapacity` | 2 | Dropped pair capacity isolation |
| `TestVehiclesUsedCount` | 3 | Active vehicle counting |
| `TestKPITupleComparison` | 5 | Lexicographic KPI ranking |
| `TestPrecedenceConstraints` | 3 | Pickup-before-delivery enforcement |
| `TestMultiStartSolving` | 8 | Multi-start determinism |
| `TestSolverDataModelSetup` | 4 | Data model initialization |
| `TestIntegrationPrecedence` | 1 (xfail) | Full integration (timing issue) |

---

## Quick Reference

### Key Files

| Category | File | Lines |
|----------|------|-------|
| Architecture | `backend_py/ROADMAP.md` | 613 |
| API Entry | `backend_py/api/main.py` | - |
| Solver | `backend_py/v3/solver_wrapper.py` | 330 |
| Audit | `backend_py/v3/audit_fixed.py` | 691 |
| Security | `backend_py/db/migrations/025e_final_hardening.sql` | ~400 |
| ACL Fix | `backend_py/db/migrations/025f_acl_fix.sql` | ~380 |
| RLS Tests | `backend_py/tests/test_tenants_rls.py` | ~1300 |
| Hardening Tests | `backend_py/tests/test_final_hardening.py` | ~470 |
| ACL Config | `backend_py/config/acl_allowlist.json` | 52 |
| **Routing P0** | `backend_py/packs/routing/services/solver/vrptw_solver.py` | ~550 |
| **Routing P0** | `backend_py/packs/routing/services/solver/constraints.py` | ~475 |
| **Routing P0** | `backend_py/packs/routing/services/solver/data_model.py` | ~420 |
| **P0 Tests** | `backend_py/packs/routing/tests/test_p0_precedence_multistart.py` | ~750 |
| **Plan Versioning** | `backend_py/db/migrations/027_plan_versioning.sql` | ~300 |
| **Snapshot Fixes** | `backend_py/db/migrations/027a_snapshot_fixes.sql` | ~350 |
| **Plans API** | `backend_py/api/routers/plans.py` | ~500 |
| **SaaS Reality** | `docs/SAAS_DEPLOYMENT_REALITY.md` | ~270 |

### Key Commands

```bash
# Start database
docker compose up -d postgres

# Apply all migrations (in order!)
psql $DATABASE_URL < backend_py/db/migrations/025_tenants_rls_fix.sql
psql $DATABASE_URL < backend_py/db/migrations/025a_rls_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025b_rls_role_lockdown.sql
psql $DATABASE_URL < backend_py/db/migrations/025c_rls_boundary_fix.sql
psql $DATABASE_URL < backend_py/db/migrations/025d_definer_owner_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025e_final_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025f_acl_fix.sql
psql $DATABASE_URL < backend_py/db/migrations/026_solver_runs.sql
psql $DATABASE_URL < backend_py/db/migrations/026a_state_atomicity.sql
psql $DATABASE_URL < backend_py/db/migrations/027_plan_versioning.sql
psql $DATABASE_URL < backend_py/db/migrations/027a_snapshot_fixes.sql

# Verify security (SOURCE OF TRUTH)
psql $DATABASE_URL -c "SELECT * FROM verify_final_hardening();"

# Verify plan versioning
psql $DATABASE_URL -c "SELECT * FROM verify_snapshot_integrity();"

# Generate ACL report for CI
psql $DATABASE_URL -c "SELECT acl_scan_report_json();" -t > acl_scan_report.json

# Run Python tests
pytest backend_py/tests/test_final_hardening.py -v
pytest backend_py/tests/test_tenants_rls.py -v

# Wien Pilot smoke test
python scripts/wien_pilot_smoke_test.py --env staging
```

### Database Roles Verification

```sql
-- Check role hierarchy
SELECT r.rolname, r.rolinherit, r.rolbypassrls
FROM pg_roles r
WHERE r.rolname LIKE 'solvereign_%';

-- Verify API role CANNOT access tenants
SET ROLE solvereign_api;
SELECT COUNT(*) FROM tenants;  -- Should return 0 (RLS blocks)

-- Verify API cannot escalate
SET app.is_super_admin = 'true';
SELECT COUNT(*) FROM tenants;  -- Still 0 (session vars don't bypass pg_has_role)
```

---

## Production Verification Checklist

Before production deployment, verify:

### Security (V3.6.4)
- [ ] `verify_final_hardening()` returns 17 PASS (0 FAIL)
- [ ] `acl_scan_report()` shows 0 user objects with PUBLIC grants
- [ ] `solvereign_api` cannot SELECT from tenants directly
- [ ] `solvereign_api` cannot execute `verify_rls_boundary()` or `list_all_tenants()`
- [ ] No role has BYPASSRLS except postgres superuser
- [ ] ALTER DEFAULT PRIVILEGES set for admin/definer/platform in public AND core schemas

### Plan Versioning (V3.7.2)
- [ ] `verify_snapshot_integrity()` returns all PASS
- [ ] Unique constraint `plan_snapshots_unique_version_per_plan` exists
- [ ] `build_snapshot_payload()` function exists and works
- [ ] `backfill_snapshot_payloads(TRUE)` reports legacy count (dry run)
- [ ] Freeze window enforcement: HTTP 409 on publish during freeze
- [ ] Force override requires `force_reason` (min 10 chars)
- [ ] Test full flow: Solve → Approve → Publish → Snapshot → Repair

---

## Architecture Patterns (For Reference)

### Template vs Instance
- **Templates** (`tours_normalized`): Store with `count=3`
- **Instances** (`tour_instances`): Expand to 3 rows (1:1 with assignments)
- Solver operates on instances, not templates

### Immutability
- LOCKED plans: No UPDATE/DELETE via triggers
- Audit log: Append-only even after LOCK

### Plan Versioning (V3.7)
- **plan_versions**: Working plan (modifiable, can re-solve)
- **plan_snapshots**: Immutable published versions
- Trigger `tr_prevent_snapshot_modification` blocks updates to snapshots
- Repair creates new plan_version from snapshot (snapshot unchanged)

### Lexicographic Optimization
```python
cost = 1_000_000_000 * num_drivers    # Minimize headcount
cost += 1_000_000 * num_pt_drivers    # Minimize part-time
cost += 1_000 * num_splits            # Minimize splits
```

---

**Total Codebase**: ~19,000 lines (code + docs + tests + schemas)
**Test Coverage**: 50+ security tests, 88 enterprise skill tests, 68 routing tests, 28 P0 precedence tests, 5 snapshot integrity checks

---

*For detailed implementation history, see `docs/SAAS_DEPLOYMENT_REALITY.md` and `backend_py/ROADMAP.md`*
