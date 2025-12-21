# Shift Optimizer - Operational Runbook

## Daily Validation Workflow

### Quick Health Check (60s - Gate 1)
```powershell
cd backend_py
python scripts/diagnostic_run.py --time_budget 60 --output_profile BEST_BALANCED
python scripts/validate_schedule.py diag_run_result.json
```

**Required Green KPIs (Gate 1 - Must Pass):**
| Metric | Expected |
|--------|----------|
| Coverage | 100% |
| Hard Violations | 0 |
| Zone Violations | 0 |
| Math Check | OK |



### Full Performance Run (120s - Gate 2)
```powershell
python scripts/diagnostic_run.py --time_budget 120 --output_profile BEST_BALANCED
python scripts/validate_schedule.py diag_run_result.json
```

**Required Green KPIs (Gate 2 - Performance):**
| Metric | Expected |
|--------|----------|
| twopass_executed | True |
| split_blocks_selected | > 0 |
| drivers_total | 160-180 |
| split_share | 3-30% |



## Troubleshooting

### If `twopass_executed=False` with 120s budget:
1. Check `pass1_time_s` - should be ~80s (not >100s)
2. Check server logs for Pass-2 start/stop messages
3. If budget exhausted in Pass-1: increase `time_budget` to 150s

### If `split_blocks_selected=0`:
1. Check `candidates_2er_split_pre_cap` - should be > 0
2. Check `candidates_2er_split_post_cap` - if 0, pruning killed splits
3. Increase `K_2ER_SPLIT_PER_TOUR` in smart_block_builder.py

### If Zone Violations > 0:
1. Check block ID prefixes - B2S- blocks must have gaps 240-360min
2. Check regular blocks - must have gaps 30-120min
3. Forbidden zone (121-239min) should never appear



## CI Regression Test Commands

```powershell
# Smoke Test (60s) - Gate 1 only
pytest tests/test_regression_best_balanced.py::TestSmokeGate1 -v

# Performance Test (120s) - Gate 2
pytest tests/test_regression_best_balanced.py::TestPerformanceGate2 -v

# Full Suite
pytest tests/test_regression_best_balanced.py -v
```



## Key Metrics Reference

| Metric | Non-Split Baseline | Split-Enabled Target |
|--------|-------------------|---------------------|
| drivers_total | ~187 | 160-180 |
| split_blocks | 0 | 40-80 |
| split_share | 0% | 5-15% |
| coverage | 100% | 100% |
| hard_violations | 0 | 0 |
