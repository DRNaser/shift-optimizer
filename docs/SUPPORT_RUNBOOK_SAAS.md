# SaaS Support Runbook

**System**: SOLVEREIGN V3.7
**Scope**: LTS Wien Pilot Operations Support
**Last Updated**: 2026-03-05

---

## Overview

This runbook defines support procedures for SOLVEREIGN SaaS operations. It covers incident response, escalation paths, and routine support tasks.

---

## Support Tiers

| Tier | Response SLA | Resolution SLA | Scope |
|------|--------------|----------------|-------|
| **L1** | 15 min | 4 hours | Known issues, status checks, basic troubleshooting |
| **L2** | 1 hour | 8 hours | Investigation, configuration changes, workarounds |
| **L3** | 2 hours | 24 hours | Code fixes, database operations, platform issues |

---

## Incident Severity Classification

| Severity | Description | Example | Response |
|----------|-------------|---------|----------|
| **S0** | Complete service outage | API unreachable, DB down | All hands, war room |
| **S1** | Critical feature broken | Solver fails, lock broken | Immediate L3 escalation |
| **S2** | Major feature degraded | Slow response, partial data | L2 investigation |
| **S3** | Minor issue | UI glitch, non-blocking | Normal queue |

---

## On-Call Rotation

### Primary On-Call

| Week | Primary | Backup | Contact |
|------|---------|--------|---------|
| Odd weeks | Platform Lead | Backend Dev | +43-XXX-XXXX |
| Even weeks | Backend Dev | Platform Lead | +43-XXX-XXXX |

### Escalation Matrix

| Severity | First Contact | Escalate After | Final Escalate |
|----------|---------------|----------------|----------------|
| S0 | On-call | Immediate | CTO (5 min) |
| S1 | On-call | 30 min | Platform Lead |
| S2 | On-call | 2 hours | L3 Queue |
| S3 | Support Queue | 8 hours | L2 Queue |

---

## Common Support Procedures

### SP-001: Health Check

**When**: Daily or on request
**Who**: L1

```bash
# 1. Check API health
curl -s https://api.solvereign.com/health | jq .

# Expected output:
# {"status": "healthy", "db": "connected", "redis": "connected"}

# 2. Check recent runs
python scripts/dispatcher_cli.py --site wien list-runs --limit 5

# 3. Check for active incidents
cat .claude/state/active-incidents.json | jq .
```

**Success Criteria**:
- API returns `healthy`
- Recent runs show PASS verdicts
- No active S0/S1 incidents

---

### SP-002: Failed Solver Run Investigation

**When**: Solver run returns FAIL or ERROR
**Who**: L2

**Step 1: Gather Information**
```bash
# Get run details
python scripts/dispatcher_cli.py --site wien status --run-id <RUN_ID>

# Check audit results
python scripts/dispatcher_cli.py --site wien audit --run-id <RUN_ID>
```

**Step 2: Check Common Issues**

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| Coverage < 100% | Input changed | Compare with previous week |
| Overlap FAIL | Data quality | Check for duplicate tours |
| Runtime > 60s | Large dataset | Consider splitting |
| Hash mismatch | Non-determinism | Check seed, report bug |

**Step 3: Resolution**
- If input issue: Contact ops team to correct input
- If solver bug: Escalate to L3 with evidence
- If infrastructure: Check logs, restart if needed

---

### SP-003: Publish/Lock Issues

**When**: Plan cannot be published or locked
**Who**: L2

**Step 1: Check Prerequisites**
```bash
# Verify audit status
python scripts/dispatcher_cli.py --site wien audit --run-id <RUN_ID>

# All audits must be PASS for lock
```

**Step 2: Check Freeze State**
```bash
# Check if kill switch is active
python scripts/dispatcher_cli.py --site wien status

# If DISABLED, contact Platform Lead
```

**Step 3: Common Lock Errors**

| Error | Cause | Resolution |
|-------|-------|------------|
| `AUDIT_GATE_FAIL` | Audit check failed | Fix audit issues first |
| `ALREADY_LOCKED` | Plan already locked | Use new run |
| `FREEZE_ACTIVE` | Kill switch on | Verify with ops |
| `PERMISSION_DENIED` | Wrong role | Check user permissions |

---

### SP-004: KPI Drift Alert

**When**: Drift monitor triggers WARN or BLOCK
**Who**: L2

**Step 1: Identify Drift**
```bash
# Check drift report
python -m backend_py.skills.kpi_drift check --tenant lts --site wien
```

**Step 2: Compare with Baseline**

| KPI | Baseline | Current | Drift % | Action |
|-----|----------|---------|---------|--------|
| Headcount | 145 | X | >5%? | Investigate input |
| Coverage | 100% | X | <100%? | Block, investigate |
| FTE Ratio | 100% | X | <95%? | Review driver pool |

**Step 3: Resolution**
- WARN: Document and proceed with approval
- BLOCK: Investigate before proceeding
- Update baseline if drift is expected (seasonal, business change)

---

### SP-005: Fire Drill Execution

**When**: Scheduled (weekly) or ad-hoc test
**Who**: L2

**Step 1: Pre-Drill**
```bash
# Verify current state
python scripts/dispatcher_cli.py --site wien status
# Should show: publish_enabled=true, lock_enabled=true
```

**Step 2: Execute Drill**
```bash
# Disable (measure time)
time python scripts/toggle_publish_lock.py disable --site wien --reason "Fire drill"

# Verify disabled
python scripts/dispatcher_cli.py --site wien status
# Should show: publish_enabled=false, lock_enabled=false

# Re-enable (measure time)
time python scripts/toggle_publish_lock.py enable --site wien --reason "Fire drill complete"
```

**Step 3: Record Results**
- Target: <5 seconds for each toggle
- Document in fire drill record
- Report if >5s or errors

---

### SP-006: Emergency Kill Switch

**When**: Security incident, critical bug, or ops request
**Who**: Ops Lead or Platform Lead (ONLY)

**Step 1: Assess Situation**
- Confirm severity warrants kill switch
- Document reason before executing

**Step 2: Execute Kill Switch**
```bash
# EMERGENCY ONLY
python scripts/toggle_publish_lock.py disable --site wien --reason "EMERGENCY: <description>"
```

**Step 3: Notify**
- Notify all stakeholders immediately
- Create S1 incident ticket
- Document in incident log

**Step 4: Recovery**
- Root cause analysis required before re-enable
- Platform Lead must approve re-enable
- Document lessons learned

---

## Routine Tasks

### Daily Tasks

| Time | Task | Owner | Procedure |
|------|------|-------|-----------|
| 08:00 | Health check | L1 | SP-001 |
| 09:00 | Review overnight runs | L1 | Check audit results |
| 17:00 | End-of-day status | L1 | Document any issues |

### Weekly Tasks

| Day | Task | Owner | Procedure |
|-----|------|-------|-----------|
| Monday | Fire drill | L2 | SP-005 |
| Wednesday | KPI review | L2 | SP-004 |
| Friday | Weekly report | L1 | Compile metrics |

### Monthly Tasks

| Task | Owner | Deliverable |
|------|-------|-------------|
| Baseline review | Platform Lead | Updated thresholds if needed |
| Runbook review | Platform Lead | Updated procedures |
| SLO review | Platform Lead | SLO compliance report |

---

## Contact Directory

| Role | Primary | Backup | Email |
|------|---------|--------|-------|
| Platform Lead | [Name] | [Name] | platform@company.com |
| Ops Lead | [Name] | [Name] | ops@lts-transport.at |
| Dispatcher | [Name] | [Name] | dispatch@lts-transport.at |
| Support Queue | — | — | support@company.com |

---

## Tooling Reference

### CLI Commands

```bash
# Health and status
python scripts/dispatcher_cli.py --site wien status
python scripts/dispatcher_cli.py --site wien list-runs

# Run operations
python scripts/dispatcher_cli.py --site wien audit --run-id <ID>
python scripts/dispatcher_cli.py --site wien publish --run-id <ID>
python scripts/dispatcher_cli.py --site wien lock --run-id <ID>

# Drift monitoring
python -m backend_py.skills.kpi_drift check --tenant lts --site wien

# Kill switch
python scripts/toggle_publish_lock.py status --site wien
python scripts/toggle_publish_lock.py disable --site wien --reason "..."
python scripts/toggle_publish_lock.py enable --site wien --reason "..."
```

### Log Locations

| Log | Location | Retention |
|-----|----------|-----------|
| API logs | `/var/log/solvereign/api.log` | 30 days |
| Solver logs | `/var/log/solvereign/solver.log` | 30 days |
| Audit trail | Database (audit_log table) | 2 years |
| Evidence packs | Azure Blob / S3 | 90 days (pilot) |

---

## Appendix: Error Code Reference

| Code | Description | Severity | Action |
|------|-------------|----------|--------|
| `ERR_AUTH_001` | Invalid API key | S3 | Check credentials |
| `ERR_AUTH_002` | Expired token | S3 | Refresh token |
| `ERR_SOLVE_001` | Solver timeout | S2 | Retry or split input |
| `ERR_SOLVE_002` | No feasible solution | S2 | Review constraints |
| `ERR_AUDIT_001` | Coverage check failed | S2 | Review input data |
| `ERR_AUDIT_002` | Overlap detected | S2 | Check duplicates |
| `ERR_LOCK_001` | Plan already locked | S3 | Use new plan |
| `ERR_LOCK_002` | Audit gate failed | S2 | Fix audit issues |
| `ERR_DB_001` | Connection failed | S1 | Check DB status |
| `ERR_DB_002` | Transaction timeout | S2 | Retry operation |

---

**Document Version**: 1.0

**Last Updated**: 2026-03-05

**Next Review**: After first live month (2026-04-01)
