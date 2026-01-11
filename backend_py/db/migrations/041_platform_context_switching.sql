-- =============================================================================
-- MIGRATION 041: Platform Admin Context Switching
-- =============================================================================
--
-- SOLVEREIGN V4.5 - SaaS Admin Core (Context Switching)
--
-- Purpose:
--   Allows platform admins to switch their active tenant/site context
--   within a session, enabling them to use tenant-scoped UIs (pack, portal)
--   without needing actual bindings to those tenants.
--
-- How it works:
--   - Platform admin sessions have is_platform_scope=TRUE
--   - active_tenant_id/active_site_id track their current working context
--   - When set, RLS uses active_tenant_id instead of NULL
--   - All context switches are audited with target_tenant_id
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- SCHEMA UPDATES FOR CONTEXT SWITCHING
-- =============================================================================

-- Add active tenant/site context columns to sessions
ALTER TABLE auth.sessions
ADD COLUMN IF NOT EXISTS active_tenant_id INTEGER NULL REFERENCES tenants(id),
ADD COLUMN IF NOT EXISTS active_site_id INTEGER NULL REFERENCES sites(id);

-- Index for efficient context-aware queries
CREATE INDEX IF NOT EXISTS idx_sessions_active_tenant
ON auth.sessions(active_tenant_id) WHERE active_tenant_id IS NOT NULL;

-- =============================================================================
-- FUNCTION: auth.set_platform_context()
-- =============================================================================
-- Allows platform admin to switch their active tenant/site context
-- Validates: (1) session is platform scope, (2) tenant exists and is active

CREATE OR REPLACE FUNCTION auth.set_platform_context(
    p_session_hash TEXT,
    p_tenant_id INTEGER,
    p_site_id INTEGER DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_session auth.sessions%ROWTYPE;
    v_user_id UUID;
    v_site_tenant_id INTEGER;
BEGIN
    -- Get and validate session
    SELECT * INTO v_session
    FROM auth.sessions
    WHERE token_hash = p_session_hash
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
-- FUNCTION: auth.clear_platform_context()
-- =============================================================================
-- Clears the active context (returns to platform-wide scope)

CREATE OR REPLACE FUNCTION auth.clear_platform_context(p_session_hash TEXT)
RETURNS JSONB AS $$
DECLARE
    v_session auth.sessions%ROWTYPE;
BEGIN
    -- Get and validate session
    SELECT * INTO v_session
    FROM auth.sessions
    WHERE token_hash = p_session_hash
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
-- UPDATE: auth.validate_session() to include active context
-- =============================================================================

DROP FUNCTION IF EXISTS auth.validate_session(TEXT);

CREATE OR REPLACE FUNCTION auth.validate_session(p_session_hash TEXT)
RETURNS TABLE (
    session_id UUID,
    user_id UUID,
    user_email TEXT,
    user_display_name TEXT,
    tenant_id INTEGER,
    site_id INTEGER,
    role_id INTEGER,
    role_name TEXT,
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
        s.tenant_id,  -- NULL for platform admin (binding-level)
        s.site_id,    -- NULL for platform admin (binding-level)
        s.role_id,
        r.name,
        s.expires_at,
        COALESCE(s.is_platform_scope, FALSE),
        s.active_tenant_id,  -- Current working context (can be set by platform admin)
        s.active_site_id     -- Current working context
    FROM auth.sessions s
    JOIN auth.users u ON u.id = s.user_id
    JOIN auth.roles r ON r.id = s.role_id
    WHERE s.token_hash = p_session_hash
      AND s.revoked_at IS NULL
      AND s.expires_at > NOW()
      AND u.is_active = TRUE
      AND u.is_locked = FALSE;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- =============================================================================
-- FUNCTION: auth.get_effective_tenant_context()
-- =============================================================================
-- Returns the effective tenant ID for RLS: active context > binding context
-- Used by RLS policies and data access functions

CREATE OR REPLACE FUNCTION auth.get_effective_tenant_context()
RETURNS INTEGER AS $$
DECLARE
    v_active_tenant INTEGER;
    v_bound_tenant INTEGER;
BEGIN
    -- First check active context (for platform admin working in specific tenant)
    v_active_tenant := COALESCE(current_setting('app.active_tenant_id', TRUE)::INTEGER, NULL);
    IF v_active_tenant IS NOT NULL THEN
        RETURN v_active_tenant;
    END IF;

    -- Fall back to binding context
    v_bound_tenant := COALESCE(current_setting('app.current_tenant_id', TRUE)::INTEGER, NULL);
    RETURN v_bound_tenant;
END;
$$ LANGUAGE plpgsql STABLE;

GRANT EXECUTE ON FUNCTION auth.get_effective_tenant_context() TO solvereign_api;

-- =============================================================================
-- UPDATE VERIFY FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.verify_rbac_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Roles exist (now 5 roles)
    RETURN QUERY
    SELECT 'roles_seeded'::TEXT,
           CASE WHEN COUNT(*) >= 5 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s roles defined', COUNT(*))::TEXT
    FROM auth.roles;

    -- Check 2: Permissions exist (now more)
    RETURN QUERY
    SELECT 'permissions_seeded'::TEXT,
           CASE WHEN COUNT(*) >= 19 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s permissions defined', COUNT(*))::TEXT
    FROM auth.permissions;

    -- Check 3: Role-permission mappings exist
    RETURN QUERY
    SELECT 'role_permissions_mapped'::TEXT,
           CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s mappings defined', COUNT(*))::TEXT
    FROM auth.role_permissions;

    -- Check 4: Sessions table has is_platform_scope column
    RETURN QUERY
    SELECT 'sessions_platform_scope_column'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'is_platform_scope'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'is_platform_scope column exists'::TEXT;

    -- Check 5: Sessions table has active_tenant_id column
    RETURN QUERY
    SELECT 'sessions_active_context_column'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'active_tenant_id'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'active_tenant_id column exists'::TEXT;

    -- Check 6: Audit log has target_tenant_id column
    RETURN QUERY
    SELECT 'audit_log_target_tenant_column'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'audit_log'
               AND column_name = 'target_tenant_id'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'target_tenant_id column exists'::TEXT;

    -- Check 7: tenant_admin role exists
    RETURN QUERY
    SELECT 'tenant_admin_role_exists'::TEXT,
           CASE WHEN EXISTS(SELECT 1 FROM auth.roles WHERE name = 'tenant_admin') THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'tenant_admin role configured'::TEXT;

    -- Check 8: Platform permissions exist
    RETURN QUERY
    SELECT 'platform_permissions_exist'::TEXT,
           CASE WHEN COUNT(*) >= 7 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s platform.* permissions', COUNT(*))::TEXT
    FROM auth.permissions WHERE category = 'platform';

    -- Check 9: Users table has RLS
    RETURN QUERY
    SELECT 'users_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.users'::TEXT
    FROM pg_class WHERE relname = 'users' AND relnamespace = 'auth'::regnamespace;

    -- Check 10: Sessions table has RLS
    RETURN QUERY
    SELECT 'sessions_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.sessions'::TEXT
    FROM pg_class WHERE relname = 'sessions' AND relnamespace = 'auth'::regnamespace;

    -- Check 11: Audit log has immutability trigger
    RETURN QUERY
    SELECT 'audit_log_immutable'::TEXT,
           CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'Immutability trigger on audit_log'::TEXT
    FROM pg_trigger WHERE tgname = 'tr_audit_log_immutable';

    -- Check 12: Essential functions exist
    RETURN QUERY
    SELECT 'functions_exist'::TEXT,
           CASE WHEN COUNT(*) >= 12 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s auth functions exist', COUNT(*))::TEXT
    FROM pg_proc WHERE pronamespace = 'auth'::regnamespace;

    -- Check 13: NO fake tenant_id=0 (critical fix verification)
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
-- SELECT * FROM auth.verify_rbac_integrity();
-- Expected: 13 checks, all PASS
