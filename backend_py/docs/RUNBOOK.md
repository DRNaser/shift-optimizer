# Shift Optimizer - Operational Runbook

**Release Candidate: v2.0.0-rc0**  
**Schema Version: 2.0**

> [!IMPORTANT]
> **Architektur-Referenz**: Für tiefgreifende technische Details siehe [System Dokumentation](file:///.gemini/antigravity/brain/system_documentation.md) - die Source of Truth für Code-Strukturen, Module-Inventar, Constraint-Enforcement und Debug-Flows.

---

## Prerequisites

> [!IMPORTANT]
> All diagnostic runs and verification scripts require the API server to be running.

**Start API Server (Terminal 1):**
```powershell
cd backend_py
# Default port 8000 (or use 8010 for RC0 verification)
uvicorn src.main:app --host 0.0.0.0 --port 8010
```

**Port Configuration:**
- Default: `8000`
- RC0 Verification: `8010` (recommended to avoid conflicts)
- Override via environment: `$env:API_PORT="8010"`

Keep this terminal open while running tests.

---

## Schema Contract (v2.0)

| Field | Location | Requirement |
|-------|----------|-------------|
| `schema_version` | WeeklyPlan (top-level) | Always `"2.0"` |
| `pause_zone` | Block | Enum: `"REGULAR"` or `"SPLIT"` only |

**Backward Compatibility:** Old JSONs without `pause_zone` are normalized via:
1. `is_split=true` → `SPLIT`
2. Block ID starts with `B2S-` → `SPLIT`
3. Otherwise → `REGULAR`

---

## Two-Pass Policy (QUALITY-FIRST)

### Definition
### Definition (Quality Unbounded)
- **Pass-1 (dynamic):** Minimize headcount via capacity solver. Runs until OPTIMAL or Stagnation.
- **Pass-2 (guaranteed):** Optimize balance. Runs until OPTIMAL or Stagnation.
- **Constraint:** Time is a resource, not a limit. Process runs until output is stable.

### `twopass_executed` Definition (Contract)

`twopass_executed=True` means ALL of the following:
1. Pass-1 completed with feasible solution
2. Pass-2 was started (solver call initiated)
3. Pass-2 returned a valid solution

### QUALITY-FIRST Guarantee

> [!IMPORTANT]
> In QUALITY mode, Pass-2 is **guaranteed** a minimum runtime (`pass2_min_time_s`).
> Pass-1 budget is dynamically reduced if needed to ensure Pass-2 always runs.

| Parameter | Default | QUALITY Mode |
|-----------|---------|--------------|
| `pass2_min_time_s` | 15s | 30s |
| `total_time_budget` | 120s | 300s |
| Budget split | ~65/35 | Adaptive |

### Budget Allocation

### Budget Allocation & Stop Criteria (Quality First)

| Profile | Mode | Stop Criteria | Pass-2 Guarantee |
|---------|------|---------------|------------------|
| Smoke | CI (Timed) | CI Timeout (e.g. 60s) | Optional |
| Performance | CI (Timed) | CI Timeout (e.g. 120s) | Best Effort |
| **QUALITY** | **Release** | **OPTIMAL / LB / Stagnation** | **Guaranteed (≥30s)** |

> [!NOTE]
> RELEASE/RC runs are "unbounded". Time budgets in scripts (e.g. 3600s) serve as a high resource window to allow convergence, not a hard stop. The solver should stop early if OPTIMAL is proven.

---

## Daily Validation Workflow

### Quick Health Check (60s - Gate 1)
```powershell
cd backend_py
python scripts/diagnostic_run.py --time_budget 60 --output_profile BEST_BALANCED
python scripts/validate_schedule.py diag_run_result.json
```

**Required KPIs (Gate 1 - Smoke):**
| Metric | Expected |
|--------|----------|
| Coverage | 100% |
| Hard Violations | 0 |
| Zone Violations | 0 |
| `schema_version` | "2.0" |



### Full Performance Run (120s - Gate 2)
```powershell
python scripts/diagnostic_run.py --time_budget 120 --output_profile BEST_BALANCED
python scripts/validate_schedule.py diag_run_result.json
```

**Required KPIs (Gate 2 - Performance):**
| Metric | Expected |
|--------|----------|
| twopass_executed | True |
| split_blocks | > 0 |
| drivers_total | 155-185 |



### QUALITY Run (Unbounded - RC Releases)
```powershell
# Standard Quality Verification (Unbounded, Strict Contract)
$env:API_PORT="8010"; python scripts/verify_rc0.py
```

**Quality Stop Criteria:**
1. **OPTIMAL:** Solver proves global optimum.
2. **LB Reached:** Drivers = Lower Bound (Theoretical Minimum).
3. **Stagnation:** No objective improvement for N iterations.

**Required KPIs (QUALITY Gate):**
| Metric | Expected |
|--------|----------|
| twopass_executed | **True (guaranteed)** |
| split_blocks | > 0 |
| drivers_total | **Minimal (155-175)** |
| pass2_time_s | ≥ 30s |

---

## Troubleshooting

### If `twopass_executed=False`:
1. Check total budget - should be ≥60s for Pass-2 to run
2. Check `pass1_time_s` - should leave ≥`pass2_min_time_s` remaining
3. Use QUALITY mode (`verify_rc0.py`) for guaranteed Pass-2
4. Verify seed=42 is set (determinism)

### If `split_blocks=0`:
1. Check `candidates_2er_split_pre_cap` - should be > 0
2. Check `candidates_2er_split_post_cap` - if 0, pruning killed splits
3. Increase `K_2ER_SPLIT_PER_TOUR` in smart_block_builder.py

### If Zone Violations > 0:
1. B2S- blocks must have gaps 240-360min (SPLIT)
2. Regular blocks must have gaps 30-120min
3. Forbidden zone (121-239min) should never appear

---

## Port Troubleshooting

### Port Already in Use/Conflicts
```powershell
# Check usage
netstat -ano | findstr :8010

# Kill process by PID
Stop-Process -Id <PID> -Force
```

### Choosing a Different Port
```powershell
# 1. Start server on custom port
uvicorn src.main:app --host 0.0.0.0 --port 9000

# 2. Run verification against custom port
$env:API_PORT="9000"; python scripts/verify_rc0.py
```

### Zombie Process Detection
```powershell
# Check if port shows LISTENING but server is unresponsive
netstat -ano | findstr :8000
# If PID exists but server doesn't respond, kill and restart
```

---

## Response Contract Check

### Key Verification (Quick Check)

**Top-Level Response must contain:**
```json
{
  "schema_version": "2.0",
  "version": "4.0",
  "solver_type": "portfolio_v4"
}
```

**Block-Level must contain:**
```json
{
  "pause_zone": "REGULAR" | "SPLIT"
}
```

### Manual Verification
```powershell
# Quick contract check via PowerShell
$plan = Invoke-RestMethod -Uri "http://localhost:8010/api/v1/runs/<run_id>/plan"
Write-Host "schema_version: $($plan.schema_version)"
Write-Host "pause_zone: $($plan.assignments[0].block.pause_zone)"
```

**Expected Output:**
- `schema_version: 2.0`
- `pause_zone: REGULAR` or `SPLIT`

---

## CI Regression Test Commands

```powershell
# Gate 1 - Smoke (Merge Blocker, ~90s)
pytest tests/test_regression_best_balanced.py -m smoke -v

# Gate 2 - Performance (Nightly, ~150s)
pytest tests/test_regression_best_balanced.py -m performance -v

# Contract Tests (Fast, ~5s)
pytest tests/test_contract_schema.py -v

# QUALITY Gate (RC Releases, ~5min)
python scripts/verify_rc0.py

# Full Suite
pytest tests/ -v
```

### Gate Summary
| Gate | Budget | CI Runtime | twopass_executed |
|------|--------|------------|------------------|
| Smoke | 60s | ~90s | Optional |
| Performance | 120s | ~150s | Should be True |
| **QUALITY** | 300s | ~6min | **Guaranteed True** |
| Contract | N/A | <5s | N/A |

---

## Key Metrics Reference

| Metric | Baseline | Target (QUALITY) |
|--------|----------|------------------|
| drivers_total | ~187 | 155-175 |
| split_blocks | 0 | 40-80 |
| split_share | 0% | 5-15% |
| coverage | 100% | 100% |
| hard_violations | 0 | 0 |

---

## RC0 Verification (Server Mode)

### Step-by-Step

1. **Start API Server (Terminal 1):**
```powershell
cd backend_py
uvicorn src.main:app --host 0.0.0.0 --port 8010
```

2. **Run Verification (Terminal 2):**
```powershell
cd backend_py
$env:API_PORT="8010"; python scripts/verify_rc0.py
```

3. **Check Results:**
- `RC0 VERIFICATION: PASSED [OK]` = Success
- `RC0 VERIFICATION: FAILED` = Check errors listed

### Commands by Gate

| Gate | Command | Server Required |
|------|---------|----------------|
| Contract Tests | `pytest tests/test_contract_schema.py -v` | No |
| Smoke Gate | `python scripts/diagnostic_run.py --time_budget 60` | Yes |
| Performance Gate | `python scripts/diagnostic_run.py --time_budget 120` | Yes |
| QUALITY Gate | `$env:API_PORT="8010"; python scripts/verify_rc0.py` | Yes |

### Configuration
### Configuration
| Parameter | Value | Description |
|-----------|-------|-------------|
| time_budget | 600s+ | Minimum budget (not hard limit for Quality) |
| pass2_min_time_s | 30s | Guaranteed floor for Pass-2 |
| stop_criteria | OPTIMAL/LB | Primary termination condition |

---

## RC0 Acceptance Checklist

| Item | Requirement | Verification |
|------|-------------|-------------|
| Contract | `schema_version="2.0"`, `pause_zone` present | `verify_rc0.py` |
| Backward-Compat | Old JSONs parse without errors | `test_contract_schema.py` |
| Performance | Coverage 100%, Violations 0 | `validate_schedule.py` |
| Quality | `twopass_executed=True`, Split Blocks > 0 | `verify_rc0.py` report |
| Artifacts | `artifacts/rc0/*` present and reproducible | Manual check |

---

## Artifacts

### Location
```
backend_py/artifacts/rc0/
├── weekly_plan.json      # Golden schedule output
├── validation.json       # Validation KPIs
└── README.md             # Reproduction instructions
```

### Required Contents
- `weekly_plan.json`: Full schedule with `schema_version="2.0"`, all blocks with `pause_zone`
- `validation.json`: Coverage, violations, driver counts, split block count

### Reproduction
```powershell
# Reproduce exact output (deterministic)
cd backend_py
uvicorn src.main:app --host 0.0.0.0 --port 8010 &
$env:API_PORT="8010"; python scripts/verify_rc0.py
# Uses: seed=42, output_profile=BEST_BALANCED
```

**Expected Results:**
- Coverage: 100%
- Violations: 0
- Drivers: 155-185
- Split Blocks: > 0
- `twopass_executed`: True


