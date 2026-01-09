# Operations Cadence Runbook

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot Operations
**Audience**: Dispatchers, Ops Team, Platform Engineering
**Last Updated**: 2026-01-08

---

## 1) Weekly Operations Calendar

### 1.1 Weekly Schedule Overview

| Day | Time (CET) | Activity | Owner |
|-----|------------|----------|-------|
| **Monday** | 06:00 | Forecast ingestion opens | Dispatcher |
| **Monday** | 18:00 | Forecast ingestion deadline | Dispatcher |
| **Tuesday** | 08:00 | Solver run (automated) | Platform |
| **Tuesday** | 10:00 | Dispatcher review opens | Dispatcher |
| **Tuesday** | 16:00 | Plan approval deadline | Dispatcher |
| **Tuesday** | 17:00 | Plan lock (LOCKED status) | Dispatcher |
| **Wednesday** | 08:00 | Driver notifications sent | Platform |
| **Thursday-Sunday** | — | Operational monitoring | On-call |

### 1.2 Cutover Times

| Event | Time | Frozen After |
|-------|------|--------------|
| Monday tours | Sunday 18:00 | Sunday 06:00 |
| Tuesday tours | Monday 18:00 | Monday 06:00 |
| Wednesday tours | Tuesday 18:00 | Tuesday 06:00 |
| Thursday tours | Wednesday 18:00 | Wednesday 06:00 |
| Friday tours | Thursday 18:00 | Thursday 06:00 |
| Saturday tours | Friday 18:00 | Friday 06:00 |
| Sunday tours | Saturday 18:00 | Saturday 06:00 |

**Freeze Horizon**: 12 hours before tour start

---

## 2) Forecast Ingestion Phase

### 2.1 Input Requirements

| Item | Format | Validation |
|------|--------|------------|
| Forecast file | JSON or CSV | `validate_import_contract.py` |
| Week anchor date | Monday of target week | YYYY-MM-DD |
| Tours | Day, start/end time, count | HG-001 to HG-008 |

### 2.2 Ingestion Workflow

```
1. Customer/FLS exports forecast
              │
              ▼
2. Dispatcher receives file (email/SFTP)
              │
              ▼
3. Validate import contract
   python scripts/validate_import_contract.py --input forecast.json
              │
              ├── PASS → Continue
              ├── WARN → Review warnings, proceed if acceptable
              └── FAIL → Request corrected file from customer
              │
              ▼
4. Upload to SOLVEREIGN
   POST /api/v1/forecasts
              │
              ▼
5. Confirm ingestion
   GET /api/v1/forecasts/{id}
   Status: INGESTED
```

### 2.3 Ingestion Checklist

```markdown
## Forecast Ingestion Checklist

Date: _______________
Week: _______________
Dispatcher: _______________

### Pre-Ingestion
- [ ] Forecast file received
- [ ] File format verified (JSON/CSV)
- [ ] Week anchor date is Monday

### Validation
- [ ] Run validate_import_contract.py
- [ ] Hard gates: PASS
- [ ] Soft gates reviewed: ___ warnings
- [ ] Warning rationale documented

### Upload
- [ ] Forecast uploaded successfully
- [ ] Forecast ID: _______________
- [ ] Status: INGESTED

### Confirmation
- [ ] Tour count matches expected: _____ tours
- [ ] Instance count: _____ instances
- [ ] No duplicate external IDs
```

---

## 3) Solver Run Phase

### 3.1 Automated Solver

The solver runs automatically at scheduled times:

| Trigger | Time | Conditions |
|---------|------|------------|
| Scheduled | Tuesday 08:00 | Forecast status = INGESTED |
| Manual | On-demand | Dispatcher request |

### 3.2 Solver Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Seed | 94 | Deterministic |
| Max drivers | — | No limit |
| Max hours/week | 55h | Hard cap |
| FTE threshold | 40h | >=40h = FTE |

### 3.3 Solver Run Monitoring

```bash
# Check solver status
GET /api/v1/plans/{plan_id}

# Expected states
QUEUED    → Waiting for solver
SOLVING   → Solver running (typically 10-30s)
SOLVED    → Solver complete, awaiting audit
AUDITING  → Running 7 audit checks
AUDITED   → All checks complete
```

### 3.4 Solver Output Review

| KPI | Target | Alert If |
|-----|--------|----------|
| Coverage | 100% | <100% |
| FTE ratio | >95% | <90% |
| PT ratio | <5% | >10% |
| Max driver hours | <55h | >=55h |
| Audit pass | 7/7 | Any FAIL |

---

## 4) Plan Review Phase

### 4.1 Review Window

| Event | Time |
|-------|------|
| Review opens | Tuesday 10:00 |
| Review closes | Tuesday 16:00 |
| Duration | 6 hours |

### 4.2 Review Tasks

1. **Check KPIs**: Coverage, driver count, FTE ratio
2. **Review assignments**: Spot-check driver schedules
3. **Verify audits**: All 7 checks PASS
4. **Check warnings**: Any WARN conditions addressed
5. **Approve or reject**: Decision within window

### 4.3 Review Outcomes

| Outcome | Action | Next Step |
|---------|--------|-----------|
| **Approve** | Mark ready for lock | Proceed to lock |
| **Request changes** | Notify platform team | Re-solve or manual adjust |
| **Reject** | Document reason | Escalate to product owner |

---

## 5) Plan Lock Phase

### 5.1 Lock Prerequisites

- [ ] Solver status: AUDITED
- [ ] All 7 audits: PASS
- [ ] Dispatcher approval: Received
- [ ] Within lock window: Yes

### 5.2 Lock Procedure

```bash
# Lock the plan
POST /api/v1/plans/{plan_id}/lock

# Response
{
  "status": "LOCKED",
  "locked_at": "2026-01-07T17:00:00Z",
  "locked_by": "dispatcher@lts.com"
}
```

### 5.3 Post-Lock Actions

1. **Generate evidence pack**
   ```bash
   python scripts/export_evidence_pack.py export \
     --plan-id {plan_id} \
     --out evidence_w02.zip
   ```

2. **Update state file**
   ```bash
   # Update .claude/state/last-known-good.json
   ```

3. **Trigger notifications** (if configured)
   - Driver SMS/email
   - Dispatcher confirmation

### 5.4 Lock is Immutable

After lock:
- ❌ Cannot modify assignments
- ❌ Cannot change tour instances
- ✅ Can view and export
- ✅ Can run repair (creates new plan version)

---

## 6) Evidence Retention

### 6.1 What to Retain

| Artifact | Retention | Storage |
|----------|-----------|---------|
| Forecast input | 90 days | S3/Azure |
| Canonical JSON | 90 days | S3/Azure |
| Solver output | 90 days | Database |
| Audit log | 1 year | Database |
| Evidence pack | 1 year | S3/Azure |
| Drill results | 90 days | S3/Azure |

### 6.2 Evidence Pack Contents

```
evidence_pack_<plan_id>.zip
├── manifest.json           # Metadata + hashes
├── forecast_input.json     # Original input
├── canonical_input.json    # Canonicalized input
├── solver_output.json      # Assignment results
├── audit_results.json      # 7 audit checks
├── kpis.json               # Plan KPIs
└── checksums.txt           # SHA256 of all files
```

### 6.3 Storage Locations

| Environment | Location |
|-------------|----------|
| Staging | `s3://solvereign-staging/evidence/` |
| Production | `s3://solvereign-prod/evidence/` |
| Local dev | `artifacts/evidence/` |

---

## 7) Approval Workflow

### 7.1 Approval Levels

| Action | Approver | Conditions |
|--------|----------|------------|
| Plan lock | Dispatcher | All audits PASS |
| Plan with warnings | Dispatcher + Lead | Documented rationale |
| Emergency repair | On-call | Freeze window exception |
| Data deletion | DPO + Platform Lead | GDPR request |

### 7.2 Approval Record

Each approval must be recorded:

```json
{
  "action": "plan_lock",
  "plan_id": 123,
  "approver": "dispatcher@lts.com",
  "timestamp": "2026-01-07T17:00:00Z",
  "conditions_met": [
    "audits_pass",
    "within_window",
    "coverage_100"
  ],
  "notes": "Approved for week 2026-W02"
}
```

---

## 8) Incident Drill Schedule

### 8.1 Monthly Drill Calendar

| Week | Drill | Purpose |
|------|-------|---------|
| Week 1 | H1: Sick-call | Test repair service |
| Week 2 | H2: Freeze-window | Test enforcement |
| Week 3 | H3: Partial-forecast | Test delta handling |
| Week 4 | Break-glass | Test emergency access |

### 8.2 Drill Execution

```bash
# H1: Sick-call drill
python scripts/run_sick_call_drill.py --dry-run --seed 94 \
  --absent-drivers DRV001,DRV002,DRV003 \
  --tenant wien_pilot

# H2: Freeze-window drill
python scripts/run_freeze_window_drill.py --dry-run --seed 94 \
  --freeze-horizon 720 \
  --tenant wien_pilot

# H3: Partial-forecast drill
python scripts/run_partial_forecast_drill.py --dry-run --seed 94 \
  --tenant wien_pilot
```

### 8.3 Drill Success Criteria

| Drill | Pass Condition |
|-------|----------------|
| H1 Sick-call | Coverage=100%, Churn<20%, Audits PASS |
| H2 Freeze-window | BLOCK on frozen, ALLOW on unfrozen |
| H3 Partial-forecast | Deterministic hash on re-run |

### 8.4 Drill Documentation

Each drill must produce:
- Evidence JSON (`artifacts/drills/{type}/`)
- Pass/Fail verdict
- Lessons learned (if failure)

---

## 9) Escalation Procedures

### 9.1 Escalation Matrix

| Issue | Severity | First Contact | Escalation |
|-------|----------|---------------|------------|
| Solver timeout | S2 | On-call | Platform Lead |
| Audit failure | S2 | On-call | Platform Lead |
| Coverage <100% | S1 | Platform Lead | Product Owner |
| RLS violation | S0 | Security Lead | CTO |
| Data breach | S0 | Security Lead | CTO + Legal |

### 9.2 Response Times

| Severity | Acknowledge | Resolve/Mitigate |
|----------|-------------|------------------|
| S0 | 15 min | 1 hour |
| S1 | 30 min | 4 hours |
| S2 | 1 hour | 8 hours |
| S3 | 4 hours | Next business day |

### 9.3 Communication Channels

| Channel | Purpose |
|---------|---------|
| #solvereign-ops | Daily operations |
| #solvereign-incidents | Active incidents |
| PagerDuty | S0/S1 alerts |
| Email | Non-urgent notifications |

---

## 10) Handoff Procedures

### 10.1 Shift Handoff (Ops)

```markdown
## Ops Shift Handoff

Date: _______________
From: _______________
To: _______________

### Current Status
- Active plans: ___
- Open incidents: ___
- Pending approvals: ___

### Key Events
- [Event 1]
- [Event 2]

### Attention Items
- [Item requiring follow-up]

### Handoff Confirmed
From: _____________ Time: _____
To: _____________ Time: _____
```

### 10.2 Weekly Handoff (Platform)

```markdown
## Weekly Platform Handoff

Week: _______________
Outgoing: _______________
Incoming: _______________

### Deployments This Week
- [Deployment 1]

### Incidents This Week
- [Incident 1]

### Upcoming Changes
- [Change 1]

### Technical Debt
- [Item 1]

### Handoff Confirmed
Date: _____________
```

---

## 11) Dispatcher Cockpit UI Rollout

### 11.1 Feature Flag Configuration

| Environment | Flag | Value | Notes |
|-------------|------|-------|-------|
| Development | `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT` | `true` | Always on |
| Staging | `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT` | `true` | UAT enabled |
| Production | `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT` | `false` | Default OFF |

**Allowed Roles** (set via `NEXT_PUBLIC_FF_DISPATCHER_COCKPIT_ROLES`):
- `platform_admin`
- `platform_ops`
- `dispatcher`
- `ops_lead`

### 11.2 Rollout Timeline

| Phase | Date | Action |
|-------|------|--------|
| **Staging Deploy** | Burn-in W01 | Deploy UI, run UAT |
| **Internal Preview** | Burn-in W02 | Platform team only |
| **Wien Rollout** | After Day 30 | Enable for Wien dispatchers |
| **Full Rollout** | After Day 60 | Enable for all sites |

### 11.3 Production Enable Procedure

```bash
# 1. Verify burn-in complete (day 30+)
cat .claude/state/drift-baselines.json | jq '.day_number'

# 2. Enable feature flag
# In production .env or config:
NEXT_PUBLIC_FF_DISPATCHER_COCKPIT=true
NEXT_PUBLIC_FF_DISPATCHER_COCKPIT_ROLES=platform_admin,platform_ops,dispatcher,ops_lead
NEXT_PUBLIC_ENABLED_SITES=wien

# 3. Deploy frontend
npm run build && npm run start

# 4. Verify
curl https://app.solvereign.com/runs
# Should load runs list page
```

### 11.4 UI vs CLI Equivalence

| Action | CLI Command | UI Equivalent |
|--------|-------------|---------------|
| List runs | `dispatcher_cli.py list-runs --site wien` | `/runs` page |
| Show run | `dispatcher_cli.py show-run <id>` | `/runs/<id>` page |
| Publish | `dispatcher_cli.py publish <id> --reason "..."` | Publish button + modal |
| Lock | `dispatcher_cli.py lock <id> --reason "..."` | Lock button + modal |
| Repair | `dispatcher_cli.py repair <id> --driver D001 ...` | Request Repair form |
| Evidence | `dispatcher_cli.py evidence <id>` | Download Evidence button |
| Status | `dispatcher_cli.py status` | Header badges |

### 11.5 Fallback to CLI

If UI is unavailable or has issues:

```bash
# 1. List runs via CLI
python scripts/dispatcher_cli.py list-runs --site wien --tenant lts

# 2. Show run detail
python scripts/dispatcher_cli.py show-run <run_id>

# 3. Publish (with reason)
python scripts/dispatcher_cli.py publish <run_id> \
  --approver dispatcher@lts.com \
  --reason "Weekly schedule approval"

# 4. Lock (with reason)
python scripts/dispatcher_cli.py lock <run_id> \
  --approver dispatcher@lts.com \
  --reason "Final lock for export"

# 5. Download evidence
python scripts/dispatcher_cli.py evidence <run_id> --out evidence.zip
```

### 11.6 UI Incident Response

| Issue | Detection | Response |
|-------|-----------|----------|
| UI not loading | 5xx on `/runs` | Fall back to CLI |
| Session expired | 401 on API calls | Re-login or use CLI |
| Kill switch shown | Banner visible | Expected, use CLI to verify |
| Actions disabled | Buttons grayed out | Check kill switch / site gate |

### 11.7 UI Monitoring

| Metric | Source | Alert If |
|--------|--------|----------|
| UI load time | Lighthouse | > 3s |
| API error rate | BFF logs | > 1% |
| Session failures | Auth logs | > 5/hour |
| Publish failures | Audit log | Any (not kill switch) |

---

## 12) Reference Documents

| Document | Purpose |
|----------|---------|
| [RUNBOOK_WIEN_PILOT.md](RUNBOOK_WIEN_PILOT.md) | Technical operations |
| [RUNBOOK_PROD_CUTOVER.md](RUNBOOK_PROD_CUTOVER.md) | Production deployment |
| [docs/DISPATCHER_CHECKLIST.md](docs/DISPATCHER_CHECKLIST.md) | Quick reference |
| [docs/SLO_WIEN_PILOT.md](docs/SLO_WIEN_PILOT.md) | Service levels |
| [docs/INCIDENT_BREAK_GLASS.md](docs/INCIDENT_BREAK_GLASS.md) | Emergency access |
| [docs/UAT_DISPATCHER_COCKPIT.md](docs/UAT_DISPATCHER_COCKPIT.md) | UI acceptance testing |

---

## 12) Quick Reference

### 12.1 Key Commands

```bash
# Validate import
python scripts/validate_import_contract.py --input forecast.json

# Check plan status
curl -H "X-API-Key: $API_KEY" https://api.solvereign.com/api/v1/plans/{id}

# Lock plan
curl -X POST -H "X-API-Key: $API_KEY" \
  https://api.solvereign.com/api/v1/plans/{id}/lock

# Export evidence
python scripts/export_evidence_pack.py export --plan-id {id} --out evidence.zip

# Run drill
python scripts/run_sick_call_drill.py --dry-run --seed 94 --tenant wien_pilot
```

### 12.2 Key Contacts

| Role | Contact |
|------|---------|
| On-call | PagerDuty |
| Platform Lead | [Name/Slack] |
| Security Lead | [Name/Slack] |
| Product Owner | [Name/Slack] |

### 12.3 Key URLs

| Service | URL |
|---------|-----|
| API (Prod) | https://api.solvereign.com |
| Health | https://api.solvereign.com/health |
| Monitoring | [Dashboard URL] |

---

**Document Version**: 1.0

**Effective**: Wien Pilot W02 onwards

**Review Cycle**: Monthly
