# Wien Pilot Burn-In Report

> **Week**: 2026-W__
> **Day Number**: __ / 60
> **Report Date**: _______________
> **Status**: [ ] On Track [ ] At Risk [ ] Blocked

---

## Executive Summary

| Metric | This Week | Target | Status |
|--------|-----------|--------|--------|
| Coverage Rate | | 100% | |
| Audit Pass Rate | | 100% | |
| Incidents (S0-S2) | | 0 | |
| UI Adoption Rate | | N/A (until Gate 3) | |

**Key Highlights**:
-
-

**Issues/Risks**:
-

---

## 1. Pipeline KPIs

### Import Pipeline
| KPI | Value | Baseline | Delta | Status |
|-----|-------|----------|-------|--------|
| import_duration_ms | | 2500 | | |
| parse_success_rate | | 99.8% | | |
| coords_coverage_rate | | 97.5% | | |
| validation_pass_rate | | 100% | | |

### Solve Pipeline
| KPI | Value | Baseline | Delta | Status |
|-----|-------|----------|-------|--------|
| solve_duration_s | | 120 | | |
| vehicles_used | | 38 | | |
| coverage_rate | | 100% | | |
| on_time_rate | | 99.2% | | |

### Audit Pipeline
| Check | Result | Notes |
|-------|--------|-------|
| Coverage | | |
| Overlap | | |
| Rest | | |
| Span Regular | | |
| Span Split | | |
| Fatigue | | |
| Reproducibility | | |

---

## 2. Operational Metrics

### Weekly Operations
| Metric | Value |
|--------|-------|
| Forecasts ingested | |
| Solver runs | |
| Plans published | |
| Plans locked | |
| Repair requests | |

### Incident Summary
| Severity | Count | Details |
|----------|-------|---------|
| S0 | | |
| S1 | | |
| S2 | | |
| S3 | | |

---

## 3. Dispatcher Cockpit UI Metrics

> **Phase**: [ ] Pre-Enable [ ] Gate 1 (Staging) [ ] Gate 2 (Internal) [ ] Gate 3 (Wien Live)

### UI Availability
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| UI uptime | | 99.9% | |
| Avg page load time | | < 3s | |
| API error rate | | < 1% | |

### UI Usage (When Enabled)
| Action | UI Count | CLI Count | UI % |
|--------|----------|-----------|------|
| Runs listed | | | |
| Runs viewed | | | |
| Publishes | | | |
| Locks | | | |
| Repairs submitted | | | |
| Evidence downloads | | | |

### UI Gate Enforcement
| Gate | Triggered | Blocked | Bypassed |
|------|-----------|---------|----------|
| Kill switch | | | 0 |
| Site gate (non-Wien) | | | 0 |
| Approval validation | | | 0 |
| Session expiry | | | 0 |

### UI Errors
| Error Type | Count | Trend |
|------------|-------|-------|
| 401 Unauthorized | | |
| 403 Forbidden | | |
| 400 Bad Request | | |
| 500 Server Error | | |

### CLI Fallback Usage
| Reason | Count |
|--------|-------|
| UI unavailable | |
| User preference | |
| Training | |

---

## 4. Security & Compliance

### RLS Verification
| Check | Result |
|-------|--------|
| Cross-tenant isolation | |
| Session enforcement | |
| HMAC validation | |

### Audit Trail
| Event Type | Count | Verified |
|------------|-------|----------|
| Publish events | | [ ] |
| Lock events | | [ ] |
| Repair events | | [ ] |

### Evidence Integrity
| Metric | Value |
|--------|-------|
| Evidence packs generated | |
| Hash verification pass rate | |
| Missing artifacts | 0 |

---

## 5. Burn-In Progress

### Gate Status
| Gate | Target Day | Actual Day | Status |
|------|------------|------------|--------|
| Gate 1: Staging UAT | 1-7 | | |
| Gate 2: Prod Internal | 8-14 | | |
| Gate 3: Wien Dispatchers | 30+ | | |
| Gate 4: Full Rollout | 60+ | | |

### Waiver Status
| Waiver ID | Description | Status | Due |
|-----------|-------------|--------|-----|
| WAV-2026-001 | OSRM local not Docker | | |
| WAV-2026-002 | | | |

### Milestone Checklist
| Day | Milestone | Completed |
|-----|-----------|-----------|
| 7 | Staging UAT complete | [ ] |
| 14 | Internal prod test complete | [ ] |
| 21 | No S0/S1 incidents | [ ] |
| 30 | Wien dispatcher enable | [ ] |
| 45 | 2 full weeks on UI | [ ] |
| 60 | Full rollout decision | [ ] |

---

## 6. KPI Drift Detection

### Drift Alerts (This Week)
| KPI | Expected | Actual | Drift % | Alert |
|-----|----------|--------|---------|-------|
| | | | | |

### Trend (Last 4 Weeks)
| Week | Coverage | On-Time | Vehicles | Incidents |
|------|----------|---------|----------|-----------|
| W-3 | | | | |
| W-2 | | | | |
| W-1 | | | | |
| Current | | | | |

---

## 7. Action Items

### From Last Week
| Item | Owner | Due | Status |
|------|-------|-----|--------|
| | | | |

### New This Week
| Item | Owner | Due | Priority |
|------|-------|-----|----------|
| | | | |

---

## 8. Next Week Plan

| Day | Activity | Owner |
|-----|----------|-------|
| Mon | | |
| Tue | | |
| Wed | | |
| Thu | | |
| Fri | | |

---

## Sign-Off

| Role | Name | Date |
|------|------|------|
| Platform Lead | | |
| Ops Lead | | |
| Dispatcher (if Gate 3+) | | |

---

**Report Generated**: _______________
**Next Report Due**: _______________
