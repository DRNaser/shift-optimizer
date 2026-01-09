# Deployment Checklist

> **Purpose**: Production deployment procedures
> **Last Updated**: 2026-01-07

---

## PRE-DEPLOYMENT

### Code Verification

- [ ] All tests pass locally
- [ ] All CI checks pass
- [ ] Code reviewed and approved
- [ ] No security vulnerabilities (pip-audit, npm audit)
- [ ] Documentation updated if needed

### Migration Verification

- [ ] Migrations tested on staging
- [ ] Rollback scripts exist
- [ ] Migration timing estimated
- [ ] RLS policies verified

### Configuration

- [ ] Environment variables documented
- [ ] Secrets rotated if needed
- [ ] Feature flags configured
- [ ] Monitoring alerts configured

### Communication

- [ ] Stakeholders notified
- [ ] Maintenance window scheduled (if needed)
- [ ] Customer communication prepared (if breaking changes)

---

## DEPLOYMENT STEPS

### 1. Pre-Flight Checks

```bash
# Verify current state
git log -1 --oneline
kubectl get pods -l app=solvereign

# Health check
curl http://api.solvereign.local/health/ready

# Check current version
curl http://api.solvereign.local/health | jq .version
```

### 2. Create Backup

```bash
# Database backup
pg_dump solvereign > backup_$(date +%Y%m%d_%H%M%S).sql

# Current deployment state
kubectl get deployment solvereign-api -o yaml > deployment_backup.yaml
```

### 3. Apply Migrations (if any)

```bash
# Check pending migrations
ls backend_py/db/migrations/*.sql | tail -5

# Apply migrations
psql $DATABASE_URL < backend_py/db/migrations/NNN_description.sql

# Verify
psql $DATABASE_URL -c "SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 5"
```

### 4. Deploy Application

```bash
# Update image
kubectl set image deployment/solvereign-api api=solvereign:$VERSION

# Watch rollout
kubectl rollout status deployment/solvereign-api --timeout=300s
```

### 5. Verify Deployment

```bash
# Check pods are running
kubectl get pods -l app=solvereign

# Health check
curl http://api.solvereign.local/health/ready

# Version check
curl http://api.solvereign.local/health | jq .version
```

### 6. Run Smoke Tests

```bash
# API smoke test
python -m backend_py.tests.smoke_test

# Pack-specific tests
python -m backend_py.packs.routing.tests.smoke_test
python -m backend_py.packs.roster.tests.smoke_test
```

### 7. Monitor

```bash
# Watch logs for 5 minutes
kubectl logs -f deployment/solvereign-api --since=5m

# Check error rate
# (Use your monitoring dashboard)
```

---

## POST-DEPLOYMENT

### Update State

```bash
# Update last-known-good.json
cat > .claude/state/last-known-good.json << EOF
{
  "git_sha": "$(git rev-parse --short HEAD)",
  "migrations_version": "NNN_description",
  "config_hash": "sha256:...",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "all_tests_pass": true,
  "health_status": "healthy"
}
EOF

git add .claude/state/last-known-good.json
git commit -m "chore: update LKG after deployment"
```

### Monitoring Period

- [ ] Monitor error rates for 30 minutes
- [ ] Check key KPIs haven't regressed
- [ ] Verify customer-facing features work
- [ ] No increase in support tickets

### Communication

- [ ] Announce completion to stakeholders
- [ ] Update release notes
- [ ] Close deployment ticket

---

## ROLLBACK PROCEDURE

### Immediate Rollback (< 5 minutes)

```bash
# Rollback deployment
kubectl rollout undo deployment/solvereign-api

# Verify
kubectl rollout status deployment/solvereign-api
curl http://api.solvereign.local/health/ready
```

### Rollback with Migration

```bash
# 1. Rollback application first
kubectl rollout undo deployment/solvereign-api

# 2. Apply migration rollback
psql $DATABASE_URL < backend_py/db/migrations/NNN_description_rollback.sql

# 3. Verify database state
psql $DATABASE_URL -c "SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 5"

# 4. Verify application
curl http://api.solvereign.local/health/ready
```

### When to Rollback

- Health probes failing
- Error rate > 1%
- Key feature broken
- Data corruption detected
- Security vulnerability discovered

---

## DEPLOYMENT ENVIRONMENTS

### Staging

```yaml
purpose: Pre-production testing
url: https://staging.solvereign.local
database: solvereign_staging
features: All features enabled
data: Anonymized copy of production
```

### Production

```yaml
purpose: Live customer traffic
url: https://api.solvereign.com
database: solvereign
features: Feature flags control
data: Real customer data
```

---

## DEPLOYMENT TYPES

### Standard Deployment

- During business hours
- Non-breaking changes
- Follow full checklist

### Hotfix Deployment

- Any time (for critical issues)
- Minimal change set
- Abbreviated checklist:
  - [ ] Fix verified
  - [ ] Tests pass
  - [ ] Backup created
  - [ ] Deploy
  - [ ] Verify
  - [ ] Monitor

### Maintenance Window Deployment

- Scheduled downtime
- Breaking changes
- Extended migration time
- Customer notification required

---

## FEATURE FLAGS

### Enable/Disable Features

```python
# Check feature flag
if settings.features.get("new_solver_algorithm"):
    result = new_solver.solve(data)
else:
    result = legacy_solver.solve(data)
```

### Gradual Rollout

```python
# Roll out to percentage of tenants
import hashlib

def is_feature_enabled(tenant_id: str, feature: str, percentage: int) -> bool:
    hash_value = int(hashlib.md5(f"{tenant_id}:{feature}".encode()).hexdigest(), 16)
    return (hash_value % 100) < percentage
```

---

## MONITORING CHECKLIST

### During Deployment

- [ ] Pod status (Running/Pending/CrashLoop)
- [ ] Health endpoint status
- [ ] Error logs
- [ ] Resource usage (CPU/Memory)

### After Deployment

- [ ] API error rate
- [ ] Response time p95
- [ ] Solver success rate
- [ ] Customer-reported issues

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Deployment failed | S2 | Rollback. Investigate. |
| Health probes failing | S2 | Rollback immediately. |
| Error rate > 1% | S2 | Rollback. Investigate. |
| Migration failed | S2 | Apply rollback script. |
| Performance degraded | S3 | Monitor. Rollback if worsening. |
