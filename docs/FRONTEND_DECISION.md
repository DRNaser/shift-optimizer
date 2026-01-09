# Frontend Decision: Minimal Dispatcher Cockpit MVP

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot Dispatcher UI
**Status**: Planning
**Last Updated**: 2026-03-05

---

## Found Facts (Discovery Results)

### 1. Frontend Stack (`frontend_v5/`)

| Aspect | Finding |
|--------|---------|
| **Framework** | Next.js 14+ with App Router |
| **Auth Wiring** | `lib/platform-auth.ts` - Mock auth (TODO: Entra ID) |
| **Tenant Auth** | `lib/tenant-api.ts` - HMAC-signed BFF layer (server-side only) |
| **RBAC** | `lib/tenant-rbac.ts` - Role-based permission checks |
| **Security Arch** | `SECURITY_ARCHITECTURE.md` - Comprehensive trust boundary doc |
| **Layout** | `app/(tenant)/layout.tsx` - TenantStatusProvider + GlobalErrorHandler |
| **Status Banner** | `components/tenant/status-banner.tsx` - Shows degraded/blocked |

### 2. Existing BFF Routes (`app/api/tenant/`)

| Route | Methods | Status |
|-------|---------|--------|
| `/api/tenant/me` | GET | ✅ Exists |
| `/api/tenant/switch-site` | POST | ✅ Exists |
| `/api/tenant/status` | GET | ✅ Exists |
| `/api/tenant/plans/[planId]` | GET | ✅ Exists |
| `/api/tenant/plans/[planId]/lock` | POST | ✅ Exists (MOCK) |
| `/api/tenant/plans/[planId]/audit` | GET, POST | ✅ Exists |
| `/api/tenant/plans/[planId]/evidence` | GET, POST | ✅ Exists |
| `/api/tenant/plans/[planId]/repair` | GET, POST | ✅ Exists |
| `/api/tenant/plans/[planId]/freeze` | GET, POST | ✅ Exists |
| `/api/tenant/scenarios/*` | CRUD | ✅ Exists |
| `/api/tenant/imports/*` | CRUD | ✅ Exists |

### 3. Existing Backend Routers (`backend_py/api/routers/`)

| Router | Endpoints | Notes |
|--------|-----------|-------|
| `platform.py` | `/platform/tenants`, `/platform/tenants/{code}/sites`, etc. | Platform admin only |
| `service_status.py` | `/platform/status`, `/platform/escalations` | Kill switch, incidents |
| `runs.py` | `/runs`, `/runs/{id}`, `/runs/{id}/stream` | In-memory run store |
| `plans.py` | Plan management | Tenant-scoped |
| `repair.py` | Repair operations | Exists |

### 4. CLI Integration Points (`scripts/dispatcher_cli.py`)

| Command | Service | Key Requirement |
|---------|---------|-----------------|
| `list-runs` | File-based (`runs/*.json`) | Needs API equivalent |
| `show-run` | File-based | Needs API equivalent |
| `publish` | `PublishGateService` | Approval + evidence hash linkage |
| `lock` | `PublishGateService` | Same gates as publish |
| `request-repair` | File-based | Needs API equivalent |
| `status` | `PublishGateService.is_kill_switch_active()` | Exists |

### 5. Key Services (`backend_py/api/services/`)

| Service | Purpose | UI Integration |
|---------|---------|----------------|
| `publish_gate.py` | Publish/lock authorization | Critical - same gates as CLI |
| `pack_entitlements.py` | Pack enablement checks | Feature flags |
| `escalation.py` | Incident management | Status display |

### 6. Evidence Artifacts (`artifacts/live_wien_week_W*/`)

| Artifact | Format | Access |
|----------|--------|--------|
| `run_summary.json` | JSON | Direct read |
| `audit_results.json` | JSON | Direct read |
| `kpi_summary.json` | JSON | Direct read |
| `approval_record.json` | JSON | Direct read |
| `lock_record.json` | JSON | Direct read |
| `checksums.sha256` | Text | For verification |
| `evidence.zip` | ZIP | Download endpoint needed |

---

## Gaps Identified

### Critical Gaps (Must Fix)

| Gap | Risk | Solution |
|-----|------|----------|
| **No `/platform/runs` endpoint** | CLI reads files; UI needs API | Create platform endpoint |
| **BFF lock route uses MOCK** | No real publish gate call | Wire to `PublishGateService` |
| **No evidence download route** | Can't download evidence.zip | Add streaming endpoint |
| **Platform auth is mock** | No real user identity | Keep mock for MVP; Entra ID later |

### Security Verified (No Gaps)

| Check | Status |
|-------|--------|
| HMAC signing in browser | ✅ NOT done - server-side only via `tenant-api.ts` |
| BFF is only public gateway | ✅ Documented in SECURITY_ARCHITECTURE.md |
| CSRF protection | ✅ Origin/Referer validation in middleware |
| Tenant isolation | ✅ SET LOCAL in transaction wrapper |

---

## MVP Scope

### Pages

| Page | Route | Priority | Status |
|------|-------|----------|--------|
| **Runs List** | `/runs` | P0 | NEW |
| **Run Detail** | `/runs/[id]` | P0 | NEW |
| **Repair Request** | `/runs/[id]/repair` | P1 | NEW |
| **Publish/Lock** | Modal on Run Detail | P0 | NEW |
| **Status Dashboard** | `/status` | P1 | EXISTS (enhance) |

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| `RunsListPage` | Table of runs with status badges | NEW |
| `RunDetailPage` | Audit 7/7, KPIs, evidence downloads | NEW |
| `PublishLockModal` | Approval form + gate checks | NEW |
| `RepairRequestForm` | Sick-call input form | NEW |
| `KillSwitchBadge` | Shows kill switch state | NEW |

### Endpoints Required

| Endpoint | Method | Purpose | Implementation |
|----------|--------|---------|----------------|
| `GET /platform/runs` | GET | List runs for site | NEW backend router |
| `GET /platform/runs/{id}` | GET | Run detail with audits | NEW backend router |
| `POST /platform/runs/{id}/publish` | POST | Publish with approval | Wire to PublishGateService |
| `POST /platform/runs/{id}/lock` | POST | Lock with approval | Wire to PublishGateService |
| `POST /platform/runs/{id}/repair` | POST | Submit repair request | NEW backend router |
| `GET /platform/status` | GET | Kill switch + SLO + drift | EXISTS (enhance) |
| `GET /platform/evidence/{id}/download` | GET | Stream evidence.zip | NEW backend router |

---

## Security Rules (Non-Negotiable)

### Browser MUST NOT:
- [ ] Handle HMAC keys
- [ ] Sign requests
- [ ] Call pack endpoints directly
- [ ] Store tenant secrets

### Frontend MUST:
- [ ] Use platform session auth (cookie + CSRF) only
- [ ] Call BFF routes which call backend
- [ ] Display approval modal before publish/lock
- [ ] Show kill switch state before any state-changing action
- [ ] Produce same audit events + evidence hash linkage as CLI

### Acceptance Tests Required:
- [ ] `e2e/security-no-pack-calls.spec.ts` - Frontend cannot call pack endpoints
- [ ] `e2e/publish-gate.spec.ts` - Publish requires approval + respects Wien-only + kill switch
- [ ] `e2e/csrf-enforcement.spec.ts` - CSRF enforced on state changes

---

## Implementation Plan

### Phase A: Backend Platform Endpoints (Day 1)

1. Create `backend_py/api/routers/dispatcher_platform.py`:
   ```python
   # GET /platform/runs - List runs for site
   # GET /platform/runs/{run_id} - Run detail
   # POST /platform/runs/{run_id}/publish - Publish with approval
   # POST /platform/runs/{run_id}/lock - Lock with approval
   # POST /platform/runs/{run_id}/repair - Submit repair
   # GET /platform/evidence/{run_id}/download - Stream evidence.zip
   ```

2. Wire to existing `PublishGateService` for gates

### Phase B: BFF Routes (Day 2)

1. Create `frontend_v5/app/api/platform/runs/route.ts` (list)
2. Create `frontend_v5/app/api/platform/runs/[id]/route.ts` (detail)
3. Create `frontend_v5/app/api/platform/runs/[id]/publish/route.ts`
4. Create `frontend_v5/app/api/platform/runs/[id]/lock/route.ts`
5. Create `frontend_v5/app/api/platform/runs/[id]/repair/route.ts`
6. Create `frontend_v5/app/api/platform/evidence/[id]/download/route.ts`

### Phase C: UI Pages (Day 3-4)

1. Create `frontend_v5/app/(platform)/runs/page.tsx` - Runs list
2. Create `frontend_v5/app/(platform)/runs/[id]/page.tsx` - Run detail
3. Create `frontend_v5/components/platform/publish-lock-modal.tsx`
4. Create `frontend_v5/components/platform/repair-request-form.tsx`
5. Create `frontend_v5/components/platform/kill-switch-badge.tsx`

### Phase D: E2E Tests (Day 5)

1. `e2e/security-no-pack-calls.spec.ts`
2. `e2e/publish-gate.spec.ts`
3. `e2e/csrf-enforcement.spec.ts`
4. `e2e/dispatcher-happy-path.spec.ts`

### Phase E: Feature Flag + Deploy

1. Add feature flag: `DISPATCHER_UI_ENABLED=false` (default)
2. Deploy to staging during burn-in
3. Enable for internal platform users only
4. Ops go-live after day 30

---

## Acceptance Criteria (Hard Gates)

### Before Ops Can Use:

- [ ] No secrets in browser (code review + tests)
- [ ] All actions create same audit events + evidence hash linkage as CLI
- [ ] Cannot bypass gates (Wien-only, approval, kill switch, entitlements)
- [ ] CI green (lint, type-check, e2e tests)
- [ ] Auth separation unchanged
- [ ] `verify_final_hardening` still PASS
- [ ] Platform Lead sign-off

### Definition of Done:

| Check | Requirement |
|-------|-------------|
| Security | No browser HMAC, no direct pack calls |
| Parity | Same audit events as CLI |
| Gates | Wien-only + approval + kill switch enforced |
| Tests | E2E security tests pass |
| Docs | Updated SECURITY_ARCHITECTURE.md |

---

## Timeline

| Phase | Duration | Milestone |
|-------|----------|-----------|
| A: Backend | 1 day | Platform endpoints working |
| B: BFF | 1 day | BFF routes wired |
| C: UI | 2 days | Pages functional |
| D: Tests | 1 day | E2E tests pass |
| E: Deploy | 1 day | Staging deployment |
| **Total** | **6 days** | **MVP complete** |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| UI breaks burn-in | Feature flag OFF by default |
| Security regression | E2E tests + code review |
| Parity with CLI | Same PublishGateService |
| Auth confusion | Mock user clearly labeled |

---

## Sign-Off

| Role | Name | Date |
|------|------|------|
| Platform Lead | ____________ | ______ |
| Security Review | ____________ | ______ |
| Ops Lead | ____________ | ______ |

---

**Document Version**: 1.0

**Last Updated**: 2026-03-05

**Next Review**: After Phase A complete
