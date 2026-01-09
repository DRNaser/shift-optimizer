# SOLVEREIGN Frontend UI Requirements Blueprint

> **Generated**: 2026-01-07 (CORRECTED v6 - DECISIONS INCLUDED)
> **Scope**: frontend_v5 complete analysis
> **Status**: GROUNDED IN CODE - NO HALLUCINATION
> **Verification**: Every claim traceable to source file:line with grep/find
> **Decisions**: Platform fix, Scenario→Plan contract, PlanStatus derivation, /plans triad, Permission keys
> **Summary**: 4 Security Critical, 3 Critical Bugs, 2 Contract Blockers, 1 Type Mismatch

---

## CRITICAL BLOCKERS (v5)

| ID | Severity | Description | Impact |
|----|----------|-------------|--------|
| **S1** | 🔴 SECURITY CRITICAL | **27/32 routes have NO RBAC** | Any authenticated user can call solve/audit/evidence/repair |
| **S2** | 🔴 SECURITY CRITICAL | **27/32 routes have NO Idempotency** | Write operations not protected against duplicates |
| **S3** | 🔴 SECURITY CRITICAL | **4/5 guarded routes bypass blocked-tenant** | `checkPermission()` ignores isBlocked flag |
| **S4** | 🟠 HIGH | **BFF: No replay protection visible** (Backend: UNVERIFIED) | KEY-REQUIRED ≠ dedupe; BFF has no nonce store |
| **B1** | 🔴 CRITICAL BUG | Platform sidebar URLs **all 404** (repo: no rewrites; Infra/Proxy: UNVERIFIED) | Platform admin broken in repo state |
| **B2** | 🔴 CRITICAL BUG | `/plans` feature incomplete: Page missing + List API missing + RBAC undefined | Tenant nav has 404 link, no backend |
| **C1** | 🟠 CONTRACT BLOCKED | Scenario→Plan lookup **no BFF endpoint exists** (backend unknown) | Cannot wire Audit/Lock/Evidence tabs |
| **C2** | 🟠 CONTRACT BLOCKED | Reject import route **BFF missing** but UI calls it | Import reject button broken |
| **T1** | 🟠 TYPE MISMATCH | PlanStatus has 2 incompatible definitions (8 vs 14 states) | Runtime mapping required |

---

## SECURITY STATUS (v5 - HARD AUDIT)

> **Severity**: 🔴 **SECURITY CRITICAL** - 27/32 routes have NO security guards
> **Status**: Coverage gap must be closed before production

---

### CRITICAL DISTINCTIONS (v5)

#### RBAC Patterns - NOT Equivalent

| Pattern | Blocked-Tenant Check | Status Code | Error Body | Used In |
|---------|---------------------|-------------|------------|---------|
| `requirePermission()` | ✅ YES (503) | 403/503 | `{code, message, details}` | lock only |
| `checkPermission()` | ❌ NO | 403 | `{code, message}` | 4 routes |

**CRITICAL**: `checkPermission()` does NOT check `isBlocked` flag. Blocked tenant can still call freeze/import/validate/publish!

#### Idempotency Levels - NOT Equivalent

| Level | Behavior | Replay Protection | Used In |
|-------|----------|-------------------|---------|
| **KEY-REQUIRED** | 400 if header missing | ❌ NONE in BFF | All 5 routes |
| **REPLAY-PROTECTED** | Nonce store, dedupe | N/A | 0 routes (BFF) |

**BFF FINDING**: All 5 routes only check header presence. No dedupe/nonce logic visible in BFF code.
**BACKEND STATUS**: UNVERIFIED - Backend may or may not implement idempotency dedupe.
**RISK**: If backend also lacks dedupe, same request with same key will execute multiple times.

---

### FULL 32-ROUTE SECURITY COVERAGE TABLE

**Proof Commands**:
```bash
find frontend_v5/app/api -name "route.ts" | sort | wc -l
# Result: 32

grep -rn "requirePermission\|checkPermission" frontend_v5/app/api/
grep -rn "requireIdempotencyKey\|X-Idempotency-Key" frontend_v5/app/api/
```

#### GUARDED ROUTES (5 of 32)

| # | Route File | RBAC | Blocked Check | Idempotency | Lines |
|---|------------|------|---------------|-------------|-------|
| 1 | `plans/[planId]/lock/route.ts` | `requirePermission('lock:plan')` | ✅ YES | KEY-REQUIRED | :35, :42 |
| 2 | `plans/[planId]/freeze/route.ts` | `checkPermission(['APPROVER','TENANT_ADMIN'])` | ❌ NO | KEY-REQUIRED | :112, :120 |
| 3 | `teams/daily/import/route.ts` | `checkPermission(['PLANNER','APPROVER','TENANT_ADMIN'])` | ❌ NO | KEY-REQUIRED | :48, :56 |
| 4 | `teams/daily/[importId]/validate/route.ts` | `checkPermission(['PLANNER','APPROVER','TENANT_ADMIN'])` | ❌ NO | KEY-REQUIRED | :65, :73 |
| 5 | `teams/daily/[importId]/publish/route.ts` | `checkPermission(['APPROVER','TENANT_ADMIN'])` | ❌ NO | KEY-REQUIRED | :97, :105 |

#### UNGUARDED ROUTES (27 of 32) - 🔴 SECURITY CRITICAL

**Platform Routes (10) - NO GUARDS**:
| # | Route File | RBAC | Idempotency |
|---|------------|------|-------------|
| 6 | `platform/orgs/route.ts` | NONE | NONE |
| 7 | `platform/orgs/[orgCode]/route.ts` | NONE | NONE |
| 8 | `platform/orgs/[orgCode]/tenants/route.ts` | NONE | NONE |
| 9 | `platform/tenants/[tenantCode]/route.ts` | NONE | NONE |
| 10 | `platform/tenants/[tenantCode]/sites/route.ts` | NONE | NONE |
| 11 | `platform/tenants/[tenantCode]/entitlements/route.ts` | NONE | NONE |
| 12 | `platform/tenants/[tenantCode]/entitlements/[packId]/route.ts` | NONE | NONE |
| 13 | `platform/status/route.ts` | NONE | NONE |
| 14 | `platform/escalations/route.ts` | NONE | NONE |
| 15 | `platform/escalations/resolve/route.ts` | NONE | NONE |

**Tenant Routes (17) - NO GUARDS**:
| # | Route File | RBAC | Idempotency |
|---|------------|------|-------------|
| 16 | `tenant/me/route.ts` | NONE | NONE |
| 17 | `tenant/switch-site/route.ts` | NONE | NONE |
| 18 | `tenant/status/route.ts` | NONE | NONE |
| 19 | `tenant/status/details/route.ts` | NONE | NONE |
| 20 | `tenant/imports/route.ts` | NONE | NONE |
| 21 | `tenant/imports/[importId]/route.ts` | NONE | NONE |
| 22 | `tenant/imports/[importId]/validate/route.ts` | NONE | NONE |
| 23 | `tenant/imports/[importId]/accept/route.ts` | NONE | NONE |
| 24 | `tenant/scenarios/route.ts` | NONE | NONE |
| 25 | `tenant/scenarios/[scenarioId]/route.ts` | NONE | NONE |
| 26 | `tenant/scenarios/[scenarioId]/solve/route.ts` | NONE | NONE |
| 27 | `tenant/plans/[planId]/route.ts` | NONE | NONE |
| 28 | `tenant/plans/[planId]/audit/route.ts` | NONE | NONE |
| 29 | `tenant/plans/[planId]/evidence/route.ts` | NONE | NONE |
| 30 | `tenant/plans/[planId]/repair/route.ts` | NONE | NONE |
| 31 | `tenant/teams/daily/route.ts` | NONE | NONE |
| 32 | `tenant/teams/daily/check-compliance/route.ts` | NONE | NONE |

---

### MACHINE-VERIFIABLE ROUTE AUDIT

> **Purpose**: This section provides regeneratable proof commands. Run these to verify the 32-route table is current.

**Source of Truth Script** (run from repo root):
```bash
#!/bin/bash
# Generate current route inventory with guard markers

echo "=== ROUTE INVENTORY (Source of Truth) ==="
echo "Generated: $(date -I)"
echo ""

# List all routes
echo "### ALL ROUTES (32 expected)"
find frontend_v5/app/api -name "route.ts" | sort

echo ""
echo "### ROUTES WITH requirePermission (expected: 1)"
grep -l "requirePermission" $(find frontend_v5/app/api -name "route.ts") 2>/dev/null || echo "(none)"

echo ""
echo "### ROUTES WITH checkPermission (expected: 4)"
grep -l "checkPermission" $(find frontend_v5/app/api -name "route.ts") 2>/dev/null || echo "(none)"

echo ""
echo "### ROUTES WITH X-Idempotency-Key (expected: 5)"
grep -l "X-Idempotency-Key\|requireIdempotencyKey" $(find frontend_v5/app/api -name "route.ts") 2>/dev/null || echo "(none)"

echo ""
echo "### ROUTES WITH isBlocked CHECK (expected: 1 - only requirePermission)"
grep -l "isBlocked\|isWriteBlocked" $(find frontend_v5/app/api -name "route.ts") 2>/dev/null || echo "(none)"

echo ""
echo "### UNGUARDED ROUTES (no RBAC, no Idempotency)"
for route in $(find frontend_v5/app/api -name "route.ts" | sort); do
  if ! grep -q "requirePermission\|checkPermission\|X-Idempotency-Key\|requireIdempotencyKey" "$route" 2>/dev/null; then
    echo "$route"
  fi
done
```

**Expected Output** (current state):
```
ROUTES WITH requirePermission: 1 (lock/route.ts)
ROUTES WITH checkPermission: 4 (freeze, import, validate, publish)
ROUTES WITH X-Idempotency-Key: 5 (same 5)
ROUTES WITH isBlocked CHECK: 1 (only lock via requirePermission)
UNGUARDED ROUTES: 27
```

**Table Staleness Check**:
```bash
# If this returns different count than 32, table is stale
find frontend_v5/app/api -name "route.ts" | wc -l

# If these return different counts than documented, table needs update
grep -l "requirePermission" $(find frontend_v5/app/api -name "route.ts") 2>/dev/null | wc -l  # Expected: 1
grep -l "checkPermission" $(find frontend_v5/app/api -name "route.ts") 2>/dev/null | wc -l    # Expected: 4
```

---

### SECURITY GAPS SUMMARY

| Gap ID | Issue | Severity | Routes Affected | Scope |
|--------|-------|----------|-----------------|-------|
| **S1** | RBAC missing | 🔴 CRITICAL | 27/32 routes | BFF verified |
| **S2** | Idempotency missing | 🔴 CRITICAL | 27/32 routes | BFF verified |
| **S3** | Blocked-tenant bypass | 🔴 CRITICAL | 4/5 guarded routes | BFF verified |
| **S4** | No replay protection (BFF) | 🟠 HIGH | 5/5 routes with keys | Backend UNVERIFIED |

**Note**: S3 upgraded to CRITICAL - blocked-tenant bypass is a security vulnerability, not just a gap.

---

### S3 FIX PATH: Blocked-Tenant Bypass (P0)

> **Problem**: `checkPermission()` only checks role, not `isBlocked` flag.
> **Impact**: Blocked tenant (escalation active) can still call freeze/import/validate/publish.
> **Severity**: 🔴 P0 SECURITY - Must fix before production.

**DECISION REQUIRED - Choose One**:

| Option | Description | Effort | Recommendation |
|--------|-------------|--------|----------------|
| **A: Enforce requirePermission()** | Replace all `checkPermission()` calls with `requirePermission()` for write operations | Low | ✅ RECOMMENDED |
| **B: Extend checkPermission()** | Add `isBlocked` check inside `checkPermission()` and replace all usages | Medium | Alternative |

**Option A Implementation** (RECOMMENDED):
```typescript
// BEFORE (freeze/route.ts:112)
if (!checkPermission(userRole, ['APPROVER', 'TENANT_ADMIN'])) {
  return NextResponse.json({ code: 'FORBIDDEN' }, { status: 403 });
}

// AFTER - Replace with requirePermission helper
const permError = await requirePermission('freeze:plan');
if (permError) return permError;  // Returns 503 if blocked, 403 if no permission
```

**Files to Change**:
| File | Line | Current | Change To |
|------|------|---------|-----------|
| `freeze/route.ts` | 112 | `checkPermission()` | `requirePermission('freeze:plan')` |
| `teams/daily/import/route.ts` | 48 | `checkPermission()` | `requirePermission('teams:import')` |
| `teams/daily/[importId]/validate/route.ts` | 65 | `checkPermission()` | `requirePermission('teams:validate')` |
| `teams/daily/[importId]/publish/route.ts` | 97 | `checkPermission()` | `requirePermission('teams:publish')` |

**Verification After Fix**:
```bash
# Should return 0 matches (all replaced)
grep -rn "checkPermission" frontend_v5/app/api/
# Expected: 0 results

# Should return 5 matches (all writes use requirePermission)
grep -rn "requirePermission" frontend_v5/app/api/
# Expected: 5 results (lock, freeze, import, validate, publish)
```

---

### PERMISSION KEY CONSISTENCY (v5)

> **Purpose**: Define canonical permission key set. All keys must be consistent across BFF, UI, and types.

**CANONICAL PERMISSION KEYS** (Source of Truth):

| Key | Operation | BFF Route | UI Guard | Defined In |
|-----|-----------|-----------|----------|------------|
| `lock:plan` | Lock plan | `plans/[id]/lock` | ✅ requirePermission | tenant-rbac.ts |
| `freeze:plan` | Freeze plan | `plans/[id]/freeze` | ❌ Uses checkPermission | **NEEDS FIX** |
| `teams:import` | Import team data | `teams/daily/import` | ❌ Uses checkPermission | **NEEDS FIX** |
| `teams:validate` | Validate import | `teams/[id]/validate` | ❌ Uses checkPermission | **NEEDS FIX** |
| `teams:publish` | Publish import | `teams/[id]/publish` | ❌ Uses checkPermission | **NEEDS FIX** |
| `plans:list` | List plans | `plans/route.ts` | ❓ NOT DEFINED | **NEEDS DEFINITION** |
| `scenarios:read` | Read scenarios | `scenarios/route.ts` | ❓ NOT DEFINED | **NEEDS DEFINITION** |
| `scenarios:solve` | Trigger solve | `scenarios/[id]/solve` | ❓ NOT DEFINED | **NEEDS DEFINITION** |
| `plans:audit` | Run audit | `plans/[id]/audit` | ❓ NOT DEFINED | **NEEDS DEFINITION** |
| `plans:evidence` | Generate evidence | `plans/[id]/evidence` | ❓ NOT DEFINED | **NEEDS DEFINITION** |
| `plans:repair` | Create repair | `plans/[id]/repair` | ❓ NOT DEFINED | **NEEDS DEFINITION** |

**FORBIDDEN KEYS** (Must NOT appear):

| Forbidden Pattern | Reason |
|-------------------|--------|
| `APPROVER`, `TENANT_ADMIN` (role names) | Use permission keys, not roles |
| Inline role arrays `['APPROVER', 'PLANNER']` | Use permission key mapping |
| `checkPermission()` with raw roles | Replace with `requirePermission(key)` |

**Verification Command**:
```bash
# Check for forbidden patterns (should return 0 matches)
grep -rn "checkPermission.*\['APPROVER" frontend_v5/app/api/
grep -rn "checkPermission.*\['PLANNER" frontend_v5/app/api/
grep -rn "checkPermission.*\['TENANT_ADMIN" frontend_v5/app/api/
# Expected: 0 results after fix

# Check all permission keys are defined
grep -n "Permission.*=" frontend_v5/lib/tenant-rbac.ts
# Should list all canonical keys
```

**tenant-rbac.ts Requirements** (After Fix):
```typescript
// lib/tenant-rbac.ts - CANONICAL PERMISSION MAPPING
export const PERMISSION_KEYS = {
  // Plan operations
  'lock:plan': ['APPROVER', 'TENANT_ADMIN'],
  'freeze:plan': ['APPROVER', 'TENANT_ADMIN'],
  'plans:list': ['VIEWER', 'PLANNER', 'APPROVER', 'TENANT_ADMIN'],
  'plans:audit': ['APPROVER', 'TENANT_ADMIN'],
  'plans:evidence': ['APPROVER', 'TENANT_ADMIN'],
  'plans:repair': ['APPROVER', 'TENANT_ADMIN'],

  // Scenario operations
  'scenarios:read': ['VIEWER', 'PLANNER', 'APPROVER', 'TENANT_ADMIN'],
  'scenarios:solve': ['PLANNER', 'APPROVER', 'TENANT_ADMIN'],

  // Team operations
  'teams:import': ['PLANNER', 'APPROVER', 'TENANT_ADMIN'],
  'teams:validate': ['PLANNER', 'APPROVER', 'TENANT_ADMIN'],
  'teams:publish': ['APPROVER', 'TENANT_ADMIN'],
} as const;

export type PermissionKey = keyof typeof PERMISSION_KEYS;
```

---

## CORRECTIONS LOG (v4)

| Issue | Previous (v3) | Correction (v4) | Evidence |
|-------|---------------|-----------------|----------|
| #1 URL Structure | Routes are `/tenant/dashboard` | Routes are `/dashboard` (route group adds NO URL segment) | sidebar.tsx:57-72 |
| #2 Route Counts | "21 tenant" | **22 tenant, 10 platform, 32 total** | `find ... \| wc -l` |
| #3 RBAC Claims | "ONLY lock/route.ts:35" | **5 routes have RBAC** (2 patterns: `requirePermission`, `checkPermission`) | grep evidence |
| #4 Idempotency Claims | "ONLY lock/route.ts:42" | **5 routes have Idempotency** (1 helper + 4 manual checks) | grep evidence |
| #5 Scenario→Plan | "no endpoint exists" | **No BFF endpoint** (backend contract unknown) | See Section 3.8 |
| #6 PlanStatus | "AUDITED → AUDIT_PASS" | **AUDITED → use BFF aggregation or explicit loading state** (no async mapper) | See Section 3.7 |
| #7 Platform URLs | "all 404" | **Confirmed 404** - next.config.ts has NO `/platform/*` rewrites | next.config.ts:4-11 |
| #8 /plans page | Not checked | **BUG: `/plans` in sidebar but NO page exists** | glob returns 0 files |
| #9 Reject Route | Listed as capability | **BROKEN: Route does NOT exist** but UI calls it | No route.ts file |
| #10 Section 8.1 | "5 pages, 21/21 routes" | **4 pages, 32 routes exist** | Corrected |
| #11 "All BFF mock" | Claimed for all routes | **Only lock/route.ts proven** to have mock branch | Single example only |
| #12 Blocker Counts | "4 SECURITY CRITICAL" | **2 Critical Bugs, 2 Contract Blockers, 1 Type Mismatch** | Consistent taxonomy |

---

## Executive Summary

This document provides a complete, file-by-file analysis of the SOLVEREIGN frontend_v5 codebase. All requirements are derived directly from existing code.

**Tech Stack (from [package.json](../package.json))**:
- Next.js 16.1.1 (App Router)
- React 19.2.3
- TypeScript 5
- Tailwind CSS 4

**Key Architectural Patterns**:
- BFF (Backend-for-Frontend) with HMAC V2 signing
- Multi-tenant via `__Host-sv_tenant` HttpOnly cookie
- RBAC server-side enforcement (5 of 32 routes - see Security Status)
- Provider-based context hierarchy

**CRITICAL VERIFICATION NOTES**:
- Route group `(tenant)` does NOT add `/tenant/` to URLs - actual paths are `/dashboard`, `/scenarios`, etc.
- RBAC enforcement found in **5 of 32 routes** (2 patterns: `requirePermission()` helper, `checkPermission()` inline)
- Idempotency enforcement found in **5 of 32 routes** (1 helper + 4 manual header checks)
- See SECURITY STATUS section for full evidence

---

## SECTION 1: REPO INVENTORY

### 1.1 Configuration Files

| File | Lines | Purpose | Source |
|------|-------|---------|--------|
| `package.json` | ~50 | Dependencies, scripts | Root |
| `tsconfig.json` | ~30 | TypeScript configuration | Root |
| `tailwind.config.ts` | ~100 | Tailwind theme, CSS vars | Root |
| `next.config.ts` | ~30 | Next.js configuration | Root |
| `playwright.config.ts` | ~40 | E2E test configuration | Root |

### 1.2 App Directory Structure

```
frontend_v5/app/
├── layout.tsx                 # Root layout with Providers
├── globals.css                # CSS variables, Tailwind base
├── providers.tsx              # TenantProvider wrapper
├── (tenant)/                  # Tenant-scoped route group
│   ├── layout.tsx            # 111 lines - TenantStatusProvider + TenantErrorProvider
│   ├── dashboard/page.tsx    # Dashboard overview
│   ├── scenarios/page.tsx    # Scenario list
│   ├── scenarios/[id]/page.tsx  # 731 lines - Scenario detail with tabs
│   ├── imports/stops/page.tsx   # 413 lines - CSV import flow
│   ├── teams/daily/page.tsx     # 408 lines - 2-person enforcement
│   └── status/page.tsx          # 526 lines - Operational status
├── (platform)/               # Platform admin route group
│   ├── layout.tsx            # 59 lines - Dark theme admin layout
│   ├── orgs/page.tsx         # Organization list
│   ├── orgs/[orgCode]/page.tsx  # Org detail
│   ├── orgs/[orgCode]/tenants/[tenantCode]/page.tsx  # Tenant detail
│   └── escalations/page.tsx  # 632 lines - Platform escalations
└── api/                      # BFF API routes (32 endpoints)
```

### 1.3 BFF API Routes (32 Total - VERIFIED)

**Verification Command**:
```bash
find frontend_v5/app/api -name "route.ts" | wc -l
# Result: 32

find frontend_v5/app/api/tenant -name "route.ts" | wc -l
# Result: 22

find frontend_v5/app/api/platform -name "route.ts" | wc -l
# Result: 10
```

#### Tenant Routes (22 - CORRECTED from 21)

> **CRITICAL**: RBAC and Idempotency enforcement verified via grep for both patterns.
> - `requirePermission()` helper found in lock/route.ts:35
> - `checkPermission()` inline found in freeze/route.ts, teams/daily/*
> - `requireIdempotencyKey()` helper found in lock/route.ts:42
> - Manual `X-Idempotency-Key` check found in 4 additional routes
> - **5 of 32 routes have enforcement; 27 routes have NONE** (see Security Status section)

| Method | Route | RBAC Status | Idempotency Status | Source |
|--------|-------|-------------|-------------------|--------|
| GET | `/api/tenant/me` | - | - | [me/route.ts](../app/api/tenant/me/route.ts) |
| POST | `/api/tenant/switch-site` | UNVERIFIED | UNVERIFIED | [switch-site/route.ts](../app/api/tenant/switch-site/route.ts) |
| GET | `/api/tenant/status` | UNVERIFIED | - | [status/route.ts](../app/api/tenant/status/route.ts) |
| GET | `/api/tenant/status/details` | UNVERIFIED | - | [status/details/route.ts](../app/api/tenant/status/details/route.ts) |
| GET | `/api/tenant/imports` | UNVERIFIED | - | [imports/route.ts](../app/api/tenant/imports/route.ts) |
| POST | `/api/tenant/imports` | UNVERIFIED | UNVERIFIED | [imports/route.ts](../app/api/tenant/imports/route.ts) |
| GET | `/api/tenant/imports/[id]` | UNVERIFIED | - | [imports/[importId]/route.ts](../app/api/tenant/imports/[importId]/route.ts) |
| POST | `/api/tenant/imports/[id]/validate` | UNVERIFIED | UNVERIFIED | [validate/route.ts](../app/api/tenant/imports/[importId]/validate/route.ts) |
| POST | `/api/tenant/imports/[id]/accept` | UNVERIFIED | UNVERIFIED | [accept/route.ts](../app/api/tenant/imports/[importId]/accept/route.ts) |
| ~~POST~~ | ~~`/api/tenant/imports/[id]/reject`~~ | **GAP/BUG** | **GAP/BUG** | **ROUTE DOES NOT EXIST** - UI calls it (tenant-api.ts:406-414) |
| GET | `/api/tenant/teams/daily` | UNVERIFIED | - | [daily/route.ts](../app/api/tenant/teams/daily/route.ts) |
| GET | `/api/tenant/teams/daily/check-compliance` | UNVERIFIED | - | [check-compliance/route.ts](../app/api/tenant/teams/daily/check-compliance/route.ts) |
| POST | `/api/tenant/teams/daily/import` | **VERIFIED: checkPermission()** | **VERIFIED: Manual check** | [import/route.ts:48,56-59](../app/api/tenant/teams/daily/import/route.ts) |
| POST | `/api/tenant/teams/daily/[id]/validate` | **VERIFIED: checkPermission()** | **VERIFIED: Manual check** | [validate/route.ts:65,72-76](../app/api/tenant/teams/daily/[importId]/validate/route.ts) |
| POST | `/api/tenant/teams/daily/[id]/publish` | **VERIFIED: checkPermission()** | **VERIFIED: Manual check** | [publish/route.ts:97,104-108](../app/api/tenant/teams/daily/[importId]/publish/route.ts) |
| GET | `/api/tenant/scenarios` | UNVERIFIED | - | [scenarios/route.ts](../app/api/tenant/scenarios/route.ts) |
| POST | `/api/tenant/scenarios` | UNVERIFIED | UNVERIFIED | [scenarios/route.ts](../app/api/tenant/scenarios/route.ts) |
| GET | `/api/tenant/scenarios/[id]` | UNVERIFIED | - | [scenarios/[scenarioId]/route.ts](../app/api/tenant/scenarios/[scenarioId]/route.ts) |
| POST | `/api/tenant/scenarios/[id]/solve` | UNVERIFIED | UNVERIFIED | [solve/route.ts](../app/api/tenant/scenarios/[scenarioId]/solve/route.ts) |
| GET | `/api/tenant/plans/[id]` | UNVERIFIED | - | [plans/[planId]/route.ts](../app/api/tenant/plans/[planId]/route.ts) |
| GET | `/api/tenant/plans/[id]/audit` | UNVERIFIED | - | [audit/route.ts](../app/api/tenant/plans/[planId]/audit/route.ts) |
| POST | `/api/tenant/plans/[id]/audit` | UNVERIFIED | UNVERIFIED | [audit/route.ts](../app/api/tenant/plans/[planId]/audit/route.ts) |
| POST | `/api/tenant/plans/[id]/lock` | **VERIFIED: lock:plan** | **VERIFIED: Required** | [lock/route.ts:35,42](../app/api/tenant/plans/[planId]/lock/route.ts) |
| GET | `/api/tenant/plans/[id]/freeze` | UNVERIFIED | - | [freeze/route.ts](../app/api/tenant/plans/[planId]/freeze/route.ts) |
| POST | `/api/tenant/plans/[id]/freeze` | **VERIFIED: checkPermission()** | **VERIFIED: Manual check** | [freeze/route.ts:112,120-123](../app/api/tenant/plans/[planId]/freeze/route.ts) |
| GET | `/api/tenant/plans/[id]/evidence` | UNVERIFIED | - | [evidence/route.ts](../app/api/tenant/plans/[planId]/evidence/route.ts) |
| POST | `/api/tenant/plans/[id]/evidence` | UNVERIFIED | UNVERIFIED | [evidence/route.ts](../app/api/tenant/plans/[planId]/evidence/route.ts) |
| GET | `/api/tenant/plans/[id]/repair` | UNVERIFIED | - | [repair/route.ts](../app/api/tenant/plans/[planId]/repair/route.ts) |
| POST | `/api/tenant/plans/[id]/repair` | UNVERIFIED | UNVERIFIED | [repair/route.ts](../app/api/tenant/plans/[planId]/repair/route.ts) |

**Verification Evidence for RBAC/Idempotency**:
```bash
# Pattern 1: requirePermission helper
grep -rn "requirePermission" frontend_v5/app/api/
# Result: frontend_v5/app/api/tenant/plans/[planId]/lock/route.ts:35

# Pattern 2: checkPermission inline function
grep -rn "checkPermission" frontend_v5/app/api/
# Result: freeze/route.ts:112, teams/daily/import/route.ts:48,
#         teams/daily/[importId]/validate/route.ts:65, teams/daily/[importId]/publish/route.ts:97

# Pattern 1: requireIdempotencyKey helper
grep -rn "requireIdempotencyKey" frontend_v5/app/api/
# Result: frontend_v5/app/api/tenant/plans/[planId]/lock/route.ts:42

# Pattern 2: Manual X-Idempotency-Key header check
grep -rn "X-Idempotency-Key" frontend_v5/app/api/
# Result: freeze/route.ts:120-123, teams/daily/import/route.ts:56-59,
#         teams/daily/[importId]/validate/route.ts:72-76, teams/daily/[importId]/publish/route.ts:104-108
```

#### Platform Routes (10 - CORRECTED from 11)

| Method | Route | Purpose | Source |
|--------|-------|---------|--------|
| GET | `/api/platform/orgs` | List organizations | [orgs/route.ts](../app/api/platform/orgs/route.ts) |
| GET | `/api/platform/orgs/[orgCode]` | Org detail | [orgs/[orgCode]/route.ts](../app/api/platform/orgs/[orgCode]/route.ts) |
| GET | `/api/platform/orgs/[orgCode]/tenants` | Tenants in org | [tenants/route.ts](../app/api/platform/orgs/[orgCode]/tenants/route.ts) |
| GET | `/api/platform/tenants/[tenantCode]` | Tenant detail | [tenants/[tenantCode]/route.ts](../app/api/platform/tenants/[tenantCode]/route.ts) |
| GET | `/api/platform/tenants/[tenantCode]/sites` | Sites list | [sites/route.ts](../app/api/platform/tenants/[tenantCode]/sites/route.ts) |
| GET | `/api/platform/tenants/[tenantCode]/entitlements` | Pack entitlements | [entitlements/route.ts](../app/api/platform/tenants/[tenantCode]/entitlements/route.ts) |
| POST | `/api/platform/tenants/[tenantCode]/entitlements/[packId]` | Enable pack | [entitlements/[packId]/route.ts](../app/api/platform/tenants/[tenantCode]/entitlements/[packId]/route.ts) |
| GET | `/api/platform/status` | Platform health | [status/route.ts](../app/api/platform/status/route.ts) |
| GET | `/api/platform/escalations` | List escalations | [escalations/route.ts](../app/api/platform/escalations/route.ts) |
| POST | `/api/platform/escalations/resolve` | Resolve escalation | [resolve/route.ts](../app/api/platform/escalations/resolve/route.ts) |

### 1.4 Core Libraries

| File | Lines | Purpose | Key Exports |
|------|-------|---------|-------------|
| [lib/tenant-types.ts](../lib/tenant-types.ts) | ~200 | Type definitions | `Tenant`, `Site`, `User`, `PackId`, `TenantMeResponse` |
| [lib/tenant-api.ts](../lib/tenant-api.ts) | ~400 | Tenant API client | `tenantFetch`, `RoutingPlan`, `Scenario` |
| [lib/tenant-rbac.ts](../lib/tenant-rbac.ts) | 258 | RBAC enforcement | `requirePermission`, `getTenantContext`, `requireIdempotencyKey` |
| [lib/platform-api.ts](../lib/platform-api.ts) | ~200 | Platform API client | `platformFetch` |
| [lib/platform-auth.ts](../lib/platform-auth.ts) | ~100 | Platform auth helpers | `getResolvedByIdentifier` |
| [lib/hooks/use-tenant.ts](../lib/hooks/use-tenant.ts) | ~150 | Tenant context hook | `useTenant`, `usePacks`, `TenantProvider` |

### 1.5 Components

#### Layout Components

| File | Lines | Purpose | Key Exports |
|------|-------|---------|-------------|
| [components/layout/sidebar.tsx](../components/layout/sidebar.tsx) | 261 | Navigation sidebar | `Sidebar` |
| [components/layout/header.tsx](../components/layout/header.tsx) | 230 | Header with site selector | `Header` |
| [components/layout/site-selector.tsx](../components/layout/site-selector.tsx) | ~100 | Site dropdown | `SiteSelector` |
| [components/layout/platform-sidebar.tsx](../components/layout/platform-sidebar.tsx) | ~150 | Platform nav | `PlatformSidebar` |
| [components/layout/platform-header.tsx](../components/layout/platform-header.tsx) | ~100 | Platform header | `PlatformHeader` |

#### Tenant Components

| File | Lines | Purpose | Key Exports |
|------|-------|---------|-------------|
| [components/tenant/status-banner.tsx](../components/tenant/status-banner.tsx) | 315 | Status + write guard | `TenantStatusBanner`, `TenantStatusProvider`, `useTenantStatus`, `WriteGuard`, `BlockedButton` |
| [components/tenant/error-handler.tsx](../components/tenant/error-handler.tsx) | 439 | Error handling | `TenantErrorProvider`, `useTenantError`, `ErrorDisplay`, `ErrorModal`, `ErrorToast`, `GlobalErrorHandler` |

#### Platform Components

| File | Lines | Purpose | Key Exports |
|------|-------|---------|-------------|
| [components/platform/onboarding-wizard.tsx](../components/platform/onboarding-wizard.tsx) | ~300 | Tenant onboarding | `OnboardingWizard` |
| [components/platform/resolve-escalation-dialog.tsx](../components/platform/resolve-escalation-dialog.tsx) | 319 | Escalation resolution | `ResolveEscalationDialog`, `ResolveData` |

#### UI Components

| File | Lines | Purpose | Key Exports |
|------|-------|---------|-------------|
| [components/ui/button.tsx](../components/ui/button.tsx) | ~50 | Button component | `Button` |
| [components/ui/tabs.tsx](../components/ui/tabs.tsx) | ~100 | Tabs component | `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` |
| [components/ui/status-badge.tsx](../components/ui/status-badge.tsx) | ~50 | Status indicator | `StatusBadge` |
| [components/ui/kpi-cards.tsx](../components/ui/kpi-cards.tsx) | ~100 | KPI display | `KPICards` |
| [components/ui/matrix-view.tsx](../components/ui/matrix-view.tsx) | ~150 | Matrix visualization | `MatrixView` |
| [components/ui/live-console.tsx](../components/ui/live-console.tsx) | ~100 | Console output | `LiveConsole` |

#### Domain Components

| File | Lines | Purpose | Key Exports |
|------|-------|---------|-------------|
| [components/domain/roster-matrix.tsx](../components/domain/roster-matrix.tsx) | ~200 | Roster grid | `RosterMatrix` |
| [components/domain/pipeline-stepper.tsx](../components/domain/pipeline-stepper.tsx) | ~150 | Workflow steps | `PipelineStepper` |
| [components/domain/shift-pill.tsx](../components/domain/shift-pill.tsx) | ~80 | Shift display | `ShiftPill` |

### 1.6 E2E Tests

| File | Lines | Tests | Purpose |
|------|-------|-------|---------|
| [e2e/tenant-gates.spec.ts](../e2e/tenant-gates.spec.ts) | 426 | 25 | Hard gate enforcement |
| [e2e/tenant-happy-path.spec.ts](../e2e/tenant-happy-path.spec.ts) | ~200 | 15 | Full workflow validation |

### 1.7 Documentation

| File | Lines | Purpose |
|------|-------|---------|
| [SECURITY_ARCHITECTURE.md](../SECURITY_ARCHITECTURE.md) | 640 | Security design |
| [docs/PHASE2_TENANT_COCKPIT.md](../docs/PHASE2_TENANT_COCKPIT.md) | 366 | Phase 2 specification |

---

## SECTION 2: ROUTE MAP

### 2.1 Tenant Routes - CORRECTED

> **CRITICAL FIX**: `(tenant)` is a Next.js route group that does NOT add URL segments.
> Actual URLs are `/dashboard`, `/scenarios`, etc. - NOT `/tenant/dashboard`.

**From [sidebar.tsx:57-72](../components/layout/sidebar.tsx)**:
```typescript
// ACTUAL CODE - note hrefs do NOT include /tenant/
const NAV_ITEMS: NavSection[] = [
  {
    title: 'Core',
    items: [
      { label: 'Dashboard', href: '/dashboard', icon: LayoutDashboard, pack: 'core' },
      { label: 'Szenarien', href: '/scenarios', icon: FileText, pack: 'core' },
      { label: 'Pläne', href: '/plans', icon: Calendar, pack: 'core' },
    ],
  },
];
```

### 2.2 Route Hierarchy - CORRECTED

```
(tenant)/                        # Route group - NO URL segment added
├── /dashboard                   # Dashboard overview (NOT /tenant/dashboard)
├── /status                      # Operational status + escalations
├── /scenarios                   # Scenario list
├── /scenarios/[id]              # Scenario detail (4 tabs)
├── /imports/stops               # CSV import flow
└── /teams/daily                 # 2-person enforcement

(platform)/                      # Route group - NO URL segment added
├── /orgs                        # Organization list (NOT /platform/orgs)
├── /orgs/[orgCode]              # Org detail
├── /orgs/[orgCode]/tenants/[tenantCode]  # Tenant detail
└── /escalations                 # Platform-wide escalations
```

**Verification Command**:
```bash
grep -n "href:" frontend_v5/components/layout/sidebar.tsx | head -10
# Lines 57-72 show: href: '/dashboard', href: '/scenarios', href: '/plans'
# NO /tenant/ prefix in actual code!
```

### 2.3 Platform URL Bug - 🔴 CRITICAL

> **BUG CONFIRMED**: Platform sidebar uses `/platform/*` hrefs but route group `(platform)` adds NO URL segment.
> All 9 navigation items will 404!

**From [platform-sidebar.tsx:30-39](../components/layout/platform-sidebar.tsx)**:
```typescript
// ACTUAL CODE - hrefs use /platform/ prefix which is WRONG
const platformNavItems: NavItem[] = [
  { label: 'Dashboard', href: '/platform', icon: LayoutDashboard },        // ❌ 404
  { label: 'Organizations', href: '/platform/orgs', icon: Building2 },     // ❌ 404 (actual: /orgs)
  { label: 'Packs', href: '/platform/packs', icon: Package },              // ❌ 404 - NO PAGE EXISTS
  { label: 'Health', href: '/platform/health', icon: Activity },           // ❌ 404 - NO PAGE EXISTS
  { label: 'Escalations', href: '/platform/escalations', icon: AlertTriangle }, // ❌ 404 (actual: /escalations)
  { label: 'Audit Log', href: '/platform/audit-log', icon: Shield },       // ❌ 404 - NO PAGE EXISTS
  { label: 'API Keys', href: '/platform/api-keys', icon: Key },            // ❌ 404 - NO PAGE EXISTS
  { label: 'Metriken', href: '/platform/metrics', icon: BarChart3 },       // ❌ 404 - NO PAGE EXISTS
];
```

**Pages That Actually Exist** (verified via glob):
```bash
find frontend_v5/app/\(platform\) -name "page.tsx"
# Result: ONLY 4 pages
```

| Sidebar Href | Actual Page File | Actual URL | Status |
|--------------|------------------|------------|--------|
| `/platform` | NO PAGE | - | ❌ 404 |
| `/platform/orgs` | `(platform)/orgs/page.tsx` | `/orgs` | ❌ WRONG URL |
| `/platform/packs` | NO PAGE | - | ❌ 404 |
| `/platform/health` | NO PAGE | - | ❌ 404 |
| `/platform/escalations` | `(platform)/escalations/page.tsx` | `/escalations` | ❌ WRONG URL |
| `/platform/audit-log` | NO PAGE | - | ❌ 404 |
| `/platform/api-keys` | NO PAGE | - | ❌ 404 |
| `/platform/metrics` | NO PAGE | - | ❌ 404 |
| `/platform/settings` | NO PAGE | - | ❌ 404 |

**Fix Required**:
```typescript
// Option A: Fix sidebar hrefs (remove /platform/ prefix)
const platformNavItems: NavItem[] = [
  { label: 'Dashboard', href: '/', icon: LayoutDashboard },  // or create /platform page
  { label: 'Organizations', href: '/orgs', icon: Building2 },
  { label: 'Escalations', href: '/escalations', icon: AlertTriangle },
  // Remove items without pages
];

// Option B: Create platform subfolder structure
// Move app/(platform)/orgs → app/(platform)/platform/orgs
// This makes (platform) prefix the URL with /platform
```

**Middleware.ts Verification** (Task 4 Proof):
```bash
# Check if middleware.ts exists (could provide URL rewriting)
ls -la frontend_v5/middleware.ts 2>&1
# Result: FILE_NOT_FOUND - No middleware exists

# Verify no /platform rewrites anywhere
grep -rn '"/platform"' frontend_v5/next.config.ts frontend_v5/middleware.ts 2>/dev/null
# Result: No matches - no URL rewriting configured

# Only rewrite in next.config.ts is API proxy:
cat frontend_v5/next.config.ts
# Shows: source: "/api/:path*" → destination: "http://localhost:8000/api/:path*"
# NO /platform rewrite exists!
```

**Conclusion**: The 404 bug is CONFIRMED (in repo). There is:
1. NO `middleware.ts` file to handle URL rewriting
2. NO `/platform` rewrite in `next.config.ts`
3. Route group `(platform)` adds NO URL segment by Next.js design
4. Sidebar hrefs `/platform/*` will ALL 404
5. **UNVERIFIED**: Infra/Reverse-Proxy (Nginx/Ingress) rewrites not checked

---

### B1 FIX DECISION: Platform URL Architecture (P1)

> **DECISION REQUIRED**: Choose ONE approach. Both options open = plan uncertainty.

| Option | Description | Scope | Recommendation |
|--------|-------------|-------|----------------|
| **A: Fix Sidebar URLs** | Remove `/platform/` prefix, feature-flag missing pages | Sidebar only | ✅ RECOMMENDED (lowest effort) |
| **B: Create URL Namespace** | Restructure `app/(platform)/platform/...` to get `/platform/*` URLs | Folder restructure | Alternative (higher effort) |

**DECISION**: Option A (Recommended)

**Option A Implementation**:
```typescript
// platform-sidebar.tsx - FIXED VERSION
const platformNavItems: NavItem[] = [
  // EXISTING PAGES (4) - fix hrefs
  { label: 'Organizations', href: '/orgs', icon: Building2 },
  { label: 'Org Detail', href: '/orgs/[orgCode]', icon: Building2 },  // Dynamic
  { label: 'Tenant Detail', href: '/orgs/[orgCode]/tenants/[tenantCode]', icon: Building2 },  // Dynamic
  { label: 'Escalations', href: '/escalations', icon: AlertTriangle },

  // REMOVE THESE (no pages exist)
  // Dashboard, Packs, Health, Audit Log, API Keys, Metriken, Settings
];
```

**Files to Change**:
| File | Change |
|------|--------|
| `platform-sidebar.tsx` | Remove `/platform/` prefix from hrefs |
| `platform-sidebar.tsx` | Remove nav items for pages that don't exist |
| OR: Create missing pages | `/platform/dashboard`, `/platform/packs`, etc. (higher effort) |

**Verification After Fix**:
```bash
# All hrefs should match actual page routes
grep -n "href:" frontend_v5/components/layout/platform-sidebar.tsx
# Expected: '/orgs', '/escalations' (NOT '/platform/orgs')
```

---

### 2.4 Pack-Gated Navigation

From [sidebar.tsx:138-145](../components/layout/sidebar.tsx):
```typescript
// Filter nav items by enabled packs
const filteredSections = NAV_ITEMS.map((section) => ({
  ...section,
  items: section.items.filter((item) => {
    if (!item.pack || item.pack === 'core') return true;
    return enabledPacks.includes(item.pack);
  }),
})).filter((section) => section.items.length > 0);
```

---

## SECTION 3: STATE & DATA FLOW ARCHITECTURE

### 3.1 Provider Hierarchy

From [app/(tenant)/layout.tsx:41-49](../app/(tenant)/layout.tsx):
```typescript
<TenantErrorProvider>
  <TenantStatusProvider tenantCode={tenantCode} siteCode={siteCode}>
    <TenantLayoutContent>
      {children}
    </TenantLayoutContent>
  </TenantStatusProvider>
</TenantErrorProvider>
```

### 3.2 Context Providers

| Provider | Source | State | Exports |
|----------|--------|-------|---------|
| `TenantProvider` | [lib/hooks/use-tenant.ts](../lib/hooks/use-tenant.ts) | tenant, sites, user, currentSite, enabledPacks | `useTenant()`, `usePacks()` |
| `TenantStatusProvider` | [components/tenant/status-banner.tsx:99-165](../components/tenant/status-banner.tsx) | status, isLoading, isWriteBlocked | `useTenantStatus()` |
| `TenantErrorProvider` | [components/tenant/error-handler.tsx:95-156](../components/tenant/error-handler.tsx) | errors, showError, clearError | `useTenantError()` |

### 3.3 Tenant Status State Machine

From [status-banner.tsx:7-25](../components/tenant/status-banner.tsx):
```typescript
type OperationalStatus = 'healthy' | 'degraded' | 'blocked';

interface TenantStatus {
  tenant_code: string;
  site_code: string;
  status: OperationalStatus;
  is_write_blocked: boolean;
  blocked_reason: string | null;
  last_updated: string;
}
```

### 3.4 Error Classification

From [error-handler.tsx:20-55](../components/tenant/error-handler.tsx):
```typescript
type ErrorCode =
  | 'SESSION_EXPIRED'     // 401 - Redirect to login
  | 'PERMISSION_DENIED'   // 403 - RBAC violation
  | 'CONFLICT'            // 409 - Idempotency/stale data
  | 'SERVICE_UNAVAILABLE' // 503 - Tenant blocked
  | 'NETWORK_ERROR'       // Network failure
  | 'UNKNOWN';            // Catch-all

interface TenantError {
  id: string;
  code: ErrorCode;
  message: string;
  details?: string;
  timestamp: number;
  action?: { label: string; onClick: () => void };
}
```

### 3.5 Data Flow: Tenant Context

```
1. App Start
   └─> TenantProvider fetches /api/tenant/me
       └─> Returns { tenant, sites, user, enabled_packs, current_site_id }

2. Site Switch
   └─> POST /api/tenant/switch-site
       └─> Updates cookie sv_current_site
       └─> Triggers re-fetch of tenant context

3. Status Monitoring (30s interval)
   └─> TenantStatusProvider fetches /api/tenant/status
       └─> Updates isWriteBlocked flag
       └─> Triggers TenantStatusBanner visibility
```

### 3.6 Write Guard Pattern

From [status-banner.tsx:242-275](../components/tenant/status-banner.tsx):
```typescript
export function BlockedButton({
  children,
  onClick,
  disabled,
  ...props
}: BlockedButtonProps) {
  const { isWriteBlocked, blockedReason, openBlockedDialog } = useTenantStatus();

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (isWriteBlocked) {
      e.preventDefault();
      openBlockedDialog();
      return;
    }
    onClick?.(e);
  };

  return (
    <button
      {...props}
      onClick={handleClick}
      disabled={disabled}
      className={cn(
        props.className,
        isWriteBlocked && 'cursor-not-allowed opacity-60'
      )}
    >
      {children}
    </button>
  );
}
```

### 3.7 PlanStatus Definition - 🟠 MAPPING DECISION REQUIRED

> **CRITICAL BUG**: Two different PlanStatus definitions exist in the codebase that are NOT compatible.

**Definition 1: tenant-api.ts:314 (used by BFF API types)** - 8 states
```typescript
// From lib/tenant-api.ts:314
export interface RoutingPlan {
  status: 'QUEUED' | 'SOLVING' | 'SOLVED' | 'AUDITED' | 'DRAFT' | 'LOCKED' | 'FAILED' | 'SUPERSEDED';
}
```

**Definition 2: tenant-types.ts:220-234 (used by UI components)** - 14 states
```typescript
// From lib/tenant-types.ts:220-234
export type PlanStatus =
  | 'IMPORTED'       // Raw forecast imported
  | 'SNAPSHOTTED'    // Teams/vehicles snapshotted
  | 'SOLVING'        // Solver running
  | 'SOLVED'         // Solver complete, pending audit
  | 'FAILED'         // Solver failed
  | 'AUDIT_PASS'     // All audits passed
  | 'AUDIT_FAIL'     // One or more audits failed (can't lock)
  | 'LOCKED'         // Released for operations
  | 'FROZEN'         // Within freeze window (DB-enforced immutability)
  | 'REPAIRING'      // Repair in progress
  | 'REPAIRED'       // Repair complete, pending re-audit
  | 'RE_AUDIT'       // Re-audit after repair
  | 'RE_LOCKED'      // Re-locked after repair
  | 'SUPERSEDED';    // Replaced by newer version
```

**Mismatch Analysis**:

| Status | In tenant-api.ts (8) | In tenant-types.ts (14) | Mapping Decision |
|--------|---------------------|------------------------|------------------|
| QUEUED | ✅ Yes | ❌ No | → Map to `IMPORTED` or remove |
| SOLVING | ✅ Yes | ✅ Yes | ✅ Keep |
| SOLVED | ✅ Yes | ✅ Yes | ✅ Keep |
| AUDITED | ✅ Yes | ❌ No | → Map to `AUDIT_PASS` |
| DRAFT | ✅ Yes | ❌ No | → Drop (intermediate state) |
| LOCKED | ✅ Yes | ✅ Yes | ✅ Keep |
| FAILED | ✅ Yes | ✅ Yes | ✅ Keep |
| SUPERSEDED | ✅ Yes | ✅ Yes | ✅ Keep |
| IMPORTED | ❌ No | ✅ Yes | → Add to API or UI-only |
| SNAPSHOTTED | ❌ No | ✅ Yes | → Add to API or UI-only |
| AUDIT_PASS | ❌ No | ✅ Yes | ← Backend returns `AUDITED` |
| AUDIT_FAIL | ❌ No | ✅ Yes | → Add to API |
| FROZEN | ❌ No | ✅ Yes | → Add to API |
| REPAIRING | ❌ No | ✅ Yes | → Add to API |
| REPAIRED | ❌ No | ✅ Yes | → Add to API |
| RE_AUDIT | ❌ No | ✅ Yes | → Add to API |
| RE_LOCKED | ❌ No | ✅ Yes | → Add to API |

**DECISION REQUIRED - Choose One**:

> ⚠️ **ANTI-PATTERN**: Do NOT create async mapper that fetches in mapping function.
> Status mapping should be synchronous. Audit data must be fetched separately.

**Option A: BFF Aggregation (REQUIRES BFF + BACKEND)**
```typescript
// BFF route: GET /api/tenant/plans/[planId]
// Returns aggregated response with audit_summary
{
  "id": "plan-001",
  "status": "AUDITED",
  "audit_summary": {          // <-- BFF joins this data
    "all_passed": true,       // Backend must provide audit_summary
    "pass_count": 7,
    "fail_count": 0
  }
}

// UI then maps synchronously:
const uiStatus = plan.audit_summary?.all_passed ? 'AUDIT_PASS' : 'AUDIT_FAIL';
```

**Option B: Explicit UI Loading State**
```typescript
// UI shows AUDIT_UNKNOWN until audit loaded
type UIStatus = PlanStatus | 'AUDIT_UNKNOWN';

// Page loads plan first, then audit separately
const [plan, setPlan] = useState<RoutingPlan | null>(null);
const [auditResult, setAuditResult] = useState<AuditResult | null>(null);

const displayStatus = useMemo(() => {
  if (!plan) return 'LOADING';
  if (plan.status === 'AUDITED' && !auditResult) return 'AUDIT_UNKNOWN';
  if (plan.status === 'AUDITED' && auditResult) {
    return auditResult.all_passed ? 'AUDIT_PASS' : 'AUDIT_FAIL';
  }
  return plan.status;
}, [plan, auditResult]);
```

**Option C: Backend Returns All 14 States (REQUIRES BACKEND CHANGE)**
- Backend returns `AUDIT_PASS` or `AUDIT_FAIL` directly (not `AUDITED`)
- Frontend uses without mapping
- Cleanest solution but requires backend contract change

---

### T1 FIX DECISION: PlanStatus Source of Truth (REQUIRED)

> **DECISION REQUIRED**: Define canonical status derivation. UI must NOT guess status.

**DECISION**: UI Status is **DERIVED** (not 1:1 from backend)

**Canonical Derivation Function**:
```typescript
// lib/status-derivation.ts
// SOURCE OF TRUTH: UI status is derived from multiple backend fields

type UIPlanStatus =
  | 'IMPORTED' | 'SNAPSHOTTED' | 'SOLVING' | 'SOLVED'
  | 'AUDIT_PASS' | 'AUDIT_FAIL' | 'LOCKED' | 'FROZEN'
  | 'REPAIRING' | 'REPAIRED' | 'RE_AUDIT' | 'RE_LOCKED'
  | 'FAILED' | 'SUPERSEDED';

interface PlanWithContext {
  status: string;           // Backend status (8 values)
  audit_summary?: {         // Optional - from GET /plans/{id}/audit
    all_passed: boolean;
    pass_count: number;
    fail_count: number;
  };
  freeze_state?: {          // Optional - from GET /plans/{id}/freeze
    is_frozen: boolean;
    freeze_until: string;
  };
  repair_state?: {          // Optional - from repair context
    is_repairing: boolean;
    is_repaired: boolean;
  };
}

/**
 * CANONICAL DERIVATION FUNCTION
 * plan_status_ui = f(plan.status, audit_summary, freeze_state, repair_state)
 */
export function deriveUIStatus(plan: PlanWithContext): UIPlanStatus {
  // Priority 1: Terminal states
  if (plan.status === 'FAILED') return 'FAILED';
  if (plan.status === 'SUPERSEDED') return 'SUPERSEDED';

  // Priority 2: Repair states (if context available)
  if (plan.repair_state?.is_repairing) return 'REPAIRING';
  if (plan.repair_state?.is_repaired) return 'REPAIRED';

  // Priority 3: Freeze state (if context available)
  if (plan.freeze_state?.is_frozen) return 'FROZEN';

  // Priority 4: Audit-derived states
  if (plan.status === 'AUDITED' && plan.audit_summary) {
    return plan.audit_summary.all_passed ? 'AUDIT_PASS' : 'AUDIT_FAIL';
  }

  // Priority 5: Direct mapping for other states
  const directMap: Record<string, UIPlanStatus> = {
    'QUEUED': 'IMPORTED',      // Map QUEUED → IMPORTED
    'SOLVING': 'SOLVING',
    'SOLVED': 'SOLVED',
    'LOCKED': 'LOCKED',
    'DRAFT': 'SOLVED',         // DRAFT is intermediate, show as SOLVED
  };

  return directMap[plan.status] ?? 'SOLVING';  // Fallback
}
```

**Required Data Fetches Per Page**:
| Page | Data Needed | Fetch Calls |
|------|-------------|-------------|
| Scenario Detail | Plan + Audit | `GET /plans/{id}` + `GET /plans/{id}/audit` |
| Plan Detail | Plan + Audit + Freeze | `GET /plans/{id}` + `GET /plans/{id}/audit` + `GET /plans/{id}/freeze` |
| Plan List | Plans only | `GET /plans` (no derived status, show backend status) |

**Verification**:
```bash
# Ensure deriveUIStatus exists and is used
grep -rn "deriveUIStatus" frontend_v5/lib/
grep -rn "deriveUIStatus" frontend_v5/app/

# Ensure NO direct status comparison against AUDIT_PASS/AUDIT_FAIL without derivation
grep -rn "status.*===.*AUDIT_" frontend_v5/app/
# Expected: 0 matches (all should use deriveUIStatus)
```

---

### 3.8 Scenario → Plan Relationship - 🟠 BLOCKED BY CONTRACT

> **BLOCKER**: No **BFF endpoint** exists to fetch plans by scenario_id.
> Backend contract status: **UNKNOWN** (not verified).
> This blocks wiring of Audit, Lock, Evidence, and Repair tabs.

**From [tenant-api.ts:311-326](../lib/tenant-api.ts)**:
```typescript
export interface RoutingPlan {
  id: string;
  scenario_id: string;   // ← Links Plan to Scenario (1:N relationship)
  status: '...';
  // ...
}
```

**Data Flow (EXPECTED)**:
```
Scenario (CREATED)
    │
    └─> POST /solve → Creates Plan (SOLVING)
        │
        ├─> Plan.scenario_id = Scenario.id
        │
        └─> Plan status: SOLVING → SOLVED → AUDITED → LOCKED
```

**Current UI Implementation - BROKEN** (from [scenarios/[id]/page.tsx:530-539](../app/(tenant)/scenarios/[id]/page.tsx)):
```typescript
// ❌ HARDCODED - Cannot work with real data
const fetchPlan = useCallback(async () => {
  try {
    const res = await fetch(`/api/tenant/plans/plan-001`);  // ← HARDCODED ID!
    if (res.ok) {
      setPlan(await res.json());
    }
  } catch (err) {
    // No plan yet
  }
}, []);
```

**BFF Verification (VERIFIED - NOT FOUND)**:
```bash
# Check if scenario→plans BFF endpoint exists
find frontend_v5/app/api/tenant/scenarios -name "route.ts" -path "*plans*"
# Result: NO FILES FOUND

# Check if plans route supports query params
grep -n "scenario_id" frontend_v5/app/api/tenant/plans/route.ts 2>/dev/null
# Result: NO MATCHES (file does not exist - only [planId]/route.ts)
```

**Backend Verification: NOT PERFORMED**
- Backend may or may not support `GET /plans?scenario_id=X`
- Requires checking `backend_py/api/routers/plans.py`

**BLOCKERS CAUSED BY THIS**:

| Tab | Blocked Action | Why |
|-----|---------------|-----|
| Audit | Run Audit | Cannot get plan_id for scenario |
| Lock | Lock Plan | Cannot get plan_id for scenario |
| Evidence | Generate Evidence | Cannot get plan_id for scenario |
| Repair | Create Repair | Cannot get plan_id for scenario |

**FIX OPTIONS (ALL REQUIRE BFF + POTENTIALLY BACKEND)**:

**Option A: Add nested BFF endpoint (REQUIRES BFF + BACKEND)**
```typescript
// Create: app/api/tenant/scenarios/[scenarioId]/plans/route.ts
// ⚠️ Requires backend endpoint: GET /api/v1/tenants/{t}/sites/{s}/scenarios/{id}/plans
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ scenarioId: string }> }
) {
  const { scenarioId } = await params;
  const plans = await tenantFetch(`/scenarios/${scenarioId}/plans`);  // BACKEND REQUIRED
  return NextResponse.json(plans);
}
```

**Option B: Add query param to BFF plans endpoint (REQUIRES BFF + BACKEND)**
```typescript
// Create: app/api/tenant/plans/route.ts (does not exist yet)
// ⚠️ Requires backend support: GET /api/v1/.../plans?scenario_id=X
export async function GET(request: NextRequest) {
  const scenarioId = request.nextUrl.searchParams.get('scenario_id');
  const plans = await tenantFetch(`/plans?scenario_id=${scenarioId}`);  // BACKEND REQUIRED
  return NextResponse.json(plans);
}
```

**Option C: Return plan_id from solve response (REQUIRES BACKEND CHANGE)**
```typescript
// ⚠️ Requires backend to return plan_id in solve response
// POST /api/tenant/scenarios/[id]/solve response:
{
  "plan_id": "plan-abc123",  // ← UI stores this in state
  "status": "SOLVING"
}
// UI then uses stored plan_id for subsequent calls
```

---

### C1 CONTRACT DECISION: Scenario → Plan Lookup (REQUIRED)

> **DECISION REQUIRED**: Choose ONE minimal contract change. All options require backend change.

| Option | Contract Change | BFF Change | Backend Change | Recommendation |
|--------|----------------|------------|----------------|----------------|
| **A: Nested Endpoint** | `GET /scenarios/{id}/plans` | New route | New endpoint | Higher effort |
| **B: Query Param** | `GET /plans?scenario_id=X` | New route | Modify existing | Medium effort |
| **C: Solve Returns plan_id** | Solve response includes `plan_id` | None | Modify solve | ✅ RECOMMENDED |
| **D: Scenario DTO includes latest_plan_id** | GET scenario returns `latest_plan_id` | Modify existing | Modify scenario | Alternative |

**DECISION**: Option C or D (both low-effort)

**Option C Implementation** (RECOMMENDED):
```typescript
// Backend: POST /api/v1/.../scenarios/{id}/solve
// Response (CHANGE REQUIRED):
{
  "run_id": "run-abc123",
  "plan_id": "plan-abc123",   // ← ADD THIS FIELD
  "status": "SOLVING"
}

// UI stores plan_id from solve response
const handleSolve = async () => {
  const res = await fetch(`/api/tenant/scenarios/${scenarioId}/solve`, { method: 'POST' });
  const { plan_id } = await res.json();
  setPlanId(plan_id);  // Store for Audit/Lock/Evidence tabs
};
```

**Option D Implementation** (Alternative):
```typescript
// Backend: GET /api/v1/.../scenarios/{id}
// Response (CHANGE REQUIRED):
{
  "id": "scenario-123",
  "status": "SOLVED",
  "latest_plan_id": "plan-abc123"   // ← ADD THIS FIELD
}

// UI gets plan_id from scenario
const { latest_plan_id } = scenario;
```

**Verification Command**:
```bash
# After backend change, verify solve returns plan_id
curl -X POST /api/tenant/scenarios/test/solve | jq '.plan_id'
# Expected: non-null plan ID
```

---

## SECTION 4: UI CAPABILITIES (FUNCTIONAL REQUIREMENTS)

### 4.1 Stops Import Page

**Route**: `/imports/stops` (NOT `/tenant/imports/stops` - route group adds no segment)
**Source**: [imports/stops/page.tsx](../app/(tenant)/imports/stops/page.tsx)

**Capabilities**:
| Feature | Implementation | Lines |
|---------|---------------|-------|
| CSV drag-and-drop upload | `UploadDropzone` component | 210-276 |
| Validation error table | `ValidationErrorsTable` component | 63-101 |
| Import status badges | `ImportStatusBadge` (PENDING, VALIDATING, VALIDATED, ACCEPTED, REJECTED, FAILED) | 39-57 |
| Validate action | `handleValidate()` → POST `/api/tenant/imports/[id]/validate` | 329-337 |
| Accept action | `handleAccept()` → POST `/api/tenant/imports/[id]/accept` | 339-346 |
| Reject action | `handleReject()` → POST `/api/tenant/imports/[id]/reject` | 348-361 | **🔴 BROKEN: route.ts does NOT exist** |
| Blocked tenant guard | `isWriteBlocked` disables dropzone | 212, 217, 240 |

**Data Types** (from [tenant-api.ts](../lib/tenant-api.ts)):
```typescript
interface StopImportJob {
  id: string;
  filename: string;
  status: 'PENDING' | 'VALIDATING' | 'VALIDATED' | 'ACCEPTED' | 'REJECTED' | 'FAILED';
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  validation_errors: ValidationError[];
  created_at: string;
}

interface ValidationError {
  row: number;
  field: string;
  error_code: string;
  message: string;
}
```

### 4.2 Teams Daily Page

**Route**: `/teams/daily` (NOT `/tenant/teams/daily`)
**Source**: [teams/daily/page.tsx](../app/(tenant)/teams/daily/page.tsx)

**Capabilities**:
| Feature | Implementation | Lines |
|---------|---------------|-------|
| Date selector | `DateSelector` component | 237-294 |
| Team cards | `TeamCard` component | 67-151 |
| Demand status badges | `DemandStatusBadge` (MATCHED, MISMATCH_UNDER, MISMATCH_OVER) | 44-61 |
| Compliance summary | `ComplianceSummaryCard` component | 165-231 |
| Compliance check | `handleCheckCompliance()` → GET `/api/tenant/teams/daily/check-compliance` | 342-356 |

**2-Person Hard Gate** (from [teams/daily/page.tsx:6-9](../app/(tenant)/teams/daily/page.tsx)):
```
MISMATCH_UNDER = Stop requires 2-person but team has 1 => BLOCKS PUBLISH
MISMATCH_OVER = Team has 2 but stop only needs 1 => Warning only
```

### 4.3 Scenarios List Page

**Route**: `/scenarios` (NOT `/tenant/scenarios`)
**Source**: [scenarios/page.tsx](../app/(tenant)/scenarios/page.tsx)

**Capabilities**:
| Feature | Implementation |
|---------|---------------|
| Scenario list view | Fetches GET `/api/tenant/scenarios` |
| Create scenario | POST `/api/tenant/scenarios` with idempotency key |
| Status filtering | Filter by scenario status |
| Navigate to detail | Link to `/scenarios/[id]` |

### 4.4 Scenario Detail Page

**Route**: `/scenarios/[id]` (NOT `/tenant/scenarios/[id]`)
**Source**: [scenarios/[id]/page.tsx](../app/(tenant)/scenarios/[id]/page.tsx) (731 lines)

**Tabs**:
| Tab | Content | Lines |
|-----|---------|-------|
| Overview | Scenario info, KPIs, Solve button | ~100-200 |
| Audit | Audit results, Run Audit button | ~200-350 |
| Evidence | Evidence pack generation | ~350-500 |
| Repair | Repair creation, freeze state | ~500-650 |

**Actions**:
| Action | Function | API Call | RBAC |
|--------|----------|----------|------|
| Solve | `handleSolve()` | POST `/api/tenant/scenarios/[id]/solve` | PLANNER+ |
| Run Audit | `handleRunAudit()` | POST `/api/tenant/plans/[id]/audit` | PLANNER+ |
| Lock Plan | `handleLock()` | POST `/api/tenant/plans/[id]/lock` | **APPROVER+** |
| Generate Evidence | `handleGenerateEvidence()` | POST `/api/tenant/plans/[id]/evidence` | PLANNER+ |
| Create Repair | `handleCreateRepair()` | POST `/api/tenant/plans/[id]/repair` | PLANNER+ |

**Plan State Machine** (from [tenant-api.ts](../lib/tenant-api.ts)):
```typescript
type PlanStatus =
  | 'QUEUED'   // Solve requested
  | 'SOLVING'  // Solver running
  | 'SOLVED'   // Solver complete
  | 'AUDITED'  // Audits run
  | 'DRAFT'    // Ready for lock
  | 'LOCKED';  // Immutable
```

### 4.5 Status Page

**Route**: `/status` (NOT `/tenant/status`)
**Source**: [status/page.tsx](../app/(tenant)/status/page.tsx) (526 lines)

**Capabilities**:
| Feature | Component | Lines |
|---------|-----------|-------|
| Status indicator | `StatusIndicator` (healthy/degraded/blocked) | 92-131 |
| Severity badges | `SeverityBadge` (S0/S1/S2/S3) | 137-153 |
| Escalation cards | `EscalationCard` | 180-227 |
| Degraded services | `DegradedServiceCard` | 233-261 |
| Status history | `StatusHistoryTimeline` | 267-310 |
| Auto-refresh | 60-second interval | 339-341 |

**Escalation Types** (from [status/page.tsx:40-58](../app/(tenant)/status/page.tsx)):
```typescript
type EscalationSeverity = 'S0' | 'S1' | 'S2' | 'S3';
type EscalationStatus = 'OPEN' | 'ACKNOWLEDGED' | 'IN_PROGRESS' | 'RESOLVED';
```

### 4.6 Platform Escalations Page

**Route**: `/escalations` (NOT `/platform/escalations` - route group adds no segment)
**Source**: [escalations/page.tsx](../app/(platform)/escalations/page.tsx) (632 lines)

**Capabilities**:
| Feature | Implementation | Lines |
|---------|---------------|-------|
| Scope filter | platform/org/tenant/site dropdown | 321-337 |
| Severity filter | S0/S1/S2/S3 dropdown | 339-355 |
| Status filter | active/resolved/all dropdown | 357-371 |
| Resolve button | Opens `ResolveEscalationDialog` | 125-129 |
| Escalation cards | `EscalationCard` with expand/collapse | 463-631 |

**Resolution Dialog** (from [resolve-escalation-dialog.tsx:42-44](../components/platform/resolve-escalation-dialog.tsx)):
```typescript
// S0/S1: Type "RESOLVE" + mandatory comment (min 10 chars)
// S2/S3: Simple confirm + optional comment
const HIGH_SEVERITY = ['S0', 'S1'];
```

---

## SECTION 5: NON-FUNCTIONAL REQUIREMENTS

### 5.1 Security (from [SECURITY_ARCHITECTURE.md](../SECURITY_ARCHITECTURE.md))

| Requirement | Implementation | Source |
|-------------|---------------|--------|
| Trust Anchor | `__Host-sv_tenant` HttpOnly cookie | SECURITY_ARCHITECTURE.md:45-67 |
| HMAC Signing | `X-SV-Signature` header with V2 format | SECURITY_ARCHITECTURE.md:89-120 |
| Replay Protection | Nonce + 5min TTL in `core.used_signatures` | SECURITY_ARCHITECTURE.md:130-145 |
| RBAC Enforcement | Server-side via `requirePermission()` | lib/tenant-rbac.ts:176-190 |
| CSP | Strict Content-Security-Policy | SECURITY_ARCHITECTURE.md:250-280 |

### 5.2 RBAC Matrix

From [PHASE2_TENANT_COCKPIT.md:153-170](../docs/PHASE2_TENANT_COCKPIT.md):

| Permission | PLANNER | APPROVER | TENANT_ADMIN |
|------------|---------|----------|--------------|
| read:* | Yes | Yes | Yes |
| upload:* | Yes | Yes | Yes |
| validate:* | Yes | Yes | Yes |
| create:scenario | Yes | Yes | Yes |
| solve:scenario | Yes | Yes | Yes |
| audit:plan | Yes | Yes | Yes |
| create:repair | Yes | Yes | Yes |
| generate:evidence | Yes | Yes | Yes |
| **publish:teams** | No | Yes | Yes |
| **lock:plan** | No | Yes | Yes |
| **freeze:stops** | No | Yes | Yes |
| manage:tenant | No | No | Yes |

### 5.3 Idempotency

From [PHASE2_TENANT_COCKPIT.md:195-216](../docs/PHASE2_TENANT_COCKPIT.md):

**Key Format**:
```
{tenant_code}:{site_code}:{operation}:{identifiers...}
```

**Examples**:
| Operation | Key Format |
|-----------|------------|
| Upload stops | `lts-transport:wien:upload-import:stops_2026-01-07.csv` |
| Lock plan | `lts-transport:wien:lock-plan:plan-001` |
| Freeze stops | `lts-transport:wien:freeze-stops:plan-001:stop-001:stop-002` |

### 5.4 Error Handling

From [error-handler.tsx:158-250](../components/tenant/error-handler.tsx):

| HTTP Status | Error Code | User Action |
|-------------|------------|-------------|
| 401 | SESSION_EXPIRED | Redirect to login |
| 403 | PERMISSION_DENIED | Show modal with permission name |
| 409 | CONFLICT | Show toast with retry option |
| 503 | SERVICE_UNAVAILABLE | Show banner (tenant blocked) |
| Network | NETWORK_ERROR | Show toast with retry |

### 5.5 Accessibility - GROUNDED EVIDENCE

> **NOTE**: Only claims with file:line evidence included below.

**Verified Implementations**:

| Feature | File | Line | Evidence |
|---------|------|------|----------|
| aria-label on buttons | header.tsx | 49 | `aria-label="Menü öffnen"` |
| aria-label on buttons | header.tsx | 77 | `aria-label="Hilfe"` |
| aria-label on buttons | header.tsx | 88 | `aria-label="Benachrichtigungen"` |
| aria-label on buttons | header.tsx | 139 | `aria-label="Benutzermenü"` |
| Tabs role="tablist" | tabs.tsx | 65 | `role="tablist"` |
| Tab role="tab" | tabs.tsx | 88-89 | `role="tab"`, `aria-selected={isSelected}` |
| TabPanel role | tabs.tsx | 122 | `role="tabpanel"` |
| Site selector ARIA | site-selector.tsx | 113-115 | `aria-expanded`, `aria-haspopup="listbox"`, `aria-busy` |
| Listbox role | site-selector.tsx | 142 | `role="listbox"` |
| Escape to close dialog | resolve-escalation-dialog.tsx | 99-107 | `if (e.key === 'Escape' && !submitting) { onClose(); }` |

**Verification Command**:
```bash
grep -rn "aria-\|role=" frontend_v5/components/ | wc -l
# Shows actual ARIA attribute usage count
```

**UNVERIFIED Claims Removed**:
- Generic "keyboard nav" - no specific file:line evidence
- "Focus management" - no specific file:line evidence for autoFocus

---

## SECTION 6: COMPONENT CONTRACTS

### 6.1 TenantStatusProvider

**Source**: [status-banner.tsx:99-165](../components/tenant/status-banner.tsx)

**Props**:
```typescript
interface TenantStatusProviderProps {
  tenantCode: string;
  siteCode: string;
  children: React.ReactNode;
}
```

**Context Value**:
```typescript
interface TenantStatusContextValue {
  status: TenantStatus | null;
  isLoading: boolean;
  isWriteBlocked: boolean;
  blockedReason: string | null;
  refresh: () => void;
  openBlockedDialog: () => void;
}
```

**Behavior**:
- Fetches `/api/tenant/status` on mount
- Auto-refreshes every 30 seconds
- Sets `isWriteBlocked=true` when `status.status === 'blocked'`

### 6.2 TenantErrorProvider

**Source**: [error-handler.tsx:95-156](../components/tenant/error-handler.tsx)

**Props**:
```typescript
interface TenantErrorProviderProps {
  children: React.ReactNode;
}
```

**Context Value**:
```typescript
interface TenantErrorContextValue {
  errors: TenantError[];
  showError: (error: TenantError) => void;
  clearError: (id: string) => void;
  clearAllErrors: () => void;
}
```

### 6.3 BlockedButton

**Source**: [status-banner.tsx:242-275](../components/tenant/status-banner.tsx)

**Props**:
```typescript
interface BlockedButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
}
```

**Behavior**:
- If `isWriteBlocked=true`, prevents default click and opens blocked dialog
- Otherwise, passes through to normal click handler
- Applies `opacity-60` and `cursor-not-allowed` when blocked

### 6.4 ResolveEscalationDialog

**Source**: [resolve-escalation-dialog.tsx:49-316](../components/platform/resolve-escalation-dialog.tsx)

**Props**:
```typescript
interface ResolveEscalationDialogProps {
  escalation: {
    id: string;
    scope_type: 'platform' | 'org' | 'tenant' | 'site';
    scope_id: string | null;
    severity: 'S0' | 'S1' | 'S2' | 'S3';
    reason_code: string;
    reason_message: string;
  };
  onClose: () => void;
  onConfirm: (data: ResolveData) => Promise<void>;
}
```

**Validation Rules**:
- S0/S1: Must type "RESOLVE" + comment >= 10 chars
- S2/S3: Direct confirm allowed

---

## SECTION 7: TEST PLAN

### 7.1 E2E Test Coverage

From [e2e/tenant-gates.spec.ts](../e2e/tenant-gates.spec.ts):

| Gate | Tests | Status | Lines |
|------|-------|--------|-------|
| Gate 1: Blocked Tenant | 6 | Implemented | 49-123 |
| Gate 2: 2-Person UNDER | 4 | Implemented | 129-180 |
| Gate 3: 2-Person OVER | 4 | Implemented | 186-229 |
| Gate 4: 409 Conflict | 4 | Implemented | 235-287 |
| Gate 5: RBAC Enforcement | 5 | Implemented | 293-373 |
| Gate 6: Idempotency Key | 3 | Implemented | 380-425 |

### 7.2 Gate Test Details

**Gate 1: Blocked Tenant** ([tenant-gates.spec.ts:49-123](../e2e/tenant-gates.spec.ts)):
```typescript
test('should show 503 status banner when tenant is blocked')
test('should disable upload button when tenant is blocked')
test('should disable validate button when tenant is blocked')
test('should disable publish button when tenant is blocked')
test('should disable lock button when tenant is blocked')
test('API should return 503 for write operations when blocked')
```

**Gate 5: RBAC Enforcement** ([tenant-gates.spec.ts:293-373](../e2e/tenant-gates.spec.ts)):
```typescript
test('PLANNER should NOT be able to lock plan')  // Expects 403
test('PLANNER should NOT be able to publish teams')  // Expects 403
test('PLANNER should NOT be able to freeze stops')  // Expects 403
test('APPROVER should be able to lock plan')  // Expects NOT 403
test('TENANT_ADMIN should have all permissions')  // Expects NOT 403
```

**Gate 6: Idempotency Key** ([tenant-gates.spec.ts:380-425](../e2e/tenant-gates.spec.ts)):
```typescript
test('lock without idempotency key should return 400')
test('freeze without idempotency key should return 400')
test('publish without idempotency key should return 400')
// All expect: { code: 'MISSING_IDEMPOTENCY_KEY' }
```

### 7.3 Test Execution

From [PHASE2_TENANT_COCKPIT.md:296-309](../docs/PHASE2_TENANT_COCKPIT.md):
```bash
# Install Playwright
cd frontend_v5
npm install @playwright/test

# Run happy path
npx playwright test e2e/tenant-happy-path.spec.ts

# Run gate tests
npx playwright test e2e/tenant-gates.spec.ts

# Run all E2E
npx playwright test
```

---

## SECTION 8: IMPLEMENTATION ROADMAP

### 8.1 Current Status

| Component | Status | Evidence |
|-----------|--------|----------|
| Tenant Layout | Implemented | app/(tenant)/layout.tsx:111 lines |
| Status Banner | Implemented | components/tenant/status-banner.tsx:315 lines |
| Error Handler | Implemented | components/tenant/error-handler.tsx:439 lines |
| BFF Routes | **32 route.ts files exist** | `find app/api -name "route.ts" \| wc -l` |
| E2E Tests | 25+ Implemented | e2e/tenant-gates.spec.ts:426 lines |
| Platform Admin | **4 pages** (not 5) | `find app/(platform) -name "page.tsx"` |
| **Tenant `/plans` Page** | **🔴 MISSING** | sidebar.tsx has `/plans` but no page exists |

### 8.2 Mock vs Production

> **Note**: Only `lock/route.ts` has been verified to contain mock implementation. Other routes not verified.

**Verified Example** - [lock/route.ts:54-86](../app/api/tenant/plans/[planId]/lock/route.ts):
```typescript
// In production: Call backend - backend enforces audit gate
// const response = await tenantFetch<RoutingPlan>(
//   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/lock`,
//   { tenantCode, siteCode, method: 'POST', idempotencyKey }
// );

// MOCK: Simulate successful lock
const lockedPlan: RoutingPlan = {
  id: planId,
  status: 'LOCKED',
  // ...
};
```

**Unverified**: Whether other routes follow the same mock pattern has not been checked.

### 8.3 Production Readiness Checklist

From [PHASE2_TENANT_COCKPIT.md:313-351](../docs/PHASE2_TENANT_COCKPIT.md):

| Item | Status | Required For |
|------|--------|--------------|
| Apply migrations | Pending | Staging |
| Configure S3/Azure Blob | Pending | Evidence storage |
| Set `SOLVEREIGN_INTERNAL_SECRET` | Pending | HMAC signing |
| Configure tenant cookies | Pending | Auth flow |
| FLS Stops CSV Import test | Pending | Go/No-Go |
| TeamsDaily Flow test | Pending | Go/No-Go |
| Scenario Flow test | Pending | Go/No-Go |
| Audit + Lock test | Pending | Go/No-Go |
| Evidence Pack test | Pending | Go/No-Go |
| Repair Drill test | Pending | Go/No-Go |

---

## SECTION 9: WIRING MAP

### 9.1 Frontend → BFF → Backend

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Next.js)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Page Component                                                         │
│  ├─ useTenant() ─────────────────┐                                      │
│  ├─ useTenantStatus() ───────────┼─> Context Providers                  │
│  └─ useTenantError() ────────────┘                                      │
│                                                                         │
│  User Action (e.g., Lock Plan)                                          │
│  ├─ BlockedButton.onClick()                                             │
│  │   └─ if (isWriteBlocked) → openBlockedDialog() [STOP]               │
│  │   └─ else → continue                                                 │
│  └─ fetch('/api/tenant/plans/[id]/lock', {                             │
│       headers: { 'X-Idempotency-Key': '...' }                          │
│     })                                                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         BFF (Next.js API Routes)                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  /api/tenant/plans/[planId]/lock/route.ts                              │
│  │                                                                      │
│  ├─ 1. requirePermission('lock:plan')                                   │
│  │      └─ Returns 403 if PLANNER                                       │
│  │      └─ Returns 503 if tenant blocked                                │
│  │                                                                      │
│  ├─ 2. requireIdempotencyKey()                                          │
│  │      └─ Returns 400 if missing                                       │
│  │                                                                      │
│  ├─ 3. getTenantContext()                                               │
│  │      └─ Reads from __Host-sv_tenant cookie                           │
│  │                                                                      │
│  └─ 4. tenantFetch() → Backend                                          │
│         └─ Signs with HMAC V2                                           │
│         └─ Returns 409 if audit gate blocked                            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  POST /api/v1/tenants/{tenant}/sites/{site}/plans/{plan}/lock          │
│  │                                                                      │
│  ├─ Verify HMAC signature                                               │
│  ├─ Check idempotency key                                               │
│  ├─ Run audit gate check                                                │
│  │   └─ If FAIL audits exist → 409 AUDIT_GATE_BLOCKED                  │
│  ├─ Lock plan (status → LOCKED)                                         │
│  └─ Return locked plan                                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Error Flow

```
Backend Error (e.g., 403)
        │
        ▼
BFF catches and returns structured error
        │
        ▼
Page component receives error
        │
        ▼
useTenantError().showError({
  code: 'PERMISSION_DENIED',
  message: 'Lock requires APPROVER role'
})
        │
        ▼
GlobalErrorHandler renders ErrorModal
        │
        ▼
User sees "Permission Denied: lock:plan"
```

### 9.3 Status Refresh Flow

```
TenantStatusProvider mounts
        │
        ▼
fetch('/api/tenant/status') ─────────────────────┐
        │                                         │
        ▼                                         │
Update context: { status, isWriteBlocked }        │
        │                                         │
        ▼                                         │
setInterval(30000) ───────────────────────────────┘
        │
        ▼
TenantStatusBanner re-renders
        │
        ├─ status === 'healthy' → Hidden
        ├─ status === 'degraded' → Yellow banner
        └─ status === 'blocked' → Red banner + disables writes
```

---

## APPENDIX A: LINE COUNTS

| Category | Files | Total Lines |
|----------|-------|-------------|
| Pages | 7 | ~2,800 |
| API Routes | 32 | ~2,500 |
| Components | 18 | ~3,200 |
| Libraries | 6 | ~1,300 |
| E2E Tests | 2 | ~650 |
| Documentation | 2 | ~1,000 |
| **TOTAL** | **67** | **~11,450** |

---

## APPENDIX B: TYPE DEFINITIONS INDEX

| Type | Source | Usage |
|------|--------|-------|
| `Tenant` | lib/tenant-types.ts | Tenant entity |
| `Site` | lib/tenant-types.ts | Site entity |
| `User` | lib/tenant-types.ts | User entity |
| `PackId` | lib/tenant-types.ts | 'core' | 'routing' | 'forecasting' |
| `TenantMeResponse` | lib/tenant-types.ts | /api/tenant/me response |
| `RoutingPlan` | lib/tenant-api.ts | Plan entity |
| `Scenario` | lib/tenant-api.ts | Scenario entity |
| `StopImportJob` | lib/tenant-api.ts | Import job |
| `ValidationError` | lib/tenant-api.ts | Validation error |
| `TeamDailyAssignment` | lib/tenant-api.ts | Team assignment |
| `TenantStatus` | components/tenant/status-banner.tsx | Status state |
| `TenantError` | components/tenant/error-handler.tsx | Error state |
| `Escalation` | app/(tenant)/status/page.tsx | Escalation entity |

---

## VERIFICATION CHECKLIST - v4

| Claim | Source File | Line | Status |
|-------|-------------|------|--------|
| Next.js 16.1.1 | package.json | 12 | VERIFIED |
| React 19.2.3 | package.json | 13 | VERIFIED |
| **22 tenant API routes** | app/api/tenant/**/*.ts | - | VERIFIED |
| **10 platform API routes** | app/api/platform/**/*.ts | - | VERIFIED |
| **RBAC enforced in 5/32 routes** | lock, freeze, teams/daily/* | multiple | **VERIFIED (v4: 2 patterns found)** |
| **Idempotency enforced in 5/32 routes** | lock, freeze, teams/daily/* | multiple | **VERIFIED (v4: 2 patterns found)** |
| 30s status auto-refresh | status-banner.tsx | 127 | VERIFIED |
| S0/S1 requires "RESOLVE" | resolve-escalation-dialog.tsx | 42-44 | VERIFIED |
| 6 E2E gate tests | tenant-gates.spec.ts | 49-425 | VERIFIED |
| BlockedButton pattern | status-banner.tsx | 242-275 | VERIFIED |
| URL routes (NO /tenant/ prefix) | sidebar.tsx | 57-72 | VERIFIED |
| PlanStatus MISMATCH | tenant-api.ts vs tenant-types.ts | 314 vs 220-234 | **T1: TYPE MISMATCH** |
| Reject route MISSING | - | - | **C2: CONTRACT BLOCKED** |
| /plans page MISSING | - | - | **B3: CRITICAL BUG** |

---

## APPENDIX C: PROOF COMMANDS (v4)

**All verification commands for independent validation**:

```bash
# 1. Route Counts
find frontend_v5/app/api -name "route.ts" | wc -l
# Expected: 32

find frontend_v5/app/api/tenant -name "route.ts" | wc -l
# Expected: 22

find frontend_v5/app/api/platform -name "route.ts" | wc -l
# Expected: 10

# 2. RBAC Enforcement (5 routes, 2 patterns)
grep -rn "requirePermission" frontend_v5/app/api/
# Expected: lock/route.ts:35

grep -rn "checkPermission" frontend_v5/app/api/
# Expected: freeze/route.ts:112, teams/daily/import/route.ts:48,
#           teams/daily/[importId]/validate/route.ts:65, teams/daily/[importId]/publish/route.ts:97

# 3. Idempotency Enforcement (5 routes, 2 patterns)
grep -rn "requireIdempotencyKey" frontend_v5/app/api/
# Expected: lock/route.ts:42

grep -rn "X-Idempotency-Key" frontend_v5/app/api/
# Expected: freeze/route.ts:120-123, teams/daily/import/route.ts:56-59,
#           teams/daily/[importId]/validate/route.ts:72-76, teams/daily/[importId]/publish/route.ts:104-108

# 4. URL Structure (no /tenant/ prefix in tenant sidebar)
grep -n "href:" frontend_v5/components/layout/sidebar.tsx | head -10
# Expected: href: '/dashboard', href: '/scenarios', etc. (NO /tenant/)

# 5. Platform URL Bug (uses /platform/ prefix which will 404)
grep -n "href:" frontend_v5/components/layout/platform-sidebar.tsx
# Expected: /platform/orgs, /platform/escalations, etc. (WRONG - will 404)

# 6. No rewrites for /platform/*
grep -A 5 "rewrites" frontend_v5/next.config.ts
# Expected: Only /api/:path* rewrite, NO /platform/* rewrite

# 7. Reject Route Missing
ls frontend_v5/app/api/tenant/imports/\[importId\]/reject/route.ts 2>&1
# Expected: "No such file" - ROUTE DOES NOT EXIST

# 8. /plans Page Missing
find frontend_v5/app/\(tenant\) -path "*plans*" -name "page.tsx"
# Expected: 0 files - NO /plans page exists

# 9. PlanStatus Definitions (incompatible)
grep -n "status:" frontend_v5/lib/tenant-api.ts | grep -i plan
# Shows: 8 statuses

grep -n "PlanStatus =" frontend_v5/lib/tenant-types.ts
# Shows: 14 statuses (MISMATCH!)
```

---

## APPENDIX D: KNOWN GAPS AND BUGS (COMPREHENSIVE v4)

### 🔴 CRITICAL BUGS (App Broken)

| ID | Issue | Description | Evidence | Fix |
|----|-------|-------------|----------|-----|
| **B1** | Platform URLs 404 | Sidebar uses `/platform/*` but route group adds NO segment; next.config.ts has NO rewrites | platform-sidebar.tsx:30-39, next.config.ts | Fix hrefs to `/orgs`, `/escalations` |
| **B2** | 5 Platform Pages Missing | Sidebar has 9 nav items, only 4 pages exist | `find app/(platform) -name "page.tsx"` → 4 files | Create pages or remove nav items |
| **B3** | Tenant `/plans` 404 | Sidebar has `/plans` link but **no page exists** | `glob (tenant)/plans/**/page.tsx` → 0 files | See B2 FIX DECISION below |

---

### B2 FIX DECISION: /plans Feature Triad (P1)

> **Problem**: `/plans` is not just a "missing page" - it's a full feature gap.
> **Scope**: Page + List API + RBAC definition required.

| Component | Status | Evidence | Required Action |
|-----------|--------|----------|-----------------|
| **1. Page** | ❌ MISSING | `ls (tenant)/plans/page.tsx` → No file | Create `app/(tenant)/plans/page.tsx` |
| **2. List API (BFF)** | ❌ MISSING | `ls app/api/tenant/plans/route.ts` → Only `[planId]/` exists | Create `GET /api/tenant/plans` route |
| **3. List API (Backend)** | ❓ UNVERIFIED | Need to check `backend_py/api/routers/plans.py` | Verify `GET /plans` exists |
| **4. Read RBAC** | ❓ UNDEFINED | No permission key for `plans:list` | Define permission key for plan list |

**DECISION**: Implement in order: Backend verify → BFF route → Page

**Implementation Plan**:
```bash
# Step 1: Verify backend supports plan list
grep -rn "def.*list" backend_py/api/routers/plans.py
# Expected: GET endpoint for listing plans

# Step 2: Create BFF route
# app/api/tenant/plans/route.ts
export async function GET(request: NextRequest) {
  const plans = await tenantFetch('/plans');
  return NextResponse.json(plans);
}

# Step 3: Create page
# app/(tenant)/plans/page.tsx
# - Use existing StatusBadge, StatusConfig from tenant-types.ts
# - Add RBAC guard (same pattern as scenarios page)

# Step 4: Define RBAC permission
# lib/tenant-rbac.ts - add 'plans:list' permission
```

**Verification After Fix**:
```bash
# Page exists
ls frontend_v5/app/\(tenant\)/plans/page.tsx
# Expected: file exists

# BFF route exists
ls frontend_v5/app/api/tenant/plans/route.ts
# Expected: file exists (not just [planId]/)

# RBAC key exists
grep -n "plans:list" frontend_v5/lib/tenant-rbac.ts
# Expected: permission defined
```

---

### 🟠 CONTRACT BLOCKERS (Feature Not Wirable)

| ID | Issue | Description | Evidence | Fix |
|----|-------|-------------|----------|-----|
| **C1** | Scenario→Plan Lookup | **No BFF endpoint** to get plans by scenario_id (backend unknown) | `find app/api -name "route.ts" -path "*plans*"` in scenarios → 0 | Add BFF endpoint (may require backend) |
| **C2** | Reject Route Missing | UI calls `/api/tenant/imports/[id]/reject` but route doesn't exist | tenant-api.ts:406-414 calls it; no route.ts file | Create route or remove UI call |

### 🟠 TYPE MISMATCHES (Runtime Errors Likely)

| ID | Issue | Description | Evidence | Fix |
|----|-------|-------------|----------|-----|
| **T1** | PlanStatus Mismatch | API returns 8 states, UI expects 14 states | tenant-api.ts:314 vs tenant-types.ts:220-234 | Create async mapper with audit lookup (Section 3.7) |

### 🟡 SECURITY GAPS (Not Critical But Should Fix)

| ID | Issue | Description | Evidence | Fix |
|----|-------|-------------|----------|-----|
| **S1** | RBAC Coverage | 5/32 routes have RBAC checks; 27 routes have none | grep evidence (Section Security Status) | Add `checkPermission()` to remaining routes |
| **S2** | Idempotency Coverage | 5/32 routes have idempotency checks; 27 routes have none | grep evidence (Section Security Status) | Add header checks to remaining POST routes |

### 🟡 CODE QUALITY (Technical Debt)

| ID | Issue | Description | Evidence | Fix |
|----|-------|-------------|----------|-----|
| **Q1** | Plan Fetch Hardcoded | Scenario page fetches hardcoded `plan-001` | scenarios/[id]/page.tsx:533 | Use scenario→plan lookup (blocked by C1) |
| **Q2** | No Plan List BFF | `/api/tenant/plans/route.ts` doesn't exist (only `/plans/[id]`) | `ls app/api/tenant/plans/` → only `[planId]/` folder | Create plans list route |

---

## APPENDIX E: FIX PRIORITY MATRIX (v5)

| Priority | IDs | Effort | Impact |
|----------|-----|--------|--------|
| **P0 - SECURITY CRITICAL** | S1, S2, S3, S4 | Medium | 27/32 routes unguarded, blocked-tenant bypass, no replay protection |
| **P1 - Before Pilot** | B1, B2, B3, C1, C2, T1 | Low-Medium | Platform 404s, core workflows not wirable |
| **P2 - Tech Debt** | Q1, Q2 | Low | Code quality |

> **SECURITY CRITICAL (P0)**:
> - **S1**: 27/32 routes have NO security guards (RBAC, Idempotency, or Blocked check)
> - **S2**: 4/5 guarded routes use `checkPermission()` which does NOT check blocked-tenant flag
> - **S3**: 0/5 routes have actual replay protection (only key-required, no dedupe)
> - **S4**: Write operations can bypass escalation blocks in 4 routes
>
> These are security vulnerabilities, not just "gaps". Must fix before any external access.

---

## APPENDIX F: VERIFICATION COMMANDS (COMPLETE v5)

```bash
# === SECURITY VERIFICATION (COMPLETE) ===

# S1: RBAC enforcement - Pattern 1: requirePermission helper (FULL checks)
grep -rn "requirePermission" frontend_v5/app/api/
# RESULT: lock/route.ts:35 (ONLY 1 route uses full helper)

# S1: RBAC enforcement - Pattern 2: checkPermission inline (ROLE-ONLY, NO blocked check!)
grep -rn "checkPermission" frontend_v5/app/api/
# RESULT: freeze/route.ts:112, teams/daily/import/route.ts:48,
#         teams/daily/[importId]/validate/route.ts:65, teams/daily/[importId]/publish/route.ts:97
# WARNING: These 4 routes do NOT check isBlocked flag!

# S2: Idempotency - KEY-REQUIRED (NOT replay-protected!)
grep -rn "X-Idempotency-Key" frontend_v5/app/api/
# RESULT: 5 routes check header presence, but NONE dedupe/store nonces

# S3: Blocked-tenant bypass check
grep -rn "isBlocked\|isWriteBlocked" frontend_v5/app/api/
# RESULT: Only in requirePermission helper - 4/5 guarded routes skip this!

# TOTAL: 5/32 routes have RBAC, 5/32 have idempotency key check
#        1/5 guarded routes check blocked-tenant, 0/5 have replay protection

# === MIDDLEWARE VERIFICATION (Task 4) ===
ls -la frontend_v5/middleware.ts 2>&1
# RESULT: FILE_NOT_FOUND - No middleware exists

grep -rn '"/platform"' frontend_v5/next.config.ts 2>/dev/null
# RESULT: No matches - no /platform rewrite configured

# === PLATFORM URL BUG ===
# B1: Sidebar hrefs
grep -n "href:" frontend_v5/components/layout/platform-sidebar.tsx
# RESULT: Lines 31-39 show /platform/* hrefs

# B2: Actual platform pages
find frontend_v5/app/\(platform\) -name "page.tsx"
# RESULT: Only 4 files (orgs, orgs/[orgCode], tenants/[tenantCode], escalations)

# === /PLANS PAGE BUG (Task 6) ===
grep -n "'/plans'" frontend_v5/components/layout/sidebar.tsx
# RESULT: Line 72 shows href: '/plans'

ls frontend_v5/app/\(tenant\)/plans/page.tsx 2>&1
# RESULT: No such file or directory - PAGE DOES NOT EXIST

# === CONTRACT VERIFICATION ===
# C1: Scenario→Plan endpoint
find frontend_v5/app/api/tenant/scenarios -name "route.ts" -path "*plans*"
# RESULT: No files found

# C2: Reject route
ls frontend_v5/app/api/tenant/imports/\[importId\]/reject/route.ts 2>&1
# RESULT: No such file or directory

# === TYPE VERIFICATION ===
# T1: PlanStatus definitions
grep -A 10 "status:" frontend_v5/lib/tenant-api.ts | head -15
grep -A 20 "PlanStatus =" frontend_v5/lib/tenant-types.ts | head -25

# === ROUTE COUNTS ===
find frontend_v5/app/api -name "route.ts" | wc -l        # Expected: 32
find frontend_v5/app/api/tenant -name "route.ts" | wc -l # Expected: 22
find frontend_v5/app/api/platform -name "route.ts" | wc -l # Expected: 10
```

---

**Document Generated**: 2026-01-07 (CORRECTED v6 - DECISIONS INCLUDED)
**Grounded In**: frontend_v5 codebase analysis
**Verification**: All claims traceable to source file:line with grep/find commands
**Corrections Applied**: 9 corrections in v6 + 7 tasks in v5 + 12 issues from v4

**v6 Corrections**:
1. Replay-Protection: Changed to "BFF: no dedupe visible; Backend: UNVERIFIED"
2. middleware.ts: Changed to "repo: no rewrites; Infra/Proxy: UNVERIFIED"
3. S3 Blocked-Tenant-Bypass: Added as P0 with fix path (requirePermission everywhere)
4. 32-Route Table: Added machine-verifiable script for staleness detection
5. Platform-Fix: Added DECISION section (Option A recommended)
6. Scenario→Plan: Added CONTRACT DECISION (Option C/D recommended)
7. PlanStatus: Added SOURCE OF TRUTH derivation function
8. /plans Bug: Expanded to triad (Page + API + RBAC)
9. Permission Keys: Added canonical key set with forbidden patterns

**Issues Summary**:
- 4 Security Critical (S1-S4): 27/32 routes unguarded, blocked-tenant bypass, no BFF replay protection
- 3 Critical Bugs (B1-B3): Platform 404s, /plans feature incomplete
- 2 Contract Blockers (C1-C2): Scenario→Plan, Reject endpoint
- 1 Type Mismatch (T1): PlanStatus derivation required
