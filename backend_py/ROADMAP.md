# SOLVEREIGN Roadmap

> **Letzte Aktualisierung**: 2025-12-27
> **Version**: 6.1.0
> **Status**: FTE Balancing Optimized (Stable)

---

## 📋 Projekt-Übersicht

**Solvereign** ist ein Schichtoptimierungssystem für Last-Mile-Delivery.

### Das Problem
- **Input**: ~1385 Touren pro Woche (Mo-Sa)
- **Ziel**: Minimiere Anzahl der **FTE-Fahrer** (Vollzeit, 40-55h/Woche)
- **Constraints**: Max 55h/Woche, 11h Ruhezeit, max 3 Touren/Tag, keine Überlappungen

### Die Lösung (Optimale Pipeline)
```
Touren → SmartBlockBuilder → CP-SAT Block Selection → Set Partitioning (RMP) → Schedule
         (Phase 0)           (Phase 1)                 (Phase 2)
```

---

## 🏗️ Architektur

### Kernmodule (BEHALTEN)

| Datei | Funktion |
|-------|----------|
| `portfolio_controller.py` | Orchestrator - steuert die Solver-Pipeline |
| `forecast_solver_v4.py` | Phase 1: Block Selection (Kapazitätsplanung) |
| `set_partition_solver.py` | Phase 2: Driver Assignment (Column Generation) |
| `set_partition_master.py` | RMP Solver für Set-Partitioning |
| `roster_column.py` | RosterColumn Datenstruktur |
| `roster_column_generator.py` | Generiert valide Rosters für RMP |
| `smart_block_builder.py` | Phase 0: Block-Generierung |

### Gelöschte Dateien (v6.0 Cleanup - 2025-12-27)

**Services:**
- `src/services/daychoice_solver.py`
- `src/services/heuristic_solver.py`
- `src/services/assignment_solver.py`
- `src/services/cpsat_solver.py`
- `src/services/scheduler.py`
- `src/services/domain_lns.py`
- `src/services/cpsat_assigner.py`
- `src/services/cpsat_global_assigner.py`
- `src/services/lns_refiner.py`
- `src/services/model_strip_test.py`

**API:**
- `src/api/forecast_router.py`
- `src/api/routes.py`

**Tests & Scripts:**
- `tests/unit/test_cpsat_solver.py`
- `tests/unit/test_scheduler.py`
- `tests/unit/test_domain_lns.py`
- `tests/unit/test_lns_refiner.py`
- `tests/test_rest_constraint.py`
- `tests/test_synthetic_3er_block.py`
- `test_daychoice_isolated.py`
- `scripts/drivercap_search.py`
- `scripts/run_production_smoke.py`

**Code Cleanup (forecast_solver_v4.py):**
- Removed `HEURISTIC` solver_mode branch (imported deleted `heuristic_solver`)
- Removed `solve_forecast_fte_only` function (imported deleted `cpsat_global_assigner`, `model_strip_test`)

---

## ✅ GELÖST: FTE/PT Klassifizierung

### Das Problem (Behoben)
Fahrer mit <40h wurden als FTE klassifiziert, wenn der Solver auf Greedy Assignment zurückfiel.

### Die Lösung
1. **`set_partition_master.py`**: Massive Penalty für PT (<40h).
2. **`portfolio_controller.py`**: 
   - Path A/B: Hatten bereits `rebalance_to_min_fte_hours`.
   - **Path C (Fix)**: `rebalance_to_min_fte_hours` zum Greedy Fallback hinzugefügt.
   - Damit werden unterfüllte FTEs (<40h) korrekt zu PT reklassifiziert.

### Verifikation
Test-Script `tests/reproduce_fallback_fte_bug.py` bestätigt:
- Vor Fix: FTE mit 20h.
- Nach Fix: Korrekt als PT mit 20h klassifiziert.

---

## 📊 Aktuelle KPIs (Stand: 2025-12-27, NACH SOLVER OPTIMIZATION SUITE)

```
Drivers: 113 FTE + 76 PT = 189 total
FTE Hours: Min 40.5h, Avg 45.2h, Max 49.5h
FTE Under 40h: 0 (0.0%) ← FIX VERIFIED!
FTE Over 55h: 0 (0.0%)
PT Share: 40.2% of drivers (76/189) - Reduction from 46.3% (88/190)
Rest Violations: 0
Method: Best-of-Two (RMP vs Greedy) + Multi-Stage Column Generation
```

### KPI Improvement (2025-12-27 Optimization)
| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Total Drivers | 190 | **189** | -0.5% |
| FTE Drivers | 102 | **113** | **+11%** ⬆️ |
| PT Drivers | 88 | **76** | **-14%** ⬇️ |
| PT Share | 46.3% | **40.2%** | -6.1pp |

### Ziel-KPIs

```
FTE Hours: Min 40h, Avg 45-50h, Max 55h
FTE Under 40h: 0 (0%)
PT Share: <10% (target, requires further optimization)
```


---

## 🗂️ Wichtige Dateien zum Verstehen

### 1. Pipeline-Einstieg
```
src/api/routes_v2.py          # API Endpoint /runs
  → run_manager.create_run()  # Startet async Job
    → portfolio_controller.run_portfolio()  # Main Entry
```

### 2. Solver-Pipeline
```python
# portfolio_controller.py - run_portfolio()

# Phase 0: Block Building
selected_blocks = build_weekly_blocks_smart(tours, config)

# Phase 1: Capacity Planning
result = solve_capacity_phase(blocks, config)

# Phase 2: Driver Assignment (Path C = Set Partitioning)
sp_result = solve_set_partitioning(blocks, ...)

# Klassifizierung
driver_type = "FTE" if roster.total_hours >= 40.0 else "PT"
```

### 3. RMP Kosten-Struktur (Optimiert 2025-12-27)
```python
# set_partition_master.py - solve_rmp()

# UTILIZATION-BASED COST: Higher hours = lower cost (Parabolic)
FTE_BASE_COST = 1000             # Base cost per FTE
# Parabolic cost function centers optimal cost around 47.5h

PT_BASE_COST = 500_000           # Massive penalty for <40h (Effective PT barrier)
SINGLETON_COST = 100_000         # Penalty for 1-block rosters
```

---

## 📝 Nächste Schritte

### ✅ Cleanup (Erledigt - 2025-12-27)
- [x] Deprecated Module gelöscht
- [x] Path A/B Dead Code entfernt

### ✅ Pool-Cap Optimierung (Erledigt - 2025-12-27)
- [x] Demand analysiert: 1385 Touren, 6232h, Peak 116 concurrent
- [x] Realistischer LB: 138-152 FTE (nicht ~138 wegen Peak-Constraints)
- [x] RMP Kosten angepasst: Efficiency Bonus für höhere FTE-Stunden

### ✅ Structured Logging (Erledigt - 2025-12-27)
- [x] `src/utils/structured_logging.py` erstellt (JSON for prod, console for dev)
- [x] In `main.py` integriert
- [x] In `portfolio_controller.py` importiert (log_phase_start, log_phase_end, log_kpi)
- [x] Env vars: LOG_FORMAT=json, LOG_LEVEL=INFO

### ✅ FTE Balance & PT Reduction (Erledigt - 2025-12-27)
- [x] **RMP Costs Tuned**: Parabolic FTE Cost (Target 47.5h) + 500k PT Penalty.
- [x] **Solver Logic Optimized**: 
    - Fix: Prevent "GOOD_ENOUGH" early exit when PT count is high.
    - Feature: Forced Column Generation loop to target PT covered blocks.
    - Feature: **Greedy Fallback** when Generation stalls (Key to success).
- [x] **Verified**: PT Share reduced from 81% -> 23.2%. Drivers 383 -> 191.

### ✅ PT Balance Quality Gate Fixes (Erledigt - 2025-12-27)
- [x] **Forecast Parsing**: Replaced fragile regex-based TSV parsing with robust `split()` approach.
- [x] **Regex Escaping**: Fixed double-escaped patterns in `_to_minutes` and `_parse_time_range` helpers.
- [x] **Object Conversion**: Fixed `_convert_tours_to_domain_objects` to correctly instantiate `Tour` objects with proper type conversions (`int` → `Weekday`/`time`).
- [x] **KPI Extraction**: Adapted `compute_kpis` and `_iter_rosters` to handle `PortfolioResult` wrapper objects from `portfolio_controller`.
- [x] **Deep-Scan Enhancement**: Implemented robust multi-source KPI extraction:
    - `_deep_scan_hours_by_driver`: Scans for hours_by_driver maps
    - `_deep_scan_rosters`: Scans for roster lists in multiple locations
    - `_deep_scan_assignments`: Computes hours from assignment/shift lists
    - Extraction metadata tracking (which path was used)
    - `--debug-extract` flag for troubleshooting (writes `artifacts/extraction_debug.json`)

### ✅ Solver Optimization Suite (Erledigt - 2025-12-27)
- [x] **Quick Wins**:
    - Increased `anytime_budget`: 30s → 120s
    - Increased `quality_time_budget`: 300s → 600s
    - Tuned Column Generation: `max_rounds` 100→500, `pool_size` 5000→10000
- [x] **Multi-Stage Column Generation**:
    - Added `build_from_seed_targeted()` for hour-range specific generation
    - Added `generate_multistage_pool()`: Stage 1 (47-53h), Stage 2 (42-47h), Stage 3 (30-42h)
    - Integrated into `set_partition_solver.py`
- [x] **Best-of-Two Comparison** (Key Fix):
    - RMP often hits time limits, returning FEASIBLE (not OPTIMAL) with high PT
    - Added comparison: if Greedy produces fewer drivers than RMP, use Greedy
    - Returns `OK_GREEDY_BETTER` status when Greedy outperforms RMP
- [x] **Swap Consolidation Post-Processing**:
    - Added `swap_consolidation()` function in `set_partition_solver.py`
    - Attempts to redistribute blocks to eliminate underutilized drivers
- [x] **Time Budget Fix**:
    - Fixed `pt_balance_quality_gate.py` to properly pass `time_budget` to `run_portfolio()`

### Nächste Schritte
- [ ] **Further PT Reduction**: Ziel <10% PT Share (currently 40.2%)
    - Enable LNS Endgame: `enable_lns_low_hour_consolidation=True`
    - Increase RMP time per round: 15s → 30-60s
    - Improve column generation: focus on 45-50h rosters
- [ ] **Hybrid Pipeline**: Parallel solver strategies (deferred)
- [ ] **Log-Rotation**: Konfigurieren
- [ ] **Metrics/Tracing**: OpenTelemetry hinzufügen

---

## 🧪 Test-Befehle


```powershell
cd backend_py

# Business KPIs validieren
python test_business_kpis.py

# PT Balance Quality Gate (mit Deep-Scan Debug)
cd ..
python pt_balance_quality_gate.py --input forecast-test.txt --time-budget 120 --debug-extract

# API starten
cd backend_py
python -m uvicorn src.main:app --reload

# Import-Test
python -c "from src.main import app; print('OK')"
```

---

## 📁 Dateistruktur

```
backend_py/
├── src/
│   ├── api/
│   │   ├── routes_v2.py        # Canonical API (v6.0)
│   │   ├── run_manager.py      # Async Job Management
│   │   └── config_validator.py # Config Validation
│   ├── services/
│   │   ├── portfolio_controller.py  # ⭐ ORCHESTRATOR
│   │   ├── forecast_solver_v4.py    # ⭐ Phase 1
│   │   ├── set_partition_solver.py  # ⭐ Phase 2
│   │   ├── set_partition_master.py  # ⭐ RMP Solver
│   │   ├── roster_column.py         # Column Structure
│   │   ├── roster_column_generator.py # Column Generation
│   │   └── smart_block_builder.py   # Block Building
│   └── domain/
│       ├── models.py           # Domain Models
│       └── constraints.py      # Hard Constraints
├── test_business_kpis.py       # KPI Validation Script
├── pt_balance_quality_gate.py  # ⭐ Quality Gate (Deep-Scan Enhanced)
└── ROADMAP.md                  # ← DIESE DATEI
```

---

## 🔑 Schlüssel-Konzepte

### Set Partitioning
- Mathematisch optimaler Ansatz für Crew Scheduling
- Generiert "Columns" (komplette Wochen-Rosters)
- RMP wählt minimale Menge an Columns die alle Blöcke abdecken

### FTE vs PT
- **FTE (Vollzeit)**: 40-55h/Woche, Basis-Kosten
- **PT (Teilzeit)**: <40h/Woche, MASSIVE Kosten (150,000 Basis)
- Ziel: Minimiere PT-Anteil durch teure Kosten im RMP

### Block-Typen
- **3er**: 3 Touren/Tag (am effizientesten)
- **2er_regular**: 2 Touren/Tag, normale Pause
- **2er_split**: 2 Touren/Tag, lange Pause (Split-Shift)
- **1er**: 1 Tour/Tag (am ineffizientesten, wird vermieden)

---

*Diese Datei dient als Referenz für nachfolgende Agents, um das Projekt schnell zu verstehen und weiterzuarbeiten.*
