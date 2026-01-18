-- =============================================================================
-- Migration 027: Plan Versioning (Immutable Snapshots)
-- =============================================================================
-- Fixes the "Plan vs PlanVersion" problem:
--
-- BEFORE:
--   plan_versions = working plan + immutable published record (broken)
--   - PUBLISHED plans blocked from modification
--   - Repair impossible without breaking immutability
--
-- AFTER:
--   plan_versions = working plan (can be modified/re-solved)
--   plan_snapshots = immutable published snapshots
--   - Publish creates snapshot, doesn't lock the working plan
--   - Repair creates new version from working plan
--   - Each published snapshot is forever immutable
--
-- Run: psql $DATABASE_URL < backend_py/db/migrations/027_plan_versioning.sql
-- =============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('027', 'Plan versioning with immutable snapshots', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- 1. CREATE PLAN_SNAPSHOTS TABLE (IMMUTABLE PUBLISHED VERSIONS)
-- =============================================================================

CREATE TABLE IF NOT EXISTS plan_snapshots (
    -- Primary key
    id SERIAL PRIMARY KEY,
    snapshot_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),

    -- Source plan reference
    plan_version_id INTEGER NOT NULL,  -- References plan_versions(id)

    -- Tenant/Site scope (denormalized for RLS)
    tenant_id UUID NOT NULL REFERENCES core.tenants(id),
    site_id UUID NOT NULL REFERENCES core.sites(id),

    -- Version number within the plan
    version_number INTEGER NOT NULL DEFAULT 1,

    -- Publish metadata
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_by VARCHAR(255) NOT NULL,
    publish_reason TEXT,

    -- Freeze window (12h by default)
    freeze_until TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '12 hours'),

    -- Solver run that created this snapshot
    solver_run_id UUID,

    -- KPIs at publish time (immutable record)
    kpi_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- Output hashes (immutable proof)
    input_hash VARCHAR(64) NOT NULL,
    matrix_hash VARCHAR(64),
    output_hash VARCHAR(64) NOT NULL,
    evidence_hash VARCHAR(64),

    -- Artifact URIs (immutable references)
    result_artifact_uri VARCHAR(1000),
    evidence_artifact_uri VARCHAR(1000),

    -- Full plan data snapshot (JSON blob for reconstruction)
    assignments_snapshot JSONB NOT NULL DEFAULT '[]'::JSONB,
    routes_snapshot JSONB DEFAULT '{}'::JSONB,

    -- Status (for superseding)
    snapshot_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',

    -- Audit metadata at publish time
    audit_passed_count INTEGER DEFAULT 0,
    audit_results_snapshot JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT plan_snapshots_status_check CHECK (
        snapshot_status IN ('ACTIVE', 'SUPERSEDED', 'ARCHIVED')
    )
);

-- Each plan_version can only have one ACTIVE snapshot (partial unique index, not constraint)
CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_snapshots_unique_active
    ON plan_snapshots(plan_version_id) WHERE snapshot_status = 'ACTIVE';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_plan_snapshots_tenant ON plan_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_plan_snapshots_plan_version ON plan_snapshots(plan_version_id);
CREATE INDEX IF NOT EXISTS idx_plan_snapshots_published_at ON plan_snapshots(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_plan_snapshots_active ON plan_snapshots(tenant_id, plan_version_id)
    WHERE snapshot_status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_plan_snapshots_output_hash ON plan_snapshots(output_hash);

-- RLS Policy
ALTER TABLE plan_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY plan_snapshots_tenant_isolation ON plan_snapshots
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

COMMENT ON TABLE plan_snapshots IS
'Immutable published plan snapshots. Each publish creates a new snapshot.
Working plan (plan_versions) can be modified; snapshots cannot.';


-- =============================================================================
-- 2. ADD current_snapshot_id TO PLAN_VERSIONS
-- =============================================================================

DO $$
BEGIN
    -- Add reference to current active snapshot
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'current_snapshot_id'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN current_snapshot_id INTEGER;
        ALTER TABLE plan_versions ADD CONSTRAINT fk_plan_versions_current_snapshot
            FOREIGN KEY (current_snapshot_id) REFERENCES plan_snapshots(id);
    END IF;

    -- Add version counter
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'publish_count'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN publish_count INTEGER DEFAULT 0;
    END IF;

    -- Track if this is a repair version
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'repair_source_snapshot_id'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN repair_source_snapshot_id INTEGER;
        ALTER TABLE plan_versions ADD CONSTRAINT fk_plan_versions_repair_source
            FOREIGN KEY (repair_source_snapshot_id) REFERENCES plan_snapshots(id);
    END IF;
END $$;


-- =============================================================================
-- 3. IMMUTABILITY TRIGGER ON SNAPSHOTS (NOT plan_versions!)
-- =============================================================================

-- First, REMOVE the old trigger from plan_versions
DROP TRIGGER IF EXISTS tr_prevent_published_modification ON plan_versions;

-- Create new trigger on plan_snapshots
CREATE OR REPLACE FUNCTION prevent_snapshot_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Cannot delete plan snapshot (id=%, snapshot_id=%)',
            OLD.id, OLD.snapshot_id;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        -- Only allow status change to SUPERSEDED or ARCHIVED
        IF NEW.snapshot_status != OLD.snapshot_status AND
           NEW.snapshot_status IN ('SUPERSEDED', 'ARCHIVED') THEN
            -- Allow status change only
            IF NEW.kpi_snapshot IS DISTINCT FROM OLD.kpi_snapshot OR
               NEW.assignments_snapshot IS DISTINCT FROM OLD.assignments_snapshot OR
               NEW.output_hash IS DISTINCT FROM OLD.output_hash OR
               NEW.published_by IS DISTINCT FROM OLD.published_by THEN
                RAISE EXCEPTION 'Cannot modify snapshot data (only status change allowed)';
            END IF;
            RETURN NEW;
        END IF;

        RAISE EXCEPTION 'Cannot modify published plan snapshot (id=%, snapshot_id=%)',
            OLD.id, OLD.snapshot_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_prevent_snapshot_modification
    BEFORE UPDATE OR DELETE ON plan_snapshots
    FOR EACH ROW
    EXECUTE FUNCTION prevent_snapshot_modification();

COMMENT ON FUNCTION prevent_snapshot_modification() IS
'Enforces immutability of published snapshots. Only status change to SUPERSEDED/ARCHIVED allowed.';


-- =============================================================================
-- 4. PUBLISH FUNCTION (CREATES IMMUTABLE SNAPSHOT)
-- =============================================================================

CREATE OR REPLACE FUNCTION publish_plan_snapshot(
    p_plan_version_id INTEGER,
    p_published_by VARCHAR,
    p_publish_reason TEXT DEFAULT NULL,
    p_kpi_snapshot JSONB DEFAULT NULL,
    p_assignments_snapshot JSONB DEFAULT '[]'::JSONB,
    p_routes_snapshot JSONB DEFAULT '{}'::JSONB
)
RETURNS JSONB
SECURITY DEFINER
SET search_path = public, core
AS $$
DECLARE
    v_plan RECORD;
    v_new_snapshot_id INTEGER;
    v_new_version_number INTEGER;
    v_freeze_until TIMESTAMPTZ;
BEGIN
    -- Lock the plan row
    SELECT pv.*, sr.input_hash, sr.matrix_hash, sr.output_hash, sr.evidence_hash,
           sr.result_artifact_uri, sr.evidence_artifact_uri
    INTO v_plan
    FROM plan_versions pv
    LEFT JOIN solver_runs sr ON sr.run_id = pv.solver_run_id
    WHERE pv.id = p_plan_version_id
    FOR UPDATE;

    IF v_plan IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Plan version not found'
        );
    END IF;

    -- Check plan is in APPROVED state (using new plan_state column)
    IF COALESCE(v_plan.plan_state, 'DRAFT') != 'APPROVED' THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Plan must be APPROVED to publish (current: %s)',
                           COALESCE(v_plan.plan_state, 'DRAFT'))
        );
    END IF;

    -- Calculate next version number
    SELECT COALESCE(MAX(version_number), 0) + 1
    INTO v_new_version_number
    FROM plan_snapshots
    WHERE plan_version_id = p_plan_version_id;

    -- Supersede any existing ACTIVE snapshot for this plan
    UPDATE plan_snapshots
    SET snapshot_status = 'SUPERSEDED'
    WHERE plan_version_id = p_plan_version_id
      AND snapshot_status = 'ACTIVE';

    -- Calculate freeze window
    v_freeze_until := NOW() + INTERVAL '12 hours';

    -- Create immutable snapshot
    INSERT INTO plan_snapshots (
        plan_version_id,
        tenant_id,
        site_id,
        version_number,
        published_by,
        publish_reason,
        freeze_until,
        solver_run_id,
        kpi_snapshot,
        input_hash,
        matrix_hash,
        output_hash,
        evidence_hash,
        result_artifact_uri,
        evidence_artifact_uri,
        assignments_snapshot,
        routes_snapshot,
        audit_passed_count,
        snapshot_status
    ) VALUES (
        p_plan_version_id,
        v_plan.tenant_id,
        v_plan.site_id,
        v_new_version_number,
        p_published_by,
        p_publish_reason,
        v_freeze_until,
        v_plan.solver_run_id,
        COALESCE(p_kpi_snapshot, '{}'::JSONB),
        COALESCE(v_plan.input_hash, 'N/A'),
        v_plan.matrix_hash,
        COALESCE(v_plan.output_hash, 'N/A'),
        v_plan.evidence_hash,
        v_plan.result_artifact_uri,
        v_plan.evidence_artifact_uri,
        p_assignments_snapshot,
        p_routes_snapshot,
        v_plan.audit_passed_count,
        'ACTIVE'
    )
    RETURNING id INTO v_new_snapshot_id;

    -- Update plan_versions to point to new snapshot
    UPDATE plan_versions
    SET current_snapshot_id = v_new_snapshot_id,
        publish_count = COALESCE(publish_count, 0) + 1,
        plan_state = 'PUBLISHED',
        plan_state_changed_at = NOW(),
        published_at = NOW(),
        published_by = p_published_by,
        freeze_until = v_freeze_until
    WHERE id = p_plan_version_id;

    -- Record in approvals audit trail
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
        v_plan.solver_run_id,
        v_plan.tenant_id,
        'PUBLISH',
        p_published_by,
        'APPROVED',
        'PUBLISHED',
        p_publish_reason,
        p_kpi_snapshot
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'snapshot_id', v_new_snapshot_id,
        'version_number', v_new_version_number,
        'plan_version_id', p_plan_version_id,
        'published_by', p_published_by,
        'freeze_until', v_freeze_until,
        'message', format('Plan published as version %s', v_new_version_number)
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION publish_plan_snapshot IS
'Creates immutable snapshot from approved plan. Supersedes any previous active snapshot.
Plan_versions can still be modified; snapshot is forever immutable.';


-- =============================================================================
-- 5. REPAIR FUNCTION (CREATES NEW VERSION FROM SNAPSHOT)
-- =============================================================================

CREATE OR REPLACE FUNCTION create_repair_version(
    p_snapshot_id INTEGER,
    p_created_by VARCHAR,
    p_repair_reason TEXT
)
RETURNS JSONB
SECURITY DEFINER
SET search_path = public, core
AS $$
DECLARE
    v_snapshot RECORD;
    v_new_plan_id INTEGER;
    v_freeze_window_active BOOLEAN;
BEGIN
    -- Get the snapshot
    SELECT *
    INTO v_snapshot
    FROM plan_snapshots
    WHERE id = p_snapshot_id;

    IF v_snapshot IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Snapshot not found'
        );
    END IF;

    -- Check freeze window
    v_freeze_window_active := v_snapshot.freeze_until > NOW();

    -- Create new plan_version as repair copy
    INSERT INTO plan_versions (
        tenant_id,
        site_id,
        forecast_version_id,
        status,
        plan_state,
        repair_source_snapshot_id,
        created_by,
        notes
    )
    SELECT
        pv.tenant_id,
        pv.site_id,
        pv.forecast_version_id,
        'DRAFT',
        'DRAFT',
        p_snapshot_id,
        p_created_by,
        format('Repair from snapshot v%s: %s', v_snapshot.version_number, p_repair_reason)
    FROM plan_versions pv
    WHERE pv.id = v_snapshot.plan_version_id
    RETURNING id INTO v_new_plan_id;

    -- Record repair action
    INSERT INTO plan_approvals (
        plan_version_id,
        tenant_id,
        action,
        performed_by,
        from_state,
        to_state,
        reason,
        evidence_snapshot
    ) VALUES (
        v_new_plan_id,
        v_snapshot.tenant_id,
        'REVERT',
        p_created_by,
        'PUBLISHED',
        'DRAFT',
        p_repair_reason,
        jsonb_build_object(
            'source_snapshot_id', p_snapshot_id,
            'source_version', v_snapshot.version_number,
            'freeze_window_active', v_freeze_window_active
        )
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'new_plan_version_id', v_new_plan_id,
        'source_snapshot_id', p_snapshot_id,
        'source_version_number', v_snapshot.version_number,
        'freeze_window_active', v_freeze_window_active,
        'message', format('Created repair version %s from snapshot v%s',
                         v_new_plan_id, v_snapshot.version_number)
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_repair_version IS
'Creates new draft plan from published snapshot for repair.
Original snapshot remains immutable. Freeze window noted but not enforced (dispatcher discretion).';


-- =============================================================================
-- 6. GET SNAPSHOT HISTORY
-- =============================================================================

CREATE OR REPLACE FUNCTION get_snapshot_history(p_plan_version_id INTEGER)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_agg(
        jsonb_build_object(
            'snapshot_id', ps.snapshot_id,
            'version_number', ps.version_number,
            'status', ps.snapshot_status,
            'published_at', ps.published_at,
            'published_by', ps.published_by,
            'publish_reason', ps.publish_reason,
            'freeze_until', ps.freeze_until,
            'is_frozen', ps.freeze_until > NOW(),
            'kpis', ps.kpi_snapshot,
            'hashes', jsonb_build_object(
                'input', ps.input_hash,
                'output', ps.output_hash,
                'evidence', ps.evidence_hash
            )
        ) ORDER BY ps.version_number DESC
    )
    INTO v_result
    FROM plan_snapshots ps
    WHERE ps.plan_version_id = p_plan_version_id;

    RETURN COALESCE(v_result, '[]'::JSONB);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_snapshot_history IS 'Returns all published snapshots for a plan';


-- =============================================================================
-- 7. CHECK FREEZE STATUS
-- =============================================================================

CREATE OR REPLACE FUNCTION is_plan_frozen(p_plan_version_id INTEGER)
RETURNS JSONB AS $$
DECLARE
    v_snapshot RECORD;
BEGIN
    SELECT ps.*
    INTO v_snapshot
    FROM plan_snapshots ps
    WHERE ps.plan_version_id = p_plan_version_id
      AND ps.snapshot_status = 'ACTIVE';

    IF v_snapshot IS NULL THEN
        RETURN jsonb_build_object(
            'is_frozen', FALSE,
            'has_active_snapshot', FALSE,
            'reason', 'No active published snapshot'
        );
    END IF;

    IF v_snapshot.freeze_until > NOW() THEN
        RETURN jsonb_build_object(
            'is_frozen', TRUE,
            'has_active_snapshot', TRUE,
            'freeze_until', v_snapshot.freeze_until,
            'minutes_remaining', EXTRACT(EPOCH FROM (v_snapshot.freeze_until - NOW())) / 60,
            'snapshot_id', v_snapshot.snapshot_id,
            'version_number', v_snapshot.version_number
        );
    END IF;

    RETURN jsonb_build_object(
        'is_frozen', FALSE,
        'has_active_snapshot', TRUE,
        'freeze_expired_at', v_snapshot.freeze_until,
        'snapshot_id', v_snapshot.snapshot_id,
        'version_number', v_snapshot.version_number
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION is_plan_frozen IS 'Check if plan has active frozen snapshot';


-- =============================================================================
-- 8. UPDATE EXISTING plan_state HANDLING
-- =============================================================================

-- Now plan_versions with plan_state='PUBLISHED' means "has active snapshot"
-- The working plan can still be modified (re-solve, etc.)
-- Only the snapshot is immutable

-- Remove the old constraint that blocked modifications to PUBLISHED plans
-- (We already dropped tr_prevent_published_modification above)

-- Instead, add a helpful view
CREATE OR REPLACE VIEW plan_version_status AS
SELECT
    pv.id AS plan_version_id,
    pv.tenant_id,
    pv.forecast_version_id,
    pv.status AS legacy_status,
    COALESCE(pv.plan_state, 'DRAFT') AS plan_state,
    pv.current_snapshot_id,
    pv.publish_count,
    pv.repair_source_snapshot_id,
    ps.snapshot_id AS active_snapshot_uuid,
    ps.version_number AS active_version,
    ps.published_at AS last_published_at,
    ps.freeze_until,
    ps.freeze_until > NOW() AS is_frozen,
    CASE
        WHEN ps.id IS NULL THEN 'Never published'
        WHEN ps.freeze_until > NOW() THEN format('Frozen until %s', ps.freeze_until)
        ELSE 'Published (freeze expired)'
    END AS status_description
FROM plan_versions pv
LEFT JOIN plan_snapshots ps ON ps.id = pv.current_snapshot_id
    AND ps.snapshot_status = 'ACTIVE';

COMMENT ON VIEW plan_version_status IS 'Plan status with snapshot information';


-- =============================================================================
-- 9. SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 027: Plan Versioning COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'NEW MODEL:';
    RAISE NOTICE '  plan_versions = Working plan (can be modified)';
    RAISE NOTICE '  plan_snapshots = Immutable published versions';
    RAISE NOTICE '';
    RAISE NOTICE 'KEY CHANGES:';
    RAISE NOTICE '  - Created plan_snapshots table (immutable)';
    RAISE NOTICE '  - Added current_snapshot_id to plan_versions';
    RAISE NOTICE '  - Moved immutability trigger to plan_snapshots';
    RAISE NOTICE '  - plan_versions can now be modified after publish!';
    RAISE NOTICE '';
    RAISE NOTICE 'FUNCTIONS:';
    RAISE NOTICE '  - publish_plan_snapshot(): Creates immutable snapshot';
    RAISE NOTICE '  - create_repair_version(): Creates new plan from snapshot';
    RAISE NOTICE '  - get_snapshot_history(): List all versions';
    RAISE NOTICE '  - is_plan_frozen(): Check freeze window status';
    RAISE NOTICE '';
    RAISE NOTICE 'FLOW:';
    RAISE NOTICE '  1. Solve → plan_versions updated (modifiable)';
    RAISE NOTICE '  2. Approve → plan_state = APPROVED';
    RAISE NOTICE '  3. Publish → create snapshot (IMMUTABLE)';
    RAISE NOTICE '  4. Repair → create_repair_version() → new draft';
    RAISE NOTICE '============================================================';
END $$;
