-- =============================================================================
-- SOLVEREIGN Routing Pack - Gate 4: Site/Depot Partitioning
-- =============================================================================
-- Migration: 021_scenario_site_partitioning.sql
-- Version: 1.0.1
-- Created: 2026-01-06
--
-- Gate 4 Requirements:
-- - scenario.site_id FK auf routing_depots
-- - Advisory locks scoped to (tenant_id, site_id, scenario_id)
-- - Prevent cross-site operations
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. ADD site_id TO routing_scenarios
-- =============================================================================
-- Each scenario is scoped to a specific depot/site.
-- This enforces that all operations are site-partitioned.

ALTER TABLE routing_scenarios
ADD COLUMN IF NOT EXISTS site_id VARCHAR(100);

-- Add FK constraint (after populating existing rows)
-- For now, we don't add NOT NULL - existing scenarios need migration

-- Create index for site-scoped queries
CREATE INDEX IF NOT EXISTS idx_routing_scenarios_site
    ON routing_scenarios(tenant_id, site_id);

COMMENT ON COLUMN routing_scenarios.site_id IS 'Gate 4: Site/Depot partition key - FK to routing_depots.site_id';


-- =============================================================================
-- 2. SITE-SCOPED ADVISORY LOCK FUNCTION
-- =============================================================================
-- Advisory lock key is now: hash(tenant_id || ':' || site_id || ':' || scenario_id)
-- This prevents cross-site concurrent solves.

CREATE OR REPLACE FUNCTION routing_advisory_lock_key(
    p_tenant_id INTEGER,
    p_site_id VARCHAR(100),
    p_scenario_id UUID
) RETURNS BIGINT AS $$
BEGIN
    -- Create a deterministic hash for advisory lock
    -- Format: routing:{tenant}:{site}:{scenario}
    RETURN hashtext(
        'routing:' || p_tenant_id::TEXT || ':' ||
        COALESCE(p_site_id, 'GLOBAL') || ':' ||
        p_scenario_id::TEXT
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION routing_advisory_lock_key IS 'Gate 4: Generate site-scoped advisory lock key';


-- =============================================================================
-- 3. SITE VALIDATION FUNCTION
-- =============================================================================
-- Validates that a scenario's site_id matches the depot's site_id.

CREATE OR REPLACE FUNCTION routing_validate_site_match(
    p_scenario_id UUID,
    p_depot_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    v_scenario_site_id VARCHAR(100);
    v_depot_site_id VARCHAR(100);
BEGIN
    -- Get scenario's site_id
    SELECT site_id INTO v_scenario_site_id
    FROM routing_scenarios
    WHERE id = p_scenario_id;

    -- Get depot's site_id
    SELECT site_id INTO v_depot_site_id
    FROM routing_depots
    WHERE id = p_depot_id;

    -- If scenario has no site_id (legacy), allow any depot
    IF v_scenario_site_id IS NULL THEN
        RETURN TRUE;
    END IF;

    -- Site IDs must match
    RETURN v_scenario_site_id = v_depot_site_id;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION routing_validate_site_match IS 'Gate 4: Validate scenario-depot site_id match';


-- =============================================================================
-- 4. VEHICLE INSERT/UPDATE TRIGGER FOR SITE VALIDATION
-- =============================================================================
-- Ensures vehicles reference depots with matching site_id.

CREATE OR REPLACE FUNCTION routing_enforce_vehicle_site_match()
RETURNS TRIGGER AS $$
DECLARE
    v_scenario_site_id VARCHAR(100);
    v_start_depot_site_id VARCHAR(100);
    v_end_depot_site_id VARCHAR(100);
BEGIN
    -- Get scenario's site_id
    SELECT site_id INTO v_scenario_site_id
    FROM routing_scenarios
    WHERE id = NEW.scenario_id;

    -- If scenario has no site_id (legacy), skip validation
    IF v_scenario_site_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Get start depot's site_id
    SELECT site_id INTO v_start_depot_site_id
    FROM routing_depots
    WHERE id = NEW.start_depot_id;

    -- Get end depot's site_id
    SELECT site_id INTO v_end_depot_site_id
    FROM routing_depots
    WHERE id = NEW.end_depot_id;

    -- Validate start depot matches scenario site
    IF v_start_depot_site_id != v_scenario_site_id THEN
        RAISE EXCEPTION 'Gate 4 violation: Vehicle start_depot site_id (%) does not match scenario site_id (%)',
            v_start_depot_site_id, v_scenario_site_id;
    END IF;

    -- Validate end depot matches scenario site
    IF v_end_depot_site_id != v_scenario_site_id THEN
        RAISE EXCEPTION 'Gate 4 violation: Vehicle end_depot site_id (%) does not match scenario site_id (%)',
            v_end_depot_site_id, v_scenario_site_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_vehicle_site_match ON routing_vehicles;
CREATE TRIGGER enforce_vehicle_site_match
    BEFORE INSERT OR UPDATE ON routing_vehicles
    FOR EACH ROW
    EXECUTE FUNCTION routing_enforce_vehicle_site_match();

COMMENT ON FUNCTION routing_enforce_vehicle_site_match IS 'Gate 4: Enforce vehicle-depot-scenario site_id consistency';


-- =============================================================================
-- 5. VIEW FOR SITE-SCOPED QUERIES
-- =============================================================================
-- Convenience view for site-scoped scenario access.

CREATE OR REPLACE VIEW routing_scenarios_by_site AS
SELECT
    s.id,
    s.tenant_id,
    s.site_id,
    s.vertical,
    s.plan_date,
    s.timezone,
    s.input_hash,
    s.created_at,
    d.name as depot_name,
    d.lat as depot_lat,
    d.lng as depot_lng
FROM routing_scenarios s
LEFT JOIN routing_depots d ON s.tenant_id = d.tenant_id AND s.site_id = d.site_id
WHERE d.is_active = TRUE OR s.site_id IS NULL;

COMMENT ON VIEW routing_scenarios_by_site IS 'Gate 4: Scenarios with depot info for site-scoped access';


-- =============================================================================
-- 6. RECORD MIGRATION
-- =============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('021', 'Gate 4: Site/Depot Partitioning - scenario.site_id + advisory locks', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
