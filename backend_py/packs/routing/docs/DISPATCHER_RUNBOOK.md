# SOLVEREIGN Routing Pack - Dispatcher Runbook

> **Version**: 1.0 (Gate 6 Pilot)
> **Last Updated**: 2026-01-06
> **Status**: APPROVED for Pilot

---

## Overview

This runbook covers daily operations for dispatchers using SOLVEREIGN Routing Pack.
It includes both **Happy Path** (normal operations) and **Failure Path** (incident handling).

---

## 1. Daily Planning Workflow (Happy Path)

### 1.1 Morning Start (06:00 - 07:00)

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Import FLS Data                                        │
├─────────────────────────────────────────────────────────────────┤
│  • Export CSV from FLS (File → Export → Daily Orders)           │
│  • Verify format: UTF-8, Semicolon delimiter                    │
│  • Upload to SOLVEREIGN: POST /api/v1/routing/scenarios         │
│  • Expected: Status = INGESTED                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Validate Import                                        │
├─────────────────────────────────────────────────────────────────┤
│  • Check validation report in UI                                │
│  • GREEN (✓): All stops parsed successfully                     │
│  • YELLOW (⚠): Warnings - review but continue                   │
│  • RED (✗): Errors - fix in FLS and re-import                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Trigger Solve                                          │
├─────────────────────────────────────────────────────────────────┤
│  • Click "Solve" button (or POST /solve)                        │
│  • Wait for solver (typically 30-120 seconds)                   │
│  • Monitor progress bar                                         │
│  • Expected: Status = SOLVED                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: Review Audit Results                                   │
├─────────────────────────────────────────────────────────────────┤
│  • All audits should PASS:                                      │
│    - Coverage: 100% stops assigned (or justified unassigned)    │
│    - Overlap: No driver double-booked                           │
│    - Time Windows: All deliveries within windows                │
│    - Capacity: No vehicle overloaded                            │
│    - Skills: All requirements met                               │
│  • Expected: Status = AUDITED                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 5: Review Plan                                            │
├─────────────────────────────────────────────────────────────────┤
│  • Open Plan Preview (matrix view)                              │
│  • Check vehicle utilization                                    │
│  • Review unassigned stops (if any)                             │
│  • Verify high-priority stops are scheduled early               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 6: Lock & Publish                                         │
├─────────────────────────────────────────────────────────────────┤
│  • Click "Lock Plan" (requires APPROVER role)                   │
│  • Plan becomes immutable                                       │
│  • Evidence Pack generated automatically                        │
│  • Routes sent to driver apps (if integrated)                   │
│  • Expected: Status = LOCKED                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Checkpoints

| Time | Action | Expected State |
|------|--------|----------------|
| 06:00 | FLS Export | CSV ready |
| 06:15 | Import complete | INGESTED |
| 06:30 | Solve complete | SOLVED |
| 06:45 | Audit review | AUDITED |
| 07:00 | Plan locked | LOCKED |
| 07:15 | Drivers briefed | Routes assigned |

### 1.3 API Workflow

```bash
# Step 1: Create scenario
curl -X POST "$API_URL/api/v1/routing/scenarios" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d @scenario_payload.json

# Response: {"scenario_id": "scn-123", "status": "INGESTED"}

# Step 2: Trigger solve
curl -X POST "$API_URL/api/v1/routing/scenarios/scn-123/solve" \
  -H "X-API-Key: $API_KEY" \
  -d '{"seed": 94}'

# Response: {"job_id": "job-456", "status": "QUEUED"}

# Step 3: Poll for completion
curl "$API_URL/api/v1/routing/jobs/job-456" \
  -H "X-API-Key: $API_KEY"

# Response: {"status": "SUCCESS", "plan_id": "plan-789"}

# Step 4: Get plan with audit results
curl "$API_URL/api/v1/routing/plans/plan-789" \
  -H "X-API-Key: $API_KEY"

# Step 5: Lock plan
curl -X POST "$API_URL/api/v1/routing/plans/plan-789/lock" \
  -H "X-API-Key: $API_KEY"

# Response: {"status": "LOCKED", "locked_at": "..."}

# Step 6: Download evidence
curl "$API_URL/api/v1/routing/plans/plan-789/evidence" \
  -H "X-API-Key: $API_KEY" \
  -o evidence_plan_789.zip
```

---

## 2. Intraday Changes (Repair Flow)

### 2.1 NO_SHOW Handling

**Scenario**: Customer not available at delivery time.

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Receive No-Show Report                                 │
├─────────────────────────────────────────────────────────────────┤
│  • Driver reports via app: "Customer not home"                  │
│  • Note stop ID and time                                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Trigger Repair                                         │
├─────────────────────────────────────────────────────────────────┤
│  POST /api/v1/routing/plans/{plan_id}/repair                    │
│  {                                                              │
│    "event_type": "NO_SHOW",                                     │
│    "stop_id": "STOP_123",                                       │
│    "reason": "Customer not home - rescheduled to tomorrow"      │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Review Repair Result                                   │
├─────────────────────────────────────────────────────────────────┤
│  • Check churn score (should be minimal)                        │
│  • Verify frozen stops unchanged                                │
│  • Review any reassignments                                     │
│  • Confirm with driver(s) affected                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: Apply Repair                                           │
├─────────────────────────────────────────────────────────────────┤
│  • Click "Apply Repair" (or POST /apply)                        │
│  • New plan version created                                     │
│  • Original plan archived (not modified)                        │
│  • New evidence pack generated                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 VEHICLE_DOWN Handling

**Scenario**: Vehicle breaks down during route.

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Receive Breakdown Report                               │
├─────────────────────────────────────────────────────────────────┤
│  • Driver reports: "Van won't start" / "Flat tire"              │
│  • Get vehicle ID, location, remaining stops                    │
│  • Assess severity: Can it be repaired quickly?                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Trigger Repair (if cannot fix quickly)                 │
├─────────────────────────────────────────────────────────────────┤
│  POST /api/v1/routing/plans/{plan_id}/repair                    │
│  {                                                              │
│    "event_type": "VEHICLE_DOWN",                                │
│    "vehicle_id": "VAN_05",                                      │
│    "reason": "Engine failure - towing arranged"                 │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Review Reassignment Options                            │
├─────────────────────────────────────────────────────────────────┤
│  System will suggest:                                           │
│  • Option A: Reassign to available vehicles                     │
│  • Option B: Mark as unassigned (for tomorrow)                  │
│  • Option C: Call in backup vehicle                             │
│                                                                 │
│  Review churn impact:                                           │
│  • Stops moved: X                                               │
│  • Total churn score: Y                                         │
│  • ETA impacts: Z                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: Notify Affected Drivers                                │
├─────────────────────────────────────────────────────────────────┤
│  • Send route updates to receiving drivers                      │
│  • Confirm they can accept additional stops                     │
│  • Update customer ETAs if needed                               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Churn Thresholds

| Churn Score | Classification | Action Required |
|-------------|----------------|-----------------|
| 0 - 5,000 | LOW | Auto-approve |
| 5,001 - 20,000 | MEDIUM | Dispatcher review |
| 20,001 - 50,000 | HIGH | Supervisor approval |
| > 50,000 | CRITICAL | Operations manager |

---

## 3. Failure Scenarios

### 3.1 Import Failures

#### Error: "REJECT - Missing Coordinates"

**Cause**: FLS export contains stops without geocoded addresses.

**Resolution**:
1. Open FLS, go to affected orders
2. Click "Geocode" or enter coordinates manually
3. Re-export CSV
4. Re-import to SOLVEREIGN

```
Example Error:
{
  "status": "REJECTED",
  "errors": [
    {"line": 45, "field": "lat", "error": "Missing or invalid latitude"},
    {"line": 45, "field": "lng", "error": "Missing or invalid longitude"}
  ]
}
```

#### Error: "REJECT - Invalid Time Window"

**Cause**: Time window end is before start, or invalid format.

**Resolution**:
1. Check tw_start and tw_end columns in FLS
2. Ensure format: ISO8601 with timezone (e.g., `2026-01-06T10:00:00+01:00`)
3. Ensure end > start
4. Re-export and re-import

### 3.2 Solver Failures

#### Error: "TIMEOUT - No solution found"

**Cause**: Problem too complex, or impossible constraints.

**Resolution**:
1. Check for conflicting time windows
2. Check for impossible skill requirements
3. Add more vehicles if capacity insufficient
4. Relax soft constraints (contact supervisor)

```
Checklist:
□ Total stops < vehicle capacity × num_vehicles?
□ All required skills available on at least one vehicle?
□ Time windows feasible given travel times?
□ 2-Mann stops have 2-Mann teams available?
```

#### Error: "INFEASIBLE - No valid assignment"

**Cause**: Hard constraints cannot all be satisfied.

**Resolution**:
1. Identify which stops are causing infeasibility
2. Check unassigned list for specific reasons:
   - `NO_CAPACITY`: Add vehicles
   - `NO_SKILL_MATCH`: Assign different team
   - `TW_IMPOSSIBLE`: Contact customer for TW change
   - `DISTANCE_EXCEED`: Customer too far

### 3.3 Audit Failures

#### Error: "AUDIT FAIL - Coverage below 100%"

**Cause**: Some stops could not be assigned.

**Resolution**:
1. Review unassigned stops list
2. For each unassigned stop:
   - Check reason code
   - Attempt manual assignment
   - Or mark for next-day delivery
3. Document decisions in notes
4. Escalate if > 5% unassigned

#### Error: "AUDIT FAIL - Overlap detected"

**Cause**: Solver bug or data corruption.

**Resolution**:
1. This should NEVER happen in production
2. Take screenshot of error
3. Contact tech support immediately
4. Do NOT lock the plan
5. Fallback to previous day's plan pattern

### 3.4 Lock Failures

#### Error: "FORBIDDEN - Insufficient permissions"

**Cause**: User lacks APPROVER role.

**Resolution**:
1. Contact supervisor to lock plan, OR
2. Request APPROVER role from admin

#### Error: "CONFLICT - Plan already locked"

**Cause**: Another user locked the plan.

**Resolution**:
1. Check who locked (see locked_by field)
2. Contact them if need to modify
3. For changes, use Repair flow (creates new version)

---

## 4. Escalation Matrix

| Issue Type | First Contact | Escalation | SLA |
|------------|---------------|------------|-----|
| Import errors | Dispatcher fixes | IT Support | 30 min |
| Solver timeout | Supervisor | Tech Support | 1 hour |
| Audit failures | Supervisor | Operations Manager | 1 hour |
| System down | IT Support | On-call Engineer | 15 min |
| Data breach suspect | IT Security | CISO | Immediate |

### Contact Information

| Role | Contact | Phone |
|------|---------|-------|
| IT Support | support@lts.de | ext. 1000 |
| Tech Support | routing@solvereign.de | +49-XXX-XXXXX |
| Operations Manager | ops@lts.de | ext. 2000 |
| On-call Engineer | oncall@solvereign.de | +49-XXX-XXXXX |

---

## 5. Daily Checklist

### Morning (Before 07:00)

- [ ] FLS export downloaded
- [ ] CSV validation passed
- [ ] Import to SOLVEREIGN successful
- [ ] Solver completed without timeout
- [ ] All audits PASS
- [ ] Plan reviewed and approved
- [ ] Plan LOCKED
- [ ] Evidence pack downloaded
- [ ] Drivers briefed

### Evening (After 18:00)

- [ ] All routes completed or exceptions documented
- [ ] No-shows recorded for rescheduling
- [ ] Repair events documented
- [ ] KPIs reviewed:
  - [ ] On-time delivery %
  - [ ] Stops per vehicle
  - [ ] Total distance
- [ ] Next-day FLS data prepared

---

## 6. Rollback Procedures

### If SOLVEREIGN is unavailable:

1. **Immediate**: Use yesterday's routes as template
2. **Short-term**: Manual Excel planning (backup spreadsheet)
3. **Contact**: Tech support for ETA

### If plan is locked but needs changes:

1. Use Repair API to create new version
2. Lock new version
3. Archive old version (automatic)

### If audit failures cannot be resolved:

1. Document all unassigned stops
2. Manual assignment with supervisor approval
3. Create incident report
4. Post-mortem within 24 hours

---

## Appendix A: Status Reference

| Status | Meaning | Next Action |
|--------|---------|-------------|
| INGESTED | Data imported | Run validation |
| VALIDATED | Validation passed | Trigger solve |
| SOLVING | Solver running | Wait |
| SOLVED | Solution found | Review audit |
| AUDITED | All audits passed | Review plan |
| DRAFT | Ready for approval | Lock when ready |
| LOCKED | Plan finalized | Publish to drivers |
| FAILED | Error occurred | Check logs, retry |

## Appendix B: Glossary

- **FLS**: Fleet Logistics System (source of order data)
- **Churn**: Measure of route disruption during repair
- **Freeze Window**: Time before stop when it cannot be moved
- **Evidence Pack**: Audit trail ZIP with all plan details
- **2-Mann**: Two-person delivery team requirement

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-06 | SOLVEREIGN | Initial pilot version |
