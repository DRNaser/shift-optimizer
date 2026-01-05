-- ============================================================================
-- MIGRATION 005: Enterprise Indexes and Constraints
-- ============================================================================
-- Adds:
-- 1. Performance indexes for common queries
-- 2. Unique constraints for idempotency
-- 3. Solver config JSON storage
-- 4. Extended plan_versions fields
-- ============================================================================

-- ============================================================================
-- 1. PERFORMANCE INDEXES
-- ============================================================================

-- tour_instances: Critical for audit queries
CREATE INDEX IF NOT EXISTS idx_tour_instances_fv_start_end
    ON tour_instances(forecast_version_id, start_ts, end_ts);

CREATE INDEX IF NOT EXISTS idx_tour_instances_fv_day
    ON tour_instances(forecast_version_id, day);

-- assignments: Critical for KPI and audit queries
CREATE INDEX IF NOT EXISTS idx_assignments_pv_driver_start
    ON assignments(plan_version_id, driver_id);

CREATE INDEX IF NOT EXISTS idx_assignments_pv_day
    ON assignments(plan_version_id, day);

-- tours_normalized: For diff engine
CREATE INDEX IF NOT EXISTS idx_tours_normalized_fingerprint_fv
    ON tours_normalized(tour_fingerprint, forecast_version_id);

-- audit_log: For release gate queries
CREATE INDEX IF NOT EXISTS idx_audit_log_pv_status
    ON audit_log(plan_version_id, status);

-- plan_versions: For finding latest by forecast
CREATE INDEX IF NOT EXISTS idx_plan_versions_fv_status_created
    ON plan_versions(forecast_version_id, status, created_at DESC);

-- ============================================================================
-- 2. IDEMPOTENCY CONSTRAINTS
-- ============================================================================

-- Prevent duplicate plans with same (forecast, seed, config)
-- Note: Only applies to non-FAILED plans
CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_versions_idempotent
    ON plan_versions(forecast_version_id, seed, solver_config_hash)
    WHERE status NOT IN ('FAILED', 'SUPERSEDED');

-- ============================================================================
-- 3. SOLVER CONFIG JSON STORAGE
-- ============================================================================

-- Add solver_config_json to plan_versions if not exists
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS solver_config_json JSONB;

COMMENT ON COLUMN plan_versions.solver_config_json IS 'Full solver configuration (JSON for auditability)';

-- Add baseline_plan_version_id for churn tracking
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS baseline_plan_version_id INTEGER REFERENCES plan_versions(id);

COMMENT ON COLUMN plan_versions.baseline_plan_version_id IS 'Baseline plan for churn calculation';

-- Add scenario_label for simulation tracking
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS scenario_label VARCHAR(100);

COMMENT ON COLUMN plan_versions.scenario_label IS 'Scenario name for simulation tracking';

-- Add churn metrics
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS churn_count INTEGER;

ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS churn_drivers_affected INTEGER;

COMMENT ON COLUMN plan_versions.churn_count IS 'Number of assignment changes vs baseline';
COMMENT ON COLUMN plan_versions.churn_drivers_affected IS 'Number of drivers with changed assignments';

-- ============================================================================
-- 4. VALIDATION FUNCTION FOR CONFIG HASH
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_solver_config_hash()
RETURNS TRIGGER AS $$
BEGIN
    -- Verify solver_config_hash matches solver_config_json if both present
    IF NEW.solver_config_json IS NOT NULL AND NEW.solver_config_hash IS NOT NULL THEN
        -- Just log warning, don't block (for migration compatibility)
        IF encode(digest(NEW.solver_config_json::text, 'sha256'), 'hex') != NEW.solver_config_hash THEN
            RAISE WARNING 'solver_config_hash may not match solver_config_json for plan_version %', NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Only create trigger if pgcrypto extension is available
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') THEN
        DROP TRIGGER IF EXISTS validate_solver_config_hash_trigger ON plan_versions;
        CREATE TRIGGER validate_solver_config_hash_trigger
        BEFORE INSERT OR UPDATE ON plan_versions
        FOR EACH ROW
        EXECUTE FUNCTION validate_solver_config_hash();
    END IF;
END $$;

-- ============================================================================
-- 5. EXTENDED AUDIT CHECK NAMES
-- ============================================================================

-- Add STATE_CHANGE and SOLVER_ERROR to valid check names
-- (Already handled by VARCHAR(100), just documenting)
COMMENT ON COLUMN audit_log.check_name IS
    'Standard: COVERAGE | OVERLAP | REST | SPAN_REGULAR | SPAN_SPLIT | FATIGUE | REPRODUCIBILITY | SENSITIVITY | '
    'Extended: STATE_CHANGE | SOLVER_ERROR | FREEZE_OVERRIDE';

-- ============================================================================
-- 6. PARTIAL INDEX FOR ACTIVE PLANS
-- ============================================================================

-- Fast lookup of active (non-superseded) plans
CREATE INDEX IF NOT EXISTS idx_plan_versions_active
    ON plan_versions(forecast_version_id, created_at DESC)
    WHERE status IN ('DRAFT', 'LOCKED', 'SOLVING');

-- ============================================================================
-- 7. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('005', 'Enterprise indexes and constraints', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 8. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Migration 005 Applied: Enterprise Indexes and Constraints';
    RAISE NOTICE '   - Performance indexes on tour_instances, assignments, tours_normalized';
    RAISE NOTICE '   - Idempotency constraint on plan_versions';
    RAISE NOTICE '   - Solver config JSON storage';
    RAISE NOTICE '   - Churn tracking columns';
    RAISE NOTICE '   - Active plans partial index';
END $$;
