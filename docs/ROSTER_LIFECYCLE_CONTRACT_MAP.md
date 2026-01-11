# Roster Lifecycle Contract Map

> **Generated**: 2026-01-10
> **Phase**: B1 Inventory Complete
> **Status**: Source of Truth Verified

---

## Entity → Table Map

| Entity | Table | Schema | Primary Key | RLS |
|--------|-------|--------|-------------|-----|
| **PlanVersion** | `plan_versions` | public | `id` (SERIAL) | `tenant_id` via `app.current_tenant_id` |
| **Snapshot** | `plan_snapshots` | public | `id` (SERIAL), `snapshot_id` (UUID) | `tenant_id` |
| **Assignment** | `assignments` | public | `id` (SERIAL) | Via `plan_version_id` |
| **TourInstance** | `tour_instances` | public | `id` (SERIAL) | Via `forecast_version_id` |
| **Evidence** | `routing_evidence` | public | `id` (SERIAL) | `tenant_id` |
| **AuditLog** | `auth.audit_log` | auth | `id` (BIGSERIAL) | `tenant_id` |
| **PlanApproval** | `plan_approvals` | public | `id` (SERIAL) | Via `plan_version_id` |
| **ImportRun** | `import_runs` | public | `id` (SERIAL) | `tenant_id` |

---

## Key Columns

### plan_versions
```
id, tenant_id, site_id, forecast_version_id, status, plan_state,
seed, output_hash, solver_run_id, audit_passed_count, audit_failed_count,
current_snapshot_id, publish_count, freeze_until, repair_source_snapshot_id,
plan_state_changed_at, created_at
```

### plan_snapshots
```
id, snapshot_id (UUID), plan_version_id, tenant_id, site_id,
version_number, published_at, published_by, publish_reason,
freeze_until, solver_run_id, kpi_snapshot (JSONB),
input_hash, matrix_hash, output_hash, evidence_hash,
result_artifact_uri, evidence_artifact_uri,
assignments_snapshot (JSONB), routes_snapshot (JSONB),
snapshot_status (ACTIVE|SUPERSEDED|ARCHIVED),
audit_passed_count, audit_results_snapshot (JSONB)
```

### auth.audit_log
```
id, event_type, user_id, user_email, tenant_id, site_id,
session_id, details (JSONB), error_code, ip_hash, user_agent_hash,
created_at, target_tenant_id
```

---

## API Route Map

### Existing (Entra Auth - kernel)
| Route | Method | Auth | Location |
|-------|--------|------|----------|
| `/api/v1/plans/solve` | POST | Entra | `api/routers/plans.py` |
| `/api/v1/plans/{id}` | GET | Entra | `api/routers/plans.py` |
| `/api/v1/plans/{id}/state` | GET | Entra | `api/routers/plans.py` |
| `/api/v1/plans/{id}/publish` | POST | Entra+Approver | `api/routers/plans.py` |
| `/api/v1/plans/{id}/snapshots` | GET | Entra | `api/routers/plans.py` |
| `/api/v1/plans/{id}/repair` | POST | Entra+Approver | `api/routers/plans.py` |

### New (Internal RBAC - SaaS)
| Route | Method | Auth | Guards | Location |
|-------|--------|------|--------|----------|
| `/api/v1/roster/plans` | GET | Session | RBAC | `packs/roster/api/routers/lifecycle.py` |
| `/api/v1/roster/plans` | POST | Session | RBAC+CSRF+Idem | `packs/roster/api/routers/lifecycle.py` |
| `/api/v1/roster/plans/{id}` | GET | Session | RBAC | `packs/roster/api/routers/lifecycle.py` |
| `/api/v1/roster/snapshots` | GET | Session | RBAC | `packs/roster/api/routers/lifecycle.py` |
| `/api/v1/roster/snapshots/publish` | POST | Session | RBAC+CSRF+Idem | `packs/roster/api/routers/lifecycle.py` |
| `/api/v1/roster/snapshots/{id}` | GET | Session | RBAC | `packs/roster/api/routers/lifecycle.py` |
| `/api/v1/tenant/dashboard` | GET | Session | RBAC | `api/routers/tenant_dashboard.py` |
| `/api/v1/evidence` | GET | Session | RBAC | `api/routers/evidence.py` |
| `/api/v1/evidence/{id}` | GET | Session | RBAC | `api/routers/evidence.py` |
| `/api/v1/audit` | GET | Session | RBAC | `api/routers/audit_viewer.py` |

---

## DB Functions (Source of Truth)

### Plan Lifecycle
| Function | Purpose |
|----------|---------|
| `transition_plan_state()` | Safe state machine transitions |
| `get_plan_with_state()` | Full plan state + history |
| `is_plan_frozen()` | Check freeze window status |

### Snapshot Lifecycle
| Function | Purpose |
|----------|---------|
| `publish_plan_snapshot()` | Create immutable snapshot (12h freeze) |
| `create_repair_version()` | Create new draft from snapshot |
| `get_snapshot_history()` | All snapshots for a plan |
| `build_snapshot_payload()` | Build assignments/routes JSONB |
| `verify_snapshot_integrity()` | 5-point integrity check |

### Evidence
| Function | Purpose |
|----------|---------|
| `get_routing_evidence()` | Full evidence JSON for plan |

---

## State Machine

```
DRAFT → SOLVING → SOLVED → APPROVED → PUBLISHED
         ↓                    ↓
       FAILED              REJECTED
```

### Snapshot Status
```
ACTIVE → SUPERSEDED → ARCHIVED
```

---

## Immutability Rules

1. **plan_snapshots**: Trigger `prevent_snapshot_modification()` blocks:
   - All DELETE
   - All UPDATE except `snapshot_status` change

2. **assignments**: Trigger blocks UPDATE/DELETE when `plan_versions.status = 'LOCKED'`

3. **auth.audit_log**: Trigger `prevent_audit_modification()` blocks UPDATE/DELETE

---

## Policy Hash / Seed Tracking

| Column | Table | Purpose |
|--------|-------|---------|
| `seed` | plan_versions | Solver reproducibility seed |
| `output_hash` | plan_versions | SHA-256 of solver output |
| `input_hash` | plan_snapshots | Hash of input data at publish |
| `matrix_hash` | plan_snapshots | Hash of routing matrix |
| `evidence_hash` | plan_snapshots | Hash of evidence artifact |
| `policy_hash` | (future) | Policy profile content hash |

---

## Evidence Flow

```
Plan Create → routing_evidence row created
    ↓
Publish → plan_snapshots row with:
    - evidence_hash
    - evidence_artifact_uri
    - kpi_snapshot (JSONB)
    - audit_results_snapshot (JSONB)
```

---

## Audit Event Types

| Event | Where Logged |
|-------|--------------|
| plan_create | plan_approvals (action=CREATE) |
| plan_approve | plan_approvals (to_state=APPROVED) |
| plan_publish | plan_approvals (to_state=PUBLISHED) |
| plan_reject | plan_approvals (to_state=REJECTED) |
| repair_create | plan_approvals (action=REPAIR) |
| login_success | auth.audit_log |
| login_failed | auth.audit_log |
| session_revoked | auth.audit_log |

---

## Known Limitations

1. **No policy_hash column yet** - Will add in future migration
2. **Evidence files local** - Future: S3/Azure artifact store
3. **Idempotency keys not persisted** - Future: Redis or DB table

---

## Verification Commands

```sql
-- Snapshot integrity (5 checks)
SELECT * FROM verify_snapshot_integrity();

-- RBAC integrity (13 checks)
SELECT * FROM auth.verify_rbac_integrity();

-- Security (17 tests)
SELECT * FROM verify_final_hardening();
```
