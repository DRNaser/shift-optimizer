# SOLVEREIGN Release 1 - Readiness Pack

**Date**: 2026-01-13
**Commit**: `dafad8c9e210f91562c34cc7aa358666cb262929`
**Branch**: main
**Gate Status**: **GO×2** (2 consecutive passes)

---

## Executive Scorecard

| Category | Status | Evidence |
|----------|--------|----------|
| Backend Health | **PASS** | `curl localhost:8000/health/ready` → ready |
| Frontend Build | **PASS** | 59 pages built, 0 TypeScript errors |
| DB Schema Integrity | **PASS** | 7/7 checks via `auth.verify_schema_integrity()` |
| DB RBAC Integrity | **PASS** | 16/16 checks via `auth.verify_rbac_integrity()` |
| DB Roster Integrity | **PASS** | 13/13 checks via `roster.verify_roster_integrity()` |
| E2E Tests | **PASS** | 23/32 passed, 8 skipped (env-specific), 0 failed |
| Gate-Critical GO×2 | **PASS** | 2 consecutive runs (83s + 91.4s) |
| **CRITICAL BUG** | **FAIL** | Permission mismatch - see Risk #1 below |

---

## Part 1: Truth Inventory

### 1.1 Next.js Pages (43 Total)

| Route Group | Count | Critical Pages |
|-------------|-------|----------------|
| `(platform)` | 8 | `/platform/login`, `/platform-admin/*` |
| `(packs)` | 12 | `/packs/roster/workbench`, `/packs/roster/plans/[id]/matrix` |
| `/packs` (legacy) | 5 | `/packs/roster/repair` |
| `/my-plan` | 2 | Driver portal |
| API Routes | 16 | See BFF section |

### 1.2 BFF Routes (86 Total)

| Category | Count | Details |
|----------|-------|---------|
| Using `proxy.ts` | 37 | Centralized cookie/trace_id handling |
| Special Routes (Direct Fetch) | 6 | Auth login/logout, Portal session/ack/read |
| Static/Internal | 43 | Health checks, etc. |

**Special Routes (Justified)**:

| Route | Reason | File:Line |
|-------|--------|-----------|
| `/api/auth/login` | Set-Cookie passthrough | `app/api/auth/login/route.ts:29` |
| `/api/auth/logout` | Cookie clearing | `app/api/auth/logout/route.ts:32` |
| `/api/portal/session` | Magic link token exchange | `app/api/portal/session/route.ts:46` |
| `/api/portal/ack` | Portal cookie extraction | `app/api/portal/ack/route.ts:60` |
| `/api/portal/read` | Portal cookie extraction | `app/api/portal/read/route.ts:48` |

### 1.3 Cookie Handling

| Cookie | Domain | TTL | Secure | HttpOnly | Source |
|--------|--------|-----|--------|----------|--------|
| `__Host-sv_platform_session` | Production | 8h | true | true | `internal_rbac.py:54` |
| `sv_platform_session` | Development | 8h | false | true | `internal_rbac.py:57` |
| `admin_session` | Legacy fallback | 8h | varies | true | `internal_rbac.py:349` |
| `portal_session` | Driver portal | 60m | varies | true | `portal/session/route.ts:22-23` |

**Cookie extraction in proxy.ts:26-30**:
```typescript
const SESSION_COOKIE_NAMES = [
  '__Host-sv_platform_session', // Production (Secure, no Domain)
  'sv_platform_session',        // Development
  'admin_session',              // Legacy fallback
] as const;
```

---

## Part 2: Click-Flow Wiring Audit

### Flow A: Login

| Step | Component | Evidence | Status |
|------|-----------|----------|--------|
| UI | Login Form | `app/platform/login/page.tsx` | **OK** |
| BFF | POST `/api/auth/login` | `app/api/auth/login/route.ts:29` | **OK** |
| Backend | POST `/api/auth/login` | `backend_py/api/routers/auth.py:164` | **OK** |
| Cookie Set | `Set-Cookie` passthrough | `login/route.ts:42-48` | **OK** |
| E2E | `auth-flow.spec.ts:194` | "Login succeeds and redirects" | **PASS** |

### Flow B: Create Roster Run

| Step | Component | Evidence | Status |
|------|-----------|----------|--------|
| UI | Workbench Upload | `app/(packs)/roster/workbench/page.tsx` | **OK** |
| BFF | POST `/api/roster/runs` | `app/api/roster/runs/route.ts:51-58` | **OK** |
| Backend | POST `/api/v1/roster/runs` | `packs/roster/api/routers/runs.py:223` | **OK** |
| Permission | `roster.runs.write` | `runs.py:223` | **OK** |
| E2E | `roster-business-invariants.spec.ts` | Creates run | **PASS** |

### Flow C: View Matrix

| Step | Component | Evidence | Status |
|------|-----------|----------|--------|
| UI | Matrix Page | `app/(packs)/roster/plans/[id]/matrix/page.tsx` | **OK** |
| BFF | GET `/api/roster/plans/[id]/matrix` | `route.ts` uses `proxyToBackend` | **OK** |
| Backend | GET `/api/v1/roster/plans/{id}/matrix` | `lifecycle.py:281` | **OK** |
| Permission | `portal.summary.read` | `lifecycle.py:281` | **OK** |

### Flow D: Add/Remove Pins

| Step | Component | Evidence | Status |
|------|-----------|----------|--------|
| UI | Pin Button | Matrix cells | **OK** |
| BFF | POST/DELETE `/api/roster/plans/[id]/pins` | Uses `proxyToBackend` | **OK** |
| Backend | POST/DELETE `/api/v1/roster/pins` | `pins.py:264,439` | **OK** |
| Permission | `portal.approve.write` | **MISMATCH** - see Risk #1 | **RISK** |

### Flow E: Repair Session

| Step | Component | Evidence | Status |
|------|-----------|----------|--------|
| UI | Repair Page | `app/packs/roster/repair/page.tsx` | **OK** |
| BFF | POST `/api/roster/repairs/sessions` | Uses `proxyToBackend` | **OK** |
| Backend | POST `/api/v1/roster/repairs/sessions` | `repair_sessions.py:402-541` | **OK** |
| Concurrency | Advisory lock + unique check | `repair_sessions.py:461-496` | **OK** |
| 409 Handling | `SESSION_ALREADY_EXISTS` | `repair_sessions.py:488-496` | **OK** |
| 410 Handling | `SESSION_EXPIRED` | `repair_sessions.py:280-288` | **OK** |

### Flow F: Publish Snapshot

| Step | Component | Evidence | Status |
|------|-----------|----------|--------|
| UI | Publish Button | Workbench | **OK** |
| BFF | POST `/api/roster/snapshots/publish` | Uses `proxyToBackend` | **OK** |
| Backend | POST `/api/v1/roster/snapshots/publish` | `lifecycle.py:362` | **OK** |
| Permission | `portal.approve.write` | **MISMATCH** - see Risk #1 | **RISK** |

### Flow G: Lock Plan

| Step | Component | Evidence | Status |
|------|-----------|----------|--------|
| UI | Lock Button | Workbench | **OK** |
| BFF | POST `/api/roster/plans/[id]/lock` | `route.ts:62-71` | **OK** |
| Confirmation | Requires `confirm: true` | `route.ts:62-71` | **OK** |
| Backend | POST `/api/v1/roster/plans/{id}/lock` | `lifecycle.py:649` | **OK** |
| Permission | `portal.approve.write` | **MISMATCH** - see Risk #1 | **RISK** |
| Irreversibility | DB trigger blocks UPDATE/DELETE | Migration 027 | **OK** |

---

## Part 3: Top 10 Stability Risks

### Risk #1: CRITICAL - Permission Mismatch (P0)

**Impact**: Publish/Lock may fail for all non-platform_admin users

**Evidence**:
- Backend uses `portal.approve.write`: `lifecycle.py:362,649`, `pins.py:264,439`
- DB only has `plan.approve` and `plan.publish`: `039_internal_rbac.sql:296-297`
- Dispatcher permissions: `plan.view` only (`039_internal_rbac.sql:330-333`)
- operator_admin permissions: `plan.view, plan.publish, plan.approve` (`039_internal_rbac.sql:317-322`)

**Root Cause**: Code expects `portal.approve.write` but migration created `plan.approve`

**Fix Required**:
```sql
-- Option A: Add missing permission
INSERT INTO auth.permissions (key, display_name, description, category)
VALUES ('portal.approve.write', 'Approve Portal Actions', 'Publish/lock plans', 'portal')
ON CONFLICT DO NOTHING;

-- Grant to operator_admin, tenant_admin
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM auth.roles r, auth.permissions p
WHERE r.name IN ('operator_admin', 'tenant_admin') AND p.key = 'portal.approve.write'
ON CONFLICT DO NOTHING;

-- Option B: Change code to use plan.publish/plan.approve
```

**Workaround**: platform_admin bypasses all permission checks (`internal_rbac.py:717-725`)

---

### Risk #2: HIGH - No Backup Script

**Impact**: Data loss on DB failure

**Evidence**: No `scripts/backup.sh` exists

**Fix Required**: Create backup script before go-live

---

### Risk #3: MEDIUM - Repair Session TTL Hardcoded

**Impact**: Sessions expire in 30 minutes, not configurable

**Evidence**: `repair_sessions.py:448` - `timedelta(minutes=30)`

**Fix Required**: Make configurable via environment variable

---

### Risk #4: LOW - Legacy Cookie Fallback

**Impact**: Old sessions may still work after security update

**Evidence**: `admin_session` fallback in `proxy.ts:30`

**Recommendation**: Remove after migration window

---

### Risk #5: LOW - Portal Session Not Signed

**Impact**: Theoretical manipulation risk (low severity)

**Evidence**: Base64-encoded session in `portal/session/route.ts`

**Recommendation**: Sign with HMAC in future release

---

### Risk #6: LOW - E2E Tests Skip MSAL/Freeze

**Impact**: 8/32 tests skipped, may miss regressions

**Evidence**: `playwright.config.ts` skip conditions

**Recommendation**: Run full suite on staging with MSAL configured

---

### Risk #7: MEDIUM - Special Routes Error Handling

**Impact**: Direct fetch routes may not propagate trace_id consistently

**Evidence**: 6 special routes use direct `fetch()` instead of `proxyToBackend()`

**Verification**: All 6 have `!response.ok` checks - VERIFIED OK

---

### Risk #8: LOW - Zod Validation Coverage

**Impact**: Schema changes may cause runtime crashes

**Evidence**: Not all BFF routes use Zod validation

**Recommendation**: Add Zod to remaining routes incrementally

---

### Risk #9: LOW - Frontend Not Running in Forensic Report

**Impact**: Full E2E verification requires manual frontend start

**Evidence**: `FORENSIC_CURRENT_STATE_2026-01-13.md` shows frontend DOWN

**Workaround**: Run `cd frontend_v5 && npm run start -- -p 3002`

---

### Risk #10: MEDIUM - Mock Repository Permissions Mismatch

**Impact**: Unit tests may pass but production fails

**Evidence**: `internal_rbac.py:1308-1317` mock has `portal.approve.write` but DB doesn't

**Fix Required**: Sync mock with actual DB permissions

---

## Part 4: Decisions Needed (Defaults Provided)

| # | Decision | Default | Rationale |
|---|----------|---------|-----------|
| 1 | Cookie name (prod) | `__Host-sv_platform_session` | Already implemented |
| 2 | Session TTL | 8 hours | Already implemented |
| 3 | Publish policy | `operator_admin` + above can publish | Policy locked |
| 4 | Lock irreversibility | DB trigger enforced | Already implemented |
| 5 | Backup schedule | Daily 03:00 UTC | **NEEDS SCRIPT** |
| 6 | Repair session TTL | 30 minutes | Already implemented |
| 7 | Freeze window | Disabled initially | Per docs |
| 8 | Approver role name | `operator_admin` | No change needed |

---

## Part 5: Acceptance Tests / DoD

### Automated Gates (All Must Pass)

```powershell
# 1. Backend health
curl http://localhost:8000/health/ready
# Expected: {"status":"ready",...}

# 2. DB Invariants
docker compose -f docker-compose.pilot.yml exec postgres psql -U solvereign -d solvereign -c "SELECT * FROM auth.verify_rbac_integrity();"
# Expected: 16/16 PASS

# 3. TypeScript
cd frontend_v5 && npx tsc --noEmit
# Expected: 0 errors

# 4. Frontend Build
cd frontend_v5 && npm run build
# Expected: Exit 0

# 5. E2E Tests
cd frontend_v5 && npx playwright test
# Expected: 0 failures (skips OK)

# 6. Gate-Critical GO×2
.\scripts\gate-critical.ps1
.\scripts\gate-critical.ps1
# Expected: 2 consecutive GO
```

### Manual Smoke Tests

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1 | Login | Navigate to `/platform/login`, enter credentials | Redirect to dashboard |
| 2 | Tenant List | Navigate to `/platform-admin/tenants` | List renders |
| 3 | Create Run | Upload CSV, click Optimize | Run completes |
| 4 | View Matrix | Navigate to matrix view | Grid renders |
| 5 | Add Pin | Click cell, select pin type | Pin appears |
| 6 | Create Repair | Open repair page, create session | Session ID returned |
| 7 | Publish (as operator_admin) | Click Publish | **EXPECTED TO FAIL - Risk #1** |
| 8 | Lock (as operator_admin) | Click Lock with confirm | **EXPECTED TO FAIL - Risk #1** |

### Negative Path Tests

| # | Test | Expected Error |
|---|------|----------------|
| 1 | Login with bad password | 401 + "Invalid credentials" |
| 2 | Create second repair session | 409 + "SESSION_ALREADY_EXISTS" |
| 3 | Use expired session | 410 + "SESSION_EXPIRED" |
| 4 | Dispatcher publish | 403 + "Permission required" |
| 5 | Lock without confirm | 400 + "CONFIRMATION_REQUIRED" |

---

## Part 6: Next 5 Commits

### Commit 1: Fix Permission Mismatch (P0)

```sql
-- backend_py/db/migrations/052_fix_portal_approve_permission.sql
INSERT INTO auth.permissions (key, display_name, description, category)
VALUES ('portal.approve.write', 'Approve Portal Actions', 'Publish and lock plans', 'portal')
ON CONFLICT DO NOTHING;

INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM auth.roles r, auth.permissions p
WHERE r.name IN ('operator_admin', 'tenant_admin', 'platform_admin')
  AND p.key = 'portal.approve.write'
ON CONFLICT DO NOTHING;
```

### Commit 2: Create Backup Script

```bash
# scripts/backup.sh
#!/bin/bash
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-/var/backups/solvereign}"
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump -Fc solvereign > "${BACKUP_DIR}/solvereign_${DATE}.dump"
find "${BACKUP_DIR}" -name "*.dump" -mtime +90 -delete
```

### Commit 3: Add Repair TTL Config

```python
# backend_py/packs/roster/config_schema.py
REPAIR_SESSION_TTL_MINUTES = int(os.environ.get("REPAIR_SESSION_TTL_MINUTES", "30"))
```

### Commit 4: Sync Mock Permissions

Update `internal_rbac.py` MockRBACRepository to match actual DB permissions.

### Commit 5: E2E Test for Permission Check

Add Playwright test that verifies dispatcher gets 403 on publish attempt.

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Tech Lead | __________ | __________ | __________ |
| QA Lead | __________ | __________ | __________ |
| Product Owner | __________ | __________ | __________ |

---

**CRITICAL BLOCKER**: Risk #1 (Permission Mismatch) must be fixed before operator_admin can publish/lock.

---

*Generated: 2026-01-13 by Claude Code*
*Commit: dafad8c9e210f91562c34cc7aa358666cb262929*
*Gate Status: GO×2 (with P0 caveat)*
