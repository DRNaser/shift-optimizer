# Gurkerl Roster Solver E2E Test Report

> **Date**: 2026-01-08 19:18:50
> **Status**: WARN
> **Reason**: Validation warnings present

---

## Test Summary

| Metric | Value |
|--------|-------|
| Input File | `gurkerl_test_input.json` |
| Tenant | gurkerl |
| Site | wien |
| Week Anchor | 2026-01-05 |
| Tours | 10 |
| Solver Seed | 94 |

---

## Step 1: Validation Results

| Check | Result |
|-------|--------|
| Hard Gates Passed | 5 |
| Hard Gates Failed | 0 |
| Soft Gates Warnings | 30 |
| Status | WARN |
| Input Hash | `sha256:e7563327f80474f546e451b48af731f7db600cd92ff...` |

---

## Step 2: Canonicalization

| Field | Value |
|-------|-------|
| Schema Version | 1.0.0 |
| Service Code | roster |
| Canonical Hash | `sha256:5b790d5ac81927969b8164f02463c9466f07a3cbbcd...` |

### Tours Sample (First 5)

| ID | Day | Time | Depot | Skill |
|----|-----|------|-------|-------|
| T001 | 1 | 08:00-16:00 | default | standard |
| T002 | 1 | 06:00-14:00 | default | standard |
| T003 | 1 | 14:00-22:00 | default | standard |
| T004 | 2 | 08:00-16:00 | default | standard |
| T005 | 2 | 06:00-14:00 | default | standard |

---

## Step 3: Solver Results

| Metric | Value |
|--------|-------|
| Status | SOLVED |
| Assignments | 10 |
| Unique Drivers | 3 |
| Output Hash | `0bc9580c9d8d84e1` |

### Assignments Sample (First 5)

| Tour | Driver | Day | Time |
|------|--------|-----|------|
| T001 | D001 | 1 | 08:00-16:00 |
| T002 | D002 | 1 | 06:00-14:00 |
| T003 | D003 | 1 | 14:00-22:00 |
| T004 | D001 | 2 | 08:00-16:00 |
| T005 | D002 | 2 | 06:00-14:00 |

---

## Step 4: Determinism Check

| Check | Result |
|-------|--------|
| Determinism | PASS |
| Verified Hash | `0bc9580c9d8d84e1` |

---

## Final Verdict

**Status**: WARN


Validation passed with warnings. Review soft gate warnings.


---

## Artifacts

| Artifact | Location |
|----------|----------|
| Test Input | `tests/fixtures/gurkerl_test_input.json` |
| Canonical Output | `tests/fixtures/gurkerl_canonical.json` |
| This Report | `GURKERL_SOLVER_TEST_REPORT_2026-01-08.md` |

---

**Generated**: 2026-01-08T19:18:50.006870
