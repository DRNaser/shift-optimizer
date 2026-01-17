# SOLVEREIGN - Wien Pilot Dry Run Runbook

> **Version**: 1.0
> **Last Updated**: 2026-01-17
> **Pilot**: LTS Transport Wien (46 Fahrzeuge)
> **Order Source**: FLS

---

## Overview

This runbook guides the Wien Pilot dry run through the complete pipeline:

```
IMPORT → SOLVE → AUDIT → LOCK/FREEZE → EVIDENCE → REPAIR
```

---

## Prerequisites

### Environment
- [ ] Docker + Docker Compose installed
- [ ] `docker-compose.pilot.yml` accessible
- [ ] API container running (`docker compose -f docker-compose.pilot.yml up -d`)
- [ ] Fresh DB proof passed (migrations applied)

### Data
- [ ] FLS export file available (JSON or CSV format)
- [ ] Test tenant created (tenant_id known)
- [ ] Test site created (site_id known)

### Network (for OSRM)
- [ ] OSRM container running (optional but recommended)
- [ ] OR: Static matrix available as fallback

---

## Input Contract: FLS Export Format

### JSON Format (Recommended)

```json
{
  "meta": {
    "export_date": "2026-01-17T10:00:00Z",
    "source": "FLS",
    "version": "1.0"
  },
  "orders": [
    {
      "order_id": "FLS-12345",
      "service_code": "DEL",
      "time_window": {
        "start": "2026-01-20T08:00:00",
        "end": "2026-01-20T12:00:00"
      },
      "location": {
        "lat": 48.2082,
        "lng": 16.3738,
        "address": "Stephansplatz 1, 1010 Wien"
      },
      "duration_minutes": 15,
      "priority": "NORMAL"
    }
  ],
  "vehicles": [
    {
      "vehicle_id": "V-001",
      "capacity": 100,
      "shift_start": "06:00",
      "shift_end": "14:00",
      "home_depot": {
        "lat": 48.1951,
        "lng": 16.3890
      }
    }
  ]
}
```

### CSV Format (Alternative)

```csv
order_id,service_code,tw_start,tw_end,lat,lng,address,duration_min,priority
FLS-12345,DEL,2026-01-20T08:00:00,2026-01-20T12:00:00,48.2082,16.3738,"Stephansplatz 1, 1010 Wien",15,NORMAL
FLS-12346,DEL,2026-01-20T09:00:00,2026-01-20T13:00:00,48.2100,16.3700,"Kärntner Str. 10, 1010 Wien",10,HIGH
```

### Required Fields

| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `order_id` | string | Unique order identifier | YES |
| `service_code` | string | Service type (DEL, PU, etc.) | YES |
| `tw_start` | ISO datetime | Time window start | YES |
| `tw_end` | ISO datetime | Time window end | YES |
| `lat` | float | Latitude (WGS84) | YES for OSRM |
| `lng` | float | Longitude (WGS84) | YES for OSRM |
| `duration_min` | int | Service duration in minutes | YES |

---

## Routing Decision: OSRM vs Static Matrix

### Decision Matrix

| Condition | Use |
|-----------|-----|
| All orders have valid lat/lng | OSRM |
| Missing/invalid coordinates | Static Matrix |
| OSRM container unavailable | Static Matrix |
| < 50 orders (quick test) | Either |
| > 100 orders | OSRM (performance) |

### OSRM Setup

```bash
# Start OSRM container (with routing profile)
docker compose -f docker-compose.yml --profile routing up -d osrm

# Verify OSRM is running
curl http://localhost:5000/status
```

### Static Matrix Fallback

If OSRM is unavailable or coordinates are missing:

```bash
# Run with static matrix
python scripts/run_wien_pilot_dry_run.py \
    --input data/fls_export.json \
    --skip-osrm
```

---

## Dry Run Steps

### Step 1: Prepare Input Data

```bash
# Place FLS export in data directory
mkdir -p data
cp /path/to/fls_export.json data/wien_pilot_input.json

# Verify format
python -c "import json; print(len(json.load(open('data/wien_pilot_input.json'))['orders']))"
```

### Step 2: Run Full Pipeline

```bash
# Full dry run (OSRM enabled)
python scripts/run_wien_pilot_dry_run.py \
    --input data/wien_pilot_input.json \
    --output-dir runs/wien_pilot_$(date +%Y%m%d)

# Without OSRM (static matrix)
python scripts/run_wien_pilot_dry_run.py \
    --input data/wien_pilot_input.json \
    --output-dir runs/wien_pilot_$(date +%Y%m%d) \
    --skip-osrm
```

### Step 3: Inspect Output

```bash
# Check manifest
cat runs/wien_pilot_*/manifest.json | jq .

# Check verdict chain
cat runs/wien_pilot_*/manifest.json | jq '.stages | to_entries[] | {stage: .key, verdict: .value.verdict}'
```

---

## Pipeline Stages

### Stage 1: IMPORT
- Reads FLS export
- Validates required fields
- Creates internal order objects

**Expected Output:**
- `import_result.json` with order count
- `orders_validated.json` with processed orders

**Pass Criteria:**
- [ ] All orders parsed successfully
- [ ] No missing required fields
- [ ] Order count matches expected

### Stage 2: COORDS_GATE (if OSRM)
- Validates coordinates are within Austria bounds
- Checks for duplicates

**Expected Output:**
- `coords_validation.json`

**Pass Criteria:**
- [ ] All coordinates within Austria (lat: 46.4-49.0, lng: 9.5-17.2)
- [ ] No duplicate order_ids

### Stage 3: SOLVE
- Runs OR-Tools solver
- Generates route assignments

**Expected Output:**
- `solution.json` with routes
- `solver_metrics.json` with KPIs

**Pass Criteria:**
- [ ] Solver exits with optimal/feasible status
- [ ] All orders assigned to routes
- [ ] No time window violations

### Stage 4: FINALIZE
- Validates routes against constraints
- Calculates final KPIs

**Expected Output:**
- `finalized_routes.json`
- `kpi_report.json`

**Pass Criteria:**
- [ ] All routes valid
- [ ] KPIs within acceptable range

### Stage 5: DRIFT_GATE
- Compares against baseline (if exists)
- Detects significant changes

**Expected Output:**
- `drift_report.json`

**Pass Criteria:**
- [ ] No critical drift detected
- [ ] OR: Drift acknowledged and documented

### Stage 6: AUDIT
- Runs 7 audit checks
- Generates evidence pack

**Expected Output:**
- `audit_results.json`
- `evidence_pack/` directory

**Pass Criteria:**
- [ ] 7/7 audits PASS

### Stage 7: LOCK/FREEZE
- Locks plan for publishing
- Creates immutable snapshot

**Expected Output:**
- `lock_confirmation.json`
- `snapshot_id`

**Pass Criteria:**
- [ ] Plan state = LOCKED
- [ ] Snapshot created

---

## Expected Outputs

### Directory Structure

```
runs/wien_pilot_20260117/
├── manifest.json           # Pipeline manifest with all results
├── input/
│   └── orders_raw.json     # Original input
├── import/
│   ├── import_result.json
│   └── orders_validated.json
├── solve/
│   ├── solution.json
│   └── solver_metrics.json
├── finalize/
│   ├── finalized_routes.json
│   └── kpi_report.json
├── audit/
│   ├── audit_results.json
│   └── evidence_pack/
│       ├── coverage_proof.json
│       ├── constraint_proof.json
│       └── hash_manifest.json
└── lock/
    └── lock_confirmation.json
```

### Manifest Structure

```json
{
  "run_id": "wien_pilot_20260117_143052",
  "started_at": "2026-01-17T14:30:52Z",
  "completed_at": "2026-01-17T14:35:12Z",
  "overall_verdict": "GO",
  "can_publish": true,
  "stages": {
    "import_stage": {"success": true, "verdict": "PASS"},
    "coords_gate": {"success": true, "verdict": "PASS"},
    "solve_stage": {"success": true, "verdict": "OPTIMAL"},
    "finalize_stage": {"success": true, "verdict": "PASS"},
    "drift_gate": {"success": true, "verdict": "NO_DRIFT"},
    "audit_stage": {"success": true, "verdict": "7/7 PASS"},
    "lock_stage": {"success": true, "verdict": "LOCKED"}
  },
  "kpis": {
    "total_orders": 150,
    "assigned_orders": 150,
    "coverage_percent": 100.0,
    "total_routes": 12,
    "avg_stops_per_route": 12.5,
    "total_distance_km": 245.3,
    "total_duration_hours": 18.5
  }
}
```

---

## KPI Baseline Checklist

After successful dry run, document baseline KPIs:

| KPI | Baseline Value | Acceptable Range |
|-----|----------------|------------------|
| Coverage % | ___% | > 98% |
| Orders/Day | ___ | 100-200 |
| Routes/Day | ___ | 10-20 |
| Avg Stops/Route | ___ | 10-15 |
| Avg Route Duration | ___ h | 4-8 h |
| Total Distance | ___ km | < 500 km |

---

## Repair Flow (Post-Dry-Run)

If issues are found after lock:

### 1. Identify Repair Candidates

```bash
# Check for violations
cat runs/wien_pilot_*/audit/audit_results.json | jq '.violations'
```

### 2. Run Repair Session

```bash
# Start repair session
python scripts/run_repair_session.py \
    --plan-id <locked_plan_id> \
    --reason "Time window adjustment"
```

### 3. Re-validate

```bash
# Re-run audit after repair
python scripts/run_wien_pilot_dry_run.py \
    --input runs/wien_pilot_*/finalize/finalized_routes.json \
    --repair-mode
```

---

## Troubleshooting

### OSRM Connection Failed

```bash
# Check OSRM status
curl http://localhost:5000/status

# If down, restart
docker compose -f docker-compose.yml --profile routing restart osrm
```

### Solver Timeout

```bash
# Increase time budget
python scripts/run_wien_pilot_dry_run.py \
    --input data/wien_pilot_input.json \
    --time-budget 300  # 5 minutes
```

### Missing Coordinates

```bash
# Run without OSRM
python scripts/run_wien_pilot_dry_run.py \
    --input data/wien_pilot_input.json \
    --skip-osrm
```

### Audit Failures

```bash
# Check specific audit failures
cat runs/wien_pilot_*/audit/audit_results.json | jq '.checks[] | select(.passed == false)'
```

---

## Sign-Off Checklist

Before declaring dry run successful:

```
[ ] Full pipeline completed (all stages PASS)
[ ] 7/7 audits PASS
[ ] KPIs documented (baseline)
[ ] Evidence pack generated
[ ] Plan locked successfully
[ ] Manifest reviewed and saved
[ ] No critical warnings in logs
```

**Sign-off:**

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Ops Lead | | | |
| QA | | | |
| Product | | | |

---

*This runbook is the single source of truth for Wien Pilot dry runs.*
