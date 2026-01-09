-- ============================================================================
-- MIGRATION 025a: RLS Hardening Patch (Security Review Fixes)
-- ============================================================================
-- Applies security hardening to migration 025 functions:
--
-- FIXES:
--   1. Add SET search_path to prevent search_path hijacking attacks
--   2. Add is_active=TRUE filter to get_tenant_by_api_key_hash()
--   3. Add REVOKE FROM PUBLIC on list_all_tenants()
--   4. Add FORCE RLS on idempotency_keys table
--   5. Document app.is_super_admin security boundary
--
-- SECURITY NOTE: app.is_super_admin is a session variable that MUST only be
-- set by the application server. It is NOT a hard DB boundary. Connections
-- from untrusted sources (e.g., direct psql access) should use a separate
-- DB role without access to these functions.
-- ============================================================================

-- ============================================================================
-- 1. HARDEN get_tenant_by_api_key_hash() FUNCTION
-- ============================================================================
-- Fixes:
--   - Add SET search_path = pg_catalog, public (prevent hijacking)
--   - Add is_active = TRUE filter (reject inactive tenants at DB level)
--   - Ensure REVOKE FROM PUBLIC is applied

CREATE OR REPLACE FUNCTION get_tenant_by_api_key_hash(p_api_key_hash VARCHAR(64))
RETURNS TABLE (
    id INTEGER,
    name VARCHAR(255),
    is_active BOOLEAN,
    metadata JSONB,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
-- CRITICAL: Prevent search_path hijacking attacks
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- Only return ACTIVE tenants (inactive cannot authenticate)
    -- This is defense-in-depth; application should also check is_active
    RETURN QUERY
    SELECT
        t.id,
        t.name,
        t.is_active,
        t.metadata,
        t.created_at
    FROM public.tenants t
    WHERE t.api_key_hash = p_api_key_hash
      AND t.is_active = TRUE;  -- HARDENING: Reject inactive at DB level
END;
$$;

COMMENT ON FUNCTION get_tenant_by_api_key_hash IS
'SECURITY DEFINER: Bypasses RLS to lookup tenant by API key hash during authentication.
HARDENED: search_path fixed, only returns ACTIVE tenants.
Called before tenant context is established.';

-- Restrict execution: REVOKE from PUBLIC, GRANT only to API role
REVOKE ALL ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT EXECUTE ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) TO solvereign_api;
        RAISE NOTICE '[025a] Granted EXECUTE on get_tenant_by_api_key_hash to solvereign_api';
    ELSE
        RAISE WARNING '[025a] Role solvereign_api not found - function not granted to any role!';
    END IF;
END $$;

-- ============================================================================
-- 2. HARDEN list_all_tenants() FUNCTION
-- ============================================================================
-- Fixes:
--   - Add SET search_path = pg_catalog, public
--   - REVOKE FROM PUBLIC (was missing!)
--   - Ensure output does NOT include api_key_hash (already correct)

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
-- CRITICAL: Prevent search_path hijacking attacks
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- Only allow if super_admin flag is set
    -- SECURITY NOTE: app.is_super_admin must ONLY be set by the application server.
    -- Direct database connections should use a role without EXECUTE on this function.
    IF current_setting('app.is_super_admin', true) IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION 'Access denied: requires super_admin'
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
'Lists all tenants (super_admin only). Does NOT return api_key_hash.
HARDENED: search_path fixed, REVOKE FROM PUBLIC applied.
SECURITY: app.is_super_admin must only be set by application server.';

-- Restrict execution: REVOKE from PUBLIC, GRANT only to API role
REVOKE ALL ON FUNCTION list_all_tenants() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT EXECUTE ON FUNCTION list_all_tenants() TO solvereign_api;
        RAISE NOTICE '[025a] Granted EXECUTE on list_all_tenants to solvereign_api';
    ELSE
        RAISE WARNING '[025a] Role solvereign_api not found - function not granted to any role!';
    END IF;
END $$;

-- ============================================================================
-- 3. ADD FORCE RLS ON idempotency_keys
-- ============================================================================
-- FORCE RLS ensures RLS applies even to table owner

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
        -- Enable FORCE RLS (defense in depth)
        ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;
        RAISE NOTICE '[025a] FORCE RLS enabled on idempotency_keys';
    ELSE
        RAISE NOTICE '[025a] idempotency_keys table does not exist, skipping FORCE RLS';
    END IF;
END $$;

-- ============================================================================
-- 4. DOCUMENT SECURITY BOUNDARY FOR app.is_super_admin
-- ============================================================================
-- Create a function to safely set super_admin context (for documentation)

CREATE OR REPLACE FUNCTION set_super_admin_context(is_admin BOOLEAN)
RETURNS VOID
LANGUAGE plpgsql
-- CRITICAL: Prevent search_path hijacking attacks
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- SECURITY WARNING:
    -- This function sets the app.is_super_admin session variable.
    -- It MUST only be called by the application server, never by untrusted code.
    --
    -- The app.is_super_admin variable is NOT a hard database boundary.
    -- Any connection can technically call SET app.is_super_admin = 'true'.
    --
    -- DEFENSE STRATEGY:
    -- 1. Use separate DB roles for application vs admin connections
    -- 2. REVOKE EXECUTE on sensitive functions from non-admin roles
    -- 3. Use connection pooling that prevents direct SET commands
    -- 4. Audit log any super_admin context activation
    --
    -- For true isolation, consider:
    -- - Separate database role for platform admin operations
    -- - Network-level isolation (different connection strings)
    -- - Mutual TLS for admin connections

    IF is_admin THEN
        PERFORM set_config('app.is_super_admin', 'true', true);  -- true = LOCAL (transaction-scoped)
    ELSE
        PERFORM set_config('app.is_super_admin', 'false', true);
    END IF;
END;
$$;

COMMENT ON FUNCTION set_super_admin_context IS
'Sets super_admin context. SECURITY: Must only be called by application server.
See function body for security boundary documentation.';

-- Restrict execution
REVOKE ALL ON FUNCTION set_super_admin_context(BOOLEAN) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT EXECUTE ON FUNCTION set_super_admin_context(BOOLEAN) TO solvereign_api;
    END IF;
END $$;

-- ============================================================================
-- 5. CREATE HELPER FUNCTION FOR TENANT CONTEXT (for completeness)
-- ============================================================================

CREATE OR REPLACE FUNCTION set_tenant_context(p_tenant_id INTEGER)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- Set tenant context for RLS policies
    -- This is transaction-scoped (LOCAL)
    PERFORM set_config('app.current_tenant_id', p_tenant_id::TEXT, true);
    -- Clear super_admin when setting tenant context
    PERFORM set_config('app.is_super_admin', 'false', true);
END;
$$;

COMMENT ON FUNCTION set_tenant_context IS
'Sets tenant context for RLS policies. Clears super_admin flag.';

REVOKE ALL ON FUNCTION set_tenant_context(INTEGER) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT EXECUTE ON FUNCTION set_tenant_context(INTEGER) TO solvereign_api;
    END IF;
END $$;

-- ============================================================================
-- 6. VERIFY HARDENING
-- ============================================================================

DO $$
DECLARE
    func_record RECORD;
    search_path_set BOOLEAN;
BEGIN
    -- Verify search_path is set on SECURITY DEFINER functions
    FOR func_record IN
        SELECT p.proname, p.proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public'
          AND p.prosecdef = true  -- SECURITY DEFINER
          AND p.proname IN ('get_tenant_by_api_key_hash', 'list_all_tenants',
                           'set_super_admin_context', 'set_tenant_context')
    LOOP
        search_path_set := func_record.proconfig IS NOT NULL
                          AND 'search_path=pg_catalog, public' = ANY(func_record.proconfig);

        IF NOT search_path_set THEN
            RAISE WARNING '[025a] Function % missing search_path setting!', func_record.proname;
        ELSE
            RAISE NOTICE '[025a] VERIFIED: % has search_path hardening', func_record.proname;
        END IF;
    END LOOP;
END $$;

-- Verify REVOKE FROM PUBLIC
DO $$
DECLARE
    has_public_execute BOOLEAN;
BEGIN
    -- Check get_tenant_by_api_key_hash
    SELECT EXISTS (
        SELECT 1 FROM information_schema.routine_privileges
        WHERE routine_name = 'get_tenant_by_api_key_hash'
          AND grantee = 'PUBLIC'
          AND privilege_type = 'EXECUTE'
    ) INTO has_public_execute;

    IF has_public_execute THEN
        RAISE WARNING '[025a] get_tenant_by_api_key_hash still has PUBLIC EXECUTE!';
    ELSE
        RAISE NOTICE '[025a] VERIFIED: get_tenant_by_api_key_hash has no PUBLIC EXECUTE';
    END IF;

    -- Check list_all_tenants
    SELECT EXISTS (
        SELECT 1 FROM information_schema.routine_privileges
        WHERE routine_name = 'list_all_tenants'
          AND grantee = 'PUBLIC'
          AND privilege_type = 'EXECUTE'
    ) INTO has_public_execute;

    IF has_public_execute THEN
        RAISE WARNING '[025a] list_all_tenants still has PUBLIC EXECUTE!';
    ELSE
        RAISE NOTICE '[025a] VERIFIED: list_all_tenants has no PUBLIC EXECUTE';
    END IF;
END $$;

-- ============================================================================
-- 7. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('025a', 'RLS hardening patch: search_path, is_active filter, REVOKE PUBLIC', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- 8. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 025a: RLS Hardening Patch COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Hardening applied:';
    RAISE NOTICE '  1. SET search_path = pg_catalog, public on all SECURITY DEFINER functions';
    RAISE NOTICE '  2. get_tenant_by_api_key_hash() now filters is_active = TRUE';
    RAISE NOTICE '  3. REVOKE ALL FROM PUBLIC on list_all_tenants()';
    RAISE NOTICE '  4. FORCE RLS enabled on idempotency_keys';
    RAISE NOTICE '  5. Added set_super_admin_context() with security documentation';
    RAISE NOTICE '  6. Added set_tenant_context() helper';
    RAISE NOTICE '';
    RAISE NOTICE 'SECURITY BOUNDARY: app.is_super_admin is NOT a hard DB boundary.';
    RAISE NOTICE 'See set_super_admin_context() function for security documentation.';
    RAISE NOTICE '==================================================================';
END $$;
