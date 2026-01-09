# UAT Sign-Off: Dispatcher Cockpit - Staging

> **Environment**: Staging
> **Phase**: Gate 1 - Staging UAT
> **Date**: _______________
> **Version**: V3.7 Wien Pilot

---

## Sign-Off Summary

| Item | Status |
|------|--------|
| All 10 scenarios executed | [ ] |
| Critical issues | _____ (must be 0) |
| Minor issues | _____ |
| Sign-off approved | [ ] |

---

## Configuration Verified

| Setting | Expected | Actual | OK |
|---------|----------|--------|-----|
| `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT` | `true` | | [ ] |
| `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT_ROLES` | `platform_admin,platform_ops,dispatcher,ops_lead` | | [ ] |
| `NEXT_PUBLIC_ENABLED_SITES` | `wien` | | [ ] |
| Backend API reachable | 200 on /health | | [ ] |

---

## Test Execution Results

### Scenario 1: Runs List Page
| Step | Result | Notes |
|------|--------|-------|
| Page loads in < 2s | [ ] Pass [ ] Fail | |
| Status badges visible | [ ] Pass [ ] Fail | |
| KPIs shown | [ ] Pass [ ] Fail | |
| Filter works | [ ] Pass [ ] Fail | |
| Refresh works | [ ] Pass [ ] Fail | |

### Scenario 2: Run Detail Page
| Step | Result | Notes |
|------|--------|-------|
| KPI cards visible | [ ] Pass [ ] Fail | |
| Audit Results section | [ ] Pass [ ] Fail | |
| Evidence Hash displayed | [ ] Pass [ ] Fail | |
| Actions section | [ ] Pass [ ] Fail | |

### Scenario 3: Publish Flow (Happy Path)
| Step | Result | Notes |
|------|--------|-------|
| Modal opens | [ ] Pass [ ] Fail | |
| Reason validation | [ ] Pass [ ] Fail | |
| Publish succeeds | [ ] Pass [ ] Fail | |
| State changes to published | [ ] Pass [ ] Fail | |

**Audit Event Captured**:
```json
{
  "action": "publish",
  "run_id": "",
  "approver_id": "",
  "approver_role": "",
  "reason": "",
  "evidence_hash": "",
  "timestamp": ""
}
```

### Scenario 4: Lock Flow (Happy Path)
| Step | Result | Notes |
|------|--------|-------|
| Modal opens | [ ] Pass [ ] Fail | |
| Lock succeeds | [ ] Pass [ ] Fail | |
| State changes to locked | [ ] Pass [ ] Fail | |
| Buttons disabled after | [ ] Pass [ ] Fail | |

**Audit Event Captured**:
```json
{
  "action": "lock",
  "run_id": "",
  "approver_id": "",
  "approver_role": "",
  "reason": "",
  "evidence_hash": "",
  "timestamp": ""
}
```

### Scenario 5: Repair Request
| Step | Result | Notes |
|------|--------|-------|
| Form opens | [ ] Pass [ ] Fail | |
| Validation enforced | [ ] Pass [ ] Fail | |
| Submit succeeds | [ ] Pass [ ] Fail | |

### Scenario 6: Evidence Download
| Step | Result | Notes |
|------|--------|-------|
| Hash visible | [ ] Pass [ ] Fail | |
| Download button works | [ ] Pass [ ] Fail | |

### Scenario 7: Kill Switch Denial
| Step | Result | Notes |
|------|--------|-------|
| Banner shown | [ ] Pass [ ] Fail | |
| Publish disabled | [ ] Pass [ ] Fail | |
| Lock disabled | [ ] Pass [ ] Fail | |

### Scenario 8: Session Expiry
| Step | Result | Notes |
|------|--------|-------|
| Redirect to login | [ ] Pass [ ] Fail | |
| No silent failure | [ ] Pass [ ] Fail | |

### Scenario 9: Role-Based Access
| Step | Result | Notes |
|------|--------|-------|
| Viewer cannot publish | [ ] Pass [ ] Fail | |
| Blocked reason shown | [ ] Pass [ ] Fail | |

### Scenario 10: Non-Wien Site
| Step | Result | Notes |
|------|--------|-------|
| Banner shown | [ ] Pass [ ] Fail | |
| Actions disabled | [ ] Pass [ ] Fail | |

---

## Issues Found

### Critical Issues (Blocking)
| ID | Description | Owner | Due Date |
|----|-------------|-------|----------|
| | | | |

### Minor Issues (Non-Blocking)
| ID | Description | Owner | Due Date |
|----|-------------|-------|----------|
| | | | |

---

## Artifact Links

| Artifact | Location |
|----------|----------|
| Test run logs | |
| Audit events | |
| Screenshots | |
| Evidence pack | |

---

## Comparison: UI vs CLI Artifacts

| Artifact | CLI Hash | UI Hash | Match |
|----------|----------|---------|-------|
| Publish audit event | | | [ ] |
| Lock audit event | | | [ ] |
| Evidence pack | | | [ ] |

---

## Sign-Off

### Testers
| Name | Role | Date | Signature |
|------|------|------|-----------|
| | Platform Engineer | | |
| | QA | | |

### Approvers
| Name | Role | Date | Result |
|------|------|------|--------|
| | Platform Lead | | [ ] Approved [ ] Rejected |
| | Product Owner | | [ ] Approved [ ] Rejected |

---

## Decision

- [ ] **APPROVED**: Proceed to Gate 2 (Prod Internal Enable)
- [ ] **REJECTED**: Fix issues and re-test

**Rejection Reason** (if applicable):
```
_______________________________________________
```

---

## Next Steps

1. [ ] Resolve any minor issues within 48 hours
2. [ ] Update RUNBOOK if needed
3. [ ] Schedule Gate 2 (Prod Internal Enable)

---

**Document Created**: _______________
**Last Updated**: _______________
