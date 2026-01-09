# Golden Dataset Management

> **Purpose**: Versioned test fixtures for regression testing
> **Last Updated**: 2026-01-07

---

## PURPOSE

Golden datasets are versioned, reproducible test fixtures that:
1. Provide consistent inputs for regression testing
2. Enable determinism verification
3. Document expected behavior
4. Speed up debugging by providing known-good/known-bad examples

---

## DATASET STRUCTURE

```
golden_datasets/
├── routing/
│   ├── wien_small/
│   │   ├── input.json           # Scenario data
│   │   ├── expected_output.json # Expected solution
│   │   ├── metadata.json        # Hashes, version, description
│   │   └── README.md            # Dataset documentation
│   ├── wien_mid/
│   ├── wien_46_teams/
│   └── known_failures/
│       ├── bad_time_windows/
│       └── missing_geo/
└── roster/
    ├── gurkerl_small/
    ├── gurkerl_full/
    └── known_failures/
        ├── 3er_violation/
        └── 55h_overflow/
```

---

## DATASET METADATA

Each dataset has a `metadata.json`:

```json
{
  "name": "wien_small",
  "pack": "routing",
  "version": "1.0.0",
  "created_at": "2026-01-07T10:00:00Z",
  "description": "Small Wien scenario for quick smoke tests",

  "input": {
    "stops": 10,
    "vehicles": 3,
    "depots": 1
  },

  "hashes": {
    "input_hash": "abc123...",
    "expected_output_hash": "def456...",
    "solver_config_hash": "ghi789..."
  },

  "expected_kpis": {
    "coverage_pct": 100,
    "total_distance_km": 45.2,
    "routes_used": 3,
    "time_window_violations": 0
  },

  "solver_config": {
    "seed": 94,
    "time_limit_seconds": 30,
    "metaheuristic": "GUIDED_LOCAL_SEARCH"
  },

  "tags": ["smoke_test", "quick", "wien"]
}
```

---

## DATASET OPERATIONS

### List Datasets

```bash
python -m backend_py.tools.golden_datasets list

# Output:
# routing/wien_small        v1.0.0  10 stops, 3 vehicles
# routing/wien_mid          v1.0.0  50 stops, 10 vehicles
# routing/wien_46_teams     v1.0.0  46 teams, real OSRM
# roster/gurkerl_small      v1.0.0  50 tours
# roster/gurkerl_full       v1.0.0  1385 tours
```

### Validate Dataset

```bash
python -m backend_py.tools.golden_datasets validate --dataset routing/wien_small

# Output:
# ✅ Input hash matches: abc123...
# ✅ Solver config hash matches: ghi789...
# ✅ Output hash matches: def456...
# ✅ KPIs match expected values
# VALIDATION PASSED
```

### Validate All Datasets

```bash
python -m backend_py.tools.golden_datasets validate --all

# Output:
# routing/wien_small        ✅ PASS
# routing/wien_mid          ✅ PASS
# routing/wien_46_teams     ⏭️ SKIP (requires OSRM)
# roster/gurkerl_small      ✅ PASS
# roster/gurkerl_full       ✅ PASS
#
# 4/5 PASSED, 1 SKIPPED
```

### Create New Dataset

```bash
python -m backend_py.tools.golden_datasets create \
    --name wien_large \
    --pack routing \
    --from-scenario 123 \
    --description "Large Wien scenario for load testing"

# Output:
# Created: golden_datasets/routing/wien_large/
# Input hash: abc123...
# Run solver to generate expected output? [y/N]
```

### Update Expected Output

```bash
python -m backend_py.tools.golden_datasets update \
    --dataset routing/wien_small \
    --reason "Solver algorithm improved"

# Output:
# Previous output_hash: def456...
# New output_hash: xyz789...
# Updated metadata.json
# Version bumped: 1.0.0 -> 1.1.0
```

---

## KNOWN FAILURE DATASETS

For documenting and testing edge cases:

```json
// known_failures/bad_time_windows/metadata.json
{
  "name": "bad_time_windows",
  "pack": "routing",
  "version": "1.0.0",
  "description": "Scenario with impossible time windows",

  "expected_behavior": "FAIL",
  "expected_error": "Time window violation: stop 5 cannot be served",

  "purpose": "Verify solver rejects invalid input gracefully",

  "input": {
    "stops": 5,
    "vehicles": 2,
    "invalid_windows": ["stop_5: 08:00-07:00"]  // End before start
  }
}
```

### Testing Known Failures

```python
def test_known_failure_bad_time_windows():
    """Verify solver correctly rejects impossible time windows."""
    dataset = load_dataset("routing/known_failures/bad_time_windows")

    with pytest.raises(TimeWindowViolationError) as exc:
        solve_scenario(dataset.input)

    assert "stop 5" in str(exc.value)
```

---

## CI INTEGRATION

### Nightly Regression

```yaml
# .github/workflows/nightly-torture.yml
name: Nightly Regression
on:
  schedule:
    - cron: '0 2 * * *'

jobs:
  golden-regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Golden Dataset Validation
        run: |
          python -m backend_py.tools.golden_datasets validate --all

      - name: Check for Drift
        run: |
          python -m backend_py.tools.golden_datasets check-drift --threshold 10
```

### PR Fast Check

```yaml
# .github/workflows/pr-fast.yml
golden-smoke:
  runs-on: ubuntu-latest
  steps:
    - name: Run Smoke Datasets
      run: |
        python -m backend_py.tools.golden_datasets validate \
          --tags smoke_test
```

---

## DATASET VERSIONING

### Version Bump Rules

| Change | Version Bump | Action |
|--------|--------------|--------|
| Input data change | MAJOR | Full re-validation required |
| Expected output change | MINOR | Document reason |
| Metadata update only | PATCH | No re-validation needed |

### Git Tracking

```bash
# Golden datasets are git-tracked
git add golden_datasets/routing/wien_small/
git commit -m "feat(golden): add wien_small routing dataset"
```

---

## BEST PRACTICES

### Creating Datasets

1. **Size appropriately**: Small for smoke tests, large for load tests
2. **Document purpose**: Clear README for each dataset
3. **Version immediately**: Don't use unversioned data
4. **Include expected KPIs**: Not just output hash

### Maintaining Datasets

1. **Validate regularly**: Nightly CI runs
2. **Update intentionally**: Document why output changed
3. **Retire gracefully**: Mark deprecated, don't delete
4. **Backup hashes**: Keep history of expected_output_hash changes

### Using Datasets

1. **Match environment**: Use static matrices, not live OSRM
2. **Fix seed**: Always use metadata.solver_config.seed
3. **Compare KPIs too**: Not just binary pass/fail
4. **Report drift**: Alert on KPI changes >10%

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Output hash mismatch | S2 | Block release. Investigate regression. |
| KPI drift > 25% | S2 | Block release. Verify intentional. |
| KPI drift 10-25% | S3 | Review before release. Document reason. |
| Dataset validation timeout | S3 | Check input size. Optimize or split. |
| Missing dataset | S4 | Create before next release. |
