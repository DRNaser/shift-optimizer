# 🏛️ SOLVEREIGN: The Complete Blueprint
> **System Architecture & Technical Vision**  
> **Version**: 7.2.0 | **Status**: OPERATIONAL ✅ | **Updated**: 2025-12-28

---

## 1. Executive Summary

**Problem**: Weekly demand forecasting requires optimal driver scheduling under strict legal and operational constraints.

**Solution**: SOLVEREIGN delivers **158 drivers** instead of 190+ (greedy baseline) through hybrid column generation.

**Business Impact**: ~40 fewer drivers = **€1.2-1.6M annual savings** at €40k/driver.

---

## 2. The Problem: "The Forecast Problem"

### Input
Weekly demand curve: "Monday 08:00 → 50 drivers needed"

### Constraints (Hard)
1. **Legal**: Rest periods (11h minimum), max weekly hours (55h), split-shift rules
2. **Operational**: Vehicle qualifications, location coverage
3. **Economic**: FTE drivers (40h+) profitable, Part-Time (PT) expensive → target <15% PT share

### Combinatorial Complexity
Billions of valid schedule combinations → requires mathematical optimization, not heuristics.

---

## 3. Solution Architecture: Hybrid Column Generation

### Phase 0: Demand Profiling
**Module**: `portfolio_controller.py`
- Analyzes forecast features (peaks, demand variance)
- Determines optimization parameters
- Budget allocation: profiling=2%, phase1=20%, phase2=65%, lns=8%

### Phase 1: Block Building
**Module**: `smart_block_builder.py`
- Converts abstract demand → concrete work blocks
- Prioritizes multi-tour blocks (3er, 2er) over singles
- **v7.0.0**: Dynamic peak detection (Mon/Fri adaptive)
- Output: ~1000-2000 blocks per forecast

**Example**:
```
Mon 08:00-17:00 → Block_001 (3er: Tour A + Tour B + Tour C)
Fri 18:00-23:00 → Block_456 (2er Split: Tour X + Tour Y)
```

### Phase 2: Roster Column Generation
**Module**: `roster_column_generator.py`
- Generates valid weekly rosters (Mon-Sat schedules)
- Each roster satisfies **all** constraints locally (rest, hours, qualifications)
- Uses templates: Peak-ON/Peak+1-OFF adjacency patterns
- Output: 5k-15k roster columns

**Quality Biasing**:
- FTE-band rosters (40-55h): +1000 priority
- Singletons: capped, used only for feasibility net

### Phase 3: Set Partitioning (RMP)
**Module**: `set_partition_master.py`
- **Solver**: Google OR-Tools CP-SAT
- **Objective**: Minimize drivers (Prio 1), then minimize PT share (Prio 2)
- **Constraint**: Cover each block exactly once
- Iterative: 5-10 rounds, adds columns dynamically

**Cost Function**:
```python
cost = base_cost + fte_underutil_penalty + pt_penalty + singleton_penalty
PT_BASE_COST = 500 (heavily discouraged)
```

### Phase 4: Repair & LNS
**Module**: `forecast_solver_v4.py`, `lns_refiner_v4.py`
- **2-Step Swap Repair**: Fixes rest violations (next-day early starts)
- **Mini-LNS**: Consolidates low-hour drivers, removes orphans
- **Bump/Absorb**: Flex pool for peak overflow

---

## 4. Current Performance (v7.0.0 Frozen Baseline)

```
Input:      1385 tours/week
Drivers:    113 FTE + 26 Core PT + 17 Flex PT = 156 effective
FTE Hours:  Avg 47.8h, Min 40.5h
PT Share:   10.3% (Core PT only, target <20%)
Flex Pool:  17 drivers (≤13.5h/week, peak overflow absorption)
Fleet Peak: 113 vehicles @ Fri 18:30 (v7.2.0)
Runtime:    ~120s (default budget)
```

**Guardrails**:
- Core PT Share: <20% (Hard Limit)
- Drivers Active: ≤160 (Hard Limit)
- Flex Pool: ≤15 (Soft Warning)

---

## 5. Tech Stack

### Core
- **Language**: Python 3.13
- **Solver**: Google OR-Tools CP-SAT (deterministic, num_workers=1)
- **Framework**: Pydantic (strict typing), FastAPI (REST API)

### Key Modules
```
backend_py/
├── src/services/
│   ├── portfolio_controller.py      # Pipeline orchestrator
│   ├── smart_block_builder.py       # Phase 1: Blocks
│   ├── roster_column_generator.py   # Phase 2: Rosters
│   ├── set_partition_master.py      # Phase 3: RMP
│   ├── forecast_solver_v4.py        # Phase 4: Repair
│   └── lns_refiner_v4.py            # LNS endgame
├── fleet_counter.py                 # v7.2.0: Fleet analysis
├── export_roster_matrix.py          # Entrypoint
└── validate_promotion_gates.py      # CI quality gates
```

### API & Frontend
- **Backend**: FastAPI + SSE (Server-Sent Events) for real-time progress
- **Frontend**: Next.js v5 + shadcn/ui
- **Events**: `ProgressEvent` schema → live pipeline visualization

---

## 6. Post-Freeze Features

### v7.1.0 Real-Time Transparency (2025-12-28) ✅
**Goal**: Maximum visibility into solver execution

**Backend**:
- Event Bus: `ProgressEvent` schema + SSE at `/api/v1/runs/{id}/events`
- Instrumented Phases:
  - Phase 0: `run_started`
  - Phase 1: `capacity_tighten` (cap iterations)
  - Phase 2: `rmp_round` (pool size, coverage, stall detection)
  - Phase 4: `repair_action` (bumps/absorbs)

**Frontend**:
- Live Dashboard: `PipelineStepper` component
- RMP Visualization: Live rounds table
- Repair Log: Auto-repair tracking panel

### v7.2.0 Fleet Counter (2025-12-28) ✅
**Goal**: Derive peak vehicle demand from tour data

**Algorithm**: Sweep-Line (O(n log n))
- Events at tour start (+1) and end (-1)
- Ends before starts at same time → vehicle handover = no extra fleet
- Optional turnaround delay

**Usage**:
```bash
python fleet_counter.py [--turnaround 5] [--interval 15] [--export]
```

**Output**:
```
+-----------------------------------------+
| FLEET COUNTER (Peak Vehicle Demand)     |
+-----------------------------------------+
| Mon: 105 vehicles @ 09:00               |
| Tue:  79 vehicles @ 18:00               |
| Wed:  76 vehicles @ 18:15               |
| Thu:  74 vehicles @ 08:45               |
| Fri: 113 vehicles @ 18:30 <- PEAK       |
| Sat: 111 vehicles @ 09:15               |
+-----------------------------------------+
| GLOBAL PEAK: 113 vehicles (Fri 18:30)   |
+-----------------------------------------+
```

**Exports**:
- `fleet_peak_summary.csv`: Per-day peaks
- `fleet_profile_15min.csv`: Timeline (15-min intervals)

---

## 7. Why Not Simpler? (FAQ)

### "Why not Greedy (fill in order)?"
**Problem**: Short-sighted. Assigns Monday tours without considering Friday overtime.  
**Result**: 190 drivers (greedy) vs. 158 drivers (SOLVEREIGN).

### "Why not AI/Deep Learning?"
**Problem**: Neural nets hallucinate illegal schedules (e.g., rest violations).  
**Requirement**: **Guaranteed legality** → mathematical optimization > ML for this domain.

### "Why Column Generation instead of direct IP?"
**Problem**: Direct IP has 10^9+ variables → intractable.  
**Solution**: Column generation generates only "good" columns → 10^4 variables → solvable.

---

## 8. Operational Runbook

### Standard Run
```bash
python backend_py/export_roster_matrix.py --time-budget 120
```
**Expected**: PASS (Core PT Share) + WARN (Flex Pool) — both acceptable.

### Troubleshooting
| Issue | Action |
|-------|--------|
| Feasibility Fail | Check input overlaps. Try `--time-budget 300` |
| Driver Count >160 | Debug with seed variance: `--seed 0-4` |
| Peak Orphans | Check logs for "Dynamic Peak Days" |

### Emergency Flags
- `--time-budget 300`: Extended budget for quality improvement
- `--seed <N>`: Deterministic debugging (default: 42)

---

## 9. Compliance & Audit

### Legal Modeling
- **Work vs. Presence**: Exports distinguish blocked time (presence) from paid work (tour segments)
- **Split-Schicht**: Unbezahlte Pausen (240-360min) modeled correctly as `pause_zone=SPLIT`
- **Daily Rest**: 11h minimum strictly enforced via CP-SAT constraints
- **Audit Trail**: `compliance_report.json` (Planned v7.3.0)

### Austrian Law Compliance
- **11h Rest Rule**: Hard constraint, no exceptions
- **Split-Shift Rules**: Explicitly tracked via `is_split` + `pause_zone` fields
- **Max Weekly Hours**: 55h hard cap

---

## 10. Definition of Done (Acceptance Criteria)

System is production-ready when:
1. **Legality**: 0% constraint violations (automated validation)
2. **Efficiency**: Driver count within 10% of theoretical lower bound
3. **Quality**: <20% Core PT share (target <15%)
4. **Robustness**: Stable results across seed variance (±3 drivers)
5. **Transparency**: Real-time progress events for all phases
6. **Audit**: Compliance reports generated per run

---

## 11. Version History

### v7.2.0 (2025-12-28)
- ✅ Fleet Counter: Peak vehicle demand analysis
- ✅ Sweep-line algorithm (O(n log n))
- ✅ CSV exports (peak summary, timeline)

### v7.1.0 (2025-12-28)
- ✅ Real-time transparency via SSE
- ✅ Live dashboard (RMP rounds, repair log)
- ✅ Full pipeline instrumentation

### v7.0.0 (2025-12-27/28)
- ✅ Dynamic peak detection (Mon/Fri adaptive)
- ✅ Flex pool categorization (Core PT vs. Flex PT)
- ✅ 156 effective drivers (frozen baseline)
- ✅ 10.3% Core PT share (target met)

---

## 12. Future Roadmap

### v7.3.0 (Planned)
- [ ] Compliance Report: `compliance_report.json` with zero-violation proof
- [ ] Multi-Location Support: Expand beyond single depot
- [ ] Driver Preferences: Soft constraints for shift preferences

### v8.0.0 (Research)
- [ ] Multi-Week Planning: 2-4 week horizon
- [ ] Stochastic Demand: Uncertainty modeling
- [ ] Real-Time Re-Optimization: Intraday adjustments

---

## 13. Key Design Principles

1. **Determinism First**: Same input → Same output (seed=42 default)
2. **Legality Non-Negotiable**: Hard constraints never violated
3. **Incremental Complexity**: Build simple, add complexity only when ROI justified
4. **Transparency**: Every decision logged and explainable
5. **Performance**: Sub-5min runtime for production forecasts

---

## 14. Team Requirements

**Must Have**:
- Python 3.10+ (type hints, Pydantic)
- Google OR-Tools competency (CP-SAT)
- Constraint programming fundamentals
- Production-grade logging & monitoring

**Nice to Have**:
- Operations Research background
- Experience with column generation
- Domain knowledge in shift scheduling

---

> **Final Note**:  
> SOLVEREIGN is not calendar software. It's a **high-performance mathematical optimizer** built around Google CP-SAT. Focus: **Column Generation** + **Clean Data Models** + **Guaranteed Legality**.

---

**Repository**: [DRNaser/shift-optimizer](https://github.com/DRNaser/shift-optimizer)  
**Tag**: `v7.0.0-freeze` (baseline), `v7.2.0` (current)  
**License**: Proprietary
