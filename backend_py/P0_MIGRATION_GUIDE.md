# P0 Migration Guide: Tour Instances Fix

## Overview

This migration fixes critical P0 blockers in the V3 architecture related to template vs instances data model inconsistency.

## P0 Blockers Fixed

### 1. Template vs Instances (CRITICAL)

**Problem:**
```
tours_normalized: id=1, count=3 (template)
assignments: tour_id=1 (only 1 row possible due to UNIQUE constraint)

❌ How are 3 drivers covered? Coverage check logically broken!
```

**Solution:**
```
tours_normalized: id=1, count=3 (template - defines WHAT tours exist)
tour_instances: (1,1), (1,2), (1,3) (instances - 3 separate rows)
assignments: tour_instance_id=1, tour_instance_id=2, tour_instance_id=3

✅ 1:1 mapping between instances and assignments
```

### 2. Cross-Midnight Time Model

**Problem:**
```sql
tours_normalized:
  start_ts TIME,  -- "22:00:00"
  end_ts TIME     -- "06:00:00"

❌ Unclear if this crosses midnight!
❌ Rest/Overlap/Span checks fehleranfällig (error-prone)
```

**Solution:**
```sql
tour_instances:
  start_ts TIME,
  end_ts TIME,
  crosses_midnight BOOLEAN  -- Explicit flag!

✅ Clear semantics for cross-midnight tours
✅ Reliable audit checks
```

### 3. LOCKED Immutability Incomplete

**Problem:**
```
LOCKED plan only protected plan_versions table.
assignments and audit_log could be modified after LOCK!

❌ Data integrity violation
```

**Solution:**
```sql
-- Trigger prevents modifications to assignments for LOCKED plans
CREATE TRIGGER prevent_locked_assignments
BEFORE INSERT OR UPDATE OR DELETE ON assignments
FOR EACH ROW
EXECUTE FUNCTION prevent_locked_plan_data_modification();

-- Trigger prevents UPDATE/DELETE on audit_log for LOCKED plans
-- (INSERT still allowed - append-only)
CREATE TRIGGER prevent_audit_log_modification_trigger
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_log_modification();

✅ Complete immutability enforcement
```

## Migration Steps

### Step 1: Apply Database Migration

```bash
# Start PostgreSQL
docker-compose up -d postgres

# Apply migration 001
docker exec -i solvereign-db psql -U solvereign -d solvereign < backend_py/db/migrations/001_tour_instances.sql
```

**What this does:**
1. Creates `tour_instances` table with:
   - `tour_template_id` → references `tours_normalized.id`
   - `instance_number` → 1, 2, 3 for count=3
   - `crosses_midnight` → explicit boolean flag
   - Denormalized tour data for performance

2. Creates `expand_tour_instances()` function to auto-expand templates

3. Modifies `assignments` table:
   - Renames `tour_id` → `tour_id_DEPRECATED`
   - Adds `tour_instance_id` → references `tour_instances.id`
   - Updates UNIQUE constraint

4. Adds LOCKED immutability triggers for `assignments` and `audit_log`

### Step 2: Update Application Code

Replace broken modules with fixed versions:

```bash
# Backup old modules
mv backend_py/v3/audit.py backend_py/v3/audit_OLD.py

# Use fixed modules
cp backend_py/v3/audit_fixed.py backend_py/v3/audit.py
```

Update imports:
```python
# OLD (BROKEN)
from v3.db import create_assignment, get_assignments
from v3.audit import audit_plan

# NEW (FIXED)
from v3.db_instances import create_assignment_fixed, get_assignments_with_instances
from v3.audit_fixed import audit_plan_fixed
```

### Step 3: Expand Existing Tours to Instances

For each existing forecast version:

```python
from v3.db_instances import expand_tour_template

# Expand all tours in forecast version 123
instances_created = expand_tour_template(forecast_version_id=123)
print(f"Created {instances_created} tour instances")
```

### Step 4: Verify Migration

Run the migration test suite:

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

## API Changes

### Creating Assignments

**OLD (BROKEN):**
```python
from v3.db import create_assignment

assignment_id = create_assignment(
    plan_version_id=plan_id,
    driver_id="D001",
    tour_id=tour_id,  # ❌ References template (count=3)
    day=1,
    block_id="D1_B1"
)
```

**NEW (FIXED):**
```python
from v3.db_instances import create_assignment_fixed

assignment_id = create_assignment_fixed(
    plan_version_id=plan_id,
    driver_id="D001",
    tour_instance_id=instance_id,  # ✅ References specific instance
    day=1,
    block_id="D1_B1"
)
```

### Coverage Check

**OLD (BROKEN):**
```python
from v3.audit import CoverageCheck

check = CoverageCheck(plan_id)
status, count, details = check.run()
# ❌ Compares tours_normalized.count vs COUNT(assignments) - wrong logic!
```

**NEW (FIXED):**
```python
from v3.db_instances import check_coverage_fixed

result = check_coverage_fixed(plan_id)
# ✅ Compares tour_instances (1:1) vs assignments - correct logic!
```

### Audit Framework

**OLD (BROKEN):**
```python
from v3.audit import audit_plan

results = audit_plan(plan_id)
# ❌ Uses broken coverage/overlap/rest checks
```

**NEW (FIXED):**
```python
from v3.audit_fixed import audit_plan_fixed

results = audit_plan_fixed(plan_id)
# ✅ Uses fixed checks with tour_instances
```

## Database Schema Changes

### New Table: `tour_instances`

```sql
CREATE TABLE tour_instances (
    id                  SERIAL PRIMARY KEY,
    tour_template_id    INTEGER NOT NULL REFERENCES tours_normalized(id),
    instance_number     INTEGER NOT NULL CHECK (instance_number > 0),
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id),

    -- Denormalized tour data
    day                 INTEGER NOT NULL,
    start_ts            TIME NOT NULL,
    end_ts              TIME NOT NULL,
    crosses_midnight    BOOLEAN DEFAULT FALSE,  -- NEW!
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
```

### Modified Table: `assignments`

```sql
-- BEFORE
CREATE TABLE assignments (
    tour_id INTEGER NOT NULL REFERENCES tours_normalized(id),  -- ❌ Template
    CONSTRAINT assignments_unique_tour_assignment
        UNIQUE (plan_version_id, tour_id)  -- ❌ Only 1 assignment per template!
);

-- AFTER
CREATE TABLE assignments (
    tour_id_DEPRECATED INTEGER,  -- Renamed, no longer used
    tour_instance_id INTEGER REFERENCES tour_instances(id),  -- ✅ Instance
    CONSTRAINT assignments_unique_instance_assignment
        UNIQUE (plan_version_id, tour_instance_id)  -- ✅ 1:1 instance mapping
);
```

## Data Flow

### Before Migration (BROKEN):

```
1. Parser creates tours_normalized (count=3)
   ↓
2. Solver assigns tour_id to driver
   ↓
3. ❌ PROBLEM: How to assign 3 drivers to same tour_id?
   ↓
4. ❌ Coverage check: Expected 3, got 1
```

### After Migration (FIXED):

```
1. Parser creates tours_normalized (count=3, template)
   ↓
2. expand_tour_instances() creates 3 tour_instances
   ↓
3. Solver assigns tour_instance_id to driver (1:1 mapping)
   ↓
4. ✅ Coverage check: Expected 3, got 3
```

## Rollback Plan

If migration fails:

```sql
-- 1. Drop new structures
DROP TRIGGER IF EXISTS prevent_locked_assignments ON assignments;
DROP TRIGGER IF EXISTS prevent_audit_log_modification_trigger ON audit_log;
DROP TABLE IF EXISTS tour_instances CASCADE;

-- 2. Restore assignments table
ALTER TABLE assignments DROP COLUMN tour_instance_id;
ALTER TABLE assignments RENAME COLUMN tour_id_DEPRECATED TO tour_id;
ALTER TABLE assignments ADD CONSTRAINT assignments_tour_id_fkey
    FOREIGN KEY (tour_id) REFERENCES tours_normalized(id);

-- 3. Revert to old application code
mv backend_py/v3/audit_OLD.py backend_py/v3/audit.py
```

## Testing Checklist

- [ ] Migration 001 applied successfully
- [ ] `tour_instances` table created
- [ ] `expand_tour_instances()` function works
- [ ] `assignments.tour_instance_id` column exists
- [ ] LOCKED plan triggers prevent modifications
- [ ] Fixed coverage check passes
- [ ] Fixed overlap check passes
- [ ] Fixed rest check passes
- [ ] Integration tests pass

## FAQ

### Q: Do I need to migrate existing data?

**A:** Yes, for each existing forecast version, run:
```python
expand_tour_template(forecast_version_id)
```

### Q: What happens to old assignments?

**A:** Old assignments using `tour_id` are deprecated. The column is renamed to `tour_id_DEPRECATED`. New assignments must use `tour_instance_id`.

### Q: Can I still use tours_normalized?

**A:** Yes! `tours_normalized` is now a **template** table. It defines WHAT tours exist (count=3). The new `tour_instances` table expands templates into individual instances.

### Q: How do I query assignments now?

**A:** Use the fixed functions:
```python
# Get enriched assignments with tour instance data
from v3.db_instances import get_assignments_with_instances

assignments = get_assignments_with_instances(plan_id)
# Returns assignments JOINed with tour_instances
```

### Q: What about cross-midnight tours?

**A:** Use the explicit `crosses_midnight` boolean flag:
```python
# Tour 22:00 → 06:00 (crosses midnight)
instance = {
    "start_ts": "22:00:00",
    "end_ts": "06:00:00",
    "crosses_midnight": True  # Explicit!
}
```

## Support

For issues or questions:
1. Check test output: `python backend_py/test_p0_migration.py`
2. Review migration logs
3. Verify database schema: `\d tour_instances` in psql
4. Check application logs for errors

## Next Steps After Migration

1. **P1: Quickstart Guide Fixes**
   - Consistent docker-compose service names
   - Reliable health checks
   - Minimal .env setup

2. **P2: Complete Remaining Audit Checks**
   - SpanRegularCheck (≤14h for regular blocks)
   - SpanSplitCheck (≤16h + 360min break)
   - ReproducibilityCheck (output_hash matching)
   - FatigueCheck (no 3er→3er consecutive triples)

3. **M4: Solver Wrapper**
   - Integration with block heuristic solver
   - Deterministic execution (seed=94)
   - Output hash generation

4. **M1: Parser**
   - Excel/CSV ingestion
   - Whitelist validation
   - Fingerprint generation

5. **Streamlit UI**
   - 4-tab interface
   - Diff visualization
   - Audit dashboard
   - Release workflow
