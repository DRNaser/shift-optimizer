-- =============================================================================
-- MIGRATION 040: Platform Admin Model + Tenant Admin Role (FIXED)
-- =============================================================================
--
-- SOLVEREIGN V4.5 - SaaS Admin Core
--
-- Purpose:
--   Implements ROLE-BASED platform admin scoping:
--   - platform_admin identified by role name ONLY (no fake tenant_id=0)
--   - Sessions track is_platform_scope flag
--   - Audit log tracks target_tenant_id for cross-tenant actions
--   - Adds tenant_admin role for tenant-level administration
--   - Adds platform.* permissions for SaaS administration
--
-- Security Model:
--   - platform_admin: Full platform access, identified by role, not tenant
--   - tenant_admin: Full access within assigned tenant(s)
--   - operator_admin: Operational admin within tenant
--   - dispatcher: Operational user within tenant/site
--   - ops_readonly: Read-only operational access
--
-- CRITICAL: NO FAKE TENANT_ID=0 CONCEPT
--   Platform admins have NULL tenant_id in their binding and is_platform_scope=TRUE
--   in their session. They access tenants via target_tenant_id parameter.
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- SCHEMA UPDATES FOR PLATFORM ADMIN
-- =============================================================================

-- Add is_platform_scope to sessions for tracking platform admin sessions
ALTER TABLE auth.sessions
ADD COLUMN IF NOT EXISTS is_platform_scope BOOLEAN NOT NULL DEFAULT FALSE;

-- Add target_tenant_id to audit_log for tracking cross-tenant actions
ALTER TABLE auth.audit_log
ADD COLUMN IF NOT EXISTS target_tenant_id INTEGER NULL REFERENCES tenants(id);

-- Add password reset token columns to users table
ALTER TABLE auth.users
ADD COLUMN IF NOT EXISTS password_reset_token TEXT NULL,
ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMPTZ NULL;

-- Create index for password reset token lookup
CREATE INDEX IF NOT EXISTS idx_users_password_reset_token
ON auth.users(password_reset_token) WHERE password_reset_token IS NOT NULL;

-- Create index for efficient querying of platform admin sessions
CREATE INDEX IF NOT EXISTS idx_sessions_platform_scope
ON auth.sessions(is_platform_scope) WHERE is_platform_scope = TRUE;

-- =============================================================================
-- NEW ROLE: tenant_admin
-- =============================================================================

INSERT INTO auth.roles (name, display_name, description, is_system)
VALUES (
    'tenant_admin',
    'Tenant Administrator',
    'Full administrative access within assigned tenant(s). Can manage users, sites, and features.',
    TRUE
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description;

-- =============================================================================
-- NEW PERMISSIONS: Platform Administration
-- =============================================================================

INSERT INTO auth.permissions (key, display_name, description, category) VALUES
    -- Platform-level permissions (platform_admin only)
    ('platform.tenants.read', 'View Tenants', 'List and view all tenants', 'platform'),
    ('platform.tenants.write', 'Manage Tenants', 'Create, update, and configure tenants', 'platform'),
    ('platform.users.read', 'View All Users', 'View users across all tenants', 'platform'),
    ('platform.users.write', 'Manage All Users', 'Create and manage users across all tenants', 'platform'),
    ('platform.bindings.write', 'Manage Bindings', 'Assign/unassign user role bindings', 'platform'),
    ('platform.audit.read', 'View Platform Audit', 'Access platform-wide audit logs', 'platform'),
    ('platform.features.write', 'Manage Platform Features', 'Enable/disable platform features', 'platform'),

    -- Tenant-level permissions (tenant_admin and above)
    ('tenant.sites.read', 'View Sites', 'List and view tenant sites', 'tenant'),
    ('tenant.sites.write', 'Manage Sites', 'Create and configure tenant sites', 'tenant'),
    ('tenant.drivers.read', 'View Drivers', 'View driver master data', 'tenant'),
    ('tenant.drivers.write', 'Manage Drivers', 'Create and manage drivers', 'tenant'),
    ('tenant.tours.read', 'View Tours', 'View tour configurations', 'tenant'),
    ('tenant.tours.write', 'Manage Tours', 'Create and manage tours', 'tenant'),
    ('tenant.users.read', 'View Tenant Users', 'View users within tenant', 'tenant'),
    ('tenant.users.write', 'Manage Tenant Users', 'Manage users within tenant', 'tenant')
ON CONFLICT (key) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    category = EXCLUDED.category;

-- =============================================================================
-- UPDATE ROLE-PERMISSION MAPPINGS
-- =============================================================================

-- Platform Admin: ALL permissions
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r
CROSS JOIN auth.permissions p
WHERE r.name = 'platform_admin'
ON CONFLICT DO NOTHING;

-- Tenant Admin: All tenant.* + portal.* + audit.read + plan.* permissions
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name = 'tenant_admin'
  AND (
      p.category IN ('tenant', 'portal', 'plan')
      OR p.key = 'audit.read'
  )
ON CONFLICT DO NOTHING;

-- Operator Admin: Ensure they have tenant user management
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name = 'operator_admin'
  AND p.key IN (
      'tenant.sites.read',
      'tenant.drivers.read', 'tenant.drivers.write',
      'tenant.tours.read', 'tenant.tours.write'
  )
ON CONFLICT DO NOTHING;

-- Dispatcher: Read access to tenant data
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name = 'dispatcher'
  AND p.key IN (
      'tenant.sites.read',
      'tenant.drivers.read',
      'tenant.tours.read'
  )
ON CONFLICT DO NOTHING;

-- =============================================================================
-- FUNCTION: auth.is_platform_admin_session()
-- =============================================================================
-- Check if current session has platform admin scope
-- Uses app.current_role_name session variable set during authentication

CREATE OR REPLACE FUNCTION auth.is_platform_admin_session()
RETURNS BOOLEAN AS $$
BEGIN
    RETURN COALESCE(current_setting('app.is_platform_admin', TRUE), 'false')::BOOLEAN;
END;
$$ LANGUAGE plpgsql STABLE;

GRANT EXECUTE ON FUNCTION auth.is_platform_admin_session() TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.get_platform_admin_role_id()
-- =============================================================================
-- Helper to get the platform_admin role ID

CREATE OR REPLACE FUNCTION auth.get_platform_admin_role_id()
RETURNS INTEGER AS $$
DECLARE
    v_role_id INTEGER;
BEGIN
    SELECT id INTO v_role_id FROM auth.roles WHERE name = 'platform_admin';
    RETURN v_role_id;
END;
$$ LANGUAGE plpgsql STABLE;

-- =============================================================================
-- RLS POLICY UPDATES FOR PLATFORM ADMIN
-- =============================================================================

-- Allow platform_admin to see all sessions (via is_platform_admin flag)
DROP POLICY IF EXISTS sessions_platform_admin ON auth.sessions;
CREATE POLICY sessions_platform_admin ON auth.sessions
    FOR ALL
    USING (
        pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
        OR (
            pg_has_role(session_user, 'solvereign_api', 'MEMBER')
            AND auth.is_platform_admin_session()
        )
    );

-- Allow platform_admin to see all bindings
DROP POLICY IF EXISTS bindings_platform_admin ON auth.user_bindings;
CREATE POLICY bindings_platform_admin ON auth.user_bindings
    FOR ALL
    USING (
        pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
        OR (
            pg_has_role(session_user, 'solvereign_api', 'MEMBER')
            AND auth.is_platform_admin_session()
        )
    );

-- Allow platform_admin to see all users
DROP POLICY IF EXISTS users_platform_admin_full ON auth.users;
CREATE POLICY users_platform_admin_full ON auth.users
    FOR ALL
    USING (
        pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
        OR (
            pg_has_role(session_user, 'solvereign_api', 'MEMBER')
            AND auth.is_platform_admin_session()
        )
    );

-- =============================================================================
-- FUNCTION: auth.create_platform_session()
-- =============================================================================
-- Create a session for platform admin (with is_platform_scope=TRUE)

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
        token_hash, expires_at, ip_hash, user_agent_hash,
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
-- FUNCTION: auth.validate_target_tenant()
-- =============================================================================
-- Validate that a target tenant exists and is active

CREATE OR REPLACE FUNCTION auth.validate_target_tenant(p_tenant_id INTEGER)
RETURNS BOOLEAN AS $$
DECLARE
    v_exists BOOLEAN;
BEGIN
    SELECT EXISTS(
        SELECT 1 FROM tenants WHERE id = p_tenant_id AND is_active = TRUE
    ) INTO v_exists;

    RETURN v_exists;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.validate_target_tenant(INTEGER) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.create_tenant()
-- =============================================================================
-- Creates a new tenant with audit logging (platform admin only)

CREATE OR REPLACE FUNCTION auth.create_tenant(
    p_name TEXT,
    p_owner_display_name TEXT DEFAULT NULL
)
RETURNS INTEGER AS $$
DECLARE
    v_tenant_id INTEGER;
    v_user_id UUID;
BEGIN
    -- Only platform admin can create tenants
    IF NOT auth.is_platform_admin_session() THEN
        RAISE EXCEPTION 'Permission denied: platform admin required';
    END IF;

    -- Get current user for audit
    v_user_id := COALESCE(current_setting('app.current_user_id', TRUE)::UUID, NULL);

    INSERT INTO tenants (name, is_active, created_at)
    VALUES (p_name, true, NOW())
    RETURNING id INTO v_tenant_id;

    -- Audit log with target_tenant_id
    INSERT INTO auth.audit_log (event_type, user_id, target_tenant_id, details)
    VALUES (
        'TENANT_CREATED',
        v_user_id,
        v_tenant_id,
        jsonb_build_object(
            'name', p_name,
            'owner_display_name', p_owner_display_name
        )
    );

    RETURN v_tenant_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.create_tenant(TEXT, TEXT) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.create_site()
-- =============================================================================
-- Creates a new site within a tenant

CREATE OR REPLACE FUNCTION auth.create_site(
    p_tenant_id INTEGER,
    p_name TEXT,
    p_code TEXT DEFAULT NULL
)
RETURNS INTEGER AS $$
DECLARE
    v_site_id INTEGER;
    v_user_id UUID;
    v_current_tenant_id INTEGER;
BEGIN
    v_user_id := COALESCE(current_setting('app.current_user_id', TRUE)::UUID, NULL);
    v_current_tenant_id := COALESCE(current_setting('app.current_tenant_id', TRUE)::INTEGER, NULL);

    -- Platform admin OR tenant admin for this specific tenant
    IF NOT auth.is_platform_admin_session() THEN
        IF v_current_tenant_id IS NULL OR v_current_tenant_id != p_tenant_id THEN
            RAISE EXCEPTION 'Permission denied: cannot manage sites in other tenants';
        END IF;
    ELSE
        -- Platform admin: validate target tenant exists
        IF NOT auth.validate_target_tenant(p_tenant_id) THEN
            RAISE EXCEPTION 'Invalid target tenant: %', p_tenant_id;
        END IF;
    END IF;

    INSERT INTO sites (tenant_id, name, code, created_at)
    VALUES (p_tenant_id, p_name, COALESCE(p_code, UPPER(SUBSTRING(p_name, 1, 3))), NOW())
    RETURNING id INTO v_site_id;

    -- Audit log
    INSERT INTO auth.audit_log (event_type, user_id, tenant_id, site_id, target_tenant_id, details)
    VALUES (
        'SITE_CREATED',
        v_user_id,
        v_current_tenant_id,
        v_site_id,
        p_tenant_id,
        jsonb_build_object('name', p_name, 'code', p_code)
    );

    RETURN v_site_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.create_site(INTEGER, TEXT, TEXT) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.create_user_with_binding()
-- =============================================================================
-- Creates a new user with their initial binding

CREATE OR REPLACE FUNCTION auth.create_user_with_binding(
    p_email TEXT,
    p_password_hash TEXT,
    p_display_name TEXT,
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_role_name TEXT
)
RETURNS UUID AS $$
DECLARE
    v_user_id UUID;
    v_role_id INTEGER;
    v_current_user_id UUID;
    v_current_tenant_id INTEGER;
BEGIN
    v_current_user_id := COALESCE(current_setting('app.current_user_id', TRUE)::UUID, NULL);
    v_current_tenant_id := COALESCE(current_setting('app.current_tenant_id', TRUE)::INTEGER, NULL);

    -- Permission check
    IF NOT auth.is_platform_admin_session() THEN
        IF v_current_tenant_id IS NULL OR v_current_tenant_id != p_tenant_id THEN
            RAISE EXCEPTION 'Permission denied: cannot create users in other tenants';
        END IF;
        -- Non-platform admins cannot create platform_admin users
        IF p_role_name = 'platform_admin' THEN
            RAISE EXCEPTION 'Permission denied: only platform admins can create platform_admin users';
        END IF;
    ELSE
        -- Platform admin: validate target tenant exists (unless creating platform admin)
        IF p_role_name != 'platform_admin' AND NOT auth.validate_target_tenant(p_tenant_id) THEN
            RAISE EXCEPTION 'Invalid target tenant: %', p_tenant_id;
        END IF;
    END IF;

    -- Get role ID
    SELECT id INTO v_role_id FROM auth.roles WHERE name = p_role_name;
    IF v_role_id IS NULL THEN
        RAISE EXCEPTION 'Invalid role: %', p_role_name;
    END IF;

    -- Create user
    INSERT INTO auth.users (email, password_hash, display_name, is_active)
    VALUES (LOWER(p_email), p_password_hash, p_display_name, true)
    RETURNING id INTO v_user_id;

    -- Create binding
    -- For platform_admin, tenant_id can be NULL (they operate across all tenants)
    INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
    VALUES (
        v_user_id,
        CASE WHEN p_role_name = 'platform_admin' THEN NULL ELSE p_tenant_id END,
        CASE WHEN p_role_name = 'platform_admin' THEN NULL ELSE p_site_id END,
        v_role_id,
        true
    );

    -- Audit log
    INSERT INTO auth.audit_log (event_type, user_id, tenant_id, target_tenant_id, details)
    VALUES (
        'USER_CREATED',
        v_current_user_id,
        v_current_tenant_id,
        CASE WHEN p_role_name = 'platform_admin' THEN NULL ELSE p_tenant_id END,
        jsonb_build_object(
            'new_user_id', v_user_id,
            'email', LOWER(p_email),
            'role', p_role_name
        )
    );

    RETURN v_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.create_user_with_binding(TEXT, TEXT, TEXT, INTEGER, INTEGER, TEXT) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.create_platform_admin_binding()
-- =============================================================================
-- Creates a platform admin binding for an existing user

CREATE OR REPLACE FUNCTION auth.create_platform_admin_binding(
    p_user_id UUID
)
RETURNS INTEGER AS $$
DECLARE
    v_binding_id INTEGER;
    v_role_id INTEGER;
BEGIN
    -- Only platform admin can create platform admin bindings
    IF NOT auth.is_platform_admin_session() THEN
        RAISE EXCEPTION 'Permission denied: platform admin required';
    END IF;

    -- Get platform_admin role ID
    SELECT id INTO v_role_id FROM auth.roles WHERE name = 'platform_admin';
    IF v_role_id IS NULL THEN
        RAISE EXCEPTION 'platform_admin role not found';
    END IF;

    -- Create binding with NULL tenant_id (platform scope)
    INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
    VALUES (p_user_id, NULL, NULL, v_role_id, true)
    RETURNING id INTO v_binding_id;

    -- Audit log
    INSERT INTO auth.audit_log (event_type, user_id, details)
    VALUES (
        'PLATFORM_ADMIN_BINDING_CREATED',
        COALESCE(current_setting('app.current_user_id', TRUE)::UUID, NULL),
        jsonb_build_object('target_user_id', p_user_id)
    );

    RETURN v_binding_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.create_platform_admin_binding(UUID) TO solvereign_api;

-- =============================================================================
-- UPDATE auth.get_user_bindings() to handle NULL tenant_id
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.get_user_bindings(p_user_id UUID)
RETURNS TABLE (
    binding_id INTEGER,
    tenant_id INTEGER,
    site_id INTEGER,
    role_id INTEGER,
    role_name TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ub.id,
        ub.tenant_id,  -- Can be NULL for platform_admin
        ub.site_id,
        ub.role_id,
        r.name
    FROM auth.user_bindings ub
    JOIN auth.roles r ON r.id = ub.role_id
    WHERE ub.user_id = p_user_id AND ub.is_active = TRUE;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- =============================================================================
-- UPDATE auth.validate_session() to handle platform admin sessions
-- =============================================================================

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
    is_platform_scope BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.user_id,
        u.email,
        u.display_name,
        s.tenant_id,  -- NULL for platform admin
        s.site_id,
        s.role_id,
        r.name,
        s.expires_at,
        COALESCE(s.is_platform_scope, FALSE)
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

    -- Check 5: Audit log has target_tenant_id column
    RETURN QUERY
    SELECT 'audit_log_target_tenant_column'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'audit_log'
               AND column_name = 'target_tenant_id'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'target_tenant_id column exists'::TEXT;

    -- Check 6: tenant_admin role exists
    RETURN QUERY
    SELECT 'tenant_admin_role_exists'::TEXT,
           CASE WHEN EXISTS(SELECT 1 FROM auth.roles WHERE name = 'tenant_admin') THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'tenant_admin role configured'::TEXT;

    -- Check 7: Platform permissions exist
    RETURN QUERY
    SELECT 'platform_permissions_exist'::TEXT,
           CASE WHEN COUNT(*) >= 7 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s platform.* permissions', COUNT(*))::TEXT
    FROM auth.permissions WHERE category = 'platform';

    -- Check 8: Users table has RLS
    RETURN QUERY
    SELECT 'users_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.users'::TEXT
    FROM pg_class WHERE relname = 'users' AND relnamespace = 'auth'::regnamespace;

    -- Check 9: Sessions table has RLS
    RETURN QUERY
    SELECT 'sessions_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.sessions'::TEXT
    FROM pg_class WHERE relname = 'sessions' AND relnamespace = 'auth'::regnamespace;

    -- Check 10: Audit log has immutability trigger
    RETURN QUERY
    SELECT 'audit_log_immutable'::TEXT,
           CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'Immutability trigger on audit_log'::TEXT
    FROM pg_trigger WHERE tgname = 'tr_audit_log_immutable';

    -- Check 11: Essential functions exist
    RETURN QUERY
    SELECT 'functions_exist'::TEXT,
           CASE WHEN COUNT(*) >= 10 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s auth functions exist', COUNT(*))::TEXT
    FROM pg_proc WHERE pronamespace = 'auth'::regnamespace;

    -- Check 12: NO fake tenant_id=0 (critical fix verification)
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
-- Expected: 12 checks, all PASS
