-- =============================================================================
-- SOLVEREIGN V4.3 - Bounce/Complaint Do-Not-Contact Handling
-- =============================================================================
--
-- This PATCH migration adds:
--   1. do_not_contact_* columns to driver_preferences
--   2. soft_bounce_count tracking
--   3. handle_bounce_complaint() function
--   4. Extended process_webhook_event() for new event types
--
-- Run: psql $DATABASE_URL < backend_py/db/migrations/038_bounce_dnc.sql
--
-- Prerequisites:
--   - 034_notifications.sql (driver_preferences table)
--   - 035_notifications_hardening.sql (webhook_events table)
--
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: ADD DO_NOT_CONTACT COLUMNS TO DRIVER_PREFERENCES
-- =============================================================================

-- Email do_not_contact
ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_email BOOLEAN DEFAULT FALSE;

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_email_reason VARCHAR(50);

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_email_at TIMESTAMPTZ;

-- WhatsApp do_not_contact
ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_whatsapp BOOLEAN DEFAULT FALSE;

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_whatsapp_reason VARCHAR(50);

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_whatsapp_at TIMESTAMPTZ;

-- SMS do_not_contact
ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_sms BOOLEAN DEFAULT FALSE;

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_sms_reason VARCHAR(50);

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS do_not_contact_sms_at TIMESTAMPTZ;

-- Soft bounce counters
ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS email_soft_bounce_count INTEGER DEFAULT 0;

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS whatsapp_soft_bounce_count INTEGER DEFAULT 0;

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS sms_soft_bounce_count INTEGER DEFAULT 0;

-- Add constraint for do_not_contact_reason values
-- Note: Using CHECK constraint instead of ENUM for flexibility
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'driver_preferences_dnc_reason_check'
    ) THEN
        ALTER TABLE notify.driver_preferences
        ADD CONSTRAINT driver_preferences_dnc_reason_check CHECK (
            do_not_contact_email_reason IS NULL OR
            do_not_contact_email_reason IN (
                'HARD_BOUNCE', 'SOFT_BOUNCE_LIMIT', 'SPAM_COMPLAINT',
                'UNSUBSCRIBE', 'MANUAL', 'INVALID_PHONE'
            )
        );
    END IF;
END $$;

-- =============================================================================
-- STEP 2: CREATE HANDLE_BOUNCE_COMPLAINT FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.handle_bounce_complaint(
    p_tenant_id INTEGER,
    p_driver_id VARCHAR(255),
    p_channel VARCHAR(50),  -- EMAIL, WHATSAPP, SMS
    p_event_type VARCHAR(50),  -- BOUNCE, SOFT_BOUNCE, COMPLAINT, UNSUBSCRIBE
    p_provider_event_id VARCHAR(255) DEFAULT NULL,
    p_provider_response JSONB DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_channel_prefix VARCHAR(20);
    v_reason VARCHAR(50);
    v_bounce_count INTEGER;
    v_soft_bounce_threshold INTEGER := 3;
    v_result JSONB;
BEGIN
    -- Map channel to column prefix
    v_channel_prefix := CASE p_channel
        WHEN 'EMAIL' THEN 'email'
        WHEN 'WHATSAPP' THEN 'whatsapp'
        WHEN 'SMS' THEN 'sms'
        ELSE 'email'
    END;

    -- Map event type to do_not_contact reason
    v_reason := CASE p_event_type
        WHEN 'BOUNCE' THEN 'HARD_BOUNCE'
        WHEN 'COMPLAINT' THEN 'SPAM_COMPLAINT'
        WHEN 'UNSUBSCRIBE' THEN 'UNSUBSCRIBE'
        WHEN 'INVALID_PHONE' THEN 'INVALID_PHONE'
        ELSE NULL
    END;

    v_result := jsonb_build_object(
        'driver_id', p_driver_id,
        'channel', p_channel,
        'event_type', p_event_type,
        'action', NULL,
        'do_not_contact', FALSE
    );

    IF p_event_type = 'SOFT_BOUNCE' THEN
        -- Increment soft bounce counter
        EXECUTE format(
            'INSERT INTO notify.driver_preferences (tenant_id, driver_id, %I_soft_bounce_count)
             VALUES ($1, $2, 1)
             ON CONFLICT (tenant_id, driver_id) DO UPDATE
             SET %I_soft_bounce_count = COALESCE(notify.driver_preferences.%I_soft_bounce_count, 0) + 1,
                 updated_at = NOW()
             RETURNING %I_soft_bounce_count',
            v_channel_prefix, v_channel_prefix, v_channel_prefix, v_channel_prefix
        )
        INTO v_bounce_count
        USING p_tenant_id, p_driver_id;

        v_result := v_result || jsonb_build_object('soft_bounce_count', v_bounce_count);

        IF v_bounce_count >= v_soft_bounce_threshold THEN
            -- Threshold reached, set do_not_contact
            EXECUTE format(
                'UPDATE notify.driver_preferences
                 SET do_not_contact_%I = TRUE,
                     do_not_contact_%I_reason = $3,
                     do_not_contact_%I_at = NOW(),
                     updated_at = NOW()
                 WHERE tenant_id = $1 AND driver_id = $2',
                v_channel_prefix, v_channel_prefix, v_channel_prefix
            )
            USING p_tenant_id, p_driver_id, 'SOFT_BOUNCE_LIMIT';

            v_result := v_result || jsonb_build_object(
                'action', 'do_not_contact_set',
                'do_not_contact', TRUE,
                'reason', 'SOFT_BOUNCE_LIMIT'
            );
        ELSE
            v_result := v_result || jsonb_build_object('action', 'soft_bounce_recorded');
        END IF;

    ELSIF v_reason IS NOT NULL THEN
        -- Hard bounce, complaint, or unsubscribe - immediately set do_not_contact
        EXECUTE format(
            'INSERT INTO notify.driver_preferences (tenant_id, driver_id, do_not_contact_%I, do_not_contact_%I_reason, do_not_contact_%I_at)
             VALUES ($1, $2, TRUE, $3, NOW())
             ON CONFLICT (tenant_id, driver_id) DO UPDATE
             SET do_not_contact_%I = TRUE,
                 do_not_contact_%I_reason = $3,
                 do_not_contact_%I_at = NOW(),
                 updated_at = NOW()',
            v_channel_prefix, v_channel_prefix, v_channel_prefix,
            v_channel_prefix, v_channel_prefix, v_channel_prefix
        )
        USING p_tenant_id, p_driver_id, v_reason;

        v_result := v_result || jsonb_build_object(
            'action', 'do_not_contact_set',
            'do_not_contact', TRUE,
            'reason', v_reason
        );
    ELSE
        v_result := v_result || jsonb_build_object('action', 'ignored');
    END IF;

    RETURN v_result;
END;
$$;

-- =============================================================================
-- STEP 3: CREATE CLEAR_DO_NOT_CONTACT FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.clear_do_not_contact(
    p_tenant_id INTEGER,
    p_driver_id VARCHAR(255),
    p_channel VARCHAR(50),
    p_cleared_by VARCHAR(255),
    p_clear_reason TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_channel_prefix VARCHAR(20);
BEGIN
    -- Map channel to column prefix
    v_channel_prefix := CASE p_channel
        WHEN 'EMAIL' THEN 'email'
        WHEN 'WHATSAPP' THEN 'whatsapp'
        WHEN 'SMS' THEN 'sms'
        ELSE 'email'
    END;

    EXECUTE format(
        'UPDATE notify.driver_preferences
         SET do_not_contact_%I = FALSE,
             do_not_contact_%I_reason = NULL,
             do_not_contact_%I_at = NULL,
             %I_soft_bounce_count = 0,
             updated_at = NOW()
         WHERE tenant_id = $1 AND driver_id = $2',
        v_channel_prefix, v_channel_prefix, v_channel_prefix, v_channel_prefix
    )
    USING p_tenant_id, p_driver_id;

    -- Log the action (audit trail)
    RAISE NOTICE 'NOTIFY_DO_NOT_CONTACT_CLEARED: driver=%, channel=%, by=%, reason=%',
        p_driver_id, p_channel, p_cleared_by, p_clear_reason;

    RETURN TRUE;
END;
$$;

-- =============================================================================
-- STEP 4: UPDATE PROCESS_WEBHOOK_EVENT TO HANDLE NEW EVENT TYPES
-- =============================================================================

-- Drop and recreate to handle new event types
CREATE OR REPLACE FUNCTION notify.process_webhook_event(
    p_tenant_id INTEGER,
    p_provider VARCHAR(50),
    p_provider_event_id VARCHAR(255),
    p_event_type VARCHAR(50),
    p_event_timestamp TIMESTAMPTZ,
    p_provider_message_id VARCHAR(255),
    p_payload_hash VARCHAR(64) DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_outbox_id UUID;
    v_driver_id VARCHAR(255);
    v_channel VARCHAR(50);
    v_inserted BOOLEAN := FALSE;
BEGIN
    -- Try to insert webhook event (idempotent via unique constraint)
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
    SELECT id, driver_id, delivery_channel INTO v_outbox_id, v_driver_id, v_channel
    FROM notify.notification_outbox
    WHERE provider_message_id = p_provider_message_id
      AND tenant_id = p_tenant_id
    LIMIT 1;

    IF v_outbox_id IS NOT NULL THEN
        -- Link webhook event to outbox
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
              AND status IN ('SENT', 'DELIVERED');

        ELSIF p_event_type IN ('FAILED', 'BOUNCED', 'UNDELIVERABLE') THEN
            UPDATE notify.notification_outbox
            SET status = 'FAILED',
                provider_status = p_event_type,
                last_error_code = 'PROVIDER_' || p_event_type,
                last_error_at = p_event_timestamp,
                updated_at = NOW()
            WHERE id = v_outbox_id
              AND status IN ('SENT', 'SENDING');

        ELSIF p_event_type IN ('BOUNCE', 'SOFT_BOUNCE', 'COMPLAINT', 'UNSUBSCRIBE') THEN
            -- Handle bounce/complaint: update outbox AND set do_not_contact
            IF p_event_type != 'SOFT_BOUNCE' THEN
                UPDATE notify.notification_outbox
                SET status = 'FAILED',
                    provider_status = p_event_type,
                    last_error_code = 'BOUNCE_' || p_event_type,
                    last_error_at = p_event_timestamp,
                    updated_at = NOW()
                WHERE id = v_outbox_id
                  AND status IN ('SENT', 'SENDING', 'DELIVERED');
            END IF;

            -- Auto-set do_not_contact via handle_bounce_complaint
            PERFORM notify.handle_bounce_complaint(
                p_tenant_id,
                v_driver_id,
                v_channel,
                p_event_type
            );
        END IF;
    END IF;

    RETURN v_inserted;
END;
$$;

-- =============================================================================
-- STEP 5: CREATE CHECK_CAN_CONTACT FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION notify.check_can_contact(
    p_tenant_id INTEGER,
    p_driver_id VARCHAR(255),
    p_channel VARCHAR(50)
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
STABLE
AS $$
DECLARE
    v_prefs notify.driver_preferences%ROWTYPE;
BEGIN
    SELECT * INTO v_prefs
    FROM notify.driver_preferences
    WHERE tenant_id = p_tenant_id AND driver_id = p_driver_id;

    IF v_prefs IS NULL THEN
        -- No preferences = can contact (default opt-in)
        RETURN TRUE;
    END IF;

    -- Check channel-specific do_not_contact
    RETURN CASE p_channel
        WHEN 'EMAIL' THEN NOT COALESCE(v_prefs.do_not_contact_email, FALSE)
        WHEN 'WHATSAPP' THEN NOT COALESCE(v_prefs.do_not_contact_whatsapp, FALSE)
        WHEN 'SMS' THEN NOT COALESCE(v_prefs.do_not_contact_sms, FALSE)
        ELSE TRUE
    END;
END;
$$;

-- =============================================================================
-- STEP 6: UPDATE VERIFY FUNCTION
-- =============================================================================

-- Add bounce/dnc checks to existing verify function
CREATE OR REPLACE FUNCTION notify.verify_notification_integrity()
RETURNS TABLE(check_name VARCHAR(100), status VARCHAR(10), details TEXT)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    -- Check 1: RLS enabled on outbox
    RETURN QUERY
    SELECT
        'rls_enabled_outbox'::VARCHAR(100),
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'notification_outbox has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'notify.notification_outbox'::regclass;

    -- Check 2: RLS enabled on jobs
    RETURN QUERY
    SELECT
        'rls_enabled_jobs'::VARCHAR(100),
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'notification_jobs has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'notify.notification_jobs'::regclass;

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

    -- Check 5: Dedup key index exists
    RETURN QUERY
    SELECT
        'dedup_key_index_exists'::VARCHAR(100),
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'Dedup key unique index exists'::TEXT
    FROM pg_indexes
    WHERE schemaname = 'notify'
      AND tablename = 'notification_outbox'
      AND indexname LIKE '%dedup%';

    -- Check 6: Claim function exists
    RETURN QUERY
    SELECT
        'claim_function_exists'::VARCHAR(100),
        CASE WHEN to_regprocedure('notify.claim_outbox_batch(INTEGER)') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'claim_outbox_batch function exists'::TEXT;

    -- Check 7: Webhook unique constraint
    RETURN QUERY
    SELECT
        'webhook_unique_constraint'::VARCHAR(100),
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'webhook_events has unique event constraint'::TEXT
    FROM pg_constraint
    WHERE conrelid = 'notify.webhook_events'::regclass
      AND contype = 'u';

    -- Check 8: Rate limit table exists
    RETURN QUERY
    SELECT
        'rate_limit_table_exists'::VARCHAR(100),
        CASE WHEN to_regclass('notify.rate_limit_buckets') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'rate_limit_buckets table exists'::TEXT;

    -- Check 9: Templates exist
    RETURN QUERY
    SELECT
        'templates_exist'::VARCHAR(100),
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'WARN' END::VARCHAR(10),
        COALESCE(COUNT(*)::TEXT || ' templates configured', 'No templates found')::TEXT
    FROM notify.notification_templates
    WHERE is_active = TRUE;

    -- Check 10: Reaper function exists
    RETURN QUERY
    SELECT
        'reaper_function_exists'::VARCHAR(100),
        CASE WHEN to_regprocedure('notify.release_stuck_sending(INTEGER)') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'release_stuck_sending function exists'::TEXT;

    -- Check 11: RLS on driver_preferences
    RETURN QUERY
    SELECT
        'rls_enabled_preferences'::VARCHAR(100),
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'driver_preferences has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'notify.driver_preferences'::regclass;

    -- Check 12: do_not_contact columns exist
    RETURN QUERY
    SELECT
        'dnc_columns_exist'::VARCHAR(100),
        CASE WHEN COUNT(*) >= 3 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        COUNT(*)::TEXT || ' do_not_contact columns found (expected 3+)'::TEXT
    FROM information_schema.columns
    WHERE table_schema = 'notify'
      AND table_name = 'driver_preferences'
      AND column_name LIKE 'do_not_contact_%';

    -- Check 13: handle_bounce_complaint function exists
    RETURN QUERY
    SELECT
        'bounce_handler_exists'::VARCHAR(100),
        CASE WHEN to_regprocedure('notify.handle_bounce_complaint(INTEGER, VARCHAR, VARCHAR, VARCHAR, VARCHAR, JSONB)') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'handle_bounce_complaint function exists'::TEXT;

    -- Check 14: check_can_contact function exists
    RETURN QUERY
    SELECT
        'can_contact_check_exists'::VARCHAR(100),
        CASE WHEN to_regprocedure('notify.check_can_contact(INTEGER, VARCHAR, VARCHAR)') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'check_can_contact function exists'::TEXT;
END;
$$;

-- =============================================================================
-- STEP 7: GRANT PERMISSIONS
-- =============================================================================

-- Grant execute on new functions
GRANT EXECUTE ON FUNCTION notify.handle_bounce_complaint TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.handle_bounce_complaint TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.clear_do_not_contact TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.clear_do_not_contact TO solvereign_platform;
GRANT EXECUTE ON FUNCTION notify.check_can_contact TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.check_can_contact TO solvereign_platform;

-- =============================================================================
-- STEP 8: ADD DNC OVERRIDE COOLDOWN COLUMN
-- =============================================================================
-- After clearing DNC, there's a cooldown before resending to avoid immediate re-bounce

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS dnc_cleared_at TIMESTAMPTZ;

ALTER TABLE notify.driver_preferences
ADD COLUMN IF NOT EXISTS dnc_cleared_by VARCHAR(255);

-- Update clear_do_not_contact to set cooldown timestamp
CREATE OR REPLACE FUNCTION notify.clear_do_not_contact(
    p_tenant_id INTEGER,
    p_driver_id VARCHAR(255),
    p_channel VARCHAR(50),  -- EMAIL, WHATSAPP, SMS
    p_cleared_by VARCHAR(255),
    p_clear_reason VARCHAR(255)
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_channel_prefix VARCHAR(20);
BEGIN
    -- Map channel to column prefix
    v_channel_prefix := CASE LOWER(p_channel)
        WHEN 'email' THEN 'email'
        WHEN 'whatsapp' THEN 'whatsapp'
        WHEN 'sms' THEN 'sms'
        ELSE 'email'
    END;

    EXECUTE format(
        'UPDATE notify.driver_preferences
         SET do_not_contact_%I = FALSE,
             do_not_contact_%I_reason = NULL,
             do_not_contact_%I_at = NULL,
             %I_soft_bounce_count = 0,
             dnc_cleared_at = NOW(),
             dnc_cleared_by = $3,
             updated_at = NOW()
         WHERE tenant_id = $1 AND driver_id = $2',
        v_channel_prefix, v_channel_prefix, v_channel_prefix, v_channel_prefix
    )
    USING p_tenant_id, p_driver_id, p_cleared_by;

    -- Audit log (WARNING level for compliance visibility)
    RAISE WARNING 'NOTIFY_DNC_CLEARED: tenant=%, driver=%, channel=%, by=%, reason=%',
        p_tenant_id, p_driver_id, p_channel, p_cleared_by, p_clear_reason;

    RETURN TRUE;
END;
$$;

-- Function to check if cooldown has passed (default 1 hour)
CREATE OR REPLACE FUNCTION notify.check_dnc_cooldown(
    p_tenant_id INTEGER,
    p_driver_id VARCHAR(255),
    p_cooldown_minutes INTEGER DEFAULT 60
)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY INVOKER
AS $$
    SELECT COALESCE(
        (SELECT dnc_cleared_at IS NULL
            OR dnc_cleared_at + (p_cooldown_minutes || ' minutes')::INTERVAL <= NOW()
         FROM notify.driver_preferences
         WHERE tenant_id = p_tenant_id AND driver_id = p_driver_id),
        TRUE  -- No preferences = no cooldown
    );
$$;

GRANT EXECUTE ON FUNCTION notify.check_dnc_cooldown TO solvereign_api;
GRANT EXECUTE ON FUNCTION notify.check_dnc_cooldown TO solvereign_platform;


-- =============================================================================
-- STEP 9: UPDATE SUMMARY VIEW WITH SKIPPED COUNT + ADJUSTED KPIs
-- =============================================================================
-- SKIPPED is counted separately (not as FAILED)
-- Delivery rate excludes DNC-skipped from denominator

DROP VIEW IF EXISTS portal.snapshot_notify_summary CASCADE;

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
    -- SKIPPED is separate (not failed) - includes DNC, opted-out, invalid contact
    COUNT(*) FILTER (WHERE overall_status = 'SKIPPED') AS skipped_count,
    -- FAILED excludes SKIPPED (only actual send failures)
    COUNT(*) FILTER (WHERE overall_status IN ('NOTIFY_FAILED', 'NOTIFY_DEAD')) AS failed_count,
    -- Legacy: REVOKED/EXPIRED are their own category
    COUNT(*) FILTER (WHERE overall_status IN ('REVOKED', 'EXPIRED')) AS expired_revoked_count,
    -- Completion rate: acks / total
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE overall_status IN ('ACCEPTED', 'DECLINED'))
        / NULLIF(COUNT(*), 0),
        1
    ) AS completion_rate,
    -- Delivery rate: delivered / send-attemptable (excludes SKIPPED)
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE overall_status = 'DELIVERED')
        / NULLIF(
            COUNT(*) - COUNT(*) FILTER (WHERE overall_status = 'SKIPPED'),
            0
        ),
        1
    ) AS delivery_rate,
    -- Send-attemptable count (denominator for delivery rate)
    COUNT(*) - COUNT(*) FILTER (WHERE overall_status = 'SKIPPED') AS send_attemptable_count,
    MIN(issued_at) AS first_issued_at,
    MAX(ack_at) AS last_ack_at
FROM portal.notify_integration_status
GROUP BY tenant_id, snapshot_id;

GRANT SELECT ON portal.snapshot_notify_summary TO solvereign_api;


-- =============================================================================
-- STEP 10: UPDATE notify_integration_status TO INCLUDE SKIPPED STATUS
-- =============================================================================

DROP VIEW IF EXISTS portal.notify_integration_status CASCADE;

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
    o.skip_reason AS notify_skip_reason,  -- NEW: why was it skipped
    -- Read/Ack status
    r.first_read_at,
    r.last_read_at,
    r.read_count,
    a.status AS ack_status,
    a.ack_at,
    -- Derived status (includes SKIPPED)
    CASE
        WHEN t.revoked_at IS NOT NULL THEN 'REVOKED'
        WHEN t.expires_at < NOW() THEN 'EXPIRED'
        WHEN o.status = 'SKIPPED' THEN 'SKIPPED'  -- NEW: DNC, opted-out, etc.
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

-- Recreate summary view (depends on integration_status)
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
    COUNT(*) FILTER (WHERE overall_status = 'SKIPPED') AS skipped_count,
    COUNT(*) FILTER (WHERE overall_status IN ('NOTIFY_FAILED', 'NOTIFY_DEAD')) AS failed_count,
    COUNT(*) FILTER (WHERE overall_status IN ('REVOKED', 'EXPIRED')) AS expired_revoked_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE overall_status IN ('ACCEPTED', 'DECLINED'))
        / NULLIF(COUNT(*), 0),
        1
    ) AS completion_rate,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE overall_status = 'DELIVERED')
        / NULLIF(
            COUNT(*) - COUNT(*) FILTER (WHERE overall_status = 'SKIPPED'),
            0
        ),
        1
    ) AS delivery_rate,
    COUNT(*) - COUNT(*) FILTER (WHERE overall_status = 'SKIPPED') AS send_attemptable_count,
    MIN(issued_at) AS first_issued_at,
    MAX(ack_at) AS last_ack_at
FROM portal.notify_integration_status
GROUP BY tenant_id, snapshot_id;

GRANT SELECT ON portal.snapshot_notify_summary TO solvereign_api;


-- =============================================================================
-- STEP 11: PATCH issue_token_atomic() TO CHECK DNC STATUS
-- =============================================================================
-- Replaces the function from 037a to add DNC check at outbox creation time.
-- If driver is on DNC list for the channel, returns is_dnc_blocked=TRUE
-- and does NOT create outbox entry (prevents wasted sends).

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
    is_duplicate BOOLEAN,
    is_dnc_blocked BOOLEAN  -- NEW: TRUE if driver is on do-not-contact list
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_dedup_key CHAR(64);
    v_token_id BIGINT;
    v_outbox_id UUID;
    v_existing_token_id BIGINT;
    v_can_contact BOOLEAN;
BEGIN
    -- NEW: Check do-not-contact status FIRST
    v_can_contact := notify.check_can_contact(p_tenant_id, p_driver_id, p_delivery_channel);

    IF NOT v_can_contact THEN
        -- Driver is on DNC list - return blocked status without creating anything
        RETURN QUERY SELECT NULL::BIGINT, NULL::UUID, FALSE, TRUE;
        RETURN;
    END IF;

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
        RETURN QUERY SELECT v_existing_token_id, NULL::UUID, TRUE, FALSE;
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

    RETURN QUERY SELECT v_token_id, v_outbox_id, FALSE, FALSE;
END;
$$;

COMMENT ON FUNCTION portal.issue_token_atomic IS
    'Atomic token + outbox creation with DNC check. Returns is_dnc_blocked=TRUE if driver is on do-not-contact list.';

-- Re-grant permissions (function signature changed)
GRANT EXECUTE ON FUNCTION portal.issue_token_atomic(INTEGER, INTEGER, UUID, VARCHAR, VARCHAR, CHAR, TEXT, TEXT, TIMESTAMPTZ, UUID, VARCHAR, TEXT) TO solvereign_api;


COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Run this after applying migration:
--   SELECT * FROM notify.verify_notification_integrity();
-- Expected: 14 checks, at least 12 PASS (templates may be WARN if not seeded)
--
-- Test bounce handling:
--   SELECT notify.handle_bounce_complaint(1, 'DRV-001', 'EMAIL', 'BOUNCE');
--   SELECT notify.check_can_contact(1, 'DRV-001', 'EMAIL');  -- Should be FALSE
--   SELECT notify.clear_do_not_contact(1, 'DRV-001', 'EMAIL', 'admin@test.com', 'Address corrected');
--   SELECT notify.check_can_contact(1, 'DRV-001', 'EMAIL');  -- Should be TRUE again
-- =============================================================================
