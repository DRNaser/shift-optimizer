-- ============================================================
-- Migration 022: Driver Pool + Teams Daily + Scenario Snapshot
-- ============================================================
-- SOLVEREIGN Routing Pack V1
--
-- This migration creates the driver/team infrastructure:
-- A) drivers - Driver master data (pool)
-- B) driver_skills - Skills per driver (M:N)
-- C) driver_availability_daily - Daily availability + shift times
-- D) teams_daily - Pre-formed teams for a given day
-- E) team_history - Historical pairings for V2 stability
--
-- Key Principle:
-- - Driver Pool + daily availability is Source-of-Truth
-- - teams_daily represents dispatcher's team assignments for a day
-- - Scenario creation snapshots teams_daily → routing_vehicles (immutable)
-- ============================================================

BEGIN;

-- ============================================================
-- A) DRIVERS - Master Data Pool
-- ============================================================
CREATE TABLE IF NOT EXISTS drivers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    site_id UUID NOT NULL REFERENCES routing_depots(id),

    -- External reference (from HR/dispatch system)
    external_id VARCHAR(100) NOT NULL,

    -- Basic info (name optional for privacy)
    name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'INACTIVE', 'ON_LEAVE', 'TERMINATED')),

    -- Employment type (for capacity planning)
    employment_type VARCHAR(20) DEFAULT 'FULL_TIME'
        CHECK (employment_type IN ('FULL_TIME', 'PART_TIME', 'CONTRACTOR')),

    -- Default shift (can be overridden in availability)
    default_shift_start TIME DEFAULT '06:00',
    default_shift_end TIME DEFAULT '18:00',

    -- Capacity
    max_weekly_hours DECIMAL(4,1) DEFAULT 55.0,
    max_daily_hours DECIMAL(4,1) DEFAULT 10.0,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(tenant_id, external_id)
);

-- Indices
CREATE INDEX idx_drivers_tenant ON drivers(tenant_id);
CREATE INDEX idx_drivers_site ON drivers(site_id);
CREATE INDEX idx_drivers_tenant_site ON drivers(tenant_id, site_id);
CREATE INDEX idx_drivers_status ON drivers(tenant_id, status) WHERE status = 'ACTIVE';

-- RLS
ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;

CREATE POLICY drivers_tenant_isolation ON drivers
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::INTEGER);

-- ============================================================
-- B) DRIVER_SKILLS - Skills per Driver (M:N)
-- ============================================================
CREATE TABLE IF NOT EXISTS driver_skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    driver_id UUID NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,

    -- Skill identifier (matches job requirements)
    skill VARCHAR(100) NOT NULL,

    -- Certification info (optional)
    certified_at DATE,
    expires_at DATE,
    certification_number VARCHAR(100),

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(tenant_id, driver_id, skill)
);

-- Indices
CREATE INDEX idx_driver_skills_tenant ON driver_skills(tenant_id);
CREATE INDEX idx_driver_skills_driver ON driver_skills(driver_id);
CREATE INDEX idx_driver_skills_skill ON driver_skills(tenant_id, skill);

-- RLS
ALTER TABLE driver_skills ENABLE ROW LEVEL SECURITY;

CREATE POLICY driver_skills_tenant_isolation ON driver_skills
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::INTEGER);

-- ============================================================
-- C) DRIVER_AVAILABILITY_DAILY - Daily Availability + Shift
-- ============================================================
CREATE TABLE IF NOT EXISTS driver_availability_daily (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    driver_id UUID NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    site_id UUID NOT NULL REFERENCES routing_depots(id),

    -- Date
    plan_date DATE NOT NULL,

    -- Availability
    available BOOLEAN NOT NULL DEFAULT TRUE,
    unavailable_reason VARCHAR(100),  -- 'SICK', 'VACATION', 'TRAINING', etc.

    -- Shift times for this specific day (TIMESTAMPTZ for DST safety)
    shift_start_at TIMESTAMPTZ NOT NULL,
    shift_end_at TIMESTAMPTZ NOT NULL,

    -- Break info (optional)
    break_start_at TIMESTAMPTZ,
    break_end_at TIMESTAMPTZ,

    -- Source
    source VARCHAR(50) DEFAULT 'MANUAL',  -- 'MANUAL', 'IMPORT', 'HR_SYNC'

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(tenant_id, driver_id, plan_date),
    CONSTRAINT valid_shift CHECK (shift_end_at > shift_start_at)
);

-- Indices
CREATE INDEX idx_availability_tenant ON driver_availability_daily(tenant_id);
CREATE INDEX idx_availability_driver ON driver_availability_daily(driver_id);
CREATE INDEX idx_availability_date ON driver_availability_daily(tenant_id, site_id, plan_date);
CREATE INDEX idx_availability_available ON driver_availability_daily(tenant_id, site_id, plan_date, available)
    WHERE available = TRUE;

-- RLS
ALTER TABLE driver_availability_daily ENABLE ROW LEVEL SECURITY;

CREATE POLICY availability_tenant_isolation ON driver_availability_daily
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::INTEGER);

-- ============================================================
-- D) TEAMS_DAILY - Pre-formed Teams for a Given Day
-- ============================================================
-- This is the dispatcher's team assignment for a specific day.
-- Teams are snapshotted into routing_vehicles when a scenario is created.

CREATE TABLE IF NOT EXISTS teams_daily (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    site_id UUID NOT NULL REFERENCES routing_depots(id),

    -- Date
    plan_date DATE NOT NULL,

    -- Team members (driver_2_id NULL for solo teams)
    driver_1_id UUID NOT NULL REFERENCES drivers(id),
    driver_2_id UUID REFERENCES drivers(id),

    -- Derived/cached fields
    team_size INTEGER NOT NULL DEFAULT 1 CHECK (team_size IN (1, 2)),
    combined_skills TEXT[] NOT NULL DEFAULT '{}',

    -- Shift (computed from intersection of member availability)
    shift_start_at TIMESTAMPTZ NOT NULL,
    shift_end_at TIMESTAMPTZ NOT NULL,

    -- Depot assignment
    depot_id UUID NOT NULL REFERENCES routing_depots(id),

    -- Optional vehicle assignment (for tracking)
    vehicle_id VARCHAR(100),
    vehicle_plate VARCHAR(20),

    -- Capacity (from vehicle or defaults)
    capacity_volume_m3 DECIMAL(10,3) DEFAULT 20.0,
    capacity_weight_kg DECIMAL(10,2) DEFAULT 1000.0,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Source
    created_by VARCHAR(50) NOT NULL DEFAULT 'DISPATCHER',
        -- 'DISPATCHER', 'IMPORT', 'TEAM_BUILDER'

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(tenant_id, site_id, plan_date, driver_1_id, driver_2_id),
    CONSTRAINT valid_team_shift CHECK (shift_end_at > shift_start_at),
    CONSTRAINT different_drivers CHECK (driver_1_id != driver_2_id OR driver_2_id IS NULL),
    CONSTRAINT team_size_matches CHECK (
        (team_size = 1 AND driver_2_id IS NULL) OR
        (team_size = 2 AND driver_2_id IS NOT NULL)
    )
);

-- Indices
CREATE INDEX idx_teams_daily_tenant ON teams_daily(tenant_id);
CREATE INDEX idx_teams_daily_site ON teams_daily(site_id);
CREATE INDEX idx_teams_daily_date ON teams_daily(tenant_id, site_id, plan_date);
CREATE INDEX idx_teams_daily_active ON teams_daily(tenant_id, site_id, plan_date, is_active)
    WHERE is_active = TRUE;
CREATE INDEX idx_teams_daily_driver1 ON teams_daily(driver_1_id);
CREATE INDEX idx_teams_daily_driver2 ON teams_daily(driver_2_id) WHERE driver_2_id IS NOT NULL;

-- RLS
ALTER TABLE teams_daily ENABLE ROW LEVEL SECURITY;

CREATE POLICY teams_daily_tenant_isolation ON teams_daily
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::INTEGER);

-- ============================================================
-- E) TEAM_HISTORY - Historical Pairings for V2 Stability
-- ============================================================
-- Records actual team deployments for building stability scores.

CREATE TABLE IF NOT EXISTS team_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    site_id UUID NOT NULL REFERENCES routing_depots(id),

    -- Date
    plan_date DATE NOT NULL,

    -- Team composition (snapshot - drivers may be deleted later)
    driver_1_id UUID,  -- No FK, historical record
    driver_1_external_id VARCHAR(100) NOT NULL,
    driver_2_id UUID,
    driver_2_external_id VARCHAR(100),

    -- Team type
    team_type VARCHAR(50) NOT NULL,  -- 'SOLO', 'DUO_STANDARD', 'DUO_ELEKTRO', etc.
    combined_skills TEXT[] DEFAULT '{}',

    -- Source
    created_by VARCHAR(50) NOT NULL,  -- 'DISPATCHER', 'IMPORT', 'TEAM_BUILDER'

    -- Post-day feedback (optional, for V2)
    success_score DECIMAL(3,2),  -- 0.0 - 1.0
    feedback_notes TEXT,

    -- Link to plan (optional)
    plan_version_id UUID REFERENCES routing_plans(id),

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indices
CREATE INDEX idx_team_history_tenant ON team_history(tenant_id);
CREATE INDEX idx_team_history_site ON team_history(site_id);
CREATE INDEX idx_team_history_date ON team_history(tenant_id, site_id, plan_date);
CREATE INDEX idx_team_history_drivers ON team_history(driver_1_external_id, driver_2_external_id);

-- RLS
ALTER TABLE team_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY team_history_tenant_isolation ON team_history
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::INTEGER);

-- ============================================================
-- F) HELPER FUNCTIONS
-- ============================================================

-- Function to compute combined skills for a team
CREATE OR REPLACE FUNCTION compute_team_combined_skills(
    p_tenant_id INTEGER,
    p_driver_1_id UUID,
    p_driver_2_id UUID
) RETURNS TEXT[] AS $$
DECLARE
    v_skills TEXT[];
BEGIN
    SELECT ARRAY_AGG(DISTINCT skill) INTO v_skills
    FROM driver_skills
    WHERE tenant_id = p_tenant_id
      AND driver_id IN (p_driver_1_id, p_driver_2_id);

    RETURN COALESCE(v_skills, '{}');
END;
$$ LANGUAGE plpgsql STABLE;

-- Trigger to auto-compute combined_skills on teams_daily insert/update
CREATE OR REPLACE FUNCTION teams_daily_compute_skills()
RETURNS TRIGGER AS $$
BEGIN
    NEW.combined_skills := compute_team_combined_skills(
        NEW.tenant_id,
        NEW.driver_1_id,
        NEW.driver_2_id
    );
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_teams_daily_compute_skills
    BEFORE INSERT OR UPDATE ON teams_daily
    FOR EACH ROW
    EXECUTE FUNCTION teams_daily_compute_skills();

-- ============================================================
-- G) VALIDATION FUNCTIONS
-- ============================================================

-- Validate driver availability for team
CREATE OR REPLACE FUNCTION validate_team_availability(
    p_tenant_id INTEGER,
    p_site_id UUID,
    p_plan_date DATE,
    p_driver_1_id UUID,
    p_driver_2_id UUID
) RETURNS TABLE (
    is_valid BOOLEAN,
    error_code VARCHAR(50),
    error_message TEXT
) AS $$
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
$$ LANGUAGE plpgsql STABLE;

-- ============================================================
-- H) RECORD MIGRATION
-- ============================================================
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('022', 'Driver pool and teams daily for routing pack V1', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
