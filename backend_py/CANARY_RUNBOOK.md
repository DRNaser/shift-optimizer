# ShiftOptimizer v2.0.0 — Canary Runbook

## Release Summary

- **Version**: 2.0.0
- **Tag**: `v2.0.0`
- **OR-Tools**: `9.11.4210` (pinned)
- **Tests**: 253 passed, 2 xfailed (TICKET-001)

---

## 1. Release Cut

### Git Tag + Build
```bash
git tag -a v2.0.0 -m "v2.0.0: Deterministic + budgeted + packability + fill-to-target + repair"
git push origin v2.0.0
```

### Smoke Test (prod-like environment)
Run identical input + seed twice:

```python
from src.services.portfolio_controller import run_portfolio
from src.services.forecast_solver_v4 import ConfigV4

config = ConfigV4(seed=42)
result1 = run_portfolio(tours, time_budget=30.0, seed=42, config=config)
result2 = run_portfolio(tours, time_budget=30.0, seed=42, config=config)

# Assertions
assert result1.run_report.solution_signature == result2.run_report.solution_signature  # Determinism
assert "BUDGET_OVERRUN" not in str(result1.run_report.reason_codes)  # Budget truth
```

---

## 2. Canary Stage 0: Flags OFF (Foundation Only)

### Goal
Verify Foundation/Determinism/Budget/Report have no side effects.

### Deployment
- **Traffic**: 5-10% or selected instances
- **Config**: Default (all new features OFF)

```python
config = ConfigV4()  # All new features OFF by default
```

### Watchlist
| Metric | Expected |
|--------|----------|
| Runtime | Stable (no increase) |
| `solution_signature` | Identical on repeated runs |
| Coverage | No drops |
| Validation | No new INVALID plans |

### Duration
24-48 hours or N=500 runs

---

## 3. Canary Stage 1: Features ON (Controlled)

### Goal
Test v2.0 features with real traffic.

### Deployment
- **Traffic**: 1-5% or specific regions/depots
- **Config**: Enable v2.0 features explicitly

```python
config = ConfigV4()._replace(
    enable_fill_to_target_greedy=True,
    enable_bad_block_mix_rerun=True,
)
```

### Watchlist
| Metric | Expected | Alert If |
|--------|----------|----------|
| `pt_ratio` | ↓ or stable | ↑ > 10% |
| `underfull_ratio` | ↓ or stable | ↑ > 10% |
| `time_phase1` | ≤ 50% of budget | > 55% |
| `time_phase2` | ≤ 15% of budget | > 20% |
| `time_lns` | ≤ 28% of budget | > 33% |
| `reason_codes` | No BUDGET_OVERRUN | Any BUDGET_OVERRUN |
| `solution_signature` | Stable on repeat | Flaps |

### Duration
24-72 hours or N=1000 runs

---

## 4. Ramp-up + Exit Criteria

### Roll Forward When (over 24-72h / N=1000):
- [ ] Zero BUDGET_OVERRUN in reason_codes
- [ ] Zero determinism regressions (signature stable)
- [ ] KPIs improved or neutral (`pt_ratio`, `underfull_ratio`)
- [ ] Zero new validation errors
- [ ] Coverage stable or improved

### Rollback When:
- [ ] Any BUDGET_OVERRUN appears
- [ ] Signature flaps on identical input+seed
- [ ] Coverage/validity regressions
- [ ] Runtime doubles or worse

### Rollback Command
```bash
# Revert to previous stable
kubectl rollout undo deployment/shift-optimizer
# OR feature flag disable
config = ConfigV4()  # All OFF
```

---

## 5. Post-Release Cleanup

### TICKET-001: Fix xfailed Tests
| Test | Issue | Fix |
|------|-------|-----|
| `test_daily_span_limit` | Expects 14.5, actual 15.5 | Align test or constraint |
| `test_driver_defaults` | Expects 14.5, actual 16.5 | Align model default |

### Optional: Grafana Dashboard
Panel for:
- `pt_ratio` over time
- `underfull_ratio` over time
- `time_phase*` histograms
- `reason_codes` counters
- `solution_signature` uniqueness (should be 1 per input)

---

## Quick Reference

### Enable All v2.0 Features
```python
config = ConfigV4()._replace(
    enable_fill_to_target_greedy=True,
    enable_bad_block_mix_rerun=True,
)
```

### Check Determinism
```python
sig1 = result1.run_report.solution_signature
sig2 = result2.run_report.solution_signature
assert sig1 == sig2, f"Determinism violation: {sig1} != {sig2}"
```

### Check Budget Compliance
```python
report = result.run_report
assert "BUDGET_OVERRUN" not in str(report.reason_codes)
assert report.time_phase1 <= budget * 0.55  # With 10% tolerance
```

---

## Contact

- **Owner**: Architecture Team
- **Escalation**: On-call SRE
- **Docs**: See `CHANGELOG.md`, `walkthrough.md`
