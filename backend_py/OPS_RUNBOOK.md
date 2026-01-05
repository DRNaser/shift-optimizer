# SOLVEREIGN V3.3a Operations Runbook

## Quick Reference

| Issue | Command | Expected Result |
|-------|---------|-----------------|
| Stuck plans | `python -m v3.crash_recovery --max-age-minutes 30` | Plans marked FAILED |
| Health check | `curl localhost:8000/health` | `{"status": "ok"}` |
| Metrics | `curl localhost:8000/metrics` | Prometheus format |
| Stuck check only | `python -m v3.crash_recovery --check-only` | OK or WARNING |

---

## 1. Crash Recovery

### Problem: Plans stuck in SOLVING status

After a solver crash or timeout, plans can be stuck in `SOLVING` status indefinitely.
This blocks new solves (advisory locks) and creates operational confusion.

### Detection

```bash
# Check for stuck plans (plans SOLVING > 5 minutes)
python -m v3.crash_recovery --check-only --max-age-minutes 5
```

Output:
- `OK: No stuck plans` - All clear
- `WARNING: X stuck plans detected!` - Action required

### Recovery

```bash
# Dry run (see what would be recovered)
python -m v3.crash_recovery --max-age-minutes 30 --dry-run

# Actual recovery (marks stuck plans as FAILED)
python -m v3.crash_recovery --max-age-minutes 30
```

### What happens during recovery:
1. Plans in `SOLVING` status older than threshold are found
2. Each plan is updated: `status = FAILED`
3. Audit log entry created with `check_name = CRASH_RECOVERY`
4. Notes field updated with recovery timestamp

### When to run:
- After any unplanned API restart
- If health check shows stuck plans
- As part of daily maintenance (cron)

### Cron setup (recommended):
```bash
# Run every 15 minutes, recover plans stuck > 30 minutes
*/15 * * * * cd /app && python -m v3.crash_recovery --max-age-minutes 30
```

---

## 2. Health Monitoring

### Health Endpoint

```bash
curl localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "3.3.0",
  "timestamp": "2026-01-05T17:30:00Z",
  "environment": "production"
}
```

### Metrics Endpoint

```bash
curl localhost:8000/metrics
```

Key metrics to monitor:
- `solve_duration_seconds` - Solver execution time
- `solve_failures_total` - Number of solver failures
- `audit_failures_total` - Number of audit failures
- `http_requests_total` - Request counts by endpoint

### Alerting Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| `solve_duration_seconds{quantile="0.99"}` | > 120s | > 300s |
| `solve_failures_total` (rate 5m) | > 0.1/min | > 1/min |
| `audit_failures_total` (rate 5m) | > 0 | > 0.5/min |

---

## 3. Database Maintenance

### Check for locked plans

```sql
SELECT id, status, locked_at, locked_by
FROM plan_versions
WHERE status = 'LOCKED'
ORDER BY locked_at DESC
LIMIT 10;
```

### Check advisory locks (solve locks)

```sql
SELECT * FROM pg_locks WHERE locktype = 'advisory';
```

### Cleanup expired idempotency keys

```sql
SELECT cleanup_expired_idempotency_keys();
```

Recommended: Run daily via cron.

---

## 4. Common Issues

### Issue: API won't start on Windows

**Symptom**: `psycopg cannot use the 'ProactorEventLoop'`

**Cause**: Windows asyncio incompatibility with psycopg3

**Solution**: Use Linux/Docker for production, or set event loop policy:
```python
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

### Issue: 409 Conflict on forecast ingest

**Symptom**: `IDEMPOTENCY_MISMATCH` error

**Cause**: Same `X-Idempotency-Key` used with different payload

**Solution**: Use a new idempotency key for each unique request

### Issue: Plan stuck in LOCKED, can't modify

**Symptom**: Cannot update assignments

**Cause**: LOCKED plans are immutable (by design)

**Solution**: Create a new plan version with `SUPERSEDED` status on the old one

---

## 5. Emergency Procedures

### Force unlock advisory lock (dangerous!)

Only if absolutely necessary and you're sure no solve is running:

```sql
-- Find the lock
SELECT * FROM pg_locks WHERE locktype = 'advisory';

-- Force terminate the session holding the lock
SELECT pg_terminate_backend(<pid>);
```

### Reset stuck plan (dangerous!)

Only for development/testing:

```sql
UPDATE plan_versions
SET status = 'FAILED',
    notes = notes || E'\n[MANUAL_RESET] ' || NOW()::text
WHERE id = <plan_id>
  AND status = 'SOLVING';
```

---

## 6. Contacts

| Role | Contact |
|------|---------|
| On-call | #solvereign-ops Slack |
| Escalation | Engineering Lead |

---

## 7. Appendix: State Machine

```
INGESTED → EXPANDED → SOLVING → SOLVED → AUDITED → DRAFT → LOCKED
                         ↓
                      FAILED

LOCKED → SUPERSEDED (when newer plan is LOCKED)
```

- `SOLVING`: Advisory lock held, solver running
- `FAILED`: Solver error or crash recovery
- `LOCKED`: Immutable, released to production
- `SUPERSEDED`: Replaced by newer locked plan

---

*Last updated: 2026-01-05*
*Version: V3.3a*
