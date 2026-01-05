-- ============================================================================
-- SOLVEREIGN V3 Database Schema
-- ============================================================================
-- Purpose: Single Source of Truth for Forecast & Plan Versioning
-- Created: 2026-01-04
-- Version: 3.0.0-mvp
-- ============================================================================

-- Enable UUID extension (for future use)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 1. FORECAST VERSIONS
-- ============================================================================
-- Tracks each input forecast (from Slack, CSV, or manual entry)
-- ============================================================================

CREATE TABLE forecast_versions (
    id                  SERIAL PRIMARY KEY,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    source              VARCHAR(50) NOT NULL CHECK (source IN ('slack', 'csv', 'manual')),
    input_hash          VARCHAR(64) NOT NULL UNIQUE,  -- SHA256 of canonical input
    parser_config_hash  VARCHAR(64) NOT NULL,         -- Version control for parser rules
    status              VARCHAR(10) NOT NULL CHECK (status IN ('PASS', 'WARN', 'FAIL')),
    week_key            VARCHAR(20),                  -- Week identifier (e.g., "2026-W01")
    week_anchor_date    DATE,                         -- Monday of the week for datetime computation
    notes               TEXT,
    CONSTRAINT forecast_versions_unique_hash UNIQUE (input_hash)
);

CREATE INDEX idx_forecast_versions_created_at ON forecast_versions(created_at DESC);
CREATE INDEX idx_forecast_versions_status ON forecast_versions(status);

COMMENT ON TABLE forecast_versions IS 'Master table for input forecast versions with validation status';
COMMENT ON COLUMN forecast_versions.input_hash IS 'SHA256 hash of canonicalized input for deduplication';
COMMENT ON COLUMN forecast_versions.parser_config_hash IS 'Parser version control - changes trigger re-validation';
COMMENT ON COLUMN forecast_versions.status IS 'PASS = proceed, WARN = review recommended, FAIL = blocks solver';

-- ============================================================================
-- 2. TOURS RAW
-- ============================================================================
-- Raw input lines with parse status (before normalization)
-- ============================================================================

CREATE TABLE tours_raw (
    id                  SERIAL PRIMARY KEY,
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    line_no             INTEGER NOT NULL,
    raw_text            TEXT NOT NULL,
    parse_status        VARCHAR(10) NOT NULL CHECK (parse_status IN ('PASS', 'WARN', 'FAIL')),
    parse_errors        JSONB,  -- [{code, message, severity}, ...]
    parse_warnings      JSONB,
    canonical_text      TEXT,   -- Standardized format for hashing
    CONSTRAINT tours_raw_unique_line UNIQUE (forecast_version_id, line_no)
);

CREATE INDEX idx_tours_raw_forecast_version ON tours_raw(forecast_version_id);
CREATE INDEX idx_tours_raw_parse_status ON tours_raw(parse_status);

COMMENT ON TABLE tours_raw IS 'Unparsed input lines with validation results';
COMMENT ON COLUMN tours_raw.canonical_text IS 'Standardized format (e.g., "Mo 06:00-14:00 (3)") for hashing';
COMMENT ON COLUMN tours_raw.parse_errors IS 'JSON array of error objects for failed lines';

-- ============================================================================
-- 3. TOURS NORMALIZED
-- ============================================================================
-- Normalized tour data (ready for solver)
-- ============================================================================

CREATE TABLE tours_normalized (
    id                  SERIAL PRIMARY KEY,  -- Stable ID across versions (via fingerprint matching)
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    day                 INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),  -- 1=Mo, 7=So
    start_ts            TIME NOT NULL,
    end_ts              TIME NOT NULL,
    duration_min        INTEGER NOT NULL CHECK (duration_min > 0),
    work_hours          DECIMAL(5,2) NOT NULL CHECK (work_hours > 0),
    span_group_key      VARCHAR(50),  -- For split shift grouping (e.g., "Mo_06-14_15-19")
    tour_fingerprint    VARCHAR(64) NOT NULL,  -- hash(day, start, end, depot?, skill?)
    count               INTEGER NOT NULL DEFAULT 1 CHECK (count > 0),  -- Template expansion
    depot               VARCHAR(50),
    skill               VARCHAR(50),
    metadata            JSONB,  -- Extensible field for future attributes
    CONSTRAINT tours_normalized_unique_tour UNIQUE (forecast_version_id, tour_fingerprint)
);

CREATE INDEX idx_tours_normalized_forecast_version ON tours_normalized(forecast_version_id);
CREATE INDEX idx_tours_normalized_fingerprint ON tours_normalized(tour_fingerprint);
CREATE INDEX idx_tours_normalized_day ON tours_normalized(day);

COMMENT ON TABLE tours_normalized IS 'Canonical tour representation for solver input';
COMMENT ON COLUMN tours_normalized.tour_fingerprint IS 'Stable identity for diff matching across versions';
COMMENT ON COLUMN tours_normalized.count IS 'Number of instances (e.g., "3 Fahrer" → count=3)';
COMMENT ON COLUMN tours_normalized.span_group_key IS 'Links split shift segments together';

-- ============================================================================
-- 4. PLAN VERSIONS
-- ============================================================================
-- Solver output versions (DRAFT → LOCKED)
-- ============================================================================

CREATE TABLE plan_versions (
    id                  SERIAL PRIMARY KEY,
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    seed                INTEGER NOT NULL,  -- Deterministic solver seed
    solver_config_hash  VARCHAR(64) NOT NULL,  -- Solver parameter version
    output_hash         VARCHAR(64) NOT NULL,  -- SHA256(assignments + kpis)
    status              VARCHAR(20) NOT NULL CHECK (status IN ('DRAFT', 'LOCKED', 'SUPERSEDED', 'SOLVING', 'FAILED')),
    locked_at           TIMESTAMP,
    locked_by           VARCHAR(100),
    notes               TEXT,
    CONSTRAINT plan_versions_lock_integrity CHECK (
        (status = 'LOCKED' AND locked_at IS NOT NULL) OR
        (status != 'LOCKED' AND locked_at IS NULL)
    )
);

CREATE INDEX idx_plan_versions_forecast_version ON plan_versions(forecast_version_id);
CREATE INDEX idx_plan_versions_status ON plan_versions(status);
CREATE INDEX idx_plan_versions_created_at ON plan_versions(created_at DESC);

COMMENT ON TABLE plan_versions IS 'Immutable solver output versions';
COMMENT ON COLUMN plan_versions.seed IS 'Partition seed for reproducibility (e.g., 94 for normal forecast)';
COMMENT ON COLUMN plan_versions.output_hash IS 'SHA256 of complete solution for reproducibility testing';
COMMENT ON COLUMN plan_versions.status IS 'DRAFT = under review, LOCKED = released, SUPERSEDED = replaced by newer plan';

-- ============================================================================
-- 5. ASSIGNMENTS
-- ============================================================================
-- Driver-to-tour assignments for each plan version
-- ============================================================================

CREATE TABLE assignments (
    id                  SERIAL PRIMARY KEY,
    plan_version_id     INTEGER NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
    driver_id           VARCHAR(50) NOT NULL,  -- roster_id or driver identifier (e.g., "D001", "D002")
    tour_id             INTEGER NOT NULL REFERENCES tours_normalized(id),
    day                 INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),
    block_id            VARCHAR(50) NOT NULL,  -- e.g., "D1_B3" (Day 1, Block 3)
    role                VARCHAR(50),  -- Optional: 'PRIMARY' | 'BACKUP'
    metadata            JSONB,  -- Extensible for future attributes
    CONSTRAINT assignments_unique_tour_assignment UNIQUE (plan_version_id, tour_id)
);

CREATE INDEX idx_assignments_plan_version ON assignments(plan_version_id);
CREATE INDEX idx_assignments_driver ON assignments(driver_id);
CREATE INDEX idx_assignments_tour ON assignments(tour_id);
CREATE INDEX idx_assignments_day ON assignments(day);

COMMENT ON TABLE assignments IS 'Driver-to-tour mappings for each plan version';
COMMENT ON COLUMN assignments.driver_id IS 'Roster identifier (not FK yet - drivers table in V4+)';
COMMENT ON COLUMN assignments.block_id IS 'Daily block identifier (e.g., D1_B3 = Day 1, Block 3)';

-- ============================================================================
-- 6. AUDIT LOG
-- ============================================================================
-- Automated validation checks for each plan version
-- ============================================================================

CREATE TABLE audit_log (
    id                  SERIAL PRIMARY KEY,
    plan_version_id     INTEGER NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
    check_name          VARCHAR(100) NOT NULL,  -- 'COVERAGE' | 'REST' | 'OVERLAP' | 'SPAN' | 'REPRODUCIBILITY'
    status              VARCHAR(10) NOT NULL CHECK (status IN ('PASS', 'FAIL', 'OVERRIDE')),
    count               INTEGER DEFAULT 0,  -- Violation count (0 for PASS)
    details_json        JSONB,  -- Full check details (violations, driver IDs, tour IDs, etc.)
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT audit_log_count_integrity CHECK (
        (status = 'PASS' AND count = 0) OR
        (status = 'FAIL' AND count > 0) OR
        (status = 'OVERRIDE')  -- Override can have any count (number of affected instances)
    )
);

CREATE INDEX idx_audit_log_plan_version ON audit_log(plan_version_id);
CREATE INDEX idx_audit_log_check_name ON audit_log(check_name);
CREATE INDEX idx_audit_log_status ON audit_log(status);

COMMENT ON TABLE audit_log IS 'Write-only validation log for audit trail';
COMMENT ON COLUMN audit_log.check_name IS 'Standardized check identifier (see roadmap section 8)';
COMMENT ON COLUMN audit_log.details_json IS 'Full violation details for debugging';

-- ============================================================================
-- 7. FREEZE WINDOWS (Optional MVP)
-- ============================================================================
-- Operational stability rules for last-minute plan changes
-- ============================================================================

CREATE TABLE freeze_windows (
    id                  SERIAL PRIMARY KEY,
    rule_name           VARCHAR(100) NOT NULL UNIQUE,  -- 'PRE_SHIFT_12H' | 'SAME_DAY'
    minutes_before_start INTEGER NOT NULL CHECK (minutes_before_start > 0),  -- Freeze threshold
    behavior            VARCHAR(50) NOT NULL CHECK (behavior IN ('FROZEN', 'OVERRIDE_REQUIRED')),
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

INSERT INTO freeze_windows (rule_name, minutes_before_start, behavior, enabled) VALUES
    ('PRE_SHIFT_12H', 720, 'FROZEN', TRUE),  -- Default: 12-hour freeze window
    ('PRE_SHIFT_6H', 360, 'OVERRIDE_REQUIRED', FALSE),  -- Alternative: 6-hour with override
    ('SAME_DAY', 1440, 'FROZEN', FALSE);  -- Optional: Full day-before freeze

COMMENT ON TABLE freeze_windows IS 'Operational stability rules to prevent last-minute plan thrashing';
COMMENT ON COLUMN freeze_windows.minutes_before_start IS 'Freeze if now >= tour.start - X minutes';
COMMENT ON COLUMN freeze_windows.behavior IS 'FROZEN = block changes, OVERRIDE_REQUIRED = allow with audit';

-- ============================================================================
-- 8. DIFF RESULTS (Optional - for caching)
-- ============================================================================
-- Pre-computed diff between forecast versions (performance optimization)
-- ============================================================================

CREATE TABLE diff_results (
    id                  SERIAL PRIMARY KEY,
    forecast_version_old INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    forecast_version_new INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    diff_type           VARCHAR(20) NOT NULL CHECK (diff_type IN ('ADDED', 'REMOVED', 'CHANGED')),
    tour_fingerprint    VARCHAR(64) NOT NULL,
    old_values          JSONB,  -- For REMOVED/CHANGED
    new_values          JSONB,  -- For ADDED/CHANGED
    changed_fields      JSONB,  -- For CHANGED only
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT diff_results_unique_diff UNIQUE (forecast_version_old, forecast_version_new, tour_fingerprint)
);

CREATE INDEX idx_diff_results_versions ON diff_results(forecast_version_old, forecast_version_new);
CREATE INDEX idx_diff_results_type ON diff_results(diff_type);

COMMENT ON TABLE diff_results IS 'Cached diff results for performance (compute once, query many)';
COMMENT ON COLUMN diff_results.diff_type IS 'ADDED = new tour, REMOVED = deleted tour, CHANGED = modified attributes';

-- ============================================================================
-- 9. UTILITY VIEWS
-- ============================================================================

-- View: Latest LOCKED plan per forecast
CREATE VIEW latest_locked_plans AS
SELECT DISTINCT ON (forecast_version_id)
    forecast_version_id,
    id AS plan_version_id,
    locked_at,
    seed,
    output_hash
FROM plan_versions
WHERE status = 'LOCKED'
ORDER BY forecast_version_id, locked_at DESC;

COMMENT ON VIEW latest_locked_plans IS 'Most recent LOCKED plan for each forecast version';

-- View: Release-ready DRAFT plans (all gates passed)
CREATE VIEW release_ready_plans AS
SELECT
    pv.id AS plan_version_id,
    pv.forecast_version_id,
    pv.created_at,
    pv.seed,
    COUNT(DISTINCT al.check_name) AS checks_run,
    COUNT(DISTINCT CASE WHEN al.status = 'PASS' THEN al.check_name END) AS checks_passed
FROM plan_versions pv
LEFT JOIN audit_log al ON pv.id = al.plan_version_id
WHERE pv.status = 'DRAFT'
GROUP BY pv.id
HAVING COUNT(DISTINCT CASE WHEN al.status = 'FAIL' THEN al.check_name END) = 0;

COMMENT ON VIEW release_ready_plans IS 'DRAFT plans with zero failed audit checks (ready for release)';

-- ============================================================================
-- 10. TRIGGERS FOR AUDIT TRAIL
-- ============================================================================

-- Trigger 1: Prevent status change from LOCKED in plan_versions
CREATE OR REPLACE FUNCTION prevent_locked_plan_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'LOCKED' AND NEW.status != OLD.status THEN
        RAISE EXCEPTION 'Cannot modify LOCKED plan_version %', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_locked_plan_modification_trigger
BEFORE UPDATE ON plan_versions
FOR EACH ROW
EXECUTE FUNCTION prevent_locked_plan_modification();

COMMENT ON FUNCTION prevent_locked_plan_modification() IS 'Enforce immutability of LOCKED plans';

-- Trigger 2: Prevent modifying assignments for LOCKED plans
CREATE OR REPLACE FUNCTION prevent_locked_assignments_modification()
RETURNS TRIGGER AS $$
DECLARE
    v_plan_status VARCHAR(20);
BEGIN
    -- Get plan status
    SELECT status INTO v_plan_status
    FROM plan_versions
    WHERE id = OLD.plan_version_id;

    IF v_plan_status = 'LOCKED' THEN
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'Cannot UPDATE assignment % - plan_version % is LOCKED', OLD.id, OLD.plan_version_id;
        ELSIF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Cannot DELETE assignment % - plan_version % is LOCKED', OLD.id, OLD.plan_version_id;
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_locked_assignments_modification_trigger
BEFORE UPDATE OR DELETE ON assignments
FOR EACH ROW
EXECUTE FUNCTION prevent_locked_assignments_modification();

COMMENT ON FUNCTION prevent_locked_assignments_modification() IS 'Prevent modifications to assignments for LOCKED plans';

-- Trigger 3: Make audit_log append-only (no UPDATE/DELETE)
CREATE OR REPLACE FUNCTION audit_log_append_only()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'audit_log is append-only: UPDATE not allowed on row %', OLD.id;
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit_log is append-only: DELETE not allowed on row %', OLD.id;
    END IF;
    RETURN NULL;  -- Never reached
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_append_only_trigger
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW
EXECUTE FUNCTION audit_log_append_only();

COMMENT ON FUNCTION audit_log_append_only() IS 'Enforce append-only (write-only) audit log';

-- ============================================================================
-- INITIALIZATION COMPLETE
-- ============================================================================

-- Insert default parser config version
INSERT INTO forecast_versions (source, input_hash, parser_config_hash, status, notes)
VALUES ('manual', 'initial', 'v3.0.0-mvp', 'PASS', 'Initial schema setup - placeholder forecast')
ON CONFLICT (input_hash) DO NOTHING;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ SOLVEREIGN V3 Database Schema Initialized Successfully';
    RAISE NOTICE '📊 Tables Created: forecast_versions, tours_raw, tours_normalized, plan_versions, assignments, audit_log, freeze_windows, diff_results';
    RAISE NOTICE '🔍 Views Created: latest_locked_plans, release_ready_plans';
    RAISE NOTICE '🛡️ Triggers Created:';
    RAISE NOTICE '   - prevent_locked_plan_modification (plan_versions immutability)';
    RAISE NOTICE '   - prevent_locked_assignments_modification (assignments for LOCKED plans)';
    RAISE NOTICE '   - audit_log_append_only (write-only audit log)';
    RAISE NOTICE '🚀 Ready for M2 Testing: docker-compose up -d postgres';
END $$;
