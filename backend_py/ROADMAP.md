# SOLVEREIGN Roadmap

> **Letzte Aktualisierung**: 2025-12-29
> **Version**: 7.0.0 (Frozen Baseline)
> **Add-ons**: v7.1.0-ui (Feature Overlay), v7.2.4 (Fleet Counter), v7.3.0 (Holiday Support)
> **Status**: **OPERATIONAL** ✅
> **Tag**: [`v7.0.0-freeze`](https://github.com/DRNaser/shift-optimizer/tree/v7.0.0-freeze) (Baseline), `v7.3.0-dev` (Current)

---

## 📊 Final Status (v7.0.0 Peak-Robust)

```
Drivers: 113 FTE + 26 Core + 17 Flex = 156 Effective (Total)
FTE Hours: Avg 47.8h, Min 40.5h
PT Share (Core): 10.3% (Target < 20%)
Flex Pool: 17 Drivers (<13.5h/week)
Result: PEAK-ROBUST & OPERATIONAL (Flex Pool Validated)
```

### Key Improvements
1. **Dynamic Peak Detection**: Automatically detects Peak days (e.g. Fri, Mon) per forecast.
2. **Adjacency-Templates**: `Peak-ON / Peak+1-OFF` columns ensure rest feasibility.
3. **2-Step Swap Repair**: Mini-LNS resolves "Next-Day Early Start" blockers.

---

## 🛑 Operational Concept (Flex Pool)

**"Status: FEATURE, NOT BUG"**

PT drivers are now categorized into two operational buckets:

*   **Core PT** (>13.5h/week): ~26 drivers, 10.3% of total hours. These are scheduled PT drivers working regular patterns.
*   **Flex PT** (≤13.5h/week): ~17 drivers, primarily for peak overflow absorption (Sat "2er Split" slots).

**Role**: The Flex Pool absorbs Peak Overflow (Fri/Mon peaks) that cannot be covered by FTEs without violating legal 11h rest limits.

**Guardrails (Frozen)**:
*   Core PT Share: **< 20%** (Hard Limit)
*   Drivers Active: **≤ 160** (Hard Limit)
*   Flex Pool Size: **≤ 15** (Soft Warn)

---

## 📘 Operational Runbook

### 1. Standard Run
*   **Command**: `python backend_py/export_roster_matrix.py --time-budget 120`
*   **Budget**: `120s` (Recommended for Stability)
*   **Expected Result**: **PASS** (Core PT Share) and **WARN** (Flex Pool Size) — both operationally acceptable.

### 2. Troubleshooting
| Issue | Action |
|-------|--------|
| **Feasibility Fail** | Check input for massive overlaps. Try `time_budget=120`. |
| **Driver Count > 160** | `python backend_py/pt_balance_quality_gate.py --debug-extract` |
| **Peak Orphans** | Check Logs for "Dynamic Peak Days". Verify if new peak pattern emerged (e.g. Tue peak). |

### 3. Emergency Flags
*   `--time-budget 300`: If quality drops significantly.
*   `--seed <N>`: Try seeds 0-4 (Debug only) if a specific run gets stuck. Standard is seed 42.

### 4. Compliance & Audit Readiness
*   **Work vs. Presence**: UI/Exports distinguish blocked time (presence) from paid work (segments).
*   **Split-Schicht**: Geteilte Dienste (Pause = unbezahlte Unterbrechung) werden korrekt als Non-Working Time modelliert (Policy-Check).
*   **Daily Rest**: 11h minimum strictly enforced via `min_rest_hours`.
*   **Audit**: `compliance_report.json` generated per run with zero-violation proof. (Planned/Next for v7.2.0)

---

## ✅ Completed Milestones (History)

### v7.0.0 Reporting Upgrade (2025-12-28)
**Context**: Initial freeze showed 158 total drivers. Analysis revealed 2 ghosts and 17 flex.
**Result**: 156 Effective, 10.3% Core PT Share. **FROZEN BASELINE**.

### v7.0.0 Peak-Robust (2025-12-27)
**Context**: Replaced hardcoded Friday peak with dynamic detection.
**Result**: Robust across Mon/Fri peaks.

---

## 🚀 Post-Freeze Released Features

### v7.1.0 Real-Time Transparency (2025-12-28)
**Status**: **DEPLOYED** ✅

**Context**: Maximum transparency into solver execution.

**Backend Implementation**:
- [x] **Event Bus**: `ProgressEvent` schema + SSE at `/api/v1/runs/{id}/events`.
- [x] **Full Instrumentation**:
    - **Phase 0 (Block Build)**: Run start events.
    - **Phase 1 (Capacity)**: `capacity_tighten` events.
    - **Phase 2 (Set Partitioning)**: `rmp_round` (pool, coverage, stall).
    - **Post (Repair)**: `repair_action` (Bumps/Absorbs).

**Frontend Implementation**:
- [x] **Live Dashboard**: Real-time `PipelineStepper`.
- [x] **RMP Visualization**: Live rounds table.
- [x] **Repair Log**: Auto-repair tracking panel.

---

## 📁 File Structure

```
backend_py/
├── src/services/
│   ├── portfolio_controller.py  # ORCHESTRATOR
│   ├── forecast_solver_v4.py    # REPAIR LOGIC
│   ├── roster_column_generator.py # TEMPLATES
├── fleet_counter.py             # FLEET PEAK ANALYSIS (v7.2.0)
├── validate_promotion_gates.py  # CI GATE
└── export_roster_matrix.py      # ENTRYPOINT
```

---

## 📊 v7.2.0 Fleet Counter (2025-12-28)
**Status**: **DEPLOYED** ✅

**Purpose**: Peak vehicle demand analysis from tour data. Derives minimum fleet size by calculating maximum simultaneously active tours (= simultaneously bound vehicles). Vehicle handovers automatically accounted for.

**Algorithm**: Sweep-Line (O(n log n))
- Events at tour start (+1) and end (-1)
- Ends before starts at same time (handover = no extra vehicle)
- Optional turnaround delay (default: 5 min)

### Pipeline Integration (2025-12-29)
Fleet counter is now fully integrated into the optimization pipeline:

**Backend Integration**:
- Fleet metrics computed in `portfolio_controller.py` and included in KPI output
- Metrics: `fleet_peak_count`, `fleet_peak_day`, `fleet_peak_time`, `fleet_day_peaks`

**Export Integration** (`export_roster_matrix.py`):
- Pre-solve fleet analysis displayed in console
- New CSV: `fleet_summary.csv` (per-day peaks)
- Fleet metrics added to `roster_matrix_kpis.csv`

**Frontend Integration**:
- Fleet Peak KPI card added to dashboard
- Shows peak vehicles, day, and time
- Included in UI export CSV

**Usage**:
```bash
# Standalone analysis
python fleet_counter.py [--turnaround 5] [--interval 15] [--export]

# Integrated with solver (automatic)
python export_roster_matrix.py --time-budget 120
```

**Current Peak**: 116 vehicles @ Sat 10:00 (1385 tours)

**Exports**:
- `fleet_summary.csv` (per-day peaks)
- `roster_matrix_kpis.csv` (includes fleet metrics)
- `fleet_profile_15min.csv` (timeline, standalone only)

---

## 🎨 v7.2.3 UI & Export Fixes (2025-12-28)
**Status**: **DEPLOYED** ✅

**Context**: Production testing revealed several UI/Export issues.

### Fixes Applied

| Issue | Status | Fix |
|-------|--------|-----|
| **PT/FTE Classification** | ✅ | `_renumber_driver_ids()` after consolidation |
| **Empty Shift Columns** | ✅ | Fixed dayMapping (`Mon`→`Montag`) |
| **Missing KPI Insights** | ✅ | Export now generates 2 CSVs |
| **Shift Color Scheme** | ✅ | 3er=Orange, 2er=Blue, Split=Grey, 1er=Green |

### Driver ID Renumbering

```python
def _renumber_driver_ids(assignments, log_fn):
    # Update driver_type based on final hours (post-consolidation)
    for a in assignments:
        a.driver_type = "FTE" if a.total_hours >= 40.0 else "PT"
    # Renumber with correct prefix (FTE001..N, PT001..M)
```

**Impact**: 40h+ drivers now correctly get `FTE###` prefix instead of keeping `PT###` from initial assignment.

### Export Pack Improvements

- **Roster CSV**: Now includes Montag-Samstag shift data (was empty due to day format mismatch)
- **KPI CSV**: New `_kpis.csv` file with driver counts, tour stats, block distribution
- **Format**: UTF-8 BOM, Semicolon separator (German Excel compatible)

### Shift Color Scheme (UI)

| Schicht | Farbe | Tailwind |
|---------|-------|----------|
| 3er | 🟠 Orange | `bg-orange-500` |
| 2er | 🔵 Blue | `bg-blue-500` |
| 2er_split | ⚪ Grey | `bg-slate-500` |
| 1er | 🟢 Green | `bg-emerald-500` |

### Latest Run Analysis (run_01e37f8b41e9)

```
FTE: 122 (40.5-49.5h)
PT:   26 (9-36h)
─────────────────────
Total: 148 Drivers

PT Distribution:
- 36h: 2 drivers (near-FTE, potential bump candidates)
- 27h: 6 drivers
- 22.5h: 3 drivers
- 18h: 6 drivers
- 13.5h: 5 drivers
- 9h: 4 drivers
```

---
---

## 🎄 v7.3.0 Holiday Week Support (2025-12-29)
**Status**: **TUNING / PARTIAL** ⚠️

**Objective**: Optimize driver allocation during holiday weeks (Compressed Weeks, e.g., KW51) where active days ≤ 4.

### Features
1.  **Compressed Week Detection**:
    -   Automatically identifies weeks with $k \le 4$ active days via `active_days` feature.
    -   Switches `roster_column_generator` to **Beam Search Mode** for dense column generation.

2.  **Objective Tuning (Aggressive)**:
    -   Strongly penalizes single-tour rosters (`CW_SINGLETON_PENALTY=400k`) to force 2-4 tour density.
    -   Dominance Hierarchy: `M_DRIVER` > `CW_SINGLETON` > `W_UNDER`.

3.  **Safety Net: Incumbent Injection**:
    -   Converts Greedy heuristic solution into `RosterColumn` hints.
    -   Injects them into RMP pool to guarantee that RMP never performs worse than Greedy (Headcount $\le$ Greedy).

4.  **Diagnostics Suite (Checks A/B)**:
    -   **Check A (Tiling)**: Analyzes pool tileability (Support Count per Tour). 
        -   *Finding*: 86% of blocks have low support (1-2 columns), identifying needed "Bridging" improvements.
    -   **Check B (Density)**: Verifies dense column coverage (>80% unions).

### Current Benchmark (KW51)
*   **Drivers**: 236 (Greedy Incumbent)
*   **Gap to Peak**: +67 drivers (Target: <35)
*   **Status**: Safe but not fully optimized. Requires "Bridging" generator for next improvement.

### Verified: Step 8 Bridging (2025-12-29)
**Status**: **COMPLETED** ✅

**Problem**: KW51 (Compressed Week) showed 86% low-support tours, leading to fragmentation (high PT/Singleton count).
**Fix**: Implemented "Bridging Generator" loop to target tours with support <= 2.
-   **Robustness**: Uses `can_add_block_to_roster` to validate candidates against Rest/Overlap constraints during generation.
-   **Diversity**: Deterministic Anchor & Pack strategy with diverse candidate selection.

**Results (Gate Checks)**:
1.  **KW51 Final**:
    -   Drivers: **230** (176 FTE + 54 PT) -> Beat Greedy (231)
    -   Pool Quality: **0.0%** tours with low support (Bridging effective)
    -   Avg Hours: 24.9h (on 4 active days)
2.  **Regression (6-Day Week)**:
    -   Drivers: 113 (vs 110 Peak) -> Minimal overhead
    -   Runtime: 45s (Fast)
    -   Violations: 0

### Verified: Step 9 Merge Repair (2025-12-29)
**Status**: **COMPLETED** ✅

**Problem**: Even with bridging, RMP settled at high headcount (250+) due to fragmentation/dust.
**Fix**:
1.  **Merge Repair (Type C)**: Pairwise merge of short rosters (<=3 tours) into dense columns.
    -   Reduced headcount 491 -> 250 in compressed week stress test.
2.  **Adaptive RMP**: Increases solver time (20s->60s) for deep search in compressed weeks.
3.  **Pool Pruning**: Keeps clean pool (<6000 cols) to prevent solver choke.

**Results**:
-   Headcount moving towards target (<220).
-   6-Day Regression Test: **PASSED** (113 drivers, 0 violations).

---
*v7.0.0 Baseline is FROZEN. v7.1.0+ features are additive.*
