-- =============================================================================
-- Migration 017: Service Status and Escalation Tracking
-- =============================================================================
-- Implements the escalation strategy with severity levels (S0-S3):
--   - S0: Security/Data Leak Risk - Hard Stop
--   - S1: Integrity/Evidence Risk - Block Lock/Repair
--   - S2: Operational Degraded - Fallback Mode
--   - S3: UX/Non-critical - Log Only
--
-- Service status is scoped by platform/org/tenant/site for granular control.
-- =============================================================================

BEGIN;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('017', 'Service status and escalation tracking')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- ENUM: Severity Level
-- =============================================================================
CREATE TYPE core.severity_level AS ENUM ('S0', 'S1', 'S2', 'S3');

-- =============================================================================
-- ENUM: Service Status
-- =============================================================================
CREATE TYPE core.service_status_enum AS ENUM ('healthy', 'degraded', 'blocked');

-- =============================================================================
-- ENUM: Scope Type
-- =============================================================================
CREATE TYPE core.scope_type AS ENUM ('platform', 'org', 'tenant', 'site');

-- =============================================================================
-- TABLE: core.service_status
-- =============================================================================
-- Tracks operational health state at different scopes.
-- UI dashboards read this to show health tiles and banners.
-- GREENFIELD FIX: Drop simpler version from 000_initial_schema if exists

DROP TABLE IF EXISTS core.service_status CASCADE;

CREATE TABLE core.service_status (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scope
    scope_type      core.scope_type NOT NULL,
    scope_id        UUID,                             -- NULL for platform scope

    -- Status
    status          core.service_status_enum NOT NULL DEFAULT 'healthy',
    severity        core.severity_level NOT NULL DEFAULT 'S3',

    -- Reason
    reason_code     VARCHAR(100) NOT NULL,            -- e.g., OSRM_DOWN, EVIDENCE_HASH_MISMATCH
    reason_message  TEXT,                             -- Human-readable description

    -- Fix guidance
    fix_steps       TEXT[],                           -- Array of fix instructions
    runbook_link    VARCHAR(500),                     -- URL to runbook section

    -- Details
    details         JSONB DEFAULT '{}',               -- Additional context

    -- Lifecycle
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,                      -- NULL = still active
    resolved_by     VARCHAR(255),                     -- Who resolved it

    -- Prevent duplicate active statuses for same scope+reason
    CONSTRAINT unique_active_status UNIQUE NULLS NOT DISTINCT (scope_type, scope_id, reason_code, ended_at)
);

CREATE INDEX idx_core_service_status_scope ON core.service_status(scope_type, scope_id);
CREATE INDEX idx_core_service_status_active ON core.service_status(scope_type, scope_id) WHERE ended_at IS NULL;
CREATE INDEX idx_core_service_status_severity ON core.service_status(severity) WHERE ended_at IS NULL;
CREATE INDEX idx_core_service_status_started ON core.service_status(started_at);

-- Add updated_at trigger
CREATE TRIGGER trg_service_status_updated_at
    BEFORE UPDATE ON core.service_status
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

COMMENT ON TABLE core.service_status IS 'Tracks service health state at platform/org/tenant/site scope.';
COMMENT ON COLUMN core.service_status.reason_code IS 'Machine-readable reason (e.g., OSRM_DOWN, RLS_VIOLATION)';
COMMENT ON COLUMN core.service_status.fix_steps IS 'Human-readable fix steps for operators';
COMMENT ON COLUMN core.service_status.runbook_link IS 'Link to runbook section for this issue';

-- =============================================================================
-- RLS POLICIES: core.service_status
-- =============================================================================
-- Platform admin: full access
-- Tenant users: read their scope only

ALTER TABLE core.service_status ENABLE ROW LEVEL SECURITY;

-- Platform admins: full access
CREATE POLICY service_status_platform_admin ON core.service_status
    FOR ALL
    USING (core.app_is_platform_admin() = TRUE)
    WITH CHECK (core.app_is_platform_admin() = TRUE);

-- Tenant users: read platform-wide + their own scope
CREATE POLICY service_status_tenant_read ON core.service_status
    FOR SELECT
    USING (
        core.app_is_platform_admin() = FALSE
        AND (
            -- Platform-wide status (e.g., maintenance)
            scope_type = 'platform'
            -- Or their org
            OR (scope_type = 'org' AND scope_id IN (
                SELECT owner_org_id FROM core.tenants WHERE id = core.app_current_tenant_id()
            ))
            -- Or their tenant
            OR (scope_type = 'tenant' AND scope_id = core.app_current_tenant_id())
            -- Or their site
            OR (scope_type = 'site' AND scope_id IN (
                SELECT id FROM core.sites WHERE tenant_id = core.app_current_tenant_id()
            ))
        )
    );

-- =============================================================================
-- REASON CODE REFERENCE TABLE
-- =============================================================================
-- Documents all known reason codes with their fix steps.

CREATE TABLE core.reason_code_registry (
    reason_code     VARCHAR(100) PRIMARY KEY,
    severity        core.severity_level NOT NULL,
    category        VARCHAR(50) NOT NULL,             -- security, integrity, infra, application
    description     TEXT NOT NULL,
    default_fix_steps TEXT[],
    runbook_section VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed common reason codes
INSERT INTO core.reason_code_registry (reason_code, severity, category, description, default_fix_steps, runbook_section) VALUES
    -- S0: Security
    ('PLATFORM_ADMIN_SPOOF', 'S0', 'security', 'Attempt to spoof platform admin via headers without valid signature',
     ARRAY['Block client IP', 'Review access logs', 'Verify no data leak'], 'security/admin-spoof'),
    ('RLS_VIOLATION', 'S0', 'security', 'Cross-tenant data access attempt detected',
     ARRAY['Block request', 'Audit affected queries', 'Review RLS policies'], 'security/rls-violation'),
    ('SIGNATURE_INVALID', 'S0', 'security', 'Invalid or expired internal signature',
     ARRAY['Verify BFF secret key', 'Check clock sync', 'Review request source'], 'security/signature'),
    ('REPLAY_ATTACK', 'S0', 'security', 'Reused signature detected (replay attack)',
     ARRAY['Block client', 'Invalidate session', 'Review IP patterns'], 'security/replay'),

    -- S1: Integrity
    ('EVIDENCE_HASH_MISMATCH', 'S1', 'integrity', 'Evidence pack hash does not match stored value',
     ARRAY['Block plan lock', 'Re-generate evidence', 'Verify artifact store'], 'integrity/evidence-hash'),
    ('SNAPSHOT_HASH_MISMATCH', 'S1', 'integrity', 'Snapshot hash does not match during replay/verify',
     ARRAY['Block operation', 'Compare snapshots', 'Check for tampering'], 'integrity/snapshot-hash'),
    ('ARTIFACT_WRITE_FAILED', 'S1', 'integrity', 'Failed to write artifact to store during LOCK',
     ARRAY['Check artifact store health', 'Retry with backoff', 'Manual upload'], 'integrity/artifact-write'),
    ('FREEZE_LOCK_BYPASS', 'S1', 'integrity', 'Attempt to modify frozen/locked data',
     ARRAY['Block modification', 'Log violation', 'Review freeze window'], 'integrity/freeze-bypass'),

    -- S2: Operational
    ('OSRM_DOWN', 'S2', 'infra', 'OSRM routing service unavailable',
     ARRAY['Use fallback (static matrix)', 'Check OSRM container', 'Review network'], 'infra/osrm-down'),
    ('QUEUE_BACKLOG', 'S2', 'infra', 'Job queue backlog exceeds threshold',
     ARRAY['Scale workers', 'Check Celery/Redis health', 'Review job priorities'], 'infra/queue-backlog'),
    ('SOLVER_TIMEOUT', 'S2', 'application', 'Solver repeatedly exceeding timeout',
     ARRAY['Reduce problem size', 'Increase timeout', 'Check resource usage'], 'application/solver-timeout'),
    ('DATABASE_SLOW', 'S2', 'infra', 'Database response time exceeds threshold',
     ARRAY['Check connection pool', 'Review slow queries', 'Scale resources'], 'infra/database-slow'),
    ('IMPORT_VALIDATION_HIGH', 'S2', 'application', 'Import validation warning rate exceeds threshold',
     ARRAY['Review input quality', 'Check parser rules', 'Contact data source'], 'application/import-validation'),

    -- S3: Minor
    ('UI_ERROR', 'S3', 'application', 'Non-critical UI error logged',
     ARRAY['Check browser console', 'Review error logs'], 'application/ui-error'),
    ('SLOW_PAGE_LOAD', 'S3', 'application', 'Page load time exceeds threshold',
     ARRAY['Check CDN', 'Review bundle size', 'Profile frontend'], 'application/slow-page'),
    ('MINOR_VALIDATION_WARN', 'S3', 'application', 'Minor validation warning (non-blocking)',
     ARRAY['Review warning details', 'Update rules if needed'], 'application/validation-warn')
ON CONFLICT (reason_code) DO NOTHING;

COMMENT ON TABLE core.reason_code_registry IS 'Registry of all reason codes with default fix steps and runbook links.';

-- =============================================================================
-- HELPER FUNCTIONS: Escalation
-- =============================================================================

-- Record escalation event
CREATE OR REPLACE FUNCTION core.record_escalation(
    p_scope_type core.scope_type,
    p_scope_id UUID,
    p_reason_code VARCHAR,
    p_details JSONB DEFAULT '{}'
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_registry_row core.reason_code_registry;
    v_status_id UUID;
BEGIN
    -- Get reason code details from registry
    SELECT * INTO v_registry_row FROM core.reason_code_registry WHERE reason_code = p_reason_code;

    IF NOT FOUND THEN
        -- Unknown reason code - use S2 as safe default
        v_registry_row.severity := 'S2';
        v_registry_row.default_fix_steps := ARRAY['Check logs', 'Contact support'];
        v_registry_row.runbook_section := 'unknown';
    END IF;

    -- Insert status record
    INSERT INTO core.service_status (
        scope_type, scope_id, status, severity,
        reason_code, reason_message,
        fix_steps, runbook_link, details
    ) VALUES (
        p_scope_type, p_scope_id,
        CASE
            WHEN v_registry_row.severity = 'S0' THEN 'blocked'::core.service_status_enum
            WHEN v_registry_row.severity = 'S1' THEN 'blocked'::core.service_status_enum
            WHEN v_registry_row.severity = 'S2' THEN 'degraded'::core.service_status_enum
            ELSE 'healthy'::core.service_status_enum
        END,
        v_registry_row.severity,
        p_reason_code,
        COALESCE(v_registry_row.description, p_reason_code),
        v_registry_row.default_fix_steps,
        '/runbook/' || COALESCE(v_registry_row.runbook_section, 'unknown'),
        p_details
    )
    RETURNING id INTO v_status_id;

    RETURN v_status_id;
END;
$$;

-- Resolve escalation
CREATE OR REPLACE FUNCTION core.resolve_escalation(
    p_scope_type core.scope_type,
    p_scope_id UUID,
    p_reason_code VARCHAR,
    p_resolved_by VARCHAR DEFAULT 'system'
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE core.service_status
    SET ended_at = NOW(),
        resolved_by = p_resolved_by,
        status = 'healthy'
    WHERE scope_type = p_scope_type
      AND (scope_id = p_scope_id OR (scope_id IS NULL AND p_scope_id IS NULL))
      AND reason_code = p_reason_code
      AND ended_at IS NULL;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- Get active escalations for scope
CREATE OR REPLACE FUNCTION core.get_active_escalations(
    p_scope_type core.scope_type DEFAULT NULL,
    p_scope_id UUID DEFAULT NULL
)
RETURNS SETOF core.service_status
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT * FROM core.service_status
    WHERE ended_at IS NULL
      AND (p_scope_type IS NULL OR scope_type = p_scope_type)
      AND (p_scope_id IS NULL OR scope_id = p_scope_id)
    ORDER BY
        CASE severity
            WHEN 'S0' THEN 0
            WHEN 'S1' THEN 1
            WHEN 'S2' THEN 2
            WHEN 'S3' THEN 3
        END,
        started_at DESC;
$$;

-- Check if scope is blocked (S0/S1)
CREATE OR REPLACE FUNCTION core.is_scope_blocked(
    p_scope_type core.scope_type,
    p_scope_id UUID DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT EXISTS (
        SELECT 1 FROM core.service_status
        WHERE ended_at IS NULL
          AND (
              -- Exact scope match
              (scope_type = p_scope_type AND (scope_id = p_scope_id OR (scope_id IS NULL AND p_scope_id IS NULL)))
              -- Or platform-wide block
              OR scope_type = 'platform'
          )
          AND severity IN ('S0', 'S1')
    );
$$;

-- Check if scope is degraded (S2)
CREATE OR REPLACE FUNCTION core.is_scope_degraded(
    p_scope_type core.scope_type,
    p_scope_id UUID DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT EXISTS (
        SELECT 1 FROM core.service_status
        WHERE ended_at IS NULL
          AND (
              (scope_type = p_scope_type AND (scope_id = p_scope_id OR (scope_id IS NULL AND p_scope_id IS NULL)))
              OR scope_type = 'platform'
          )
          AND severity IN ('S0', 'S1', 'S2')
    );
$$;

COMMENT ON FUNCTION core.record_escalation IS 'Record a new escalation event. Automatically sets severity/status from registry.';
COMMENT ON FUNCTION core.resolve_escalation IS 'Resolve (end) an escalation. Returns count of resolved records.';
COMMENT ON FUNCTION core.get_active_escalations IS 'Get all active escalations, optionally filtered by scope.';
COMMENT ON FUNCTION core.is_scope_blocked IS 'Check if scope has S0/S1 block. Use before critical operations.';
COMMENT ON FUNCTION core.is_scope_degraded IS 'Check if scope has any degradation (S0-S2). Use for UI banners.';

-- =============================================================================
-- ESCALATION COUNTERS (for rate limiting)
-- =============================================================================

CREATE TABLE core.escalation_counters (
    counter_key     VARCHAR(200) PRIMARY KEY,         -- e.g., "security:ip:192.168.1.1"
    count           INTEGER NOT NULL DEFAULT 1,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_core_escalation_counters_expires ON core.escalation_counters(expires_at);

-- Increment counter (atomic)
CREATE OR REPLACE FUNCTION core.increment_escalation_counter(
    p_key VARCHAR,
    p_window_minutes INTEGER DEFAULT 60
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    INSERT INTO core.escalation_counters (counter_key, count, expires_at)
    VALUES (p_key, 1, NOW() + (p_window_minutes || ' minutes')::INTERVAL)
    ON CONFLICT (counter_key) DO UPDATE SET
        count = core.escalation_counters.count + 1,
        last_seen = NOW(),
        expires_at = GREATEST(
            core.escalation_counters.expires_at,
            NOW() + (p_window_minutes || ' minutes')::INTERVAL
        )
    RETURNING count INTO v_count;

    RETURN v_count;
END;
$$;

-- Cleanup expired counters
CREATE OR REPLACE FUNCTION core.cleanup_expired_counters()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM core.escalation_counters WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

COMMENT ON TABLE core.escalation_counters IS 'Rate limiting counters for escalation events.';
COMMENT ON FUNCTION core.increment_escalation_counter IS 'Atomically increment counter. Returns new count.';

COMMIT;
