# GitHub Actions CI forSOLVEREIGN

## Workflows Übersicht

### 1. `ci_pr.yml` - Pull Request & Push Gate
**Trigger**: PR → main, Push → main  
**Dauer**: ~10-15 Min  
**Zweck**: Schnelle Quality Gate Prüfung

### 2. `nightly_robustness.yml` - Tägl. Robustness Suite  
**Trigger**: Schedule (2 AM), manual dispatch  
**Dauer**: ~20-30 Min  
**Zweck**: Seeds 0-4 validation, Artifacts

### 3. `ab_experiments.yml` - A/B Testing  
**Trigger**: Manual dispatch only  
**Dauer**: ~30-45 Min (Seeds 0-9)  
**Zweck**: Baseline vs Candidate comparison

## Lokales Testen

```bash
# Quality Gate (wie PR workflow)
python backend_py/export_roster_matrix.py \
  --time-budget 60 \
  --seed 42

# Test-Fixture nutzen
cp backend_py/tests/fixtures/forecast_ci_test.csv "forecast input.csv"
```

## CI Environment

- Python: 3.11
- OR-Tools: 9.11.4210 (deterministic)
- PYTHONHASHSEED: 0 (forced)
- Runner: ubuntu-latest

## Artifacts

### PR Workflow
- `roster_matrix.csv`
- Quality gate logs

### Nightly Workflow
- `roster_matrix_seed0.csv` ... `seed4.csv`
- `robustness_summary.json`

### A/B Workflow 
- `ab_report.json`
- Promotion gate result

## Known Issues

- ⚠️ `test_business_kpis.py` marked as xfail (0 drivers bug)
- Non-blocking, documented in ROADMAP.md
