# SKILL.md — SOLVEREIGN V3 (Claude Operating Manual)

> **Version**: 8.5.0 | **Status**: V3.1 ENTERPRISE FEATURES | **Updated**: 2026-01-04
> **Result**: 145 Drivers | 0 PT | Max 54h | 1385/1385 Coverage | 7/7 Audits PASS
> **Parser**: 100/100 Fixtures PASS | 0 False Positives
> **Features**: Compose Engine | Scenario Runner | Churn Minimization | Freeze Windows
> **Deployment**: Internal Tool (LTS Transport u. Logistik GmbH)

---

## 1. Intent

Deterministische Dispatch-Plattform für Enterprise Logistik (500+ Fahrer).

**Pipeline:**
```
Ingest (Slack/CSV) → Parse → Validate → Solve (DRAFT) → Audit → Release (LOCK) → Export
```

**Core Principle:** Kein LLM im Core. Same input → same output.

---

## 2. Hard Gates (Blocking)

| Gate | Requirement | Failure = Blocker |
|------|-------------|-------------------|
| **Coverage** | 100% (jede Tour genau 1x assigned) | Ja |
| **Rest** | ≥11h zwischen BLOCKS (Tagen) | Ja |
| **Span Regular** | ≤14h für 1er, 2er-reg | Ja |
| **Span Split/3er** | ≤16h für 2er-split, 3er-chain | Ja |
| **Split Break** | 240-360min (4-6h) | Ja |
| **Fatigue** | Kein 3er → 3er (consecutive days) | Ja |
| **Max Weekly Hours** | ≤55h pro Fahrer/Woche | Ja |
| **Reproducibility** | Same (input_hash, seed, config) → same output_hash | Ja |

---

## 3. Block-Typen

| Typ | Gap zwischen Tours | Span Limit | Beschreibung |
|-----|-------------------|------------|--------------|
| **3er-chain** | 30-60min | ≤16h | Connected triple, kein langer Idle |
| **2er-split** | 240-360min | ≤16h | Split Shift mit 4-6h Pause |
| **2er-reg** | 30-60min | ≤14h | Regular Double Shift |
| **1er** | — | — | Single Tour |

**Wichtig:** 3er-chain hat NUR 30-60min Gaps (keine Split-Gaps wie 240-360min).

---

## 4. Domain Definitions

| Begriff | Definition |
|---------|------------|
| **WorkHours** | Summe Tour-Dauern pro Fahrer-Woche (FTE ≥ 40h) |
| **SpanHours** | First start → Last end pro Tag inkl. Idle |
| **Tour Template** | 1 Zeile mit `count` (z.B. count=3 → 3 Instanzen) |
| **Tour Instance** | 1 konkrete Arbeitseinheit (1:1 mit Assignment) |
| **Block** | Set von Tours pro Fahrer pro Tag (1er/2er/3er) |

---

## 5. Tech Stack

```
Python 3.x | PostgreSQL 16 (Docker) | Streamlit | psycopg3
Kein LLM im Core (deterministisch)
```

---

## 6. Critical Files

| Datei | Funktion |
|-------|----------|
| `v3/solver_v2_integration.py` | Block Partitioning (is_reg, is_split, 3er logic) |
| `v3/solver_wrapper.py` | Solver Entry Point mit Churn + Freeze |
| `v3/audit_fixed.py` | 7 Audit Checks (Coverage, Rest, Span, Fatigue) |
| `v3/compose.py` | **V3.1** LWW Compose Engine |
| `v3/scenario_runner.py` | **V3.1** Parameterized Solver Runs |
| `run_block_heuristic.py` | Legacy Solver Entry Point |
| `src/services/block_heuristic_solver.py` | can_assign() mit Fatigue Rule |
| `v3/parser.py` | Whitelist Parser (PASS/WARN/FAIL) |
| `v3/diff_engine.py` | Fingerprint-based Diff |
| `db/init.sql` | PostgreSQL Schema (10 Tables) |
| `db/migrations/001_tour_instances.sql` | P0 Migration |
| `db/migrations/002_compose_scenarios.sql` | **V3.1** Compose + Scenario Schema |
| `test_audit_proofs.py` | Proof #4-9 Validation |
| `streamlit_app.py` | Dispatcher Cockpit UI |

---

## 7. Code Locations (Bug-Critical)

### 3er-Chain Logic
```python
# v3/solver_v2_integration.py:286, 303
# run_block_heuristic.py:435, 452
if is_reg(g):  # NUR 30-60min, KEINE Split-Gaps
```

### Split Break Range
```python
# v3/solver_v2_integration.py:266-268
# run_block_heuristic.py:418
def is_split(gap): return 240 <= gap <= 360  # 4-6h
```

### Fatigue Rule
```python
# src/services/block_heuristic_solver.py:35-47
if len(prev_block.tours) == 3 and len(block.tours) == 3:
    return False  # 3er → 3er verboten
```

### Rest Check (zwischen BLOCKS, nicht Tours)
```python
# test_audit_proofs.py:270-320
# Gruppiere nach Tag, prüfe Rest zwischen Block-Grenzen
```

---

## 8. Do / Don't

### DO
- Tests für jeden Bugfix
- Stable ordering überall (sort before process)
- Evidence mit Hashes (input_hash, output_hash)
- Update Docs wenn Model ändert

### DON'T
- Kein "PASS" ohne exakte Counters zeigen
- Keine Schema-Änderung ohne Migration
- Keine Heuristiken ohne Audit-Trail
- Kein `dict`/`set` iterieren ohne sort (Determinismus)

---

## 9. Work Protocol

```
1. Intent    → Was wird geändert (1 Absatz)
2. Impact    → Welche Komponenten betroffen
3. Implement → Code ändern
4. Test      → pytest / test_audit_proofs.py
5. Evidence  → Hashes, KPIs, Audit Results
6. Docs      → ROADMAP, SKILL.md updaten
```

---

## 10. Evidence Policy

### Für jeden "DONE" Claim:
- [ ] `metadata.json` (seed + hashes)
- [ ] `kpis.json` (drivers, PT, coverage)
- [ ] Audit Results (6/6 PASS mit Counters)
- [ ] Reproducibility Proof (2 Runs → same hash)

**Kein Evidence → nicht akzeptiert.**

---

## 11. Acceptance Checklist

- [ ] 7/7 Audits PASS (inkl. 55h Max)
- [ ] Reproducibility verified (same input → same output)
- [ ] Driver Count documented (aktuell: 145)
- [ ] Max Weekly Hours ≤55h (aktuell: Max 54h)
- [ ] Artifacts exported (matrix.csv, rosters.csv, kpis.json)
- [ ] SKILL.md und ROADMAP.md consistent

---

## 12. Crash Recovery & Transaction Safety

### PlanStatus Lifecycle
```
SOLVING → DRAFT → LOCKED
    ↓
  FAILED (on error/timeout)
```

### Transaction Safety
- All assignments inserted in SINGLE transaction
- If crash mid-insert → plan stays SOLVING → cleanup marks FAILED
- No partial data possible

### Recovery Functions
```python
from v3.solver_wrapper import run_crash_recovery

# On startup: clean stale SOLVING plans (>60min old)
run_crash_recovery(max_age_minutes=60)
```

### Database Functions
| Funktion | Zweck |
|----------|-------|
| `create_assignments_batch()` | Atomic batch insert |
| `update_plan_status()` | Status transition |
| `cleanup_stale_solving_plans()` | Mark old SOLVING → FAILED |
| `get_solving_plans()` | Find stuck plans |

---

## 13. Parser Robustness Suite

### Test Coverage
```
100 Fixtures | 8 Categories | 100% Pass Rate
```

### Categories
| Cat | Count | Examples |
|-----|-------|----------|
| basic | 10 | `Mo 06:00-14:00` |
| count | 10 | `Mo 06:00-14:00 3 Fahrer` |
| depot | 10 | `Mo 06:00-14:00 Depot Nord` |
| split | 10 | `Mo 06:00-10:00 + 15:00-19:00` |
| midnight | 10 | `Mo 22:00-06:00` |
| edge | 20 | Empty lines, comments, spacing |
| warn | 10 | `HIGH_COUNT`, `EXCESSIVE_WORK_HOURS` |
| fail | 20 | Invalid day, time, format |

### Run Tests
```bash
python tests/test_parser_robustness.py
```

### Output
```
tests/reports/parser_report.json      # Summary
tests/reports/parser_full_results.json # Full details
```

### Key Principle
**0 False Positives** - Parser FAIL > "best effort" guess

---

## 14. Common Failure Modes

| # | Fehler | Fix |
|---|--------|-----|
| 1 | Rest zwischen Tours statt Blocks | Gruppiere nach Tag, prüfe Block-Grenzen |
| 2 | 3er mit Split-Gaps (240-360min) | `if is_reg(g):` nicht `if is_reg(g) or is_split(g):` |
| 3 | Split Break fix 360min | Range 240-360min verwenden |
| 4 | Fatigue nicht in can_assign() | Check bei prev/next day für 3er→3er |
| 5 | Dict/Set ordering | Immer sort() vor iterate |
| 6 | TIME-only Audits | week_anchor_date + datetime verwenden |

---

## 15. Compose Engine (V3.1)

### Partial Forecast Handling
Slack-Nachrichten können partielle Updates sein (nur bestimmte Tage). Das Compose Engine merged diese via LWW (Latest-Write-Wins).

```
PATCH (Mo, Di) + PATCH (Mi, Do) → COMPOSED (Mo-Do)
```

### Key Concepts

| Begriff | Definition |
|---------|------------|
| **PATCH** | Partial forecast update für eine Woche |
| **COMPOSED** | LWW-Merge aller Patches für `week_key` |
| **Tombstone** | Explizite Tour-Löschung in Patch |
| **Completeness** | PARTIAL / COMPLETE basierend auf days_present |

### Critical Files
| Datei | Funktion |
|-------|----------|
| `v3/compose.py` | LWW Compose Engine |
| `db/migrations/002_compose_scenarios.sql` | Schema Migration |

### Compose Flow
```python
from v3.compose import compose_week_forecast

result = compose_week_forecast(
    week_key="2026-W01",
    db_connection=conn,
    expected_days=6  # Mo-Sa
)
# result.completeness: PARTIAL | COMPLETE
```

### Release Gating
```python
from v3.compose import check_release_gate

gate = check_release_gate(forecast_id, conn, require_complete=True)
if not gate['can_release']:
    # Admin override erforderlich
    gate = check_release_gate(..., admin_override=True, admin_user="admin@lts.de")
```

---

## 16. Scenario Runner (V3.1)

### Parameterized Solver Runs
Mehrere Solver-Konfigurationen auf derselben Forecast ausführen und vergleichen.

### SolverConfig Parameters
| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `seed` | 94 | Random seed |
| `weekly_hours_cap` | 55 | Max Wochenstunden |
| `freeze_window_minutes` | 720 | Freeze Window (12h) |
| `triple_gap_min` | 30 | 3er Gap Minimum |
| `triple_gap_max` | 60 | 3er Gap Maximum |
| `split_break_min` | 240 | Split Break Min (4h) |
| `split_break_max` | 360 | Split Break Max (6h) |
| `churn_weight` | 0.0 | Stability penalty |

### Usage
```python
from v3.scenario_runner import ScenarioRunner, compare_scenarios
from v3.models import SolverConfig

runner = ScenarioRunner(db_connection)
comparison = runner.run_scenarios(
    forecast_version_id=1,
    scenarios=[
        SolverConfig(seed=42, churn_weight=0.0),
        SolverConfig(seed=42, churn_weight=0.5),
    ],
    labels=["No Churn", "Churn 0.5"],
    week_key="2026-W01"
)

# Get best scenario
best = comparison.best_by_drivers()  # Minimize headcount
best = comparison.best_by_churn()    # Minimize churn
```

### Seed Sweep
```python
comparison = runner.run_seed_sweep(
    forecast_version_id=1,
    base_config=SolverConfig(seed=1),
    seed_count=10,
    week_key="2026-W01"
)
```

---

## 17. Churn Minimization (V3.1)

### Definition
Churn = Anzahl der Instanz-Änderungen vs. Baseline (letzter LOCKED Plan).

### Metrics
| Metric | Definition |
|--------|------------|
| `churn_count` | Anzahl geänderter Tour-Instanzen |
| `churn_drivers_affected` | Anzahl betroffener Fahrer |
| `churn_percent` | churn_count / total_instances * 100 |

### Churn Weight
```python
# cost = base_cost + churn_weight * churn_count
SolverConfig(churn_weight=0.5)  # Penalize churn
```

### Baseline Lookup
```python
from v3.compose import get_baseline_plan

baseline = get_baseline_plan("2026-W01", conn)
# Returns last LOCKED plan for week_key
```

---

## 18. Freeze Windows (V3.1)

### Baseline-Tied Semantics
Freeze Window = Zeitfenster vor Tour-Start, in dem Assignment nicht geändert werden darf (tied to baseline).

```
freeze_window_minutes = 720  # 12h default
```

### Freeze Check
```python
from v3.solver_wrapper import check_freeze_violations, get_frozen_instances

violations = check_freeze_violations(
    forecast_version_id=1,
    baseline_plan_id=5,
    freeze_minutes=720
)
# Returns list of frozen tour instances

frozen_ids = get_frozen_instances(forecast_id, baseline_id, 720)
```

### Freeze = Baseline Required
- Ohne Baseline → keine Freeze Violations möglich
- Frozen Instance → Assignment muss von Baseline übernommen werden

---

## 19. Appendix: Current Hashes

```
input_hash:         d1fc3cc7b2d8425faa91fc25472cbc90c4e5b891a4521500ddc9af4a4153885d
output_hash:        d329b1c40b8fc566fa32487db0830d1a2948b61ed72ab30847e39dbf731efd10
solver_config_hash: 0793d620da605806bf96a1e08e5a50687a10533b6cc6382d7400a09b43ce497f
```

---

**Next Agent**: Read [ROADMAP.md](backend_py/ROADMAP.md) und [claude.md](claude.md) vor Änderungen.
