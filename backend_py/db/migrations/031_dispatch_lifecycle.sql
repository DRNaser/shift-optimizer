-- =============================================================================
-- Migration 031: Dispatch Lifecycle - Proposal/Apply with Concurrency Control
-- =============================================================================
-- Purpose: Track dispatch proposals and apply operations with optimistic
--          concurrency control via fingerprinting.
--
-- Key Features:
--   - Open shift tracking from Google Sheets
--   - Proposal lifecycle (GENERATED -> PROPOSED -> APPLIED)
--   - Fingerprint-based optimistic concurrency
--   - Idempotent apply via apply_request_id
--   - Append-only audit trail
--
-- RLS: All tables have tenant isolation via RLS policies.
--
-- Run:
--   psql $DATABASE_URL < backend_py/db/migrations/031_dispatch_lifecycle.sql
-- =============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('031', 'Dispatch Lifecycle - proposals + apply + audit', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- CREATE SCHEMA
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS dispatch;

COMMENT ON SCHEMA dispatch IS
'Dispatch Assist Lifecycle - Open shift detection, proposal generation, and
apply operations with optimistic concurrency control via fingerprinting.
Part of the Gurkerl Dispatch Assist MVP.';


-- =============================================================================
-- GRANT SCHEMA USAGE
-- =============================================================================
-- Following existing role hierarchy from 025x migrations

DO $$
BEGIN
    -- Grant usage to platform and API roles
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT USAGE ON SCHEMA dispatch TO solvereign_platform;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT USAGE ON SCHEMA dispatch TO solvereign_api;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        GRANT USAGE ON SCHEMA dispatch TO solvereign_definer;
    END IF;
END $$;


-- =============================================================================
-- TABLE: dispatch_open_shifts (Detected unassigned shifts)
-- =============================================================================

CREATE TABLE IF NOT EXISTS dispatch.dispatch_open_shifts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID REFERENCES masterdata.md_sites(id) ON DELETE SET NULL,

    -- Shift identification
    shift_date DATE NOT NULL,
    shift_key VARCHAR(255) NOT NULL,  -- Unique key within day, e.g., "row_10" or "ROUTE_001_AM"
    shift_start TIME NOT NULL,
    shift_end TIME NOT NULL,
    route_id VARCHAR(100),
    zone VARCHAR(100),
    required_skills JSONB DEFAULT '[]',  -- Skills required for this shift

    -- Source tracking
    source_system VARCHAR(100) DEFAULT 'google_sheets',
    source_row_index INTEGER,  -- Row number in sheet for traceability
    source_revision INTEGER,   -- Sheet revision when detected

    -- Status lifecycle: DETECTED -> PROPOSAL_GENERATED -> APPLIED -> CLOSED | INVALIDATED
    status VARCHAR(50) NOT NULL DEFAULT 'DETECTED',

    -- Detection metadata
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detected_by VARCHAR(255) DEFAULT 'solvereign',

    -- Closure tracking
    closed_at TIMESTAMPTZ,
    closed_reason TEXT,

    -- Arbitrary metadata
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique shift per tenant per date (prevents duplicates)
    CONSTRAINT dispatch_open_shifts_unique_key UNIQUE (tenant_id, shift_date, shift_key),

    -- Status validation
    CONSTRAINT dispatch_open_shifts_status_check CHECK (
        status IN ('DETECTED', 'PROPOSAL_GENERATED', 'APPLIED', 'CLOSED', 'INVALIDATED')
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_dispatch_open_shifts_tenant ON dispatch.dispatch_open_shifts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_open_shifts_date ON dispatch.dispatch_open_shifts(tenant_id, shift_date);
CREATE INDEX IF NOT EXISTS idx_dispatch_open_shifts_status ON dispatch.dispatch_open_shifts(tenant_id, status) WHERE status IN ('DETECTED', 'PROPOSAL_GENERATED');
CREATE INDEX IF NOT EXISTS idx_dispatch_open_shifts_site ON dispatch.dispatch_open_shifts(site_id) WHERE site_id IS NOT NULL;

COMMENT ON TABLE dispatch.dispatch_open_shifts IS 'Detected open shifts requiring driver assignment';
COMMENT ON COLUMN dispatch.dispatch_open_shifts.shift_key IS 'Unique identifier within tenant+date (e.g., row_10, ROUTE_AM)';
COMMENT ON COLUMN dispatch.dispatch_open_shifts.source_revision IS 'Google Sheets revision number when shift was detected';


-- =============================================================================
-- TABLE: dispatch_proposals (Generated proposals with candidates)
-- =============================================================================

CREATE TABLE IF NOT EXISTS dispatch.dispatch_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID REFERENCES masterdata.md_sites(id) ON DELETE SET NULL,

    -- Reference to open shift
    open_shift_id UUID NOT NULL REFERENCES dispatch.dispatch_open_shifts(id) ON DELETE CASCADE,
    shift_key VARCHAR(255) NOT NULL,  -- Denormalized for easy lookup

    -- Fingerprint for optimistic concurrency (scope-based)
    expected_plan_fingerprint VARCHAR(64) NOT NULL,  -- SHA-256 of scoped sheet data
    expected_revision INTEGER,  -- Google Sheets revision at proposal time
    config_version VARCHAR(50) DEFAULT 'v1',  -- Config schema version
    fingerprint_scope JSONB NOT NULL DEFAULT '{"scope_type":"DAY_PM1"}',
    -- Stores: {scope_type, shift_date, include_absences, include_driver_hours}

    -- Candidates: ranked list with eligibility and scoring details
    -- Format: [{driver_id, driver_name, score, rank, reasons, disqualifications, is_eligible}]
    candidates JSONB NOT NULL DEFAULT '[]',

    -- Status lifecycle: GENERATED -> PROPOSED -> APPLIED | REJECTED | EXPIRED | INVALIDATED
    status VARCHAR(50) NOT NULL DEFAULT 'GENERATED',

    -- Generation tracking
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    generated_by VARCHAR(255) DEFAULT 'solvereign',

    -- Proposal (when sent to dispatcher)
    proposed_at TIMESTAMPTZ,
    proposed_by VARCHAR(255),

    -- Apply tracking (when accepted and written to sheet)
    applied_at TIMESTAMPTZ,
    applied_by VARCHAR(255),
    selected_driver_id VARCHAR(255),
    selected_driver_name VARCHAR(255),
    apply_request_id UUID UNIQUE,  -- Idempotency key for apply operation

    -- Force override tracking (for compliance)
    forced_apply BOOLEAN DEFAULT FALSE,
    force_reason TEXT,

    -- Conflict tracking (populated on fingerprint mismatch)
    latest_fingerprint VARCHAR(64),  -- Actual fingerprint at apply time
    hint_diffs JSONB,  -- What changed: {roster_changed, drivers_changed, changed_rows}

    -- Invalidation tracking
    invalidated_at TIMESTAMPTZ,
    invalidated_reason TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Status validation
    CONSTRAINT dispatch_proposals_status_check CHECK (
        status IN ('GENERATED', 'PROPOSED', 'APPLIED', 'REJECTED', 'EXPIRED', 'INVALIDATED')
    ),

    -- Force reason required if forced
    CONSTRAINT dispatch_proposals_force_reason_check CHECK (
        NOT forced_apply OR (force_reason IS NOT NULL AND LENGTH(TRIM(force_reason)) >= 10)
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_dispatch_proposals_tenant ON dispatch.dispatch_proposals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_proposals_open_shift ON dispatch.dispatch_proposals(open_shift_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_proposals_status ON dispatch.dispatch_proposals(tenant_id, status) WHERE status IN ('GENERATED', 'PROPOSED');
CREATE INDEX IF NOT EXISTS idx_dispatch_proposals_apply_request ON dispatch.dispatch_proposals(apply_request_id) WHERE apply_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dispatch_proposals_generated_at ON dispatch.dispatch_proposals(tenant_id, generated_at DESC);

COMMENT ON TABLE dispatch.dispatch_proposals IS 'Dispatch proposals with candidates and concurrency control';
COMMENT ON COLUMN dispatch.dispatch_proposals.expected_plan_fingerprint IS 'SHA-256 fingerprint of scoped sheet state at proposal time';
COMMENT ON COLUMN dispatch.dispatch_proposals.fingerprint_scope IS 'Scope parameters used for fingerprint: {scope_type, shift_date, ...}';
COMMENT ON COLUMN dispatch.dispatch_proposals.apply_request_id IS 'Client-provided idempotency key for apply operation';


-- =============================================================================
-- TABLE: dispatch_apply_audit (Append-only audit trail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS dispatch.dispatch_apply_audit (
    id SERIAL PRIMARY KEY,
    audit_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- References
    proposal_id UUID NOT NULL REFERENCES dispatch.dispatch_proposals(id) ON DELETE CASCADE,
    open_shift_id UUID REFERENCES dispatch.dispatch_open_shifts(id) ON DELETE SET NULL,

    -- Action type: APPLY, REJECT, CONFLICT, EXPIRE, INVALIDATE
    action VARCHAR(50) NOT NULL,

    -- Actor
    performed_by VARCHAR(255) NOT NULL,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Apply details (if action = APPLY)
    selected_driver_id VARCHAR(255),
    selected_driver_name VARCHAR(255),

    -- Fingerprint comparison
    expected_fingerprint VARCHAR(64),
    actual_fingerprint VARCHAR(64),
    fingerprint_matched BOOLEAN,
    fingerprint_scope JSONB,  -- Scope used for comparison

    -- Eligibility revalidation result
    eligibility_passed BOOLEAN,
    eligibility_reasons JSONB,  -- Disqualification codes if failed

    -- Sheet mutation details
    sheet_cells_written JSONB,  -- Which cells were modified, e.g., ["D10", "E10"]

    -- Force tracking
    forced BOOLEAN DEFAULT FALSE,
    force_reason TEXT,

    -- Error details (if failed)
    error_code VARCHAR(50),
    error_message TEXT,

    -- Client tracking
    apply_request_id UUID,  -- Client idempotency key
    client_ip VARCHAR(45),
    user_agent TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Action validation
    CONSTRAINT dispatch_apply_audit_action_check CHECK (
        action IN ('APPLY', 'REJECT', 'CONFLICT', 'EXPIRE', 'INVALIDATE', 'REVALIDATE_FAIL')
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_dispatch_apply_audit_tenant ON dispatch.dispatch_apply_audit(tenant_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_apply_audit_proposal ON dispatch.dispatch_apply_audit(proposal_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_apply_audit_performed_at ON dispatch.dispatch_apply_audit(tenant_id, performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_dispatch_apply_audit_action ON dispatch.dispatch_apply_audit(tenant_id, action);

COMMENT ON TABLE dispatch.dispatch_apply_audit IS 'Append-only audit trail for all proposal actions';
COMMENT ON COLUMN dispatch.dispatch_apply_audit.error_code IS 'Error code if action failed: PLAN_CHANGED, NOT_ELIGIBLE, etc.';


-- =============================================================================
-- ENABLE RLS ON ALL DISPATCH TABLES
-- =============================================================================

ALTER TABLE dispatch.dispatch_open_shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE dispatch.dispatch_open_shifts FORCE ROW LEVEL SECURITY;

ALTER TABLE dispatch.dispatch_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE dispatch.dispatch_proposals FORCE ROW LEVEL SECURITY;

ALTER TABLE dispatch.dispatch_apply_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE dispatch.dispatch_apply_audit FORCE ROW LEVEL SECURITY;


-- =============================================================================
-- RLS POLICIES - Tenant Isolation
-- =============================================================================
-- Pattern: tenant_id = current_setting('app.current_tenant_id')::INTEGER

-- dispatch_open_shifts policies
CREATE POLICY dispatch_open_shifts_tenant_isolation ON dispatch.dispatch_open_shifts
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);

-- dispatch_proposals policies
CREATE POLICY dispatch_proposals_tenant_isolation ON dispatch.dispatch_proposals
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);

-- dispatch_apply_audit policies
CREATE POLICY dispatch_apply_audit_tenant_isolation ON dispatch.dispatch_apply_audit
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);


-- =============================================================================
-- GRANT TABLE PERMISSIONS
-- =============================================================================

DO $$
BEGIN
    -- API role (tenant operations)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT SELECT, INSERT, UPDATE ON dispatch.dispatch_open_shifts TO solvereign_api;
        GRANT SELECT, INSERT, UPDATE ON dispatch.dispatch_proposals TO solvereign_api;
        GRANT SELECT, INSERT ON dispatch.dispatch_apply_audit TO solvereign_api;  -- Audit is INSERT-only
        GRANT USAGE ON SEQUENCE dispatch.dispatch_apply_audit_id_seq TO solvereign_api;
    END IF;

    -- Platform role (admin operations)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT ALL ON dispatch.dispatch_open_shifts TO solvereign_platform;
        GRANT ALL ON dispatch.dispatch_proposals TO solvereign_platform;
        GRANT ALL ON dispatch.dispatch_apply_audit TO solvereign_platform;
        GRANT ALL ON SEQUENCE dispatch.dispatch_apply_audit_id_seq TO solvereign_platform;
    END IF;
END $$;


-- =============================================================================
-- TRIGGER: Auto-update updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION dispatch.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_dispatch_open_shifts_updated_at
    BEFORE UPDATE ON dispatch.dispatch_open_shifts
    FOR EACH ROW EXECUTE FUNCTION dispatch.update_updated_at();

CREATE TRIGGER tr_dispatch_proposals_updated_at
    BEFORE UPDATE ON dispatch.dispatch_proposals
    FOR EACH ROW EXECUTE FUNCTION dispatch.update_updated_at();


-- =============================================================================
-- TRIGGER: Proposal Immutability (Append-Only for Critical Fields)
-- =============================================================================
-- After status moves past GENERATED, candidates and fingerprint are frozen

CREATE OR REPLACE FUNCTION dispatch.enforce_proposal_immutability()
RETURNS TRIGGER AS $$
BEGIN
    -- Once past GENERATED, candidates and fingerprint cannot change
    IF OLD.status NOT IN ('GENERATED') THEN
        IF NEW.candidates IS DISTINCT FROM OLD.candidates THEN
            RAISE EXCEPTION 'Cannot modify candidates after proposal status "%"', OLD.status
                USING HINT = 'Candidates are frozen once proposal leaves GENERATED status';
        END IF;
        IF NEW.expected_plan_fingerprint IS DISTINCT FROM OLD.expected_plan_fingerprint THEN
            RAISE EXCEPTION 'Cannot modify fingerprint after proposal status "%"', OLD.status
                USING HINT = 'Fingerprint is frozen once proposal leaves GENERATED status';
        END IF;
        IF NEW.fingerprint_scope IS DISTINCT FROM OLD.fingerprint_scope THEN
            RAISE EXCEPTION 'Cannot modify fingerprint_scope after proposal status "%"', OLD.status
                USING HINT = 'Scope is frozen once proposal leaves GENERATED status';
        END IF;
    END IF;

    -- Once APPLIED, core apply fields are frozen
    IF OLD.status = 'APPLIED' THEN
        IF NEW.applied_by IS DISTINCT FROM OLD.applied_by OR
           NEW.applied_at IS DISTINCT FROM OLD.applied_at OR
           NEW.selected_driver_id IS DISTINCT FROM OLD.selected_driver_id OR
           NEW.apply_request_id IS DISTINCT FROM OLD.apply_request_id THEN
            RAISE EXCEPTION 'Cannot modify apply details after APPLIED status'
                USING HINT = 'Applied proposals are immutable for audit compliance';
        END IF;
    END IF;

    -- Valid status transitions only
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        -- Define valid transitions
        IF NOT (
            (OLD.status = 'GENERATED' AND NEW.status IN ('PROPOSED', 'EXPIRED', 'INVALIDATED')) OR
            (OLD.status = 'PROPOSED' AND NEW.status IN ('APPLIED', 'REJECTED', 'EXPIRED', 'INVALIDATED')) OR
            (OLD.status IN ('APPLIED', 'REJECTED', 'EXPIRED', 'INVALIDATED'))  -- Terminal states allow no change
        ) THEN
            -- Special case: allow terminal state to terminal state for corrections
            IF OLD.status NOT IN ('APPLIED', 'REJECTED', 'EXPIRED', 'INVALIDATED') THEN
                RAISE EXCEPTION 'Invalid status transition from "%" to "%"', OLD.status, NEW.status
                    USING HINT = 'Valid transitions: GENERATED->PROPOSED->APPLIED|REJECTED|EXPIRED|INVALIDATED';
            END IF;
        END IF;
    END IF;

    -- Allow status transitions and non-critical metadata updates
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_dispatch_proposals_immutability
    BEFORE UPDATE ON dispatch.dispatch_proposals
    FOR EACH ROW
    EXECUTE FUNCTION dispatch.enforce_proposal_immutability();

COMMENT ON FUNCTION dispatch.enforce_proposal_immutability IS
'Enforces append-only semantics for proposals: candidates/fingerprint frozen after GENERATED';


-- =============================================================================
-- FUNCTION: Upsert Open Shift (Idempotent)
-- =============================================================================
-- Create or update open shift, returns the shift ID

CREATE OR REPLACE FUNCTION dispatch.upsert_open_shift(
    p_tenant_id INTEGER,
    p_shift_date DATE,
    p_shift_key VARCHAR,
    p_shift_start TIME,
    p_shift_end TIME,
    p_zone VARCHAR DEFAULT NULL,
    p_route_id VARCHAR DEFAULT NULL,
    p_site_id UUID DEFAULT NULL,
    p_source_row_index INTEGER DEFAULT NULL,
    p_source_revision INTEGER DEFAULT NULL,
    p_required_skills JSONB DEFAULT '[]',
    p_metadata JSONB DEFAULT '{}'
)
RETURNS UUID AS $$
DECLARE
    v_shift_id UUID;
BEGIN
    INSERT INTO dispatch.dispatch_open_shifts (
        tenant_id, shift_date, shift_key, shift_start, shift_end,
        zone, route_id, site_id, source_row_index, source_revision,
        required_skills, metadata
    ) VALUES (
        p_tenant_id, p_shift_date, p_shift_key, p_shift_start, p_shift_end,
        p_zone, p_route_id, p_site_id, p_source_row_index, p_source_revision,
        p_required_skills, p_metadata
    )
    ON CONFLICT (tenant_id, shift_date, shift_key)
    DO UPDATE SET
        shift_start = EXCLUDED.shift_start,
        shift_end = EXCLUDED.shift_end,
        zone = EXCLUDED.zone,
        route_id = EXCLUDED.route_id,
        site_id = EXCLUDED.site_id,
        source_row_index = EXCLUDED.source_row_index,
        source_revision = EXCLUDED.source_revision,
        required_skills = EXCLUDED.required_skills,
        metadata = dispatch.dispatch_open_shifts.metadata || EXCLUDED.metadata,
        updated_at = NOW()
    WHERE dispatch.dispatch_open_shifts.status = 'DETECTED'  -- Only update if still open
    RETURNING id INTO v_shift_id;

    -- If UPDATE didn't happen (status != DETECTED), get existing ID
    IF v_shift_id IS NULL THEN
        SELECT id INTO v_shift_id
        FROM dispatch.dispatch_open_shifts
        WHERE tenant_id = p_tenant_id
          AND shift_date = p_shift_date
          AND shift_key = p_shift_key;
    END IF;

    RETURN v_shift_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION dispatch.upsert_open_shift IS
'Idempotent open shift upsert. Only updates if status is still DETECTED.';


-- =============================================================================
-- FUNCTION: Check Apply Idempotency
-- =============================================================================
-- Returns existing result if apply_request_id was already processed

CREATE OR REPLACE FUNCTION dispatch.check_apply_idempotency(
    p_apply_request_id UUID
)
RETURNS JSONB AS $$
DECLARE
    v_proposal dispatch.dispatch_proposals%ROWTYPE;
BEGIN
    IF p_apply_request_id IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT * INTO v_proposal
    FROM dispatch.dispatch_proposals
    WHERE apply_request_id = p_apply_request_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    -- Return cached result
    RETURN jsonb_build_object(
        'idempotent', TRUE,
        'proposal_id', v_proposal.id,
        'status', v_proposal.status,
        'applied_at', v_proposal.applied_at,
        'applied_by', v_proposal.applied_by,
        'selected_driver_id', v_proposal.selected_driver_id,
        'selected_driver_name', v_proposal.selected_driver_name
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION dispatch.check_apply_idempotency IS
'Check if apply_request_id was already processed. Returns cached result if found.';


-- =============================================================================
-- FUNCTION: Record Apply Audit Entry
-- =============================================================================

CREATE OR REPLACE FUNCTION dispatch.record_apply_audit(
    p_tenant_id INTEGER,
    p_proposal_id UUID,
    p_open_shift_id UUID,
    p_action VARCHAR,
    p_performed_by VARCHAR,
    p_selected_driver_id VARCHAR DEFAULT NULL,
    p_selected_driver_name VARCHAR DEFAULT NULL,
    p_expected_fingerprint VARCHAR DEFAULT NULL,
    p_actual_fingerprint VARCHAR DEFAULT NULL,
    p_fingerprint_matched BOOLEAN DEFAULT NULL,
    p_fingerprint_scope JSONB DEFAULT NULL,
    p_eligibility_passed BOOLEAN DEFAULT NULL,
    p_eligibility_reasons JSONB DEFAULT NULL,
    p_sheet_cells_written JSONB DEFAULT NULL,
    p_forced BOOLEAN DEFAULT FALSE,
    p_force_reason TEXT DEFAULT NULL,
    p_error_code VARCHAR DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL,
    p_apply_request_id UUID DEFAULT NULL,
    p_client_ip VARCHAR DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_audit_id UUID;
BEGIN
    INSERT INTO dispatch.dispatch_apply_audit (
        tenant_id, proposal_id, open_shift_id, action, performed_by,
        selected_driver_id, selected_driver_name,
        expected_fingerprint, actual_fingerprint, fingerprint_matched, fingerprint_scope,
        eligibility_passed, eligibility_reasons,
        sheet_cells_written,
        forced, force_reason,
        error_code, error_message,
        apply_request_id, client_ip, user_agent
    ) VALUES (
        p_tenant_id, p_proposal_id, p_open_shift_id, p_action, p_performed_by,
        p_selected_driver_id, p_selected_driver_name,
        p_expected_fingerprint, p_actual_fingerprint, p_fingerprint_matched, p_fingerprint_scope,
        p_eligibility_passed, p_eligibility_reasons,
        p_sheet_cells_written,
        p_forced, p_force_reason,
        p_error_code, p_error_message,
        p_apply_request_id, p_client_ip, p_user_agent
    )
    RETURNING audit_id INTO v_audit_id;

    RETURN v_audit_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION dispatch.record_apply_audit IS
'Create an audit entry for proposal actions. Called by apply workflow.';


-- =============================================================================
-- FUNCTION: verify_dispatch_integrity
-- =============================================================================
-- Verification function for dispatch lifecycle health

CREATE OR REPLACE FUNCTION dispatch.verify_dispatch_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: RLS enabled on all dispatch tables
    RETURN QUERY
    SELECT
        'rls_enabled'::TEXT,
        CASE WHEN COUNT(*) = 3 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/3 tables have RLS enabled', COUNT(*))
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'dispatch')
    WHERE t.schemaname = 'dispatch'
      AND t.tablename IN ('dispatch_open_shifts', 'dispatch_proposals', 'dispatch_apply_audit')
      AND c.relrowsecurity = TRUE;

    -- Check 2: FORCE RLS enabled
    RETURN QUERY
    SELECT
        'force_rls_enabled'::TEXT,
        CASE WHEN COUNT(*) = 3 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/3 tables have FORCE RLS enabled', COUNT(*))
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'dispatch')
    WHERE t.schemaname = 'dispatch'
      AND t.tablename IN ('dispatch_open_shifts', 'dispatch_proposals', 'dispatch_apply_audit')
      AND c.relforcerowsecurity = TRUE;

    -- Check 3: Unique constraint on open_shifts exists
    RETURN QUERY
    SELECT
        'open_shifts_unique_constraint'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'dispatch_open_shifts_unique_key'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'Unique constraint (tenant_id, shift_date, shift_key)'::TEXT;

    -- Check 4: apply_request_id unique index exists
    RETURN QUERY
    SELECT
        'apply_request_id_unique'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'dispatch'
              AND tablename = 'dispatch_proposals'
              AND indexname LIKE '%apply_request%'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'Unique index on apply_request_id for idempotency'::TEXT;

    -- Check 5: No orphan proposals (open_shift_id exists)
    RETURN QUERY
    SELECT
        'no_orphan_proposals'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s proposals with missing open_shift_id', COUNT(*))
    FROM dispatch.dispatch_proposals p
    LEFT JOIN dispatch.dispatch_open_shifts os ON p.open_shift_id = os.id
    WHERE os.id IS NULL;

    -- Check 6: tenant_id NOT NULL on all tables
    RETURN QUERY
    SELECT
        'tenant_id_not_null'::TEXT,
        CASE WHEN COUNT(*) = 3 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/3 tables have tenant_id NOT NULL', COUNT(*))
    FROM information_schema.columns c
    WHERE c.table_schema = 'dispatch'
      AND c.table_name IN ('dispatch_open_shifts', 'dispatch_proposals', 'dispatch_apply_audit')
      AND c.column_name = 'tenant_id'
      AND c.is_nullable = 'NO';

    -- Check 7: Valid status values in open_shifts
    RETURN QUERY
    SELECT
        'valid_open_shift_statuses'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s open_shifts with invalid status', COUNT(*))
    FROM dispatch.dispatch_open_shifts
    WHERE status NOT IN ('DETECTED', 'PROPOSAL_GENERATED', 'APPLIED', 'CLOSED', 'INVALIDATED');

    -- Check 8: Valid status values in proposals
    RETURN QUERY
    SELECT
        'valid_proposal_statuses'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s proposals with invalid status', COUNT(*))
    FROM dispatch.dispatch_proposals
    WHERE status NOT IN ('GENERATED', 'PROPOSED', 'APPLIED', 'REJECTED', 'EXPIRED', 'INVALIDATED');

    -- Check 9: Applied proposals have selected_driver_id
    RETURN QUERY
    SELECT
        'applied_has_driver'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s APPLIED proposals without selected_driver_id', COUNT(*))
    FROM dispatch.dispatch_proposals
    WHERE status = 'APPLIED' AND selected_driver_id IS NULL;

    -- Check 10: Forced proposals have force_reason
    RETURN QUERY
    SELECT
        'forced_has_reason'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s forced proposals without force_reason', COUNT(*))
    FROM dispatch.dispatch_proposals
    WHERE forced_apply = TRUE AND (force_reason IS NULL OR LENGTH(TRIM(force_reason)) < 10);

    -- Check 11: RLS policies exist
    RETURN QUERY
    SELECT
        'rls_policies_exist'::TEXT,
        CASE WHEN COUNT(*) >= 3 THEN 'PASS' ELSE 'FAIL' END,
        format('%s RLS policies found (expected 3)', COUNT(*))
    FROM pg_policies
    WHERE schemaname = 'dispatch';

    -- Check 12: Functions exist
    RETURN QUERY
    SELECT
        'functions_exist'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s functions found (expected 4+)', COUNT(*))
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'dispatch'
      AND p.proname IN ('upsert_open_shift', 'check_apply_idempotency', 'record_apply_audit', 'verify_dispatch_integrity');

END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION dispatch.verify_dispatch_integrity IS
'Verify dispatch lifecycle health. Run after migration to confirm RLS, constraints, and functions.';


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 031: Dispatch Lifecycle COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'SCHEMA: dispatch';
    RAISE NOTICE '';
    RAISE NOTICE 'TABLES:';
    RAISE NOTICE '  - dispatch.dispatch_open_shifts     (detected shifts)';
    RAISE NOTICE '  - dispatch.dispatch_proposals       (proposals + fingerprint)';
    RAISE NOTICE '  - dispatch.dispatch_apply_audit     (append-only audit)';
    RAISE NOTICE '';
    RAISE NOTICE 'FUNCTIONS:';
    RAISE NOTICE '  - upsert_open_shift(tenant, date, key, ...)';
    RAISE NOTICE '  - check_apply_idempotency(apply_request_id)';
    RAISE NOTICE '  - record_apply_audit(tenant, proposal_id, action, ...)';
    RAISE NOTICE '  - verify_dispatch_integrity()';
    RAISE NOTICE '';
    RAISE NOTICE 'SECURITY:';
    RAISE NOTICE '  - RLS enabled + FORCE on all tables';
    RAISE NOTICE '  - Tenant isolation via app.current_tenant_id';
    RAISE NOTICE '  - Proposal immutability trigger after GENERATED';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM dispatch.verify_dispatch_integrity();';
    RAISE NOTICE '============================================================';
END $$;
