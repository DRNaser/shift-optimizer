-- ============================================================================
-- MIGRATION 051: Fix Function Signatures (Forward-Only)
-- ============================================================================
--
-- SOLVEREIGN V4.5.2 - Forward-Only Bug Fixes
--
-- Purpose:
--   Fixes function signature issues introduced in 040_platform_admin_model.sql:
--   1. Column name mismatch: token_hash vs session_hash
--   2. Return type mismatches (TEXT vs VARCHAR)
--
-- This migration is:
--   - FORWARD-ONLY (no history rewriting)
--   - IDEMPOTENT (safe to run multiple times)
--   - BACKWARD-COMPATIBLE (fixes don't change behavior)
--
-- ============================================================================

BEGIN;

-- ============================================================================
-- 0. RE-SEED ROLES AND PERMISSIONS (if 040 ROLLBACK lost them)
-- ============================================================================
-- Migration 040 has function bugs that cause ROLLBACK, losing these inserts.
-- This forward-only migration re-seeds them idempotently.

-- 0a. Seed tenant_admin role
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

-- 0b. Seed platform.* and tenant.* permissions
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

-- 0c. Map platform_admin to ALL permissions
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r
CROSS JOIN auth.permissions p
WHERE r.name = 'platform_admin'
ON CONFLICT DO NOTHING;

-- 0d. Map tenant_admin to tenant/portal/plan permissions
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name = 'tenant_admin'
  AND (
      p.category IN ('tenant', 'portal', 'plan')
      OR p.key = 'audit.read'
  )
ON CONFLICT DO NOTHING;

-- 0e. Map operator_admin to relevant tenant permissions
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

-- 0f. Map dispatcher to tenant read permissions
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

-- ============================================================================
-- 1. FIX auth.create_platform_session() - uses wrong column name
-- ============================================================================
-- Original 040 uses "token_hash" but 039 created "session_hash"

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

-- ============================================================================
-- 2. FIX auth.get_user_bindings() - return type mismatch
-- ============================================================================
-- Original 040 returns role_name as TEXT, but auth.roles.name is VARCHAR(50)
-- PostgreSQL requires exact type match for CREATE OR REPLACE with different return

-- Drop and recreate with correct types
DROP FUNCTION IF EXISTS auth.get_user_bindings(UUID);

CREATE FUNCTION auth.get_user_bindings(p_user_id UUID)
RETURNS TABLE (
    binding_id INTEGER,
    tenant_id INTEGER,
    site_id INTEGER,
    role_id INTEGER,
    role_name VARCHAR(50)
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

GRANT EXECUTE ON FUNCTION auth.get_user_bindings(UUID) TO solvereign_api;

-- ============================================================================
-- 3. FIX auth.validate_session() - column name and return type mismatches
-- ============================================================================
-- Original 040 uses "s.token_hash" but column is "session_hash"
-- Also return types TEXT vs VARCHAR mismatch

-- Drop and recreate with correct column and types
DROP FUNCTION IF EXISTS auth.validate_session(TEXT);

CREATE FUNCTION auth.validate_session(p_session_hash TEXT)
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
    WHERE s.session_hash = p_session_hash
      AND s.revoked_at IS NULL
      AND s.expires_at > NOW()
      AND u.is_active = TRUE
      AND u.is_locked = FALSE;

    -- Update last activity
    UPDATE auth.sessions sess
    SET last_activity_at = NOW()
    WHERE sess.session_hash = p_session_hash
      AND sess.revoked_at IS NULL
      AND sess.expires_at > NOW();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.validate_session(TEXT) TO solvereign_api;

COMMIT;

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '[051_fix_function_signatures] Forward-only fixes applied:';
    RAISE NOTICE '  - auth.create_platform_session: fixed column name (token_hash -> session_hash)';
    RAISE NOTICE '  - auth.get_user_bindings: fixed return type (role_name VARCHAR(50))';
    RAISE NOTICE '  - auth.validate_session: fixed column name and return types';
END $$;
