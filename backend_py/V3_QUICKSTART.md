# SOLVEREIGN V3 - Quick Start Guide

> **Status**: Core infrastructure complete (M2, M3, M5 partial) ✅
> **Ready for**: Database testing, Diff engine testing, Audit framework testing
> **Pending**: M1 (Parser), M4 (Solver wrapper), Streamlit UI

---

## 🚀 5-Minute Setup

### 1. Start PostgreSQL Database

```bash
# Start database (includes automatic schema initialization)
docker-compose up -d postgres

# Wait for database to be ready
docker logs -f solvereign-db

# You should see:
# ✅ SOLVEREIGN V3 Database Schema Initialized Successfully
```

### 2. Install Python Dependencies

```bash
# Install required packages
pip install 'psycopg[binary]' python-dotenv

# Optional (for full V3 features)
pip install streamlit plotly pandas
```

### 3. Test Database Connection

```bash
# Run connection test
python backend_py/test_db_connection.py

# Expected output:
# ✅ ALL TESTS PASSED!
```

---

## 📚 What's Been Implemented

### ✅ Milestone 2: Postgres Core (COMPLETE)

**Database Schema** ([db/init.sql](db/init.sql)):
- 8 core tables with full constraints
- 2 utility views for release management
- Triggers for LOCKED plan immutability
- Default freeze window rules

**Test it:**
```bash
docker exec -it solvereign-db psql -U solvereign -d solvereign

# In psql:
\dt                          # List tables
SELECT * FROM freeze_windows; # View default rules
\q                           # Exit
```

---

### ✅ Milestone 3: Diff Engine (COMPLETE)

**Module** ([v3/diff_engine.py](v3/diff_engine.py)):
- Fingerprint-based tour matching
- ADDED/REMOVED/CHANGED classification
- Diff result caching in database

**Test it:**
```python
from backend_py.v3.diff_engine import compute_diff

# Create two test forecast versions first (see example below)
diff = compute_diff(forecast_old=1, forecast_new=2)

print(f"Added: {diff.added}")
print(f"Removed: {diff.removed}")
print(f"Changed: {diff.changed}")
```

---

### ✅ Milestone 5: Audit Framework (PARTIAL)

**Module** ([v3/audit.py](v3/audit.py)):
- ✅ Coverage check (100% tour assignment)
- ✅ Overlap check (no concurrent tours per driver)
- ✅ Rest check (≥11h between blocks)
- ⏳ TODO: Span checks, reproducibility check, fatigue check

**Test it:**
```python
from backend_py.v3.audit import audit_plan

# Run all enabled checks
results = audit_plan(plan_version_id=1)

if results["all_passed"]:
    print("✅ Plan ready for release!")
else:
    print(f"❌ Failed {results['checks_failed']} checks")
    print(results["results"])
```

---

### ✅ Core Infrastructure

**Configuration** ([v3/config.py](v3/config.py)):
- Environment-based configuration
- Feature flags
- Validation warnings

**Database Layer** ([v3/db.py](v3/db.py)):
- Connection management
- CRUD operations for all tables
- Release gate checking

**Data Models** ([v3/models.py](v3/models.py)):
- Dataclasses for all entities
- Enums for status types
- Utility functions (fingerprinting, hashing)

---

## 🧪 Testing Examples

### Example 1: Create Forecast Version

```python
from backend_py.v3 import db, models

# Create forecast version
forecast_id = db.create_forecast_version(
    source="manual",
    input_hash="test_hash_001",
    parser_config_hash="v3.0.0-mvp",
    status="PASS",
    notes="Test forecast"
)

print(f"Created forecast_version_id: {forecast_id}")

# Add normalized tours
tour_id = db.create_tour_normalized(
    forecast_version_id=forecast_id,
    day=1,  # Monday
    start_ts="06:00:00",
    end_ts="14:00:00",
    duration_min=480,
    work_hours=8.0,
    tour_fingerprint=models.compute_tour_fingerprint(1, "06:00:00", "14:00:00"),
    count=3  # 3 drivers needed
)

print(f"Created tour_id: {tour_id}")
```

### Example 2: Test Diff Engine

```python
from backend_py.v3 import db, models
from backend_py.v3.diff_engine import compute_diff

# Create forecast v1
fv1 = db.create_forecast_version("manual", "hash_v1", "v3.0.0", "PASS")
db.create_tour_normalized(
    fv1, 1, "06:00:00", "14:00:00", 480, 8.0,
    models.compute_tour_fingerprint(1, "06:00:00", "14:00:00"),
    count=3
)

# Create forecast v2 (with changes)
fv2 = db.create_forecast_version("manual", "hash_v2", "v3.0.0", "PASS")
db.create_tour_normalized(
    fv2, 1, "06:00:00", "14:00:00", 480, 8.0,
    models.compute_tour_fingerprint(1, "06:00:00", "14:00:00"),
    count=5  # Changed from 3 to 5
)
db.create_tour_normalized(  # New tour
    fv2, 2, "07:00:00", "15:00:00", 480, 8.0,
    models.compute_tour_fingerprint(2, "07:00:00", "15:00:00"),
    count=2
)

# Compute diff
diff = compute_diff(fv1, fv2)
print(f"Added: {diff.added}, Removed: {diff.removed}, Changed: {diff.changed}")
```

### Example 3: Test Audit Framework

```python
from backend_py.v3 import db
from backend_py.v3.audit import audit_plan

# Create plan version
plan_id = db.create_plan_version(
    forecast_version_id=1,
    seed=94,
    solver_config_hash="v3.0.0-mvp",
    output_hash="test_output_hash",
    status="DRAFT"
)

# Add assignments
db.create_assignment(
    plan_version_id=plan_id,
    driver_id="D001",
    tour_id=1,
    day=1,
    block_id="D1_B1"
)

# Run audits
results = audit_plan(plan_id)
print(results)
```

---

## 📁 Project Structure

```
backend_py/
├── ROADMAP.md                  # V3 architecture specification (613 lines)
├── V3_IMPLEMENTATION.md        # Implementation guide (321 lines)
├── V3_QUICKSTART.md           # This file
├── test_db_connection.py      # Database validation script
├── .env.example               # Environment configuration template
│
├── db/
│   └── init.sql               # PostgreSQL schema (375 lines)
│
└── v3/                        # V3 core modules
    ├── __init__.py
    ├── config.py              # Configuration management
    ├── models.py              # Data models & enums (400+ lines)
    ├── db.py                  # Database layer (450+ lines)
    ├── diff_engine.py         # Diff computation (M3)
    └── audit.py               # Audit framework (M5 partial)
```

---

## 🎯 Next Steps

### Option A: Complete M4 (Solver Wrapper)
**Goal**: Integrate existing V2 solver with versioning layer

**Required**:
1. Create `v3/solver_wrapper.py`
2. Wrap `run_block_heuristic.py` results
3. Store assignments + KPIs in database
4. Compute output_hash for reproducibility

**Effort**: 2-3 hours

---

### Option B: Complete M1 (Parser)
**Goal**: Whitelist-based tour parsing

**Required**:
1. Collect 50+ real Slack message examples
2. Define grammar (regex or EBNF)
3. Create `v3/parser.py` with PASS/WARN/FAIL logic
4. Write 20+ test cases

**Effort**: 4-6 hours

---

### Option C: Build Streamlit UI
**Goal**: 4-tab dispatcher cockpit

**Required**:
1. Create `streamlit_app.py`
2. Implement 4 tabs (Parser, Diff, Preview, Release)
3. Connect to Postgres
4. Reuse `final_schedule_matrix.html` for preview

**Effort**: 6-8 hours

---

## 🐛 Troubleshooting

### Database Connection Failed

```bash
# Check if Postgres is running
docker ps | grep solvereign-db

# Check logs
docker logs solvereign-db

# Restart database
docker-compose restart postgres
```

### Import Errors

```bash
# Install missing dependencies
pip install 'psycopg[binary]' python-dotenv

# Verify installation
python -c "import psycopg; print(psycopg.__version__)"
```

### Test Script Fails

```bash
# Ensure you're in project root
cd shift-optimizer

# Run test with full path
python backend_py/test_db_connection.py
```

---

## 📖 Additional Resources

- **Full Architecture**: [ROADMAP.md](ROADMAP.md)
- **Implementation Details**: [V3_IMPLEMENTATION.md](V3_IMPLEMENTATION.md)
- **Database Schema**: [db/init.sql](db/init.sql)
- **V2 Solver** (still operational): `run_block_heuristic.py`

---

## 🎓 Key Concepts

### Forecast Version
- Input snapshot (Slack text, CSV, manual entry)
- Immutable after creation
- Status: PASS/WARN/FAIL
- Identified by `input_hash` (SHA256 of canonical input)

### Plan Version
- Solver output for a forecast version
- Lifecycle: DRAFT → LOCKED → SUPERSEDED
- Identified by `output_hash` for reproducibility
- LOCKED plans cannot be modified (database enforced)

### Diff Engine
- Matches tours by `tour_fingerprint`
- Classifies changes: ADDED/REMOVED/CHANGED
- Results cached in `diff_results` table

### Audit Framework
- Automated validation checks
- Mandatory gates: Coverage, Overlap, Rest, Span
- Soft KPIs: Block mix, PT ratio, peak fleet
- Results stored in `audit_log` (write-only)

### Freeze Windows
- Operational stability rules
- Default: 12h before shift start
- Prevents last-minute plan changes
- Behavior: FROZEN or OVERRIDE_REQUIRED

---

**Last Updated**: 2026-01-04
**Status**: Core infrastructure complete, ready for M1/M4/UI development
