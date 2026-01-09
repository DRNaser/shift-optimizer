# Routing Pack E2E Test Report

> **Date**: 2026-01-08
> **Status**: PASS
> **Determinism**: VERIFIED

---

## Test Summary

| Metric | Value |
|--------|-------|
| Dataset | `golden_datasets/routing/wien_pilot_46_vehicles/wien_pilot_all_coords.json` |
| Orders | 5 |
| Depots | 1 |
| Matrix Mode | StaticMatrix (OSRM skipped - Docker not running) |
| Profile | `wien_pilot_routing` |
| Run 1 Verdict | OK |
| Run 2 Verdict | OK |
| Can Publish | YES |

---

## Step 0: Dataset Selection

**Chosen Dataset**: `wien_pilot_all_coords.json`
- 5 orders with direct lat/lng coordinates
- 1 depot (Wien Hauptdepot)
- All orders have valid coordinates (no zone/h3 fallback needed)

**Note**: The `wien_pilot_small.json` dataset was also tested but blocked by coords gate due to 2 orders with only zone/h3 fallback (no lookup tables configured in test environment). This is expected behavior - the strict policy requires all coordinates to be resolved.

---

## Step 1: Matrix Mode Selection

| Check | Result |
|-------|--------|
| Docker Running | NO |
| OSRM Available | NO |
| Selected Mode | **StaticMatrix** (--skip-osrm) |

The test ran with StaticMatrix mode since Docker/OSRM was not available. StaticMatrix provides deterministic distance calculations using Euclidean distance.

---

## Step 2: Run 1 Results

**Run ID**: `dry_run_20260108_192341`
**Duration**: 0.097 seconds
**Output**: `artifacts/routing_e2e/run1/`

### Verdict Chain

| Gate | Verdict |
|------|---------|
| Import | OK |
| Coords Gate | OK |
| Solve | OK |
| Drift Gate | N/A (OSRM skipped) |
| Audit | PASS |
| Lock | LOCKED |
| **Overall** | **OK** |

### Hashes

| Hash | Value |
|------|-------|
| Input | `f4feaafd3f3104a6704374de721b7fccb112269a09d6fc530807ce95673e5978` |
| Canonical | `48f93eaa80945925cb7610dd0871f57b5479a1c5f0baf6fe050427ecd5aa4e6b` |

### Metrics

| Stage | Key Metrics |
|-------|-------------|
| Import | 5 orders raw, 5 canonical, 5 with coords |
| Coords Gate | 0% missing, 0% fallback, 0 unresolved |
| Solve | VRPTW/GUIDED_LOCAL_SEARCH, 5 assigned |
| Audit | 5/5 checks passed |

---

## Step 3: Run 2 (Determinism Check)

**Run ID**: `dry_run_20260108_192356`
**Duration**: 0.111 seconds
**Output**: `artifacts/routing_e2e/run2_rerun/`

### Hash Comparison

| Artifact | Run 1 | Run 2 | Match |
|----------|-------|-------|-------|
| Input Hash | `f4feaafd3f31...` | `f4feaafd3f31...` | YES |
| Canonical Hash | `48f93eaa8094...` | `48f93eaa8094...` | YES |
| canonical_orders.json | `575e56cc61ac...` | `575e56cc61ac...` | YES |
| solve_result.json | `b8f52d5e985d...` | `b8f52d5e985d...` | YES |

**Determinism Status**: VERIFIED

All content-based hashes are identical. Files with timestamps (manifest, audit_results, validation_report, coords_quality_report) differ as expected.

---

## Step 4: Drift Gate Analysis

| Check | Result |
|-------|--------|
| Drift Gate Enabled | NO (OSRM skipped) |
| Drift Report | Not generated |
| Fallback Report | Not generated |

**Note**: Drift gate only runs when OSRM finalize is enabled. In StaticMatrix mode, drift detection is not applicable.

---

## Artifacts Generated

### Run 1 (`artifacts/routing_e2e/run1/`)

| File | Description | SHA256 |
|------|-------------|--------|
| manifest.json | Run manifest with verdict chain | `605d8176a935...` |
| canonical_orders.json | Canonicalized orders | `575e56cc61ac...` |
| validation_report.json | Import validation | `76b05707c43b...` |
| coords_quality_report.json | Coords gate result | `562001a2b530...` |
| solve_result.json | Solver output | `b8f52d5e985d...` |
| audit_results.json | Audit check results | `3ea1f00faa0f...` |
| checksums.sha256 | File checksums | - |

### Run 2 (`artifacts/routing_e2e/run2_rerun/`)

| File | Description | SHA256 |
|------|-------------|--------|
| manifest.json | Run manifest with verdict chain | `221c378c15ed...` |
| canonical_orders.json | Canonicalized orders | `575e56cc61ac...` |
| validation_report.json | Import validation | `90f979eedc94...` |
| coords_quality_report.json | Coords gate result | `d4742575f111...` |
| solve_result.json | Solver output | `b8f52d5e985d...` |
| audit_results.json | Audit check results | `4e1eea7a8809...` |
| checksums.sha256 | File checksums | - |

---

## Audit Check Results

| Check | Status |
|-------|--------|
| COVERAGE | PASS |
| TIME_WINDOW | PASS |
| SHIFT_FEASIBILITY | PASS |
| SKILLS_COMPLIANCE | PASS |
| OVERLAP | PASS |

All 5 audit checks passed.

---

## Blocked Scenario Test

The `wien_pilot_small.json` dataset (10 orders, 2 with zone/h3 only) correctly blocked:

```
Overall Verdict: BLOCK
coords_gate: BLOCK
Reason: 2 unresolved orders (strict mode requires 0)
```

This proves that the coords gate BLOCK behavior works correctly - plans with unresolved coordinates cannot be published.

---

## Final Verdict

| Check | Status |
|-------|--------|
| E2E Pipeline | PASS |
| Verdict Chain | OK → PASS → LOCKED |
| Determinism | VERIFIED |
| Can Publish | YES |
| BLOCK Behavior | VERIFIED (tested with unresolved coords) |

**OVERALL RESULT**: **PASS**

---

## Recommendations

1. **Enable OSRM for full drift gate testing**: Start Docker and run with `--profile routing` to test OSRM finalize and drift detection
2. **Configure zone/h3 lookup tables**: To test the `wien_pilot_small.json` dataset, configure zone centroid and H3 lookup tables
3. **Evidence ZIP**: Create ZIP archive of artifacts for long-term storage

---

## Commands Used

```bash
# Run 1
python scripts/run_wien_pilot_dry_run.py \
  --input golden_datasets/routing/wien_pilot_46_vehicles/wien_pilot_all_coords.json \
  --output-dir artifacts/routing_e2e/run1 \
  --skip-osrm

# Run 2 (Determinism Check)
python scripts/run_wien_pilot_dry_run.py \
  --input golden_datasets/routing/wien_pilot_46_vehicles/wien_pilot_all_coords.json \
  --output-dir artifacts/routing_e2e/run2_rerun \
  --skip-osrm
```

---

**Generated**: 2026-01-08T19:24:00
**Test Duration**: ~2 minutes total
