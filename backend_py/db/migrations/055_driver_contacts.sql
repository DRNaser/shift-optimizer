-- =============================================================================
-- Migration 055: Driver Contacts - Canonical Contact Data for WhatsApp DMs
-- =============================================================================
-- Purpose: Store driver contact information with consent tracking for WhatsApp
--          communications. Phone numbers stored in E.164 format.
--
-- Key Principle: All outbound WhatsApp DMs require consent_whatsapp = TRUE.
--                No consent = no message (fail fast).
--
-- RLS: All tables have tenant isolation via RLS policies.
--
-- Run:
--   psql $DATABASE_URL < backend_py/db/migrations/055_driver_contacts.sql
-- =============================================================================

BEGIN;

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('055', 'Driver Contacts - canonical contact data with WhatsApp consent', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- TABLE: driver_contacts
-- =============================================================================
-- Canonical driver contact information with consent tracking

CREATE TABLE IF NOT EXISTS masterdata.driver_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID REFERENCES masterdata.md_sites(id) ON DELETE SET NULL,

    -- Driver identity (link to MDL or pack-specific driver table)
    driver_id UUID NOT NULL,  -- Canonical driver UUID from MDL
    driver_external_id VARCHAR(255),  -- Original external ID (for reference)
    display_name VARCHAR(255) NOT NULL,

    -- Contact information
    phone_e164 VARCHAR(20) NOT NULL,  -- E.164 format: +436641234567
    phone_hash CHAR(64) GENERATED ALWAYS AS (
        encode(sha256(phone_e164::bytea), 'hex')
    ) STORED,  -- For dedup/privacy lookups

    -- Consent tracking (GDPR compliant)
    consent_whatsapp BOOLEAN NOT NULL DEFAULT FALSE,
    consent_whatsapp_at TIMESTAMPTZ,  -- When consent was given
    consent_source VARCHAR(100),  -- PORTAL, APP, MANUAL, IMPORT
    opt_out_at TIMESTAMPTZ,  -- If driver opted out
    opt_out_reason VARCHAR(255),  -- Optional reason

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    -- active: can be contacted (if consent=true)
    -- inactive: temporarily unavailable
    -- blocked: permanently blocked (e.g., invalid number)

    -- Tracking
    last_contacted_at TIMESTAMPTZ,  -- Last successful contact
    contact_attempt_count INTEGER DEFAULT 0,
    last_error_at TIMESTAMPTZ,
    last_error_code VARCHAR(50),

    -- Metadata
    department VARCHAR(100),  -- Optional grouping
    notes TEXT,  -- Admin notes
    metadata JSONB DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT driver_contacts_status_check CHECK (
        status IN ('active', 'inactive', 'blocked')
    ),
    -- Unique phone per tenant (one contact per phone number per tenant)
    CONSTRAINT driver_contacts_unique_phone UNIQUE (tenant_id, phone_e164),
    -- Unique driver per tenant (one contact record per driver per tenant)
    CONSTRAINT driver_contacts_unique_driver UNIQUE (tenant_id, driver_id)
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_driver_contacts_tenant
    ON masterdata.driver_contacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_driver_contacts_driver
    ON masterdata.driver_contacts(tenant_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_driver_contacts_phone_hash
    ON masterdata.driver_contacts(phone_hash);
CREATE INDEX IF NOT EXISTS idx_driver_contacts_consent
    ON masterdata.driver_contacts(tenant_id, consent_whatsapp)
    WHERE consent_whatsapp = TRUE AND status = 'active';
CREATE INDEX IF NOT EXISTS idx_driver_contacts_site
    ON masterdata.driver_contacts(site_id) WHERE site_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_driver_contacts_status
    ON masterdata.driver_contacts(tenant_id, status);

COMMENT ON TABLE masterdata.driver_contacts IS
'Canonical driver contact information with WhatsApp consent tracking.
Phone numbers stored in E.164 format (+CountryCode...).
consent_whatsapp=TRUE required for any outbound WhatsApp DM.';

COMMENT ON COLUMN masterdata.driver_contacts.phone_e164 IS
'Phone number in E.164 format (e.g., +436641234567). Validated on insert.';
COMMENT ON COLUMN masterdata.driver_contacts.consent_whatsapp IS
'Explicit WhatsApp consent. Must be TRUE to send any WhatsApp message.';
COMMENT ON COLUMN masterdata.driver_contacts.opt_out_at IS
'Timestamp when driver opted out. If set, no messages regardless of consent.';


-- =============================================================================
-- ENABLE RLS
-- =============================================================================

ALTER TABLE masterdata.driver_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE masterdata.driver_contacts FORCE ROW LEVEL SECURITY;


-- =============================================================================
-- RLS POLICIES
-- =============================================================================

CREATE POLICY driver_contacts_tenant_isolation ON masterdata.driver_contacts
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);


-- =============================================================================
-- GRANTS
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT SELECT, INSERT, UPDATE ON masterdata.driver_contacts TO solvereign_api;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT ALL ON masterdata.driver_contacts TO solvereign_platform;
    END IF;
END $$;


-- =============================================================================
-- TRIGGER: Auto-update updated_at
-- =============================================================================

CREATE TRIGGER tr_driver_contacts_updated_at
    BEFORE UPDATE ON masterdata.driver_contacts
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();


-- =============================================================================
-- FUNCTION: validate_e164_phone
-- =============================================================================
-- Validates phone number is in E.164 format

CREATE OR REPLACE FUNCTION masterdata.validate_e164_phone(
    p_phone VARCHAR
)
RETURNS BOOLEAN AS $$
BEGIN
    -- E.164 format: + followed by 1-15 digits
    -- Examples: +1234567890, +436641234567
    IF p_phone IS NULL OR p_phone = '' THEN
        RETURN FALSE;
    END IF;

    -- Must start with + followed by 7-15 digits (minimum country code + local)
    RETURN p_phone ~ '^\+[1-9][0-9]{6,14}$';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION masterdata.validate_e164_phone IS
'Validate phone number is in E.164 format (+CountryCode followed by digits).';


-- =============================================================================
-- FUNCTION: normalize_to_e164
-- =============================================================================
-- Attempts to normalize a phone number to E.164 format

CREATE OR REPLACE FUNCTION masterdata.normalize_to_e164(
    p_phone VARCHAR,
    p_default_country_code VARCHAR DEFAULT '+43'  -- Austria default
)
RETURNS VARCHAR AS $$
DECLARE
    v_clean VARCHAR;
    v_result VARCHAR;
BEGIN
    IF p_phone IS NULL OR p_phone = '' THEN
        RETURN NULL;
    END IF;

    -- Remove all non-digit characters except leading +
    v_clean := regexp_replace(p_phone, '[^0-9+]', '', 'g');

    -- If already starts with +, just validate
    IF v_clean LIKE '+%' THEN
        v_result := v_clean;
    -- If starts with 00, replace with +
    ELSIF v_clean LIKE '00%' THEN
        v_result := '+' || substring(v_clean from 3);
    -- If starts with 0, assume local number, add default country code
    ELSIF v_clean LIKE '0%' THEN
        v_result := p_default_country_code || substring(v_clean from 2);
    -- Otherwise, add + prefix
    ELSE
        v_result := '+' || v_clean;
    END IF;

    -- Validate result
    IF masterdata.validate_e164_phone(v_result) THEN
        RETURN v_result;
    ELSE
        RETURN NULL;  -- Invalid, return NULL
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION masterdata.normalize_to_e164 IS
'Normalize phone number to E.164 format. Returns NULL if normalization fails.
Default country code is +43 (Austria).';


-- =============================================================================
-- TRIGGER: Validate E.164 on insert/update
-- =============================================================================

CREATE OR REPLACE FUNCTION masterdata.trigger_validate_phone_e164()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT masterdata.validate_e164_phone(NEW.phone_e164) THEN
        RAISE EXCEPTION 'Invalid phone number format. Must be E.164 (e.g., +436641234567). Got: %',
            NEW.phone_e164;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_driver_contacts_validate_phone
    BEFORE INSERT OR UPDATE OF phone_e164 ON masterdata.driver_contacts
    FOR EACH ROW EXECUTE FUNCTION masterdata.trigger_validate_phone_e164();


-- =============================================================================
-- FUNCTION: upsert_driver_contact
-- =============================================================================
-- Idempotent upsert for driver contact

CREATE OR REPLACE FUNCTION masterdata.upsert_driver_contact(
    p_tenant_id INTEGER,
    p_driver_id UUID,
    p_display_name VARCHAR,
    p_phone_e164 VARCHAR,
    p_site_id UUID DEFAULT NULL,
    p_consent_whatsapp BOOLEAN DEFAULT FALSE,
    p_consent_source VARCHAR DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
)
RETURNS UUID AS $$
DECLARE
    v_contact_id UUID;
    v_normalized_phone VARCHAR;
BEGIN
    -- Normalize phone number
    v_normalized_phone := masterdata.normalize_to_e164(p_phone_e164);

    IF v_normalized_phone IS NULL THEN
        RAISE EXCEPTION 'Cannot normalize phone number to E.164: %', p_phone_e164;
    END IF;

    -- Upsert by driver_id (canonical key)
    INSERT INTO masterdata.driver_contacts (
        tenant_id, driver_id, display_name, phone_e164, site_id,
        consent_whatsapp, consent_whatsapp_at, consent_source, metadata
    ) VALUES (
        p_tenant_id, p_driver_id, p_display_name, v_normalized_phone, p_site_id,
        p_consent_whatsapp,
        CASE WHEN p_consent_whatsapp THEN NOW() ELSE NULL END,
        p_consent_source, p_metadata
    )
    ON CONFLICT (tenant_id, driver_id) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        phone_e164 = EXCLUDED.phone_e164,
        site_id = EXCLUDED.site_id,
        consent_whatsapp = EXCLUDED.consent_whatsapp,
        consent_whatsapp_at = CASE
            WHEN EXCLUDED.consent_whatsapp AND NOT masterdata.driver_contacts.consent_whatsapp
            THEN NOW()
            ELSE masterdata.driver_contacts.consent_whatsapp_at
        END,
        consent_source = COALESCE(EXCLUDED.consent_source, masterdata.driver_contacts.consent_source),
        metadata = masterdata.driver_contacts.metadata || EXCLUDED.metadata,
        updated_at = NOW()
    RETURNING id INTO v_contact_id;

    RETURN v_contact_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION masterdata.upsert_driver_contact IS
'Idempotent upsert for driver contact. Normalizes phone to E.164. Updates consent timestamp only on change.';


-- =============================================================================
-- FUNCTION: set_whatsapp_consent
-- =============================================================================
-- Set or revoke WhatsApp consent

CREATE OR REPLACE FUNCTION masterdata.set_whatsapp_consent(
    p_tenant_id INTEGER,
    p_driver_id UUID,
    p_consent BOOLEAN,
    p_source VARCHAR DEFAULT 'MANUAL'
)
RETURNS BOOLEAN AS $$
DECLARE
    v_updated BOOLEAN;
BEGIN
    IF p_consent THEN
        -- Grant consent
        UPDATE masterdata.driver_contacts
        SET
            consent_whatsapp = TRUE,
            consent_whatsapp_at = NOW(),
            consent_source = p_source,
            opt_out_at = NULL,  -- Clear any previous opt-out
            opt_out_reason = NULL,
            updated_at = NOW()
        WHERE tenant_id = p_tenant_id
          AND driver_id = p_driver_id;
    ELSE
        -- Revoke consent (opt-out)
        UPDATE masterdata.driver_contacts
        SET
            consent_whatsapp = FALSE,
            opt_out_at = NOW(),
            opt_out_reason = 'User revoked consent via ' || p_source,
            updated_at = NOW()
        WHERE tenant_id = p_tenant_id
          AND driver_id = p_driver_id;
    END IF;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated > 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION masterdata.set_whatsapp_consent IS
'Set or revoke WhatsApp consent for a driver. Tracks consent/opt-out timestamps.';


-- =============================================================================
-- FUNCTION: get_contactable_drivers
-- =============================================================================
-- Get drivers who can be contacted via WhatsApp

CREATE OR REPLACE FUNCTION masterdata.get_contactable_drivers(
    p_tenant_id INTEGER,
    p_driver_ids UUID[] DEFAULT NULL,
    p_site_id UUID DEFAULT NULL
)
RETURNS TABLE (
    driver_id UUID,
    display_name VARCHAR,
    phone_e164 VARCHAR,
    site_id UUID,
    consent_whatsapp_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.driver_id,
        dc.display_name,
        dc.phone_e164,
        dc.site_id,
        dc.consent_whatsapp_at
    FROM masterdata.driver_contacts dc
    WHERE dc.tenant_id = p_tenant_id
      AND dc.consent_whatsapp = TRUE
      AND dc.status = 'active'
      AND dc.opt_out_at IS NULL
      AND (p_driver_ids IS NULL OR dc.driver_id = ANY(p_driver_ids))
      AND (p_site_id IS NULL OR dc.site_id = p_site_id);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION masterdata.get_contactable_drivers IS
'Get drivers with valid WhatsApp consent who can be contacted.';


-- =============================================================================
-- FUNCTION: verify_contact_for_dm
-- =============================================================================
-- Verify a driver can receive a WhatsApp DM (fail fast check)

CREATE OR REPLACE FUNCTION masterdata.verify_contact_for_dm(
    p_tenant_id INTEGER,
    p_driver_id UUID
)
RETURNS JSONB AS $$
DECLARE
    v_contact RECORD;
    v_errors TEXT[] := ARRAY[]::TEXT[];
BEGIN
    SELECT * INTO v_contact
    FROM masterdata.driver_contacts
    WHERE tenant_id = p_tenant_id
      AND driver_id = p_driver_id;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'can_send', FALSE,
            'driver_id', p_driver_id,
            'errors', ARRAY['DRIVER_NOT_FOUND']
        );
    END IF;

    -- Check all conditions
    IF v_contact.status != 'active' THEN
        v_errors := array_append(v_errors, 'DRIVER_INACTIVE');
    END IF;

    IF NOT v_contact.consent_whatsapp THEN
        v_errors := array_append(v_errors, 'NO_WHATSAPP_CONSENT');
    END IF;

    IF v_contact.opt_out_at IS NOT NULL THEN
        v_errors := array_append(v_errors, 'DRIVER_OPTED_OUT');
    END IF;

    IF v_contact.phone_e164 IS NULL OR v_contact.phone_e164 = '' THEN
        v_errors := array_append(v_errors, 'NO_PHONE_NUMBER');
    END IF;

    RETURN jsonb_build_object(
        'can_send', array_length(v_errors, 1) IS NULL,
        'driver_id', p_driver_id,
        'display_name', v_contact.display_name,
        'phone_e164', CASE WHEN array_length(v_errors, 1) IS NULL THEN v_contact.phone_e164 ELSE NULL END,
        'errors', COALESCE(v_errors, ARRAY[]::TEXT[])
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION masterdata.verify_contact_for_dm IS
'Verify a driver can receive WhatsApp DM. Returns can_send=false with error codes if blocked.';


-- =============================================================================
-- AUDIT TRIGGER: Log consent changes
-- =============================================================================

CREATE OR REPLACE FUNCTION masterdata.audit_consent_change()
RETURNS TRIGGER AS $$
BEGIN
    -- Only audit consent changes
    IF OLD.consent_whatsapp IS DISTINCT FROM NEW.consent_whatsapp
       OR OLD.opt_out_at IS DISTINCT FROM NEW.opt_out_at THEN
        INSERT INTO auth.audit_log (
            tenant_id, user_id, action, entity_type, entity_id,
            changes, ip_hash
        ) VALUES (
            NEW.tenant_id,
            COALESCE(current_setting('app.current_user_id', TRUE), 'system'),
            CASE
                WHEN NEW.consent_whatsapp AND NOT COALESCE(OLD.consent_whatsapp, FALSE) THEN 'CONSENT_GRANTED'
                WHEN NOT NEW.consent_whatsapp AND OLD.consent_whatsapp THEN 'CONSENT_REVOKED'
                WHEN NEW.opt_out_at IS NOT NULL AND OLD.opt_out_at IS NULL THEN 'OPT_OUT'
                ELSE 'CONSENT_CHANGED'
            END,
            'driver_contact',
            NEW.id::TEXT,
            jsonb_build_object(
                'driver_id', NEW.driver_id,
                'display_name', NEW.display_name,
                'consent_whatsapp', jsonb_build_object('old', OLD.consent_whatsapp, 'new', NEW.consent_whatsapp),
                'consent_source', NEW.consent_source,
                'opt_out_at', NEW.opt_out_at
            ),
            COALESCE(current_setting('app.current_ip_hash', TRUE), 'unknown')
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_driver_contacts_audit_consent
    AFTER UPDATE ON masterdata.driver_contacts
    FOR EACH ROW EXECUTE FUNCTION masterdata.audit_consent_change();


-- =============================================================================
-- VERIFICATION FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION masterdata.verify_driver_contacts_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: RLS enabled
    RETURN QUERY
    SELECT
        'rls_enabled'::TEXT,
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END,
        'driver_contacts has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'masterdata.driver_contacts'::regclass;

    -- Check 2: Unique constraints exist
    RETURN QUERY
    SELECT
        'unique_constraints'::TEXT,
        CASE WHEN EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'driver_contacts_unique_phone'
        ) AND EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'driver_contacts_unique_driver'
        ) THEN 'PASS' ELSE 'FAIL' END,
        'Unique constraints on phone_e164 and driver_id exist'::TEXT;

    -- Check 3: All phones are valid E.164
    RETURN QUERY
    SELECT
        'valid_phone_formats'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s invalid phone numbers found', COUNT(*))::TEXT
    FROM masterdata.driver_contacts
    WHERE NOT masterdata.validate_e164_phone(phone_e164);

    -- Check 4: Consent timestamps consistent
    RETURN QUERY
    SELECT
        'consent_timestamps_consistent'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s records have consent=true but no consent_at timestamp', COUNT(*))::TEXT
    FROM masterdata.driver_contacts
    WHERE consent_whatsapp = TRUE AND consent_whatsapp_at IS NULL;

    -- Check 5: No active+opted-out conflicts
    RETURN QUERY
    SELECT
        'no_consent_conflicts'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s records have consent=true AND opt_out_at set', COUNT(*))::TEXT
    FROM masterdata.driver_contacts
    WHERE consent_whatsapp = TRUE AND opt_out_at IS NOT NULL;

    -- Check 6: tenant_id FK valid
    RETURN QUERY
    SELECT
        'tenant_fk_valid'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s orphaned tenant_id references', COUNT(*))::TEXT
    FROM masterdata.driver_contacts dc
    LEFT JOIN tenants t ON t.id = dc.tenant_id
    WHERE t.id IS NULL;

    -- Check 7: Functions exist
    RETURN QUERY
    SELECT
        'functions_exist'::TEXT,
        CASE WHEN COUNT(*) >= 5 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/5 required functions exist', COUNT(*))::TEXT
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'masterdata'
      AND p.proname IN (
          'validate_e164_phone', 'normalize_to_e164', 'upsert_driver_contact',
          'set_whatsapp_consent', 'get_contactable_drivers', 'verify_contact_for_dm'
      );

END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION masterdata.verify_driver_contacts_integrity IS
'Verify driver_contacts table integrity. Run after migration.';


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 055: Driver Contacts COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'TABLE: masterdata.driver_contacts';
    RAISE NOTICE '';
    RAISE NOTICE 'KEY FEATURES:';
    RAISE NOTICE '  - E.164 phone number validation';
    RAISE NOTICE '  - WhatsApp consent tracking (GDPR)';
    RAISE NOTICE '  - Opt-out support';
    RAISE NOTICE '  - Consent audit trail';
    RAISE NOTICE '';
    RAISE NOTICE 'FUNCTIONS:';
    RAISE NOTICE '  - validate_e164_phone(phone)';
    RAISE NOTICE '  - normalize_to_e164(phone, country_code)';
    RAISE NOTICE '  - upsert_driver_contact(...)';
    RAISE NOTICE '  - set_whatsapp_consent(tenant, driver, consent, source)';
    RAISE NOTICE '  - get_contactable_drivers(tenant, driver_ids, site_id)';
    RAISE NOTICE '  - verify_contact_for_dm(tenant, driver) -> {can_send, errors}';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM masterdata.verify_driver_contacts_integrity();';
    RAISE NOTICE '============================================================';
END $$;

COMMIT;
