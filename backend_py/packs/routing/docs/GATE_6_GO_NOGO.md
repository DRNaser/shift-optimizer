# SOLVEREIGN Routing Pack - Gate 6: Go/No-Go Decision

> **Gate**: 6 (Pilot Readiness)
> **Date**: 2026-01-06
> **Status**: READY FOR DECISION
> **Decision Required By**: Operations Manager + IT Lead

---

## 1. Executive Summary

Gate 6 is the final checkpoint before pilot deployment of SOLVEREIGN Routing Pack.
This document presents the acceptance criteria, current status, and rollback procedures.

**Recommendation**: ✅ **GO** - All mandatory criteria met.

---

## 2. Gate 6 Checklist

### 2.1 Technical Readiness

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | FLS Export Contract frozen | ✅ PASS | [FLS_EXPORT_CONTRACT.md](FLS_EXPORT_CONTRACT.md) |
| 2 | Travel Time Provider decided | ✅ PASS | [ADR_002_TRAVEL_TIME_PROVIDER.md](ADR_002_TRAVEL_TIME_PROVIDER.md) |
| 3 | E2E flow tested in staging | ✅ PASS | [test_e2e_osrm_flow.py](../tests/test_e2e_osrm_flow.py) |
| 4 | Matrix determinism verified | ✅ PASS | Hash reproducibility in E2E test |
| 5 | ArtifactStore configured | ✅ PASS | Local/S3/Azure support in [artifact_store.py](../services/evidence/artifact_store.py) |
| 6 | RLS isolation verified | ✅ PASS | [test_rls_parallel_leak.py](../tests/test_rls_parallel_leak.py) |
| 7 | Repair engine tested | ✅ PASS | [test_repair_engine.py](../tests/test_repair_engine.py) |

### 2.2 Operational Readiness

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 8 | Dispatcher Runbook complete | ✅ PASS | [DISPATCHER_RUNBOOK.md](DISPATCHER_RUNBOOK.md) |
| 9 | KPI Baseline established | ✅ PASS | [KPI_BASELINE.md](KPI_BASELINE.md) |
| 10 | Rollback procedures documented | ✅ PASS | Section 5 of this document |
| 11 | Training materials ready | ✅ PASS | Runbook + API docs |
| 12 | Support escalation defined | ✅ PASS | Runbook Section 4 |

### 2.3 Infrastructure Readiness

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 13 | PostgreSQL deployed | ✅ PASS | Production DB ready |
| 14 | Redis cache deployed | ✅ PASS | For matrix caching |
| 15 | API endpoints deployed | ✅ PASS | Staging verified |
| 16 | Monitoring configured | ✅ PASS | Prometheus + Grafana |
| 17 | Backup procedures verified | ✅ PASS | Daily DB backups |

---

## 3. Pilot Acceptance Criteria

### 3.1 MUST PASS (Mandatory)

These criteria MUST be met for pilot to proceed:

| ID | Criterion | Threshold | Current | Status |
|----|-----------|-----------|---------|--------|
| M1 | Coverage | ≥ 98% stops assigned | 99%+ in tests | ✅ PASS |
| M2 | On-Time | ≥ 95% within TW | 97%+ in tests | ✅ PASS |
| M3 | No Overlap | 0 driver conflicts | 0 in all tests | ✅ PASS |
| M4 | Solver Success | ≥ 99% solve rate | 100% in staging | ✅ PASS |
| M5 | Audit Pass | 100% mandatory audits | 100% | ✅ PASS |
| M6 | Data Security | 0 cross-tenant leaks | 0 in stress test | ✅ PASS |

**Result**: All MUST PASS criteria met.

### 3.2 SHOULD MEET (Target)

Improvements expected but not blocking:

| ID | Criterion | Target | Expected | Confidence |
|----|-----------|--------|----------|------------|
| S1 | Planning Time | -90% | -95% | HIGH |
| S2 | Total Distance | -5% | -8% to -12% | MEDIUM |
| S3 | Stops/Vehicle | +15% | +20% to +25% | MEDIUM |
| S4 | Overtime Hours | -50% | -60% | LOW |

**Result**: All targets expected to meet or exceed.

---

## 4. Risk Assessment

### 4.1 Identified Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Geocoding gaps in FLS | MEDIUM | HIGH | Validation rejects; manual fix |
| Solver timeout on large days | LOW | MEDIUM | Time limit + fallback |
| User adoption resistance | MEDIUM | MEDIUM | Training + parallel run |
| Unexpected edge cases | MEDIUM | LOW | Runbook + support |
| OSRM API downtime | LOW | MEDIUM | StaticMatrix fallback |

### 4.2 Risk Matrix

```
Impact
  HIGH   │     │  ◆  │     │
         ├─────┼─────┼─────┤
  MEDIUM │     │ ◆◆  │  ◆  │
         ├─────┼─────┼─────┤
  LOW    │     │  ◆  │     │
         └─────┴─────┴─────┘
           LOW  MED  HIGH
               Likelihood

◆ = Identified risk
```

**Overall Risk Level**: MEDIUM (Acceptable for pilot)

---

## 5. Rollback Procedures

### 5.1 Rollback Triggers

Initiate rollback if ANY of:
1. Coverage drops below 95% for 2 consecutive days
2. Solver fails for > 5% of attempts
3. Cross-tenant data exposure detected
4. System unavailable > 30 minutes during operations
5. Operations manager decision

### 5.2 Rollback Steps

```
┌─────────────────────────────────────────────────────────────────┐
│  IMMEDIATE (< 15 minutes)                                       │
├─────────────────────────────────────────────────────────────────┤
│  1. Stop using SOLVEREIGN for new plans                         │
│  2. Switch to manual planning (Excel backup)                    │
│  3. Notify all dispatchers                                      │
│  4. Contact tech support                                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SHORT-TERM (< 1 hour)                                          │
├─────────────────────────────────────────────────────────────────┤
│  1. Use yesterday's routes as template                          │
│  2. Manual adjustments for new orders                           │
│  3. Document incident details                                   │
│  4. Assess root cause                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RECOVERY (< 24 hours)                                          │
├─────────────────────────────────────────────────────────────────┤
│  1. Incident post-mortem                                        │
│  2. Fix identified issues                                       │
│  3. Re-validate in staging                                      │
│  4. Approval to resume pilot                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Manual Planning Backup

**Location**: `\\lts-share\dispatch\routing_backup\manual_template.xlsx`

**Contents**:
- Previous week's route templates
- Vehicle assignments
- Customer addresses
- Time window defaults

**Usage**:
1. Copy template for today's date
2. Import FLS data manually
3. Assign routes based on previous patterns
4. Print driver sheets

### 5.4 Communication Plan

| Stage | Notify | Method | Template |
|-------|--------|--------|----------|
| Rollback initiated | Dispatchers | Teams chat | ROLLBACK_ALERT |
| Manual mode active | Drivers | SMS | MANUAL_MODE_MSG |
| Issue resolved | All staff | Email | ISSUE_RESOLVED |
| Pilot resumed | Dispatchers | Teams | PILOT_RESUMED |

---

## 6. Pilot Configuration

### 6.1 Pilot Scope

| Parameter | Value |
|-----------|-------|
| Duration | 2 weeks |
| Sites | MediaMarkt Berlin |
| Vehicles | 10-15 vans |
| Daily Stops | 100-200 |
| Vertical | MM_DELIVERY |

### 6.2 Feature Flags

```python
# Pilot feature configuration
PILOT_CONFIG = {
    "tenant_id": 1,
    "vertical": "MEDIAMARKT",
    "features": {
        "travel_time_provider": "static_matrix",  # Switch to OSRM in Week 2
        "enable_repair": True,
        "enable_freeze_window": True,
        "freeze_horizon_minutes": 60,
        "max_solver_time_seconds": 120,
    },
    "fallback": {
        "on_solver_fail": "manual_mode",
        "on_osrm_fail": "static_matrix",
    }
}
```

### 6.3 Success Metrics

| Week | Primary Metric | Target |
|------|----------------|--------|
| Week 1 | System stability | 0 critical issues |
| Week 2 | KPI improvement | Meet SHOULD targets |

---

## 7. Pilot Timeline

```
Week 0 (Prep)        Week 1 (Soft Launch)     Week 2 (Full Pilot)
│                    │                        │
├── Baseline data    ├── Parallel run         ├── Primary system
├── Training         ├── Manual backup ready  ├── OSRM enabled
├── Staging final    ├── Daily reviews        ├── KPI comparison
│                    │                        │
▼                    ▼                        ▼
Gate 6 Decision      Week 1 Review            Pilot Summary
```

### 7.1 Key Dates

| Date | Milestone |
|------|-----------|
| 2026-01-06 | Gate 6 Go/No-Go Decision |
| 2026-01-07 | Pilot Week 1 Start |
| 2026-01-10 | Week 1 Midpoint Review |
| 2026-01-13 | Week 1 End / Week 2 Start |
| 2026-01-17 | Week 2 Midpoint Review |
| 2026-01-20 | Pilot End / Final Review |

---

## 8. Approval Matrix

### 8.1 Required Approvals

| Role | Name | Decision | Date | Signature |
|------|------|----------|------|-----------|
| Operations Manager | _______________ | GO / NO-GO | ________ | ________ |
| IT Lead | _______________ | GO / NO-GO | ________ | ________ |
| Dispatcher Lead | _______________ | GO / NO-GO | ________ | ________ |

### 8.2 Final Decision

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   GATE 6 DECISION:   [ ] GO    [ ] CONDITIONAL GO    [ ] NO-GO │
│                                                                 │
│   Date: _________________                                       │
│                                                                 │
│   Conditions (if CONDITIONAL GO):                               │
│   ______________________________________________________________│
│   ______________________________________________________________│
│   ______________________________________________________________│
│                                                                 │
│   Decision Made By: ____________________________________________│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. Post-Pilot Actions

### 9.1 If GO Decision

1. Confirm pilot start date
2. Enable production access for dispatchers
3. Schedule daily standups
4. Monitor dashboards
5. Collect feedback

### 9.2 If CONDITIONAL GO

1. Document conditions to meet
2. Set deadline for conditions
3. Re-evaluate at deadline
4. Proceed with reduced scope if needed

### 9.3 If NO-GO Decision

1. Document blocking issues
2. Create remediation plan
3. Set new Gate 6 date
4. Continue staging validation

---

## 10. Supporting Documents

| Document | Location | Purpose |
|----------|----------|---------|
| FLS Export Contract | [FLS_EXPORT_CONTRACT.md](FLS_EXPORT_CONTRACT.md) | Data format spec |
| Provider ADR | [ADR_002_TRAVEL_TIME_PROVIDER.md](ADR_002_TRAVEL_TIME_PROVIDER.md) | Travel time decision |
| Dispatcher Runbook | [DISPATCHER_RUNBOOK.md](DISPATCHER_RUNBOOK.md) | Operations guide |
| KPI Baseline | [KPI_BASELINE.md](KPI_BASELINE.md) | Success metrics |
| API Documentation | `/api/docs` | Technical reference |
| Test Results | `/tests/` | Validation evidence |

---

## Appendix A: Checklist Summary

### Pre-Pilot Checklist

- [ ] Gate 6 approval obtained
- [ ] All dispatchers trained
- [ ] Backup procedures tested
- [ ] Monitoring dashboards verified
- [ ] Support contacts confirmed
- [ ] Feature flags configured
- [ ] FLS integration tested
- [ ] Evidence storage configured

### Day 1 Checklist

- [ ] FLS export successful
- [ ] Import validation passed
- [ ] Solver completed
- [ ] Audits passed
- [ ] Plan locked
- [ ] Routes published
- [ ] Drivers confirmed
- [ ] No critical issues

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-06 | SOLVEREIGN | Initial Gate 6 document |
