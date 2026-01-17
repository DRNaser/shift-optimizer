-- ============================================================================
-- MIGRATION 006: Multi-Tenant Architecture
-- ============================================================================
-- V3.3a Product Core: Full multi-tenant support
--
-- Creates:
-- 1. tenants table (master tenant registry)
-- 2. tenant_id on all data tables
-- 3. Foreign keys and indexes
-- 4. Row-level isolation foundation
-- ============================================================================

-- ============================================================================
-- 1. TENANTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    api_key_hash    VARCHAR(64) NOT NULL UNIQUE,   -- SHA256 of API key
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB                           -- Extensible: rate limits, contact info, etc.
);

CREATE INDEX IF NOT EXISTS idx_tenants_api_key_hash ON tenants(api_key_hash) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_tenants_name ON tenants(name);

COMMENT ON TABLE tenants IS 'Multi-tenant registry with API key authentication';
COMMENT ON COLUMN tenants.api_key_hash IS 'SHA256 hash of API key (never store plaintext)';
COMMENT ON COLUMN tenants.metadata IS 'JSON for rate limits, contact info, billing tier, etc.';

-- ============================================================================
-- 2. DEFAULT TENANT (for migration of existing data)
-- ============================================================================
-- SECURITY NOTE: This tenant exists ONLY to own migrated legacy data.
-- It is INACTIVE by default and cannot be used for authentication.
-- Real tenants must be created via proper provisioning with valid API keys.

INSERT INTO tenants (id, name, api_key_hash, is_active, metadata)
VALUES (
    1,
    '_migration_data_owner',
    '__INVALID_PLACEHOLDER_NOT_A_REAL_HASH_DO_NOT_USE_FOR_AUTH__',  -- Invalid placeholder (not for auth)
    FALSE,  -- CRITICAL: Inactive - cannot be used for auth
    '{"tier": "migration", "note": "Owns legacy data from pre-multi-tenant era. NOT for auth.", "security": "inactive_by_design"}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    api_key_hash = EXCLUDED.api_key_hash,
    is_active = EXCLUDED.is_active,
    metadata = EXCLUDED.metadata;

-- Ensure sequence is ahead of manual insert
SELECT setval('tenants_id_seq', GREATEST(1, (SELECT MAX(id) FROM tenants)));

-- ============================================================================
-- 3. ADD tenant_id TO ALL DATA TABLES
-- ============================================================================

-- 3a. forecast_versions
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

UPDATE forecast_versions SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE forecast_versions ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE forecast_versions ALTER COLUMN tenant_id DROP DEFAULT;

ALTER TABLE forecast_versions
ADD CONSTRAINT fk_forecast_versions_tenant
FOREIGN KEY (tenant_id) REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_forecast_versions_tenant
ON forecast_versions(tenant_id);

CREATE INDEX IF NOT EXISTS idx_forecast_versions_tenant_created
ON forecast_versions(tenant_id, created_at DESC);

-- 3b. tours_raw
ALTER TABLE tours_raw
ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

UPDATE tours_raw tr
SET tenant_id = fv.tenant_id
FROM forecast_versions fv
WHERE tr.forecast_version_id = fv.id AND tr.tenant_id IS NULL;

-- Fallback for orphans (shouldn't exist due to FK)
UPDATE tours_raw SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE tours_raw ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE tours_raw ALTER COLUMN tenant_id DROP DEFAULT;

ALTER TABLE tours_raw
ADD CONSTRAINT fk_tours_raw_tenant
FOREIGN KEY (tenant_id) REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_tours_raw_tenant
ON tours_raw(tenant_id);

-- 3c. tours_normalized
ALTER TABLE tours_normalized
ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

UPDATE tours_normalized tn
SET tenant_id = fv.tenant_id
FROM forecast_versions fv
WHERE tn.forecast_version_id = fv.id AND tn.tenant_id IS NULL;

UPDATE tours_normalized SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE tours_normalized ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE tours_normalized ALTER COLUMN tenant_id DROP DEFAULT;

ALTER TABLE tours_normalized
ADD CONSTRAINT fk_tours_normalized_tenant
FOREIGN KEY (tenant_id) REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_tours_normalized_tenant
ON tours_normalized(tenant_id);

CREATE INDEX IF NOT EXISTS idx_tours_normalized_tenant_day
ON tours_normalized(tenant_id, day);

-- 3d. tour_instances (from migration 001)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tour_instances') THEN
        ALTER TABLE tour_instances
        ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

        UPDATE tour_instances ti
        SET tenant_id = fv.tenant_id
        FROM forecast_versions fv
        WHERE ti.forecast_version_id = fv.id AND ti.tenant_id IS NULL;

        UPDATE tour_instances SET tenant_id = 1 WHERE tenant_id IS NULL;

        ALTER TABLE tour_instances ALTER COLUMN tenant_id SET NOT NULL;
        ALTER TABLE tour_instances ALTER COLUMN tenant_id DROP DEFAULT;

        -- Check if constraint exists before adding
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_tour_instances_tenant'
        ) THEN
            ALTER TABLE tour_instances
            ADD CONSTRAINT fk_tour_instances_tenant
            FOREIGN KEY (tenant_id) REFERENCES tenants(id);
        END IF;

        CREATE INDEX IF NOT EXISTS idx_tour_instances_tenant
        ON tour_instances(tenant_id);
    END IF;
END $$;

-- 3e. plan_versions
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

UPDATE plan_versions pv
SET tenant_id = fv.tenant_id
FROM forecast_versions fv
WHERE pv.forecast_version_id = fv.id AND pv.tenant_id IS NULL;

UPDATE plan_versions SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE plan_versions ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE plan_versions ALTER COLUMN tenant_id DROP DEFAULT;

ALTER TABLE plan_versions
ADD CONSTRAINT fk_plan_versions_tenant
FOREIGN KEY (tenant_id) REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_plan_versions_tenant
ON plan_versions(tenant_id);

CREATE INDEX IF NOT EXISTS idx_plan_versions_tenant_status
ON plan_versions(tenant_id, status);

-- 3f. assignments
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

UPDATE assignments a
SET tenant_id = pv.tenant_id
FROM plan_versions pv
WHERE a.plan_version_id = pv.id AND a.tenant_id IS NULL;

UPDATE assignments SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE assignments ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE assignments ALTER COLUMN tenant_id DROP DEFAULT;

ALTER TABLE assignments
ADD CONSTRAINT fk_assignments_tenant
FOREIGN KEY (tenant_id) REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_assignments_tenant
ON assignments(tenant_id);

CREATE INDEX IF NOT EXISTS idx_assignments_tenant_driver
ON assignments(tenant_id, driver_id);

-- 3g. audit_log
ALTER TABLE audit_log
ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

UPDATE audit_log al
SET tenant_id = pv.tenant_id
FROM plan_versions pv
WHERE al.plan_version_id = pv.id AND al.tenant_id IS NULL;

UPDATE audit_log SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE audit_log ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE audit_log ALTER COLUMN tenant_id DROP DEFAULT;

ALTER TABLE audit_log
ADD CONSTRAINT fk_audit_log_tenant
FOREIGN KEY (tenant_id) REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_audit_log_tenant
ON audit_log(tenant_id);

CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_plan
ON audit_log(tenant_id, plan_version_id);

-- 3h. diff_results
ALTER TABLE diff_results
ADD COLUMN IF NOT EXISTS tenant_id INTEGER DEFAULT 1;

UPDATE diff_results dr
SET tenant_id = fv.tenant_id
FROM forecast_versions fv
WHERE dr.forecast_version_old = fv.id AND dr.tenant_id IS NULL;

UPDATE diff_results SET tenant_id = 1 WHERE tenant_id IS NULL;

ALTER TABLE diff_results ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE diff_results ALTER COLUMN tenant_id DROP DEFAULT;

ALTER TABLE diff_results
ADD CONSTRAINT fk_diff_results_tenant
FOREIGN KEY (tenant_id) REFERENCES tenants(id);

CREATE INDEX IF NOT EXISTS idx_diff_results_tenant
ON diff_results(tenant_id);

-- ============================================================================
-- 4. UNIQUE CONSTRAINTS WITH TENANT SCOPE
-- ============================================================================

-- Drop old unique constraints and recreate with tenant_id
-- Note: Use DO blocks to handle cases where constraints may not exist

DO $$
BEGIN
    -- forecast_versions: input_hash unique per tenant (not globally)
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'forecast_versions_unique_hash'
    ) THEN
        ALTER TABLE forecast_versions DROP CONSTRAINT forecast_versions_unique_hash;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'forecast_versions_input_hash_key'
    ) THEN
        ALTER TABLE forecast_versions DROP CONSTRAINT forecast_versions_input_hash_key;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_forecast_versions_tenant_hash
ON forecast_versions(tenant_id, input_hash);

-- tours_raw: (forecast_version_id, line_no) already tenant-scoped via FK cascade

-- tours_normalized: fingerprint unique per tenant+forecast
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'tours_normalized_unique_tour'
    ) THEN
        ALTER TABLE tours_normalized DROP CONSTRAINT tours_normalized_unique_tour;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tours_normalized_tenant_fp
ON tours_normalized(tenant_id, forecast_version_id, tour_fingerprint);

-- assignments: tour unique per plan (already tenant-scoped via plan FK)

-- diff_results: unique per tenant + versions + fingerprint
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'diff_results_unique_diff'
    ) THEN
        ALTER TABLE diff_results DROP CONSTRAINT diff_results_unique_diff;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_diff_results_tenant_unique
ON diff_results(tenant_id, forecast_version_old, forecast_version_new, tour_fingerprint);

-- ============================================================================
-- 5. TENANT ISOLATION VALIDATION FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_tenant_isolation()
RETURNS TABLE (
    table_name TEXT,
    total_rows BIGINT,
    rows_with_tenant BIGINT,
    tenant_coverage_pct NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 'forecast_versions'::TEXT,
           COUNT(*)::BIGINT,
           COUNT(tenant_id)::BIGINT,
           ROUND(COUNT(tenant_id)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
    FROM forecast_versions
    UNION ALL
    SELECT 'tours_raw'::TEXT, COUNT(*)::BIGINT, COUNT(tenant_id)::BIGINT,
           ROUND(COUNT(tenant_id)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
    FROM tours_raw
    UNION ALL
    SELECT 'tours_normalized'::TEXT, COUNT(*)::BIGINT, COUNT(tenant_id)::BIGINT,
           ROUND(COUNT(tenant_id)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
    FROM tours_normalized
    UNION ALL
    SELECT 'plan_versions'::TEXT, COUNT(*)::BIGINT, COUNT(tenant_id)::BIGINT,
           ROUND(COUNT(tenant_id)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
    FROM plan_versions
    UNION ALL
    SELECT 'assignments'::TEXT, COUNT(*)::BIGINT, COUNT(tenant_id)::BIGINT,
           ROUND(COUNT(tenant_id)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
    FROM assignments
    UNION ALL
    SELECT 'audit_log'::TEXT, COUNT(*)::BIGINT, COUNT(tenant_id)::BIGINT,
           ROUND(COUNT(tenant_id)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
    FROM audit_log
    UNION ALL
    SELECT 'diff_results'::TEXT, COUNT(*)::BIGINT, COUNT(tenant_id)::BIGINT,
           ROUND(COUNT(tenant_id)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
    FROM diff_results;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION validate_tenant_isolation() IS 'Verify all tables have tenant_id populated (should be 100%)';

-- ============================================================================
-- 6. UPDATE VIEWS FOR TENANT AWARENESS
-- ============================================================================

-- Drop and recreate views with tenant_id
DROP VIEW IF EXISTS latest_locked_plans;
DROP VIEW IF EXISTS release_ready_plans;

CREATE VIEW latest_locked_plans AS
SELECT DISTINCT ON (tenant_id, forecast_version_id)
    tenant_id,
    forecast_version_id,
    id AS plan_version_id,
    locked_at,
    seed,
    output_hash
FROM plan_versions
WHERE status = 'LOCKED'
ORDER BY tenant_id, forecast_version_id, locked_at DESC;

COMMENT ON VIEW latest_locked_plans IS 'Most recent LOCKED plan per tenant + forecast';

CREATE VIEW release_ready_plans AS
SELECT
    pv.tenant_id,
    pv.id AS plan_version_id,
    pv.forecast_version_id,
    pv.created_at,
    pv.seed,
    COUNT(DISTINCT al.check_name) AS checks_run,
    COUNT(DISTINCT CASE WHEN al.status = 'PASS' THEN al.check_name END) AS checks_passed
FROM plan_versions pv
LEFT JOIN audit_log al ON pv.id = al.plan_version_id
WHERE pv.status = 'DRAFT'
GROUP BY pv.tenant_id, pv.id
HAVING COUNT(DISTINCT CASE WHEN al.status = 'FAIL' THEN al.check_name END) = 0;

COMMENT ON VIEW release_ready_plans IS 'DRAFT plans with zero failed audits per tenant';

-- ============================================================================
-- 7. RECORD MIGRATION
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(20) PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('006', 'Multi-tenant architecture (V3.3a)', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 8. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 006: Multi-Tenant Architecture COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - tenants table with API key authentication';
    RAISE NOTICE '  - Default tenant (id=1) for migrated data';
    RAISE NOTICE '  - tenant_id on: forecast_versions, tours_raw, tours_normalized,';
    RAISE NOTICE '    tour_instances, plan_versions, assignments, audit_log, diff_results';
    RAISE NOTICE '  - Tenant-scoped indexes and unique constraints';
    RAISE NOTICE '  - Updated views: latest_locked_plans, release_ready_plans';
    RAISE NOTICE '  - Validation function: validate_tenant_isolation()';
    RAISE NOTICE '';
    RAISE NOTICE 'IMPORTANT: Replace default tenant API key hash before production!';
    RAISE NOTICE '==================================================================';
END $$;
