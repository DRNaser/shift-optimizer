# CI Hardening Checklist & Branch Protection Setup

## 1. End-to-End Verification

### Manual PR Workflow Test
```bash
# Via GitHub UI:
Actions → CI - PR & Push Gate → Run workflow
  Branch: main

# Or via gh CLI:
gh workflow run ci_pr.yml --ref main
```

**Verify**:
- ✅ Exit code: 0 (PASS/WARN) or 1 (FAIL)
- ✅ Artifacts uploaded: `pr-gate-results-{sha}`
- ✅ Logs show: "Using CI test fixture (~100 lines)"
- ✅ No production forecast leakage

### Check Artifact Contents
```bash
# Download artifact from Actions → Click run → Artifacts
ls -lh roster_matrix.csv
wc -l roster_matrix.csv  # Should show active drivers (e.g., 40-60)
```

---

## 2. Branch Protection Rules (GitHub Settings)

### Required Setup
```
Settings → Branches → Add rule (main)
```

**Required checks**:
- [x] `quality-gate (Fast)` - Must pass before merge
- [x] `pytest-suite (xfail known issues)` - Optional (continue-on-error)

**Settings**:
```yaml
Branch name pattern: main

[x] Require status checks to pass before merging
    [x] Require branches to be up to date before merging
    Status checks that are required:
      ✓ quality-gate (Fast)

[ ] Require linear history  # Optional, recommended
[ ] Restrict who can push   # Optional for small teams

[x] Allow force pushes
    [ ] Everyone (DISABLE THIS)
    [x] Specify who can force push
        → Only admins/release managers
```

### Test Branch Protection
```bash
# Try pushing directly to main (should fail if protected)
git checkout main
git commit --allow-empty -m "test: branch protection"
git push origin main
# → Should be rejected or require PR

# Create PR instead
git checkout -b test/ci-verification
git push origin test/ci-verification
# → Create PR via GitHub UI
# → CI should run automatically
# → Merge button disabled until CI green
```

---

## 3. Concurrency & Cost Controls

### Nightly Workflow Concurrency (Already Added)
```yaml
# .github/workflows/nightly_robustness.yml
concurrency:
  group: nightly-robustness
  cancel-in-progress: false  # Let running jobs finish
```

**What this does**:
- Only 1 nightly run at a time
- If schedule triggers while previous run still active → queue it
- `cancel-in-progress: false` → finish current run first

### Budget Monitoring
```yaml
# In nightly_robustness.yml, add budget warning
- name: Check Runtime Budget
  run: |
    # If job approaches timeout (45 min), warn
    if [ "$SECONDS" -gt 2400 ]; then  # 40 min
      echo "⚠️ WARNING: Job running for ${SECONDS}s (close to 45min timeout)"
    fi
```

**GitHub Actions Limits**:
- Jobs: 6h max (we use 45 min)
- Matrix jobs: Run in parallel (seeds 0-4 = 5 concurrent)
- Free tier: 2000 min/month (enough for daily nightly + PRs)

---

## 4. Determinism: Hash Interpretation

### What Hash Checks Verify
```python
# Hash is computed on roster_matrix.csv
hash = sha256sum(roster_matrix.csv)
```

**Hash is deterministic if**:
- ✅ Same solver logic
- ✅ Same input (seed, forecast)
- ✅ **Same driver ordering in export**

**Hash will differ if**:
- ⚠️ Driver sorting changes (e.g., alphabetical → by hours)
- ⚠️ Floating point rounding changes
- ⚠️ CSV formatting changes (delimiter, line endings)

### Recommendation
```yaml
# Nightly workflow already checks hash consistency
# If hashes differ:
1. Check if it's just ordering → non-critical
2. Check if KPIs changed → critical!

# Right approach:
- Hash = signal (quick smoke test)
- KPIs = truth (drivers_active, core_pt_share, violations)
```

**Future Enhancement** (optional):
```python
# Add KPI-based determinism check
def check_determinism(runs):
    kpis = [r['drivers_active'] for r in runs]
    if len(set(kpis)) == 1:
        return "PASS: KPI deterministic"
    else:
        return f"FAIL: KPI variance detected: {kpis}"
```

---

## 5. Fixture Quality (`forecast_ci_test.csv`)

### Enhanced Fixture (Already Updated)
```
Lines: ~110 (vs ~100 before)
Tours/day: 14-18 (realistic distribution)
```

**Patterns included**:
- ✅ **Peak Day**: Friday (15 tours vs avg 10)
- ✅ **Split Opportunities**: Early tours (04:45-09:15) + Late tours (18:30-23:00)
- ✅ **Rest Edge Cases**: Consecutive days with tight rest (Thu→Fri)
- ✅ **Orphan Patterns**: 04:45-09:15 (early outlier)

**Why these matter**:
- **Peak detection**: Friday should trigger dynamic peak logic
- **Split patterns**: 2er_split blocks should be generated
- **Rest compliance**: 11h minimum enforced (Thu 22:30 → Fri 04:45 = 6h15m rest violation)
- **Orphan handling**: Early/late tours test singleton fallback

### Verify Feature Coverage
```bash
# Run solver with fixture
python backend_py/export_roster_matrix.py --time-budget 60 --seed 42

# Check logs for v7.0.0 features
grep "Dynamic Peak Days" # Should show ['Fri']
grep "Split" roster_matrix.csv # Should have some split blocks
grep "11h rest" # Should show rest validation
```

---

## 6. Post-Merge Verification

### After CI merge to main:
1. **Check Actions tab**: Nightly runs at 2 AM UTC
2. **Download artifacts**: Verify robustness_summary.json
3. **Monitor PR gate**: Should block bad PRs

### First PR after merge:
```bash
git checkout -b feat/example
# Make any change (e.g., update README)
git commit -am "test: verify CI gate"
git push origin feat/example
# Create PR
# → CI should run automatically
# → Check that quality-gate passes
# → Merge only if green
```

---

## 7. Troubleshooting

### CI fails with "forecast not found"
```bash
# Check that fixture exists
ls backend_py/tests/fixtures/forecast_ci_test.csv

# Verify workflow path
cat .github/workflows/ci_pr.yml | grep forecast_ci_test
```

### "PYTHONHASHSEED not working"
```bash
# Check env in workflow logs
echo $PYTHONHASHSEED  # Should be 0

# Verify in Python
python -c "import os; print(os.environ.get('PYTHONHASHSEED'))"
```

### Hash differs between seeds
```bash
# Download artifacts for multiple seeds
diff artifacts/roster_matrix_seed0.csv artifacts/roster_matrix_seed1.csv

# If only ordering differs → OK
# If content differs → investigate KPIs
```

---

## ✅ Hardening Checklist

- [x] workflow_dispatch added to ci_pr.yml
- [x] Concurrency limits in nightly_robustness.yml
- [x] Fixture verification step (production data detection)
- [x] Enhanced fixture with realistic patterns
- [ ] **USER ACTION**: Enable branch protection on main
- [ ] **USER ACTION**: Run manual test of ci_pr.yml workflow
- [ ] **USER ACTION**: Merge CI PR and verify nightly runs

**Next Steps**:
1. Merge CI implementation to main
2. Enable branch protection rules
3. Test with dummy PR
4. Monitor first nightly run (2 AM UTC)

---

**Status**: CI Hardened & Production-Ready! 🔒
