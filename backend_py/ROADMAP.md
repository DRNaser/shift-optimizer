# SOLVEREIGN Roadmap

> **Last Update**: 2026-01-04
> **Version**: 8.0.0 (V2 Production Release)
> **Status**: **OPERATIONAL** ✅
> **Tag**: [`v8.0.0-final`](https://github.com/DRNaser/shift-optimizer/tree/main)

---

## 📊 Final Status (V2 Block Heuristic)

```
Target: 160 Drivers
Actual: 145 Drivers (FTE)
PT Drivers: 0 (100% FTE)
Violations: 0 (Rest/Overlap)
Consecutive Triples: MAX 1 (Fatigue Rule Enforced)
Result: EXCEEDS EXPECTATIONS
```

### Key Achievements (Jan 2026)
1.  **Baseline Re-Established**: Moved from ~250 (Legacy) -> **145 Drivers**.
2.  **Fatigue Safety**: Implemented "No Consecutive Triple Days" rule (3er -> 3er forbidden) with **Zero Cost** (still 145 drivers).
3.  **Visualization**: Deployed `final_schedule_matrix.html` - a Dispatcher Cockpit with Density, Safety, and Chronological views.
4.  **Clean Codebase**: Removed 20+ legacy files, stabilizing the repo on the V2 Architecture.

---

## 🛑 Operational Rules

### 1. Legal Compliance (Hard)
*   **11h Rest**: Strictly enforced between blocks.
*   **Max Span**: 14h (Regular) / 16h (Split).
*   **Split Break**: Exactly 360m (6h) for Split shifts.

### 2. Fatigue Management (Soft/Hard)
*   **Triple Limit**: A driver performing a Triple Tour (3er) **cannot** do a Triple Tour the next day.
*   **Gap Quality**: Gaps < 45 min are flagged as "Risk" in the dashboard.

---

## 📘 Operational Runbook

### 1. Standard Run
*   **Command**: `python backend_py/run_block_heuristic.py`
*   **Input**: `forecast input.csv` (Standard) or `forecast_kw51.csv` (Compressed).
*   **Output**:
    *   `final_schedule_matrix.csv` (Data)
    *   `final_schedule_matrix.html` (Visual Dashboard)

### 2. Tuning
*   **Seed Optimization**: Run `python find_best_partition.py` to find the best seed for new data.
    *   Current Best (Normal): **Seed 94** (Peak 145).
    *   Current Best (KW51): **Seed 18** (Peak 187).

### 3. Verification
*   **Regression Test**: `python test_golden_run.py`
    *   Checks Coverage, Rest, Overlap, and KPI adherence.

---

## ✅ Completed Milestones (History)

### v8.0.0 Final Delivery (Jan 3, 2026)
**Context**: User required a production-ready roster with visual confirmation of safety rules.
**Deliverables**:
*   [x] **Solver V2**: Block Heuristic + Min-Cost Max-Flow.
*   [x] **Fatigue Rule**: Forbid 3er->3er transitions.
*   [x] **Dispatcher Heatmap**: Interactive HTML export.
*   [x] **Cleanup**: Repo sanitized.

### v7.0.0 Legacy V1 Freeze (Dec 2025)
**Context**: Old MIP solver (deprecated).
**Result**: 156 Drivers. Superseded by V2 (145 Drivers).

---

## 🔮 Next Steps (Phase 3 - Future Agent)

### 1. Real-World Constraints
*   **Driving Time**: The current system optimizes *Span* (Working Time). Future work should sum actual driving minutes (from tour duration) to ensure EU 9h/10h compliance.
*   **Geo-Coding**: The current system assumes a central depot. Future work should validate Start/End locations of linked tours.

### 2. Frontend Integration
*   Currently, the UI is a standalone HTML file.
*   **TODO**: Integrate the HTML/JSON data model into a React/Next.js frontend for a persistent web application.

### 3. Automated Training
*   **TODO**: Automate `find_best_partition.py` to run weekly via GitHub Actions and update the `SEED` automatically.

---
*End of Document*
