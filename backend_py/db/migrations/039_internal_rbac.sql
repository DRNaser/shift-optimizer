-- =============================================================================
-- MIGRATION 039: Internal RBAC (Role-Based Access Control)
-- =============================================================================
--
-- SOLVEREIGN V4.4 - Entra ID Migration to Internal Auth
--
-- Purpose:
--   Implements internal RBAC system for admin/dispatcher authentication,
--   replacing Microsoft Entra ID dependency for portal-admin access.
--   Driver Portal (magic links) remains unchanged.
--
-- Key Features:
--   - User accounts with Argon2id password hashing
--   - Role-based permissions with tenant/site scope
--   - Server-side sessions with HttpOnly cookie pattern
--   - Audit logging for login/logout/actions
--   - Multi-tenant isolation via user_bindings
--
-- Security:
--   - Password stored as Argon2id hash only
--   - Session tokens stored as SHA-256 hash
--   - Tenant/Site isolation enforced via bindings, not request params
--   - No secrets in logs
--
-- Dependencies:
--   - tenants table (for tenant_id FK)
--   - sites table (for site_id FK, if applicable)
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- SCHEMA: auth
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS auth;

-- Secure the schema
REVOKE ALL ON SCHEMA auth FROM PUBLIC;
GRANT USAGE ON SCHEMA auth TO solvereign_api;
GRANT USAGE ON SCHEMA auth TO solvereign_platform;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA auth
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA auth
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA auth
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA auth
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO solvereign_api;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA auth
    GRANT USAGE ON SEQUENCES TO solvereign_api;

-- =============================================================================
-- TABLE: auth.users
-- =============================================================================
-- User accounts for internal authentication

CREATE TABLE IF NOT EXISTS auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(255) NULL,

    -- Authentication
    password_hash TEXT NOT NULL,  -- Argon2id hash

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    lock_reason TEXT NULL,
    failed_login_count INTEGER NOT NULL DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ NULL,
    password_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT users_email_unique UNIQUE (email),
    CONSTRAINT users_email_lowercase CHECK (email = LOWER(email))
);

-- Index for login lookups
CREATE INDEX IF NOT EXISTS idx_users_email_active ON auth.users(email) WHERE is_active = TRUE;

-- =============================================================================
-- TABLE: auth.roles
-- =============================================================================
-- Role definitions (seeded, rarely changed)

CREATE TABLE IF NOT EXISTS auth.roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,  -- Cannot be deleted
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT roles_name_unique UNIQUE (name)
);

-- =============================================================================
-- TABLE: auth.permissions
-- =============================================================================
-- Permission definitions (seeded, rarely changed)

CREATE TABLE IF NOT EXISTS auth.permissions (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) NOT NULL,  -- e.g., "portal.resend.write"
    display_name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    category VARCHAR(50) NULL,  -- For grouping in UI
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT permissions_key_unique UNIQUE (key)
);

-- =============================================================================
-- TABLE: auth.role_permissions
-- =============================================================================
-- Many-to-many: which permissions each role has

CREATE TABLE IF NOT EXISTS auth.role_permissions (
    role_id INTEGER NOT NULL REFERENCES auth.roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES auth.permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (role_id, permission_id)
);

-- Index for permission lookups
CREATE INDEX IF NOT EXISTS idx_role_permissions_permission ON auth.role_permissions(permission_id);

-- =============================================================================
-- TABLE: auth.user_bindings
-- =============================================================================
-- Binds a user to a tenant/site with a specific role
-- This is THE source of truth for tenant/site access

CREATE TABLE IF NOT EXISTS auth.user_bindings (
    id SERIAL PRIMARY KEY,

    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id INTEGER NULL,  -- NULL = all sites in tenant
    role_id INTEGER NOT NULL REFERENCES auth.roles(id) ON DELETE RESTRICT,

    -- Metadata
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NULL REFERENCES auth.users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A user can have only one role per tenant/site combination
    -- Note: site_id NULL means "all sites", so (user, tenant, NULL) is valid once
    CONSTRAINT user_bindings_unique UNIQUE (user_id, tenant_id, site_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_user_bindings_user ON auth.user_bindings(user_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_user_bindings_tenant ON auth.user_bindings(tenant_id) WHERE is_active = TRUE;

-- =============================================================================
-- TABLE: auth.sessions
-- =============================================================================
-- Server-side session storage (HttpOnly cookie references this)

CREATE TABLE IF NOT EXISTS auth.sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- User reference
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Scope from binding at login time (denormalized for fast access)
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id INTEGER NULL,
    role_id INTEGER NOT NULL REFERENCES auth.roles(id),

    -- Session security
    session_hash CHAR(64) NOT NULL UNIQUE,  -- SHA-256 of session token

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Revocation
    revoked_at TIMESTAMPTZ NULL,
    revoked_reason TEXT NULL,

    -- Rotation tracking
    rotated_from UUID NULL REFERENCES auth.sessions(id),

    -- Security metadata (hashed)
    ip_hash CHAR(64) NULL,
    user_agent_hash CHAR(64) NULL,

    CONSTRAINT sessions_expires_future CHECK (expires_at > created_at)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth.sessions(user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON auth.sessions(expires_at) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON auth.sessions(session_hash) WHERE revoked_at IS NULL;

-- =============================================================================
-- TABLE: auth.audit_log
-- =============================================================================
-- Append-only audit log for authentication events

CREATE TABLE IF NOT EXISTS auth.audit_log (
    id BIGSERIAL PRIMARY KEY,

    -- Event type
    event_type VARCHAR(50) NOT NULL,  -- login_success, login_failed, logout, session_revoked, etc.

    -- Actor (may be null for failed login attempts)
    user_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    user_email VARCHAR(255) NULL,  -- Denormalized for audit trail even if user deleted

    -- Scope
    tenant_id INTEGER NULL REFERENCES tenants(id) ON DELETE SET NULL,
    site_id INTEGER NULL,
    session_id UUID NULL,

    -- Details (no secrets!)
    details JSONB NULL,
    error_code VARCHAR(50) NULL,

    -- Security metadata
    ip_hash CHAR(64) NULL,
    user_agent_hash CHAR(64) NULL,

    -- Timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON auth.audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON auth.audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON auth.audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON auth.audit_log(created_at DESC);

-- Make audit log append-only
CREATE OR REPLACE FUNCTION auth.prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'auth.audit_log is append-only. Modifications not allowed.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_audit_log_immutable ON auth.audit_log;
CREATE TRIGGER tr_audit_log_immutable
    BEFORE UPDATE OR DELETE ON auth.audit_log
    FOR EACH ROW
    EXECUTE FUNCTION auth.prevent_audit_modification();

-- =============================================================================
-- SEED: Roles
-- =============================================================================

INSERT INTO auth.roles (name, display_name, description, is_system) VALUES
    ('platform_admin', 'Platform Administrator', 'Full access to all platform features', TRUE),
    ('operator_admin', 'Operator Administrator', 'Tenant-level admin for operators', TRUE),
    ('dispatcher', 'Dispatcher', 'Operational access for plan management and notifications', TRUE),
    ('ops_readonly', 'Operations Viewer', 'Read-only access to operational data', TRUE)
ON CONFLICT (name) DO NOTHING;

-- =============================================================================
-- SEED: Permissions
-- =============================================================================

INSERT INTO auth.permissions (key, display_name, description, category) VALUES
    -- Portal permissions
    ('portal.summary.read', 'View Portal Summary', 'View dashboard KPI summary', 'portal'),
    ('portal.details.read', 'View Driver Details', 'View driver status list', 'portal'),
    ('portal.resend.write', 'Resend Notifications', 'Trigger notification resend', 'portal'),
    ('portal.export.read', 'Export Data', 'Export driver lists as CSV', 'portal'),

    -- Tenant permissions
    ('tenant.features.write', 'Manage Features', 'Enable/disable tenant features', 'tenant'),
    ('tenant.users.write', 'Manage Users', 'Add/modify tenant users', 'tenant'),
    ('tenant.users.read', 'View Users', 'View tenant user list', 'tenant'),

    -- Audit permissions
    ('audit.read', 'View Audit Logs', 'Access audit log records', 'audit'),

    -- Plan permissions (for future use)
    ('plan.view', 'View Plans', 'View plan data and snapshots', 'plan'),
    ('plan.publish', 'Publish Plans', 'Publish plan snapshots', 'plan'),
    ('plan.approve', 'Approve Plans', 'Approve plans for publishing', 'plan')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- SEED: Role-Permission Mappings
-- =============================================================================

-- Platform Admin: everything
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r
CROSS JOIN auth.permissions p
WHERE r.name = 'platform_admin'
ON CONFLICT DO NOTHING;

-- Operator Admin: tenant management + all portal + audit
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name = 'operator_admin'
  AND p.key IN (
      'portal.summary.read', 'portal.details.read', 'portal.resend.write', 'portal.export.read',
      'tenant.features.write', 'tenant.users.write', 'tenant.users.read',
      'audit.read',
      'plan.view', 'plan.publish', 'plan.approve'
  )
ON CONFLICT DO NOTHING;

-- Dispatcher: portal read + resend + plan view
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name = 'dispatcher'
  AND p.key IN (
      'portal.summary.read', 'portal.details.read', 'portal.resend.write', 'portal.export.read',
      'plan.view'
  )
ON CONFLICT DO NOTHING;

-- Ops Readonly: read-only access
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name = 'ops_readonly'
  AND p.key IN (
      'portal.summary.read', 'portal.details.read', 'portal.export.read',
      'plan.view'
  )
ON CONFLICT DO NOTHING;

-- =============================================================================
-- RLS: Enable Row-Level Security
-- =============================================================================

ALTER TABLE auth.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.user_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.audit_log ENABLE ROW LEVEL SECURITY;

-- Force RLS even for table owners
ALTER TABLE auth.users FORCE ROW LEVEL SECURITY;
ALTER TABLE auth.sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE auth.user_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE auth.audit_log FORCE ROW LEVEL SECURITY;

-- Roles and permissions are public (read-only seed data)
-- No RLS needed on auth.roles and auth.permissions

-- =============================================================================
-- RLS Policies: auth.users
-- =============================================================================

-- Platform admins can see all users
CREATE POLICY users_platform_admin ON auth.users
    FOR ALL
    USING (pg_has_role(session_user, 'solvereign_platform', 'MEMBER'));

-- API role: users can be accessed via binding lookup (internal functions only)
-- Direct table access blocked; use functions instead

-- =============================================================================
-- RLS Policies: auth.sessions
-- =============================================================================

-- Platform can manage all sessions
CREATE POLICY sessions_platform ON auth.sessions
    FOR ALL
    USING (pg_has_role(session_user, 'solvereign_platform', 'MEMBER'));

-- API can manage sessions for current tenant
CREATE POLICY sessions_api_tenant ON auth.sessions
    FOR ALL
    USING (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(current_setting('app.current_tenant_id', TRUE)::INTEGER, 0)
    );

-- =============================================================================
-- RLS Policies: auth.user_bindings
-- =============================================================================

-- Platform can see all bindings
CREATE POLICY bindings_platform ON auth.user_bindings
    FOR ALL
    USING (pg_has_role(session_user, 'solvereign_platform', 'MEMBER'));

-- API can see bindings for current tenant
CREATE POLICY bindings_api_tenant ON auth.user_bindings
    FOR SELECT
    USING (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(current_setting('app.current_tenant_id', TRUE)::INTEGER, 0)
    );

-- =============================================================================
-- RLS Policies: auth.audit_log
-- =============================================================================

-- Platform can see all audit logs
CREATE POLICY audit_platform ON auth.audit_log
    FOR ALL
    USING (pg_has_role(session_user, 'solvereign_platform', 'MEMBER'));

-- API can see audit logs for current tenant
CREATE POLICY audit_api_tenant ON auth.audit_log
    FOR SELECT
    USING (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(current_setting('app.current_tenant_id', TRUE)::INTEGER, 0)
    );

-- =============================================================================
-- FUNCTION: auth.get_user_by_email(email)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.get_user_by_email(p_email TEXT)
RETURNS TABLE (
    id UUID,
    email VARCHAR(255),
    display_name VARCHAR(255),
    password_hash TEXT,
    is_active BOOLEAN,
    is_locked BOOLEAN,
    failed_login_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT u.id, u.email, u.display_name, u.password_hash,
           u.is_active, u.is_locked, u.failed_login_count
    FROM auth.users u
    WHERE u.email = LOWER(p_email);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute to API
GRANT EXECUTE ON FUNCTION auth.get_user_by_email(TEXT) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.get_user_bindings(user_id)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.get_user_bindings(p_user_id UUID)
RETURNS TABLE (
    binding_id INTEGER,
    tenant_id INTEGER,
    site_id INTEGER,
    role_id INTEGER,
    role_name VARCHAR(50)
) AS $$
BEGIN
    RETURN QUERY
    SELECT ub.id, ub.tenant_id, ub.site_id, ub.role_id, r.name
    FROM auth.user_bindings ub
    JOIN auth.roles r ON r.id = ub.role_id
    WHERE ub.user_id = p_user_id
      AND ub.is_active = TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.get_user_bindings(UUID) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.get_role_permissions(role_id)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.get_role_permissions(p_role_id INTEGER)
RETURNS TABLE (
    permission_key VARCHAR(100)
) AS $$
BEGIN
    RETURN QUERY
    SELECT p.key
    FROM auth.role_permissions rp
    JOIN auth.permissions p ON p.id = rp.permission_id
    WHERE rp.role_id = p_role_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.get_role_permissions(INTEGER) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.create_session(...)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.create_session(
    p_user_id UUID,
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_role_id INTEGER,
    p_session_hash CHAR(64),
    p_expires_at TIMESTAMPTZ,
    p_ip_hash CHAR(64) DEFAULT NULL,
    p_user_agent_hash CHAR(64) DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_session_id UUID;
BEGIN
    INSERT INTO auth.sessions (
        user_id, tenant_id, site_id, role_id,
        session_hash, expires_at, ip_hash, user_agent_hash
    ) VALUES (
        p_user_id, p_tenant_id, p_site_id, p_role_id,
        p_session_hash, p_expires_at, p_ip_hash, p_user_agent_hash
    )
    RETURNING id INTO v_session_id;

    -- Update user's last login
    UPDATE auth.users SET last_login_at = NOW() WHERE id = p_user_id;

    RETURN v_session_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.create_session(UUID, INTEGER, INTEGER, INTEGER, CHAR, TIMESTAMPTZ, CHAR, CHAR) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.validate_session(session_hash)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.validate_session(p_session_hash CHAR(64))
RETURNS TABLE (
    session_id UUID,
    user_id UUID,
    user_email VARCHAR(255),
    user_display_name VARCHAR(255),
    tenant_id INTEGER,
    site_id INTEGER,
    role_id INTEGER,
    role_name VARCHAR(50),
    expires_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.user_id, u.email, u.display_name,
           s.tenant_id, s.site_id, s.role_id, r.name,
           s.expires_at
    FROM auth.sessions s
    JOIN auth.users u ON u.id = s.user_id
    JOIN auth.roles r ON r.id = s.role_id
    WHERE s.session_hash = p_session_hash
      AND s.revoked_at IS NULL
      AND s.expires_at > NOW()
      AND u.is_active = TRUE
      AND u.is_locked = FALSE;

    -- Update last activity if found (use table alias to avoid ambiguity with return column)
    UPDATE auth.sessions sess
    SET last_activity_at = NOW()
    WHERE sess.session_hash = p_session_hash
      AND sess.revoked_at IS NULL
      AND sess.expires_at > NOW();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.validate_session(CHAR) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.revoke_session(session_hash, reason)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.revoke_session(
    p_session_hash CHAR(64),
    p_reason TEXT DEFAULT 'logout'
)
RETURNS BOOLEAN AS $$
DECLARE
    v_rows_affected INTEGER;
BEGIN
    UPDATE auth.sessions
    SET revoked_at = NOW(),
        revoked_reason = p_reason
    WHERE session_hash = p_session_hash
      AND revoked_at IS NULL;

    GET DIAGNOSTICS v_rows_affected = ROW_COUNT;
    RETURN v_rows_affected > 0;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.revoke_session(CHAR, TEXT) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.revoke_all_user_sessions(user_id, reason)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.revoke_all_user_sessions(
    p_user_id UUID,
    p_reason TEXT DEFAULT 'password_changed'
)
RETURNS INTEGER AS $$
DECLARE
    v_rows_affected INTEGER;
BEGIN
    UPDATE auth.sessions
    SET revoked_at = NOW(),
        revoked_reason = p_reason
    WHERE user_id = p_user_id
      AND revoked_at IS NULL;

    GET DIAGNOSTICS v_rows_affected = ROW_COUNT;
    RETURN v_rows_affected;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.revoke_all_user_sessions(UUID, TEXT) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.record_login_attempt(...)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.record_login_attempt(
    p_success BOOLEAN,
    p_user_id UUID,
    p_email VARCHAR(255),
    p_tenant_id INTEGER DEFAULT NULL,
    p_session_id UUID DEFAULT NULL,
    p_error_code VARCHAR(50) DEFAULT NULL,
    p_ip_hash CHAR(64) DEFAULT NULL,
    p_user_agent_hash CHAR(64) DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO auth.audit_log (
        event_type, user_id, user_email, tenant_id, session_id,
        error_code, ip_hash, user_agent_hash
    ) VALUES (
        CASE WHEN p_success THEN 'login_success' ELSE 'login_failed' END,
        p_user_id, p_email, p_tenant_id, p_session_id,
        p_error_code, p_ip_hash, p_user_agent_hash
    );

    -- Update failed login count
    IF NOT p_success AND p_user_id IS NOT NULL THEN
        UPDATE auth.users
        SET failed_login_count = failed_login_count + 1,
            -- Lock after 10 failed attempts
            is_locked = CASE WHEN failed_login_count >= 9 THEN TRUE ELSE is_locked END,
            lock_reason = CASE WHEN failed_login_count >= 9 THEN 'Too many failed login attempts' ELSE lock_reason END
        WHERE id = p_user_id;
    END IF;

    -- Reset failed count on success
    IF p_success AND p_user_id IS NOT NULL THEN
        UPDATE auth.users
        SET failed_login_count = 0
        WHERE id = p_user_id;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.record_login_attempt(BOOLEAN, UUID, VARCHAR, INTEGER, UUID, VARCHAR, CHAR, CHAR) TO solvereign_api;

-- =============================================================================
-- FUNCTION: auth.cleanup_expired_sessions(days)
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.cleanup_expired_sessions(p_days INTEGER DEFAULT 7)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM auth.sessions
    WHERE (revoked_at IS NOT NULL AND revoked_at < NOW() - INTERVAL '1 day' * p_days)
       OR (expires_at < NOW() - INTERVAL '1 day' * p_days);

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.cleanup_expired_sessions(INTEGER) TO solvereign_platform;

-- =============================================================================
-- FUNCTION: auth.verify_rbac_integrity()
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.verify_rbac_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Roles exist
    RETURN QUERY
    SELECT 'roles_seeded'::TEXT,
           CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s roles defined', COUNT(*))::TEXT
    FROM auth.roles;

    -- Check 2: Permissions exist
    RETURN QUERY
    SELECT 'permissions_seeded'::TEXT,
           CASE WHEN COUNT(*) >= 10 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s permissions defined', COUNT(*))::TEXT
    FROM auth.permissions;

    -- Check 3: Role-permission mappings exist
    RETURN QUERY
    SELECT 'role_permissions_mapped'::TEXT,
           CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s mappings defined', COUNT(*))::TEXT
    FROM auth.role_permissions;

    -- Check 4: Dispatcher has portal permissions
    RETURN QUERY
    SELECT 'dispatcher_has_portal_perms'::TEXT,
           CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('dispatcher has %s portal permissions', COUNT(*))::TEXT
    FROM auth.role_permissions rp
    JOIN auth.roles r ON r.id = rp.role_id
    JOIN auth.permissions p ON p.id = rp.permission_id
    WHERE r.name = 'dispatcher' AND p.category = 'portal';

    -- Check 5: Users table has RLS
    RETURN QUERY
    SELECT 'users_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.users'::TEXT
    FROM pg_class WHERE relname = 'users' AND relnamespace = 'auth'::regnamespace;

    -- Check 6: Sessions table has RLS
    RETURN QUERY
    SELECT 'sessions_rls_enabled'::TEXT,
           CASE WHEN relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'RLS on auth.sessions'::TEXT
    FROM pg_class WHERE relname = 'sessions' AND relnamespace = 'auth'::regnamespace;

    -- Check 7: Audit log has immutability trigger
    RETURN QUERY
    SELECT 'audit_log_immutable'::TEXT,
           CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'Immutability trigger on audit_log'::TEXT
    FROM pg_trigger WHERE tgname = 'tr_audit_log_immutable';

    -- Check 8: Essential functions exist
    RETURN QUERY
    SELECT 'functions_exist'::TEXT,
           CASE WHEN COUNT(*) >= 6 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s auth functions exist', COUNT(*))::TEXT
    FROM pg_proc WHERE pronamespace = 'auth'::regnamespace;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION auth.verify_rbac_integrity() TO solvereign_platform;

-- =============================================================================
-- GRANT TABLE ACCESS
-- =============================================================================

-- Read-only tables (seed data)
GRANT SELECT ON auth.roles TO solvereign_api;
GRANT SELECT ON auth.permissions TO solvereign_api;
GRANT SELECT ON auth.role_permissions TO solvereign_api;

-- Platform can manage users and bindings
GRANT SELECT, INSERT, UPDATE ON auth.users TO solvereign_platform;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth.user_bindings TO solvereign_platform;
GRANT SELECT, INSERT ON auth.sessions TO solvereign_platform;
GRANT SELECT, INSERT ON auth.audit_log TO solvereign_platform;

-- Grant sequence usage
GRANT USAGE ON ALL SEQUENCES IN SCHEMA auth TO solvereign_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA auth TO solvereign_platform;

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Run after migration:
-- SELECT * FROM auth.verify_rbac_integrity();
-- Expected: 8 checks, all PASS
