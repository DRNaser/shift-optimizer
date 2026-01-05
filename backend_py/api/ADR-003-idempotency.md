# ADR-003: Request Idempotency

## Status
Accepted

## Context
Network failures and retries are common. Without idempotency:
- Duplicate forecasts created
- Double solves
- Inconsistent state

## Decision
Implement **request-level idempotency** via X-Idempotency-Key header:

1. Client provides unique key per logical request
2. Server stores (key, request_hash, response)
3. On retry:
   - Same key + same body = return cached response (HIT)
   - Same key + different body = 409 Conflict (MISMATCH)
   - New key = process request (NEW)

## Implementation

### Database Table
```sql
CREATE TABLE idempotency_keys (
    tenant_id INTEGER,
    idempotency_key VARCHAR(64),
    request_hash VARCHAR(64),  -- SHA256 of body
    response_status INTEGER,
    response_body JSONB,
    expires_at TIMESTAMPTZ,    -- 24h TTL
    UNIQUE (tenant_id, idempotency_key, endpoint)
);
```

### Flow
```
Request with X-Idempotency-Key
       ↓
   check_idempotency()
       ↓
   ┌──────────────────┐
   │ NEW → Process    │
   │ HIT → Return     │
   │ MISMATCH → 409   │
   └──────────────────┘
       ↓
   record_idempotency()
```

## Consequences

### Positive
- Safe retries for clients
- No duplicate resources
- Response caching reduces load on retries

### Negative
- Storage overhead for keys
- TTL management needed
- Client must generate/track keys

### Mitigations
- 24h TTL with cleanup function
- cleanup_expired_idempotency_keys() cron job
- UUIDs recommended for key generation

## HTTP Response Codes
- **2xx**: Normal processing or cache hit
- **409 Conflict**: Same key, different request body

## References
- Migration 007: Idempotency keys
- backend_py/api/database.py: check_idempotency()
- backend_py/api/dependencies.py: get_idempotency()
