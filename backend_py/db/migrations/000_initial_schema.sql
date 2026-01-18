-- ============================================================================
-- MIGRATION 000: Initial Schema (Base Tables)
-- ============================================================================
-- Purpose: Create base tables required by all subsequent migrations.
--          This extracts the essential tables from init.sql that MUST exist
--          before migration 001 can run.
--
-- IDEMPOTENT: Safe to run multiple times (uses IF NOT EXISTS)
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- 1. TENANTS (Required for multi-tenant RLS)
-- ============================================================================
CREATE TABLE IF NOT EXISTS tenants (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    api_key_hash    VARCHAR(128),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_name ON tenants(name);
CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE tenants IS 'Multi-tenant isolation - each tenant has isolated data';

-- ============================================================================
-- 2. FORECAST VERSIONS (Core table for forecast management)
-- ============================================================================
CREATE TABLE IF NOT EXISTS forecast_versions (
    id                  SERIAL PRIMARY KEY,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    source              VARCHAR(50) NOT NULL CHECK (source IN ('slack', 'csv', 'manual', 'rls_harness_test', 'test')),
    input_hash          VARCHAR(64) NOT NULL,
    parser_config_hash  VARCHAR(64) NOT NULL,
    status              VARCHAR(10) NOT NULL CHECK (status IN ('PASS', 'WARN', 'FAIL', 'PARSED')),
    week_key            VARCHAR(20),
    week_anchor_date    DATE,
    notes               TEXT,
    tenant_id           INTEGER REFERENCES tenants(id),
    CONSTRAINT forecast_versions_unique_hash UNIQUE (input_hash)
);

-- Add tenant_id if upgrading from init.sql (column may not exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forecast_versions' AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE forecast_versions ADD COLUMN tenant_id INTEGER REFERENCES tenants(id);
        RAISE NOTICE '[000] Added tenant_id column to forecast_versions (upgrade path)';
    END IF;
END $$;

-- Update source constraint if upgrading from init.sql (old constraint has fewer values)
DO $$
BEGIN
    -- Drop old constraint if it exists with fewer values
    IF EXISTS (
        SELECT 1 FROM information_schema.constraint_column_usage
        WHERE table_name = 'forecast_versions' AND constraint_name = 'forecast_versions_source_check'
    ) THEN
        ALTER TABLE forecast_versions DROP CONSTRAINT IF EXISTS forecast_versions_source_check;
        ALTER TABLE forecast_versions ADD CONSTRAINT forecast_versions_source_check
            CHECK (source IN ('slack', 'csv', 'manual', 'rls_harness_test', 'test'));
        RAISE NOTICE '[000] Updated forecast_versions source constraint (upgrade path)';
    END IF;
EXCEPTION WHEN OTHERS THEN
    -- Constraint may already be correct, ignore
    NULL;
END $$;

-- Update status constraint if upgrading from init.sql (old constraint missing PARSED)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.constraint_column_usage
        WHERE table_name = 'forecast_versions' AND constraint_name = 'forecast_versions_status_check'
    ) THEN
        ALTER TABLE forecast_versions DROP CONSTRAINT IF EXISTS forecast_versions_status_check;
        ALTER TABLE forecast_versions ADD CONSTRAINT forecast_versions_status_check
            CHECK (status IN ('PASS', 'WARN', 'FAIL', 'PARSED'));
        RAISE NOTICE '[000] Updated forecast_versions status constraint (upgrade path)';
    END IF;
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_forecast_versions_created_at ON forecast_versions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_forecast_versions_status ON forecast_versions(status);

-- Create index only if tenant_id column exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forecast_versions' AND column_name = 'tenant_id'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_forecast_versions_tenant ON forecast_versions(tenant_id);
    END IF;
END $$;

COMMENT ON TABLE forecast_versions IS 'Master table for input forecast versions with validation status';
COMMENT ON COLUMN forecast_versions.input_hash IS 'SHA256 hash of canonicalized input for deduplication';
COMMENT ON COLUMN forecast_versions.status IS 'PASS = proceed, WARN = review recommended, FAIL = blocks solver';

-- ============================================================================
-- 3. TOURS RAW (Raw input lines)
-- ============================================================================
CREATE TABLE IF NOT EXISTS tours_raw (
    id                  SERIAL PRIMARY KEY,
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    line_no             INTEGER NOT NULL,
    raw_text            TEXT NOT NULL,
    parse_status        VARCHAR(10) NOT NULL CHECK (parse_status IN ('PASS', 'WARN', 'FAIL')),
    parse_errors        JSONB,
    parse_warnings      JSONB,
    canonical_text      TEXT,
    CONSTRAINT tours_raw_unique_line UNIQUE (forecast_version_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_tours_raw_forecast_version ON tours_raw(forecast_version_id);

COMMENT ON TABLE tours_raw IS 'Unparsed input lines with validation results';

-- ============================================================================
-- 4. TOURS NORMALIZED (Canonical tour representation)
-- ============================================================================
CREATE TABLE IF NOT EXISTS tours_normalized (
    id                  SERIAL PRIMARY KEY,
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    day                 INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),
    start_ts            TIME NOT NULL,
    end_ts              TIME NOT NULL,
    duration_min        INTEGER NOT NULL CHECK (duration_min > 0),
    work_hours          DECIMAL(5,2) NOT NULL CHECK (work_hours > 0),
    span_group_key      VARCHAR(50),
    tour_fingerprint    VARCHAR(64) NOT NULL,
    count               INTEGER NOT NULL DEFAULT 1 CHECK (count > 0),
    depot               VARCHAR(50),
    skill               VARCHAR(50),
    metadata            JSONB,
    CONSTRAINT tours_normalized_unique_tour UNIQUE (forecast_version_id, tour_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_tours_normalized_forecast_version ON tours_normalized(forecast_version_id);
CREATE INDEX IF NOT EXISTS idx_tours_normalized_fingerprint ON tours_normalized(tour_fingerprint);
CREATE INDEX IF NOT EXISTS idx_tours_normalized_day ON tours_normalized(day);

COMMENT ON TABLE tours_normalized IS 'Canonical tour representation for solver input';

-- ============================================================================
-- 5. PLAN VERSIONS (Solver output management)
-- ============================================================================
CREATE TABLE IF NOT EXISTS plan_versions (
    id                  SERIAL PRIMARY KEY,
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    status              VARCHAR(20) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'PENDING', 'APPROVED', 'LOCKED', 'REJECTED')),
    seed                INTEGER,
    solver_config_hash  VARCHAR(64),
    output_hash         VARCHAR(64),
    locked_at           TIMESTAMP,
    locked_by           VARCHAR(100),
    notes               TEXT,
    tenant_id           INTEGER REFERENCES tenants(id),
    CONSTRAINT plan_versions_unique_output UNIQUE (forecast_version_id, output_hash)
);

-- Add tenant_id if upgrading from init.sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN tenant_id INTEGER REFERENCES tenants(id);
        RAISE NOTICE '[000] Added tenant_id column to plan_versions (upgrade path)';
    END IF;
END $$;

-- Update status constraint if upgrading from init.sql (different status values)
DO $$
BEGIN
    ALTER TABLE plan_versions DROP CONSTRAINT IF EXISTS plan_versions_status_check;
    ALTER TABLE plan_versions ADD CONSTRAINT plan_versions_status_check
        CHECK (status IN ('DRAFT', 'PENDING', 'APPROVED', 'LOCKED', 'REJECTED', 'SOLVING', 'FAILED', 'SUPERSEDED'));
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;

-- Drop old lock integrity constraint from init.sql (incompatible)
ALTER TABLE plan_versions DROP CONSTRAINT IF EXISTS plan_versions_lock_integrity;

CREATE INDEX IF NOT EXISTS idx_plan_versions_forecast ON plan_versions(forecast_version_id);
CREATE INDEX IF NOT EXISTS idx_plan_versions_status ON plan_versions(status);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'tenant_id'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_plan_versions_tenant ON plan_versions(tenant_id);
    END IF;
END $$;

COMMENT ON TABLE plan_versions IS 'Solver output versions with approval workflow';

-- ============================================================================
-- 6. ASSIGNMENTS (Driver to tour mapping)
-- ============================================================================
CREATE TABLE IF NOT EXISTS assignments (
    id                  SERIAL PRIMARY KEY,
    plan_version_id     INTEGER NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
    driver_id           VARCHAR(50) NOT NULL,
    tour_instance_id    INTEGER,
    day                 INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),
    block_id            VARCHAR(50),
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Add tour_instance_id if upgrading from init.sql (has tour_id instead)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'assignments' AND column_name = 'tour_instance_id'
    ) THEN
        ALTER TABLE assignments ADD COLUMN tour_instance_id INTEGER;
        RAISE NOTICE '[000] Added tour_instance_id column to assignments (upgrade path)';
    END IF;

    -- Add created_at if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'assignments' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE assignments ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT NOW();
        RAISE NOTICE '[000] Added created_at column to assignments (upgrade path)';
    END IF;

    -- Make block_id nullable (init.sql has it as NOT NULL)
    ALTER TABLE assignments ALTER COLUMN block_id DROP NOT NULL;
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_assignments_plan ON assignments(plan_version_id);
CREATE INDEX IF NOT EXISTS idx_assignments_driver ON assignments(driver_id);
CREATE INDEX IF NOT EXISTS idx_assignments_day ON assignments(day);

COMMENT ON TABLE assignments IS 'Driver to tour instance assignments';

-- ============================================================================
-- 7. AUDIT LOGS (Plan audit trail)
-- ============================================================================
-- NOTE: init.sql uses "audit_log" (singular), migrations use "audit_logs" (plural)
-- We create both for compatibility. audit_logs is the canonical table.

-- Create audit_logs (canonical name for migrations)
CREATE TABLE IF NOT EXISTS audit_logs (
    id                  SERIAL PRIMARY KEY,
    plan_version_id     INTEGER REFERENCES plan_versions(id) ON DELETE CASCADE,
    check_name          VARCHAR(100) NOT NULL,
    status              VARCHAR(10) NOT NULL CHECK (status IN ('PASS', 'WARN', 'FAIL')),
    violation_count     INTEGER DEFAULT 0,
    details_json        JSONB,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Handle upgrade from init.sql which creates audit_log (singular)
-- IMPORTANT: Do NOT create audit_log as a VIEW because later migrations
-- (001_tour_instances.sql) need to create triggers on it, and views cannot have triggers.
DO $$
BEGIN
    -- If audit_log table exists but audit_logs doesn't, rename audit_log → audit_logs
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'audit_log' AND table_type = 'BASE TABLE'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'audit_logs' AND table_type = 'BASE TABLE'
    ) THEN
        ALTER TABLE audit_log RENAME TO audit_logs;
        RAISE NOTICE '[000] Renamed audit_log to audit_logs (upgrade path)';
    -- If both tables exist, just drop the older audit_log table
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'audit_log' AND table_type = 'BASE TABLE'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'audit_logs' AND table_type = 'BASE TABLE'
    ) THEN
        -- Drop triggers on audit_log first (if any)
        DROP TRIGGER IF EXISTS audit_log_append_only_trigger ON audit_log;
        DROP TABLE audit_log CASCADE;
        RAISE NOTICE '[000] Dropped duplicate audit_log table (upgrade path)';
    END IF;
    -- For greenfield: audit_logs created above, 000a will create audit_log table
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE '[000] audit_log handling: %', SQLERRM;
END $$;

-- Update status constraint to include OVERRIDE from init.sql
DO $$
BEGIN
    ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_status_check;
    ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_status_check
        CHECK (status IN ('PASS', 'WARN', 'FAIL', 'OVERRIDE'));
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_audit_logs_plan ON audit_logs(plan_version_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_check ON audit_logs(check_name);

COMMENT ON TABLE audit_logs IS 'Audit check results for plan versions';

-- ============================================================================
-- 8. DIFF RESULTS (Version comparison)
-- ============================================================================
-- NOTE: init.sql has different columns (diff_type, tour_fingerprint, old_values, etc.)
-- Migration schema is simpler (diff_hash, summary_json). We need to handle both.

CREATE TABLE IF NOT EXISTS diff_results (
    id                    SERIAL PRIMARY KEY,
    forecast_version_old  INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    forecast_version_new  INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    diff_hash             VARCHAR(64) NOT NULL,
    summary_json          JSONB NOT NULL,
    CONSTRAINT diff_results_unique UNIQUE (forecast_version_old, forecast_version_new)
);

-- Handle upgrade from init.sql which has different schema
DO $$
BEGIN
    -- Add diff_hash column if missing (init.sql doesn't have it)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'diff_results' AND column_name = 'diff_hash'
    ) THEN
        ALTER TABLE diff_results ADD COLUMN diff_hash VARCHAR(64) NOT NULL DEFAULT '';
        RAISE NOTICE '[000] Added diff_hash column to diff_results (upgrade path)';
    END IF;

    -- Add summary_json column if missing (init.sql doesn't have it)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'diff_results' AND column_name = 'summary_json'
    ) THEN
        ALTER TABLE diff_results ADD COLUMN summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
        RAISE NOTICE '[000] Added summary_json column to diff_results (upgrade path)';
    END IF;

    -- Drop old unique constraint from init.sql (different columns)
    ALTER TABLE diff_results DROP CONSTRAINT IF EXISTS diff_results_unique_diff;

    -- Ensure new unique constraint exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'diff_results' AND constraint_name = 'diff_results_unique'
    ) THEN
        -- Only add if no duplicate rows exist
        ALTER TABLE diff_results ADD CONSTRAINT diff_results_unique
            UNIQUE (forecast_version_old, forecast_version_new);
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE '[000] diff_results upgrade: %', SQLERRM;
END $$;

CREATE INDEX IF NOT EXISTS idx_diff_results_old ON diff_results(forecast_version_old);
CREATE INDEX IF NOT EXISTS idx_diff_results_new ON diff_results(forecast_version_new);

COMMENT ON TABLE diff_results IS 'Cached diff results between forecast versions';

-- ============================================================================
-- 9. CORE SCHEMA (For escalation drill and service status)
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.service_status (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(100) NOT NULL,
    scope_type      VARCHAR(50) NOT NULL,
    scope_id        UUID,
    severity        VARCHAR(10) CHECK (severity IN ('S0', 'S1', 'S2', 'S3')),
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'acknowledged')),
    context         JSONB,
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMP,
    resolution      TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_service_status_event ON core.service_status(event_type);
CREATE INDEX IF NOT EXISTS idx_service_status_status ON core.service_status(status);
CREATE INDEX IF NOT EXISTS idx_service_status_severity ON core.service_status(severity);

COMMENT ON TABLE core.service_status IS 'Service status and escalation tracking';

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
-- NOTE: Subsequent migrations (001+) can now safely reference these tables.
-- ============================================================================
