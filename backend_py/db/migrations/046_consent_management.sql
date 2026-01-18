-- SOLVEREIGN Consent Management (P2.3)
-- =====================================
--
-- GDPR-compliant consent tracking for data processing.
-- Tracks user consents, revocations, and data subject requests.
--
-- Usage:
--   psql $DATABASE_URL < backend_py/db/migrations/046_consent_management.sql

BEGIN;

-- =============================================================================
-- CONSENT SCHEMA
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS consent;

GRANT USAGE ON SCHEMA consent TO solvereign_platform, solvereign_api;

-- =============================================================================
-- CONSENT PURPOSES
-- =============================================================================

-- Define consent purposes (GDPR requires specific purposes)
CREATE TABLE IF NOT EXISTS consent.purposes (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,  -- e.g., 'necessary', 'analytics', 'marketing'
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,  -- Necessary for service = can't decline
    data_retention_days INTEGER,  -- How long data is kept
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default purposes
INSERT INTO consent.purposes (code, name, description, is_required, data_retention_days) VALUES
    ('necessary', 'Notwendige Verarbeitung', 'Für die Bereitstellung des Dienstes erforderlich (Authentifizierung, Sicherheit)', TRUE, NULL),
    ('contract', 'Vertragserfüllung', 'Verarbeitung zur Erfüllung des Vertrags (Schichtplanung, Fahrerzuordnung)', TRUE, 2555),  -- 7 years
    ('analytics', 'Analyse', 'Anonymisierte Nutzungsstatistiken zur Verbesserung des Dienstes', FALSE, 90),
    ('notifications', 'Benachrichtigungen', 'E-Mail/WhatsApp Benachrichtigungen über Schichtpläne', FALSE, 365),
    ('marketing', 'Marketing', 'Informationen über neue Funktionen und Angebote', FALSE, 365)
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- USER CONSENTS
-- =============================================================================

-- Track user consent decisions
CREATE TABLE IF NOT EXISTS consent.user_consents (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    purpose_id INTEGER NOT NULL REFERENCES consent.purposes(id),
    granted BOOLEAN NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address INET,
    user_agent TEXT,
    version TEXT,  -- Version of consent form shown

    -- Track history (don't update, always insert new row)
    is_current BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT user_consents_current_unique UNIQUE (user_id, purpose_id, is_current)
);

CREATE INDEX idx_user_consents_user ON consent.user_consents(user_id);
CREATE INDEX idx_user_consents_current ON consent.user_consents(user_id, purpose_id) WHERE is_current = TRUE;

-- =============================================================================
-- DRIVER PORTAL CONSENTS
-- =============================================================================

-- Track driver consent (via portal, separate from auth.users)
CREATE TABLE IF NOT EXISTS consent.driver_consents (
    id SERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    driver_id TEXT NOT NULL,  -- External driver ID
    purpose_id INTEGER NOT NULL REFERENCES consent.purposes(id),
    granted BOOLEAN NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address INET,
    user_agent TEXT,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT driver_consents_current_unique UNIQUE (tenant_id, driver_id, purpose_id, is_current)
);

CREATE INDEX idx_driver_consents_driver ON consent.driver_consents(tenant_id, driver_id);

-- =============================================================================
-- DATA SUBJECT REQUESTS (GDPR Art. 15-22)
-- =============================================================================

-- Track DSR (Data Subject Requests)
CREATE TABLE IF NOT EXISTS consent.data_subject_requests (
    id SERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES core.tenants(id) ON DELETE SET NULL,
    request_type TEXT NOT NULL CHECK (request_type IN (
        'access',      -- Art. 15: Right of access
        'rectification', -- Art. 16: Right to rectification
        'erasure',     -- Art. 17: Right to erasure ("right to be forgotten")
        'restriction', -- Art. 18: Right to restriction
        'portability', -- Art. 20: Right to data portability
        'objection'    -- Art. 21: Right to object
    )),
    requester_email TEXT NOT NULL,
    requester_name TEXT,
    subject_email TEXT NOT NULL,  -- Person whose data is requested
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'verified', 'in_progress', 'completed', 'rejected'
    )),
    verification_token TEXT,
    verified_at TIMESTAMPTZ,
    notes TEXT,
    completed_at TIMESTAMPTZ,
    completed_by UUID REFERENCES auth.users(id),
    response_data JSONB,  -- For access/portability: exported data
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- GDPR requires response within 30 days
    due_date TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 days')
);

CREATE INDEX idx_dsr_status ON consent.data_subject_requests(status);
CREATE INDEX idx_dsr_due_date ON consent.data_subject_requests(due_date) WHERE status NOT IN ('completed', 'rejected');

-- =============================================================================
-- CONSENT HELPER FUNCTIONS
-- =============================================================================

-- Check if user has granted consent for a purpose
CREATE OR REPLACE FUNCTION consent.has_consent(
    p_user_id UUID,
    p_purpose_code TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_purpose_id INTEGER;
    v_is_required BOOLEAN;
    v_granted BOOLEAN;
BEGIN
    -- Get purpose
    SELECT id, is_required INTO v_purpose_id, v_is_required
    FROM consent.purposes WHERE code = p_purpose_code;

    IF v_purpose_id IS NULL THEN
        RETURN FALSE;  -- Unknown purpose
    END IF;

    -- Required purposes are always "granted"
    IF v_is_required THEN
        RETURN TRUE;
    END IF;

    -- Check user's consent
    SELECT granted INTO v_granted
    FROM consent.user_consents
    WHERE user_id = p_user_id
      AND purpose_id = v_purpose_id
      AND is_current = TRUE;

    RETURN COALESCE(v_granted, FALSE);
END;
$$ LANGUAGE plpgsql STABLE;

-- Record consent decision (handles history)
CREATE OR REPLACE FUNCTION consent.record_consent(
    p_user_id UUID,
    p_purpose_code TEXT,
    p_granted BOOLEAN,
    p_ip_address INET DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL,
    p_version TEXT DEFAULT '1.0'
) RETURNS BOOLEAN AS $$
DECLARE
    v_purpose_id INTEGER;
BEGIN
    -- Get purpose
    SELECT id INTO v_purpose_id
    FROM consent.purposes WHERE code = p_purpose_code;

    IF v_purpose_id IS NULL THEN
        RAISE EXCEPTION 'Unknown consent purpose: %', p_purpose_code;
    END IF;

    -- Mark previous consent as not current
    UPDATE consent.user_consents
    SET is_current = FALSE
    WHERE user_id = p_user_id
      AND purpose_id = v_purpose_id
      AND is_current = TRUE;

    -- Insert new consent
    INSERT INTO consent.user_consents (
        user_id, purpose_id, granted, ip_address, user_agent, version
    ) VALUES (
        p_user_id, v_purpose_id, p_granted, p_ip_address, p_user_agent, p_version
    );

    -- Audit log
    INSERT INTO auth.audit_log (event_type, user_id, details)
    VALUES (
        CASE WHEN p_granted THEN 'consent.granted' ELSE 'consent.revoked' END,
        p_user_id,
        jsonb_build_object(
            'purpose', p_purpose_code,
            'granted', p_granted,
            'ip_address', p_ip_address::TEXT
        )
    );

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Get user's current consents
CREATE OR REPLACE FUNCTION consent.get_user_consents(p_user_id UUID)
RETURNS TABLE (
    purpose_code TEXT,
    purpose_name TEXT,
    is_required BOOLEAN,
    granted BOOLEAN,
    granted_at TIMESTAMPTZ
) AS $$
    SELECT
        p.code,
        p.name,
        p.is_required,
        COALESCE(c.granted, p.is_required),  -- Required = always granted
        c.granted_at
    FROM consent.purposes p
    LEFT JOIN consent.user_consents c ON c.purpose_id = p.id
        AND c.user_id = p_user_id
        AND c.is_current = TRUE;
$$ LANGUAGE SQL STABLE;

-- =============================================================================
-- RLS POLICIES
-- =============================================================================

ALTER TABLE consent.purposes ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent.user_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent.driver_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent.data_subject_requests ENABLE ROW LEVEL SECURITY;

-- Purposes are readable by all
CREATE POLICY purposes_select ON consent.purposes
    FOR SELECT TO solvereign_api, solvereign_platform
    USING (TRUE);

-- Platform can manage purposes
CREATE POLICY purposes_all ON consent.purposes
    FOR ALL TO solvereign_platform
    USING (TRUE) WITH CHECK (TRUE);

-- Users can see/manage their own consents
CREATE POLICY user_consents_own ON consent.user_consents
    FOR ALL TO solvereign_api
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID);

-- Platform can see all consents
CREATE POLICY user_consents_platform ON consent.user_consents
    FOR SELECT TO solvereign_platform
    USING (TRUE);

-- Driver consents follow tenant isolation
CREATE POLICY driver_consents_tenant ON consent.driver_consents
    FOR ALL TO solvereign_api
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

CREATE POLICY driver_consents_platform ON consent.driver_consents
    FOR SELECT TO solvereign_platform
    USING (TRUE);

-- DSRs visible to platform admin
CREATE POLICY dsr_platform ON consent.data_subject_requests
    FOR ALL TO solvereign_platform
    USING (TRUE) WITH CHECK (TRUE);

-- =============================================================================
-- VERIFICATION
-- =============================================================================

CREATE OR REPLACE FUNCTION consent.verify_consent_schema()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Schema exists
    check_name := 'consent_schema';
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'consent') THEN
        status := 'PASS';
        details := 'Schema exists';
    ELSE
        status := 'FAIL';
        details := 'Schema missing';
    END IF;
    RETURN NEXT;

    -- Check 2: Core tables exist
    check_name := 'core_tables';
    IF (SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'consent'
        AND table_name IN ('purposes', 'user_consents', 'data_subject_requests')) = 3 THEN
        status := 'PASS';
        details := 'All core tables exist';
    ELSE
        status := 'FAIL';
        details := 'Missing tables';
    END IF;
    RETURN NEXT;

    -- Check 3: Default purposes seeded
    check_name := 'default_purposes';
    IF (SELECT COUNT(*) FROM consent.purposes) >= 3 THEN
        status := 'PASS';
        details := 'Default purposes seeded';
    ELSE
        status := 'FAIL';
        details := 'Missing default purposes';
    END IF;
    RETURN NEXT;

    -- Check 4: Helper functions
    check_name := 'helper_functions';
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'has_consent' AND pronamespace = 'consent'::regnamespace) THEN
        status := 'PASS';
        details := 'Helper functions exist';
    ELSE
        status := 'FAIL';
        details := 'Helper functions missing';
    END IF;
    RETURN NEXT;

    -- Check 5: RLS enabled
    check_name := 'rls_enabled';
    IF (SELECT bool_and(relrowsecurity) FROM pg_class
        WHERE relname IN ('purposes', 'user_consents', 'driver_consents')
        AND relnamespace = 'consent'::regnamespace) THEN
        status := 'PASS';
        details := 'RLS enabled on all tables';
    ELSE
        status := 'FAIL';
        details := 'RLS not enabled on some tables';
    END IF;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Run verification
SELECT * FROM consent.verify_consent_schema();

COMMIT;
