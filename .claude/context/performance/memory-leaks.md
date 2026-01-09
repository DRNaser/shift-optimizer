# Memory Leak Detection

> **Purpose**: Identify and fix memory leaks
> **Last Updated**: 2026-01-07

---

## SYMPTOMS

- RSS (Resident Set Size) grows over time
- OOM (Out of Memory) kills in production
- Gradual performance degradation
- GC pauses increasing

---

## QUICK DIAGNOSIS

### Check Current Memory Usage

```bash
# Process memory
ps aux | grep python | awk '{print $4, $11}'

# Docker container memory
docker stats --no-stream

# Detailed memory breakdown
cat /proc/<PID>/status | grep -E "(VmRSS|VmSize|VmPeak)"
```

### Python Memory Tracking

```python
import tracemalloc

tracemalloc.start()

# ... run operations ...

snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')

print("Top 10 memory allocations:")
for stat in top_stats[:10]:
    print(stat)
```

---

## COMMON LEAK PATTERNS

### 1. Unclosed Database Connections

**Symptom**: Connection pool exhausted, memory grows

**Detection**:
```python
# Check connection count
async with db.pool.connection() as conn:
    result = await conn.fetchone(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = 'solvereign'"
    )
    print(f"Active connections: {result['count']}")
```

**Fix**:
```python
# WRONG - connection not returned to pool
conn = await db.pool.getconn()
# ... use conn ...
# Missing: await db.pool.putconn(conn)

# CORRECT - use context manager
async with db.pool.connection() as conn:
    # ... use conn ...
    # Automatically returned to pool
```

---

### 2. Growing Caches Without Bounds

**Symptom**: Memory grows linearly with requests

**Detection**:
```python
import sys

print(f"Cache size: {sys.getsizeof(my_cache)}")
print(f"Cache entries: {len(my_cache)}")
```

**Fix**:
```python
from functools import lru_cache
from cachetools import TTLCache

# Bounded LRU cache
@lru_cache(maxsize=1000)
def expensive_computation(key):
    return compute(key)

# Time-based expiry
cache = TTLCache(maxsize=1000, ttl=3600)  # 1 hour TTL
```

---

### 3. Circular References

**Symptom**: Objects not garbage collected

**Detection**:
```python
import gc

gc.collect()
print(f"Uncollectable: {gc.garbage}")
```

**Fix**:
```python
import weakref

# WRONG - circular reference
class Parent:
    def __init__(self):
        self.child = Child(self)

class Child:
    def __init__(self, parent):
        self.parent = parent  # Strong reference creates cycle

# CORRECT - use weakref
class Child:
    def __init__(self, parent):
        self.parent = weakref.ref(parent)  # Weak reference
```

---

### 4. Large Objects Not Released

**Symptom**: Memory spike during processing, never returns

**Detection**:
```python
import tracemalloc

tracemalloc.start()
process_large_data()
current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current/1024/1024:.1f}MB, Peak: {peak/1024/1024:.1f}MB")
```

**Fix**:
```python
# WRONG - keeps entire dataset in memory
def process_all():
    data = load_entire_dataset()  # 2GB
    results = process(data)
    return results  # data still in memory during return

# CORRECT - process in chunks
def process_all():
    results = []
    for chunk in load_dataset_chunks(size=10000):
        result = process(chunk)
        results.append(result)
        del chunk  # Explicitly free
    return results
```

---

### 5. Logging Large Objects

**Symptom**: Memory grows with log activity

**Detection**:
```python
import logging
logger = logging.getLogger()
for handler in logger.handlers:
    print(f"Handler buffer: {type(handler)}, {sys.getsizeof(handler)}")
```

**Fix**:
```python
# WRONG - logging full object
logger.debug(f"Full data: {large_object}")

# CORRECT - log summary only
logger.debug(f"Data summary: count={len(large_object)}, first={large_object[0]}")
```

---

## PROFILING TOOLS

### objgraph - Object Graph Visualization

```python
import objgraph

# Most common types
objgraph.show_most_common_types(limit=10)

# Growth since last check
objgraph.show_growth()

# Find what's holding a reference
objgraph.show_backrefs(my_object, filename='refs.png')
```

### memory_profiler - Line-by-Line

```python
from memory_profiler import profile

@profile
def process_data():
    data = load_data()      # Line memory usage
    result = transform(data)
    save(result)
    return result
```

### guppy3 - Heap Analysis

```python
from guppy import hpy
h = hpy()

print(h.heap())
# Partition by type, size, etc.
```

---

## MEMORY LIMITS

### Set Pod Limits (Kubernetes)

```yaml
resources:
  limits:
    memory: "4Gi"
  requests:
    memory: "2Gi"
```

### Set Python Limits

```python
import resource

# Limit to 4GB
resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
```

---

## PREVENTION CHECKLIST

- [ ] All DB connections use context managers
- [ ] Caches have maxsize or TTL
- [ ] Large objects processed in chunks
- [ ] No circular references (or use weakref)
- [ ] Logging doesn't include full objects
- [ ] Background tasks clean up after completion
- [ ] File handles closed after use

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| OOM kill in production | S1 | Restart. Capture heap dump. Investigate. |
| RSS > 2x baseline | S2 | Profile immediately. Block deploy. |
| Slow memory growth | S3 | Schedule investigation. Monitor trend. |
| Connection pool exhausted | S2 | Check for connection leaks. Restart. |
