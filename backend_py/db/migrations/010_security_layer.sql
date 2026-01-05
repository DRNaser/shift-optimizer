-- =============================================================================
-- SOLVEREIGN V3.3b - Security Layer Migration
-- =============================================================================
--
-- This migration adds:
-- 1. Security audit log with hash chain
-- 2. Row-Level Security (RLS) policies
-- 3. Immutability constraints
--
-- Run with: psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f 010_security_layer.sql
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. SECURITY AUDIT LOG
-- =============================================================================

CREATE TABLE IF NOT EXISTS security_audit_log (
    id BIGSERIAL PRIMARY KEY,

    -- Event metadata
    event_type VARCHAR(100) NOT NULL,
    tenant_id UUID,
    user_id UUID,
    severity VARCHAR(20) NOT NULL DEFAULT 'INFO',

    -- Request context
    ip_address INET,
    user_agent TEXT,
    request_id VARCHAR(100),

    -- Event details
    details_json JSONB,

    -- Timestamps
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Hash chain for tamper detection
    previous_hash VARCHAR(64),
    current_hash VARCHAR(64) NOT NULL,

    -- Constraints
    CONSTRAINT valid_severity CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL'))
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_security_audit_tenant ON security_audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_security_audit_user ON security_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_security_audit_event_type ON security_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_security_audit_severity ON security_audit_log(severity);
CREATE INDEX IF NOT EXISTS idx_security_audit_timestamp ON security_audit_log(timestamp DESC);

-- Hash chain computation trigger
CREATE OR REPLACE FUNCTION compute_security_audit_hash()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash VARCHAR(64);
    hash_input TEXT;
BEGIN
    -- Get previous hash
    SELECT current_hash INTO prev_hash
    FROM security_audit_log
    ORDER BY id DESC
    LIMIT 1;

    NEW.previous_hash := prev_hash;

    -- Compute current hash
    hash_input := COALESCE(prev_hash, 'GENESIS') ||
                  NEW.timestamp::TEXT ||
                  NEW.event_type ||
                  COALESCE(NEW.tenant_id::TEXT, '') ||
                  COALESCE(NEW.user_id::TEXT, '') ||
                  NEW.severity ||
                  COALESCE(NEW.details_json::TEXT, '{}');

    NEW.current_hash := encode(sha256(hash_input::BYTEA), 'hex');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS security_audit_hash_trigger ON security_audit_log;
CREATE TRIGGER security_audit_hash_trigger
    BEFORE INSERT ON security_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION compute_security_audit_hash();

-- =============================================================================
-- 2. IMMUTABILITY: Prevent modification of audit log
-- =============================================================================

-- Prevent UPDATE on security_audit_log
CREATE OR REPLACE FUNCTION prevent_audit_log_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Security audit log is immutable. UPDATE not allowed.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS prevent_audit_update ON security_audit_log;
CREATE TRIGGER prevent_audit_update
    BEFORE UPDATE ON security_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_update();

-- Prevent DELETE on security_audit_log
CREATE OR REPLACE FUNCTION prevent_audit_log_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Security audit log is immutable. DELETE not allowed.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS prevent_audit_delete ON security_audit_log;
CREATE TRIGGER prevent_audit_delete
    BEFORE DELETE ON security_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_delete();

-- =============================================================================
-- 3. ROW-LEVEL SECURITY (RLS)
-- =============================================================================

-- Enable RLS on tables
ALTER TABLE forecast_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE tours_raw ENABLE ROW LEVEL SECURITY;
ALTER TABLE tours_normalized ENABLE ROW LEVEL SECURITY;
ALTER TABLE tour_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- 3.1 APPLICATION ROLES (Security-Critical)
-- =============================================================================

-- API Role: Used by application for all runtime queries
-- CRITICAL: NO BYPASSRLS, NO SUPERUSER, NOINHERIT
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        CREATE ROLE solvereign_api NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

-- Ensure API role cannot bypass RLS (defense in depth)
ALTER ROLE solvereign_api NOBYPASSRLS;

-- Admin Role: Used ONLY for migrations and maintenance
-- Has BYPASSRLS but should NEVER be used by application
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        CREATE ROLE solvereign_admin NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
    END IF;
END
$$;

-- Grant schema usage to API role
GRANT USAGE ON SCHEMA public TO solvereign_api;

-- Grant table access to API role (SELECT, INSERT, UPDATE, DELETE)
-- RLS policies will restrict actual row access
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO solvereign_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO solvereign_api;

-- Grant full access to admin role (for migrations)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO solvereign_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO solvereign_admin;

-- RLS policies for forecast_versions
DROP POLICY IF EXISTS tenant_isolation_forecast ON forecast_versions;
CREATE POLICY tenant_isolation_forecast ON forecast_versions
    FOR ALL
    USING (
        tenant_id::TEXT = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_super_admin', true) = 'true'
    );

-- RLS policies for plan_versions
DROP POLICY IF EXISTS tenant_isolation_plan ON plan_versions;
CREATE POLICY tenant_isolation_plan ON plan_versions
    FOR ALL
    USING (
        tenant_id::TEXT = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_super_admin', true) = 'true'
    );

-- RLS policies for assignments
DROP POLICY IF EXISTS tenant_isolation_assignments ON assignments;
CREATE POLICY tenant_isolation_assignments ON assignments
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM plan_versions pv
            WHERE pv.id = assignments.plan_version_id
            AND (
                pv.tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            )
        )
    );

-- RLS policies for tours_raw
DROP POLICY IF EXISTS tenant_isolation_tours_raw ON tours_raw;
CREATE POLICY tenant_isolation_tours_raw ON tours_raw
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM forecast_versions fv
            WHERE fv.id = tours_raw.forecast_version_id
            AND (
                fv.tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            )
        )
    );

-- RLS policies for tours_normalized
DROP POLICY IF EXISTS tenant_isolation_tours_normalized ON tours_normalized;
CREATE POLICY tenant_isolation_tours_normalized ON tours_normalized
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM forecast_versions fv
            WHERE fv.id = tours_normalized.forecast_version_id
            AND (
                fv.tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            )
        )
    );

-- RLS policies for tour_instances
DROP POLICY IF EXISTS tenant_isolation_tour_instances ON tour_instances;
CREATE POLICY tenant_isolation_tour_instances ON tour_instances
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM forecast_versions fv
            WHERE fv.id = tour_instances.forecast_version_id
            AND (
                fv.tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            )
        )
    );

-- RLS policies for audit_log (read own tenant only)
DROP POLICY IF EXISTS tenant_isolation_audit_log ON audit_log;
CREATE POLICY tenant_isolation_audit_log ON audit_log
    FOR SELECT
    USING (
        tenant_id::TEXT = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_super_admin', true) = 'true'
    );

-- Audit log insert policy (anyone can insert)
DROP POLICY IF EXISTS audit_log_insert_policy ON audit_log;
CREATE POLICY audit_log_insert_policy ON audit_log
    FOR INSERT
    WITH CHECK (true);

-- Security audit log: Tenant can read own, super admin reads all
DROP POLICY IF EXISTS security_audit_read_policy ON security_audit_log;
CREATE POLICY security_audit_read_policy ON security_audit_log
    FOR SELECT
    USING (
        tenant_id::TEXT = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_super_admin', true) = 'true'
    );

-- Security audit log: Insert always allowed (for logging)
DROP POLICY IF EXISTS security_audit_insert_policy ON security_audit_log;
CREATE POLICY security_audit_insert_policy ON security_audit_log
    FOR INSERT
    WITH CHECK (true);

-- =============================================================================
-- 4. HELPER FUNCTIONS FOR RLS
-- =============================================================================

-- Function to set tenant context (called at start of each transaction)
-- IMPORTANT: Uses SET LOCAL for transaction-scoped settings (connection pool safe)
-- The 'true' parameter to set_config means "local to transaction"
CREATE OR REPLACE FUNCTION set_tenant_context(p_tenant_id TEXT, p_is_super_admin BOOLEAN DEFAULT false)
RETURNS VOID AS $$
BEGIN
    -- Set tenant_id for RLS policies (transaction-local)
    PERFORM set_config('app.current_tenant_id', p_tenant_id, true);
    PERFORM set_config('app.is_super_admin', p_is_super_admin::TEXT, true);

    -- Log context setting for debugging (can be disabled in production)
    -- RAISE NOTICE 'Tenant context set: tenant=%, super_admin=%', p_tenant_id, p_is_super_admin;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to clear tenant context (called at end of transaction or on error)
CREATE OR REPLACE FUNCTION clear_tenant_context()
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    PERFORM set_config('app.is_super_admin', 'false', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get current tenant (for debugging/logging)
CREATE OR REPLACE FUNCTION get_current_tenant()
RETURNS TEXT AS $$
BEGIN
    RETURN current_setting('app.current_tenant_id', true);
END;
$$ LANGUAGE plpgsql STABLE;

-- =============================================================================
-- 5. AUDIT LOG INTEGRITY CHECK
-- =============================================================================

CREATE OR REPLACE FUNCTION verify_security_audit_chain(
    p_start_id BIGINT DEFAULT 1,
    p_limit INTEGER DEFAULT 1000
)
RETURNS TABLE (
    is_valid BOOLEAN,
    checked_count INTEGER,
    first_invalid_id BIGINT
) AS $$
DECLARE
    prev_hash VARCHAR(64);
    computed_hash VARCHAR(64);
    hash_input TEXT;
    rec RECORD;
    check_count INTEGER := 0;
    invalid_id BIGINT := NULL;
BEGIN
    FOR rec IN
        SELECT id, event_type, tenant_id, user_id, severity,
               details_json, timestamp, previous_hash, current_hash
        FROM security_audit_log
        WHERE id >= p_start_id
        ORDER BY id ASC
        LIMIT p_limit
    LOOP
        check_count := check_count + 1;

        -- Compute expected hash
        hash_input := COALESCE(rec.previous_hash, 'GENESIS') ||
                      rec.timestamp::TEXT ||
                      rec.event_type ||
                      COALESCE(rec.tenant_id::TEXT, '') ||
                      COALESCE(rec.user_id::TEXT, '') ||
                      rec.severity ||
                      COALESCE(rec.details_json::TEXT, '{}');

        computed_hash := encode(sha256(hash_input::BYTEA), 'hex');

        -- Check hash matches
        IF rec.current_hash != computed_hash THEN
            invalid_id := rec.id;
            RETURN QUERY SELECT false, check_count, invalid_id;
            RETURN;
        END IF;

        -- Check chain continuity
        IF prev_hash IS NOT NULL AND rec.previous_hash != prev_hash THEN
            invalid_id := rec.id;
            RETURN QUERY SELECT false, check_count, invalid_id;
            RETURN;
        END IF;

        prev_hash := rec.current_hash;
    END LOOP;

    RETURN QUERY SELECT true, check_count, NULL::BIGINT;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 6. MIGRATION TRACKING
-- =============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES (
    '010_security_layer',
    'Security audit log with hash chain, RLS policies, immutability constraints',
    NOW()
)
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- =============================================================================
-- VERIFICATION QUERIES (run manually to verify)
-- =============================================================================

-- Check RLS is enabled:
-- SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';

-- Check policies:
-- SELECT * FROM pg_policies WHERE schemaname = 'public';

-- Verify audit chain:
-- SELECT * FROM verify_security_audit_chain();
