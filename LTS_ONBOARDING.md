# LTS Tenant Onboarding Pack

**Version**: 1.0
**Date**: 2026-01-05
**Owner**: SOLVEREIGN Operations Team

---

## Overview

This document provides the complete onboarding guide for LTS Transport & Logistik GmbH as a production tenant on SOLVEREIGN V3.3b.

### Timeline
- Phase 1: Foundation (1-3 days)
- Phase 2: Data Onboarding (1 week)
- Phase 3: Operational Workflow (1-2 weeks)
- Phase 4: Incident/Repair Operations (1-2 weeks)

**Total**: 4-6 weeks to full operational capability

---

## Phase 1: Tenant Setup (Foundation)

### 1.1 Tenant Registration

| Field | Value |
|-------|-------|
| Tenant Name | LTS Transport & Logistik GmbH |
| Tenant ID | `lts-transport-001` |
| Status | `active` |
| Timezone | `Europe/Vienna` |
| Default Depot | Configured per driver |

### 1.2 RBAC Roles

| Role | Permissions | Assigned To |
|------|-------------|-------------|
| `TENANT_ADMIN` | Full access, user management | IT/Operations Lead |
| `PLANNER` | Solve, Review, Export | Dispatchers |
| `APPROVER` | Lock plans | Operations Manager |
| `VIEWER` | Read-only dashboards | Management |

**Critical Rule**: Only `APPROVER` role can lock plans.

### 1.3 Authentication

| Mode | Status | Notes |
|------|--------|-------|
| OIDC/IdP | Preferred | Azure AD / Okta integration |
| API Key | Temporary | Only for system-to-system calls |

**Security Requirements**:
- No shared accounts (1 user = 1 identity)
- API Keys rotate every 90 days
- Tenant ID comes from token, NOT client header

### 1.4 Checklist

- [ ] Tenant row created in `tenants` table
- [ ] Admin user(s) assigned with `TENANT_ADMIN` role
- [ ] RBAC roles configured per above matrix
- [ ] Auth mode determined (OIDC preferred)
- [ ] API Key generated (if needed for system calls)
- [ ] RLS verified for tenant isolation

---

## Phase 2: Data Onboarding

### 2.1 Driver Master Data

#### Required Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `external_ref` | VARCHAR(100) | Yes | HR/Payroll ID (unique per tenant) |
| `display_name` | VARCHAR(100) | No | Name for UI display |
| `home_depot` | VARCHAR(50) | Yes | Primary depot assignment |
| `max_weekly_hours` | DECIMAL(5,2) | No | Default: 55.0 |
| `is_active` | BOOLEAN | No | Default: true |

#### Skills (Optional)

| Skill Code | Description |
|------------|-------------|
| `ADR` | Hazardous materials certified |
| `KUEHL` | Refrigerated transport |
| `SCHWER` | Heavy goods transport |

#### Import Process

1. Download template: `templates/drivers_import.csv`
2. Fill in driver data
3. Upload via API: `POST /api/v1/drivers/bulk`
4. Use `dry_run=true` first for validation
5. Review validation errors
6. Execute import with `dry_run=false`

#### Blindspots to Avoid

- [ ] Check for duplicate `external_ref` values
- [ ] Verify all depots exist in master list
- [ ] Ensure skill codes match canonical list
- [ ] Mark inactive drivers as `is_active=false`

### 2.2 Driver Availability

#### Status Values

| Status | Description | Use Case |
|--------|-------------|----------|
| `AVAILABLE` | Can be assigned | Default (no row needed) |
| `SICK` | Sick leave | Primary repair trigger |
| `VACATION` | Planned absence | Pre-scheduled |
| `BLOCKED` | Other unavailability | Training, etc. |

#### Import Process

1. Download template: `templates/availability_import.csv`
2. Fill in weekly availability
3. Upload via API: `POST /api/v1/drivers/availability/bulk`
4. Validate before each weekly solve

#### Blindspots to Avoid

- [ ] Use correct timezone (Europe/Vienna)
- [ ] Date format: YYYY-MM-DD
- [ ] SICK entries may arrive late → Repair workflow handles this
- [ ] Default = AVAILABLE only if driver is_active=true

### 2.3 Forecast Input

#### Format Requirements

```
Day Start-End [Count] [Depot] [Notes]
```

#### Examples

```
Mo 06:00-14:00                    # Single tour
Di 08:00-16:00 3 Fahrer           # 3 drivers needed
Mi 06:00-10:00 + 14:00-18:00      # Split shift
Do 22:00-06:00                    # Cross-midnight
Fr 06:00-14:00 2 Fahrer Depot Nord
```

#### Parser Validation

| Status | Meaning |
|--------|---------|
| `PASS` | All lines valid, ready to solve |
| `WARN` | Valid but with warnings |
| `FAIL` | Invalid, cannot proceed |

#### Blindspots to Avoid

- [ ] Freeze forecast format (no ad-hoc changes!)
- [ ] Test cross-midnight + depot + split combinations
- [ ] Unknown patterns → reject, don't guess
- [ ] Validate day names: Mo, Di, Mi, Do, Fr, Sa, So

---

## Phase 3: Operational Workflow

### 3.1 Weekly Cycle (Mo-Sa)

```
┌─────────────────────────────────────────────────────────────────┐
│                    WEEKLY WORKFLOW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  MONDAY (Preparation)                                           │
│  ├── Receive forecast for next week                             │
│  ├── Update driver availability (sick, vacation)                │
│  └── Ingest forecast into SOLVEREIGN                            │
│                                                                 │
│  TUESDAY (Solve & Review)                                       │
│  ├── Run solver (seed=94 default, or seed sweep)                │
│  ├── Review KPIs:                                               │
│  │   • Headcount (target: ≤145)                                 │
│  │   • PT ratio (target: 0%)                                    │
│  │   • Max hours (target: ≤54h)                                 │
│  │   • Coverage (target: 100%)                                  │
│  ├── Review near-violations (yellow zone)                       │
│  └── Approve or re-solve with different config                  │
│                                                                 │
│  WEDNESDAY (Lock & Export)                                      │
│  ├── Operations Manager locks plan (APPROVER role)              │
│  ├── Export Proof Pack (ZIP)                                    │
│  ├── Export Roster Matrix (CSV/Excel)                           │
│  └── Distribute to drivers (manual for now)                     │
│                                                                 │
│  THURSDAY-SATURDAY (Execution)                                  │
│  ├── Monitor for sick calls                                     │
│  ├── Run repair if needed (see Repair Runbook)                  │
│  └── Document any manual overrides                              │
│                                                                 │
│  SUNDAY (Close)                                                 │
│  ├── Archive week's outputs                                     │
│  └── Prepare for next cycle                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Solve Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `seed` | 94 | Best known seed for LTS workload |
| `max_weekly_hours` | 55 | ArbZG limit |
| `min_rest_hours` | 11 | Between blocks |
| `max_span_regular` | 14h | For 1er/2er-reg |
| `max_span_split` | 16h | For split/3er |
| `split_break_min` | 240min | Minimum split break |
| `split_break_max` | 360min | Maximum split break |

### 3.3 Golden Run Practice

After each successful solve + lock:

1. Save `input_hash`, `output_hash`, `seed`, `config_hash`
2. Store in `golden_runs/YYYY-WXX/` directory
3. Enables: reproducibility, comparison, audit

### 3.4 Lock Governance

**Who Can Lock**: Only users with `APPROVER` role

**Lock Checklist**:
- [ ] All 7 audits PASS
- [ ] KPIs within targets
- [ ] Near-violations reviewed
- [ ] Peak fleet acceptable
- [ ] Operations Manager approval

**After Lock**:
- Plan is immutable (DB triggers enforce)
- Any changes require new plan version
- Superseding old plan (not overwriting)

---

## Phase 4: Incident/Repair Operations

### 4.1 When to Use Repair

| Scenario | Action |
|----------|--------|
| 1-3 drivers sick (same day) | Repair |
| 4+ drivers sick | Consider re-solve |
| Tour cancellations (>10) | Re-solve |
| Minor schedule adjustments | Repair |
| Major forecast change | New forecast + solve |

### 4.2 Repair Process

```
1. Identify absent drivers (get driver IDs)
2. Call repair API:
   POST /api/v1/plans/{plan_id}/repair
   {
     "absent_driver_ids": [1, 5, 12],
     "respect_freeze": true,
     "strategy": "MIN_CHURN"
   }
3. Review result:
   - tours_reassigned: number changed
   - churn_rate: % of total tours
   - freeze_violations: should be 0
4. If SUCCESS: new plan version created
5. If FAILED: see error handling below
```

### 4.3 Error Handling

| Error | Meaning | Action |
|-------|---------|--------|
| `INSUFFICIENT_ELIGIBLE_DRIVERS` | Not enough available drivers | Call standby pool or re-solve with relaxed constraints |
| `frozen tours cannot change` | Tours within 12h | Override freeze or manual dispatch |
| `Invalid driver IDs` | ID not in system | Verify driver master data |
| `409 Conflict` | Concurrent repair | Wait and retry |

### 4.4 Repair Limits

| Constraint | Limit |
|------------|-------|
| Max absent drivers per repair | 10 |
| Freeze window | 12h before tour start |
| Time budget | 60 seconds |
| Retries on failure | 2 |

### 4.5 Standby Protocol

When `INSUFFICIENT_ELIGIBLE_DRIVERS`:

1. Check standby pool (drivers marked as on-call)
2. Contact standby drivers
3. Update availability to `AVAILABLE`
4. Re-run repair
5. If still fails: escalate to Operations Manager

---

## KPIs for Management

### Weekly Dashboard

| KPI | Target | Alert Threshold |
|-----|--------|-----------------|
| **Headcount** | ≤145 | >150 |
| **PT Ratio** | 0% | >5% |
| **Max Hours** | ≤54h | >55h |
| **Coverage** | 100% | <100% |
| **Churn Rate** | <5% | >10% |
| **Audit Pass Rate** | 100% | <100% |
| **Peak Fleet** | Per SLA | +10% over SLA |

### Monthly Report

- Average headcount trend
- Repair frequency
- Freeze violation rate
- Standby utilization
- Forecast accuracy (actual vs planned)

---

## Support & Escalation

### Level 1: Dispatcher Self-Service
- Use runbooks
- Check FAQ
- Review error messages

### Level 2: Operations Lead
- Constraint adjustments
- Config changes
- Lock approval

### Level 3: SOLVEREIGN Support
- System issues
- Bug reports
- Feature requests

### Contact

| Role | Responsibility |
|------|----------------|
| Operations Manager | Lock approval, escalations |
| IT Lead | Tenant admin, integrations |
| SOLVEREIGN Support | System issues |

---

## Appendices

### A. File Locations

```
templates/
├── drivers_import.csv
├── availability_import.csv
└── forecast_template.txt

golden_runs/
├── 2026-W01/
│   ├── input.json
│   ├── output.json
│   ├── proof_pack.zip
│   └── roster_matrix.csv
└── ...

runbooks/
├── weekly_runbook.md
└── repair_runbook.md
```

### B. API Endpoints Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/drivers` | GET | List drivers |
| `/api/v1/drivers` | POST | Create driver |
| `/api/v1/drivers/bulk` | POST | Bulk import |
| `/api/v1/drivers/{id}/availability` | POST | Set availability |
| `/api/v1/plans/{id}/repair` | POST | Repair plan |
| `/api/v1/plans/{id}/repairs` | GET | Repair history |

### C. Glossary

| Term | Definition |
|------|------------|
| **Forecast** | Weekly tour schedule input |
| **Solve** | Run optimizer on forecast |
| **Lock** | Freeze plan for dispatch |
| **Repair** | Fix plan after driver absence |
| **Churn** | % of tours that changed assignment |
| **PT** | Part-time driver (<40h/week) |
| **FTE** | Full-time equivalent (≥40h/week) |

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-05 | Initial release |

---

*Document Owner: SOLVEREIGN Operations Team*
*Next Review: 2026-02-05*
