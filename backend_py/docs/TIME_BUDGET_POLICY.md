# Time Budget Policy

> **Version:** 2.0.1  
> **Applies to:** Shift Optimizer backend

---

## Budget Tiers

| Tier | Seconds | Use Case |
|------|---------|----------|
| **FAST** | 120s | Monitoring, smoke tests, quick previews |
| **QUALITY** | 180s | Default for production runs (recommended) |
| **PREMIUM** | 300s | Manual rerun for critical week planning |

---

## Default Configuration

```python
# In schemas.py → RunConfig
time_budget_seconds: float = Field(default=180.0, ...)
```

---

## Stop Criteria (Stagnation Detection)

Solver stops when:
1. `drivers_total` hasn't improved in last 20s
2. OR `coverage_rate` = 1.0 AND no objective improvement for 3 LNS rounds

**Primary metric:** `drivers_total` (minimize headcount)  
**Secondary:** `pt_ratio`, `underfull_ratio`

---

## When to Use Each Tier

### FAST (120s)
- Canary/baseline collection
- CI/CD smoke tests
- Quick feasibility check

### QUALITY (180s) ⭐ Default
- Normal production runs
- Weekly planning
- Best effort within operational SLA

### PREMIUM (300s)
- Manual "reoptimize" button
- Critical high-stakes weeks
- When QUALITY didn't reach target

---

## Adaptive Extension (Future)

```
1. Run with 120s
2. If LNS still improving → extend to 180s
3. If still improving after 180s → extend to 300s
4. Stop when stagnation detected
```

---

## Expected Results (1385 tours)

| Tier | Avg Runtime | drivers_total |
|------|-------------|---------------|
| FAST | ~85s | ~165 |
| QUALITY | ~180s | ~160 |
| PREMIUM | ~280s | ~158 |

(Values are estimates - actual results vary by instance)
