-- SOLVEREIGN Legal Acceptance Tracking (P0.3 + P1.4)
-- ====================================================
--
-- Tracks user acceptance of legal documents (Terms, Privacy Policy).
-- Required for GDPR compliance and contract formation.
--
-- Usage:
--   psql $DATABASE_URL < backend_py/db/migrations/044_legal_acceptance.sql

BEGIN;

-- =============================================================================
-- LEGAL DOCUMENT VERSIONS
-- =============================================================================

-- Track published versions of legal documents
CREATE TABLE IF NOT EXISTS auth.legal_documents (
    id SERIAL PRIMARY KEY,
    document_type TEXT NOT NULL CHECK (document_type IN ('terms', 'privacy', 'dpa', 'cookie')),
    version TEXT NOT NULL,
    effective_date TIMESTAMPTZ NOT NULL,
    content_hash TEXT NOT NULL,  -- SHA-256 of document content for integrity
    summary TEXT,  -- Brief description of changes
    requires_acceptance BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Each document type can only have one version per effective date
    CONSTRAINT legal_documents_unique UNIQUE (document_type, version)
);

-- Index for looking up current version
CREATE INDEX idx_legal_documents_effective
    ON auth.legal_documents(document_type, effective_date DESC);

-- =============================================================================
-- USER ACCEPTANCES
-- =============================================================================

-- Track when users accepted which document versions
CREATE TABLE IF NOT EXISTS auth.legal_acceptances (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES auth.legal_documents(id),
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address INET,  -- For audit purposes
    user_agent TEXT,  -- For audit purposes

    -- Each user can only accept each document version once
    CONSTRAINT legal_acceptances_unique UNIQUE (user_id, document_id)
);

-- Index for checking user's acceptances
CREATE INDEX idx_legal_acceptances_user ON auth.legal_acceptances(user_id);
CREATE INDEX idx_legal_acceptances_document ON auth.legal_acceptances(document_id);

-- =============================================================================
-- TENANT ACCEPTANCES (for B2B contracts)
-- =============================================================================

-- Track tenant-level acceptance (DPA, Master Agreement)
CREATE TABLE IF NOT EXISTS auth.tenant_legal_acceptances (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES auth.legal_documents(id),
    accepted_by_user_id INTEGER NOT NULL REFERENCES auth.users(id),
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address INET,
    notes TEXT,  -- e.g., "Signed by CEO"

    -- Each tenant can only accept each document version once
    CONSTRAINT tenant_legal_acceptances_unique UNIQUE (tenant_id, document_id)
);

CREATE INDEX idx_tenant_legal_acceptances_tenant
    ON auth.tenant_legal_acceptances(tenant_id);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get current version of a document type
CREATE OR REPLACE FUNCTION auth.get_current_legal_document(
    p_document_type TEXT
) RETURNS auth.legal_documents AS $$
    SELECT *
    FROM auth.legal_documents
    WHERE document_type = p_document_type
      AND effective_date <= NOW()
    ORDER BY effective_date DESC
    LIMIT 1;
$$ LANGUAGE SQL STABLE;

-- Check if user has accepted current version
CREATE OR REPLACE FUNCTION auth.has_accepted_current(
    p_user_id INTEGER,
    p_document_type TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_doc auth.legal_documents;
BEGIN
    -- Get current document
    SELECT * INTO v_current_doc
    FROM auth.get_current_legal_document(p_document_type);

    IF v_current_doc IS NULL THEN
        RETURN TRUE;  -- No document = nothing to accept
    END IF;

    IF NOT v_current_doc.requires_acceptance THEN
        RETURN TRUE;  -- Document doesn't require acceptance
    END IF;

    -- Check if user has accepted
    RETURN EXISTS (
        SELECT 1 FROM auth.legal_acceptances
        WHERE user_id = p_user_id
          AND document_id = v_current_doc.id
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- Get all pending acceptances for a user
CREATE OR REPLACE FUNCTION auth.get_pending_acceptances(
    p_user_id INTEGER
) RETURNS TABLE (
    document_type TEXT,
    version TEXT,
    effective_date TIMESTAMPTZ,
    summary TEXT
) AS $$
    SELECT
        d.document_type,
        d.version,
        d.effective_date,
        d.summary
    FROM auth.legal_documents d
    WHERE d.requires_acceptance
      AND d.effective_date <= NOW()
      AND NOT EXISTS (
          SELECT 1 FROM auth.legal_acceptances a
          WHERE a.user_id = p_user_id
            AND a.document_id = d.id
      )
      -- Only get the latest version of each type
      AND d.id = (
          SELECT id FROM auth.legal_documents
          WHERE document_type = d.document_type
            AND effective_date <= NOW()
          ORDER BY effective_date DESC
          LIMIT 1
      );
$$ LANGUAGE SQL STABLE;

-- Record user acceptance
CREATE OR REPLACE FUNCTION auth.record_acceptance(
    p_user_id INTEGER,
    p_document_type TEXT,
    p_ip_address INET DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_doc auth.legal_documents;
BEGIN
    -- Get current document
    SELECT * INTO v_current_doc
    FROM auth.get_current_legal_document(p_document_type);

    IF v_current_doc IS NULL THEN
        RAISE EXCEPTION 'No document found for type: %', p_document_type;
    END IF;

    -- Insert acceptance (ignore if already exists)
    INSERT INTO auth.legal_acceptances (user_id, document_id, ip_address, user_agent)
    VALUES (p_user_id, v_current_doc.id, p_ip_address, p_user_agent)
    ON CONFLICT (user_id, document_id) DO NOTHING;

    -- Log to audit
    INSERT INTO auth.audit_log (event_type, user_id, details)
    VALUES (
        'legal.acceptance',
        p_user_id,
        jsonb_build_object(
            'document_type', p_document_type,
            'version', v_current_doc.version,
            'document_id', v_current_doc.id
        )
    );

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- SEED INITIAL DOCUMENTS
-- =============================================================================

-- Insert initial document versions
INSERT INTO auth.legal_documents (document_type, version, effective_date, content_hash, summary, requires_acceptance)
VALUES
    ('terms', '1.0.0', '2026-01-11', 'pending_hash', 'Initial Terms of Service', TRUE),
    ('privacy', '1.0.0', '2026-01-11', 'pending_hash', 'Initial Privacy Policy (GDPR compliant)', TRUE)
ON CONFLICT (document_type, version) DO NOTHING;

-- =============================================================================
-- RLS POLICIES
-- =============================================================================

-- Enable RLS
ALTER TABLE auth.legal_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.legal_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.tenant_legal_acceptances ENABLE ROW LEVEL SECURITY;

-- Legal documents are readable by all authenticated users
CREATE POLICY legal_documents_select ON auth.legal_documents
    FOR SELECT TO solvereign_api, solvereign_platform
    USING (TRUE);

-- Platform admin can manage documents
CREATE POLICY legal_documents_all ON auth.legal_documents
    FOR ALL TO solvereign_platform
    USING (TRUE)
    WITH CHECK (TRUE);

-- Users can see their own acceptances
CREATE POLICY legal_acceptances_select ON auth.legal_acceptances
    FOR SELECT TO solvereign_api
    USING (
        user_id = NULLIF(current_setting('app.current_user_id', true), '')::INTEGER
    );

-- Platform can see all acceptances
CREATE POLICY legal_acceptances_platform ON auth.legal_acceptances
    FOR ALL TO solvereign_platform
    USING (TRUE)
    WITH CHECK (TRUE);

-- API can insert acceptances for current user
CREATE POLICY legal_acceptances_insert ON auth.legal_acceptances
    FOR INSERT TO solvereign_api
    WITH CHECK (
        user_id = NULLIF(current_setting('app.current_user_id', true), '')::INTEGER
    );

-- Tenant acceptances follow tenant isolation
CREATE POLICY tenant_legal_acceptances_select ON auth.tenant_legal_acceptances
    FOR SELECT TO solvereign_api
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::INTEGER
    );

CREATE POLICY tenant_legal_acceptances_platform ON auth.tenant_legal_acceptances
    FOR ALL TO solvereign_platform
    USING (TRUE)
    WITH CHECK (TRUE);

-- =============================================================================
-- VERIFICATION
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.verify_legal_acceptance_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Tables exist
    check_name := 'legal_documents_table';
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'legal_documents') THEN
        status := 'PASS';
        details := 'Table exists';
    ELSE
        status := 'FAIL';
        details := 'Table missing';
    END IF;
    RETURN NEXT;

    -- Check 2: Acceptances table exists
    check_name := 'legal_acceptances_table';
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'legal_acceptances') THEN
        status := 'PASS';
        details := 'Table exists';
    ELSE
        status := 'FAIL';
        details := 'Table missing';
    END IF;
    RETURN NEXT;

    -- Check 3: Initial documents seeded
    check_name := 'initial_documents_seeded';
    IF (SELECT COUNT(*) FROM auth.legal_documents WHERE document_type IN ('terms', 'privacy')) >= 2 THEN
        status := 'PASS';
        details := 'Terms and Privacy documents exist';
    ELSE
        status := 'FAIL';
        details := 'Missing initial documents';
    END IF;
    RETURN NEXT;

    -- Check 4: RLS enabled
    check_name := 'rls_enabled';
    IF (SELECT relrowsecurity FROM pg_class WHERE relname = 'legal_documents' AND relnamespace = 'auth'::regnamespace) THEN
        status := 'PASS';
        details := 'RLS enabled on legal_documents';
    ELSE
        status := 'FAIL';
        details := 'RLS not enabled';
    END IF;
    RETURN NEXT;

    -- Check 5: Functions exist
    check_name := 'helper_functions';
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'has_accepted_current' AND pronamespace = 'auth'::regnamespace) THEN
        status := 'PASS';
        details := 'Helper functions created';
    ELSE
        status := 'FAIL';
        details := 'Helper functions missing';
    END IF;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Run verification
SELECT * FROM auth.verify_legal_acceptance_integrity();

COMMIT;
