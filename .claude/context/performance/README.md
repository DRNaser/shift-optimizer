# Performance Branch - Router Checklist

> **Purpose**: Timeouts, memory issues, capacity planning, and profiling
> **Severity Default**: S2 (HIGH) - Investigate before continuing

---

## ENTRY CHECKLIST

Before proceeding, answer these questions:

1. **Is the system frozen/unresponsive?**
   - YES → Read `timeout-playbook.md` IMMEDIATELY
   - NO → Continue

2. **Is memory usage abnormal (OOM, high RSS)?**
   - YES → Read `memory-leaks.md`
   - NO → Continue

3. **Is solver taking too long (>60s for typical load)?**
   - YES → Read `timeout-playbook.md`
   - NO → Continue

4. **Are API response times degraded (p95 > baseline)?**
   - YES → Read `profiling-runbook.md`
   - NO → Continue

5. **Planning capacity for new tenant/load?**
   - YES → Read `capacity-planning.md`
   - NO → Use general performance guidance below

---

## FILES IN THIS BRANCH

| File | Purpose | When to Read |
|------|---------|--------------|
| `timeout-playbook.md` | Solver/API timeout diagnosis and fixes | Timeouts, freezes, slow responses |
| `memory-leaks.md` | Memory debugging and leak detection | High RSS, OOM errors, gradual degradation |
| `profiling-runbook.md` | Performance profiling procedures | Identifying bottlenecks |
| `capacity-planning.md` | Load testing and capacity estimation | New tenant onboarding, scaling |

---

## QUICK DIAGNOSTICS

### Check Current Baselines
```bash
cat .claude/state/drift-baselines.json
# Expected: api_p95_ms, solver_p95_s, solver_peak_rss_mb
```

### Memory Check (Python)
```python
import tracemalloc
tracemalloc.start()
# ... run operation ...
current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current / 1024 / 1024:.1f}MB, Peak: {peak / 1024 / 1024:.1f}MB")
```

### API Response Time
```bash
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/health/ready
```

### Solver Timing
```bash
time python -m backend_py.v3.solver_wrapper --forecast-id 1 --seed 94
```

---

## PERFORMANCE BASELINES

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| API p95 | <120ms | 120-500ms | >500ms |
| Solver p95 | <45s | 45-120s | >120s |
| Peak RSS | <2GB | 2-4GB | >4GB |
| Pool connections | <80% | 80-95% | >95% |

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| System frozen | S1 | STOP-THE-LINE. Restart pods. Secure logs. |
| OOM kill | S1 | Capture heap dump. Scale up immediately. |
| Solver timeout (>5min) | S2 | Cancel job. Check input size. |
| API p95 > 500ms | S2 | Enable profiling. Check DB connections. |
| Gradual memory growth | S3 | Schedule investigation. Monitor trend. |
| 10% slower than baseline | S4 | Log for review. Check after next deploy. |

---

## RELATED BRANCHES

- Is this an incident? → `stability/incident-triage.md`
- Security causing slowdown? → `security/auth-flows.md`
- Need to deploy fix? → `operations/deployment-checklist.md`
