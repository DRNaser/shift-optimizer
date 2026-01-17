# MERGE DECISION
## PR #15: cleanup/pr4-deterministic-solver → main
**Decision Date**: 2026-01-17T07:32:00+01:00  
**Forensic Engineer**: Claude Code (SOLVEREIGN)

---

## 🔴 DECISION: NO-GO (CONDITIONAL)

### Reason
Local verification PASSED all gates, but GitHub CI shows failures on SHA `d3f519f`. Local HEAD `22abfc29` contains fixes that haven't been pushed OR need fresh CI run.

**Blocking Issues**:
1. ❌ **Gitleaks FALSE POSITIVE**: Placeholder hash in `006_multi_tenant.sql` flagged as secret
2. ❌ **CI runs on stale SHA**: GitHub shows `d3f519f`, local is `22abfc29` (4 commits ahead)

---

## Required Actions Before Merge

### Action 1: Add .gitleaksignore (DONE)
Create `.gitleaksignore` to exclude the placeholder hash in migration file:
```
# False positive: Placeholder hash for inactive migration tenant
# File: backend_py/db/migrations/006_multi_tenant.sql
# Pattern: 64 zeros used as invalid API key hash placeholder
006_multi_tenant.sql:0000000000000000000000000000000000000000000000000000000000000000
```

### Action 2: Push Local Commits
```bash
git push origin cleanup/pr4-deterministic-solver
```
Current local commits (not yet verified by CI):
- `22abfc29` fix(ci): correct roster_matrix.csv path in quality gate
- `19f15b4` fix(ci): convert forecast_ci_test.csv to parser-compatible format
- `c215940` gate: make CleanCut pass (remove legacy imports in tests)
- `e999f36` ci(migration): add tenant_id to forecast_compositions and tour_removals

### Action 3: Wait for Fresh CI Run
After push, monitor:
- Guardian Gate → Cross-Process Determinism (should remain ✅)
- Gitleaks Secret Scan (should become ✅ with .gitleaksignore)
- V3 Solver Regression Gate (should become ✅ with path fix)

---

## Local Verification Summary (ALL PASSED)

| Gate | Status | Evidence |
|------|--------|----------|
| Git Identity | ✅ PASS | HEAD=22abfc29, origin matches |
| Legacy Cleanup | ✅ PASS | No streamlit/cli/src/v3 files |
| Import Hygiene | ✅ PASS | No production v3/src imports |
| Determinism Proof | ✅ PASS | 3 runs, hash `73fb8941ad950be6...` |
| Migration Order | ✅ PASS | tenant_id before FK constraints |

---

## CI Passing Gates (Pre-existing on GitHub)

| Gate | SHA | Status |
|------|-----|--------|
| Cross-Process Determinism | d3f519f | ✅ PASS |
| Wien W02 Security Gate | d3f519f | ✅ PASS |
| Golden Dataset Tests | d3f519f | ✅ PASS |
| KPI Drift Tests | d3f519f | ✅ PASS |

---

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Gitleaks false positive blocking | LOW | .gitleaksignore added |
| V3 Solver Regression path | LOW | Fixed in commit 22abfc29 |
| Migration contract | LOW | tenant_id verified in 002, FK in 006 |
| Determinism regression | NONE | Local proof passed |

---

## Upgrade Path to MERGE-GO

1. ✅ Create `.gitleaksignore` (DONE in this session)
2. ⏳ Commit `.gitleaksignore` with message: `ci: add gitleaksignore for migration placeholder hash`
3. ⏳ Push all local commits to origin
4. ⏳ Wait for CI to complete
5. ⏳ Verify all critical gates pass:
   - [ ] Gitleaks Secret Scan → GREEN
   - [ ] Cross-Process Determinism → GREEN (already)
   - [ ] V3 Solver Regression Gate → GREEN (expected with path fix)
   - [ ] Migration Contract → GREEN

---

## Follow-up PRs (After Merge)

1. **Gitleaks Permissions Hardening**: Add explicit `permissions:` block to workflow
2. **FK Hardening**: Add explicit FK constraints for `forecast_compositions`/`tour_removals` in 006 if missing
3. **RLS Enforcement**: Complete RLS policy implementation for roster/dispatch schemas

---

## Evidence Files
- [FORENSIC_TRUTH_SNAPSHOT.md](./FORENSIC_TRUTH_SNAPSHOT.md)
- [CI_STATUS_MATRIX.md](./CI_STATUS_MATRIX.md)
