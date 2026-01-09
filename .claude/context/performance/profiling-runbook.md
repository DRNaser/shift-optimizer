# Profiling Runbook

> **Purpose**: Performance profiling procedures and tools
> **Last Updated**: 2026-01-07

---

## WHEN TO PROFILE

- API p95 > 120ms (baseline: 80ms)
- Solver p95 > 45s (baseline: 30s)
- Memory usage trending up
- Before major release
- After performance regression reported

---

## PROFILING TOOLS

### 1. Python cProfile (CPU)

```python
import cProfile
import pstats
from io import StringIO

def profile_function():
    pr = cProfile.Profile()
    pr.enable()

    # Code to profile
    result = expensive_operation()

    pr.disable()

    # Print stats
    s = StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(20)  # Top 20 functions
    print(s.getvalue())

    return result
```

### 2. py-spy (Live Profiling)

```bash
# Install
pip install py-spy

# Profile running process
py-spy top --pid <PID>

# Generate flame graph
py-spy record -o profile.svg --pid <PID> --duration 60
```

### 3. memory_profiler (Memory)

```python
from memory_profiler import profile

@profile
def memory_intensive_function():
    data = load_large_dataset()
    process(data)
    return summarize(data)
```

### 4. tracemalloc (Memory Tracking)

```python
import tracemalloc

tracemalloc.start()

# Run code
result = operation()

# Get stats
current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current / 1024 / 1024:.1f}MB")
print(f"Peak: {peak / 1024 / 1024:.1f}MB")

# Top allocations
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)

tracemalloc.stop()
```

---

## API PROFILING

### Enable Request Timing

```python
# Middleware for timing
@app.middleware("http")
async def add_timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    response.headers["X-Response-Time"] = f"{duration:.3f}s"
    return response
```

### Slow Query Detection

```python
# Log slow queries
import logging

async def log_slow_queries(query: str, duration: float):
    if duration > 0.1:  # 100ms threshold
        logging.warning(f"Slow query ({duration:.3f}s): {query[:100]}")
```

### curl Timing

```bash
# Create format file
cat > curl-format.txt << 'EOF'
     time_namelookup:  %{time_namelookup}s\n
        time_connect:  %{time_connect}s\n
     time_appconnect:  %{time_appconnect}s\n
    time_pretransfer:  %{time_pretransfer}s\n
       time_redirect:  %{time_redirect}s\n
  time_starttransfer:  %{time_starttransfer}s\n
                     ----------\n
          time_total:  %{time_total}s\n
EOF

# Use with curl
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/health/ready
```

---

## SOLVER PROFILING

### Time Individual Phases

```python
import time

def solve_with_timing(forecast_id: int, seed: int):
    timings = {}

    t0 = time.perf_counter()
    data = load_forecast(forecast_id)
    timings['load'] = time.perf_counter() - t0

    t0 = time.perf_counter()
    model = build_model(data)
    timings['build'] = time.perf_counter() - t0

    t0 = time.perf_counter()
    solution = solver.solve(model, seed=seed)
    timings['solve'] = time.perf_counter() - t0

    t0 = time.perf_counter()
    result = extract_result(solution)
    timings['extract'] = time.perf_counter() - t0

    print(f"Timings: {timings}")
    return result
```

### OR-Tools Statistics

```python
from ortools.constraint_solver import pywrapcp

# After solving
print(f"Branches: {solver.Branches()}")
print(f"Failures: {solver.Failures()}")
print(f"Wall time: {solver.WallTime()}ms")
print(f"Solutions: {solver.Solutions()}")
```

---

## DATABASE PROFILING

### Enable Query Logging (PostgreSQL)

```sql
-- In postgresql.conf
log_min_duration_statement = 100  -- Log queries > 100ms

-- Or per-session
SET log_min_duration_statement = 100;
```

### EXPLAIN ANALYZE

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM large_table WHERE tenant_id = '...' AND created_at > '2026-01-01';
```

### Check Missing Indexes

```sql
-- Tables with sequential scans
SELECT schemaname, relname, seq_scan, seq_tup_read,
       idx_scan, idx_tup_fetch
FROM pg_stat_user_tables
WHERE seq_scan > 0
ORDER BY seq_tup_read DESC
LIMIT 10;
```

---

## PROFILING WORKFLOW

### 1. Baseline

```bash
# Record current performance
python -m backend_py.tools.perf_baseline record

# View baselines
cat .claude/state/drift-baselines.json
```

### 2. Reproduce Issue

```bash
# Run specific scenario
python -m backend_py.v3.solver_wrapper \
    --forecast-id 1 \
    --seed 94 \
    --profile
```

### 3. Identify Bottleneck

- CPU-bound? → cProfile / py-spy
- Memory-bound? → tracemalloc / memory_profiler
- I/O-bound? → Database query analysis
- Network-bound? → curl timing / OSRM latency

### 4. Fix and Verify

```bash
# Run before/after comparison
python -m backend_py.tools.perf_compare --before baseline.json --after current.json
```

---

## COMMON BOTTLENECKS

| Symptom | Likely Cause | Investigation |
|---------|--------------|---------------|
| High CPU, low I/O | Algorithm inefficiency | cProfile |
| Growing memory | Memory leak | tracemalloc |
| High p95, low p50 | GC pauses or locks | py-spy live |
| Slow first request | Cold start | Check lazy loading |
| Slow all requests | DB or external service | Query timing |

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| p95 > 3x baseline | S2 | Block release. Profile and fix. |
| Memory growing unbounded | S2 | Identify leak. Fix before OOM. |
| Solver timeout frequent | S2 | Check input size. Tune parameters. |
| Gradual degradation | S3 | Schedule investigation. Monitor. |
