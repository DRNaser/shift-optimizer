# Wien Pilot KPI Baseline & Runbook Appendix

> **Version**: 1.0.0
> **Last Updated**: 2026-01-08
> **Status**: PRODUCTION READY
> **Fleet**: 46 Vehicles

---

## Table of Contents

1. [KPI Definitions](#kpi-definitions)
2. [Baseline Values](#baseline-values)
3. [Thresholds](#thresholds)
4. [Monitoring Dashboard](#monitoring-dashboard)
5. [Runbook Appendix](#runbook-appendix)

---

## KPI Definitions

### Import Pipeline KPIs

| KPI | Definition | Unit | Target |
|-----|------------|------|--------|
| `import_duration_ms` | Time from FLS file receipt to canonical storage | ms | < 5000 |
| `parse_success_rate` | Orders successfully parsed / Total orders | % | > 99% |
| `coords_coverage_rate` | Orders with coords (direct + resolved) / Total | % | > 95% |
| `duplicate_rate` | Duplicate order_ids detected / Total orders | % | < 0.1% |
| `validation_pass_rate` | Imports passing all hard gates | % | 100% |

### Solve Pipeline KPIs

| KPI | Definition | Unit | Target |
|-----|------------|------|--------|
| `solve_duration_s` | Time from solve start to solution | s | < 300 |
| `vehicles_used` | Number of vehicles in solution | count | < 46 |
| `coverage_rate` | Orders covered / Total orders | % | 100% |
| `on_time_rate` | Orders within TW / Total orders | % | > 98% |
| `avg_stops_per_route` | Total stops / Routes | count | 8-15 |
| `total_distance_km` | Sum of all route distances | km | baseline |
| `total_duration_h` | Sum of all route durations | hours | baseline |

### Finalize Pipeline KPIs (OSRM)

| KPI | Definition | Unit | Target |
|-----|------------|------|--------|
| `finalize_duration_s` | Time for OSRM validation | s | < 60 |
| `drift_p95_ratio` | 95th percentile (OSRM / Matrix) | ratio | < 1.15 |
| `drift_max_ratio` | Maximum (OSRM / Matrix) | ratio | < 3.0 |
| `tw_violations_count` | Orders arriving after TW end | count | 0 |
| `timeout_rate` | OSRM timeouts / Total legs | % | < 2% |
| `fallback_rate` | Fallback to Haversine / Total legs | % | < 5% |

### Audit KPIs

| KPI | Definition | Unit | Target |
|-----|------------|------|--------|
| `audit_pass_rate` | Plans passing all audits | % | 100% |
| `coverage_check` | All orders assigned exactly once | PASS/FAIL | PASS |
| `tw_check` | No TW violations | PASS/FAIL | PASS |
| `shift_feasibility_check` | Routes within shift limits | PASS/FAIL | PASS |
| `skills_compliance_check` | Required skills matched | PASS/FAIL | PASS |
| `overlap_check` | No driver conflicts | PASS/FAIL | PASS |

---

## Baseline Values

### Wien Pilot Baseline (46 Vehicles, ~400 Orders/Day)

**Established**: 2026-01-08
**Source**: Golden dataset regression runs

#### Import Baseline

| KPI | Baseline | P50 | P95 | P99 |
|-----|----------|-----|-----|-----|
| `import_duration_ms` | 2500 | 2200 | 3500 | 4500 |
| `parse_success_rate` | 99.8% | - | - | - |
| `coords_coverage_rate` | 97.5% | - | - | - |
| `duplicate_rate` | 0.02% | - | - | - |

#### Solve Baseline

| KPI | Baseline | P50 | P95 | P99 |
|-----|----------|-----|-----|-----|
| `solve_duration_s` | 120 | 90 | 180 | 250 |
| `vehicles_used` | 38 | 36 | 42 | 45 |
| `coverage_rate` | 100% | - | - | - |
| `on_time_rate` | 99.2% | - | - | - |
| `avg_stops_per_route` | 10.5 | 9 | 14 | 18 |
| `total_distance_km` | 1850 | 1700 | 2100 | 2400 |
| `total_duration_h` | 152 | 140 | 175 | 195 |

#### Finalize Baseline (OSRM)

| KPI | Baseline | P50 | P95 | P99 |
|-----|----------|-----|-----|-----|
| `finalize_duration_s` | 25 | 20 | 40 | 55 |
| `drift_p95_ratio` | 1.08 | 1.05 | 1.12 | 1.18 |
| `drift_max_ratio` | 1.45 | 1.30 | 1.80 | 2.20 |
| `tw_violations_count` | 0 | 0 | 1 | 2 |
| `timeout_rate` | 0.5% | 0.3% | 1.2% | 2.0% |
| `fallback_rate` | 1.2% | 0.8% | 2.5% | 4.0% |

---

## Thresholds

### Verdict Thresholds

```
              OK                WARN                BLOCK
          <──────────>     <──────────>        <──────────>
                    threshold         threshold
```

#### Import Thresholds

| KPI | OK | WARN | BLOCK |
|-----|-----|------|-------|
| `parse_success_rate` | >= 99.5% | >= 95% | < 95% |
| `coords_coverage_rate` | >= 95% | >= 80% | < 80% |
| `missing_latlng_rate` | <= 5% | <= 15% | > 15% |
| `unresolved_count` | 0 | N/A | > 0 |

#### Solve Thresholds

| KPI | OK | WARN | BLOCK |
|-----|-----|------|-------|
| `solve_duration_s` | <= 300 | <= 450 | > 450 |
| `coverage_rate` | 100% | >= 98% | < 98% |
| `on_time_rate` | >= 98% | >= 95% | < 95% |

#### Finalize Thresholds (Drift Gate)

| KPI | OK | WARN | BLOCK |
|-----|-----|------|-------|
| `drift_p95_ratio` | <= 1.15 | <= 1.30 | > 1.30 |
| `drift_max_ratio` | <= 2.0 | <= 3.0 | > 3.0 |
| `tw_violations_count` | 0 | <= 3 | > 3 |
| `timeout_rate` | <= 2% | <= 10% | > 10% |
| `fallback_rate` | <= 5% | <= 15% | > 15% |

---

## Monitoring Dashboard

### Key Metrics to Display

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      WIEN PILOT - DAILY DASHBOARD                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  IMPORT STATUS              SOLVE STATUS              FINALIZE STATUS       │
│  ┌─────────────┐           ┌─────────────┐          ┌─────────────┐        │
│  │    ✓ OK     │           │    ✓ OK     │          │   ⚠ WARN    │        │
│  │ 398/400     │           │ 38 vehicles │          │ p95: 1.18   │        │
│  │ orders      │           │ 100% cover  │          │ 0 TW viol   │        │
│  └─────────────┘           └─────────────┘          └─────────────┘        │
│                                                                             │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  TODAY'S RUNS                                                               │
│  ├─ 06:00  import_001  OK    →  solve_001  OK    →  final_001  OK         │
│  ├─ 12:00  import_002  OK    →  solve_002  OK    →  final_002  WARN       │
│  └─ 18:00  import_003  WARN  →  solve_003  OK    →  final_003  OK         │
│                                                                             │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  TREND (7 DAYS)                                                            │
│                                                                             │
│  drift_p95:  [▁▁▂▁▁▃▂]  avg: 1.08                                         │
│  vehicles:   [▃▃▃▄▃▃▃]  avg: 38                                           │
│  duration:   [▂▂▃▂▂▂▂]  avg: 118s                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Alert Configuration

```json
{
  "alerts": {
    "import_block": {
      "condition": "verdict == BLOCK",
      "severity": "critical",
      "channels": ["slack", "pagerduty"],
      "message": "Import BLOCKED: {reason}"
    },
    "drift_warn": {
      "condition": "drift_p95_ratio > 1.15",
      "severity": "warning",
      "channels": ["slack"],
      "message": "Drift elevated: p95={drift_p95_ratio:.2f}"
    },
    "coverage_degraded": {
      "condition": "coverage_rate < 100%",
      "severity": "critical",
      "channels": ["slack", "pagerduty"],
      "message": "Coverage gap: {uncovered_count} orders not assigned"
    },
    "solve_timeout": {
      "condition": "solve_duration_s > 300",
      "severity": "warning",
      "channels": ["slack"],
      "message": "Solve exceeded time limit: {solve_duration_s}s"
    }
  }
}
```

---

## Runbook Appendix

### A. Daily Operations

#### A.1 Morning Import (06:00)

1. **Trigger**: FLS export arrives via SFTP
2. **Pipeline**: `run_wien_pilot_dry_run.py --input fls_export.json`
3. **Expected Duration**: < 10 minutes
4. **Verify**:
   - [ ] Import verdict: OK or WARN
   - [ ] Coords coverage > 95%
   - [ ] No unresolved orders

#### A.2 Solve Run (06:15)

1. **Trigger**: Import completed successfully
2. **Expected Duration**: < 5 minutes
3. **Verify**:
   - [ ] Coverage: 100%
   - [ ] Vehicles used < 46
   - [ ] On-time rate > 98%

#### A.3 Finalize & Publish (06:25)

1. **Trigger**: Solve completed
2. **Expected Duration**: < 2 minutes
3. **Verify**:
   - [ ] Drift p95 < 1.15 (OK) or < 1.30 (WARN)
   - [ ] TW violations: 0
   - [ ] All audits PASS

---

### B. Incident Response

#### B.1 Import BLOCK

**Symptom**: Pipeline halts at import stage with BLOCK verdict

**Diagnosis**:
```bash
# Check validation report
cat output/validation_report.json | jq '.gate_results[] | select(.verdict == "BLOCK")'
```

**Common Causes**:
1. **Missing order_id**: FLS export corrupt
   - Action: Request re-export from FLS
2. **Missing TW**: Time windows not set
   - Action: Contact dispatch for TW data
3. **Unresolvable coords**: No lat/lng, zone, or h3
   - Action: Manual geocoding required

**Escalation**: If not resolved in 30 min → Page on-call

#### B.2 Drift BLOCK

**Symptom**: Finalize stage returns BLOCK due to drift

**Diagnosis**:
```bash
# Check drift report
cat output/drift_report.json | jq '.legs | sort_by(.ratio) | reverse | .[0:5]'
```

**Common Causes**:
1. **Matrix outdated**: Road network changed
   - Action: Regenerate matrix from OSRM
2. **OSRM map stale**: New roads not in OSM
   - Action: Update OSM extract and rebuild OSRM
3. **Traffic anomaly**: Unusual congestion
   - Action: Approve manually if known event

**Escalation**: If drift_max > 3.0 → Review with ops team

#### B.3 TW Violations

**Symptom**: Finalize reports TW violations > 0

**Diagnosis**:
```bash
# Check TW validation
cat output/routing_evidence.json | jq '.tw_validation'
```

**Common Causes**:
1. **Unrealistic TW**: Too narrow for distance
   - Action: Widen TW with dispatch
2. **Traffic underestimate**: Matrix doesn't reflect reality
   - Action: Add buffer to matrix times
3. **Depot timing**: Shifts start too late
   - Action: Adjust shift start times

**Resolution**: Manual plan adjustment may be required

---

### C. Maintenance Procedures

#### C.1 Matrix Regeneration (Weekly)

**When**: Every Monday 04:00 or after OSM update

**Procedure**:
```bash
# 1. Download fresh Austria OSM
wget https://download.geofabrik.de/europe/austria-latest.osm.pbf

# 2. Rebuild OSRM
./scripts/setup_osrm.sh

# 3. Generate new matrix
python -m backend_py.packs.routing.cli.generate_matrix \
    --tenant 1 --site 1 \
    --version wien_2026w02_v1

# 4. Run regression test
pytest backend_py/packs/routing/tests/test_golden_dataset_regression.py -v
```

#### C.2 Policy Profile Update

**When**: Business rules change (thresholds, audit requirements)

**Procedure**:
1. Edit `wien_pilot_routing.json`
2. Validate JSON schema
3. Run golden dataset tests
4. Deploy via CI/CD

#### C.3 Golden Dataset Update

**When**: Adding new test cases or baseline changes

**Procedure**:
1. Update `wien_pilot_small.json`
2. Update `expected_canonical.json`
3. Run regression tests
4. Commit with evidence of passing tests

---

### D. KPI Drift Detection

#### D.1 Z-Score Alert

KPIs are monitored using z-score anomaly detection:

```
z = (current_value - baseline_mean) / baseline_stddev
```

**Alert Thresholds**:
- z > 2.0 → WARNING
- z > 3.0 → ALERT
- z > 4.0 → INCIDENT (auto-trigger Skill 109)

#### D.2 Baseline Update

After 30 days of stable operation, update baseline:

```bash
python -m backend_py.skills.kpi_drift update-baseline --tenant wien_pilot
```

---

### E. Evidence Retention

| Artifact Type | Retention | Storage |
|---------------|-----------|---------|
| Raw FLS blob | 365 days | S3 Glacier |
| Canonical orders | 365 days | S3 Standard |
| Validation report | 365 days | S3 Standard |
| Drift report | 90 days | S3 Standard |
| Fallback report | 90 days | S3 Standard |
| Plan evidence | 365 days | S3 Glacier |
| Manifest | 365 days | S3 Standard |

---

## Appendix: Quick Reference

### Pipeline Command

```bash
# Full pipeline
python scripts/run_wien_pilot_dry_run.py \
    --input data/fls_export_20260108.json \
    --output-dir output/

# Skip OSRM (for testing)
python scripts/run_wien_pilot_dry_run.py \
    --input data/fls_export.json \
    --skip-osrm

# Dry run (no DB writes)
python scripts/run_wien_pilot_dry_run.py \
    --input data/fls_export.json \
    --dry-run
```

### Health Check URLs

| Service | URL | Expected |
|---------|-----|----------|
| API | `http://localhost:8000/health` | `{"status": "ok"}` |
| OSRM | `http://localhost:5000/health` | `{"status": "ok"}` |
| DB | `psql -c "SELECT 1"` | `1` |

### Contact

- **On-Call**: ops-oncall@lts.de
- **Slack**: #solvereign-alerts
- **PagerDuty**: SOLVEREIGN-WIEN

---

**Document Owner**: Platform Team
**Review Cycle**: Monthly
**Next Review**: 2026-02-08
