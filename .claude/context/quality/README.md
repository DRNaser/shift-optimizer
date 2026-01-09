# Quality Branch - Router Checklist

> **Purpose**: Testing, audits, determinism proofs, and compliance
> **Severity Default**: S3/S4 - Important but not urgent (unless blocking release)

---

## ENTRY CHECKLIST

Before proceeding, answer these questions:

1. **Is this a release-blocking audit failure?**
   - YES → Read `audit-compliance.md`. Treat as S2.
   - NO → Continue

2. **Is reproducibility broken (different outputs for same seed)?**
   - YES → Read `determinism-proof.md`. Treat as S2.
   - NO → Continue

3. **Need to create/manage test fixtures?**
   - YES → Read `golden-datasets.md`
   - NO → Continue

4. **Investigating KPI drift or regression?**
   - YES → Read `kpi-drift-monitoring.md`
   - NO → Use general quality guidance below

---

## FILES IN THIS BRANCH

| File | Purpose | When to Read |
|------|---------|--------------|
| `determinism-proof.md` | Reproducibility verification | Same seed must produce same hash |
| `golden-datasets.md` | Test fixture management | Creating/updating test data |
| `audit-compliance.md` | 7 mandatory audit checks | Release gates, compliance |
| `kpi-drift-monitoring.md` | KPI baseline comparison | Detecting regressions |

---

## THE 7 MANDATORY AUDITS

| # | Check | Rule | Severity if FAIL |
|---|-------|------|------------------|
| 1 | Coverage | 1 assignment per tour_instance | S2 (release blocked) |
| 2 | Overlap | No concurrent tours per driver | S2 (release blocked) |
| 3 | Rest | ≥11h between daily blocks | S2 (release blocked) |
| 4 | Span Regular | ≤14h for 1er/2er-reg | S2 (release blocked) |
| 5 | Span Split | ≤16h for 3er/split, 4-6h break | S2 (release blocked) |
| 6 | Fatigue | No 3er→3er consecutive days | S2 (release blocked) |
| 7 | 55h Max | Weekly cap per driver | S2 (release blocked) |

**Rule**: ALL 7 must PASS before plan can be LOCKED.

---

## QUICK COMMANDS

### Run Full Audit Suite
```bash
python -m backend_py.v3.audit_fixed --plan-version-id <id>
```

### Verify Determinism
```bash
# Run twice with same seed, compare hashes
python -m backend_py.v3.solver_wrapper --forecast-id 1 --seed 94 > run1.json
python -m backend_py.v3.solver_wrapper --forecast-id 1 --seed 94 > run2.json
diff run1.json run2.json  # Should be empty
```

### Check KPI Baseline
```bash
cat .claude/state/drift-baselines.json
```

### Run Golden Dataset Test
```bash
python -m backend_py.tools.golden_datasets validate --dataset wien_small
```

---

## DETERMINISM REQUIREMENTS

For reproducibility proof:

1. **Same seed** → Same output_hash
2. **Locked matrices** → No OSRM drift
3. **Fixed solver config** → No random variance
4. **Canonical JSON** → sorted keys, consistent separators

```python
# Correct hash computation
canonical = json.dumps(assignments, sort_keys=True, separators=(',', ':'))
output_hash = hashlib.sha256(canonical.encode()).hexdigest()
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Audit check FAIL on release candidate | S2 | Block release. Fix immediately. |
| Different hash for same seed | S2 | Block release. Investigate source of randomness. |
| KPI drift > 25% | S2 | Block release. Investigate regression. |
| KPI drift 10-25% | S3 | Warn. Investigate before next release. |
| Golden dataset outdated | S4 | Schedule update. Document gap. |

---

## RELATED BRANCHES

- Need to deploy fix? → `operations/deployment-checklist.md`
- Performance regression? → `performance/profiling-runbook.md`
- Security audit? → `security/known-vulns.md`
