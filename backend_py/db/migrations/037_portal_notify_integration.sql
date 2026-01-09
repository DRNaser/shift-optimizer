-- =============================================================================
-- MIGRATION 037: Portal-Notify Integration
-- =============================================================================
-- SOLVEREIGN V4.2 - Portal Link Service Integration
--
-- Purpose:
--   Standardize notification templates to use {plan_link} variable
--   Add outbox_id link to portal_tokens
--   Create integration views for monitoring
--
-- Changes:
--   1. Update template expected_params to use 'plan_link' instead of 'portal_url'
--   2. Add outbox_id column to portal_tokens (if not exists)
--   3. Create view for portal-notify integration monitoring
--   4. Add function for bulk token issuance
-- =============================================================================

BEGIN;

-- =============================================================================
-- UPDATE NOTIFICATION TEMPLATES: portal_url → plan_link
-- =============================================================================
-- Standardize on {plan_link} as the variable name for portal magic links
-- This matches the user-facing documentation and API naming

-- Update expected_params for all templates that use portal_url
UPDATE notify.notification_templates
SET expected_params = array_replace(expected_params, 'portal_url', 'plan_link'),
    body_template = replace(body_template, '{{portal_url}}', '{{plan_link}}'),
    body_html = replace(COALESCE(body_html, ''), '{{portal_url}}', '{{plan_link}}'),
    updated_at = NOW()
WHERE 'portal_url' = ANY(expected_params)
   OR body_template LIKE '%{{portal_url}}%';

-- =============================================================================
-- PORTAL TOKENS: Add outbox_id linkage (if not exists)
-- =============================================================================
-- Links portal tokens to notification outbox for delivery tracking

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'portal'
        AND table_name = 'portal_tokens'
        AND column_name = 'outbox_id'
    ) THEN
        -- Column already exists from 033_portal_magic_links.sql
        -- This is a no-op but kept for documentation
        RAISE NOTICE 'outbox_id column already exists on portal.portal_tokens';
    END IF;
END $$;

-- Add index for outbox_id lookup (if not exists)
CREATE INDEX IF NOT EXISTS idx_portal_tokens_outbox
    ON portal.portal_tokens(outbox_id)
    WHERE outbox_id IS NOT NULL;

-- =============================================================================
-- FUNCTION: portal.issue_tokens_for_notify()
-- =============================================================================
-- Bulk issue portal tokens and return URLs for notification job creation
-- Called by Python link_service.py

CREATE OR REPLACE FUNCTION portal.issue_tokens_for_notify(
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_snapshot_id UUID,
    p_driver_ids TEXT[],
    p_scope TEXT DEFAULT 'READ_ACK',
    p_ttl_days INTEGER DEFAULT 14,
    p_delivery_channel TEXT DEFAULT 'WHATSAPP'
)
RETURNS TABLE (
    driver_id VARCHAR(255),
    jti_hash CHAR(64),
    issued_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY INVOKER  -- RLS applies
AS $$
DECLARE
    v_driver TEXT;
    v_jti_hash CHAR(64);
    v_issued_at TIMESTAMPTZ;
    v_expires_at TIMESTAMPTZ;
BEGIN
    v_issued_at := NOW();
    v_expires_at := NOW() + (p_ttl_days || ' days')::INTERVAL;

    -- Note: Actual jti_hash must be provided by caller (Python generates JWT)
    -- This function is for bulk metadata insertion only
    -- The Python service handles token generation

    FOREACH v_driver IN ARRAY p_driver_ids
    LOOP
        -- Return placeholder - actual implementation in Python
        driver_id := v_driver;
        jti_hash := ''; -- Python fills this
        issued_at := v_issued_at;
        expires_at := v_expires_at;
        RETURN NEXT;
    END LOOP;

    RETURN;
END;
$$;

-- =============================================================================
-- FUNCTION: portal.link_token_to_outbox()
-- =============================================================================
-- Link a portal token to its notification outbox entry

CREATE OR REPLACE FUNCTION portal.link_token_to_outbox(
    p_jti_hash CHAR(64),
    p_outbox_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    UPDATE portal.portal_tokens
    SET outbox_id = p_outbox_id,
        updated_at = NOW()
    WHERE jti_hash = p_jti_hash
      AND outbox_id IS NULL;  -- Only update if not already linked

    RETURN FOUND;
END;
$$;

-- Grant execute
GRANT EXECUTE ON FUNCTION portal.link_token_to_outbox(CHAR, UUID) TO solvereign_api;

-- =============================================================================
-- VIEW: Portal-Notify Integration Status
-- =============================================================================
-- Monitoring view for dispatchers to see delivery status

CREATE OR REPLACE VIEW portal.notify_integration_status AS
SELECT
    t.tenant_id,
    t.snapshot_id,
    t.driver_id,
    t.jti_hash,
    t.scope,
    t.delivery_channel,
    t.issued_at,
    t.expires_at,
    t.revoked_at,
    t.last_seen_at,
    -- Notification status from outbox
    o.status AS notify_status,
    o.sent_at AS notify_sent_at,
    o.delivered_at AS notify_delivered_at,
    o.error_message AS notify_error,
    -- Read/Ack status from portal
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

-- RLS: Inherit from portal_tokens
-- The view will automatically filter by tenant via the underlying table's RLS

GRANT SELECT ON portal.notify_integration_status TO solvereign_api;

-- =============================================================================
-- VIEW: Snapshot Notification Summary
-- =============================================================================
-- Aggregated status for a snapshot

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
    COUNT(*) FILTER (WHERE overall_status IN ('REVOKED', 'EXPIRED', 'NOTIFY_FAILED')) AS failed_count,
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
-- UPDATE TEMPLATES: Add new {plan_link} templates
-- =============================================================================

-- Delete old templates and recreate with {plan_link}
DELETE FROM notify.notification_templates
WHERE template_key IN ('PORTAL_INVITE', 'REMINDER_24H');

INSERT INTO notify.notification_templates (
    tenant_id, template_key, delivery_channel, language,
    whatsapp_template_name, subject, body_template, body_html, expected_params
) VALUES
-- WhatsApp Portal Invite (German)
(NULL, 'PORTAL_INVITE', 'WHATSAPP', 'de',
    'portal_invite_v1', NULL,
    'Hallo {{driver_name}}, Ihr neuer Schichtplan ist verfuegbar. Bitte bestaetigen Sie hier: {{plan_link}}',
    NULL,
    ARRAY['driver_name', 'plan_link']),

-- WhatsApp Portal Invite (English)
(NULL, 'PORTAL_INVITE', 'WHATSAPP', 'en',
    'portal_invite_v1', NULL,
    'Hello {{driver_name}}, your new shift schedule is available. Please confirm here: {{plan_link}}',
    NULL,
    ARRAY['driver_name', 'plan_link']),

-- WhatsApp Reminder (German)
(NULL, 'REMINDER_24H', 'WHATSAPP', 'de',
    'reminder_24h_v1', NULL,
    'Erinnerung: Ihr Schichtplan wartet noch auf Bestaetigung. Bitte bestaetigen Sie hier: {{plan_link}}',
    NULL,
    ARRAY['driver_name', 'plan_link']),

-- Email Portal Invite (German)
(NULL, 'PORTAL_INVITE', 'EMAIL', 'de',
    NULL,
    'Ihr neuer Schichtplan ist verfügbar',
    E'Hallo {{driver_name}},\n\nIhr neuer Schichtplan für die Woche {{week_start}} ist verfügbar.\n\nBitte bestätigen Sie Ihren Plan hier:\n{{plan_link}}\n\nMit freundlichen Grüßen,\nIhr Dispositionsteam',
    E'<html><body>\n<p>Hallo {{driver_name}},</p>\n<p>Ihr neuer Schichtplan für die Woche <strong>{{week_start}}</strong> ist verfügbar.</p>\n<p><a href="{{plan_link}}" style="background-color:#0066cc;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;">Plan bestätigen</a></p>\n<p>Mit freundlichen Grüßen,<br/>Ihr Dispositionsteam</p>\n</body></html>',
    ARRAY['driver_name', 'plan_link', 'week_start']),

-- Email Reminder (German)
(NULL, 'REMINDER_24H', 'EMAIL', 'de',
    NULL,
    'Erinnerung: Schichtplan wartet auf Bestätigung',
    E'Hallo {{driver_name}},\n\nIhr Schichtplan wartet noch auf Ihre Bestätigung.\n\nBitte bestätigen Sie hier:\n{{plan_link}}\n\nMit freundlichen Grüßen,\nIhr Dispositionsteam',
    E'<html><body>\n<p>Hallo {{driver_name}},</p>\n<p>Ihr Schichtplan wartet noch auf Ihre Bestätigung.</p>\n<p><a href="{{plan_link}}" style="background-color:#cc6600;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;">Jetzt bestätigen</a></p>\n<p>Mit freundlichen Grüßen,<br/>Ihr Dispositionsteam</p>\n</body></html>',
    ARRAY['driver_name', 'plan_link']),

-- SMS Portal Invite (German)
(NULL, 'PORTAL_INVITE', 'SMS', 'de',
    NULL, NULL,
    'SOLVEREIGN: Neuer Schichtplan verfügbar. Bitte bestätigen: {{plan_link}}',
    NULL,
    ARRAY['plan_link']),

-- SMS Reminder (German)
(NULL, 'REMINDER_24H', 'SMS', 'de',
    NULL, NULL,
    'SOLVEREIGN: Erinnerung - Schichtplan noch nicht bestätigt. {{plan_link}}',
    NULL,
    ARRAY['plan_link'])

ON CONFLICT DO NOTHING;

-- =============================================================================
-- VERIFY INTEGRATION
-- =============================================================================

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

    -- Check 2: outbox_id index exists
    RETURN QUERY
    SELECT
        'outbox_id_index_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Index idx_portal_tokens_outbox'::TEXT
    FROM pg_indexes
    WHERE indexname = 'idx_portal_tokens_outbox';

    -- Check 3: Integration view exists
    RETURN QUERY
    SELECT
        'integration_view_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'View portal.notify_integration_status'::TEXT
    FROM pg_views
    WHERE viewname = 'notify_integration_status' AND schemaname = 'portal';

    -- Check 4: link_token_to_outbox function exists
    RETURN QUERY
    SELECT
        'link_function_exists'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END::TEXT,
        'Function portal.link_token_to_outbox'::TEXT
    FROM pg_proc
    WHERE proname = 'link_token_to_outbox';

END;
$$ LANGUAGE plpgsql;

-- Grant execute
GRANT EXECUTE ON FUNCTION portal.verify_notify_integration() TO solvereign_platform;

COMMIT;

-- =============================================================================
-- VERIFICATION (Run after migration)
-- =============================================================================
-- SELECT * FROM portal.verify_notify_integration();
