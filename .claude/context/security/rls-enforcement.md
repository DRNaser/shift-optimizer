# RLS Enforcement Rules

> **Purpose**: Row-Level Security implementation and verification
> **Last Updated**: 2026-01-07

---

## CORE PRINCIPLE

**Every tenant-scoped table MUST have RLS enabled and a policy that filters by `tenant_id`.**

---

## RLS IMPLEMENTATION PATTERN

### 1. Enable RLS on Table

```sql
ALTER TABLE my_table ENABLE ROW LEVEL SECURITY;
ALTER TABLE my_table FORCE ROW LEVEL SECURITY;
```

### 2. Create Policy

```sql
CREATE POLICY tenant_isolation ON my_table
    USING (tenant_id::text = current_setting('app.current_tenant_id', true));
```

### 3. Set Tenant Context in Transaction

```python
async with db.connection() as conn:
    await conn.execute(
        "SELECT set_config('app.current_tenant_id', %s, true)",
        (str(tenant_id),)
    )
    # All subsequent queries are now tenant-scoped
```

---

## VERIFICATION CHECKLIST

### Pre-Deploy Verification

```sql
-- Check RLS is enabled on all tenant tables
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('forecast_versions', 'plan_versions', 'assignments', 'tours_normalized', 'tour_instances');

-- Expected: rowsecurity = true for ALL

-- Check policies exist
SELECT tablename, policyname, cmd, qual
FROM pg_policies
WHERE schemaname = 'public';
```

### Runtime Verification

```python
# Test RLS leak - should return 0 rows for wrong tenant
async def test_rls_leak():
    async with db.connection() as conn:
        # Set tenant A
        await conn.execute("SELECT set_config('app.current_tenant_id', 'tenant-a', true)")

        # Insert test data
        await conn.execute("INSERT INTO test_table (tenant_id, data) VALUES ('tenant-a', 'secret')")

        # Switch to tenant B
        await conn.execute("SELECT set_config('app.current_tenant_id', 'tenant-b', true)")

        # Try to read tenant A's data - MUST return 0 rows
        result = await conn.execute("SELECT * FROM test_table WHERE tenant_id = 'tenant-a'")
        assert len(result.fetchall()) == 0, "RLS LEAK DETECTED!"
```

---

## TABLES REQUIRING RLS

| Table | tenant_id Column | RLS Enabled | Policy Name |
|-------|------------------|-------------|-------------|
| `tenants` | `id` (self) | N/A | N/A |
| `forecast_versions` | `tenant_id` | YES | `tenant_isolation` |
| `plan_versions` | via forecast | YES | `tenant_isolation` |
| `tours_normalized` | via forecast | YES | `tenant_isolation` |
| `tour_instances` | via forecast | YES | `tenant_isolation` |
| `assignments` | via plan | YES | `tenant_isolation` |
| `routing_scenarios` | `tenant_id` | YES | `tenant_isolation` |
| `routing_stops` | via scenario | YES | `tenant_isolation` |
| `routing_routes` | via scenario | YES | `tenant_isolation` |

---

## COMMON ISSUES

### Issue 1: RLS Not Set in Transaction

**Symptom**: Queries return all rows, not just tenant's rows

**Fix**:
```python
# WRONG - RLS context not set
conn.execute("SELECT * FROM table")

# CORRECT - Set RLS context first
conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", (tenant_id,))
conn.execute("SELECT * FROM table")
```

### Issue 2: Superuser Bypasses RLS

**Symptom**: Admin sees all data

**Fix**:
```sql
-- Force RLS even for table owner
ALTER TABLE my_table FORCE ROW LEVEL SECURITY;
```

### Issue 3: JOIN Leaks Data

**Symptom**: JOINs expose cross-tenant data

**Fix**:
```sql
-- Ensure ALL tables in JOIN have RLS or explicit tenant filter
SELECT a.*, b.*
FROM table_a a
JOIN table_b b ON a.id = b.a_id
WHERE a.tenant_id = current_setting('app.current_tenant_id')
  AND b.tenant_id = current_setting('app.current_tenant_id');
```

---

## SECURITY PROOF TEST

Run this before every release:

```bash
python -m backend_py.tests.test_security_proofs
```

Expected output:
```
test_rls_leak_harness ... PASS
test_cross_tenant_isolation ... PASS
test_parallel_tenant_isolation ... PASS
```

---

## ESCALATION

| Finding | Severity | Action |
|---------|----------|--------|
| Table missing RLS | S2 | Block deploy. Add RLS immediately. |
| Policy missing tenant filter | S1 | STOP-THE-LINE. Fix and verify. |
| Cross-tenant data visible | S1 | STOP-THE-LINE. Incident response. |
| set_config not called | S2 | Fix code path. Add tests. |
