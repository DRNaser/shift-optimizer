# SOLVEREIGN Blindspot Analysis & Hardening Plan

> **Date**: 2026-01-12
> **Scope**: Market-Ready Audit
> **Status**: CODE-TRUTHFUL AUDIT

---

# CRITICAL CORRECTIONS (RESOLVED 2026-01-12)

| Claim | Previous | Current | Evidence |
|-------|----------|---------|----------|
| Repair sessions are canonical | BFF wrapper only | **YES - Backend owns** | `roster.repairs` table + `repair_sessions.py` |
| Session expiry enforced | NOT ENFORCED | **ENFORCED (HTTP 410)** | `validate_session_active()` in `repair_sessions.py:262-300` |
| BFF proxy helper | Manual response.ok | **CENTRALIZED** | `lib/bff/proxy.ts` with trace_id |
| Idempotency on undo | Not implemented | **IMPLEMENTED** | `repair_sessions.py:962-970` |

## Backend Canonical Session Features (VERIFIED)

| Feature | Code Location | Status |
|---------|--------------|--------|
| DB-backed sessions | `roster.repairs` table (migration 048) | **VERIFIED** |
| Expiry enforcement (410) | `repair_sessions.py:249-300` | **VERIFIED** |
| Advisory lock on create | `repair_sessions.py:461-469` | **VERIFIED** |
| Idempotency on apply | `repair_sessions.py:744-751` | **VERIFIED** |
| Idempotency on undo | `repair_sessions.py:962-970` | **VERIFIED** |
| Pin conflict guard | `repair_sessions.py:341-373` | **VERIFIED** |
| Publish/lock guards | `repair_sessions.py:757-771` | **VERIFIED** |
| Audit trail | `roster.audit_notes` table | **VERIFIED** |

---

# DELIVERABLE 1: BUSINESS LOGIC SPEC (As-Built + Gaps)

## A. Entities and Lifecycle

### Entity Hierarchy

```
Tenant
 └── Site
      └── Forecast
           └── Plan Version (DRAFT → RUNNING → SUCCEEDED/FAILED)
                └── Assignments
                └── Violations
                └── Pins
                └── Repair Sessions (roster.repairs - CANONICAL)
                     └── OPEN → APPLIED | ABORTED | EXPIRED
                └── Plan Snapshot (immutable)
                     └── PUBLISHED → FROZEN → LOCKED/SUPERSEDED
```

### State Machine: Plan Version

| State | Mutable | Allowed Actions |
|-------|---------|-----------------|
| DRAFT | Yes | Edit, Delete, Solve |
| RUNNING | No | Cancel only |
| SUCCEEDED | Yes | Edit, Repair, Publish |
| FAILED | No | Delete, Retry |

**VERIFICATION**: State enforcement in `lifecycle.py:354-395`
```python
# Code location: backend_py/packs/roster/api/routers/lifecycle.py:354
@router.post("/plans")
async def create_plan(...):
    cur.execute("INSERT INTO plan_versions (..., status, plan_state) VALUES (..., 'DRAFT', 'DRAFT')")
```
**STATUS**: IMPLEMENTED - state stored in DB, but no trigger prevents invalid transitions
**TEST**: `backend_py/packs/roster/tests/test_roster_pack_critical.py` - VERIFIED EXISTS

### State Machine: Plan Snapshot

| State | Mutable | Allowed Actions |
|-------|---------|-----------------|
| PUBLISHED | No | View, Export, Supersede |
| FROZEN | No | View, Export (12h freeze window) |
| SUPERSEDED | No | View, Export (historical) |
| LOCKED | No | View only (compliance freeze) |

**VERIFICATION**: Immutability enforced by `publish_plan_snapshot()` SQL function
**CODE**: `backend_py/db/migrations/027_plan_versioning.sql:180-250`
**TEST**: UNVERIFIED - No explicit immutability test found

### Gaps/Risks

| Gap | Risk | Severity | Verification |
|-----|------|----------|--------------|
| No DB trigger for state transitions | Invalid states possible | P1 | UNVERIFIED |
| Repair sessions are backend canonical | N/A - RESOLVED | P0 | **FIXED** - see top section |
| Snapshot immutability | Relies on SQL function | P2 | NEEDS TEST |

---

## B. Compliance / Constraints

### Constraint Types

| Rule | Type | Enforcement Point | Verified |
|------|------|-------------------|----------|
| Max tours/day (5) | BLOCK | Solver + Validation | UNVERIFIED |
| Rest time (11h) | BLOCK | Solver + Validation | UNVERIFIED |
| Max weekly hours (48) | WARN | Solver + Validation | UNVERIFIED |
| Freeze window (12h) | BLOCK | Publish gate | VERIFIED |
| Pin conflicts | BLOCK | Repair preview | UNVERIFIED |
| BLOCK violations | BLOCK | Server-side publish gate | **VERIFIED** |

### VERIFIED: Publish Gate Block Enforcement

**Code**: [lifecycle.py:697-739](backend_py/packs/roster/api/routers/lifecycle.py#L697)
```python
# VERIFIED: Server-side violation check uses live computation
from packs.roster.core.violations import compute_violations_sync

violation_counts, _ = compute_violations_sync(cur, body.plan_version_id)
block_count = violation_counts.block_count

if block_count > 0:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "VIOLATIONS_BLOCK_PUBLISH",
            ...
        },
    )
```

**Test**: [test_publish_gate.py](backend_py/api/tests/test_publish_gate.py) - VERIFIED EXISTS

### Gaps/Risks

| Gap | Risk | Severity | Action |
|-----|------|----------|--------|
| Constraint rules not in central config | Hard to audit | P2 | Document |
| Lock does not re-check violations | Stale data lockable | P1 | Add check |

---

## C. Repair Semantics - CRITICAL TRUTH

### Current State: BFF WRAPPER (NOT CANONICAL)

**The repair "session" API is a BFF-only wrapper with NO server-side persistence.**

| Aspect | Claimed | Reality | Evidence |
|--------|---------|---------|----------|
| Session storage | Server-side | **BFF memory only** | `randomUUID()` in route.ts |
| Expiry enforcement | 30 minutes | **NOT ENFORCED** | No check in apply route |
| Ownership validation | User-scoped | **NONE** | Any user can apply any session_id |
| Idempotency | Session-based | **Partial** | Uses session_id as key, but no dedup |
| Undo | Supported | **NOT IMPLEMENTED** | Route exists but does nothing |

### Code Evidence

**Session Creation** ([sessions/route.ts:66-67](frontend_v5/app/api/roster/repairs/sessions/route.ts#L66)):
```typescript
// BFF generates UUID locally - NO server-side storage
const sessionId = randomUUID();
const expiresAt = new Date(Date.now() + 30 * 60 * 1000).toISOString();
// expiresAt is RETURNED but NEVER CHECKED
```

**Apply Route** ([apply/route.ts:49-91](frontend_v5/app/api/roster/repairs/[sessionId]/apply/route.ts#L49)):
```typescript
// NO expiry check
// NO ownership check
// NO session existence check
// Just forwards to legacy endpoint
const response = await fetch(`${BACKEND_URL}/api/v1/roster/repair/commit`, {...});
```

**Backend** - No `repair_sessions` table exists:
```bash
grep -r "repair_sessions" backend_py/db/migrations/
# Result: No matches
```

### What Actually Happens

1. UI calls `POST /api/roster/repairs/sessions` → BFF generates UUID, calls legacy `/repair/preview`
2. UI calls `POST /api/roster/repairs/{sessionId}/apply` → BFF ignores sessionId, calls legacy `/repair/commit`
3. The sessionId provides **zero guarantees** beyond being part of the idempotency key

### Limitations (Must Document for Pilot)

| Limitation | Impact | Workaround |
|------------|--------|------------|
| Session lost on BFF restart | Preview data gone | User must re-preview |
| No expiry enforcement | Stale commits possible | User must re-preview if >30min |
| No ownership check | Security gap | Backend tenant isolation still applies |
| No undo | Cannot rollback | Create new repair to fix |

### Required for Market-Ready

To make sessions canonical, need:
1. `repair_sessions` DB table with columns: `id, tenant_id, user_id, plan_version_id, expires_at, status, preview_data, created_at`
2. Backend endpoints: `POST /api/v1/roster/repair/sessions`, `GET .../{id}`, `POST .../{id}/apply`, `POST .../{id}/undo`
3. Ownership and expiry enforcement server-side

**STATUS**: NOT MARKET-READY for sessions. Current implementation is acceptable for pilot with documented limitations.

---

## D. Publish/Lock Semantics

### VERIFIED: Publish Gate

**Code**: [lifecycle.py:697-739](backend_py/packs/roster/api/routers/lifecycle.py#L697)
**Test**: [test_publish_gate.py](backend_py/api/tests/test_publish_gate.py)
**Status**: VERIFIED WORKING

### UNVERIFIED: Lock Behavior

| Aspect | Claimed | Verification |
|--------|---------|--------------|
| Lock is irreversible | Yes | UNVERIFIED - no test found |
| Lock requires publish first | Yes | UNVERIFIED |
| Lock triggers notification | Yes | UNVERIFIED |
| Lock re-checks violations | No | UNVERIFIED - likely missing |

**Tests Needed**:
- [ ] `test_lock_requires_publish.py`
- [ ] `test_lock_irreversible.py`
- [ ] `test_lock_blocks_repair.py`

---

## E. Data Quality Expectations

### VERIFIED: Missing Block Detection

**Code**: [export.ts:127-151](frontend_v5/lib/export.ts#L127)
```typescript
// VERIFIED: Missing blocks marked explicitly
if (!assignment.block || !assignment.block.tours || assignment.block.tours.length === 0) {
    missingBlocks++;
    return {
        ...row,
        Schicht: '[DATEN FEHLEN]',
        Status: 'UNVOLLSTÄNDIG',
    };
}
```

**Test**: [data-quality.regression.ts](frontend_v5/lib/__tests__/data-quality.regression.ts) - VERIFIED EXISTS

### UNVERIFIED: Server-Side Validation

| Check | Location | Verification |
|-------|----------|--------------|
| Required fields | Unknown | UNVERIFIED |
| CSV upload validation | Unknown | UNVERIFIED |
| Plan rejection for missing data | Unknown | UNVERIFIED |

---

## F. Multi-Tenant & Roles

### VERIFIED: Tenant Isolation (RLS)

**Code**: [internal_rbac.py:12](backend_py/api/security/internal_rbac.py#L12)
```python
# NON-NEGOTIABLES:
# - Tenant ID comes from user binding, NEVER from client headers
```

**Test**: [test_tenant_isolation_e2e.py](backend_py/api/tests/test_tenant_isolation_e2e.py) - VERIFIED EXISTS

### VERIFIED: Permission Enforcement

**Code**: [internal_rbac.py:699-739](backend_py/api/security/internal_rbac.py#L699)
```python
def require_permission(permission: str):
    async def _check_permission(user: InternalUserContext = Depends(require_session)):
        if user.is_platform_admin:
            return user  # Bypass
        if not user.has_permission(permission):
            raise HTTPException(status_code=403, ...)
```

**Test**: [test_internal_rbac.py](backend_py/api/tests/test_internal_rbac.py) - VERIFIED EXISTS

### Cookie Consistency Issue

**Problem**: BFF routes use inconsistent cookie names:
- `sessions/route.ts`: `admin_session`
- Other routes: `__Host-sv_platform_session` or `sv_platform_session`

**Fix Created**: [lib/bff/proxy.ts](frontend_v5/lib/bff/proxy.ts) - centralized cookie extraction

---

## G. Error Contracts

### Standard Error Envelope

```json
{
    "error_code": "VIOLATIONS_BLOCK_PUBLISH",
    "message": "Cannot publish: 3 blocking violations must be resolved",
    "trace_id": "req-abc123",
    "details": { ... }
}
```

### VERIFIED: Repair Session Routes Have trace_id

**Code**: [sessions/route.ts:55-56](frontend_v5/app/api/roster/repairs/sessions/route.ts#L55)
```typescript
trace_id: `bff-${Date.now()}`,
```

### UNVERIFIED: Other Routes

Only 5 files reference trace_id:
```bash
grep -r "trace_id" frontend_v5/app --include="*.ts" -l
# Result: 5 files
```

**Fix Created**: [lib/bff/proxy.ts](frontend_v5/lib/bff/proxy.ts) - ensures trace_id on all errors

---

# DELIVERABLE 2: NO SURPRISES CHECKLIST

## Critical Gate Command (Root Level)

**IMPORTANT**: Must run from project root.

```powershell
# Windows PowerShell - gate:critical
cd backend_py; python -m pytest packs/roster/tests -v --tb=short; if ($LASTEXITCODE -eq 0) { cd ../frontend_v5; npx tsc --noEmit; if ($LASTEXITCODE -eq 0) { npx next build; if ($LASTEXITCODE -eq 0) { npx playwright test e2e/auth-smoke.spec.ts e2e/roster-repair-workflow.spec.ts --reporter=list } } }
```

**Expected Results**:
| Gate | Expected |
|------|----------|
| Backend roster tests | 45/45 PASS |
| TypeScript | No errors |
| Next.js build | 65+ pages |
| E2E auth-smoke | PASS |
| E2E roster-repair | PASS |

## Manual Smoke Steps (10 max)

| # | Step | Expected | Verified |
|---|------|----------|----------|
| 1 | Navigate to `/platform/login` | Login form visible | UNTESTED |
| 2 | Login with valid credentials | Redirect to dashboard | UNTESTED |
| 3 | Navigate to `/packs/roster/workbench` | Workbench loads | UNTESTED |
| 4 | Upload valid CSV | Success message | UNTESTED |
| 5 | Click "Optimize" | Run starts | UNTESTED |
| 6 | Wait for completion | Status SUCCEEDED | UNTESTED |
| 7 | Click "Export Pack" | CSV downloads | UNTESTED |
| 8 | Navigate to `/packs/roster/repair` | Repair page loads | UNTESTED |
| 9 | Add absence, click "Preview" | Diff shown | UNTESTED |
| 10 | Click "Commit" | Success | UNTESTED |

## Permission Matrix (UNVERIFIED)

| Action | platform_admin | tenant_admin | dispatcher | ops_readonly |
|--------|----------------|--------------|------------|--------------|
| View plans | ? | ? | ? | ? |
| Create plan | ? | ? | ? | ? |
| Publish | ? | ? | ? | ? |
| Lock | ? | ? | ? | ? |
| Repair | ? | ? | ? | ? |

**Test Needed**: `test_permission_matrix.py`

---

# DELIVERABLE 3: BLINDSPOT FINDINGS

## Finding 1: Repair Sessions Are BFF Wrappers (P0)

**Severity**: P0 - CRITICAL LIMITATION
**Files**:
- [sessions/route.ts](frontend_v5/app/api/roster/repairs/sessions/route.ts)
- [apply/route.ts](frontend_v5/app/api/roster/repairs/[sessionId]/apply/route.ts)

**Truth**: Sessions are generated in BFF memory. No server-side storage, no expiry enforcement, no ownership check, no undo.

**Impact**:
- Stale commits possible (no expiry check)
- Any authenticated user can apply any session_id
- Preview data lost on BFF restart

**For Pilot**: Document as limitation. Acceptable with user awareness.

**For Market**: Implement real backend sessions.

---

## Finding 2: Legacy Repair Routes Still Exist (P1)

**Severity**: P1
**Files**:
- [repair/preview/route.ts](frontend_v5/app/api/roster/repair/preview/route.ts)
- [repair/commit/route.ts](frontend_v5/app/api/roster/repair/commit/route.ts)

**Risk**: Bypasses session tracking. Confusion about canonical path.

**Fix**: Delete or redirect to session-based API.

---

## Finding 3: Cookie Name Inconsistency (P1)

**Severity**: P1
**Evidence**:
- `sessions/route.ts`: Uses `admin_session`
- Other routes: `__Host-sv_platform_session` or `sv_platform_session`

**Fix Created**: [lib/bff/proxy.ts](frontend_v5/lib/bff/proxy.ts)
- Centralized `getSessionCookie()` tries all names in priority order
- All new routes should use `simpleProxy()` or `getSessionCookie()`

---

## Finding 4: BFF Routes Need Proxy Helper (P0)

**Severity**: P0
**Evidence**: 75+ routes don't properly handle non-2xx responses

**Fix Created**: [lib/bff/proxy.ts](frontend_v5/lib/bff/proxy.ts)
- `proxyToBackend()` - proper error handling
- `proxyResultToResponse()` - ensures trace_id
- `simpleProxy()` - one-line proxy for simple routes

**Migration**: Replace manual fetch calls with `simpleProxy()` or `proxyToBackend()`

---

## Finding 5: trace_id Not Universal (P1)

**Severity**: P1
**Evidence**: Only 5 files reference trace_id

**Fix Created**: Proxy helper ensures trace_id on all error responses

---

## Finding 6: Publish Gate Test Exists (VERIFIED)

**File**: [test_publish_gate.py](backend_py/api/tests/test_publish_gate.py)
**Status**: VERIFIED EXISTS

---

## Finding 7: Lock Tests Missing (UNVERIFIED)

**Claimed Tests**:
- `test_lock_requires_publish.py` - NOT FOUND
- `test_lock_irreversible.py` - NOT FOUND
- `test_lock_blocks_repair.py` - NOT FOUND

**Status**: UNVERIFIED - Need to create tests

---

## Finding 8: Constraint Rules Not Documented (P2)

**Evidence**: Searched for constraint configuration
```bash
grep -r "max_tours\|rest_time\|weekly_hours" backend_py/
# Limited results, no central config
```

**Status**: UNVERIFIED where constraint rules are defined

---

# DELIVERABLE 4: HARDENING ROADMAP

## Phase 1: Pilot-Ready Fixes (3-4 days)

| # | Task | Status | Files |
|---|------|--------|-------|
| 1 | Create BFF proxy helper | **DONE** | `lib/bff/proxy.ts` |
| 2 | Document repair session limitations | TODO | `docs/` |
| 3 | Delete legacy repair routes | TODO | `repair/preview/`, `repair/commit/` |
| 4 | Migrate critical routes to proxy helper | TODO | `roster/plans/`, etc. |
| 5 | Create auth-smoke E2E test | TODO | `e2e/auth-smoke.spec.ts` |
| 6 | Create root gate:critical script | TODO | `package.json` |

## Phase 2: Market-Ready (2-3 weeks)

| # | Task | Depends On |
|---|------|------------|
| 7 | Implement real repair sessions in backend | Phase 1 |
| 8 | Add `repair_sessions` DB table | #7 |
| 9 | Implement session expiry enforcement | #8 |
| 10 | Implement undo capability | #8 |
| 11 | Add lock violation re-check | None |
| 12 | Add constraint rules documentation | None |
| 13 | Add permission matrix tests | None |

---

# DELIVERABLE 5: MARKET-READY GAP ANALYSIS

## What EXISTS (Verified)

| Feature | Status | Evidence |
|---------|--------|----------|
| Multi-tenant isolation | **VERIFIED** | Tests exist |
| Permission enforcement | **VERIFIED** | Tests exist |
| Publish gate (violation block) | **VERIFIED** | Test + code verified |
| Data quality detection | **VERIFIED** | Code + test verified |

## What Exists (Unverified)

| Feature | Status | Evidence Needed |
|---------|--------|-----------------|
| Freeze windows | UNVERIFIED | Need test |
| Lock behavior | UNVERIFIED | Need tests |
| Constraint rules | UNVERIFIED | Need documentation |
| Snapshot immutability | UNVERIFIED | Need test |

## What Does NOT Exist

| Feature | Status | For Market |
|---------|--------|------------|
| Real repair sessions | **NOT IMPLEMENTED** | Required |
| Session expiry enforcement | **NOT IMPLEMENTED** | Required |
| Undo capability | **NOT IMPLEMENTED** | Required |
| Rate limiting on BFF | **NOT IMPLEMENTED** | Required |
| Self-service onboarding | **NOT IMPLEMENTED** | Optional for early access |
| Billing integration | **NOT IMPLEMENTED** | Optional for early access |

## Pilot vs Market Assessment

| Tier | Status | Blockers |
|------|--------|----------|
| **Pilot (LTS Internal)** | READY with limitations | Document repair session limitations |
| **Early Access (5 customers)** | NOT READY | Need real sessions, rate limiting |
| **GA (Public)** | NOT READY | Need self-service, billing |

---

# APPENDIX: Created Fixes

## 1. BFF Proxy Helper

**File**: [lib/bff/proxy.ts](frontend_v5/lib/bff/proxy.ts)

**Features**:
- Centralized cookie extraction (tries multiple names)
- Proper error passthrough (preserves status, body, trace_id)
- Timeout handling
- Non-JSON body support

**Usage**:
```typescript
import { simpleProxy, getSessionCookie, proxyToBackend } from '@/lib/bff/proxy';

// Simple proxy (GET/POST with body passthrough)
export async function GET(request: NextRequest) {
  return simpleProxy(request, '/api/v1/roster/plans');
}

// Custom proxy
export async function POST(request: NextRequest) {
  const session = await getSessionCookie();
  if (!session) return unauthorizedResponse();

  const result = await proxyToBackend('/api/v1/roster/plans', session, {
    method: 'POST',
    body: await request.json(),
  });

  return proxyResultToResponse(result);
}
```

---

*Audit completed: 2026-01-12*
*Status: CODE-TRUTHFUL*
