# Production Alerts: Shift Optimizer

> **Baseline:** Stage 0 (405 runs) / Stage 1 (170 runs)  
> **Commit:** `571699f`

---

## STOP Criteria (Immediate Action Required)

### 1. True Starvation (2-Tour Blocks)

**Alert Name:** `ShiftOptimizer_2er_Starvation`

```promql
sum(increase(solver_candidates_raw_total{size="2er"}[30m])) > 0
and
sum(increase(solver_candidates_kept_total{size="2er"}[30m])) == 0
```

**Severity:** CRITICAL  
**Action:** Stop workload immediately. Check block generation logic.

---

### 2. Infeasible Rate Regression

**Alert Name:** `ShiftOptimizer_Infeasible_Regression`

```promql
increase(solver_infeasible_total[60m])
/
clamp_min(increase(solver_signature_runs_total[60m]), 1)
> 0.05
```

**Threshold:** > 5% infeasible rate (baseline was 0%)  
**Severity:** CRITICAL  
**Action:** Investigate solver constraints. Rollback if regression.

---

### 3. CRITICAL Portfolio Error

**Alert Name:** `ShiftOptimizer_Critical_Error`

```promql
increase(solver_critical_error_total[30m]) > 0
```

**Severity:** CRITICAL  
**Action:** Check logs for exception details. Likely code bug.

---

## WARN Criteria (Monitor Closely)

### 4. Runtime P95 Regression

**Alert Name:** `ShiftOptimizer_Runtime_P95_High`

```promql
histogram_quantile(0.95,
  sum by (le) (rate(solver_phase_duration_seconds_bucket{phase="total"}[10m]))
) > 120
```

**Threshold:** > 120s (2 minutes)  
**Severity:** WARNING  
**Action:** Monitor. May indicate larger instances or solver degradation.

---

### 5. Budget Overrun (Informational)

**Note:** Budget overrun is a SOFT limit. Do NOT use as STOP criteria.

```promql
increase(solver_budget_overrun_total{phase="total"}[60m])
/
clamp_min(increase(solver_signature_runs_total[60m]), 1)
```

**Expected:** ~100% (solver typically exceeds soft budget)  
**Severity:** INFO only  
**Action:** None required unless combined with other issues.

---

## Alert Implementation Notes

1. **Use `increase()` not `rate()`** - Counters reset on restart. `increase()` handles this correctly.

2. **Window sizes:**
   - Starvation: 30m (fast detection)
   - Infeasible/Overrun: 60m (avoid noise)
   - Runtime P95: 10m (responsive)

3. **Baseline reference:**
   - Stage 0: 405 runs, 0% infeasible, no starvation
   - Stage 1: 170 runs, 0% infeasible, no starvation

---

## Grafana Alert Rules (JSON)

Import to Grafana via **Alerting → Alert Rules → Import**.

```json
{
  "name": "True Starvation (2er)",
  "condition": "A",
  "data": [
    {
      "refId": "A",
      "queryType": "",
      "relativeTimeRange": {"from": 1800, "to": 0},
      "model": {
        "expr": "sum(increase(solver_candidates_raw_total{size=\"2er\"}[30m])) > 0 and sum(increase(solver_candidates_kept_total{size=\"2er\"}[30m])) == 0",
        "intervalMs": 1000,
        "maxDataPoints": 43200,
        "refId": "A"
      }
    }
  ],
  "for": "5m",
  "labels": {"severity": "critical"}
}
```
