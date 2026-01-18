-- =============================================================================
-- SOLVEREIGN V4.1 - Notification Hardening Patch
-- =============================================================================
-- Migration: 035_notifications_hardening.sql
-- Purpose: Production hardening for notification pipeline
-- Author: Agent V4.1
-- Date: 2026-01-09
--
-- CHANGES:
-- 1. Status state machine with CHECK constraints
-- 2. Concurrency-safe claiming with locks
-- 3. Deduplication with semantic keys
-- 4. Webhook event deduplication
-- 5. Rate limiting tables
-- 6. Enhanced verify function (12+ checks)
-- 7. Stuck message reaper function
-- 8. Atomic claim function with SKIP LOCKED
--
-- APPLIES TO: notify schema (created by 034_notifications.sql)
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: ADD STATUS STATE MACHINE WITH CHECK CONSTRAINT
-- =============================================================================

-- Drop old check if exists
ALTER TABLE notify.notification_outbox
    DROP CONSTRAINT IF EXISTS notification_outbox_status_check;

-- Valid status transitions:
-- PENDING -> SENDING (claimed by worker)
-- SENDING -> SENT (provider success)
-- SENDING -> RETRYING (transient failure, will retry)
-- SENDING -> SKIPPED (opt-out, quiet hours, etc.)
-- RETRYING -> SENDING (next attempt)
-- RETRYING -> DEAD (max attempts exceeded)
-- SENT -> DELIVERED (webhook confirmation)
-- SENT -> FAILED (webhook indicates permanent failure)

ALTER TABLE notify.notification_outbox
    ADD CONSTRAINT notification_outbox_status_check CHECK (
        status IN ('PENDING', 'SENDING', 'SENT', 'DELIVERED', 'RETRYING', 'SKIPPED', 'FAILED', 'DEAD', 'CANCELLED')
    );

-- Update existing rows to use new status values
UPDATE notify.notification_outbox
SET status = 'RETRYING'
WHERE status = 'PROCESSING';

UPDATE notify.notification_outbox
SET status = 'DEAD'
WHERE status = 'EXPIRED';


-- =============================================================================
-- STEP 2: ADD CONCURRENCY LOCK COLUMNS
-- =============================================================================

-- Add lock columns for worker claiming
ALTER TABLE notify.notification_outbox
    ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS locked_by VARCHAR(100),
    ADD COLUMN IF NOT EXISTS lock_expires_at TIMESTAMPTZ;


-- =============================================================================
-- STEP 3: ADD DEDUPLICATION KEY
-- =============================================================================

-- Semantic dedup key: prevents duplicate outbox entries for same logical message
-- Format: SHA256(tenant_id|site_id|snapshot_id|driver_id|channel|template|template_version)
ALTER TABLE notify.notification_outbox
    ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(64);

-- Create unique index for deduplication
CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_dedup_key
    ON notify.notification_outbox(tenant_id, dedup_key)
    WHERE dedup_key IS NOT NULL;


-- =============================================================================
-- STEP 4: ADD ERROR TRACKING COLUMNS
-- =============================================================================

ALTER TABLE notify.notification_outbox
    ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS skip_reason VARCHAR(50);

-- Skip reason codes: OPT_OUT, QUIET_HOURS, NO_CONTACT, CONSENT_MISSING, INVALID_CONTACT


-- =============================================================================
-- STEP 5: CREATE WEBHOOK EVENTS TABLE (Idempotent Processing)
-- =============================================================================

CREATE TABLE IF NOT EXISTS notify.webhook_events (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Provider identification
    provider VARCHAR(50) NOT NULL,  -- WHATSAPP, SENDGRID
    provider_event_id VARCHAR(255) NOT NULL,  -- Unique event ID from provider

    -- Event data
    event_type VARCHAR(50) NOT NULL,  -- SENT, DELIVERED, READ, FAILED, BOUNCED
    event_timestamp TIMESTAMPTZ NOT NULL,
    provider_message_id VARCHAR(255),

    -- Related outbox
    outbox_id UUID REFERENCES notify.notification_outbox(id),

    -- Raw payload (sanitized - no PII)
    payload_hash VARCHAR(64),  -- SHA256 of payload for debugging

    -- Processing status
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint for idempotent processing
    CONSTRAINT webhook_events_unique_event UNIQUE (provider, provider_event_id)
);

-- RLS on webhook_events
ALTER TABLE notify.webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.webhook_events FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_webhook ON notify.webhook_events
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        tenant_id
    ));


-- =============================================================================
-- STEP 6: CREATE RATE LIMITING TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS notify.rate_limit_buckets (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    bucket_key VARCHAR(100) NOT NULL,  -- e.g., 'whatsapp:tenant:1' or 'sendgrid:global'

    -- Token bucket state
    tokens_remaining INTEGER NOT NULL DEFAULT 100,
    max_tokens INTEGER NOT NULL DEFAULT 100,
    refill_rate INTEGER NOT NULL DEFAULT 10,  -- tokens per minute
    last_refill_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT rate_limit_unique_bucket UNIQUE (tenant_id, provider, bucket_key)
);

-- RLS on rate_limit_buckets
ALTER TABLE notify.rate_limit_buckets ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.rate_limit_buckets FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_rate_limit ON notify.rate_limit_buckets
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        tenant_id
    ));


-- =============================================================================
-- STEP 7: CREATE PERFORMANCE INDEXES
-- =============================================================================

-- Index for ready messages (worker polling)
DROP INDEX IF EXISTS notify.idx_outbox_ready;
CREATE INDEX idx_outbox_ready
    ON notify.notification_outbox(status, next_attempt_at)
    WHERE status IN ('PENDING', 'RETRYING');

-- Index for stuck messages (reaper)
DROP INDEX IF EXISTS notify.idx_outbox_stuck;
CREATE INDEX idx_outbox_stuck
    ON notify.notification_outbox(status, lock_expires_at)
    WHERE status = 'SENDING';

-- Index for webhook lookups
CREATE INDEX IF NOT EXISTS idx_outbox_provider_msg
    ON notify.notification_outbox(provider_message_id)
    WHERE provider_message_id IS NOT NULL;

-- Index for job status queries
CREATE INDEX IF NOT EXISTS idx_outbox_job_status
    ON notify.notification_outbox(job_id, status);


-- =============================================================================
-- STEP 8: ATOMIC CLAIM FUNCTION (Concurrency Safe)
-- =============================================================================

-- Drop old 2-parameter version from 034 to avoid function overload ambiguity
DROP FUNCTION IF EXISTS notify.claim_outbox_batch(INTEGER, VARCHAR);

CREATE OR REPLACE FUNCTION notify.claim_outbox_batch(
    p_batch_size INTEGER DEFAULT 10,
    p_worker_id VARCHAR(100) DEFAULT NULL,
    p_lock_duration_seconds INTEGER DEFAULT 300  -- 5 minutes default
)
RETURNS TABLE (
    outbox_id UUID,
    tenant_id INTEGER,
    driver_id VARCHAR(255),
    driver_name VARCHAR(255),
    delivery_channel VARCHAR(50),
    message_template VARCHAR(100),
    message_params JSONB,
    portal_url TEXT,
    attempt_count INTEGER,
    snapshot_id UUID,
    job_id UUID
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_lock_expires TIMESTAMPTZ;
BEGIN
    v_lock_expires := NOW() + (p_lock_duration_seconds * INTERVAL '1 second');

    -- Atomic: SELECT FOR UPDATE SKIP LOCKED + UPDATE in single statement
    -- This ensures no two workers can claim the same row
    RETURN QUERY
    WITH claimable AS (
        SELECT o.id
        FROM notify.notification_outbox o
        WHERE o.status IN ('PENDING', 'RETRYING')
          AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= NOW())
          AND (o.expires_at IS NULL OR o.expires_at > NOW())
        ORDER BY
            CASE WHEN o.status = 'RETRYING' THEN 0 ELSE 1 END,  -- Prioritize retries
            o.created_at
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    ),
    claimed AS (
        UPDATE notify.notification_outbox o
        SET
            status = 'SENDING',
            attempt_count = o.attempt_count + 1,
            last_attempt_at = NOW(),
            locked_at = NOW(),
            locked_by = p_worker_id,
            lock_expires_at = v_lock_expires,
            updated_at = NOW()
        FROM claimable c
        WHERE o.id = c.id
        RETURNING o.*
    )
    SELECT
        claimed.id,
        claimed.tenant_id,
        claimed.driver_id,
        claimed.driver_name,
        claimed.delivery_channel,
        claimed.message_template,
        claimed.message_params,
        claimed.portal_url,
        claimed.attempt_count,
        claimed.snapshot_id,
        claimed.job_id
    FROM claimed;
END;
$$;


-- =============================================================================
-- STEP 9: RELEASE STUCK MESSAGES FUNCTION (Reaper)
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.release_stuck_sending(
    p_max_age INTERVAL DEFAULT '10 minutes'
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_released_count INTEGER;
BEGIN
    WITH stuck AS (
        SELECT id
        FROM notify.notification_outbox
        WHERE status = 'SENDING'
          AND lock_expires_at IS NOT NULL
          AND lock_expires_at < NOW()
        FOR UPDATE SKIP LOCKED
    )
    UPDATE notify.notification_outbox o
    SET
        status = 'RETRYING',
        locked_at = NULL,
        locked_by = NULL,
        lock_expires_at = NULL,
        last_error_code = 'LOCK_EXPIRED',
        last_error_at = NOW(),
        next_attempt_at = NOW() + INTERVAL '1 minute',  -- Short retry
        updated_at = NOW()
    FROM stuck s
    WHERE o.id = s.id;

    GET DIAGNOSTICS v_released_count = ROW_COUNT;

    RETURN v_released_count;
END;
$$;


-- =============================================================================
-- STEP 10: MARK SENT FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.mark_outbox_sent(
    p_outbox_id UUID,
    p_provider_message_id VARCHAR(255),
    p_provider_status VARCHAR(50) DEFAULT 'SENT'
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    UPDATE notify.notification_outbox
    SET
        status = 'SENT',
        provider_message_id = p_provider_message_id,
        provider_status = p_provider_status,
        sent_at = NOW(),
        locked_at = NULL,
        locked_by = NULL,
        lock_expires_at = NULL,
        updated_at = NOW()
    WHERE id = p_outbox_id
      AND status = 'SENDING';  -- Only if still in SENDING state
END;
$$;


-- =============================================================================
-- STEP 11: MARK RETRY FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.mark_outbox_retry(
    p_outbox_id UUID,
    p_error_code VARCHAR(50),
    p_base_backoff_seconds INTEGER DEFAULT 60,
    p_max_attempts INTEGER DEFAULT 5
)
RETURNS BOOLEAN  -- Returns TRUE if moved to RETRYING, FALSE if moved to DEAD
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_current_attempts INTEGER;
    v_next_attempt TIMESTAMPTZ;
    v_backoff_seconds INTEGER;
    v_jitter INTEGER;
BEGIN
    -- Get current attempt count
    SELECT attempt_count INTO v_current_attempts
    FROM notify.notification_outbox
    WHERE id = p_outbox_id;

    IF v_current_attempts >= p_max_attempts THEN
        -- Move to DEAD
        UPDATE notify.notification_outbox
        SET
            status = 'DEAD',
            last_error_code = p_error_code,
            last_error_at = NOW(),
            locked_at = NULL,
            locked_by = NULL,
            lock_expires_at = NULL,
            updated_at = NOW()
        WHERE id = p_outbox_id;

        RETURN FALSE;
    END IF;

    -- Calculate exponential backoff with jitter
    -- Backoff: 60s, 300s, 900s, 2700s (clamped at ~45 min)
    v_backoff_seconds := LEAST(
        p_base_backoff_seconds * POWER(5, v_current_attempts - 1),
        2700
    );

    -- Add 0-15% jitter
    v_jitter := (v_backoff_seconds * (random() * 0.15))::INTEGER;
    v_next_attempt := NOW() + ((v_backoff_seconds + v_jitter) * INTERVAL '1 second');

    -- Move to RETRYING
    UPDATE notify.notification_outbox
    SET
        status = 'RETRYING',
        last_error_code = p_error_code,
        last_error_at = NOW(),
        next_attempt_at = v_next_attempt,
        locked_at = NULL,
        locked_by = NULL,
        lock_expires_at = NULL,
        updated_at = NOW()
    WHERE id = p_outbox_id;

    RETURN TRUE;
END;
$$;


-- =============================================================================
-- STEP 12: MARK DEAD FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.mark_outbox_dead(
    p_outbox_id UUID,
    p_error_code VARCHAR(50)
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    UPDATE notify.notification_outbox
    SET
        status = 'DEAD',
        last_error_code = p_error_code,
        last_error_at = NOW(),
        locked_at = NULL,
        locked_by = NULL,
        lock_expires_at = NULL,
        updated_at = NOW()
    WHERE id = p_outbox_id;
END;
$$;


-- =============================================================================
-- STEP 13: MARK SKIPPED FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.mark_outbox_skipped(
    p_outbox_id UUID,
    p_skip_reason VARCHAR(50)
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    UPDATE notify.notification_outbox
    SET
        status = 'SKIPPED',
        skip_reason = p_skip_reason,
        locked_at = NULL,
        locked_by = NULL,
        lock_expires_at = NULL,
        updated_at = NOW()
    WHERE id = p_outbox_id;
END;
$$;


-- =============================================================================
-- STEP 14: REQUEUE DEAD MESSAGE FUNCTION (Manual Recovery)
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.requeue_dead_message(
    p_outbox_id UUID,
    p_reset_attempts BOOLEAN DEFAULT FALSE
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_updated INTEGER;
BEGIN
    UPDATE notify.notification_outbox
    SET
        status = 'RETRYING',
        attempt_count = CASE WHEN p_reset_attempts THEN 0 ELSE attempt_count END,
        next_attempt_at = NOW(),
        last_error_code = NULL,
        last_error_at = NULL,
        updated_at = NOW()
    WHERE id = p_outbox_id
      AND status = 'DEAD';

    GET DIAGNOSTICS v_updated = ROW_COUNT;

    RETURN v_updated > 0;
END;
$$;


-- =============================================================================
-- STEP 15: PROCESS WEBHOOK EVENT FUNCTION (Idempotent)
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.process_webhook_event(
    p_tenant_id INTEGER,
    p_provider VARCHAR(50),
    p_provider_event_id VARCHAR(255),
    p_event_type VARCHAR(50),
    p_event_timestamp TIMESTAMPTZ,
    p_provider_message_id VARCHAR(255),
    p_payload_hash VARCHAR(64) DEFAULT NULL
)
RETURNS BOOLEAN  -- Returns TRUE if new event, FALSE if duplicate
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_outbox_id UUID;
    v_inserted BOOLEAN := FALSE;
BEGIN
    -- Try to insert webhook event (unique constraint prevents duplicates)
    BEGIN
        INSERT INTO notify.webhook_events (
            tenant_id, provider, provider_event_id, event_type,
            event_timestamp, provider_message_id, payload_hash
        ) VALUES (
            p_tenant_id, p_provider, p_provider_event_id, p_event_type,
            p_event_timestamp, p_provider_message_id, p_payload_hash
        );
        v_inserted := TRUE;
    EXCEPTION WHEN unique_violation THEN
        -- Duplicate event, ignore
        RETURN FALSE;
    END;

    -- Find related outbox entry
    SELECT id INTO v_outbox_id
    FROM notify.notification_outbox
    WHERE provider_message_id = p_provider_message_id
      AND tenant_id = p_tenant_id
    LIMIT 1;

    IF v_outbox_id IS NOT NULL THEN
        -- Update outbox entry with webhook event reference
        UPDATE notify.webhook_events
        SET outbox_id = v_outbox_id
        WHERE provider = p_provider AND provider_event_id = p_provider_event_id;

        -- Update outbox status based on event type
        IF p_event_type = 'DELIVERED' THEN
            UPDATE notify.notification_outbox
            SET status = 'DELIVERED',
                provider_status = 'DELIVERED',
                delivered_at = p_event_timestamp,
                updated_at = NOW()
            WHERE id = v_outbox_id
              AND status IN ('SENT', 'DELIVERED');  -- Only if in valid state

        ELSIF p_event_type IN ('FAILED', 'BOUNCED', 'UNDELIVERABLE') THEN
            UPDATE notify.notification_outbox
            SET status = 'FAILED',
                provider_status = p_event_type,
                last_error_code = 'PROVIDER_' || p_event_type,
                last_error_at = p_event_timestamp,
                updated_at = NOW()
            WHERE id = v_outbox_id
              AND status IN ('SENT', 'SENDING');
        END IF;
    END IF;

    RETURN v_inserted;
END;
$$;


-- =============================================================================
-- STEP 16: RATE LIMIT CHECK FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.check_rate_limit(
    p_tenant_id INTEGER,
    p_provider VARCHAR(50),
    p_tokens_needed INTEGER DEFAULT 1
)
RETURNS TABLE (
    allowed BOOLEAN,
    tokens_remaining INTEGER,
    retry_after_seconds INTEGER
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_bucket RECORD;
    v_now TIMESTAMPTZ := NOW();
    v_elapsed_minutes NUMERIC;
    v_new_tokens INTEGER;
BEGIN
    -- Get or create bucket
    INSERT INTO notify.rate_limit_buckets (tenant_id, provider, bucket_key, tokens_remaining, max_tokens, refill_rate)
    VALUES (p_tenant_id, p_provider, p_provider || ':tenant:' || p_tenant_id, 100, 100, 10)
    ON CONFLICT (tenant_id, provider, bucket_key) DO NOTHING;

    -- Lock and update bucket
    SELECT * INTO v_bucket
    FROM notify.rate_limit_buckets
    WHERE tenant_id = p_tenant_id
      AND provider = p_provider
      AND bucket_key = p_provider || ':tenant:' || p_tenant_id
    FOR UPDATE;

    -- Calculate token refill
    v_elapsed_minutes := EXTRACT(EPOCH FROM (v_now - v_bucket.last_refill_at)) / 60.0;
    v_new_tokens := LEAST(
        v_bucket.max_tokens,
        v_bucket.tokens_remaining + (v_elapsed_minutes * v_bucket.refill_rate)::INTEGER
    );

    IF v_new_tokens >= p_tokens_needed THEN
        -- Consume tokens
        UPDATE notify.rate_limit_buckets
        SET tokens_remaining = v_new_tokens - p_tokens_needed,
            last_refill_at = v_now,
            updated_at = v_now
        WHERE tenant_id = p_tenant_id
          AND provider = p_provider
          AND bucket_key = p_provider || ':tenant:' || p_tenant_id;

        RETURN QUERY SELECT TRUE, v_new_tokens - p_tokens_needed, 0;
    ELSE
        -- Update refill time only
        UPDATE notify.rate_limit_buckets
        SET tokens_remaining = v_new_tokens,
            last_refill_at = v_now,
            updated_at = v_now
        WHERE tenant_id = p_tenant_id
          AND provider = p_provider
          AND bucket_key = p_provider || ':tenant:' || p_tenant_id;

        -- Calculate retry time
        RETURN QUERY SELECT
            FALSE,
            v_new_tokens,
            CEIL((p_tokens_needed - v_new_tokens)::NUMERIC / v_bucket.refill_rate * 60)::INTEGER;
    END IF;
END;
$$;


-- =============================================================================
-- STEP 17: COMPUTE DEDUP KEY FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.compute_dedup_key(
    p_tenant_id INTEGER,
    p_site_id UUID,
    p_snapshot_id UUID,
    p_driver_id VARCHAR(255),
    p_channel VARCHAR(50),
    p_template VARCHAR(100),
    p_template_version VARCHAR(20) DEFAULT 'v1'
)
RETURNS VARCHAR(64)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN encode(
        sha256(
            (COALESCE(p_tenant_id::TEXT, '') || '|' ||
             COALESCE(p_site_id::TEXT, '') || '|' ||
             COALESCE(p_snapshot_id::TEXT, '') || '|' ||
             COALESCE(p_driver_id, '') || '|' ||
             COALESCE(p_channel, '') || '|' ||
             COALESCE(p_template, '') || '|' ||
             COALESCE(p_template_version, ''))::bytea
        ),
        'hex'
    );
END;
$$;


-- =============================================================================
-- STEP 18: ENHANCED VERIFY FUNCTION (12 CHECKS)
-- =============================================================================

DROP FUNCTION IF EXISTS notify.verify_notification_integrity();

CREATE OR REPLACE FUNCTION notify.verify_notification_integrity()
RETURNS TABLE (
    check_name VARCHAR(100),
    status VARCHAR(10),
    details TEXT
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    -- Check 1: RLS enabled on notification_jobs
    RETURN QUERY
    SELECT
        'rls_enabled_jobs'::VARCHAR(100),
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'notification_jobs has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'notify.notification_jobs'::regclass;

    -- Check 2: RLS enabled on notification_outbox
    RETURN QUERY
    SELECT
        'rls_enabled_outbox'::VARCHAR(100),
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'notification_outbox has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'notify.notification_outbox'::regclass;

    -- Check 3: RLS enabled on webhook_events
    RETURN QUERY
    SELECT
        'rls_enabled_webhook'::VARCHAR(100),
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'webhook_events has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'notify.webhook_events'::regclass;

    -- Check 4: Valid outbox statuses
    RETURN QUERY
    SELECT
        'valid_outbox_statuses'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        COALESCE('Invalid statuses: ' || COUNT(*)::TEXT, 'All statuses valid')::TEXT
    FROM notify.notification_outbox
    WHERE status NOT IN ('PENDING', 'SENDING', 'SENT', 'DELIVERED', 'RETRYING', 'SKIPPED', 'FAILED', 'DEAD', 'CANCELLED');

    -- Check 5: No stuck SENDING without lock_expires_at
    RETURN QUERY
    SELECT
        'sending_has_lock_expires'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'SENDING rows without lock_expires_at: ' || COUNT(*)::TEXT
    FROM notify.notification_outbox
    WHERE status = 'SENDING' AND lock_expires_at IS NULL;

    -- Check 6: No expired locks in SENDING state
    RETURN QUERY
    SELECT
        'no_expired_locks'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END::VARCHAR(10),
        'Expired locks needing reaper: ' || COUNT(*)::TEXT
    FROM notify.notification_outbox
    WHERE status = 'SENDING'
      AND lock_expires_at IS NOT NULL
      AND lock_expires_at < NOW();

    -- Check 7: Dedup index exists
    RETURN QUERY
    SELECT
        'dedup_index_exists'::VARCHAR(100),
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'Dedup unique index on outbox'::TEXT
    FROM pg_indexes
    WHERE schemaname = 'notify'
      AND tablename = 'notification_outbox'
      AND indexname = 'idx_outbox_dedup_key';

    -- Check 8: Ready index exists
    RETURN QUERY
    SELECT
        'ready_index_exists'::VARCHAR(100),
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'Ready index for worker polling'::TEXT
    FROM pg_indexes
    WHERE schemaname = 'notify'
      AND tablename = 'notification_outbox'
      AND indexname = 'idx_outbox_ready';

    -- Check 9: No orphaned outbox (job_id references valid job)
    RETURN QUERY
    SELECT
        'no_orphaned_outbox'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'Orphaned outbox entries: ' || COUNT(*)::TEXT
    FROM notify.notification_outbox o
    LEFT JOIN notify.notification_jobs j ON j.id = o.job_id
    WHERE o.job_id IS NOT NULL AND j.id IS NULL;

    -- Check 10: Tenant ID not null on critical tables
    RETURN QUERY
    SELECT
        'tenant_id_not_null'::VARCHAR(100),
        CASE WHEN (
            SELECT COUNT(*) FROM notify.notification_jobs WHERE tenant_id IS NULL
        ) + (
            SELECT COUNT(*) FROM notify.notification_outbox WHERE tenant_id IS NULL
        ) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'All records have tenant_id'::TEXT;

    -- Check 11: DEAD messages have error codes
    RETURN QUERY
    SELECT
        'dead_has_error_code'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END::VARCHAR(10),
        'DEAD without error_code: ' || COUNT(*)::TEXT
    FROM notify.notification_outbox
    WHERE status = 'DEAD' AND last_error_code IS NULL;

    -- Check 12: Claim function exists
    RETURN QUERY
    SELECT
        'claim_function_exists'::VARCHAR(100),
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'notify.claim_outbox_batch function exists'::TEXT
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'notify' AND p.proname = 'claim_outbox_batch';

    RETURN;
END;
$$;


-- =============================================================================
-- STEP 19: UPDATE JOB STATUS TRIGGER (Enhanced)
-- =============================================================================

DROP TRIGGER IF EXISTS tr_update_job_status ON notify.notification_outbox;

CREATE OR REPLACE FUNCTION notify.update_job_status_on_outbox_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_job RECORD;
    v_new_status VARCHAR(50);
BEGIN
    -- Only run when status changes to terminal state
    IF NEW.status NOT IN ('SENT', 'DELIVERED', 'FAILED', 'DEAD', 'SKIPPED', 'CANCELLED') THEN
        RETURN NEW;
    END IF;

    IF NEW.job_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Check job completion (use aggregate to avoid locking)
    SELECT
        j.id,
        j.status,
        j.total_count,
        COUNT(*) FILTER (WHERE o.status IN ('PENDING', 'SENDING', 'RETRYING')) as pending_count,
        COUNT(*) FILTER (WHERE o.status IN ('SENT', 'DELIVERED')) as success_count,
        COUNT(*) FILTER (WHERE o.status IN ('FAILED', 'DEAD', 'SKIPPED', 'CANCELLED')) as terminal_count
    INTO v_job
    FROM notify.notification_jobs j
    LEFT JOIN notify.notification_outbox o ON o.job_id = j.id
    WHERE j.id = NEW.job_id
    GROUP BY j.id, j.status, j.total_count;

    -- Determine new job status
    IF v_job.pending_count = 0 THEN
        IF v_job.terminal_count = 0 OR v_job.success_count = v_job.total_count THEN
            v_new_status := 'COMPLETED';
        ELSIF v_job.success_count = 0 THEN
            v_new_status := 'FAILED';
        ELSE
            v_new_status := 'PARTIALLY_FAILED';
        END IF;

        UPDATE notify.notification_jobs
        SET
            status = v_new_status,
            sent_count = v_job.success_count,
            failed_count = v_job.terminal_count,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE id = NEW.job_id
          AND status NOT IN ('COMPLETED', 'FAILED', 'PARTIALLY_FAILED');  -- Don't overwrite terminal
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_update_job_status
    AFTER UPDATE OF status ON notify.notification_outbox
    FOR EACH ROW
    EXECUTE FUNCTION notify.update_job_status_on_outbox_change();


-- =============================================================================
-- STEP 20: GRANTS
-- =============================================================================

-- Grant to API role
GRANT SELECT, INSERT, UPDATE ON notify.webhook_events TO solvereign_api;
GRANT SELECT, INSERT, UPDATE ON notify.rate_limit_buckets TO solvereign_api;
GRANT USAGE ON SEQUENCE notify.webhook_events_id_seq TO solvereign_api;
GRANT USAGE ON SEQUENCE notify.rate_limit_buckets_id_seq TO solvereign_api;

-- Grant function execution
GRANT EXECUTE ON FUNCTION notify.claim_outbox_batch(INTEGER, VARCHAR, INTEGER) TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.release_stuck_sending TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_sent TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_retry TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_dead TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_skipped TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.requeue_dead_message TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.process_webhook_event TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.check_rate_limit TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.compute_dedup_key TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.verify_notification_integrity TO solvereign_api;

-- Platform role gets same grants
GRANT SELECT, INSERT, UPDATE ON notify.webhook_events TO solvereign_platform;
GRANT SELECT, INSERT, UPDATE ON notify.rate_limit_buckets TO solvereign_platform;
GRANT USAGE ON SEQUENCE notify.webhook_events_id_seq TO solvereign_platform;
GRANT USAGE ON SEQUENCE notify.rate_limit_buckets_id_seq TO solvereign_platform;

GRANT EXECUTE ON FUNCTION notify.claim_outbox_batch(INTEGER, VARCHAR, INTEGER) TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.release_stuck_sending TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_sent TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_retry TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_dead TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.mark_outbox_skipped TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.requeue_dead_message TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.process_webhook_event TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.check_rate_limit TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.compute_dedup_key TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.verify_notification_integrity TO solvereign_platform;

COMMIT;

-- =============================================================================
-- VERIFICATION (Run after migration)
-- =============================================================================
-- SELECT * FROM notify.verify_notification_integrity();
-- Expected: 12 checks, all PASS (or WARN for operational items)
