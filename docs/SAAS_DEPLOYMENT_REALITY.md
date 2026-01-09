# SOLVEREIGN SaaS Deployment Reality Check

> **Date**: 2026-01-08
> **Version**: V3.7.2 (Snapshot Fixes Complete)
> **Honesty Level**: 100%

---

## What's Actually Implemented

### ✅ Authentication (Entra ID / Azure AD)

| Component | Status | Notes |
|-----------|--------|-------|
| Frontend MSAL | ✅ Implemented | `@azure/msal-browser` with popup/redirect |
| Backend JWT validation | ✅ Implemented | RS256 via JWKS, issuer validation |
| Role mapping | ✅ Implemented | Entra App Roles → internal roles |
| Tenant mapping | ✅ Implemented | `tid` claim → `tenant_identities` table |
| Token refresh | ✅ Implemented | Silent acquisition with fallback |

**Current Auth Mode**: Depends on env vars
- `AZURE_STORAGE_CONNECTION_STRING` → Pilot mode (Account Key)
- `AZURE_STORAGE_ACCOUNT_URL` → Production mode (Managed Identity)

**NOT Implemented**:
- [ ] Logout everywhere (token revocation)
- [ ] Session management (server-side sessions)

---

### ✅ Plan State Machine

| State Transition | DB Enforced | Audit Trail |
|------------------|-------------|-------------|
| DRAFT → SOLVING | ✅ | ✅ |
| SOLVING → SOLVED | ✅ | ✅ |
| SOLVED → APPROVED | ✅ | ✅ (unique constraint) |
| APPROVED → PUBLISHED | ✅ | ✅ (unique constraint) |
| PUBLISHED → REPAIR | ✅ | ✅ (creates new plan) |

**Atomicity Guards**:
- `FOR UPDATE NOWAIT` row locking in `transition_plan_state()`
- Unique indexes prevent duplicate APPROVE/PUBLISH
- Idempotency: calling same transition twice returns success

**V3.7.1: Plan Versioning (NEW!)**:
- `plan_versions` = Working plan (CAN be modified, re-solved)
- `plan_snapshots` = Immutable published versions
- Trigger `tr_prevent_snapshot_modification` blocks updates to snapshots
- Working plan is NOT blocked after publish!

**NOT Implemented**:
- [ ] Automatic freeze window enforcement (advisory only)

---

### ✅ Artifact Storage (Azure Blob)

| Feature | Status | Auth Mode |
|---------|--------|-----------|
| Blob upload | ✅ | Both |
| Blob download | ✅ | Both |
| Signed URL (Account Key SAS) | ✅ | Connection String |
| Signed URL (User Delegation SAS) | ✅ | Managed Identity |
| Lifecycle Policy | ✅ JSON + CLI | Manual apply |

**Path Schema**:
```
solvereign-artifacts/
└── tenant-{tenant_id}/
    └── site-{site_id}/
        ├── evidence_pack/
        │   └── {artifact_id}.json
        ├── solver_result/
        └── audit_report/
```

**Lifecycle Policy** (must apply via Azure CLI):
- Hot → Cool: 30 days
- Cool → Archive: 90 days
- Delete archived: 730 days (2 years)

```bash
./scripts/setup_azure_storage.sh <rg> <storage-account> westeurope
```

**NOT Implemented**:
- [ ] Archive tier rehydration endpoint
- [ ] Blob versioning (using lifecycle delete instead)

---

### ✅ Solver Run Persistence

| Field | Purpose | Required |
|-------|---------|----------|
| `input_hash` | Stops + vehicles + config | ✅ |
| `matrix_hash` | Travel time matrix | ✅ |
| `policy_hash` | Policy/constraint config | Optional |
| `output_hash` | Routes + unassigned | ✅ |
| `evidence_hash` | Evidence pack integrity | Optional |
| `seed` | RNG seed for reproducibility | ✅ |
| `workers` | Thread count (1 = deterministic) | ✅ |
| `determinism_mode` | deterministic/parallel/best_effort | ✅ |
| `routing_provider` | OSRM/Google/etc | Optional |

**Reproducibility Guarantee**:
Same `(input_hash, matrix_hash, policy_hash, seed, workers=1)` → Same `output_hash`

---

## What's NOT Implemented (Be Honest)

### ✅ Plan Versioning for Repair (IMPLEMENTED in V3.7.1!)

**NEW MODEL**:
- `plan_versions` = Working plan (modifiable)
- `plan_snapshots` = Immutable published versions

**Repair Flow**:
1. Dispatcher calls `POST /plans/{id}/repair` with reason
2. New `plan_versions` row created in DRAFT state
3. Original snapshot remains immutable
4. New plan goes through DRAFT → SOLVE → APPROVE → PUBLISH

**API Endpoints**:
- `POST /plans/{id}/publish` → Creates immutable snapshot
- `POST /plans/{id}/repair` → Creates new draft from snapshot
- `GET /plans/{id}/snapshots` → Version history
- `GET /plans/{id}/freeze-status` → Freeze window status

**DB Functions**:
- `publish_plan_snapshot()` → Creates immutable snapshot
- `create_repair_version()` → Creates repair plan from snapshot
- `get_snapshot_history()` → List all versions
- `is_plan_frozen()` → Check freeze window

---

### ⚠️ Freeze Window Enforcement (V3.7.2: Improved!)

`freeze_until` column exists with **conditional enforcement**:
- ✅ Publish during freeze: BLOCKED by default (HTTP 409)
- ✅ Force override: `force_during_freeze=true` + `force_reason` (min 10 chars)
- ✅ Audit trail: `forced_during_freeze` + `force_reason` columns in `plan_approvals`
- ✅ Repair create: ALLOWED (with warning logged)
- ⚠️ No background job checking freeze expiry
- ⚠️ UI must check `is_frozen` flag and show warning

### ❌ Evidence Archive Retrieval

Azure Archive tier has 15-hour rehydration time.
Currently: No endpoint to trigger rehydration.

Workaround: Access via Azure Portal or `az storage blob set-tier`

---

## Database State Verification

Run after migrations:

```sql
-- Check state machine integrity
SELECT * FROM verify_state_machine_integrity();

-- Expected: All PASS
-- check_name               | status | details
-- -------------------------+--------+---------
-- published_immutability   | PASS   | 0 plans modified after publish
-- publish_audit_trail      | PASS   | 0 published plans without audit record
-- unique_approve           | PASS   | 0 plans with duplicate APPROVE
-- unique_publish           | PASS   | 0 plans with duplicate PUBLISH
-- determinism_fields       | PASS   | 0 runs missing determinism_mode
```

---

## Environment Variables Required

### Backend (Python/FastAPI)

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/solvereign

# Entra ID / Azure AD
ENTRA_TENANT_ID=<azure-ad-tenant-id>
OIDC_AUDIENCE=api://<client-id>
OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0

# Azure Storage (choose one)
# Option A: Connection String (Pilot)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...

# Option B: Managed Identity (Production)
AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.windows.net
```

### Frontend (Next.js)

```bash
NEXT_PUBLIC_AZURE_AD_CLIENT_ID=<app-registration-client-id>
NEXT_PUBLIC_AZURE_AD_TENANT_ID=<azure-ad-tenant-id>
NEXT_PUBLIC_AZURE_AD_REDIRECT_URI=https://your-app.com
NEXT_PUBLIC_AZURE_AD_API_SCOPE=api://<client-id>/access_as_user
```

---

## Migration Order

```bash
# 1. Base tables (if not already applied)
psql $DATABASE_URL < backend_py/db/migrations/025e_final_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/025f_acl_fix.sql

# 2. Solver runs + state machine
psql $DATABASE_URL < backend_py/db/migrations/026_solver_runs.sql

# 3. Atomicity hardening
psql $DATABASE_URL < backend_py/db/migrations/026a_state_atomicity.sql

# 4. Plan Versioning (V3.7.1)
psql $DATABASE_URL < backend_py/db/migrations/027_plan_versioning.sql

# 5. Snapshot Fixes (V3.7.2)
psql $DATABASE_URL < backend_py/db/migrations/027a_snapshot_fixes.sql

# 6. Verify
psql $DATABASE_URL -c "SELECT * FROM verify_state_machine_integrity();"
psql $DATABASE_URL -c "SELECT * FROM verify_final_hardening();"
psql $DATABASE_URL -c "SELECT * FROM verify_snapshot_integrity();"
```

---

## Known Limitations (Pilot Phase)

1. **Account Key SAS**: Pilot uses connection string. Key rotation needed quarterly.
2. **No SSO Logout**: Clearing localStorage doesn't invalidate token at IdP.
3. **Archive Retrieval**: Manual process via Azure Portal.
4. **Freeze Window**: Advisory only, no hard enforcement (dispatcher discretion).

**RESOLVED in V3.7.1**:
- ~~No Plan Versioning~~ → `plan_snapshots` table + repair flow implemented!

**RESOLVED in V3.7.2**:
- ~~Empty snapshot payload~~ → `build_snapshot_payload()` populates real assignments/routes
- ~~Version race condition~~ → `FOR UPDATE` locking + unique constraint
- ~~Freeze bypass undocumented~~ → `force_during_freeze` param with audit trail

---

## Legacy Snapshot Handling (V3.7.2)

### What are Legacy Snapshots?

Snapshots created **before V3.7.2** have empty `assignments_snapshot` and `routes_snapshot` fields.
These are marked with `is_legacy: true` in the API response.

### Implications

| Scenario | Legacy (pre-V3.7.2) | Current (V3.7.2+) |
|----------|---------------------|-------------------|
| View snapshot KPIs | ✅ Works | ✅ Works |
| View assignments | ❌ Empty | ✅ Full data |
| Replay/Reconstruct | ❌ Not possible | ✅ Fully reproducible |
| Audit trail | ✅ Hashes intact | ✅ Hashes + payload |

### UI Warning Required

Frontend **MUST** check `is_legacy` flag and display warning:

```tsx
{snapshot.is_legacy && (
  <Alert severity="warning">
    This is a legacy snapshot from before V3.7.2.
    Assignment details are not available for reconstruction.
    KPIs and audit hashes are still valid.
  </Alert>
)}
```

### Backfill (Optional)

If original plan data still exists in `plan_assignments` table:

```sql
-- Dry run first
SELECT * FROM backfill_snapshot_payloads(TRUE);

-- If satisfied, execute
SELECT * FROM backfill_snapshot_payloads(FALSE);
```

**Note**: Backfill only updates SUPERSEDED/ARCHIVED snapshots, not ACTIVE ones.

---

## Production Checklist

### Infrastructure
- [ ] Switch to Managed Identity (remove connection string)
- [ ] Assign `Storage Blob Data Contributor` + `Storage Blob Delegator` roles
- [ ] Apply Azure lifecycle policy via CLI
- [ ] Configure Entra ID App Registration with correct redirect URIs
- [ ] Create App Roles: `Platform.Admin`, `Tenant.Admin`, `Approver`, `Dispatcher`, `Viewer`

### Database Verification
- [ ] Run `verify_state_machine_integrity()` - all PASS
- [ ] Run `verify_final_hardening()` - all PASS
- [ ] Run `verify_snapshot_integrity()` - all PASS (V3.7.2)
- [ ] Run `backfill_snapshot_payloads(TRUE)` - check legacy count

### Functional Tests
- [ ] Test full flow: Login → Solve → Approve → Publish → Download evidence
- [ ] Test repair flow: Publish → Repair → Solve → Approve → Publish (V3.7.1)

### Freeze Enforcement (V3.7.2)
- [ ] Freeze active + no force → HTTP 409
- [ ] Freeze active + force + not approver → HTTP 403
- [ ] Freeze active + force + approver + reason (10+ chars) → OK
- [ ] Verify `plan_approvals.forced_during_freeze` = TRUE in audit row
- [ ] UI shows warning for `is_legacy` snapshots
