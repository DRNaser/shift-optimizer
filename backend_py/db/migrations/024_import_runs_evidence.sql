-- =============================================================================
-- Migration 024: Import Runs + Evidence Pointers
-- =============================================================================
-- Adds tables for tracking FLS imports and evidence artifacts.
--
-- Tables:
-- - import_runs: Tracks each import batch with hashes and verdicts
-- - import_artifacts: Links import runs to artifact store URIs
-- - routing_evidence: Tracks routing evidence for plans
--
-- Run with: psql $DATABASE_URL < backend_py/db/migrations/024_import_runs_evidence.sql
-- =============================================================================

-- Record migration start
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('024', 'Import runs + evidence pointers', NOW())
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- IMPORT RUNS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS import_runs (
    -- Primary key
    id SERIAL PRIMARY KEY,
    import_run_id VARCHAR(50) NOT NULL UNIQUE,

    -- Tenant/Site scope
    tenant_id UUID NOT NULL REFERENCES core.tenants(id),
    site_id UUID NOT NULL REFERENCES core.sites(id),

    -- Timestamps
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Source info
    source_type VARCHAR(50) NOT NULL DEFAULT 'FLS',
    source_file VARCHAR(500),
    fls_export_id VARCHAR(100),

    -- Hashes (for audit/determinism)
    raw_hash VARCHAR(64) NOT NULL,
    canonical_hash VARCHAR(64) NOT NULL,

    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'IN_PROGRESS',
    verdict VARCHAR(20) NOT NULL DEFAULT 'PENDING',

    -- Statistics
    orders_raw INTEGER NOT NULL DEFAULT 0,
    orders_canonical INTEGER NOT NULL DEFAULT 0,
    orders_imported INTEGER NOT NULL DEFAULT 0,
    orders_skipped INTEGER NOT NULL DEFAULT 0,

    -- Coords stats
    orders_with_coords INTEGER NOT NULL DEFAULT 0,
    orders_with_zone INTEGER NOT NULL DEFAULT 0,
    orders_missing_location INTEGER NOT NULL DEFAULT 0,

    -- Error tracking (JSONB for flexibility)
    errors JSONB DEFAULT '[]'::JSONB,
    warnings JSONB DEFAULT '[]'::JSONB,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255),

    -- Constraints
    CONSTRAINT import_runs_status_check CHECK (
        status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED', 'BLOCKED', 'PENDING_APPROVAL')
    ),
    CONSTRAINT import_runs_verdict_check CHECK (
        verdict IN ('PENDING', 'OK', 'WARN', 'BLOCK')
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_import_runs_tenant_site ON import_runs(tenant_id, site_id);
CREATE INDEX IF NOT EXISTS idx_import_runs_status ON import_runs(status);
CREATE INDEX IF NOT EXISTS idx_import_runs_started_at ON import_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_import_runs_canonical_hash ON import_runs(canonical_hash);

-- RLS Policy
ALTER TABLE import_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY import_runs_tenant_isolation ON import_runs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

COMMENT ON TABLE import_runs IS 'Tracks FLS import batches with hashes and verdicts';


-- =============================================================================
-- IMPORT ARTIFACTS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS import_artifacts (
    -- Primary key
    id SERIAL PRIMARY KEY,

    -- Foreign key to import run
    import_run_id VARCHAR(50) NOT NULL REFERENCES import_runs(import_run_id) ON DELETE CASCADE,

    -- Artifact info
    artifact_type VARCHAR(50) NOT NULL,
    artifact_uri VARCHAR(1000) NOT NULL,
    content_hash VARCHAR(64),
    content_type VARCHAR(100) DEFAULT 'application/json',
    size_bytes BIGINT,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::JSONB,

    -- Constraints
    CONSTRAINT import_artifacts_type_check CHECK (
        artifact_type IN (
            'raw_blob',
            'canonical_orders',
            'validation_report',
            'coords_quality_report'
        )
    ),
    UNIQUE(import_run_id, artifact_type)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_import_artifacts_run ON import_artifacts(import_run_id);
CREATE INDEX IF NOT EXISTS idx_import_artifacts_type ON import_artifacts(artifact_type);

COMMENT ON TABLE import_artifacts IS 'Links import runs to artifact store URIs';


-- =============================================================================
-- ROUTING EVIDENCE TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS routing_evidence (
    -- Primary key
    id SERIAL PRIMARY KEY,

    -- Foreign key to plan
    plan_version_id INTEGER NOT NULL, -- References plan_versions(id)

    -- Tenant/Site scope
    tenant_id UUID NOT NULL REFERENCES core.tenants(id),
    site_id UUID NOT NULL REFERENCES core.sites(id),

    -- Matrix info
    matrix_version VARCHAR(100) NOT NULL,
    matrix_hash VARCHAR(64) NOT NULL,

    -- OSRM info
    osrm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    osrm_map_hash VARCHAR(64),
    osrm_profile VARCHAR(50),

    -- Finalize verdict
    finalize_verdict VARCHAR(20) NOT NULL DEFAULT 'N/A',
    finalize_time_seconds FLOAT DEFAULT 0,

    -- Drift metrics
    drift_p95_ratio FLOAT,
    drift_max_ratio FLOAT,
    drift_mean_ratio FLOAT,

    -- TW validation
    tw_violations_count INTEGER NOT NULL DEFAULT 0,
    tw_max_violation_seconds INTEGER NOT NULL DEFAULT 0,

    -- Rates
    timeout_rate FLOAT NOT NULL DEFAULT 0,
    fallback_rate FLOAT NOT NULL DEFAULT 0,
    total_legs INTEGER NOT NULL DEFAULT 0,

    -- Verdict reasons (JSONB array)
    verdict_reasons JSONB DEFAULT '[]'::JSONB,

    -- Artifact references
    drift_report_artifact_id VARCHAR(500),
    fallback_report_artifact_id VARCHAR(500),
    tw_validation_artifact_id VARCHAR(500),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT routing_evidence_verdict_check CHECK (
        finalize_verdict IN ('OK', 'WARN', 'BLOCK', 'N/A')
    ),
    UNIQUE(plan_version_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_routing_evidence_plan ON routing_evidence(plan_version_id);
CREATE INDEX IF NOT EXISTS idx_routing_evidence_tenant_site ON routing_evidence(tenant_id, site_id);
CREATE INDEX IF NOT EXISTS idx_routing_evidence_verdict ON routing_evidence(finalize_verdict);
CREATE INDEX IF NOT EXISTS idx_routing_evidence_matrix ON routing_evidence(matrix_version);

-- RLS Policy
ALTER TABLE routing_evidence ENABLE ROW LEVEL SECURITY;

CREATE POLICY routing_evidence_tenant_isolation ON routing_evidence
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

COMMENT ON TABLE routing_evidence IS 'Stores routing evidence for plan audit trail';


-- =============================================================================
-- ADD COLUMNS TO EXISTING TABLES
-- =============================================================================

-- Add import_run_id to orders if table exists and column not exists
-- GREENFIELD FIX: Check table exists first
DO $$
BEGIN
    -- Only proceed if orders table exists
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'orders'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'orders' AND column_name = 'import_run_id'
        ) THEN
            ALTER TABLE orders ADD COLUMN import_run_id VARCHAR(50);
            CREATE INDEX idx_orders_import_run ON orders(import_run_id);
        END IF;
    ELSE
        RAISE NOTICE '[024] Table orders does not exist - skipping import_run_id column';
    END IF;
END $$;

-- Add matrix_version to plan_versions if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'matrix_version'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN matrix_version VARCHAR(100);
        ALTER TABLE plan_versions ADD COLUMN osrm_map_hash VARCHAR(64);
        ALTER TABLE plan_versions ADD COLUMN drift_verdict VARCHAR(20);
        CREATE INDEX idx_plan_versions_matrix ON plan_versions(matrix_version);
    END IF;
END $$;


-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get import run summary
CREATE OR REPLACE FUNCTION get_import_run_summary(p_import_run_id VARCHAR)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'import_run_id', ir.import_run_id,
        'status', ir.status,
        'verdict', ir.verdict,
        'started_at', ir.started_at,
        'completed_at', ir.completed_at,
        'orders', jsonb_build_object(
            'raw', ir.orders_raw,
            'canonical', ir.orders_canonical,
            'imported', ir.orders_imported,
            'skipped', ir.orders_skipped
        ),
        'coords', jsonb_build_object(
            'with_latlng', ir.orders_with_coords,
            'with_zone', ir.orders_with_zone,
            'missing', ir.orders_missing_location
        ),
        'hashes', jsonb_build_object(
            'raw', ir.raw_hash,
            'canonical', ir.canonical_hash
        ),
        'artifacts', (
            SELECT jsonb_agg(jsonb_build_object(
                'type', ia.artifact_type,
                'uri', ia.artifact_uri
            ))
            FROM import_artifacts ia
            WHERE ia.import_run_id = ir.import_run_id
        )
    )
    INTO v_result
    FROM import_runs ir
    WHERE ir.import_run_id = p_import_run_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_import_run_summary(VARCHAR) IS 'Returns JSON summary of an import run';


-- Function to get routing evidence for a plan
CREATE OR REPLACE FUNCTION get_routing_evidence(p_plan_version_id INTEGER)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'matrix', jsonb_build_object(
            'version', re.matrix_version,
            'hash', re.matrix_hash
        ),
        'osrm', jsonb_build_object(
            'enabled', re.osrm_enabled,
            'map_hash', re.osrm_map_hash,
            'profile', re.osrm_profile
        ),
        'finalize', jsonb_build_object(
            'verdict', re.finalize_verdict,
            'time_seconds', re.finalize_time_seconds,
            'reasons', re.verdict_reasons
        ),
        'drift', jsonb_build_object(
            'p95_ratio', re.drift_p95_ratio,
            'max_ratio', re.drift_max_ratio,
            'mean_ratio', re.drift_mean_ratio
        ),
        'tw_validation', jsonb_build_object(
            'violations_count', re.tw_violations_count,
            'max_violation_seconds', re.tw_max_violation_seconds
        ),
        'rates', jsonb_build_object(
            'timeout_rate', re.timeout_rate,
            'fallback_rate', re.fallback_rate,
            'total_legs', re.total_legs
        ),
        'artifacts', jsonb_build_object(
            'drift_report', re.drift_report_artifact_id,
            'fallback_report', re.fallback_report_artifact_id,
            'tw_validation', re.tw_validation_artifact_id
        )
    )
    INTO v_result
    FROM routing_evidence re
    WHERE re.plan_version_id = p_plan_version_id;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_routing_evidence(INTEGER) IS 'Returns JSON routing evidence for a plan';


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Migration 024 completed successfully';
    RAISE NOTICE 'Created tables: import_runs, import_artifacts, routing_evidence';
    RAISE NOTICE 'Created functions: get_import_run_summary, get_routing_evidence';
END $$;
