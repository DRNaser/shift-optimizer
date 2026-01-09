# SOLVEREIGN V4 - Agent Context Handoff

> **Last Updated**: 2026-01-09
> **Status**: V4.3.1 COMPLETE | Wien Pilot: 4 P0 Blockers, 2 P1 Warnings | NOT READY
> **Next Milestone**: Wien Pilot Pre-Flight Gates (A-F) → Production Launch

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
| **V3.7** | **Wien Pilot Infrastructure (557 files committed)** | **COMPLETE** |
| V3.8.0 | Master Data Layer (MDL) - Kernel Service | COMPLETE |
| V3.8.1 | Gurkerl Dispatch Assist MVP | COMPLETE |
| V3.8.2 | Blindspot Fixes (location dedup, 9 MDL checks, overnight tests) | COMPLETE |
| **V3.9.0** | **Dispatch Apply Lifecycle (A1-A3)** | **COMPLETE** |
| **V4.1.0** | **Driver Portal + Magic Links** | **COMPLETE** |
| **V4.1.1** | **Notification Pipeline Hardening (C#/.NET)** | **COMPLETE** |
| **V4.1.2** | **Security Fix: SendGrid ECDSA + Retention** | **COMPLETE** |
| **V4.2.0** | **Portal-Notify Integration ({plan_link})** | **COMPLETE** |
| **V4.2.1** | **Portal-Notify Hardening (Atomic + Dedup + Retention)** | **COMPLETE** |
| **V4.2.2** | **Dashboard MVP + E2E Evidence Script** | **COMPLETE** |
| **V4.3.0** | **Frontend Driver Portal MVP** | **COMPLETE** |
| **V4.3.1** | **Frontend Session Hardening (HttpOnly Cookie)** | **COMPLETE** |

---

## V4.3.0: Frontend Driver Portal MVP (Jan 9, 2026)

### Overview

Mobile-first driver portal page for shift confirmation via magic link:
- **Token Validation**: Validates JWT from `?t=` query parameter
- **Read Tracking**: Records read receipt on page load
- **Shift Display**: Shows all assigned shifts with times and routes
- **Ack Workflow**: Accept/Decline buttons with reason codes

### Page Location

```
frontend_v5/app/my-plan/page.tsx
```

URL: `https://portal.solvereign.com/my-plan?t=<jwt_token>`

### Features

1. **Token States**:
   - `loading` - Validating token
   - `valid` - Plan loaded successfully
   - `expired` - Token has expired
   - `revoked` - Token was revoked
   - `superseded` - New plan version available
   - `error` - General error

2. **Plan Display**:
   - Driver name and total hours
   - Week date range
   - Shift cards with day, date, start/end times
   - Route names (if available)
   - Hours per shift

3. **Acknowledgment**:
   - Accept button (green, confirms immediately)
   - Decline button (amber, opens reason modal)
   - Reason codes: PERSONAL, MEDICAL, CONFLICT, OTHER
   - Optional free-text comment

4. **Mobile Optimizations**:
   - Responsive design (max-width: 2xl)
   - Fixed action bar at bottom
   - Touch-friendly button sizes (py-4)
   - Dark theme for outdoor visibility

### API Integration

```typescript
// Validate token and get plan
GET /api/portal/view?t=<token>
→ { plan: DriverPlan, ack_status: string }

// Record read receipt
POST /api/portal/read
→ { token: string }

// Submit acknowledgment
POST /api/portal/ack
→ { token, status, reason_code?, free_text? }
```

### UI Components

| Component | Purpose |
|-----------|---------|
| `LoadingState` | Spinner while loading |
| `ErrorState` | Error/expired/revoked message |
| `SupersededState` | New version available banner |
| `ShiftCard` | Individual shift display |
| `DeclineModal` | Reason selection modal |
| `DriverPortalContent` | Main page content |

### Styling (Tailwind)

- Dark theme: `bg-slate-900`, `text-slate-100`
- Cards: `bg-slate-800/50`, `border-slate-700`
- Success: `emerald-500/600`
- Warning: `amber-500/600`
- Info: `blue-500/600`

### V4.3.0 Definition of Done

- [x] `/my-plan` page with token validation
- [x] Read receipt on page load
- [x] Shift display with date/time/route
- [x] Accept button with immediate submission
- [x] Decline modal with reason codes
- [x] Superseded state handling
- [x] Mobile-responsive design
- [x] German UI text (Fahrer, Schichtplan, etc.)
- [ ] Integration test with real backend (P1)
- [ ] Accessibility audit (P2)

---

## V4.3.1: Frontend Session Hardening (Jan 9, 2026)

### Overview

Critical UX fix and production hardening for driver portal:
- **Session Cookie Pattern**: Token exchanged for HttpOnly session cookie (refresh-safe)
- **Route Caching Prevention**: `export const dynamic = "force-dynamic"` on all BFF routes
- **SKIPPED Visibility**: Skip reasons displayed in table and drawer

### Problem: Token Stripping Breaks Refresh

**Original Issue**: Token was stripped from URL immediately after extraction, but page still needed token for:
- Browser refresh (F5)
- Back button navigation
- Deep linking / bookmarks
- Link re-sharing

**Solution**: Token Exchange → HttpOnly Session Cookie pattern:
```
1. Driver clicks magic link: /my-plan?t=<jwt>
2. Page loads, exchanges token for session cookie (POST /api/portal/session)
3. Session cookie set (HttpOnly, SameSite=Lax, 60 min expiry)
4. Token stripped from URL (security)
5. Refresh/Back → Page uses session cookie (GET /api/portal/session)
```

### New BFF Routes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/portal/session` | POST | Exchange token for session cookie |
| `/api/portal/session` | GET | Check existing session (refresh/back) |
| `/api/portal/session` | DELETE | Clear session (logout) |
| `/api/portal/read` | POST | Record read receipt (session-based) |
| `/api/portal/ack` | POST | Submit acknowledgment (session-based) |

### Session Cookie Structure

```typescript
// Cookie name: portal_session
// Value: Base64 encoded JSON
{
  "t": "<original_jwt_token>",
  "expires_at": 1736444400 // Unix timestamp
}
```

Cookie options:
- `httpOnly: true` - Not accessible via JavaScript
- `secure: true` - HTTPS only (production)
- `sameSite: "lax"` - CSRF protection
- `maxAge: 3600` - 60 minute expiry
- `path: "/"` - Available site-wide

### Files Modified

| File | Changes |
|------|---------|
| `frontend_v5/app/api/portal/session/route.ts` | NEW: Token exchange endpoint |
| `frontend_v5/app/api/portal/read/route.ts` | NEW: Session-based read receipt |
| `frontend_v5/app/api/portal/ack/route.ts` | NEW: Session-based acknowledgment |
| `frontend_v5/lib/portal-api.ts` | Added session-based API functions |
| `frontend_v5/app/my-plan/page.tsx` | Updated to use session cookie pattern |
| `frontend_v5/app/api/portal-admin/*.ts` | Added `force-dynamic` + `revalidate = 0` |
| `frontend_v5/lib/format.ts` | Added `getSkippedReasonLabel()` |
| `frontend_v5/components/portal/driver-table.tsx` | Show skip_reason in status column |
| `frontend_v5/components/portal/driver-drawer.tsx` | Use label function for skip_reason |

### Next.js Route Caching Fix

**Problem**: Next.js caches API routes by default, causing stale data.

**Solution**: All BFF routes now include:
```typescript
export const dynamic = "force-dynamic";
export const revalidate = 0;
```

Routes updated:
- `/api/portal/session`
- `/api/portal/read`
- `/api/portal/ack`
- `/api/portal-admin/summary`
- `/api/portal-admin/details`
- `/api/portal-admin/resend`
- `/api/portal-admin/snapshots`
- `/api/portal-admin/export`

### SKIPPED Reason Labels

| Code | German Label |
|------|--------------|
| `NO_CONTACT` | Keine Kontaktdaten |
| `NO_SHIFTS` | Keine Schichten |
| `NO_CHANNEL` | Kein Zustellkanal |
| `OPT_OUT` | Abgemeldet |
| `DUPLICATE` | Duplikat |
| `EXCLUDED` | Ausgeschlossen |
| `MANUAL` | Manuell übersprungen |
| `SYSTEM` | Systembedingt |

### V4.3.1 Definition of Done

- [x] Token exchange endpoint (POST /api/portal/session)
- [x] Session check endpoint (GET /api/portal/session)
- [x] HttpOnly session cookie with 60 min expiry
- [x] my-plan page uses session cookie pattern
- [x] Token stripped from URL after successful exchange
- [x] Refresh/Back navigation works without token
- [x] `force-dynamic` on all BFF routes
- [x] `revalidate = 0` on all BFF routes
- [x] SKIPPED reasons visible in driver table
- [x] SKIPPED reasons visible in driver drawer
- [x] TypeScript check passes
- [x] Next.js build passes
- [x] E2E mock test passes (5/5 gates)

---

## Wien Pilot Pre-Flight Gates (Jan 9, 2026)

### Overview

Pre-flight verification gates before Wien Pilot launch. Engineering complete, staging verification pending.

**Current Status**: NOT READY (4 P0 Blockers, 2 P1 Warnings)

**Reference**: [docs/WIEN_PILOT_BLOCKERS.md](docs/WIEN_PILOT_BLOCKERS.md)

### P0 Blockers (Pilot = Tot ohne diese)

| Gate | Blocker | Status | Evidence Required |
|------|---------|--------|-------------------|
| **A** | Entra ID aud/iss Verification | NOT TESTED | `staging_preflight.py` PASS |
| **B** | Security Headers per curl | NOT TESTED | curl output with all headers |
| **C** | Real Provider E2E | NOT TESTED | Email + WhatsApp screenshots |
| **D** | Prod Migrations (037/037a/038) | NOT APPLIED | `verify_notify_integration()` PASS |

### P1 Warnings (Pilot riskant ohne diese)

| Gate | Warning | Status | Evidence Required |
|------|---------|--------|-------------------|
| **E** | Feature Flag + Rollback | NOT TESTED | Rollback procedure executed |
| **F** | Cookie Flags + Refresh Test | NOT TESTED | Live test on staging |

### Gate A: Entra ID aud/iss Verification

**Problem**: Wrong `OIDC_AUDIENCE` or `OIDC_ISSUER` → random 401 on all API calls.

**Pre-Flight Script**:
```bash
export STAGING_URL=https://staging.solvereign.com
export STAGING_TOKEN=<entra_bearer_token>
python scripts/staging_preflight.py
```

**Checklist**:
- [ ] `OIDC_AUDIENCE` = `api://<client-id>` (from Azure AD App Registration)
- [ ] `OIDC_ISSUER` = `https://login.microsoftonline.com/<tenant-id>/v2.0`
- [ ] `tenant_identities` has mapping for LTS Entra tid

### Gate B: Security Headers per curl

**Problem**: `next.config.ts` has headers, but CDN/proxy can override.

**Verification**:
```bash
curl -I https://staging.solvereign.com/my-plan | grep -i "referrer\|cache-control\|frame-options\|csp"

# Expected:
# referrer-policy: no-referrer
# cache-control: no-store, no-cache, must-revalidate, proxy-revalidate
# x-frame-options: DENY
# content-security-policy: default-src 'self'; ...
```

### Gate C: Real Provider E2E

**Problem**: E2E with `--mock-provider` only proves code exists, not that WhatsApp/SendGrid work.

**Verification**:
```bash
export STAGING_URL=https://staging.solvereign.com
export SENDGRID_API_KEY=<real_key>
export WHATSAPP_ACCESS_TOKEN=<real_token>
python scripts/e2e_portal_notify_evidence.py --env staging
```

**Evidence Required**:
- [ ] Email lands in inbox (screenshot)
- [ ] WhatsApp message received (screenshot)
- [ ] Webhook events visible in DB

### Gate D: Production Migrations

**Migrations Required** (in order):
```bash
# Pre-Gate (MUST be green)
python scripts/prod_migration_gate.py --env prod --phase pre

# Apply
psql $DATABASE_URL_PROD < backend_py/db/migrations/037_portal_notify_integration.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/037a_portal_notify_hardening.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/038_bounce_dnc.sql

# Post-Gate (MUST be green)
python scripts/prod_migration_gate.py --env prod --phase post

# Verify
psql $DATABASE_URL_PROD -c "SELECT * FROM portal.verify_notify_integration();"
psql $DATABASE_URL_PROD -c "SELECT * FROM notify.verify_notification_integrity();"
```

### Gate E: Feature Flag + Rollback

**Activation**:
```sql
UPDATE tenants SET features = features || '{"portal_enabled": true}'::jsonb WHERE id = 1;
```

**Rollback** (Airbag):
```sql
UPDATE tenants SET features = features - 'portal_enabled' WHERE id = 1;
docker stop notify-worker
```

### Gate F: Cookie Flags + Refresh Test

**Cookie Verification**:
```bash
# Check cookie attributes
curl -c - https://staging.solvereign.com/api/portal/session -X POST -d '{"token":"test"}'
# Must show: HttpOnly, Secure, SameSite=Strict
```

**Live Test**:
1. Click magic link: `/my-plan?t=<jwt>`
2. Verify plan loads
3. Press F5 (refresh) → plan still visible
4. Press Back → plan still visible
5. Close browser, reopen → session expired (expected)

### New Pre-Flight Scripts

| Script | Purpose |
|--------|---------|
| `scripts/staging_preflight.py` | Automated staging checks (headers, auth, health) |
| `docs/WIEN_PILOT_BLOCKERS.md` | Detailed blocker documentation |

### What Already Works

| Check | Status | Evidence |
|-------|--------|----------|
| Security Headers (Code) | PASS | `next.config.ts` correct |
| Rate Limit (Code) | PASS | 10/h in `portal_admin.py` |
| Session Cookie Pattern | PASS | Build + E2E mock passed |
| SKIPPED Visibility | PASS | `getSkippedReasonLabel()` + UI |
| E2E Script (Mock) | PASS | 5/5 gates passed |
| Feature Flag | READY | `features.portal_enabled` |

### Monitoring (Post-Launch)

```sql
-- Token issuance rate
SELECT date_trunc('hour', created_at), count(*) FROM portal.portal_tokens GROUP BY 1;

-- Notification delivery rate
SELECT status, count(*) FROM notify.notification_outbox GROUP BY 1;

-- Read rate
SELECT date_trunc('hour', first_read_at), count(*) FROM portal.read_receipts GROUP BY 1;

-- Ack completion rate
SELECT status, count(*) FROM portal.driver_ack GROUP BY 1;
```

---

## V4.2.2: Dashboard MVP + E2E Evidence (Jan 9, 2026)

### Overview

Dispatcher Dashboard MVP and E2E evidence collection for production verification:
- **Dashboard Summary**: KPI cards from `snapshot_notify_summary` view
- **Dashboard Details**: Filterable driver table from `notify_integration_status` view
- **Dashboard Resend**: Batch resend to filtered group (UNREAD/UNACKED/DECLINED)
- **E2E Evidence Script**: JSON artifact proving portal-notify integration works

### New Dashboard API Endpoints (Entra ID Required)

| Endpoint | Method | Role | Purpose |
|----------|--------|------|---------|
| `/api/v1/portal/dashboard/summary` | GET | Dispatcher | KPI cards (total, read, accepted, declined, unread) |
| `/api/v1/portal/dashboard/details` | GET | Dispatcher | Driver table with status filter + pagination |
| `/api/v1/portal/dashboard/resend` | POST | Dispatcher | Batch resend to filtered drivers |

### Dashboard Summary Response

Returns pre-built KPI cards for frontend rendering:
```json
{
  "snapshot_id": "uuid",
  "tenant_id": 1,
  "total_tokens": 145,
  "pending_count": 10,
  "sent_count": 5,
  "delivered_count": 100,
  "read_count": 80,
  "accepted_count": 70,
  "declined_count": 5,
  "failed_count": 0,
  "completion_rate": 51.7,
  "read_rate": 55.2,
  "acceptance_rate": 93.3,
  "kpi_cards": [
    {"label": "Total Drivers", "value": 145, "color": "default"},
    {"label": "Accepted", "value": 70, "percentage": 48.3, "color": "success"},
    {"label": "Unread", "value": 30, "percentage": 20.7, "color": "danger"}
  ]
}
```

### Dashboard Details Filters

| Filter | Description |
|--------|-------------|
| `ALL` | All drivers |
| `PENDING` | Not yet sent |
| `SENT` | Sent but not delivered |
| `DELIVERED` | Delivered but not read |
| `READ` | Read but not acked |
| `UNREAD` | Not read (sent/delivered without read receipt) |
| `UNACKED` | Read but no acknowledgment |
| `ACCEPTED` | Accepted |
| `DECLINED` | Declined |
| `FAILED` | Notification failed |

### Dashboard Resend Action

```bash
# Resend REMINDER_24H to all unread drivers
curl -X POST /api/v1/portal/dashboard/resend \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "snapshot_id": "uuid",
    "filter": "UNREAD",
    "delivery_channel": "WHATSAPP",
    "template_key": "REMINDER_24H"
  }'
```

### E2E Evidence Script

```bash
# Run E2E evidence collection (30 min staging test)
python scripts/e2e_portal_notify_evidence.py --env staging

# Output: e2e_evidence_YYYYMMDD_HHMMSS.json
```

Evidence gates verified:
1. `notification_created` - Job created with portal URLs
2. `outbox_sent` - Outbox entry status = SENT/DELIVERED
3. `portal_accessible` - GET /my-plan?t=... returns 200
4. `read_recorded` - Read receipt created
5. `view_status_correct` - notify_integration_status shows READ

### V4.2.2 Definition of Done

- [x] Dashboard summary endpoint with KPI cards
- [x] Dashboard details endpoint with filters + pagination
- [x] Dashboard resend endpoint for batch operations
- [x] E2E evidence script with JSON artifact
- [x] Health check updated to v4.2.0 with dashboard_mvp feature
- [ ] Frontend dashboard UI (Next.js) - deferred to V4.3
- [ ] Frontend driver portal UI - pending

---

## V4.2.1: Portal-Notify Hardening (Jan 9, 2026)

### Overview

Production hardening for portal-notify integration:
- **ATOMIC**: `issue_and_notify_atomic()` - single transaction for tokens + outbox
- **DEDUP**: `dedup_key` column prevents duplicate tokens for same snapshot+driver+channel
- **PII-SAFE VIEWS**: Removed `error_message` from views (could contain PII)
- **RETENTION**: `cleanup_portal_data()` aligned with notify retention (036)
- **ORPHAN CLEANUP**: `revoke_tokens_for_job()` on job failure

### New Migration: 037a_portal_notify_hardening.sql

| Fix | Implementation |
|-----|----------------|
| Atomicity | `portal.issue_token_atomic()` - creates token + outbox in single transaction |
| Dedup Key | `sha256(tenant\|site\|snapshot\|driver\|channel\|scope)` with unique index |
| PII Views | Removed `jti_hash` and `error_message` from `notify_integration_status` |
| Retention | `portal.cleanup_portal_data(90)` - archive + delete old tokens |
| Orphan Cleanup | `portal.revoke_tokens_for_job(job_id)` - revokes all tokens if job fails |

### Dedup Key Formula

```sql
dedup_key = sha256(tenant_id|site_id|snapshot_id|driver_id|channel|scope)
```

**Behavior**:
- Same driver + snapshot + channel + scope → returns existing token (duplicate)
- Different scope (e.g., REMINDER vs PORTAL_INVITE) → new token allowed
- Revoked token → new token allowed (WHERE revoked_at IS NULL)

### Atomic Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                  ATOMIC ISSUE + NOTIFY                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   BEGIN TRANSACTION                                              │
│   │                                                              │
│   ├─ Compute dedup_key                                          │
│   ├─ Check existing (FOR UPDATE SKIP LOCKED)                    │
│   │   └─ If exists + not revoked → return duplicate             │
│   │                                                              │
│   ├─ INSERT portal.portal_tokens (jti_hash, dedup_key)         │
│   ├─ INSERT notify.notification_outbox (portal_url)            │
│   ├─ UPDATE portal_tokens SET outbox_id                        │
│   │                                                              │
│   └─ COMMIT                                                      │
│                                                                  │
│   ON FAILURE:                                                    │
│   └─ ROLLBACK + revoke_tokens_for_job()                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Retention Strategy

| Table | Retention | Archive | Notes |
|-------|-----------|---------|-------|
| `portal_tokens` | 90 days | Yes | After expires_at + retention |
| `read_receipts` | 90 days | No | Only if no ack exists |
| `driver_ack` | **NEVER** | N/A | Arbeitsrechtlich immutable |
| `rate_limits` | 90 days | No | Always safe to delete |

### Verification Commands

```bash
# Apply hardening migration
psql $DATABASE_URL < backend_py/db/migrations/037a_portal_notify_hardening.sql

# Verify (should return 8 PASS)
psql $DATABASE_URL -c "SELECT * FROM portal.verify_notify_integration();"

# Check old records
psql $DATABASE_URL -c "SELECT * FROM portal.count_old_portal_records(90);"

# Cleanup (90 day retention, with archive)
psql $DATABASE_URL -c "SELECT * FROM portal.cleanup_portal_data(90, TRUE);"
```

### V4.2.1 Definition of Done

- [x] `portal.issue_token_atomic()` function (token + outbox in one transaction)
- [x] `dedup_key` column with unique index
- [x] `portal.compute_token_dedup_key()` function
- [x] `portal.revoke_tokens_for_job()` for orphan cleanup
- [x] Views updated: no `jti_hash`, no `error_message` (PII risk)
- [x] `portal.cleanup_portal_data()` retention function
- [x] `portal.count_old_portal_records()` monitoring function
- [x] Archive table `portal.portal_tokens_archive`
- [x] `issue_and_notify_atomic()` Python method
- [x] Enhanced `verify_notify_integration()` (8 checks)

---

## V4.2: Portal-Notify Integration (Jan 9, 2026)

### Overview

Complete integration between portal magic links and notification pipeline:
- **{plan_link}** template variable standardized across all notification templates
- **PortalLinkService** bridges token issuance with notification job creation
- **Monitoring views** for tracking delivery → read → ack funnel

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  PORTAL-NOTIFY INTEGRATION                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   DISPATCHER                                                     │
│   └─ POST /api/v1/portal/issue-and-notify                       │
│                                                                  │
│   PortalLinkService                                              │
│   ├─ generate_bulk_links()  → portal.portal_tokens              │
│   │   └─ Each driver gets unique JWT token                       │
│   │   └─ Only jti_hash stored (NEVER raw token)                 │
│   │                                                              │
│   └─ create_notify_job()    → notify.notification_outbox        │
│       └─ portal_urls: {driver_id: "https://.../my-plan?t=..."}  │
│       └─ Template: "Ihr Plan: {{plan_link}}"                    │
│                                                                  │
│   NOTIFY WORKER                                                  │
│   └─ Resolves {{plan_link}} per driver from portal_urls         │
│   └─ Sends WhatsApp/Email/SMS                                    │
│                                                                  │
│   DRIVER                                                         │
│   └─ Clicks link → /my-plan?t=...                                │
│   └─ Token validated → plan rendered                             │
│   └─ POST /portal/read → read receipt                            │
│   └─ POST /portal/ack → accept/decline                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### New Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `backend_py/packs/portal/link_service.py` | Integration service for token issuance + notify | ~400 |
| `backend_py/db/migrations/037_portal_notify_integration.sql` | Templates, views, link functions | ~350 |
| `backend_py/packs/portal/tests/test_link_service.py` | Integration tests (~25 tests) | ~350 |

### Template Variable: {plan_link}

**Standard Variable Name**: All notification templates now use `{{plan_link}}` instead of `{{portal_url}}`.

**Migration 037** updates existing templates and adds new ones:

| Template Key | Channel | Language | Variables |
|--------------|---------|----------|-----------|
| `PORTAL_INVITE` | WHATSAPP | de | `driver_name`, `plan_link` |
| `PORTAL_INVITE` | EMAIL | de | `driver_name`, `plan_link`, `week_start` |
| `REMINDER_24H` | WHATSAPP | de | `driver_name`, `plan_link` |
| `REMINDER_24H` | EMAIL | de | `driver_name`, `plan_link` |
| `PORTAL_INVITE` | SMS | de | `plan_link` |

### API Integration

**Issue and Notify Endpoint:**
```python
# POST /api/v1/portal/issue-and-notify
request = NotifyLinkRequest(
    tenant_id=1,
    site_id=10,
    snapshot_id="uuid",
    driver_requests=[
        DriverLinkRequest(driver_id="DRV-001", driver_name="Max"),
        DriverLinkRequest(driver_id="DRV-002", driver_name="Eva"),
    ],
    delivery_channel=DeliveryChannel.WHATSAPP,
    template_key="PORTAL_INVITE",
    initiated_by="dispatcher@company.com",
)

result = await link_service.issue_and_notify(request, notify_repository)
# Returns: job_id, portal_urls, success/fail counts
```

### Database Additions (Migration 037)

**New Function: `portal.link_token_to_outbox()`**
Links portal tokens to notification outbox entries for delivery tracking.

**New View: `portal.notify_integration_status`**
Combines portal tokens, outbox status, read receipts, and acks into single view:

| Column | Source |
|--------|--------|
| `notify_status` | notification_outbox.status |
| `notify_sent_at` | notification_outbox.sent_at |
| `first_read_at` | read_receipts.first_read_at |
| `ack_status` | driver_ack.status |
| `overall_status` | Derived: PENDING → SENT → DELIVERED → READ → ACCEPTED/DECLINED |

**New View: `portal.snapshot_notify_summary`**
Aggregated metrics per snapshot:

| Metric | Description |
|--------|-------------|
| `total_tokens` | Total drivers with tokens issued |
| `sent_count` | Messages sent |
| `delivered_count` | Messages confirmed delivered |
| `read_count` | Drivers who viewed plan |
| `accepted_count` | Drivers who accepted |
| `declined_count` | Drivers who declined |
| `completion_rate` | (accepted + declined) / total * 100 |

### Verification Commands

```bash
# Apply migration
psql $DATABASE_URL < backend_py/db/migrations/037_portal_notify_integration.sql

# Verify integration (should return 4 PASS)
psql $DATABASE_URL -c "SELECT * FROM portal.verify_notify_integration();"

# Run tests
pytest backend_py/packs/portal/tests/test_link_service.py -v

# Check templates use plan_link
psql $DATABASE_URL -c "
  SELECT template_key, delivery_channel, expected_params
  FROM notify.notification_templates
  WHERE 'plan_link' = ANY(expected_params);
"
```

### V4.2 Definition of Done

- [x] PortalLinkService for token issuance + notify integration
- [x] DriverLinkRequest, BulkLinkResult, NotifyLinkRequest models
- [x] generate_link() and generate_bulk_links() methods
- [x] issue_and_notify() integration method
- [x] Migration 037 with template updates (portal_url → plan_link)
- [x] portal.link_token_to_outbox() function
- [x] portal.notify_integration_status view
- [x] portal.snapshot_notify_summary view
- [x] portal.verify_notify_integration() verification function
- [x] Integration tests (~25 tests)
- [x] Portal package exports updated

---

## V4.1.2: SendGrid ECDSA Fix + Retention (Jan 9, 2026)

### Overview

Critical security fix and production hardening:
- **SendGrid Webhook**: Fixed signature verification to use ECDSA P-256 (was incorrectly using HMAC placeholder)
- **Retention Jobs**: Added cleanup functions to prevent unbounded table growth

### Security Fix: SendGrid ECDSA Signature Verification

**Problem**: The original implementation only checked `!string.IsNullOrEmpty(signature)` - accepting ANY non-empty string without cryptographic verification.

**Solution**: Proper ECDSA P-256 verification matching SendGrid's Signed Event Webhook specification.

**Updated Files:**

| File | Changes |
|------|---------|
| `backend_dotnet/Solvereign.Notify/Models/NotifyConfig.cs` | Added `WebhookPublicKey` (replaces `WebhookSigningKey`), `WebhookMaxAgeSeconds` |
| `backend_dotnet/Solvereign.Notify/Api/WebhookController.cs` | Proper ECDSA verification with P-256, timestamp freshness, raw body bytes |
| `backend_dotnet/Solvereign.Notify.Tests/WebhookSignatureTests.cs` | Updated tests for ECDSA (test key pair generation, 8 SendGrid tests) |

**Correct Implementation:**
```csharp
// 1. Validate timestamp freshness (< 5 min, > -1 min clock skew)
// 2. Build payload: timestamp + rawBody as UTF-8 bytes
// 3. Decode public key (SPKI DER format, Base64)
// 4. Decode signature (Base64)
// 5. Verify: ecdsa.VerifyData(payloadBytes, signatureBytes, SHA256)
```

**Environment Variables:**
```bash
# OLD (removed):
# SENDGRID_WEBHOOK_SIGNING_KEY=...

# NEW:
SENDGRID_WEBHOOK_PUBLIC_KEY=MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...  # From SendGrid Settings
SENDGRID_WEBHOOK_MAX_AGE_SECONDS=300  # Optional, default 300
```

### Retention: Migration 036

**Problem**: notification_outbox, delivery_log, webhook_events grow unbounded.

**Solution**: `notify.cleanup_notifications()` function with:
- Configurable retention (default 30 days)
- Optional archive before delete (audit trail)
- Batch deletion (avoids lock contention)
- Monitoring function `count_old_records()`

**New Files:**

| File | Purpose | Lines |
|------|---------|-------|
| `backend_py/db/migrations/036_notifications_retention.sql` | Retention functions, archive table, verify enhancement | ~500 |

**Key Functions:**
| Function | Purpose |
|----------|---------|
| `notify.cleanup_notifications(days, archive, batch, max_batches)` | Main cleanup entry point |
| `notify.count_old_records(days)` | Count records eligible for cleanup (monitoring) |
| `notify.purge_archive(days)` | Purge old archive records (365 day default) |
| `notify.verify_notification_integrity()` | Enhanced: now 13 checks including retention threshold |

**Scheduling:**
```bash
# Option A: pg_cron
SELECT cron.schedule('notify-cleanup', '0 2 * * *',
  'SELECT notify.cleanup_notifications(30)');

# Option B: External scheduler
psql $DATABASE_URL -c "SELECT notify.cleanup_notifications(30);"

# Monitoring (before cleanup):
SELECT * FROM notify.count_old_records(30);
```

### V4.1.2 Definition of Done

- [x] SendGrid ECDSA verification (P-256, raw bytes, timestamp freshness)
- [x] Config: WebhookPublicKey replaces WebhookSigningKey
- [x] Tests: 8 SendGrid ECDSA tests (valid, tampered, wrong key, expired, future, missing)
- [x] Migration 036: cleanup_notifications(), count_old_records(), purge_archive()
- [x] Archive table with RLS
- [x] Batch deletion with SKIP LOCKED (lock contention avoidance)
- [x] verify_notification_integrity() enhanced (13 checks, retention threshold)
- [x] Cleanup indexes for performance

### Verification Commands

```bash
# Apply retention migration
psql $DATABASE_URL < backend_py/db/migrations/036_notifications_retention.sql

# Verify integrity (should return 13 checks)
psql $DATABASE_URL -c "SELECT * FROM notify.verify_notification_integrity();"

# Check old records before cleanup
psql $DATABASE_URL -c "SELECT * FROM notify.count_old_records(30);"

# Run cleanup (dry-run: check count first!)
psql $DATABASE_URL -c "SELECT * FROM notify.cleanup_notifications(30);"
```

---

## V3.9: Dispatch Apply Lifecycle (Jan 9, 2026)

### Overview

Implements optimistic concurrency control for Gurkerl Dispatch Assist with:
- **A1**: Database tables for tracking proposals and open shifts with RLS
- **A2**: Sheet fingerprinting for change detection
- **A3**: Apply endpoint with conflict detection and server-side revalidation

### New Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `backend_py/db/migrations/031_dispatch_lifecycle.sql` | Schema, tables, RLS, triggers, verify function | ~450 |
| `backend_py/packs/roster/dispatch/repository.py` | DB operations (proposal CRUD, audit entries) | ~520 |
| `backend_py/packs/roster/dispatch/tests/test_fingerprint.py` | Fingerprint calculation tests | ~280 |
| `backend_py/packs/roster/dispatch/tests/test_apply.py` | Apply workflow tests | ~450 |

### Modified Files

| File | Changes |
|------|---------|
| `backend_py/packs/roster/dispatch/models.py` | Added FingerprintScope, ApplyRequest, ApplyResult, PersistedProposal |
| `backend_py/packs/roster/dispatch/sheet_adapter.py` | Added fingerprint methods, FingerprintCache, write_assignment |
| `backend_py/packs/roster/dispatch/service.py` | Added DispatchApplyService with apply_proposal workflow |
| `backend_py/packs/roster/api/dispatch.py` | Added POST /apply endpoint with schemas |

### Database Schema: `dispatch`

**Tables:**
- `dispatch.dispatch_open_shifts` - Detected open shifts with lifecycle status
- `dispatch.dispatch_proposals` - Proposals with fingerprint and candidates
- `dispatch.dispatch_apply_audit` - Append-only audit trail

**Key Features:**
- RLS with `FORCE ROW LEVEL SECURITY` for tenant isolation
- Immutability trigger on proposals after PROPOSED status
- `verify_dispatch_integrity()` function with 12 checks
- Unique constraint on `apply_request_id` for idempotency

### Apply Endpoint: `POST /api/v1/roster/dispatch/apply`

**Request:**
```json
{
  "proposal_id": "uuid",
  "selected_driver_id": "DRV-001",
  "expected_plan_fingerprint": "sha256_hash",
  "apply_request_id": "uuid (idempotency key)",
  "force": false,
  "force_reason": "min 10 chars if force=true"
}
```

**Response Codes:**
- `200 OK` - Apply successful, returns cells_written
- `409 PLAN_CHANGED` - Fingerprint mismatch, includes diff hints
- `422 NOT_ELIGIBLE` - Driver failed revalidation, includes disqualifications
- `403 FORCE_NOT_ALLOWED` - App tokens cannot use force

### Fingerprint Design

**Scope-Based Hashing** (not whole-sheet):
- `DAY_ONLY`: Single day only
- `DAY_PM1`: Date ± 1 day (default)
- `WEEK_WINDOW`: Full week Mon-Sun

**Fingerprint includes:**
- Roster rows within scope date range
- Driver master data (skills, zones, target_hours)
- Absences within date range
- Sheet revision number
- Config version string

### V3.9 Definition of Done

- [x] Migration 031_dispatch_lifecycle.sql with dispatch schema
- [x] FingerprintScope, ApplyResult dataclasses in models.py
- [x] Fingerprint methods in sheet_adapter.py
- [x] Repository.py with MockDispatchRepository
- [x] DispatchApplyService in service.py
- [x] POST /apply endpoint in dispatch.py
- [x] test_fingerprint.py with ~15 tests
- [x] test_apply.py with ~25 tests
- [x] Blindspot fixes (scope edge cases, contract validation, patch semantics, parallel apply)
- [ ] Integration test with real Google Sheet (P1)
- [ ] Production DB migration (P1)

---

## V4.1: Driver Portal + Magic Links (Jan 9, 2026)

### Overview

Driver Portal infrastructure for:
- **Magic Links**: JWT-based secure access without Entra ID
- **Read Receipts**: Idempotent tracking of plan views
- **Acknowledgments**: Accept/Decline workflow (arbeitsrechtlich relevant)
- **Supersede Tracking**: Old links show "new version available" banner

### New Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `backend_py/db/migrations/033_portal_magic_links.sql` | Portal schema, tables, RLS, triggers, verify function | ~650 |
| `backend_py/packs/portal/__init__.py` | Portal package initialization | ~40 |
| `backend_py/packs/portal/models.py` | Token, ReadReceipt, DriverAck, PortalStatus models | ~350 |
| `backend_py/packs/portal/token_service.py` | JWT generation/validation, rate limiting | ~350 |
| `backend_py/packs/portal/repository.py` | DB operations (PostgreSQL + Mock) | ~500 |
| `backend_py/packs/portal/renderer.py` | Driver view rendering from DB snapshots | ~350 |
| `backend_py/api/routers/portal_public.py` | Public endpoints (magic link auth) | ~350 |
| `backend_py/api/routers/portal_admin.py` | Dispatcher admin endpoints (Entra ID auth) | ~350 |
| `backend_py/packs/portal/tests/test_portal.py` | Portal tests (~20 tests) | ~450 |

### Database Schema: `portal`

**Tables:**
- `portal.portal_tokens` - Magic link tokens (jti_hash, never raw token)
- `portal.read_receipts` - When drivers read plans (idempotent)
- `portal.driver_ack` - Accept/Decline records (immutable)
- `portal.driver_views` - Pre-rendered views
- `portal.snapshot_supersedes` - Old→New snapshot mapping
- `portal.portal_audit` - Audit trail (append-only)
- `portal.rate_limits` - Rate limiting per jti_hash

**Key Features:**
- RLS with `FORCE ROW LEVEL SECURITY` for tenant isolation
- Immutability trigger on `driver_ack` (arbeitsrechtlich)
- `verify_portal_integrity()` function with 8 checks
- Single-use ACK tokens (revoked after first use)

### Public API Endpoints (No Entra ID)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/my-plan?t=...` | GET | View driver's plan (HTML) |
| `/api/portal/read` | POST | Record read receipt |
| `/api/portal/ack` | POST | Accept/Decline plan |
| `/api/portal/status` | GET | Get current ack status |

### Admin API Endpoints (Entra ID Required)

| Endpoint | Method | Role | Purpose |
|----------|--------|------|---------|
| `/api/v1/portal/status` | GET | Dispatcher | Get aggregated status |
| `/api/v1/portal/drivers` | GET | Dispatcher | List drivers with status |
| `/api/v1/portal/issue-tokens` | POST | Dispatcher | Issue magic links |
| `/api/v1/portal/resend` | POST | Dispatcher | Resend notifications |
| `/api/v1/portal/override-ack` | POST | Approver | Override driver ack |
| `/api/v1/portal/revoke-tokens` | POST | Dispatcher | Revoke tokens |

### Security Features

1. **Token Storage**: Only `jti_hash` (SHA-256) stored - NEVER raw token
2. **Single-Use ACK**: Token revoked after first acknowledgment
3. **Rate Limiting**: Per jti_hash (100 req/hour default)
4. **GDPR Compliant**: Minimal data, IP hashed, no raw token logging
5. **Immutable ACK**: Trigger prevents modification (except override)

### Verification Commands

```bash
# Apply migration
psql $DATABASE_URL < backend_py/db/migrations/033_portal_magic_links.sql

# Verify integrity (should return 8 PASS)
psql $DATABASE_URL -c "SELECT * FROM portal.verify_portal_integrity();"

# Run tests
pytest backend_py/packs/portal/tests/test_portal.py -v
```

### Part B: Notification Pipeline

**Purpose**: Transactional outbox pattern for reliable driver notifications (WhatsApp, Email, SMS).

**New Files Created:**

| File | Purpose | Lines |
|------|---------|-------|
| `backend_py/db/migrations/034_notifications.sql` | Notify schema, outbox, jobs, templates, RLS | ~650 |
| `backend_py/packs/notify/__init__.py` | Notification package initialization | ~40 |
| `backend_py/packs/notify/models.py` | Job, Outbox, Template, Preferences models | ~400 |
| `backend_py/packs/notify/repository.py` | DB operations for notifications | ~500 |
| `backend_py/packs/notify/worker.py` | Background outbox processor | ~300 |
| `backend_py/packs/notify/providers/__init__.py` | Provider exports | ~20 |
| `backend_py/packs/notify/providers/base.py` | Base provider interface + MockProvider | ~150 |
| `backend_py/packs/notify/providers/whatsapp.py` | WhatsApp Cloud API integration | ~300 |
| `backend_py/packs/notify/providers/email.py` | SendGrid email provider | ~250 |
| `backend_py/api/routers/notifications.py` | Notification API endpoints | ~400 |
| `backend_py/packs/notify/tests/test_notifications.py` | Notification tests (~35 tests) | ~500 |

**Database Schema: `notify`**

**Tables:**
- `notify.notification_jobs` - High-level job tracking (bulk sends)
- `notify.notification_outbox` - Individual messages to process
- `notify.notification_delivery_log` - Delivery attempts (append-only)
- `notify.notification_templates` - Message templates per channel/language
- `notify.driver_preferences` - Driver opt-in/opt-out and quiet hours

**Key Features:**
- Transactional outbox pattern for at-least-once delivery
- RLS with `FORCE ROW LEVEL SECURITY` for tenant isolation
- Exponential backoff retry (60s, 300s, 900s)
- Webhook handlers for delivery confirmation
- GDPR compliant (recipient_hash for dedup, no raw contact logging)
- `verify_notification_integrity()` function with 8 checks

### Notification API Endpoints (Entra ID Required)

| Endpoint | Method | Role | Purpose |
|----------|--------|------|---------|
| `/api/v1/notifications/send` | POST | Dispatcher | Create notification job |
| `/api/v1/notifications/jobs/{id}` | GET | Dispatcher | Get job status |
| `/api/v1/notifications/jobs` | GET | Dispatcher | List jobs |
| `/api/v1/notifications/resend` | POST | Dispatcher | Resend failed messages |
| `/api/v1/notifications/webhook/whatsapp` | POST | - | WhatsApp webhook handler |
| `/api/v1/notifications/webhook/sendgrid` | POST | - | SendGrid webhook handler |

### Environment Variables (Providers)

```bash
# WhatsApp Cloud API
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
WHATSAPP_ACCESS_TOKEN=your-access-token
WHATSAPP_WEBHOOK_VERIFY_TOKEN=solvereign-notify-v1

# SendGrid Email
SENDGRID_API_KEY=your-api-key
SENDGRID_FROM_EMAIL=noreply@solvereign.com
SENDGRID_FROM_NAME=SOLVEREIGN

# Worker Config
NOTIFY_WORKER_BATCH_SIZE=10
NOTIFY_WORKER_POLL_INTERVAL=5
NOTIFY_WORKER_MAX_CONCURRENT=5
```

### Verification Commands (Notifications)

```bash
# Apply migration
psql $DATABASE_URL < backend_py/db/migrations/034_notifications.sql

# Verify integrity (should return 8 PASS)
psql $DATABASE_URL -c "SELECT * FROM notify.verify_notification_integrity();"

# Run tests
pytest backend_py/packs/notify/tests/test_notifications.py -v

# Start worker (standalone)
python -m backend_py.packs.notify.worker
```

### V4.1 Definition of Done

- [x] Migration 033_portal_magic_links.sql with portal schema
- [x] PortalToken, ReadReceipt, DriverAck models
- [x] Token service with JWT generation/validation
- [x] Public portal endpoints (read, ack, status)
- [x] Admin portal endpoints (status, issue-tokens, override)
- [x] Driver view renderer from DB snapshots
- [x] Portal tests (~20 tests)
- [x] Register portal routers in main.py
- [x] Migration 034_notifications.sql with notify schema
- [x] Notification models, repository, worker
- [x] WhatsApp Cloud API provider
- [x] SendGrid email provider
- [x] Notification API endpoints
- [x] Notification tests (~35 tests)
- [x] Register notification routers in main.py
- [ ] Integration with plan_snapshots publishing
- [ ] Frontend portal pages (Next.js)

---

## V4.1.1: Notification Pipeline Hardening (Jan 9, 2026)

### Overview

Production-grade notification infrastructure with C#/.NET HostedService:
- **Concurrency-Safe Claiming**: `SELECT FOR UPDATE SKIP LOCKED` prevents double-sends
- **Provider Idempotency**: SHA-256 dedup key ensures duplicate prevention
- **Webhook Security**: HMAC signature verification for WhatsApp and SendGrid
- **GDPR/PII Hygiene**: No raw contacts (phone/email) in notify schema or logs
- **Retry with Backoff**: Exponential backoff `base * 5^(attempt-1)` clamped at 2700s
- **Dead Letter**: Manual requeue with RBAC

### New Files Created

**Database Migration:**

| File | Purpose | Lines |
|------|---------|-------|
| `backend_py/db/migrations/035_notifications_hardening.sql` | PATCH migration for production hardening | ~650 |

**C#/.NET Worker (`backend_dotnet/Solvereign.Notify/`):**

| File | Purpose | Lines |
|------|---------|-------|
| `Models/OutboxMessage.cs` | Status enums, result records, error codes | ~200 |
| `Models/NotifyConfig.cs` | Configuration classes for DI | ~100 |
| `Repository/INotifyRepository.cs` | Repository interface | ~60 |
| `Repository/NotifyRepository.cs` | Dapper implementation calling PostgreSQL functions | ~350 |
| `Worker/NotifyWorker.cs` | BackgroundService with parallel processing | ~350 |
| `Providers/INotificationProvider.cs` | Provider interface | ~40 |
| `Providers/WhatsAppProvider.cs` | WhatsApp Cloud API (no PII logging) | ~300 |
| `Providers/SendGridProvider.cs` | SendGrid email provider | ~250 |
| `Api/WebhookController.cs` | Signature verification for webhooks | ~250 |
| `Api/NotifyController.cs` | RBAC endpoints (requeue, dead-letter) | ~200 |
| `Program.cs` | DI setup, HostedService registration | ~100 |

**xUnit Tests (`backend_dotnet/Solvereign.Notify.Tests/`):**

| File | Tests | Purpose |
|------|-------|---------|
| `ConcurrencyClaimingTests.cs` | 4 | Two workers claim without overlap |
| `DeduplicationTests.cs` | 5 | Deterministic SHA-256 dedup key |
| `RetryBackoffTests.cs` | 5 | Exponential backoff, max attempts |
| `StuckReaperTests.cs` | 8 | SENDING with expired lock → RETRYING |
| `WebhookSignatureTests.cs` | 12 | Invalid sig → 401, idempotent processing |
| `PIIHygieneTests.cs` | 11 | No raw phone/email in notify schema |

### Migration 035: Key Additions

**Schema Enhancements:**
```sql
-- State machine with CHECK constraint
ALTER TABLE notify.notification_outbox
ADD COLUMN status VARCHAR(20) DEFAULT 'PENDING'
CONSTRAINT status_check CHECK (status IN (
    'PENDING', 'SENDING', 'SENT', 'DELIVERED',
    'RETRYING', 'SKIPPED', 'FAILED', 'DEAD', 'CANCELLED'
));

-- Lock columns for concurrency
ADD COLUMN locked_at TIMESTAMPTZ;
ADD COLUMN locked_by VARCHAR(100);
ADD COLUMN lock_expires_at TIMESTAMPTZ;

-- Dedup key for idempotency
ADD COLUMN dedup_key VARCHAR(64);
CREATE UNIQUE INDEX idx_outbox_dedup_key ON notification_outbox(tenant_id, dedup_key)
WHERE dedup_key IS NOT NULL;
```

**New Tables:**
- `notify.webhook_events` - Idempotent webhook processing (unique on provider + event_id)
- `notify.rate_limit_buckets` - Token bucket per provider/tenant

**Core Functions:**
| Function | Purpose |
|----------|---------|
| `notify.claim_outbox_batch()` | Atomic claiming with SKIP LOCKED |
| `notify.release_stuck_sending()` | Reaper for stuck SENDING messages |
| `notify.mark_outbox_sent/retry/dead/skipped()` | Status transitions |
| `notify.process_webhook_event()` | Idempotent webhook processing |
| `notify.check_rate_limit()` | Token bucket rate limiting |
| `notify.compute_dedup_key()` | SHA-256 semantic deduplication |
| `notify.verify_notification_integrity()` | 12 checks (was 8) |

### Dedup Key Design

```
SHA-256(tenant_id | site_id | snapshot_id | driver_id | channel | template | version)
```

Prevents duplicate sends for same driver + plan + channel combination.

### Webhook Security

**WhatsApp:**
```csharp
// Verify X-Hub-Signature-256 header
var expected = "sha256=" + HMAC_SHA256(body, secret);
return CryptographicOperations.FixedTimeEquals(expected, header);
```

**SendGrid:**
```csharp
// Verify X-Twilio-Email-Event-Webhook-Signature + timestamp
var payload = timestamp + body;
var expected = HMAC_SHA256(payload, secret);
// Also check timestamp freshness (< 5 min)
```

### Worker Configuration

```bash
# .NET Worker Config
NOTIFY_WORKER_BATCH_SIZE=10
NOTIFY_WORKER_POLL_INTERVAL_SECONDS=5
NOTIFY_WORKER_LOCK_DURATION_SECONDS=300
NOTIFY_WORKER_MAX_CONCURRENT=5
NOTIFY_WORKER_REAPER_INTERVAL_SECONDS=60

# Provider Config
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
WHATSAPP_ACCESS_TOKEN=your-access-token
WHATSAPP_WEBHOOK_SECRET=your-hmac-secret
SENDGRID_API_KEY=your-api-key
SENDGRID_FROM_EMAIL=noreply@solvereign.com
SENDGRID_WEBHOOK_SECRET=your-hmac-secret
```

### API Endpoints (RBAC)

| Endpoint | Method | Role | Purpose |
|----------|--------|------|---------|
| `/api/v1/notify/dead-letter` | GET | Dispatcher | List dead-letter messages |
| `/api/v1/notify/requeue` | POST | Approver | Requeue dead-letter messages |
| `/api/v1/notify/health` | GET | - | Worker health check |
| `/webhooks/whatsapp` | POST | - | WhatsApp webhook (signature verified) |
| `/webhooks/sendgrid` | POST | - | SendGrid webhook (signature verified) |

### Verification Commands

```bash
# Apply migration (PATCH - idempotent)
psql $DATABASE_URL < backend_py/db/migrations/035_notifications_hardening.sql

# Verify integrity (should return 12 PASS)
psql $DATABASE_URL -c "SELECT * FROM notify.verify_notification_integrity();"

# Build .NET worker
cd backend_dotnet/Solvereign.Notify
dotnet build

# Run xUnit tests
cd backend_dotnet/Solvereign.Notify.Tests
dotnet test

# Start worker (Docker)
docker build -t solvereign-notify-worker ./backend_dotnet/Solvereign.Notify
docker run -d --name notify-worker \
    -e DATABASE_URL="..." \
    -e WHATSAPP_ACCESS_TOKEN="..." \
    solvereign-notify-worker
```

### Runbook Notes

**Starting the Worker:**
```bash
# Development
cd backend_dotnet/Solvereign.Notify
dotnet run

# Production (Docker)
docker-compose up -d notify-worker
```

**Health Checks:**
```bash
# Check worker is processing
curl http://localhost:5000/api/v1/notify/health

# Check for stuck messages
psql $DATABASE_URL -c "SELECT COUNT(*) FROM notify.notification_outbox
    WHERE status = 'SENDING' AND lock_expires_at < NOW();"

# Check dead-letter queue
psql $DATABASE_URL -c "SELECT COUNT(*) FROM notify.notification_outbox
    WHERE status = 'DEAD';"
```

**Manual Requeue (Admin):**
```bash
# Requeue specific message
curl -X POST http://localhost:5000/api/v1/notify/requeue \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"outbox_ids": ["uuid1", "uuid2"]}'
```

**Typical Failure Modes:**

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Messages stuck in SENDING | Worker crashed | Reaper auto-releases after 5 min |
| High rate of RETRYING | Provider rate limit | Check rate_limit_buckets, increase backoff |
| Dead-letter growing | Invalid contact data | Fix data in masterdata, requeue |
| Webhook events not updating | Invalid signature | Check webhook secret matches provider config |
| Duplicate sends | Missing dedup_key | Ensure compute_dedup_key() called at enqueue |

### V4.1.1 Definition of Done

- [x] Migration 035_notifications_hardening.sql (PATCH)
- [x] Status state machine with CHECK constraints
- [x] Lock columns for concurrency (locked_at, locked_by, lock_expires_at)
- [x] Dedup key column with unique index
- [x] claim_outbox_batch() with SKIP LOCKED
- [x] release_stuck_sending() reaper function
- [x] Webhook events table with idempotent processing
- [x] Rate limit buckets with token bucket
- [x] verify_notification_integrity() enhanced (12 checks)
- [x] C# NotifyWorker HostedService
- [x] C# Repository with Dapper + PostgreSQL functions
- [x] WhatsApp provider (no PII logging)
- [x] SendGrid provider (no PII logging)
- [x] Webhook signature verification (HMAC-SHA256)
- [x] RBAC endpoints (dead-letter, requeue)
- [x] xUnit tests: Concurrency, Dedup, Retry, Reaper, Webhook, PII
- [ ] Integration test with real providers (P1)
- [ ] Kubernetes deployment manifests (P2)

---

## V3.7 Commit Summary (Jan 9, 2026)

**Commit**: `6345ca4` - `feat(v3.7): complete Wien Pilot infrastructure + 85/100 staging ready`

### What's Included

| Category | Files | Key Features |
|----------|-------|--------------|
| Routing Pack | 68+ tests | VRPTW solver, OSRM Austria, 6 gates |
| Enterprise Skills | 88 tests | Audit Report, Golden Datasets, KPI Drift, Impact Preview |
| Security Stack | 50+ tests | 7 migrations (025-025f), RLS hardening |
| P0 Precedence | 28 tests | Pickup-delivery, multi-start determinism |
| Plan Versioning | 5 checks | plan_snapshots, repair flow, freeze audit |
| Dispatcher Cockpit | 4 tabs | Runs, publish, lock, evidence |

### Fixes in This Commit

| Issue | Resolution |
|-------|------------|
| Route conflict (`/runs` vs `/(platform)/runs`) | Deleted legacy `app/runs/` directory |
| `next build` failures | Clean build passes |
| API test failures (15 tests) | 13 marked xfail (DB-dependent), 0 real failures |
| Evidence fields missing | Added 5 fields: `input_hash`, `output_hash`, `evidence_hash`, `evidence_path`, `artifact_uri` |
| Staging E2E tests | Created `staging-publish.spec.ts` (publish, freeze 409, force publish) |

### Rating: 85/100 Staging Ready

**Blocking for Production**:
- [ ] Token audience verification in staging (Entra ID)
- [ ] Evidence screenshot from live solver run
- [ ] E2E test with real MSAL authentication

**See**: `docs/SAAS_RATING_REPORT.md` for detailed assessment.

---

## Next Steps: Wien Pilot Launch

### Immediate Actions (Gate-Based)

**Reference**: See "Wien Pilot Pre-Flight Gates" section above for full details.

1. **Gate A: Entra ID Verification** (Needs staging token)
   ```bash
   export STAGING_URL=https://staging.solvereign.com
   export STAGING_TOKEN=<entra_bearer_token>
   python scripts/staging_preflight.py
   ```

2. **Gate B: Security Headers** (Needs staging access)
   ```bash
   curl -I https://staging.solvereign.com/my-plan | grep -i "referrer\|cache-control\|frame-options\|csp"
   ```

3. **Gate C: Real Provider E2E** (Needs real API keys)
   ```bash
   python scripts/e2e_portal_notify_evidence.py --env staging
   ```

4. **Gate D: Production Migrations** (After Gates A-C pass)
   ```bash
   psql $DATABASE_URL_PROD < backend_py/db/migrations/037_portal_notify_integration.sql
   psql $DATABASE_URL_PROD < backend_py/db/migrations/037a_portal_notify_hardening.sql
   ```

### Wien Pilot Launch Sequence

```
Gate A (Entra ID) ──┐
Gate B (Headers) ───┼──► Gate D (Migrations) ──► Gate E (Feature Flag) ──► LAUNCH
Gate C (Providers) ─┘                          └──► Gate F (Cookie Test)
```

### Pending Work Items

| Priority | Gate | Task | Status |
|----------|------|------|--------|
| **P0** | **A** | **Entra ID aud/iss verification** | **Needs staging token** |
| **P0** | **B** | **Security headers per curl** | **Needs staging access** |
| **P0** | **C** | **Real Provider E2E** | **Needs API keys** |
| **P0** | **D** | **Prod migrations (037/037a/038)** | **Blocked by A-C** |
| P1 | E | Feature flag + rollback test | Ready to test |
| P1 | F | Cookie flags + refresh test | Ready to test |

### Contacts

| Role | Name | Status |
|------|------|--------|
| Platform Lead | TBD | - |
| DBA | TBD | - |
| On-Call | TBD | - |

---

## V3.8: Master Data Layer + Dispatch Assist (Jan 9, 2026)

### Overview

Platform expansion beyond Routing Pack with two new components:

1. **Master Data Layer (MDL)** - Kernel service for canonical entities and external ID mapping
2. **Gurkerl Dispatch Assist** - MVP for open shift detection and candidate suggestions

### Part A: Master Data Layer (MDL P0)

**Purpose**: Canonical entities + external-id mappings so packs never store external IDs directly.

| Table | Purpose |
|-------|---------|
| `masterdata.md_sites` | Depots/hubs per tenant |
| `masterdata.md_locations` | Geocoded addresses (lat/lng) |
| `masterdata.md_vehicles` | Fleet vehicles with capacity |
| `masterdata.md_external_mappings` | External ID → Internal UUID |

**Mapping Rule**:
```
(tenant_id, external_system, entity_type, external_id) → internal_uuid
```

**API Endpoints**:
- `POST /api/v1/masterdata/resolve` - Resolve or create mapping
- `POST /api/v1/masterdata/resolve-bulk` - Batch resolve (up to 1000 IDs)
- `GET /api/v1/masterdata/mappings` - List mappings
- `GET /api/v1/masterdata/sites` - List sites
- `GET /api/v1/masterdata/vehicles` - List vehicles
- `GET /api/v1/masterdata/integrity` - Health check

**Files**:
- Migration: `backend_py/db/migrations/028_masterdata.sql`
- Router: `backend_py/api/routers/masterdata.py`
- Tests: `backend_py/api/tests/test_masterdata.py`
- Docs: `docs/MASTERDATA.md`

### Part B: Gurkerl Dispatch Assist (MVP)

**Problem**: ~200 drivers, daily absences. Google Sheets is source of truth for Gurkerl roster.
SOLVEREIGN provides assist functions (does NOT replace the Sheet).

**MVP Features**:
1. **Open Shift Detection** - Read Sheet, identify unassigned shifts
2. **Candidate Finder** - Hard constraint filtering (absence, rest, max hours)
3. **Scoring** - Soft ranking (fairness, minimal churn)
4. **Proposal Output** - Top N candidates with reasons

**Hard Constraints** (eligibility.py):
- Not absent (sick/vacation)
- 11-hour rest between shifts
- Max 2 tours per day
- Max 55 hours per week
- Required skills match
- Zone match

**Soft Ranking** (scoring.py):
- Fairness (under-target hours preferred)
- Minimal churn (already-working drivers preferred)
- Zone affinity
- Part-time balance

**API Endpoints**:
- `POST /api/v1/roster/dispatch/open-shifts` - Detect open shifts
- `POST /api/v1/roster/dispatch/suggest` - Get candidate suggestions
- `POST /api/v1/roster/dispatch/propose` - Generate proposals (optional write to Sheet)
- `GET /api/v1/roster/dispatch/health` - Module health

**Files**:
- Models: `backend_py/packs/roster/dispatch/models.py`
- Eligibility: `backend_py/packs/roster/dispatch/eligibility.py`
- Scoring: `backend_py/packs/roster/dispatch/scoring.py`
- Sheet Adapter: `backend_py/packs/roster/dispatch/sheet_adapter.py`
- Service: `backend_py/packs/roster/dispatch/service.py`
- API: `backend_py/packs/roster/api/dispatch.py`
- Tests: `backend_py/packs/roster/dispatch/tests/test_dispatch.py`

**Environment Variables** (for Google Sheets):
```bash
SHEETS_SPREADSHEET_ID=your-spreadsheet-id
SHEETS_SERVICE_ACCOUNT_JSON=/path/to/credentials.json
# OR inline JSON
SHEETS_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

### V3.8.2: Blindspot Fixes (Jan 9, 2026)

**MDL Hardening**:
- Added `md_locations_unique_coords` constraint (lat/lng rounded to 5 decimals = ~1.1m)
- Enhanced `verify_masterdata_integrity()` → 9 checks (was 6)
  - New: `entity_unique_constraints`, `tenant_id_not_null`, `tenant_fk_exists`
- Functions use caller privileges (NOT SECURITY DEFINER) - RLS applies normally

**Dispatch Hardening**:
- Added 5 overnight/weekend rest tests in `TestOvernightRestConstraint`
- Verified `SheetConfig` is used throughout (no hardcoded columns)
- DisqualificationReason codes returned with all candidates

### V3.8 Definition of Done

- [x] MDL migration 028 with RLS, unique constraints
- [x] MDL API (resolve, resolve-bulk, mappings)
- [x] MDL tests (idempotency, unique constraints)
- [x] MDL location deduplication (lat/lng rounding)
- [x] MDL verify function enhanced (9 checks)
- [x] Dispatch MVP models
- [x] Dispatch eligibility (7 hard constraints)
- [x] Dispatch scoring (5 soft factors)
- [x] Sheet adapter (read roster, write proposals)
- [x] Dispatch API (open-shifts, suggest, propose)
- [x] Dispatch tests (including overnight rest edge cases)
- [ ] Integration test with real Google Sheet (P1)
- [ ] Swap engine (1-swap, 2-swap) (P2)

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
| **Dispatcher Platform** | `backend_py/api/routers/dispatcher_platform.py` | ~825 |
| **Staging E2E** | `frontend_v5/e2e/staging-publish.spec.ts` | ~180 |
| **Test Classification** | `backend_py/api/tests/TEST_FAILURE_CLASSIFICATION.md` | ~120 |
| **SaaS Rating** | `docs/SAAS_RATING_REPORT.md` | ~150 |
| **SaaS Reality** | `docs/SAAS_DEPLOYMENT_REALITY.md` | ~270 |
| **MDL Migration** | `backend_py/db/migrations/028_masterdata.sql` | ~650 |
| **MDL Router** | `backend_py/api/routers/masterdata.py` | ~380 |
| **Dispatch Models** | `backend_py/packs/roster/dispatch/models.py` | ~280 |
| **Dispatch Eligibility** | `backend_py/packs/roster/dispatch/eligibility.py` | ~250 |
| **Dispatch Scoring** | `backend_py/packs/roster/dispatch/scoring.py` | ~200 |
| **Dispatch Adapter** | `backend_py/packs/roster/dispatch/sheet_adapter.py` | ~750 |
| **Dispatch Service** | `backend_py/packs/roster/dispatch/service.py` | ~820 |
| **Dispatch Tests** | `backend_py/packs/roster/dispatch/tests/test_dispatch.py` | ~600 |
| **Dispatch Lifecycle** | `backend_py/db/migrations/031_dispatch_lifecycle.sql` | ~450 |
| **Dispatch Repository** | `backend_py/packs/roster/dispatch/repository.py` | ~520 |
| **Dispatch API** | `backend_py/packs/roster/api/dispatch.py` | ~695 |
| **Apply Tests** | `backend_py/packs/roster/dispatch/tests/test_apply.py` | ~1100 |
| **Fingerprint Tests** | `backend_py/packs/roster/dispatch/tests/test_fingerprint.py` | ~280 |
| **Portal Migration** | `backend_py/db/migrations/033_portal_magic_links.sql` | ~650 |
| **Portal Models** | `backend_py/packs/portal/models.py` | ~350 |
| **Portal Tokens** | `backend_py/packs/portal/token_service.py` | ~350 |
| **Portal Repository** | `backend_py/packs/portal/repository.py` | ~500 |
| **Portal Renderer** | `backend_py/packs/portal/renderer.py` | ~350 |
| **Portal Public API** | `backend_py/api/routers/portal_public.py` | ~350 |
| **Portal Admin API** | `backend_py/api/routers/portal_admin.py` | ~350 |
| **Portal Tests** | `backend_py/packs/portal/tests/test_portal.py` | ~450 |
| **Notify Migration** | `backend_py/db/migrations/034_notifications.sql` | ~650 |
| **Notify Models** | `backend_py/packs/notify/models.py` | ~400 |
| **Notify Repository** | `backend_py/packs/notify/repository.py` | ~500 |
| **Notify Worker** | `backend_py/packs/notify/worker.py` | ~300 |
| **WhatsApp Provider** | `backend_py/packs/notify/providers/whatsapp.py` | ~300 |
| **Email Provider** | `backend_py/packs/notify/providers/email.py` | ~250 |
| **Notify API** | `backend_py/api/routers/notifications.py` | ~400 |
| **Notify Tests** | `backend_py/packs/notify/tests/test_notifications.py` | ~500 |
| **Notify Hardening** | `backend_py/db/migrations/035_notifications_hardening.sql` | ~650 |
| **C# Notify Worker** | `backend_dotnet/Solvereign.Notify/Worker/NotifyWorker.cs` | ~350 |
| **C# Notify Repo** | `backend_dotnet/Solvereign.Notify/Repository/NotifyRepository.cs` | ~350 |
| **C# WhatsApp** | `backend_dotnet/Solvereign.Notify/Providers/WhatsAppProvider.cs` | ~300 |
| **C# SendGrid** | `backend_dotnet/Solvereign.Notify/Providers/SendGridProvider.cs` | ~250 |
| **C# Webhooks** | `backend_dotnet/Solvereign.Notify/Api/WebhookController.cs` | ~350 |
| **C# Notify Tests** | `backend_dotnet/Solvereign.Notify.Tests/*.cs` | ~50 tests |
| **Notify Retention** | `backend_py/db/migrations/036_notifications_retention.sql` | ~500 |
| **Portal Link Service** | `backend_py/packs/portal/link_service.py` | ~550 |
| **Portal-Notify Migration** | `backend_py/db/migrations/037_portal_notify_integration.sql` | ~350 |
| **Portal-Notify Hardening** | `backend_py/db/migrations/037a_portal_notify_hardening.sql` | ~400 |
| **Portal Link Tests** | `backend_py/packs/portal/tests/test_link_service.py` | ~350 |
| **Frontend my-plan** | `frontend_v5/app/my-plan/page.tsx` | ~495 |
| **Frontend Portal API** | `frontend_v5/lib/portal-api.ts` | ~415 |
| **Frontend Portal Types** | `frontend_v5/lib/portal-types.ts` | ~200 |
| **Frontend Format Utils** | `frontend_v5/lib/format.ts` | ~335 |
| **Portal Session Route** | `frontend_v5/app/api/portal/session/route.ts` | ~130 |
| **Portal Read Route** | `frontend_v5/app/api/portal/read/route.ts` | ~65 |
| **Portal Ack Route** | `frontend_v5/app/api/portal/ack/route.ts` | ~95 |
| **Driver Table Component** | `frontend_v5/components/portal/driver-table.tsx` | ~255 |
| **Driver Drawer Component** | `frontend_v5/components/portal/driver-drawer.tsx` | ~220 |
| **Dispatcher Dashboard** | `frontend_v5/app/(platform)/portal-admin/dashboard/page.tsx` | ~350 |
| **Staging Pre-Flight** | `scripts/staging_preflight.py` | ~465 |
| **Wien Pilot Blockers** | `docs/WIEN_PILOT_BLOCKERS.md` | ~210 |
| **E2E Evidence Script** | `scripts/e2e_portal_notify_evidence.py` | ~600 |

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
psql $DATABASE_URL < backend_py/db/migrations/028_masterdata.sql
psql $DATABASE_URL < backend_py/db/migrations/031_dispatch_lifecycle.sql
psql $DATABASE_URL < backend_py/db/migrations/033_portal_magic_links.sql
psql $DATABASE_URL < backend_py/db/migrations/034_notifications.sql
psql $DATABASE_URL < backend_py/db/migrations/035_notifications_hardening.sql
psql $DATABASE_URL < backend_py/db/migrations/036_notifications_retention.sql
psql $DATABASE_URL < backend_py/db/migrations/037_portal_notify_integration.sql
psql $DATABASE_URL < backend_py/db/migrations/037a_portal_notify_hardening.sql

# Verify security (SOURCE OF TRUTH)
psql $DATABASE_URL -c "SELECT * FROM verify_final_hardening();"

# Verify plan versioning
psql $DATABASE_URL -c "SELECT * FROM verify_snapshot_integrity();"

# Verify master data layer (9 checks)
psql $DATABASE_URL -c "SELECT * FROM masterdata.verify_masterdata_integrity();"

# Verify dispatch lifecycle (12 checks)
psql $DATABASE_URL -c "SELECT * FROM dispatch.verify_dispatch_integrity();"

# Verify portal integrity (8 checks)
psql $DATABASE_URL -c "SELECT * FROM portal.verify_portal_integrity();"

# Verify notification integrity (13 checks after retention migration)
psql $DATABASE_URL -c "SELECT * FROM notify.verify_notification_integrity();"

# Verify portal-notify integration (4 checks)
psql $DATABASE_URL -c "SELECT * FROM portal.verify_notify_integration();"

# Check old records pending cleanup
psql $DATABASE_URL -c "SELECT * FROM notify.count_old_records(30);"

# Generate ACL report for CI
psql $DATABASE_URL -c "SELECT acl_scan_report_json();" -t > acl_scan_report.json

# Run Python tests
pytest backend_py/tests/test_final_hardening.py -v
pytest backend_py/tests/test_tenants_rls.py -v
pytest backend_py/packs/roster/dispatch/tests/test_dispatch.py -v
pytest backend_py/packs/portal/tests/test_portal.py -v
pytest backend_py/packs/portal/tests/test_link_service.py -v

# Run C#/.NET tests (notification hardening)
cd backend_dotnet/Solvereign.Notify.Tests && dotnet test

# Wien Pilot smoke test
python scripts/wien_pilot_smoke_test.py --env staging

# Staging pre-flight checks (Gate A, B verification)
export STAGING_URL=https://staging.solvereign.com
export STAGING_TOKEN=<entra_bearer_token>
python scripts/staging_preflight.py

# E2E portal-notify evidence (Gate C verification)
python scripts/e2e_portal_notify_evidence.py --env staging

# Frontend TypeScript check
cd frontend_v5 && npx tsc --noEmit

# Frontend build
cd frontend_v5 && npx next build
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

**Total Codebase**: ~158,000 lines (V3.9 adds ~3,000 lines)
**Test Coverage**: 50+ security tests, 88 enterprise skill tests, 68 routing tests, 28 P0 precedence tests, 5 snapshot integrity checks, 9 MDL integrity checks, 12 dispatch integrity checks, ~90 dispatch tests (including apply + fingerprint), 13 API tests (xfail for DB)

---

## API Test Status

| Category | Count | Status |
|----------|-------|--------|
| Passing | 88 | ✅ OK |
| xfail (DB-dependent) | 13 | Tracked in `TEST_FAILURE_CLASSIFICATION.md` |
| Skipped | 5 | Intentional |
| **Total** | **106** | **98% healthy** |

**Key File**: `backend_py/api/tests/TEST_FAILURE_CLASSIFICATION.md`

---

*For detailed implementation history, see `docs/SAAS_DEPLOYMENT_REALITY.md`, `docs/SAAS_RATING_REPORT.md`, and `backend_py/ROADMAP.md`*
