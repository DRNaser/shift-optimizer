-- =============================================================================
-- SOLVEREIGN V4.1 - Notification Pipeline Schema
-- =============================================================================
-- Migration: 034_notifications.sql
-- Purpose: Notification outbox pattern for reliable driver notifications
-- Author: Agent V4.1
-- Date: 2026-01-09
--
-- ARCHITECTURE:
-- Uses transactional outbox pattern for reliable notification delivery:
-- 1. notification_jobs - High-level job tracking (bulk sends, campaigns)
-- 2. notification_outbox - Individual messages to process
-- 3. notification_delivery_log - Delivery attempts and outcomes
--
-- DELIVERY CHANNELS:
-- - WHATSAPP: Via WhatsApp Business API
-- - EMAIL: Via SendGrid/SMTP
-- - SMS: Via Twilio/SNS (optional)
-- - PUSH: Future - PWA push notifications
--
-- SECURITY:
-- - RLS enforced on all tables
-- - Phone/email stored as SHA-256 hash for lookup (GDPR)
-- - Raw contact info only in encrypted vault (external)
-- =============================================================================

BEGIN;

-- Create notify schema
CREATE SCHEMA IF NOT EXISTS notify;

-- =============================================================================
-- NOTIFICATION JOBS TABLE
-- =============================================================================
-- High-level tracking of bulk notification sends (e.g., "notify all drivers for snapshot X")

CREATE TABLE IF NOT EXISTS notify.notification_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID,

    -- Job identification
    job_type VARCHAR(50) NOT NULL,  -- SNAPSHOT_PUBLISH, REMINDER, RESEND, CUSTOM
    reference_type VARCHAR(50),     -- SNAPSHOT, PLAN_VERSION, etc.
    reference_id UUID,              -- snapshot_id or plan_version_id

    -- Job scope
    target_driver_ids TEXT[],       -- NULL = all drivers in scope
    target_group VARCHAR(50),       -- UNREAD, UNACKED, DECLINED, ALL
    delivery_channel VARCHAR(50) NOT NULL DEFAULT 'WHATSAPP',

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    -- PENDING -> PROCESSING -> COMPLETED | PARTIALLY_FAILED | FAILED

    -- Counts
    total_count INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    delivered_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,

    -- Job metadata
    initiated_by VARCHAR(255) NOT NULL,  -- email of user who triggered
    initiated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Configuration
    priority INTEGER DEFAULT 5,  -- 1 = highest, 10 = lowest
    retry_policy JSONB DEFAULT '{"max_attempts": 3, "backoff_seconds": [60, 300, 900]}',
    scheduled_at TIMESTAMPTZ,   -- NULL = immediate, else delayed send
    expires_at TIMESTAMPTZ,     -- After this time, skip pending messages

    -- Error tracking
    last_error TEXT,
    error_count INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT notification_jobs_status_check CHECK (
        status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'PARTIALLY_FAILED', 'FAILED', 'CANCELLED')
    ),
    CONSTRAINT notification_jobs_channel_check CHECK (
        delivery_channel IN ('WHATSAPP', 'EMAIL', 'SMS', 'PUSH')
    ),
    CONSTRAINT notification_jobs_type_check CHECK (
        job_type IN ('SNAPSHOT_PUBLISH', 'REMINDER', 'RESEND', 'PORTAL_INVITE', 'CUSTOM')
    )
);

-- Indexes for job queries
CREATE INDEX IF NOT EXISTS idx_notification_jobs_tenant_status
    ON notify.notification_jobs(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_notification_jobs_reference
    ON notify.notification_jobs(reference_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_notification_jobs_scheduled
    ON notify.notification_jobs(scheduled_at) WHERE status = 'PENDING';


-- =============================================================================
-- NOTIFICATION OUTBOX TABLE
-- =============================================================================
-- Individual messages to be sent (one per driver per notification)

CREATE TABLE IF NOT EXISTS notify.notification_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    job_id UUID REFERENCES notify.notification_jobs(id) ON DELETE SET NULL,

    -- Recipient (hashed for privacy)
    driver_id VARCHAR(255) NOT NULL,
    driver_name VARCHAR(255),         -- For display/logging (not contact info)
    recipient_hash VARCHAR(64),       -- SHA-256 of phone/email for dedup
    delivery_channel VARCHAR(50) NOT NULL,

    -- Message content
    message_template VARCHAR(100) NOT NULL,  -- Template key
    message_params JSONB DEFAULT '{}',        -- Template variables
    portal_url TEXT,                          -- Magic link URL if applicable

    -- Reference linking
    snapshot_id UUID,
    reference_type VARCHAR(50),
    reference_id UUID,

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    -- PENDING -> PROCESSING -> SENT -> DELIVERED | FAILED | EXPIRED

    -- Attempt tracking
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    next_attempt_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,

    -- Provider response
    provider_message_id VARCHAR(255),  -- WhatsApp/SendGrid message ID
    provider_status VARCHAR(50),       -- Provider-specific status
    provider_response JSONB,           -- Full provider response for debugging

    -- Error tracking
    error_code VARCHAR(50),
    error_message TEXT,

    -- Timing
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,

    CONSTRAINT notification_outbox_status_check CHECK (
        status IN ('PENDING', 'PROCESSING', 'SENT', 'DELIVERED', 'FAILED', 'EXPIRED', 'CANCELLED')
    ),
    CONSTRAINT notification_outbox_channel_check CHECK (
        delivery_channel IN ('WHATSAPP', 'EMAIL', 'SMS', 'PUSH')
    )
);

-- Indexes for outbox processing
CREATE INDEX IF NOT EXISTS idx_notification_outbox_pending
    ON notify.notification_outbox(tenant_id, status, next_attempt_at)
    WHERE status IN ('PENDING', 'PROCESSING');
CREATE INDEX IF NOT EXISTS idx_notification_outbox_job
    ON notify.notification_outbox(job_id);
CREATE INDEX IF NOT EXISTS idx_notification_outbox_driver
    ON notify.notification_outbox(tenant_id, driver_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_notification_outbox_recipient_hash
    ON notify.notification_outbox(recipient_hash, delivery_channel);


-- =============================================================================
-- NOTIFICATION DELIVERY LOG TABLE
-- =============================================================================
-- Append-only log of all delivery attempts and webhook callbacks

CREATE TABLE IF NOT EXISTS notify.notification_delivery_log (
    id SERIAL PRIMARY KEY,
    log_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    outbox_id UUID NOT NULL REFERENCES notify.notification_outbox(id),

    -- Attempt tracking
    attempt_number INTEGER NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- ATTEMPT, SENT, DELIVERED, FAILED, WEBHOOK

    -- Provider details
    provider VARCHAR(50),             -- WHATSAPP_CLOUD, SENDGRID, TWILIO
    provider_message_id VARCHAR(255),
    provider_status VARCHAR(50),
    provider_response JSONB,

    -- Webhook data (if event from provider callback)
    webhook_event_id VARCHAR(255),
    webhook_timestamp TIMESTAMPTZ,
    webhook_raw JSONB,

    -- Error tracking
    error_code VARCHAR(50),
    error_message TEXT,
    is_retryable BOOLEAN DEFAULT TRUE,

    -- Timing
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    duration_ms INTEGER,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for delivery log queries
CREATE INDEX IF NOT EXISTS idx_notification_delivery_log_outbox
    ON notify.notification_delivery_log(outbox_id);
CREATE INDEX IF NOT EXISTS idx_notification_delivery_log_tenant_event
    ON notify.notification_delivery_log(tenant_id, event_at DESC);
CREATE INDEX IF NOT EXISTS idx_notification_delivery_log_provider_msg
    ON notify.notification_delivery_log(provider_message_id) WHERE provider_message_id IS NOT NULL;


-- =============================================================================
-- NOTIFICATION TEMPLATES TABLE
-- =============================================================================
-- Message templates per tenant/channel

CREATE TABLE IF NOT EXISTS notify.notification_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL = system default
    site_id UUID,  -- NULL = all sites

    -- Template identification
    template_key VARCHAR(100) NOT NULL,  -- e.g., PORTAL_INVITE, REMINDER_24H
    delivery_channel VARCHAR(50) NOT NULL,
    language VARCHAR(10) DEFAULT 'de',

    -- WhatsApp-specific (requires pre-approval)
    whatsapp_template_name VARCHAR(255),
    whatsapp_template_namespace VARCHAR(255),

    -- Template content
    subject VARCHAR(500),              -- For email
    body_template TEXT NOT NULL,       -- Supports {{variable}} placeholders
    body_html TEXT,                    -- HTML version for email

    -- Configuration
    is_active BOOLEAN DEFAULT TRUE,
    requires_approval BOOLEAN DEFAULT FALSE,  -- WhatsApp templates need Meta approval
    approval_status VARCHAR(50),

    -- Variables this template expects
    expected_params TEXT[],  -- ['driver_name', 'portal_url', 'shift_date']

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT notification_templates_unique_key UNIQUE (
        COALESCE(tenant_id, -1),
        template_key,
        delivery_channel,
        language
    ),
    CONSTRAINT notification_templates_channel_check CHECK (
        delivery_channel IN ('WHATSAPP', 'EMAIL', 'SMS', 'PUSH')
    )
);


-- =============================================================================
-- NOTIFICATION PREFERENCES TABLE
-- =============================================================================
-- Driver notification preferences (opt-in/opt-out)

CREATE TABLE IF NOT EXISTS notify.driver_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    driver_id VARCHAR(255) NOT NULL,

    -- Channel preferences
    preferred_channel VARCHAR(50) DEFAULT 'WHATSAPP',
    whatsapp_opted_in BOOLEAN DEFAULT FALSE,
    whatsapp_opted_in_at TIMESTAMPTZ,
    email_opted_in BOOLEAN DEFAULT FALSE,
    email_opted_in_at TIMESTAMPTZ,
    sms_opted_in BOOLEAN DEFAULT FALSE,
    sms_opted_in_at TIMESTAMPTZ,

    -- Contact verification
    contact_verified BOOLEAN DEFAULT FALSE,
    contact_verified_at TIMESTAMPTZ,

    -- Quiet hours (local time)
    quiet_hours_start TIME,  -- e.g., 22:00
    quiet_hours_end TIME,    -- e.g., 07:00
    timezone VARCHAR(50) DEFAULT 'Europe/Vienna',

    -- GDPR compliance
    consent_given_at TIMESTAMPTZ,
    consent_source VARCHAR(100),  -- PORTAL, APP, MANUAL

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT driver_preferences_unique_driver UNIQUE (tenant_id, driver_id),
    CONSTRAINT driver_preferences_channel_check CHECK (
        preferred_channel IN ('WHATSAPP', 'EMAIL', 'SMS', 'PUSH', 'NONE')
    )
);


-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================

-- Enable RLS on all notify tables
ALTER TABLE notify.notification_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.notification_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.notification_delivery_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.notification_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.driver_preferences ENABLE ROW LEVEL SECURITY;

-- FORCE RLS for table owners
ALTER TABLE notify.notification_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE notify.notification_outbox FORCE ROW LEVEL SECURITY;
ALTER TABLE notify.notification_delivery_log FORCE ROW LEVEL SECURITY;
ALTER TABLE notify.notification_templates FORCE ROW LEVEL SECURITY;
ALTER TABLE notify.driver_preferences FORCE ROW LEVEL SECURITY;

-- RLS Policies for notification_jobs
CREATE POLICY tenant_isolation_jobs ON notify.notification_jobs
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        tenant_id
    ));

-- RLS Policies for notification_outbox
CREATE POLICY tenant_isolation_outbox ON notify.notification_outbox
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        tenant_id
    ));

-- RLS Policies for notification_delivery_log
CREATE POLICY tenant_isolation_delivery_log ON notify.notification_delivery_log
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        tenant_id
    ));

-- RLS Policies for notification_templates
-- Templates can be system-wide (tenant_id NULL) or per-tenant
CREATE POLICY template_access ON notify.notification_templates
    FOR ALL
    USING (
        tenant_id IS NULL  -- System templates accessible to all
        OR tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
            tenant_id
        )
    );

-- RLS Policies for driver_preferences
CREATE POLICY tenant_isolation_preferences ON notify.driver_preferences
    FOR ALL
    USING (tenant_id = COALESCE(
        NULLIF(current_setting('app.current_tenant_id', TRUE), '')::INTEGER,
        tenant_id
    ));


-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function: Create notification job with outbox entries
CREATE OR REPLACE FUNCTION notify.create_notification_job(
    p_tenant_id INTEGER,
    p_site_id UUID,
    p_job_type VARCHAR(50),
    p_reference_type VARCHAR(50),
    p_reference_id UUID,
    p_delivery_channel VARCHAR(50),
    p_initiated_by VARCHAR(255),
    p_driver_ids TEXT[],  -- Array of driver_ids
    p_portal_urls JSONB,  -- {driver_id: portal_url}
    p_template_key VARCHAR(100),
    p_template_params JSONB DEFAULT '{}'
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY INVOKER  -- Uses caller privileges, RLS applies
AS $$
DECLARE
    v_job_id UUID;
    v_driver_id TEXT;
    v_portal_url TEXT;
    v_driver_count INTEGER := 0;
BEGIN
    -- Create the job
    INSERT INTO notify.notification_jobs (
        tenant_id, site_id, job_type, reference_type, reference_id,
        delivery_channel, initiated_by, target_driver_ids,
        status, total_count
    ) VALUES (
        p_tenant_id, p_site_id, p_job_type, p_reference_type, p_reference_id,
        p_delivery_channel, p_initiated_by, p_driver_ids,
        'PENDING', COALESCE(array_length(p_driver_ids, 1), 0)
    )
    RETURNING id INTO v_job_id;

    -- Create outbox entries for each driver
    FOREACH v_driver_id IN ARRAY p_driver_ids
    LOOP
        v_portal_url := p_portal_urls ->> v_driver_id;

        INSERT INTO notify.notification_outbox (
            tenant_id, job_id, driver_id, delivery_channel,
            message_template, message_params, portal_url,
            snapshot_id, reference_type, reference_id,
            status, next_attempt_at, expires_at
        ) VALUES (
            p_tenant_id, v_job_id, v_driver_id, p_delivery_channel,
            p_template_key, p_template_params, v_portal_url,
            p_reference_id, p_reference_type, p_reference_id,
            'PENDING', NOW(), NOW() + INTERVAL '7 days'
        );

        v_driver_count := v_driver_count + 1;
    END LOOP;

    -- Update job total count
    UPDATE notify.notification_jobs
    SET total_count = v_driver_count
    WHERE id = v_job_id;

    RETURN v_job_id;
END;
$$;


-- Function: Claim next batch of messages to process (worker function)
CREATE OR REPLACE FUNCTION notify.claim_outbox_batch(
    p_batch_size INTEGER DEFAULT 10,
    p_worker_id VARCHAR(100) DEFAULT NULL
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
    attempt_count INTEGER
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    RETURN QUERY
    WITH claimed AS (
        SELECT o.id
        FROM notify.notification_outbox o
        WHERE o.status = 'PENDING'
          AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= NOW())
          AND (o.expires_at IS NULL OR o.expires_at > NOW())
        ORDER BY o.created_at
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    )
    UPDATE notify.notification_outbox o
    SET
        status = 'PROCESSING',
        attempt_count = o.attempt_count + 1,
        last_attempt_at = NOW(),
        updated_at = NOW()
    FROM claimed c
    WHERE o.id = c.id
    RETURNING
        o.id,
        o.tenant_id,
        o.driver_id,
        o.driver_name,
        o.delivery_channel,
        o.message_template,
        o.message_params,
        o.portal_url,
        o.attempt_count;
END;
$$;


-- Function: Record delivery result
CREATE OR REPLACE FUNCTION notify.record_delivery_result(
    p_outbox_id UUID,
    p_success BOOLEAN,
    p_provider VARCHAR(50),
    p_provider_message_id VARCHAR(255) DEFAULT NULL,
    p_provider_status VARCHAR(50) DEFAULT NULL,
    p_provider_response JSONB DEFAULT NULL,
    p_error_code VARCHAR(50) DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL,
    p_is_retryable BOOLEAN DEFAULT TRUE,
    p_duration_ms INTEGER DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_outbox RECORD;
    v_new_status VARCHAR(50);
    v_next_attempt TIMESTAMPTZ;
    v_retry_policy JSONB;
BEGIN
    -- Get current outbox state
    SELECT o.*, j.retry_policy
    INTO v_outbox
    FROM notify.notification_outbox o
    LEFT JOIN notify.notification_jobs j ON j.id = o.job_id
    WHERE o.id = p_outbox_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Outbox message not found: %', p_outbox_id;
    END IF;

    v_retry_policy := COALESCE(v_outbox.retry_policy, '{"max_attempts": 3, "backoff_seconds": [60, 300, 900]}');

    IF p_success THEN
        v_new_status := 'SENT';
        v_next_attempt := NULL;
    ELSE
        IF NOT p_is_retryable OR v_outbox.attempt_count >= v_outbox.max_attempts THEN
            v_new_status := 'FAILED';
            v_next_attempt := NULL;
        ELSE
            v_new_status := 'PENDING';  -- Retry
            -- Calculate next attempt with exponential backoff
            v_next_attempt := NOW() + (
                COALESCE(
                    (v_retry_policy -> 'backoff_seconds' ->> (v_outbox.attempt_count - 1))::INTEGER,
                    900
                ) * INTERVAL '1 second'
            );
        END IF;
    END IF;

    -- Update outbox
    UPDATE notify.notification_outbox
    SET
        status = v_new_status,
        provider_message_id = COALESCE(p_provider_message_id, provider_message_id),
        provider_status = p_provider_status,
        provider_response = p_provider_response,
        error_code = p_error_code,
        error_message = p_error_message,
        next_attempt_at = v_next_attempt,
        sent_at = CASE WHEN p_success THEN NOW() ELSE sent_at END,
        updated_at = NOW()
    WHERE id = p_outbox_id;

    -- Log delivery attempt
    INSERT INTO notify.notification_delivery_log (
        tenant_id, outbox_id, attempt_number, event_type,
        provider, provider_message_id, provider_status, provider_response,
        error_code, error_message, is_retryable, duration_ms
    ) VALUES (
        v_outbox.tenant_id, p_outbox_id, v_outbox.attempt_count,
        CASE WHEN p_success THEN 'SENT' ELSE 'FAILED' END,
        p_provider, p_provider_message_id, p_provider_status, p_provider_response,
        p_error_code, p_error_message, p_is_retryable, p_duration_ms
    );

    -- Update job counts
    IF v_outbox.job_id IS NOT NULL THEN
        UPDATE notify.notification_jobs
        SET
            sent_count = sent_count + CASE WHEN p_success THEN 1 ELSE 0 END,
            failed_count = failed_count + CASE WHEN v_new_status = 'FAILED' THEN 1 ELSE 0 END,
            updated_at = NOW()
        WHERE id = v_outbox.job_id;
    END IF;
END;
$$;


-- Function: Record webhook delivery confirmation
CREATE OR REPLACE FUNCTION notify.record_webhook_event(
    p_provider_message_id VARCHAR(255),
    p_event_type VARCHAR(50),  -- DELIVERED, READ, FAILED
    p_provider VARCHAR(50),
    p_provider_status VARCHAR(50),
    p_webhook_event_id VARCHAR(255),
    p_webhook_timestamp TIMESTAMPTZ,
    p_webhook_raw JSONB
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_outbox RECORD;
BEGIN
    -- Find outbox by provider message ID
    SELECT * INTO v_outbox
    FROM notify.notification_outbox
    WHERE provider_message_id = p_provider_message_id;

    IF NOT FOUND THEN
        -- Log orphaned webhook (provider message ID not found)
        INSERT INTO notify.notification_delivery_log (
            tenant_id, outbox_id, attempt_number, event_type,
            provider, provider_message_id, provider_status,
            webhook_event_id, webhook_timestamp, webhook_raw
        ) VALUES (
            1, gen_random_uuid(), 0, 'WEBHOOK_ORPHAN',  -- Placeholder values
            p_provider, p_provider_message_id, p_provider_status,
            p_webhook_event_id, p_webhook_timestamp, p_webhook_raw
        );
        RETURN;
    END IF;

    -- Update outbox status based on webhook event
    IF p_event_type = 'DELIVERED' THEN
        UPDATE notify.notification_outbox
        SET
            status = 'DELIVERED',
            provider_status = p_provider_status,
            delivered_at = COALESCE(p_webhook_timestamp, NOW()),
            updated_at = NOW()
        WHERE id = v_outbox.id;

        -- Update job delivered count
        IF v_outbox.job_id IS NOT NULL THEN
            UPDATE notify.notification_jobs
            SET
                delivered_count = delivered_count + 1,
                updated_at = NOW()
            WHERE id = v_outbox.job_id;
        END IF;
    ELSIF p_event_type = 'FAILED' THEN
        UPDATE notify.notification_outbox
        SET
            status = 'FAILED',
            provider_status = p_provider_status,
            error_code = 'WEBHOOK_FAILURE',
            updated_at = NOW()
        WHERE id = v_outbox.id;

        -- Update job failed count
        IF v_outbox.job_id IS NOT NULL THEN
            UPDATE notify.notification_jobs
            SET
                failed_count = failed_count + 1,
                updated_at = NOW()
            WHERE id = v_outbox.job_id;
        END IF;
    END IF;

    -- Log webhook event
    INSERT INTO notify.notification_delivery_log (
        tenant_id, outbox_id, attempt_number, event_type,
        provider, provider_message_id, provider_status,
        webhook_event_id, webhook_timestamp, webhook_raw
    ) VALUES (
        v_outbox.tenant_id, v_outbox.id, v_outbox.attempt_count, 'WEBHOOK',
        p_provider, p_provider_message_id, p_provider_status,
        p_webhook_event_id, p_webhook_timestamp, p_webhook_raw
    );
END;
$$;


-- Function: Update job status based on outbox completion
CREATE OR REPLACE FUNCTION notify.update_job_status()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_job RECORD;
    v_new_status VARCHAR(50);
BEGIN
    -- Only run when outbox status changes to terminal state
    IF NEW.status NOT IN ('SENT', 'DELIVERED', 'FAILED', 'EXPIRED', 'CANCELLED') THEN
        RETURN NEW;
    END IF;

    IF NEW.job_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Check job completion
    SELECT
        j.*,
        COUNT(*) FILTER (WHERE o.status IN ('PENDING', 'PROCESSING')) as pending_count,
        COUNT(*) FILTER (WHERE o.status IN ('SENT', 'DELIVERED')) as success_count,
        COUNT(*) FILTER (WHERE o.status IN ('FAILED', 'EXPIRED', 'CANCELLED')) as failed_count
    INTO v_job
    FROM notify.notification_jobs j
    LEFT JOIN notify.notification_outbox o ON o.job_id = j.id
    WHERE j.id = NEW.job_id
    GROUP BY j.id;

    -- Determine new job status
    IF v_job.pending_count = 0 THEN
        IF v_job.failed_count = 0 THEN
            v_new_status := 'COMPLETED';
        ELSIF v_job.success_count = 0 THEN
            v_new_status := 'FAILED';
        ELSE
            v_new_status := 'PARTIALLY_FAILED';
        END IF;

        UPDATE notify.notification_jobs
        SET
            status = v_new_status,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE id = NEW.job_id;
    END IF;

    RETURN NEW;
END;
$$;

-- Trigger to update job status when outbox changes
DROP TRIGGER IF EXISTS tr_update_job_status ON notify.notification_outbox;
CREATE TRIGGER tr_update_job_status
    AFTER UPDATE OF status ON notify.notification_outbox
    FOR EACH ROW
    EXECUTE FUNCTION notify.update_job_status();


-- =============================================================================
-- INTEGRITY VERIFICATION
-- =============================================================================

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

    -- Check 3: RLS enabled on notification_delivery_log
    RETURN QUERY
    SELECT
        'rls_enabled_delivery_log'::VARCHAR(100),
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'notification_delivery_log has RLS enabled and forced'::TEXT
    FROM pg_class
    WHERE oid = 'notify.notification_delivery_log'::regclass;

    -- Check 4: All jobs have valid status
    RETURN QUERY
    SELECT
        'valid_job_statuses'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        COALESCE(
            'Invalid job statuses found: ' || COUNT(*)::TEXT,
            'All job statuses valid'
        )::TEXT
    FROM notify.notification_jobs
    WHERE status NOT IN ('PENDING', 'PROCESSING', 'COMPLETED', 'PARTIALLY_FAILED', 'FAILED', 'CANCELLED');

    -- Check 5: All outbox entries have valid status
    RETURN QUERY
    SELECT
        'valid_outbox_statuses'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        COALESCE(
            'Invalid outbox statuses found: ' || COUNT(*)::TEXT,
            'All outbox statuses valid'
        )::TEXT
    FROM notify.notification_outbox
    WHERE status NOT IN ('PENDING', 'PROCESSING', 'SENT', 'DELIVERED', 'FAILED', 'EXPIRED', 'CANCELLED');

    -- Check 6: No orphaned outbox entries (job_id references valid job)
    RETURN QUERY
    SELECT
        'no_orphaned_outbox'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        COALESCE(
            'Orphaned outbox entries: ' || COUNT(*)::TEXT,
            'No orphaned outbox entries'
        )::TEXT
    FROM notify.notification_outbox o
    LEFT JOIN notify.notification_jobs j ON j.id = o.job_id
    WHERE o.job_id IS NOT NULL AND j.id IS NULL;

    -- Check 7: Tenant ID not null on all tables
    RETURN QUERY
    SELECT
        'tenant_id_not_null'::VARCHAR(100),
        CASE WHEN (
            SELECT COUNT(*) FROM notify.notification_jobs WHERE tenant_id IS NULL
        ) + (
            SELECT COUNT(*) FROM notify.notification_outbox WHERE tenant_id IS NULL
        ) + (
            SELECT COUNT(*) FROM notify.notification_delivery_log WHERE tenant_id IS NULL
        ) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'All tables have non-null tenant_id'::TEXT;

    -- Check 8: Job counts consistency
    RETURN QUERY
    SELECT
        'job_counts_consistent'::VARCHAR(100),
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
        'Job sent+delivered+failed counts match outbox'::TEXT
    FROM notify.notification_jobs j
    WHERE j.status = 'COMPLETED'
      AND j.total_count != (j.sent_count + j.delivered_count + j.failed_count);

    RETURN;
END;
$$;


-- =============================================================================
-- DEFAULT TEMPLATES
-- =============================================================================

INSERT INTO notify.notification_templates (
    tenant_id, template_key, delivery_channel, language,
    whatsapp_template_name, body_template, expected_params
) VALUES
-- Portal Invite (German)
(NULL, 'PORTAL_INVITE', 'WHATSAPP', 'de',
    'portal_invite_v1',
    'Hallo {{driver_name}}, Ihr neuer Schichtplan ist verfuegbar. Bitte bestaetigen Sie hier: {{portal_url}}',
    ARRAY['driver_name', 'portal_url']),

-- Portal Invite (English)
(NULL, 'PORTAL_INVITE', 'WHATSAPP', 'en',
    'portal_invite_v1',
    'Hello {{driver_name}}, your new shift schedule is available. Please confirm here: {{portal_url}}',
    ARRAY['driver_name', 'portal_url']),

-- Reminder (German)
(NULL, 'REMINDER_24H', 'WHATSAPP', 'de',
    'reminder_24h_v1',
    'Erinnerung: Ihr Schichtplan wartet noch auf Bestaetigung. Bitte bestaetigen Sie hier: {{portal_url}}',
    ARRAY['driver_name', 'portal_url']),

-- Email Portal Invite (German)
(NULL, 'PORTAL_INVITE', 'EMAIL', 'de',
    NULL,
    'Hallo {{driver_name}},

Ihr neuer Schichtplan fuer die Woche {{week_start}} ist verfuegbar.

Bitte bestaetigen Sie Ihren Plan hier: {{portal_url}}

Mit freundlichen Gruessen,
Ihr Dispositionsteam',
    ARRAY['driver_name', 'portal_url', 'week_start']),

-- Email Reminder (German)
(NULL, 'REMINDER_24H', 'EMAIL', 'de',
    NULL,
    'Hallo {{driver_name}},

Ihr Schichtplan wartet noch auf Ihre Bestaetigung. Bitte bestaetigen Sie hier:

{{portal_url}}

Mit freundlichen Gruessen,
Ihr Dispositionsteam',
    ARRAY['driver_name', 'portal_url'])

ON CONFLICT DO NOTHING;


-- =============================================================================
-- GRANTS
-- =============================================================================

-- Grant schema usage
GRANT USAGE ON SCHEMA notify TO solvereign_api;
GRANT USAGE ON SCHEMA notify TO solvereign_platform;

-- Grant table access
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA notify TO solvereign_api;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA notify TO solvereign_platform;

-- Grant sequence access
GRANT USAGE ON ALL SEQUENCES IN SCHEMA notify TO solvereign_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA notify TO solvereign_platform;

-- Grant function execution
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA notify TO solvereign_api;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA notify TO solvereign_platform;

COMMIT;

-- =============================================================================
-- VERIFICATION QUERY (Run after migration)
-- =============================================================================
-- SELECT * FROM notify.verify_notification_integrity();
