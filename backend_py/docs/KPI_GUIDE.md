# KPI Guide - Shift Optimizer v2.0

## Overview

This guide explains how to interpret the Key Performance Indicators (KPIs) produced by the Shift Optimizer solver.

---

## Core KPIs

### `drivers_fte` / `drivers_pt` / `drivers_total`

**Definition:**
- `drivers_fte`: Number of Full-Time Equivalent drivers (≥42h/week)
- `drivers_pt`: Number of Part-Time drivers (<42h/week)
- `drivers_total`: Sum of FTE and PT drivers

**Interpretation:**
- Lower total = better efficiency
- Goal: Minimize total while covering all tours

**Target Values:**
- Depends on tour volume, typically 130-160 for ~450 tours/week

---

### `pt_ratio`

**Definition:**
```
pt_ratio = drivers_pt / drivers_total
```

**Interpretation:**
- Lower = better (fewer part-timers needed)
- High ratio indicates peak demand exceeds FTE capacity

**Target Values:**
- Excellent: < 0.10 (< 10% PT)
- Good: 0.10 - 0.20
- Warning: > 0.25 (triggers BAD_BLOCK_MIX rerun if enabled)

**Dashboard Formula (Grafana):**
```promql
histogram_quantile(0.5, sum by (le) (rate(solver_pt_ratio_bucket[30m])))
```

---

### `underfull_ratio`

**Definition:**
```
underfull_ratio = (FTE drivers with hours < min_hours) / (total FTE drivers)
```

**Interpretation:**
- Lower = better (FTEs are well-utilized)
- High ratio means FTEs are under-assigned

**Target Values:**
- Excellent: < 0.05 (< 5% underfull)
- Good: 0.05 - 0.15
- Warning: > 0.15 (triggers BAD_BLOCK_MIX rerun if enabled)

---

### `coverage_rate`

**Definition:**
```
coverage_rate = tours_assigned / tours_total
```

**Interpretation:**
- 1.0 = all tours covered
- < 1.0 = some tours unassigned (check `reason_codes`)

**Target Values:**
- Required: 1.0 (100% coverage)
- Any value < 1.0 requires investigation

---

## Block Mix KPIs

### `blocks_1er` / `blocks_2er` / `blocks_3er`

**Definition:**
- `blocks_1er`: Single-tour blocks (least efficient)
- `blocks_2er`: Double-tour blocks (good)
- `blocks_3er`: Triple-tour blocks (most efficient)

**Interpretation:**
- More 2er/3er = fewer drivers needed
- 1er blocks should be minimized

**Target Mix:**
- 1er: < 20% of total blocks
- 2er: ~50-60%
- 3er: ~20-30%

---

### `forced_1er_rate`

**Definition:**
```
forced_1er_rate = (tours with ONLY 1er options in pool) / total_tours
```

**Interpretation:**
- High rate = structural constraint (tours can't combine)
- Look at timing/gap constraints if high

**Target Values:**
- Good: < 0.10 (< 10% forced single)

---

### `missed_3er_opps`

**Definition:**
Count of tours that were assigned to 1er blocks despite having 3er options available.

**Interpretation:**
- Non-zero = optimizer skipped better options
- May indicate cost function tuning needed

**Target Values:**
- Ideal: 0

---

## Timing KPIs

### `time_phase1` / `time_phase2` / `time_lns`

**Definition:**
Time spent in each solver phase (seconds).

**Budget Slices (default):**
- Phase 1 (Block Selection): 50% of budget
- Phase 2 (Assignment): 15% of budget
- LNS (Refinement): 28% of budget
- Buffer: 5%

**Warning Signs:**
- Any phase exceeding its slice = `BUDGET_OVERRUN`
- Total time > time_budget = hard failure

---

## Reason Codes

### Healthy Codes

| Code | Meaning |
|------|---------|
| `NORMAL_INSTANCE` | Standard instance, fast path used |
| `OPTIMAL_FOUND` | Solver found optimal solution |
| `FEASIBLE_SOLUTION` | Valid solution found |
| `GOOD_ENOUGH` | Solution within ε of lower bound |

### Warning Codes

| Code | Meaning | Action |
|------|---------|--------|
| `PEAKY_HIGH` | High peak concentration | Path B activated |
| `FALLBACK_PATH_B` | Switched A → B | Monitor PT ratio |
| `FALLBACK_PATH_C` | Switched B → C | Check block pool size |
| `STAGNATION` | No improvement for k iterations | May need more time |

### Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| `BUDGET_OVERRUN` | Exceeded time budget | **Investigate immediately** |
| `INFEASIBLE` | No valid solution | Check constraints |

---

## Prometheus Metric Names

| KPI | Prometheus Metric |
|-----|-------------------|
| `drivers_fte` | `solver_driver_count{driver_type="fte"}` |
| `drivers_pt` | `solver_driver_count{driver_type="pt"}` |
| `pt_ratio` | `solver_pt_ratio` |
| `underfull_ratio` | `solver_underfull_ratio` |
| `coverage_rate` | `solver_coverage_rate` |
| Phase timing | `solver_phase_duration_seconds{phase="..."}` |
| Path selection | `solver_path_selection_total{path="...",reason="..."}` |
| Budget overrun | `solver_budget_overrun_total` |
| Signature uniqueness | `solver_signature_runs_total` / `solver_signature_unique_total` |
| Block Starvation | `solver_candidates_kept_total{size="..."}` / `solver_candidates_raw_total{size="..."}` |

---

## Grafana Dashboard Queries

### Starvation Alert (True Positive)
*Stable alert using `increase` over 30m window:*

```promql
sum(increase(solver_candidates_raw_total{size="2er"}[30m])) > 0
and
sum(increase(solver_candidates_kept_total{size="2er"}[30m])) == 0
```

*Sustained Starvation Alert (Low False Positive Reference):*

```promql
sum(increase(solver_candidates_raw_total{size="2er"}[2h])) > 100
and
sum(increase(solver_candidates_kept_total{size="2er"}[2h])) == 0
```

### PT Ratio Over Time (Median)
```promql
histogram_quantile(0.5, sum by (le) (rate(solver_pt_ratio_bucket[5m])))
```

### Budget Overrun Rate (per Run)
```promql
increase(solver_budget_overrun_total{phase="total"}[30m]) /
clamp_min(increase(solver_signature_runs_total[30m]), 1)
```

### Phase Duration P95
```promql
histogram_quantile(0.95, sum by (le) (rate(solver_phase_duration_seconds_bucket{phase="phase1"}[5m])))
```

### Signature Uniqueness (LRU)
```promql
increase(solver_signature_unique_total[1h]) / clamp_min(increase(solver_signature_runs_total[1h]), 1)
```
