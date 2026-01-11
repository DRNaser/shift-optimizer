-- =============================================================================
-- SOLVEREIGN V4.7 - Tenant Pack Configuration
-- =============================================================================
-- Adds pack_* columns to tenants table for dynamic nav capabilities.
-- Each pack can be enabled/disabled per tenant.
-- =============================================================================

-- Add pack columns to tenants table (if not exist)
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS pack_roster BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS pack_routing BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS pack_masterdata BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS pack_portal BOOLEAN NOT NULL DEFAULT true;

-- Add comments
COMMENT ON COLUMN tenants.pack_roster IS 'Roster Pack enabled for shift optimization';
COMMENT ON COLUMN tenants.pack_routing IS 'Routing Pack enabled for VRPTW optimization';
COMMENT ON COLUMN tenants.pack_masterdata IS 'Master Data Pack enabled for driver/vehicle management';
COMMENT ON COLUMN tenants.pack_portal IS 'Portal Pack enabled for driver self-service';

-- Verify
DO $$
BEGIN
    RAISE NOTICE 'Migration 042_tenant_packs.sql complete';
    RAISE NOTICE 'Pack columns added to tenants table';
END $$;
