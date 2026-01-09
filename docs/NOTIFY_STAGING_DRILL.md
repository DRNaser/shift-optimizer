# SOLVEREIGN V4.1.2 - Notification Staging Drill Runbook

> **Version**: V4.1.2
> **Date**: 2026-01-09
> **Purpose**: Production readiness verification for notification pipeline

---

## 1. Crash Recovery Drill (CRITICAL)

### Setup: Seed 10k Outbox Rows

```sql
-- Seed script: Creates 10k messages with realistic distribution
-- 60% WhatsApp, 40% Email
-- 5% hard fail (invalid contact), 10% rate limit (429), 85% success

DO $$
DECLARE
    v_tenant_id INTEGER := 1;
    v_job_id UUID := gen_random_uuid();
    v_channel TEXT;
    v_status TEXT;
    v_dedup_key TEXT;
BEGIN
    -- Create job
    INSERT INTO notify.notification_jobs (id, tenant_id, site_id, created_by)
    VALUES (v_job_id, v_tenant_id, 1, 'staging-drill');

    FOR i IN 1..10000 LOOP
        -- Channel distribution
        v_channel := CASE WHEN random() < 0.6 THEN 'WHATSAPP' ELSE 'EMAIL' END;

        -- Status distribution (5% SKIPPED, 10% will 429, 85% normal)
        v_status := CASE
            WHEN random() < 0.05 THEN 'SKIPPED'  -- Invalid contact
            ELSE 'PENDING'
        END;

        v_dedup_key := encode(sha256(('drill-' || i || '-' || v_channel)::bytea), 'hex');

        INSERT INTO notify.notification_outbox (
            id, tenant_id, site_id, job_id, driver_id,
            delivery_channel, template_id, message_params,
            status, dedup_key, skip_reason
        ) VALUES (
            gen_random_uuid(), v_tenant_id, 1, v_job_id,
            'DRV-' || lpad(i::text, 5, '0'),
            v_channel, 'plan_published_v1',
            jsonb_build_object('driver_name', 'Driver ' || i, 'plan_date', '2026-01-15'),
            v_status, v_dedup_key,
            CASE WHEN v_status = 'SKIPPED' THEN 'INVALID_CONTACT' ELSE NULL END
        );
    END LOOP;

    RAISE NOTICE 'Seeded 10k messages for job %', v_job_id;
END $$;

-- Verify distribution
SELECT
    delivery_channel,
    status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as pct
FROM notify.notification_outbox
WHERE job_id = (SELECT id FROM notify.notification_jobs ORDER BY created_at DESC LIMIT 1)
GROUP BY delivery_channel, status
ORDER BY delivery_channel, status;
```

### Drill: 2 Workers + Kill -9

```bash
# Terminal 1: Start Worker A
cd backend_dotnet/Solvereign.Notify
NOTIFY_WORKER_ID="worker-A-$(hostname)" dotnet run

# Terminal 2: Start Worker B
cd backend_dotnet/Solvereign.Notify
NOTIFY_WORKER_ID="worker-B-$(hostname)" dotnet run

# Wait for ~30 seconds (workers claiming batches)

# Terminal 3: Monitor claiming
watch -n 1 'psql $DATABASE_URL -c "
  SELECT locked_by, status, COUNT(*)
  FROM notify.notification_outbox
  WHERE status IN ('"'"'SENDING'"'"', '"'"'PENDING'"'"', '"'"'RETRYING'"'"')
  GROUP BY locked_by, status
  ORDER BY locked_by, status;"'

# Kill Worker A abruptly (simulate crash)
pkill -9 -f "worker-A"

# Expected: Worker A's SENDING messages have lock_expires_at set
```

### Verification: Reaper Recovery

```sql
-- Check stuck messages immediately after kill
SELECT
    locked_by,
    status,
    COUNT(*) as count,
    MIN(lock_expires_at) as earliest_lock_expires,
    MAX(lock_expires_at) as latest_lock_expires
FROM notify.notification_outbox
WHERE status = 'SENDING'
GROUP BY locked_by, status;

-- Wait for reaper (default: 60s interval, 5min lock timeout)
-- Or trigger manually:
SELECT notify.release_stuck_sending('10 minutes'::interval);

-- Verify recovery
SELECT
    status,
    COUNT(*) as count,
    COUNT(*) FILTER (WHERE last_error_code = 'LOCK_EXPIRED') as recovered_by_reaper
FROM notify.notification_outbox
GROUP BY status
ORDER BY status;
```

### Success Criteria

| Check | Expected | FAIL if |
|-------|----------|---------|
| No double-sends | `provider_message_id` unique per message | Duplicates found |
| Reaper recovery | Stuck SENDING → RETRYING | Messages stay SENDING > 10 min |
| Dead-letter stable | DEAD count = 5% of 10k ± tolerance | Unexpected DEAD growth |
| No lost messages | Total = 10k | Count < 10k |

```sql
-- Double-send check
SELECT provider_message_id, COUNT(*)
FROM notify.notification_outbox
WHERE provider_message_id IS NOT NULL
GROUP BY provider_message_id
HAVING COUNT(*) > 1;
-- Expected: 0 rows

-- Message integrity
SELECT COUNT(*) FROM notify.notification_outbox
WHERE job_id = (SELECT id FROM notify.notification_jobs ORDER BY created_at DESC LIMIT 1);
-- Expected: 10000
```

---

## 2. Webhook Signature Drill

### Clock Skew Test

```bash
# Test: Webhook with timestamp in past (6 min ago) - should FAIL
TIMESTAMP=$(($(date +%s) - 360))
BODY='[{"event":"delivered","sg_message_id":"test123"}]'

# This should return 401 Unauthorized
curl -X POST http://localhost:5000/api/notify/webhooks/sendgrid \
  -H "Content-Type: application/json" \
  -H "X-Twilio-Email-Event-Webhook-Timestamp: $TIMESTAMP" \
  -H "X-Twilio-Email-Event-Webhook-Signature: invalid" \
  -d "$BODY"

# Test: Webhook with timestamp in future (2 min) - should FAIL
TIMESTAMP=$(($(date +%s) + 120))
curl -X POST http://localhost:5000/api/notify/webhooks/sendgrid \
  -H "Content-Type: application/json" \
  -H "X-Twilio-Email-Event-Webhook-Timestamp: $TIMESTAMP" \
  -H "X-Twilio-Email-Event-Webhook-Signature: invalid" \
  -d "$BODY"
```

### NTP Verification (Runbook Item)

```bash
# On all worker nodes, verify NTP sync
timedatectl status | grep -E "NTP|synchronized"
# Expected: NTP service: active, System clock synchronized: yes

# Check drift
chronyc tracking | grep "System time"
# Expected: offset < 100ms

# Alert if drift > 1s
if [ $(chronyc tracking | grep "System time" | awk '{print $4}' | sed 's/[^0-9.]//g' | cut -d'.' -f1) -gt 1 ]; then
    echo "ALERT: Clock drift > 1 second!"
fi
```

### Stale Timestamp Alerting

```sql
-- Create monitoring view for webhook rejections
CREATE OR REPLACE VIEW notify.webhook_rejection_stats AS
SELECT
    date_trunc('hour', created_at) as hour,
    COUNT(*) FILTER (WHERE last_error_code = 'TIMESTAMP_EXPIRED') as stale_timestamp,
    COUNT(*) FILTER (WHERE last_error_code = 'SIGNATURE_INVALID') as invalid_signature,
    COUNT(*) as total_webhooks,
    ROUND(100.0 * COUNT(*) FILTER (WHERE last_error_code = 'TIMESTAMP_EXPIRED') / NULLIF(COUNT(*), 0), 2) as stale_pct
FROM notify.webhook_events
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY date_trunc('hour', created_at)
ORDER BY hour DESC;

-- Alert query: >1% stale timestamp rejections
SELECT hour, stale_pct
FROM notify.webhook_rejection_stats
WHERE stale_pct > 1.0
  AND hour > NOW() - INTERVAL '1 hour';
-- If rows returned: CHECK NTP SYNC ON ALL NODES
```

---

## 3. Retention & VACUUM Tuning

### Autovacuum Configuration

```sql
-- Check current autovacuum settings for notify tables
SELECT
    schemaname || '.' || relname as table_name,
    n_dead_tup,
    n_live_tup,
    last_vacuum,
    last_autovacuum,
    autovacuum_count
FROM pg_stat_user_tables
WHERE schemaname = 'notify'
ORDER BY n_dead_tup DESC;

-- Tune autovacuum for high-churn tables
ALTER TABLE notify.notification_outbox SET (
    autovacuum_vacuum_threshold = 1000,
    autovacuum_vacuum_scale_factor = 0.05,  -- 5% dead tuples triggers vacuum
    autovacuum_analyze_threshold = 500,
    autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE notify.notification_delivery_log SET (
    autovacuum_vacuum_threshold = 500,
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_threshold = 250,
    autovacuum_analyze_scale_factor = 0.01
);

ALTER TABLE notify.webhook_events SET (
    autovacuum_vacuum_threshold = 500,
    autovacuum_vacuum_scale_factor = 0.02
);
```

### Index Bloat Monitoring

```sql
-- Check index bloat (run weekly)
SELECT
    schemaname || '.' || tablename as table_name,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
    idx_scan as index_scans,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'notify'
ORDER BY pg_relation_size(indexrelid) DESC;

-- Reindex if bloat > 30% (run during maintenance window)
-- REINDEX INDEX CONCURRENTLY notify.idx_outbox_dedup_key;
```

### Partitioning Strategy (Volume > 100k/day)

```sql
-- Future: Partition delivery_log by month
-- Only implement when daily volume exceeds 100k rows

-- Example partition setup (DO NOT RUN unless volume justifies)
/*
CREATE TABLE notify.notification_delivery_log_partitioned (
    LIKE notify.notification_delivery_log INCLUDING ALL
) PARTITION BY RANGE (created_at);

CREATE TABLE notify.delivery_log_2026_01 PARTITION OF notify.notification_delivery_log_partitioned
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- Automated partition creation via pg_partman extension
*/
```

### Cleanup Schedule

```sql
-- Production cleanup schedule (pg_cron)
-- Run at 2 AM daily, 30-day retention, archive enabled
SELECT cron.schedule(
    'notify-cleanup-daily',
    '0 2 * * *',
    $$SELECT notify.cleanup_notifications(
        p_retention_days := 30,
        p_archive_before_delete := TRUE,
        p_batch_size := 1000,
        p_max_batches := 100
    )$$
);

-- Archive purge (365-day retention, run monthly)
SELECT cron.schedule(
    'notify-archive-purge-monthly',
    '0 3 1 * *',  -- 3 AM on 1st of month
    $$SELECT notify.purge_archive(365)$$
);
```

---

## 4. Security Hygiene

### Public Key Rotation (Dual-Key Window)

SendGrid allows configuring a new public key while keeping the old one active during rotation.

**Rotation Procedure:**

1. **Generate new key in SendGrid** (Settings → Mail Settings → Event Webhook → Generate New Key)
2. **Note both keys** - SendGrid shows both during transition
3. **Update config with new key** (but keep old key working for 1 hour)
4. **Deploy** - New pods use new key
5. **Verify** - Check webhook success rate
6. **Disable old key in SendGrid** after 1 hour

```csharp
// Config supports key rotation (add to NotifyConfig.cs if needed)
public sealed class SendGridConfig
{
    // Primary key (current)
    public string? WebhookPublicKey { get; set; }

    // Secondary key (during rotation)
    public string? WebhookPublicKeySecondary { get; set; }
}

// Controller: Try primary, fallback to secondary
private bool VerifySendGridSignature(string rawBody, string? signature, string? timestamp)
{
    // Try primary key
    if (VerifyWithKey(rawBody, signature, timestamp, _sendGridConfig.WebhookPublicKey))
        return true;

    // Fallback to secondary during rotation
    if (!string.IsNullOrEmpty(_sendGridConfig.WebhookPublicKeySecondary))
    {
        _logger.LogInformation("Primary key failed, trying secondary (rotation mode)");
        return VerifyWithKey(rawBody, signature, timestamp, _sendGridConfig.WebhookPublicKeySecondary);
    }

    return false;
}
```

### Raw Body Logging Prevention

**Audit Checklist:**

| Location | Check | Status |
|----------|-------|--------|
| `WebhookController.cs` | No `_logger.Log*` with `body` variable | ☐ |
| `WebhookController.cs` catch blocks | Only log exception type, not body | ☐ |
| Provider classes | No raw payload logging | ☐ |
| Repository classes | No message_params logging | ☐ |

```csharp
// WRONG - exposes PII
_logger.LogError(ex, "Webhook failed. Body: {Body}", body);  // ❌ NEVER

// CORRECT - safe logging
_logger.LogError(ex, "Webhook signature verification failed");  // ✓
_logger.LogWarning("Webhook rejected. EventCount: {Count}", events.Count);  // ✓
```

**Grep Check (CI Pipeline):**

```bash
# Add to CI: Fail if raw body logged
grep -rn "body\|rawBody\|payload" backend_dotnet/Solvereign.Notify/ \
  | grep -i "log\|Log" \
  | grep -v "//.*log" \
  | grep -v "PayloadHash"  # Hash is OK

# Should return 0 results
```

---

## 5. Evidence Artifacts (Go/No-Go Proof)

### Output File: `drill_evidence_{timestamp}.json`

After each drill run, generate and archive this evidence file:

```bash
# Generate evidence artifact
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
psql $DATABASE_URL -t -A -F',' -c "
SELECT json_build_object(
    'timestamp', NOW(),
    'drill_id', 'staging-drill-${TIMESTAMP}',
    'job_id', (SELECT id FROM notify.notification_jobs WHERE created_by = 'staging-drill' ORDER BY created_at DESC LIMIT 1),

    -- Status counts
    'counts', (
        SELECT json_build_object(
            'total', COUNT(*),
            'pending', COUNT(*) FILTER (WHERE status = 'PENDING'),
            'sending', COUNT(*) FILTER (WHERE status = 'SENDING'),
            'sent', COUNT(*) FILTER (WHERE status = 'SENT'),
            'delivered', COUNT(*) FILTER (WHERE status = 'DELIVERED'),
            'retrying', COUNT(*) FILTER (WHERE status = 'RETRYING'),
            'failed', COUNT(*) FILTER (WHERE status = 'FAILED'),
            'dead', COUNT(*) FILTER (WHERE status = 'DEAD'),
            'skipped', COUNT(*) FILTER (WHERE status = 'SKIPPED')
        )
        FROM notify.notification_outbox
        WHERE job_id = (SELECT id FROM notify.notification_jobs WHERE created_by = 'staging-drill' ORDER BY created_at DESC LIMIT 1)
    ),

    -- Duplicate check (MUST be 0)
    'duplicates_detected', (
        SELECT COUNT(*)
        FROM (
            SELECT provider_message_id
            FROM notify.notification_outbox
            WHERE provider_message_id IS NOT NULL
            GROUP BY provider_message_id
            HAVING COUNT(*) > 1
        ) dupes
    ),

    -- Stuck sending (before reaper)
    'stuck_sending_count', (
        SELECT COUNT(*)
        FROM notify.notification_outbox
        WHERE status = 'SENDING'
          AND lock_expires_at < NOW()
    ),

    -- Webhook rejection rate
    'webhook_stats', (
        SELECT json_build_object(
            'total_received', COUNT(*),
            'stale_timestamp_rejected', COUNT(*) FILTER (WHERE processed_at IS NULL),
            'rejection_rate_pct', ROUND(100.0 * COUNT(*) FILTER (WHERE processed_at IS NULL) / NULLIF(COUNT(*), 0), 2)
        )
        FROM notify.webhook_events
        WHERE created_at > NOW() - INTERVAL '1 hour'
    ),

    -- Reaper stats
    'reaper_stats', (
        SELECT json_build_object(
            'recovered_by_reaper', COUNT(*) FILTER (WHERE last_error_code = 'LOCK_EXPIRED'),
            'max_recovery_time_seconds', EXTRACT(EPOCH FROM MAX(updated_at - lock_expires_at))
        )
        FROM notify.notification_outbox
        WHERE last_error_code = 'LOCK_EXPIRED'
          AND created_at > NOW() - INTERVAL '1 hour'
    ),

    -- Worker distribution
    'worker_distribution', (
        SELECT json_agg(json_build_object('worker', locked_by, 'claimed', count))
        FROM (
            SELECT locked_by, COUNT(*) as count
            FROM notify.notification_outbox
            WHERE locked_by IS NOT NULL
            GROUP BY locked_by
        ) w
    )
);
" > "drill_evidence_${TIMESTAMP}.json"

echo "Evidence saved to drill_evidence_${TIMESTAMP}.json"
```

### Success Criteria in Evidence

| Field | Pass | Fail |
|-------|------|------|
| `duplicates_detected` | `= 0` | `> 0` |
| `stuck_sending_count` | `= 0` (after reaper) | `> 0` after 15 min |
| `webhook_stats.rejection_rate_pct` | `< 1.0` | `> 1.0` |
| `counts.dead` | `≈ 5%` of total (± 1%) | Unexpected growth |
| `reaper_stats.max_recovery_time_seconds` | `< 600` (10 min) | `> 900` |

### Archive Evidence

```bash
# Create evidence directory
mkdir -p staging_drill_evidence/$(date +%Y%m)

# Move evidence file
mv drill_evidence_*.json staging_drill_evidence/$(date +%Y%m)/

# Also export raw SQL snapshots
psql $DATABASE_URL -c "
  COPY (
    SELECT status, COUNT(*), AVG(attempt_count)::numeric(5,2) as avg_attempts
    FROM notify.notification_outbox
    WHERE created_at > NOW() - INTERVAL '2 hours'
    GROUP BY status
  ) TO STDOUT WITH CSV HEADER
" > "staging_drill_evidence/$(date +%Y%m)/status_summary_$(date +%Y%m%d_%H%M%S).csv"
```

### CI Integration (GitHub Actions)

```yaml
# .github/workflows/notify-staging-drill.yml
name: Notify Staging Drill

on:
  workflow_dispatch:
  schedule:
    - cron: '0 3 * * 1'  # Weekly Monday 3 AM

jobs:
  drill:
    runs-on: ubuntu-latest
    environment: staging

    steps:
      - uses: actions/checkout@v4

      - name: Run Staging Drill
        run: |
          # Seed data
          psql $DATABASE_URL < docs/notify_drill_seed.sql

          # Start workers (background)
          dotnet run --project backend_dotnet/Solvereign.Notify &
          WORKER_PID=$!

          # Wait for processing
          sleep 60

          # Kill worker (simulate crash)
          kill -9 $WORKER_PID || true

          # Wait for reaper
          sleep 120

          # Generate evidence
          ./scripts/generate_drill_evidence.sh > drill_evidence.json

      - name: Validate Evidence
        run: |
          # Check duplicates = 0
          DUPES=$(jq '.duplicates_detected' drill_evidence.json)
          if [ "$DUPES" != "0" ]; then
            echo "FAIL: Duplicates detected: $DUPES"
            exit 1
          fi

          # Check stuck = 0
          STUCK=$(jq '.stuck_sending_count' drill_evidence.json)
          if [ "$STUCK" != "0" ]; then
            echo "FAIL: Stuck messages: $STUCK"
            exit 1
          fi

          echo "PASS: All checks passed"

      - name: Upload Evidence
        uses: actions/upload-artifact@v4
        with:
          name: drill-evidence-${{ github.run_id }}
          path: drill_evidence.json
          retention-days: 90
```

---

## 6. Drill Execution Checklist

### Pre-Drill

- [ ] Staging DB backup taken
- [ ] Workers scaled to 2 replicas
- [ ] NTP sync verified on all nodes
- [ ] SendGrid public key configured
- [ ] Monitoring dashboards open

### Drill Execution

- [ ] Seed 10k messages (Section 1)
- [ ] Start 2 workers
- [ ] Monitor claiming distribution
- [ ] Kill Worker A with `kill -9`
- [ ] Verify reaper recovery
- [ ] Run webhook clock skew tests (Section 2)
- [ ] Run double-send verification query
- [ ] Run message integrity check

### Post-Drill

- [ ] Cleanup test data: `DELETE FROM notify.notification_jobs WHERE created_by = 'staging-drill';`
- [ ] Reset sequences if needed
- [ ] Document any issues found
- [ ] Update runbook with learnings

### Success Criteria Summary

| Test | Pass | Fail |
|------|------|------|
| Crash Recovery | 100% messages recovered, 0 duplicates | Any lost or duplicated |
| Webhook Signatures | Stale/future timestamps rejected | Any accepted |
| Reaper | SENDING → RETRYING within 10 min | Stuck > 15 min |
| Rate Limiting | No provider 429 errors in prod | Burst exceeds limits |
| VACUUM | Bloat < 20% | Bloat > 30% |

---

## 6. Monitoring Queries (Grafana/Prometheus)

```sql
-- Query 1: Outbox Status Distribution (gauge)
SELECT status, COUNT(*) as count
FROM notify.notification_outbox
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status;

-- Query 2: Processing Rate (counter)
SELECT
    date_trunc('minute', updated_at) as minute,
    COUNT(*) FILTER (WHERE status = 'SENT') as sent,
    COUNT(*) FILTER (WHERE status = 'DELIVERED') as delivered,
    COUNT(*) FILTER (WHERE status = 'FAILED') as failed
FROM notify.notification_outbox
WHERE updated_at > NOW() - INTERVAL '1 hour'
GROUP BY date_trunc('minute', updated_at)
ORDER BY minute;

-- Query 3: Stuck Message Alert (alert if > 0)
SELECT COUNT(*) as stuck_count
FROM notify.notification_outbox
WHERE status = 'SENDING'
  AND lock_expires_at < NOW();

-- Query 4: Dead Letter Queue Size (alert if > 100)
SELECT COUNT(*) as dead_letter_count
FROM notify.notification_outbox
WHERE status = 'DEAD';

-- Query 5: Webhook Rejection Rate (alert if > 1%)
SELECT
    ROUND(100.0 * COUNT(*) FILTER (WHERE processed_at IS NULL) / NULLIF(COUNT(*), 0), 2) as rejection_pct
FROM notify.webhook_events
WHERE created_at > NOW() - INTERVAL '1 hour';
```

---

*Last Updated: 2026-01-09 | Author: Agent V4.1.2*
