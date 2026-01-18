-- ============================================================================
-- MIGRATION 025c: RLS Boundary Fix - Replace Session Variable with Role Checks
-- ============================================================================
-- SECURITY FIX: Closes the remaining RLS boundary hole.
--
-- PROBLEM:
--   RLS policies rely on app.is_super_admin session variable which ANY
--   connection can set via: SET app.is_super_admin = 'true'
--   This is NOT a hard database boundary.
--
-- SOLUTION:
--   1. Replace session-variable checks with pg_has_role() checks
--   2. REVOKE direct table access from solvereign_api on tenants
--   3. All tenants access MUST go through SECURITY DEFINER functions
--   4. Only solvereign_platform role can access tenants directly
--
-- SECURITY MODEL:
--   solvereign_api:
--     - NO direct SELECT/INSERT/UPDATE/DELETE on tenants
--     - CAN call get_tenant_by_api_key_hash() for auth
--     - CAN call set_tenant_context() for tenant context
--     - CANNOT bypass RLS even with SET app.is_super_admin = 'true'
--
--   solvereign_platform:
--     - Full access to tenants table (role-based RLS allows it)
--     - CAN call list_all_tenants()
--     - Typically used via SET ROLE from superuser connection
-- ============================================================================

-- ============================================================================
-- 0. VERIFY ROLES EXIST
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        CREATE ROLE solvereign_api NOLOGIN NOINHERIT;
        RAISE NOTICE '[025c] Created role: solvereign_api';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        CREATE ROLE solvereign_platform NOLOGIN NOINHERIT;
        RAISE NOTICE '[025c] Created role: solvereign_platform';
    END IF;
END $$;

-- ============================================================================
-- 1. DROP OLD SESSION-VARIABLE BASED POLICY ON TENANTS
-- ============================================================================

DROP POLICY IF EXISTS tenants_super_admin_only ON tenants;

-- ============================================================================
-- 2. CREATE NEW ROLE-BASED POLICY ON TENANTS
-- ============================================================================
-- Uses pg_has_role() which cannot be spoofed by setting session variables.
-- Only members of solvereign_platform role can access tenants table directly.

CREATE POLICY tenants_platform_role_only ON tenants
    FOR ALL
    USING (
        -- Check if current user/role is a member of solvereign_platform
        -- This works with both direct login and SET ROLE
        pg_has_role(current_user, 'solvereign_platform', 'MEMBER')
    )
    WITH CHECK (
        pg_has_role(current_user, 'solvereign_platform', 'MEMBER')
    );

COMMENT ON POLICY tenants_platform_role_only ON tenants IS
'ROLE-BASED RLS: Only solvereign_platform role members can access tenants table.
This CANNOT be bypassed by setting session variables.
API role uses SECURITY DEFINER functions for auth operations.';

-- ============================================================================
-- 3. REVOKE DIRECT TABLE ACCESS FROM API ROLE
-- ============================================================================
-- CRITICAL: solvereign_api should NOT have direct table access to tenants.
-- All operations go through SECURITY DEFINER functions.

REVOKE ALL ON tenants FROM solvereign_api;

-- Verify the revoke worked
DO $$
DECLARE
    has_select BOOLEAN;
BEGIN
    SELECT has_table_privilege('solvereign_api', 'tenants', 'SELECT') INTO has_select;
    IF has_select THEN
        RAISE EXCEPTION '[025c] CRITICAL: Failed to revoke SELECT on tenants from solvereign_api!';
    ELSE
        RAISE NOTICE '[025c] VERIFIED: solvereign_api has NO direct access to tenants';
    END IF;
END $$;

-- ============================================================================
-- 4. DROP OLD SESSION-VARIABLE BASED POLICY ON IDEMPOTENCY_KEYS
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
        DROP POLICY IF EXISTS idempotency_keys_tenant_isolation ON idempotency_keys;
        RAISE NOTICE '[025c] Dropped old idempotency_keys_tenant_isolation policy';
    END IF;
END $$;

-- ============================================================================
-- 5. CREATE NEW ROLE-BASED POLICY ON IDEMPOTENCY_KEYS
-- ============================================================================
-- Uses tenant context for normal operations, role check for platform admin.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
        CREATE POLICY idempotency_keys_tenant_or_platform ON idempotency_keys
            FOR ALL
            USING (
                -- Tenant-scoped access: match current tenant context
                tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                -- OR platform role has full access (role-based, not session var)
                OR pg_has_role(current_user, 'solvereign_platform', 'MEMBER')
            )
            WITH CHECK (
                tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR pg_has_role(current_user, 'solvereign_platform', 'MEMBER')
            );

        COMMENT ON POLICY idempotency_keys_tenant_or_platform ON idempotency_keys IS
        'ROLE-BASED RLS: Tenant isolation via current_tenant_id context.
         Platform role has full access (cannot be spoofed).';

        RAISE NOTICE '[025c] Created new idempotency_keys_tenant_or_platform policy';
    END IF;
END $$;

-- ============================================================================
-- 6. UPDATE list_all_tenants() TO USE ROLE CHECK
-- ============================================================================
-- Replace session variable check with role membership check.

CREATE OR REPLACE FUNCTION list_all_tenants()
RETURNS TABLE (
    id INTEGER,
    name VARCHAR(255),
    is_active BOOLEAN,
    created_at TIMESTAMPTZ
    -- NOTE: api_key_hash is intentionally NOT returned (security)
)
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- ROLE-BASED CHECK: Only platform role members can list all tenants
    -- This CANNOT be bypassed by setting session variables
    --
    -- CRITICAL: Must use session_user, NOT current_user!
    -- In SECURITY DEFINER functions, current_user is the function OWNER,
    -- not the caller. session_user is the original authenticated user.
    IF NOT pg_has_role(session_user, 'solvereign_platform', 'MEMBER') THEN
        RAISE EXCEPTION 'Access denied: requires solvereign_platform role membership (session_user=%, current_user=%)',
            session_user, current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    RETURN QUERY
    SELECT
        t.id,
        t.name,
        t.is_active,
        t.created_at
        -- SECURITY: api_key_hash is NOT selected
    FROM public.tenants t
    ORDER BY t.id;
END;
$$;

COMMENT ON FUNCTION list_all_tenants IS
'Lists all tenants (platform role only). Does NOT return api_key_hash.
ROLE-BASED: Uses pg_has_role() check that cannot be spoofed.';

-- ============================================================================
-- 7. UPDATE set_super_admin_context() - DEPRECATE BUT KEEP FOR COMPAT
-- ============================================================================
-- This function is now deprecated. It sets a session var that has NO effect.
-- Keeping for backward compatibility but it does nothing useful.

CREATE OR REPLACE FUNCTION set_super_admin_context(is_admin BOOLEAN)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- DEPRECATED: This function now has NO EFFECT on RLS policies.
    -- RLS policies use pg_has_role() which cannot be influenced by session vars.
    -- This function is kept for backward compatibility only.
    --
    -- To get platform admin access:
    --   1. Connect as a user that is a member of solvereign_platform role
    --   2. Or use SET ROLE solvereign_platform (if permitted)
    --
    RAISE WARNING 'set_super_admin_context() is DEPRECATED and has no effect. '
                  'RLS now uses role-based checks. Use SET ROLE solvereign_platform instead.';

    -- Still set the variable for any legacy code that might check it
    IF is_admin THEN
        PERFORM set_config('app.is_super_admin', 'true', true);
    ELSE
        PERFORM set_config('app.is_super_admin', 'false', true);
    END IF;
END;
$$;

COMMENT ON FUNCTION set_super_admin_context IS
'DEPRECATED: This function has no effect on RLS policies.
RLS now uses role-based checks via pg_has_role().
Use SET ROLE solvereign_platform for admin access.';

-- ============================================================================
-- 8. ENSURE FUNCTION GRANTS ARE CORRECT
-- ============================================================================

-- API role: auth and tenant context only
REVOKE ALL ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) TO solvereign_api;

REVOKE ALL ON FUNCTION set_tenant_context(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION set_tenant_context(INTEGER) TO solvereign_api;

-- Platform role: admin functions
REVOKE ALL ON FUNCTION list_all_tenants() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION list_all_tenants() TO solvereign_platform;

-- Deprecated function - keep grants for backward compat warnings
REVOKE ALL ON FUNCTION set_super_admin_context(BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION set_super_admin_context(BOOLEAN) TO solvereign_api;
GRANT EXECUTE ON FUNCTION set_super_admin_context(BOOLEAN) TO solvereign_platform;

-- API role CANNOT list all tenants
REVOKE ALL ON FUNCTION list_all_tenants() FROM solvereign_api;

-- ============================================================================
-- 9. GRANT PLATFORM ROLE TABLE ACCESS (RLS will filter)
-- ============================================================================

-- Platform role needs table grants for RLS policy to work
GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO solvereign_platform;

-- ============================================================================
-- 10. CREATE VERIFICATION FUNCTION
-- ============================================================================

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
    policy_qual TEXT;
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
    -- Verify list_all_tenants() source contains 'session_user' for role check
    test_name := 'list_all_tenants() uses session_user for role check';
    expected := 'true';
    SELECT (
        pg_get_functiondef(oid) LIKE '%pg_has_role(session_user%'
    )::TEXT INTO actual
    FROM pg_proc WHERE proname = 'list_all_tenants';
    status := CASE WHEN actual = 'true' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 9: SECURITY DEFINER function does NOT use current_user for role check
    -- (current_user would be function owner, not caller - security bug!)
    test_name := 'list_all_tenants() does NOT use current_user for role check';
    expected := 'false';
    SELECT (
        pg_get_functiondef(oid) LIKE '%pg_has_role(current_user%'
    )::TEXT INTO actual
    FROM pg_proc WHERE proname = 'list_all_tenants';
    status := CASE WHEN actual = 'false' THEN 'PASS' ELSE 'FAIL' END;
    RETURN NEXT;

    -- Test 10: Verify session_user vs current_user behavior in this SECURITY DEFINER context
    -- In SECURITY DEFINER, current_user = function owner, session_user = caller
    test_name := 'SECURITY DEFINER context: session_user != current_user (if not superuser)';
    expected := 'documented';
    actual := format('session_user=%s, current_user=%s', session_user, current_user);
    -- This is informational - session_user should be the connection user
    status := 'INFO';
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION verify_rls_boundary IS
'Verification function for RLS boundary fix. Run after migration.';

-- ============================================================================
-- 11. RUN VERIFICATION
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    all_pass BOOLEAN := TRUE;
BEGIN
    RAISE NOTICE '[025c] Running RLS boundary verification...';

    FOR r IN SELECT * FROM verify_rls_boundary() LOOP
        IF r.status = 'PASS' THEN
            RAISE NOTICE '[025c] PASS: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
        ELSIF r.status = 'INFO' THEN
            -- Informational tests don't affect pass/fail status
            RAISE NOTICE '[025c] INFO: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
        ELSE
            RAISE WARNING '[025c] FAIL: % (expected=%, actual=%)', r.test_name, r.expected, r.actual;
            all_pass := FALSE;
        END IF;
    END LOOP;

    IF NOT all_pass THEN
        RAISE EXCEPTION '[025c] RLS boundary verification FAILED!';
    END IF;

    RAISE NOTICE '[025c] All verification tests PASSED';
END $$;

-- ============================================================================
-- 12. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('025c', 'RLS boundary fix: role-based checks replace session variables', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- 13. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 025c: RLS Boundary Fix COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'SECURITY IMPROVEMENTS:';
    RAISE NOTICE '  1. RLS policies now use pg_has_role() - CANNOT be spoofed';
    RAISE NOTICE '  2. solvereign_api has NO direct access to tenants table';
    RAISE NOTICE '  3. list_all_tenants() uses role check, not session var';
    RAISE NOTICE '  4. set_super_admin_context() is now DEPRECATED (no-op)';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFICATION:';
    RAISE NOTICE '  Run: SELECT * FROM verify_rls_boundary();';
    RAISE NOTICE '';
    RAISE NOTICE 'TEST THE FIX:';
    RAISE NOTICE '  -- This should now FAIL (returns 0 rows):';
    RAISE NOTICE '  SET ROLE solvereign_api;';
    RAISE NOTICE '  SET app.is_super_admin = ''true'';  -- Has no effect now!';
    RAISE NOTICE '  SELECT * FROM tenants;  -- Returns 0 rows';
    RAISE NOTICE '';
    RAISE NOTICE '  -- This should WORK:';
    RAISE NOTICE '  SET ROLE solvereign_platform;';
    RAISE NOTICE '  SELECT * FROM tenants;  -- Returns all tenants';
    RAISE NOTICE '==================================================================';
END $$;
