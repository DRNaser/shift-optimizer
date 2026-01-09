-- =============================================================================
-- SOLVEREIGN Routing Pack V1 - Database Migration
-- =============================================================================
-- Migration: 020_routing_pack.sql
-- Version: 1.0.0
-- Created: 2026-01-06
--
-- P0 FIXES INTEGRATED:
-- - P0-1: routing_depots table for Multi-Depot support
-- - P0-3: Unified state machine on routing_plans (not scenario)
-- - P0-4: service_code instead of job_type
-- - P0-5: All time fields as TIMESTAMPTZ
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. DEPOTS (P0-1: Multi-Depot Support)
-- =============================================================================
-- Each vehicle references start_depot_id and end_depot_id.
-- This enables scenarios where vehicles start/end at different locations.

CREATE TABLE IF NOT EXISTS routing_depots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- External reference
    site_id VARCHAR(100) NOT NULL,           -- External site code (e.g., "MM_BERLIN_01")
    name VARCHAR(255) NOT NULL,

    -- Location (required for distance matrix)
    lat DECIMAL(10, 7) NOT NULL,
    lng DECIMAL(10, 7) NOT NULL,

    -- Depot config
    loading_time_min INTEGER DEFAULT 15,     -- Default loading time at this depot
    is_active BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(tenant_id, site_id)
);

CREATE INDEX IF NOT EXISTS idx_routing_depots_tenant ON routing_depots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_routing_depots_active ON routing_depots(tenant_id, is_active) WHERE is_active = TRUE;

COMMENT ON TABLE routing_depots IS 'P0-1: Depots for Multi-Depot routing support';
COMMENT ON COLUMN routing_depots.site_id IS 'External site code for integration';
COMMENT ON COLUMN routing_depots.loading_time_min IS 'Default loading time at depot (minutes)';


-- =============================================================================
-- 2. SCENARIOS (P0-3: Status removed - only metadata)
-- =============================================================================
-- Scenarios are input containers. Status lives on routing_plans only.

CREATE TABLE IF NOT EXISTS routing_scenarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Scenario metadata
    vertical VARCHAR(50) NOT NULL,           -- 'MEDIAMARKT' | 'HDL_PLUS'
    plan_date DATE NOT NULL,                 -- The date being planned
    timezone VARCHAR(50) DEFAULT 'Europe/Berlin',  -- P0-5: Timezone for datetime computation

    -- Deduplication
    input_hash VARCHAR(64) NOT NULL,         -- SHA256 of canonical input

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints (prevent duplicate imports)
    UNIQUE(tenant_id, input_hash)
);

CREATE INDEX IF NOT EXISTS idx_routing_scenarios_tenant ON routing_scenarios(tenant_id);
CREATE INDEX IF NOT EXISTS idx_routing_scenarios_date ON routing_scenarios(tenant_id, plan_date);

COMMENT ON TABLE routing_scenarios IS 'P0-3: Scenarios hold input data only, no status';
COMMENT ON COLUMN routing_scenarios.vertical IS 'Vertical: MEDIAMARKT or HDL_PLUS';
COMMENT ON COLUMN routing_scenarios.input_hash IS 'SHA256 of canonical input for deduplication';


-- =============================================================================
-- 3. STOPS (P0-4: service_code, P0-5: TIMESTAMPTZ)
-- =============================================================================
-- Delivery/Montage/Pickup stops with time windows and requirements.

CREATE TABLE IF NOT EXISTS routing_stops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID NOT NULL REFERENCES routing_scenarios(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Order reference
    order_id VARCHAR(100) NOT NULL,

    -- Service Type (P0-4: service_code for template lookup)
    service_code VARCHAR(100) NOT NULL,      -- MM_DELIVERY, MM_DELIVERY_MONTAGE, HDL_MONTAGE_COMPLEX
    category VARCHAR(50),                     -- DELIVERY | MONTAGE | PICKUP | ENTSORGUNG (derived)

    -- Location
    address_raw TEXT,                         -- Raw address for geocoding
    lat DECIMAL(10, 7),                       -- NULL = needs geocoding
    lng DECIMAL(10, 7),
    geocode_quality VARCHAR(20),              -- HIGH | MEDIUM | LOW | MANUAL | MISSING

    -- Time Window (P0-5: TIMESTAMPTZ everywhere!)
    tw_start TIMESTAMPTZ NOT NULL,
    tw_end TIMESTAMPTZ NOT NULL,
    tw_is_hard BOOLEAN DEFAULT TRUE,          -- Hard constraint or soft (penalty)

    -- Service
    service_duration_min INTEGER NOT NULL,
    requires_two_person BOOLEAN DEFAULT FALSE,
    required_skills TEXT[] DEFAULT '{}',
    floor INTEGER,                            -- Floor number (affects service time)

    -- Capacity
    volume_m3 DECIMAL(10, 3) DEFAULT 0,
    weight_kg DECIMAL(10, 2) DEFAULT 0,
    load_delta INTEGER DEFAULT -1,            -- -1 = Delivery, +1 = Pickup

    -- Priority & Risk
    priority VARCHAR(20) DEFAULT 'NORMAL',    -- NORMAL | HIGH | CRITICAL
    no_show_risk DECIMAL(3, 2) DEFAULT 0.0,   -- 0.0-1.0 from historical data

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(scenario_id, order_id),
    CONSTRAINT valid_time_window CHECK (tw_end > tw_start),
    CONSTRAINT valid_load_delta CHECK (load_delta IN (-1, 0, 1)),
    CONSTRAINT valid_no_show_risk CHECK (no_show_risk >= 0.0 AND no_show_risk <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_routing_stops_scenario ON routing_stops(scenario_id);
CREATE INDEX IF NOT EXISTS idx_routing_stops_tenant ON routing_stops(tenant_id);
CREATE INDEX IF NOT EXISTS idx_routing_stops_geocode_missing ON routing_stops(scenario_id) WHERE lat IS NULL;
CREATE INDEX IF NOT EXISTS idx_routing_stops_priority ON routing_stops(scenario_id, priority) WHERE priority != 'NORMAL';

COMMENT ON TABLE routing_stops IS 'P0-4: Stops with service_code for deterministic template lookup';
COMMENT ON COLUMN routing_stops.service_code IS 'Service code for template lookup (e.g., MM_DELIVERY_MONTAGE)';
COMMENT ON COLUMN routing_stops.load_delta IS '-1 = Delivery (decreases load), +1 = Pickup (increases load)';


-- =============================================================================
-- 4. VEHICLES (P0-1: Depot FK, P0-5: TIMESTAMPTZ)
-- =============================================================================
-- Vehicles with team info, skills, capacity, and depot references.

CREATE TABLE IF NOT EXISTS routing_vehicles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID NOT NULL REFERENCES routing_scenarios(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- External reference
    external_id VARCHAR(100),                 -- External ID (e.g., plate number)

    -- Team
    team_id VARCHAR(100),
    team_size INTEGER NOT NULL DEFAULT 1,
    skills TEXT[] DEFAULT '{}',

    -- Shift (P0-5: TIMESTAMPTZ, not TIME!)
    shift_start_at TIMESTAMPTZ NOT NULL,
    shift_end_at TIMESTAMPTZ NOT NULL,

    -- Depots (P0-1: Multi-Depot support)
    start_depot_id UUID NOT NULL REFERENCES routing_depots(id),
    end_depot_id UUID NOT NULL REFERENCES routing_depots(id),

    -- Capacity
    capacity_volume_m3 DECIMAL(10, 3),
    capacity_weight_kg DECIMAL(10, 2),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_team_size CHECK (team_size IN (1, 2)),
    CONSTRAINT valid_shift CHECK (shift_end_at > shift_start_at)
);

CREATE INDEX IF NOT EXISTS idx_routing_vehicles_scenario ON routing_vehicles(scenario_id);
CREATE INDEX IF NOT EXISTS idx_routing_vehicles_tenant ON routing_vehicles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_routing_vehicles_depot ON routing_vehicles(start_depot_id);

COMMENT ON TABLE routing_vehicles IS 'P0-1: Vehicles with Multi-Depot support via start/end depot FKs';
COMMENT ON COLUMN routing_vehicles.team_size IS '1 = single driver, 2 = 2-Mann team';
COMMENT ON COLUMN routing_vehicles.shift_start_at IS 'P0-5: Shift start as TIMESTAMPTZ (not TIME)';


-- =============================================================================
-- 5. ROUTING PLANS (P0-3: Unified State Machine)
-- =============================================================================
-- Plans hold solver output and status. Status is ONLY on plan, not scenario.

CREATE TABLE IF NOT EXISTS routing_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID NOT NULL REFERENCES routing_scenarios(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Status (P0-3: Unified state machine)
    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'SOLVING', 'SOLVED', 'AUDITED', 'DRAFT', 'LOCKED', 'FAILED', 'SUPERSEDED')),

    -- Solver config (P0-3: Idempotency)
    seed INTEGER,
    solver_config_hash VARCHAR(64) NOT NULL,
    output_hash VARCHAR(64),                  -- Hash of solution for reproducibility

    -- Job tracking
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,

    -- Metrics
    total_vehicles INTEGER,
    total_distance_km DECIMAL(10, 2),
    total_duration_min INTEGER,
    unassigned_count INTEGER,
    on_time_percentage DECIMAL(5, 2),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Lock info
    locked_at TIMESTAMPTZ,
    locked_by VARCHAR(255),

    -- Constraints (P0-3: Idempotency - one plan per config)
    UNIQUE(scenario_id, solver_config_hash)
);

CREATE INDEX IF NOT EXISTS idx_routing_plans_scenario ON routing_plans(scenario_id);
CREATE INDEX IF NOT EXISTS idx_routing_plans_tenant_status ON routing_plans(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_routing_plans_solving ON routing_plans(status) WHERE status = 'SOLVING';
CREATE INDEX IF NOT EXISTS idx_routing_plans_locked ON routing_plans(tenant_id, locked_at) WHERE status = 'LOCKED';

COMMENT ON TABLE routing_plans IS 'P0-3: Plans with unified state machine (status only here, not on scenario)';
COMMENT ON COLUMN routing_plans.solver_config_hash IS 'Config hash for idempotency (UNIQUE with scenario_id)';


-- =============================================================================
-- 6. ROUTE ASSIGNMENTS
-- =============================================================================
-- Stop assignments to vehicles with sequence and timing.

CREATE TABLE IF NOT EXISTS routing_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES routing_plans(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Assignment
    vehicle_id UUID NOT NULL REFERENCES routing_vehicles(id),
    stop_id UUID NOT NULL REFERENCES routing_stops(id),

    -- Sequence & Timing
    sequence_index INTEGER NOT NULL,         -- Order in route (0, 1, 2, ...)
    arrival_at TIMESTAMPTZ,                  -- Computed arrival time
    departure_at TIMESTAMPTZ,                -- Computed departure time
    slack_minutes INTEGER,                   -- Buffer before time window end

    -- Status
    is_locked BOOLEAN DEFAULT FALSE,         -- Frozen (cannot be reassigned)
    assignment_reason TEXT,                  -- Explainability: why this vehicle?

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(plan_id, stop_id),                -- Each stop assigned once per plan
    UNIQUE(plan_id, vehicle_id, sequence_index)  -- Unique sequence per vehicle
);

CREATE INDEX IF NOT EXISTS idx_routing_assignments_plan ON routing_assignments(plan_id);
CREATE INDEX IF NOT EXISTS idx_routing_assignments_vehicle ON routing_assignments(plan_id, vehicle_id);
CREATE INDEX IF NOT EXISTS idx_routing_assignments_locked ON routing_assignments(plan_id) WHERE is_locked = TRUE;

COMMENT ON TABLE routing_assignments IS 'Stop-to-vehicle assignments with sequence and timing';


-- =============================================================================
-- 7. UNASSIGNED STOPS
-- =============================================================================
-- Stops that couldn't be assigned, with reason codes.

CREATE TABLE IF NOT EXISTS routing_unassigned (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES routing_plans(id) ON DELETE CASCADE,
    stop_id UUID NOT NULL REFERENCES routing_stops(id),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Reason
    reason_code VARCHAR(50) NOT NULL,        -- TIME_WINDOW, CAPACITY, SKILL, NO_VEHICLE, etc.
    reason_details TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(plan_id, stop_id)
);

CREATE INDEX IF NOT EXISTS idx_routing_unassigned_plan ON routing_unassigned(plan_id);
CREATE INDEX IF NOT EXISTS idx_routing_unassigned_reason ON routing_unassigned(plan_id, reason_code);

COMMENT ON TABLE routing_unassigned IS 'Unassigned stops with reason codes';


-- =============================================================================
-- 8. AUDIT LOG
-- =============================================================================
-- Write-only audit log for routing plans.

CREATE TABLE IF NOT EXISTS routing_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES routing_plans(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Audit check
    check_name VARCHAR(100) NOT NULL,        -- ON_TIME, CAPACITY, SKILL, TIME_WINDOW, etc.
    status VARCHAR(20) NOT NULL,             -- PASS | FAIL | WARN
    violation_count INTEGER DEFAULT 0,
    details JSONB,                           -- Detailed violation info

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_audit_plan ON routing_audit_log(plan_id);
CREATE INDEX IF NOT EXISTS idx_routing_audit_status ON routing_audit_log(plan_id, status) WHERE status != 'PASS';

COMMENT ON TABLE routing_audit_log IS 'Write-only audit log for routing plans';


-- =============================================================================
-- 9. REPAIR HISTORY
-- =============================================================================
-- Track repair events and their outcomes.

CREATE TABLE IF NOT EXISTS routing_repair_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_plan_id UUID NOT NULL REFERENCES routing_plans(id),
    repaired_plan_id UUID NOT NULL REFERENCES routing_plans(id),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Event that triggered repair
    event_type VARCHAR(50) NOT NULL,         -- NO_SHOW, DELAY, VEHICLE_DOWN, etc.
    event_timestamp TIMESTAMPTZ NOT NULL,
    event_details JSONB,

    -- Affected entities
    affected_stop_ids UUID[] DEFAULT '{}',
    affected_vehicle_ids UUID[] DEFAULT '{}',

    -- Churn metrics
    stops_moved INTEGER DEFAULT 0,
    vehicles_changed INTEGER DEFAULT 0,
    churn_score DECIMAL(10, 2) DEFAULT 0,

    -- Diff (what changed)
    diff JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_repair_original ON routing_repair_history(original_plan_id);
CREATE INDEX IF NOT EXISTS idx_routing_repair_tenant ON routing_repair_history(tenant_id);

COMMENT ON TABLE routing_repair_history IS 'Track repair events and churn metrics';


-- =============================================================================
-- 10. IMMUTABILITY TRIGGERS
-- =============================================================================
-- Prevent modification of LOCKED plans (like existing plan_versions).

-- Check if function exists, create if not
CREATE OR REPLACE FUNCTION prevent_locked_routing_plan_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'LOCKED' AND NEW.status != 'SUPERSEDED' THEN
        RAISE EXCEPTION 'Cannot modify LOCKED routing plan. Use repair to create new version.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION prevent_locked_routing_assignment_modification()
RETURNS TRIGGER AS $$
DECLARE
    plan_status VARCHAR(20);
BEGIN
    SELECT status INTO plan_status FROM routing_plans WHERE id = OLD.plan_id;
    IF plan_status = 'LOCKED' THEN
        RAISE EXCEPTION 'Cannot modify assignments for LOCKED routing plan.';
    END IF;
    RETURN OLD;  -- For DELETE, return OLD; for UPDATE would return NEW
END;
$$ LANGUAGE plpgsql;

-- Create triggers (drop first if exist)
DROP TRIGGER IF EXISTS prevent_locked_routing_plan ON routing_plans;
CREATE TRIGGER prevent_locked_routing_plan
    BEFORE UPDATE ON routing_plans
    FOR EACH ROW
    WHEN (OLD.status = 'LOCKED')
    EXECUTE FUNCTION prevent_locked_routing_plan_modification();

DROP TRIGGER IF EXISTS prevent_locked_routing_assignments_update ON routing_assignments;
CREATE TRIGGER prevent_locked_routing_assignments_update
    BEFORE UPDATE ON routing_assignments
    FOR EACH ROW
    EXECUTE FUNCTION prevent_locked_routing_assignment_modification();

DROP TRIGGER IF EXISTS prevent_locked_routing_assignments_delete ON routing_assignments;
CREATE TRIGGER prevent_locked_routing_assignments_delete
    BEFORE DELETE ON routing_assignments
    FOR EACH ROW
    EXECUTE FUNCTION prevent_locked_routing_assignment_modification();


-- =============================================================================
-- 11. UPDATED_AT TRIGGERS
-- =============================================================================

CREATE OR REPLACE FUNCTION update_routing_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS routing_depots_updated_at ON routing_depots;
CREATE TRIGGER routing_depots_updated_at
    BEFORE UPDATE ON routing_depots
    FOR EACH ROW
    EXECUTE FUNCTION update_routing_updated_at();


-- =============================================================================
-- 12. RECORD MIGRATION
-- =============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('020', 'Routing Pack V1 - VRP/VRPTW tables with P0 fixes', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
