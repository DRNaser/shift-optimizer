-- ============================================================================
-- MIGRATION 060: Assert Verify Pass Gate
-- ============================================================================
-- Adds assert_verify_pass_gate() that THROWS on any failing gate.
-- Designed for Pilot Runbook to fail fast if any gate is red.
--
-- Usage:
--   SELECT assert_verify_pass_gate();  -- Throws if any gate fails
--   SELECT * FROM verify_pass_gate();  -- Returns rows (existing behavior)
--
-- IDEMPOTENT: Safe to run multiple times
-- ============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('060', 'Assert verify pass gate function', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();


-- ============================================================================
-- FUNCTION: assert_verify_pass_gate()
-- ============================================================================
-- Calls verify_pass_gate() and throws if ANY gate has passed = false.
-- Returns void on success, throws exception on failure.
--
-- NOT SECURITY DEFINER: runs as caller (solvereign_admin recommended)

CREATE OR REPLACE FUNCTION assert_verify_pass_gate()
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_gate RECORD;
    v_failures TEXT[] := ARRAY[]::TEXT[];
    v_total_non_pass INTEGER := 0;
BEGIN
    -- Iterate through all gates
    FOR v_gate IN SELECT * FROM verify_pass_gate() LOOP
        IF NOT v_gate.passed THEN
            v_failures := array_append(v_failures,
                format('%s: %s non-pass checks', v_gate.gate_name, v_gate.non_pass_count));
            v_total_non_pass := v_total_non_pass + v_gate.non_pass_count;
        END IF;
    END LOOP;

    -- Throw if any failures
    IF array_length(v_failures, 1) > 0 THEN
        RAISE EXCEPTION 'VERIFY GATE FAILED: % gate(s) with % total non-pass checks. Failures: %',
            array_length(v_failures, 1),
            v_total_non_pass,
            array_to_string(v_failures, '; ')
            USING ERRCODE = 'check_violation';
    END IF;

    -- Success - no failures
    RAISE NOTICE 'VERIFY GATE PASSED: All 5 gates green';
END;
$$;

COMMENT ON FUNCTION assert_verify_pass_gate IS
'Asserts all verify gates pass. Throws exception on any failure.
Usage: SELECT assert_verify_pass_gate();
Run as solvereign_admin for best results (no RLS interference).';


-- ============================================================================
-- PERMISSIONS: Grant to roles that should run verify gates
-- ============================================================================

-- Grant verify_pass_gate to solvereign_admin (primary use case)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        GRANT EXECUTE ON FUNCTION verify_pass_gate() TO solvereign_admin;
        GRANT EXECUTE ON FUNCTION assert_verify_pass_gate() TO solvereign_admin;
        RAISE NOTICE '[060] Granted verify functions to solvereign_admin';
    END IF;
END $$;

-- Grant to solvereign_platform (for platform admin operations)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT EXECUTE ON FUNCTION verify_pass_gate() TO solvereign_platform;
        GRANT EXECUTE ON FUNCTION assert_verify_pass_gate() TO solvereign_platform;
        RAISE NOTICE '[060] Granted verify functions to solvereign_platform';
    END IF;
END $$;

-- Revoke from PUBLIC (defense in depth)
REVOKE ALL ON FUNCTION verify_pass_gate() FROM PUBLIC;
REVOKE ALL ON FUNCTION assert_verify_pass_gate() FROM PUBLIC;


-- ============================================================================
-- GRANT UNDERLYING VERIFY FUNCTIONS TO solvereign_admin
-- ============================================================================
-- The verify_pass_gate calls other verify functions. Ensure caller can execute them.

DO $$
BEGIN
    -- Grant to solvereign_admin
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        -- auth.verify_rbac_integrity
        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'auth' AND p.proname = 'verify_rbac_integrity') THEN
            GRANT EXECUTE ON FUNCTION auth.verify_rbac_integrity() TO solvereign_admin;
        END IF;

        -- masterdata.verify_masterdata_integrity
        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'masterdata' AND p.proname = 'verify_masterdata_integrity') THEN
            GRANT EXECUTE ON FUNCTION masterdata.verify_masterdata_integrity() TO solvereign_admin;
        END IF;

        -- verify_final_hardening (public schema)
        IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'verify_final_hardening' AND pronamespace = 'public'::regnamespace) THEN
            GRANT EXECUTE ON FUNCTION verify_final_hardening() TO solvereign_admin;
        END IF;

        -- portal.verify_portal_integrity
        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'portal' AND p.proname = 'verify_portal_integrity') THEN
            GRANT EXECUTE ON FUNCTION portal.verify_portal_integrity() TO solvereign_admin;
        END IF;

        -- dispatch.verify_dispatch_integrity
        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'dispatch' AND p.proname = 'verify_dispatch_integrity') THEN
            GRANT EXECUTE ON FUNCTION dispatch.verify_dispatch_integrity() TO solvereign_admin;
        END IF;

        RAISE NOTICE '[060] Granted underlying verify functions to solvereign_admin';
    END IF;

    -- Grant to solvereign_platform (may already have access, but ensure)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'auth' AND p.proname = 'verify_rbac_integrity') THEN
            GRANT EXECUTE ON FUNCTION auth.verify_rbac_integrity() TO solvereign_platform;
        END IF;

        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'masterdata' AND p.proname = 'verify_masterdata_integrity') THEN
            GRANT EXECUTE ON FUNCTION masterdata.verify_masterdata_integrity() TO solvereign_platform;
        END IF;

        IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'verify_final_hardening' AND pronamespace = 'public'::regnamespace) THEN
            GRANT EXECUTE ON FUNCTION verify_final_hardening() TO solvereign_platform;
        END IF;

        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'portal' AND p.proname = 'verify_portal_integrity') THEN
            GRANT EXECUTE ON FUNCTION portal.verify_portal_integrity() TO solvereign_platform;
        END IF;

        IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                   WHERE n.nspname = 'dispatch' AND p.proname = 'verify_dispatch_integrity') THEN
            GRANT EXECUTE ON FUNCTION dispatch.verify_dispatch_integrity() TO solvereign_platform;
        END IF;

        RAISE NOTICE '[060] Granted underlying verify functions to solvereign_platform';
    END IF;
END $$;


-- ============================================================================
-- FIX: masterdata.verify_masterdata_integrity - tenant_fk_exists check
-- ============================================================================
-- Issue: Check expected exactly 4 tables, but driver_contacts was added (5 total)
-- Classification: FALSE POSITIVE (more FKs = more secure)
-- Fix: Change from COUNT(*) = 4 to COUNT(*) >= 4

CREATE OR REPLACE FUNCTION masterdata.verify_masterdata_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: RLS enabled on all MDL tables (core 4)
    RETURN QUERY
    SELECT
        'rls_enabled'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 tables have RLS enabled', COUNT(*))
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'masterdata')
    WHERE t.schemaname = 'masterdata'
      AND t.tablename IN ('md_sites', 'md_locations', 'md_vehicles', 'md_external_mappings')
      AND c.relrowsecurity = TRUE;

    -- Check 2: FORCE RLS enabled (core 4)
    RETURN QUERY
    SELECT
        'force_rls_enabled'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 tables have FORCE RLS enabled', COUNT(*))
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'masterdata')
    WHERE t.schemaname = 'masterdata'
      AND t.tablename IN ('md_sites', 'md_locations', 'md_vehicles', 'md_external_mappings')
      AND c.relforcerowsecurity = TRUE;

    -- Check 3: Unique constraint on mappings exists
    RETURN QUERY
    SELECT
        'mapping_unique_constraint'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'md_external_mappings_unique_external'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'Unique constraint (tenant_id, external_system, entity_type, external_id)'::TEXT;

    -- Check 4: Unique constraints on sites and vehicles exist
    RETURN QUERY
    SELECT
        'entity_unique_constraints'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'md_sites_unique_code'
        ) AND EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'md_vehicles_unique_code'
        ) AND EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'md_locations_unique_coords'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'Unique constraints on sites (site_code), vehicles (vehicle_code), locations (lat/lng)'::TEXT;

    -- Check 5: RLS policies exist
    RETURN QUERY
    SELECT
        'rls_policies_exist'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s RLS policies found (expected 4+)', COUNT(*))
    FROM pg_policies
    WHERE schemaname = 'masterdata';

    -- Check 6: Functions exist
    RETURN QUERY
    SELECT
        'functions_exist'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s functions found (expected 4+)', COUNT(*))
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'masterdata'
      AND p.proname IN ('resolve_external_id', 'upsert_mapping', 'resolve_or_create', 'resolve_bulk');

    -- Check 7: tenant_id NOT NULL on core MDL tables
    RETURN QUERY
    SELECT
        'tenant_id_not_null'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 tables have tenant_id NOT NULL', COUNT(*))
    FROM information_schema.columns c
    WHERE c.table_schema = 'masterdata'
      AND c.table_name IN ('md_sites', 'md_locations', 'md_vehicles', 'md_external_mappings')
      AND c.column_name = 'tenant_id'
      AND c.is_nullable = 'NO';

    -- Check 8: No orphaned mappings (internal_id points to existing entity)
    RETURN QUERY
    SELECT
        'orphaned_mappings'::TEXT,
        CASE WHEN orphan_count = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s orphaned mappings (internal_id not in any MDL table)', orphan_count)
    FROM (
        SELECT COUNT(*) as orphan_count
        FROM masterdata.md_external_mappings m
        WHERE m.entity_type IN ('site', 'location', 'vehicle')
          AND m.sync_status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM masterdata.md_sites s WHERE s.id = m.internal_id
              UNION ALL
              SELECT 1 FROM masterdata.md_locations l WHERE l.id = m.internal_id
              UNION ALL
              SELECT 1 FROM masterdata.md_vehicles v WHERE v.id = m.internal_id
          )
    ) x;

    -- Check 9: Verify tenant FK references exist (4+ tables)
    -- NOTE: >= 4 instead of = 4 because additional MDL tables may have tenant_id FK
    RETURN QUERY
    SELECT
        'tenant_fk_exists'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4+ tables have tenant_id FK to tenants', COUNT(*))
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = 'masterdata'
      AND kcu.column_name = 'tenant_id';

END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION masterdata.verify_masterdata_integrity IS
'Verify MDL health. Run after migration to confirm RLS, constraints, and functions.
Check 9 uses >= 4 to allow for additional MDL tables with tenant_id FK.';


-- ============================================================================
-- FIX: Tables with NULL ACL (default PUBLIC access)
-- ============================================================================
-- Issue: 6 tables had NULL relacl = default PUBLIC SELECT (security risk)
-- Classification: SECURITY ISSUE (not false positive)
-- Fix: Revoke PUBLIC, grant explicit permissions to app roles

DO $$
DECLARE
    v_table TEXT;
    v_tables TEXT[] := ARRAY[
        'import_artifacts',
        'import_runs',
        'plan_approvals',
        'plan_snapshots',
        'routing_evidence',
        'solver_runs'
    ];
BEGIN
    FOREACH v_table IN ARRAY v_tables LOOP
        -- Check if table exists before revoking
        IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = v_table) THEN
            EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', v_table);
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO solvereign_api', v_table);
            EXECUTE format('GRANT ALL ON %I TO solvereign_admin', v_table);
            RAISE NOTICE '[060] Secured table: %', v_table;
        END IF;
    END LOOP;
END $$;


-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 060: Assert Verify Pass Gate COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'USAGE:';
    RAISE NOTICE '  -- Returns rows (existing behavior):';
    RAISE NOTICE '  SELECT * FROM verify_pass_gate();';
    RAISE NOTICE '';
    RAISE NOTICE '  -- Throws on failure (for Runbook):';
    RAISE NOTICE '  SELECT assert_verify_pass_gate();';
    RAISE NOTICE '';
    RAISE NOTICE 'RECOMMENDED ROLE: solvereign_admin (no RLS interference)';
    RAISE NOTICE '============================================================';
END $$;
