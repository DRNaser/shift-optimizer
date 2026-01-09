# SOLVEREIGN V4.3 - Portal Pilot Launch Checklist

> **Target**: Wien Pilot Launch
> **Date**: 2026-01
> **Status**: READY FOR PILOT

---

## Pre-Flight Checks

### 1. Production Migrations

```bash
# Order: 036 → 037 → 037a (must be sequential)

# Step 1: Pre-migration verification
python scripts/prod_migration_gate.py --env prod --phase pre
# Expected: ALL CHECKS PASS

# Step 2: Apply migrations
psql $DATABASE_URL_PROD < backend_py/db/migrations/037_portal_notify_integration.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/037a_portal_notify_hardening.sql
psql $DATABASE_URL_PROD < backend_py/db/migrations/038_bounce_dnc.sql

# Step 3: Post-migration verification
python scripts/prod_migration_gate.py --env prod --phase post
# Expected: ALL CHECKS PASS

# Step 4: Verify all integrity functions
psql $DATABASE_URL_PROD -c "SELECT * FROM portal.verify_notify_integration();"
psql $DATABASE_URL_PROD -c "SELECT * FROM notify.verify_notification_integrity();"
# Expected: ALL checks return PASS
```

- [ ] Pre-migration gate PASS
- [ ] Migrations applied successfully
- [ ] Post-migration gate PASS
- [ ] verify_notify_integration() returns all PASS
- [ ] verify_notification_integrity() returns 14 PASS (after 038)

---

### 2. Real Provider Integration Test

```bash
# Run in staging with real providers
python scripts/e2e_portal_notify_evidence.py --env staging --real-providers

# Expected output:
# - notification_created: PASS
# - outbox_sent: PASS (with real message ID)
# - portal_accessible: PASS
# - read_recorded: PASS
# - view_status_correct: PASS
```

- [ ] SendGrid email delivered (check inbox)
- [ ] WhatsApp message received (if enabled)
- [ ] Webhook events recorded in `notify.webhook_events`
- [ ] Evidence JSON artifact saved

---

### 3. Security Headers Verification

```bash
# Check headers on /my-plan page
curl -I https://portal.solvereign.com/my-plan?t=test

# Expected headers:
# Referrer-Policy: no-referrer
# Cache-Control: no-store, no-cache, must-revalidate, proxy-revalidate
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
# Content-Security-Policy: default-src 'self'; ...
```

- [ ] Referrer-Policy: no-referrer
- [ ] Cache-Control: no-store
- [ ] X-Frame-Options: DENY
- [ ] CSP baseline set

---

### 4. RBAC Verification

```bash
# Test rate limiting on dashboard/resend
# Should return 429 after 10 requests in 1 hour

for i in {1..12}; do
  curl -X POST https://api.solvereign.com/api/v1/portal/dashboard/resend \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"snapshot_id":"test","filter":"UNREAD"}'
done

# Request 11 and 12 should return 429
```

- [ ] Rate limit works (10/hour)
- [ ] Audit log contains PORTAL_RESEND_TRIGGERED events
- [ ] Batch hard limit enforced (max 500)

---

### 5. Frontend Smoke Test

```bash
# Open portal with test token
open "https://portal.solvereign.com/my-plan?t=<test_token>"
```

Manual checks:
- [ ] Page loads without errors
- [ ] Driver name and shifts display correctly
- [ ] Accept button works
- [ ] Decline modal opens and submits reason
- [ ] Status badge updates after ack
- [ ] Superseded state shows "new version" message
- [ ] Expired/revoked shows error state
- [ ] No token visible in browser console (F12)

---

### 6. Dashboard Verification

```bash
# Test dashboard endpoints
curl "https://api.solvereign.com/api/v1/portal/dashboard/summary?snapshot_id=<uuid>" \
  -H "Authorization: Bearer $TOKEN"

curl "https://api.solvereign.com/api/v1/portal/dashboard/details?snapshot_id=<uuid>&filter=UNREAD" \
  -H "Authorization: Bearer $TOKEN"
```

- [ ] Summary returns KPI cards
- [ ] Details returns filtered driver list
- [ ] Pagination works (page, page_size)
- [ ] Filters work: UNREAD, UNACKED, ACCEPTED, DECLINED

---

## Go-Live Runbook

### Step 1: Enable Portal for Tenant

```sql
-- Enable portal for LTS Transport (tenant_id = 1)
UPDATE tenants
SET features = features || '{"portal_enabled": true}'::jsonb
WHERE id = 1;
```

### Step 2: Create First Snapshot

1. Dispatcher approves plan in cockpit
2. Click "Publish to Portal"
3. Select drivers to notify
4. Choose delivery channel (WhatsApp/Email)
5. Confirm publish

### Step 3: Monitor First Wave

```sql
-- Check notification status
SELECT * FROM portal.snapshot_notify_summary
WHERE tenant_id = 1
ORDER BY first_issued_at DESC
LIMIT 5;

-- Check for failures
SELECT COUNT(*) as failed_count
FROM notify.notification_outbox
WHERE tenant_id = 1 AND status = 'FAILED';
```

### Step 4: Handle Escalations

If messages fail:
1. Check `notify.notification_outbox` for error details
2. Check `notify.webhook_events` for provider responses
3. Use dashboard "Resend to failed" action
4. If persistent, check provider credentials

---

## Rollback Plan

### If Migration Fails

```sql
-- Rollback is complex, prefer fixing forward
-- Contact DBA before attempting rollback

-- Emergency: disable portal feature
UPDATE tenants
SET features = features - 'portal_enabled'
WHERE id = 1;
```

### If Provider Fails

```sql
-- Switch to backup channel
UPDATE notify.notification_outbox
SET delivery_channel = 'EMAIL',
    status = 'PENDING',
    attempts = 0
WHERE status = 'FAILED'
AND delivery_channel = 'WHATSAPP';

-- Restart worker to pick up
```

---

## Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Token issuance success | > 99% | `success_count / total_count` |
| Notification delivery | > 95% | `DELIVERED / total` |
| Portal read rate | > 80% | `read_count / total` |
| Ack completion | > 70% | `(accepted + declined) / total` |
| P95 response time | < 500ms | API metrics |

---

## V4.3 Production Hardening (Jan 9, 2026)

### CSP Hardening
- [x] No external img-src (removed `https:` wildcard)
- [x] form-action restricted to 'self'
- [x] base-uri restricted to 'self'
- [x] frame-ancestors set to 'none'

### DECLINED Resend Guardrail
- [x] `include_declined=true` flag required to target DECLINED drivers
- [x] `declined_reason` (min 10 chars) required when using DECLINED filter
- [x] `PORTAL_RESEND_DECLINED` audit log event

### JWT Key Rotation
- [x] `PORTAL_JWT_SECRET_SECONDARY` env var for rotation
- [x] Primary key used for signing, both tried for validation
- [x] Graceful fallback when signature doesn't match primary

### Bounce/Complaint Handling
- [x] `WebhookEventType.BOUNCE`, `SOFT_BOUNCE`, `COMPLAINT`, `UNSUBSCRIBE` events
- [x] `DoNotContactReason` enum for tracking
- [x] Auto-set `do_not_contact_email/whatsapp/sms` on hard bounce/complaint
- [x] Soft bounce threshold (3) before setting do_not_contact
- [x] `clear_do_not_contact()` for admin override with audit
- [x] **Migration 038_bounce_dnc.sql** - DB columns + functions
- [x] **DNC Enforcement at Outbox Creation** - `issue_token_atomic()` checks `check_can_contact()`
- [x] **DNC Enforcement at Send Time** - Worker re-checks before sending, marks SKIPPED if DNC

### SKIPPED Status Handling
- [x] SKIPPED counted separately in Dashboard (not as FAILED)
- [x] `skipped_count` in `snapshot_notify_summary` view
- [x] `delivery_rate` excludes SKIPPED from denominator (send-attemptable basis)
- [x] `send_attemptable_count` column for KPI calculation
- [x] Resend to SKIPPED requires `include_skipped=true` + `skipped_reason` (min 10 chars)
- [x] `PORTAL_RESEND_SKIPPED` audit log event (WARNING level)

### DNC Override Cooldown
- [x] `dnc_cleared_at` column on driver_preferences
- [x] `check_dnc_cooldown()` function (default 1 hour)
- [x] `clear_do_not_contact()` sets cooldown timestamp + `dnc_cleared_by`
- [x] WARNING level audit on DNC clear

```bash
# Apply bounce/dnc migration
psql $DATABASE_URL < backend_py/db/migrations/038_bounce_dnc.sql

# Verify (should return 14 checks)
psql $DATABASE_URL -c "SELECT * FROM notify.verify_notification_integrity();"

# Test bounce handling
psql $DATABASE_URL -c "SELECT notify.handle_bounce_complaint(1, 'TEST-DRV', 'EMAIL', 'BOUNCE');"
psql $DATABASE_URL -c "SELECT notify.check_can_contact(1, 'TEST-DRV', 'EMAIL');"  -- Should be FALSE

# Test DNC override with cooldown
psql $DATABASE_URL -c "SELECT notify.clear_do_not_contact(1, 'TEST-DRV', 'EMAIL', 'admin@lts.at', 'Address corrected after verification');"
psql $DATABASE_URL -c "SELECT notify.check_dnc_cooldown(1, 'TEST-DRV');"  -- FALSE (in cooldown)
-- Wait 1 hour...
psql $DATABASE_URL -c "SELECT notify.check_dnc_cooldown(1, 'TEST-DRV');"  -- TRUE (cooldown passed)
```

### Evidence Storage
- [x] `scripts/evidence_store.py` utility created
- [x] Date-partitioned storage: `evidence/YYYY-MM-DD/*.json`
- [x] Latest symlinks: `evidence/latest/*.json`
- [x] 90-day retention with automatic cleanup
- [x] Integration with `prod_migration_gate.py`
- [x] Integration with `e2e_portal_notify_evidence.py`

```bash
# List recent evidence
python scripts/evidence_store.py list --category e2e --env staging

# View latest evidence
python scripts/evidence_store.py latest --category e2e_portal_notify --env staging

# Cleanup old evidence
python scripts/evidence_store.py cleanup
```

---

## Contacts

| Role | Name | Contact |
|------|------|---------|
| Platform Lead | - | - |
| DB Admin | - | - |
| On-Call | - | - |

---

**Last Updated**: 2026-01-09
**Approved By**: [Pending]
