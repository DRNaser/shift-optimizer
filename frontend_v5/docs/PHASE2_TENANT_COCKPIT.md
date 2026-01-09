# SOLVEREIGN Phase 2: Tenant Ops Cockpit

**Date**: 2026-01-06
**Version**: V3.3b Phase 2
**Status**: GATE-READY

---

## Executive Summary

Phase 2 implements the Tenant Operations Cockpit for Routing Pack V1 (MediaMarkt/Wien pilot).

**Key Features**:
- BFF Pattern with HMAC V2 Signing
- 2-Person Hard Gate (UNDER + OVER both blocking)
- Lock/Freeze Separation
- RBAC Server-Side Enforcement
- Idempotency Keys on All Writes
- 6 Gate-Ready E2E Tests

---

## UI Pages (5 Pages)

| Page | Route | Description |
|------|-------|-------------|
| **Stops Import** | `/tenant/imports/stops` | FLS CSV upload, validate, accept |
| **Teams Daily** | `/tenant/teams/daily` | 2-person compliance, import/validate/publish |
| **Scenarios List** | `/tenant/scenarios` | Scenario overview and creation |
| **Scenario Detail** | `/tenant/scenarios/[id]` | Overview, Audit, Evidence, Repair tabs |
| **Status** | `/tenant/status` | Operational status, escalations, history |

---

## BFF Routes (21 Endpoints)

### Status Endpoints
| Method | Route | Permission | Idempotency |
|--------|-------|------------|-------------|
| GET | `/api/tenant/status` | read:status | - |
| GET | `/api/tenant/status/details` | read:status | - |

### Import Endpoints
| Method | Route | Permission | Idempotency |
|--------|-------|------------|-------------|
| GET | `/api/tenant/imports` | read:imports | - |
| POST | `/api/tenant/imports` | upload:stops | Required |
| GET | `/api/tenant/imports/[id]` | read:imports | - |
| POST | `/api/tenant/imports/[id]/validate` | validate:import | Required |
| POST | `/api/tenant/imports/[id]/accept` | accept:import | Required |
| POST | `/api/tenant/imports/[id]/reject` | reject:import | Required |

### Teams Daily Endpoints (NEW)
| Method | Route | Permission | Idempotency |
|--------|-------|------------|-------------|
| GET | `/api/tenant/teams/daily` | read:teams | - |
| GET | `/api/tenant/teams/daily/check-compliance` | read:teams | - |
| POST | `/api/tenant/teams/daily/import` | upload:teams | Required |
| POST | `/api/tenant/teams/daily/[id]/validate` | validate:teams | Required |
| POST | `/api/tenant/teams/daily/[id]/publish` | **publish:teams** | Required |

### Scenario Endpoints
| Method | Route | Permission | Idempotency |
|--------|-------|------------|-------------|
| GET | `/api/tenant/scenarios` | read:scenarios | - |
| POST | `/api/tenant/scenarios` | create:scenario | Required |
| GET | `/api/tenant/scenarios/[id]` | read:scenarios | - |
| POST | `/api/tenant/scenarios/[id]/solve` | solve:scenario | Required |

### Plan Endpoints
| Method | Route | Permission | Idempotency |
|--------|-------|------------|-------------|
| GET | `/api/tenant/plans/[id]` | read:plans | - |
| GET | `/api/tenant/plans/[id]/audit` | read:plans | - |
| POST | `/api/tenant/plans/[id]/audit` | audit:plan | Required |
| POST | `/api/tenant/plans/[id]/lock` | **lock:plan** | Required |
| GET | `/api/tenant/plans/[id]/freeze` | read:freeze | - |
| POST | `/api/tenant/plans/[id]/freeze` | **freeze:stops** | Required |
| GET | `/api/tenant/plans/[id]/evidence` | read:evidence | - |
| POST | `/api/tenant/plans/[id]/evidence` | generate:evidence | Required |
| GET | `/api/tenant/plans/[id]/repair` | read:repair | - |
| POST | `/api/tenant/plans/[id]/repair` | create:repair | Required |

---

## 2-Person Hard Gate

### Violation Types

| Type | Description | Action |
|------|-------------|--------|
| **MISMATCH_UNDER** | Team has 1 person, stop requires 2 | **BLOCKS PUBLISH** |
| **MISMATCH_OVER** | Team has 2 persons, stop requires 1 | **BLOCKS PUBLISH** |
| MATCHED | Team size matches stop requirement | OK |

### Gate Enforcement

```
POST /api/tenant/teams/daily/[importId]/publish

1. Check RBAC (APPROVER+ required)
2. Check tenant blocked status
3. Run 2-person compliance check
4. IF violations exist:
   - Count UNDER violations
   - Count OVER violations
   - Return 409 Conflict with:
     {
       "code": "TWO_PERSON_GATE_FAILED",
       "message": "Publish BLOCKED: X UNDER violations, Y OVER violations",
       "violations": [...],
       "under_count": X,
       "over_count": Y
     }
5. ELSE: Create immutable snapshot, return publish_id
```

### Why Both Are Blocking

- **UNDER = Safety Risk**: Heavy goods delivery with single driver is dangerous
- **OVER = Resource Waste**: 2 drivers for light goods = wasted capacity

---

## Lock vs Freeze

| Feature | Lock | Freeze |
|---------|------|--------|
| **Purpose** | Plan version immutability | Operational stop protection |
| **Scope** | Entire plan | Individual stops |
| **Trigger** | Manual (APPROVER action) | Time-based (60min) + Manual |
| **Effect** | Prevents plan modifications | Prevents stop reassignment |
| **Reversible** | No (creates new version) | No (within horizon) |

### Freeze State

```typescript
interface FreezeState {
  plan_id: string;
  total_stops: number;
  frozen_stops: number;      // time_frozen + manually_frozen
  unfrozen_stops: number;
  freeze_status: 'NONE' | 'PARTIAL' | 'FULL';
  frozen_stop_ids: string[];
  manually_frozen: string[]; // APPROVER action
  time_frozen: string[];     // Within 60min horizon
  next_freeze_at: string;    // When next stop freezes
}
```

---

## RBAC Matrix

| Permission | PLANNER | APPROVER | TENANT_ADMIN |
|------------|---------|----------|--------------|
| read:* | ✅ | ✅ | ✅ |
| upload:* | ✅ | ✅ | ✅ |
| validate:* | ✅ | ✅ | ✅ |
| accept:import | ✅ | ✅ | ✅ |
| create:scenario | ✅ | ✅ | ✅ |
| solve:scenario | ✅ | ✅ | ✅ |
| audit:plan | ✅ | ✅ | ✅ |
| create:repair | ✅ | ✅ | ✅ |
| generate:evidence | ✅ | ✅ | ✅ |
| **publish:teams** | ❌ | ✅ | ✅ |
| **lock:plan** | ❌ | ✅ | ✅ |
| **freeze:stops** | ❌ | ✅ | ✅ |
| **execute:repair** | ❌ | ✅ | ✅ |
| manage:tenant | ❌ | ❌ | ✅ |

### Server-Side Enforcement

```typescript
// lib/tenant-rbac.ts
export async function requirePermission(permissionKey: string): Promise<NextResponse | null> {
  const ctx = await getTenantContext();

  // Block writes for blocked tenant
  if (isWriteOperation(permissionKey) && ctx.isBlocked) {
    return blockedResponse('Tenant writes are disabled');
  }

  // Check role permission
  if (!hasPermission(ctx.userRole, permissionKey)) {
    return forbiddenResponse(`Permission denied: ${permissionKey}`);
  }

  return null;
}
```

---

## Idempotency Keys

### Format

```
{tenant_code}:{site_code}:{operation}:{identifiers...}
```

### Examples

| Operation | Key Format |
|-----------|------------|
| Upload stops | `lts-transport:wien:upload-import:stops_2026-01-07.csv` |
| Validate import | `lts-transport:wien:validate-import:imp-001` |
| Publish teams | `lts-transport:wien:publish-teams-daily:imp-001` |
| Create scenario | `lts-transport:wien:create-scenario:2026-01-07:MEDIAMARKT` |
| Solve scenario | `lts-transport:wien:solve-scenario:scen-001:94` |
| Lock plan | `lts-transport:wien:lock-plan:plan-001` |
| Freeze stops | `lts-transport:wien:freeze-stops:plan-001:stop-001:stop-002` |
| Generate evidence | `lts-transport:wien:generate-evidence:plan-001` |
| Create repair | `lts-transport:wien:create-repair:plan-001:NO_SHOW:stop-045` |

---

## E2E Test Coverage

### Test Files

| File | Tests | Purpose |
|------|-------|---------|
| `tenant-happy-path.spec.ts` | 15 | Complete workflow validation |
| `tenant-gates.spec.ts` | 20+ | Hard gate enforcement |

### Gate Tests

| Gate | Test | Expected |
|------|------|----------|
| **Blocked Tenant** | All writes | 503 + disabled UI |
| **2-Person UNDER** | Publish | 409 TWO_PERSON_GATE_FAILED |
| **2-Person OVER** | Publish | 409 TWO_PERSON_GATE_FAILED |
| **409 Conflict** | Idempotency mismatch | 409 + user-friendly message |
| **RBAC Lock** | PLANNER tries lock | 403 FORBIDDEN |
| **RBAC Publish** | PLANNER tries publish | 403 FORBIDDEN |
| **Missing Idem Key** | Write without key | 400 MISSING_IDEMPOTENCY_KEY |

---

## Files Created/Modified

### New Files

```
lib/
├── tenant-api.ts           # Tenant API client with HMAC V2
├── tenant-rbac.ts          # Server-side RBAC module

components/tenant/
├── status-banner.tsx       # Blocked status UI
├── error-handler.tsx       # Error handling UI
├── index.ts                # Barrel exports

app/api/tenant/
├── status/route.ts
├── status/details/route.ts
├── imports/route.ts
├── imports/[importId]/route.ts
├── imports/[importId]/validate/route.ts
├── imports/[importId]/accept/route.ts
├── teams/daily/route.ts
├── teams/daily/import/route.ts              # NEW
├── teams/daily/[importId]/validate/route.ts # NEW
├── teams/daily/[importId]/publish/route.ts  # NEW (2-person gate)
├── teams/daily/check-compliance/route.ts
├── scenarios/route.ts
├── scenarios/[scenarioId]/route.ts
├── scenarios/[scenarioId]/solve/route.ts
├── plans/[planId]/route.ts
├── plans/[planId]/audit/route.ts
├── plans/[planId]/lock/route.ts             # RBAC enforced
├── plans/[planId]/freeze/route.ts           # NEW (lock/freeze separation)
├── plans/[planId]/evidence/route.ts
├── plans/[planId]/repair/route.ts

app/(tenant)/
├── imports/stops/page.tsx
├── teams/daily/page.tsx
├── scenarios/page.tsx
├── scenarios/[id]/page.tsx
├── status/page.tsx

e2e/
├── tenant-happy-path.spec.ts
├── tenant-gates.spec.ts     # NEW (gate tests)

playwright.config.ts
```

---

## Run Tests

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

## Staging Checklist

### Pre-Deploy

- [ ] Apply all migrations to staging DB
- [ ] Configure S3/Azure Blob for evidence storage
- [ ] Set `SOLVEREIGN_INTERNAL_SECRET` in staging
- [ ] Configure tenant cookies in auth flow

### Go/No-Go Tests (Wien Data)

1. **FLS Stops CSV Import**
   - [ ] Upload → Validate → Accept (with real sample)
   - [ ] Verify body hash integrity

2. **TeamsDaily Flow**
   - [ ] Import → Validate → Compliance Check
   - [ ] Test UNDER violation → 409 block
   - [ ] Test OVER violation → 409 block
   - [ ] Test clean → Publish succeeds

3. **Scenario Flow**
   - [ ] Create → Solve → Plan fetch
   - [ ] Verify solver actually runs (objective > 0, time > 1ms)

4. **Audit + Lock**
   - [ ] Run audit → All PASS
   - [ ] Lock as APPROVER → Success
   - [ ] Lock as PLANNER → 403

5. **Evidence Pack**
   - [ ] Generate → Verify SHA256 in response
   - [ ] Download → Verify integrity

6. **Repair Drill**
   - [ ] Create NO_SHOW event
   - [ ] Verify freeze enforcement

---

## Conclusion

Phase 2 Tenant Ops Cockpit is **GATE-READY** with:

- ✅ 5 UI Pages (correct count)
- ✅ 21 BFF Routes (with new TeamsDaily + Freeze)
- ✅ 2-Person Hard Gate (UNDER + OVER both blocking)
- ✅ Lock/Freeze Separation
- ✅ RBAC Server-Side Enforcement
- ✅ Idempotency Keys on All Writes
- ✅ 35+ E2E Tests (happy path + gates)

Ready for Wien pilot staging deployment.
