-- =============================================================================
-- Migration 014: Seed Tenants, Sites, and Entitlements
-- =============================================================================
-- Seeds the core tenant infrastructure with:
--   - 4 Tenants: Rohlik, Mediamarkt, HDPlus, Amazon Logistics
--   - Sites per tenant with correct timezones
--   - Pack entitlements per tenant
-- =============================================================================

BEGIN;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('014', 'Seed tenants, sites, and entitlements')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- TENANT 1: ROHLIK
-- =============================================================================
-- Czech grocery delivery, operates in CZ, AT, HU, DE

INSERT INTO core.tenants (id, tenant_code, name, metadata) VALUES
    ('11111111-1111-1111-1111-111111111111', 'rohlik', 'Rohlik Group', '{"industry": "grocery_delivery", "country_hq": "CZ"}');

-- Rohlik Sites (4)
INSERT INTO core.sites (tenant_id, site_code, name, timezone) VALUES
    ('11111111-1111-1111-1111-111111111111', 'wien', 'Rohlik Wien', 'Europe/Vienna'),
    ('11111111-1111-1111-1111-111111111111', 'prag', 'Rohlik Praha', 'Europe/Prague'),
    ('11111111-1111-1111-1111-111111111111', 'budapest', 'Rohlik Budapest', 'Europe/Budapest'),
    ('11111111-1111-1111-1111-111111111111', 'muenchen', 'Rohlik München', 'Europe/Berlin');

-- Rohlik Entitlements: core + routing (pilot)
INSERT INTO core.tenant_entitlements (tenant_id, pack_id, is_enabled, config) VALUES
    ('11111111-1111-1111-1111-111111111111', 'core', TRUE, '{}'),
    ('11111111-1111-1111-1111-111111111111', 'routing', TRUE, '{"max_vehicles": 100, "pilot_site": "wien"}'),
    ('11111111-1111-1111-1111-111111111111', 'roster', FALSE, '{}'),
    ('11111111-1111-1111-1111-111111111111', 'analytics', FALSE, '{}');

-- =============================================================================
-- TENANT 2: MEDIAMARKT
-- =============================================================================
-- Electronics retail, home delivery + installation services

INSERT INTO core.tenants (id, tenant_code, name, metadata) VALUES
    ('22222222-2222-2222-2222-222222222222', 'mediamarkt', 'MediaMarktSaturn Retail Group', '{"industry": "electronics_retail", "country_hq": "DE"}');

-- MediaMarkt Sites (7)
INSERT INTO core.sites (tenant_id, site_code, name, timezone) VALUES
    ('22222222-2222-2222-2222-222222222222', 'berlin', 'MediaMarkt Berlin', 'Europe/Berlin'),
    ('22222222-2222-2222-2222-222222222222', 'hamburg', 'MediaMarkt Hamburg', 'Europe/Berlin'),
    ('22222222-2222-2222-2222-222222222222', 'muenchen', 'MediaMarkt München', 'Europe/Berlin'),
    ('22222222-2222-2222-2222-222222222222', 'koeln', 'MediaMarkt Köln', 'Europe/Berlin'),
    ('22222222-2222-2222-2222-222222222222', 'frankfurt', 'MediaMarkt Frankfurt', 'Europe/Berlin'),
    ('22222222-2222-2222-2222-222222222222', 'wien', 'MediaMarkt Wien', 'Europe/Vienna'),
    ('22222222-2222-2222-2222-222222222222', 'zuerich', 'MediaMarkt Zürich', 'Europe/Zurich');

-- MediaMarkt Entitlements: core + routing + roster
INSERT INTO core.tenant_entitlements (tenant_id, pack_id, is_enabled, config) VALUES
    ('22222222-2222-2222-2222-222222222222', 'core', TRUE, '{}'),
    ('22222222-2222-2222-2222-222222222222', 'routing', TRUE, '{"max_vehicles": 500, "verticals": ["delivery", "montage"]}'),
    ('22222222-2222-2222-2222-222222222222', 'roster', TRUE, '{"max_drivers": 1000}'),
    ('22222222-2222-2222-2222-222222222222', 'analytics', FALSE, '{}');

-- =============================================================================
-- TENANT 3: HDL PLUS
-- =============================================================================
-- Heavy goods delivery + assembly (furniture, appliances)

INSERT INTO core.tenants (id, tenant_code, name, metadata) VALUES
    ('33333333-3333-3333-3333-333333333333', 'hdplus', 'HDL Plus Logistik', '{"industry": "heavy_delivery", "country_hq": "DE"}');

-- HDPlus Sites (1) - Single hub operation
INSERT INTO core.sites (tenant_id, site_code, name, timezone) VALUES
    ('33333333-3333-3333-3333-333333333333', 'nrw', 'HDL Plus NRW Hub', 'Europe/Berlin');

-- HDPlus Entitlements: core + routing (montage-focused)
INSERT INTO core.tenant_entitlements (tenant_id, pack_id, is_enabled, config) VALUES
    ('33333333-3333-3333-3333-333333333333', 'core', TRUE, '{}'),
    ('33333333-3333-3333-3333-333333333333', 'routing', TRUE, '{"max_vehicles": 200, "verticals": ["montage_complex"]}'),
    ('33333333-3333-3333-3333-333333333333', 'roster', FALSE, '{}'),
    ('33333333-3333-3333-3333-333333333333', 'analytics', FALSE, '{}');

-- =============================================================================
-- TENANT 4: AMAZON LOGISTICS
-- =============================================================================
-- Last-mile delivery for Amazon packages

INSERT INTO core.tenants (id, tenant_code, name, metadata) VALUES
    ('44444444-4444-4444-4444-444444444444', 'amazonlogistics', 'Amazon Logistics DE', '{"industry": "parcel_delivery", "country_hq": "DE"}');

-- Amazon Logistics Sites (3)
INSERT INTO core.sites (tenant_id, site_code, name, timezone) VALUES
    ('44444444-4444-4444-4444-444444444444', 'ber1', 'Amazon Berlin DBS1', 'Europe/Berlin'),
    ('44444444-4444-4444-4444-444444444444', 'muc2', 'Amazon München DMU2', 'Europe/Berlin'),
    ('44444444-4444-4444-4444-444444444444', 'fra3', 'Amazon Frankfurt DFR3', 'Europe/Berlin');

-- Amazon Logistics Entitlements: core + routing + analytics
INSERT INTO core.tenant_entitlements (tenant_id, pack_id, is_enabled, config) VALUES
    ('44444444-4444-4444-4444-444444444444', 'core', TRUE, '{}'),
    ('44444444-4444-4444-4444-444444444444', 'routing', TRUE, '{"max_vehicles": 2000, "verticals": ["parcel"]}'),
    ('44444444-4444-4444-4444-444444444444', 'roster', FALSE, '{}'),
    ('44444444-4444-4444-4444-444444444444', 'analytics', TRUE, '{"dashboards": ["delivery_performance", "driver_utilization"]}');

-- =============================================================================
-- VERIFICATION QUERIES (for manual testing)
-- =============================================================================
-- Uncomment to verify seed data:
--
-- SELECT tenant_code, name, is_active FROM core.tenants ORDER BY tenant_code;
--
-- SELECT t.tenant_code, s.site_code, s.name, s.timezone
-- FROM core.sites s
-- JOIN core.tenants t ON s.tenant_id = t.id
-- ORDER BY t.tenant_code, s.site_code;
--
-- SELECT t.tenant_code, e.pack_id, e.is_enabled, e.config
-- FROM core.tenant_entitlements e
-- JOIN core.tenants t ON e.tenant_id = t.id
-- ORDER BY t.tenant_code, e.pack_id;

COMMIT;
