-- =============================================================================
-- Migration 013: Core Tenants, Sites, and Entitlements
-- =============================================================================
-- Creates the foundational multi-tenant infrastructure:
--   - core.tenants: Fixed tenant registry with URL-safe codes
--   - core.sites: Tenant-owned sites with timezones
--   - core.tenant_entitlements: Pack-based feature flags
--   - RLS policies with platform admin bypass
--   - Helper functions for transaction-scoped context
-- =============================================================================

BEGIN;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('013', 'Core tenants, sites, and entitlements')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- SCHEMA: core
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS core;

-- =============================================================================
-- HELPER FUNCTIONS (before tables, as RLS policies reference them)
-- =============================================================================

-- Get current tenant ID from transaction-local config
CREATE OR REPLACE FUNCTION core.app_current_tenant_id()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::UUID;
$$;

-- Get current site ID from transaction-local config
CREATE OR REPLACE FUNCTION core.app_current_site_id()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_site_id', true), '')::UUID;
$$;

-- Check if current session is platform admin (bypasses tenant RLS)
CREATE OR REPLACE FUNCTION core.app_is_platform_admin()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(current_setting('app.is_platform_admin', true), 'false')::BOOLEAN;
$$;

-- =============================================================================
-- TABLE: core.tenants
-- =============================================================================
-- Fixed tenant registry. tenant_code is URL-safe slug.
-- UUID PK for security (no enumerable integer IDs in URLs).

CREATE TABLE core.tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_code     VARCHAR(50) NOT NULL UNIQUE,  -- URL-safe: rohlik, mediamarkt, hdplus, amazonlogistics
    name            VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_core_tenants_code ON core.tenants(tenant_code);
CREATE INDEX idx_core_tenants_active ON core.tenants(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE core.tenants IS 'Fixed tenant registry. Each tenant is a separate organization (Rohlik, Mediamarkt, etc.)';
COMMENT ON COLUMN core.tenants.tenant_code IS 'URL-safe slug used in API paths and config. Immutable after creation.';

-- =============================================================================
-- TABLE: core.sites
-- =============================================================================
-- Physical locations belonging to tenants. Each site has its own timezone.
-- site_code is unique within tenant (not globally).

CREATE TABLE core.sites (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    site_code       VARCHAR(50) NOT NULL,         -- URL-safe: wien, berlin, budapest
    name            VARCHAR(255) NOT NULL,
    timezone        VARCHAR(50) NOT NULL DEFAULT 'Europe/Berlin',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(tenant_id, site_code)
);

CREATE INDEX idx_core_sites_tenant ON core.sites(tenant_id);
CREATE INDEX idx_core_sites_tenant_code ON core.sites(tenant_id, site_code);
CREATE INDEX idx_core_sites_active ON core.sites(tenant_id, is_active) WHERE is_active = TRUE;

COMMENT ON TABLE core.sites IS 'Physical locations owned by tenants. Each site operates in its own timezone.';
COMMENT ON COLUMN core.sites.site_code IS 'URL-safe slug unique within tenant. Used in API paths.';
COMMENT ON COLUMN core.sites.timezone IS 'IANA timezone identifier (Europe/Vienna, Europe/Berlin, etc.)';

-- =============================================================================
-- TABLE: core.tenant_entitlements
-- =============================================================================
-- Pack-based feature flags per tenant. Controls access to packs: core, routing, roster, analytics.

CREATE TABLE core.tenant_entitlements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    pack_id         VARCHAR(50) NOT NULL,         -- core, routing, roster, analytics
    is_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    config          JSONB DEFAULT '{}',           -- Pack-specific configuration
    valid_from      TIMESTAMPTZ,                  -- NULL = immediately
    valid_until     TIMESTAMPTZ,                  -- NULL = forever
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(tenant_id, pack_id)
);

CREATE INDEX idx_core_entitlements_tenant ON core.tenant_entitlements(tenant_id);
CREATE INDEX idx_core_entitlements_pack ON core.tenant_entitlements(pack_id);

COMMENT ON TABLE core.tenant_entitlements IS 'Pack-based entitlements per tenant. Controls feature access.';
COMMENT ON COLUMN core.tenant_entitlements.pack_id IS 'Pack identifier: core, routing, roster, analytics';
COMMENT ON COLUMN core.tenant_entitlements.config IS 'Pack-specific config (e.g., max_vehicles, feature_flags)';

-- =============================================================================
-- TRIGGER: touch_updated_at
-- =============================================================================
CREATE OR REPLACE FUNCTION core.touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_tenants_updated_at
    BEFORE UPDATE ON core.tenants
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

CREATE TRIGGER trg_sites_updated_at
    BEFORE UPDATE ON core.sites
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

CREATE TRIGGER trg_entitlements_updated_at
    BEFORE UPDATE ON core.tenant_entitlements
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

-- =============================================================================
-- RLS POLICIES
-- =============================================================================
-- Pattern: Platform admins bypass, regular users see only their tenant's data.
-- Uses app.current_tenant_id (transaction-local) and app.is_platform_admin flag.

-- Enable RLS on all tables
ALTER TABLE core.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.tenant_entitlements ENABLE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------------
-- core.tenants policies
-- -----------------------------------------------------------------------------
-- Platform admins: full access
CREATE POLICY tenants_platform_admin ON core.tenants
    FOR ALL
    USING (core.app_is_platform_admin() = TRUE)
    WITH CHECK (core.app_is_platform_admin() = TRUE);

-- Regular users: read own tenant only
CREATE POLICY tenants_tenant_read ON core.tenants
    FOR SELECT
    USING (
        core.app_is_platform_admin() = FALSE
        AND id = core.app_current_tenant_id()
    );

-- -----------------------------------------------------------------------------
-- core.sites policies
-- -----------------------------------------------------------------------------
-- Platform admins: full access
CREATE POLICY sites_platform_admin ON core.sites
    FOR ALL
    USING (core.app_is_platform_admin() = TRUE)
    WITH CHECK (core.app_is_platform_admin() = TRUE);

-- Regular users: read own tenant's sites
CREATE POLICY sites_tenant_read ON core.sites
    FOR SELECT
    USING (
        core.app_is_platform_admin() = FALSE
        AND tenant_id = core.app_current_tenant_id()
    );

-- -----------------------------------------------------------------------------
-- core.tenant_entitlements policies
-- -----------------------------------------------------------------------------
-- Platform admins: full access
CREATE POLICY entitlements_platform_admin ON core.tenant_entitlements
    FOR ALL
    USING (core.app_is_platform_admin() = TRUE)
    WITH CHECK (core.app_is_platform_admin() = TRUE);

-- Regular users: read own tenant's entitlements
CREATE POLICY entitlements_tenant_read ON core.tenant_entitlements
    FOR SELECT
    USING (
        core.app_is_platform_admin() = FALSE
        AND tenant_id = core.app_current_tenant_id()
    );

-- =============================================================================
-- CONTEXT SETTER FUNCTION
-- =============================================================================
-- Called by FastAPI at start of each request to set tenant context.
-- Uses SET LOCAL (transaction-scoped) for security.

CREATE OR REPLACE FUNCTION core.set_tenant_context(
    p_tenant_id UUID,
    p_site_id UUID DEFAULT NULL,
    p_is_platform_admin BOOLEAN DEFAULT FALSE
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Transaction-scoped settings (true = local to transaction)
    PERFORM set_config('app.current_tenant_id', COALESCE(p_tenant_id::TEXT, ''), true);
    PERFORM set_config('app.current_site_id', COALESCE(p_site_id::TEXT, ''), true);
    PERFORM set_config('app.is_platform_admin', p_is_platform_admin::TEXT, true);
END;
$$;

COMMENT ON FUNCTION core.set_tenant_context IS 'Sets transaction-local tenant context for RLS. Called by API layer.';

-- =============================================================================
-- LOOKUP HELPERS
-- =============================================================================

-- Get tenant by code
CREATE OR REPLACE FUNCTION core.get_tenant_by_code(p_tenant_code VARCHAR)
RETURNS core.tenants
LANGUAGE sql
STABLE
SECURITY DEFINER  -- Bypasses RLS to allow lookup before context is set
AS $$
    SELECT * FROM core.tenants WHERE tenant_code = p_tenant_code AND is_active = TRUE;
$$;

-- Get site by tenant and site code
CREATE OR REPLACE FUNCTION core.get_site_by_code(p_tenant_id UUID, p_site_code VARCHAR)
RETURNS core.sites
LANGUAGE sql
STABLE
SECURITY DEFINER  -- Bypasses RLS to allow lookup before context is set
AS $$
    SELECT * FROM core.sites WHERE tenant_id = p_tenant_id AND site_code = p_site_code AND is_active = TRUE;
$$;

-- Check if tenant has entitlement for pack
CREATE OR REPLACE FUNCTION core.has_entitlement(p_tenant_id UUID, p_pack_id VARCHAR)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER  -- Bypasses RLS for auth checks
AS $$
    SELECT EXISTS (
        SELECT 1 FROM core.tenant_entitlements
        WHERE tenant_id = p_tenant_id
          AND pack_id = p_pack_id
          AND is_enabled = TRUE
          AND (valid_from IS NULL OR valid_from <= NOW())
          AND (valid_until IS NULL OR valid_until > NOW())
    );
$$;

COMMENT ON FUNCTION core.has_entitlement IS 'Checks if tenant has active entitlement for a pack. Used for authorization.';

COMMIT;
