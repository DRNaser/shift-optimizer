-- Migration: 023_policy_profiles.sql
-- Purpose: Data-driven tenant pack configuration for SaaS scaling
-- See: ADR-002-policy-profiles.md

BEGIN;

-- ============================================
-- POLICY PROFILES TABLE
-- Versioned configuration per tenant/pack
-- ============================================

CREATE TABLE IF NOT EXISTS core.policy_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    pack_id TEXT NOT NULL CHECK (pack_id IN ('routing', 'roster', 'analytics')),
    name TEXT NOT NULL,
    description TEXT,
    version INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),

    -- Configuration (JSONB for flexibility)
    config_json JSONB NOT NULL,

    -- Computed hash for determinism verification
    -- Same config_json = same config_hash (reproducibility)
    config_hash TEXT GENERATED ALWAYS AS (
        encode(sha256(config_json::text::bytea), 'hex')
    ) STORED,

    -- Schema version for validation
    schema_version TEXT NOT NULL DEFAULT '1.0',

    -- Audit fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL,

    -- Constraints
    CONSTRAINT policy_profiles_unique_version
        UNIQUE (tenant_id, pack_id, name, version)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_policy_profiles_tenant_pack
    ON core.policy_profiles(tenant_id, pack_id);

CREATE INDEX IF NOT EXISTS idx_policy_profiles_active
    ON core.policy_profiles(status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_policy_profiles_config_hash
    ON core.policy_profiles(config_hash);

-- Comment
COMMENT ON TABLE core.policy_profiles IS
    'Versioned configuration profiles per tenant/pack. See ADR-002.';

COMMENT ON COLUMN core.policy_profiles.config_hash IS
    'SHA256 hash of config_json for determinism verification';


-- ============================================
-- TENANT PACK SETTINGS TABLE
-- Which profile is active for each tenant/pack
-- ============================================

CREATE TABLE IF NOT EXISTS core.tenant_pack_settings (
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    pack_id TEXT NOT NULL CHECK (pack_id IN ('routing', 'roster', 'analytics')),
    active_profile_id UUID REFERENCES core.policy_profiles(id),

    -- Whether to use pack defaults when no profile selected
    use_pack_defaults BOOLEAN NOT NULL DEFAULT true,

    -- Audit fields
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL,

    PRIMARY KEY (tenant_id, pack_id)
);

-- Comment
COMMENT ON TABLE core.tenant_pack_settings IS
    'Active policy profile selection per tenant/pack';


-- ============================================
-- TRIGGER: Enforce single active profile per name
-- When a profile is activated, archive previous active
-- ============================================

CREATE OR REPLACE FUNCTION core.enforce_single_active_profile()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'active' THEN
        -- Archive any existing active profile with same name
        UPDATE core.policy_profiles
        SET status = 'archived',
            updated_at = NOW(),
            updated_by = NEW.updated_by
        WHERE tenant_id = NEW.tenant_id
          AND pack_id = NEW.pack_id
          AND name = NEW.name
          AND id != NEW.id
          AND status = 'active';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enforce_single_active_profile ON core.policy_profiles;
CREATE TRIGGER trg_enforce_single_active_profile
    BEFORE INSERT OR UPDATE ON core.policy_profiles
    FOR EACH ROW
    EXECUTE FUNCTION core.enforce_single_active_profile();


-- ============================================
-- ROW-LEVEL SECURITY
-- Tenants can only see their own profiles
-- ============================================

ALTER TABLE core.policy_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS policy_profiles_tenant_isolation ON core.policy_profiles;
CREATE POLICY policy_profiles_tenant_isolation ON core.policy_profiles
    USING (
        tenant_id::text = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_platform_admin', true) = 'true'
    );

ALTER TABLE core.tenant_pack_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_pack_settings_isolation ON core.tenant_pack_settings;
CREATE POLICY tenant_pack_settings_isolation ON core.tenant_pack_settings
    USING (
        tenant_id::text = current_setting('app.current_tenant_id', true)
        OR current_setting('app.is_platform_admin', true) = 'true'
    );


-- ============================================
-- ADD POLICY SNAPSHOT FIELDS TO RUN TABLES
-- For determinism: record which policy was used
-- ============================================

-- Routing scenarios (only if table exists - routing pack may not be deployed)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'routing_scenarios') THEN
        ALTER TABLE routing_scenarios
            ADD COLUMN IF NOT EXISTS policy_profile_id UUID REFERENCES core.policy_profiles(id),
            ADD COLUMN IF NOT EXISTS policy_config_hash TEXT;

        COMMENT ON COLUMN routing_scenarios.policy_profile_id IS
            'Policy profile used for this scenario (NULL = pack defaults)';
        COMMENT ON COLUMN routing_scenarios.policy_config_hash IS
            'SHA256 of policy config at scenario creation - ensures determinism';
    END IF;
END $$;

-- Routing plans (only if table exists - routing pack may not be deployed)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'routing_plans') THEN
        ALTER TABLE routing_plans
            ADD COLUMN IF NOT EXISTS policy_profile_id UUID REFERENCES core.policy_profiles(id),
            ADD COLUMN IF NOT EXISTS policy_config_hash TEXT;

        COMMENT ON COLUMN routing_plans.policy_profile_id IS
            'Policy profile used for this plan (NULL = pack defaults)';
        COMMENT ON COLUMN routing_plans.policy_config_hash IS
            'SHA256 of policy config at solve time - ensures determinism';
    END IF;
END $$;

-- Plan versions (roster - should always exist in core schema)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'plan_versions') THEN
        ALTER TABLE plan_versions
            ADD COLUMN IF NOT EXISTS policy_profile_id UUID REFERENCES core.policy_profiles(id),
            ADD COLUMN IF NOT EXISTS policy_config_hash TEXT;

        COMMENT ON COLUMN plan_versions.policy_profile_id IS
            'Policy profile used for this solve (NULL = pack defaults)';
        COMMENT ON COLUMN plan_versions.policy_config_hash IS
            'SHA256 of policy config at solve time - ensures determinism';
    ELSE
        RAISE NOTICE 'plan_versions table not found - skipping policy columns';
    END IF;
END $$;


-- ============================================
-- AUDIT LOG: Track policy changes
-- ============================================

CREATE TABLE IF NOT EXISTS core.policy_audit_log (
    id BIGSERIAL PRIMARY KEY,
    policy_profile_id UUID NOT NULL REFERENCES core.policy_profiles(id),
    action TEXT NOT NULL CHECK (action IN ('created', 'updated', 'activated', 'archived')),
    old_status TEXT,
    new_status TEXT,
    old_config_hash TEXT,
    new_config_hash TEXT,
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_policy_audit_log_profile
    ON core.policy_audit_log(policy_profile_id);

CREATE INDEX IF NOT EXISTS idx_policy_audit_log_time
    ON core.policy_audit_log(changed_at DESC);

-- Trigger to auto-log changes
CREATE OR REPLACE FUNCTION core.log_policy_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO core.policy_audit_log
            (policy_profile_id, action, new_status, new_config_hash, changed_by)
        VALUES
            (NEW.id, 'created', NEW.status, NEW.config_hash, NEW.created_by);
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.status != NEW.status THEN
            INSERT INTO core.policy_audit_log
                (policy_profile_id, action, old_status, new_status, old_config_hash, new_config_hash, changed_by)
            VALUES
                (NEW.id,
                 CASE NEW.status WHEN 'active' THEN 'activated' WHEN 'archived' THEN 'archived' ELSE 'updated' END,
                 OLD.status, NEW.status, OLD.config_hash, NEW.config_hash, NEW.updated_by);
        ELSIF OLD.config_json::text != NEW.config_json::text THEN
            INSERT INTO core.policy_audit_log
                (policy_profile_id, action, old_config_hash, new_config_hash, changed_by)
            VALUES
                (NEW.id, 'updated', OLD.config_hash, NEW.config_hash, NEW.updated_by);
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_policy_change ON core.policy_profiles;
CREATE TRIGGER trg_log_policy_change
    AFTER INSERT OR UPDATE ON core.policy_profiles
    FOR EACH ROW
    EXECUTE FUNCTION core.log_policy_change();


-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Get active policy config for a tenant/pack
CREATE OR REPLACE FUNCTION core.get_active_policy(
    p_tenant_id UUID,
    p_pack_id TEXT
)
RETURNS TABLE (
    profile_id UUID,
    config_json JSONB,
    config_hash TEXT,
    schema_version TEXT,
    use_defaults BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        pp.id AS profile_id,
        pp.config_json,
        pp.config_hash,
        pp.schema_version,
        COALESCE(tps.use_pack_defaults, true) AS use_defaults
    FROM core.tenant_pack_settings tps
    LEFT JOIN core.policy_profiles pp ON pp.id = tps.active_profile_id
    WHERE tps.tenant_id = p_tenant_id
      AND tps.pack_id = p_pack_id;

    -- If no settings exist, return NULL with use_defaults=true
    IF NOT FOUND THEN
        RETURN QUERY
        SELECT
            NULL::UUID,
            NULL::JSONB,
            NULL::TEXT,
            NULL::TEXT,
            true AS use_defaults;
    END IF;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION core.get_active_policy IS
    'Get active policy profile for a tenant/pack. Returns NULL profile with use_defaults=true if no profile set.';


-- ============================================
-- RECORD MIGRATION
-- ============================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('023', 'Policy profiles for tenant pack configuration', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
