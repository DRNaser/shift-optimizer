-- Migration 044: Platform-wide Idempotency Keys
-- =============================================
--
-- DB-backed idempotency for critical write operations.
-- Prevents duplicate commits even across server restarts.
--
-- REQUIREMENTS:
-- - Same key + same payload = return cached response
-- - Same key + different payload = 409 CONFLICT
-- - Keys expire after 24 hours (cleanup via cron/scheduled task)
--
-- SECURITY:
-- - tenant_id required for isolation
-- - No secrets stored (only refs and hashes)

BEGIN;

-- Create core schema if not exists (platform services)
CREATE SCHEMA IF NOT EXISTS core;

-- Grant usage to API role
GRANT USAGE ON SCHEMA core TO solvereign_api;
GRANT USAGE ON SCHEMA core TO solvereign_platform;

-- =============================================================================
-- IDEMPOTENCY KEYS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS core.idempotency_keys (
    id                  SERIAL PRIMARY KEY,

    -- Scoping
    tenant_id           INTEGER NOT NULL,
    action              VARCHAR(100) NOT NULL,  -- e.g., 'roster.repair.commit'
    idempotency_key     VARCHAR(100) NOT NULL,  -- UUID from client

    -- Request tracking
    request_hash        VARCHAR(64) NOT NULL,   -- SHA-256 of normalized payload

    -- Response storage (minimal - no secrets)
    response_json       JSONB NOT NULL DEFAULT '{}',
    -- Example: {"new_plan_version_id": 123, "evidence_id": "...", "verdict": "OK"}

    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),

    -- Constraints
    CONSTRAINT idempotency_keys_tenant_action_key UNIQUE (tenant_id, action, idempotency_key)
);

-- Indexes for lookup and cleanup
CREATE INDEX idx_idempotency_keys_lookup
    ON core.idempotency_keys (tenant_id, action, idempotency_key);

CREATE INDEX idx_idempotency_keys_expires
    ON core.idempotency_keys (expires_at)
    WHERE expires_at < NOW();  -- Partial index for cleanup

-- Grant permissions
GRANT SELECT, INSERT, DELETE ON core.idempotency_keys TO solvereign_api;
GRANT SELECT, INSERT, DELETE ON core.idempotency_keys TO solvereign_platform;
GRANT USAGE, SELECT ON SEQUENCE core.idempotency_keys_id_seq TO solvereign_api;
GRANT USAGE, SELECT ON SEQUENCE core.idempotency_keys_id_seq TO solvereign_platform;

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Check idempotency key and return cached response if exists
CREATE OR REPLACE FUNCTION core.check_idempotency_key(
    p_tenant_id INTEGER,
    p_action VARCHAR,
    p_idempotency_key VARCHAR,
    p_request_hash VARCHAR
) RETURNS JSONB AS $$
DECLARE
    v_existing RECORD;
    v_result JSONB;
BEGIN
    -- Cleanup expired keys first (opportunistic)
    DELETE FROM core.idempotency_keys
    WHERE expires_at < NOW()
    LIMIT 100;  -- Don't block on large cleanup

    -- Check for existing key
    SELECT request_hash, response_json
    INTO v_existing
    FROM core.idempotency_keys
    WHERE tenant_id = p_tenant_id
      AND action = p_action
      AND idempotency_key = p_idempotency_key
      AND expires_at > NOW();

    IF NOT FOUND THEN
        -- No existing key - caller should proceed
        RETURN jsonb_build_object(
            'status', 'NOT_FOUND',
            'can_proceed', true
        );
    END IF;

    -- Key exists - check hash match
    IF v_existing.request_hash = p_request_hash THEN
        -- Same payload - return cached response
        RETURN jsonb_build_object(
            'status', 'FOUND_MATCH',
            'can_proceed', false,
            'cached_response', v_existing.response_json
        );
    ELSE
        -- Different payload - conflict!
        RETURN jsonb_build_object(
            'status', 'FOUND_CONFLICT',
            'can_proceed', false,
            'error_code', 'IDEMPOTENCY_KEY_REUSE_CONFLICT',
            'message', 'Idempotency key already used with different request payload'
        );
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Store idempotency key after successful operation
CREATE OR REPLACE FUNCTION core.store_idempotency_key(
    p_tenant_id INTEGER,
    p_action VARCHAR,
    p_idempotency_key VARCHAR,
    p_request_hash VARCHAR,
    p_response_json JSONB,
    p_ttl_hours INTEGER DEFAULT 24
) RETURNS BOOLEAN AS $$
BEGIN
    INSERT INTO core.idempotency_keys (
        tenant_id, action, idempotency_key, request_hash,
        response_json, expires_at
    ) VALUES (
        p_tenant_id, p_action, p_idempotency_key, p_request_hash,
        p_response_json, NOW() + (p_ttl_hours || ' hours')::INTERVAL
    )
    ON CONFLICT (tenant_id, action, idempotency_key) DO NOTHING;
    -- If conflict, key was already stored (race condition ok)

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Manual cleanup function (for cron job)
CREATE OR REPLACE FUNCTION core.cleanup_expired_idempotency_keys()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM core.idempotency_keys
    WHERE expires_at < NOW();

    GET DIAGNOSTICS v_deleted = ROW_COUNT;

    RAISE NOTICE 'Cleaned up % expired idempotency keys', v_deleted;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute on functions
GRANT EXECUTE ON FUNCTION core.check_idempotency_key TO solvereign_api;
GRANT EXECUTE ON FUNCTION core.check_idempotency_key TO solvereign_platform;
GRANT EXECUTE ON FUNCTION core.store_idempotency_key TO solvereign_api;
GRANT EXECUTE ON FUNCTION core.store_idempotency_key TO solvereign_platform;
GRANT EXECUTE ON FUNCTION core.cleanup_expired_idempotency_keys TO solvereign_platform;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

CREATE OR REPLACE FUNCTION core.verify_idempotency_integrity()
RETURNS TABLE (
    check_name VARCHAR,
    status VARCHAR,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Table exists
    RETURN QUERY
    SELECT
        'idempotency_table_exists'::VARCHAR,
        CASE WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'core' AND table_name = 'idempotency_keys'
        ) THEN 'PASS' ELSE 'FAIL' END::VARCHAR,
        'core.idempotency_keys table'::TEXT;

    -- Check 2: Unique constraint exists
    RETURN QUERY
    SELECT
        'unique_constraint_exists'::VARCHAR,
        CASE WHEN EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_schema = 'core'
              AND table_name = 'idempotency_keys'
              AND constraint_type = 'UNIQUE'
        ) THEN 'PASS' ELSE 'FAIL' END::VARCHAR,
        'Unique constraint on (tenant_id, action, idempotency_key)'::TEXT;

    -- Check 3: Functions exist
    RETURN QUERY
    SELECT
        'check_function_exists'::VARCHAR,
        CASE WHEN EXISTS (
            SELECT 1 FROM information_schema.routines
            WHERE routine_schema = 'core'
              AND routine_name = 'check_idempotency_key'
        ) THEN 'PASS' ELSE 'FAIL' END::VARCHAR,
        'core.check_idempotency_key function'::TEXT;

    RETURN QUERY
    SELECT
        'store_function_exists'::VARCHAR,
        CASE WHEN EXISTS (
            SELECT 1 FROM information_schema.routines
            WHERE routine_schema = 'core'
              AND routine_name = 'store_idempotency_key'
        ) THEN 'PASS' ELSE 'FAIL' END::VARCHAR,
        'core.store_idempotency_key function'::TEXT;
END;
$$ LANGUAGE plpgsql;

-- Run verification
DO $$
DECLARE
    v_check RECORD;
    v_all_pass BOOLEAN := TRUE;
BEGIN
    RAISE NOTICE '=== Idempotency Keys Migration Verification ===';

    FOR v_check IN SELECT * FROM core.verify_idempotency_integrity() LOOP
        RAISE NOTICE '% : % - %', v_check.check_name, v_check.status, v_check.details;
        IF v_check.status != 'PASS' THEN
            v_all_pass := FALSE;
        END IF;
    END LOOP;

    IF v_all_pass THEN
        RAISE NOTICE '=== ALL CHECKS PASSED ===';
    ELSE
        RAISE EXCEPTION 'Migration verification failed';
    END IF;
END $$;

COMMIT;
