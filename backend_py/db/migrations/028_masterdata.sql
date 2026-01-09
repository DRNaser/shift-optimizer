-- =============================================================================
-- Migration 028: Master Data Layer (MDL) - Kernel Service
-- =============================================================================
-- Purpose: Canonical entities + external-id mappings for domain packs
--
-- Key Principle: Packs NEVER store external IDs directly. All external IDs
-- are resolved to canonical UUIDs via md_external_mappings.
--
-- Mapping Rule:
--   (tenant_id, external_system, entity_type, external_id) -> internal_uuid
--
-- RLS: All tables have tenant isolation via RLS policies.
--
-- Run:
--   psql $DATABASE_URL < backend_py/db/migrations/028_masterdata.sql
-- =============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('028', 'Master Data Layer (MDL) - canonical entities + external mappings', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- CREATE SCHEMA
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS masterdata;

COMMENT ON SCHEMA masterdata IS
'Master Data Layer (MDL) - Canonical entities and external ID mappings.
Packs resolve external IDs through this layer to maintain single source of truth.';


-- =============================================================================
-- GRANT SCHEMA USAGE
-- =============================================================================
-- Following existing role hierarchy from 025x migrations

DO $$
BEGIN
    -- Grant usage to platform and API roles
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT USAGE ON SCHEMA masterdata TO solvereign_platform;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT USAGE ON SCHEMA masterdata TO solvereign_api;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_definer') THEN
        GRANT USAGE ON SCHEMA masterdata TO solvereign_definer;
    END IF;
END $$;


-- =============================================================================
-- TABLE: md_sites (Depots/Locations within tenant)
-- =============================================================================

CREATE TABLE IF NOT EXISTS masterdata.md_sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'Europe/Vienna',
    is_active BOOLEAN DEFAULT TRUE,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique site code per tenant
    CONSTRAINT md_sites_unique_code UNIQUE (tenant_id, site_code)
);

CREATE INDEX IF NOT EXISTS idx_md_sites_tenant ON masterdata.md_sites(tenant_id);
CREATE INDEX IF NOT EXISTS idx_md_sites_active ON masterdata.md_sites(tenant_id, is_active) WHERE is_active = TRUE;

COMMENT ON TABLE masterdata.md_sites IS 'Canonical site/depot entities per tenant';
COMMENT ON COLUMN masterdata.md_sites.site_code IS 'Tenant-unique site code (e.g., "WIEN", "LINZ")';
COMMENT ON COLUMN masterdata.md_sites.config IS 'Site-specific config (operating hours, default rules)';


-- =============================================================================
-- TABLE: md_locations (Geocoded addresses)
-- =============================================================================

CREATE TABLE IF NOT EXISTS masterdata.md_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID REFERENCES masterdata.md_sites(id) ON DELETE SET NULL,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    -- Rounded coordinates for deduplication (5 decimals = ~1.1m precision)
    lat_rounded DOUBLE PRECISION GENERATED ALWAYS AS (ROUND(lat::NUMERIC, 5)::DOUBLE PRECISION) STORED,
    lng_rounded DOUBLE PRECISION GENERATED ALWAYS AS (ROUND(lng::NUMERIC, 5)::DOUBLE PRECISION) STORED,
    address_text VARCHAR(500),  -- Original input address
    address_norm VARCHAR(500),  -- Normalized address (geocoder output)
    location_type VARCHAR(50) DEFAULT 'customer',  -- customer, depot, hub
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Deduplication: same rounded coordinates within tenant
    CONSTRAINT md_locations_unique_coords UNIQUE (tenant_id, lat_rounded, lng_rounded)
);

-- Spatial-friendly index for geoqueries
CREATE INDEX IF NOT EXISTS idx_md_locations_tenant ON masterdata.md_locations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_md_locations_coords ON masterdata.md_locations(lat, lng);
CREATE INDEX IF NOT EXISTS idx_md_locations_site ON masterdata.md_locations(site_id) WHERE site_id IS NOT NULL;

COMMENT ON TABLE masterdata.md_locations IS 'Geocoded locations for routing and distance calculations';
COMMENT ON COLUMN masterdata.md_locations.address_norm IS 'Normalized address from geocoder for deduplication';


-- =============================================================================
-- TABLE: md_vehicles (Fleet vehicles)
-- =============================================================================

CREATE TABLE IF NOT EXISTS masterdata.md_vehicles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID REFERENCES masterdata.md_sites(id) ON DELETE SET NULL,
    vehicle_code VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    vehicle_type VARCHAR(50) DEFAULT 'van',  -- van, truck, bike, etc.

    -- Capacity fields
    capacity_weight_kg NUMERIC(10,2),
    capacity_volume_m3 NUMERIC(10,2),
    capacity_pallets INTEGER,
    capacity_items INTEGER,

    -- Operating constraints
    max_range_km NUMERIC(10,2),
    fuel_type VARCHAR(50),  -- diesel, electric, hybrid
    is_refrigerated BOOLEAN DEFAULT FALSE,
    is_adr_certified BOOLEAN DEFAULT FALSE,  -- hazmat

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    flags JSONB DEFAULT '{}',  -- arbitrary flags (night_shift_only, etc.)

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique vehicle code per tenant
    CONSTRAINT md_vehicles_unique_code UNIQUE (tenant_id, vehicle_code)
);

CREATE INDEX IF NOT EXISTS idx_md_vehicles_tenant ON masterdata.md_vehicles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_md_vehicles_site ON masterdata.md_vehicles(site_id) WHERE site_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_md_vehicles_active ON masterdata.md_vehicles(tenant_id, is_active) WHERE is_active = TRUE;

COMMENT ON TABLE masterdata.md_vehicles IS 'Canonical fleet vehicle entities';
COMMENT ON COLUMN masterdata.md_vehicles.flags IS 'Arbitrary vehicle flags as JSONB (e.g., {"night_shift_only": true})';


-- =============================================================================
-- TABLE: md_external_mappings (THE KEY TABLE)
-- =============================================================================
-- Maps external system IDs to internal canonical UUIDs
-- This is the SINGLE SOURCE OF TRUTH for external ID resolution

CREATE TABLE IF NOT EXISTS masterdata.md_external_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Mapping keys
    external_system VARCHAR(100) NOT NULL,  -- e.g., "fls", "sap", "google_sheets"
    entity_type VARCHAR(50) NOT NULL,       -- e.g., "driver", "vehicle", "tour", "site"
    external_id VARCHAR(255) NOT NULL,      -- The external system's ID

    -- Target
    internal_id UUID NOT NULL,              -- Our canonical UUID

    -- Metadata
    sync_status VARCHAR(50) DEFAULT 'active',  -- active, deprecated, deleted
    last_synced_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- THE CRITICAL CONSTRAINT
    -- One mapping per (tenant, system, type, external_id) combination
    CONSTRAINT md_external_mappings_unique_external
        UNIQUE (tenant_id, external_system, entity_type, external_id)
);

-- Lookup indexes
CREATE INDEX IF NOT EXISTS idx_md_external_mappings_tenant ON masterdata.md_external_mappings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_md_external_mappings_lookup ON masterdata.md_external_mappings(tenant_id, external_system, entity_type);
CREATE INDEX IF NOT EXISTS idx_md_external_mappings_internal ON masterdata.md_external_mappings(internal_id);
CREATE INDEX IF NOT EXISTS idx_md_external_mappings_active ON masterdata.md_external_mappings(tenant_id, sync_status) WHERE sync_status = 'active';

COMMENT ON TABLE masterdata.md_external_mappings IS
'External ID to internal UUID mappings. THE source of truth for resolving external IDs.';
COMMENT ON COLUMN masterdata.md_external_mappings.external_system IS
'Source system identifier (e.g., "fls", "sap", "google_sheets", "customer_erp")';
COMMENT ON COLUMN masterdata.md_external_mappings.entity_type IS
'Entity type being mapped (driver, vehicle, tour, site, customer, etc.)';
COMMENT ON COLUMN masterdata.md_external_mappings.internal_id IS
'Canonical internal UUID - the ID used by all SOLVEREIGN packs';


-- =============================================================================
-- ENABLE RLS ON ALL MDL TABLES
-- =============================================================================

ALTER TABLE masterdata.md_sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE masterdata.md_sites FORCE ROW LEVEL SECURITY;

ALTER TABLE masterdata.md_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE masterdata.md_locations FORCE ROW LEVEL SECURITY;

ALTER TABLE masterdata.md_vehicles ENABLE ROW LEVEL SECURITY;
ALTER TABLE masterdata.md_vehicles FORCE ROW LEVEL SECURITY;

ALTER TABLE masterdata.md_external_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE masterdata.md_external_mappings FORCE ROW LEVEL SECURITY;


-- =============================================================================
-- RLS POLICIES - Tenant Isolation
-- =============================================================================
-- Pattern: tenant_id = current_setting('app.current_tenant_id')::INTEGER

-- md_sites policies
CREATE POLICY md_sites_tenant_isolation ON masterdata.md_sites
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);

-- md_locations policies
CREATE POLICY md_locations_tenant_isolation ON masterdata.md_locations
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);

-- md_vehicles policies
CREATE POLICY md_vehicles_tenant_isolation ON masterdata.md_vehicles
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);

-- md_external_mappings policies
CREATE POLICY md_external_mappings_tenant_isolation ON masterdata.md_external_mappings
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);


-- =============================================================================
-- GRANT TABLE PERMISSIONS
-- =============================================================================

DO $$
BEGIN
    -- API role (tenant operations)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT SELECT, INSERT, UPDATE ON masterdata.md_sites TO solvereign_api;
        GRANT SELECT, INSERT, UPDATE ON masterdata.md_locations TO solvereign_api;
        GRANT SELECT, INSERT, UPDATE ON masterdata.md_vehicles TO solvereign_api;
        GRANT SELECT, INSERT, UPDATE ON masterdata.md_external_mappings TO solvereign_api;
    END IF;

    -- Platform role (admin operations)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT ALL ON masterdata.md_sites TO solvereign_platform;
        GRANT ALL ON masterdata.md_locations TO solvereign_platform;
        GRANT ALL ON masterdata.md_vehicles TO solvereign_platform;
        GRANT ALL ON masterdata.md_external_mappings TO solvereign_platform;
    END IF;
END $$;


-- =============================================================================
-- TRIGGER: Auto-update updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION masterdata.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_md_sites_updated_at
    BEFORE UPDATE ON masterdata.md_sites
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();

CREATE TRIGGER tr_md_locations_updated_at
    BEFORE UPDATE ON masterdata.md_locations
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();

CREATE TRIGGER tr_md_vehicles_updated_at
    BEFORE UPDATE ON masterdata.md_vehicles
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();

CREATE TRIGGER tr_md_external_mappings_updated_at
    BEFORE UPDATE ON masterdata.md_external_mappings
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();


-- =============================================================================
-- FUNCTION: resolve_external_id
-- =============================================================================
-- Core resolution function - returns internal_id for external_id

CREATE OR REPLACE FUNCTION masterdata.resolve_external_id(
    p_tenant_id INTEGER,
    p_external_system VARCHAR,
    p_entity_type VARCHAR,
    p_external_id VARCHAR
)
RETURNS UUID AS $$
DECLARE
    v_internal_id UUID;
BEGIN
    SELECT internal_id INTO v_internal_id
    FROM masterdata.md_external_mappings
    WHERE tenant_id = p_tenant_id
      AND external_system = p_external_system
      AND entity_type = p_entity_type
      AND external_id = p_external_id
      AND sync_status = 'active';

    RETURN v_internal_id;  -- NULL if not found
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION masterdata.resolve_external_id IS
'Resolve external ID to internal UUID. Returns NULL if not found.';


-- =============================================================================
-- FUNCTION: upsert_mapping (Idempotent)
-- =============================================================================
-- Create or update mapping - returns the internal_id

CREATE OR REPLACE FUNCTION masterdata.upsert_mapping(
    p_tenant_id INTEGER,
    p_external_system VARCHAR,
    p_entity_type VARCHAR,
    p_external_id VARCHAR,
    p_internal_id UUID,
    p_metadata JSONB DEFAULT '{}'
)
RETURNS UUID AS $$
DECLARE
    v_result UUID;
BEGIN
    INSERT INTO masterdata.md_external_mappings (
        tenant_id, external_system, entity_type, external_id, internal_id, metadata, last_synced_at
    ) VALUES (
        p_tenant_id, p_external_system, p_entity_type, p_external_id, p_internal_id, p_metadata, NOW()
    )
    ON CONFLICT (tenant_id, external_system, entity_type, external_id)
    DO UPDATE SET
        internal_id = EXCLUDED.internal_id,
        metadata = EXCLUDED.metadata,
        last_synced_at = NOW(),
        sync_status = 'active',
        updated_at = NOW()
    RETURNING internal_id INTO v_result;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION masterdata.upsert_mapping IS
'Idempotent mapping upsert. Creates new or updates existing mapping.';


-- =============================================================================
-- FUNCTION: resolve_or_create
-- =============================================================================
-- Resolve external ID, creating entity + mapping if payload provided

CREATE OR REPLACE FUNCTION masterdata.resolve_or_create(
    p_tenant_id INTEGER,
    p_external_system VARCHAR,
    p_entity_type VARCHAR,
    p_external_id VARCHAR,
    p_create_payload JSONB DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_internal_id UUID;
    v_created BOOLEAN := FALSE;
    v_entity_data JSONB;
BEGIN
    -- First try to resolve existing mapping
    v_internal_id := masterdata.resolve_external_id(
        p_tenant_id, p_external_system, p_entity_type, p_external_id
    );

    IF v_internal_id IS NOT NULL THEN
        -- Found existing mapping
        RETURN jsonb_build_object(
            'found', TRUE,
            'internal_id', v_internal_id,
            'external_id', p_external_id,
            'entity_type', p_entity_type,
            'created', FALSE
        );
    END IF;

    -- Not found - check if we should create
    IF p_create_payload IS NULL THEN
        -- No payload to create entity
        RETURN jsonb_build_object(
            'found', FALSE,
            'external_id', p_external_id,
            'entity_type', p_entity_type,
            'error', 'Mapping not found and no create_payload provided'
        );
    END IF;

    -- Create entity based on type
    CASE p_entity_type
        WHEN 'site' THEN
            INSERT INTO masterdata.md_sites (tenant_id, site_code, name, timezone, config)
            VALUES (
                p_tenant_id,
                COALESCE(p_create_payload->>'site_code', p_external_id),
                COALESCE(p_create_payload->>'name', p_external_id),
                COALESCE(p_create_payload->>'timezone', 'Europe/Vienna'),
                COALESCE(p_create_payload->'config', '{}')
            )
            RETURNING id INTO v_internal_id;

        WHEN 'location' THEN
            INSERT INTO masterdata.md_locations (tenant_id, lat, lng, address_text, address_norm, location_type, metadata)
            VALUES (
                p_tenant_id,
                (p_create_payload->>'lat')::DOUBLE PRECISION,
                (p_create_payload->>'lng')::DOUBLE PRECISION,
                p_create_payload->>'address_text',
                p_create_payload->>'address_norm',
                COALESCE(p_create_payload->>'location_type', 'customer'),
                COALESCE(p_create_payload->'metadata', '{}')
            )
            RETURNING id INTO v_internal_id;

        WHEN 'vehicle' THEN
            INSERT INTO masterdata.md_vehicles (tenant_id, vehicle_code, name, vehicle_type, capacity_weight_kg, capacity_volume_m3, flags)
            VALUES (
                p_tenant_id,
                COALESCE(p_create_payload->>'vehicle_code', p_external_id),
                p_create_payload->>'name',
                COALESCE(p_create_payload->>'vehicle_type', 'van'),
                (p_create_payload->>'capacity_weight_kg')::NUMERIC,
                (p_create_payload->>'capacity_volume_m3')::NUMERIC,
                COALESCE(p_create_payload->'flags', '{}')
            )
            RETURNING id INTO v_internal_id;

        ELSE
            -- For other types (driver, tour, etc.), generate UUID and let pack handle creation
            v_internal_id := gen_random_uuid();
    END CASE;

    -- Create mapping
    PERFORM masterdata.upsert_mapping(
        p_tenant_id, p_external_system, p_entity_type, p_external_id, v_internal_id,
        jsonb_build_object('created_from_resolve', TRUE, 'original_payload', p_create_payload)
    );

    v_created := TRUE;

    RETURN jsonb_build_object(
        'found', TRUE,
        'internal_id', v_internal_id,
        'external_id', p_external_id,
        'entity_type', p_entity_type,
        'created', v_created
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION masterdata.resolve_or_create IS
'Resolve external ID or create entity + mapping if payload provided. Idempotent.';


-- =============================================================================
-- FUNCTION: resolve_bulk
-- =============================================================================
-- Batch resolution for performance

CREATE OR REPLACE FUNCTION masterdata.resolve_bulk(
    p_tenant_id INTEGER,
    p_external_system VARCHAR,
    p_entity_type VARCHAR,
    p_external_ids VARCHAR[]
)
RETURNS TABLE (
    external_id VARCHAR,
    internal_id UUID,
    found BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.ext_id AS external_id,
        m.internal_id,
        m.internal_id IS NOT NULL AS found
    FROM unnest(p_external_ids) AS e(ext_id)
    LEFT JOIN masterdata.md_external_mappings m
        ON m.tenant_id = p_tenant_id
        AND m.external_system = p_external_system
        AND m.entity_type = p_entity_type
        AND m.external_id = e.ext_id
        AND m.sync_status = 'active';
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION masterdata.resolve_bulk IS
'Batch resolve external IDs. Returns all inputs with found/not-found status.';


-- =============================================================================
-- FUNCTION: verify_masterdata_integrity
-- =============================================================================
-- Verification function for MDL health

CREATE OR REPLACE FUNCTION masterdata.verify_masterdata_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: RLS enabled on all MDL tables
    RETURN QUERY
    SELECT
        'rls_enabled'::TEXT,
        CASE WHEN COUNT(*) = 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 tables have RLS enabled', COUNT(*))
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'masterdata')
    WHERE t.schemaname = 'masterdata'
      AND t.tablename IN ('md_sites', 'md_locations', 'md_vehicles', 'md_external_mappings')
      AND c.relrowsecurity = TRUE;

    -- Check 2: FORCE RLS enabled
    RETURN QUERY
    SELECT
        'force_rls_enabled'::TEXT,
        CASE WHEN COUNT(*) = 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 tables have FORCE RLS enabled', COUNT(*))
    FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'masterdata')
    WHERE t.schemaname = 'masterdata'
      AND t.tablename IN ('md_sites', 'md_locations', 'md_vehicles', 'md_external_mappings')
      AND c.relforcerowsecurity = TRUE;

    -- Check 3: Unique constraint on mappings exists
    RETURN QUERY
    SELECT
        'mapping_unique_constraint'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'md_external_mappings_unique_external'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'Unique constraint (tenant_id, external_system, entity_type, external_id)'::TEXT;

    -- Check 4: Unique constraints on sites and vehicles exist
    RETURN QUERY
    SELECT
        'entity_unique_constraints'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'md_sites_unique_code'
        ) AND EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'md_vehicles_unique_code'
        ) AND EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'md_locations_unique_coords'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'Unique constraints on sites (site_code), vehicles (vehicle_code), locations (lat/lng)'::TEXT;

    -- Check 5: RLS policies exist
    RETURN QUERY
    SELECT
        'rls_policies_exist'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s RLS policies found (expected 4)', COUNT(*))
    FROM pg_policies
    WHERE schemaname = 'masterdata';

    -- Check 6: Functions exist
    RETURN QUERY
    SELECT
        'functions_exist'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s functions found (expected 4+)', COUNT(*))
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'masterdata'
      AND p.proname IN ('resolve_external_id', 'upsert_mapping', 'resolve_or_create', 'resolve_bulk');

    -- Check 7: tenant_id NOT NULL on all tables (verified via column constraints)
    RETURN QUERY
    SELECT
        'tenant_id_not_null'::TEXT,
        CASE WHEN COUNT(*) = 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 tables have tenant_id NOT NULL', COUNT(*))
    FROM information_schema.columns c
    WHERE c.table_schema = 'masterdata'
      AND c.table_name IN ('md_sites', 'md_locations', 'md_vehicles', 'md_external_mappings')
      AND c.column_name = 'tenant_id'
      AND c.is_nullable = 'NO';

    -- Check 8: No orphaned mappings (internal_id points to existing entity)
    -- This is a warning, not a failure (driver/tour mappings may point to other tables)
    RETURN QUERY
    SELECT
        'orphaned_mappings'::TEXT,
        CASE WHEN orphan_count = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s orphaned mappings (internal_id not in any MDL table)', orphan_count)
    FROM (
        SELECT COUNT(*) as orphan_count
        FROM masterdata.md_external_mappings m
        WHERE m.entity_type IN ('site', 'location', 'vehicle')
          AND m.sync_status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM masterdata.md_sites s WHERE s.id = m.internal_id
              UNION ALL
              SELECT 1 FROM masterdata.md_locations l WHERE l.id = m.internal_id
              UNION ALL
              SELECT 1 FROM masterdata.md_vehicles v WHERE v.id = m.internal_id
          )
    ) x;

    -- Check 9: Verify tenant FK references exist
    RETURN QUERY
    SELECT
        'tenant_fk_exists'::TEXT,
        CASE WHEN COUNT(*) = 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 tables have tenant_id FK to tenants', COUNT(*))
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = 'masterdata'
      AND kcu.column_name = 'tenant_id';

END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION masterdata.verify_masterdata_integrity IS
'Verify MDL health. Run after migration to confirm RLS, constraints, and functions.';


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 028: Master Data Layer (MDL) COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'SCHEMA: masterdata';
    RAISE NOTICE '';
    RAISE NOTICE 'TABLES:';
    RAISE NOTICE '  - masterdata.md_sites          (tenant depots)';
    RAISE NOTICE '  - masterdata.md_locations      (geocoded addresses)';
    RAISE NOTICE '  - masterdata.md_vehicles       (fleet vehicles)';
    RAISE NOTICE '  - masterdata.md_external_mappings (THE key table)';
    RAISE NOTICE '';
    RAISE NOTICE 'FUNCTIONS:';
    RAISE NOTICE '  - resolve_external_id(tenant, system, type, ext_id)';
    RAISE NOTICE '  - upsert_mapping(tenant, system, type, ext_id, internal_id)';
    RAISE NOTICE '  - resolve_or_create(tenant, system, type, ext_id, payload)';
    RAISE NOTICE '  - resolve_bulk(tenant, system, type, ext_ids[])';
    RAISE NOTICE '  - verify_masterdata_integrity()';
    RAISE NOTICE '';
    RAISE NOTICE 'SECURITY:';
    RAISE NOTICE '  - RLS enabled + FORCE on all tables';
    RAISE NOTICE '  - Tenant isolation via app.current_tenant_id';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM masterdata.verify_masterdata_integrity();';
    RAISE NOTICE '============================================================';
END $$;
