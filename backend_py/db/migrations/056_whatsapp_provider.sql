-- =============================================================================
-- Migration 056: WhatsApp Provider Abstraction
-- =============================================================================
-- Purpose: Provider abstraction layer for WhatsApp notifications
--          Supports multiple providers (Meta Cloud API as PRIMARY, ClawdBot as OPTIONAL)
--
-- Key Principle: Template-only outbound (no free text generation).
--                All messages must use pre-approved templates.
--
-- RLS: All tables have tenant isolation via RLS policies.
--
-- Run:
--   psql $DATABASE_URL < backend_py/db/migrations/056_whatsapp_provider.sql
-- =============================================================================

BEGIN;

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('056', 'WhatsApp Provider Abstraction - multi-provider support', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- TABLE: notify.providers
-- =============================================================================
-- Provider configuration per tenant (or system-wide)

CREATE TABLE IF NOT EXISTS notify.providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL = system default

    -- Provider identification
    provider_key VARCHAR(50) NOT NULL,  -- whatsapp_meta, whatsapp_clawdbot, email_sendgrid
    display_name VARCHAR(100) NOT NULL,
    channel VARCHAR(20) NOT NULL,  -- WHATSAPP, EMAIL, SMS

    -- Provider status
    is_primary BOOLEAN DEFAULT FALSE,  -- Primary provider for this channel
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 100,  -- Lower = higher priority for failover

    -- Configuration (encrypted in application layer)
    config JSONB DEFAULT '{}',  -- API keys, endpoints, etc.
    -- For whatsapp_meta: {phone_number_id, business_account_id, access_token_ref}
    -- For whatsapp_clawdbot: {api_url, api_key_ref, group_id}

    -- Rate limits
    rate_limit_per_minute INTEGER DEFAULT 80,  -- Meta default
    rate_limit_per_day INTEGER DEFAULT 1000,
    current_minute_count INTEGER DEFAULT 0,
    current_day_count INTEGER DEFAULT 0,
    rate_limit_reset_at TIMESTAMPTZ,

    -- Health tracking
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    consecutive_failures INTEGER DEFAULT 0,
    health_status VARCHAR(20) DEFAULT 'UNKNOWN',  -- HEALTHY, DEGRADED, UNHEALTHY, UNKNOWN

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT providers_channel_check CHECK (channel IN ('WHATSAPP', 'EMAIL', 'SMS', 'PUSH')),
    CONSTRAINT providers_health_check CHECK (health_status IN ('HEALTHY', 'DEGRADED', 'UNHEALTHY', 'UNKNOWN')),
    -- One primary provider per channel per tenant (or system)
    CONSTRAINT providers_unique_primary UNIQUE NULLS NOT DISTINCT (tenant_id, channel, is_primary)
        WHERE is_primary = TRUE
);

CREATE INDEX IF NOT EXISTS idx_providers_tenant ON notify.providers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_providers_channel ON notify.providers(channel, is_active);
CREATE INDEX IF NOT EXISTS idx_providers_key ON notify.providers(provider_key);

COMMENT ON TABLE notify.providers IS
'Notification provider configuration. Supports multiple providers per channel with failover.';
COMMENT ON COLUMN notify.providers.config IS
'Provider-specific configuration. Sensitive values stored as references to secrets manager.';


-- =============================================================================
-- TABLE: notify.provider_templates
-- =============================================================================
-- Provider-specific template mappings (WhatsApp pre-approved templates)

CREATE TABLE IF NOT EXISTS notify.provider_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL = system default
    provider_id UUID NOT NULL REFERENCES notify.providers(id) ON DELETE CASCADE,

    -- Template identification
    template_key VARCHAR(100) NOT NULL,  -- Internal key (PORTAL_INVITE, REMINDER_24H)
    language VARCHAR(10) NOT NULL DEFAULT 'de',

    -- WhatsApp-specific (Meta Cloud API)
    wa_template_name VARCHAR(255) NOT NULL,  -- Meta-approved template name
    wa_template_namespace VARCHAR(255),  -- Optional namespace
    wa_template_category VARCHAR(50) DEFAULT 'UTILITY',  -- UTILITY, MARKETING, AUTHENTICATION

    -- Template approval status (WhatsApp requires pre-approval)
    approval_status VARCHAR(30) DEFAULT 'PENDING',
    -- PENDING, APPROVED, REJECTED, DISABLED, IN_APPEAL
    approval_status_at TIMESTAMPTZ,
    rejection_reason TEXT,

    -- Variable mapping (internal param names -> WhatsApp component indices)
    variable_mapping JSONB DEFAULT '{}',
    -- Example: {"driver_name": {"type": "body", "index": 0}, "portal_url": {"type": "body", "index": 1}}

    -- Content preview (for admin UI, not used in sending)
    preview_body TEXT,
    preview_header TEXT,
    preview_footer TEXT,

    -- Configuration
    is_active BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT provider_templates_approval_check CHECK (
        approval_status IN ('PENDING', 'APPROVED', 'REJECTED', 'DISABLED', 'IN_APPEAL')
    ),
    CONSTRAINT provider_templates_category_check CHECK (
        wa_template_category IN ('UTILITY', 'MARKETING', 'AUTHENTICATION')
    ),
    -- One template per key/language per provider
    CONSTRAINT provider_templates_unique_key UNIQUE (provider_id, template_key, language)
);

CREATE INDEX IF NOT EXISTS idx_provider_templates_provider ON notify.provider_templates(provider_id);
CREATE INDEX IF NOT EXISTS idx_provider_templates_key ON notify.provider_templates(template_key, language);
CREATE INDEX IF NOT EXISTS idx_provider_templates_approved ON notify.provider_templates(provider_id, approval_status)
    WHERE approval_status = 'APPROVED' AND is_active = TRUE;

COMMENT ON TABLE notify.provider_templates IS
'Provider-specific template configurations. WhatsApp templates require Meta pre-approval.';


-- =============================================================================
-- TABLE: notify.webhook_events
-- =============================================================================
-- Raw webhook events from providers (for debugging and audit)

CREATE TABLE IF NOT EXISTS notify.webhook_events (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    provider_key VARCHAR(50) NOT NULL,

    -- Event identification
    event_type VARCHAR(50),  -- message.sent, message.delivered, message.read, message.failed
    provider_message_id VARCHAR(255),
    provider_timestamp TIMESTAMPTZ,

    -- Raw payload (full webhook body)
    raw_payload JSONB NOT NULL,

    -- Processing status
    processed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMPTZ,
    outbox_id UUID,  -- Link to notification_outbox if matched

    -- Verification
    signature_valid BOOLEAN,
    verification_details JSONB,

    -- Error handling
    processing_error TEXT,

    -- Timing
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_provider_msg ON notify.webhook_events(provider_message_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_unprocessed ON notify.webhook_events(processed, received_at)
    WHERE processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_webhook_events_provider ON notify.webhook_events(provider_key, received_at DESC);

COMMENT ON TABLE notify.webhook_events IS
'Raw webhook events from notification providers. Retained for debugging and audit.';


-- =============================================================================
-- TABLE: notify.dm_queue
-- =============================================================================
-- WhatsApp DM-specific queue with consent enforcement

CREATE TABLE IF NOT EXISTS notify.dm_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Target driver
    driver_id UUID NOT NULL,
    driver_contact_id UUID NOT NULL REFERENCES masterdata.driver_contacts(id),

    -- Message details
    template_key VARCHAR(100) NOT NULL,
    template_params JSONB DEFAULT '{}',
    correlation_id UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Provider selection
    provider_id UUID REFERENCES notify.providers(id),
    provider_key VARCHAR(50),

    -- Consent verification (fail-fast)
    consent_verified BOOLEAN NOT NULL DEFAULT FALSE,
    consent_verified_at TIMESTAMPTZ,
    consent_check_result JSONB,  -- Result from verify_contact_for_dm

    -- Status
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    -- PENDING -> CONSENT_CHECK -> QUEUED -> SENDING -> SENT -> DELIVERED | FAILED | BLOCKED

    -- Blocking reasons
    blocked_reason VARCHAR(100),  -- NO_CONSENT, OPTED_OUT, INVALID_PHONE, RATE_LIMITED

    -- Delivery tracking
    outbox_id UUID REFERENCES notify.notification_outbox(id),
    delivery_ref VARCHAR(255),  -- Provider's delivery reference

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    queued_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT dm_queue_status_check CHECK (
        status IN ('PENDING', 'CONSENT_CHECK', 'QUEUED', 'SENDING', 'SENT', 'DELIVERED', 'FAILED', 'BLOCKED')
    )
);

CREATE INDEX IF NOT EXISTS idx_dm_queue_tenant ON notify.dm_queue(tenant_id);
CREATE INDEX IF NOT EXISTS idx_dm_queue_driver ON notify.dm_queue(driver_id);
CREATE INDEX IF NOT EXISTS idx_dm_queue_status ON notify.dm_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_dm_queue_correlation ON notify.dm_queue(correlation_id);

COMMENT ON TABLE notify.dm_queue IS
'WhatsApp DM queue with mandatory consent verification before sending.';


-- =============================================================================
-- ENABLE RLS
-- =============================================================================

ALTER TABLE notify.providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.providers FORCE ROW LEVEL SECURITY;

ALTER TABLE notify.provider_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.provider_templates FORCE ROW LEVEL SECURITY;

ALTER TABLE notify.webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.webhook_events FORCE ROW LEVEL SECURITY;

ALTER TABLE notify.dm_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.dm_queue FORCE ROW LEVEL SECURITY;


-- =============================================================================
-- RLS POLICIES
-- =============================================================================

-- Providers: tenant-specific or system-wide (NULL tenant_id)
CREATE POLICY providers_access ON notify.providers
    FOR ALL
    USING (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER
    );

-- Provider templates: follow provider access
CREATE POLICY provider_templates_access ON notify.provider_templates
    FOR ALL
    USING (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER
    );

-- Webhook events: no tenant isolation (system-level processing)
-- Platform role required
CREATE POLICY webhook_events_platform ON notify.webhook_events
    FOR ALL
    USING (TRUE);  -- Webhook processing is system-level

-- DM queue: tenant isolation
CREATE POLICY dm_queue_tenant ON notify.dm_queue
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);


-- =============================================================================
-- GRANTS
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT SELECT ON notify.providers TO solvereign_api;
        GRANT SELECT ON notify.provider_templates TO solvereign_api;
        GRANT SELECT, INSERT, UPDATE ON notify.dm_queue TO solvereign_api;
        -- webhook_events is platform-only
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT ALL ON notify.providers TO solvereign_platform;
        GRANT ALL ON notify.provider_templates TO solvereign_platform;
        GRANT ALL ON notify.webhook_events TO solvereign_platform;
        GRANT ALL ON notify.dm_queue TO solvereign_platform;
        GRANT USAGE ON SEQUENCE notify.webhook_events_id_seq TO solvereign_platform;
    END IF;
END $$;


-- =============================================================================
-- TRIGGERS: Auto-update updated_at
-- =============================================================================

CREATE TRIGGER tr_providers_updated_at
    BEFORE UPDATE ON notify.providers
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();

CREATE TRIGGER tr_provider_templates_updated_at
    BEFORE UPDATE ON notify.provider_templates
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();

CREATE TRIGGER tr_dm_queue_updated_at
    BEFORE UPDATE ON notify.dm_queue
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();


-- =============================================================================
-- FUNCTION: get_provider_for_channel
-- =============================================================================
-- Get the primary active provider for a channel

CREATE OR REPLACE FUNCTION notify.get_provider_for_channel(
    p_tenant_id INTEGER,
    p_channel VARCHAR
)
RETURNS TABLE (
    provider_id UUID,
    provider_key VARCHAR,
    config JSONB,
    rate_limit_per_minute INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.provider_key,
        p.config,
        p.rate_limit_per_minute
    FROM notify.providers p
    WHERE (p.tenant_id = p_tenant_id OR p.tenant_id IS NULL)
      AND p.channel = p_channel
      AND p.is_active = TRUE
      AND p.health_status != 'UNHEALTHY'
    ORDER BY
        p.tenant_id NULLS LAST,  -- Tenant-specific first
        p.is_primary DESC,       -- Primary first
        p.priority ASC,          -- Then by priority
        p.consecutive_failures ASC  -- Healthiest first
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION notify.get_provider_for_channel IS
'Get the best available provider for a channel. Tenant-specific > system default, primary > backup.';


-- =============================================================================
-- FUNCTION: get_template_for_provider
-- =============================================================================
-- Get approved template for a provider

CREATE OR REPLACE FUNCTION notify.get_template_for_provider(
    p_provider_id UUID,
    p_template_key VARCHAR,
    p_language VARCHAR DEFAULT 'de'
)
RETURNS TABLE (
    template_id UUID,
    wa_template_name VARCHAR,
    wa_template_namespace VARCHAR,
    variable_mapping JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        pt.id,
        pt.wa_template_name,
        pt.wa_template_namespace,
        pt.variable_mapping
    FROM notify.provider_templates pt
    WHERE pt.provider_id = p_provider_id
      AND pt.template_key = p_template_key
      AND pt.language = p_language
      AND pt.approval_status = 'APPROVED'
      AND pt.is_active = TRUE;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION notify.get_template_for_provider IS
'Get approved WhatsApp template for a provider. Only returns APPROVED templates.';


-- =============================================================================
-- FUNCTION: queue_whatsapp_dm
-- =============================================================================
-- Queue a WhatsApp DM with consent verification

CREATE OR REPLACE FUNCTION notify.queue_whatsapp_dm(
    p_tenant_id INTEGER,
    p_driver_id UUID,
    p_template_key VARCHAR,
    p_template_params JSONB DEFAULT '{}',
    p_correlation_id UUID DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_contact RECORD;
    v_consent_result JSONB;
    v_dm_id UUID;
    v_status VARCHAR;
    v_blocked_reason VARCHAR;
BEGIN
    -- Get driver contact
    SELECT * INTO v_contact
    FROM masterdata.driver_contacts
    WHERE tenant_id = p_tenant_id
      AND driver_id = p_driver_id;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error_code', 'DRIVER_CONTACT_NOT_FOUND',
            'driver_id', p_driver_id
        );
    END IF;

    -- Verify consent
    v_consent_result := masterdata.verify_contact_for_dm(p_tenant_id, p_driver_id);

    IF NOT (v_consent_result->>'can_send')::BOOLEAN THEN
        v_status := 'BLOCKED';
        v_blocked_reason := v_consent_result->'errors'->>0;  -- First error
    ELSE
        v_status := 'QUEUED';
        v_blocked_reason := NULL;
    END IF;

    -- Insert into queue
    INSERT INTO notify.dm_queue (
        tenant_id, driver_id, driver_contact_id,
        template_key, template_params, correlation_id,
        consent_verified, consent_verified_at, consent_check_result,
        status, blocked_reason,
        queued_at
    ) VALUES (
        p_tenant_id, p_driver_id, v_contact.id,
        p_template_key, p_template_params,
        COALESCE(p_correlation_id, gen_random_uuid()),
        (v_consent_result->>'can_send')::BOOLEAN, NOW(), v_consent_result,
        v_status, v_blocked_reason,
        CASE WHEN v_status = 'QUEUED' THEN NOW() ELSE NULL END
    )
    RETURNING id INTO v_dm_id;

    RETURN jsonb_build_object(
        'success', v_status = 'QUEUED',
        'dm_id', v_dm_id,
        'status', v_status,
        'blocked_reason', v_blocked_reason,
        'driver_id', p_driver_id,
        'template_key', p_template_key
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION notify.queue_whatsapp_dm IS
'Queue a WhatsApp DM with mandatory consent verification. Returns blocked status if consent fails.';


-- =============================================================================
-- FUNCTION: record_provider_health
-- =============================================================================
-- Update provider health after a send attempt

CREATE OR REPLACE FUNCTION notify.record_provider_health(
    p_provider_id UUID,
    p_success BOOLEAN,
    p_error_code VARCHAR DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    IF p_success THEN
        UPDATE notify.providers
        SET
            last_success_at = NOW(),
            consecutive_failures = 0,
            health_status = 'HEALTHY',
            current_minute_count = current_minute_count + 1,
            current_day_count = current_day_count + 1,
            updated_at = NOW()
        WHERE id = p_provider_id;
    ELSE
        UPDATE notify.providers
        SET
            last_failure_at = NOW(),
            consecutive_failures = consecutive_failures + 1,
            health_status = CASE
                WHEN consecutive_failures >= 10 THEN 'UNHEALTHY'
                WHEN consecutive_failures >= 3 THEN 'DEGRADED'
                ELSE health_status
            END,
            updated_at = NOW()
        WHERE id = p_provider_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION notify.record_provider_health IS
'Update provider health metrics after send attempt. Auto-degrades after consecutive failures.';


-- =============================================================================
-- FUNCTION: reset_rate_limits
-- =============================================================================
-- Reset provider rate limit counters (called by scheduler)

CREATE OR REPLACE FUNCTION notify.reset_rate_limits()
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Reset minute counters (if last reset > 1 minute ago)
    UPDATE notify.providers
    SET
        current_minute_count = 0,
        rate_limit_reset_at = NOW()
    WHERE rate_limit_reset_at IS NULL
       OR rate_limit_reset_at < NOW() - INTERVAL '1 minute';

    GET DIAGNOSTICS v_count = ROW_COUNT;

    -- Reset day counters at midnight UTC
    IF EXTRACT(HOUR FROM NOW() AT TIME ZONE 'UTC') = 0 THEN
        UPDATE notify.providers SET current_day_count = 0;
    END IF;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- SEED: Default WhatsApp Meta provider (system-wide)
-- =============================================================================

INSERT INTO notify.providers (
    tenant_id, provider_key, display_name, channel,
    is_primary, is_active, priority,
    config, rate_limit_per_minute, rate_limit_per_day,
    health_status
) VALUES (
    NULL,  -- System default
    'whatsapp_meta',
    'WhatsApp Cloud API (Meta)',
    'WHATSAPP',
    TRUE,  -- Primary
    FALSE,  -- Inactive until configured
    10,
    jsonb_build_object(
        'api_version', 'v18.0',
        'phone_number_id', 'CONFIGURE_ME',
        'business_account_id', 'CONFIGURE_ME',
        'access_token_env', 'WHATSAPP_META_ACCESS_TOKEN',
        'webhook_verify_token_env', 'WHATSAPP_META_WEBHOOK_VERIFY_TOKEN'
    ),
    80,   -- Meta default
    1000,
    'UNKNOWN'
)
ON CONFLICT DO NOTHING;

-- Seed ClawdBot as optional secondary
INSERT INTO notify.providers (
    tenant_id, provider_key, display_name, channel,
    is_primary, is_active, priority,
    config, health_status
) VALUES (
    NULL,
    'whatsapp_clawdbot',
    'ClawdBot WhatsApp',
    'WHATSAPP',
    FALSE,  -- Not primary
    FALSE,  -- Inactive until configured
    50,     -- Lower priority (higher number = backup)
    jsonb_build_object(
        'api_url', 'https://api.clawdbot.com/v1',
        'api_key_env', 'CLAWDBOT_API_KEY',
        'supports_groups', TRUE
    ),
    'UNKNOWN'
)
ON CONFLICT DO NOTHING;


-- =============================================================================
-- SEED: Default templates for whatsapp_meta
-- =============================================================================

DO $$
DECLARE
    v_provider_id UUID;
BEGIN
    SELECT id INTO v_provider_id
    FROM notify.providers
    WHERE provider_key = 'whatsapp_meta' AND tenant_id IS NULL;

    IF v_provider_id IS NOT NULL THEN
        INSERT INTO notify.provider_templates (
            tenant_id, provider_id, template_key, language,
            wa_template_name, wa_template_category,
            variable_mapping, preview_body, approval_status
        ) VALUES
        -- Portal invite (German)
        (NULL, v_provider_id, 'PORTAL_INVITE', 'de',
            'portal_invite_v1', 'UTILITY',
            '{"driver_name": {"type": "body", "index": 0}, "portal_url": {"type": "body", "index": 1}}',
            'Hallo {{1}}, Ihr neuer Schichtplan ist verfuegbar. Bitte bestaetigen Sie hier: {{2}}',
            'PENDING'),
        -- Reminder (German)
        (NULL, v_provider_id, 'REMINDER_24H', 'de',
            'reminder_24h_v1', 'UTILITY',
            '{"driver_name": {"type": "body", "index": 0}, "portal_url": {"type": "body", "index": 1}}',
            'Erinnerung {{1}}: Ihr Schichtplan wartet noch auf Bestaetigung. {{2}}',
            'PENDING'),
        -- Coverage offer (German)
        (NULL, v_provider_id, 'COVERAGE_OFFER', 'de',
            'coverage_offer_v1', 'UTILITY',
            '{"driver_name": {"type": "body", "index": 0}, "shift_date": {"type": "body", "index": 1}, "response_url": {"type": "body", "index": 2}}',
            'Hallo {{1}}, am {{2}} ist eine Schicht verfuegbar. Interesse? {{3}}',
            'PENDING')
        ON CONFLICT (provider_id, template_key, language) DO NOTHING;
    END IF;
END $$;


-- =============================================================================
-- VERIFICATION FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.verify_provider_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: RLS enabled on providers
    RETURN QUERY
    SELECT
        'rls_providers'::TEXT,
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END,
        'notify.providers has RLS enabled'::TEXT
    FROM pg_class WHERE oid = 'notify.providers'::regclass;

    -- Check 2: RLS enabled on provider_templates
    RETURN QUERY
    SELECT
        'rls_templates'::TEXT,
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END,
        'notify.provider_templates has RLS enabled'::TEXT
    FROM pg_class WHERE oid = 'notify.provider_templates'::regclass;

    -- Check 3: RLS enabled on dm_queue
    RETURN QUERY
    SELECT
        'rls_dm_queue'::TEXT,
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END,
        'notify.dm_queue has RLS enabled'::TEXT
    FROM pg_class WHERE oid = 'notify.dm_queue'::regclass;

    -- Check 4: At least one WhatsApp provider exists
    RETURN QUERY
    SELECT
        'whatsapp_provider_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s WhatsApp providers configured', COUNT(*))::TEXT
    FROM notify.providers WHERE channel = 'WHATSAPP';

    -- Check 5: Primary providers defined
    RETURN QUERY
    SELECT
        'primary_providers'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s primary providers defined', COUNT(*))::TEXT
    FROM notify.providers WHERE is_primary = TRUE;

    -- Check 6: Templates have valid variable mappings
    RETURN QUERY
    SELECT
        'valid_template_mappings'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s templates with empty variable_mapping', COUNT(*))::TEXT
    FROM notify.provider_templates
    WHERE variable_mapping = '{}' OR variable_mapping IS NULL;

    -- Check 7: Functions exist
    RETURN QUERY
    SELECT
        'functions_exist'::TEXT,
        CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/4 provider functions exist', COUNT(*))::TEXT
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'notify'
      AND p.proname IN (
          'get_provider_for_channel', 'get_template_for_provider',
          'queue_whatsapp_dm', 'record_provider_health'
      );

END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION notify.verify_provider_integrity IS
'Verify WhatsApp provider configuration integrity.';


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 056: WhatsApp Provider Abstraction COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'TABLES:';
    RAISE NOTICE '  - notify.providers (provider configuration)';
    RAISE NOTICE '  - notify.provider_templates (WhatsApp templates)';
    RAISE NOTICE '  - notify.webhook_events (raw webhook storage)';
    RAISE NOTICE '  - notify.dm_queue (DM queue with consent)';
    RAISE NOTICE '';
    RAISE NOTICE 'PROVIDERS:';
    RAISE NOTICE '  - whatsapp_meta (PRIMARY) - Meta Cloud API';
    RAISE NOTICE '  - whatsapp_clawdbot (OPTIONAL) - ClawdBot backup';
    RAISE NOTICE '';
    RAISE NOTICE 'FUNCTIONS:';
    RAISE NOTICE '  - get_provider_for_channel(tenant, channel)';
    RAISE NOTICE '  - get_template_for_provider(provider, key, lang)';
    RAISE NOTICE '  - queue_whatsapp_dm(tenant, driver, template, params)';
    RAISE NOTICE '  - record_provider_health(provider, success, error)';
    RAISE NOTICE '';
    RAISE NOTICE 'CONFIGURATION:';
    RAISE NOTICE '  - WHATSAPP_META_ACCESS_TOKEN (env var)';
    RAISE NOTICE '  - WHATSAPP_META_WEBHOOK_VERIFY_TOKEN (env var)';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM notify.verify_provider_integrity();';
    RAISE NOTICE '============================================================';
END $$;

COMMIT;
