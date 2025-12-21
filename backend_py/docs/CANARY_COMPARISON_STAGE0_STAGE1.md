# Canary Comparison: Stage 0 vs Stage 1

> **Exported:** 2025-12-21

## Build Info (Both Stages)

| Key | Value |
|-----|-------|
| `git_commit` | `4e1abb5` |
| `app_version` | `2.0.0` |
| `ortools_version` | `9.11.4210` |

---

## Configuration Difference

| Setting | Stage 0 | Stage 1 |
|---------|---------|---------|
| `cap_quota_2er` | OFF | **0.30** |
| `enable_diag_block_caps` | OFF | OFF |

---

## KPI Comparison

| Metric | Stage 0 (405 runs) | Stage 1 (27 runs) | Delta |
|--------|-------------------|-------------------|-------|
| **Run Count** | 405 | 27 | - |
| **Infeasible Rate** | 0.00% | 0.00% | ✅ Same |
| **Budget Overrun Rate** | 99.75% | 100% | ~ Same |
| **Starvation (2er)** | NO | NO | ✅ Same |

---

## Candidate Blocks (Avg per Run)

| Size | Stage 0 (avg/run) | Stage 1 (avg/run) | Delta |
|------|-------------------|-------------------|-------|
| 1er | 1,385 | 1,385 | Same |
| 2er | 5,584 | 5,584 | Same |
| 3er | 13,031 | 13,031 | Same |

---

## Conclusion

**Stage 1 (cap_quota_2er=0.30) shows:**
- ✅ No regression in infeasibility
- ✅ No starvation of 2-tour blocks
- ✅ Same candidate block distribution
- ⚠️ Budget overrun remains high (expected - soft limit)

**Recommendation:** Stage 1 is **SAFE TO DEPLOY**. The `cap_quota_2er=0.30` feature does not cause regressions.

---

## Next Steps

1. Merge `cleanup/remove-outdated-files` branch to main
2. Deploy with `cap_quota_2er=0.30` enabled by default
3. Monitor production KPIs against this baseline
