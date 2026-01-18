-- ============================================================================
-- MIGRATION 000a: Bootstrap Fixes for Dependency Chain
-- ============================================================================
-- PURPOSE: Fix migration ordering issues that prevent fresh-db-proof from
-- running on an empty database.
--
-- BUGS FIXED:
--   1. audit_log table missing (expected by 004, 010)
--      - 000_initial_schema creates "audit_logs" (plural)
--      - 004_triggers_and_statuses expects "audit_log" (singular)
--      - 010_security_layer tries to enable RLS on "audit_log"
--
--   2. Roles created too late (expected by 039)
--      - solvereign_admin created in 010 but 010 fails before that
--      - 039_internal_rbac needs solvereign_admin for GRANT statements
--
--   3. schema_migrations.version too small (expected by 012+)
--      - 006_multi_tenant creates version as VARCHAR(20)
--      - 012_tenant_identities uses longer version strings
--
-- DESIGN:
--   - Fully idempotent (safe on already-migrated DBs)
--   - Uses IF NOT EXISTS, DO blocks with exception handlers
--   - Creates missing objects early in migration order
--
-- RUN ORDER: Runs after 000, before 001 (alphabetical: 000a)
-- ============================================================================

-- ============================================================================
-- 1. EARLY ROLE CREATION (needed by 010, 025+, 039)
-- ============================================================================
-- Create all solvereign roles early so later migrations can reference them.
-- Uses DO blocks with IF NOT EXISTS pattern for idempotency.

DO $$
BEGIN
    -- solvereign_api: Runtime API role (no BYPASSRLS)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        CREATE ROLE solvereign_api NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
        RAISE NOTICE 'Bootstrap: Created role solvereign_api';
    END IF;

    -- solvereign_admin: Migration/admin role (with BYPASSRLS for migrations)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        CREATE ROLE solvereign_admin NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
        RAISE NOTICE 'Bootstrap: Created role solvereign_admin';
    END IF;

    -- solvereign_definer: SECURITY DEFINER function owner (no BYPASSRLS)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        CREATE ROLE solvereign_definer NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
        RAISE NOTICE 'Bootstrap: Created role solvereign_definer';
    END IF;

    -- solvereign_platform: Platform admin operations (no BYPASSRLS)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        CREATE ROLE solvereign_platform NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
        RAISE NOTICE 'Bootstrap: Created role solvereign_platform';
    END IF;
END $$;

-- ============================================================================
-- 2. AUDIT_LOG TABLE (singular - expected by 004, 010)
-- ============================================================================
-- The original 000_initial_schema creates "audit_logs" (plural) with
-- "violation_count" column. But 004 expects "audit_log" (singular) with
-- "count" column. This creates the expected table structure.
--
-- NOTE: 000_initial_schema may create audit_log as a VIEW pointing to audit_logs
-- when upgrading from init.sql. We need to handle both cases.

DO $$
BEGIN
    -- Check if audit_log exists as a VIEW (created by 000 upgrade path)
    IF EXISTS (
        SELECT 1 FROM information_schema.views WHERE table_name = 'audit_log'
    ) THEN
        RAISE NOTICE 'Bootstrap: audit_log exists as VIEW (pointing to audit_logs) - skipping table creation';
    -- Check if audit_log exists as a TABLE
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log' AND table_type = 'BASE TABLE'
    ) THEN
        RAISE NOTICE 'Bootstrap: audit_log table already exists - skipping creation';
    ELSE
        -- Neither exists, create the table
        CREATE TABLE audit_log (
            id              SERIAL PRIMARY KEY,
            plan_version_id INTEGER,  -- FK added after plan_versions exists
            check_name      VARCHAR(100) NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'PASS',
            count           INTEGER DEFAULT 0,  -- 004 expects "count", not "violation_count"
            details_json    JSONB,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW()
        );
        RAISE NOTICE 'Bootstrap: Created audit_log table';
    END IF;
END $$;

-- Add FK if plan_versions exists and audit_log is a table (not view)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'plan_versions')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log' AND table_type = 'BASE TABLE')
    THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'audit_log_plan_version_id_fkey'
        ) THEN
            ALTER TABLE audit_log ADD CONSTRAINT audit_log_plan_version_id_fkey
                FOREIGN KEY (plan_version_id) REFERENCES plan_versions(id) ON DELETE CASCADE;
            RAISE NOTICE 'Bootstrap: Added FK to audit_log';
        END IF;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Bootstrap: FK creation skipped (plan_versions may not exist yet)';
END $$;

-- Indexes - only create if audit_log is a TABLE (not a VIEW)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log' AND table_type = 'BASE TABLE') THEN
        CREATE INDEX IF NOT EXISTS idx_audit_log_plan ON audit_log(plan_version_id);
        CREATE INDEX IF NOT EXISTS idx_audit_log_check ON audit_log(check_name);
        RAISE NOTICE 'Bootstrap: Created indexes on audit_log';
    ELSE
        RAISE NOTICE 'Bootstrap: Skipping indexes (audit_log is a view or does not exist)';
    END IF;
END $$;

-- Comment - only if audit_log is a table
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log' AND table_type = 'BASE TABLE') THEN
        COMMENT ON TABLE audit_log IS 'Audit check results (bootstrap table for migration chain fix)';
    END IF;
END $$;

-- ============================================================================
-- 3. BASIC GRANTS FOR EARLY MIGRATIONS
-- ============================================================================
-- Grant usage on public schema to roles created above.
-- This is needed before 010 runs so role references work.

DO $$
BEGIN
    -- Grant USAGE on public schema
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT USAGE ON SCHEMA public TO solvereign_api;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        GRANT USAGE ON SCHEMA public TO solvereign_admin;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        GRANT USAGE ON SCHEMA public TO solvereign_definer;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT USAGE ON SCHEMA public TO solvereign_platform;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Bootstrap: Some grants skipped: %', SQLERRM;
END $$;

-- ============================================================================
-- 4. SCHEMA_MIGRATIONS TABLE (create early with larger version column)
-- ============================================================================
-- 006_multi_tenant.sql creates schema_migrations with version VARCHAR(20)
-- but some migrations use longer version strings like '012_tenant_identities'.
-- Create the table here with VARCHAR(50) to prevent truncation errors.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(50) PRIMARY KEY,  -- Larger than 006's VARCHAR(20)
    description TEXT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Also fix existing table if it has wrong column size
DO $$
BEGIN
    -- Check if column is too small
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'schema_migrations'
          AND column_name = 'version'
          AND character_maximum_length < 50
    ) THEN
        ALTER TABLE schema_migrations ALTER COLUMN version TYPE VARCHAR(50);
        RAISE NOTICE 'Bootstrap: Enlarged schema_migrations.version to VARCHAR(50)';
    END IF;
END $$;

-- ============================================================================
-- 5. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('000a', 'Bootstrap fixes: roles + audit_log + schema_migrations', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 6. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 000a: Bootstrap Fixes COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Created roles: solvereign_api, solvereign_admin, solvereign_definer, solvereign_platform';
    RAISE NOTICE 'Created table: audit_log (singular, with count column)';
    RAISE NOTICE 'Created table: schema_migrations (with VARCHAR(50) version column)';
    RAISE NOTICE 'Granted: USAGE ON SCHEMA public to all roles';
    RAISE NOTICE '';
    RAISE NOTICE 'Migration chain dependencies now satisfied:';
    RAISE NOTICE '  - 004 can ALTER TABLE audit_log';
    RAISE NOTICE '  - 010 can ENABLE RLS on audit_log';
    RAISE NOTICE '  - 012 can INSERT long version strings';
    RAISE NOTICE '  - 039 can GRANT to solvereign_admin';
    RAISE NOTICE '============================================================';
END $$;
