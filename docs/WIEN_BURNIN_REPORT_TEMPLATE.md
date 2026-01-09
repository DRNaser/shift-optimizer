# Wien Pilot Burn-In Report - [WEEK_ID]

**Generated**: [DATE]
**Burn-In Day**: [X] of 30
**Overall Status**: [STATUS_EMOJI] [STATUS]

---

## Executive Summary

| Metric | Value | Status |
|--------|-------|--------|
| Burn-In Progress | Day [X]/30 | [EMOJI] |
| Open Incidents | [COUNT] | [EMOJI] |
| Drift Alerts | [COUNT] | [EMOJI] |
| SLO Compliance | [X]/[Y] | [EMOJI] |

---

## KPI Summary

| KPI | Value | Baseline | Status |
|-----|-------|----------|--------|
| Headcount | [VALUE] | 145 | [EMOJI] |
| Coverage | [VALUE]% | 100% | [EMOJI] |
| FTE Ratio | [VALUE]% | 100% | [EMOJI] |
| PT Ratio | [VALUE]% | 0% | [EMOJI] |
| Audit Pass Rate | [VALUE]% | 100% | [EMOJI] |
| Runtime | [VALUE]s | <30s | [EMOJI] |
| Churn | [VALUE]% | <10% | [EMOJI] |
| Drift Status | [STATUS] | OK | [EMOJI] |

---

## SLO Compliance

| Metric | Target | Actual | Compliant |
|--------|--------|--------|-----------|
| API Uptime | >= 99.5% | [VALUE] | [EMOJI] |
| API P95 Latency | < 2s | [VALUE] | [EMOJI] |
| Solver P95 Latency | < 30s | [VALUE] | [EMOJI] |
| Audit Pass Rate | 100% | [VALUE] | [EMOJI] |
| Assignment Churn | < 10% | [VALUE] | [EMOJI] |

---

## Drift Alerts

| KPI | Level | Message |
|-----|-------|--------|
| [KPI] | [LEVEL_EMOJI] [LEVEL] | [MESSAGE] |

*Or: "No drift alerts this week. ✅"*

---

## Incidents

| ID | Severity | Status | Title | Owner |
|----|----------|--------|-------|-------|
| [INC-ID] | [SEV_EMOJI] [SEV] | [STATUS_EMOJI] [STATUS] | [TITLE] | [OWNER] |

*Or: "No incidents this week. ✅"*

---

## Actions Required

1. [ACTION_1]
2. [ACTION_2]
3. ...

*Or: "No actions required."*

---

## Recommendations

- [RECOMMENDATION_1]
- [RECOMMENDATION_2]
- ...

---

## Trend Charts

### Headcount Trend (Last 4 Weeks)

```
Week    Headcount
----    ---------
W-3     [VALUE]
W-2     [VALUE]
W-1     [VALUE]
W-0     [VALUE]
```

### Coverage Trend (Last 4 Weeks)

```
Week    Coverage
----    --------
W-3     [VALUE]%
W-2     [VALUE]%
W-1     [VALUE]%
W-0     [VALUE]%
```

---

## Next Steps

1. [STEP_1]
2. Review this report in weekly burn-in standup
3. [STEP_3]

---

**Report Generated**: [TIMESTAMP]

**Document Version**: 1.0

---

## Appendix: Incident Response Procedure

### When WARN/BLOCK detected:

1. **Auto-create incident**:
   ```bash
   python scripts/generate_burnin_report.py create-incident \
     --severity S2 \
     --title "KPI drift detected: headcount" \
     --description "Headcount drift 8% exceeds 5% WARN threshold" \
     --source WARN \
     --owner platform_eng
   ```

2. **Investigate root cause**

3. **Resolve incident**:
   ```bash
   python scripts/generate_burnin_report.py resolve-incident \
     --id INC-20260210120000 \
     --resolution "Root cause: data quality issue in import. Fixed by re-running onboarding."
   ```

### Break-Glass Usage:

Any break-glass usage automatically creates an incident stub:
```bash
python scripts/generate_burnin_report.py create-incident \
  --severity S1 \
  --title "Break-glass activated" \
  --description "Break-glass used to bypass publish gate for urgent repair" \
  --source BREAK_GLASS \
  --owner ops_lead
```

---

## Appendix: Status Definitions

| Status | Emoji | Meaning |
|--------|-------|---------|
| HEALTHY | ✅ | All KPIs nominal, no incidents |
| WARNING | ⚠️ | WARN-level drift or open S2/S3 incidents |
| CRITICAL | 🚨 | BLOCK-level drift or open S0/S1 incidents |

| Severity | Emoji | Definition |
|----------|-------|------------|
| S0 | 🚨 | Critical - data breach, cross-tenant access |
| S1 | ❌ | High - failed audit, potential exposure |
| S2 | ⚠️ | Medium - warning, non-critical |
| S3 | ℹ️ | Low - minor improvement |

| Incident Status | Emoji | Meaning |
|-----------------|-------|---------|
| OPEN | 🔴 | Not yet addressed |
| IN_PROGRESS | 🟡 | Being worked on |
| RESOLVED | 🟢 | Fixed and verified |
| WONT_FIX | ⚫ | Accepted risk or not applicable |
