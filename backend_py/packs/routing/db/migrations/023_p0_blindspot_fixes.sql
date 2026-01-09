-- ============================================================
-- Migration 023: P0 Blindspot Fixes
-- ============================================================
-- Fixes identified in code review:
-- 1. SECURITY INVOKER + search_path on validation functions
-- 2. Missing composite indices for query performance
-- 3. Idempotent UPSERT support for teams_daily
-- 4. GIN index on combined_skills for array filtering
-- ============================================================

BEGIN;

-- ============================================================
-- 1. FIX: SECURITY INVOKER + search_path on validation functions
-- ============================================================
-- By default, plpgsql functions are SECURITY INVOKER, but we make it EXPLICIT.
-- Also set search_path to prevent search_path manipulation attacks.

-- Drop and recreate validate_team_availability with security settings
DROP FUNCTION IF EXISTS validate_team_availability(INTEGER, UUID, DATE, UUID, UUID);

CREATE FUNCTION validate_team_availability(
    p_tenant_id INTEGER,
    p_site_id UUID,
    p_plan_date DATE,
    p_driver_1_id UUID,
    p_driver_2_id UUID
) RETURNS TABLE (
    is_valid BOOLEAN,
    error_code VARCHAR(50),
    error_message TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER  -- EXPLICIT: Run with caller's permissions, respects RLS
SET search_path = public, pg_catalog  -- SECURITY: Prevent search_path attacks
AS $$
DECLARE
    v_d1_available BOOLEAN;
    v_d2_available BOOLEAN;
    v_d1_site UUID;
    v_d2_site UUID;
BEGIN
    -- Check driver 1 availability
    SELECT available, site_id INTO v_d1_available, v_d1_site
    FROM driver_availability_daily
    WHERE tenant_id = p_tenant_id
      AND driver_id = p_driver_1_id
      AND plan_date = p_plan_date;

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, 'DRIVER_1_NO_AVAILABILITY'::VARCHAR,
            'Driver 1 has no availability record for this date'::TEXT;
        RETURN;
    END IF;

    IF NOT v_d1_available THEN
        RETURN QUERY SELECT FALSE, 'DRIVER_1_NOT_AVAILABLE'::VARCHAR,
            'Driver 1 is not available on this date'::TEXT;
        RETURN;
    END IF;

    IF v_d1_site != p_site_id THEN
        RETURN QUERY SELECT FALSE, 'DRIVER_1_WRONG_SITE'::VARCHAR,
            'Driver 1 availability is for a different site'::TEXT;
        RETURN;
    END IF;

    -- Check driver 2 if present
    IF p_driver_2_id IS NOT NULL THEN
        SELECT available, site_id INTO v_d2_available, v_d2_site
        FROM driver_availability_daily
        WHERE tenant_id = p_tenant_id
          AND driver_id = p_driver_2_id
          AND plan_date = p_plan_date;

        IF NOT FOUND THEN
            RETURN QUERY SELECT FALSE, 'DRIVER_2_NO_AVAILABILITY'::VARCHAR,
                'Driver 2 has no availability record for this date'::TEXT;
            RETURN;
        END IF;

        IF NOT v_d2_available THEN
            RETURN QUERY SELECT FALSE, 'DRIVER_2_NOT_AVAILABLE'::VARCHAR,
                'Driver 2 is not available on this date'::TEXT;
            RETURN;
        END IF;

        IF v_d2_site != p_site_id THEN
            RETURN QUERY SELECT FALSE, 'DRIVER_2_WRONG_SITE'::VARCHAR,
                'Driver 2 availability is for a different site'::TEXT;
            RETURN;
        END IF;
    END IF;

    RETURN QUERY SELECT TRUE, NULL::VARCHAR, NULL::TEXT;
END;
$$;

-- Fix compute_team_combined_skills with security settings
DROP FUNCTION IF EXISTS compute_team_combined_skills(INTEGER, UUID, UUID);

CREATE FUNCTION compute_team_combined_skills(
    p_tenant_id INTEGER,
    p_driver_1_id UUID,
    p_driver_2_id UUID
) RETURNS TEXT[]
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_skills TEXT[];
BEGIN
    SELECT ARRAY_AGG(DISTINCT skill ORDER BY skill) INTO v_skills  -- ORDER BY for determinism!
    FROM driver_skills
    WHERE tenant_id = p_tenant_id
      AND driver_id IN (p_driver_1_id, p_driver_2_id);

    RETURN COALESCE(v_skills, '{}');
END;
$$;

-- Fix teams_daily_compute_skills trigger function
DROP FUNCTION IF EXISTS teams_daily_compute_skills() CASCADE;

CREATE FUNCTION teams_daily_compute_skills()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
BEGIN
    NEW.combined_skills := compute_team_combined_skills(
        NEW.tenant_id,
        NEW.driver_1_id,
        NEW.driver_2_id
    );
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

-- Recreate trigger
CREATE TRIGGER trg_teams_daily_compute_skills
    BEFORE INSERT OR UPDATE ON teams_daily
    FOR EACH ROW
    EXECUTE FUNCTION teams_daily_compute_skills();

-- ============================================================
-- 2. FIX: Additional Indices for Query Performance
-- ============================================================

-- Composite index for availability lookup (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_availability_lookup
    ON driver_availability_daily(tenant_id, driver_id, plan_date);

-- Already have UNIQUE which creates index, but add explicit for clarity
-- (tenant_id, site_id, plan_date) on teams_daily - already exists via idx_teams_daily_date

-- Add index for driver lookup with status (common in import validation)
CREATE INDEX IF NOT EXISTS idx_drivers_tenant_external
    ON drivers(tenant_id, external_id);

-- ============================================================
-- 3. FIX: GIN Index on combined_skills for Array Filtering
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_teams_daily_skills_gin
    ON teams_daily USING GIN (combined_skills);

CREATE INDEX IF NOT EXISTS idx_team_history_skills_gin
    ON team_history USING GIN (combined_skills);

-- ============================================================
-- 4. FIX: Idempotent UPSERT Function for Teams Import
-- ============================================================

CREATE OR REPLACE FUNCTION upsert_team_daily(
    p_tenant_id INTEGER,
    p_site_id UUID,
    p_plan_date DATE,
    p_driver_1_id UUID,
    p_driver_2_id UUID,
    p_team_size INTEGER,
    p_shift_start_at TIMESTAMPTZ,
    p_shift_end_at TIMESTAMPTZ,
    p_depot_id UUID,
    p_vehicle_id VARCHAR(100) DEFAULT NULL,
    p_capacity_volume_m3 DECIMAL(10,3) DEFAULT 20.0,
    p_capacity_weight_kg DECIMAL(10,2) DEFAULT 1000.0,
    p_created_by VARCHAR(50) DEFAULT 'IMPORT'
) RETURNS UUID
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_team_id UUID;
BEGIN
    -- Upsert: Insert or update existing team
    INSERT INTO teams_daily (
        tenant_id, site_id, plan_date,
        driver_1_id, driver_2_id, team_size,
        shift_start_at, shift_end_at,
        depot_id, vehicle_id,
        capacity_volume_m3, capacity_weight_kg,
        is_active, created_by
    ) VALUES (
        p_tenant_id, p_site_id, p_plan_date,
        p_driver_1_id, p_driver_2_id, p_team_size,
        p_shift_start_at, p_shift_end_at,
        p_depot_id, p_vehicle_id,
        p_capacity_volume_m3, p_capacity_weight_kg,
        TRUE, p_created_by
    )
    ON CONFLICT (tenant_id, site_id, plan_date, driver_1_id, driver_2_id)
    DO UPDATE SET
        team_size = EXCLUDED.team_size,
        shift_start_at = EXCLUDED.shift_start_at,
        shift_end_at = EXCLUDED.shift_end_at,
        depot_id = EXCLUDED.depot_id,
        vehicle_id = EXCLUDED.vehicle_id,
        capacity_volume_m3 = EXCLUDED.capacity_volume_m3,
        capacity_weight_kg = EXCLUDED.capacity_weight_kg,
        is_active = TRUE,  -- Reactivate if was deactivated
        updated_at = NOW()
    RETURNING id INTO v_team_id;

    RETURN v_team_id;
END;
$$;

-- ============================================================
-- 5. FIX: Function to deactivate old teams (for import overwrite)
-- ============================================================

CREATE OR REPLACE FUNCTION deactivate_teams_for_date(
    p_tenant_id INTEGER,
    p_site_id UUID,
    p_plan_date DATE
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE teams_daily
    SET is_active = FALSE, updated_at = NOW()
    WHERE tenant_id = p_tenant_id
      AND site_id = p_site_id
      AND plan_date = p_plan_date
      AND is_active = TRUE;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- ============================================================
-- 6. FIX: Ensure driver_availability has proper unique constraint
-- ============================================================

-- The UNIQUE constraint already exists, but let's add a named one for clarity
-- ALTER TABLE driver_availability_daily
--     DROP CONSTRAINT IF EXISTS driver_availability_daily_tenant_id_driver_id_plan_date_key;
-- (Skip if already exists from migration 022)

-- ============================================================
-- 7. RECORD MIGRATION
-- ============================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('023', 'P0 blindspot fixes: security invoker, indices, upsert', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
