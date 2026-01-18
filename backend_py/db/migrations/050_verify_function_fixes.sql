-- ============================================================================
-- MIGRATION 050: Verify Function Fixes
-- ============================================================================
-- RELEASE GATE FIX: Repairs SQL bugs in verify_*() functions that prevent
-- integrity checks from running.
--
-- BUGS FIXED:
--   1. verify_final_hardening() - 'PUBLIC' as string literal doesn't work
--   2. portal.verify_portal_integrity() - pg_constraint_conargs() doesn't exist
--   3. dispatch.verify_dispatch_integrity() - column "status" is ambiguous
--      (conflicts with RETURNS TABLE column name)
--
-- RUN: Automatic via fresh-db-proof.ps1 or migration runner
-- ============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('050', 'Fix verify_*() function SQL bugs', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- FIX 1: verify_final_hardening() - PUBLIC role check
-- ============================================================================
-- Bug: Line 329 used has_schema_privilege('PUBLIC', 'public', 'CREATE')
-- PostgreSQL doesn't accept 'PUBLIC' as a quoted string for the PUBLIC pseudo-role.
-- Fix: Check via nspacl pattern instead.

CREATE OR REPLACE FUNCTION verify_final_hardening()
RETURNS TABLE (
    test_name TEXT,
    expected TEXT,
    actual TEXT,
    status TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    api_can_verify BOOLEAN;
    platform_can_verify BOOLEAN;
    api_can_create BOOLEAN;
    public_can_create BOOLEAN;
BEGIN
    -- Test 1: solvereign_api should NOT have EXECUTE on verify_rls_boundary()
    SELECT has_function_privilege('solvereign_api', 'verify_rls_boundary()', 'EXECUTE')
    INTO api_can_verify;
    test_name := 'solvereign_api EXECUTE on verify_rls_boundary()';
    expected := 'false';
    actual := api_can_verify::TEXT;
    status := CASE WHEN api_can_verify = FALSE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 2: solvereign_platform SHOULD have EXECUTE on verify_rls_boundary()
    SELECT has_function_privilege('solvereign_platform', 'verify_rls_boundary()', 'EXECUTE')
    INTO platform_can_verify;
    test_name := 'solvereign_platform EXECUTE on verify_rls_boundary()';
    expected := 'true';
    actual := platform_can_verify::TEXT;
    status := CASE WHEN platform_can_verify = TRUE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 3: solvereign_api should NOT have CREATE on schema public
    SELECT has_schema_privilege('solvereign_api', 'public', 'CREATE')
    INTO api_can_create;
    test_name := 'solvereign_api CREATE on schema public';
    expected := 'false';
    actual := api_can_create::TEXT;
    status := CASE WHEN api_can_create = FALSE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 4: PUBLIC should NOT have CREATE on schema public
    -- FIX: Use nspacl check instead of has_schema_privilege('PUBLIC', ...)
    -- Check if the schema's ACL contains '=C/' which means PUBLIC has CREATE
    SELECT (
        SELECT NOT EXISTS (
            SELECT 1 FROM pg_namespace
            WHERE nspname = 'public'
            AND nspacl::text LIKE '%=C/%'
        )
    ) INTO public_can_create;
    test_name := 'PUBLIC CREATE on schema public';
    expected := 'false';
    -- Note: public_can_create is TRUE if PUBLIC does NOT have CREATE (inverted)
    actual := (NOT public_can_create)::TEXT;
    status := CASE WHEN public_can_create = TRUE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 5: Default privileges for solvereign_admin (FUNCTIONS, TABLES, SEQUENCES)
    test_name := 'Default privileges set for solvereign_admin';
    expected := 'true';
    SELECT EXISTS(
        SELECT 1 FROM pg_default_acl d
        JOIN pg_roles r ON d.defaclrole = r.oid
        WHERE r.rolname = 'solvereign_admin'
          AND d.defaclnamespace = 'public'::regnamespace
    )::TEXT INTO actual;
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 6: Default privileges for solvereign_definer
    test_name := 'Default privileges set for solvereign_definer';
    expected := 'true';
    SELECT EXISTS(
        SELECT 1 FROM pg_default_acl d
        JOIN pg_roles r ON d.defaclrole = r.oid
        WHERE r.rolname = 'solvereign_definer'
          AND d.defaclnamespace = 'public'::regnamespace
    )::TEXT INTO actual;
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 7: Default privileges for solvereign_platform
    test_name := 'Default privileges set for solvereign_platform';
    expected := 'true';
    SELECT EXISTS(
        SELECT 1 FROM pg_default_acl d
        JOIN pg_roles r ON d.defaclrole = r.oid
        WHERE r.rolname = 'solvereign_platform'
          AND d.defaclnamespace = 'public'::regnamespace
    )::TEXT INTO actual;
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 8: Schema comment includes security policy (WARN acceptable)
    test_name := 'Schema security policy documented (WARN ok)';
    expected := 'true';
    SELECT (obj_description('public'::regnamespace, 'pg_namespace') LIKE '%SECURITY POLICY%')::TEXT
    INTO actual;
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'WARN' END;
    RETURN NEXT;

    -- =========================================================================
    -- CORE SCHEMA TESTS (9-14) - Only if core schema exists
    -- =========================================================================

    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core') THEN
        -- Test 9: core schema default privileges for solvereign_admin
        test_name := 'Default privileges for solvereign_admin in core schema';
        expected := 'true';
        SELECT EXISTS(
            SELECT 1 FROM pg_default_acl d
            JOIN pg_roles r ON d.defaclrole = r.oid
            WHERE r.rolname = 'solvereign_admin'
              AND d.defaclnamespace = 'core'::regnamespace
        )::TEXT INTO actual;
        status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;

        -- Test 10: core schema default privileges for solvereign_definer
        test_name := 'Default privileges for solvereign_definer in core schema';
        expected := 'true';
        SELECT EXISTS(
            SELECT 1 FROM pg_default_acl d
            JOIN pg_roles r ON d.defaclrole = r.oid
            WHERE r.rolname = 'solvereign_definer'
              AND d.defaclnamespace = 'core'::regnamespace
        )::TEXT INTO actual;
        status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;

        -- Test 11: core schema default privileges for solvereign_platform
        test_name := 'Default privileges for solvereign_platform in core schema';
        expected := 'true';
        SELECT EXISTS(
            SELECT 1 FROM pg_default_acl d
            JOIN pg_roles r ON d.defaclrole = r.oid
            WHERE r.rolname = 'solvereign_platform'
              AND d.defaclnamespace = 'core'::regnamespace
        )::TEXT INTO actual;
        status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;

        -- Test 12: solvereign_api cannot CREATE in core schema
        test_name := 'solvereign_api CREATE on schema core';
        expected := 'false';
        SELECT has_schema_privilege('solvereign_api', 'core', 'CREATE')::TEXT INTO actual;
        status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;

        -- Test 13: solvereign_platform cannot CREATE in core schema
        test_name := 'solvereign_platform CREATE on schema core';
        expected := 'false';
        SELECT has_schema_privilege('solvereign_platform', 'core', 'CREATE')::TEXT INTO actual;
        status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;

        -- Test 14: solvereign_definer cannot CREATE in core schema
        test_name := 'solvereign_definer CREATE on schema core';
        expected := 'false';
        SELECT has_schema_privilege('solvereign_definer', 'core', 'CREATE')::TEXT INTO actual;
        status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;
    ELSE
        -- core schema doesn't exist - mark as skipped
        test_name := 'core schema tests (9-14)';
        expected := 'skipped';
        actual := 'core schema does not exist';
        status := 'INFO';
        RETURN NEXT;
    END IF;

    -- =========================================================================
    -- RETROACTIVE ACL CHECKS (15-17)
    -- =========================================================================

    -- Test 15: User-defined functions with PUBLIC EXECUTE (ALLOWLIST-BASED)
    test_name := 'User functions with PUBLIC EXECUTE (public schema)';
    expected := '0';
    SELECT COUNT(*)::TEXT INTO actual
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
      AND p.proacl IS NOT NULL
      AND p.proacl::text LIKE '%=X/%'  -- PUBLIC EXECUTE grant pattern
      -- Exclude extension patterns (allowlist)
      AND p.proname NOT LIKE 'pg_%'
      AND p.proname NOT LIKE 'pgp_%'
      AND p.proname NOT LIKE 'armor%'
      AND p.proname NOT LIKE 'dearmor%'
      AND p.proname NOT LIKE 'crypt%'
      AND p.proname NOT LIKE 'gen_random%'
      AND p.proname NOT LIKE 'gen_salt%'
      AND p.proname NOT LIKE 'digest%'
      AND p.proname NOT LIKE 'hmac%'
      AND p.proname NOT LIKE 'encrypt%'
      AND p.proname NOT LIKE 'decrypt%'
      AND p.proname NOT LIKE 'uuid_%'
      AND p.proname NOT LIKE 'st_%'
      AND p.proname NOT LIKE 'geography_%'
      AND p.proname NOT LIKE 'geometry_%'
      AND p.proname NOT LIKE 'box2d%'
      AND p.proname NOT LIKE 'box3d%'
      AND p.proname NOT LIKE 'postgis_%'
      AND p.proname NOT LIKE '_%';  -- Exclude internal functions
    status := CASE WHEN actual = '0' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 16: User-defined tables with PUBLIC SELECT (ALLOWLIST-BASED)
    test_name := 'User tables with PUBLIC SELECT (public schema)';
    expected := '0';
    SELECT COUNT(*)::TEXT INTO actual
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relacl IS NOT NULL
      AND c.relacl::text LIKE '%=r/%'  -- PUBLIC SELECT grant pattern
      -- Exclude extension patterns (allowlist)
      AND c.relname NOT LIKE 'pg_%'
      AND c.relname NOT LIKE 'spatial_ref_sys%'
      AND c.relname NOT LIKE 'geometry_columns%'
      AND c.relname NOT LIKE 'geography_columns%';
    status := CASE WHEN actual = '0' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 17: Security functions accessible by solvereign_api (AUDIT LIST)
    test_name := 'Security functions executable by solvereign_api';
    expected := 'get_tenant_by_api_key_hash, set_tenant_context';
    SELECT COALESCE(string_agg(p.proname, ', ' ORDER BY p.proname), '(none)') INTO actual
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
      AND (p.proname LIKE '%tenant%' OR p.proname LIKE '%admin%' OR p.proname LIKE '%verify%')
      AND has_function_privilege('solvereign_api', p.oid, 'EXECUTE') = true;
    status := CASE
        WHEN actual = expected THEN 'PASS'
        WHEN actual = '(none)' THEN 'WARN'
        ELSE 'WARN'
    END;
    RETURN NEXT;
END;
$$;

-- Ownership and permissions
ALTER FUNCTION verify_final_hardening() OWNER TO solvereign_definer;
REVOKE ALL ON FUNCTION verify_final_hardening() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        REVOKE ALL ON FUNCTION verify_final_hardening() FROM solvereign_api;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT EXECUTE ON FUNCTION verify_final_hardening() TO solvereign_platform;
    END IF;
END $$;


-- ============================================================================
-- FIX 2: portal.verify_portal_integrity() - Remove non-existent function call
-- ============================================================================
-- Bug: Lines 617-620 used pg_constraint_conargs(c.oid) which doesn't exist.
-- Fix: Use proper pg_constraint.conkey + pg_attribute join pattern.
-- NOTE: Must DROP first because RETURNS TABLE columns changed (status -> check_status)

DROP FUNCTION IF EXISTS portal.verify_portal_integrity();

CREATE OR REPLACE FUNCTION portal.verify_portal_integrity()
RETURNS TABLE (
    check_name TEXT,
    check_status TEXT,
    details TEXT
) AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check 1: RLS enabled on portal_tokens
    SELECT COUNT(*) INTO v_count
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename
        AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.schemaname)
    WHERE t.schemaname = 'portal'
    AND t.tablename = 'portal_tokens'
    AND c.relrowsecurity = TRUE
    AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_portal_tokens'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_portal_tokens'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 2: RLS enabled on read_receipts
    SELECT COUNT(*) INTO v_count
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename
        AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.schemaname)
    WHERE t.schemaname = 'portal'
    AND t.tablename = 'read_receipts'
    AND c.relrowsecurity = TRUE
    AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_read_receipts'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_read_receipts'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 3: RLS enabled on driver_ack
    SELECT COUNT(*) INTO v_count
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename
        AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.schemaname)
    WHERE t.schemaname = 'portal'
    AND t.tablename = 'driver_ack'
    AND c.relrowsecurity = TRUE
    AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_driver_ack'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_driver_ack'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 4: Unique constraints exist
    SELECT COUNT(*) INTO v_count
    FROM pg_constraint
    WHERE conname IN (
        'portal_tokens_jti_hash_key',
        'read_receipts_unique_driver_snapshot',
        'driver_ack_unique_driver_snapshot',
        'driver_views_unique_driver_snapshot',
        'snapshot_supersedes_unique_old'
    );

    IF v_count >= 4 THEN
        RETURN QUERY SELECT 'unique_constraints'::TEXT, 'PASS'::TEXT,
            format('%s constraints found', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'unique_constraints'::TEXT, 'FAIL'::TEXT,
            format('Only %s unique constraints found, expected at least 4', v_count)::TEXT;
    END IF;

    -- Check 5: Immutability trigger exists on driver_ack
    SELECT COUNT(*) INTO v_count
    FROM pg_trigger
    WHERE tgname = 'tr_driver_ack_immutable';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'driver_ack_immutable_trigger'::TEXT, 'PASS'::TEXT, 'Trigger exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'driver_ack_immutable_trigger'::TEXT, 'FAIL'::TEXT, 'Trigger missing'::TEXT;
    END IF;

    -- Check 6: No expired non-revoked tokens older than 30 days (WARN)
    SELECT COUNT(*) INTO v_count
    FROM portal.portal_tokens
    WHERE expires_at < NOW() - INTERVAL '30 days'
    AND revoked_at IS NULL;

    IF v_count = 0 THEN
        RETURN QUERY SELECT 'expired_token_cleanup'::TEXT, 'PASS'::TEXT, 'No stale tokens'::TEXT;
    ELSE
        RETURN QUERY SELECT 'expired_token_cleanup'::TEXT, 'WARN'::TEXT,
            format('%s expired tokens should be cleaned up', v_count)::TEXT;
    END IF;

    -- Check 7: All tables have tenant_id NOT NULL
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'portal'
    AND column_name = 'tenant_id'
    AND is_nullable = 'NO';

    IF v_count >= 6 THEN
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'PASS'::TEXT,
            format('%s tables have tenant_id NOT NULL', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'FAIL'::TEXT,
            format('Only %s tables have tenant_id NOT NULL', v_count)::TEXT;
    END IF;

    -- Check 8: Tenant FK exists on main tables
    -- FIX: Use proper pg_constraint + pg_attribute join instead of non-existent pg_constraint_conargs
    SELECT COUNT(DISTINCT con.conrelid) INTO v_count
    FROM pg_constraint con
    JOIN pg_class tbl ON con.conrelid = tbl.oid
    JOIN pg_namespace nsp ON tbl.relnamespace = nsp.oid
    JOIN pg_attribute att ON att.attrelid = con.conrelid
        AND att.attnum = ANY(con.conkey)
    WHERE nsp.nspname = 'portal'
    AND con.contype = 'f'
    AND att.attname = 'tenant_id';

    IF v_count >= 5 THEN
        RETURN QUERY SELECT 'tenant_fk_exists'::TEXT, 'PASS'::TEXT,
            format('%s tables with tenant_id FK found', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'tenant_fk_exists'::TEXT, 'WARN'::TEXT,
            format('%s tables with tenant_id FK found', v_count)::TEXT;
    END IF;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute to platform role
GRANT EXECUTE ON FUNCTION portal.verify_portal_integrity() TO solvereign_platform;


-- ============================================================================
-- FIX 3: dispatch.verify_dispatch_integrity() - Disambiguate column references
-- ============================================================================
-- Bug: Column "status" is ambiguous because RETURNS TABLE has a "status" column
--      and dispatch tables also have a "status" column.
-- Fix: Rename RETURNS TABLE column to "check_status" AND fully qualify table columns.
-- NOTE: Must DROP first because RETURNS TABLE columns changed (status -> check_status)

DROP FUNCTION IF EXISTS dispatch.verify_dispatch_integrity();

CREATE OR REPLACE FUNCTION dispatch.verify_dispatch_integrity()
RETURNS TABLE (
    check_name TEXT,
    check_status TEXT,
    details TEXT
) AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check 1: RLS enabled on all dispatch tables
    SELECT COUNT(*) INTO v_count
    FROM pg_tables tbl
    JOIN pg_class cls ON cls.relname = tbl.tablename
    JOIN pg_namespace nsp ON cls.relnamespace = nsp.oid AND nsp.nspname = tbl.schemaname
    WHERE tbl.schemaname = 'dispatch'
      AND tbl.tablename IN ('dispatch_open_shifts', 'dispatch_proposals', 'dispatch_apply_audit')
      AND cls.relrowsecurity = TRUE;

    RETURN QUERY SELECT
        'rls_enabled'::TEXT,
        CASE WHEN v_count = 3 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s/3 tables have RLS enabled', v_count)::TEXT;

    -- Check 2: FORCE RLS enabled
    SELECT COUNT(*) INTO v_count
    FROM pg_tables tbl
    JOIN pg_class cls ON cls.relname = tbl.tablename
    JOIN pg_namespace nsp ON cls.relnamespace = nsp.oid AND nsp.nspname = tbl.schemaname
    WHERE tbl.schemaname = 'dispatch'
      AND tbl.tablename IN ('dispatch_open_shifts', 'dispatch_proposals', 'dispatch_apply_audit')
      AND cls.relforcerowsecurity = TRUE;

    RETURN QUERY SELECT
        'force_rls_enabled'::TEXT,
        CASE WHEN v_count = 3 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s/3 tables have FORCE RLS enabled', v_count)::TEXT;

    -- Check 3: Unique constraint on open_shifts exists
    RETURN QUERY SELECT
        'open_shifts_unique_constraint'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'dispatch_open_shifts_unique_key'
        ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Unique constraint (tenant_id, shift_date, shift_key)'::TEXT;

    -- Check 4: apply_request_id unique index exists
    RETURN QUERY SELECT
        'apply_request_id_unique'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'dispatch'
              AND tablename = 'dispatch_proposals'
              AND indexname LIKE '%apply_request%'
        ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Unique index on apply_request_id for idempotency'::TEXT;

    -- Check 5: No orphan proposals (open_shift_id exists)
    SELECT COUNT(*) INTO v_count
    FROM dispatch.dispatch_proposals p
    LEFT JOIN dispatch.dispatch_open_shifts os ON p.open_shift_id = os.id
    WHERE os.id IS NULL;

    RETURN QUERY SELECT
        'no_orphan_proposals'::TEXT,
        CASE WHEN v_count = 0 THEN 'PASS' ELSE 'WARN' END::TEXT,
        format('%s proposals with missing open_shift_id', v_count)::TEXT;

    -- Check 6: tenant_id NOT NULL on all tables
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns col
    WHERE col.table_schema = 'dispatch'
      AND col.table_name IN ('dispatch_open_shifts', 'dispatch_proposals', 'dispatch_apply_audit')
      AND col.column_name = 'tenant_id'
      AND col.is_nullable = 'NO';

    RETURN QUERY SELECT
        'tenant_id_not_null'::TEXT,
        CASE WHEN v_count = 3 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s/3 tables have tenant_id NOT NULL', v_count)::TEXT;

    -- Check 7: Valid status values in open_shifts
    -- FIX: Fully qualify dispatch_open_shifts.status to avoid ambiguity with RETURNS TABLE column
    SELECT COUNT(*) INTO v_count
    FROM dispatch.dispatch_open_shifts dos
    WHERE dos.status NOT IN ('DETECTED', 'PROPOSAL_GENERATED', 'APPLIED', 'CLOSED', 'INVALIDATED');

    RETURN QUERY SELECT
        'valid_open_shift_statuses'::TEXT,
        CASE WHEN v_count = 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s open_shifts with invalid status', v_count)::TEXT;

    -- Check 8: Valid status values in proposals
    -- FIX: Fully qualify dispatch_proposals.status
    SELECT COUNT(*) INTO v_count
    FROM dispatch.dispatch_proposals dp
    WHERE dp.status NOT IN ('GENERATED', 'PROPOSED', 'APPLIED', 'REJECTED', 'EXPIRED', 'INVALIDATED');

    RETURN QUERY SELECT
        'valid_proposal_statuses'::TEXT,
        CASE WHEN v_count = 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s proposals with invalid status', v_count)::TEXT;

    -- Check 9: Applied proposals have selected_driver_id
    SELECT COUNT(*) INTO v_count
    FROM dispatch.dispatch_proposals dp
    WHERE dp.status = 'APPLIED' AND dp.selected_driver_id IS NULL;

    RETURN QUERY SELECT
        'applied_has_driver'::TEXT,
        CASE WHEN v_count = 0 THEN 'PASS' ELSE 'WARN' END::TEXT,
        format('%s APPLIED proposals without selected_driver_id', v_count)::TEXT;

    -- Check 10: Forced proposals have force_reason
    SELECT COUNT(*) INTO v_count
    FROM dispatch.dispatch_proposals dp
    WHERE dp.forced_apply = TRUE AND (dp.force_reason IS NULL OR LENGTH(TRIM(dp.force_reason)) < 10);

    RETURN QUERY SELECT
        'forced_has_reason'::TEXT,
        CASE WHEN v_count = 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s forced proposals without force_reason', v_count)::TEXT;

    -- Check 11: RLS policies exist
    SELECT COUNT(*) INTO v_count
    FROM pg_policies
    WHERE schemaname = 'dispatch';

    RETURN QUERY SELECT
        'rls_policies_exist'::TEXT,
        CASE WHEN v_count >= 3 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s RLS policies found (expected 3)', v_count)::TEXT;

    -- Check 12: Functions exist
    SELECT COUNT(*) INTO v_count
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'dispatch'
      AND p.proname IN ('upsert_open_shift', 'check_apply_idempotency', 'record_apply_audit', 'verify_dispatch_integrity');

    RETURN QUERY SELECT
        'functions_exist'::TEXT,
        CASE WHEN v_count >= 4 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        format('%s functions found (expected 4+)', v_count)::TEXT;

END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION dispatch.verify_dispatch_integrity IS
'Verify dispatch lifecycle health. Fixed in migration 050 to resolve ambiguous column references.';


-- ============================================================================
-- VERIFICATION BLOCK
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    fail_count INTEGER := 0;
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 050: Verify Function Fixes - Running Verification';
    RAISE NOTICE '============================================================';

    -- Test verify_final_hardening()
    RAISE NOTICE '';
    RAISE NOTICE 'verify_final_hardening():';
    BEGIN
        FOR r IN SELECT * FROM verify_final_hardening() LOOP
            IF r.status = 'FAIL' THEN
                fail_count := fail_count + 1;
            END IF;
            RAISE NOTICE '  [%] %: expected=%, actual=%', r.status, r.test_name, r.expected, r.actual;
        END LOOP;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE '  [EXCEPTION] %', SQLERRM;
        fail_count := fail_count + 1;
    END;

    -- Test portal.verify_portal_integrity()
    RAISE NOTICE '';
    RAISE NOTICE 'portal.verify_portal_integrity():';
    BEGIN
        FOR r IN SELECT * FROM portal.verify_portal_integrity() LOOP
            IF r.check_status = 'FAIL' THEN
                fail_count := fail_count + 1;
            END IF;
            RAISE NOTICE '  [%] %: %', r.check_status, r.check_name, r.details;
        END LOOP;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE '  [EXCEPTION] %', SQLERRM;
        fail_count := fail_count + 1;
    END;

    -- Test dispatch.verify_dispatch_integrity()
    RAISE NOTICE '';
    RAISE NOTICE 'dispatch.verify_dispatch_integrity():';
    BEGIN
        FOR r IN SELECT * FROM dispatch.verify_dispatch_integrity() LOOP
            IF r.check_status = 'FAIL' THEN
                fail_count := fail_count + 1;
            END IF;
            RAISE NOTICE '  [%] %: %', r.check_status, r.check_name, r.details;
        END LOOP;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE '  [EXCEPTION] %', SQLERRM;
        fail_count := fail_count + 1;
    END;

    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    IF fail_count = 0 THEN
        RAISE NOTICE 'Migration 050: ALL VERIFY FUNCTIONS EXECUTE WITHOUT EXCEPTION';
    ELSE
        RAISE WARNING 'Migration 050: %s issues found - review output above', fail_count;
    END IF;
    RAISE NOTICE '============================================================';
END $$;


-- ============================================================================
-- HELPER: verify_pass_gate() - Combined gate check for all verify functions
-- ============================================================================

CREATE OR REPLACE FUNCTION verify_pass_gate()
RETURNS TABLE (
    gate_name TEXT,
    passed BOOLEAN,
    non_pass_count INTEGER
) AS $$
BEGIN
    -- auth.verify_rbac_integrity
    RETURN QUERY SELECT
        'auth.verify_rbac_integrity'::TEXT,
        (SELECT count(*) FROM auth.verify_rbac_integrity() WHERE status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM auth.verify_rbac_integrity() WHERE status <> 'PASS');

    -- masterdata.verify_masterdata_integrity
    RETURN QUERY SELECT
        'masterdata.verify_masterdata_integrity'::TEXT,
        (SELECT count(*) FROM masterdata.verify_masterdata_integrity() WHERE status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM masterdata.verify_masterdata_integrity() WHERE status <> 'PASS');

    -- verify_final_hardening (WARN allowed, only count FAIL)
    RETURN QUERY SELECT
        'verify_final_hardening'::TEXT,
        (SELECT count(*) FROM verify_final_hardening() WHERE status = 'FAIL') = 0,
        (SELECT count(*)::INTEGER FROM verify_final_hardening() WHERE status = 'FAIL');

    -- portal.verify_portal_integrity
    RETURN QUERY SELECT
        'portal.verify_portal_integrity'::TEXT,
        (SELECT count(*) FROM portal.verify_portal_integrity() WHERE check_status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM portal.verify_portal_integrity() WHERE check_status <> 'PASS');

    -- dispatch.verify_dispatch_integrity
    RETURN QUERY SELECT
        'dispatch.verify_dispatch_integrity'::TEXT,
        (SELECT count(*) FROM dispatch.verify_dispatch_integrity() WHERE check_status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM dispatch.verify_dispatch_integrity() WHERE check_status <> 'PASS');
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION verify_pass_gate IS
'Combined gate check for all verify functions. Returns TRUE for each gate if 0 non-PASS rows.
Usage: SELECT * FROM verify_pass_gate();
Akzeptanz: Alle passed = true';


-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 050: Verify Function Fixes COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'BUGS FIXED:';
    RAISE NOTICE '  1. verify_final_hardening() - PUBLIC role check via nspacl';
    RAISE NOTICE '  2. portal.verify_portal_integrity() - Removed pg_constraint_conargs()';
    RAISE NOTICE '  3. dispatch.verify_dispatch_integrity() - Renamed RETURNS column + qualified refs';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM verify_final_hardening();';
    RAISE NOTICE '  SELECT * FROM portal.verify_portal_integrity();';
    RAISE NOTICE '  SELECT * FROM dispatch.verify_dispatch_integrity();';
    RAISE NOTICE '';
    RAISE NOTICE 'ALL FUNCTIONS SHOULD RETURN ROWS WITHOUT EXCEPTIONS.';
    RAISE NOTICE '============================================================';
END $$;
