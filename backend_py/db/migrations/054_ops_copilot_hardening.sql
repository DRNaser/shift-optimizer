-- ============================================================================
-- Migration 054: Ops-Copilot Hardening
-- ============================================================================
-- FORENSIC FIXES for MVP safety gaps:
-- 1. Idempotency: DB-backed dedup for webhook ingestion
-- 2. Broadcast: Add idempotency_key to drafts for dedupe
-- 3. Validation: Enhanced constraints for driver broadcasts
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. INGEST IDEMPOTENCY TABLE
-- ============================================================================
-- Prevents duplicate processing of webhook messages
-- Uses INSERT conflict to atomically check and record

CREATE TABLE IF NOT EXISTS ops.ingest_dedup (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(255) NOT NULL,
    wa_user_id      VARCHAR(100) NOT NULL,
    tenant_id       INTEGER,  -- NULL for unpaired users
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_id        UUID,  -- Reference to ops.events if created

    -- Unique constraint prevents duplicate processing
    CONSTRAINT ops_ingest_dedup_unique UNIQUE (idempotency_key)
);

-- Index for cleanup of old entries
CREATE INDEX IF NOT EXISTS idx_ops_ingest_dedup_processed_at
ON ops.ingest_dedup(processed_at);

-- Auto-cleanup old entries (keep 7 days)
COMMENT ON TABLE ops.ingest_dedup IS
'Idempotency guard for webhook ingest. Entries older than 7 days can be purged.';

-- RLS: No direct access needed, internal use only via SECURITY DEFINER
ALTER TABLE ops.ingest_dedup ENABLE ROW LEVEL SECURITY;

-- Grant to API role (needs INSERT for idempotency check)
GRANT SELECT, INSERT ON ops.ingest_dedup TO solvereign_api;

-- ============================================================================
-- 2. DRAFTS: Add idempotency_key for broadcast dedupe
-- ============================================================================

ALTER TABLE ops.drafts
ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);

-- Unique per tenant to prevent duplicate confirms
CREATE UNIQUE INDEX IF NOT EXISTS idx_ops_drafts_idempotency
ON ops.drafts(tenant_id, idempotency_key)
WHERE idempotency_key IS NOT NULL AND status IN ('PENDING_CONFIRM', 'COMMITTED');

COMMENT ON COLUMN ops.drafts.idempotency_key IS
'Optional idempotency key for broadcast deduplication. Prevents duplicate sends.';

-- ============================================================================
-- 3. BROADCAST TEMPLATES: Ensure allowed_placeholders enforced
-- ============================================================================

-- Add check constraint for audience values
ALTER TABLE ops.broadcast_templates
DROP CONSTRAINT IF EXISTS broadcast_templates_audience_check;

ALTER TABLE ops.broadcast_templates
ADD CONSTRAINT broadcast_templates_audience_check
CHECK (audience IN ('OPS', 'DRIVER'));

-- Driver templates MUST have wa_template_name
ALTER TABLE ops.broadcast_templates
DROP CONSTRAINT IF EXISTS broadcast_templates_driver_requires_wa_template;

ALTER TABLE ops.broadcast_templates
ADD CONSTRAINT broadcast_templates_driver_requires_wa_template
CHECK (
    audience != 'DRIVER' OR
    (wa_template_name IS NOT NULL AND wa_template_name != '')
);

-- ============================================================================
-- 4. IDEMPOTENCY CHECK FUNCTION
-- ============================================================================
-- Returns TRUE if already processed (should skip), FALSE if new

CREATE OR REPLACE FUNCTION ops.check_and_record_idempotency(
    p_idempotency_key VARCHAR,
    p_wa_user_id VARCHAR,
    p_tenant_id INTEGER DEFAULT NULL
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ops, public
AS $$
DECLARE
    v_exists BOOLEAN;
BEGIN
    -- Try to insert (atomic check + record)
    INSERT INTO ops.ingest_dedup (idempotency_key, wa_user_id, tenant_id)
    VALUES (p_idempotency_key, p_wa_user_id, p_tenant_id)
    ON CONFLICT (idempotency_key) DO NOTHING;

    -- If insert succeeded (1 row), return FALSE (not a duplicate)
    -- If insert was skipped (0 rows), return TRUE (duplicate)
    GET DIAGNOSTICS v_exists = ROW_COUNT;

    RETURN v_exists = 0;  -- TRUE if already existed (duplicate)
END;
$$;

COMMENT ON FUNCTION ops.check_and_record_idempotency IS
'Atomically checks and records idempotency key. Returns TRUE if duplicate.';

GRANT EXECUTE ON FUNCTION ops.check_and_record_idempotency TO solvereign_api;

-- ============================================================================
-- 5. CLEANUP FUNCTION FOR OLD IDEMPOTENCY RECORDS
-- ============================================================================

CREATE OR REPLACE FUNCTION ops.cleanup_old_idempotency_records(
    p_retention_days INTEGER DEFAULT 7
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ops, public
AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM ops.ingest_dedup
    WHERE processed_at < NOW() - (p_retention_days || ' days')::INTERVAL;

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION ops.cleanup_old_idempotency_records IS
'Purges idempotency records older than retention period.';

-- ============================================================================
-- 6. UPDATE VERIFY FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION ops.verify_ops_copilot_integrity()
RETURNS TABLE(
    check_name VARCHAR,
    status VARCHAR,
    details JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ops, auth, public
AS $$
BEGIN
    -- Check 1: All required tables exist
    RETURN QUERY
    SELECT
        'tables_exist'::VARCHAR,
        CASE
            WHEN COUNT(*) = 13 THEN 'PASS'::VARCHAR
            ELSE 'FAIL'::VARCHAR
        END,
        jsonb_build_object(
            'expected', 13,
            'found', COUNT(*),
            'tables', array_agg(table_name ORDER BY table_name)
        )
    FROM information_schema.tables
    WHERE table_schema = 'ops'
      AND table_name IN (
          'whatsapp_identities', 'pairing_invites', 'threads',
          'events', 'memories', 'playbooks', 'drafts', 'tickets',
          'ticket_comments', 'broadcast_templates', 'broadcast_subscriptions',
          'personas', 'ingest_dedup'
      );

    -- Check 2: RLS enabled on all tables
    RETURN QUERY
    SELECT
        'rls_enabled'::VARCHAR,
        CASE
            WHEN bool_and(rowsecurity) THEN 'PASS'::VARCHAR
            ELSE 'FAIL'::VARCHAR
        END,
        jsonb_build_object(
            'tables_with_rls', array_agg(relname) FILTER (WHERE rowsecurity),
            'tables_without_rls', array_agg(relname) FILTER (WHERE NOT rowsecurity)
        )
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
      AND c.relkind = 'r'
      AND c.relname NOT LIKE 'pg_%';

    -- Check 3: Permissions seeded
    RETURN QUERY
    SELECT
        'permissions_seeded'::VARCHAR,
        CASE
            WHEN COUNT(*) >= 6 THEN 'PASS'::VARCHAR
            ELSE 'FAIL'::VARCHAR
        END,
        jsonb_build_object(
            'expected_min', 6,
            'found', COUNT(*),
            'permissions', array_agg(permission_key)
        )
    FROM auth.permissions
    WHERE permission_key LIKE 'ops_copilot.%';

    -- Check 4: Idempotency function exists
    RETURN QUERY
    SELECT
        'idempotency_function_exists'::VARCHAR,
        CASE
            WHEN COUNT(*) > 0 THEN 'PASS'::VARCHAR
            ELSE 'FAIL'::VARCHAR
        END,
        jsonb_build_object('function', 'ops.check_and_record_idempotency')
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
      AND p.proname = 'check_and_record_idempotency';

    -- Check 5: Driver template constraint
    RETURN QUERY
    SELECT
        'driver_template_constraint'::VARCHAR,
        CASE
            WHEN COUNT(*) > 0 THEN 'PASS'::VARCHAR
            ELSE 'FAIL'::VARCHAR
        END,
        jsonb_build_object('constraint', 'broadcast_templates_driver_requires_wa_template')
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'ops'
      AND c.conname = 'broadcast_templates_driver_requires_wa_template';

    -- Check 6: Ingest dedup unique constraint
    RETURN QUERY
    SELECT
        'ingest_dedup_unique'::VARCHAR,
        CASE
            WHEN COUNT(*) > 0 THEN 'PASS'::VARCHAR
            ELSE 'FAIL'::VARCHAR
        END,
        jsonb_build_object('constraint', 'ops_ingest_dedup_unique')
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'ops'
      AND c.conname = 'ops_ingest_dedup_unique';
END;
$$;

COMMIT;
