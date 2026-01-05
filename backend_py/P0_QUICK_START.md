# P0 Fixes - Quick Start Guide

## Apply Migration (Windows)

```batch
# Run the migration script
backend_py\apply_p0_migration.bat
```

**Or manually:**
```batch
# 1. Start PostgreSQL
docker-compose up -d postgres

# 2. Apply migration
docker exec -i solvereign-db psql -U solvereign -d solvereign < backend_py\db\migrations\001_tour_instances.sql

# 3. Verify
docker exec solvereign-db psql -U solvereign -d solvereign -c "\d tour_instances"
```

## Apply Migration (Linux/Mac)

```bash
# Run the migration script
chmod +x backend_py/apply_p0_migration.sh
backend_py/apply_p0_migration.sh
```

**Or manually:**
```bash
# 1. Start PostgreSQL
docker-compose up -d postgres

# 2. Apply migration
docker exec -i solvereign-db psql -U solvereign -d solvereign < backend_py/db/migrations/001_tour_instances.sql

# 3. Verify
docker exec solvereign-db psql -U solvereign -d solvereign -c "\d tour_instances"
```

## Run Tests

```bash
# Test without database
python backend_py/test_v3_without_db.py

# Test with database (requires migration applied)
python backend_py/test_p0_migration.py
```

## What Was Fixed?

### 1. Template vs Instances ✅
**Before:** `tours_normalized.count=3` but only 1 assignment possible
**After:** 3 separate `tour_instances` (1:1 with assignments)

### 2. Cross-Midnight ✅
**Before:** Unclear if tour 22:00→06:00 crosses midnight
**After:** Explicit `crosses_midnight` boolean flag

### 3. LOCKED Immutability ✅
**Before:** Only `plan_versions` protected
**After:** `assignments` and `audit_log` also protected

## Files Overview

| File | Purpose | Lines |
|------|---------|-------|
| [001_tour_instances.sql](db/migrations/001_tour_instances.sql) | Database migration | 154 |
| [db_instances.py](v3/db_instances.py) | Fixed DB operations | 194 |
| [audit_fixed.py](v3/audit_fixed.py) | Fixed audit checks | 420 |
| [test_p0_migration.py](test_p0_migration.py) | Test suite | 450 |
| [P0_MIGRATION_GUIDE.md](P0_MIGRATION_GUIDE.md) | Full documentation | 400+ |

## Quick Test

After applying migration:

```python
# Expand tours to instances
from v3.db_instances import expand_tour_template
instances_created = expand_tour_template(forecast_version_id=1)
print(f"Created {instances_created} instances")

# Check coverage
from v3.db_instances import check_coverage_fixed
result = check_coverage_fixed(plan_version_id=1)
print(f"Coverage: {result['status']}")
```

## Next Steps

1. **P1 Tasks**: Quickstart guide fixes, Docker health checks
2. **M4**: Solver wrapper integration
3. **M1**: Parser with whitelist validation
4. **UI**: Streamlit 4-tab interface

## Troubleshooting

### Migration fails with "relation already exists"
```sql
-- Check if already applied
docker exec solvereign-db psql -U solvereign -d solvereign -c "\d tour_instances"

-- If exists, migration already applied (OK)
```

### Cannot connect to database
```bash
# Check if PostgreSQL is running
docker ps | grep solvereign-db

# Check logs
docker logs solvereign-db

# Restart
docker-compose restart postgres
```

### Tests fail
```bash
# Ensure migration applied first
python backend_py/test_p0_migration.py

# Check database
docker exec solvereign-db psql -U solvereign -d solvereign -c "SELECT COUNT(*) FROM tour_instances;"
```

## Documentation

- **Full Guide**: [P0_MIGRATION_GUIDE.md](P0_MIGRATION_GUIDE.md)
- **Summary**: [P0_FIXES_SUMMARY.md](P0_FIXES_SUMMARY.md)
- **Roadmap**: [ROADMAP.md](ROADMAP.md) (updated with P0 status)

## Status

✅ **P0 Implementation**: COMPLETE
✅ **Code**: 1,618+ lines
✅ **Tests**: 6 comprehensive tests
✅ **Documentation**: 3 detailed guides

**Ready for deployment!**
