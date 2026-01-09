-- ============================================================================
-- MIGRATION 022: Replay Protection Tables
-- ============================================================================
-- V3.3b Security: Nonce tracking for replay attack prevention
--
-- Creates:
-- 1. core.used_signatures - Nonce storage for replay detection
-- 2. core.security_events - Security event logging
-- ============================================================================

-- ============================================================================
-- 1. SCHEMA
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS core;

-- ============================================================================
-- 2. USED SIGNATURES TABLE (NONCE STORAGE)
-- ============================================================================

CREATE TABLE IF NOT EXISTS core.used_signatures (
    signature           VARCHAR(64) PRIMARY KEY,  -- Nonce value (unique)
    timestamp           BIGINT NOT NULL,          -- Original timestamp
    expires_at          TIMESTAMPTZ NOT NULL,     -- Auto-cleanup time
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for TTL cleanup
CREATE INDEX IF NOT EXISTS idx_used_signatures_expires
ON core.used_signatures(expires_at);

COMMENT ON TABLE core.used_signatures IS 'Tracks used nonces for replay attack prevention (V3.3b)';
COMMENT ON COLUMN core.used_signatures.signature IS 'Nonce value (32-char hex)';
COMMENT ON COLUMN core.used_signatures.expires_at IS 'Auto-cleanup after 5 minutes';

-- ============================================================================
-- 3. SECURITY EVENTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS core.security_events (
    id                  SERIAL PRIMARY KEY,
    event_type          VARCHAR(50) NOT NULL,     -- SIG_TIMESTAMP_SKEW, REPLAY_ATTACK, etc.
    severity            VARCHAR(10) NOT NULL,     -- S0, S1, S2, S3
    source_ip           VARCHAR(45),              -- Client IP (IPv4 or IPv6)
    request_path        VARCHAR(500),             -- Request path
    request_method      VARCHAR(10),              -- HTTP method
    details             JSONB,                    -- Event-specific details
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for querying by type and time
CREATE INDEX IF NOT EXISTS idx_security_events_type_time
ON core.security_events(event_type, created_at DESC);

-- Index for severity filtering
CREATE INDEX IF NOT EXISTS idx_security_events_severity
ON core.security_events(severity, created_at DESC);

COMMENT ON TABLE core.security_events IS 'Security event log for monitoring and alerting (V3.3b)';
COMMENT ON COLUMN core.security_events.event_type IS 'Event type: SIG_TIMESTAMP_SKEW, SIG_BODY_MISMATCH, REPLAY_ATTACK, SIGNATURE_INVALID';
COMMENT ON COLUMN core.security_events.severity IS 'Severity: S0 (critical), S1 (high), S2 (medium), S3 (low)';

-- ============================================================================
-- 4. TTL CLEANUP FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION core.cleanup_expired_signatures()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM core.used_signatures
    WHERE expires_at < NOW();

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION core.cleanup_expired_signatures() IS
    'Remove expired nonces (run via cron every 5 minutes)';

-- ============================================================================
-- 5. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('022', 'Replay protection tables (V3.3b)', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 6. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 022: Replay Protection COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - core.used_signatures table for nonce tracking';
    RAISE NOTICE '  - core.security_events table for security logging';
    RAISE NOTICE '  - core.cleanup_expired_signatures() function';
    RAISE NOTICE '';
    RAISE NOTICE 'Security Events Tracked:';
    RAISE NOTICE '  - SIG_TIMESTAMP_SKEW: Request timestamp outside ±120s window';
    RAISE NOTICE '  - SIG_BODY_MISMATCH: Body hash does not match signature';
    RAISE NOTICE '  - REPLAY_ATTACK: Duplicate nonce detected';
    RAISE NOTICE '  - SIGNATURE_INVALID: HMAC verification failed';
    RAISE NOTICE '==================================================================';
END $$;
