# Repair Operations Runbook

**Version**: 1.0
**Updated**: 2026-01-05
**Audience**: Dispatchers, Operations Team

---

## Overview

This runbook covers how to handle driver absences (sick calls) using the SOLVEREIGN Repair API. The goal is to reassign affected tours with minimal disruption (MIN_CHURN strategy).

---

## Decision Tree: Repair vs Re-Solve

```
                    Driver Absence Reported
                             |
                             v
              +-----------------------------+
              | How many drivers absent?    |
              +-----------------------------+
                     |              |
                  1-3             4+
                     |              |
                     v              v
              +----------+    +-----------+
              |  REPAIR  |    | RE-SOLVE  |
              +----------+    +-----------+
                     |              |
                     v              v
              Fast, low churn    Full optimization
              (~2-5 sec)         (~30 sec)
```

### When to REPAIR
- 1-3 drivers absent
- Tours within operational hours
- No major forecast changes
- Need quick turnaround

### When to RE-SOLVE
- 4+ drivers absent
- Major forecast changes
- Multiple constraint violations
- Time permits full optimization

---

## Repair Process: Step by Step

### Step 1: Identify Absent Drivers

**Get Driver IDs**:
1. Look up driver by name in system
2. Note the `driver_id` (integer)
3. Collect all absent driver IDs

**Example**:
```
Driver Name          | Driver ID
---------------------|----------
Max Mustermann       | 7
Anna Schmidt         | 12
Peter Mueller        | 23
```

### Step 2: Run Repair

**Via UI** (Preferred):
1. Go to "Planning" tab
2. Click "Repair Plan"
3. Enter absent driver IDs: `7, 12, 23`
4. Click "Execute Repair"

**Via API**:
```bash
curl -X POST /api/v1/plans/{plan_id}/repair \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: lts-transport-001" \
  -H "X-Idempotency-Key: repair-2026-01-05-001" \
  -d '{
    "absent_driver_ids": [7, 12, 23],
    "respect_freeze": true,
    "strategy": "MIN_CHURN",
    "time_budget_seconds": 60
  }'
```

### Step 3: Review Result

**Success Response**:
```json
{
  "status": "SUCCESS",
  "new_plan_version_id": 456,
  "tours_reassigned": 18,
  "drivers_affected": 5,
  "churn_rate": 0.013,
  "freeze_violations": 0
}
```

**Key Metrics to Check**:
| Metric | Target | Action if Exceeded |
|--------|--------|-------------------|
| tours_reassigned | <30 | Review assignments |
| churn_rate | <5% | Acceptable |
| freeze_violations | 0 | See Freeze section |

### Step 4: Verify New Plan

1. Check new plan version in UI
2. Verify affected tours reassigned
3. Confirm all audits still PASS
4. Notify affected drivers

---

## Error Handling

### Error: INSUFFICIENT_ELIGIBLE_DRIVERS

**Meaning**: Not enough available drivers to cover tours.

**Immediate Actions**:
1. Check standby pool (on-call drivers)
2. Contact standby drivers
3. Update availability to AVAILABLE
4. Re-run repair

**Standby Protocol**:
```
1. Call standby driver
2. Confirm availability
3. In system: Set availability to AVAILABLE
4. Re-run repair
5. If still fails: Escalate
```

**Escalation Path**:
- Contact Operations Manager
- Options:
  - Approve overtime for existing drivers
  - Cancel low-priority tours
  - External staffing agency

### Error: Frozen Tours Cannot Change

**Meaning**: Some tours are within 12h freeze window.

**Options**:
1. **Accept partial repair**: Only non-frozen tours reassigned
2. **Override freeze**: Set `respect_freeze: false` (requires approval)
3. **Manual dispatch**: Handle frozen tours manually

**Override Freeze (requires APPROVER)**:
```bash
curl -X POST /api/v1/plans/{plan_id}/repair \
  -d '{
    "absent_driver_ids": [7],
    "respect_freeze": false,  # REQUIRES APPROVAL
    "strategy": "MIN_CHURN"
  }'
```

### Error: 409 Conflict (Concurrent Repair)

**Meaning**: Another repair is in progress.

**Action**:
1. Wait 30 seconds
2. Retry
3. If persists: Contact IT

### Error: Invalid Driver IDs

**Meaning**: Driver ID not found in system.

**Action**:
1. Verify driver exists in master data
2. Check for typos
3. Ensure driver is active

---

## Quick Reference Cards

### Repair Decision Matrix

| Scenario | Action | Notes |
|----------|--------|-------|
| 1 driver sick, morning | REPAIR | Fast, low impact |
| 2 drivers sick, same depot | REPAIR | May need standby |
| 3 drivers sick, different depots | REPAIR | Higher churn expected |
| 4+ drivers sick | RE-SOLVE | Full optimization needed |
| Driver sick + tour cancellations | RE-SOLVE | Multiple changes |
| Frozen tour affected | MANUAL or OVERRIDE | Needs approval |

### Churn Rate Guide

| Churn Rate | Assessment | Action |
|------------|------------|--------|
| <2% | Excellent | Proceed |
| 2-5% | Good | Proceed |
| 5-10% | Acceptable | Review |
| >10% | High | Consider re-solve |

### Time Budget Guide

| Absent Drivers | Expected Time | Max Retries |
|----------------|---------------|-------------|
| 1-2 | 2-5 sec | 2 |
| 3-5 | 5-15 sec | 2 |
| 5-10 | 15-30 sec | 1 |
| >10 | Not recommended | - |

---

## Post-Repair Checklist

After successful repair:

- [ ] New plan version created
- [ ] All audits PASS
- [ ] Affected drivers notified
- [ ] Document in incident log
- [ ] Update roster if needed

---

## Incident Log Template

```
Date: _______________
Time Reported: _______________
Reporter: _______________

Absent Drivers:
  ID: _____ Name: _______________
  ID: _____ Name: _______________
  ID: _____ Name: _______________

Action Taken: [ ] REPAIR  [ ] RE-SOLVE  [ ] MANUAL

Result:
  Status: [ ] SUCCESS  [ ] FAILED
  Tours Reassigned: _____
  Churn Rate: _____%
  New Plan ID: _____

Notes:
_________________________________
_________________________________

Resolved By: _______________
Time Resolved: _______________
```

---

## FAQ

### Q: Can I repair a LOCKED plan?
**A**: No. Locked plans are immutable. Repair creates a NEW plan version.

### Q: What if repair fails completely?
**A**: Document the failure, escalate to Operations Manager, consider manual dispatch for critical tours.

### Q: How do I know which tours were affected?
**A**: Compare the old and new plan versions. The `tours_reassigned` count tells you how many changed.

### Q: Can I undo a repair?
**A**: No direct undo. You can re-run repair with different parameters or re-solve entirely.

### Q: What's the maximum absent drivers for repair?
**A**: Recommended max is 10. For more, use re-solve.

---

## Emergency Contacts

| Role | Contact | When to Call |
|------|---------|--------------|
| Operations Manager | [Phone] | Approval needed, major incidents |
| IT Support | [Phone] | System issues |
| Standby Pool Lead | [Phone] | Need additional drivers |
| SOLVEREIGN Support | [Email] | System errors |

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-05 | Initial release |
