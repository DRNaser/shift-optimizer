# SOLVEREIGN Forensic Stabilization - FIXES APPLIED
> **Date**: 2026-01-12 | **Phase**: P0 + P1 Implementation

---

## Summary

| Priority | Fix | Status |
|----------|-----|--------|
| P0 | Fixed doubled API path in roster/runs BFF route | DONE |
| P0 | Migrated evidence route to use centralized proxy | DONE |
| P1 | Added Zod validation schemas for Platform Admin | DONE |
| P1 | Wired Zod validation into Tenants list page | DONE |
| P1 | Wired Zod validation into Users list page | DONE |

---

## Fix Details

### 1. Fixed Doubled API Path (P0 - CRITICAL)

**File**: `frontend_v5/app/api/roster/runs/route.ts`

**Issue**: API path was incorrectly doubled: `/api/v1/roster/api/v1/roster/runs`

**Lines Changed**: 52-53, 123-124

**Before**:
```typescript
const result = await proxyToBackend(
  `/api/v1/roster/api/v1/roster/runs?limit=${limit}&offset=${offset}`,
```

**After**:
```typescript
const result = await proxyToBackend(
  `/api/v1/roster/runs?limit=${limit}&offset=${offset}`,
```

**Impact**: This was causing roster workbench runs to fail with 404 errors.

---

### 2. Evidence Route Proxy Migration (P0)

**File**: `frontend_v5/app/api/evidence/route.ts`

**Issue**: Route was using raw `fetch()` with manual cookie handling instead of centralized proxy.

**Changes**:
- Replaced raw fetch with `proxyToBackend()` from `@/lib/bff/proxy`
- Added proper `traceId` generation
- Now uses standard error envelope from proxy

**Before** (47 lines):
```typescript
const cookieStore = await cookies();
const sessionCookie = cookieStore.get('__Host-sv_platform_session') || ...
// manual fetch and error handling
```

**After** (47 lines):
```typescript
import { getSessionCookie, proxyToBackend, ... } from '@/lib/bff/proxy';
// centralized proxy usage
const result = await proxyToBackend(path, session, { method: 'GET', traceId });
return proxyResultToResponse(result);
```

**Impact**: Now returns consistent error envelope with trace_id, matches other BFF routes.

---

### 3. Platform Admin Zod Schemas (P1)

**File**: `frontend_v5/lib/schemas/platform-admin-schemas.ts` (NEW)

**Created schemas**:
- `TenantSchema` - validates tenant objects
- `TenantListResponseSchema` - validates tenant array response
- `UserSchema` - validates user objects
- `UserListResponseSchema` - validates user array response
- `SiteSchema`, `RoleSchema`, `PermissionSchema` - additional types

**Helper functions**:
- `parseTenantListResponse()` - safe parsing with fallback to empty array
- `parseUserListResponse()` - safe parsing with fallback to empty array
- `parseSiteListResponse()`, `parseRoleListResponse()` - additional helpers

---

### 4. Tenants Page Validation (P1)

**File**: `frontend_v5/app/(platform)/platform-admin/tenants/page.tsx`

**Changes**:
- Added import: `import { parseTenantListResponse, type Tenant } from '@/lib/schemas/platform-admin-schemas'`
- Removed local `Tenant` interface (now uses Zod-inferred type)
- Added validation call: `const validated = parseTenantListResponse(data);`

**Line**: 47-50

---

### 5. Users Page Validation (P1)

**File**: `frontend_v5/app/(platform)/platform-admin/users/page.tsx`

**Changes**:
- Added imports: `parseUserListResponse, parseTenantListResponse, type User, type Tenant`
- Added validation calls on lines 54-55
- Removed local `User` and `Tenant` interfaces (partial - UserBinding kept for display)

---

## Regression Tests

The following E2E tests should verify these fixes:

| Test File | Covers |
|-----------|--------|
| `e2e/auth-flow.spec.ts` | Platform admin navigation (no login loops) |
| `e2e/platform-tenants-sites.spec.ts` | Tenant list loads correctly |
| `e2e/roster-repair-workflow.spec.ts` | Roster operations work |

### Manual Verification Steps

1. **Roster Runs Path Fix**:
   ```bash
   # Start backend and frontend
   # Navigate to /packs/roster/workbench
   # Upload CSV and click Optimize
   # Should NOT get 404 error
   ```

2. **Evidence Route**:
   ```bash
   # Make request to /api/evidence
   # Should return { success: true, ... } or { error_code, message, trace_id }
   ```

3. **Platform Admin Validation**:
   ```bash
   # Navigate to /platform-admin/tenants
   # Should load without errors even if backend returns unexpected fields
   # Check browser console for "[VALIDATION]" warnings on malformed data
   ```

---

## Commands to Run Gate

```powershell
# Full gate (requires backend + E2E credentials)
.\scripts\gate-critical.ps1

# Skip E2E for quick typecheck + build
$env:SV_SKIP_E2E="1"; .\scripts\gate-critical.ps1

# Just TypeScript check
cd frontend_v5
npx tsc --noEmit

# Just build
cd frontend_v5
npx next build
```

---

## Files Changed Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `frontend_v5/app/api/roster/runs/route.ts` | Edit | 2 path fixes |
| `frontend_v5/app/api/evidence/route.ts` | Rewrite | Full file (47 lines) |
| `frontend_v5/lib/schemas/platform-admin-schemas.ts` | Create | 150 lines |
| `frontend_v5/app/(platform)/platform-admin/tenants/page.tsx` | Edit | +5 lines |
| `frontend_v5/app/(platform)/platform-admin/users/page.tsx` | Edit | +10 lines |
| `docs/CURRENT_STATE_REPORT.md` | Create | Full report |
| `docs/FIXES_APPLIED.md` | Create | This file |

---

## Next Steps

1. Run `npx tsc --noEmit` to verify no type errors
2. Run `npx next build` to verify build succeeds
3. Run gate script with E2E tests
4. If gate passes, P0/P1 fixes are verified
5. Consider P2 items for future iteration
