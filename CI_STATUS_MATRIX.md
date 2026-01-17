# CI STATUS MATRIX
## PR #15: cleanup/pr4-deterministic-solver
**Last Updated**: 2026-01-17T07:31:00+01:00  
**GitHub PR HEAD (at CI run)**: `d3f519fca0909798528945f56fc29fca2137fd87`  
**Local HEAD (verified)**: `22abfc294801713d8198fb49ffcb52daa13ec862`

> ⚠️ **SHA DISCREPANCY**: GitHub CI shows older SHA. Local has 4 newer commits that fix CI issues.
> These commits need to be pushed to trigger fresh CI runs.

---

## CI Check Status (from GitHub Actions)

| Workflow | Job | Status | Root Cause | Fix Required |
|----------|-----|--------|------------|--------------|
| **Guardian Gate** | Guardian Bootstrap | ✅ PASS | - | None |
| **Guardian Gate** | Secret Scan (gitleaks) | ❌ FAIL | "SECRET DETECTED!" | See below |
| **Guardian Gate** | Pack Boundary Linter | ❌ FAIL | Unknown | Investigate |
| **Guardian Gate** | KPI Drift Tests | ✅ PASS | - | None |
| **Guardian Gate** | Golden Dataset Tests | ✅ PASS | - | None |
| **Guardian Gate** | Impact Preview Tests | ✅ PASS | - | None |
| **Guardian Gate** | Audit Report Tests | ✅ PASS | - | None |
| **Guardian Gate** | Allow-Only Override Check | ⏭️ SKIP | - | None |
| **Guardian Gate** | Auth Separation Gate (F) | ❌ FAIL | Unknown | Investigate |
| **Guardian Gate** | Wien W02 Security Gate | ✅ PASS | - | None |
| **Guardian Gate** | Wien W02 Roster Gate | ❌ FAIL | Unknown | Investigate |
| **Guardian Gate** | Ops Drills Gate (H) | ❌ FAIL | Unknown | Investigate |
| **Guardian Gate** | Integration Gate (Docker) | ❌ FAIL | Unknown | Investigate |
| **Guardian Gate** | Migration Idempotency | ❌ FAIL | Unknown | Investigate |
| **Guardian Gate** | **Cross-Process Determinism** | ✅ PASS | - | None |
| **Guardian Gate** | V3 Solver Regression Gate | ❌ FAIL | "No evidence file generated!" | See below |
| **Guardian Gate** | Schema Validation | ❌ FAIL | Unknown | Investigate |
| **PR Fast Gates** | Backend Unit Tests | ❌ FAIL | Unknown | Investigate |
| **PR Proof Gates** | Migration Contract | ❌ FAIL | Unknown | Investigate |
| **SOLVEREIGN CI/CD** | backend-test | ❌ FAIL | Unknown | Investigate |
| **Gitleaks Secret Scan** | Secret Detection | ❌ FAIL | "SECRET DETECTED!" | See below |
| **Vercel** | Deployment | ❌ FAIL | Unknown | Investigate |

---

## Critical Failure Analysis

### 1. Gitleaks - SECRET DETECTED! ❌
**Screenshot Evidence**: 
```
Error: SECRET DETECTED! PR blocked until secrets are removed.
Possible secrets found in commits. Actions:
1. Remove the secret from code
2. Rotate the exposed credential immediately
3. Add to .gitleaksignore if false positive
Error: Process completed with exit code 1.
```

**Diagnosis**: The gitleaks scan found potential secrets in commit history.

**Possible Causes**:
1. **False Positive**: Test API keys, example tokens, or hash strings misidentified as secrets
2. **Real Secret**: Actual credentials committed (requires rotation)

**Required Action**: 
- Run `gitleaks detect --source . --verbose` locally to identify the flagged content
- If false positive: add to `.gitleaksignore`
- If real secret: remove from history with `git filter-branch` or BFG

### 2. V3 Solver Regression Gate ❌
**Screenshot Evidence**:
```
Run # Parse evidence file
Error: No evidence file generated!
Error: Process completed with exit code 1.
```

**Diagnosis**: The `Run V3 solver regression test` step did not produce an evidence file.

**Possible Causes**:
1. Test script crashed before writing output
2. Wrong output path configured
3. Missing test fixture (e.g., `roster_matrix.csv`)

**Note**: Recent commits `22abfc29` and `19f15b4` appear to fix this:
- `fix(ci): correct roster_matrix.csv path in quality gate`
- `fix(ci): convert forecast_ci_test.csv to parser-compatible format`

---

## Key Passing Gates ✅

| Gate | Significance |
|------|--------------|
| **Cross-Process Determinism** | CRITICAL - Solver produces identical output across processes |
| **Wien W02 Security Gate** | Security invariants maintained |
| **Golden Dataset Tests** | No regression in expected outputs |
| **KPI Drift Tests** | No unexpected KPI changes |

---

## Recommended Actions

1. **Push local commits to remote** - SHA `22abfc29` contains CI fixes
2. **Wait for fresh CI run** - Re-evaluate after push
3. **Investigate Gitleaks** - Run locally to identify flagged content
4. **Re-run failed gates** - Many may pass with updated code

---

## CI Run URLs
- **Guardian Gate #21**: https://github.com/DRNaser/shift-optimizer/actions/runs/[RUN_ID]
- **Gitleaks**: https://github.com/DRNaser/shift-optimizer/actions/workflows/gitleaks.yml

> **Note**: Exact run URLs require `gh` CLI or manual extraction from GitHub.
