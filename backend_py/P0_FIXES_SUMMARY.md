# P0 Fixes Summary

## Status: IMPLEMENTATION COMPLETE ✅

All P0 blockers identified in user feedback have been fixed.

## Files Created

### 1. Database Migration
- **[001_tour_instances.sql](db/migrations/001_tour_instances.sql)** (154 lines)
  - Creates `tour_instances` table
  - Adds `crosses_midnight` BOOLEAN field
  - Creates `expand_tour_instances()` function
  - Modifies `assignments` table (tour_id → tour_instance_id)
  - Adds LOCKED immutability triggers

### 2. Fixed Database Operations
- **[db_instances.py](v3/db_instances.py)** (194 lines)
  - `expand_tour_template()` - Auto-expand templates to instances
  - `get_tour_instances()` - Query instances
  - `create_assignment_fixed()` - Uses tour_instance_id
  - `get_assignments_with_instances()` - JOIN with instance data
  - `check_coverage_fixed()` - 1:1 instance mapping

### 3. Fixed Audit Framework
- **[audit_fixed.py](v3/audit_fixed.py)** (420 lines)
  - `CoverageCheckFixed` - Uses tour_instances
  - `OverlapCheckFixed` - Cross-midnight support
  - `RestCheckFixed` - Cross-midnight rest calculation
  - `AuditFrameworkFixed` - Orchestrator
  - `audit_plan_fixed()` - Convenience function

### 4. Test Suite
- **[test_p0_migration.py](test_p0_migration.py)** (450 lines)
  - 6 comprehensive tests
  - Migration verification
  - Instance expansion validation
  - Coverage check validation
  - Audit framework validation
  - LOCKED immutability verification

### 5. Documentation
- **[P0_MIGRATION_GUIDE.md](P0_MIGRATION_GUIDE.md)** (400+ lines)
  - Complete migration instructions
  - API changes documentation
  - Data flow diagrams
  - Rollback plan
  - FAQ section

- **This file** (P0_FIXES_SUMMARY.md)

## P0 Blockers Fixed

### ✅ P0-1: Template vs Instances

**Problem:**
```
tours_normalized.count=3 but assignments only references tour_id once
→ Coverage/Diff/Audit logically broken
```

**Solution:**
- Created `tour_instances` table (1 row per driver needed)
- Changed assignments: `tour_id` → `tour_instance_id`
- Auto-expand function: `expand_tour_instances(forecast_version_id)`

**Files:**
- `db/migrations/001_tour_instances.sql:9-31` (table definition)
- `db/migrations/001_tour_instances.sql:42-77` (expand function)
- `v3/db_instances.py:35-50` (Python wrapper)

### ✅ P0-2: Cross-Midnight Time Model

**Problem:**
```
Felder heißen *_ts, du gibst aber nur 'HH:MM:SS' ohne Datum
→ Rest/Overlap/Sun→Mon/cross-midnight wird fehleranfällig
```

**Solution:**
- Added `crosses_midnight BOOLEAN` field to `tour_instances`
- Explicit flag calculated during expansion: `end_ts < start_ts`
- Updated audit checks to handle cross-midnight correctly

**Files:**
- `db/migrations/001_tour_instances.sql:19` (field definition)
- `db/migrations/001_tour_instances.sql:56` (calculation logic)
- `v3/audit_fixed.py:152-179` (overlap check with cross-midnight)
- `v3/audit_fixed.py:285-308` (rest check with cross-midnight)

### ✅ P0-3: LOCKED Immutability Incomplete

**Problem:**
```
LOCKED-Immutability muss alle relevanten Tabellen abdecken:
nicht nur plan_versions, sondern auch assignments + audit_log
```

**Solution:**
- Added trigger: `prevent_locked_assignments` on assignments table
- Added trigger: `prevent_audit_log_modification_trigger` on audit_log
- Audit log remains append-only (INSERT allowed, UPDATE/DELETE blocked)

**Files:**
- `db/migrations/001_tour_instances.sql:98-116` (assignments trigger)
- `db/migrations/001_tour_instances.sql:121-144` (audit_log trigger)
- `test_p0_migration.py:276-327` (immutability tests)

## Technical Changes

### Database Schema

```sql
-- NEW TABLE: tour_instances
CREATE TABLE tour_instances (
    id                  SERIAL PRIMARY KEY,
    tour_template_id    INTEGER NOT NULL REFERENCES tours_normalized(id),
    instance_number     INTEGER NOT NULL,  -- 1, 2, 3 for count=3
    forecast_version_id INTEGER NOT NULL,

    -- Denormalized tour data
    day                 INTEGER NOT NULL,
    start_ts            TIME NOT NULL,
    end_ts              TIME NOT NULL,
    crosses_midnight    BOOLEAN DEFAULT FALSE,  -- ✅ P0 FIX
    duration_min        INTEGER NOT NULL,
    work_hours          DECIMAL(5,2) NOT NULL,
    depot               VARCHAR(50),
    skill               VARCHAR(50),

    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_template_instance
        UNIQUE (tour_template_id, instance_number),
    CONSTRAINT unique_forecast_instance
        UNIQUE (forecast_version_id, tour_template_id, instance_number)
);

-- MODIFIED TABLE: assignments
ALTER TABLE assignments RENAME COLUMN tour_id TO tour_id_DEPRECATED;
ALTER TABLE assignments ADD COLUMN tour_instance_id INTEGER;
ALTER TABLE assignments ADD CONSTRAINT fk_tour_instance
    FOREIGN KEY (tour_instance_id) REFERENCES tour_instances(id);
ALTER TABLE assignments ADD CONSTRAINT assignments_unique_instance_assignment
    UNIQUE (plan_version_id, tour_instance_id);  -- ✅ 1:1 mapping
```

### Data Flow

**BEFORE (BROKEN):**
```
Parser → tours_normalized (count=3, template)
            ↓
         Solver → assignments (tour_id=1, only 1 row possible)
            ↓
         ❌ Coverage check: Expected 3, got 1
```

**AFTER (FIXED):**
```
Parser → tours_normalized (count=3, template)
            ↓
         expand_tour_instances() → tour_instances (3 rows: 1,2,3)
            ↓
         Solver → assignments (tour_instance_id=1/2/3, 3 rows)
            ↓
         ✅ Coverage check: Expected 3, got 3
```

### API Changes

| Operation | OLD (BROKEN) | NEW (FIXED) |
|-----------|--------------|-------------|
| Create assignment | `create_assignment(tour_id=1)` | `create_assignment_fixed(tour_instance_id=1)` |
| Get assignments | `get_assignments(plan_id)` | `get_assignments_with_instances(plan_id)` |
| Coverage check | `CoverageCheck(plan_id).run()` | `check_coverage_fixed(plan_id)` |
| Audit plan | `audit_plan(plan_id)` | `audit_plan_fixed(plan_id)` |

## Migration Instructions

### Step 1: Apply Migration
```bash
docker-compose up -d postgres
docker exec -i solvereign-db psql -U solvereign -d solvereign < backend_py/db/migrations/001_tour_instances.sql
```

### Step 2: Expand Existing Tours
```python
from v3.db_instances import expand_tour_template

# For each forecast version
expand_tour_template(forecast_version_id=123)
```

### Step 3: Update Application Code
```python
# Replace imports
from v3.db_instances import (
    create_assignment_fixed,
    get_assignments_with_instances,
    check_coverage_fixed
)
from v3.audit_fixed import audit_plan_fixed
```

### Step 4: Verify
```bash
python backend_py/test_p0_migration.py
```

Expected output:
```
SUCCESS: ALL 6 P0 TESTS PASSED!

P0 Blockers FIXED:
   [OK] Template vs Instances: tour_instances table working
   [OK] Coverage Check: 1:1 instance mapping validated
   [OK] LOCKED Immutability: assignments protected
   [OK] Cross-midnight: crosses_midnight field implemented
```

## Testing Coverage

### Test Suite: test_p0_migration.py

1. **test_migration_applied()** - Verifies:
   - `tour_instances` table exists
   - `expand_tour_instances()` function exists
   - `assignments.tour_instance_id` column exists

2. **test_tour_instance_expansion()** - Verifies:
   - Tours expand to correct instance count
   - Instance numbers are sequential (1, 2, 3)
   - Denormalized data is correct

3. **test_fixed_assignments()** - Verifies:
   - Assignments use `tour_instance_id`
   - 1:1 mapping between instances and assignments

4. **test_fixed_coverage_check()** - Verifies:
   - Coverage check uses instances (not templates)
   - 100% coverage detected correctly
   - Missing instances detected

5. **test_fixed_audit_framework()** - Verifies:
   - All audit checks pass
   - Coverage/Overlap/Rest use tour_instances
   - Cross-midnight handling works

6. **test_locked_immutability()** - Verifies:
   - LOCKED plans prevent assignment modifications
   - Audit log remains append-only
   - Triggers work correctly

## Code Metrics

| File | Lines | Purpose |
|------|-------|---------|
| 001_tour_instances.sql | 154 | Database migration |
| db_instances.py | 194 | Fixed DB operations |
| audit_fixed.py | 420 | Fixed audit checks |
| test_p0_migration.py | 450 | Test suite |
| P0_MIGRATION_GUIDE.md | 400+ | Documentation |
| **TOTAL** | **1,618+** | **Complete P0 fix** |

## Breaking Changes

### ⚠️ assignments.tour_id → assignments.tour_instance_id

**Impact:** High - All solver code must be updated

**Migration:**
- Old assignments using `tour_id` are deprecated
- Column renamed to `tour_id_DEPRECATED`
- New code MUST use `tour_instance_id`

### ⚠️ Coverage logic changed

**Impact:** Medium - Audit checks use different logic

**Migration:**
- Old: Compare `tours_normalized.count` vs `COUNT(assignments)`
- New: Compare `tour_instances` vs `assignments` (1:1)

### ⚠️ API changes

**Impact:** Medium - Import paths changed

**Migration:**
```python
# OLD
from v3.db import create_assignment
from v3.audit import audit_plan

# NEW
from v3.db_instances import create_assignment_fixed
from v3.audit_fixed import audit_plan_fixed
```

## Benefits

### 1. Correct Coverage Checking
- ✅ 1:1 mapping between instances and assignments
- ✅ No more count vs assignments mismatch
- ✅ Accurate coverage reporting

### 2. Explicit Cross-Midnight Handling
- ✅ `crosses_midnight` boolean flag
- ✅ Reliable rest period calculations
- ✅ Correct overlap detection

### 3. Complete Immutability
- ✅ LOCKED plans protect assignments
- ✅ Audit log append-only
- ✅ Data integrity guaranteed

### 4. Better Performance
- ✅ Denormalized tour data in instances
- ✅ No JOIN needed for basic queries
- ✅ Indexed on day, template, forecast

## Limitations

### Known Issues
- [ ] Old assignments (using `tour_id`) must be migrated manually
- [ ] Requires database migration (not backward compatible)
- [ ] Breaking API changes (import paths)

### Future Work
- [ ] Implement remaining audit checks (SPAN, REPRODUCIBILITY, FATIGUE)
- [ ] Add migration script for existing assignments
- [ ] Update Streamlit UI to show instance details
- [ ] Add instance-level reporting/exports

## Conclusion

All P0 blockers have been **completely fixed**:

1. ✅ **Template vs Instances**: tour_instances table provides 1:1 mapping
2. ✅ **Cross-Midnight Time Model**: Explicit crosses_midnight boolean flag
3. ✅ **LOCKED Immutability**: Triggers protect assignments and audit_log

**Next Priority: P1 Tasks**
- Quickstart guide fixes
- Docker health checks
- Minimal .env setup

**Ready for:** Integration testing, V2 solver integration, Streamlit UI development
