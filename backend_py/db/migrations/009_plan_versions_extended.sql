-- ============================================================================
-- MIGRATION 009: Extended Plan Versions + Status Enum
-- ============================================================================
-- V3.3a Product Core: Extended state machine and plan tracking
--
-- Changes:
-- 1. Extended status enum (INGESTED → EXPANDED → SOLVING → SOLVED → AUDITED → DRAFT → LOCKED)
-- 2. Additional tracking columns (started_at, completed_at, error_message)
-- 3. Advisory lock support columns
-- 4. Churn tracking improvements
-- ============================================================================

-- ============================================================================
-- 1. EXTEND STATUS CHECK CONSTRAINT
-- ============================================================================
-- Add new states for full pipeline tracking

-- First, drop the old constraint
ALTER TABLE plan_versions
DROP CONSTRAINT IF EXISTS plan_versions_status_check;

-- Add new constraint with extended statuses
ALTER TABLE plan_versions
ADD CONSTRAINT plan_versions_status_check
CHECK (status IN (
    'INGESTED',     -- NEW: Forecast parsed, awaiting expansion
    'EXPANDED',     -- NEW: Tour instances created
    'SOLVING',      -- Solver running
    'SOLVED',       -- NEW: Solver complete, awaiting audit
    'AUDITED',      -- NEW: Audit complete (may have failures)
    'DRAFT',        -- Ready for review (all audits passed)
    'LOCKED',       -- Released to production
    'SUPERSEDED',   -- Replaced by newer version
    'FAILED'        -- Solver or system error
));

-- ============================================================================
-- 2. ADD TRACKING COLUMNS
-- ============================================================================

-- Solver timing
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

-- Error tracking
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Advisory lock tracking
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS lock_acquired_at TIMESTAMPTZ;

ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS lock_released_at TIMESTAMPTZ;

-- Audit summary
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS audit_passed_count INTEGER DEFAULT 0;

ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS audit_failed_count INTEGER DEFAULT 0;

COMMENT ON COLUMN plan_versions.started_at IS 'Timestamp when solver started';
COMMENT ON COLUMN plan_versions.completed_at IS 'Timestamp when solver completed';
COMMENT ON COLUMN plan_versions.error_message IS 'Error details if status=FAILED';
COMMENT ON COLUMN plan_versions.lock_acquired_at IS 'Advisory lock acquisition time';
COMMENT ON COLUMN plan_versions.lock_released_at IS 'Advisory lock release time';
COMMENT ON COLUMN plan_versions.audit_passed_count IS 'Number of passed audit checks';
COMMENT ON COLUMN plan_versions.audit_failed_count IS 'Number of failed audit checks';

-- ============================================================================
-- 3. UPDATE LOCK INTEGRITY CONSTRAINT
-- ============================================================================

-- Drop old constraint
ALTER TABLE plan_versions
DROP CONSTRAINT IF EXISTS plan_versions_lock_integrity;

-- Add updated constraint
ALTER TABLE plan_versions
ADD CONSTRAINT plan_versions_lock_integrity CHECK (
    (status = 'LOCKED' AND locked_at IS NOT NULL AND locked_by IS NOT NULL) OR
    (status != 'LOCKED')
);

-- ============================================================================
-- 4. STATE TRANSITION VALIDATION FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_plan_state_transition()
RETURNS TRIGGER AS $$
DECLARE
    v_valid_transitions JSONB := '{
        "INGESTED": ["EXPANDED", "FAILED"],
        "EXPANDED": ["SOLVING", "FAILED"],
        "SOLVING": ["SOLVED", "FAILED"],
        "SOLVED": ["AUDITED", "FAILED"],
        "AUDITED": ["DRAFT", "FAILED"],
        "DRAFT": ["LOCKED", "SUPERSEDED", "SOLVING"],
        "LOCKED": ["SUPERSEDED"],
        "SUPERSEDED": [],
        "FAILED": []
    }'::JSONB;
    v_allowed_targets JSONB;
BEGIN
    -- Skip validation for new records
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;

    -- Skip if status hasn't changed
    IF OLD.status = NEW.status THEN
        RETURN NEW;
    END IF;

    -- Get allowed transitions
    v_allowed_targets := v_valid_transitions -> OLD.status;

    -- Check if transition is valid
    IF NOT (v_allowed_targets ? NEW.status) THEN
        RAISE EXCEPTION 'Invalid state transition: % -> %. Allowed: %',
            OLD.status, NEW.status, v_allowed_targets;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for state validation
DROP TRIGGER IF EXISTS validate_plan_state_transition_trigger ON plan_versions;

CREATE TRIGGER validate_plan_state_transition_trigger
BEFORE UPDATE ON plan_versions
FOR EACH ROW
EXECUTE FUNCTION validate_plan_state_transition();

COMMENT ON FUNCTION validate_plan_state_transition() IS
    'Enforce valid state machine transitions (V3.3a)';

-- ============================================================================
-- 5. HELPER FUNCTIONS FOR STATE TRANSITIONS
-- ============================================================================

-- Transition to SOLVING (with advisory lock timestamp)
CREATE OR REPLACE FUNCTION start_solving(
    p_plan_version_id INTEGER
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE plan_versions
    SET status = 'SOLVING',
        started_at = NOW(),
        lock_acquired_at = NOW()
    WHERE id = p_plan_version_id
      AND status IN ('EXPANDED', 'DRAFT');  -- Allow re-solve from DRAFT

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Transition to SOLVED
CREATE OR REPLACE FUNCTION complete_solving(
    p_plan_version_id INTEGER,
    p_output_hash VARCHAR(64)
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE plan_versions
    SET status = 'SOLVED',
        completed_at = NOW(),
        lock_released_at = NOW(),
        output_hash = p_output_hash
    WHERE id = p_plan_version_id
      AND status = 'SOLVING';

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Transition to FAILED
CREATE OR REPLACE FUNCTION mark_failed(
    p_plan_version_id INTEGER,
    p_error_message TEXT
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE plan_versions
    SET status = 'FAILED',
        completed_at = NOW(),
        lock_released_at = NOW(),
        error_message = p_error_message
    WHERE id = p_plan_version_id
      AND status NOT IN ('LOCKED', 'SUPERSEDED', 'FAILED');

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Transition to AUDITED
CREATE OR REPLACE FUNCTION complete_audit(
    p_plan_version_id INTEGER,
    p_passed_count INTEGER,
    p_failed_count INTEGER
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE plan_versions
    SET status = CASE
            WHEN p_failed_count = 0 THEN 'DRAFT'  -- All passed -> DRAFT
            ELSE 'AUDITED'                        -- Has failures -> AUDITED
        END,
        audit_passed_count = p_passed_count,
        audit_failed_count = p_failed_count
    WHERE id = p_plan_version_id
      AND status = 'SOLVED';

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION start_solving(INTEGER) IS 'Transition plan to SOLVING state';
COMMENT ON FUNCTION complete_solving(INTEGER, VARCHAR) IS 'Transition plan to SOLVED state';
COMMENT ON FUNCTION mark_failed(INTEGER, TEXT) IS 'Transition plan to FAILED state';
COMMENT ON FUNCTION complete_audit(INTEGER, INTEGER, INTEGER) IS 'Transition plan to AUDITED or DRAFT';

-- ============================================================================
-- 6. ADVISORY LOCK HELPERS
-- ============================================================================

-- Acquire advisory lock for solving
CREATE OR REPLACE FUNCTION try_acquire_solve_lock(
    p_tenant_id INTEGER,
    p_forecast_version_id INTEGER
)
RETURNS BOOLEAN AS $$
DECLARE
    v_lock_key BIGINT;
BEGIN
    -- Generate deterministic lock key from tenant + forecast
    v_lock_key := (p_tenant_id::BIGINT << 32) | p_forecast_version_id::BIGINT;

    -- Try to acquire lock (non-blocking)
    RETURN pg_try_advisory_lock(v_lock_key);
END;
$$ LANGUAGE plpgsql;

-- Release advisory lock
CREATE OR REPLACE FUNCTION release_solve_lock(
    p_tenant_id INTEGER,
    p_forecast_version_id INTEGER
)
RETURNS BOOLEAN AS $$
DECLARE
    v_lock_key BIGINT;
BEGIN
    v_lock_key := (p_tenant_id::BIGINT << 32) | p_forecast_version_id::BIGINT;
    RETURN pg_advisory_unlock(v_lock_key);
END;
$$ LANGUAGE plpgsql;

-- Check if solve lock is held
CREATE OR REPLACE FUNCTION is_solve_locked(
    p_tenant_id INTEGER,
    p_forecast_version_id INTEGER
)
RETURNS BOOLEAN AS $$
DECLARE
    v_lock_key BIGINT;
    v_is_locked BOOLEAN;
BEGIN
    v_lock_key := (p_tenant_id::BIGINT << 32) | p_forecast_version_id::BIGINT;

    -- Check if lock exists in pg_locks
    SELECT EXISTS (
        SELECT 1 FROM pg_locks
        WHERE locktype = 'advisory'
          AND objid = (v_lock_key & x'FFFFFFFF'::BIGINT)
          AND classid = (v_lock_key >> 32)
    ) INTO v_is_locked;

    RETURN v_is_locked;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION try_acquire_solve_lock(INTEGER, INTEGER) IS
    'Try to acquire advisory lock for solving (returns FALSE if already held)';
COMMENT ON FUNCTION release_solve_lock(INTEGER, INTEGER) IS
    'Release advisory lock after solving';
COMMENT ON FUNCTION is_solve_locked(INTEGER, INTEGER) IS
    'Check if forecast is currently being solved';

-- ============================================================================
-- 7. SOLVER DURATION VIEW
-- ============================================================================

CREATE OR REPLACE VIEW plan_solve_durations AS
SELECT
    tenant_id,
    id AS plan_version_id,
    forecast_version_id,
    status,
    started_at,
    completed_at,
    EXTRACT(EPOCH FROM (completed_at - started_at))::INTEGER AS duration_seconds,
    CASE
        WHEN status = 'FAILED' THEN error_message
        ELSE NULL
    END AS error
FROM plan_versions
WHERE started_at IS NOT NULL;

COMMENT ON VIEW plan_solve_durations IS 'Solver execution times for monitoring';

-- ============================================================================
-- 8. INDEXES FOR NEW COLUMNS
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_plan_versions_started_at
ON plan_versions(tenant_id, started_at DESC)
WHERE started_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_plan_versions_status_tenant
ON plan_versions(tenant_id, status);

-- Partial index for active solves
CREATE INDEX IF NOT EXISTS idx_plan_versions_solving
ON plan_versions(tenant_id, forecast_version_id)
WHERE status = 'SOLVING';

-- ============================================================================
-- 9. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('009', 'Extended plan_versions with state machine (V3.3a)', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 10. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 009: Extended Plan Versions COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Changes:';
    RAISE NOTICE '  - Extended status enum: INGESTED -> EXPANDED -> SOLVING ->';
    RAISE NOTICE '    SOLVED -> AUDITED -> DRAFT -> LOCKED (+ SUPERSEDED, FAILED)';
    RAISE NOTICE '  - Added: started_at, completed_at, error_message columns';
    RAISE NOTICE '  - Added: lock_acquired_at, lock_released_at for advisory locks';
    RAISE NOTICE '  - Added: audit_passed_count, audit_failed_count';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions:';
    RAISE NOTICE '  - validate_plan_state_transition() trigger';
    RAISE NOTICE '  - start_solving(), complete_solving(), mark_failed()';
    RAISE NOTICE '  - complete_audit()';
    RAISE NOTICE '  - try_acquire_solve_lock(), release_solve_lock()';
    RAISE NOTICE '  - is_solve_locked()';
    RAISE NOTICE '';
    RAISE NOTICE 'Views:';
    RAISE NOTICE '  - plan_solve_durations';
    RAISE NOTICE '==================================================================';
END $$;
