-- =============================================================================
-- MIGRATION 037a: Portal-Notify Hardening (Production Gates)
-- =============================================================================
-- SOLVEREIGN V4.2.1 - Production Hardening Patch
--
-- Fixes:
--   1. ATOMICITY: issue_tokens_atomic() - single transaction for tokens + outbox
--   2. DEDUP: dedup_key column on portal_tokens
--   3. PII: Remove error_message from views (could contain PII)
--   4. RETENTION: Cleanup functions for portal tables
--   5. ORPHAN: Auto-revoke tokens on job failure
-- =============================================================================

BEGIN;

-- =============================================================================
-- FIX 1: Add dedup_key to portal_tokens
-- =============================================================================
-- Prevents duplicate tokens for same snapshot+driver+channel combination
-- Formula: sha256(tenant|site|snapshot|driver|channel|scope)

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'portal'
        AND table_name = 'portal_tokens'
        AND column_name = 'dedup_key'
    ) THEN
        ALTER TABLE portal.portal_tokens
        ADD COLUMN dedup_key CHAR(64);
    END IF;
END $$;

-- Unique constraint on dedup_key (allows resend with different scope/template)
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_tokens_dedup_key
    ON portal.portal_tokens(tenant_id, dedup_key)
    WHERE dedup_key IS NOT NULL AND revoked_at IS NULL;

-- =============================================================================
-- FIX 2: Compute dedup key function
-- =============================================================================

CREATE OR REPLACE FUNCTION portal.compute_token_dedup_key(
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_snapshot_id UUID,
    p_driver_id VARCHAR(255),
    p_delivery_channel TEXT,
    p_scope TEXT
)
RETURNS CHAR(64)
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT encode(
        sha256(
            (p_tenant_id::TEXT || '|' ||
             p_site_id::TEXT || '|' ||
             p_snapshot_id::TEXT || '|' ||
             p_driver_id || '|' ||
             p_delivery_channel || '|' ||
             p_scope)::BYTEA
        ),
        'hex'
    )::CHAR(64);
$$;

GRANT EXECUTE ON FUNCTION portal.compute_token_dedup_key(INTEGER, INTEGER, UUID, VARCHAR, TEXT, TEXT) TO solvereign_api;

-- =============================================================================
-- FIX 3: Atomic token + outbox creation
-- =============================================================================
-- Creates token and outbox entry in single transaction
-- Returns NULL on dedup collision (already exists)

CREATE OR REPLACE FUNCTION portal.issue_token_atomic(
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_snapshot_id UUID,
    p_driver_id VARCHAR(255),
    p_driver_name VARCHAR(255),
    p_jti_hash CHAR(64),
    p_scope TEXT,
    p_delivery_channel TEXT,
    p_expires_at TIMESTAMPTZ,
    p_job_id UUID,
    p_template_key VARCHAR(100),
    p_portal_url TEXT
)
RETURNS TABLE (
    token_id BIGINT,
    outbox_id UUID,
    is_duplicate BOOLEAN
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_dedup_key CHAR(64);
    v_token_id BIGINT;
    v_outbox_id UUID;
    v_existing_token_id BIGINT;
BEGIN
    -- Compute dedup key
    v_dedup_key := portal.compute_token_dedup_key(
        p_tenant_id, p_site_id, p_snapshot_id, p_driver_id, p_delivery_channel, p_scope
    );

    -- Check for existing non-revoked token with same dedup key
    SELECT id INTO v_existing_token_id
    FROM portal.portal_tokens
    WHERE tenant_id = p_tenant_id
      AND dedup_key = v_dedup_key
      AND revoked_at IS NULL
    FOR UPDATE SKIP LOCKED;

    IF v_existing_token_id IS NOT NULL THEN
        -- Return existing as duplicate
        RETURN QUERY SELECT v_existing_token_id, NULL::UUID, TRUE;
        RETURN;
    END IF;

    -- Insert token
    INSERT INTO portal.portal_tokens (
        tenant_id, site_id, snapshot_id, driver_id,
        scope, jti_hash, delivery_channel,
        expires_at, dedup_key
    ) VALUES (
        p_tenant_id, p_site_id, p_snapshot_id, p_driver_id,
        p_scope, p_jti_hash, p_delivery_channel,
        p_expires_at, v_dedup_key
    )
    RETURNING id INTO v_token_id;

    -- Insert outbox entry
    v_outbox_id := gen_random_uuid();
    INSERT INTO notify.notification_outbox (
        id, tenant_id, job_id, driver_id, driver_name,
        delivery_channel, message_template, portal_url,
        snapshot_id, status, next_attempt_at, expires_at
    ) VALUES (
        v_outbox_id, p_tenant_id, p_job_id, p_driver_id, p_driver_name,
        p_delivery_channel, p_template_key, p_portal_url,
        p_snapshot_id, 'PENDING', NOW(), p_expires_at
    );

    -- Link token to outbox
    UPDATE portal.portal_tokens
    SET outbox_id = v_outbox_id
    WHERE id = v_token_id;

    RETURN QUERY SELECT v_token_id, v_outbox_id, FALSE;
END;
$$;

GRANT EXECUTE ON FUNCTION portal.issue_token_atomic(INTEGER, INTEGER, UUID, VARCHAR, VARCHAR, CHAR, TEXT, TEXT, TIMESTAMPTZ, UUID, VARCHAR, TEXT) TO solvereign_api;

-- =============================================================================
-- FIX 4: Rollback tokens on job failure
-- =============================================================================
-- Revokes all tokens for a job if job fails

CREATE OR REPLACE FUNCTION portal.revoke_tokens_for_job(
    p_job_id UUID,
    p_reason TEXT DEFAULT 'JOB_FAILED'
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH updated AS (
        UPDATE portal.portal_tokens t
        SET revoked_at = NOW()
        FROM notify.notification_outbox o
        WHERE o.job_id = p_job_id
          AND t.outbox_id = o.id
          AND t.revoked_at IS NULL
        RETURNING t.id
    )
    SELECT COUNT(*) INTO v_count FROM updated;

    -- Audit
    INSERT INTO portal.portal_audit (
        tenant_id, site_id, action, details
    )
    SELECT DISTINCT
        t.tenant_id, t.site_id, 'TOKENS_REVOKED_JOB_FAIL',
        jsonb_build_object('job_id', p_job_id, 'reason', p_reason, 'count', v_count)
    FROM notify.notification_outbox o
    JOIN portal.portal_tokens t ON t.outbox_id = o.id
    WHERE o.job_id = p_job_id
    LIMIT 1;

    RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION portal.revoke_tokens_for_job(UUID, TEXT) TO solvereign_api;

-- =============================================================================
-- FIX 5: Updated views WITHOUT PII-leaking fields
-- =============================================================================

DROP VIEW IF EXISTS portal.snapshot_notify_summary CASCADE;
DROP VIEW IF EXISTS portal.notify_integration_status CASCADE;

-- Recreate without error_message (could contain PII)
CREATE OR REPLACE VIEW portal.notify_integration_status AS
SELECT
    t.tenant_id,
    t.snapshot_id,
    t.driver_id,
    -- NO jti_hash in view (security)
    t.scope,
    t.delivery_channel,
    t.issued_at,
    t.expires_at,
    t.revoked_at,
    t.last_seen_at,
    -- Notification status (NO error_message - could contain PII)
    o.status AS notify_status,
    o.sent_at AS notify_sent_at,
    o.delivered_at AS notify_delivered_at,
    o.error_code AS notify_error_code,  -- Only code, not message
    -- Read/Ack status
    r.first_read_at,
    r.last_read_at,
    r.read_count,
    a.status AS ack_status,
    a.ack_at,
    -- Derived status
    CASE
        WHEN t.revoked_at IS NOT NULL THEN 'REVOKED'
        WHEN t.expires_at < NOW() THEN 'EXPIRED'
        WHEN o.status = 'FAILED' THEN 'NOTIFY_FAILED'
        WHEN o.status = 'DEAD' THEN 'NOTIFY_DEAD'
        WHEN o.status IS NULL AND t.outbox_id IS NOT NULL THEN 'NOTIFY_PENDING'
        WHEN a.status = 'ACCEPTED' THEN 'ACCEPTED'
        WHEN a.status = 'DECLINED' THEN 'DECLINED'
        WHEN r.first_read_at IS NOT NULL THEN 'READ'
        WHEN o.delivered_at IS NOT NULL THEN 'DELIVERED'
        WHEN o.sent_at IS NOT NULL THEN 'SENT'
        ELSE 'PENDING'
    END AS overall_status
FROM portal.portal_tokens t
LEFT JOIN notify.notification_outbox o ON o.id = t.outbox_id
LEFT JOIN portal.read_receipts r ON r.snapshot_id = t.snapshot_id AND r.driver_id = t.driver_id
LEFT JOIN portal.driver_ack a ON a.snapshot_id = t.snapshot_id AND a.driver_id = t.driver_id;

GRANT SELECT ON portal.notify_integration_status TO solvereign_api;

-- Summary view (aggregates only, no PII possible)
CREATE OR REPLACE VIEW portal.snapshot_notify_summary AS
SELECT
    tenant_id,
    snapshot_id,
    COUNT(*) AS total_tokens,
    COUNT(*) FILTER (WHERE overall_status = 'PENDING') AS pending_count,
    COUNT(*) FILTER (WHERE overall_status = 'SENT') AS sent_count,
    COUNT(*) FILTER (WHERE overall_status = 'DELIVERED') AS delivered_count,
    COUNT(*) FILTER (WHERE overall_status = 'READ') AS read_count,
    COUNT(*) FILTER (WHERE overall_status = 'ACCEPTED') AS accepted_count,
    COUNT(*) FILTER (WHERE overall_status = 'DECLINED') AS declined_count,
    COUNT(*) FILTER (WHERE overall_status IN ('REVOKED', 'EXPIRED', 'NOTIFY_FAILED', 'NOTIFY_DEAD')) AS failed_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE overall_status IN ('ACCEPTED', 'DECLINED'))
        / NULLIF(COUNT(*), 0),
        1
    ) AS completion_rate,
    MIN(issued_at) AS first_issued_at,
    MAX(ack_at) AS last_ack_at
FROM portal.notify_integration_status
GROUP BY tenant_id, snapshot_id;

GRANT SELECT ON portal.snapshot_notify_summary TO solvereign_api;

-- =============================================================================
-- FIX 6: Portal retention (aligned with notify 036)
-- =============================================================================

-- Archive table for portal tokens
CREATE TABLE IF NOT EXISTS portal.portal_tokens_archive (
    LIKE portal.portal_tokens INCLUDING ALL
);

-- No RLS on archive (platform role only)
REVOKE ALL ON portal.portal_tokens_archive FROM solvereign_api;
GRANT SELECT, INSERT ON portal.portal_tokens_archive TO solvereign_platform;

-- Cleanup function
CREATE OR REPLACE FUNCTION portal.cleanup_portal_data(
    p_retention_days INTEGER DEFAULT 90,
    p_archive_before_delete BOOLEAN DEFAULT TRUE,
    p_batch_size INTEGER DEFAULT 1000,
    p_max_batches INTEGER DEFAULT 100
)
RETURNS TABLE (
    tokens_archived INTEGER,
    tokens_deleted INTEGER,
    read_receipts_deleted INTEGER,
    rate_limits_deleted INTEGER
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_cutoff TIMESTAMPTZ;
    v_tokens_archived INTEGER := 0;
    v_tokens_deleted INTEGER := 0;
    v_receipts_deleted INTEGER := 0;
    v_rate_deleted INTEGER := 0;
    v_batch INTEGER := 0;
    v_deleted INTEGER;
BEGIN
    v_cutoff := NOW() - (p_retention_days || ' days')::INTERVAL;

    -- Archive and delete old tokens
    WHILE v_batch < p_max_batches LOOP
        -- Archive if requested
        IF p_archive_before_delete THEN
            INSERT INTO portal.portal_tokens_archive
            SELECT * FROM portal.portal_tokens
            WHERE expires_at < v_cutoff
              AND id NOT IN (SELECT id FROM portal.portal_tokens_archive)
            LIMIT p_batch_size;

            GET DIAGNOSTICS v_deleted = ROW_COUNT;
            v_tokens_archived := v_tokens_archived + v_deleted;
        END IF;

        -- Delete old tokens (only expired + past retention)
        DELETE FROM portal.portal_tokens
        WHERE id IN (
            SELECT id FROM portal.portal_tokens
            WHERE expires_at < v_cutoff
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
        );

        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        v_tokens_deleted := v_tokens_deleted + v_deleted;

        EXIT WHEN v_deleted < p_batch_size;
        v_batch := v_batch + 1;
    END LOOP;

    -- Delete old read receipts (where snapshot is old)
    -- Note: Keep receipts if ack exists (arbeitsrechtlich)
    DELETE FROM portal.read_receipts
    WHERE id IN (
        SELECT r.id FROM portal.read_receipts r
        LEFT JOIN portal.driver_ack a ON a.snapshot_id = r.snapshot_id AND a.driver_id = r.driver_id
        WHERE r.created_at < v_cutoff
          AND a.id IS NULL  -- No ack record
        LIMIT p_batch_size * p_max_batches
        FOR UPDATE OF r SKIP LOCKED
    );
    GET DIAGNOSTICS v_receipts_deleted = ROW_COUNT;

    -- Delete old rate limits (always safe)
    DELETE FROM portal.rate_limits
    WHERE window_end < v_cutoff;
    GET DIAGNOSTICS v_rate_deleted = ROW_COUNT;

    -- Note: driver_ack is NEVER deleted (arbeitsrechtlich)

    RETURN QUERY SELECT v_tokens_archived, v_tokens_deleted, v_receipts_deleted, v_rate_deleted;
END;
$$;

GRANT EXECUTE ON FUNCTION portal.cleanup_portal_data(INTEGER, BOOLEAN, INTEGER, INTEGER) TO solvereign_platform;

-- Count old records for monitoring
CREATE OR REPLACE FUNCTION portal.count_old_portal_records(
    p_retention_days INTEGER DEFAULT 90
)
RETURNS TABLE (
    table_name TEXT,
    old_count BIGINT,
    total_count BIGINT,
    percentage NUMERIC(5,2)
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_cutoff TIMESTAMPTZ;
BEGIN
    v_cutoff := NOW() - (p_retention_days || ' days')::INTERVAL;

    RETURN QUERY
    SELECT 'portal_tokens'::TEXT,
           COUNT(*) FILTER (WHERE expires_at < v_cutoff),
           COUNT(*),
           ROUND(100.0 * COUNT(*) FILTER (WHERE expires_at < v_cutoff) / NULLIF(COUNT(*), 0), 2)
    FROM portal.portal_tokens;

    RETURN QUERY
    SELECT 'read_receipts'::TEXT,
           COUNT(*) FILTER (WHERE created_at < v_cutoff),
           COUNT(*),
           ROUND(100.0 * COUNT(*) FILTER (WHERE created_at < v_cutoff) / NULLIF(COUNT(*), 0), 2)
    FROM portal.read_receipts;

    RETURN QUERY
    SELECT 'rate_limits'::TEXT,
           COUNT(*) FILTER (WHERE window_end < v_cutoff),
           COUNT(*),
           ROUND(100.0 * COUNT(*) FILTER (WHERE window_end < v_cutoff) / NULLIF(COUNT(*), 0), 2)
    FROM portal.rate_limits;
END;
$$;

GRANT EXECUTE ON FUNCTION portal.count_old_portal_records(INTEGER) TO solvereign_platform;

-- =============================================================================
-- FIX 7: Enhanced verification
-- =============================================================================

DROP FUNCTION IF EXISTS portal.verify_notify_integration();

CREATE OR REPLACE FUNCTION portal.verify_notify_integration()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Templates use plan_link
    RETURN QUERY
    SELECT
        'templates_use_plan_link'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        CASE WHEN COUNT(*) = 0
            THEN 'All templates use {{plan_link}}'
            ELSE 'Found ' || COUNT(*)::TEXT || ' templates still using {{portal_url}}'
        END::TEXT
    FROM notify.notification_templates
    WHERE body_template LIKE '%{{portal_url}}%';

    -- Check 2: dedup_key column exists
    RETURN QUERY
    SELECT
        'dedup_key_column_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Column portal.portal_tokens.dedup_key'::TEXT
    FROM information_schema.columns
    WHERE table_schema = 'portal'
      AND table_name = 'portal_tokens'
      AND column_name = 'dedup_key';

    -- Check 3: dedup_key index exists
    RETURN QUERY
    SELECT
        'dedup_key_index_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Index idx_portal_tokens_dedup_key'::TEXT
    FROM pg_indexes
    WHERE indexname = 'idx_portal_tokens_dedup_key';

    -- Check 4: Integration view exists and has no jti_hash column
    RETURN QUERY
    SELECT
        'integration_view_no_jti_hash'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'View portal.notify_integration_status should not expose jti_hash'::TEXT
    FROM information_schema.columns
    WHERE table_schema = 'portal'
      AND table_name = 'notify_integration_status'
      AND column_name = 'jti_hash';

    -- Check 5: View has no error_message column (PII risk)
    RETURN QUERY
    SELECT
        'integration_view_no_error_message'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'View should not expose error_message (PII risk)'::TEXT
    FROM information_schema.columns
    WHERE table_schema = 'portal'
      AND table_name = 'notify_integration_status'
      AND column_name IN ('error_message', 'notify_error');

    -- Check 6: issue_token_atomic function exists
    RETURN QUERY
    SELECT
        'atomic_function_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Function portal.issue_token_atomic'::TEXT
    FROM pg_proc
    WHERE proname = 'issue_token_atomic';

    -- Check 7: Archive table exists
    RETURN QUERY
    SELECT
        'archive_table_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Table portal.portal_tokens_archive'::TEXT
    FROM pg_tables
    WHERE schemaname = 'portal'
      AND tablename = 'portal_tokens_archive';

    -- Check 8: No orphaned tokens (tokens without outbox where job exists)
    RETURN QUERY
    SELECT
        'no_orphaned_tokens'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END::TEXT,
        CASE WHEN COUNT(*) = 0
            THEN 'No orphaned tokens found'
            ELSE 'Found ' || COUNT(*)::TEXT || ' tokens without outbox link'
        END::TEXT
    FROM portal.portal_tokens t
    WHERE t.outbox_id IS NULL
      AND t.revoked_at IS NULL
      AND t.created_at < NOW() - INTERVAL '1 hour';  -- Grace period

END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION portal.verify_notify_integration() TO solvereign_platform;

COMMIT;

-- =============================================================================
-- VERIFICATION (Run after migration)
-- =============================================================================
-- SELECT * FROM portal.verify_notify_integration();
-- Expected: 8 PASS
