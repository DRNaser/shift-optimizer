-- =============================================================================
-- Migration 015: Core Organizations (Customer Hierarchy)
-- =============================================================================
-- Adds the Customer/Organization hierarchy above tenants:
--   - Platform Owner → Customer (Organization) → Tenants
--
-- Organizations are NOT for data mixing - they are purely grouping/ownership
-- metadata for the platform admin console. RLS isolation remains tenant-based.
--
-- Business hierarchy:
--   - Platform Owner (me) manages everything
--   - Customer (e.g., LTS) is a company that owns tenants
--   - Tenants (Rohlik, Mediamarkt, etc.) remain the isolation boundary
-- =============================================================================

BEGIN;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('015', 'Core organizations hierarchy')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- TABLE: core.organizations
-- =============================================================================
-- Customer/Partner companies that own one or more tenants.
-- This enables the platform to onboard multiple customers (reseller model).

CREATE TABLE core.organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_code        VARCHAR(50) NOT NULL UNIQUE,      -- URL-safe: lts, customer_xyz
    name            VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_core_orgs_code ON core.organizations(org_code);
CREATE INDEX idx_core_orgs_active ON core.organizations(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE core.organizations IS 'Customer organizations that own tenants. Platform admin grouping only, not for data isolation.';
COMMENT ON COLUMN core.organizations.org_code IS 'URL-safe slug for API paths. Immutable after creation.';

-- Add updated_at trigger
CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON core.organizations
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

-- =============================================================================
-- ALTER TABLE: core.tenants - Add owner_org_id
-- =============================================================================
-- Links tenants to their owning organization.
-- ON DELETE RESTRICT prevents orphaning tenants.

-- Step 1: Add column as nullable first (existing data won't have it)
ALTER TABLE core.tenants
ADD COLUMN owner_org_id UUID REFERENCES core.organizations(id) ON DELETE RESTRICT;

-- Create index for efficient org-tenant lookups
CREATE INDEX idx_core_tenants_owner_org ON core.tenants(owner_org_id);
CREATE INDEX idx_core_tenants_owner_org_code ON core.tenants(owner_org_id, tenant_code);

COMMENT ON COLUMN core.tenants.owner_org_id IS 'FK to owning organization (customer). Cannot be NULL after backfill.';

-- =============================================================================
-- RLS POLICIES: core.organizations
-- =============================================================================
-- Organizations are platform-admin only for write, readable by anyone with context.

ALTER TABLE core.organizations ENABLE ROW LEVEL SECURITY;

-- Platform admins: full access
CREATE POLICY orgs_platform_admin ON core.organizations
    FOR ALL
    USING (core.app_is_platform_admin() = TRUE)
    WITH CHECK (core.app_is_platform_admin() = TRUE);

-- Regular users: read their own org (via tenant lookup)
-- This allows a tenant user to see which org they belong to
CREATE POLICY orgs_tenant_read ON core.organizations
    FOR SELECT
    USING (
        core.app_is_platform_admin() = FALSE
        AND id IN (
            SELECT owner_org_id FROM core.tenants
            WHERE id = core.app_current_tenant_id()
        )
    );

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get organization by code
CREATE OR REPLACE FUNCTION core.get_org_by_code(p_org_code VARCHAR)
RETURNS core.organizations
LANGUAGE sql
STABLE
SECURITY DEFINER  -- Bypasses RLS for platform lookups
AS $$
    SELECT * FROM core.organizations WHERE org_code = p_org_code AND is_active = TRUE;
$$;

-- Get all tenants for an organization (platform admin use)
CREATE OR REPLACE FUNCTION core.get_tenants_for_org(p_org_id UUID)
RETURNS SETOF core.tenants
LANGUAGE sql
STABLE
SECURITY DEFINER  -- Bypasses RLS for platform lookups
AS $$
    SELECT * FROM core.tenants WHERE owner_org_id = p_org_id ORDER BY tenant_code;
$$;

-- Get tenant count for organization
CREATE OR REPLACE FUNCTION core.get_org_tenant_count(p_org_id UUID)
RETURNS INTEGER
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT COUNT(*)::INTEGER FROM core.tenants WHERE owner_org_id = p_org_id;
$$;

-- Get organization for current tenant
CREATE OR REPLACE FUNCTION core.get_current_org()
RETURNS core.organizations
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT o.* FROM core.organizations o
    JOIN core.tenants t ON t.owner_org_id = o.id
    WHERE t.id = core.app_current_tenant_id();
$$;

COMMENT ON FUNCTION core.get_org_by_code IS 'Platform lookup: get organization by code.';
COMMENT ON FUNCTION core.get_tenants_for_org IS 'Platform lookup: get all tenants owned by an organization.';
COMMENT ON FUNCTION core.get_org_tenant_count IS 'Platform lookup: count tenants in organization.';
COMMENT ON FUNCTION core.get_current_org IS 'Get organization for current tenant context.';

-- =============================================================================
-- SECURITY EVENTS TABLE
-- =============================================================================
-- Tracks security escalation events for audit and monitoring.

CREATE TABLE core.security_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(50) NOT NULL,             -- PLATFORM_ADMIN_SPOOF, RLS_VIOLATION, SIGNATURE_INVALID, etc.
    severity        VARCHAR(10) NOT NULL DEFAULT 'S1' CHECK (severity IN ('S0', 'S1', 'S2', 'S3')),
    source_ip       VARCHAR(50),
    tenant_id       UUID REFERENCES core.tenants(id) ON DELETE SET NULL,
    user_id         VARCHAR(255),
    request_path    VARCHAR(500),
    request_method  VARCHAR(10),
    details         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_core_security_events_type ON core.security_events(event_type);
CREATE INDEX idx_core_security_events_severity ON core.security_events(severity);
CREATE INDEX idx_core_security_events_created ON core.security_events(created_at);
CREATE INDEX idx_core_security_events_tenant ON core.security_events(tenant_id);

-- RLS: Platform admin only
ALTER TABLE core.security_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY security_events_platform_admin ON core.security_events
    FOR ALL
    USING (core.app_is_platform_admin() = TRUE)
    WITH CHECK (core.app_is_platform_admin() = TRUE);

COMMENT ON TABLE core.security_events IS 'Security escalation events. Platform admin audit log.';
COMMENT ON COLUMN core.security_events.severity IS 'S0=Security/Leak, S1=Integrity, S2=Degraded, S3=Minor';

-- =============================================================================
-- INTERNAL REQUEST SIGNATURE TRACKING
-- =============================================================================
-- Tracks used signatures to prevent replay attacks.

CREATE TABLE core.used_signatures (
    signature       VARCHAR(128) PRIMARY KEY,
    timestamp       BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_core_used_signatures_expires ON core.used_signatures(expires_at);

-- Auto-cleanup expired signatures (can be called by cron or pg_cron)
CREATE OR REPLACE FUNCTION core.cleanup_expired_signatures()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM core.used_signatures WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

COMMENT ON TABLE core.used_signatures IS 'Tracks used HMAC signatures to prevent replay attacks.';
COMMENT ON FUNCTION core.cleanup_expired_signatures IS 'Cleanup function for expired signatures. Call periodically.';

COMMIT;
