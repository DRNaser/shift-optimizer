# UAT Sign-Off: Dispatcher Cockpit - Production (Internal)

> **Environment**: Production
> **Phase**: Gate 2 - Internal Team Only
> **Week**: W___ (2026-W__)
> **Date**: _______________
> **Version**: V3.7 Wien Pilot

---

## Sign-Off Summary

| Item | Status |
|------|--------|
| Live weekly flow completed via UI | [ ] |
| Artifacts identical to CLI | [ ] |
| No incidents during test | [ ] |
| CLI fallback verified | [ ] |
| Sign-off approved | [ ] |

---

## Configuration Verified

| Setting | Expected | Actual | OK |
|---------|----------|--------|-----|
| `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT` | `true` | | [ ] |
| `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT_ROLES` | `platform_admin,platform_ops` | | [ ] |
| `NEXT_PUBLIC_ENABLED_SITES` | `wien` | | [ ] |
| Production API healthy | 200 on /health | | [ ] |
| Kill switch OFF | Verified | | [ ] |

---

## Live Weekly Flow Execution

### Test Details
| Item | Value |
|------|-------|
| Week tested | 2026-W__ |
| Run ID | |
| Forecast ID | |
| Tester | |
| Test date/time | |

### Step 1: List Runs
| Check | Result | Notes |
|-------|--------|-------|
| Runs page loads | [ ] Pass [ ] Fail | |
| Correct runs visible | [ ] Pass [ ] Fail | |
| Status badges accurate | [ ] Pass [ ] Fail | |

### Step 2: View Run Detail
| Check | Result | Notes |
|-------|--------|-------|
| Detail page loads | [ ] Pass [ ] Fail | |
| KPIs match CLI output | [ ] Pass [ ] Fail | |
| All 7 audits displayed | [ ] Pass [ ] Fail | |

### Step 3: Publish Run
| Check | Result | Notes |
|-------|--------|-------|
| Modal opens correctly | [ ] Pass [ ] Fail | |
| Approval submitted | [ ] Pass [ ] Fail | |
| Status changes to published | [ ] Pass [ ] Fail | |
| Audit event logged | [ ] Pass [ ] Fail | |

**Publish Details**:
```
Run ID: _______________
Approver: _______________
Reason: _______________
Timestamp: _______________
```

### Step 4: Lock Run
| Check | Result | Notes |
|-------|--------|-------|
| Lock modal opens | [ ] Pass [ ] Fail | |
| Approval submitted | [ ] Pass [ ] Fail | |
| Status changes to locked | [ ] Pass [ ] Fail | |
| Audit event logged | [ ] Pass [ ] Fail | |

**Lock Details**:
```
Run ID: _______________
Approver: _______________
Reason: _______________
Timestamp: _______________
Evidence Hash: _______________
```

### Step 5: Evidence Download
| Check | Result | Notes |
|-------|--------|-------|
| Evidence hash visible | [ ] Pass [ ] Fail | |
| Download works | [ ] Pass [ ] Fail | |
| Hash matches | [ ] Pass [ ] Fail | |

---

## Artifact Comparison: UI vs CLI

| Artifact | UI Value | CLI Value | Match |
|----------|----------|-----------|-------|
| Publish audit event hash | | | [ ] |
| Lock audit event hash | | | [ ] |
| Evidence pack SHA256 | | | [ ] |
| approver_id | | | [ ] |
| approver_role | | | [ ] |
| timestamp (within 1 min) | | | [ ] |

**Comparison Method**:
```bash
# CLI verification commands used:
python scripts/dispatcher_cli.py show-run <run_id>
python scripts/dispatcher_cli.py evidence <run_id> --checksum-only
```

---

## CLI Fallback Verification

| Test | Result | Notes |
|------|--------|-------|
| CLI list-runs works | [ ] Pass [ ] Fail | |
| CLI show-run works | [ ] Pass [ ] Fail | |
| CLI publish works | [ ] Pass [ ] Fail | |
| CLI lock works | [ ] Pass [ ] Fail | |
| CLI evidence works | [ ] Pass [ ] Fail | |

**Fallback scenario tested**: _______________

---

## Incidents During Test

| Time | Issue | Severity | Resolution |
|------|-------|----------|------------|
| | | | |

**Total incidents**: _____ (must be 0 to pass)

---

## Monitoring Observations

| Metric | Value | Expected | OK |
|--------|-------|----------|-----|
| UI load time (avg) | | < 3s | [ ] |
| API error rate | | < 1% | [ ] |
| 401 errors | | 0 | [ ] |
| 403 errors (expected) | | N/A | [ ] |

---

## Sign-Off

### Testers
| Name | Role | Date | Signature |
|------|------|------|-----------|
| | Platform Admin | | |
| | Ops Lead | | |

### Approvers
| Name | Role | Date | Result |
|------|------|------|--------|
| | Platform Lead | | [ ] Approved [ ] Rejected |
| | Security Lead | | [ ] Approved [ ] Rejected |

---

## Decision

- [ ] **APPROVED**: Proceed to Gate 3 (Wien Dispatchers Enable)
- [ ] **HOLD**: Wait for burn-in day 30
- [ ] **REJECTED**: Fix issues and re-test

**Next Action**:
```
_______________________________________________
```

---

## Checklist Before Gate 3

- [ ] Burn-in day >= 30
- [ ] No open critical issues
- [ ] RUNBOOK updated with UI procedures
- [ ] Dispatcher training scheduled
- [ ] Fallback documented and tested

---

**Document Created**: _______________
**Last Updated**: _______________
