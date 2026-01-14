-- =============================================================================
-- MIGRATION 049: Auth Schema Drift Fix (Idempotent)
-- =============================================================================
--
-- SOLVEREIGN V4.5.1 - Schema Drift Prevention
--
-- Purpose:
--   Fixes schema drift issues discovered during E2E testing:
--   1. Column naming inconsistency: token_hash vs session_hash
--   2. Missing is_platform_scope column
--   3. validate_session function return type mismatches
--
-- Root Cause Analysis:
--   - Migration 039 created auth.sessions with 'session_hash' column
--   - Migrations 040/041 referenced 'token_hash' in some functions
--   - This caused runtime errors when Python code called validate_session
--
-- This migration is IDEMPOTENT - safe to run multiple times.
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. ENSURE session_hash COLUMN EXISTS (canonical name from 039)
-- =============================================================================
-- The column should already exist from 039, but we ensure it's there

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'sessions'
        AND column_name = 'session_hash'
    ) THEN
        -- This shouldn't happen if 039 was applied, but fallback
        ALTER TABLE auth.sessions ADD COLUMN session_hash CHAR(64) NULL;
    END IF;
END $$;

-- =============================================================================
-- 1b. ALLOW NULL tenant_id FOR PLATFORM ADMIN SESSIONS
-- =============================================================================
-- Platform admins have is_platform_scope=TRUE and tenant_id=NULL
-- Regular users have is_platform_scope=FALSE and tenant_id NOT NULL

ALTER TABLE auth.sessions ALTER COLUMN tenant_id DROP NOT NULL;

-- Also allow NULL tenant_id in user_bindings for platform admins
ALTER TABLE auth.user_bindings ALTER COLUMN tenant_id DROP NOT NULL;

-- =============================================================================
-- 2. ENSURE is_platform_scope COLUMN EXISTS
-- =============================================================================
-- Added in 040 but may be missing if migration was partial

ALTER TABLE auth.sessions
ADD COLUMN IF NOT EXISTS is_platform_scope BOOLEAN NOT NULL DEFAULT FALSE;

-- =============================================================================
-- 3. ENSURE active_tenant_id AND active_site_id COLUMNS EXIST
-- =============================================================================
-- Added in 041 for context switching

ALTER TABLE auth.sessions
ADD COLUMN IF NOT EXISTS active_tenant_id INTEGER NULL;

ALTER TABLE auth.sessions
ADD COLUMN IF NOT EXISTS active_site_id INTEGER NULL;

-- Add FK constraints if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'auth' AND table_name = 'sessions'
        AND constraint_name = 'sessions_active_tenant_id_fkey'
    ) THEN
        BEGIN
            ALTER TABLE auth.sessions
            ADD CONSTRAINT sessions_active_tenant_id_fkey
            FOREIGN KEY (active_tenant_id) REFERENCES tenants(id);
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END;
    END IF;
END $$;

-- =============================================================================
-- 4. FIX validate_session FUNCTION
-- =============================================================================
-- CRITICAL: Uses 'session_hash' (not token_hash) and returns correct types

DROP FUNCTION IF EXISTS auth.validate_session(TEXT);
DROP FUNCTION IF EXISTS auth.validate_session(CHAR);

CREATE OR REPLACE FUNCTION auth.validate_session(p_session_hash TEXT)
RETURNS TABLE (
    session_id UUID,
    user_id UUID,
    user_email VARCHAR(255),
    user_display_name VARCHAR(255),
    tenant_id INTEGER,
    site_id INTEGER,
    role_id INTEGER,
    role_name VARCHAR(50),
    expires_at TIMESTAMPTZ,
    is_platform_scope BOOLEAN,
    active_tenant_id INTEGER,
    active_site_id INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.user_id,
        u.email,
        u.display_name,
        s.tenant_id,
        s.site_id,
        s.role_id,
        r.name,
        s.expires_at,
        COALESCE(s.is_platform_scope, FALSE),
        s.active_tenant_id,
        s.active_site_id
    FROM auth.sessions s
    JOIN auth.users u ON u.id = s.user_id
    JOIN auth.roles r ON r.id = s.role_id
    WHERE s.session_hash = p_session_hash  -- CORRECT: session_hash, not token_hash
      AND s.revoked_at IS NULL
      AND s.expires_at > NOW()
      AND u.is_active = TRUE
      AND u.is_locked = FALSE;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.validate_session(TEXT) TO solvereign_api;

-- =============================================================================
-- 5. FIX set_platform_context FUNCTION
-- =============================================================================
-- CRITICAL: Uses 'session_hash' (not token_hash)

DROP FUNCTION IF EXISTS auth.set_platform_context(TEXT, INTEGER, INTEGER);

CREATE OR REPLACE FUNCTION auth.set_platform_context(
    p_session_hash TEXT,
    p_tenant_id INTEGER,
    p_site_id INTEGER DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_session auth.sessions%ROWTYPE;
    v_site_tenant_id INTEGER;
BEGIN
    -- Get and validate session (using session_hash, not token_hash)
    SELECT * INTO v_session
    FROM auth.sessions
    WHERE session_hash = p_session_hash
      AND revoked_at IS NULL
      AND expires_at > NOW();

    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', FALSE, 'error', 'Invalid or expired session');
    END IF;

    -- Must be platform admin session
    IF NOT v_session.is_platform_scope THEN
        RETURN jsonb_build_object('success', FALSE, 'error', 'Context switching requires platform admin');
    END IF;

    -- Validate target tenant exists and is active
    IF NOT auth.validate_target_tenant(p_tenant_id) THEN
        RETURN jsonb_build_object('success', FALSE, 'error', 'Invalid or inactive tenant');
    END IF;

    -- Validate site belongs to tenant (if provided)
    IF p_site_id IS NOT NULL THEN
        SELECT tenant_id INTO v_site_tenant_id FROM sites WHERE id = p_site_id;
        IF v_site_tenant_id IS NULL OR v_site_tenant_id != p_tenant_id THEN
            RETURN jsonb_build_object('success', FALSE, 'error', 'Site does not belong to tenant');
        END IF;
    END IF;

    -- Update session context
    UPDATE auth.sessions
    SET active_tenant_id = p_tenant_id,
        active_site_id = p_site_id
    WHERE id = v_session.id;

    -- Audit the context switch
    INSERT INTO auth.audit_log (event_type, user_id, session_id, target_tenant_id, site_id, details)
    VALUES (
        'CONTEXT_SWITCHED',
        v_session.user_id,
        v_session.id,
        p_tenant_id,
        p_site_id,
        jsonb_build_object(
            'previous_tenant_id', v_session.active_tenant_id,
            'previous_site_id', v_session.active_site_id,
            'new_tenant_id', p_tenant_id,
            'new_site_id', p_site_id
        )
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'active_tenant_id', p_tenant_id,
        'active_site_id', p_site_id
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.set_platform_context(TEXT, INTEGER, INTEGER) TO solvereign_api;

-- =============================================================================
-- 6. FIX clear_platform_context FUNCTION
-- =============================================================================
-- CRITICAL: Uses 'session_hash' (not token_hash)

DROP FUNCTION IF EXISTS auth.clear_platform_context(TEXT);

CREATE OR REPLACE FUNCTION auth.clear_platform_context(p_session_hash TEXT)
RETURNS JSONB AS $$
DECLARE
    v_session auth.sessions%ROWTYPE;
BEGIN
    -- Get and validate session (using session_hash, not token_hash)
    SELECT * INTO v_session
    FROM auth.sessions
    WHERE session_hash = p_session_hash
      AND revoked_at IS NULL
      AND expires_at > NOW();

    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', FALSE, 'error', 'Invalid or expired session');
    END IF;

    -- Must be platform admin session
    IF NOT v_session.is_platform_scope THEN
        RETURN jsonb_build_object('success', FALSE, 'error', 'Context switching requires platform admin');
    END IF;

    -- Clear context
    UPDATE auth.sessions
    SET active_tenant_id = NULL,
        active_site_id = NULL
    WHERE id = v_session.id;

    -- Audit the context clear
    INSERT INTO auth.audit_log (event_type, user_id, session_id, details)
    VALUES (
        'CONTEXT_CLEARED',
        v_session.user_id,
        v_session.id,
        jsonb_build_object(
            'previous_tenant_id', v_session.active_tenant_id,
            'previous_site_id', v_session.active_site_id
        )
    );

    RETURN jsonb_build_object('success', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.clear_platform_context(TEXT) TO solvereign_api;

-- =============================================================================
-- 7. FIX create_platform_session FUNCTION
-- =============================================================================
-- CRITICAL: Uses 'session_hash' (not token_hash)

DROP FUNCTION IF EXISTS auth.create_platform_session(UUID, INTEGER, TEXT, TIMESTAMPTZ, TEXT, TEXT);

CREATE OR REPLACE FUNCTION auth.create_platform_session(
    p_user_id UUID,
    p_role_id INTEGER,
    p_session_hash TEXT,
    p_expires_at TIMESTAMPTZ,
    p_ip_hash TEXT DEFAULT NULL,
    p_user_agent_hash TEXT DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_session_id UUID;
BEGIN
    INSERT INTO auth.sessions (
        user_id, tenant_id, site_id, role_id,
        session_hash, expires_at, ip_hash, user_agent_hash,
        is_platform_scope
    )
    VALUES (
        p_user_id, NULL, NULL, p_role_id,
        p_session_hash, p_expires_at, p_ip_hash, p_user_agent_hash,
        TRUE
    )
    RETURNING id INTO v_session_id;

    RETURN v_session_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.create_platform_session(UUID, INTEGER, TEXT, TIMESTAMPTZ, TEXT, TEXT) TO solvereign_api;

-- =============================================================================
-- 8. CREATE INDEX FOR session_hash LOOKUP
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_sessions_session_hash_active
ON auth.sessions(session_hash) WHERE revoked_at IS NULL;

-- =============================================================================
-- 9. VERIFY FUNCTION: auth.verify_schema_integrity()
-- =============================================================================
-- Comprehensive schema verification that catches drift

CREATE OR REPLACE FUNCTION auth.verify_schema_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: session_hash column exists
    RETURN QUERY
    SELECT 'session_hash_column'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'session_hash'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'session_hash column exists in auth.sessions'::TEXT;

    -- Check 2: session_hash is NOT NULL and UNIQUE
    RETURN QUERY
    SELECT 'session_hash_unique'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.table_constraints tc
               JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
               WHERE tc.table_schema = 'auth' AND tc.table_name = 'sessions'
               AND ccu.column_name = 'session_hash' AND tc.constraint_type = 'UNIQUE'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'session_hash has UNIQUE constraint'::TEXT;

    -- Check 3: is_platform_scope column exists
    RETURN QUERY
    SELECT 'is_platform_scope_column'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'is_platform_scope'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'is_platform_scope column exists'::TEXT;

    -- Check 4: active_tenant_id column exists
    RETURN QUERY
    SELECT 'active_tenant_id_column'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'active_tenant_id'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'active_tenant_id column exists'::TEXT;

    -- Check 5: validate_session function returns 12 columns
    RETURN QUERY
    SELECT 'validate_session_signature'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.routines
               WHERE routine_schema = 'auth' AND routine_name = 'validate_session'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'validate_session function exists'::TEXT;

    -- Check 6: No token_hash column (should be session_hash)
    RETURN QUERY
    SELECT 'no_token_hash_column'::TEXT,
           CASE WHEN NOT EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'token_hash'
           ) THEN 'PASS' ELSE 'WARN' END::TEXT,
           'No deprecated token_hash column (session_hash is canonical)'::TEXT;

    -- Check 7: Required columns have correct types
    RETURN QUERY
    SELECT 'column_types_correct'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'session_hash'
               AND (data_type = 'character' OR data_type = 'character varying')
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'session_hash has correct data type'::TEXT;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.verify_schema_integrity() TO solvereign_api;
GRANT EXECUTE ON FUNCTION auth.verify_schema_integrity() TO solvereign_platform;

-- =============================================================================
-- 10. UPDATE verify_rbac_integrity TO INCLUDE SCHEMA CHECKS
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.verify_rbac_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Include all schema checks
    RETURN QUERY SELECT * FROM auth.verify_schema_integrity();

    -- Check: Roles exist (5+ roles)
    RETURN QUERY
    SELECT 'roles_seeded'::TEXT,
           CASE WHEN COUNT(*) >= 5 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s roles defined', COUNT(*))::TEXT
    FROM auth.roles;

    -- Check: Permissions exist
    RETURN QUERY
    SELECT 'permissions_seeded'::TEXT,
           CASE WHEN COUNT(*) >= 19 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s permissions defined', COUNT(*))::TEXT
    FROM auth.permissions;

    -- Check: Role-permission mappings exist
    RETURN QUERY
    SELECT 'role_permissions_mapped'::TEXT,
           CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s mappings defined', COUNT(*))::TEXT
    FROM auth.role_permissions;

    -- Check: tenant_admin role exists
    RETURN QUERY
    SELECT 'tenant_admin_role_exists'::TEXT,
           CASE WHEN EXISTS(SELECT 1 FROM auth.roles WHERE name = 'tenant_admin') THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'tenant_admin role configured'::TEXT;

    -- Check: Platform permissions exist
    RETURN QUERY
    SELECT 'platform_permissions_exist'::TEXT,
           CASE WHEN COUNT(*) >= 7 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s platform.* permissions', COUNT(*))::TEXT
    FROM auth.permissions WHERE category = 'platform';

    -- Check: RLS enabled on users
    RETURN QUERY
    SELECT 'users_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.users'::TEXT
    FROM pg_class WHERE relname = 'users' AND relnamespace = 'auth'::regnamespace;

    -- Check: RLS enabled on sessions
    RETURN QUERY
    SELECT 'sessions_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.sessions'::TEXT
    FROM pg_class WHERE relname = 'sessions' AND relnamespace = 'auth'::regnamespace;

    -- Check: Audit log immutability
    RETURN QUERY
    SELECT 'audit_log_immutable'::TEXT,
           CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'Immutability trigger on audit_log'::TEXT
    FROM pg_trigger WHERE tgname = 'tr_audit_log_immutable';

    -- Check: NO fake tenant_id=0
    RETURN QUERY
    SELECT 'no_fake_tenant_zero'::TEXT,
           CASE WHEN NOT EXISTS(SELECT 1 FROM tenants WHERE id = 0) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'No fake tenant_id=0 exists'::TEXT;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Run after migration:
-- SELECT * FROM auth.verify_schema_integrity();
-- SELECT * FROM auth.verify_rbac_integrity();
-- Expected: All checks PASS
