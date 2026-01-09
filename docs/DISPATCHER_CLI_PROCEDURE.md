# Dispatcher CLI Procedure

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot Weekly Workflow
**Last Updated**: 2026-01-08

---

## Overview

This document describes the verified CLI procedure for completing the weekly dispatch workflow without direct database or SQL access.

**Tool**: `scripts/dispatcher_cli.py`

---

## Quick Reference

```bash
# Check system status
python scripts/dispatcher_cli.py status

# List latest runs
python scripts/dispatcher_cli.py list-runs

# Show run details
python scripts/dispatcher_cli.py show-run <run_id>

# Request sick-call repair
python scripts/dispatcher_cli.py request-repair --week 2026-W03 --driver D001 --name "Max Mustermann" --type sick --tours T1,T2,T3 --requester disp001

# Publish plan (requires approval)
python scripts/dispatcher_cli.py publish <run_id> --approver disp001 --role dispatcher --reason "Weekly plan reviewed and approved"

# Lock plan for export
python scripts/dispatcher_cli.py lock <run_id> --approver ops001 --role ops_lead --reason "Ready for dispatch system export"
```

---

## Weekly Workflow

### Monday: Review Solver Output

**Step 1**: Check system status
```bash
python scripts/dispatcher_cli.py status
```

Expected output:
```
==============================================================
SYSTEM STATUS - LTS/WIEN
==============================================================

Kill Switch:     ✅ Inactive
Publish Enabled: ✅ Yes
Lock Enabled:    ✅ Yes
Shadow Mode:     ✅ Disabled

--- Latest Run ---
Run ID:    RUN-20260113-001
Week:      2026-W03
Status:    ✅ PASS
Timestamp: 2026-01-13T08:00:00Z

--- Pending Repairs ---
No pending repairs
```

**Step 2**: List available runs
```bash
python scripts/dispatcher_cli.py list-runs
```

Expected output:
```
================================================================================
LATEST RUNS - LTS/WIEN
================================================================================

Status: ✅ PASS | ⚠️  WARN | ❌ FAIL | 🚫 BLOCKED | ⏳ PENDING

Run ID       Week       Status     Drivers  Coverage   Audits   Drift
--------------------------------------------------------------------------------
RUN-001      2026-W03   ✅ PASS    145      100.0%     7/7      OK
RUN-002      2026-W02   ✅ PASS    143      100.0%     7/7      OK
--------------------------------------------------------------------------------
```

**Step 3**: Review run details
```bash
python scripts/dispatcher_cli.py show-run RUN-20260113-001
```

---

### Monday-Tuesday: Handle Sick Calls

**If driver calls in sick**:

**Step 1**: Create repair request
```bash
python scripts/dispatcher_cli.py request-repair \
  --week 2026-W03 \
  --driver D042 \
  --name "Hans Schmidt" \
  --type sick \
  --tours T101,T102,T103 \
  --requester disp001 \
  --urgency high \
  --notes "Called in at 06:30, flu symptoms"
```

**Step 2**: Run repair solver (separate script)
```bash
python scripts/run_repair.py --request REP-20260113063000
```

**Step 3**: Review and apply repair

---

### Wednesday: Publish Plan

**Prerequisites**:
- Run status is PASS or WARN
- All sick calls resolved
- KPI drift within threshold

**Step 1**: Verify run is ready
```bash
python scripts/dispatcher_cli.py show-run RUN-20260113-001
```

Check:
- Status: PASS (or WARN with documented reason)
- Audits: 7/7
- Coverage: 100%
- Drift: OK or WARN (not BLOCK)

**Step 2**: Publish with approval
```bash
python scripts/dispatcher_cli.py publish RUN-20260113-001 \
  --approver disp001 \
  --role dispatcher \
  --reason "Week 2026-W03 plan reviewed. All audits pass, KPIs within threshold. No pending repairs."
```

**If blocked**:
- Check blocked reason in output
- If kill switch active, contact platform admin
- If approval invalid, verify your role and reason length (min 10 chars)

---

### Thursday: Lock for Export

**After publish approved**:

**Step 1**: Lock the plan
```bash
python scripts/dispatcher_cli.py lock RUN-20260113-001 \
  --approver ops001 \
  --role ops_lead \
  --reason "Approved for export to dispatch system. Week 2026-W03 finalized."
```

**After lock**:
- Plan is immutable
- Evidence pack is sealed
- Ready for export to dispatch system

---

## Decision Tree

```
                    ┌─────────────────┐
                    │   Run Status?   │
                    └────────┬────────┘
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
        ┌──▼──┐          ┌───▼───┐         ┌───▼───┐
        │PASS │          │ WARN  │         │FAIL/  │
        │     │          │       │         │BLOCKED│
        └──┬──┘          └───┬───┘         └───┬───┘
           │                 │                 │
           │            Review warnings        │
           │            Document reason        ▼
           │                 │           Cannot publish
           ▼                 ▼           Fix issues or
      Can publish       Can publish      escalate
      directly          with override
           │                 │
           └────────┬────────┘
                    │
            ┌───────▼───────┐
            │   Sick calls? │
            └───────┬───────┘
                    │
            ┌───────┴───────┐
            │               │
           Yes              No
            │               │
            ▼               │
       Run repair           │
       Apply fix            │
            │               │
            └───────┬───────┘
                    │
            ┌───────▼───────┐
            │   PUBLISH     │
            │ (with approval)│
            └───────┬───────┘
                    │
            ┌───────▼───────┐
            │    LOCK       │
            │ (for export)  │
            └───────────────┘
```

---

## Error Handling

### Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | Success | Continue workflow |
| 1 | Operation failed | Check error message, retry |
| 2 | Blocked by gate | Check blocked reason, escalate if needed |

### Common Errors

**"Kill switch is active"**
- Emergency disable is active
- Contact platform admin
- Do not attempt to bypass

**"Approval required but not provided"**
- Missing --approver, --role, or --reason
- Add all required flags

**"Approver role not in allowed roles"**
- Your role is not authorized for this operation
- Contact ops_lead or platform_admin

**"Reason must be at least 10 characters"**
- Provide more detailed reason
- Document why plan is being approved

**"Site is in shadow-only mode"**
- Publish not enabled for this site
- Contact platform admin to enable

---

## Evidence and Audit Trail

Every publish/lock operation creates:

1. **Audit Event**: Immutable record with:
   - Timestamp
   - Approver ID and role
   - Reason
   - Evidence hash
   - Plan version ID

2. **Evidence Hash**: SHA256 of evidence pack contents

3. **Updated Run Record**: Run file updated with:
   - `published: true/false`
   - `published_at: timestamp`
   - `published_by: approver_id`
   - `locked: true/false`
   - `locked_at: timestamp`
   - `locked_by: approver_id`

---

## Emergency Procedures

### Kill Switch Activation

If security incident detected:
```bash
python -m backend_py.api.services.publish_gate kill-switch \
  --activate \
  --by platform_admin \
  --reason "Security incident: cross-tenant data exposure suspected"
```

This immediately blocks ALL publish/lock operations.

### Kill Switch Deactivation

After incident resolved:
```bash
python -m backend_py.api.services.publish_gate kill-switch \
  --deactivate \
  --by platform_admin \
  --reason "Incident resolved, RLS verified"
```

---

## Support Contacts

| Issue | Contact |
|-------|---------|
| System errors | Platform Engineering |
| Kill switch active | Platform Admin |
| Approval questions | Ops Lead |
| Solver issues | Platform Engineering |

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08
