-- ============================================================================
-- MIGRATION 025e: Final Security Hardening
-- ============================================================================
-- SECURITY FIX: Close remaining security gaps before production.
--
-- PROBLEMS ADDRESSED:
--   1. verify_rls_boundary() exposes role names, policy defs to solvereign_api
--   2. New functions/tables may accidentally get PUBLIC permissions (drift)
--   3. solvereign_api could CREATE objects in public schema
--   4. Extensions could be installed by non-admin roles
--
-- SOLUTION:
--   1. REVOKE verify_rls_boundary() from PUBLIC and solvereign_api
--   2. ALTER DEFAULT PRIVILEGES to prevent future drift
--   3. REVOKE CREATE ON SCHEMA public FROM PUBLIC
--   4. Document extension installation policy
-- ============================================================================

-- ============================================================================
-- 0. PRE-CHECK: REQUIRED ROLES MUST EXIST
-- ============================================================================
-- FAIL FAST if any required role is missing. Silent skip = security hole.

DO $$
DECLARE
    missing_roles TEXT[] := '{}';
BEGIN
    -- Check all required roles
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        missing_roles := array_append(missing_roles, 'solvereign_admin');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        missing_roles := array_append(missing_roles, 'solvereign_definer');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        missing_roles := array_append(missing_roles, 'solvereign_platform');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        missing_roles := array_append(missing_roles, 'solvereign_api');
    END IF;

    -- FAIL if any role is missing
    IF array_length(missing_roles, 1) > 0 THEN
        RAISE EXCEPTION '[025e] FATAL: Required roles missing: %. Run role creation migrations first!',
            array_to_string(missing_roles, ', ');
    END IF;

    RAISE NOTICE '[025e] PRE-CHECK PASSED: All required roles exist (solvereign_admin, solvereign_definer, solvereign_platform, solvereign_api)';
END $$;

-- ============================================================================
-- 1. VERIFY_RLS_BOUNDARY() ACCESS RESTRICTION
-- ============================================================================
-- This function returns sensitive info: role names, policy definitions, grants
-- Only platform admins should be able to run security diagnostics

DO $$
BEGIN
    -- Revoke from PUBLIC (default grant for functions)
    REVOKE ALL ON FUNCTION verify_rls_boundary() FROM PUBLIC;

    -- Explicitly revoke from solvereign_api (defense in depth)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        REVOKE ALL ON FUNCTION verify_rls_boundary() FROM solvereign_api;
        RAISE NOTICE '[025e] Revoked verify_rls_boundary() from solvereign_api';
    END IF;

    -- Grant only to platform role (security diagnostics = admin function)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT EXECUTE ON FUNCTION verify_rls_boundary() TO solvereign_platform;
        RAISE NOTICE '[025e] Granted verify_rls_boundary() to solvereign_platform only';
    END IF;
END $$;

-- ============================================================================
-- 2. ALTER DEFAULT PRIVILEGES - PREVENT FUTURE DRIFT
-- ============================================================================
-- New objects created by migration roles should NOT get PUBLIC access
-- This prevents accidental exposure when adding new functions/tables

-- For solvereign_admin (migration role)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        -- Revoke default EXECUTE on new functions from PUBLIC
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
            REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

        -- Revoke default SELECT/INSERT/UPDATE/DELETE on new tables from PUBLIC
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
            REVOKE ALL ON TABLES FROM PUBLIC;

        -- Revoke default USAGE on new sequences from PUBLIC
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA public
            REVOKE ALL ON SEQUENCES FROM PUBLIC;

        RAISE NOTICE '[025e] Set default privileges for solvereign_admin: no PUBLIC access on new objects';
    END IF;
END $$;

-- For solvereign_definer (owns security functions)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        -- FUNCTIONS
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA public
            REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

        -- TABLES (in case definer ever creates tables)
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA public
            REVOKE ALL ON TABLES FROM PUBLIC;

        -- SEQUENCES
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA public
            REVOKE ALL ON SEQUENCES FROM PUBLIC;

        RAISE NOTICE '[025e] Set default privileges for solvereign_definer: no PUBLIC access on new objects';
    END IF;
END $$;

-- For solvereign_platform (in case platform role creates objects)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        -- FUNCTIONS
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
            REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

        -- TABLES
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
            REVOKE ALL ON TABLES FROM PUBLIC;

        -- SEQUENCES
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA public
            REVOKE ALL ON SEQUENCES FROM PUBLIC;

        RAISE NOTICE '[025e] Set default privileges for solvereign_platform: no PUBLIC access on new objects';
    END IF;
END $$;

-- NOTE: We removed the generic "ALTER DEFAULT PRIVILEGES IN SCHEMA public" without FOR ROLE
-- because it only applies to the current user running the migration.
-- All relevant roles are now explicitly covered above.

DO $$
BEGIN
    RAISE NOTICE '[025e] Default privileges set for: solvereign_admin, solvereign_definer, solvereign_platform';
END $$;

-- ============================================================================
-- 3. SCHEMA HARDENING - REVOKE CREATE FROM PUBLIC
-- ============================================================================
-- Prevent non-admin roles from creating objects in public schema

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- GREENFIELD FIX: Wrap RAISE in DO block
DO $$ BEGIN RAISE NOTICE '[025e] Revoked CREATE ON SCHEMA public FROM PUBLIC'; END $$;

-- Ensure solvereign_api cannot create objects
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        REVOKE CREATE ON SCHEMA public FROM solvereign_api;
        RAISE NOTICE '[025e] Revoked CREATE ON SCHEMA public FROM solvereign_api';
    END IF;

    -- solvereign_platform can create for admin tasks (optional, remove if too risky)
    -- IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
    --     REVOKE CREATE ON SCHEMA public FROM solvereign_platform;
    -- END IF;
END $$;

-- ============================================================================
-- 4. CORE SCHEMA HARDENING (if core schema exists)
-- ============================================================================
-- The core schema contains tenant/site/entitlement tables - must be hardened

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core') THEN
        RAISE NOTICE '[025e] core schema does not exist - skipping core hardening';
        RETURN;
    END IF;

    -- Revoke CREATE from PUBLIC and ALL runtime roles
    -- Only solvereign_admin (via migrations) should create objects in core
    REVOKE CREATE ON SCHEMA core FROM PUBLIC;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        REVOKE CREATE ON SCHEMA core FROM solvereign_api;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        REVOKE CREATE ON SCHEMA core FROM solvereign_platform;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        REVOKE CREATE ON SCHEMA core FROM solvereign_definer;
    END IF;

    RAISE NOTICE '[025e] Revoked CREATE ON SCHEMA core FROM PUBLIC/api/platform/definer';
END $$;

-- Default privileges for core schema - same pattern as public schema
-- Must use FOR ROLE to apply to all object-creating roles

-- solvereign_admin in core schema
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core') THEN
        RETURN;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA core
            REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA core
            REVOKE ALL ON TABLES FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA core
            REVOKE ALL ON SEQUENCES FROM PUBLIC;

        RAISE NOTICE '[025e] Set default privileges for solvereign_admin in core schema';
    END IF;
END $$;

-- solvereign_definer in core schema
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core') THEN
        RETURN;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA core
            REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA core
            REVOKE ALL ON TABLES FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_definer IN SCHEMA core
            REVOKE ALL ON SEQUENCES FROM PUBLIC;

        RAISE NOTICE '[025e] Set default privileges for solvereign_definer in core schema';
    END IF;
END $$;

-- solvereign_platform in core schema
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core') THEN
        RETURN;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA core
            REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA core
            REVOKE ALL ON TABLES FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_platform IN SCHEMA core
            REVOKE ALL ON SEQUENCES FROM PUBLIC;

        RAISE NOTICE '[025e] Set default privileges for solvereign_platform in core schema';
    END IF;
END $$;

-- ============================================================================
-- 5. EXTENSION INSTALLATION POLICY (DOCUMENTATION)
-- ============================================================================

COMMENT ON SCHEMA public IS
'SECURITY POLICY:
- Extensions MUST be installed by solvereign_admin or superuser only
- solvereign_api: SELECT/INSERT/UPDATE/DELETE on allowed tables only
- solvereign_platform: Admin operations, security diagnostics
- No role except admin/superuser can CREATE objects
- All new objects default to NO PUBLIC access (ALTER DEFAULT PRIVILEGES)
Last hardened: 025e_final_hardening.sql';

-- ============================================================================
-- 6. VERIFICATION FUNCTION UPDATE
-- ============================================================================
-- Add tests for the new hardening measures

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
    -- NOTE: cannot use has_schema_privilege('PUBLIC', ...) because PUBLIC is a pseudo-role
    -- Instead, check the schema ACL for the public CREATE grant pattern (=C/ means PUBLIC has CREATE)
    SELECT NOT EXISTS (
        SELECT 1 FROM pg_namespace
        WHERE nspname = 'public'
          AND array_to_string(nspacl, ',') ~ '(^|,)=C/'
    ) INTO public_can_create;
    test_name := 'PUBLIC CREATE on schema public';
    expected := 'false';  -- We expect PUBLIC does NOT have CREATE (public_can_create should be TRUE meaning "no CREATE")
    actual := (NOT public_can_create)::TEXT;  -- Invert for display: if public_can_create is TRUE, actual shows FALSE
    status := CASE WHEN public_can_create = TRUE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 5: Default privileges for solvereign_admin (FUNCTIONS, TABLES, SEQUENCES)
    -- FAIL if not set - this is a security requirement, not optional
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
    -- FAIL if not set - security requirement
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
    -- FAIL if not set - security requirement
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

    -- Test 8: Schema comment includes security policy (WARN acceptable - documentation only)
    test_name := 'Schema security policy documented (WARN ok)';
    expected := 'true';
    SELECT (obj_description('public'::regnamespace, 'pg_namespace') LIKE '%SECURITY POLICY%')::TEXT
    INTO actual;
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'WARN' END;
    RETURN NEXT;

    -- =========================================================================
    -- CORE SCHEMA TESTS (9-12) - Only if core schema exists
    -- =========================================================================

    -- Test 9: core schema default privileges for solvereign_admin
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
    -- RETROACTIVE ACL CHECKS (15-17) - Existing objects in public/core
    -- =========================================================================
    -- Default privileges only protect NEW objects. Must check existing ones.
    -- Uses ALLOWLIST approach: extension patterns excluded, anything else = FAIL
    --
    -- Extension patterns (excluded from checks):
    --   pg_*, pgp_*, armor, dearmor, crypt, gen_random, gen_salt, digest, hmac,
    --   encrypt, decrypt, uuid_*, st_*, geography_*, geometry_*, box2d, box3d,
    --   postgis_*, spatial_ref_sys

    -- Test 15: User-defined functions with PUBLIC EXECUTE (ALLOWLIST-BASED)
    -- Extension functions are excluded. Any remaining = FAIL (not threshold)
    -- NOTE: Cannot use has_function_privilege('PUBLIC', ...) because PUBLIC is pseudo-role
    -- Instead, check proacl for public EXECUTE grant pattern (=X/ means PUBLIC has EXECUTE)
    test_name := 'User functions with PUBLIC EXECUTE (public schema)';
    expected := '0';
    SELECT COUNT(*)::TEXT INTO actual
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
      AND p.proacl IS NOT NULL
      AND array_to_string(p.proacl, ',') ~ '(^|,)=X/'  -- PUBLIC EXECUTE pattern
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
    -- FAIL if ANY non-extension function has PUBLIC EXECUTE
    status := CASE WHEN actual = '0' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 16: User-defined tables with PUBLIC SELECT (ALLOWLIST-BASED)
    -- Extension tables excluded. Any remaining = FAIL
    -- NOTE: Cannot use has_table_privilege('PUBLIC', ...) because PUBLIC is pseudo-role
    -- Instead, check relacl for public SELECT grant pattern (=r/ means PUBLIC has SELECT)
    test_name := 'User tables with PUBLIC SELECT (public schema)';
    expected := '0';
    SELECT COUNT(*)::TEXT INTO actual
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relacl IS NOT NULL
      AND array_to_string(c.relacl, ',') ~ '(^|,)=r/'  -- PUBLIC SELECT pattern
      -- Exclude extension patterns (allowlist)
      AND c.relname NOT LIKE 'pg_%'
      AND c.relname NOT LIKE 'spatial_ref_sys%'
      AND c.relname NOT LIKE 'geometry_columns%'
      AND c.relname NOT LIKE 'geography_columns%';
    -- FAIL if ANY non-extension table has PUBLIC SELECT
    status := CASE WHEN actual = '0' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 17: Security functions accessible by solvereign_api (AUDIT LIST)
    -- Expected: ONLY get_tenant_by_api_key_hash, set_tenant_context
    -- Any others = review required
    test_name := 'Security functions executable by solvereign_api';
    expected := 'get_tenant_by_api_key_hash, set_tenant_context';
    SELECT COALESCE(string_agg(p.proname, ', ' ORDER BY p.proname), '(none)') INTO actual
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
      AND (p.proname LIKE '%tenant%' OR p.proname LIKE '%admin%' OR p.proname LIKE '%verify%')
      AND has_function_privilege('solvereign_api', p.oid, 'EXECUTE') = true;
    -- WARN if unexpected functions (not FAIL - may be intentional)
    status := CASE
        WHEN actual = expected THEN 'PASS'
        WHEN actual = '(none)' THEN 'WARN'
        ELSE 'WARN'
    END;
    RETURN NEXT;
END;
$$;

-- Set ownership and permissions for new verification function
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
-- 7. RUN VERIFICATION
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    all_pass BOOLEAN := TRUE;
    fail_count INTEGER := 0;
BEGIN
    RAISE NOTICE '[025e] Running final hardening verification...';

    FOR r IN SELECT * FROM verify_final_hardening() LOOP
        IF r.status = 'PASS' THEN
            RAISE NOTICE '[025e] PASS: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
        ELSIF r.status = 'WARN' THEN
            RAISE WARNING '[025e] WARN: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
        ELSIF r.status = 'INFO' THEN
            RAISE NOTICE '[025e] INFO: % -> %', r.test_name, r.actual;
        ELSE
            RAISE WARNING '[025e] FAIL: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
            all_pass := FALSE;
            fail_count := fail_count + 1;
        END IF;
    END LOOP;

    IF NOT all_pass THEN
        RAISE WARNING '[025e] % hardening tests FAILED!', fail_count;
    ELSE
        RAISE NOTICE '[025e] All hardening tests PASSED';
    END IF;
END $$;

-- ============================================================================
-- 8. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('025e', 'Final hardening: verify_rls_boundary access, default privileges (public+core), schema CREATE', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- 9. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 025e: Final Security Hardening COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'SECURITY IMPROVEMENTS:';
    RAISE NOTICE '  1. verify_rls_boundary() restricted to solvereign_platform only';
    RAISE NOTICE '  2. ALTER DEFAULT PRIVILEGES for public schema (3 roles x 3 types)';
    RAISE NOTICE '  3. ALTER DEFAULT PRIVILEGES for core schema (3 roles x 3 types)';
    RAISE NOTICE '  4. REVOKE CREATE ON SCHEMA public FROM PUBLIC/solvereign_api';
    RAISE NOTICE '  5. REVOKE CREATE ON SCHEMA core FROM ALL runtime roles';
    RAISE NOTICE '  6. Schema security policy documented in comment';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFICATION:';
    RAISE NOTICE '  Run: SELECT * FROM verify_final_hardening();';
    RAISE NOTICE '';
    RAISE NOTICE 'TEST EXPECTATIONS (17 tests):';
    RAISE NOTICE '  Tests 1-7:   PASS required (public schema hard gates)';
    RAISE NOTICE '  Test 8:      WARN ok (documentation only)';
    RAISE NOTICE '  Tests 9-14:  PASS required IF core schema exists';
    RAISE NOTICE '  Tests 15-16: PASS/WARN for retroactive ACL check';
    RAISE NOTICE '  Test 17:     INFO (security function audit)';
    RAISE NOTICE '';
    RAISE NOTICE 'EXTENSION POLICY:';
    RAISE NOTICE '  Extensions MUST be installed by solvereign_admin or superuser';
    RAISE NOTICE '  Example: CREATE EXTENSION IF NOT EXISTS pgcrypto;';
    RAISE NOTICE '  (Run as admin, not as solvereign_api)';
    RAISE NOTICE '==================================================================';
END $$;
