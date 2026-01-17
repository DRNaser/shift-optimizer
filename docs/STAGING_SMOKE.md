# SOLVEREIGN - Staging Smoke Test Runbook

> **Version**: 1.0
> **Last Updated**: 2026-01-17
> **Environment**: Staging (pre-production)

---

## Purpose

This runbook validates that staging is functional after deployment.
It must be executed after every staging deploy.

---

## Prerequisites

- [ ] Staging URL is accessible
- [ ] Valid test credentials exist
- [ ] Network access to staging environment

---

## Configuration

```bash
# Set these before running
export STAGING_URL="https://staging.solvereign.example.com"
export TEST_EMAIL="test@example.com"
# Password will be prompted interactively
```

---

## Smoke Test Steps

### Step 1: Health Check

**Command:**
```bash
curl -s "$STAGING_URL/health" | jq .
```

**Expected Result:**
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "X.Y.Z"
}
```

**Pass Criteria:**
- [ ] HTTP 200
- [ ] `status` = `healthy`
- [ ] `database` = `connected`

---

### Step 2: Frontend Accessible

**Command:**
```bash
curl -s -o /dev/null -w "%{http_code}" "$STAGING_URL"
```

**Expected Result:** `200`

**Manual Check:**
- [ ] Open `$STAGING_URL` in browser
- [ ] Login page loads without errors
- [ ] No console errors in browser DevTools

---

### Step 3: Login Flow

**Using staging_preflight.py:**
```bash
# Inside Docker (recommended - avoids Windows issues)
docker compose exec api python scripts/staging_preflight.py \
    --base-url $STAGING_URL \
    --email $TEST_EMAIL
# Password will be prompted

# Or direct (if local Python works)
python scripts/staging_preflight.py \
    --base-url $STAGING_URL \
    --email $TEST_EMAIL
```

**Pass Criteria:**
- [ ] Login succeeds
- [ ] Session cookie received
- [ ] `/api/auth/me` returns user info

---

### Step 4: API Routes Accessible

**Test key endpoints:**

```bash
# With session cookie from login
curl -s "$STAGING_URL/api/v1/roster/plans" \
    -H "Cookie: admin_session=<token>" | jq .

# Health endpoints (no auth)
curl -s "$STAGING_URL/health" | jq .
curl -s "$STAGING_URL/metrics" | head -20
```

**Pass Criteria:**
- [ ] `/api/v1/roster/plans` returns 200 (or 401 without auth)
- [ ] `/health` returns healthy
- [ ] `/metrics` returns Prometheus format

---

### Step 5: Evidence/Audit Viewer

**Manual Check:**
1. Login to staging
2. Navigate to Evidence Viewer (`/evidence` or similar)
3. Check that page loads
4. Navigate to Audit Viewer (`/audit` or similar)
5. Check that page loads

**Pass Criteria:**
- [ ] Evidence viewer loads without errors
- [ ] Audit viewer loads without errors

---

### Step 6: Idempotency Check (Optional)

**Purpose:** Verify that re-running operations doesn't create duplicates.

**Test:**
1. Create a test entity (e.g., draft plan)
2. Note the ID
3. Refresh page
4. Verify same entity exists (not duplicated)

**Pass Criteria:**
- [ ] No duplicate entities created on refresh

---

## Quick Reference: Pass/Fail Summary

| Step | Check | Status |
|------|-------|--------|
| 1 | Health endpoint | [ ] PASS / [ ] FAIL |
| 2 | Frontend loads | [ ] PASS / [ ] FAIL |
| 3 | Login works | [ ] PASS / [ ] FAIL |
| 4 | API routes respond | [ ] PASS / [ ] FAIL |
| 5 | Viewers load | [ ] PASS / [ ] FAIL |
| 6 | Idempotency OK | [ ] PASS / [ ] FAIL / [ ] SKIP |

---

## Failure Handling

### If Health Check Fails
1. Check `docker logs` on staging server
2. Verify database connection string
3. Check if migrations ran successfully

### If Login Fails
1. Verify test user exists in database
2. Check session secret is set
3. Verify HTTPS certificate (Secure cookie issue)

### If Frontend Fails
1. Check Next.js build logs
2. Verify `BACKEND_URL` environment variable
3. Check browser console for errors

---

## Post-Smoke Actions

After successful smoke test:

1. [ ] Update deployment log with timestamp
2. [ ] Notify team of successful deploy
3. [ ] Tag commit if this is a release candidate

After failed smoke test:

1. [ ] Document failure in deployment log
2. [ ] Rollback if critical
3. [ ] Create incident ticket if needed

---

## Staging vs Production

| Aspect | Staging | Production |
|--------|---------|------------|
| Data | Test data only | Real customer data |
| Auth | Test accounts | Real accounts |
| Notifications | Sandbox/disabled | Live providers |
| Rollback | Aggressive | Careful |

---

*Execute this runbook after every staging deployment.*
