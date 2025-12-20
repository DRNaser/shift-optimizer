# Portfolio-Orchestration + Adaptive Parameter Policy

## Overview

The Portfolio Controller is a meta-orchestration layer for the Shift Optimizer that automatically selects the best solver path and parameters based on instance characteristics.

**Key Benefits:**
- 🎯 Automatic path selection (no manual tuning needed)
- ⚡ Early-stop when solution is good enough
- 🔄 Automatic fallback if primary path stagnates
- 📊 Full telemetry and run reports
- 🔁 Deterministic: same input = same output

---

## Quick Start

```python
from src.services.portfolio_controller import solve_forecast_portfolio

# Simple usage (recommended)
result = solve_forecast_portfolio(
    tours=my_tours,
    time_budget=30.0,  # seconds
    seed=42,
)

# Access results
print(f"Status: {result.status}")
print(f"Drivers: {result.kpi['drivers_fte']} FTE, {result.kpi['drivers_pt']} PT")
```

For full telemetry:

```python
from src.services.portfolio_controller import run_portfolio, generate_run_report

result = run_portfolio(tours, time_budget=60.0, seed=42)

# Access detailed metrics
print(f"Path used: {result.final_path.value}")
print(f"Gap to lower bound: {result.gap_to_lb * 100:.1f}%")
print(f"Fallback used: {result.fallback_used}")

# Generate JSON report
report = generate_run_report(result, tours, output_path="logs/run_report.json")
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Portfolio Controller                      │
│                                                              │
│  ┌──────────────┐    ┌───────────────┐    ┌─────────────┐  │
│  │   Instance   │───▶│    Policy     │───▶│   Solver    │  │
│  │   Profiler   │    │    Engine     │    │  Execution  │  │
│  └──────────────┘    └───────────────┘    └─────────────┘  │
│        │                     │                    │          │
│   Features             Path + Params         Result         │
│        │                     │                    │          │
│  ┌───────────────────────────────────────────────────────┐ │
│  │                    Early Stop / Fallback               │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Feature Glossary

| Feature | Type | Description |
|---------|------|-------------|
| `n_tours` | int | Total tours in forecast |
| `n_blocks` | int | Generated blocks after smart capping |
| `blocks_per_tour_avg` | float | Average blocks covering each tour |
| `peakiness_index` | float | 0-1, concentration of tours in peak hours |
| `rest_risk_proxy` | float | 0-1, late→early transition potential |
| `pt_pressure_proxy` | float | 0-1, peak demand vs capacity |
| `pool_pressure` | str | LOW/MEDIUM/HIGH based on block count |
| `daymin_*` | int | Lower bound drivers per day |
| `lower_bound_drivers` | int | Max of daily lower bounds |
| `coverage_density` | float | Avg blocks covering each tour |

---

## Path Selection Rules

### Path A: Fast Mode
- **When:** Normal instances (low peakiness, low pressure)
- **Strategy:** Greedy + Light LNS
- **Time allocation:** 20% Phase 1, 70% LNS, 10% buffer

### Path B: Balanced Mode
- **When:** Peaky instances OR high PT pressure OR high rest risk
- **Strategy:** Heuristic + Extended LNS
- **Triggers:**
  - `peakiness_index >= 0.35`
  - `pt_pressure_proxy >= 0.50`
  - `rest_risk_proxy >= 0.15`

### Path C: Heavy Mode
- **When:** Large block pools near capacity
- **Strategy:** Set-Partitioning + Fallback
- **Triggers:**
  - `pool_pressure == HIGH` (>80% of max_blocks)

---

## Reason Codes

| Code | Description |
|------|-------------|
| `NORMAL_INSTANCE` | Standard instance, fast path viable |
| `PEAKY_HIGH` | High peak concentration |
| `PEAKY_OR_PT_PRESSURE` | Peak demand exceeds capacity |
| `POOL_TOO_LARGE` | Block pool near limit |
| `REST_RISK_HIGH` | Many late→early transitions |
| `STAGNATION` | No improvement for k iterations |
| `GOOD_ENOUGH` | Score within ε of lower bound |
| `NEAR_DAYMIN` | Drivers at/near minimum |
| `FALLBACK_PATH_B` | Switched A → B |
| `FALLBACK_PATH_C` | Switched B → C |

---

## Early Stop Conditions

The solver stops early when:

1. **GOOD_ENOUGH:** `score <= (1 + epsilon) * lower_bound`
   - Default epsilon: 2%
   - Shorter budgets: 5%
   - Longer budgets: 1%

2. **NEAR_DAYMIN:** `drivers <= daymin + buffer`
   - Default buffer: 2 drivers
   - Large instances: 3 drivers
   - Small instances: 1 driver

---

## Fallback Logic

Fallback is triggered when:
- No improvement for `stagnation_iters` iterations (default: 20)
- Repair failure rate exceeds threshold (default: 30%)

Fallback order: **A → B → C**

When path C also fails, greedy fallback is used.

---

## Parameter Adaptation

Parameters are automatically tuned based on features:

| Parameter | Path A | Path B | Path C |
|-----------|--------|--------|--------|
| LNS iterations | 100 | 200-300 | 150 |
| Destroy fraction | 10% | 20% | 15% |
| Repair time limit | 3s | 5s | 4s |
| PT focus weight | 20% | 50% | 40% |
| SP enabled | ❌ | ❌ | ✅ |

---

## Run Report

The `run_report.json` contains:

```json
{
  "timestamp": "2024-01-15T10:30:00",
  "input_summary": {
    "n_tours": 450,
    "total_hours": 3600
  },
  "features": {
    "peakiness_index": 0.32,
    "pool_pressure": "MEDIUM",
    "lower_bound_drivers": 45
  },
  "policy_decisions": {
    "initial_path": "FAST",
    "final_path": "BALANCED",
    "reason_codes": ["NORMAL_INSTANCE", "STAGNATION", "FALLBACK_PATH_B"],
    "fallback_used": true
  },
  "result_summary": {
    "status": "OK",
    "drivers_fte": 48,
    "drivers_pt": 3,
    "gap_to_lb_pct": 6.67
  },
  "solve_times": {
    "profiling_s": 0.05,
    "phase1_s": 5.2,
    "phase2_s": 8.1,
    "lns_s": 12.4,
    "total_s": 25.8
  }
}
```

---

## Debugging Guide

### Problem: Solver takes Path C when A would work

Check these features:
- `pool_pressure`: Should be < HIGH (< 80% of max_blocks)
- Increase `max_blocks` in config if needed

### Problem: Too many fallbacks

Check these metrics:
- `stagnation_iters`: May need increase
- `repair_failure_threshold`: May be too sensitive

### Problem: Not hitting lower bound

Check:
- `lower_bound_drivers`: Is it realistic?
- `gap_to_lb_pct`: What's the gap?
- Consider increasing `time_budget`

### Problem: Non-deterministic results

Verify:
- `seed` is set consistently
- `num_workers=1` in config
- No parallel calls to run_portfolio

---

## Runbook: Weekly Forecast Processing

### 1. Prepare Forecast

```python
from src.domain.models import Tour, Weekday
from your_parser import parse_forecast_excel

tours = parse_forecast_excel("forecast_week_48.xlsx")
print(f"Loaded {len(tours)} tours")
```

### 2. Run Optimization

```python
from src.services.portfolio_controller import run_portfolio, generate_run_report

result = run_portfolio(
    tours=tours,
    time_budget=60.0,  # Give it a minute
    seed=42,
)

# Check quality
if result.gap_to_lb > 0.10:
    print(f"WARNING: Gap to LB is {result.gap_to_lb*100:.1f}% - consider more time")
```

### 3. Review Results

```python
# Generate report
report = generate_run_report(
    result, 
    tours, 
    output_path=f"logs/week48_report.json"
)

# Check KPIs
kpi = result.solution.kpi
print(f"Drivers: {kpi['drivers_fte']} FTE + {kpi['drivers_pt']} PT")
print(f"Path: {result.final_path.value}")
print(f"Fallbacks: {result.fallback_count}")
```

### 4. Export Assignments

```python
assignments = result.solution.assignments

for driver in assignments:
    print(f"{driver.driver_id} ({driver.driver_type}): {driver.total_hours:.1f}h")
    for block in driver.blocks:
        print(f"  {block.day.value}: {block.first_start}-{block.last_end}")
```

---

## Testing

Run the test suite:

```bash
cd backend_py
python -m pytest tests/test_instance_profiler.py tests/test_policy_engine.py tests/test_portfolio_controller.py -v
```

Test determinism:

```python
result1 = run_portfolio(tours, seed=42)
result2 = run_portfolio(tours, seed=42)
assert result1.achieved_score == result2.achieved_score
assert result1.final_path == result2.final_path
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2024-12-19 | Initial implementation |
