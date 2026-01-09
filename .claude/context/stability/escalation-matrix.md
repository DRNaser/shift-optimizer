# Escalation Matrix

> **Purpose**: Clear escalation paths and responsibilities
> **Last Updated**: 2026-01-07

---

## ESCALATION DECISION TREE

```
Issue Detected
     │
     ▼
Is it a security breach? ──YES──► S1 + Security Lead + Legal
     │
     NO
     │
     ▼
Is system completely down? ──YES──► S1 + Platform Lead
     │
     NO
     │
     ▼
Is data at risk? ──YES──► S1 + Platform Lead + Data Owner
     │
     NO
     │
     ▼
Is customer-facing feature broken? ──YES──► S2 + On-call
     │
     NO
     │
     ▼
Is performance severely degraded? ──YES──► S2 + On-call
     │
     NO
     │
     ▼
Is it a minor issue with workaround? ──YES──► S3 + Backlog
     │
     NO
     │
     ▼
S4 + Track in backlog
```

---

## ROLES AND RESPONSIBILITIES

### Incident Commander (IC)

**Who**: First senior responder

**Responsibilities**:
- Own the incident end-to-end
- Coordinate response team
- Make escalation decisions
- Communicate status updates
- Ensure post-mortem happens

### Technical Lead

**Who**: Senior engineer with domain expertise

**Responsibilities**:
- Lead investigation
- Propose and implement fixes
- Validate resolution
- Document technical details

### Communications Lead

**Who**: Customer Success or Platform Lead

**Responsibilities**:
- Craft customer communications
- Update status page
- Coordinate with external parties
- Handle customer inquiries

---

## SEVERITY-BASED ESCALATION

### S1 - CRITICAL

| Time | Action | Responsible |
|------|--------|-------------|
| 0min | Incident created | Detector |
| 5min | IC assigned | On-call |
| 15min | First status update | IC |
| 15min | Technical Lead engaged | IC |
| 30min | Platform Lead notified | IC |
| 30min | Customer communication sent | Comms Lead |
| 1h | Management update | IC |
| Every 30min | Status updates | IC |

**Auto-Escalation**: If no IC assigned in 10 minutes, auto-page Platform Lead.

### S2 - HIGH

| Time | Action | Responsible |
|------|--------|-------------|
| 0min | Incident created | Detector |
| 15min | IC assigned | On-call |
| 30min | First status update | IC |
| 1h | Technical Lead engaged | IC |
| 2h | Platform Lead notified (if unresolved) | IC |
| Every 1h | Status updates | IC |

**Auto-Escalation**: If unresolved after 2 hours, escalate to S1.

### S3 - MEDIUM

| Time | Action | Responsible |
|------|--------|-------------|
| 0min | Issue logged | Detector |
| 4h | Owner assigned | Team Lead |
| 24h | Fix scheduled | Owner |

### S4 - LOW

| Time | Action | Responsible |
|------|--------|-------------|
| 0min | Issue logged | Detector |
| Sprint planning | Prioritized | Product Owner |

---

## CONTACT MATRIX

| Role | Primary Contact | Backup Contact | When to Contact |
|------|-----------------|----------------|-----------------|
| On-call Engineer | [rotation] | [rotation] | S1/S2 any time |
| Platform Lead | [name] | [name] | S1 any time, S2 >2h |
| Security Lead | [name] | [name] | Security incidents |
| Customer Success | [name] | [name] | Customer impact |
| Legal | [name] | - | Data breach |

---

## ESCALATION TRIGGERS

### Automatic Escalation

| Condition | Current | Escalate To | Method |
|-----------|---------|-------------|--------|
| S1 unacknowledged >10min | - | Platform Lead | Auto-page |
| S2 unresolved >2h | S2 | S1 | Auto-page |
| 3+ incidents in 24h | S3 | S2 | Notify |
| Customer complaint | - | S3 minimum | Create incident |

### Manual Escalation Criteria

Escalate UP if:
- Root cause unknown after 30min (S1/S2)
- Fix requires architectural change
- Multiple tenants affected
- Customer requesting update
- You need help

Escalate DOWN if:
- Root cause found and fix is simple
- Only single tenant affected (isolate)
- Workaround available
- Non-critical component

---

## COMMUNICATION CHANNELS

### S1 - CRITICAL

1. **Immediate**: Phone/video call
2. **Status**: Dedicated Slack channel (#incident-xxx)
3. **Customer**: Email + phone call
4. **Status page**: Update immediately

### S2 - HIGH

1. **Primary**: Slack #incidents
2. **Customer**: Email (if impacted)
3. **Status page**: Update if public-facing

### S3/S4

1. **Primary**: Jira ticket
2. **Updates**: Weekly team meeting

---

## SERVICE STATUS LEVELS

### Platform Status Page

| Status | Definition | Triggers |
|--------|------------|----------|
| Operational | All systems normal | Default state |
| Degraded | Some features impacted | S2 incident, p95 > 3x |
| Partial Outage | Major feature down | S1/S2, single pack down |
| Major Outage | Multiple features down | S1, multiple packs down |

### Tenant-Specific Status

| Status | Effect | API Response |
|--------|--------|--------------|
| Active | Normal operation | 200 |
| Degraded | Read-only mode | 503 on writes |
| Blocked | No access | 503 on all |

---

## POST-INCIDENT ACTIONS

### Required for S1/S2

- [ ] Post-mortem within 48h
- [ ] Action items assigned
- [ ] Runbooks updated
- [ ] Monitoring improved
- [ ] Communication sent to customers

### Optional for S3/S4

- [ ] Brief summary in team meeting
- [ ] Ticket for follow-up work

---

## ESCALATION ANTI-PATTERNS

**DON'T**:
- Wait to escalate because "I can fix it"
- Skip levels (engineer → CTO directly)
- Escalate without trying basic troubleshooting
- Forget to de-escalate when resolved

**DO**:
- Escalate early if unsure
- Follow the matrix
- Document why you escalated
- Close the loop when resolved

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| IC not assigned (S1 >10min) | - | Auto-page Platform Lead |
| S2 unresolved >2h | - | Escalate to S1 |
| Customer complaint | - | Create S3 minimum |
| Multiple incidents same root cause | - | Create problem ticket |
