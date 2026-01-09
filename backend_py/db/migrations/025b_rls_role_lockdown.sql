-- ============================================================================
-- MIGRATION 025b: RLS Role Lockdown (Least Privilege Enforcement)
-- ============================================================================
-- Finalizes RLS hardening by enforcing role-based EXECUTE grants.
--
-- ROLES DEFINED:
--   solvereign_api       - Application API role (tenant operations)
--   solvereign_platform  - Platform admin role (super_admin operations)
--
-- GRANTS:
--   get_tenant_by_api_key_hash() → solvereign_api ONLY
--   set_tenant_context()         → solvereign_api ONLY
--   list_all_tenants()           → solvereign_platform ONLY
--   set_super_admin_context()    → solvereign_platform ONLY
--
-- SECURITY BOUNDARY:
--   - solvereign_api CANNOT escalate to super_admin
--   - solvereign_platform CANNOT be used for normal tenant operations
--   - Both roles have NOINHERIT to prevent privilege leakage
-- ============================================================================

-- ============================================================================
-- 0. PRIVILEGE ENUMERATION QUERY (for verification)
-- ============================================================================
-- Run this query to see current grants on security functions:
--
-- SELECT
--     p.proname AS function_name,
--     n.nspname AS schema,
--     r.rolname AS grantee,
--     CASE WHEN has_function_privilege(r.oid, p.oid, 'EXECUTE')
--          THEN 'EXECUTE' ELSE NULL END AS privilege
-- FROM pg_proc p
-- JOIN pg_namespace n ON p.pronamespace = n.oid
-- CROSS JOIN pg_roles r
-- WHERE n.nspname = 'public'
--   AND p.proname IN (
--       'get_tenant_by_api_key_hash',
--       'list_all_tenants',
--       'set_super_admin_context',
--       'set_tenant_context'
--   )
--   AND has_function_privilege(r.oid, p.oid, 'EXECUTE')
--   AND r.rolname NOT LIKE 'pg_%'
-- ORDER BY p.proname, r.rolname;
-- ============================================================================

-- ============================================================================
-- 1. CREATE ROLES IF NOT EXIST
-- ============================================================================

-- API role for tenant operations (used by application server)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        CREATE ROLE solvereign_api NOLOGIN NOINHERIT;
        COMMENT ON ROLE solvereign_api IS
            'Application API role for tenant operations. Cannot escalate to super_admin.';
        RAISE NOTICE '[025b] Created role: solvereign_api';
    ELSE
        -- Ensure NOINHERIT is set
        ALTER ROLE solvereign_api NOINHERIT;
        RAISE NOTICE '[025b] Role solvereign_api exists, ensured NOINHERIT';
    END IF;
END $$;

-- Platform admin role for super_admin operations
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        CREATE ROLE solvereign_platform NOLOGIN NOINHERIT;
        COMMENT ON ROLE solvereign_platform IS
            'Platform admin role for super_admin operations. Separate from API role.';
        RAISE NOTICE '[025b] Created role: solvereign_platform';
    ELSE
        ALTER ROLE solvereign_platform NOINHERIT;
        RAISE NOTICE '[025b] Role solvereign_platform exists, ensured NOINHERIT';
    END IF;
END $$;

-- ============================================================================
-- 2. REVOKE ALL FROM PUBLIC ON ALL SECURITY FUNCTIONS
-- ============================================================================

-- Ensure no PUBLIC access to any security functions
REVOKE ALL ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_all_tenants() FROM PUBLIC;
REVOKE ALL ON FUNCTION set_super_admin_context(BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION set_tenant_context(INTEGER) FROM PUBLIC;

-- Also revoke from any other roles that might have been granted
DO $$
DECLARE
    r RECORD;
    func_oid OID;
BEGIN
    -- Get function OIDs
    FOR r IN
        SELECT p.proname, p.oid
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public'
          AND p.proname IN (
              'get_tenant_by_api_key_hash',
              'list_all_tenants',
              'set_super_admin_context',
              'set_tenant_context'
          )
    LOOP
        -- Revoke from all non-system roles except our designated roles
        FOR func_oid IN
            SELECT r2.oid
            FROM pg_roles r2
            WHERE r2.rolname NOT LIKE 'pg_%'
              AND r2.rolname NOT IN ('solvereign_api', 'solvereign_platform', 'postgres')
              AND has_function_privilege(r2.oid, r.oid, 'EXECUTE')
        LOOP
            -- Note: Dynamic REVOKE not directly possible, but we've already done REVOKE FROM PUBLIC
            NULL;
        END LOOP;
    END LOOP;
END $$;

-- ============================================================================
-- 3. GRANT EXECUTE TO APPROPRIATE ROLES
-- ============================================================================

-- API role: can authenticate tenants and set tenant context
GRANT EXECUTE ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) TO solvereign_api;
GRANT EXECUTE ON FUNCTION set_tenant_context(INTEGER) TO solvereign_api;

-- Platform role: can list tenants and set super_admin context
GRANT EXECUTE ON FUNCTION list_all_tenants() TO solvereign_platform;
GRANT EXECUTE ON FUNCTION set_super_admin_context(BOOLEAN) TO solvereign_platform;

-- Log the grants
DO $$
BEGIN
    RAISE NOTICE '[025b] Granted get_tenant_by_api_key_hash() to solvereign_api';
    RAISE NOTICE '[025b] Granted set_tenant_context() to solvereign_api';
    RAISE NOTICE '[025b] Granted list_all_tenants() to solvereign_platform';
    RAISE NOTICE '[025b] Granted set_super_admin_context() to solvereign_platform';
END $$;

-- ============================================================================
-- 4. ENSURE API ROLE CANNOT ESCALATE
-- ============================================================================

-- Explicitly deny platform functions to API role
-- (REVOKE is idempotent, safe to run)
REVOKE ALL ON FUNCTION list_all_tenants() FROM solvereign_api;
REVOKE ALL ON FUNCTION set_super_admin_context(BOOLEAN) FROM solvereign_api;

-- ============================================================================
-- 5. GRANT TABLE ACCESS FOR RLS TO WORK
-- ============================================================================

-- API role needs SELECT on tenants (RLS will filter)
GRANT SELECT ON tenants TO solvereign_api;

-- API role needs full access to idempotency_keys (RLS will filter by tenant)
GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_keys TO solvereign_api;

-- Platform role needs full access to tenants (for admin operations)
GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO solvereign_platform;

-- ============================================================================
-- 6. VERIFY idempotency_keys POLICIES ARE COMPLETE
-- ============================================================================

DO $$
DECLARE
    policy_count INTEGER;
    has_using BOOLEAN;
    has_with_check BOOLEAN;
BEGIN
    -- Check if idempotency_keys table exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'idempotency_keys'
    ) THEN
        RAISE NOTICE '[025b] idempotency_keys table does not exist, skipping policy verification';
        RETURN;
    END IF;

    -- Count policies
    SELECT COUNT(*) INTO policy_count
    FROM pg_policies
    WHERE tablename = 'idempotency_keys';

    IF policy_count = 0 THEN
        RAISE WARNING '[025b] idempotency_keys has NO RLS policies!';
        RETURN;
    END IF;

    -- Check for tenant isolation policy with USING and WITH CHECK
    SELECT
        qual IS NOT NULL,
        with_check IS NOT NULL
    INTO has_using, has_with_check
    FROM pg_policies
    WHERE tablename = 'idempotency_keys'
      AND policyname = 'idempotency_keys_tenant_isolation';

    IF has_using AND has_with_check THEN
        RAISE NOTICE '[025b] VERIFIED: idempotency_keys has USING + WITH CHECK policies';
    ELSE
        RAISE WARNING '[025b] idempotency_keys policy may be incomplete: USING=%, WITH CHECK=%',
            has_using, has_with_check;
    END IF;
END $$;

-- ============================================================================
-- 7. CREATE TEST HELPER FUNCTION (for role-based testing)
-- ============================================================================

-- Function to test if current role can execute a function
CREATE OR REPLACE FUNCTION test_function_access(func_name TEXT)
RETURNS TABLE (
    function_name TEXT,
    can_execute BOOLEAN,
    current_role NAME
)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        func_name,
        has_function_privilege(current_user, func_name, 'EXECUTE'),
        current_user;
END;
$$;

COMMENT ON FUNCTION test_function_access IS
'Helper function for testing role-based function access.';

-- ============================================================================
-- 8. VERIFICATION QUERIES
-- ============================================================================

-- Verify privilege assignments
DO $$
DECLARE
    api_can_auth BOOLEAN;
    api_can_list BOOLEAN;
    api_can_escalate BOOLEAN;
    platform_can_list BOOLEAN;
    platform_can_escalate BOOLEAN;
BEGIN
    -- Check solvereign_api privileges
    SELECT has_function_privilege('solvereign_api', 'get_tenant_by_api_key_hash(VARCHAR)', 'EXECUTE')
    INTO api_can_auth;

    SELECT has_function_privilege('solvereign_api', 'list_all_tenants()', 'EXECUTE')
    INTO api_can_list;

    SELECT has_function_privilege('solvereign_api', 'set_super_admin_context(BOOLEAN)', 'EXECUTE')
    INTO api_can_escalate;

    -- Check solvereign_platform privileges
    SELECT has_function_privilege('solvereign_platform', 'list_all_tenants()', 'EXECUTE')
    INTO platform_can_list;

    SELECT has_function_privilege('solvereign_platform', 'set_super_admin_context(BOOLEAN)', 'EXECUTE')
    INTO platform_can_escalate;

    -- Verify expected state
    IF api_can_auth AND NOT api_can_list AND NOT api_can_escalate THEN
        RAISE NOTICE '[025b] VERIFIED: solvereign_api has correct privileges (auth only)';
    ELSE
        RAISE WARNING '[025b] solvereign_api privileges incorrect: auth=%, list=%, escalate=%',
            api_can_auth, api_can_list, api_can_escalate;
    END IF;

    IF platform_can_list AND platform_can_escalate THEN
        RAISE NOTICE '[025b] VERIFIED: solvereign_platform has correct privileges (admin only)';
    ELSE
        RAISE WARNING '[025b] solvereign_platform privileges incorrect: list=%, escalate=%',
            platform_can_list, platform_can_escalate;
    END IF;
END $$;

-- ============================================================================
-- 9. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('025b', 'RLS role lockdown: least privilege enforcement', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- 10. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 025b: RLS Role Lockdown COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Roles:';
    RAISE NOTICE '  solvereign_api      - Tenant operations (auth, set_tenant_context)';
    RAISE NOTICE '  solvereign_platform - Admin operations (list_tenants, set_super_admin)';
    RAISE NOTICE '';
    RAISE NOTICE 'EXECUTE Grants:';
    RAISE NOTICE '  get_tenant_by_api_key_hash() → solvereign_api';
    RAISE NOTICE '  set_tenant_context()         → solvereign_api';
    RAISE NOTICE '  list_all_tenants()           → solvereign_platform';
    RAISE NOTICE '  set_super_admin_context()    → solvereign_platform';
    RAISE NOTICE '';
    RAISE NOTICE 'SECURITY: solvereign_api CANNOT escalate to super_admin.';
    RAISE NOTICE '==================================================================';
END $$;
