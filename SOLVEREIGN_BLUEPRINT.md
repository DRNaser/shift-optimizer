# 🏛️ SOLVEREIGN: Technical Blueprint v7.2.1
> **System Architecture & Operational Documentation**  
> **Version**: 7.2.1 | **Status**: OPERATIONAL ✅ | **Updated**: 2025-12-28

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
- **Column Pool**: Set of pre-validated rosters (constraints already satisfied).
- **Restricted Master**: CP-SAT optimization selecting from pool to cover each `tour_id` exactly once.

### What is Covered "Exactly Once"?
**Primary Element**: `tour_id`  
**Master Constraint**: Each `tour_id` appears in exactly one selected roster.  
**Why**: Audit trail. Cannot hide double/missing tours.

---

## 3. Solution Architecture: Column Pooling + Set-Partitioning

### IMPORTANT: NOT Classical Column Generation
**What we do**:
1. **Heuristic Column Pool Generation**: Create large pool of valid rosters (~10k) without dual-based pricing
2. **Gap-Driven Pool Expansion**: If RMP shows uncovered tours → generate more columns for those tours
3. **CP-SAT Set-Partitioning**: Select optimal subset from pool (exact coverage of all tour_ids)

**What we don't do**: 
- Dual-based reduced cost pricing (CP-SAT provides no duals)
- LP relaxation for bounds
- Provable global optimality

**Optimality claim**: **Optimal relative to current pool** (not globally optimal).

---

## 4. Formal Problem Statement

### Decision Variables
```
x_r ∈ {0,1}  for each roster r in pool
u_t ∈ {0,1}  elastic slack for uncovered tour t (heavily penalized)
```

### Constraints
```
For each tour_id t:
  Σ_{r covers t} x_r + u_t = 1    (exact coverage with elastic slack)
```

### Objective (Dominance-Weighted, NOT Lexicographic)
```python
Minimize: Σ cost(r) · x_r + 100M · Σ u_t

where cost(r) = {
  PT_BASE (1M) + penalties    if hours < 40h (PT driver)
  FTE_BASE (50k) + deviation² if hours ≥ 40h (FTE driver)
}
```

**Weight Scaling** (ensures dominance):
- `W_UNDER = 100M` → Eliminating gaps dominates everything
- `PT_BASE = 1M` → Reducing PT count dominates FTE utilization
- `FTE_BASE = 50k` → Minimizing FTE count
- `DEVIATION = 100` → Balancing FTE hours (parabolic penalty from 47.5h target)

**Note**: This is NOT true lexicographic (no sequential solves). It's a single weighted objective with strict dominance via large weight ratios.

---

## 5. Pipeline Phases

### Phase 0: Demand Profiling
**Module**: `portfolio_controller.py`  
**Input**: List of `Tour` objects  
**Output**: `FeatureVector` (peakiness, variance, lower bound estimate)  
**Budget**: 2% of total

### Phase 1: Block Pooling + Capacity Tighten
**Modules**: `smart_block_builder.py`, `solve_capacity_phase`  
**Process**:
1. Convert abstract demand → concrete blocks (1-3 tours/day combinations)
2. Prioritize multi-tour blocks (3er > 2er > 1er)
3. **v7.0.0**: Dynamic peak detection (Mon/Fri adaptive)
4. **Optional CP-SAT**: Capacity tightening to select initial block subset
5. Track which `tour_ids` each block covers

**Budget**: 20% of total  
**Output**: ~1000-2000 blocks

### Phase 2: Roster Pool Generation + Expansion
**Modules**: `roster_column_generator.py`, `set_partition_solver.py`  
**Process**:
1. **Initial Pool**: Multi-stage generation targeting FTE-bands (47-53h, 42-47h, 30-42h)
2. **Templates**: Peak-ON/Peak+1-OFF adjacency patterns
3. **Local Validation**: Rest rules, weekly hours, qualifications
4. **PT Columns**: For hard-to-cover blocks
5. **Singleton Fallback**: One column per block (high cost) as feasibility net
6. **Iterative Expansion**: If RMP shows gaps → `targeted_repair()` generates more columns for uncovered tours

**Budget**: 65% of total (majority for quality)  
**Output**: 5k-15k roster columns, expanded adaptively

**Gap-Driven Expansion** (NOT classical CG):
```python
for round in range(max_rounds):
    rmp_result = solve_rmp(pool, tour_ids)
    if rmp_result["uncovered_tours"]:
        relaxed = solve_relaxed_rmp(pool)  # Diagnose gaps
        under_tours = relaxed["under_blocks"]
        new_columns = generator.targeted_repair(under_tours)  # Heuristic generation
        pool.add(new_columns)
    else:
        break  # Full coverage achieved
```

**Note**: No dual values, no reduced-cost pricing. Pure gap-driven heuristic repair.

### Phase 3: CP-SAT Restricted Master
**Module**: `set_partition_master.py` → `solve_rmp()`  
**Solver**: Google OR-Tools CP-SAT  
**Constraint**: Cover each `tour_id` exactly once (with elastic slack `u`)  
**Objective**: Weighted sum (see Formal Problem Statement)

**Process**:
- CP-SAT solves Set-Partitioning over current pool
- Typical: 5-10 rounds (capped at max_rounds=500)
- Early-stop on stall (20 rounds without improvement)
- RMP time limit: 45s/solve

**Budget**: Implicitly included in Phase 2 budget (integrated loop)  
**Output**: Selected rosters (optimal relative to pool)

### Phase 4: Post-Processing & Validation
**Module**: `forecast_solver_v4.py`  
**Process**:
1. **Validation**: Check all hard constraints (11h rest, weekly hours)
2. **Repair** (if violations detected):
   - 2-Step Swap: Fix next-day early start conflicts
   - Bump/Absorb: Reallocate to flex pool
3. **LNS Consolidation** (optional): Merge low-hour fragments (<30h FTE)
4. **Final Gate**: 0 violations required, else FAIL

**Budget**: 8% of total (LNS)  
**Critical**: Repair runs ONLY if validation fails. It's a safety net, not part of normal flow.

---

## 6. Budget Allocation (Source of Truth)

From `BudgetSlice.from_total()` (portfolio_controller.py:76-89):

| Phase | Budget % | Purpose |
|-------|----------|---------|
| Profiling | 2% | Feature extraction + lower bound estimate |
| Phase 1 | 20% | Block pooling + capacity tighten (CP-SAT) |
| Phase 2 | 65% | Roster generation + gap-driven expansion + RMP iterations |
| LNS | 8% | Low-hour consolidation (post-solve) |
| Buffer | 5% | Safety margin |

**Example** (120s budget):
- Profiling: 2.4s
- Phase 1: 24s
- Phase 2: 78s (majority time for quality)
- LNS: 9.6s
- Buffer: 6s

---

## 7. Hard Constraints (0 Violations Required)

1. **Rest Period**: Min 11h between shift end (day d) and start (day d+1)
2. **Weekly Hours**: Max 55h
3. **Daily Limits**: Max 3 tours/day (via block building)
4. **Split-Shift Rules**: Defined min/max gaps, `pause_zone` tracking
5. **Qualifications**: Tour requirements match driver skills

**Enforcement**: 
- **Local** (during roster generation): Pre-check each roster
- **Global** (post-selection): Validate final solution
- **Compliance Gate**: If violations exist after repair → status=INFEASIBLE

---

## 8. Current Performance (v7.0.0 Frozen Baseline)

### Run Metrics (Real Output)
```
Input:      1385 tours/week
Drivers:    113 FTE + 26 Core PT + 17 Flex PT = 156 effective
FTE Hours:  Avg 47.8h, Min 40.5h
PT Share:   10.3% (Core PT only, target <20%)
Flex Pool:  17 drivers (≤13.5h/week, peak overflow)
Fleet Peak: 113 vehicles @ Fri 18:30 (v7.2.0 Fleet Counter)
Runtime:    ~120s (default budget)
Validation: 0 violations (post-validated)
```

### Guardrails
- Core PT Share: **<20%** (Hard Limit)
- Drivers Active: **≤160** (Hard Limit)
- Flex Pool: **≤15** (Soft Warning)

---

## 9. Tech Stack

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
│   ├── roster_column_generator.py      # Phase 2a: Heuristic roster generation
│   ├── set_partition_solver.py         # Phase 2b: Main loop (RMP + expansion)
│   ├── set_partition_master.py         # Phase 3: CP-SAT RMP solve
│   ├── forecast_solver_v4.py           # Phase 4: Validation + repair
│   └── lns_refiner_v4.py               # LNS consolidation
├── fleet_counter.py                    # v7.2.0: Fleet demand analysis
├── export_roster_matrix.py             # CLI entrypoint
└── validate_promotion_gates.py         # CI quality gates
```

---

## 10. Post-Freeze Features

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
# Sort: time ASC, then delta ASC (-1 before +1)
# At same timestamp: end processed before start → vehicle handover = no extra fleet
events.sort(key=lambda e: (time_minutes(e[0]), e[1], e[2]))

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

**Note**: Times normalized to absolute datetimes; cross-midnight supported.

---

## 11. FAQ: Why This Approach?

### "Why not Greedy (fill in order)?"
**Problem**: Short-sighted. Assigns Monday without considering Friday overtime.  
**Result**: 190 drivers (greedy) vs. 156 (SOLVEREIGN) = 34 drivers saved.

### "Why not classical Column Generation with LP relaxation?"
**Reason**: CP-SAT provides better integer solutions directly, but lacks dual values.  
**Trade-off**: We generate larger pools upfront (10k columns) + adaptive expansion instead of dual-based pricing.  
**Benefit**: Simpler, more robust, no LP/MIP complexity.

### "Why not AI/Deep Learning?"
**Problem**: Neural nets hallucinate illegal schedules (rest violations).  
**Requirement**: Guaranteed legality → mathematical optimization > ML.

---

## 12. Operational Runbook

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

## 13. Compliance & Audit

### Legal Modeling
- **Work vs. Presence**: Exports distinguish paid work (tour segments) from blocked time (presence)
- **Split-Schicht**: Unpaid gaps (240-360min) tracked via `pause_zone=SPLIT`
- **Daily Rest**: 11h enforced via CP-SAT hard constraints
- **Audit Trail**: Every tour_id traceable to assigned driver

### Validation Process
1. **Post-RMP**: Check all selected rosters for violations
2. **Repair Gate**: If violations → repair → re-check
3. **Final Gate**: If violations persist → status=INFEASIBLE
4. **Compliance Report**: `compliance_report.json` (Planned v7.3.0)

**Critical Distinction**:  
We do NOT "guarantee 0 violations" during optimization. We **enforce a validation gate**: output is accepted only if it has 0 violations; otherwise the run fails.

---

## 14. Optimality Statement

### What We Claim
**CP-SAT is optimal relative to the current column pool.**

For a given pool of N rosters:
- CP-SAT finds the minimum-cost subset that covers all tour_ids
- Optimality is proven within the pool (exact solver)

### What We Don't Claim
**Global optimality** (across all possible rosters).

Why?:
- We don't enumerate all possible rosters (intractable)
- We don't compute a provable lower bound (no LP relaxation)
- We use heuristic pool generation + gap-driven expansion

### Gap to Lower Bound
We compute a **greedy lower bound** (total_hours / 55h) as a rough estimate.  
Typical gap: ~10% above lower bound.

---

## 15. Definition of Done

System is production-ready when:
1. **Legality**: 0% violations (post-validation gate)
2. **Efficiency**: Within 10% of theoretical lower bound
3. **Quality**: <20% Core PT share
4. **Robustness**: ±3 drivers variance across seeds
5. **Transparency**: Real-time events for all phases
6. **Audit**: Full trace from tour_id → driver

---

## 16. Version History

### v7.2.1 (2025-12-28)
- Corrected technical claims (CG → Gap-Driven Pool Expansion)
- Clarified objective (Dominance-Weighted, not lexicographic)
- Added formal problem statement + optimality disclaimer
- Fixed budget allocation table (single source from code)

### v7.2.0 (2025-12-28)
- Fleet Counter: Sweep-line peak vehicle demand
- CSV exports: peak summary + 15min timeline

### v7.1.0 (2025-12-28)
- SSE event bus for live progress
- Frontend dashboard with RMP visualization

### v7.0.0 (2025-12-27/28)
- Dynamic peak detection (Mon/Fri adaptive)
- Flex pool categorization (Core vs. Flex PT)
- 156 effective drivers (frozen baseline)
- 10.3% Core PT share
- Tag: `v7.0.0-freeze`

---

## 17. Future Roadmap

### v7.3.0 (Planned)
- Compliance report: `compliance_report.json` with zero-violation proof
- Multi-location support
- Driver preferences (soft constraints)

### v8.0.0 (Research)
- Multi-week planning (2-4 week horizon)
- Stochastic demand modeling
- Real-time re-optimization
- LP-based lower bounds for gap proof

---

## 18. Key Design Principles

1. **Determinism**: Same input → Same output (`seed=42`, `num_workers=1`)
2. **Legality**: Hard constraints validated (gate enforced post-solve)
3. **Transparency**: Every decision logged, every tour traceable
4. **Performance**: <5min runtime for production forecasts
5. **Honesty**: Claims must be mathematically accurate (no false optimality guarantees)

---

## 19. Team Requirements

**Must Have**:
- Python 3.13+ (type hints, Pydantic)
- Google OR-Tools (CP-SAT solver)
- Constraint programming fundamentals
- Production logging & monitoring

**Nice to Have**:
- Operations Research background
- Set-Partitioning / crew scheduling experience
- Shift scheduling domain knowledge

---

> **Final Note**:  
> SOLVEREIGN is a **high-performance heuristic optimizer** built around Google CP-SAT.  
> It uses **Column Pooling + Gap-Driven Expansion + Restricted Master Set-Partitioning**.  
> Results are **optimal relative to the generated pool**, with 0 violations guaranteed via post-solve validation gate.

---

**Repository**: [DRNaser/shift-optimizer](https://github.com/DRNaser/shift-optimizer)  
**Tag**: `v7.0.0-freeze` (baseline), `v7.2.1` (current)  
**License**: Proprietary
