-- =============================================================================
-- MIGRATION 048b: Roster Pack Undo Feature
-- =============================================================================
--
-- Adds undo tracking columns to repair_actions table:
-- - undone_at: Timestamp when action was undone
-- - undone_by: User who undone the action
--
-- This enables 1-step undo during repair sessions, reducing dispatcher anxiety.
--
-- =============================================================================

BEGIN;

-- Add undo tracking columns to repair_actions
ALTER TABLE roster.repair_actions
    ADD COLUMN IF NOT EXISTS undone_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS undone_by VARCHAR(255);

-- =============================================================================
-- UNDO HOT PATH INDEX
-- =============================================================================
-- The undo query needs to find the last applied action by action_seq (not applied_at
-- to avoid clock skew issues). This index supports:
--   SELECT ... WHERE repair_session_id = $1 AND applied_at IS NOT NULL AND undone_at IS NULL
--   ORDER BY action_seq DESC LIMIT 1
--
-- We use action_seq DESC as the sort key for deterministic ordering.
CREATE INDEX IF NOT EXISTS idx_repair_actions_undo_candidate
    ON roster.repair_actions(repair_session_id, action_seq DESC)
    WHERE applied_at IS NOT NULL AND undone_at IS NULL;

-- Index for counting remaining undoable actions
CREATE INDEX IF NOT EXISTS idx_repair_actions_applied_count
    ON roster.repair_actions(repair_session_id)
    WHERE applied_at IS NOT NULL AND undone_at IS NULL;

-- Update verification function to include undo columns check
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

    -- Check 13: Undo columns exist
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'roster'
      AND table_name = 'repair_actions'
      AND column_name IN ('undone_at', 'undone_by');

    IF v_count = 2 THEN
        RETURN QUERY SELECT 'undo_columns'::TEXT, 'PASS'::TEXT, 'Undo tracking columns exist'::TEXT;
    ELSE
        RETURN QUERY SELECT 'undo_columns'::TEXT, 'WARN'::TEXT, format('Only %s undo columns found (expected 2)', v_count)::TEXT;
    END IF;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Run: SELECT * FROM roster.verify_roster_integrity();
-- Expected: 13 checks, all PASS (or WARN for optional indexes)
