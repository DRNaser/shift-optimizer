-- ============================================================================
-- MIGRATION 007: Idempotency Keys
-- ============================================================================
-- V3.3a Product Core: Request-level idempotency for safe retries
--
-- Creates:
-- 1. idempotency_keys table for tracking request hashes
-- 2. TTL-based cleanup for old entries
-- 3. Conflict detection (409) support
-- ============================================================================

-- ============================================================================
-- 1. IDEMPOTENCY KEYS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id),
    idempotency_key     VARCHAR(64) NOT NULL,       -- X-Idempotency-Key header value
    request_hash        VARCHAR(64) NOT NULL,       -- SHA256 of request body
    endpoint            VARCHAR(255) NOT NULL,      -- e.g., '/api/v1/forecasts'
    method              VARCHAR(10) NOT NULL,       -- HTTP method (POST, PUT, etc.)
    response_status     INTEGER,                    -- HTTP status code of response
    response_body       JSONB,                      -- Cached response (for replay)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),

    CONSTRAINT idempotency_keys_unique
        UNIQUE (tenant_id, idempotency_key, endpoint)
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_lookup
ON idempotency_keys(tenant_id, idempotency_key, endpoint);

-- Index for TTL cleanup (simple B-tree, filtered at query time)
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires
ON idempotency_keys(expires_at);

COMMENT ON TABLE idempotency_keys IS 'Request idempotency tracking for safe retries (V3.3a)';
COMMENT ON COLUMN idempotency_keys.idempotency_key IS 'Client-provided key (X-Idempotency-Key header)';
COMMENT ON COLUMN idempotency_keys.request_hash IS 'SHA256 of request body for mismatch detection (409)';
COMMENT ON COLUMN idempotency_keys.response_body IS 'Cached successful response for replay';
COMMENT ON COLUMN idempotency_keys.expires_at IS 'Auto-cleanup after 24h default TTL';

-- ============================================================================
-- 2. IDEMPOTENCY CHECK FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION check_idempotency(
    p_tenant_id INTEGER,
    p_key VARCHAR(64),
    p_endpoint VARCHAR(255),
    p_request_hash VARCHAR(64)
)
RETURNS TABLE (
    status VARCHAR(20),           -- 'NEW', 'HIT', 'MISMATCH'
    cached_response JSONB,
    cached_status INTEGER
) AS $$
DECLARE
    v_existing RECORD;
BEGIN
    -- Try to find existing key
    SELECT ik.request_hash, ik.response_status, ik.response_body
    INTO v_existing
    FROM idempotency_keys ik
    WHERE ik.tenant_id = p_tenant_id
      AND ik.idempotency_key = p_key
      AND ik.endpoint = p_endpoint
      AND ik.expires_at > NOW();

    IF NOT FOUND THEN
        -- New request
        RETURN QUERY SELECT 'NEW'::VARCHAR(20), NULL::JSONB, NULL::INTEGER;
    ELSIF v_existing.request_hash != p_request_hash THEN
        -- Same key but different request body = 409 Conflict
        RETURN QUERY SELECT 'MISMATCH'::VARCHAR(20), NULL::JSONB, NULL::INTEGER;
    ELSE
        -- Cache hit - return cached response
        RETURN QUERY SELECT 'HIT'::VARCHAR(20), v_existing.response_body, v_existing.response_status;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_idempotency(INTEGER, VARCHAR, VARCHAR, VARCHAR) IS
    'Check idempotency key: NEW=proceed, HIT=return cached, MISMATCH=409 error';

-- ============================================================================
-- 3. IDEMPOTENCY RECORD FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION record_idempotency(
    p_tenant_id INTEGER,
    p_key VARCHAR(64),
    p_endpoint VARCHAR(255),
    p_method VARCHAR(10),
    p_request_hash VARCHAR(64),
    p_response_status INTEGER,
    p_response_body JSONB,
    p_ttl_hours INTEGER DEFAULT 24
)
RETURNS INTEGER AS $$
DECLARE
    v_id INTEGER;
BEGIN
    INSERT INTO idempotency_keys (
        tenant_id,
        idempotency_key,
        endpoint,
        method,
        request_hash,
        response_status,
        response_body,
        expires_at
    )
    VALUES (
        p_tenant_id,
        p_key,
        p_endpoint,
        p_method,
        p_request_hash,
        p_response_status,
        p_response_body,
        NOW() + (p_ttl_hours || ' hours')::INTERVAL
    )
    ON CONFLICT (tenant_id, idempotency_key, endpoint)
    DO UPDATE SET
        response_status = EXCLUDED.response_status,
        response_body = EXCLUDED.response_body
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_idempotency(INTEGER, VARCHAR, VARCHAR, VARCHAR, VARCHAR, INTEGER, JSONB, INTEGER) IS
    'Record successful response for idempotency replay';

-- ============================================================================
-- 4. TTL CLEANUP FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_expired_idempotency_keys()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM idempotency_keys
    WHERE expires_at < NOW();

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_expired_idempotency_keys() IS
    'Remove expired idempotency keys (run via cron or scheduled job)';

-- ============================================================================
-- 5. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('007', 'Idempotency keys for safe retries (V3.3a)', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 6. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 007: Idempotency Keys COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - idempotency_keys table with tenant isolation';
    RAISE NOTICE '  - check_idempotency() function (NEW/HIT/MISMATCH)';
    RAISE NOTICE '  - record_idempotency() function';
    RAISE NOTICE '  - cleanup_expired_idempotency_keys() function';
    RAISE NOTICE '';
    RAISE NOTICE 'Usage:';
    RAISE NOTICE '  1. On request: SELECT * FROM check_idempotency(tenant, key, endpoint, hash)';
    RAISE NOTICE '  2. If NEW: process request, then record_idempotency(...)';
    RAISE NOTICE '  3. If HIT: return cached_response';
    RAISE NOTICE '  4. If MISMATCH: return 409 Conflict';
    RAISE NOTICE '==================================================================';
END $$;
