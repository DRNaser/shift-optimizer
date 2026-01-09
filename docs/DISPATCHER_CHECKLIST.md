# Dispatcher Checklist

**Quick Reference for Daily Operations**

---

## Before Publishing a Plan

### 1. Forecast Ingestion ✓

| Check | Status |
|-------|--------|
| Forecast file received | ☐ |
| Week anchor date is Monday | ☐ |
| Validation script passes | ☐ |
| Upload successful | ☐ |

**Validation Command**:
```bash
python scripts/validate_import_contract.py --input forecast.json
```

Expected: `✅ Validation PASSED` or `⚠️ PASSED with warnings`

---

### 2. Solver Output ✓

| KPI | Target | Actual | OK? |
|-----|--------|--------|-----|
| Coverage | 100% | ___% | ☐ |
| Total Drivers | — | ___ | ☐ |
| FTE (>=40h) | >95% | ___% | ☐ |
| PT (<40h) | <5% | ___% | ☐ |
| Max Hours | <55h | ___h | ☐ |

---

### 3. Audit Checks ✓

All 7 audits must PASS:

| Audit | Status |
|-------|--------|
| Coverage (every tour assigned once) | ☐ PASS |
| Overlap (no concurrent tours) | ☐ PASS |
| Rest (>=11h between days) | ☐ PASS |
| Span Regular (1er/2er <=14h) | ☐ PASS |
| Span Split (3er/split <=16h) | ☐ PASS |
| Fatigue (no 3er→3er) | ☐ PASS |
| Reproducibility (deterministic) | ☐ PASS |

**If ANY audit shows FAIL**: STOP. Do not publish. Contact Platform Team.

---

### 4. Final Review ✓

| Item | Checked |
|------|---------|
| Total tours match forecast | ☐ |
| Driver count reasonable | ☐ |
| No unusual warnings | ☐ |
| Spot-check 3 driver schedules | ☐ |

---

## Publishing Decision

### ✅ PUBLISH if:
- Coverage = 100%
- All 7 audits PASS
- KPIs within targets

### ⚠️ PUBLISH WITH CAUTION if:
- Warnings present (document rationale)
- KPIs slightly off target

### ❌ DO NOT PUBLISH if:
- Coverage < 100%
- Any audit FAIL
- Unresolved errors

---

## On FAIL or WARN

### Coverage < 100%

1. Check unassigned tours in output
2. Verify forecast input is correct
3. Contact Platform Team if persists

### Audit Failure

| Audit | What to Check |
|-------|---------------|
| Coverage | Duplicate tours? Missing drivers? |
| Overlap | Same driver double-booked? |
| Rest | Driver working consecutive days without break? |
| Span | Block duration too long? |
| Fatigue | 3er block followed by another 3er? |

### High Part-Time Ratio

1. Check driver availability constraints
2. Review forecast tour distribution
3. May need more drivers or adjusted schedule

---

## Lock the Plan

Once approved:

```bash
# Lock command (API)
POST /api/v1/plans/{plan_id}/lock
```

After lock:
- Plan is **IMMUTABLE**
- Changes require new plan version
- Evidence pack generated automatically

---

## Daily Checks

| Time | Check |
|------|-------|
| 08:00 | Review overnight alerts |
| 10:00 | Check solver run status |
| 14:00 | Verify plan approval progress |
| 17:00 | Confirm lock (Tuesday only) |

---

## Emergency: Sick-Call Repair

If driver calls in sick after plan lock:

1. **Check freeze status**
   - Tours < 12h away: FROZEN (contact Platform)
   - Tours > 12h away: Can repair

2. **Run repair** (Platform Team)
   ```bash
   python scripts/run_sick_call_drill.py \
     --absent-drivers DRV001 \
     --tenant wien_pilot
   ```

3. **Verify repair**
   - Coverage still 100%
   - Churn < 20%
   - All audits PASS

---

## Contacts

| Issue | Contact |
|-------|---------|
| Validation errors | Platform Team |
| Audit failures | Platform Team |
| Urgent (< 2h to tour) | On-call |
| System down | On-call (PagerDuty) |

---

## Quick Links

| Resource | Link |
|----------|------|
| Full Runbook | [RUNBOOK_OPERATIONS_CADENCE.md](../RUNBOOK_OPERATIONS_CADENCE.md) |
| Technical Runbook | [RUNBOOK_WIEN_PILOT.md](../RUNBOOK_WIEN_PILOT.md) |
| Import Contract | [IMPORT_CONTRACT_ROSTER.md](IMPORT_CONTRACT_ROSTER.md) |
| SLO Targets | [SLO_WIEN_PILOT.md](SLO_WIEN_PILOT.md) |

---

**Version**: 1.0 | **Last Updated**: 2026-01-08
