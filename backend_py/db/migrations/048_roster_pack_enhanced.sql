-- =============================================================================
-- MIGRATION 048: Roster Pack Enhancement (Pins, Repairs, Violations)
-- =============================================================================
--
-- SOLVEREIGN V4.6 - Roster Pack Operational Tools
--
-- Purpose:
--   Implements operational dispatch features for the roster pack:
--   - Pin/Lock assignments (anti-churn)
--   - Repair sessions with preview/apply workflow
--   - Violations cache for BLOCK/WARN overlays
--   - Audit notes for all mutations
--
-- Key Features:
--   - Pin assignments to prevent solver changes (MANUAL, FREEZE_WINDOW, DRIVER_ACK)
--   - Repair sessions with action log (SWAP, MOVE, FILL)
--   - Preview delta before applying changes
--   - Violations computed from audit rules (overlap, rest, hours, unassigned)
--   - Required audit notes for all mutations
--
-- Security:
--   - RLS tenant isolation on all tables
--   - Immutable audit_notes table (arbeitsrechtlich)
--   - Idempotent operations via core.idempotency_keys integration
--
-- Dependencies:
--   - core.tenants (for tenant_id FK)
--   - core.sites (for site_id FK)
--   - plan_versions (for plan_version_id FK)
--   - core.idempotency_keys (for idempotent operations)
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- SCHEMA: roster
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS roster;

-- Secure the schema (follow hardening pattern)
REVOKE ALL ON SCHEMA roster FROM PUBLIC;
GRANT USAGE ON SCHEMA roster TO solvereign_api;
GRANT USAGE ON SCHEMA roster TO solvereign_platform;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA roster
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA roster
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA roster
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA roster
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO solvereign_api;
ALTER DEFAULT PRIVILEGES FOR ROLE solvereign_admin IN SCHEMA roster
    GRANT USAGE ON SEQUENCES TO solvereign_api;

-- =============================================================================
-- TABLE: roster.pins
-- =============================================================================
-- Pinned assignments for anti-churn stability.
-- Pins prevent the solver/repair from modifying specific assignments.

CREATE TABLE IF NOT EXISTS roster.pins (
    id SERIAL PRIMARY KEY,
    pin_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,

    -- Tenant/Site isolation (CRITICAL for RLS)
    tenant_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,

    -- Plan scope
    plan_version_id INTEGER NOT NULL,

    -- Assignment key (composite: driver + tour_instance + day)
    driver_id VARCHAR(255) NOT NULL,
    tour_instance_id INTEGER NOT NULL,
    day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),

    -- Pin metadata
    pinned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pinned_by VARCHAR(255) NOT NULL,  -- User email
    pin_type VARCHAR(20) NOT NULL DEFAULT 'MANUAL' CHECK (
        pin_type IN ('MANUAL', 'FREEZE_WINDOW', 'DRIVER_ACK', 'SYSTEM')
    ),

    -- Audit (required)
    reason_code VARCHAR(50) NOT NULL CHECK (
        reason_code IN (
            'DRIVER_REQUEST', 'DISPATCHER_DECISION', 'CONTRACTUAL',
            'OPERATIONAL', 'FREEZE_WINDOW', 'ACK_LOCKED', 'OTHER'
        )
    ),
    note TEXT,

    -- Lifecycle
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    unpinned_at TIMESTAMPTZ,
    unpinned_by VARCHAR(255),
    unpin_reason TEXT,

    -- Constraints
    CONSTRAINT pins_unique_assignment UNIQUE (plan_version_id, driver_id, tour_instance_id, day),
    CONSTRAINT pins_unpin_integrity CHECK (
        (is_active = TRUE AND unpinned_at IS NULL) OR
        (is_active = FALSE AND unpinned_at IS NOT NULL)
    ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_pins_tenant_plan ON roster.pins(tenant_id, plan_version_id);
CREATE INDEX idx_pins_driver ON roster.pins(driver_id) WHERE is_active = TRUE;
CREATE INDEX idx_pins_active ON roster.pins(plan_version_id) WHERE is_active = TRUE;

-- RLS
ALTER TABLE roster.pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster.pins FORCE ROW LEVEL SECURITY;

CREATE POLICY pins_tenant_isolation ON roster.pins
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER, 0
    ));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON roster.pins TO solvereign_api;
GRANT USAGE ON SEQUENCE roster.pins_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: roster.repairs
-- =============================================================================
-- Repair session tracking for preview/apply workflow.
-- Sessions have a 2-hour TTL and track all actions.

CREATE TABLE IF NOT EXISTS roster.repairs (
    id SERIAL PRIMARY KEY,
    repair_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,

    -- Tenant/Site isolation
    tenant_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,

    -- Plan scope
    plan_version_id INTEGER NOT NULL,

    -- Session state machine: OPEN -> APPLIED | ABORTED | EXPIRED
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (
        status IN ('OPEN', 'PREVIEWING', 'APPLIED', 'ABORTED', 'EXPIRED')
    ),

    -- Session metadata
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    opened_by VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '2 hours'),

    -- Apply tracking
    applied_at TIMESTAMPTZ,
    applied_by VARCHAR(255),
    result_plan_version_id INTEGER,

    -- Abort tracking
    aborted_at TIMESTAMPTZ,
    aborted_by VARCHAR(255),
    abort_reason TEXT,

    -- Audit (required on apply)
    apply_reason_code VARCHAR(50),
    apply_note TEXT,

    -- Summary (populated on apply)
    summary_json JSONB,  -- {actions_count, preview_delta, violations_at_apply}

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_repairs_tenant_plan ON roster.repairs(tenant_id, plan_version_id);
CREATE INDEX idx_repairs_status ON roster.repairs(status) WHERE status = 'OPEN';
CREATE INDEX idx_repairs_expires ON roster.repairs(expires_at) WHERE status IN ('OPEN', 'PREVIEWING');

-- RLS
ALTER TABLE roster.repairs ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster.repairs FORCE ROW LEVEL SECURITY;

CREATE POLICY repairs_tenant_isolation ON roster.repairs
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER, 0
    ));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON roster.repairs TO solvereign_api;
GRANT USAGE ON SEQUENCE roster.repairs_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: roster.repair_actions
-- =============================================================================
-- Individual repair actions within a session.
-- Actions are SWAP, MOVE, FILL, UNASSIGN, REVERT.

CREATE TABLE IF NOT EXISTS roster.repair_actions (
    id SERIAL PRIMARY KEY,
    action_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,

    -- Parent session
    repair_id UUID NOT NULL REFERENCES roster.repairs(repair_id) ON DELETE CASCADE,

    -- Tenant isolation (denormalized for RLS)
    tenant_id INTEGER NOT NULL,

    -- Action type
    action_type VARCHAR(20) NOT NULL CHECK (
        action_type IN ('SWAP', 'MOVE', 'FILL', 'UNASSIGN', 'REVERT')
    ),

    -- Action sequence (order of application)
    sequence_no INTEGER NOT NULL,

    -- Payload (varies by action_type)
    payload JSONB NOT NULL,
    -- SWAP: {driver_a_id, driver_b_id, tour_a_id, tour_b_id, day}
    -- MOVE: {driver_id, from_tour_id, to_tour_id, day}
    -- FILL: {tour_id, driver_id, day}
    -- UNASSIGN: {tour_id, day}
    -- REVERT: {action_id_to_revert}

    -- Preview result (computed)
    preview_delta JSONB,  -- {driver_impacts: [], tour_impacts: [], violation_delta: {}}
    preview_computed_at TIMESTAMPTZ,

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'PREVIEWED', 'APPLIED', 'REVERTED', 'FAILED')
    ),

    -- Error tracking
    error_code VARCHAR(50),
    error_message TEXT,

    -- Audit
    created_by VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT repair_actions_sequence_unique UNIQUE (repair_id, sequence_no)
);

-- Indexes
CREATE INDEX idx_repair_actions_repair ON roster.repair_actions(repair_id);
CREATE INDEX idx_repair_actions_tenant ON roster.repair_actions(tenant_id);

-- RLS
ALTER TABLE roster.repair_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster.repair_actions FORCE ROW LEVEL SECURITY;

CREATE POLICY repair_actions_tenant_isolation ON roster.repair_actions
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER, 0
    ));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON roster.repair_actions TO solvereign_api;
GRANT USAGE ON SEQUENCE roster.repair_actions_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: roster.violations_cache
-- =============================================================================
-- Computed violations cache for BLOCK/WARN overlay.
-- Invalidated when assignments change.

CREATE TABLE IF NOT EXISTS roster.violations_cache (
    id SERIAL PRIMARY KEY,

    -- Scope
    tenant_id INTEGER NOT NULL,
    plan_version_id INTEGER NOT NULL,

    -- Cache metadata
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '5 minutes'),
    input_hash VARCHAR(64) NOT NULL,  -- Hash of assignments to detect changes

    -- Violation summary
    violations_json JSONB NOT NULL DEFAULT '[]',
    -- [{type, severity, driver_id, tour_id, day, cell_key, message, details}]

    -- Aggregates
    block_count INTEGER NOT NULL DEFAULT 0,
    warn_count INTEGER NOT NULL DEFAULT 0,
    ok_count INTEGER NOT NULL DEFAULT 0,
    unassigned_count INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT violations_cache_unique_plan UNIQUE (plan_version_id)
);

-- Index
CREATE INDEX idx_violations_cache_plan ON roster.violations_cache(plan_version_id);

-- RLS
ALTER TABLE roster.violations_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster.violations_cache FORCE ROW LEVEL SECURITY;

CREATE POLICY violations_cache_tenant_isolation ON roster.violations_cache
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER, 0
    ));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON roster.violations_cache TO solvereign_api;
GRANT USAGE ON SEQUENCE roster.violations_cache_id_seq TO solvereign_api;

-- =============================================================================
-- TABLE: roster.audit_notes
-- =============================================================================
-- Immutable audit trail for all roster mutations.
-- Required for compliance and arbeitsrechtlich requirements.

CREATE TABLE IF NOT EXISTS roster.audit_notes (
    id BIGSERIAL PRIMARY KEY,
    note_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,

    -- Context
    tenant_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    plan_version_id INTEGER NOT NULL,

    -- What was mutated
    entity_type VARCHAR(50) NOT NULL CHECK (
        entity_type IN ('PIN', 'REPAIR_SESSION', 'REPAIR_ACTION', 'ASSIGNMENT', 'SNAPSHOT', 'PUBLISH')
    ),
    entity_id VARCHAR(100) NOT NULL,

    -- Who and when
    performed_by VARCHAR(255) NOT NULL,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Required audit fields
    reason_code VARCHAR(50) NOT NULL,
    note TEXT NOT NULL CHECK (LENGTH(note) >= 5),  -- Minimum 5 chars

    -- Evidence reference
    evidence_ref VARCHAR(1000),

    -- Immutable
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_audit_notes_tenant_plan ON roster.audit_notes(tenant_id, plan_version_id);
CREATE INDEX idx_audit_notes_entity ON roster.audit_notes(entity_type, entity_id);
CREATE INDEX idx_audit_notes_performed ON roster.audit_notes(performed_at DESC);

-- RLS
ALTER TABLE roster.audit_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster.audit_notes FORCE ROW LEVEL SECURITY;

CREATE POLICY audit_notes_tenant_isolation ON roster.audit_notes
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER, 0
    ));

-- Grant permissions (INSERT only for solvereign_api, no UPDATE/DELETE)
GRANT SELECT, INSERT ON roster.audit_notes TO solvereign_api;
GRANT USAGE ON SEQUENCE roster.audit_notes_id_seq TO solvereign_api;

-- Immutability trigger
CREATE OR REPLACE FUNCTION roster.prevent_audit_notes_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'roster.audit_notes is append-only. Modifications not allowed.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_audit_notes_immutable ON roster.audit_notes;
CREATE TRIGGER tr_audit_notes_immutable
    BEFORE UPDATE OR DELETE ON roster.audit_notes
    FOR EACH ROW
    EXECUTE FUNCTION roster.prevent_audit_notes_modification();

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get active pins for a plan
CREATE OR REPLACE FUNCTION roster.get_active_pins(
    p_tenant_id INTEGER,
    p_plan_version_id INTEGER
) RETURNS TABLE (
    pin_id UUID,
    driver_id VARCHAR(255),
    tour_instance_id INTEGER,
    day INTEGER,
    pin_type VARCHAR(20),
    reason_code VARCHAR(50),
    pinned_by VARCHAR(255),
    pinned_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.pin_id,
        p.driver_id,
        p.tour_instance_id,
        p.day,
        p.pin_type,
        p.reason_code,
        p.pinned_by,
        p.pinned_at
    FROM roster.pins p
    WHERE p.tenant_id = p_tenant_id
      AND p.plan_version_id = p_plan_version_id
      AND p.is_active = TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION roster.get_active_pins(INTEGER, INTEGER) TO solvereign_api;

-- Check if assignment is pinned
CREATE OR REPLACE FUNCTION roster.is_assignment_pinned(
    p_tenant_id INTEGER,
    p_plan_version_id INTEGER,
    p_driver_id VARCHAR(255),
    p_tour_instance_id INTEGER,
    p_day INTEGER
) RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM roster.pins
        WHERE tenant_id = p_tenant_id
          AND plan_version_id = p_plan_version_id
          AND driver_id = p_driver_id
          AND tour_instance_id = p_tour_instance_id
          AND day = p_day
          AND is_active = TRUE
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION roster.is_assignment_pinned(INTEGER, INTEGER, VARCHAR, INTEGER, INTEGER) TO solvereign_api;

-- Record audit note
CREATE OR REPLACE FUNCTION roster.record_audit_note(
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_plan_version_id INTEGER,
    p_entity_type VARCHAR(50),
    p_entity_id VARCHAR(100),
    p_performed_by VARCHAR(255),
    p_reason_code VARCHAR(50),
    p_note TEXT,
    p_evidence_ref VARCHAR(1000) DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_note_id UUID;
BEGIN
    INSERT INTO roster.audit_notes (
        tenant_id, site_id, plan_version_id,
        entity_type, entity_id,
        performed_by, reason_code, note, evidence_ref
    ) VALUES (
        p_tenant_id, p_site_id, p_plan_version_id,
        p_entity_type, p_entity_id,
        p_performed_by, p_reason_code, p_note, p_evidence_ref
    )
    RETURNING note_id INTO v_note_id;

    RETURN v_note_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION roster.record_audit_note(INTEGER, INTEGER, INTEGER, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TEXT, VARCHAR) TO solvereign_api;

-- Cleanup expired repair sessions
CREATE OR REPLACE FUNCTION roster.cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    v_updated INTEGER;
BEGIN
    UPDATE roster.repairs
    SET status = 'EXPIRED'
    WHERE status IN ('OPEN', 'PREVIEWING')
      AND expires_at < NOW();

    GET DIAGNOSTICS v_updated = ROW_COUNT;

    RAISE NOTICE 'Expired % repair sessions', v_updated;
    RETURN v_updated;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION roster.cleanup_expired_sessions() TO solvereign_platform;

-- Invalidate violations cache for a plan
CREATE OR REPLACE FUNCTION roster.invalidate_violations_cache(
    p_plan_version_id INTEGER
) RETURNS BOOLEAN AS $$
BEGIN
    DELETE FROM roster.violations_cache
    WHERE plan_version_id = p_plan_version_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION roster.invalidate_violations_cache(INTEGER) TO solvereign_api;

-- =============================================================================
-- VERIFICATION FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION roster.verify_roster_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check 1: RLS on pins
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'pins'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_pins'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_pins'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 2: RLS on repairs
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'repairs'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_repairs'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_repairs'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 3: RLS on repair_actions
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'repair_actions'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_repair_actions'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_repair_actions'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 4: RLS on violations_cache
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'violations_cache'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_violations_cache'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_violations_cache'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 5: RLS on audit_notes
    SELECT COUNT(*) INTO v_count FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'roster' AND c.relname = 'audit_notes'
    AND c.relrowsecurity = TRUE AND c.relforcerowsecurity = TRUE;

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'rls_audit_notes'::TEXT, 'PASS'::TEXT, 'RLS enabled and forced'::TEXT;
    ELSE
        RETURN QUERY SELECT 'rls_audit_notes'::TEXT, 'FAIL'::TEXT, 'RLS not properly configured'::TEXT;
    END IF;

    -- Check 6: Audit notes immutability trigger
    SELECT COUNT(*) INTO v_count FROM pg_trigger WHERE tgname = 'tr_audit_notes_immutable';

    IF v_count = 1 THEN
        RETURN QUERY SELECT 'audit_notes_immutable_trigger'::TEXT, 'PASS'::TEXT, 'Immutability trigger exists'::TEXT;
    ELSE
        RETURN QUERY SELECT 'audit_notes_immutable_trigger'::TEXT, 'FAIL'::TEXT, 'Trigger missing'::TEXT;
    END IF;

    -- Check 7: All tables have tenant_id NOT NULL
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'roster' AND column_name = 'tenant_id' AND is_nullable = 'NO';

    IF v_count >= 5 THEN
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'PASS'::TEXT, format('%s tables have tenant_id NOT NULL', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'tenant_id_not_null'::TEXT, 'FAIL'::TEXT, format('Only %s tables have tenant_id NOT NULL', v_count)::TEXT;
    END IF;

    -- Check 8: Unique constraints exist
    SELECT COUNT(*) INTO v_count
    FROM pg_constraint
    WHERE conname IN (
        'pins_unique_assignment',
        'violations_cache_unique_plan',
        'repair_actions_sequence_unique'
    );

    IF v_count >= 3 THEN
        RETURN QUERY SELECT 'unique_constraints'::TEXT, 'PASS'::TEXT, format('%s unique constraints found', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'unique_constraints'::TEXT, 'WARN'::TEXT, format('Only %s unique constraints found', v_count)::TEXT;
    END IF;

    -- Check 9: Helper functions exist
    SELECT COUNT(*) INTO v_count
    FROM information_schema.routines
    WHERE routine_schema = 'roster'
      AND routine_name IN ('get_active_pins', 'is_assignment_pinned', 'record_audit_note', 'invalidate_violations_cache');

    IF v_count >= 4 THEN
        RETURN QUERY SELECT 'helper_functions'::TEXT, 'PASS'::TEXT, format('%s helper functions exist', v_count)::TEXT;
    ELSE
        RETURN QUERY SELECT 'helper_functions'::TEXT, 'FAIL'::TEXT, format('Only %s helper functions found', v_count)::TEXT;
    END IF;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute to platform role
GRANT EXECUTE ON FUNCTION roster.verify_roster_integrity() TO solvereign_platform;

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Run: SELECT * FROM roster.verify_roster_integrity();
