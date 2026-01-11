# SOLVEREIGN GA Deployment Runbook

> **Version**: 1.0.0
> **Last Updated**: 2026-01-11
> **Target**: P0-P2 Market Readiness Implementation

---

## Deploy Order (Staging → Production)

### A) Database Migrations (First)

```bash
# 1. Legal acceptance tracking
psql $DATABASE_URL < backend_py/db/migrations/044_legal_acceptance.sql

# 2. Stripe billing schema
psql $DATABASE_URL < backend_py/db/migrations/045_stripe_billing.sql

# 3. GDPR consent management
psql $DATABASE_URL < backend_py/db/migrations/046_consent_management.sql
```

**Verification after each migration:**
```sql
-- Legal
SELECT * FROM auth.verify_legal_acceptance_integrity();

-- Billing
SELECT * FROM billing.verify_billing_schema();

-- Consent
SELECT * FROM consent.verify_consent_schema();
```

All checks must return `PASS`.

---

### B) Environment Variables

#### Sentry (Error Tracking)
```env
SOLVEREIGN_SENTRY_DSN=https://xxx@o123.ingest.sentry.io/456
SENTRY_ENVIRONMENT=staging|production
SENTRY_RELEASE=v4.7.0  # or git SHA
SOLVEREIGN_SENTRY_TRACES_SAMPLE_RATE=0.1  # Start low, increase if needed
SOLVEREIGN_SENTRY_PROFILES_SAMPLE_RATE=0.1
```

#### Stripe (Billing)
```env
SOLVEREIGN_STRIPE_API_KEY=sk_live_...  # or sk_test_... for staging
SOLVEREIGN_STRIPE_WEBHOOK_SECRET=whsec_...
SOLVEREIGN_STRIPE_DEFAULT_CURRENCY=eur

# Optional: Lock API version to prevent drift
STRIPE_API_VERSION=2024-12-18.acacia
```

**CRITICAL**: Configure webhook endpoint in Stripe Dashboard:
- URL: `https://api.solvereign.com/api/billing/webhook`
- Events: `customer.subscription.*`, `invoice.*`, `payment_method.attached`

#### Backups (S3)
```env
BACKUP_S3_BUCKET=solvereign-backups-prod
BACKUP_S3_PREFIX=postgresql/  # Use different prefix per env
BACKUP_RETENTION_DAYS=30
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=eu-central-1
BACKUP_WEBHOOK_URL=https://hooks.slack.com/services/...  # Optional
SOLVEREIGN_ENVIRONMENT=production
```

---

### C) Deploy Backend

```bash
# 1. Build and push image
docker build -t ghcr.io/solvereign/api:v4.7.0 .
docker push ghcr.io/solvereign/api:v4.7.0

# 2. Deploy (Kubernetes)
kubectl set image deployment/api api=ghcr.io/solvereign/api:v4.7.0

# 3. Verify startup logs
kubectl logs -f deployment/api | grep -E "(sentry|stripe|billing)"
```

**Expected logs:**
```
sentry_error_tracking_enabled
stripe_billing_initialized
billing_router_registered
```

---

### D) Deploy Frontend

```bash
# Vercel auto-deploys from main branch
# Or manual:
cd frontend_v5 && vercel --prod
```

**Verify:**
- `/legal/terms` loads
- `/legal/privacy` loads
- `/legal/imprint` loads
- Consent banner appears on first visit

---

### E) Deploy Backup CronJob

```bash
# 1. Build backup image
docker build -f docker/Dockerfile.backup -t ghcr.io/solvereign/backup:latest .
docker push ghcr.io/solvereign/backup:latest

# 2. Deploy CronJob
kubectl apply -f k8s/backup-cronjob.yaml

# 3. Verify (trigger manual job)
kubectl create job --from=cronjob/solvereign-backup backup-test-$(date +%s)
kubectl logs job/backup-test-*
```

---

## Common Pitfalls & Verification

### 1. CronJob Timezone

The CronJob is set to `02:00 UTC`, not Vienna local time.

| UTC | Vienna (Winter) | Vienna (Summer) |
|-----|-----------------|-----------------|
| 02:00 | 03:00 | 04:00 |

**To use Vienna time** (requires Kubernetes 1.27+):
```yaml
spec:
  timeZone: "Europe/Vienna"
  schedule: "0 2 * * *"
```

**Smoke test:**
```bash
# Temporarily set to run every 5 minutes
kubectl patch cronjob solvereign-backup -p '{"spec":{"schedule":"*/5 * * * *"}}'

# Watch for job completion
kubectl get jobs -w

# Restore original schedule
kubectl patch cronjob solvereign-backup -p '{"spec":{"schedule":"0 2 * * *"}}'
```

---

### 2. Stripe Webhooks: Signature & Idempotency

**Verify signature:**
```bash
# Send test webhook from Stripe CLI
stripe listen --forward-to localhost:8000/api/billing/webhook
stripe trigger invoice.paid
```

**Test idempotency:**
```python
# Send same event twice - should only process once
import requests

event_payload = {...}  # From Stripe
for _ in range(3):
    r = requests.post(
        "https://api.solvereign.com/api/billing/webhook",
        json=event_payload,
        headers={"Stripe-Signature": "..."}
    )
    print(r.json())  # Should show "skipped: already_processed" on 2nd/3rd

# Verify DB state unchanged after duplicates
psql -c "SELECT COUNT(*) FROM billing.webhook_events WHERE stripe_event_id = 'evt_xxx'"
# Should be 1, not 3
```

---

### 3. Billing Gating UX

**Test each status:**
```bash
# Set tenant to different statuses and verify behavior
psql -c "UPDATE tenants SET billing_status = 'past_due' WHERE id = 1"

# API call should return 402 for write operations
curl -X POST https://api.solvereign.com/api/v1/solver/solve \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nStatus: %{http_code}\n"

# Expected: 402 Payment Required
# {
#   "error": "subscription_required",
#   "message": "Payment overdue. Please update your payment method.",
#   "billing_status": "past_due"
# }

# Reset
psql -c "UPDATE tenants SET billing_status = 'active' WHERE id = 1"
```

---

### 4. Backup Restore Test

**CRITICAL: Test restore on staging before go-live!**

```bash
# 1. Download latest backup
aws s3 cp s3://solvereign-backups-prod/postgresql/solvereign_production_20260111_020000.dump ./

# 2. Create fresh test database
createdb solvereign_restore_test

# 3. Restore
pg_restore -d solvereign_restore_test solvereign_production_20260111_020000.dump

# 4. Verify
psql solvereign_restore_test -c "SELECT COUNT(*) FROM tenants"
psql solvereign_restore_test -c "SELECT * FROM verify_final_hardening()"

# 5. Start app against restored DB (staging only!)
DATABASE_URL=postgresql://localhost/solvereign_restore_test python -m uvicorn api.main:app

# 6. Cleanup
dropdb solvereign_restore_test
```

---

## Observability "Done" Criteria

### Sentry
- [ ] Test error appears as Issue in Sentry
- [ ] Tags visible: `tenant_id`, `request_id`, `environment`, `release`
- [ ] PII scrubbed: No emails, tokens, passwords in error data
- [ ] Performance traces appearing (if enabled)

**Test:**
```python
# Trigger test error (staging only!)
import sentry_sdk
sentry_sdk.capture_message("Deployment test - please ignore", level="info")
```

### Grafana/Prometheus
- [ ] Dashboard "SOLVEREIGN Overview" loads without "No data"
- [ ] All panels show live metrics
- [ ] Backup age panel shows recent timestamp

**Test alerts:**
```bash
# Temporarily break something to trigger alert
kubectl scale deployment/api --replicas=0
# Wait for SolvereignAPIDown alert
kubectl scale deployment/api --replicas=2
```

---

## Legal & Consent "Done" Criteria

### Legal Pages
- [ ] `/legal/terms` publicly accessible (no auth)
- [ ] `/legal/privacy` publicly accessible
- [ ] `/legal/imprint` publicly accessible
- [ ] Version + date shown on each page
- [ ] Links between pages work

### Acceptance Tracking
- [ ] First login shows acceptance prompt (if implemented)
- [ ] Acceptance recorded in `auth.legal_acceptances`
- [ ] Acceptance audit logged in `auth.audit_log`

**Verify:**
```sql
SELECT * FROM auth.legal_acceptances WHERE user_id = 1;
SELECT * FROM auth.audit_log WHERE event_type = 'legal.acceptance' LIMIT 5;
```

### Consent Banner
- [ ] Banner appears on first visit
- [ ] "Only necessary" saves minimal consents
- [ ] "Accept all" saves all consents
- [ ] Custom settings persist after reload
- [ ] Banner doesn't appear after consent given

**Verify:**
```javascript
// In browser console
localStorage.getItem('solvereign_consent')
// Should show: {"version":"1.0","timestamp":"...","purposes":{...}}
```

---

## Quick Rollback Plan

### Backend Rollback
```bash
# Rollback to previous image
kubectl rollout undo deployment/api

# Or specific version
kubectl set image deployment/api api=ghcr.io/solvereign/api:v4.6.0
```

### Frontend Rollback
```bash
# Vercel: Promote previous deployment
vercel rollback
```

### Database Rollback
- **Additive migrations** (new tables/columns): Usually no rollback needed
- **If critical**: Restore from backup

```bash
# Disable billing if causing issues
psql -c "UPDATE tenants SET billing_status = 'active'"
```

### Stripe Webhooks
```bash
# Disable webhook in Stripe Dashboard temporarily
# Or in code, comment out webhook router registration
```

### Backup CronJob
```bash
# Suspend CronJob
kubectl patch cronjob solvereign-backup -p '{"spec":{"suspend":true}}'
```

---

## Go/No-Go Checklist (10 Points)

| # | Check | Command/Action | Expected |
|---|-------|----------------|----------|
| 1 | Migrations applied | `SELECT * FROM billing.verify_billing_schema()` | All PASS |
| 2 | App boots clean | `kubectl logs deployment/api` | No errors |
| 3 | Stripe webhook verified | `stripe trigger invoice.paid` | 200 OK, DB updated |
| 4 | Webhook idempotent | Send same event 3x | Only 1 DB record |
| 5 | Billing gating works | Set tenant to `past_due`, call API | 402 response |
| 6 | Sentry sees errors | Trigger test error | Issue in Sentry |
| 7 | Backup runs | Manual trigger | S3 file created |
| 8 | Restore works | Restore to test DB | App starts |
| 9 | Grafana shows data | Open dashboard | All panels populated |
| 10 | Legal pages accessible | Visit `/legal/terms` | Page loads |

**All 10 must pass before production deployment.**

---

## Emergency Contacts

| Role | Contact |
|------|---------|
| On-Call | PagerDuty escalation |
| Stripe Support | dashboard.stripe.com/support |
| AWS Support | aws.amazon.com/support |
| Sentry Support | sentry.io/support |

---

*Document maintained by Platform Team. Last verified: 2026-01-11*
