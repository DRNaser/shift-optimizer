-- ============================================================================
-- MIGRATION 025: RLS on Legacy tenants Table (P0 Security Fix)
-- ============================================================================
-- P0-1: CRITICAL SECURITY FIX
--
-- Problem: The `tenants` table (legacy, created in migration 006) has NO RLS.
--          This table contains api_key_hash values. Without RLS, a compromised
--          connection could read ALL tenants' API key hashes.
--
-- Solution:
--   1. Enable RLS on tenants table
--   2. Create policy that ONLY allows super_admin access
--   3. Normal tenant connections see NO rows (tenants don't query each other)
--
-- Rationale: The `tenants` table is a REGISTRY table, not tenant-scoped data.
--            Only platform admins should ever read it directly.
--            Application code uses get_tenant_by_api_key() which is called
--            BEFORE RLS context is set (uses SECURITY DEFINER or raw connection).
-- ============================================================================

-- ============================================================================
-- 1. ENABLE RLS ON TENANTS TABLE
-- ============================================================================

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

-- Force RLS even for table owner (defense in depth)
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;

COMMENT ON TABLE tenants IS
'Multi-tenant registry with API key authentication. RLS enabled: only super_admin can access.';

-- ============================================================================
-- 2. CREATE RESTRICTIVE POLICY
-- ============================================================================

-- Policy: Only super_admin can see/modify tenants
-- CRITICAL: Normal tenant connections (app.current_tenant_id set) see NOTHING
CREATE POLICY tenants_super_admin_only ON tenants
    FOR ALL
    USING (
        -- Only allow if super_admin flag is set
        current_setting('app.is_super_admin', true) = 'true'
    )
    WITH CHECK (
        -- Same check for INSERT/UPDATE
        current_setting('app.is_super_admin', true) = 'true'
    );

COMMENT ON POLICY tenants_super_admin_only ON tenants IS
'CRITICAL: Only platform super_admin can access tenants registry. Prevents API key hash leakage.';

-- ============================================================================
-- 3. GRANT ACCESS TO API ROLE (RLS will filter)
-- ============================================================================

-- Grant full access to API role - RLS policy will restrict actual access
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO solvereign_api;
        RAISE NOTICE 'Granted table access to solvereign_api (RLS will filter)';
    END IF;
END $$;

-- ============================================================================
-- 4. CREATE SECURITY DEFINER FUNCTION FOR API KEY LOOKUP
-- ============================================================================

-- This function BYPASSES RLS to allow API key lookup during authentication
-- CRITICAL: Called BEFORE tenant context is established
CREATE OR REPLACE FUNCTION get_tenant_by_api_key_hash(p_api_key_hash VARCHAR(64))
RETURNS TABLE (
    id INTEGER,
    name VARCHAR(255),
    is_active BOOLEAN,
    metadata JSONB,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER  -- Bypasses RLS for auth lookups
STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id,
        t.name,
        t.is_active,
        t.metadata,
        t.created_at
    FROM tenants t
    WHERE t.api_key_hash = p_api_key_hash;
END;
$$;

COMMENT ON FUNCTION get_tenant_by_api_key_hash IS
'SECURITY DEFINER: Bypasses RLS to lookup tenant by API key hash during authentication.
Called before tenant context is established.';

-- Restrict function execution to API role
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        REVOKE ALL ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION get_tenant_by_api_key_hash(VARCHAR) TO solvereign_api;
    END IF;
END $$;

-- ============================================================================
-- 5. CREATE FUNCTION FOR TENANT EXISTENCE CHECK (Platform Admin)
-- ============================================================================

CREATE OR REPLACE FUNCTION list_all_tenants()
RETURNS TABLE (
    id INTEGER,
    name VARCHAR(255),
    is_active BOOLEAN,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
AS $$
BEGIN
    -- Only allow if super_admin
    IF current_setting('app.is_super_admin', true) != 'true' THEN
        RAISE EXCEPTION 'Access denied: requires super_admin';
    END IF;

    RETURN QUERY
    SELECT
        t.id,
        t.name,
        t.is_active,
        t.created_at
    FROM tenants t
    ORDER BY t.id;
END;
$$;

COMMENT ON FUNCTION list_all_tenants IS
'Lists all tenants (super_admin only). Does NOT return api_key_hash.';

-- ============================================================================
-- 6. ALSO APPLY RLS TO idempotency_keys (P0-2 fix)
-- ============================================================================

-- idempotency_keys should also be tenant-scoped
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
        -- Enable RLS if not already
        ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;

        -- Check if policy exists
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = 'idempotency_keys' AND policyname = 'idempotency_keys_tenant_isolation'
        ) THEN
            CREATE POLICY idempotency_keys_tenant_isolation ON idempotency_keys
                FOR ALL
                USING (
                    tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                    OR current_setting('app.is_super_admin', true) = 'true'
                )
                WITH CHECK (
                    tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                    OR current_setting('app.is_super_admin', true) = 'true'
                );

            RAISE NOTICE 'Created RLS policy on idempotency_keys';
        ELSE
            RAISE NOTICE 'RLS policy already exists on idempotency_keys';
        END IF;
    ELSE
        RAISE NOTICE 'idempotency_keys table does not exist, skipping';
    END IF;
END $$;

-- ============================================================================
-- 7. VERIFICATION QUERIES
-- ============================================================================

-- Verify RLS is enabled
DO $$
DECLARE
    rls_enabled BOOLEAN;
BEGIN
    SELECT relrowsecurity INTO rls_enabled
    FROM pg_class
    WHERE relname = 'tenants';

    IF NOT rls_enabled THEN
        RAISE EXCEPTION 'CRITICAL: RLS not enabled on tenants table!';
    END IF;

    RAISE NOTICE 'VERIFIED: RLS enabled on tenants table';
END $$;

-- Verify policy exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'tenants' AND policyname = 'tenants_super_admin_only'
    ) THEN
        RAISE EXCEPTION 'CRITICAL: RLS policy not created on tenants table!';
    END IF;

    RAISE NOTICE 'VERIFIED: RLS policy exists on tenants table';
END $$;

-- ============================================================================
-- 8. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('025', 'RLS on legacy tenants table (P0 Security Fix)', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- 9. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 025: RLS on tenants Table COMPLETE (P0 Security Fix)';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Changes:';
    RAISE NOTICE '  - RLS enabled on tenants table (FORCE ROW LEVEL SECURITY)';
    RAISE NOTICE '  - Policy: super_admin_only (normal tenants see NOTHING)';
    RAISE NOTICE '  - Created: get_tenant_by_api_key_hash() SECURITY DEFINER function';
    RAISE NOTICE '  - Created: list_all_tenants() for platform admin';
    RAISE NOTICE '  - RLS enabled on idempotency_keys (if exists)';
    RAISE NOTICE '';
    RAISE NOTICE 'SECURITY NOTE: API key lookups now use SECURITY DEFINER function.';
    RAISE NOTICE 'Update database.py to use get_tenant_by_api_key_hash() function.';
    RAISE NOTICE '==================================================================';
END $$;
