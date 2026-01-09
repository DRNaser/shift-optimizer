# UAT: Dispatcher Cockpit MVP

> **Version**: V3.7 Wien Pilot
> **Status**: Ready for UAT
> **Duration**: ~1 hour
> **Prerequisites**: Staging access, platform_admin or dispatcher role

---

## Overview

This UAT validates that the Dispatcher Cockpit UI can fully replace the CLI for Wien weekly operations.

**Acceptance Criteria**:
1. UI produces identical audit events as CLI
2. Evidence hash linkage is preserved
3. Kill switch and site gates are enforced
4. Approval workflow requires human confirmation

---

## Pre-UAT Checklist

| Item | Check |
|------|-------|
| Staging deployed with `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT=true` | [ ] |
| At least one solver run exists in staging | [ ] |
| Platform session valid (login to staging) | [ ] |
| CLI available as fallback | [ ] |

---

## Test Scenarios

### Scenario 1: Runs List Page

**Steps**:
1. Navigate to `/runs` in staging
2. Verify page loads with "Solver Runs" heading
3. Verify "Wien Site • LTS Tenant" shown
4. Verify run cards display with status badges

**Expected Results**:
- [ ] Page loads in < 2s
- [ ] Status badges visible (PASS/WARN/FAIL)
- [ ] KPIs shown (headcount, runtime, audits)
- [ ] Filter dropdown works
- [ ] Refresh button works

**Notes**:
```
_______________________________________________
```

---

### Scenario 2: Run Detail Page

**Steps**:
1. Click on any run card from list
2. Verify navigation to `/runs/[id]`
3. Verify all sections load

**Expected Results**:
- [ ] KPI cards: Total Drivers, Coverage, Runtime, Max Hours
- [ ] Audit Results section with 7 checks
- [ ] Evidence Hash displayed (if available)
- [ ] Actions section visible

**Notes**:
```
_______________________________________________
```

---

### Scenario 3: Publish Flow (Happy Path)

**Prerequisites**: Run in DRAFT state with PASS audits

**Steps**:
1. Navigate to a DRAFT run
2. Click "Publish Run" button
3. Enter approval reason (min 10 chars)
4. Click "Publish"
5. Verify success

**Expected Results**:
- [ ] Modal opens with approval reason field
- [ ] Confirm button disabled until reason >= 10 chars
- [ ] Publish succeeds
- [ ] Run state changes to "published"
- [ ] Published timestamp shown

**Audit Event Capture**:
```
Approver ID: _______________
Reason: _______________
Timestamp: _______________
Evidence Hash: _______________
```

---

### Scenario 4: Lock Flow (Happy Path)

**Prerequisites**: Run in PUBLISHED state

**Steps**:
1. Navigate to a PUBLISHED run
2. Click "Lock Run" button
3. Enter approval reason (min 10 chars)
4. Click "Lock"
5. Verify success

**Expected Results**:
- [ ] Modal opens with approval reason field
- [ ] Lock succeeds
- [ ] Run state changes to "locked"
- [ ] Locked timestamp shown
- [ ] Publish/Lock buttons disabled

**Audit Event Capture**:
```
Approver ID: _______________
Reason: _______________
Timestamp: _______________
Evidence Hash: _______________
```

---

### Scenario 5: Repair Request

**Steps**:
1. Navigate to any run
2. Click "Request Repair" button
3. Fill form:
   - Driver ID: `D001`
   - Driver Name: `Test Driver`
   - Absence Type: `Sick Call`
   - Affected Tours: `T001, T002`
   - Urgency: `High`
4. Click "Submit Request"

**Expected Results**:
- [ ] Form opens with all fields
- [ ] Validation enforces required fields
- [ ] Submit succeeds
- [ ] Confirmation message shown

**Notes**:
```
_______________________________________________
```

---

### Scenario 6: Evidence Download

**Prerequisites**: Run in LOCKED state with evidence

**Steps**:
1. Navigate to a LOCKED run
2. Verify evidence hash displayed
3. Click "Download Evidence"

**Expected Results**:
- [ ] Evidence hash visible
- [ ] Download button present
- [ ] Download starts (or URL provided)

**Downloaded Artifact**:
```
Filename: _______________
Size: _______________
Hash verified: [ ] Yes [ ] No
```

---

### Scenario 7: Kill Switch Denial

**Prerequisites**: Kill switch activated in staging

**Steps**:
1. Activate kill switch via CLI or backend
2. Navigate to `/runs`
3. Verify kill switch banner
4. Try to publish a run

**Expected Results**:
- [ ] "KILL SWITCH ACTIVE" badge shown (pulsing red)
- [ ] "Kill Switch Active" banner displayed
- [ ] Publish button disabled
- [ ] Lock button disabled
- [ ] Reason: "Kill switch is active"

**Notes**:
```
_______________________________________________
```

---

### Scenario 8: Session Expiry

**Steps**:
1. Clear cookies or wait for session to expire
2. Navigate to `/runs`

**Expected Results**:
- [ ] Redirected to `/platform/login`
- [ ] No silent failure
- [ ] After re-login, returns to runs page

---

### Scenario 9: Role-Based Access

**Steps**:
1. Login as `platform_viewer` role
2. Navigate to a run detail
3. Try to publish/lock

**Expected Results**:
- [ ] Publish button disabled or hidden
- [ ] Lock button disabled or hidden
- [ ] Blocked reason shown: "Insufficient permissions"
- [ ] Repair request may be allowed (read-only otherwise)

---

### Scenario 10: Non-Wien Site

**Steps**:
1. Navigate to `/runs?site=graz`
2. Verify site not enabled banner

**Expected Results**:
- [ ] "Site Not Enabled" banner shown
- [ ] Publish/Lock disabled
- [ ] Reason shown in UI

---

## Final Verification

### Comparison: UI vs CLI

| Action | CLI Command | UI Equivalent | Artifacts Match? |
|--------|------------|---------------|------------------|
| List runs | `dispatcher_cli.py list-runs --site wien` | `/runs` page | [ ] |
| Show run | `dispatcher_cli.py show-run <id>` | `/runs/<id>` page | [ ] |
| Publish | `dispatcher_cli.py publish <id>` | Publish button + modal | [ ] |
| Lock | `dispatcher_cli.py lock <id>` | Lock button + modal | [ ] |
| Repair | `dispatcher_cli.py repair <id>` | Request Repair form | [ ] |
| Evidence | `dispatcher_cli.py evidence <id>` | Download Evidence | [ ] |

### Audit Trail Verification

1. After UI publish/lock, check backend audit log
2. Verify same fields as CLI:
   - `approver_id`
   - `approver_role`
   - `reason`
   - `evidence_hash`
   - `timestamp`

**Audit Log Entry**:
```json
{
  "action": "",
  "approver_id": "",
  "approver_role": "",
  "reason": "",
  "evidence_hash": "",
  "timestamp": ""
}
```

---

## UAT Sign-Off

| Role | Name | Date | Result |
|------|------|------|--------|
| Tester | | | [ ] Pass [ ] Fail |
| Ops Lead | | | [ ] Pass [ ] Fail |
| Platform Admin | | | [ ] Pass [ ] Fail |

**Issues Found**:
```
_______________________________________________
_______________________________________________
```

**Recommendations**:
```
_______________________________________________
_______________________________________________
```

---

## Post-UAT Actions

- [ ] Fix any critical issues before rollout
- [ ] Update RUNBOOK with UI-specific steps
- [ ] Schedule production rollout (after burn-in day 30)
- [ ] Keep CLI as fallback

---

**UAT Completed**: [ ] Yes [ ] No
**Date**: _______________
**Signed By**: _______________
