-- ============================================================================
-- MIGRATION 051: Security Default Privileges + Table ACL Fix
-- ============================================================================
-- RELEASE GATE FIX: Repairs the 4 FAILs in verify_final_hardening():
--
-- FIXES:
--   1. verify_final_hardening() Test 16 - Pattern '%=r/%' matches specific roles
--      Fix: Use aclexplode() to properly detect PUBLIC SELECT grants
--   2. 5 tables with NULL ACL (= default PUBLIC access)
--      Fix: Set explicit ACLs (driver_availability, driver_skills, drivers,
--           repair_log, sites)
--   3. Missing default privileges for solvereign_admin, _definer, _platform
--      Fix: ALTER DEFAULT PRIVILEGES for all 3 roles in public schema
--
-- RUN: Automatic via fresh-db-proof.ps1 or migration runner
-- ============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('051', 'Security default privileges + table ACL fix', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();


-- ============================================================================
-- FIX 1: Set explicit ACLs on tables with NULL ACL (removes PUBLIC access)
-- ============================================================================
-- Tables with NULL ACL have DEFAULT privileges which includes PUBLIC SELECT.
-- Setting explicit grants removes the NULL and removes PUBLIC access.

DO $$
DECLARE
    v_tables TEXT[] := ARRAY['driver_availability', 'driver_skills', 'drivers', 'repair_log', 'sites'];
    v_table TEXT;
BEGIN
    FOREACH v_table IN ARRAY v_tables LOOP
        -- Check if table exists and has NULL ACL
        IF EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public'
              AND c.relname = v_table
              AND c.relkind = 'r'
              AND c.relacl IS NULL
        ) THEN
            -- Grant standard ACL (same as other tables)
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO solvereign_api', v_table);
            EXECUTE format('GRANT ALL ON TABLE public.%I TO solvereign_admin', v_table);
            RAISE NOTICE 'Migration 051: Set explicit ACL on public.%', v_table;
        ELSE
            RAISE NOTICE 'Migration 051: Table % already has explicit ACL or does not exist', v_table;
        END IF;
    END LOOP;
END $$;


-- ============================================================================
-- FIX 2: Set Default Privileges for solvereign_admin
-- ============================================================================
-- Ensures future tables/functions/sequences created by solvereign_admin
-- have proper grants to solvereign_api.

-- First revoke from PUBLIC (defense in depth)
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

-- Then grant to solvereign_api
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO solvereign_api;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO solvereign_api;

-- Note: We intentionally do NOT grant EXECUTE on functions by default
-- Functions should have explicit grants based on their security requirements


-- ============================================================================
-- FIX 3: Set Default Privileges for solvereign_definer
-- ============================================================================
-- solvereign_definer owns SECURITY DEFINER functions - different pattern.

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

-- Definer-owned tables get SELECT only to solvereign_api by default
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA public
    GRANT SELECT ON TABLES TO solvereign_api;

-- Functions owned by definer should NOT be executable by api by default
-- (SECURITY DEFINER functions need explicit grants)


-- ============================================================================
-- FIX 4: Set Default Privileges for solvereign_platform
-- ============================================================================
-- solvereign_platform handles admin operations.

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

-- Platform-owned tables get full access to solvereign_api
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO solvereign_api;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO solvereign_api;


-- ============================================================================
-- FIX 5: Update verify_final_hardening() Test 16 to use aclexplode
-- ============================================================================
-- Bug: Pattern '%=r/%' matches ANY grant with 'r' privilege, including
--      specific roles like 'solvereign_definer=r/solvereign'
-- Fix: Use aclexplode() to properly detect only PUBLIC (grantee=0) SELECT grants

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
    SELECT (
        SELECT NOT EXISTS (
            SELECT 1 FROM pg_namespace
            WHERE nspname = 'public'
            AND nspacl::text LIKE '%=C/%'
        )
    ) INTO public_can_create;
    test_name := 'PUBLIC CREATE on schema public';
    expected := 'false';
    actual := (NOT public_can_create)::TEXT;
    status := CASE WHEN public_can_create = TRUE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 5: Default privileges for solvereign_admin
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

        test_name := 'solvereign_api CREATE on schema core';
        expected := 'false';
        SELECT has_schema_privilege('solvereign_api', 'core', 'CREATE')::TEXT INTO actual;
        status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;

        test_name := 'solvereign_platform CREATE on schema core';
        expected := 'false';
        SELECT has_schema_privilege('solvereign_platform', 'core', 'CREATE')::TEXT INTO actual;
        status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;

        test_name := 'solvereign_definer CREATE on schema core';
        expected := 'false';
        SELECT has_schema_privilege('solvereign_definer', 'core', 'CREATE')::TEXT INTO actual;
        status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
        RETURN NEXT;
    ELSE
        test_name := 'core schema tests (9-14)';
        expected := 'skipped';
        actual := 'core schema does not exist';
        status := 'INFO';
        RETURN NEXT;
    END IF;

    -- =========================================================================
    -- RETROACTIVE ACL CHECKS (15-17)
    -- =========================================================================

    -- Test 15: User-defined functions with PUBLIC EXECUTE
    test_name := 'User functions with PUBLIC EXECUTE (public schema)';
    expected := '0';
    SELECT COUNT(*)::TEXT INTO actual
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
      AND p.proacl IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM aclexplode(p.proacl) a
          WHERE a.grantee = 0  -- PUBLIC (represented as InvalidOid = 0)
          AND a.privilege_type = 'EXECUTE'
      )
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
      AND p.proname NOT LIKE '_%';
    status := CASE WHEN actual = '0' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 16: User-defined tables with PUBLIC SELECT
    -- FIX (Migration 051): Use aclexplode() instead of LIKE pattern
    -- Also check for NULL ACL (which means default = PUBLIC access)
    test_name := 'User tables with PUBLIC SELECT (public schema)';
    expected := '0';
    SELECT COUNT(*)::TEXT INTO actual
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relname NOT LIKE 'pg_%'
      AND c.relname NOT LIKE 'spatial_ref_sys%'
      AND c.relname NOT LIKE 'geometry_columns%'
      AND c.relname NOT LIKE 'geography_columns%'
      AND (
          -- NULL ACL means default privileges (PUBLIC has SELECT)
          c.relacl IS NULL
          OR
          -- Explicit PUBLIC SELECT grant
          EXISTS (
              SELECT 1 FROM aclexplode(c.relacl) a
              WHERE a.grantee = 0  -- PUBLIC (InvalidOid = 0)
              AND a.privilege_type = 'SELECT'
          )
      );
    status := CASE WHEN actual = '0' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 17: Security functions accessible by solvereign_api
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
-- VALIDATION
-- ============================================================================

DO $$
DECLARE
    fail_count INTEGER;
BEGIN
    -- Check NULL ACL tables are now fixed
    SELECT COUNT(*) INTO fail_count
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relacl IS NULL
      AND c.relname IN ('driver_availability', 'driver_skills', 'drivers', 'repair_log', 'sites');

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 051: Security Default Privileges Fix';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Tables with NULL ACL remaining: %', fail_count;

    -- Check default privileges are set
    IF EXISTS (
        SELECT 1 FROM pg_default_acl d
        JOIN pg_roles r ON d.defaclrole = r.oid
        WHERE r.rolname = 'solvereign_admin'
          AND d.defaclnamespace = 'public'::regnamespace
    ) THEN
        RAISE NOTICE 'solvereign_admin default privileges: SET';
    ELSE
        RAISE WARNING 'solvereign_admin default privileges: NOT SET';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_default_acl d
        JOIN pg_roles r ON d.defaclrole = r.oid
        WHERE r.rolname = 'solvereign_definer'
          AND d.defaclnamespace = 'public'::regnamespace
    ) THEN
        RAISE NOTICE 'solvereign_definer default privileges: SET';
    ELSE
        RAISE WARNING 'solvereign_definer default privileges: NOT SET';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_default_acl d
        JOIN pg_roles r ON d.defaclrole = r.oid
        WHERE r.rolname = 'solvereign_platform'
          AND d.defaclnamespace = 'public'::regnamespace
    ) THEN
        RAISE NOTICE 'solvereign_platform default privileges: SET';
    ELSE
        RAISE WARNING 'solvereign_platform default privileges: NOT SET';
    END IF;

    IF fail_count = 0 THEN
        RAISE NOTICE '============================================================';
        RAISE NOTICE 'Migration 051: ALL CHECKS PASSED';
        RAISE NOTICE '============================================================';
    ELSE
        RAISE WARNING 'Migration 051: % NULL ACL tables remaining - review needed', fail_count;
    END IF;
END $$;


-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 051: Security Default Privileges COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'verify_final_hardening() should now show 0 FAIL rows';
    RAISE NOTICE '';
    RAISE NOTICE 'Verify with:';
    RAISE NOTICE '  SELECT test_name, status FROM verify_final_hardening() WHERE status = ''FAIL'';';
    RAISE NOTICE '============================================================';
END $$;
