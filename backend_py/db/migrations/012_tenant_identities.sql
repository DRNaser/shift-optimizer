-- =============================================================================
-- SOLVEREIGN V3.3b - Migration 012: Tenant Identities (Entra ID Integration)
-- =============================================================================
--
-- This migration adds:
-- 1. tenant_identities table for IdP tenant mapping (Entra tid -> tenant_id)
-- 2. Support for multiple IdPs per tenant (future-proof)
-- 3. Indexes for fast lookup during authentication
--
-- Run with: psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f 012_tenant_identities.sql
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. TENANT IDENTITIES TABLE
-- =============================================================================
-- Maps external IdP identifiers to internal tenant_id
-- For Entra ID: issuer + tid (Azure AD Tenant ID) -> tenants.id

CREATE TABLE IF NOT EXISTS tenant_identities (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- IdP identification
    issuer          VARCHAR(512) NOT NULL,    -- e.g., https://login.microsoftonline.com/{tid}/v2.0
    external_tid    VARCHAR(100) NOT NULL,    -- Entra tid claim (Azure AD Tenant ID, UUID format)

    -- Metadata
    provider_type   VARCHAR(50) NOT NULL DEFAULT 'entra_id',  -- entra_id, auth0, keycloak, etc.
    display_name    VARCHAR(255),             -- Human-readable name for admin UI
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,

    -- Audit fields
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: one mapping per issuer + external_tid
    CONSTRAINT uq_tenant_identity_issuer_tid UNIQUE (issuer, external_tid)
);

-- Indexes for fast authentication lookup
CREATE INDEX IF NOT EXISTS idx_tenant_identities_lookup
    ON tenant_identities(issuer, external_tid)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_tenant_identities_tenant
    ON tenant_identities(tenant_id);

-- Comments
COMMENT ON TABLE tenant_identities IS 'Maps external IdP tenant identifiers to internal tenant_id';
COMMENT ON COLUMN tenant_identities.issuer IS 'JWT issuer URL (iss claim)';
COMMENT ON COLUMN tenant_identities.external_tid IS 'External tenant ID from IdP (tid claim for Entra ID)';
COMMENT ON COLUMN tenant_identities.provider_type IS 'IdP type: entra_id, auth0, keycloak';

-- =============================================================================
-- 2. UPDATE TRIGGER FOR updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_tenant_identities_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_tenant_identities_updated_at ON tenant_identities;
CREATE TRIGGER trigger_tenant_identities_updated_at
    BEFORE UPDATE ON tenant_identities
    FOR EACH ROW
    EXECUTE FUNCTION update_tenant_identities_updated_at();

-- =============================================================================
-- 3. HELPER FUNCTION: Lookup tenant by IdP identity
-- =============================================================================
-- Used by auth middleware to map Entra tid -> internal tenant_id

CREATE OR REPLACE FUNCTION get_tenant_by_idp_identity(
    p_issuer VARCHAR(512),
    p_external_tid VARCHAR(100)
)
RETURNS INTEGER AS $$
DECLARE
    v_tenant_id INTEGER;
BEGIN
    SELECT ti.tenant_id INTO v_tenant_id
    FROM tenant_identities ti
    JOIN tenants t ON ti.tenant_id = t.id
    WHERE ti.issuer = p_issuer
      AND ti.external_tid = p_external_tid
      AND ti.is_active = TRUE
      AND t.is_active = TRUE;

    RETURN v_tenant_id;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_tenant_by_idp_identity IS
    'Lookup internal tenant_id by IdP issuer and external tenant ID (tid)';

-- =============================================================================
-- 4. HELPER FUNCTION: Register tenant identity
-- =============================================================================
-- Used during tenant onboarding to create IdP mapping

CREATE OR REPLACE FUNCTION register_tenant_identity(
    p_tenant_id INTEGER,
    p_issuer VARCHAR(512),
    p_external_tid VARCHAR(100),
    p_provider_type VARCHAR(50) DEFAULT 'entra_id',
    p_display_name VARCHAR(255) DEFAULT NULL
)
RETURNS INTEGER AS $$
DECLARE
    v_identity_id INTEGER;
BEGIN
    INSERT INTO tenant_identities (tenant_id, issuer, external_tid, provider_type, display_name)
    VALUES (p_tenant_id, p_issuer, p_external_tid, p_provider_type, p_display_name)
    ON CONFLICT (issuer, external_tid) DO UPDATE
        SET tenant_id = EXCLUDED.tenant_id,
            provider_type = EXCLUDED.provider_type,
            display_name = EXCLUDED.display_name,
            is_active = TRUE,
            updated_at = NOW()
    RETURNING id INTO v_identity_id;

    RETURN v_identity_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION register_tenant_identity IS
    'Register or update IdP identity mapping for a tenant';

-- =============================================================================
-- 5. REGISTER TENANT WITH ENTRA ID
-- =============================================================================
--
-- IMPORTANT: Replace placeholders before running:
--   {ENTRA_TENANT_ID}  - Your Azure AD Tenant ID (UUID format)
--
-- COMMON BUG: Mismatch between tenant 'name' in DB vs what you expect
-- Always check first: SELECT id, name FROM tenants;
--
-- STEPS TO REGISTER:
-- 1. Run migration up to here (creates table + functions)
-- 2. Check existing tenants: SELECT id, name FROM tenants;
-- 3. Uncomment ONE of the options below and replace placeholders
-- 4. Run the registration block

-- OPTION A: If tenant already exists (use ID from step 2)
-- UNCOMMENT AND RUN:
/*
SELECT register_tenant_identity(
    <YOUR_TENANT_ID>,                                              -- from: SELECT id FROM tenants WHERE name = '...'
    'https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0',    -- must match token's iss claim EXACTLY
    '{ENTRA_TENANT_ID}',                                           -- Azure AD Tenant ID (UUID)
    'entra_id',
    'LTS Entra ID'
);
*/

-- OPTION B: Create new tenant + register (fresh install)
DO $$
DECLARE
    v_lts_tenant_id INTEGER;
BEGIN
    -- Create tenant with slug-style name (company name in metadata)
    SELECT id INTO v_lts_tenant_id FROM tenants WHERE name = 'lts-transport-001';

    IF v_lts_tenant_id IS NULL THEN
        INSERT INTO tenants (name, api_key_hash, is_active, metadata)
        VALUES (
            'lts-transport-001',
            'lts_api_key_hash_replace_before_production',
            TRUE,
            jsonb_build_object(
                'tier', 'production',
                'company', 'LTS Transport & Logistik GmbH',
                'onboarded_at', NOW()::TEXT
            )
        )
        RETURNING id INTO v_lts_tenant_id;

        RAISE NOTICE 'Created LTS tenant with id=%', v_lts_tenant_id;
    ELSE
        RAISE NOTICE 'LTS tenant already exists with id=%', v_lts_tenant_id;
    END IF;

    -- UNCOMMENT AND REPLACE {ENTRA_TENANT_ID} to register Entra mapping:
    -- PERFORM register_tenant_identity(
    --     v_lts_tenant_id,
    --     'https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0',
    --     '{ENTRA_TENANT_ID}',
    --     'entra_id',
    --     'LTS Entra ID'
    -- );
END $$;

-- VERIFICATION: After registration, run:
-- SELECT ti.*, t.name as tenant_name
-- FROM tenant_identities ti
-- JOIN tenants t ON ti.tenant_id = t.id;

-- =============================================================================
-- 6. ROW-LEVEL SECURITY
-- =============================================================================
-- tenant_identities should only be readable by super admins

ALTER TABLE tenant_identities ENABLE ROW LEVEL SECURITY;

-- Super admin can see all
DROP POLICY IF EXISTS tenant_identities_super_admin ON tenant_identities;
CREATE POLICY tenant_identities_super_admin ON tenant_identities
    FOR ALL
    USING (
        current_setting('app.is_super_admin', true) = 'true'
    );

-- Grant access to API role (RLS will filter)
GRANT SELECT ON tenant_identities TO solvereign_api;
GRANT ALL ON tenant_identities TO solvereign_admin;
GRANT USAGE, SELECT ON tenant_identities_id_seq TO solvereign_api;
GRANT ALL ON tenant_identities_id_seq TO solvereign_admin;

-- =============================================================================
-- 7. MIGRATION TRACKING
-- =============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES (
    '012_tenant_identities',
    'Tenant identities for IdP mapping (Entra ID)',
    NOW()
)
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- =============================================================================
-- VERIFICATION QUERIES (run manually)
-- =============================================================================

-- Check table exists:
-- SELECT * FROM tenant_identities;

-- Test lookup function:
-- SELECT get_tenant_by_idp_identity(
--     'https://login.microsoftonline.com/{tid}/v2.0',
--     '{tid}'
-- );

-- List all IdP mappings:
-- SELECT ti.*, t.name as tenant_name
-- FROM tenant_identities ti
-- JOIN tenants t ON ti.tenant_id = t.id;
