# SOLVEREIGN V3.3b Security Proof Dossier

**Date**: 2026-01-06
**Version**: V3.3b Phase 1 Security Hardening
**Status**: VALIDATED

---

## Executive Summary

Phase 1 Security Hardening implements:

1. **HMAC-SHA256 V2 Signing** - Nonce + body hash + timestamp binding
2. **Replay Protection** - Nonce tracking with 403 REPLAY_ATTACK response
3. **Timestamp Window** - +/- 120 seconds tolerance
4. **Body Hash Binding** - SHA256 prevents payload tampering
5. **Idempotency Keys** - Deterministic keys for safe wizard retry

---

## Proof 1: Replay Attack Protection

### Unit Test Evidence

```
======================================================================
 PROOF 1: REPLAY ATTACK PROTECTION (UNIT TEST)
======================================================================

[1] Generated signed request:
    Method: GET
    Path: /api/v1/platform/orgs
    Nonce: 75bf3599db88e6b7dd29710da9d5f629
    Timestamp: 1767731272
    Signature: 171300783bcb7b2d3a6b55d64f06e794...

[2] Determinism check: PASS (same inputs -> same signature)
[3] Uniqueness check: PASS (different nonce -> different signature)
[4] Timestamp binding: PASS (timestamp change -> different signature)

[5] First request with nonce 75bf3599db88e6b7...:
    Is replay: False
    => ACCEPTED (nonce recorded)

[6] Second request with SAME nonce:
    Is replay: True
    => REJECTED (nonce already used)

----------------------------------------------------------------------
 PROOF 1 RESULT: PASS
----------------------------------------------------------------------
```

### Backend Implementation

**File**: `backend_py/api/security/internal_signature.py`

```python
# Line 418-443: Replay detection
if check_replay:
    is_replay = await _check_and_record_nonce(
        request, x_sv_nonce, timestamp
    )
    if is_replay:
        logger.error("internal_signature_replay", ...)

        await _record_security_event(
            request,
            event_type="REPLAY_ATTACK",
            severity="S0",
            details={"nonce_prefix": x_sv_nonce[:8]}
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "REPLAY_ATTACK", "message": "Replay attack detected"}
        )
```

### Database Schema

**File**: `backend_py/db/migrations/022_replay_protection.sql`

```sql
CREATE TABLE IF NOT EXISTS core.used_signatures (
    signature           VARCHAR(64) PRIMARY KEY,  -- Nonce value
    timestamp           BIGINT NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS core.security_events (
    id                  SERIAL PRIMARY KEY,
    event_type          VARCHAR(50) NOT NULL,     -- REPLAY_ATTACK, etc.
    severity            VARCHAR(10) NOT NULL,     -- S0, S1, S2, S3
    source_ip           VARCHAR(45),
    request_path        VARCHAR(500),
    request_method      VARCHAR(10),
    details             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Proof 2: Body Hash Binding

### Unit Test Evidence

```
======================================================================
 PROOF 2: BODY HASH BINDING
======================================================================

[1] Body 1: {"name":"Test Org","org_code":"test-org"}
    Hash: 5749af251d0d355589c5676b2088cb6e...

[2] Body 2: {"name":"DIFFERENT Name","org_code":"test-org"}
    Hash: 8725e91becb169097ae27d2894e2f605...

[3] Hash uniqueness: PASS (different body -> different hash)
[4] Signature binding: PASS (different body -> different signature)

----------------------------------------------------------------------
 PROOF 2 RESULT: PASS
----------------------------------------------------------------------
```

### Implementation

**Frontend**: `frontend_v5/lib/platform-api.ts`

```typescript
export function computeBodyHash(body: unknown): string {
  if (body === null || body === undefined) return '';
  const bodyString = typeof body === 'string' ? body : JSON.stringify(body);
  if (!bodyString || bodyString === '{}') return '';
  return crypto.createHash('sha256').update(bodyString, 'utf8').digest('hex');
}
```

**Backend Verification**: `internal_signature.py` line 334-362

```python
if request.method.upper() in methods_with_body:
    body_bytes = await request.body()
    expected_body_hash = compute_body_hash(body_bytes)

    if x_sv_body_hash != expected_body_hash:
        await _record_security_event(
            request,
            event_type="SIG_BODY_MISMATCH",
            severity="S0",
            details={"reason": "Body hash does not match"}
        )
        raise HTTPException(status_code=401, detail="Request body hash mismatch")
```

---

## Proof 3: Timestamp Window

### Unit Test Evidence

```
======================================================================
 PROOF 3: TIMESTAMP WINDOW VALIDATION
======================================================================

[1] Current time: 1767731272
    Window: +/- 120 seconds

[2] Valid timestamp checks:
    1767731272 (diff=+0s): VALID
    1767731212 (diff=+60s): VALID
    1767731152 (diff=+120s): VALID

[3] Invalid timestamp checks:
    1767731151 (diff=+121s): INVALID (outside window)
    1767727672 (diff=+3600s): INVALID (outside window)

----------------------------------------------------------------------
 PROOF 3 RESULT: PASS
----------------------------------------------------------------------
```

### Configuration

```python
# backend_py/api/security/internal_signature.py
TIMESTAMP_WINDOW_SECONDS = 120  # +/- 2 minutes
```

---

## Proof 4: Idempotency Keys

### Unit Test Evidence

```
======================================================================
 PROOF 4: IDEMPOTENCY KEY STRUCTURE
======================================================================

[1] Key generation:
    create-org:lts -> create-org:lts
    create-org:lts -> create-org:lts (same)
    create-org:different-org -> create-org:different-org

[2] Determinism: PASS (same inputs -> same key)
[3] Uniqueness: PASS (different inputs -> different key)

[4] Multi-part keys:
    create-tenant:lts:wien -> create-tenant:lts:wien
    create-site:wien:depot1 -> create-site:wien:depot1

----------------------------------------------------------------------
 PROOF 4 RESULT: PASS
----------------------------------------------------------------------
```

### Implementation

**Frontend**: `frontend_v5/lib/platform-api.ts`

```typescript
export function generateIdempotencyKey(
  operation: string,
  ...identifiers: string[]
): string {
  if (identifiers.length > 0) {
    return `${operation}:${identifiers.join(':')}`;
  }
  return `${operation}:${crypto.randomUUID()}`;
}

// Usage in API calls:
create: (data) => platformFetch<Organization>('/api/v1/platform/orgs', {
  method: 'POST',
  body: data,
  idempotencyKey: generateIdempotencyKey('create-org', data.org_code),
}),
```

---

## Design Decisions

| Scenario | Response | Rationale |
|----------|----------|-----------|
| Replay Attack | `403 Forbidden` | Not auth failure, request is forbidden |
| Body Mismatch | `401 Unauthorized` | Signature invalid = auth failure |
| Timestamp Skew | `401 Unauthorized` | Signature invalid = auth failure |
| Idempotency Hit | `200 OK` + cached | Already processed successfully |
| Idempotency Mismatch | `409 Conflict` | Same key, different payload |

---

## V2 Canonical Format

```
METHOD|CANONICAL_PATH|TIMESTAMP|NONCE|TENANT_CODE|SITE_CODE|IS_PLATFORM_ADMIN|BODY_SHA256
```

**Example**:
```
POST|/api/v1/platform/orgs|1767731272|75bf3599db88e6b7dd29710da9d5f629||1|5749af251d0d355589c5676b2088cb6e...
```

---

## Files Modified

| File | Changes |
|------|---------|
| `frontend_v5/lib/platform-api.ts` | V2 signing: nonce, body hash, canonicalization, idempotency keys |
| `backend_py/api/security/internal_signature.py` | V2 verification: replay check, body hash, timestamp window |
| `backend_py/db/migrations/022_replay_protection.sql` | `core.used_signatures`, `core.security_events` tables |
| `frontend_v5/components/platform/resolve-escalation-dialog.tsx` | S0/S1 confirmation with RESOLVE keyword |
| `frontend_v5/lib/platform-auth.ts` | Platform user identity utility |
| `frontend_v5/app/(platform)/escalations/page.tsx` | Resolve governance dialog integration |

---

## Test Files

| File | Purpose |
|------|---------|
| `backend_py/tests/test_replay_protection_unit.py` | 4 unit proof tests (all passing) |
| `backend_py/tests/test_security_proofs.py` | Test case generator with curl commands |
| `backend_py/tests/e2e_replay_proof.py` | E2E test (requires platform routes) |

---

## Validation Command

```bash
python backend_py/tests/test_replay_protection_unit.py
```

**Expected Output**:
```
======================================================================
 FINAL SUMMARY
======================================================================
  [PASS] Proof 1: Replay Detection
  [PASS] Proof 2: Body Hash Binding
  [PASS] Proof 3: Timestamp Window
  [PASS] Proof 4: Idempotency Keys
======================================================================

[OK] ALL SECURITY PROOFS PASSED

======================================================================
 PHASE 1 SECURITY HARDENING: VALIDATED
======================================================================
```

---

## Conclusion

Phase 1 Security Hardening is **VALIDATED**. All proofs pass. Ready for Phase 2: Tenant Ops Cockpit (Wien Pilot).
