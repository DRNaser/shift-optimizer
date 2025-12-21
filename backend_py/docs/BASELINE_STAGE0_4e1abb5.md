# Stage 0 Baseline: `4e1abb5`

> **Exported:** 2025-12-21T11:57:03  
> **Duration:** ~4 hours (after backend restart)

## Build Info

| Key | Value |
|-----|-------|
| `git_commit` | `4e1abb5` |
| `app_version` | `2.0.0` |
| `ortools_version` | `9.11.4210` |
| Stage | **0 (Flags OFF)** |
| `cap_quota_2er` | NOT ACTIVE |

---

## KPIs

| Metric | Value | Notes |
|--------|-------|-------|
| **A) Run Count** | 405 | Target was N≥500 |
| **B) Budget Overrun Rate** | 99.75% (404/405) | ⚠️ HIGH - investigate |
| **C) Infeasible Rate** | 0.00% (0/405) | ✅ PASS |

---

## D) Starvation Check (2-Tour Blocks)

| Metric | Value |
|--------|-------|
| `kept_2er` | 2,261,520 |
| `kept_1er` | 560,925 |
| `kept_3er` | 5,277,555 |

**Result:** `kept_2er > 0` → **NO STARVATION** ✅

---

## E) Path Selection

| Path | Count |
|------|-------|
| FAST | 0 |
| FULL | 0 |
| FALLBACK | 0 |

> Note: Path selection metrics may not be recording correctly (all zeros).

---

## F) Performance (P95 Total)

> To be measured via Grafana histogram query.

---

## Observations

1. **Budget Overrun Rate is 99.75%** - Almost all runs exceed budget. This is expected if `time_budget=60s` but actual solver runtime is ~85s. The "overrun" is measuring total time including all phases.

2. **Infeasible Rate = 0%** - Excellent. No solver failures.

3. **No 2-Tour Starvation** - Block capping is working correctly.

4. **Path metrics show 0** - The `solver_path_selection_total` metric may not be instrumented in all code paths.

---

## Stage 1 Comparison Queries

Use these exact queries with the same time range for Stage 1:

```promql
# Run Count
increase(solver_signature_runs_total[$__range])

# Overrun Rate
increase(solver_budget_overrun_total{phase="total"}[$__range]) /
clamp_min(increase(solver_signature_runs_total[$__range]), 1)

# Infeasible Rate
increase(solver_infeasible_total[$__range]) /
clamp_min(increase(solver_signature_runs_total[$__range]), 1)

# 2er Kept
sum(increase(solver_candidates_kept_total{size="2er"}[$__range]))
```
