# Post-GA Operations Runbook v3.7.0

**Release**: SOLVEREIGN v3.7.0
**Tag**: `v3.7.0` (commit `87b4a59`)
**Date**: 2026-01-11
**Estimated Duration**: 30 minutes
**Owner**: Release Manager

---

## Pre-Flight Checklist

Before starting, ensure you have:

- [ ] SSH/CLI access to staging and production hosts
- [ ] Database credentials (read-only sufficient for most checks)
- [ ] SendGrid + WhatsApp sandbox credentials for webhook testing
- [ ] Grafana/Prometheus access
- [ ] Sentry project access

**Environment Variables** (set before running commands):
```bash
export STAGING_URL="https://staging.solvereign.example.com"
export PROD_URL="https://app.solvereign.example.com"
export STAGING_EMAIL="dispatcher@lts.at"
export TENANT_ID="1"
export SITE_ID="10"
export DATABASE_URL="postgresql://..."  # read-only connection
```

---

## 1) Release Fingerprint Verification

### 1.1 Verify Tag on Origin

```bash
git fetch origin --tags
git show v3.7.0 --no-patch
```

**PASS Criteria**:
- Tag exists and points to commit `87b4a59`
- Tag message contains "GA Release: SOLVEREIGN v3.7.0"

**If FAIL**:
- Re-tag locally and force-push: `git tag -d v3.7.0 && git tag -a v3.7.0 <correct-sha> -m "..." && git push -f origin v3.7.0`
- Document discrepancy in release notes

### 1.2 Verify Deployed Version (Staging)

```bash
curl -s "${STAGING_URL}/api/health" | jq '.version'
```

**PASS Criteria**: Returns `"3.7.0"` or commit hash `87b4a59`

### 1.3 Verify Deployed Version (Production)

```bash
curl -s "${PROD_URL}/api/health" | jq '.version'
```

**PASS Criteria**: Returns `"3.7.0"` or commit hash `87b4a59`

**If FAIL** (version mismatch):
- Check deployment pipeline logs
- Verify container image tag matches `v3.7.0`
- DO NOT proceed until version matches

---

## 2) Health Checks

### 2.1 Staging Health

```bash
# Basic health
curl -sf "${STAGING_URL}/api/health" && echo "PASS" || echo "FAIL"

# Ready probe (includes DB)
curl -sf "${STAGING_URL}/api/health/ready" && echo "PASS" || echo "FAIL"

# Live probe
curl -sf "${STAGING_URL}/api/health/live" && echo "PASS" || echo "FAIL"
```

**PASS Criteria**: All three return HTTP 200

### 2.2 Production Health

```bash
curl -sf "${PROD_URL}/api/health" && echo "PASS" || echo "FAIL"
curl -sf "${PROD_URL}/api/health/ready" && echo "PASS" || echo "FAIL"
curl -sf "${PROD_URL}/api/health/live" && echo "PASS" || echo "FAIL"
```

**PASS Criteria**: All three return HTTP 200

**If FAIL**:
- Check container logs: `docker logs <container> --tail 100`
- Verify database connectivity
- Check if migrations completed

---

## 3) Security Headers Verification

### 3.1 Check Response Headers

```bash
curl -sI "${STAGING_URL}/api/health" | grep -iE "^(strict-transport|x-content-type|x-frame|content-security|x-xss)"
```

**Expected Headers**:
```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'
X-XSS-Protection: 1; mode=block
```

**PASS Criteria**: All 5 headers present with secure values

### 3.2 Cookie Security (Session Endpoint)

```bash
curl -sI "${STAGING_URL}/api/auth/login" -X POST \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"wrong"}' \
  | grep -i "set-cookie"
```

**PASS Criteria**:
- `HttpOnly` flag present
- `SameSite=Lax` or `SameSite=Strict`
- `Secure` flag present (HTTPS only)

**If FAIL**:
- Review `backend_py/api/routers/auth.py` cookie settings
- Check environment-specific cookie configuration

---

## 4) Auth/Login Smoke Tests

### 4.1 API Login (Valid Credentials)

```bash
# Replace with test credentials
curl -s "${STAGING_URL}/api/auth/login" \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${STAGING_EMAIL}\",\"password\":\"<PASSWORD>\"}" \
  -c cookies.txt \
  -w "\nHTTP_CODE:%{http_code}\n"
```

**PASS Criteria**: HTTP 200, response contains `user_id` and `role`

### 4.2 API Login (Invalid Credentials)

```bash
curl -s "${STAGING_URL}/api/auth/login" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"email":"invalid@example.com","password":"wrongpassword"}' \
  -w "\nHTTP_CODE:%{http_code}\n"
```

**PASS Criteria**: HTTP 401, no session cookie set

### 4.3 Session Validation (/api/auth/me)

```bash
curl -s "${STAGING_URL}/api/auth/me" \
  -b cookies.txt \
  -w "\nHTTP_CODE:%{http_code}\n"
```

**PASS Criteria**: HTTP 200, returns current user info

### 4.4 UI Login Smoke (Manual)

1. Open `${STAGING_URL}/platform/login` in browser
2. Enter valid credentials
3. Verify redirect to `/platform-admin` dashboard
4. Verify user name displayed in header

**PASS Criteria**: Login succeeds, dashboard loads, no console errors

**If FAIL**:
- Check browser console for errors
- Verify CORS settings if cross-origin
- Check session cookie domain configuration

---

## 5) Webhook E2E Verification

### 5.1 SendGrid Webhook Endpoint Existence

```bash
curl -s "${STAGING_URL}/openapi.json" | jq '.paths | keys | map(select(contains("sendgrid")))'
```

**PASS Criteria**: Returns `["/api/v1/notifications/webhook/sendgrid"]`

### 5.2 SendGrid Signature Verification (Invalid)

```bash
curl -s "${STAGING_URL}/api/v1/notifications/webhook/sendgrid" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-Twilio-Email-Event-Webhook-Signature: invalid_signature" \
  -H "X-Twilio-Email-Event-Webhook-Timestamp: 1234567890" \
  -d '[{"event":"delivered","email":"test@example.com"}]' \
  -w "\nHTTP_CODE:%{http_code}\n"
```

**PASS Criteria**: HTTP 401 or 403 (signature rejected)

### 5.3 WhatsApp Webhook Endpoint Existence

```bash
curl -s "${STAGING_URL}/openapi.json" | jq '.paths | keys | map(select(contains("whatsapp")))'
```

**PASS Criteria**: Returns `["/api/v1/notifications/webhook/whatsapp"]`

### 5.4 WhatsApp Signature Verification (Invalid)

```bash
curl -s "${STAGING_URL}/api/v1/notifications/webhook/whatsapp" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=invalid_signature" \
  -d '{"object":"whatsapp_business_account","entry":[]}' \
  -w "\nHTTP_CODE:%{http_code}\n"
```

**PASS Criteria**: HTTP 401 or 403 (signature rejected)

### 5.5 Billing Webhook Endpoint

```bash
curl -s "${STAGING_URL}/api/billing/webhook" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"type":"test"}' \
  -w "\nHTTP_CODE:%{http_code}\n"
```

**PASS Criteria**: HTTP 401/403 (requires valid signature) or HTTP 400 (invalid payload)

**If FAIL** (endpoint missing):
- Verify routes are registered in `main.py`
- Check OpenAPI schema generation
- Review container startup logs for import errors

---

## 6) Database Migration & RLS Verification

### 6.1 Migration Status

```bash
psql "${DATABASE_URL}" -c "SELECT version, name, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 10;"
```

**PASS Criteria**:
- Latest migration version matches expected (041+)
- All migrations have `applied_at` timestamps

### 6.2 RLS Hardening Verification

```bash
psql "${DATABASE_URL}" -c "SELECT * FROM verify_final_hardening();"
```

**PASS Criteria**: All rows show `status = 'PASS'`

### 6.3 RBAC Integrity

```bash
psql "${DATABASE_URL}" -c "SELECT * FROM auth.verify_rbac_integrity();"
```

**PASS Criteria**: All 13 checks pass

### 6.4 Tenant Isolation Smoke

```bash
# Attempt cross-tenant query (should fail or return empty)
psql "${DATABASE_URL}" -c "
SET app.current_tenant_id = '999';
SELECT COUNT(*) FROM plans WHERE tenant_id != 999;
"
```

**PASS Criteria**: Returns 0 rows (RLS blocks cross-tenant access)

**If FAIL**:
- DO NOT proceed to production
- Review RLS policies on affected tables
- Check `verify_final_hardening()` for specific failures

---

## 7) Observability Checks

### 7.1 Sentry Error Rate (Last 1h)

**Query** (Sentry UI or API):
```
project:solvereign level:error timestamp:>now-1h
```

**PASS Criteria**: < 10 errors in last hour, no new error patterns

### 7.2 Prometheus/Grafana Metrics

**API Latency (P95)**:
```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="solvereign-api"}[5m]))
```

**PASS Criteria**: P95 < 2s

**Error Rate**:
```promql
sum(rate(http_requests_total{job="solvereign-api",status=~"5.."}[5m]))
/ sum(rate(http_requests_total{job="solvereign-api"}[5m])) * 100
```

**PASS Criteria**: Error rate < 1%

**Database Connection Pool**:
```promql
pg_stat_activity_count{datname="solvereign"}
```

**PASS Criteria**: < 80% of max connections

### 7.3 Log Sampling (Staging)

```bash
docker logs solvereign-api --since 10m 2>&1 | grep -i "error\|exception\|critical" | head -20
```

**PASS Criteria**: No unexpected errors, no stack traces in last 10 minutes

**If FAIL**:
- Capture error samples for triage
- Check if errors are transient (network) or persistent (code)
- If persistent critical errors: initiate rollback

---

## 8) Soak Criteria & Rollback Plan

### 8.1 Soak Period (2 Hours)

After completing all checks above, monitor for 2 hours:

| Metric | Threshold | Check Interval |
|--------|-----------|----------------|
| HTTP 5xx rate | < 0.5% | Every 15 min |
| P95 latency | < 2s | Every 15 min |
| Error log volume | < 10/hour | Every 30 min |
| Memory usage | < 80% | Every 30 min |
| Active DB connections | < 50 | Every 30 min |

**SOAK PASS Criteria**: All metrics within threshold for full 2-hour period

### 8.2 Rollback Triggers (Automatic Decision)

Initiate rollback if ANY of these occur:
- HTTP 5xx rate > 5% for > 5 minutes
- P95 latency > 10s for > 5 minutes
- Complete service outage > 2 minutes
- Data corruption detected
- Security incident (RLS bypass, auth failure)

### 8.3 Rollback Procedure

```bash
# 1. Identify last known good version
git tag -l "v3.6*" --sort=-v:refname | head -1
# → v3.6.x (use this)

# 2. Deploy previous version
# (adjust for your deployment method)
docker pull solvereign/api:v3.6.x
docker-compose up -d --force-recreate api

# 3. Verify rollback
curl -s "${PROD_URL}/api/health" | jq '.version'
# → Should show v3.6.x

# 4. If DB migrations need rollback (RARE - requires DBA):
psql "${DATABASE_URL}" -f backend_py/db/rollback/rollback_to_v3.6.sql

# 5. Notify stakeholders
# - Post in #incidents channel
# - Update status page
```

**Post-Rollback**:
- Create incident report
- Do NOT re-deploy v3.7.0 without root cause fix
- Tag failed release as `v3.7.0-reverted` for tracking

---

## 9) Patch Release Process (v3.7.1)

### 9.1 When to Patch

- Critical bug discovered post-GA
- Security vulnerability
- Data integrity issue
- Performance regression

### 9.2 Branching Strategy

```bash
# Create hotfix branch from tag
git checkout v3.7.0
git checkout -b hotfix/v3.7.1

# Apply minimal fix (cherry-pick or direct commit)
git cherry-pick <fix-commit-sha>
# OR
git commit -am "fix: <description>"

# Update version
# Edit version in pyproject.toml, package.json, etc.
git commit -am "chore: bump version to 3.7.1"
```

### 9.3 Tagging Rules

```bash
# Tag format: v3.7.1
git tag -a v3.7.1 -m "Patch Release: SOLVEREIGN v3.7.1

Fix: <one-line description>

Cherry-picked from: <original-commit-sha>
Tested: <pytest summary>"

# Push
git push origin hotfix/v3.7.1
git push origin v3.7.1
```

### 9.4 Evidence Requirements

Before tagging v3.7.1, must have:

| Evidence | Location |
|----------|----------|
| Pytest summary | CI artifacts or local terminal output |
| Regression test for fix | New test case covering the bug |
| Security review (if security fix) | Sign-off from security lead |
| Staging verification | Screenshot/log of fix working |

### 9.5 Merge Back to Main

```bash
git checkout main
git merge hotfix/v3.7.1
git push origin main
```

---

## 10) Evidence Pack

Save the following for audit trail:

### Required Screenshots

| Item | Filename | Content |
|------|----------|---------|
| Health check | `evidence/health_check_staging.png` | Terminal output of all health endpoints |
| Login success | `evidence/login_smoke.png` | Browser showing logged-in dashboard |
| RLS verification | `evidence/rls_verify.png` | `verify_final_hardening()` output |
| Grafana dashboard | `evidence/grafana_post_ga.png` | 2h post-deploy metrics |

### Required Log Snippets

| Item | Filename | Content |
|------|----------|---------|
| Webhook rejection | `evidence/webhook_signature_reject.log` | curl output showing 401/403 |
| Deployment log | `evidence/deploy_v3.7.0.log` | Container/K8s deploy output |
| Migration log | `evidence/migrations_applied.log` | `schema_migrations` query result |

### Evidence Archive Command

```bash
mkdir -p release_evidence/v3.7.0
# Copy all evidence files to directory
zip -r release_evidence_v3.7.0_$(date +%Y%m%d).zip release_evidence/v3.7.0/
```

---

## Checklist Summary

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1.1 | Tag verification | [ ] | |
| 1.2 | Staging version | [ ] | |
| 1.3 | Prod version | [ ] | |
| 2.1 | Staging health | [ ] | |
| 2.2 | Prod health | [ ] | |
| 3.1 | Security headers | [ ] | |
| 3.2 | Cookie security | [ ] | |
| 4.1 | API login valid | [ ] | |
| 4.2 | API login invalid | [ ] | |
| 4.3 | Session validation | [ ] | |
| 4.4 | UI login smoke | [ ] | |
| 5.1 | SendGrid endpoint | [ ] | |
| 5.2 | SendGrid sig reject | [ ] | |
| 5.3 | WhatsApp endpoint | [ ] | |
| 5.4 | WhatsApp sig reject | [ ] | |
| 5.5 | Billing webhook | [ ] | |
| 6.1 | Migration status | [ ] | |
| 6.2 | RLS hardening | [ ] | |
| 6.3 | RBAC integrity | [ ] | |
| 6.4 | Tenant isolation | [ ] | |
| 7.1 | Sentry errors | [ ] | |
| 7.2 | Prometheus metrics | [ ] | |
| 7.3 | Log sampling | [ ] | |
| 8.1 | Soak (2h) | [ ] | |

**Sign-Off**:
```
Release Manager: _______________ Date: _______________
Platform Lead:   _______________ Date: _______________
```

---

**Document Version**: 1.0
**Created**: 2026-01-11
**Applies to**: SOLVEREIGN v3.7.0
