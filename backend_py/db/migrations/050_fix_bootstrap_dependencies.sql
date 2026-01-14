-- ============================================================================
-- MIGRATION 050: Fix Bootstrap Dependencies (Forward-Only)
-- ============================================================================
--
-- SOLVEREIGN V4.5.2 - Market-Ready Forward Migration
--
-- Purpose:
--   Fixes dependency drift issues discovered during clean-install testing.
--   This migration is FORWARD-ONLY - no history rewriting required.
--
-- Issues Fixed:
--   1. auth.sessions.tenant_id NOT NULL blocks platform_admin sessions
--   2. auth.user_bindings.tenant_id NOT NULL blocks platform_admin bindings
--   3. Sites table may be missing if 006_multi_tenant ran before 002_sites_table
--
-- This migration is IDEMPOTENT - safe to run multiple times.
--
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. ENSURE TENANTS TABLE EXISTS WITH REQUIRED COLUMNS
-- ============================================================================
-- The tenants table should exist from 002_sites_table.sql or 006_multi_tenant.sql
-- Add any missing columns idempotently

DO $$
BEGIN
    -- Ensure api_key_hash column exists (may be missing in minimal bootstrap)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'tenants'
        AND column_name = 'api_key_hash'
    ) THEN
        ALTER TABLE tenants ADD COLUMN api_key_hash VARCHAR(64);
        RAISE NOTICE '[050] Added api_key_hash column to tenants';
    END IF;
END $$;

-- ============================================================================
-- 2. ENSURE SITES TABLE EXISTS
-- ============================================================================
-- Sites table should exist from 002_sites_table.sql
-- Create if missing (for environments where migration order was incorrect)

CREATE TABLE IF NOT EXISTS sites (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    code            VARCHAR(50) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB
);

-- Add indexes if missing
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_sites_tenant_id') THEN
        CREATE INDEX idx_sites_tenant_id ON sites(tenant_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_sites_code') THEN
        CREATE INDEX idx_sites_code ON sites(code);
    END IF;
END $$;

-- Add unique constraint if missing
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sites_tenant_code_unique') THEN
        ALTER TABLE sites ADD CONSTRAINT sites_tenant_code_unique UNIQUE (tenant_id, code);
    END IF;
END $$;

-- ============================================================================
-- 3. ALLOW NULL tenant_id FOR PLATFORM ADMIN SESSIONS
-- ============================================================================
-- Platform admins have is_platform_scope=TRUE and tenant_id=NULL
-- Regular users have is_platform_scope=FALSE and tenant_id NOT NULL

DO $$
BEGIN
    -- Check if tenant_id is currently NOT NULL
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'sessions'
        AND column_name = 'tenant_id' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE auth.sessions ALTER COLUMN tenant_id DROP NOT NULL;
        RAISE NOTICE '[050] Made auth.sessions.tenant_id nullable for platform_admin';
    END IF;
END $$;

-- ============================================================================
-- 4. ALLOW NULL tenant_id FOR PLATFORM ADMIN BINDINGS
-- ============================================================================
-- Platform admin bindings can have tenant_id=NULL for platform-wide access

DO $$
BEGIN
    -- Check if tenant_id is currently NOT NULL
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'user_bindings'
        AND column_name = 'tenant_id' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE auth.user_bindings ALTER COLUMN tenant_id DROP NOT NULL;
        RAISE NOTICE '[050] Made auth.user_bindings.tenant_id nullable for platform_admin';
    END IF;
END $$;

-- ============================================================================
-- 5. ADD CHECK CONSTRAINT FOR TENANT_ID CONSISTENCY
-- ============================================================================
-- Ensure: platform_scope=TRUE implies tenant_id can be NULL
--         platform_scope=FALSE requires tenant_id NOT NULL

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sessions_platform_tenant_check'
    ) THEN
        -- Add constraint: non-platform sessions MUST have tenant_id
        ALTER TABLE auth.sessions ADD CONSTRAINT sessions_platform_tenant_check
            CHECK (is_platform_scope = TRUE OR tenant_id IS NOT NULL);
        RAISE NOTICE '[050] Added sessions_platform_tenant_check constraint';
    END IF;
EXCEPTION WHEN duplicate_object THEN
    NULL; -- Constraint already exists
END $$;

-- ============================================================================
-- 6. VERIFICATION FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION public.verify_bootstrap_dependencies()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: tenants table exists
    RETURN QUERY
    SELECT 'tenants_table_exists'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'tenants'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'tenants table exists in public schema'::TEXT;

    -- Check 2: sites table exists
    RETURN QUERY
    SELECT 'sites_table_exists'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'sites'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'sites table exists in public schema'::TEXT;

    -- Check 3: sites.tenant_id FK exists
    RETURN QUERY
    SELECT 'sites_tenant_fk'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.table_constraints
               WHERE table_schema = 'public' AND table_name = 'sites'
               AND constraint_type = 'FOREIGN KEY'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'sites.tenant_id FK constraint exists'::TEXT;

    -- Check 4: auth.sessions.tenant_id is nullable
    RETURN QUERY
    SELECT 'sessions_tenant_nullable'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'sessions'
               AND column_name = 'tenant_id' AND is_nullable = 'YES'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'auth.sessions.tenant_id allows NULL for platform_admin'::TEXT;

    -- Check 5: auth.user_bindings.tenant_id is nullable
    RETURN QUERY
    SELECT 'bindings_tenant_nullable'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'auth' AND table_name = 'user_bindings'
               AND column_name = 'tenant_id' AND is_nullable = 'YES'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'auth.user_bindings.tenant_id allows NULL for platform_admin'::TEXT;

    -- Check 6: Platform tenant check constraint exists
    RETURN QUERY
    SELECT 'platform_tenant_constraint'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM pg_constraint
               WHERE conname = 'sessions_platform_tenant_check'
           ) THEN 'PASS' ELSE 'WARN' END::TEXT,
           'sessions_platform_tenant_check constraint enforces consistency'::TEXT;

END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION public.verify_bootstrap_dependencies() TO solvereign_api;
GRANT EXECUTE ON FUNCTION public.verify_bootstrap_dependencies() TO solvereign_platform;

COMMIT;

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '[050_fix_bootstrap_dependencies] Forward-only fixes applied successfully';
    RAISE NOTICE '  - tenants/sites tables verified';
    RAISE NOTICE '  - auth.sessions.tenant_id now nullable for platform_admin';
    RAISE NOTICE '  - auth.user_bindings.tenant_id now nullable for platform_admin';
    RAISE NOTICE '  - Consistency constraint added';
END $$;

-- ============================================================================
-- VERIFICATION
-- ============================================================================
-- Run after migration:
-- SELECT * FROM verify_bootstrap_dependencies();
-- Expected: All checks PASS
