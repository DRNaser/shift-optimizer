-- =============================================================================
-- MIGRATION 048a: Roster Pack Constraints (Critical Fixes)
-- =============================================================================
--
-- Adds missing constraints identified during review:
-- - Unique constraint on pins (tenant_id, site_id, plan_id, assignment_key)
-- - Idempotency hash index on repair_actions
-- - invalidated_at for violations cache freshness
-- - Additional indexes for query performance
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. PINS: Add tenant+site scoped unique constraint
-- =============================================================================
-- Drop the old constraint if it exists (plan-only scope)
ALTER TABLE roster.pins
    DROP CONSTRAINT IF EXISTS pins_unique_assignment;

-- Add the properly scoped unique constraint
ALTER TABLE roster.pins
    ADD CONSTRAINT pins_unique_tenant_site_assignment
    UNIQUE (tenant_id, site_id, plan_version_id, driver_id, tour_instance_id, day);

-- Add index for (tenant_id, site_id, plan_id) lookups
CREATE INDEX IF NOT EXISTS idx_pins_tenant_site_plan
    ON roster.pins(tenant_id, site_id, plan_version_id);

-- Add deleted_at for soft delete pattern (for audit trail)
ALTER TABLE roster.pins
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Update active index to use deleted_at
DROP INDEX IF EXISTS roster.idx_pins_active;
CREATE INDEX IF NOT EXISTS idx_pins_active_v2
    ON roster.pins(plan_version_id)
    WHERE is_active = TRUE AND deleted_at IS NULL;

-- =============================================================================
-- 2. REPAIRS: Add tenant+site scoped constraints
-- =============================================================================
-- Only one OPEN session per plan
CREATE UNIQUE INDEX IF NOT EXISTS idx_repairs_one_open_per_plan
    ON roster.repairs(tenant_id, site_id, plan_version_id)
    WHERE status = 'OPEN';

-- Add tenant+site composite for RLS and queries
CREATE INDEX IF NOT EXISTS idx_repairs_tenant_site
    ON roster.repairs(tenant_id, site_id);

-- Add created_by and updated_at columns
ALTER TABLE roster.repairs
    ADD COLUMN IF NOT EXISTS created_by VARCHAR(255),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- =============================================================================
-- 3. REPAIR_ACTIONS: Add idempotency hash constraint
-- =============================================================================
-- Add repair_session_id alias if using repair_id (MUST be before indexes)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'roster'
          AND table_name = 'repair_actions'
          AND column_name = 'repair_session_id'
    ) THEN
        ALTER TABLE roster.repair_actions
            ADD COLUMN repair_session_id UUID;
        -- Copy from repair_id if it exists
        UPDATE roster.repair_actions SET repair_session_id = repair_id WHERE repair_session_id IS NULL;
    END IF;
END $$;

-- Add action_seq column if using sequence_no (MUST be before indexes)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'roster'
          AND table_name = 'repair_actions'
          AND column_name = 'action_seq'
    ) THEN
        ALTER TABLE roster.repair_actions
            ADD COLUMN action_seq INTEGER;
        -- Copy from sequence_no if it exists
        UPDATE roster.repair_actions SET action_seq = sequence_no WHERE action_seq IS NULL;
    END IF;
END $$;

-- Add idempotency_hash column
ALTER TABLE roster.repair_actions
    ADD COLUMN IF NOT EXISTS idempotency_hash VARCHAR(64);

-- Unique constraint on idempotency hash per session
CREATE UNIQUE INDEX IF NOT EXISTS idx_repair_actions_idempotency
    ON roster.repair_actions(repair_session_id, idempotency_hash)
    WHERE idempotency_hash IS NOT NULL;

-- Index on action sequence for ordered retrieval
CREATE INDEX IF NOT EXISTS idx_repair_actions_seq
    ON roster.repair_actions(repair_session_id, action_seq)
    WHERE repair_session_id IS NOT NULL;

-- Add applied tracking columns
ALTER TABLE roster.repair_actions
    ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS applied_by VARCHAR(255),
    ADD COLUMN IF NOT EXISTS reason_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS note TEXT;

-- =============================================================================
-- 4. VIOLATIONS_CACHE: Add freshness tracking
-- =============================================================================
-- Add site_id and freshness columns
ALTER TABLE roster.violations_cache
    ADD COLUMN IF NOT EXISTS site_id INTEGER,
    ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS plan_hash VARCHAR(64);

-- Drop old unique constraint
ALTER TABLE roster.violations_cache
    DROP CONSTRAINT IF EXISTS violations_cache_unique_plan;

-- Add scoped unique constraint
CREATE UNIQUE INDEX IF NOT EXISTS idx_violations_cache_unique
    ON roster.violations_cache(tenant_id, site_id, plan_version_id)
    WHERE invalidated_at IS NULL;

-- Index for freshness queries
CREATE INDEX IF NOT EXISTS idx_violations_cache_fresh
    ON roster.violations_cache(tenant_id, site_id, plan_version_id, computed_at DESC)
    WHERE invalidated_at IS NULL;

-- =============================================================================
-- 5. AUDIT_NOTES: Add entity scope columns
-- =============================================================================
-- The table already has entity_type and entity_id
-- Add created_by if missing
ALTER TABLE roster.audit_notes
    ADD COLUMN IF NOT EXISTS created_by VARCHAR(255);

-- =============================================================================
-- 6. UPDATE HELPER FUNCTIONS
-- =============================================================================

-- Update invalidate_violations_cache to use new pattern
CREATE OR REPLACE FUNCTION roster.invalidate_violations_cache(
    p_plan_version_id INTEGER
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE roster.violations_cache
    SET invalidated_at = NOW()
    WHERE plan_version_id = p_plan_version_id
      AND invalidated_at IS NULL;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- 7. UPDATE VERIFICATION FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION roster.verify_roster_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check 1: RLS on pins
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'pins'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_pins'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_pins'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 2: RLS on repairs
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'repairs'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_repairs'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_repairs'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 3: RLS on repair_actions
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'repair_actions'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_repair_actions'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_repair_actions'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 4: RLS on violations_cache
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'violations_cache'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_violations_cache'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_violations_cache'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 5: RLS on audit_notes
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'audit_notes'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_audit_notes'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_audit_notes'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 6: Audit notes immutability trigger
    SELECT COUNT(*) INTO v_count FROM pg_trigger WHERE tgname = 'tr_audit_notes_immutable';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'audit_notes_immutable_trigger'::TEXT, 'PASS'::TEXT, 'Immutability trigger exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'audit_notes_immutable_trigger'::TEXT, 'FAIL'::TEXT, 'Trigger missing'::TEXT;
    END IF;

    -- Check 7: All tables have tenant_id NOT NULL
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'roster' AND column_name = 'tenant_id' AND is_nullable = 'NO';

    IF v_count >= 5 THEN
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'PASS'::TEXT, format('%s tables have tenant_id NOT NULL', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'FAIL'::TEXT, format('Only %s tables have tenant_id NOT NULL', v_count)::TEXT;
    END IF;

    -- Check 8: Pins unique constraint (tenant+site scoped)
    SELECT COUNT(*) INTO v_count
    FROM pg_constraint
    WHERE conname = 'pins_unique_tenant_site_assignment';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'pins_unique_constraint'::TEXT, 'PASS'::TEXT, 'Tenant+site scoped unique constraint exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'pins_unique_constraint'::TEXT, 'WARN'::TEXT, 'Missing tenant+site scoped unique constraint'::TEXT;
    END IF;

    -- Check 9: Repair actions idempotency index
    SELECT COUNT(*) INTO v_count
    FROM pg_indexes
    WHERE indexname = 'idx_repair_actions_idempotency';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'repair_idempotency_index'::TEXT, 'PASS'::TEXT, 'Idempotency index exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'repair_idempotency_index'::TEXT, 'WARN'::TEXT, 'Missing idempotency index'::TEXT;
    END IF;

    -- Check 10: Violations cache freshness column
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'roster'
      AND table_name = 'violations_cache'
      AND column_name = 'invalidated_at';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'violations_cache_freshness'::TEXT, 'PASS'::TEXT, 'invalidated_at column exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'violations_cache_freshness'::TEXT, 'WARN'::TEXT, 'Missing invalidated_at column'::TEXT;
    END IF;

    -- Check 11: One open session per plan index
    SELECT COUNT(*) INTO v_count
    FROM pg_indexes
    WHERE indexname = 'idx_repairs_one_open_per_plan';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'one_open_session_constraint'::TEXT, 'PASS'::TEXT, 'One open session per plan index exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'one_open_session_constraint'::TEXT, 'WARN'::TEXT, 'Missing one open session constraint'::TEXT;
    END IF;

    -- Check 12: Helper functions exist
    SELECT COUNT(*) INTO v_count
    FROM information_schema.routines
    WHERE routine_schema = 'roster'
      AND routine_name IN ('get_active_pins', 'is_assignment_pinned', 'record_audit_note', 'invalidate_violations_cache');

    IF v_count >= 4 THEN
        RETURN QUERY SELECT 'helper_functions'::TEXT, 'PASS'::TEXT, format('%s helper functions exist', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'helper_functions'::TEXT, 'FAIL'::TEXT, format('Only %s helper functions found', v_count)::TEXT;
    END IF;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Run: SELECT * FROM roster.verify_roster_integrity();
-- Expected: 12 checks, all PASS (or WARN for optional indexes)
