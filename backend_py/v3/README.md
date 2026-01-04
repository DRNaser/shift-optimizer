# SOLVEREIGN V3 Core Modules

> **Version**: 3.0.0-mvp
> **Status**: Core infrastructure complete ✅
> **Date**: 2026-01-04

---

## 📚 Module Overview

This directory contains the core V3 architecture modules for SOLVEREIGN.

### Modules

| Module | Lines | Purpose | Status |
|--------|-------|---------|--------|
| [config.py](config.py) | 160 | Environment-based configuration | ✅ Complete |
| [models.py](models.py) | 430 | Data models, enums, utilities | ✅ Complete |
| [db.py](db.py) | 450 | Database layer (Postgres) | ✅ Complete |
| [diff_engine.py](diff_engine.py) | 280 | Diff computation (M3) | ✅ Complete |
| [audit.py](audit.py) | 380 | Audit framework (M5 partial) | 🔄 3/6 checks |

**Total**: ~1,700 lines of production Python code

---

## 🚀 Quick Start

### Import V3 Modules

```python
# Configuration
from backend_py.v3.config import config
print(config.SOLVER_SEED)  # 94

# Database operations
from backend_py.v3 import db

# Create forecast version
forecast_id = db.create_forecast_version(
    source="manual",
    input_hash="example_hash",
    parser_config_hash="v3.0.0",
    status="PASS"
)

# Models and utilities
from backend_py.v3 import models

fingerprint = models.compute_tour_fingerprint(
    day=1,
    start=models.time(6, 0),
    end=models.time(14, 0)
)

# Diff engine
from backend_py.v3.diff_engine import compute_diff

diff = compute_diff(forecast_old=1, forecast_new=2)
print(f"Changes: {diff.total_changes()}")

# Audit framework
from backend_py.v3.audit import audit_plan

results = audit_plan(plan_version_id=123)
if results["all_passed"]:
    print("Ready for release!")
```

---

## 📖 Module Documentation

### config.py - Configuration Management

**Purpose**: Environment-based configuration with validation

**Key Features**:
- Environment variable support (`.env` files via python-dotenv)
- Feature flags for gradual rollout
- Production safety validation
- Singleton pattern

**Usage**:
```python
from v3.config import config

# Access settings
db_url = config.DATABASE_URL
seed = config.SOLVER_SEED
freeze_window = config.FREEZE_WINDOW_MINUTES

# Validate configuration
warnings = config.validate()
if warnings:
    for warning in warnings:
        print(f"⚠️ {warning}")
```

**Environment Variables**: See [../.env.example](../.env.example)

---

### models.py - Data Models

**Purpose**: Type-safe data structures for V3 architecture

**Key Components**:

#### Enums
```python
from v3.models import (
    ForecastStatus,  # PASS, WARN, FAIL
    ParseStatus,     # PASS, WARN, FAIL
    PlanStatus,      # DRAFT, LOCKED, SUPERSEDED
    DiffType,        # ADDED, REMOVED, CHANGED
    AuditCheckName,  # COVERAGE, OVERLAP, REST, etc.
    AuditStatus      # PASS, FAIL
)
```

#### Dataclasses
```python
from v3.models import (
    ForecastVersion,
    TourNormalized,
    PlanVersion,
    Assignment,
    AuditLog,
    DiffSummary,
    TourDiff
)
```

#### Utilities
```python
from v3.models import (
    compute_tour_fingerprint,  # Stable tour identity
    compute_input_hash,        # Input deduplication
    compute_output_hash        # Reproducibility testing
)
```

---

### db.py - Database Layer

**Purpose**: Postgres connection and CRUD operations

**Key Features**:
- Context-managed connections
- Type-safe operations
- Transaction support
- Release gate checking

**Usage**:
```python
from v3.db import (
    # Connection
    get_connection,
    test_connection,

    # Forecast versions
    create_forecast_version,
    get_forecast_version,
    get_latest_forecast_version,

    # Tours
    create_tour_normalized,
    get_tours_normalized,

    # Plans
    create_plan_version,
    get_plan_version,
    lock_plan_version,

    # Assignments
    create_assignment,
    get_assignments,

    # Audits
    create_audit_log,
    get_audit_logs,
    can_release
)

# Example: Context-managed connection
from v3.db import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM forecast_versions")
        results = cur.fetchall()
```

---

### diff_engine.py - Diff Computation (M3)

**Purpose**: Compute deterministic diffs between forecast versions

**Key Features**:
- Fingerprint-based tour matching
- Change classification (ADDED/REMOVED/CHANGED)
- Diff result caching
- JSON export

**Usage**:
```python
from v3.diff_engine import compute_diff, get_diff_json

# Compute diff
diff = compute_diff(
    forecast_version_old=47,
    forecast_version_new=48,
    use_cache=True  # Use cached results if available
)

print(f"Added: {diff.added}")
print(f"Removed: {diff.removed}")
print(f"Changed: {diff.changed}")

# Get JSON representation
diff_json = get_diff_json(47, 48)
# Returns: {forecast_version_old, forecast_version_new, summary, details}
```

**Diff Classification**:
- **ADDED**: New tour in forecast_version_new
- **REMOVED**: Tour in old but not in new
- **CHANGED**: Same fingerprint, different attributes (count, depot, etc.)

---

### audit.py - Audit Framework (M5)

**Purpose**: Automated validation checks for plan versions

**Implemented Checks** (3/6):
- ✅ **COVERAGE**: Every tour assigned exactly once
- ✅ **OVERLAP**: No driver works overlapping tours
- ✅ **REST**: ≥11h rest between consecutive blocks

**Pending Checks** (TODO):
- ⏳ **SPAN_REGULAR**: ≤14h span for regular blocks
- ⏳ **SPAN_SPLIT**: ≤16h span + 360min break for splits
- ⏳ **REPRODUCIBILITY**: Same inputs → same outputs
- ⏳ **FATIGUE**: No consecutive triple shifts (3er→3er)

**Usage**:
```python
from v3.audit import audit_plan, can_release_plan

# Run all enabled checks
results = audit_plan(
    plan_version_id=123,
    save_to_db=True  # Store results in audit_log
)

# Check results
if results["all_passed"]:
    print("✅ All checks passed!")
else:
    print(f"❌ {results['checks_failed']} checks failed")
    for check_name, result in results["results"].items():
        if result["status"] == "FAIL":
            print(f"   - {check_name}: {result['violation_count']} violations")

# Check release gates
can_release, blocking = can_release_plan(123)
if can_release:
    print("Ready for release!")
else:
    print(f"Blocked by: {blocking}")
```

---

## 🧪 Testing

### Unit Tests (Per Module)
```bash
# Test database connection
python -c "from backend_py.v3.db import test_connection; print(test_connection())"

# Test configuration
python -c "from backend_py.v3.config import config; print(config.validate())"

# Test models
python -c "from backend_py.v3.models import compute_tour_fingerprint; print(compute_tour_fingerprint(1, '06:00', '14:00'))"
```

### Integration Tests
```bash
# Run full integration test suite
python backend_py/test_v3_integration.py

# Expected output:
# ✅ ALL INTEGRATION TESTS PASSED!
```

### Database Validation
```bash
# Comprehensive database test
python backend_py/test_db_connection.py

# Expected output:
# ✅ ALL TESTS PASSED!
```

---

## 🔧 Development

### Adding New Modules

1. Create module in `backend_py/v3/`
2. Add imports to `__init__.py`
3. Update this README
4. Write tests

### Code Style
- Type hints for all function signatures
- Docstrings for all public functions
- Google-style docstring format
- Maximum line length: 100 characters

### Dependencies
```bash
# Core (required)
pip install 'psycopg[binary]'

# Optional
pip install python-dotenv  # For .env file support
```

---

## 📋 Roadmap

### Completed (V3 MVP)
- [x] Configuration module
- [x] Data models
- [x] Database layer
- [x] Diff engine (M3)
- [x] Audit framework (3/6 checks)

### Pending
- [ ] M1: Parser module (`parser.py`)
- [ ] M4: Solver wrapper (`solver_wrapper.py`)
- [ ] M5: Complete audit checks (3 remaining)
- [ ] Release mechanism (`release.py`)
- [ ] Streamlit UI integration

---

## 🐛 Troubleshooting

### Import Errors
```bash
# Ensure you're in project root
cd shift-optimizer

# Python path should include backend_py
export PYTHONPATH="${PYTHONPATH}:$(pwd)/backend_py"

# Or use absolute imports
python -c "from backend_py.v3 import db"
```

### Database Connection Errors
```bash
# Check if Postgres is running
docker ps | grep solvereign-db

# Restart database
docker-compose restart postgres

# Check logs
docker logs solvereign-db
```

### Configuration Issues
```bash
# Check environment variables
python -c "from backend_py.v3.config import config; print(config.validate())"

# Create .env file from template
cp backend_py/.env.example backend_py/.env
# Edit .env with your values
```

---

## 📚 Additional Resources

- **Architecture Specification**: [../ROADMAP.md](../ROADMAP.md)
- **Implementation Guide**: [../V3_IMPLEMENTATION.md](../V3_IMPLEMENTATION.md)
- **Quick Start Guide**: [../V3_QUICKSTART.md](../V3_QUICKSTART.md)
- **Database Schema**: [../db/init.sql](../db/init.sql)

---

## 📞 Support

For questions or issues:
1. Check [V3_QUICKSTART.md](../V3_QUICKSTART.md) for common scenarios
2. Review [ROADMAP.md](../ROADMAP.md) for architecture details
3. Run `python backend_py/test_v3_integration.py` to verify setup

---

**Last Updated**: 2026-01-04
**Module Version**: 3.0.0-mvp
**Status**: Production-ready for M1/M4/UI development
