# ADR-002: Advisory Locks for Concurrent Solve Prevention

## Status
Accepted

## Context
Multiple API requests could attempt to solve the same forecast concurrently, leading to:
- Resource waste
- Inconsistent results
- Database contention

## Decision
Use **PostgreSQL Advisory Locks** to prevent concurrent solves:

```sql
SELECT pg_try_advisory_lock(lock_key);  -- Non-blocking acquire
SELECT pg_advisory_unlock(lock_key);    -- Release
```

Lock key computation:
```python
lock_key = (tenant_id << 32) | forecast_version_id
```

## Implementation

1. **try_acquire_solve_lock()**: Non-blocking, returns false if lock held
2. **release_solve_lock()**: Always release in finally block
3. **is_solve_locked()**: Check status via pg_locks

## Consequences

### Positive
- No external dependencies (Redis, etc.)
- Automatic release on connection close
- Tenant isolation via key composition
- Fast (in-memory in PostgreSQL)

### Negative
- Session-bound (lock released if connection drops)
- Not distributed (single PostgreSQL instance only)
- Lock key space limited to bigint

### Mitigations
- Always release in finally block
- Log lock acquisition/release events
- Monitor pg_locks for stuck locks

## HTTP Response Codes
- **200**: Lock acquired, solve succeeded
- **423 Locked**: Lock not acquired, forecast already being solved

## References
- Migration 009: Advisory lock helper functions
- backend_py/api/database.py: try_acquire_solve_lock()
- backend_py/api/routers/plans.py: solve_forecast()
