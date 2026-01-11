-- SOLVEREIGN Billing Override (Hardening #4)
-- ============================================
--
-- Adds per-tenant billing override ("break glass") column.
-- Allows operators to temporarily bypass billing enforcement for specific tenants.
--
-- Usage:
--   psql $DATABASE_URL < backend_py/db/migrations/047_billing_override.sql
--
-- To enable override for a tenant:
--   UPDATE tenants SET billing_override_until = NOW() + INTERVAL '24 hours' WHERE id = 1;
--
-- To disable override:
--   UPDATE tenants SET billing_override_until = NULL WHERE id = 1;

BEGIN;

-- Add billing_override_until column to tenants
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS billing_override_until TIMESTAMPTZ;

-- Add comment explaining the column
COMMENT ON COLUMN tenants.billing_override_until IS
    'Emergency override: if set and in the future, billing enforcement is bypassed for this tenant. '
    'Use with caution - audit all changes.';

-- Index for efficient lookup (only non-null values)
CREATE INDEX IF NOT EXISTS idx_tenants_billing_override
    ON tenants(billing_override_until)
    WHERE billing_override_until IS NOT NULL;

-- Audit trigger: log all override changes
CREATE OR REPLACE FUNCTION audit_billing_override_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.billing_override_until IS DISTINCT FROM NEW.billing_override_until THEN
        INSERT INTO auth.audit_log (event_type, user_id, target_tenant_id, details)
        VALUES (
            'billing.override_changed',
            NULLIF(current_setting('app.current_user_id', true), '')::INTEGER,
            NEW.id,
            jsonb_build_object(
                'old_value', OLD.billing_override_until,
                'new_value', NEW.billing_override_until,
                'action', CASE
                    WHEN NEW.billing_override_until IS NULL THEN 'disabled'
                    WHEN OLD.billing_override_until IS NULL THEN 'enabled'
                    ELSE 'modified'
                END
            )
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger (drop first if exists to handle re-runs)
DROP TRIGGER IF EXISTS trg_audit_billing_override ON tenants;
CREATE TRIGGER trg_audit_billing_override
    AFTER UPDATE ON tenants
    FOR EACH ROW
    EXECUTE FUNCTION audit_billing_override_change();

-- Verification
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tenants' AND column_name = 'billing_override_until'
    ) THEN
        RAISE NOTICE 'PASS: billing_override_until column exists';
    ELSE
        RAISE EXCEPTION 'FAIL: billing_override_until column not created';
    END IF;
END $$;

COMMIT;
