# RUNBOOK - Production Cutover (Wien Pilot)

**System**: SOLVEREIGN V3.7
**Purpose**: Step-by-step production deployment with verification, rollback, and evidence capture.
**Audience**: Platform Eng, Ops On-Call, Approver

---

## 0) Quick Reference

| Item | Value |
|------|-------|
| **Maintenance Window** | Sunday 02:00-06:00 CET (4h) |
| **RC Tag** | `v3.6.5-rc1` (or current) |
| **Rollback Target** | Previous stable tag in `.claude/state/last-known-good.json` |
| **Break-Glass Doc** | [docs/INCIDENT_BREAK_GLASS.md](docs/INCIDENT_BREAK_GLASS.md) |
| **Artifacts Dir** | `artifacts/prod_cutover_<timestamp>/` |

---

## 1) Pre-Cutover Checklist (D-1)

### 1.1 Staging Soak Complete

```bash
# Must have run soak with PASS verdict
./scripts/w02_staging_soak.sh --iterations 5 --with-drills

# Verify soak report
cat artifacts/soak_*/soak_report.json | jq '.results'
# Expected: determinism=PASS, fail_count=0
```

### 1.2 RC Tag Cut

```bash
# Only cut RC if staging soak PASS
git tag -a v3.6.5-rc1 -m "Wien Pilot RC1 - soak verified"
git push origin v3.6.5-rc1
```

### 1.3 Approver Sign-Off

- [ ] Staging soak report reviewed
- [ ] RC tag matches tested commit
- [ ] Maintenance window communicated to stakeholders
- [ ] On-call engineer assigned

---

## 2) Maintenance Window Preparation

### 2.1 Environment Variables

Verify production environment variables are set:

```bash
# Required env vars (check Azure App Configuration / Key Vault)
SOLVEREIGN_DB_URL          # PostgreSQL connection string
SOLVEREIGN_SESSION_SECRET  # 32+ byte secret for sessions
SOLVEREIGN_HMAC_SECRET     # HMAC signing key
SOLVEREIGN_ENV=production
SOLVEREIGN_LOG_LEVEL=INFO
SOLVEREIGN_PLATFORM_WRITES_DISABLED=false  # Will be set to true during cutover
```

### 2.2 Database Backup

```bash
# Create point-in-time backup BEFORE any changes
pg_dump $SOLVEREIGN_DB_URL \
  --format=custom \
  --file="backups/solvereign_pre_cutover_$(date +%Y%m%d_%H%M%S).dump"

# Verify backup
pg_restore --list "backups/solvereign_pre_cutover_*.dump" | head -20
```

### 2.3 Disable Writes

```bash
# CRITICAL: Disable writes before migration
az appconfig kv set \
  --name solvereign-config \
  --key SOLVEREIGN_PLATFORM_WRITES_DISABLED \
  --value true

# Verify
curl -s https://api.solvereign.com/health | jq '.writes_enabled'
# Expected: false
```

---

## 3) Migration Procedure

### 3.1 Run Preflight Check

```bash
# MUST pass before proceeding
python scripts/prod_preflight_check.py \
  --db-url "$SOLVEREIGN_DB_URL" \
  --env production

# Expected output: VERDICT: PASS
# Exit code: 0
```

### 3.2 Apply Migrations (ON_ERROR_STOP)

```bash
# Apply migrations in order with strict error handling
./scripts/prod_cutover.sh \
  --db-url "$SOLVEREIGN_DB_URL" \
  --rc-tag v3.6.5-rc1 \
  --artifacts-dir artifacts/prod_cutover_$(date +%Y%m%d_%H%M%S)

# This script will:
# 1. Apply migrations 025-025f with ON_ERROR_STOP
# 2. Run verify_final_hardening()
# 3. Generate ACL scan report
# 4. Run smoke tests
# 5. Produce evidence artifacts
```

### 3.3 Migration Order

| Migration | Description | Critical |
|-----------|-------------|----------|
| `025_tenants_rls_fix.sql` | RLS on tenants table | YES |
| `025a_rls_hardening.sql` | search_path, is_active filter | YES |
| `025b_rls_role_lockdown.sql` | Least-privilege grants | YES |
| `025c_rls_boundary_fix.sql` | Role-based RLS + session_user | YES |
| `025d_definer_owner_hardening.sql` | Dedicated definer role | YES |
| `025e_final_hardening.sql` | Final cleanup | YES |
| `025f_acl_fix.sql` | ACL corrections | YES |

### 3.4 Verify Hardening

```bash
# AUTHORITATIVE verification - MUST return 0 failures
psql $SOLVEREIGN_DB_URL -c "SELECT * FROM verify_final_hardening();"

# Expected: All rows show status='PASS'
# If ANY row shows status='FAIL', STOP and investigate
```

---

## 4) Post-Migration Verification

### 4.1 Security Gate

```bash
# Run security gate
./scripts/ci/security_gate.sh --db-url "$SOLVEREIGN_DB_URL"

# Expected: GATE STATUS: PASS
# Artifacts: artifacts/security_gate_result.json
```

### 4.2 ACL Scan Report

```bash
# Generate and store ACL report
psql $SOLVEREIGN_DB_URL -c "
SELECT
    nspname AS schema,
    relname AS table,
    array_agg(privilege_type) AS public_grants
FROM information_schema.role_table_grants
JOIN pg_class ON relname = table_name
JOIN pg_namespace ON pg_namespace.oid = relnamespace
WHERE grantee = 'PUBLIC'
  AND nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY nspname, relname;
" > artifacts/acl_scan_report.json

# Expected: Empty result (no PUBLIC grants on app tables)
```

### 4.3 Health Check

```bash
# Smoke test endpoints
curl -s https://api.solvereign.com/health | jq '.'
curl -s https://api.solvereign.com/health/ready | jq '.'

# Expected: status=healthy, ready=true
```

### 4.4 Auth Separation Test

```bash
# Verify auth separation is enforced
# Platform endpoint should reject API key
curl -s -X GET https://api.solvereign.com/api/v1/platform/tenants \
  -H "X-API-Key: test_key" \
  | jq '.error'
# Expected: "wrong_auth_method" or similar rejection

# Pack endpoint should reject session cookie
curl -s -X GET https://api.solvereign.com/api/v1/routing/status \
  -H "Cookie: session=test" \
  | jq '.error'
# Expected: "missing_api_key" or similar rejection
```

---

## 5) Operational Verification

### 5.1 Roster Dry Run (Prod-Safe)

```bash
# Run roster gate in read-only mode
./scripts/ci/wien_roster_gate.sh \
  --skip-routing \
  --dry-run \
  --db-url "$SOLVEREIGN_DB_URL"

# Expected: GATE STATUS: PASS
```

### 5.2 Sick-Call Drill (Prod-Safe)

```bash
# Run single ops drill to verify repair service
python scripts/run_sick_call_drill.py \
  --dry-run \
  --seed 94 \
  --absent-drivers DRV001,DRV002,DRV003 \
  --tenant wien_pilot

# Expected: VERDICT: PASS
```

---

## 6) Human Approval Gate

### 6.1 Approval Checklist

Before enabling writes:

- [ ] `verify_final_hardening()` returns 0 failures
- [ ] ACL scan report is empty (no PUBLIC grants)
- [ ] Health endpoints return healthy
- [ ] Auth separation tests pass
- [ ] Roster dry run PASS
- [ ] Ops drill PASS

### 6.2 Approver Sign-Off

```
PRODUCTION CUTOVER APPROVED

RC Tag: v3.6.5-rc1
Timestamp: [ISO timestamp]
Approver: [Name]
Evidence: artifacts/prod_cutover_[timestamp]/

Sign-off: _______________
```

---

## 7) Enable Production

### 7.1 Re-Enable Writes

```bash
# Only after approval
az appconfig kv set \
  --name solvereign-config \
  --key SOLVEREIGN_PLATFORM_WRITES_DISABLED \
  --value false

# Verify
curl -s https://api.solvereign.com/health | jq '.writes_enabled'
# Expected: true
```

### 7.2 Update Last-Known-Good

```bash
# Update state file
cat > .claude/state/last-known-good.json << EOF
{
  "git_sha": "$(git rev-parse HEAD)",
  "migrations_version": "025f_acl_fix",
  "config_hash": "$(sha256sum .env.production | cut -d' ' -f1)",
  "timestamp": "$(date -Iseconds)",
  "all_tests_pass": true,
  "health_status": "healthy",
  "deployed_by": "$(whoami)",
  "deployment_notes": "Wien Pilot production cutover v3.6.5-rc1",
  "rollback_sha": "$(git rev-parse HEAD~1)"
}
EOF

git add .claude/state/last-known-good.json
git commit -m "chore: update last-known-good after prod cutover"
git push
```

---

## 8) Post-Deploy Monitoring

### 8.1 First Hour

| Check | Frequency | Action on Fail |
|-------|-----------|----------------|
| `/health/ready` | Every 1 min | Alert if unhealthy |
| Error rate (5xx) | Every 1 min | Rollback if >1% |
| Latency P99 | Every 5 min | Investigate if >2s |
| Security events | Continuous | Immediate response |

### 8.2 Monitoring Commands

```bash
# Watch health status
watch -n 60 'curl -s https://api.solvereign.com/health | jq .'

# Check security events
psql $SOLVEREIGN_DB_URL -c "
SELECT event_type, severity, COUNT(*)
FROM core.security_events
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY event_type, severity
ORDER BY severity, COUNT(*) DESC;
"

# Check error logs (Azure)
az monitor log-analytics query \
  --workspace solvereign-logs \
  --analytics-query "AppTraces | where SeverityLevel >= 3 | take 100"
```

---

## 9) Rollback Procedure

### 9.1 Rollback Triggers

| Trigger | Severity | Action |
|---------|----------|--------|
| 5xx error rate >1% for 5 min | S1 | Immediate rollback |
| Security event REPLAY_ATTACK | S0 | Immediate rollback |
| `verify_final_hardening()` fails | S0 | Immediate rollback |
| Tenant data leak detected | S0 | Immediate rollback + incident |

### 9.2 Rollback Steps

```bash
# 1. Disable writes immediately
az appconfig kv set \
  --name solvereign-config \
  --key SOLVEREIGN_PLATFORM_WRITES_DISABLED \
  --value true

# 2. Get rollback target
ROLLBACK_SHA=$(jq -r '.rollback_sha' .claude/state/last-known-good.json)

# 3. Deploy previous version
az webapp deployment source config-zip \
  --name solvereign-api \
  --resource-group solvereign-rg \
  --src "releases/solvereign_${ROLLBACK_SHA}.zip"

# 4. Restore database (if schema changed)
pg_restore \
  --dbname $SOLVEREIGN_DB_URL \
  --clean \
  --if-exists \
  "backups/solvereign_pre_cutover_*.dump"

# 5. Re-enable writes after verification
# ... run health checks ...
az appconfig kv set \
  --name solvereign-config \
  --key SOLVEREIGN_PLATFORM_WRITES_DISABLED \
  --value false
```

### 9.3 Post-Rollback

- [ ] Create incident record
- [ ] Capture evidence (logs, metrics, security events)
- [ ] Notify stakeholders
- [ ] Schedule postmortem

---

## 10) Evidence Artifacts

All cutover artifacts are stored in `artifacts/prod_cutover_<timestamp>/`:

```
artifacts/prod_cutover_20260108_020000/
├── preflight_result.json       # Preflight check output
├── migration_log.txt           # Migration execution log
├── verify_hardening.json       # verify_final_hardening() output
├── acl_scan_report.json        # ACL scan results
├── security_gate_result.json   # Security gate output
├── health_check.json           # Health endpoint responses
├── auth_separation_test.json   # Auth test results
├── roster_dry_run.json         # Roster gate output
├── ops_drill_sick_call.json    # Ops drill evidence
├── approval_record.json        # Approver sign-off
└── cutover_summary.json        # Final summary with hashes
```

---

## 11) Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Ops On-Call | [PagerDuty rotation] | Primary |
| Platform Eng Lead | [Name/Slack] | Technical issues |
| Security Lead | [Name/Slack] | Security events |
| Product Owner | [Name/Slack] | Business decisions |

---

## 12) Appendix: Script Reference

| Script | Purpose | Exit Codes |
|--------|---------|------------|
| `scripts/prod_preflight_check.py` | Pre-cutover validation | 0=PASS, 1=WARN, 2=FAIL |
| `scripts/prod_cutover.sh` | Idempotent migration runner | 0=SUCCESS, 1=FAIL |
| `scripts/ci/security_gate.sh` | Security hardening verification | 0=PASS, 1=FAIL |
| `scripts/ci/wien_roster_gate.sh` | Roster E2E validation | 0=PASS, 1=FAIL |
| `scripts/run_sick_call_drill.py` | Ops drill | 0=PASS, 1=WARN, 2=FAIL |

---

**Document Version**: 1.0

**Effective for**: Wien Pilot Production Cutover

**Last Updated**: 2026-01-08
