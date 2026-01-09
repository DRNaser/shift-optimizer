# Rollback & Break-Glass Fire Drill Procedure

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot Burn-In Period
**Version**: 1.0.0
**Last Updated**: 2026-01-08

---

## Purpose

This procedure defines how to conduct controlled fire drills to verify rollback and break-glass capabilities work correctly without impacting production operations.

**Goal**: Prove that the kill switch provides instant rollback capability and is fully auditable.

---

## Fire Drill Schedule

| Drill | Frequency | Participants | Duration |
|-------|-----------|--------------|----------|
| Kill Switch Test | Weekly (burn-in) | Platform Eng + Ops | 15 min |
| Full Break-Glass | Monthly | All stakeholders | 30 min |
| Recovery Exercise | Quarterly | Full team | 1 hour |

---

## Pre-Drill Requirements

Before starting any fire drill:

- [ ] Notify all stakeholders (Slack/email)
- [ ] Confirm no active publish/lock operations in progress
- [ ] Document drill start time
- [ ] Assign drill observer (separate from executor)

---

## Drill Type A: Kill Switch Test (Weekly)

### Objective
Verify kill switch instantly blocks all publish/lock operations and is auditable.

### Procedure

**Step 1: Pre-Drill Status Check**
```bash
# Check current status
python scripts/dispatcher_cli.py status

# Expected: Kill Switch: ✅ Inactive
```

Record:
- [ ] Pre-drill status: ______________
- [ ] Timestamp: ______________

**Step 2: Activate Kill Switch**
```bash
# Activate kill switch
python -m backend_py.api.services.publish_gate kill-switch \
  --activate \
  --by "<your_user_id>" \
  --reason "Fire drill - weekly kill switch test"
```

Record:
- [ ] Activation timestamp: ______________
- [ ] Activated by: ______________

**Step 3: Verify Block**
```bash
# Attempt publish on Wien (should be blocked)
python scripts/dispatcher_cli.py --site wien publish TEST-DRILL-001 \
  --approver drill_user \
  --role dispatcher \
  --reason "Fire drill test - should be blocked"
```

**Expected output**: ❌ PUBLISH BLOCKED - Kill switch is active

Record:
- [ ] Wien publish blocked: Yes / No
- [ ] Block reason matches: Yes / No

**Step 4: Verify Shadow Mode Still Works**
```bash
# Check system status (should show shadow mode available)
python scripts/dispatcher_cli.py status

# Run a solver (should work, just can't publish)
python scripts/run_parallel_week.py --input test_data.json --week TEST-W00 --dry-run
```

Record:
- [ ] Shadow mode operational: Yes / No
- [ ] Solver still runs: Yes / No

**Step 5: Verify Audit Trail**
```bash
# Check audit events
python -m backend_py.api.services.publish_gate status
```

Record:
- [ ] KILL_SWITCH_ACTIVATED event exists: Yes / No
- [ ] Event has correct operator identity: Yes / No
- [ ] Event has timestamp: Yes / No

**Step 6: Deactivate Kill Switch**
```bash
# Deactivate kill switch
python -m backend_py.api.services.publish_gate kill-switch \
  --deactivate \
  --by "<your_user_id>" \
  --reason "Fire drill complete - restoring normal operations"
```

Record:
- [ ] Deactivation timestamp: ______________
- [ ] Deactivated by: ______________

**Step 7: Verify Restore**
```bash
# Check status restored
python scripts/dispatcher_cli.py status

# Expected: Kill Switch: ✅ Inactive
```

Record:
- [ ] Status restored: Yes / No
- [ ] Wien publish enabled: Yes / No

**Step 8: Verify Deactivation Audit**

Record:
- [ ] KILL_SWITCH_DEACTIVATED event exists: Yes / No
- [ ] Event has correct operator identity: Yes / No

### Drill Complete

| Metric | Result |
|--------|--------|
| Kill switch activated successfully | ✅ / ❌ |
| Publish blocked immediately | ✅ / ❌ |
| Shadow mode continued working | ✅ / ❌ |
| Audit trail captured | ✅ / ❌ |
| Kill switch deactivated successfully | ✅ / ❌ |
| Normal operations restored | ✅ / ❌ |
| No deploy or DB changes required | ✅ / ❌ |

**Drill Duration**: ______ minutes

---

## Drill Type B: Non-Wien Site Block Test

### Objective
Verify non-Wien sites remain blocked regardless of kill switch state.

### Procedure

**Step 1: Attempt Publish on Non-Wien Site**
```bash
# Try Munich (not enabled)
python scripts/dispatcher_cli.py --site munich publish TEST-MUNICH-001 \
  --approver drill_user \
  --role dispatcher \
  --reason "Fire drill - should be blocked for non-Wien"
```

**Expected**: ❌ BLOCKED_SHADOW_ONLY

**Step 2: Try Another Site**
```bash
# Try Berlin (not enabled)
python scripts/dispatcher_cli.py --site berlin publish TEST-BERLIN-001 \
  --approver drill_user \
  --role dispatcher \
  --reason "Fire drill - should be blocked for non-Wien"
```

**Expected**: ❌ BLOCKED_SHADOW_ONLY

**Step 3: Verify Wien Still Works (if kill switch inactive)**
```bash
# Wien should work when kill switch is off
python scripts/dispatcher_cli.py status
# Verify: Publish Enabled: ✅ Yes for Wien
```

### Drill Complete

| Metric | Result |
|--------|--------|
| Munich blocked | ✅ / ❌ |
| Berlin blocked | ✅ / ❌ |
| Wien enabled (when kill switch off) | ✅ / ❌ |

---

## Drill Type C: Break-Glass Usage Test (Monthly)

### Objective
Verify break-glass creates incident record and captures all required audit information.

### Procedure

**Step 1: Simulate Break-Glass Need**

Document scenario:
```
Scenario: [Describe hypothetical emergency]
Example: "Critical repair needed outside normal hours,
         regular approver unavailable"
```

**Step 2: Execute Break-Glass (Controlled)**
```bash
# Create incident for break-glass usage
python scripts/generate_burnin_report.py create-incident \
  --severity S2 \
  --title "Fire drill - break-glass test" \
  --description "Monthly fire drill testing break-glass audit trail" \
  --source BREAK_GLASS \
  --owner "<your_user_id>"
```

Record:
- [ ] Incident ID: ______________
- [ ] Created timestamp: ______________

**Step 3: Verify Incident Created**
```bash
# List incidents
python scripts/generate_burnin_report.py list-incidents
```

Record:
- [ ] Incident appears in list: Yes / No
- [ ] Severity correct (S2): Yes / No
- [ ] Source shows BREAK_GLASS: Yes / No

**Step 4: Close Fire Drill Incident**
```bash
# Resolve the drill incident
python scripts/generate_burnin_report.py resolve-incident \
  --id <incident_id> \
  --resolution "Fire drill complete - no actual break-glass usage"
```

### Drill Complete

| Metric | Result |
|--------|--------|
| Break-glass incident created | ✅ / ❌ |
| Incident has correct metadata | ✅ / ❌ |
| Incident resolution works | ✅ / ❌ |

---

## Fire Drill Record Template

```markdown
## Fire Drill Record

**Drill ID**: FD-YYYY-NNN
**Date**: YYYY-MM-DD
**Type**: Kill Switch / Non-Wien Block / Break-Glass
**Executor**: [Name]
**Observer**: [Name]

### Timeline
| Time | Action | Result |
|------|--------|--------|
| HH:MM | [action] | [result] |

### Findings
- [ ] All expected behaviors observed
- [ ] No unexpected side effects
- [ ] Audit trail complete

### Issues (if any)
[Document any issues discovered]

### Sign-Off
- Executor: _____________ Date: _____
- Observer: _____________ Date: _____
```

---

## Post-Drill Actions

### Immediate (within 1 hour)

1. [ ] Complete drill record
2. [ ] Close any test incidents
3. [ ] Verify system back to normal state
4. [ ] Notify stakeholders drill complete

### Follow-Up (within 1 day)

1. [ ] Review audit trail completeness
2. [ ] Document any issues in backlog
3. [ ] Update drill procedure if needed
4. [ ] Schedule next drill

---

## Acceptance Criteria

A fire drill is successful if:

1. **Instant Rollback**: Kill switch activates/deactivates immediately (< 5 seconds)
2. **No Deploy Required**: Toggle is config-only, no deployment needed
3. **No DB Changes**: No database modifications required
4. **Auditable**: All actions captured in audit trail with operator identity
5. **Wien-Specific**: Only Wien site affected by publish enablement
6. **Shadow Continues**: Solver still runs in shadow mode during kill switch

---

## Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Platform Lead | [contact] | Primary |
| Ops Lead | [contact] | Secondary |
| Security | [contact] | Security issues |

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08

**Next Scheduled Drill**: [DATE]
