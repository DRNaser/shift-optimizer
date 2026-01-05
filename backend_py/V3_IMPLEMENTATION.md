# SOLVEREIGN V3 Implementation Guide

> **Date**: 2026-01-04
> **Status**: M2 COMPLETE ✅ | M1-M5 IN PROGRESS
> **Roadmap**: See [../ROADMAP.md](ROADMAP.md)

---

## 🎯 Executive Summary

**V3 transforms the operational V2 solver into a production-ready dispatch platform** with:
- ✅ Postgres-based version control (forecast + plan versions)
- ✅ Immutable audit trail
- ✅ Parser validation gates
- ✅ Diff engine for change tracking
- ✅ Freeze windows for operational stability
- ✅ Streamlit UI for dispatch operators

**V2 Reality Check:**
- Current solver: **145 drivers, 0 PT, seed 94** → Production-ready
- V3 adds: Operational tooling around proven solver core

---

## 📊 Implementation Status

### ✅ Milestone 2: Postgres Core Schema (COMPLETE)

**Deliverables:**
- [x] Docker Compose updated with PostgreSQL 16
- [x] 10-table schema created ([db/init.sql](db/init.sql))
- [x] Utility views for release-ready plans
- [x] Triggers for LOCKED plan immutability
- [x] Default freeze window rules

**Test Status:**
```bash
# Start database
docker-compose up -d postgres

# Verify schema
docker exec -it solvereign-db psql -U solvereign -d solvereign -c "\dt"

# Expected output:
# forecast_versions | tours_raw | tours_normalized | plan_versions |
# assignments | audit_log | freeze_windows | diff_results
```

**Schema Highlights:**
- **forecast_versions**: Tracks input versions with validation status
- **tours_normalized**: Canonical tour data with fingerprint matching
- **plan_versions**: Immutable solver outputs (DRAFT → LOCKED)
- **assignments**: Driver-to-tour mappings
- **audit_log**: Write-only validation results
- **freeze_windows**: Operational stability rules

---

### 🔄 Milestone 1: Parser + Validation Gate (IN PROGRESS)

**Goal**: Deterministic whitelist-based parsing with PASS/WARN/FAIL gates

**Architecture:**
```python
# parser.py
class TourParser:
    def parse_line(self, raw_text: str) -> ParseResult:
        """Parse single tour line against whitelist grammar."""
        # Example inputs:
        # ✅ "Mo 06:00-14:00 3 Fahrer Depot Nord"
        # ✅ "Di 06:00-14:00 + 15:00-19:00"  (split)
        # ❌ "Fr early shift"  (ambiguous)

    def validate_forecast(self, lines: list[str]) -> ForecastValidation:
        """Validate entire forecast and compute input_hash."""
```

**Required Files:**
```
backend_py/v3/
├── __init__.py
├── parser.py           # Whitelist parser
├── grammar.py          # Tour format grammar (regex/EBNF)
├── canonicalizer.py    # Standardize input for hashing
└── tests/
    └── test_parser.py  # 20+ test cases (M1 DoD)
```

**Next Steps:**
1. Define whitelist grammar (get 50+ real Slack examples)
2. Implement parser with PASS/WARN/FAIL logic
3. Write 20+ test cases
4. Integrate with `tours_raw` table

---

### 🔄 Milestone 3: Diff Engine (PENDING)

**Goal**: Compute deterministic diffs between forecast versions

**Architecture:**
```python
# diff_engine.py
class DiffEngine:
    def compute_diff(
        self,
        forecast_old: int,
        forecast_new: int
    ) -> DiffSummary:
        """
        Match tours by fingerprint, classify as ADDED/REMOVED/CHANGED.
        Store results in diff_results table for caching.
        """

    def tour_fingerprint(self, tour: Tour) -> str:
        """hash(day, start_minute, end_minute, depot?, skill?)"""
```

**Required Files:**
```
backend_py/v3/
├── diff_engine.py       # Fingerprint matching + diff computation
├── models.py            # DiffType, TourDiff dataclasses
└── tests/
    └── test_diff.py     # Snapshot tests (fixed inputs → fixed diffs)
```

---

### 🔄 Milestone 4: Solver Integration (PENDING)

**Goal**: Wrap V2 solver with versioning layer

**Architecture:**
```python
# solver_wrapper.py
class SolverV3:
    def solve(self, forecast_version_id: int, seed: int = 94) -> int:
        """
        1. Load tours_normalized for forecast_version
        2. Run V2 block heuristic solver
        3. Create plan_version (status=DRAFT)
        4. Store assignments
        5. Run audit checks → audit_log
        6. Compute output_hash
        7. Return plan_version_id
        """
```

**Integration Points:**
- Reuse: `run_block_heuristic.py` (V2 solver)
- New: Wrap with DB I/O + versioning
- New: Audit framework (coverage, rest, overlap, span)

---

### 🔄 Milestone 5: Release Mechanism (PENDING)

**Goal**: DRAFT → LOCKED transition with freeze window enforcement

**Architecture:**
```python
# release.py
class ReleaseManager:
    def can_release(self, plan_version_id: int) -> tuple[bool, list[str]]:
        """Check all release gates (audit PASS, no frozen violations)."""

    def release_plan(self, plan_version_id: int, user: str) -> None:
        """
        1. Verify can_release() == True
        2. Update plan_version: status=LOCKED, locked_by=user
        3. Mark previous LOCKED plans as SUPERSEDED
        4. Generate exports (matrix.csv, rosters.csv, kpis.json)
        5. Trigger postgres IMMUTABILITY LOCK
        """
```

---

### 🔄 Streamlit UI (PENDING)

**Goal**: 4-tab dispatcher cockpit

**Tabs:**
1. **Ingest/Parser**: Red/yellow/green line validation
2. **Diff View**: ADDED/REMOVED/CHANGED tours
3. **Plan Preview**: Reuse `final_schedule_matrix.html` + KPIs
4. **Release**: Manual LOCK button (only active if gates PASS)

**Tech Stack:**
- Streamlit 1.30+
- PostgreSQL connection via psycopg3
- Plotly for visualizations

---

## 🚀 Quick Start (Current Status)

### 1. Database Setup
```bash
# Start Postgres
docker-compose up -d postgres

# Verify schema
docker exec -it solvereign-db psql -U solvereign -d solvereign

# In psql:
\dt                    # List tables
SELECT * FROM freeze_windows;  # Verify default rules
```

### 2. V2 Solver (Still Operational)
```bash
# Current workflow (no V3 changes yet)
python backend_py/run_block_heuristic.py

# Expected output:
# - 145 drivers
# - 0 violations
# - final_schedule_matrix.csv + .html
```

### 3. Next Development Steps

**Option A: Complete M1 (Parser)**
```bash
# 1. Collect 50+ real Slack tour messages
# 2. Design whitelist grammar
# 3. Implement parser.py
# 4. Write 20+ tests
# 5. Integrate with tours_raw table
```

**Option B: Complete M4 (Solver Wrapper)**
```bash
# 1. Create solver_wrapper.py
# 2. Load V2 solver results into plan_versions + assignments
# 3. Implement audit checks
# 4. Test reproducibility (same seed → same output_hash)
```

**Option C: Complete M3 (Diff Engine)**
```bash
# 1. Implement fingerprint matching
# 2. Classify ADDED/REMOVED/CHANGED
# 3. Write snapshot tests
# 4. Store diffs in diff_results table
```

**Recommended Order:** M4 → M3 → M1 → M5 → Streamlit UI

**Rationale:**
- M4 proves V2 solver integrates with versioning
- M3 enables change tracking (operators need this)
- M1 required for Slack integration (lower priority if using CSV)
- M5 + UI finalize operational workflow

---

## 📋 Definition of Done (Checklist)

### M1: Parser + Validation Gate
- [ ] 20+ parser test cases (PASS/WARN/FAIL)
- [ ] input_hash stable (whitespace/format irrelevant)
- [ ] FAIL status blocks solver execution
- [ ] Parser config versioned (parser_config_hash)

### M2: Postgres Core Schema ✅
- [x] docker-compose up → DB launches
- [x] Migrations create all MVP tables
- [x] Roundtrip test possible (CSV → DB → CSV)
- [x] Foreign key constraints enforced

### M3: Diff Engine
- [ ] Input: 2 forecast versions → Output: deterministic diff.json
- [ ] Snapshot tests pass (fixed inputs → fixed diff output)
- [ ] Handles ADDED/REMOVED/CHANGED correctly
- [ ] Tour fingerprint matching works across versions

### M4: Solver Integration (DRAFT Plans)
- [ ] plan_version created with status=DRAFT
- [ ] audit_log populated with all mandatory checks
- [ ] Reproducibility test passes (same inputs → same output_hash)
- [ ] V2 solver wrapped with versioning layer

### M5: Release Mechanism
- [ ] LOCKED plans immutable (no in-place edits)
- [ ] Export files include plan_version_id in metadata
- [ ] Manual release button functional (Streamlit or CLI)
- [ ] Superseded plans marked correctly

---

## 🛠️ Technical Reference

### Database Connection
```python
# backend_py/v3/db.py
import psycopg
from psycopg.rows import dict_row

def get_connection():
    return psycopg.connect(
        "host=localhost port=5432 dbname=solvereign user=solvereign password=dev_password_change_in_production",
        row_factory=dict_row
    )
```

### Running Migrations
```bash
# Currently: docker-entrypoint-initdb.d/01-init.sql runs automatically
# Future: Use Alembic or Flyway for versioned migrations
```

### Environment Variables
```bash
# .env (create this file)
DATABASE_URL=postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign
SOLVER_SEED=94
FREEZE_WINDOW_MINUTES=720
```

---

## 📚 Key Files

| File | Purpose | Status |
|------|---------|--------|
| [ROADMAP.md](../ROADMAP.md) | V3 architecture specification | ✅ Complete |
| [docker-compose.yml](../docker-compose.yml) | Postgres + services config | ✅ Updated |
| [db/init.sql](db/init.sql) | Database schema (10 tables) | ✅ Complete |
| `v3/parser.py` | Whitelist parser | ⏳ TODO (M1) |
| `v3/diff_engine.py` | Fingerprint matching + diff | ⏳ TODO (M3) |
| `v3/solver_wrapper.py` | V2 solver + versioning | ⏳ TODO (M4) |
| `v3/release.py` | DRAFT → LOCKED logic | ⏳ TODO (M5) |
| `streamlit_app.py` | 4-tab dispatcher UI | ⏳ TODO |

---

## 🎓 Learning Resources

**Postgres Best Practices:**
- JSONB columns for extensibility (parse_errors, details_json, metadata)
- CHECK constraints for data integrity
- Triggers for business rule enforcement (LOCKED immutability)
- Views for common queries (release_ready_plans)

**Deterministic Computing:**
- Fixed seeds (`random.seed(94)`)
- Sorted iteration (`blocks.sort(...)`)
- Single-threaded execution (`num_workers=1`)
- Input hashing (SHA256 of canonical format)

**Operational Stability:**
- Freeze windows prevent last-minute chaos
- Immutable audit trail (write-only audit_log)
- Version control for everything (forecast + plan + parser config)
- Manual release gates (humans approve, machines validate)

---

## 📞 Next Steps

**For Implementation:**
1. Choose milestone order (recommended: M4 → M3 → M1 → M5)
2. Set up Python environment with psycopg3
3. Create test database (`docker-compose up -d postgres`)
4. Implement chosen milestone (see DoD checklists)

**For Questions:**
- Architecture clarifications → Refer to [ROADMAP.md](../ROADMAP.md)
- Database schema → See [db/init.sql](db/init.sql)
- Business rules → See ROADMAP sections 4-9

---

**Last Updated**: 2026-01-04
**Next Review**: After M4 completion
