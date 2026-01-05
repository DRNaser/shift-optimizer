# SOLVEREIGN V3.3b - Security Review Guide

**For**: Senior Developer / Security Architect
**Date**: 2026-01-05
**Review Time**: ~15 minutes

---

## Review Path (Follow This Order)

### Step 1: Source of Truth (2 min)

**File**: [SECURITY_EVIDENCE_PACK.md](SECURITY_EVIDENCE_PACK.md) - Section 0

**Verify**:
- External IdP (OIDC) is DEFAULT
- Self-Hosted Auth is OPTIONAL and BLOCKED in production

```
| Mode        | Config              | Production |
|-------------|---------------------|------------|
| OIDC        | AUTH_MODE=OIDC      | Allowed    |
| Self-Hosted | AUTH_MODE=SELF_HOSTED | BLOCKED (unless explicit) |
```

---

### Step 2: RLS Proof (3 min)

**File**: [SECURITY_EVIDENCE_PACK.md](SECURITY_EVIDENCE_PACK.md) - Section 4.4

**Verify SQL test script**:
```sql
-- Key assertions:
SET ROLE solvereign_api;
SELECT set_tenant_context('tenant-A');
SELECT COUNT(*) FROM forecast_versions;  -- Should see ONLY Tenant A
```

**Verify NOBYPASSRLS**:
```sql
ALTER ROLE solvereign_api NOBYPASSRLS;  -- Line in migration
```

---

### Step 3: Rate Limit Failover (2 min)

**File**: [SECURITY_EVIDENCE_PACK.md](SECURITY_EVIDENCE_PACK.md) - Section 5.3

**Decision**: FAIL-OPEN

**Rationale**:
- Availability > Perfect rate limiting
- Per-instance fallback still provides protection
- Dispatcher needs to work even if Redis is down

---

### Step 4: Audit Hash Chain Spec (2 min)

**File**: [SECURITY_EVIDENCE_PACK.md](SECURITY_EVIDENCE_PACK.md) - Section 6.1

**Verify deterministic spec**:
- Fields in order: previous_hash, timestamp, event_type, tenant_id, user_id, severity, details_json
- First entry uses 'GENESIS' as prefix
- SHA-256, hex encoded

**Verify CLI exists**:
```bash
python cli.py audit verify --start 1 --limit 10000
```

---

### Step 5: Middleware Order Test (3 min)

**File**: [backend_py/tests/test_middleware_order.py](backend_py/tests/test_middleware_order.py)

**Run test**:
```bash
python backend_py/tests/test_middleware_order.py
```

**Expected output**:
```
[TEST 1] Auth before RateLimit (correct)...
Execution order: [...'4_Auth_ENTER', '5_RateLimit_ENTER', '5_RateLimit_HAS_TENANT:test-tenant-id'...]
[PASS] Middleware order correct - Auth runs before RateLimit
```

**Key assertion**: RateLimit has access to `tenant_id` (auth ran first)

---

### Step 6: Production Guardrails (2 min)

**File**: [backend_py/api/security/auth_mode.py](backend_py/api/security/auth_mode.py)

**Verify**:
```python
if mode == AuthMode.SELF_HOSTED and environment == "production":
    allow_self_hosted = os.environ.get("ALLOW_SELF_HOSTED_IN_PROD", "").lower() == "true"
    if not allow_self_hosted:
        sys.exit(1)  # BLOCKS production startup
```

---

### Step 7: Log Redaction (1 min)

**File**: [SECURITY_EVIDENCE_PACK.md](SECURITY_EVIDENCE_PACK.md) - Section 7

**Verify logged fields** (api/main.py:184-193):
- request_id, method, path, status_code, duration_ms

**Verify NOT logged**:
- Authorization header
- X-API-Key header
- Cookie header

---

### Step 8: Key Management ADR (optional, 2 min)

**File**: [backend_py/docs/ADR_001_KEY_MANAGEMENT.md](backend_py/docs/ADR_001_KEY_MANAGEMENT.md)

**Key points**:
- Envelope encryption (KEK in KMS, DEK per tenant)
- Key rotation procedure (24h overlap)
- GDPR crypto-erasure (delete DEK = data unreadable)

---

## Sign-Off Checklist

| Item | Status |
|------|--------|
| IdP default, self-hosted blocked in prod | [ ] |
| RLS enabled + NOBYPASSRLS on API role | [ ] |
| Rate limit fail-open documented | [ ] |
| Audit hash chain deterministic | [ ] |
| Middleware order tested (5/5 pass) | [ ] |
| auth_mode.py prod guardrails | [ ] |
| Log redaction (no tokens in logs) | [ ] |

---

## Sign-Off Text (Copy/Paste)

```
Security P0 completed.

Default auth = External IdP (OIDC). Self-hosted auth is production-gated.
RLS enforced (NOBYPASSRLS + row_security proof).
Middleware order is tested (5/5 pass - auth before rate limit).
Rate limit behavior: FAIL-OPEN (documented).
Audit chain: deterministic spec + verify CLI included.
Log redaction: No tokens/credentials in logs.

Ready for sign-off.
```

---

## Remaining Items (Out of Scope for This Review)

| Item | Status |
|------|--------|
| Keycloak/Auth0 tenant setup | Pending |
| MFA enforcement for PLAN_APPROVER+ | Pending |
| CRITICAL event alerting | Pending |
| Penetration test | Pending |

These are tracked in [V3.3b_BACKLOG.md](V3.3b_BACKLOG.md).

---

*Generated: 2026-01-05*
