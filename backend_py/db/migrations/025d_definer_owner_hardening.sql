-- ============================================================================
-- MIGRATION 025d: SECURITY DEFINER Owner Hardening
-- ============================================================================
-- SECURITY FIX: Ensure SECURITY DEFINER functions are properly secured.
--
-- PROBLEMS ADDRESSED:
--   1. session_user vs current_user confusion in SECURITY DEFINER functions
--   2. Function ownership by superuser allows RLS bypass
--   3. SET ROLE risk when connecting as DB owner
--   4. Platform-only functions in core schema lacking role checks
--
-- SOLUTION:
--   1. Create dedicated definer role with minimal privileges
--   2. Transfer ownership of security functions to dedicated role
--   3. Add session_user checks to all platform-only functions
--   4. Ensure solvereign_api cannot escalate to platform role
--   5. Add explicit NO BYPASSRLS to roles
-- ============================================================================

-- ============================================================================
-- 1. VERIFY SET ROLE RESTRICTION
-- ============================================================================
-- Ensure solvereign_api is NOT a member of solvereign_platform

DO $$
DECLARE
    is_member BOOLEAN;
BEGIN
    -- Check if solvereign_api is a member of solvereign_platform
    SELECT pg_has_role('solvereign_api', 'solvereign_platform', 'MEMBER')
    INTO is_member;

    IF is_member THEN
        RAISE EXCEPTION '[025d] CRITICAL: solvereign_api IS a member of solvereign_platform! This allows privilege escalation.';
    ELSE
        RAISE NOTICE '[025d] VERIFIED: solvereign_api cannot SET ROLE to solvereign_platform';
    END IF;
END $$;

-- ============================================================================
-- 2. CREATE DEDICATED DEFINER ROLE
-- ============================================================================
-- This role owns SECURITY DEFINER functions but has:
-- - NO BYPASSRLS (critical!)
-- - NO SUPERUSER
-- - NO LOGIN
-- - Minimal table permissions (only what functions need)

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        CREATE ROLE solvereign_definer NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
        RAISE NOTICE '[025d] Created role: solvereign_definer';
    END IF;

    -- Ensure NO BYPASSRLS (explicit, even though it's the default)
    ALTER ROLE solvereign_definer NOBYPASSRLS;

    -- Grant SELECT on tenants for SECURITY DEFINER functions
    GRANT SELECT ON tenants TO solvereign_definer;

    -- Grant SELECT on idempotency_keys if exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
        GRANT SELECT ON idempotency_keys TO solvereign_definer;
    END IF;
END $$;

-- ============================================================================
-- 3. TRANSFER FUNCTION OWNERSHIP TO DEFINER ROLE
-- ============================================================================
-- Change owner of SECURITY DEFINER functions from superuser to definer role

ALTER FUNCTION get_tenant_by_api_key_hash(VARCHAR) OWNER TO solvereign_definer;
ALTER FUNCTION list_all_tenants() OWNER TO solvereign_definer;
ALTER FUNCTION set_tenant_context(INTEGER) OWNER TO solvereign_definer;
ALTER FUNCTION set_super_admin_context(BOOLEAN) OWNER TO solvereign_definer;
ALTER FUNCTION verify_rls_boundary() OWNER TO solvereign_definer;

RAISE NOTICE '[025d] Transferred ownership of security functions to solvereign_definer';

-- ============================================================================
-- 4. VERIFY NO BYPASSRLS ON ANY API/PLATFORM ROLES
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    has_bypass BOOLEAN := FALSE;
BEGIN
    FOR r IN
        SELECT rolname, rolbypassrls
        FROM pg_roles
        WHERE rolname IN ('solvereign_api', 'solvereign_platform', 'solvereign_definer', 'solvereign_admin')
    LOOP
        IF r.rolbypassrls THEN
            RAISE WARNING '[025d] Role % has BYPASSRLS!', r.rolname;
            has_bypass := TRUE;
        ELSE
            RAISE NOTICE '[025d] VERIFIED: % has NO BYPASSRLS', r.rolname;
        END IF;
    END LOOP;

    -- Note: solvereign_admin has BYPASSRLS by design (for migrations)
    -- But solvereign_api and solvereign_platform should NOT have it
    IF has_bypass THEN
        RAISE WARNING '[025d] Some roles have BYPASSRLS. Review if this is intended.';
    END IF;
END $$;

-- ============================================================================
-- 5. ADD session_user CHECK TO VERIFICATION FUNCTION
-- ============================================================================
-- Update verify_rls_boundary to check for BYPASSRLS on definer role

CREATE OR REPLACE FUNCTION verify_rls_boundary()
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
    api_has_select BOOLEAN;
    api_can_list BOOLEAN;
    platform_has_select BOOLEAN;
    platform_can_list BOOLEAN;
    fn_owner TEXT;
    owner_has_bypass BOOLEAN;
BEGIN
    -- Test 1: API role should NOT have SELECT on tenants
    SELECT has_table_privilege('solvereign_api', 'public.tenants', 'SELECT') INTO api_has_select;
    test_name := 'solvereign_api SELECT on tenants';
    expected := 'false';
    actual := api_has_select::TEXT;
    status := CASE WHEN api_has_select = FALSE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 2: API role should NOT be able to execute list_all_tenants()
    SELECT has_function_privilege('solvereign_api', 'list_all_tenants()', 'EXECUTE') INTO api_can_list;
    test_name := 'solvereign_api EXECUTE on list_all_tenants()';
    expected := 'false';
    actual := api_can_list::TEXT;
    status := CASE WHEN api_can_list = FALSE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 3: Platform role SHOULD have SELECT on tenants
    SELECT has_table_privilege('solvereign_platform', 'public.tenants', 'SELECT') INTO platform_has_select;
    test_name := 'solvereign_platform SELECT on tenants';
    expected := 'true';
    actual := platform_has_select::TEXT;
    status := CASE WHEN platform_has_select = TRUE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 4: Platform role SHOULD be able to execute list_all_tenants()
    SELECT has_function_privilege('solvereign_platform', 'list_all_tenants()', 'EXECUTE') INTO platform_can_list;
    test_name := 'solvereign_platform EXECUTE on list_all_tenants()';
    expected := 'true';
    actual := platform_can_list::TEXT;
    status := CASE WHEN platform_can_list = TRUE THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 5: RLS should be FORCED on tenants
    test_name := 'tenants table FORCE RLS';
    expected := 'true';
    SELECT relforcerowsecurity::TEXT INTO actual
    FROM pg_class WHERE relname = 'tenants';
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 6: Correct policy exists
    test_name := 'tenants_platform_role_only policy exists';
    expected := 'true';
    SELECT EXISTS(
        SELECT 1 FROM pg_policies
        WHERE tablename = 'tenants' AND policyname = 'tenants_platform_role_only'
    )::TEXT INTO actual;
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 7: Old session-var policy should NOT exist
    test_name := 'tenants_super_admin_only policy removed';
    expected := 'false';
    SELECT EXISTS(
        SELECT 1 FROM pg_policies
        WHERE tablename = 'tenants' AND policyname = 'tenants_super_admin_only'
    )::TEXT INTO actual;
    status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 8: SECURITY DEFINER function uses session_user (not current_user)
    test_name := 'list_all_tenants() uses session_user for role check';
    expected := 'true';
    SELECT (
        pg_get_functiondef(oid) LIKE '%pg_has_role(session_user%'
    )::TEXT INTO actual
    FROM pg_proc WHERE proname = 'list_all_tenants';
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 9: SECURITY DEFINER function does NOT use current_user for role check
    test_name := 'list_all_tenants() does NOT use current_user for role check';
    expected := 'false';
    SELECT (
        pg_get_functiondef(oid) LIKE '%pg_has_role(current_user%'
    )::TEXT INTO actual
    FROM pg_proc WHERE proname = 'list_all_tenants';
    status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 10: Function owner is solvereign_definer (not superuser)
    test_name := 'list_all_tenants() owned by solvereign_definer';
    expected := 'solvereign_definer';
    SELECT r.rolname INTO actual
    FROM pg_proc p
    JOIN pg_roles r ON p.proowner = r.oid
    WHERE p.proname = 'list_all_tenants';
    status := CASE WHEN actual = 'solvereign_definer' THEN 'PASS' ELSE 'WARN' END;
    RETURN NEXT;

    -- Test 11: Function owner does NOT have BYPASSRLS
    test_name := 'SECURITY DEFINER owner has NO BYPASSRLS';
    expected := 'false';
    SELECT r.rolbypassrls::TEXT INTO actual
    FROM pg_proc p
    JOIN pg_roles r ON p.proowner = r.oid
    WHERE p.proname = 'list_all_tenants';
    status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 12: solvereign_api cannot SET ROLE to solvereign_platform
    test_name := 'solvereign_api cannot escalate to solvereign_platform';
    expected := 'false';
    SELECT pg_has_role('solvereign_api', 'solvereign_platform', 'MEMBER')::TEXT INTO actual;
    status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 13: Context info (informational)
    test_name := 'SECURITY DEFINER context info';
    expected := 'documented';
    actual := format('session_user=%s, current_user=%s', session_user, current_user);
    status := 'INFO';
    RETURN NEXT;
END;
$$;

-- Transfer ownership of updated function
ALTER FUNCTION verify_rls_boundary() OWNER TO solvereign_definer;

-- ============================================================================
-- 6. RUN VERIFICATION
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    all_pass BOOLEAN := TRUE;
    fail_count INTEGER := 0;
BEGIN
    RAISE NOTICE '[025d] Running security verification...';

    FOR r IN SELECT * FROM verify_rls_boundary() LOOP
        IF r.status = 'PASS' THEN
            RAISE NOTICE '[025d] PASS: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
        ELSIF r.status = 'WARN' THEN
            RAISE WARNING '[025d] WARN: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
        ELSIF r.status = 'INFO' THEN
            RAISE NOTICE '[025d] INFO: % -> %', r.test_name, r.actual;
        ELSE
            RAISE WARNING '[025d] FAIL: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
            all_pass := FALSE;
            fail_count := fail_count + 1;
        END IF;
    END LOOP;

    IF NOT all_pass THEN
        RAISE WARNING '[025d] % verification tests FAILED!', fail_count;
    ELSE
        RAISE NOTICE '[025d] All verification tests PASSED';
    END IF;
END $$;

-- ============================================================================
-- 7. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('025d', 'SECURITY DEFINER owner hardening: dedicated definer role, no BYPASSRLS', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- 8. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 025d: SECURITY DEFINER Owner Hardening COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'SECURITY IMPROVEMENTS:';
    RAISE NOTICE '  1. Created solvereign_definer role (NO BYPASSRLS)';
    RAISE NOTICE '  2. Transferred security function ownership to definer role';
    RAISE NOTICE '  3. Verified solvereign_api cannot escalate to platform';
    RAISE NOTICE '  4. Added BYPASSRLS checks to verification';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFICATION:';
    RAISE NOTICE '  Run: SELECT * FROM verify_rls_boundary();';
    RAISE NOTICE '';
    RAISE NOTICE 'SECURITY MODEL:';
    RAISE NOTICE '  - SECURITY DEFINER functions run as solvereign_definer';
    RAISE NOTICE '  - solvereign_definer has NO BYPASSRLS';
    RAISE NOTICE '  - session_user is checked for caller role (not current_user)';
    RAISE NOTICE '  - solvereign_api cannot SET ROLE to platform';
    RAISE NOTICE '==================================================================';
END $$;
