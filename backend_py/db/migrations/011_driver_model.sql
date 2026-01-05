-- ============================================================================
-- MIGRATION 011: Driver Model v1 + Availability + Repair Support
-- ============================================================================
-- Purpose: Real driver pool with availability tracking for sick-call repair
--
-- Key Design Decisions:
--   1. driver_id in assignments stays VARCHAR (backward compatible)
--   2. New real_driver_id FK for actual driver references
--   3. Availability is date-based (Europe/Vienna), not timestamp
--   4. All queries ORDER BY stable keys for determinism
-- ============================================================================

-- ============================================================================
-- 1. DRIVERS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS drivers (
    id                  SERIAL PRIMARY KEY,
    tenant_id           UUID NOT NULL,                  -- Multi-tenant support
    external_ref        VARCHAR(100) NOT NULL,          -- Stable external ID (e.g., HR system)
    display_name        VARCHAR(100),                   -- Optional, NOT in hash computation
    home_depot          VARCHAR(50),                    -- Primary depot assignment
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,  -- Soft delete
    max_weekly_hours    DECIMAL(5,2) DEFAULT 55.0,      -- Individual limit (default: ArbZG)
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT drivers_unique_external UNIQUE (tenant_id, external_ref)
);

CREATE INDEX idx_drivers_tenant ON drivers(tenant_id);
CREATE INDEX idx_drivers_active ON drivers(tenant_id, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_drivers_depot ON drivers(tenant_id, home_depot);

COMMENT ON TABLE drivers IS 'Real driver pool (PII stored separately in encrypted fields)';
COMMENT ON COLUMN drivers.external_ref IS 'Stable ID from HR/external system - use for imports';
COMMENT ON COLUMN drivers.display_name IS 'For UI only, NOT included in hash computations';
COMMENT ON COLUMN drivers.max_weekly_hours IS 'Individual weekly limit (default 55h per ArbZG)';

-- ============================================================================
-- 2. DRIVER SKILLS
-- ============================================================================

CREATE TABLE IF NOT EXISTS driver_skills (
    id                  SERIAL PRIMARY KEY,
    tenant_id           UUID NOT NULL,
    driver_id           INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    skill_code          VARCHAR(50) NOT NULL,           -- e.g., "ADR", "KUEHL", "SCHWER"
    valid_from          DATE,
    valid_until         DATE,                           -- NULL = indefinite
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT driver_skills_unique UNIQUE (tenant_id, driver_id, skill_code)
);

CREATE INDEX idx_driver_skills_driver ON driver_skills(driver_id);
CREATE INDEX idx_driver_skills_skill ON driver_skills(tenant_id, skill_code);

COMMENT ON TABLE driver_skills IS 'Driver qualifications/certifications';
COMMENT ON COLUMN driver_skills.skill_code IS 'Matches tours_normalized.skill for assignment validation';

-- ============================================================================
-- 3. DRIVER AVAILABILITY
-- ============================================================================
-- Date-based (not timestamp) - one status per driver per day
-- Default is AVAILABLE if no row exists

CREATE TYPE driver_availability_status AS ENUM (
    'AVAILABLE',    -- Can be assigned
    'SICK',         -- Sick leave (primary use case for repair)
    'VACATION',     -- Planned absence
    'BLOCKED'       -- Other unavailability (training, etc.)
);

CREATE TABLE IF NOT EXISTS driver_availability (
    id                  SERIAL PRIMARY KEY,
    tenant_id           UUID NOT NULL,
    driver_id           INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    date                DATE NOT NULL,                  -- Europe/Vienna timezone assumed
    status              driver_availability_status NOT NULL DEFAULT 'AVAILABLE',
    note                TEXT,                           -- Optional reason
    source              VARCHAR(50),                    -- "manual", "hr_import", "repair_api"
    reported_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    reported_by         VARCHAR(100),                   -- User who reported

    CONSTRAINT driver_availability_unique UNIQUE (tenant_id, driver_id, date)
);

CREATE INDEX idx_driver_availability_date ON driver_availability(tenant_id, date);
CREATE INDEX idx_driver_availability_driver ON driver_availability(driver_id);
CREATE INDEX idx_driver_availability_status ON driver_availability(tenant_id, date, status);

COMMENT ON TABLE driver_availability IS 'Daily driver availability status';
COMMENT ON COLUMN driver_availability.date IS 'Date in Europe/Vienna timezone';
COMMENT ON COLUMN driver_availability.status IS 'AVAILABLE=can work, SICK/VACATION/BLOCKED=cannot';

-- ============================================================================
-- 4. ASSIGNMENTS EXTENSION
-- ============================================================================
-- Add real_driver_id FK for actual driver references (nullable for backward compat)

ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS real_driver_id INTEGER REFERENCES drivers(id);

CREATE INDEX IF NOT EXISTS idx_assignments_real_driver ON assignments(real_driver_id);

COMMENT ON COLUMN assignments.real_driver_id IS 'FK to drivers table (NULL for anon IDs)';

-- ============================================================================
-- 5. PLAN VERSIONS EXTENSION FOR REPAIR
-- ============================================================================
-- Track repair-related metadata

ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS is_repair BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS parent_plan_id INTEGER REFERENCES plan_versions(id),
ADD COLUMN IF NOT EXISTS repair_reason TEXT,
ADD COLUMN IF NOT EXISTS absent_driver_ids JSONB;  -- Array of driver IDs that were absent

CREATE INDEX IF NOT EXISTS idx_plan_versions_repair ON plan_versions(is_repair) WHERE is_repair = TRUE;
CREATE INDEX IF NOT EXISTS idx_plan_versions_parent ON plan_versions(parent_plan_id);

COMMENT ON COLUMN plan_versions.is_repair IS 'TRUE if this plan was created via repair endpoint';
COMMENT ON COLUMN plan_versions.parent_plan_id IS 'Original plan that was repaired';
COMMENT ON COLUMN plan_versions.absent_driver_ids IS 'JSON array of driver IDs that triggered repair';

-- ============================================================================
-- 6. REPAIR AUDIT LOG
-- ============================================================================
-- Track repair operations for audit trail

CREATE TABLE IF NOT EXISTS repair_log (
    id                  SERIAL PRIMARY KEY,
    tenant_id           UUID NOT NULL,
    parent_plan_id      INTEGER NOT NULL REFERENCES plan_versions(id),
    result_plan_id      INTEGER REFERENCES plan_versions(id),  -- NULL if repair failed

    -- Repair parameters
    absent_driver_ids   JSONB NOT NULL,                 -- Input: drivers that were absent
    respect_freeze      BOOLEAN NOT NULL DEFAULT TRUE,
    strategy            VARCHAR(50) NOT NULL DEFAULT 'MIN_CHURN',
    time_budget_ms      INTEGER,
    seed                INTEGER,

    -- Repair results
    status              VARCHAR(20) NOT NULL,           -- PENDING, SUCCESS, FAILED, TIMEOUT
    error_message       TEXT,

    -- Metrics
    tours_reassigned    INTEGER,
    drivers_affected    INTEGER,
    churn_rate          DECIMAL(5,4),                   -- e.g., 0.0523 = 5.23%
    freeze_violations   INTEGER DEFAULT 0,
    execution_time_ms   INTEGER,

    -- Timestamps
    requested_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMP,
    requested_by        VARCHAR(100),

    -- Idempotency
    idempotency_key     VARCHAR(64),

    CONSTRAINT repair_log_unique_idempotency UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX idx_repair_log_tenant ON repair_log(tenant_id);
CREATE INDEX idx_repair_log_parent ON repair_log(parent_plan_id);
CREATE INDEX idx_repair_log_status ON repair_log(status);
CREATE INDEX idx_repair_log_requested ON repair_log(requested_at DESC);

COMMENT ON TABLE repair_log IS 'Audit trail for all repair operations';
COMMENT ON COLUMN repair_log.absent_driver_ids IS 'JSON array of driver IDs that were reported absent';
COMMENT ON COLUMN repair_log.churn_rate IS 'Percentage of tours that changed assignment';

-- ============================================================================
-- 7. HELPER FUNCTIONS
-- ============================================================================

-- Get eligible drivers for a date (AVAILABLE status)
CREATE OR REPLACE FUNCTION get_eligible_drivers(
    p_tenant_id UUID,
    p_date DATE
)
RETURNS TABLE (
    driver_id INTEGER,
    external_ref VARCHAR,
    home_depot VARCHAR,
    max_weekly_hours DECIMAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.external_ref,
        d.home_depot,
        d.max_weekly_hours
    FROM drivers d
    WHERE d.tenant_id = p_tenant_id
      AND d.is_active = TRUE
      AND NOT EXISTS (
          SELECT 1
          FROM driver_availability da
          WHERE da.driver_id = d.id
            AND da.date = p_date
            AND da.status != 'AVAILABLE'
      )
    ORDER BY d.id;  -- Deterministic ordering!
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_eligible_drivers IS 'Returns drivers AVAILABLE on given date (deterministic ORDER BY id)';

-- Get eligible drivers for a week (all days AVAILABLE)
CREATE OR REPLACE FUNCTION get_eligible_drivers_week(
    p_tenant_id UUID,
    p_week_start DATE
)
RETURNS TABLE (
    driver_id INTEGER,
    external_ref VARCHAR,
    home_depot VARCHAR,
    max_weekly_hours DECIMAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.external_ref,
        d.home_depot,
        d.max_weekly_hours
    FROM drivers d
    WHERE d.tenant_id = p_tenant_id
      AND d.is_active = TRUE
      AND NOT EXISTS (
          SELECT 1
          FROM driver_availability da
          WHERE da.driver_id = d.id
            AND da.date >= p_week_start
            AND da.date < p_week_start + INTERVAL '7 days'
            AND da.status != 'AVAILABLE'
      )
    ORDER BY d.id;  -- Deterministic ordering!
END;
$$ LANGUAGE plpgsql STABLE;

-- Check if driver has skills for tour
CREATE OR REPLACE FUNCTION driver_has_skill(
    p_driver_id INTEGER,
    p_skill_code VARCHAR,
    p_date DATE DEFAULT CURRENT_DATE
)
RETURNS BOOLEAN AS $$
BEGIN
    -- NULL skill = no requirement
    IF p_skill_code IS NULL THEN
        RETURN TRUE;
    END IF;

    RETURN EXISTS (
        SELECT 1
        FROM driver_skills ds
        WHERE ds.driver_id = p_driver_id
          AND ds.skill_code = p_skill_code
          AND (ds.valid_from IS NULL OR ds.valid_from <= p_date)
          AND (ds.valid_until IS NULL OR ds.valid_until >= p_date)
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- 8. RLS POLICIES (Security Layer Integration)
-- ============================================================================
-- Only apply if RLS is enabled (check for security_audit_log table existence)

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'security_audit_log') THEN
        -- Enable RLS on new tables
        ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
        ALTER TABLE driver_skills ENABLE ROW LEVEL SECURITY;
        ALTER TABLE driver_availability ENABLE ROW LEVEL SECURITY;
        ALTER TABLE repair_log ENABLE ROW LEVEL SECURITY;

        -- Create policies
        CREATE POLICY tenant_isolation_drivers ON drivers
            FOR ALL USING (
                tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            );

        CREATE POLICY tenant_isolation_driver_skills ON driver_skills
            FOR ALL USING (
                tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            );

        CREATE POLICY tenant_isolation_driver_availability ON driver_availability
            FOR ALL USING (
                tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            );

        CREATE POLICY tenant_isolation_repair_log ON repair_log
            FOR ALL USING (
                tenant_id::TEXT = current_setting('app.current_tenant_id', true)
                OR current_setting('app.is_super_admin', true) = 'true'
            );

        RAISE NOTICE 'RLS policies applied to driver tables';
    ELSE
        RAISE NOTICE 'RLS not enabled (security_audit_log not found) - skipping policies';
    END IF;
END $$;

-- ============================================================================
-- 9. MIGRATION RECORD
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('011', 'driver_model_v1', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- SUCCESS
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '================================================================';
    RAISE NOTICE 'Migration 011: Driver Model v1 applied successfully';
    RAISE NOTICE '================================================================';
    RAISE NOTICE 'Tables created:';
    RAISE NOTICE '  - drivers (with tenant_id, external_ref, home_depot)';
    RAISE NOTICE '  - driver_skills (skill_code, valid_from/until)';
    RAISE NOTICE '  - driver_availability (date-based status)';
    RAISE NOTICE '  - repair_log (audit trail for repairs)';
    RAISE NOTICE '';
    RAISE NOTICE 'Columns added to assignments:';
    RAISE NOTICE '  - real_driver_id (FK to drivers, nullable)';
    RAISE NOTICE '';
    RAISE NOTICE 'Columns added to plan_versions:';
    RAISE NOTICE '  - is_repair, parent_plan_id, absent_driver_ids';
    RAISE NOTICE '';
    RAISE NOTICE 'Helper functions:';
    RAISE NOTICE '  - get_eligible_drivers(tenant_id, date)';
    RAISE NOTICE '  - get_eligible_drivers_week(tenant_id, week_start)';
    RAISE NOTICE '  - driver_has_skill(driver_id, skill_code, date)';
    RAISE NOTICE '================================================================';
END $$;
