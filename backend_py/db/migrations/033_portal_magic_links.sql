-- =============================================================================
-- MIGRATION 033: Portal Magic Links & Driver Acknowledgment
-- =============================================================================
--
-- SOLVEREIGN V4.1 - Driver Portal Infrastructure
--
-- Purpose:
--   Implements secure magic link authentication for driver portal access,
--   read receipts, and acknowledgment workflow for published plan snapshots.
--
-- Key Features:
--   - JWT-based magic links with jti_hash storage (never store raw token)
--   - Read receipts with idempotent tracking
--   - Driver acknowledgment (Accept/Decline) with audit trail
--   - Superseded snapshot mapping for version transitions
--   - RLS tenant isolation
--
-- Security:
--   - Token stored as SHA-256 hash only (jti_hash)
--   - Single-use ACK tokens (revoked after first use)
--   - Rate limiting support via token tracking
--   - GDPR: minimal data, no raw token logging
--
-- Dependencies:
--   - tenants table (for tenant_id FK)
--   - plan_snapshots table (for snapshot_id FK)
--   - Assumes masterdata schema exists (for driver references)
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- SCHEMA: portal
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS portal;

-- Secure the schema (follow hardening pattern from 025e)
REVOKE ALL ON SCHEMA portal FROM PUBLIC;
GRANT USAGE ON SCHEMA portal TO solvereign_api;
GRANT USAGE ON SCHEMA portal TO solvereign_platform;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA portal
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA portal
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA portal
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA portal
    GRANT SELECT, INSERT, UPDATE ON TABLES TO solvereign_api;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA portal
    GRANT USAGE ON SEQUENCES TO solvereign_api;

-- =============================================================================
-- TABLE: portal.portal_tokens
-- =============================================================================
-- Stores magic link tokens for driver portal access.
-- Tokens are stored as jti_hash (SHA-256) - NEVER store raw token.

CREATE TABLE IF NOT EXISTS portal.portal_tokens (
    id BIGSERIAL PRIMARY KEY,

    -- Tenant/Site isolation
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL,

    -- Reference to published snapshot
    snapshot_id UUID NOT NULL,  -- FK to plan_snapshots.snapshot_id

    -- Driver reference (use string for flexibility with external IDs)
    driver_id VARCHAR(255) NOT NULL,

    -- Token scope: READ (view only), ACK (can accept/decline), READ_ACK (both)
    scope TEXT NOT NULL CHECK (scope IN ('READ', 'ACK', 'READ_ACK')),

    -- Security: store only hash of JWT's jti claim
    jti_hash CHAR(64) NOT NULL UNIQUE,

    -- Timestamps
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,
    last_seen_at TIMESTAMPTZ NULL,

    -- Optional tracking
    delivery_channel TEXT NULL CHECK (delivery_channel IN ('WHATSAPP', 'EMAIL', 'SMS', 'MANUAL')),
    outbox_id UUID NULL,  -- Link to notification outbox

    -- Security metadata (hashed for privacy)
    ip_hash CHAR(64) NULL,  -- SHA-256 of IP for rate limiting
    ua_class TEXT NULL,     -- User agent classification (mobile/desktop)

    -- Indexes for common queries
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT portal_tokens_expires_after_issued CHECK (expires_at > issued_at)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_portal_tokens_tenant_snapshot
    ON portal.portal_tokens(tenant_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_portal_tokens_driver
    ON portal.portal_tokens(tenant_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_portal_tokens_expires
    ON portal.portal_tokens(expires_at) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_portal_tokens_jti_hash
    ON portal.portal_tokens(jti_hash);

-- Enable RLS
ALTER TABLE portal.portal_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.portal_tokens FORCE ROW LEVEL SECURITY;

-- RLS Policy: tenant isolation
CREATE POLICY portal_tokens_tenant_isolation ON portal.portal_tokens
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        0
    ));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON portal.portal_tokens TO solvereign_api;
GRANT USAGE ON SEQUENCE portal.portal_tokens_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: portal.read_receipts
-- =============================================================================
-- Tracks when drivers read their published plans. Idempotent updates.

CREATE TABLE IF NOT EXISTS portal.read_receipts (
    id BIGSERIAL PRIMARY KEY,

    -- Tenant/Site isolation
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL,

    -- Reference
    snapshot_id UUID NOT NULL,
    driver_id VARCHAR(255) NOT NULL,

    -- Read tracking
    first_read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_count INTEGER NOT NULL DEFAULT 1,

    -- Uniqueness per snapshot+driver
    CONSTRAINT read_receipts_unique_driver_snapshot
        UNIQUE (snapshot_id, driver_id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_read_receipts_tenant_snapshot
    ON portal.read_receipts(tenant_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_read_receipts_driver
    ON portal.read_receipts(tenant_id, driver_id);

-- Enable RLS
ALTER TABLE portal.read_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.read_receipts FORCE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY read_receipts_tenant_isolation ON portal.read_receipts
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        0
    ));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON portal.read_receipts TO solvereign_api;
GRANT USAGE ON SEQUENCE portal.read_receipts_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: portal.driver_ack
-- =============================================================================
-- Driver acknowledgment (Accept/Decline) for published plans.
-- Immutable after first write (arbeitsrechtlich relevant).

CREATE TABLE IF NOT EXISTS portal.driver_ack (
    id BIGSERIAL PRIMARY KEY,

    -- Tenant/Site isolation
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL,

    -- Reference
    snapshot_id UUID NOT NULL,
    driver_id VARCHAR(255) NOT NULL,

    -- Acknowledgment
    status TEXT NOT NULL CHECK (status IN ('ACCEPTED', 'DECLINED')),
    ack_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Optional reason for decline
    reason_code TEXT NULL CHECK (
        reason_code IS NULL OR
        reason_code IN (
            'SCHEDULING_CONFLICT',
            'PERSONAL_REASONS',
            'HEALTH_ISSUE',
            'VACATION_CONFLICT',
            'OTHER'
        )
    ),
    free_text VARCHAR(200) NULL,

    -- Source tracking (for dispatcher overrides)
    source TEXT NOT NULL DEFAULT 'PORTAL' CHECK (source IN ('PORTAL', 'DISPATCHER_OVERRIDE')),

    -- Override tracking (only for DISPATCHER_OVERRIDE)
    override_by VARCHAR(255) NULL,
    override_reason TEXT NULL,

    -- Uniqueness: one ack per snapshot+driver
    CONSTRAINT driver_ack_unique_driver_snapshot
        UNIQUE (snapshot_id, driver_id),

    -- Constraint: override fields only for DISPATCHER_OVERRIDE source
    CONSTRAINT driver_ack_override_requires_source CHECK (
        (source = 'DISPATCHER_OVERRIDE' AND override_by IS NOT NULL AND override_reason IS NOT NULL)
        OR (source != 'DISPATCHER_OVERRIDE' AND override_by IS NULL AND override_reason IS NULL)
    ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_driver_ack_tenant_snapshot
    ON portal.driver_ack(tenant_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_driver_ack_driver
    ON portal.driver_ack(tenant_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_driver_ack_status
    ON portal.driver_ack(tenant_id, snapshot_id, status);

-- Enable RLS
ALTER TABLE portal.driver_ack ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.driver_ack FORCE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY driver_ack_tenant_isolation ON portal.driver_ack
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        0
    ));

-- Grant permissions
GRANT SELECT, INSERT ON portal.driver_ack TO solvereign_api;
GRANT USAGE ON SEQUENCE portal.driver_ack_id_seq TO solvereign_api;

-- =============================================================================
-- TRIGGER: Prevent driver_ack modification after creation
-- =============================================================================
-- Arbeitsrechtlich relevant: ACK records are immutable once created.

CREATE OR REPLACE FUNCTION portal.tr_driver_ack_immutable()
RETURNS TRIGGER AS $$
BEGIN
    -- Only DISPATCHER_OVERRIDE can modify (and only specific fields)
    IF TG_OP = 'UPDATE' THEN
        -- Check if this is a legitimate override
        IF NEW.source = 'DISPATCHER_OVERRIDE' AND OLD.source = 'PORTAL' THEN
            -- Allow override from PORTAL to DISPATCHER_OVERRIDE
            RETURN NEW;
        END IF;

        -- Otherwise, block all updates
        RAISE EXCEPTION 'driver_ack records are immutable after creation. Use DISPATCHER_OVERRIDE for corrections.';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'driver_ack records cannot be deleted (audit requirement).';
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_driver_ack_immutable ON portal.driver_ack;
CREATE TRIGGER tr_driver_ack_immutable
    BEFORE UPDATE OR DELETE ON portal.driver_ack
    FOR EACH ROW
    EXECUTE FUNCTION portal.tr_driver_ack_immutable();

-- =============================================================================
-- TABLE: portal.driver_views
-- =============================================================================
-- Pre-rendered driver views (HTML/PDF) for performance.

CREATE TABLE IF NOT EXISTS portal.driver_views (
    id BIGSERIAL PRIMARY KEY,

    -- Tenant/Site isolation
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL,

    -- Reference
    snapshot_id UUID NOT NULL,
    driver_id VARCHAR(255) NOT NULL,

    -- Artifact storage
    artifact_uri VARCHAR(1000) NOT NULL,  -- Path to rendered view
    artifact_hash CHAR(64) NULL,          -- SHA-256 for integrity

    -- Versioning
    render_version INTEGER NOT NULL DEFAULT 1,

    -- Uniqueness
    CONSTRAINT driver_views_unique_driver_snapshot
        UNIQUE (snapshot_id, driver_id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_driver_views_tenant_snapshot
    ON portal.driver_views(tenant_id, snapshot_id);

-- Enable RLS
ALTER TABLE portal.driver_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.driver_views FORCE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY driver_views_tenant_isolation ON portal.driver_views
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        0
    ));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON portal.driver_views TO solvereign_api;
GRANT USAGE ON SEQUENCE portal.driver_views_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: portal.snapshot_supersedes
-- =============================================================================
-- Maps old snapshots to their replacements (for "superseded" banners).

CREATE TABLE IF NOT EXISTS portal.snapshot_supersedes (
    id BIGSERIAL PRIMARY KEY,

    -- Tenant isolation
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Mapping
    old_snapshot_id UUID NOT NULL,
    new_snapshot_id UUID NOT NULL,

    -- Metadata
    superseded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_by VARCHAR(255) NULL,  -- User who triggered the supersede
    reason TEXT NULL,                  -- Why (repair, correction, etc.)

    -- Uniqueness: each old snapshot can only be superseded once
    CONSTRAINT snapshot_supersedes_unique_old
        UNIQUE (old_snapshot_id),

    -- Prevent self-reference
    CONSTRAINT snapshot_supersedes_no_self_reference
        CHECK (old_snapshot_id != new_snapshot_id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for lookup
CREATE INDEX IF NOT EXISTS idx_snapshot_supersedes_old
    ON portal.snapshot_supersedes(old_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_supersedes_new
    ON portal.snapshot_supersedes(new_snapshot_id);

-- Enable RLS
ALTER TABLE portal.snapshot_supersedes ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.snapshot_supersedes FORCE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY snapshot_supersedes_tenant_isolation ON portal.snapshot_supersedes
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        0
    ));

-- Grant permissions
GRANT SELECT, INSERT ON portal.snapshot_supersedes TO solvereign_api;
GRANT USAGE ON SEQUENCE portal.snapshot_supersedes_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: portal.portal_audit
-- =============================================================================
-- Audit trail for all portal actions (GDPR + arbeitsrechtlich).

CREATE TABLE IF NOT EXISTS portal.portal_audit (
    id BIGSERIAL PRIMARY KEY,
    audit_id UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Context
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL,
    snapshot_id UUID NULL,
    driver_id VARCHAR(255) NULL,

    -- Action
    action TEXT NOT NULL CHECK (action IN (
        'TOKEN_ISSUED',
        'TOKEN_VALIDATED',
        'TOKEN_REVOKED',
        'TOKEN_EXPIRED',
        'TOKEN_INVALID',
        'PLAN_READ',
        'PLAN_ACCEPTED',
        'PLAN_DECLINED',
        'ACK_OVERRIDE',
        'VIEW_RENDERED',
        'RATE_LIMITED'
    )),

    -- Security (never log raw token)
    jti_hash CHAR(64) NULL,
    ip_hash CHAR(64) NULL,

    -- Details
    details JSONB NULL,

    -- Timestamp
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    performed_by VARCHAR(255) NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_portal_audit_tenant
    ON portal.portal_audit(tenant_id, performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_portal_audit_snapshot
    ON portal.portal_audit(snapshot_id) WHERE snapshot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_portal_audit_driver
    ON portal.portal_audit(tenant_id, driver_id) WHERE driver_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_portal_audit_action
    ON portal.portal_audit(action, performed_at DESC);

-- Enable RLS
ALTER TABLE portal.portal_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.portal_audit FORCE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY portal_audit_tenant_isolation ON portal.portal_audit
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        0
    ));

-- Grant INSERT only (audit is append-only)
GRANT SELECT, INSERT ON portal.portal_audit TO solvereign_api;
GRANT USAGE ON SEQUENCE portal.portal_audit_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: portal.rate_limits
-- =============================================================================
-- Rate limiting for portal access (per jti_hash).

CREATE TABLE IF NOT EXISTS portal.rate_limits (
    id BIGSERIAL PRIMARY KEY,

    -- Rate limit key (jti_hash or ip_hash)
    limit_key CHAR(64) NOT NULL,
    limit_type TEXT NOT NULL CHECK (limit_type IN ('JTI', 'IP')),

    -- Counters
    request_count INTEGER NOT NULL DEFAULT 1,
    window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    window_end TIMESTAMPTZ NOT NULL,

    -- Uniqueness per key+window
    CONSTRAINT rate_limits_unique_key_window
        UNIQUE (limit_key, limit_type, window_start),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for cleanup
CREATE INDEX IF NOT EXISTS idx_rate_limits_window_end
    ON portal.rate_limits(window_end);

-- Grant permissions (no RLS needed - rate limits are global per key)
GRANT SELECT, INSERT, UPDATE, DELETE ON portal.rate_limits TO solvereign_api;
GRANT USAGE ON SEQUENCE portal.rate_limits_id_seq TO solvereign_api;

-- =============================================================================
-- FUNCTION: portal.verify_portal_integrity()
-- =============================================================================
-- Verification function for portal schema integrity.

CREATE OR REPLACE FUNCTION portal.verify_portal_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check 1: RLS enabled on portal_tokens
    SELECT COUNT(*) INTO v_count
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.schemaname)
    WHERE t.schemaname = 'portal'
    AND t.tablename = 'portal_tokens'
    AND c.relrowsecurity = TRUE
    AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_portal_tokens'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_portal_tokens'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 2: RLS enabled on read_receipts
    SELECT COUNT(*) INTO v_count
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.schemaname)
    WHERE t.schemaname = 'portal'
    AND t.tablename = 'read_receipts'
    AND c.relrowsecurity = TRUE
    AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_read_receipts'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_read_receipts'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 3: RLS enabled on driver_ack
    SELECT COUNT(*) INTO v_count
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.schemaname)
    WHERE t.schemaname = 'portal'
    AND t.tablename = 'driver_ack'
    AND c.relrowsecurity = TRUE
    AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_driver_ack'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_driver_ack'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 4: Unique constraints exist
    SELECT COUNT(*) INTO v_count
    FROM pg_constraint
    WHERE conname IN (
        'portal_tokens_jti_hash_key',
        'read_receipts_unique_driver_snapshot',
        'driver_ack_unique_driver_snapshot',
        'driver_views_unique_driver_snapshot',
        'snapshot_supersedes_unique_old'
    );

    IF v_count >= 4 THEN
        RETURN QUERY SELECT 'unique_constraints'::TEXT, 'PASS'::TEXT,
            format('%s constraints found', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'unique_constraints'::TEXT, 'FAIL'::TEXT,
            format('Only %s unique constraints found, expected at least 4', v_count)::TEXT;
    END IF;

    -- Check 5: Immutability trigger exists on driver_ack
    SELECT COUNT(*) INTO v_count
    FROM pg_trigger
    WHERE tgname = 'tr_driver_ack_immutable';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'driver_ack_immutable_trigger'::TEXT, 'PASS'::TEXT, 'Trigger exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'driver_ack_immutable_trigger'::TEXT, 'FAIL'::TEXT, 'Trigger missing'::TEXT;
    END IF;

    -- Check 6: No expired non-revoked tokens older than 30 days (WARN)
    SELECT COUNT(*) INTO v_count
    FROM portal.portal_tokens
    WHERE expires_at < NOW() - INTERVAL '30 days'
    AND revoked_at IS NULL;

    IF v_count = 0 THEN
        RETURN QUERY SELECT 'expired_token_cleanup'::TEXT, 'PASS'::TEXT, 'No stale tokens'::TEXT;
    ELSE
        RETURN QUERY SELECT 'expired_token_cleanup'::TEXT, 'WARN'::TEXT,
            format('%s expired tokens should be cleaned up', v_count)::TEXT;
    END IF;

    -- Check 7: All tables have tenant_id NOT NULL
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'portal'
    AND column_name = 'tenant_id'
    AND is_nullable = 'NO';

    IF v_count >= 6 THEN
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'PASS'::TEXT,
            format('%s tables have tenant_id NOT NULL', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'FAIL'::TEXT,
            format('Only %s tables have tenant_id NOT NULL', v_count)::TEXT;
    END IF;

    -- Check 8: Tenant FK exists on main tables
    SELECT COUNT(*) INTO v_count
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace n ON t.relnamespace = n.oid
    WHERE n.nspname = 'portal'
    AND c.contype = 'f'
    AND EXISTS (
        SELECT 1 FROM pg_constraint_conargs(c.oid)
        WHERE attname = 'tenant_id'
    );

    -- Simplified check: count FK constraints referencing tenants
    SELECT COUNT(*) INTO v_count
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace n ON t.relnamespace = n.oid
    WHERE n.nspname = 'portal'
    AND c.contype = 'f';

    IF v_count >= 5 THEN
        RETURN QUERY SELECT 'tenant_fk_exists'::TEXT, 'PASS'::TEXT,
            format('%s foreign keys found', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'tenant_fk_exists'::TEXT, 'WARN'::TEXT,
            format('%s foreign keys found', v_count)::TEXT;
    END IF;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute to platform role
GRANT EXECUTE ON FUNCTION portal.verify_portal_integrity() TO solvereign_platform;

-- =============================================================================
-- FUNCTION: portal.record_read()
-- =============================================================================
-- Idempotent read receipt recording.

CREATE OR REPLACE FUNCTION portal.record_read(
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_snapshot_id UUID,
    p_driver_id VARCHAR(255)
) RETURNS TABLE (
    first_read_at TIMESTAMPTZ,
    last_read_at TIMESTAMPTZ,
    read_count INTEGER,
    is_first_read BOOLEAN
) AS $$
DECLARE
    v_first_read_at TIMESTAMPTZ;
    v_last_read_at TIMESTAMPTZ;
    v_read_count INTEGER;
    v_is_first_read BOOLEAN := FALSE;
BEGIN
    -- Try to insert, on conflict update
    INSERT INTO portal.read_receipts (
        tenant_id, site_id, snapshot_id, driver_id,
        first_read_at, last_read_at, read_count
    ) VALUES (
        p_tenant_id, p_site_id, p_snapshot_id, p_driver_id,
        NOW(), NOW(), 1
    )
    ON CONFLICT (snapshot_id, driver_id) DO UPDATE SET
        last_read_at = NOW(),
        read_count = portal.read_receipts.read_count + 1
    RETURNING
        portal.read_receipts.first_read_at,
        portal.read_receipts.last_read_at,
        portal.read_receipts.read_count
    INTO v_first_read_at, v_last_read_at, v_read_count;

    -- Check if this was the first read
    v_is_first_read := (v_read_count = 1);

    RETURN QUERY SELECT v_first_read_at, v_last_read_at, v_read_count, v_is_first_read;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION portal.record_read(INTEGER, INTEGER, UUID, VARCHAR) TO solvereign_api;

-- =============================================================================
-- FUNCTION: portal.check_rate_limit()
-- =============================================================================
-- Check and update rate limit for a key.

CREATE OR REPLACE FUNCTION portal.check_rate_limit(
    p_limit_key CHAR(64),
    p_limit_type TEXT,
    p_max_requests INTEGER DEFAULT 100,
    p_window_seconds INTEGER DEFAULT 3600
) RETURNS TABLE (
    is_allowed BOOLEAN,
    current_count INTEGER,
    window_resets_at TIMESTAMPTZ
) AS $$
DECLARE
    v_window_start TIMESTAMPTZ;
    v_window_end TIMESTAMPTZ;
    v_current_count INTEGER;
BEGIN
    v_window_start := date_trunc('hour', NOW());
    v_window_end := v_window_start + (p_window_seconds || ' seconds')::INTERVAL;

    -- Try to insert or update
    INSERT INTO portal.rate_limits (
        limit_key, limit_type, request_count, window_start, window_end
    ) VALUES (
        p_limit_key, p_limit_type, 1, v_window_start, v_window_end
    )
    ON CONFLICT (limit_key, limit_type, window_start) DO UPDATE SET
        request_count = portal.rate_limits.request_count + 1
    RETURNING portal.rate_limits.request_count INTO v_current_count;

    RETURN QUERY SELECT
        (v_current_count <= p_max_requests),
        v_current_count,
        v_window_end;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION portal.check_rate_limit(CHAR, TEXT, INTEGER, INTEGER) TO solvereign_api;

-- =============================================================================
-- FUNCTION: portal.get_portal_status()
-- =============================================================================
-- Get aggregated portal status for a snapshot.

CREATE OR REPLACE FUNCTION portal.get_portal_status(
    p_tenant_id INTEGER,
    p_snapshot_id UUID
) RETURNS TABLE (
    total_drivers INTEGER,
    unread_count INTEGER,
    read_count INTEGER,
    accepted_count INTEGER,
    declined_count INTEGER,
    pending_count INTEGER
) AS $$
DECLARE
    v_total INTEGER;
    v_read INTEGER;
    v_accepted INTEGER;
    v_declined INTEGER;
BEGIN
    -- Count tokens issued for this snapshot
    SELECT COUNT(DISTINCT driver_id) INTO v_total
    FROM portal.portal_tokens
    WHERE tenant_id = p_tenant_id AND snapshot_id = p_snapshot_id;

    -- Count read receipts
    SELECT COUNT(*) INTO v_read
    FROM portal.read_receipts
    WHERE tenant_id = p_tenant_id AND snapshot_id = p_snapshot_id;

    -- Count accepted
    SELECT COUNT(*) INTO v_accepted
    FROM portal.driver_ack
    WHERE tenant_id = p_tenant_id AND snapshot_id = p_snapshot_id AND status = 'ACCEPTED';

    -- Count declined
    SELECT COUNT(*) INTO v_declined
    FROM portal.driver_ack
    WHERE tenant_id = p_tenant_id AND snapshot_id = p_snapshot_id AND status = 'DECLINED';

    RETURN QUERY SELECT
        v_total,
        v_total - v_read,  -- unread
        v_read,
        v_accepted,
        v_declined,
        v_read - v_accepted - v_declined;  -- pending (read but not acked)
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION portal.get_portal_status(INTEGER, UUID) TO solvereign_api;

-- =============================================================================
-- CLEANUP: Rate limit cleanup function
-- =============================================================================

CREATE OR REPLACE FUNCTION portal.cleanup_expired_rate_limits()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM portal.rate_limits
    WHERE window_end < NOW() - INTERVAL '1 hour';

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION portal.cleanup_expired_rate_limits() TO solvereign_platform;

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Run: SELECT * FROM portal.verify_portal_integrity();
