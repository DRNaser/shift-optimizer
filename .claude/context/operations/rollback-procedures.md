# Rollback Procedures

> **Purpose**: Emergency rollback steps
> **Last Updated**: 2026-01-07

---

## WHEN TO ROLLBACK

### Immediate Rollback (No Discussion)

- Health probes failing after deploy
- Error rate > 5%
- Data corruption detected
- Security vulnerability exploited
- System completely unresponsive

### Consider Rollback

- Error rate > 1% (sustained 5+ minutes)
- Key feature broken
- Significant performance degradation
- Multiple customer complaints

### Don't Rollback

- Minor UI issues
- Non-critical feature degraded
- Issue affects < 1% of requests
- Workaround available

---

## ROLLBACK DECISION TREE

```
Issue Detected
     │
     ▼
Is system down? ──YES──► IMMEDIATE ROLLBACK
     │
     NO
     │
     ▼
Is data at risk? ──YES──► IMMEDIATE ROLLBACK
     │
     NO
     │
     ▼
Is error rate > 5%? ──YES──► IMMEDIATE ROLLBACK
     │
     NO
     │
     ▼
Is error rate > 1%? ──YES──► Consider rollback (5min window)
     │
     NO
     │
     ▼
Is key feature broken? ──YES──► Consider rollback
     │
     NO
     │
     ▼
Monitor and investigate
```

---

## QUICK ROLLBACK (< 5 MINUTES)

### Application Only

```bash
# 1. Rollback to previous version
kubectl rollout undo deployment/solvereign-api

# 2. Wait for rollout
kubectl rollout status deployment/solvereign-api --timeout=120s

# 3. Verify health
curl http://api.solvereign.local/health/ready

# 4. Verify version
curl http://api.solvereign.local/health | jq .version
```

### With Docker Compose

```bash
# 1. Stop current containers
docker compose stop api

# 2. Revert to previous image
docker compose pull api:previous-tag

# 3. Start with previous image
docker compose up -d api

# 4. Verify
curl http://localhost:8000/health/ready
```

---

## FULL ROLLBACK (WITH DATABASE)

### Step 1: Stop Traffic

```bash
# Scale down to prevent new requests
kubectl scale deployment/solvereign-api --replicas=0

# Or block at load balancer
kubectl patch svc solvereign-api -p '{"spec":{"selector":{"app":"none"}}}'
```

### Step 2: Rollback Application

```bash
# Rollback to previous version
kubectl rollout undo deployment/solvereign-api
```

### Step 3: Rollback Database

```bash
# Find rollback script
ls backend_py/db/migrations/*_rollback.sql

# Apply rollback
psql $DATABASE_URL < backend_py/db/migrations/NNN_description_rollback.sql

# Verify
psql $DATABASE_URL -c "SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 5"
```

### Step 4: Restore Traffic

```bash
# Scale back up
kubectl scale deployment/solvereign-api --replicas=2

# Wait for ready
kubectl rollout status deployment/solvereign-api

# Restore service selector
kubectl patch svc solvereign-api -p '{"spec":{"selector":{"app":"solvereign-api"}}}'
```

### Step 5: Verify

```bash
# Health check
curl http://api.solvereign.local/health/ready

# Smoke test
python -m backend_py.tests.smoke_test

# Check error rate
# (Use monitoring dashboard)
```

---

## EMERGENCY PROCEDURES

### Complete System Failure

```bash
# 1. Don't panic. Document what you see.

# 2. Check infrastructure
kubectl get nodes
kubectl get pods --all-namespaces

# 3. If pods are crashing, get logs
kubectl logs deployment/solvereign-api --previous

# 4. If database is down
pg_isready -h postgres-host
systemctl status postgresql

# 5. Restore from backup if needed
psql solvereign < backup_YYYYMMDD_HHMMSS.sql
```

### Data Corruption Detected

```bash
# 1. STOP ALL WRITES IMMEDIATELY
kubectl scale deployment/solvereign-api --replicas=0

# 2. Secure evidence
pg_dump solvereign > corrupted_state_$(date +%s).sql

# 3. Identify scope
psql -c "SELECT count(*) FROM affected_table WHERE updated_at > 'DEPLOY_TIME'"

# 4. Restore from backup
# Option A: Point-in-time recovery (if WAL available)
# Option B: Restore full backup
psql solvereign < backup_before_deploy.sql

# 5. Reapply safe transactions (manual review required)
```

### Partial Failure

```bash
# 1. Identify affected pods
kubectl get pods -l app=solvereign

# 2. Delete failing pods (will be recreated)
kubectl delete pod solvereign-api-xxx

# 3. If persists, rollback deployment
kubectl rollout undo deployment/solvereign-api
```

---

## ROLLBACK VERIFICATION

After any rollback, verify:

- [ ] Health probes passing
- [ ] Error rate normalized
- [ ] Key features working
- [ ] No data loss
- [ ] Monitoring stable

### Verification Script

```bash
#!/bin/bash
# verify_rollback.sh

echo "=== Rollback Verification ==="

# Health check
echo -n "Health: "
curl -s http://api.solvereign.local/health/ready | jq .status

# Version check
echo -n "Version: "
curl -s http://api.solvereign.local/health | jq .version

# Pod status
echo "=== Pod Status ==="
kubectl get pods -l app=solvereign

# Recent logs (check for errors)
echo "=== Recent Errors ==="
kubectl logs deployment/solvereign-api --since=5m | grep -i error | tail -10

echo "=== Verification Complete ==="
```

---

## COMMUNICATION

### During Rollback

```
🔄 ROLLBACK IN PROGRESS

Issue: [brief description]
Action: Rolling back to previous version
ETA: ~5 minutes

Updates will follow.
```

### After Rollback

```
✅ ROLLBACK COMPLETE

Duration: X minutes
Previous version restored: v1.2.3
Services: All healthy

Root cause investigation in progress.
Post-mortem will be scheduled.
```

---

## POST-ROLLBACK

### Immediate

- [ ] Verify system stable
- [ ] Notify stakeholders
- [ ] Create incident ticket
- [ ] Secure logs and evidence

### Within 24 Hours

- [ ] Root cause analysis
- [ ] Fix identified
- [ ] Fix tested on staging
- [ ] Post-mortem scheduled

### Before Re-Deploy

- [ ] Root cause fixed
- [ ] Additional tests added
- [ ] Rollback procedure updated if needed
- [ ] Stakeholder approval

---

## ROLLBACK HISTORY

Track all rollbacks for pattern detection:

```json
// .claude/state/rollback-history.json
{
  "rollbacks": [
    {
      "date": "2026-01-07T10:30:00Z",
      "version_from": "v1.2.4",
      "version_to": "v1.2.3",
      "reason": "Error rate spike after deploy",
      "duration_minutes": 8,
      "root_cause": "Missing null check in new code path",
      "post_mortem_link": "..."
    }
  ]
}
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Rollback failed | S1 | All hands. Manual intervention. |
| Rollback succeeded but issue persists | S2 | Deeper investigation. May need older version. |
| Data loss during rollback | S1 | Restore from backup. Forensic analysis. |
| Rollback took > 15 minutes | S3 | Post-mortem. Improve procedure. |
