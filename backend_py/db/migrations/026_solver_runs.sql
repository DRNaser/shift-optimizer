-- =============================================================================
-- Migration 026: Solver Runs + Plan State Machine
-- =============================================================================
-- Adds tables for tracking solver runs and plan lifecycle states.
--
-- State Machine: DRAFT -> SOLVED -> APPROVED -> PUBLISHED
--
-- Tables:
-- - solver_runs: Tracks each solve operation with KPIs and hashes
-- - plan_approvals: Tracks approval workflow (who approved, when, reason)
--
-- Run with: psql $DATABASE_URL < backend_py/db/migrations/026_solver_runs.sql
-- =============================================================================

-- Record migration start
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('026', 'Solver runs + plan state machine', NOW())
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- PLAN STATE TYPE
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'plan_state') THEN
        CREATE TYPE plan_state AS ENUM (
            'DRAFT',      -- Initial state, can be modified
            'SOLVING',    -- Solver is running
            'SOLVED',     -- Solver completed, awaiting approval
            'APPROVED',   -- Approved by dispatcher/approver
            'PUBLISHED',  -- Locked and exported, immutable
            'REJECTED',   -- Rejected during approval
            'FAILED'      -- Solver failed
        );
    END IF;
END $$;


-- =============================================================================
-- SOLVER RUNS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS solver_runs (
    -- Primary key
    id SERIAL PRIMARY KEY,
    run_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),

    -- Tenant/Site scope
    tenant_id UUID NOT NULL REFERENCES core.tenants(id),
    site_id UUID NOT NULL REFERENCES core.sites(id),

    -- Plan reference (optional, set when run creates/updates a plan)
    plan_version_id INTEGER,  -- References plan_versions(id)

    -- Timestamps
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Run configuration
    solver_type VARCHAR(50) NOT NULL DEFAULT 'VRPTW',
    solver_version VARCHAR(50) NOT NULL,
    seed INTEGER,
    time_limit_seconds INTEGER DEFAULT 300,

    -- Input hashes (determinism)
    input_hash VARCHAR(64) NOT NULL,
    matrix_hash VARCHAR(64) NOT NULL,
    policy_hash VARCHAR(64),

    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',

    -- KPI Results (after solve)
    kpi_unassigned INTEGER,
    kpi_vehicles_used INTEGER,
    kpi_total_distance_km FLOAT,
    kpi_total_duration_min FLOAT,
    kpi_overtime_min FLOAT,
    kpi_coverage_pct FLOAT,

    -- Multi-start results
    multi_start_enabled BOOLEAN DEFAULT FALSE,
    multi_start_runs_total INTEGER,
    multi_start_best_seed INTEGER,
    multi_start_scores JSONB,

    -- Output hash (reproducibility proof)
    output_hash VARCHAR(64),

    -- Error tracking
    error_code VARCHAR(50),
    error_message TEXT,

    -- Artifact references (Azure Blob URIs)
    result_artifact_uri VARCHAR(1000),
    evidence_artifact_uri VARCHAR(1000),

    -- Metadata
    created_by VARCHAR(255),
    metadata JSONB DEFAULT '{}'::JSONB,

    -- Constraints
    CONSTRAINT solver_runs_status_check CHECK (
        status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'TIMEOUT', 'CANCELLED')
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_solver_runs_tenant_site ON solver_runs(tenant_id, site_id);
CREATE INDEX IF NOT EXISTS idx_solver_runs_plan ON solver_runs(plan_version_id);
CREATE INDEX IF NOT EXISTS idx_solver_runs_status ON solver_runs(status);
CREATE INDEX IF NOT EXISTS idx_solver_runs_started_at ON solver_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_solver_runs_input_hash ON solver_runs(input_hash);
CREATE INDEX IF NOT EXISTS idx_solver_runs_output_hash ON solver_runs(output_hash);

-- RLS Policy
ALTER TABLE solver_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY solver_runs_tenant_isolation ON solver_runs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

COMMENT ON TABLE solver_runs IS 'Tracks solver executions with determinism hashes and KPIs';


-- =============================================================================
-- PLAN APPROVALS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS plan_approvals (
    -- Primary key
    id SERIAL PRIMARY KEY,
    approval_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),

    -- Plan reference
    plan_version_id INTEGER NOT NULL,  -- References plan_versions(id)
    solver_run_id UUID REFERENCES solver_runs(run_id),

    -- Tenant scope
    tenant_id UUID NOT NULL REFERENCES core.tenants(id),

    -- Approval details
    action VARCHAR(20) NOT NULL,  -- APPROVE, REJECT, PUBLISH
    performed_by VARCHAR(255) NOT NULL,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- State transition
    from_state VARCHAR(20) NOT NULL,
    to_state VARCHAR(20) NOT NULL,

    -- Reason/comment
    reason TEXT,

    -- Evidence snapshot at approval time
    kpi_snapshot JSONB,
    evidence_snapshot JSONB,

    -- Constraints
    CONSTRAINT plan_approvals_action_check CHECK (
        action IN ('APPROVE', 'REJECT', 'PUBLISH', 'REVERT')
    ),
    CONSTRAINT plan_approvals_state_valid CHECK (
        from_state IN ('DRAFT', 'SOLVING', 'SOLVED', 'APPROVED', 'PUBLISHED', 'REJECTED', 'FAILED')
        AND to_state IN ('DRAFT', 'SOLVING', 'SOLVED', 'APPROVED', 'PUBLISHED', 'REJECTED', 'FAILED')
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_plan_approvals_plan ON plan_approvals(plan_version_id);
CREATE INDEX IF NOT EXISTS idx_plan_approvals_tenant ON plan_approvals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_plan_approvals_performed_at ON plan_approvals(performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_plan_approvals_action ON plan_approvals(action);

-- RLS Policy
ALTER TABLE plan_approvals ENABLE ROW LEVEL SECURITY;

CREATE POLICY plan_approvals_tenant_isolation ON plan_approvals
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

COMMENT ON TABLE plan_approvals IS 'Audit trail for plan state transitions (approval workflow)';


-- =============================================================================
-- ADD STATE COLUMN TO PLAN_VERSIONS
-- =============================================================================

DO $$
BEGIN
    -- Add plan_state column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'plan_state'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN plan_state VARCHAR(20) DEFAULT 'DRAFT';
        ALTER TABLE plan_versions ADD CONSTRAINT plan_versions_state_check CHECK (
            plan_state IN ('DRAFT', 'SOLVING', 'SOLVED', 'APPROVED', 'PUBLISHED', 'REJECTED', 'FAILED')
        );
        CREATE INDEX idx_plan_versions_state ON plan_versions(plan_state);
    END IF;

    -- Add solver_run_id reference if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'solver_run_id'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN solver_run_id UUID;
    END IF;

    -- Add published_at timestamp if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'published_at'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN published_at TIMESTAMPTZ;
        ALTER TABLE plan_versions ADD COLUMN published_by VARCHAR(255);
    END IF;

    -- Add freeze_until if not exists (for churn protection)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'freeze_until'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN freeze_until TIMESTAMPTZ;
    END IF;
END $$;


-- =============================================================================
-- STATE TRANSITION FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION transition_plan_state(
    p_plan_version_id INTEGER,
    p_to_state VARCHAR,
    p_performed_by VARCHAR,
    p_reason TEXT DEFAULT NULL,
    p_kpi_snapshot JSONB DEFAULT NULL
)
RETURNS JSONB
SECURITY DEFINER
SET search_path = public, core
AS $$
DECLARE
    v_current_state VARCHAR;
    v_tenant_id UUID;
    v_solver_run_id UUID;
    v_allowed BOOLEAN := FALSE;
    v_result JSONB;
BEGIN
    -- Get current state
    SELECT plan_state, tenant_id, solver_run_id
    INTO v_current_state, v_tenant_id, v_solver_run_id
    FROM plan_versions
    WHERE id = p_plan_version_id;

    IF v_current_state IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Plan version not found'
        );
    END IF;

    -- Validate state transition
    CASE v_current_state
        WHEN 'DRAFT' THEN
            v_allowed := p_to_state IN ('SOLVING', 'REJECTED');
        WHEN 'SOLVING' THEN
            v_allowed := p_to_state IN ('SOLVED', 'FAILED');
        WHEN 'SOLVED' THEN
            v_allowed := p_to_state IN ('APPROVED', 'REJECTED', 'DRAFT');
        WHEN 'APPROVED' THEN
            v_allowed := p_to_state IN ('PUBLISHED', 'REJECTED', 'DRAFT');
        WHEN 'REJECTED' THEN
            v_allowed := p_to_state IN ('DRAFT');
        WHEN 'FAILED' THEN
            v_allowed := p_to_state IN ('DRAFT');
        WHEN 'PUBLISHED' THEN
            v_allowed := FALSE;  -- Published is terminal
        ELSE
            v_allowed := FALSE;
    END CASE;

    IF NOT v_allowed THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Invalid state transition: %s -> %s', v_current_state, p_to_state),
            'from_state', v_current_state,
            'to_state', p_to_state
        );
    END IF;

    -- Update plan state
    UPDATE plan_versions
    SET plan_state = p_to_state,
        published_at = CASE WHEN p_to_state = 'PUBLISHED' THEN NOW() ELSE published_at END,
        published_by = CASE WHEN p_to_state = 'PUBLISHED' THEN p_performed_by ELSE published_by END,
        freeze_until = CASE WHEN p_to_state = 'PUBLISHED' THEN NOW() + INTERVAL '12 hours' ELSE freeze_until END
    WHERE id = p_plan_version_id;

    -- Record approval action
    INSERT INTO plan_approvals (
        plan_version_id,
        solver_run_id,
        tenant_id,
        action,
        performed_by,
        from_state,
        to_state,
        reason,
        kpi_snapshot
    ) VALUES (
        p_plan_version_id,
        v_solver_run_id,
        v_tenant_id,
        CASE p_to_state
            WHEN 'APPROVED' THEN 'APPROVE'
            WHEN 'REJECTED' THEN 'REJECT'
            WHEN 'PUBLISHED' THEN 'PUBLISH'
            ELSE 'REVERT'
        END,
        p_performed_by,
        v_current_state,
        p_to_state,
        p_reason,
        p_kpi_snapshot
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'from_state', v_current_state,
        'to_state', p_to_state,
        'plan_version_id', p_plan_version_id,
        'performed_by', p_performed_by,
        'freeze_until', CASE WHEN p_to_state = 'PUBLISHED' THEN NOW() + INTERVAL '12 hours' ELSE NULL END
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION transition_plan_state IS 'Safely transitions plan state with validation and audit trail';


-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get plan with full state info
CREATE OR REPLACE FUNCTION get_plan_with_state(p_plan_version_id INTEGER)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'plan_version_id', pv.id,
        'plan_state', pv.plan_state,
        'solver_run_id', pv.solver_run_id,
        'published_at', pv.published_at,
        'published_by', pv.published_by,
        'freeze_until', pv.freeze_until,
        'is_frozen', pv.freeze_until > NOW(),
        'can_modify', pv.plan_state IN ('DRAFT', 'REJECTED', 'FAILED'),
        'can_approve', pv.plan_state = 'SOLVED',
        'can_publish', pv.plan_state = 'APPROVED',
        'solver_run', (
            SELECT jsonb_build_object(
                'run_id', sr.run_id,
                'status', sr.status,
                'kpi_unassigned', sr.kpi_unassigned,
                'kpi_vehicles_used', sr.kpi_vehicles_used,
                'kpi_coverage_pct', sr.kpi_coverage_pct,
                'output_hash', sr.output_hash
            )
            FROM solver_runs sr
            WHERE sr.run_id = pv.solver_run_id
        ),
        'approval_history', (
            SELECT jsonb_agg(jsonb_build_object(
                'action', pa.action,
                'performed_by', pa.performed_by,
                'performed_at', pa.performed_at,
                'from_state', pa.from_state,
                'to_state', pa.to_state,
                'reason', pa.reason
            ) ORDER BY pa.performed_at DESC)
            FROM plan_approvals pa
            WHERE pa.plan_version_id = pv.id
        )
    )
    INTO v_result
    FROM plan_versions pv
    WHERE pv.id = p_plan_version_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_plan_with_state IS 'Returns plan with state machine info and history';


-- Get solver run summary
CREATE OR REPLACE FUNCTION get_solver_run_summary(p_run_id UUID)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'run_id', sr.run_id,
        'status', sr.status,
        'started_at', sr.started_at,
        'completed_at', sr.completed_at,
        'duration_seconds', EXTRACT(EPOCH FROM (sr.completed_at - sr.started_at)),
        'solver', jsonb_build_object(
            'type', sr.solver_type,
            'version', sr.solver_version,
            'seed', sr.seed,
            'time_limit_seconds', sr.time_limit_seconds
        ),
        'hashes', jsonb_build_object(
            'input', sr.input_hash,
            'matrix', sr.matrix_hash,
            'policy', sr.policy_hash,
            'output', sr.output_hash
        ),
        'kpis', jsonb_build_object(
            'unassigned', sr.kpi_unassigned,
            'vehicles_used', sr.kpi_vehicles_used,
            'total_distance_km', sr.kpi_total_distance_km,
            'total_duration_min', sr.kpi_total_duration_min,
            'overtime_min', sr.kpi_overtime_min,
            'coverage_pct', sr.kpi_coverage_pct
        ),
        'multi_start', CASE WHEN sr.multi_start_enabled THEN jsonb_build_object(
            'runs_total', sr.multi_start_runs_total,
            'best_seed', sr.multi_start_best_seed,
            'scores', sr.multi_start_scores
        ) ELSE NULL END,
        'artifacts', jsonb_build_object(
            'result', sr.result_artifact_uri,
            'evidence', sr.evidence_artifact_uri
        ),
        'error', CASE WHEN sr.error_code IS NOT NULL THEN jsonb_build_object(
            'code', sr.error_code,
            'message', sr.error_message
        ) ELSE NULL END
    )
    INTO v_result
    FROM solver_runs sr
    WHERE sr.run_id = p_run_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_solver_run_summary IS 'Returns solver run details with KPIs and hashes';


-- =============================================================================
-- TRIGGER: Prevent modification of PUBLISHED plans
-- =============================================================================

CREATE OR REPLACE FUNCTION prevent_published_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.plan_state = 'PUBLISHED' AND TG_OP IN ('UPDATE', 'DELETE') THEN
        -- Allow only state change to PUBLISHED (no-op) or metadata updates
        IF TG_OP = 'UPDATE' AND NEW.plan_state = 'PUBLISHED' THEN
            -- Allow updating metadata fields only, not core data
            IF OLD.solver_run_id IS DISTINCT FROM NEW.solver_run_id THEN
                RAISE EXCEPTION 'Cannot modify solver_run_id of PUBLISHED plan';
            END IF;
            RETURN NEW;
        END IF;

        RAISE EXCEPTION 'Cannot modify or delete PUBLISHED plan (id=%)', OLD.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_prevent_published_modification ON plan_versions;
CREATE TRIGGER tr_prevent_published_modification
    BEFORE UPDATE OR DELETE ON plan_versions
    FOR EACH ROW
    EXECUTE FUNCTION prevent_published_modification();


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Migration 026 completed successfully';
    RAISE NOTICE 'Created tables: solver_runs, plan_approvals';
    RAISE NOTICE 'Created functions: transition_plan_state, get_plan_with_state, get_solver_run_summary';
    RAISE NOTICE 'Created trigger: tr_prevent_published_modification';
    RAISE NOTICE 'Added columns to plan_versions: plan_state, solver_run_id, published_at, published_by, freeze_until';
END $$;
