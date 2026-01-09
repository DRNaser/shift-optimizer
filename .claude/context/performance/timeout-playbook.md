# Timeout Playbook

> **Purpose**: Diagnose and resolve timeout issues
> **Last Updated**: 2026-01-07

---

## IMMEDIATE ACTIONS

### System Frozen?

```bash
# 1. Check if processes are running
ps aux | grep python
ps aux | grep uvicorn

# 2. Check system resources
top -l 1 | head -20  # macOS
top -bn1 | head -20   # Linux

# 3. Check API health
curl -m 5 http://localhost:8000/health/live

# 4. If no response, restart
docker compose restart api
# OR
systemctl restart solvereign-api
```

---

## TIMEOUT TYPES

### 1. API Request Timeout

**Symptom**: HTTP 504 Gateway Timeout or client timeout

**Investigation**:
```bash
# Check nginx/proxy timeout settings
grep timeout /etc/nginx/nginx.conf

# Check uvicorn timeout
grep -r timeout backend_py/
```

**Common Causes**:
- Long-running database query
- External service (OSRM) slow
- Large payload processing

**Fixes**:
- Add query timeout: `SET statement_timeout = '30s'`
- Use async for long operations
- Paginate large responses

---

### 2. Solver Timeout

**Symptom**: Solver takes >60s (expected: 30-45s)

**Investigation**:
```python
# Check input size
forecast = get_forecast(forecast_id)
print(f"Tours: {len(forecast.tours)}")
print(f"Instances: {len(forecast.instances)}")

# Check solver config
print(f"Time limit: {solver_config.time_limit_seconds}")
print(f"Solution limit: {solver_config.solution_limit}")
```

**Common Causes**:
- Input too large (>500 tours)
- Solver parameters too aggressive
- Memory pressure causing swapping

**Fixes**:
- Reduce time limit for pilot
- Add early termination on good solution
- Partition large problems

---

### 3. Database Timeout

**Symptom**: `QueryCanceledError` or connection timeout

**Investigation**:
```sql
-- Check long-running queries
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY duration DESC
LIMIT 10;

-- Check locks
SELECT blocked_locks.pid AS blocked_pid,
       blocking_locks.pid AS blocking_pid,
       blocked_activity.query AS blocked_query
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
WHERE NOT blocked_locks.granted;
```

**Common Causes**:
- Missing index on filtered column
- Lock contention (concurrent solves)
- Large transaction holding locks

**Fixes**:
- Add missing indexes
- Use advisory locks for solve isolation
- Reduce transaction scope

---

### 4. OSRM Timeout

**Symptom**: Distance matrix computation hangs

**Investigation**:
```bash
# Test OSRM directly
curl -m 10 "http://osrm:5000/table/v1/driving/13.388860,52.517037;13.397634,52.529407"

# Check OSRM container
docker logs osrm --tail 100
```

**Common Causes**:
- OSRM service down
- Network issues
- Too many coordinates in single request

**Fixes**:
- Use StaticMatrix fallback
- Batch coordinate requests
- Add OSRM health check to startup

---

## TIMEOUT SETTINGS

### Recommended Values

| Component | Setting | Value | Config Location |
|-----------|---------|-------|-----------------|
| API | Request timeout | 120s | uvicorn/nginx |
| DB | Statement timeout | 30s | postgresql.conf |
| Solver | Time limit | 60s | solver_config |
| OSRM | Request timeout | 10s | routing client |
| Celery | Task timeout | 300s | celery.conf |

### Setting Database Timeout

```python
# Per-transaction
async with db.connection() as conn:
    await conn.execute("SET LOCAL statement_timeout = '30s'")
    # Query will be cancelled after 30s

# Globally
# In postgresql.conf:
# statement_timeout = 30000  # 30 seconds
```

### Setting Solver Timeout

```python
# OR-Tools time limit
solver.parameters.time_limit.seconds = 60

# Early termination on good solution
solver.parameters.solution_limit = 1  # Stop after first solution
```

---

## PREVENTION

### 1. Input Validation

```python
MAX_TOURS = 500
MAX_STOPS = 200

def validate_input(data):
    if len(data.tours) > MAX_TOURS:
        raise ValueError(f"Too many tours: {len(data.tours)} > {MAX_TOURS}")
    if len(data.stops) > MAX_STOPS:
        raise ValueError(f"Too many stops: {len(data.stops)} > {MAX_STOPS}")
```

### 2. Progress Reporting

```python
# For long operations, report progress
async def solve_with_progress(task_id: str, data):
    await update_status(task_id, "loading", 10)
    model = load_model(data)

    await update_status(task_id, "solving", 30)
    solution = solve(model)

    await update_status(task_id, "extracting", 80)
    result = extract(solution)

    await update_status(task_id, "complete", 100)
    return result
```

### 3. Circuit Breaker

```python
from circuitbreaker import circuit

@circuit(failure_threshold=3, recovery_timeout=60)
async def call_osrm(coordinates):
    return await osrm_client.get_matrix(coordinates)
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| System frozen, no response | S1 | Restart. Secure logs. Investigate. |
| Solver consistently >5min | S2 | Cancel jobs. Check input size. |
| DB queries timing out | S2 | Check locks. Add indexes. |
| OSRM unreachable | S2 | Fallback to StaticMatrix. |
| Occasional timeout (<5%) | S3 | Log and monitor. Schedule review. |
