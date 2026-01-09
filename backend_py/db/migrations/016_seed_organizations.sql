-- =============================================================================
-- Migration 016: Seed Organizations and Link Tenants
-- =============================================================================
-- Seeds the first customer organization (LTS) and links all existing tenants.
--
-- Organization hierarchy after this migration:
--   Platform Owner (you)
--   └── LTS Transport & Logistik (org_code: lts)
--       ├── Rohlik (tenant_code: rohlik)
--       ├── Mediamarkt (tenant_code: mediamarkt)
--       ├── HDPlus (tenant_code: hdplus)
--       └── Amazon Logistics (tenant_code: amazonlogistics)
-- =============================================================================

BEGIN;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('016', 'Seed LTS organization and link tenants')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- SEED: LTS Organization
-- =============================================================================
-- LTS Transport & Logistik is the first customer.
-- Using a fixed UUID for predictable testing.

INSERT INTO core.organizations (id, org_code, name, metadata) VALUES
    ('00000000-0000-0000-0000-000000000001', 'lts', 'LTS Transport & Logistik GmbH', '{
        "industry": "logistics_platform",
        "country_hq": "DE",
        "contract_type": "enterprise",
        "onboarded_at": "2026-01-06"
    }')
ON CONFLICT (org_code) DO NOTHING;

-- =============================================================================
-- BACKFILL: Link existing tenants to LTS organization
-- =============================================================================
-- All tenants created in migration 014 are owned by LTS.

UPDATE core.tenants
SET owner_org_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_code IN ('rohlik', 'mediamarkt', 'hdplus', 'amazonlogistics')
  AND owner_org_id IS NULL;

-- =============================================================================
-- ENFORCE: Make owner_org_id NOT NULL
-- =============================================================================
-- Now that all existing tenants are linked, enforce the constraint.
-- New tenants MUST specify an organization.

-- First verify all tenants have an org
DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphan_count FROM core.tenants WHERE owner_org_id IS NULL;
    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'Cannot make owner_org_id NOT NULL: % orphan tenants exist', orphan_count;
    END IF;
END $$;

-- Now make it required
ALTER TABLE core.tenants
ALTER COLUMN owner_org_id SET NOT NULL;

COMMENT ON COLUMN core.tenants.owner_org_id IS 'FK to owning organization (customer). Required for all tenants.';

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================
-- Uncomment to verify seed data:
--
-- SELECT org_code, name, is_active FROM core.organizations ORDER BY org_code;
--
-- SELECT o.org_code, t.tenant_code, t.name
-- FROM core.tenants t
-- JOIN core.organizations o ON t.owner_org_id = o.id
-- ORDER BY o.org_code, t.tenant_code;
--
-- SELECT o.org_code, core.get_org_tenant_count(o.id) as tenant_count
-- FROM core.organizations o;

COMMIT;
