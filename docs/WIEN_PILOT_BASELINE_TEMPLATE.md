# Wien Pilot - KPI Baseline Template

> **Version**: 1.0
> **Last Updated**: 2026-01-18
> **Status**: TEMPLATE

---

## Purpose

This template captures baseline KPIs for Wien Pilot runs. Fill in after each dry run to establish performance benchmarks.

---

## Run Metadata

| Field | Value |
|-------|-------|
| **Run Date** | `YYYY-MM-DD` |
| **Run Type** | `DRY_RUN` / `PRODUCTION` |
| **Commit SHA** | `abc1234` |
| **Tag** | `pilot-verification-green-YYYYMMDD` |
| **Input File** | `artifacts/input/fls_export_YYYY-MM-DD.csv` |
| **Operator** | `[Name]` |

---

## Input Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Total Orders in File | | |
| Orders Imported | | |
| Orders Rejected | | Reason breakdown below |
| Import Warnings | | |
| Unique Depots | | |
| Date Range | | e.g., "single day" |

### Rejection Breakdown

| Reason Code | Count |
|-------------|-------|
| MISSING_REQUIRED | |
| INVALID_TIME_WINDOW | |
| INVALID_DURATION | |
| INVALID_DEPOT | |
| DUPLICATE_ORDER | |

---

## Solve Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Solve Time (s)** | | < 120 | |
| **Tours Assigned** | | 100% | |
| **Tours Unassigned** | | 0 | |
| **Drivers Used** | | | |
| **FTE Drivers** | | | |
| **PT Drivers** | | | |

### Block Mix

| Block Type | Count | Percentage |
|------------|-------|------------|
| 1er | | |
| 2er-reg | | |
| 2er-split | | |
| 3er | | |

### Constraint Violations

| Type | Count | Target | Status |
|------|-------|--------|--------|
| BLOCK (hard) | | 0 | |
| SOFT (warnings) | | < 10 | |
| Zone Violations | | 0 | |

---

## Timing Metrics

| Phase | Duration (s) | P50 Target | P95 Target |
|-------|-------------|------------|------------|
| Import | | < 5 | < 15 |
| Solve Pass 1 | | < 30 | < 60 |
| Solve Pass 2 | | < 60 | < 120 |
| Solve Total | | < 90 | < 180 |
| Audit | | < 5 | < 10 |
| Export | | < 5 | < 10 |
| Freeze | | < 2 | < 5 |
| **Total E2E** | | < 120 | < 240 |

---

## Quality Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Coverage Rate | | 100% | |
| Driver Utilization | | > 85% | |
| Avg Hours/Driver | | 8-10h | |
| Max Hours/Driver | | < 12h | |
| Min Hours/Driver | | > 6h | |

---

## Manual Intervention

| Type | Count | Time (min) | Description |
|------|-------|------------|-------------|
| Order Corrections | | | |
| Manual Assignments | | | |
| Constraint Overrides | | | |
| **Total** | | | |

---

## Evidence Verification

| Check | Status | Notes |
|-------|--------|-------|
| Evidence file created | | |
| SHA256 hash verified | | |
| Assignment count match | | |
| Driver count match | | |
| Day frozen | | |

---

## Issues Encountered

| # | Issue | Severity | Resolution | Time to Fix |
|---|-------|----------|------------|-------------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

---

## Comparison to Previous Run

| Metric | Previous | Current | Delta | Trend |
|--------|----------|---------|-------|-------|
| Solve Time | | | | |
| Drivers Used | | | | |
| Violations | | | | |
| Manual Fixes | | | | |

---

## Observations

### What Went Well
-

### What Needs Improvement
-

### Action Items
- [ ]
- [ ]

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Operator | | | |
| Tech Lead | | | |
| Ops Lead | | | |

---

## Historical Runs

| Date | Commit | Solve Time | Drivers | Violations | Status |
|------|--------|------------|---------|------------|--------|
| | | | | | |
| | | | | | |
| | | | | | |

---

*This template should be copied and filled for each dry run.*
*Original: docs/WIEN_PILOT_BASELINE_TEMPLATE.md*
