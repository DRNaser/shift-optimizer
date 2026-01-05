# SOLVEREIGN - Pilot Week Acceptance Checklist

**Version**: 1.0
**Date**: 2026-01-05
**Tenant**: LTS Transport & Logistik GmbH

---

## Overview

This document defines the minimum acceptance criteria for production deployment.
**ALL items must PASS before enabling production traffic.**

---

## Section A: Core Functionality (Go/No-Go)

| # | Check | Expected | Actual | Status |
|---|-------|----------|--------|--------|
| A1 | Coverage | 100% tours assigned | | [ ] |
| A2 | Audits | 7/7 PASS | | [ ] |
| A3 | Lock - APPROVER | Only APPROVER can lock | | [ ] |
| A4 | Lock - M2M blocked | App tokens get 403 | | [ ] |
| A5 | Proof Pack | ZIP exportable + verifiable | | [ ] |
| A6 | RLS Isolation | No cross-tenant data | | [ ] |

### Evidence Required

**A1-A2**: Screenshot of plan with 100% coverage + all audits PASS
**A3-A4**: curl output showing 403 for PLANNER/M2M, 200 for APPROVER
**A5**: Proof pack ZIP opened, hash verified
**A6**: `test_rls_parallel_leak.py` output showing 0 leaks

---

## Section B: Repair Drill (Stress Test)

### Scenario B1: Minor Disruption (2 drivers sick)

| Metric | Acceptance | Actual | Status |
|--------|------------|--------|--------|
| Repair time | < 30 seconds | | [ ] |
| Coverage after repair | 100% | | [ ] |
| Freeze violations | 0 | | [ ] |
| Churn rate | < 15% | | [ ] |

**Procedure**:
1. Take current LOCKED plan
2. Mark 2 random drivers as unavailable
3. Run repair solve
4. Record metrics above

### Scenario B2: Major Disruption (6 drivers sick)

| Metric | Acceptance | Actual | Status |
|--------|------------|--------|--------|
| Repair time | < 60 seconds | | [ ] |
| Coverage after repair | 100% OR clear FAIL | | [ ] |
| Freeze violations | Documented if any | | [ ] |
| Additional drivers needed | Documented | | [ ] |

**Procedure**:
1. Take current LOCKED plan
2. Mark 6 random drivers as unavailable
3. Run repair solve
4. If FAIL: Document "need X standby drivers"
5. If PASS: Record metrics

**Acceptance**: Either 100% coverage OR clear actionable failure message.
No silent partial failures allowed.

---

## Section C: Authentication Verification

| # | Check | Test | Expected | Status |
|---|-------|------|----------|--------|
| C1 | Token without tid | Call /plans | 403 MISSING_TID | [ ] |
| C2 | Unmapped tenant | Call /plans | 403 TENANT_NOT_MAPPED | [ ] |
| C3 | PLANNER /solve | POST /solve | 200 OK | [ ] |
| C4 | PLANNER /lock | POST /lock | 403 INSUFFICIENT_ROLE | [ ] |
| C5 | APPROVER /lock | POST /lock | 200 LOCKED | [ ] |
| C6 | M2M /solve | POST /solve | 200 OK | [ ] |
| C7 | M2M /lock | POST /lock | 403 APP_TOKEN_NOT_ALLOWED | [ ] |
| C8 | Token expiry | Wait for exp | 401 Token expired | [ ] |

---

## Section D: Parallel Load Test

| Metric | Acceptance | Actual | Status |
|--------|------------|--------|--------|
| Parallel requests | 50+ concurrent | | [ ] |
| RLS leaks | 0 | | [ ] |
| Error rate | < 1% | | [ ] |
| P99 latency | < 5 seconds | | [ ] |

**Command**:
```bash
python backend_py/tests/test_rls_parallel_leak.py \
  --parallel=50 \
  --rounds=10 \
  --verbose
```

---

## Section E: Operational Readiness

| # | Check | Evidence | Status |
|---|-------|----------|--------|
| E1 | Backup before migration | DB snapshot timestamp | [ ] |
| E2 | Rollback tested | Restore verified | [ ] |
| E3 | Monitoring active | Grafana/logs accessible | [ ] |
| E4 | Alerting configured | Test alert received | [ ] |
| E5 | Runbook available | Link to docs | [ ] |
| E6 | On-call assigned | Name + contact | [ ] |

---

## Section F: Single Source of Truth Agreement

**CRITICAL ORGANIZATIONAL REQUIREMENT**

By signing below, stakeholders confirm:

1. **LOCKED Plan = Truth**: The LOCKED plan in SOLVEREIGN is the authoritative source
2. **No Excel Overrides**: Changes require new plan version (supersede), not manual edits
3. **Audit Trail Required**: All changes tracked in system, no out-of-band modifications
4. **Immutability Respected**: LOCKED plans cannot be modified, only superseded

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Operations Lead | | | |
| Dispatcher | | | |
| IT Admin | | | |

---

## Cutover Sequence

```
PRE-CUTOVER (Day -1)
[ ] 1. DB backup/snapshot
[ ] 2. Migration 012_tenant_identities.sql applied
[ ] 3. Tenant identity registered
[ ] 4. Environment variables set
[ ] 5. API restarted
[ ] 6. activation_checks.py PASS

CUTOVER (Day 0)
[ ] 7. Parallel leak test (50 requests, 10 rounds)
[ ] 8. Soft launch: 1 Dispatcher + 1 Approver
[ ] 9. First real plan created
[ ] 10. First real lock by APPROVER
[ ] 11. Proof pack exported + verified
[ ] 12. Repair drill (2 drivers sick)

POST-CUTOVER (Day +1 to +5)
[ ] 13. Monitor for 403 errors (TENANT_NOT_MAPPED)
[ ] 14. Monitor for RLS violations
[ ] 15. Daily pilot user feedback
[ ] 16. Repair drill (6 drivers sick)

PRODUCTION (Day +7)
[ ] 17. All pilots confirmed
[ ] 18. Full user rollout
[ ] 19. Acceptance document signed
```

---

## Decision

### Go / No-Go

| Section | All Pass? | Blocker? |
|---------|-----------|----------|
| A: Core Functionality | [ ] | |
| B: Repair Drill | [ ] | |
| C: Authentication | [ ] | |
| D: Parallel Load | [ ] | |
| E: Operational Readiness | [ ] | |
| F: SSOT Agreement | [ ] | |

**Final Decision**: [ ] GO / [ ] NO-GO

**If NO-GO, blockers**:
1.
2.
3.

---

## Signatures

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Project Lead | | | |
| Operations Lead | | | |
| IT Admin | | | |
| Security | | | |

---

*Generated: 2026-01-05*
*Document Owner: SOLVEREIGN Deployment Team*
