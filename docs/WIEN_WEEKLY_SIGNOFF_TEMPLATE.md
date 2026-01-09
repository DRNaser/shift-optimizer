# Wien Pilot Weekly Sign-Off - [WEEK_ID]

**System**: SOLVEREIGN V3.7
**Week**: [WEEK_ID]
**Burn-In Day**: [X]-[Y] of 30
**Sign-Off Date**: [DATE]

---

## Verdict

| Aspect | Status | Notes |
|--------|--------|-------|
| **Overall** | ✅ PASS / ⚠️ WARN / ❌ FAIL | [Brief note] |
| Audits | [7/7] PASS | |
| KPI Drift | OK / WARN / BLOCK | |
| Incidents | [0] open | |
| SLO Compliance | [5/5] met | |

---

## Run Summary

| Metric | Value |
|--------|-------|
| Run ID | [RUN_ID] |
| Input File | [filename.json] |
| Timestamp | [ISO timestamp] |
| Headcount | [N] drivers |
| Coverage | [X]% |
| FTE Ratio | [X]% |
| PT Ratio | [X]% |
| Runtime | [X]s |
| Seed | 94 |

---

## Audit Results

| Check | Status | Details |
|-------|--------|---------|
| Coverage | ✅ PASS | 100% tours assigned |
| Overlap | ✅ PASS | No concurrent tours |
| Rest | ✅ PASS | >=11h between days |
| Span Regular | ✅ PASS | <=14h |
| Span Split | ✅ PASS | <=16h, 240-360min break |
| Fatigue | ✅ PASS | No 3er→3er |
| Reproducibility | ✅ PASS | Same hash on re-run |

---

## KPI Comparison

| KPI | Baseline | This Week | Drift | Status |
|-----|----------|-----------|-------|--------|
| Headcount | 145 | [N] | [X]% | ✅/⚠️ |
| Coverage | 100% | [X]% | [X]% | ✅/⚠️ |
| FTE Ratio | 100% | [X]% | [X]% | ✅/⚠️ |
| PT Ratio | 0% | [X]% | +[X]% | ✅/⚠️ |
| Runtime | 15s | [X]s | [X]% | ✅/⚠️ |
| Churn | 3% | [X]% | [X]% | ✅/⚠️ |

---

## Incidents

| ID | Severity | Status | Title |
|----|----------|--------|-------|
| [None this week] | | | |

*Or list incidents if any occurred.*

---

## Publish/Lock Record

| Action | Timestamp | Approver | Audit Event |
|--------|-----------|----------|-------------|
| Publish | [timestamp] | [approver_id] | [AE-xxx] |
| Lock | [timestamp] | [approver_id] | [AE-xxx] |

**Evidence Hash**: `sha256:[hash]`

---

## Evidence Artifacts

| Artifact | Location | Checksum |
|----------|----------|----------|
| Run Summary | artifacts/live_wien_week_[Wxx]/run_summary.json | [hash] |
| Audit Results | artifacts/live_wien_week_[Wxx]/audit_results.json | [hash] |
| KPI Summary | artifacts/live_wien_week_[Wxx]/kpi_summary.json | [hash] |
| Evidence ZIP | artifacts/live_wien_week_[Wxx]/evidence.zip | [hash] |

---

## Approver Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Executor | ____________ | ______ | ____________ |
| Approver | ____________ | ______ | ____________ |
| Ops Lead | ____________ | ______ | ____________ |

---

## Notes

[Any additional notes, observations, or issues to track]

---

## Links

- [Burn-In Report](WIEN_BURNIN_REPORT_[Wxx].md)
- [Evidence Pack](../artifacts/live_wien_week_[Wxx]/)
- [Go-Live Checklist](GOLIVE_EXECUTION_CHECKLIST.md)

---

**Document Version**: 1.0

**Created**: [DATE]
