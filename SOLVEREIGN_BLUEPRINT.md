# 🏛️ SOLVEREIGN: Technical Blueprint
> **System Architecture & Operational Documentation**  
> **Version**: 7.2.0 | **Status**: OPERATIONAL ✅ | **Updated**: 2025-12-28

---

## 1. Executive Summary

**Problem**: Weekly demand forecasting requires optimal driver scheduling under strict legal and operational constraints.

**Solution**: SOLVEREIGN delivers **~156 drivers** (vs. 190+ greedy baseline) through **Column Pooling + Restricted Master Set-Partitioning**.

**Business Impact**: ~40 fewer drivers = **€1.2-1.6M annual savings** at €40k/driver.

---

## 2. Terminology (Strict Definitions)

### Core Concepts
- **Tour**: Atomic work unit (~4.5h). Has `tour_id`, `day`, `start_time`, `end_time`, location, qualifications.
- **Block**: Day-combination of 1-3 tours for same driver on same day. Includes pause/split-shift rules. **Each block covers specific tour_ids**.
- **Roster**: Weekly schedule (Mon-Sat) for one driver. Combines 0-6 blocks with rest enforcement.
- **Master (RMP)**: Optimization problem selecting from roster pool to **cover each tour_id exactly once**.

### What is Covered "Exactly Once"?
**Primary Element**: `tour_id`  
**Master Constraint**: Each `tour_id` appears in exactly one selected roster.  
**Why**: Audit trail. Cannot hide double/missing tours.

---

## 3. Solution Architecture: Column Pooling + Set-Partitioning

### IMPORTANT: NOT Classical Column Generation
**What we do**: Heuristic column pool generation + exact selection via CP-SAT.  
**What we don't do**: Dual-based reduced cost pricing (CP-SAT provides no duals).  

**Correct terminology**: 
- **Column Pooling** (Phase 0-2): Generate large pool of valid rosters heuristically
- **Restricted Master Problem** (Phase 3): Select optimal subset from pool via CP-SAT Set-Partitioning
- **Optimality claim**: **Optimal relative to current pool**, NOT globally optimal without bound/proof

---

## 4. Pipeline Phases

### Phase 0: Demand Profiling
**Module**: `portfolio_controller.py`  
**Input**: List of `Tour` objects  
**Output**: `FeatureVector` (peakiness, variance, lower bound estimate)

**Budget Allocation** (Source of Truth: `BudgetSlice.from_total()`):
```python
# Line 79-89 portfolio_controller.py
profiling = 2%   # Instance profiling
phase1   = 20%   # Block selection (CP-SAT)
phase2   = 65%   # Roster assignment (Set-Partitioning)
lns      = 8%    # LNS refinement
buffer   = 5%    # Safety margin
```

### Phase 1: Block Building
**Module**: `smart_block_builder.py`  
**Process**:
1. Convert abstract demand → concrete blocks
2. Prioritize multi-tour blocks (3er > 2er > 1er)
3. **v7.0.0**: Dynamic peak detection (Mon/Fri adaptive)
4. Track which `tour_ids` each block covers

**Output**: ~1000-2000 blocks

### Phase 2: Roster Pool Generation
**Module**: `roster_column_generator.py`  
**Process**:
1. Multi-stage generation targeting FTE-bands (47-53h, 42-47h, 30-42h)
2. Template-based generation (Peak-ON/Peak+1-OFF adjacency)
3. Local validation: rest rules, weekly hours, qualifications
4. PT columns for hard-to-cover blocks

**Quality Biasing**:
- FTE-band rosters (40-55h): Priority +1000
- Singletons: Capped, used only for feasibility net

**Output**: 5k-15k roster columns

### Phase 3: Restricted Master Selection (RMP)
**Module**: `set_partition_solver.py`  
**Solver**: Google OR-Tools CP-SAT  
**Constraint**: Cover each `tour_id` exactly once  
**Objective** (lexicographic):
1. Minimize number of drivers
2. Minimize Core PT share (target <20%)
3. Maximize FTE utilization (40-55h band)
4. Prefer block quality (3er > 2er > 1er)

**Important**: CP-SAT does not provide duals → no classical reduced-cost column generation. This is **optimal relative to the pool**, not globally optimal.

**Process**:
- Iterative: 5-10 rounds (configurable via `max_rounds=500`)
- RMP time limit: 45s/solve (increased from 15s for v7.0.0)
- Adds columns dynamically based on coverage gaps

### Phase 4: Post-Processing & Validation
**Module**: `forecast_solver_v4.py`  
**Process**:
1. **Validation**: Check all hard constraints (11h rest, weekly hours)
2. **Repair** (if violations detected):
   - 2-Step Swap: Fix next-day early start conflicts
   - Bump/Absorb: Reallocate to flex pool
3. **LNS Consolidation** (optional): Merge low-hour fragments
4. **Final Gate**: 0 violations required, else FAIL

**Critical**: Repair runs ONLY if validation fails. It's a safety net, not part of normal optimization.

---

## 5. Hard Constraints (0 Violations Required)

1. **Rest Period**: Min 11h between shift end (day d) and start (day d+1)
2. **Weekly Hours**: Max 55h
3. **Daily Limits**: Max 3 tours/day (via block building)
4. **Split-Shift Rules**: Defined min/max gaps, `pause_zone` tracking
5. **Qualifications**: Tour requirements match driver skills

**Enforcement**: 
- Local (during roster generation): Pre-check each roster
- Global (post-selection): Validate final solution
- **Gate**: If violations exist after repair → status=INFEASIBLE

---

## 6. Current Performance (v7.0.0 Frozen Baseline)

### Run Metrics (Real Output)
```
Input:      1385 tours/week
Drivers:    113 FTE + 26 Core PT + 17 Flex PT = 156 effective
FTE Hours:  Avg 47.8h, Min 40.5h
PT Share:   10.3% (Core PT only, target <20%)
Flex Pool:  17 drivers (≤13.5h/week, peak overflow)
Fleet Peak: 113 vehicles @ Fri 18:30 (v7.2.0 Fleet Counter)
Runtime:    ~120s (default budget)
Status:     0 violations (validated)
```

### Guardrails
- Core PT Share: **<20%** (Hard Limit)
- Drivers Active: **≤160** (Hard Limit)
- Flex Pool: **≤15** (Soft Warning)

---

## 7. Tech Stack

### Core
- **Language**: Python 3.13+
- **Solver**: Google OR-Tools CP-SAT (deterministic, `num_workers=1`)
- **Typing**: Pydantic 2.x (strict models)
- **API**: FastAPI + SSE (real-time events)

### Directory Structure
```
backend_py/
├── src/services/
│   ├── portfolio_controller.py         # Orchestrator + budget slicing
│   ├── smart_block_builder.py          # Phase 1: Block pooling
│   ├── roster_column_generator.py      # Phase 2: Roster generation
│   ├── set_partition_solver.py         # Phase 3: CP-SAT RMP
│   ├── forecast_solver_v4.py           # Phase 4: Validation + repair
│   └── lns_refiner_v4.py               # LNS consolidation
├── fleet_counter.py                    # v7.2.0: Fleet demand analysis
├── export_roster_matrix.py             # CLI entrypoint
└── validate_promotion_gates.py         # CI quality gates
```

---

## 8. Post-Freeze Features

### v7.1.0 Real-Time Transparency ✅
**Event Bus**: SSE at `/api/v1/runs/{id}/events`

**Instrumented Events**:
- `run_started`: Pipeline kickoff
- `phase_start`/`phase_end`: Phase boundaries
- `capacity_tighten`: Block selection iterations
- `rmp_round`: Pool size, coverage %, stall detection
- `repair_action`: Bump/absorb operations

**Frontend**: Live dashboard with `PipelineStepper`, RMP rounds table, repair log

### v7.2.0 Fleet Counter ✅
**Purpose**: Derive peak vehicle demand from tour output

**Algorithm**: Sweep-Line (O(n log n))
```python
events = [(tour.start, +1, tour.id), (tour.end, -1, tour.id)]
events.sort(key=lambda e: (time_minutes(e[0]), e[1], e[2]))  # Ends before starts
active = 0
for time, delta, _ in events:
    active += delta
    peak = max(peak, active)
```

**Output**:
```
| Fri: 113 vehicles @ 18:30 <- PEAK |
```

**Exports**: `fleet_peak_summary.csv`, `fleet_profile_15min.csv`

---

## 9. FAQ: Why This Approach?

### "Why not Greedy (fill in order)?"
**Problem**: Short-sighted. Assigns Monday without considering Friday overtime.  
**Result**: 190 drivers (greedy) vs. 156 (SOLVEREIGN) = 34 drivers saved.

### "Why not classical Column Generation with LP relaxation?"
**Reason**: CP-SAT provides better integer solutions directly, but lacks dual values.  
**Trade-off**: We generate larger pools upfront (10k columns) instead of pricing iteratively.  
**Benefit**: Simpler, more robust, no LP/MIP complexity.

### "Why not AI/Deep Learning?"
**Problem**: Neural nets hallucinate illegal schedules (rest violations).  
**Requirement**: Guaranteed legality → mathematical optimization > ML.

---

## 10. Operational Runbook

### Standard Run
```bash
python backend_py/export_roster_matrix.py --time-budget 120
```
**Expected**: PASS (Core PT) + WARN (Flex) — both acceptable

### Troubleshooting
| Issue | Action |
|-------|--------|
| Feasibility Fail | Check input for overlaps. Try `--time-budget 300` |
| Driver Count >160 | Debug with `--seed 0-4` for variance |
| Peak Orphans | Check logs for "Dynamic Peak Days" |

### Fleet Analysis
```bash
python backend_py/fleet_counter.py --export
```

---

## 11. Compliance & Audit

### Legal Modeling
- **Work vs. Presence**: Exports distinguish paid work (tour segments) from blocked time (presence)
- **Split-Schicht**: Unpaid gaps (240-360min) tracked via `pause_zone=SPLIT`
- **Daily Rest**: 11h enforced via CP-SAT hard constraints
- **Audit Trail**: Every tour_id traceable to assigned driver

### Validation Process
1. **Post-RMP**: Check all selected rosters for violations
2. **Repair Gate**: If violations → repair → re-check
3. **Final Gate**: If violations persist → status=INFEASIBLE
4. **Report**: `compliance_report.json` (Planned v7.3.0)

---

## 12. Definition of Done

System is production-ready when:
1. **Legality**: 0% violations (post-validation)
2. **Efficiency**: Within 10% of theoretical lower bound
3. **Quality**: <20% Core PT share
4. **Robustness**: ±3 drivers variance across seeds
5. **Transparency**: Real-time events for all phases
6. **Audit**: Full trace from tour_id → driver

---

## 13. Version History

### v7.2.0 (2025-12-28)
- Fleet Counter: Sweep-line peak vehicle demand
- CSV exports: peak summary + 15min timeline
- Commit: 5f181bd

### v7.1.0 (2025-12-28)
- SSE event bus for live progress
- Frontend dashboard with RMP visualization
- Commit: 7002358

### v7.0.0 (2025-12-27/28)
- Dynamic peak detection (Mon/Fri adaptive)
- Flex pool categorization (Core vs. Flex PT)
- 156 effective drivers (frozen baseline)
- 10.3% Core PT share
- Tag: `v7.0.0-freeze`

---

## 14. Future Roadmap

### v7.3.0 (Planned)
- Compliance report: `compliance_report.json` with zero-violation proof
- Multi-location support
- Driver preferences (soft constraints)

### v8.0.0 (Research)
- Multi-week planning (2-4 week horizon)
- Stochastic demand modeling
- Real-time re-optimization

---

## 15. Key Design Principles

1. **Determinism**: Same input → Same output (`seed=42`, `num_workers=1`)
2. **Legality**: Hard constraints never violated (validated post-solve)
3. **Transparency**: Every decision logged, every tour traceable
4. **Performance**: <5min runtime for production forecasts
5. **Honesty**: Claims must be mathematically accurate (no false optimality guarantees)

---

## 16. Team Requirements

**Must Have**:
- Python 3.13+ (type hints, Pydantic)
- Google OR-Tools (CP-SAT solver)
- Constraint programming fundamentals
- Production logging & monitoring

**Nice to Have**:
- Operations Research background
- Column generation experience
- Shift scheduling domain knowledge

---

> **Final Note**:  
> SOLVEREIGN is a **high-performance heuristic optimizer** built around Google CP-SAT. It uses **Column Pooling + Restricted Master Set-Partitioning**, not classical column generation. Results are **optimal relative to the generated pool**, with 0 violations guaranteed via post-solve validation.

---

**Repository**: [DRNaser/shift-optimizer](https://github.com/DRNaser/shift-optimizer)  
**Tag**: `v7.0.0-freeze` (baseline), `v7.2.0` (current)
