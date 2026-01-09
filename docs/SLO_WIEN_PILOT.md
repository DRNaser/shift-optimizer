# Service Level Objectives (SLO) - Wien Pilot

**System**: SOLVEREIGN V3.7
**Scope**: Wien Pilot (46 Vehicles)
**Effective**: 2026-W02 onwards
**Review Cycle**: Weekly during pilot, monthly post-GA

---

## 1) Overview

This document defines Service Level Objectives (SLOs) for the Wien Pilot deployment. SLOs establish measurable targets that balance reliability with development velocity.

**SLO Philosophy**:
- Start with achievable targets based on baseline measurements
- Tighten targets as system matures
- Alert on burn rate, not raw metrics
- Error budgets enable controlled risk-taking

---

## 2) SLO Summary Table

| Category | Metric | Target | Alert Threshold | Measurement |
|----------|--------|--------|-----------------|-------------|
| **Availability** | Uptime | 99.5% | <99.0% over 1h | /health/ready |
| **Latency** | API P95 | <2s | >3s over 5min | All endpoints |
| **Latency** | Solver P95 | <30s | >60s over 5min | /solve endpoint |
| **Correctness** | Audit Pass Rate | 100% | Any FAIL | All 7 audits |
| **Correctness** | Coverage | 100% | <99% | Tours assigned |
| **Repair** | Churn Rate | <10% | >20% | Sick-call repairs |
| **Security** | RLS Violations | 0 | Any | Cross-tenant access |

---

## 3) Availability SLO

### 3.1 Definition

**Uptime** = Time `/health/ready` returns HTTP 200 with `ready: true`

### 3.2 Target

| Period | Target | Error Budget |
|--------|--------|--------------|
| Weekly | 99.5% | 50 minutes |
| Monthly | 99.5% | 3.6 hours |

### 3.3 Exclusions

- Scheduled maintenance windows (Sunday 02:00-06:00 CET)
- Force majeure events (documented)
- Upstream provider outages (Azure, PostgreSQL)

### 3.4 Health Check Components

The `/health/ready` endpoint checks:

```json
{
  "status": "healthy",
  "ready": true,
  "checks": {
    "database": "ok",
    "migrations": "v025f_acl_fix",
    "entitlement_cache": "warm",
    "solver": "available"
  },
  "timestamp": "2026-01-08T10:00:00Z"
}
```

| Component | Healthy Condition |
|-----------|-------------------|
| `database` | Connection pool available, query <100ms |
| `migrations` | Latest migration applied |
| `entitlement_cache` | Loaded within TTL |
| `solver` | OR-Tools initialized |

### 3.5 Monitoring

```bash
# Health check every 60 seconds
curl -s https://api.solvereign.com/health/ready | jq '.ready'

# Alert if unhealthy for 5 consecutive checks
```

---

## 4) Latency SLO

### 4.1 API Latency (Non-Solver)

**Endpoints**: `/forecasts/*`, `/plans/*`, `/tenants/*`, `/health/*`

| Percentile | Target | Alert |
|------------|--------|-------|
| P50 | <200ms | — |
| P95 | <2s | >3s for 5min |
| P99 | <5s | >10s for 1min |

### 4.2 Solver Latency

**Endpoint**: `POST /solve`

| Percentile | Target | Alert |
|------------|--------|-------|
| P50 | <10s | — |
| P95 | <30s | >60s for 5min |
| P99 | <60s | >120s for 1min |

**Note**: Solver time depends on problem size. Wien Pilot (46 vehicles, ~1400 tours) baseline is ~15s.

### 4.3 Measurement

Latency is measured server-side from request receipt to response send:

```python
# Structured log fields
{
    "request_id": "uuid",
    "tenant_id": "wien_pilot",
    "endpoint": "/api/v1/solve",
    "method": "POST",
    "latency_ms": 15234,
    "status_code": 200
}
```

### 4.4 Baseline Measurements (Wien Pilot)

From staging soak tests:

| Endpoint | P50 | P95 | P99 |
|----------|-----|-----|-----|
| `GET /health/ready` | 8ms | 15ms | 25ms |
| `GET /forecasts/{id}` | 45ms | 120ms | 250ms |
| `POST /forecasts` | 180ms | 450ms | 800ms |
| `POST /solve` | 12s | 18s | 25s |
| `POST /lock` | 85ms | 200ms | 350ms |

---

## 5) Correctness SLO

### 5.1 Audit Pass Rate

**Target**: 100% of locked plans pass all 7 audits

| Audit | Description | Target |
|-------|-------------|--------|
| Coverage | Every tour assigned exactly once | 100% |
| Overlap | No driver works concurrent tours | 0 violations |
| Rest | >=11h rest between consecutive days | 0 violations |
| Span Regular | 1er/2er-reg blocks <=14h | 0 violations |
| Span Split | 3er/split blocks <=16h | 0 violations |
| Fatigue | No consecutive 3er->3er | 0 violations |
| Reproducibility | Same seed -> same output | 100% match |

### 5.2 Coverage Rate

**Target**: 100% of tours assigned

| Metric | Target | Alert |
|--------|--------|-------|
| Assigned Tours | 100% | <99% |
| Unassigned Tours | 0 | >0 |

### 5.3 Measurement

```python
# After each solve
{
    "plan_version_id": 123,
    "audit_results": {
        "all_passed": true,
        "checks_run": 7,
        "checks_passed": 7
    },
    "coverage": {
        "total_tours": 1385,
        "assigned": 1385,
        "unassigned": 0,
        "rate": 1.0
    }
}
```

---

## 6) Repair SLO

### 6.1 Churn Rate

**Definition**: Percentage of assignments changed during repair operation

**Target**: <10% churn on sick-call repairs

| Scenario | Target Churn | Max Churn |
|----------|--------------|-----------|
| 1 driver sick | <3% | 5% |
| 3 drivers sick | <5% | 10% |
| 5 drivers sick | <10% | 20% |

### 6.2 Coverage After Repair

**Target**: 100% coverage maintained after repair

### 6.3 Measurement

```python
# After each repair
{
    "repair_type": "sick_call",
    "absent_drivers": ["DRV001", "DRV002", "DRV003"],
    "churn_metrics": {
        "assignments_changed": 42,
        "total_assignments": 1385,
        "churn_rate": 0.0303
    },
    "coverage_maintained": true
}
```

---

## 7) Security SLO

### 7.1 RLS Violations

**Target**: Zero cross-tenant data access

| Metric | Target | Alert |
|--------|--------|-------|
| RLS violations | 0 | Any (S0 incident) |
| Auth failures (wrong method) | 0 | >10/hour |
| Replay attacks blocked | 100% | Any accepted |

### 7.2 Measurement

```sql
-- Security event monitoring
SELECT event_type, COUNT(*)
FROM core.security_events
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY event_type;
```

---

## 8) Alert Thresholds

### 8.1 Severity Levels

| Severity | Response Time | Escalation | Example |
|----------|---------------|------------|---------|
| **S0** | Immediate | CTO + Security | RLS violation, data leak |
| **S1** | 15 min | Platform Lead | Availability <95%, audit FAIL |
| **S2** | 1 hour | On-call | Latency degradation, high churn |
| **S3** | Next business day | Ticket | Minor warnings, cosmetic issues |

### 8.2 Alert Rules

```yaml
# Availability
- name: availability_critical
  condition: health_ready_success_rate < 0.95 for 5m
  severity: S1
  action: page_oncall

# Latency
- name: solver_slow
  condition: solver_p95_latency > 60s for 5m
  severity: S2
  action: notify_slack

# Correctness
- name: audit_failure
  condition: audit_pass_rate < 1.0
  severity: S1
  action: page_oncall, block_release

# Security
- name: rls_violation
  condition: rls_violation_count > 0
  severity: S0
  action: page_all, disable_writes, trigger_incident
```

---

## 9) Error Budget Policy

### 9.1 Error Budget Calculation

```
Error Budget = (1 - SLO Target) * Measurement Period

Example (Weekly, 99.5% availability):
Error Budget = (1 - 0.995) * 10080 minutes = 50.4 minutes
```

### 9.2 Budget Consumption Actions

| Budget Remaining | Action |
|------------------|--------|
| >50% | Normal development |
| 25-50% | Increase monitoring, review changes |
| 10-25% | Feature freeze, focus on reliability |
| <10% | All hands on reliability, no deployments |
| Exhausted | Postmortem required, extended freeze |

### 9.3 Budget Reset

- Weekly budgets reset Monday 00:00 UTC
- Monthly budgets reset 1st of month 00:00 UTC
- Carryover not allowed

---

## 10) Reporting

### 10.1 Weekly SLO Report

Generated automatically every Monday:

```json
{
  "period": "2026-W02",
  "slo_summary": {
    "availability": {"target": 0.995, "actual": 0.998, "status": "OK"},
    "latency_api_p95": {"target": 2000, "actual": 850, "status": "OK"},
    "latency_solver_p95": {"target": 30000, "actual": 18500, "status": "OK"},
    "audit_pass_rate": {"target": 1.0, "actual": 1.0, "status": "OK"},
    "coverage_rate": {"target": 1.0, "actual": 1.0, "status": "OK"}
  },
  "error_budget": {
    "weekly_budget_minutes": 50.4,
    "consumed_minutes": 12.5,
    "remaining_percent": 75.2
  },
  "incidents": [],
  "notable_events": []
}
```

### 10.2 Monthly SLO Review

- Review SLO performance vs targets
- Adjust targets if consistently exceeded (tighten) or missed (investigate)
- Update alert thresholds as needed
- Document any policy exceptions

---

## 11) Observability Requirements

### 11.1 Structured Logging

All requests must log:

```json
{
  "timestamp": "2026-01-08T10:00:00.123Z",
  "level": "INFO",
  "request_id": "uuid-1234",
  "tenant_id": "wien_pilot",
  "site_id": "site_001",
  "auth_mode": "api_key",
  "pack_id": "roster",
  "run_id": "run_456",
  "endpoint": "/api/v1/solve",
  "method": "POST",
  "latency_ms": 15234,
  "status_code": 200,
  "solver_runtime_ms": 14500,
  "tours_count": 1385,
  "drivers_count": 145
}
```

### 11.2 Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `solvereign_request_duration_ms` | Histogram | endpoint, method, status |
| `solvereign_solver_runtime_ms` | Histogram | tenant_id, tours_count |
| `solvereign_audit_result` | Counter | check_name, status |
| `solvereign_repair_churn_rate` | Gauge | tenant_id, repair_type |
| `solvereign_coverage_rate` | Gauge | tenant_id |
| `solvereign_active_drivers` | Gauge | tenant_id |

### 11.3 Health Endpoint Enhancement

```python
@app.get("/health/ready")
async def health_ready():
    return {
        "status": "healthy",
        "ready": True,
        "checks": {
            "database": check_database(),
            "migrations_version": get_migrations_version(),
            "entitlement_cache": check_entitlement_cache(),
            "solver": check_solver_available(),
        },
        "slo_status": {
            "availability_7d": 0.998,
            "error_budget_remaining": 0.75,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
```

---

## 12) SLO Review Cadence

| Review | Frequency | Participants | Focus |
|--------|-----------|--------------|-------|
| **Daily** | Every morning | On-call | Overnight incidents, budget burn |
| **Weekly** | Monday | Platform team | Weekly SLO report, trends |
| **Monthly** | 1st week | All stakeholders | Target adjustment, policy review |
| **Quarterly** | Q+1 week | Leadership | Strategic SLO changes |

---

## 13) Appendix: Baseline Data

### 13.1 Wien Pilot Baseline (from staging soak)

| Metric | Baseline Value | Date |
|--------|----------------|------|
| Solver runtime (46 vehicles) | 15s median | 2026-01-08 |
| API latency P95 | 850ms | 2026-01-08 |
| Audit pass rate | 100% | 2026-01-08 |
| Coverage rate | 100% | 2026-01-08 |
| Repair churn (3 sick) | 3.03% | 2026-01-08 |

### 13.2 KPI Drift Thresholds

From `.claude/state/wien_baseline.json`:

```json
{
  "drivers": {"baseline": 145, "warn_percent": 5, "alert_percent": 10},
  "coverage": {"baseline": 1.0, "warn_threshold": 0.99, "alert_threshold": 0.95},
  "pt_ratio": {"baseline": 0.0, "warn_threshold": 0.05, "alert_threshold": 0.1}
}
```

---

**Document Version**: 1.0

**Last Updated**: 2026-01-08

**Next Review**: 2026-01-15 (end of Wien Pilot W02)
