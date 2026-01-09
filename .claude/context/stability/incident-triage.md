# Incident Triage Procedures

> **Purpose**: Structured incident response and investigation
> **Last Updated**: 2026-01-07

---

## INCIDENT LIFECYCLE

```
NEW → ACTIVE → INVESTIGATING → MITIGATED → RESOLVED
                    ↓
                  STALE (if no activity >10min)
```

### State Transitions

| From | To | Trigger |
|------|-----|---------|
| NEW | ACTIVE | First responder assigned |
| ACTIVE | INVESTIGATING | Root cause investigation started |
| INVESTIGATING | MITIGATED | Immediate fix applied |
| MITIGATED | RESOLVED | Root cause fixed, verified |
| * | STALE | No activity for 10 minutes |
| STALE | ACTIVE | New activity/event |
| STALE (>30min) | AUTO_CLOSE_CANDIDATE | Health recovered |

---

## SEVERITY CLASSIFICATION

### S1 - CRITICAL

**Definition**: System down, data at risk, all tenants affected

**Examples**:
- Database unreachable
- Cross-tenant data leak
- All API pods down
- Authentication completely broken

**Response**:
- Immediate all-hands response
- Block ALL changes
- Notify stakeholders immediately
- 15-minute status updates

### S2 - HIGH

**Definition**: Major feature broken, single tenant severely affected

**Examples**:
- Solver producing invalid results
- Writes blocked for one tenant
- Significant data corruption
- Auth failures for specific users

**Response**:
- Response within 30 minutes
- Block writes if data at risk
- Notify affected tenants
- 30-minute status updates

### S3 - MEDIUM

**Definition**: Feature degraded, workaround available

**Examples**:
- Slow response times (p95 > 500ms)
- Non-critical API errors
- UI glitches
- Export feature broken

**Response**:
- Response within 4 hours
- Document and schedule fix
- Continue normal operations

### S4 - LOW

**Definition**: Minor issue, cosmetic, no business impact

**Examples**:
- Typos in UI
- Minor logging gaps
- Non-visible bugs

**Response**:
- Track in backlog
- Fix in next sprint

---

## TRIAGE WORKFLOW

### Step 1: Classify and Create Incident

```json
// Create incident in .claude/state/active-incidents.json
{
  "id": "INC-20260107-ABC123",
  "severity": "S2",
  "status": "new",
  "created_at": "2026-01-07T10:30:00Z",
  "tenant_id": "gurkerl",
  "summary": "Solver timeout on 500+ tour forecasts",
  "evidence": []
}
```

### Step 2: Secure Evidence (BEFORE ANY CHANGES)

```bash
# 1. Capture request IDs
grep "request_id" /var/log/solvereign/api.log | tail -100 > evidence/request_ids.txt

# 2. Capture health snapshot
curl http://localhost:8000/health/ready > evidence/health_$(date +%s).json

# 3. Capture error logs
docker logs solvereign-api --since 1h > evidence/api_logs.txt

# 4. Capture database state
pg_dump -t service_escalations solvereign > evidence/escalations.sql

# 5. Document in incident
echo "Evidence secured at $(date)" >> evidence/timeline.txt
```

### Step 3: Investigate Root Cause

```bash
# Check recent changes
git log --oneline -10

# Check recent deployments
kubectl rollout history deployment/solvereign-api

# Check metrics
curl http://localhost:8000/metrics | grep -E "(error|timeout)"

# Check database
psql -c "SELECT * FROM service_escalations WHERE status != 'resolved' ORDER BY created_at DESC LIMIT 10"
```

### Step 4: Apply Mitigation

**Options by severity**:

| Severity | Mitigation Options |
|----------|-------------------|
| S1 | Rollback, block traffic, failover |
| S2 | Isolate tenant, disable feature, manual workaround |
| S3 | Document workaround, schedule fix |
| S4 | Track and continue |

### Step 5: Verify and Resolve

```bash
# Run health check
curl http://localhost:8000/health/ready

# Run smoke tests
python -m backend_py.tests.smoke_test

# Verify specific issue is resolved
# (depends on incident type)

# Update incident status
# Edit .claude/state/active-incidents.json → status: "resolved"
```

---

## EVIDENCE CHECKLIST

Before making ANY changes during an incident:

- [ ] Run-ID / Request-ID captured
- [ ] Health snapshot saved
- [ ] Error logs captured
- [ ] Database state captured (if relevant)
- [ ] Screenshots (if UI issue)
- [ ] Timeline started
- [ ] Evidence location documented in incident

---

## COMMUNICATION TEMPLATES

### S1/S2 Initial Notification

```
🚨 INCIDENT: [INC-ID]

Severity: S1/S2
Status: Investigating
Impact: [describe user impact]
Start time: [ISO timestamp]

We are aware of the issue and actively investigating.
Next update in [15/30] minutes.

Incident Commander: [name]
```

### Status Update

```
📊 UPDATE: [INC-ID]

Status: [Investigating/Mitigating/Resolved]
Summary: [what we know]
Next steps: [what we're doing]
ETA: [if known]

Next update in [X] minutes.
```

### Resolution

```
✅ RESOLVED: [INC-ID]

Duration: [X hours Y minutes]
Root cause: [brief description]
Fix applied: [what was done]
Affected: [scope]

Post-mortem scheduled for [date].
```

---

## POST-MORTEM TEMPLATE

After S1/S2 incidents:

```markdown
# Post-Mortem: [INC-ID]

## Summary
- **Duration**: X hours
- **Impact**: Y tenants, Z operations affected
- **Root Cause**: [one sentence]

## Timeline
- HH:MM - Incident detected
- HH:MM - [action taken]
- HH:MM - [action taken]
- HH:MM - Resolved

## Root Cause Analysis
[Detailed explanation]

## What Went Well
- [item]

## What Could Be Improved
- [item]

## Action Items
| Item | Owner | Due Date |
|------|-------|----------|
| [action] | [name] | [date] |

## Lessons Learned
[Key takeaways]
```

---

## ESCALATION PATHS

| Condition | Escalate To | How |
|-----------|-------------|-----|
| S1 any time | Platform Lead | Immediate call |
| S2 > 30min unresolved | Platform Lead | Message + call |
| Data breach suspected | Security Lead + Legal | Immediate call |
| Customer-facing impact | Customer Success | Email + call |

---

## INCIDENT TOOLS

### Create Incident

```python
# Quick incident creation
import json
from datetime import datetime

incident = {
    "id": f"INC-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
    "severity": "S2",
    "status": "new",
    "created_at": datetime.utcnow().isoformat() + "Z",
    "tenant_id": None,  # or specific tenant
    "summary": "Brief description",
    "evidence": []
}

# Save to active-incidents.json
```

### Check Active Incidents

```bash
cat .claude/state/active-incidents.json | jq '.incidents[] | select(.status != "resolved")'
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Active S1/S2 | - | Follow this playbook. No exceptions. |
| Incident > 2h unresolved | S1 | Escalate to management. |
| Recurring incident | S2 | Create problem ticket. Schedule root cause fix. |
| Evidence not secured | S3 | Document gap. Improve process. |
