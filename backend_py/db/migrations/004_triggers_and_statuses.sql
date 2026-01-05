-- ============================================================================
-- MIGRATION 004: Additional Triggers and Status Updates
-- ============================================================================
-- Fixes identified in expert review:
-- 1. Missing trigger for assignment immutability on LOCKED plans
-- 2. Missing trigger for audit_log append-only enforcement
-- 3. plan_versions missing SOLVING/FAILED statuses
-- 4. audit_log missing OVERRIDE status
-- ============================================================================

-- 1. Add SOLVING and FAILED statuses to plan_versions
-- Note: This requires recreating the constraint
ALTER TABLE plan_versions DROP CONSTRAINT IF EXISTS plan_versions_status_check;
ALTER TABLE plan_versions ADD CONSTRAINT plan_versions_status_check
    CHECK (status IN ('DRAFT', 'LOCKED', 'SUPERSEDED', 'SOLVING', 'FAILED'));

-- 2. Add OVERRIDE status to audit_log
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_status_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_status_check
    CHECK (status IN ('PASS', 'FAIL', 'OVERRIDE'));

-- 3. Update audit_log count integrity constraint
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_count_integrity;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_count_integrity CHECK (
    (status = 'PASS' AND count = 0) OR
    (status = 'FAIL' AND count > 0) OR
    (status = 'OVERRIDE')  -- Override can have any count
);

-- 4. Trigger: Prevent modifying assignments for LOCKED plans
CREATE OR REPLACE FUNCTION prevent_locked_assignments_modification()
RETURNS TRIGGER AS $$
DECLARE
    v_plan_status VARCHAR(20);
BEGIN
    -- Get plan status
    SELECT status INTO v_plan_status
    FROM plan_versions
    WHERE id = OLD.plan_version_id;

    IF v_plan_status = 'LOCKED' THEN
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'Cannot UPDATE assignment % - plan_version % is LOCKED', OLD.id, OLD.plan_version_id;
        ELSIF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Cannot DELETE assignment % - plan_version % is LOCKED', OLD.id, OLD.plan_version_id;
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS prevent_locked_assignments_modification_trigger ON assignments;
CREATE TRIGGER prevent_locked_assignments_modification_trigger
BEFORE UPDATE OR DELETE ON assignments
FOR EACH ROW
EXECUTE FUNCTION prevent_locked_assignments_modification();

COMMENT ON FUNCTION prevent_locked_assignments_modification() IS 'Prevent modifications to assignments for LOCKED plans';

-- 5. Trigger: Make audit_log append-only (no UPDATE/DELETE)
CREATE OR REPLACE FUNCTION audit_log_append_only()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'audit_log is append-only: UPDATE not allowed on row %', OLD.id;
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit_log is append-only: DELETE not allowed on row %', OLD.id;
    END IF;
    RETURN NULL;  -- Never reached
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_append_only_trigger ON audit_log;
CREATE TRIGGER audit_log_append_only_trigger
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW
EXECUTE FUNCTION audit_log_append_only();

COMMENT ON FUNCTION audit_log_append_only() IS 'Enforce append-only (write-only) audit log';

-- 6. Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('004', 'Add assignment immutability trigger, audit_log append-only, new statuses', NOW())
ON CONFLICT (version) DO NOTHING;

-- 7. Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 004 Applied: Triggers and Statuses';
    RAISE NOTICE '   - Added SOLVING/FAILED statuses to plan_versions';
    RAISE NOTICE '   - Added OVERRIDE status to audit_log';
    RAISE NOTICE '   - Created prevent_locked_assignments_modification trigger';
    RAISE NOTICE '   - Created audit_log_append_only trigger';
END $$;
