-- =============================================================================
-- SOLVEREIGN V4.1.2 - Notification Retention and Cleanup
-- =============================================================================
-- Migration: 036_notifications_retention.sql
-- Purpose: Automated cleanup of old notification data to prevent unbounded growth
-- Author: Agent V4.1.2
-- Date: 2026-01-09
--
-- PROBLEM SOLVED:
-- - notification_outbox grows unbounded (expired messages not deleted)
-- - notification_delivery_log is append-only forever
-- - webhook_events table has no TTL
--
-- SOLUTION:
-- 1. Archive tables for audit trail (optional)
-- 2. cleanup_notifications() function with configurable retention
-- 3. Helper functions for batch deletion (to avoid lock contention)
-- 4. Enhanced verify function with retention check
--
-- SCHEDULING:
-- Run cleanup nightly via pg_cron or external scheduler:
--   SELECT cron.schedule('notify-cleanup', '0 2 * * *',
--     'SELECT notify.cleanup_notifications(30)');
--
-- OR via external scheduler calling:
--   SELECT notify.cleanup_notifications(30);
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: CREATE ARCHIVE TABLE (Optional - for audit trail)
-- =============================================================================
-- Archive stores summarized data for compliance. Can be disabled for simpler setups.

CREATE TABLE IF NOT EXISTS notify.notification_archive (
    id BIGSERIAL PRIMARY KEY,

    -- Original outbox reference
    original_outbox_id UUID NOT NULL,
    tenant_id INTEGER NOT NULL,
    site_id INTEGER,

    -- Message context (no PII)
    driver_id VARCHAR(100) NOT NULL,
    job_id UUID,
    delivery_channel VARCHAR(20) NOT NULL,
    template_id VARCHAR(100),

    -- Final status
    final_status VARCHAR(20) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,

    -- Timing
    created_at TIMESTAMPTZ NOT NULL,
    first_attempt_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Error info (if failed)
    final_error_code VARCHAR(50),
    skip_reason VARCHAR(50),

    -- Provider reference
    provider_message_id VARCHAR(255),

    -- Audit
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for compliance queries
CREATE INDEX IF NOT EXISTS idx_archive_tenant_created
    ON notify.notification_archive(tenant_id, created_at);

CREATE INDEX IF NOT EXISTS idx_archive_driver_id
    ON notify.notification_archive(tenant_id, driver_id, created_at);

-- RLS on archive (tenant isolation)
ALTER TABLE notify.notification_archive ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.notification_archive FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS notification_archive_tenant_isolation ON notify.notification_archive;
CREATE POLICY notification_archive_tenant_isolation ON notify.notification_archive
    USING (tenant_id IN (
        SELECT t.id FROM tenants t
        WHERE t.id::TEXT = current_setting('app.tenant_id', TRUE)
           OR pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    ));


-- =============================================================================
-- STEP 2: CLEANUP FUNCTION - MAIN ENTRY POINT
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.cleanup_notifications(
    p_retention_days INTEGER DEFAULT 30,
    p_archive_before_delete BOOLEAN DEFAULT TRUE,
    p_batch_size INTEGER DEFAULT 1000,
    p_max_batches INTEGER DEFAULT 100
)
RETURNS TABLE (
    archived_count INTEGER,
    deleted_outbox INTEGER,
    deleted_delivery_log INTEGER,
    deleted_webhook_events INTEGER,
    deleted_jobs INTEGER,
    execution_time_ms INTEGER
)
LANGUAGE plpgsql
SECURITY INVOKER  -- Uses caller's permissions (RLS applies)
AS $$
DECLARE
    v_start_time TIMESTAMPTZ := clock_timestamp();
    v_cutoff_date TIMESTAMPTZ := NOW() - (p_retention_days || ' days')::INTERVAL;
    v_archived INTEGER := 0;
    v_deleted_outbox INTEGER := 0;
    v_deleted_log INTEGER := 0;
    v_deleted_webhook INTEGER := 0;
    v_deleted_jobs INTEGER := 0;
    v_batch_deleted INTEGER;
    v_batch_count INTEGER := 0;
BEGIN
    -- Validate inputs
    IF p_retention_days < 1 THEN
        RAISE EXCEPTION 'retention_days must be >= 1 (got %)', p_retention_days;
    END IF;

    -- =========================================================================
    -- STEP A: Archive terminal outbox messages (if enabled)
    -- =========================================================================
    IF p_archive_before_delete THEN
        INSERT INTO notify.notification_archive (
            original_outbox_id,
            tenant_id,
            site_id,
            driver_id,
            job_id,
            delivery_channel,
            template_id,
            final_status,
            attempt_count,
            created_at,
            first_attempt_at,
            last_attempt_at,
            completed_at,
            final_error_code,
            skip_reason,
            provider_message_id
        )
        SELECT
            o.id,
            o.tenant_id,
            o.site_id,
            o.driver_id,
            o.job_id,
            o.delivery_channel,
            o.template_id,
            o.status,
            o.attempt_count,
            o.created_at,
            o.first_attempt_at,
            o.last_attempt_at,
            COALESCE(o.updated_at, NOW()),
            o.last_error_code,
            o.skip_reason,
            o.provider_message_id
        FROM notify.notification_outbox o
        WHERE o.status IN ('DELIVERED', 'SENT', 'FAILED', 'DEAD', 'SKIPPED', 'CANCELLED')
          AND o.created_at < v_cutoff_date
          AND NOT EXISTS (
              SELECT 1 FROM notify.notification_archive a
              WHERE a.original_outbox_id = o.id
          );

        GET DIAGNOSTICS v_archived = ROW_COUNT;
        RAISE NOTICE 'Archived % terminal outbox messages', v_archived;
    END IF;

    -- =========================================================================
    -- STEP B: Delete old outbox messages (batch to avoid locks)
    -- =========================================================================
    LOOP
        EXIT WHEN v_batch_count >= p_max_batches;

        WITH deletable AS (
            SELECT id
            FROM notify.notification_outbox
            WHERE status IN ('DELIVERED', 'SENT', 'FAILED', 'DEAD', 'SKIPPED', 'CANCELLED')
              AND created_at < v_cutoff_date
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM notify.notification_outbox
        WHERE id IN (SELECT id FROM deletable);

        GET DIAGNOSTICS v_batch_deleted = ROW_COUNT;
        v_deleted_outbox := v_deleted_outbox + v_batch_deleted;
        v_batch_count := v_batch_count + 1;

        EXIT WHEN v_batch_deleted < p_batch_size;

        -- Small pause to reduce lock contention
        PERFORM pg_sleep(0.01);
    END LOOP;

    RAISE NOTICE 'Deleted % outbox messages in % batches', v_deleted_outbox, v_batch_count;

    -- =========================================================================
    -- STEP C: Delete old delivery log entries (batch)
    -- =========================================================================
    v_batch_count := 0;
    LOOP
        EXIT WHEN v_batch_count >= p_max_batches;

        WITH deletable AS (
            SELECT id
            FROM notify.notification_delivery_log
            WHERE created_at < v_cutoff_date
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM notify.notification_delivery_log
        WHERE id IN (SELECT id FROM deletable);

        GET DIAGNOSTICS v_batch_deleted = ROW_COUNT;
        v_deleted_log := v_deleted_log + v_batch_deleted;
        v_batch_count := v_batch_count + 1;

        EXIT WHEN v_batch_deleted < p_batch_size;
        PERFORM pg_sleep(0.01);
    END LOOP;

    RAISE NOTICE 'Deleted % delivery log entries', v_deleted_log;

    -- =========================================================================
    -- STEP D: Delete old webhook events (batch)
    -- =========================================================================
    v_batch_count := 0;
    LOOP
        EXIT WHEN v_batch_count >= p_max_batches;

        WITH deletable AS (
            SELECT id
            FROM notify.webhook_events
            WHERE created_at < v_cutoff_date
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM notify.webhook_events
        WHERE id IN (SELECT id FROM deletable);

        GET DIAGNOSTICS v_batch_deleted = ROW_COUNT;
        v_deleted_webhook := v_deleted_webhook + v_batch_deleted;
        v_batch_count := v_batch_count + 1;

        EXIT WHEN v_batch_deleted < p_batch_size;
        PERFORM pg_sleep(0.01);
    END LOOP;

    RAISE NOTICE 'Deleted % webhook events', v_deleted_webhook;

    -- =========================================================================
    -- STEP E: Delete completed jobs with no remaining outbox (batch)
    -- =========================================================================
    v_batch_count := 0;
    LOOP
        EXIT WHEN v_batch_count >= p_max_batches;

        WITH completed_jobs AS (
            SELECT j.id
            FROM notify.notification_jobs j
            WHERE j.status IN ('COMPLETED', 'FAILED')
              AND j.created_at < v_cutoff_date
              AND NOT EXISTS (
                  SELECT 1 FROM notify.notification_outbox o
                  WHERE o.job_id = j.id
              )
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM notify.notification_jobs
        WHERE id IN (SELECT id FROM completed_jobs);

        GET DIAGNOSTICS v_batch_deleted = ROW_COUNT;
        v_deleted_jobs := v_deleted_jobs + v_batch_deleted;
        v_batch_count := v_batch_count + 1;

        EXIT WHEN v_batch_deleted < p_batch_size;
        PERFORM pg_sleep(0.01);
    END LOOP;

    RAISE NOTICE 'Deleted % completed jobs', v_deleted_jobs;

    -- =========================================================================
    -- Return summary
    -- =========================================================================
    archived_count := v_archived;
    deleted_outbox := v_deleted_outbox;
    deleted_delivery_log := v_deleted_log;
    deleted_webhook_events := v_deleted_webhook;
    deleted_jobs := v_deleted_jobs;
    execution_time_ms := EXTRACT(MILLISECONDS FROM (clock_timestamp() - v_start_time))::INTEGER;

    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION notify.cleanup_notifications IS
    'Clean up old notification data. Run via cron: SELECT notify.cleanup_notifications(30);';


-- =============================================================================
-- STEP 3: HELPER FUNCTION - COUNT OLD RECORDS (for monitoring)
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.count_old_records(
    p_retention_days INTEGER DEFAULT 30
)
RETURNS TABLE (
    table_name TEXT,
    old_records BIGINT,
    oldest_record TIMESTAMPTZ
)
LANGUAGE sql
SECURITY INVOKER
AS $$
    SELECT 'notification_outbox'::TEXT,
           COUNT(*),
           MIN(created_at)
    FROM notify.notification_outbox
    WHERE status IN ('DELIVERED', 'SENT', 'FAILED', 'DEAD', 'SKIPPED', 'CANCELLED')
      AND created_at < NOW() - (p_retention_days || ' days')::INTERVAL

    UNION ALL

    SELECT 'notification_delivery_log',
           COUNT(*),
           MIN(created_at)
    FROM notify.notification_delivery_log
    WHERE created_at < NOW() - (p_retention_days || ' days')::INTERVAL

    UNION ALL

    SELECT 'webhook_events',
           COUNT(*),
           MIN(created_at)
    FROM notify.webhook_events
    WHERE created_at < NOW() - (p_retention_days || ' days')::INTERVAL

    UNION ALL

    SELECT 'notification_jobs',
           COUNT(*),
           MIN(created_at)
    FROM notify.notification_jobs j
    WHERE j.status IN ('COMPLETED', 'FAILED')
      AND j.created_at < NOW() - (p_retention_days || ' days')::INTERVAL
      AND NOT EXISTS (
          SELECT 1 FROM notify.notification_outbox o WHERE o.job_id = j.id
      );
$$;

COMMENT ON FUNCTION notify.count_old_records IS
    'Count old records eligible for cleanup. Use for monitoring before cleanup runs.';


-- =============================================================================
-- STEP 4: PURGE ARCHIVE (for long-term retention management)
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.purge_archive(
    p_archive_retention_days INTEGER DEFAULT 365,
    p_batch_size INTEGER DEFAULT 1000
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_deleted INTEGER := 0;
    v_batch_deleted INTEGER;
BEGIN
    LOOP
        WITH deletable AS (
            SELECT id
            FROM notify.notification_archive
            WHERE archived_at < NOW() - (p_archive_retention_days || ' days')::INTERVAL
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM notify.notification_archive
        WHERE id IN (SELECT id FROM deletable);

        GET DIAGNOSTICS v_batch_deleted = ROW_COUNT;
        v_deleted := v_deleted + v_batch_deleted;

        EXIT WHEN v_batch_deleted < p_batch_size;
        PERFORM pg_sleep(0.01);
    END LOOP;

    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION notify.purge_archive IS
    'Purge old archive records. Default: 365 days retention.';


-- =============================================================================
-- STEP 5: ENHANCED VERIFY FUNCTION (adds retention check)
-- =============================================================================

-- Drop and recreate to update the function
DROP FUNCTION IF EXISTS notify.verify_notification_integrity();

CREATE OR REPLACE FUNCTION notify.verify_notification_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_count INTEGER;
    v_old_count BIGINT;
BEGIN
    -- Check 1: Status constraint exists
    check_name := 'status_constraint';
    SELECT COUNT(*) INTO v_count
    FROM information_schema.check_constraints
    WHERE constraint_name = 'notification_outbox_status_check';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'Status CHECK constraint exists';
    ELSE
        status := 'FAIL';
        details := 'Missing status CHECK constraint';
    END IF;
    RETURN NEXT;

    -- Check 2: Lock columns exist
    check_name := 'lock_columns';
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'notify'
      AND table_name = 'notification_outbox'
      AND column_name IN ('locked_at', 'locked_by', 'lock_expires_at');
    IF v_count = 3 THEN
        status := 'PASS';
        details := 'All lock columns exist';
    ELSE
        status := 'FAIL';
        details := format('Expected 3 lock columns, found %s', v_count);
    END IF;
    RETURN NEXT;

    -- Check 3: Dedup index exists
    check_name := 'dedup_index';
    SELECT COUNT(*) INTO v_count
    FROM pg_indexes
    WHERE schemaname = 'notify'
      AND indexname = 'idx_outbox_dedup_key';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'Dedup index exists';
    ELSE
        status := 'FAIL';
        details := 'Missing dedup index';
    END IF;
    RETURN NEXT;

    -- Check 4: Webhook events table exists with unique constraint
    check_name := 'webhook_events_unique';
    SELECT COUNT(*) INTO v_count
    FROM information_schema.table_constraints
    WHERE table_schema = 'notify'
      AND table_name = 'webhook_events'
      AND constraint_type = 'UNIQUE';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'Webhook events unique constraint exists';
    ELSE
        status := 'FAIL';
        details := 'Missing webhook events unique constraint';
    END IF;
    RETURN NEXT;

    -- Check 5: Rate limit buckets table exists
    check_name := 'rate_limit_table';
    SELECT COUNT(*) INTO v_count
    FROM information_schema.tables
    WHERE table_schema = 'notify'
      AND table_name = 'rate_limit_buckets';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'Rate limit buckets table exists';
    ELSE
        status := 'FAIL';
        details := 'Missing rate limit buckets table';
    END IF;
    RETURN NEXT;

    -- Check 6: Claim function exists
    check_name := 'claim_function';
    SELECT COUNT(*) INTO v_count
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'notify'
      AND p.proname = 'claim_outbox_batch';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'claim_outbox_batch function exists';
    ELSE
        status := 'FAIL';
        details := 'Missing claim_outbox_batch function';
    END IF;
    RETURN NEXT;

    -- Check 7: Reaper function exists
    check_name := 'reaper_function';
    SELECT COUNT(*) INTO v_count
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'notify'
      AND p.proname = 'release_stuck_sending';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'release_stuck_sending function exists';
    ELSE
        status := 'FAIL';
        details := 'Missing release_stuck_sending function';
    END IF;
    RETURN NEXT;

    -- Check 8: No stuck SENDING messages (lock expired)
    check_name := 'stuck_messages';
    SELECT COUNT(*) INTO v_count
    FROM notify.notification_outbox
    WHERE status = 'SENDING'
      AND lock_expires_at IS NOT NULL
      AND lock_expires_at < NOW();
    IF v_count = 0 THEN
        status := 'PASS';
        details := 'No stuck SENDING messages';
    ELSE
        status := 'WARN';
        details := format('%s stuck SENDING messages found', v_count);
    END IF;
    RETURN NEXT;

    -- Check 9: RLS enabled on outbox
    check_name := 'outbox_rls';
    SELECT COUNT(*) INTO v_count
    FROM pg_tables
    WHERE schemaname = 'notify'
      AND tablename = 'notification_outbox'
      AND rowsecurity = TRUE;
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'RLS enabled on notification_outbox';
    ELSE
        status := 'FAIL';
        details := 'RLS not enabled on notification_outbox';
    END IF;
    RETURN NEXT;

    -- Check 10: RLS enabled on webhook_events
    check_name := 'webhook_events_rls';
    SELECT COUNT(*) INTO v_count
    FROM pg_tables
    WHERE schemaname = 'notify'
      AND tablename = 'webhook_events'
      AND rowsecurity = TRUE;
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'RLS enabled on webhook_events';
    ELSE
        status := 'FAIL';
        details := 'RLS not enabled on webhook_events';
    END IF;
    RETURN NEXT;

    -- Check 11: Archive table exists
    check_name := 'archive_table';
    SELECT COUNT(*) INTO v_count
    FROM information_schema.tables
    WHERE table_schema = 'notify'
      AND table_name = 'notification_archive';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'Archive table exists';
    ELSE
        status := 'WARN';
        details := 'Archive table missing (optional)';
    END IF;
    RETURN NEXT;

    -- Check 12: Cleanup function exists
    check_name := 'cleanup_function';
    SELECT COUNT(*) INTO v_count
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'notify'
      AND p.proname = 'cleanup_notifications';
    IF v_count > 0 THEN
        status := 'PASS';
        details := 'cleanup_notifications function exists';
    ELSE
        status := 'FAIL';
        details := 'Missing cleanup_notifications function';
    END IF;
    RETURN NEXT;

    -- Check 13: OLD RECORDS THRESHOLD (> 10000 = WARN, > 50000 = FAIL)
    check_name := 'old_records_threshold';
    SELECT SUM(old_records) INTO v_old_count
    FROM notify.count_old_records(30);

    IF v_old_count IS NULL OR v_old_count = 0 THEN
        status := 'PASS';
        details := 'No old records pending cleanup';
    ELSIF v_old_count <= 10000 THEN
        status := 'PASS';
        details := format('%s old records pending cleanup (< 10k)', v_old_count);
    ELSIF v_old_count <= 50000 THEN
        status := 'WARN';
        details := format('%s old records pending cleanup (run cleanup_notifications)', v_old_count);
    ELSE
        status := 'FAIL';
        details := format('%s old records pending cleanup (URGENT: run cleanup_notifications)', v_old_count);
    END IF;
    RETURN NEXT;

END;
$$;

COMMENT ON FUNCTION notify.verify_notification_integrity IS
    'Verify notification infrastructure integrity. 13 checks including retention status.';


-- =============================================================================
-- STEP 6: CREATE INDEX FOR CLEANUP PERFORMANCE
-- =============================================================================

-- Index for efficient cleanup queries (status + created_at)
CREATE INDEX IF NOT EXISTS idx_outbox_cleanup
    ON notify.notification_outbox(status, created_at)
    WHERE status IN ('DELIVERED', 'SENT', 'FAILED', 'DEAD', 'SKIPPED', 'CANCELLED');

CREATE INDEX IF NOT EXISTS idx_delivery_log_cleanup
    ON notify.notification_delivery_log(created_at);

CREATE INDEX IF NOT EXISTS idx_webhook_events_cleanup
    ON notify.webhook_events(created_at);


-- =============================================================================
-- STEP 7: GRANT PERMISSIONS
-- =============================================================================

-- Allow platform role to run cleanup
GRANT EXECUTE ON FUNCTION notify.cleanup_notifications TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.count_old_records TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.purge_archive TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.verify_notification_integrity TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.verify_notification_integrity TO solvereign_api;

-- Allow API role to verify (read-only)
GRANT SELECT ON notify.notification_archive TO solvereign_api;


COMMIT;

-- =============================================================================
-- POST-MIGRATION: Schedule Cleanup (Run manually or via pg_cron)
-- =============================================================================
--
-- Option A: pg_cron (if available)
--   SELECT cron.schedule(
--     'notify-cleanup-daily',
--     '0 2 * * *',  -- 2 AM daily
--     'SELECT notify.cleanup_notifications(30, TRUE, 1000, 100)'
--   );
--
-- Option B: External scheduler (cron, Azure Functions, etc.)
--   psql $DATABASE_URL -c "SELECT notify.cleanup_notifications(30);"
--
-- Option C: Manual (run periodically)
--   -- Check what would be deleted:
--   SELECT * FROM notify.count_old_records(30);
--
--   -- Run cleanup:
--   SELECT * FROM notify.cleanup_notifications(30);
--
-- =============================================================================
