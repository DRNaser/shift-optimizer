# Migration Rules

> **Purpose**: Database migration procedures and validation
> **Last Updated**: 2026-01-07

---

## MIGRATION PRINCIPLES

1. **Backwards Compatible**: Migrations should not break existing code
2. **Reversible**: Every migration must have a rollback script
3. **Tested**: Test on staging before production
4. **Atomic**: One logical change per migration
5. **Documented**: Clear description of what and why

---

## MIGRATION FILE FORMAT

### Naming Convention

```
NNN_description.sql
```

Where:
- `NNN` = 3-digit sequential number (001, 002, ...)
- `description` = snake_case description of change

Examples:
```
023_add_policy_profiles.sql
024_add_tenant_sites_fk.sql
025_create_routing_schema.sql
```

### File Structure

```sql
-- Migration: 023_add_policy_profiles
-- Description: Add policy profiles table for pack configuration
-- Author: n.zaher
-- Date: 2026-01-07

-- ====================
-- FORWARD MIGRATION
-- ====================

-- Create table
CREATE TABLE IF NOT EXISTS core.policy_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES core.tenants(id),
    pack_id VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    config_json JSONB NOT NULL,
    config_hash VARCHAR(64) GENERATED ALWAYS AS (
        encode(sha256(config_json::text::bytea), 'hex')
    ) STORED,
    schema_version VARCHAR(20) NOT NULL DEFAULT '1.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255) NOT NULL,

    CONSTRAINT uq_policy_profile UNIQUE (tenant_id, pack_id, name, version)
);

-- Add RLS
ALTER TABLE core.policy_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.policy_profiles FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON core.policy_profiles
    USING (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Add indexes
CREATE INDEX idx_policy_profiles_tenant ON core.policy_profiles(tenant_id);
CREATE INDEX idx_policy_profiles_pack ON core.policy_profiles(pack_id);

-- ====================
-- ROLLBACK (save as 023_add_policy_profiles_rollback.sql)
-- ====================
-- DROP TABLE IF EXISTS core.policy_profiles CASCADE;
```

---

## MIGRATION CHECKLIST

### Before Writing

- [ ] Check if similar migration exists
- [ ] Identify all tables affected
- [ ] Plan rollback strategy
- [ ] Estimate execution time on production data

### Required Elements

- [ ] `tenant_id` column (if tenant-scoped)
- [ ] RLS policy (if tenant-scoped)
- [ ] Foreign keys with proper ON DELETE
- [ ] Indexes on filtered columns
- [ ] NOT NULL constraints where appropriate
- [ ] DEFAULT values where sensible
- [ ] Generated columns for hashes (if applicable)

### After Writing

- [ ] Rollback script exists
- [ ] Tested on empty database
- [ ] Tested on copy of production data
- [ ] Reviewed by another developer
- [ ] Added to migration tracker

---

## RLS REQUIREMENTS

### Every Tenant-Scoped Table MUST Have

```sql
-- 1. Enable RLS
ALTER TABLE my_table ENABLE ROW LEVEL SECURITY;
ALTER TABLE my_table FORCE ROW LEVEL SECURITY;

-- 2. Create policy
CREATE POLICY tenant_isolation ON my_table
    USING (tenant_id::text = current_setting('app.current_tenant_id', true));
```

### Exceptions

Tables that are NOT tenant-scoped:
- `core.tenants` (the tenant table itself)
- `core.used_signatures` (global dedup)
- `schema_migrations` (system table)

---

## COMMON PATTERNS

### Add Column

```sql
-- Add nullable column first
ALTER TABLE my_table ADD COLUMN new_column VARCHAR(100);

-- Backfill if needed
UPDATE my_table SET new_column = 'default_value' WHERE new_column IS NULL;

-- Then add NOT NULL if required
ALTER TABLE my_table ALTER COLUMN new_column SET NOT NULL;
```

### Add Index

```sql
-- Use CONCURRENTLY to avoid locking
CREATE INDEX CONCURRENTLY idx_my_table_column ON my_table(column);
```

### Add Foreign Key

```sql
-- With proper ON DELETE
ALTER TABLE child_table
    ADD CONSTRAINT fk_child_parent
    FOREIGN KEY (parent_id)
    REFERENCES parent_table(id)
    ON DELETE CASCADE;
```

### Create Schema

```sql
-- For new packs
CREATE SCHEMA IF NOT EXISTS routing;

-- Grant access
GRANT USAGE ON SCHEMA routing TO solvereign;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA routing TO solvereign;
```

---

## APPLYING MIGRATIONS

### Development

```bash
# Apply single migration
psql $DATABASE_URL < backend_py/db/migrations/023_add_policy_profiles.sql

# Apply all pending
for f in backend_py/db/migrations/*.sql; do
    psql $DATABASE_URL < "$f"
done
```

### Production

```bash
# 1. Backup first!
pg_dump solvereign > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Apply migration
psql $DATABASE_URL < backend_py/db/migrations/023_add_policy_profiles.sql

# 3. Verify
psql $DATABASE_URL -c "\d core.policy_profiles"

# 4. Update last-known-good.json
```

### Rollback

```bash
# Apply rollback script
psql $DATABASE_URL < backend_py/db/migrations/023_add_policy_profiles_rollback.sql
```

---

## MIGRATION TRACKING

### Schema Migrations Table

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(50) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by VARCHAR(255),
    description TEXT
);

-- Record migration
INSERT INTO schema_migrations (version, applied_by, description)
VALUES ('023_add_policy_profiles', 'deploy_script', 'Add policy profiles table');
```

### Check Applied Migrations

```sql
SELECT version, applied_at, description
FROM schema_migrations
ORDER BY version DESC
LIMIT 10;
```

---

## DANGEROUS OPERATIONS

### NEVER Do These Without Review

| Operation | Risk | Mitigation |
|-----------|------|------------|
| DROP TABLE | Data loss | Backup first, verify not in use |
| DROP COLUMN | Data loss | Verify not read anywhere |
| ALTER TYPE | Lock + potential data loss | Test thoroughly |
| DELETE without WHERE | Data loss | Always use WHERE |
| TRUNCATE | Data loss | Use DELETE with WHERE instead |

### High-Risk Migration Process

1. Create ticket with business justification
2. Get approval from data owner
3. Create backup
4. Test rollback procedure
5. Execute in maintenance window
6. Verify data integrity post-migration

---

## UPDATING LAST-KNOWN-GOOD

After successful migration:

```json
// .claude/state/last-known-good.json
{
  "git_sha": "abc123",
  "migrations_version": "023_add_policy_profiles",  // Update this
  "config_hash": "sha256:...",
  "timestamp": "2026-01-07T12:00:00Z",
  "all_tests_pass": true,
  "health_status": "healthy"
}
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Migration failed in production | S2 | Rollback immediately. Investigate. |
| Migration missing RLS | S2 | Add RLS before deploying. |
| Migration missing rollback | S3 | Create rollback before applying. |
| Migration without tenant_id | S3 | Review if table needs tenant scope. |
| Long-running migration (>1min) | S3 | Schedule for maintenance window. |
