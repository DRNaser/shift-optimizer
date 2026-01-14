# Pilot Runbook: Ops-Copilot WhatsApp

> **Version**: 2.0 | **Date**: 2026-01-13 | **Status**: Pilot Ready

---

## 1. Migration Order

Run via standard migration runner (not manual psql):

```bash
# From project root
python scripts/run_migrations.py --up-to 054

# Or individually (MUST be in order):
python scripts/run_migrations.py --apply 053_ops_copilot.sql
python scripts/run_migrations.py --apply 054_ops_copilot_hardening.sql
```

| Migration | Purpose | Rollback |
|-----------|---------|----------|
| `053_ops_copilot.sql` | Schema + 12 tables + RLS | `DROP SCHEMA ops CASCADE;` + remove permissions |
| `054_ops_copilot_hardening.sql` | Idempotency table + `check_and_record_idempotency()` function | `DROP TABLE ops.ingest_dedup;` + drop functions |

**Verify after migration:**
```sql
SELECT * FROM ops.verify_ops_copilot_integrity();
-- Expect: 6 rows, all status = 'PASS'
```

**Rollback (full):**
```sql
-- DANGER: Destroys all ops-copilot data
DROP SCHEMA ops CASCADE;
DELETE FROM auth.permissions WHERE permission_key LIKE 'ops_copilot.%';
DELETE FROM auth.role_permissions WHERE permission_id IN (
    SELECT id FROM auth.permissions WHERE permission_key LIKE 'ops_copilot.%'
);
```

---

## 2. Environment Variables

| Variable | Required | Example | Notes |
|----------|----------|---------|-------|
| `CLAWDBOT_WEBHOOK_SECRET` | **YES** | `sk_live_abc123...` | HMAC signing key from Clawdbot dashboard |
| `CLAWDBOT_HMAC_TOLERANCE_SECONDS` | No | `300` | Default: 300 (5 min) |
| `OPS_COPILOT_DRAFT_EXPIRY_MINUTES` | No | `5` | Default: 5 |
| `OPS_COPILOT_MAX_STEPS` | No | `8` | LangGraph step limit |
| `OPS_COPILOT_MAX_TOOL_CALLS` | No | `5` | Tool call limit |
| `OPS_COPILOT_TIMEOUT_SECONDS` | No | `20` | Per-request timeout |
| `DATABASE_URL` | **YES** | `postgres://...` | Must have ops schema access |

**Minimum .env addition:**
```bash
CLAWDBOT_WEBHOOK_SECRET=<get-from-clawdbot-dashboard>
```

---

## 3. 10-Minute E2E Smoke Test

### 3.1 Pairing + Ticket Flow (4 min)

```bash
# === STEP 1: Create OTP invite (as tenant_admin) ===
curl -X POST http://localhost:8000/api/v1/ops/pairing/invites \
  -H "Cookie: admin_session=<session>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<dispatcher-uuid>"}'
# Response: {"invite_id": "...", "otp": "123456", "expires_at": "..."}

# === STEP 2: User sends "PAIR 123456" via WhatsApp ===
# Bot responds: "Paired successfully!"

# === STEP 3: Verify identity created ===
curl http://localhost:8000/api/v1/ops/pairing/identities \
  -H "Cookie: admin_session=<session>"
# Expect: identity with status="ACTIVE"

# === STEP 4: User sends ticket request via WhatsApp ===
# "LKW W-1234 hat Bremsenproblem"
# Bot responds: "Create ticket: 'Bremsenproblem LKW W-1234'? Reply CONFIRM or CANCEL"

# === STEP 5: User sends "CONFIRM" ===
# Bot responds: "Ticket #123 created"

# === STEP 6: Verify ticket exists ===
curl http://localhost:8000/api/v1/ops/tickets \
  -H "Cookie: admin_session=<session>"
# Expect: ticket with title containing "Bremsenproblem"
```

### 3.2 Driver Broadcast + Double-Confirm Proof (4 min)

```bash
# === SETUP: Seed template + subscription ===
psql $DATABASE_URL -c "
INSERT INTO ops.broadcast_templates (
    tenant_id, template_key, audience, body_template,
    expected_params, wa_template_name, is_approved, is_active
) VALUES (
    1, 'shift_reminder', 'DRIVER',
    'Hallo {{driver_name}}, Schicht am {{date}} um {{time}}.',
    ARRAY['driver_name', 'date', 'time'],
    'shift_reminder_v1', TRUE, TRUE
) ON CONFLICT DO NOTHING;"

psql $DATABASE_URL -c "
INSERT INTO ops.broadcast_subscriptions (tenant_id, driver_id, is_subscribed)
VALUES (1, '<driver-uuid>', TRUE) ON CONFLICT DO NOTHING;"

# === STEP 1: User sends broadcast request via WhatsApp ===
# "Schichterinnerung an Max Mustermann für morgen 06:00"
# Bot responds: "Send template shift_reminder to 1 driver? Reply CONFIRM or CANCEL"

# === STEP 2: Get pending draft_id ===
DRAFT_ID=$(psql $DATABASE_URL -t -c "
SELECT id FROM ops.drafts WHERE status = 'PENDING_CONFIRM' ORDER BY created_at DESC LIMIT 1;")

# === STEP 3: First CONFIRM ===
curl -X POST "http://localhost:8000/api/v1/ops/drafts/${DRAFT_ID}/confirm" \
  -H "Cookie: admin_session=<session>" \
  -H "Content-Type: application/json" \
  -d '{"confirmed": true}'
# Response: {"status": "COMMITTED", "commit_result": {...}}

# === STEP 4: Second CONFIRM (must be idempotent) ===
curl -X POST "http://localhost:8000/api/v1/ops/drafts/${DRAFT_ID}/confirm" \
  -H "Cookie: admin_session=<session>" \
  -H "Content-Type: application/json" \
  -d '{"confirmed": true}'
# Response: {"status": "COMMITTED", ...} (same result, no re-execution)

# === STEP 5: Verify exactly 1 DRAFT_COMMITTED event ===
psql $DATABASE_URL -c "
SELECT COUNT(*) as event_count FROM ops.events
WHERE event_type = 'DRAFT_COMMITTED' AND payload->>'draft_id' = '${DRAFT_ID}';"
# MUST return: 1 (not 2)
```

### 3.3 Ingest Idempotency Proof (2 min)

```bash
# === Generate HMAC-signed request ===
TIMESTAMP=$(date +%s)
BODY='{"from":"whatsapp:436641234567","body":"Duplicate test","message_id":"msg_dedup_001"}'
SIG=$(echo -n "${TIMESTAMP}|${BODY}" | openssl dgst -sha256 -hmac "$CLAWDBOT_WEBHOOK_SECRET" | cut -d' ' -f2)

# === First ingest ===
curl -X POST http://localhost:8000/api/v1/ops/whatsapp/ingest \
  -H "Content-Type: application/json" \
  -H "X-Clawdbot-Signature: ${SIG}" \
  -H "X-Clawdbot-Timestamp: ${TIMESTAMP}" \
  -H "X-Request-Id: test-dedup-001" \
  -d "$BODY"
# Response: {"status": "processed", "thread_id": "..."}

# === Duplicate ingest (same X-Request-Id) ===
curl -X POST http://localhost:8000/api/v1/ops/whatsapp/ingest \
  -H "Content-Type: application/json" \
  -H "X-Clawdbot-Signature: ${SIG}" \
  -H "X-Clawdbot-Timestamp: ${TIMESTAMP}" \
  -H "X-Request-Id: test-dedup-001" \
  -d "$BODY"
# Response: {"status": "duplicate", ...}

# === Verify only 1 MESSAGE_IN event ===
psql $DATABASE_URL -c "
SELECT COUNT(*) FROM ops.events
WHERE event_type = 'MESSAGE_IN' AND payload->>'message_id' = 'msg_dedup_001';"
# MUST return: 1 (not 2)

# === Verify dedup record exists ===
psql $DATABASE_URL -c "
SELECT * FROM ops.ingest_dedup WHERE idempotency_key = 'test-dedup-001';"
# Should show 1 row
```

---

## 4. Idempotency Key Composition

### 4.1 Webhook Ingest (ops.ingest_dedup)

```
idempotency_key = X-Request-Id header (primary - from Clawdbot retry)
                  OR message_id from payload (WhatsApp's unique ID)
                  OR sha256(wa_user_id + timestamp + body[:100]) (fallback)
```

**Enforcement:** `ops.check_and_record_idempotency(key, wa_user_id, tenant_id)`
- Uses `INSERT ... ON CONFLICT DO NOTHING` on UNIQUE constraint
- Returns `TRUE` if duplicate (already processed), `FALSE` if new
- Called at start of `/ingest` before any processing

**Code reference:** [whatsapp.py:364-397](../backend_py/packs/ops_copilot/api/routers/whatsapp.py#L364-L397)

### 4.2 Draft Confirmation (atomic UPDATE)

```
idempotency_key = draft_id (UUID)
```

**Enforcement:** Two-phase atomic claim
1. `UPDATE ops.drafts SET status='COMMITTING' WHERE id=? AND status='PENDING_CONFIRM' RETURNING id`
2. If no rows returned → draft already claimed → re-fetch `commit_result` → return idempotent response
3. If rows returned → execute action → `UPDATE status='COMMITTED', commit_result=?`

**Code reference:** [drafts.py:380-410](../backend_py/packs/ops_copilot/api/routers/drafts.py#L380-L410)

### 4.3 State Transitions

```
PENDING_CONFIRM → COMMITTING → COMMITTED (happy path)
                            ↘ PENDING_CONFIRM (on error, allows retry)

Race condition:
  Request A: PENDING → COMMITTING → executes → COMMITTED
  Request B: PENDING → (UPDATE returns 0 rows) → fetch COMMITTED → return cached result
```

---

## 5. Crash Handling: Stuck COMMITTING Drafts

### Problem

If the server crashes between claiming (`COMMITTING`) and finalizing (`COMMITTED`), the draft is stuck.

### Detection

```sql
-- Find stuck drafts (COMMITTING for more than 60 seconds)
SELECT id, action_type, created_at, updated_at
FROM ops.drafts
WHERE status = 'COMMITTING'
  AND updated_at < NOW() - INTERVAL '60 seconds';
```

### Resolution

**Option A: Reset to PENDING_CONFIRM (allows retry)**
```sql
-- Reset stuck draft to allow retry
UPDATE ops.drafts
SET status = 'PENDING_CONFIRM',
    commit_error = 'Reset from COMMITTING after crash',
    updated_at = NOW()
WHERE id = '<draft_id>' AND status = 'COMMITTING';
```

**Option B: Mark as failed (if action may have partially executed)**
```sql
-- Mark as failed if side-effects may have occurred
UPDATE ops.drafts
SET status = 'FAILED',
    commit_error = 'Crash during commit - manual verification required',
    updated_at = NOW()
WHERE id = '<draft_id>' AND status = 'COMMITTING';
```

### When to use each option

| Scenario | Action |
|----------|--------|
| Crash before action executed | Option A (reset to PENDING) |
| Crash during action execution | Check if ticket/event exists, then Option A or B |
| Crash after action, before COMMITTED update | Option B + manually set `commit_result` |

### Verification after resolution

```sql
-- Check if action was actually executed
SELECT * FROM ops.events
WHERE payload->>'draft_id' = '<draft_id>';

-- For ticket drafts:
SELECT * FROM ops.tickets
WHERE draft_id = '<draft_id>';
```

---

## 6. Quick Reference Card

| Action | Endpoint | Auth | Idempotency |
|--------|----------|------|-------------|
| Webhook ingest | `POST /api/v1/ops/whatsapp/ingest` | HMAC | X-Request-Id |
| Create invite | `POST /api/v1/ops/pairing/invites` | Session | - |
| List identities | `GET /api/v1/ops/pairing/identities` | Session | - |
| Confirm draft | `POST /api/v1/ops/drafts/{id}/confirm` | Session | draft_id |
| List templates | `GET /api/v1/ops/broadcast/templates` | Session | - |

| Verify | Command |
|--------|---------|
| Schema integrity | `SELECT * FROM ops.verify_ops_copilot_integrity();` |
| Idempotency records | `SELECT COUNT(*) FROM ops.ingest_dedup;` |
| Pending drafts | `SELECT * FROM ops.drafts WHERE status = 'PENDING_CONFIRM';` |
| Stuck drafts | `SELECT * FROM ops.drafts WHERE status = 'COMMITTING' AND updated_at < NOW() - INTERVAL '60s';` |
| Event log | `SELECT * FROM ops.events ORDER BY created_at DESC LIMIT 10;` |

---

## 7. Test References

| Test | File | Purpose |
|------|------|---------|
| Double-confirm idempotent | [test_draft_commit.py:400-438](../backend_py/packs/ops_copilot/tests/test_draft_commit.py#L400-L438) | Owner gets cached result |
| Executor not called twice | [test_draft_commit.py:441-487](../backend_py/packs/ops_copilot/tests/test_draft_commit.py#L441-L487) | Spy verifies no side-effects |
| Race condition handling | [test_draft_commit.py:512-554](../backend_py/packs/ops_copilot/tests/test_draft_commit.py#L512-L554) | Loser gets idempotent response |
| Integration broadcast dedup | [test_broadcast_idempotency_integration.py](../backend_py/packs/ops_copilot/tests/test_broadcast_idempotency_integration.py) | Real DB proof |

---

**Sign-off:** Ready for Wien pilot deployment.
