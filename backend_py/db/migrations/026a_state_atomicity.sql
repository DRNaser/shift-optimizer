-- =============================================================================
-- Migration 026a: State Machine Atomicity + Determinism Hardening
-- =============================================================================
-- Fixes identified in review:
-- 1. Add unique constraint to prevent double approve/publish
-- 2. Add row locking to transition function
-- 3. Add missing determinism fields to solver_runs
-- 4. Add idempotency protection
--
-- Run AFTER 026_solver_runs.sql:
-- psql $DATABASE_URL < backend_py/db/migrations/026a_state_atomicity.sql
-- =============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('026a', 'State atomicity + determinism hardening', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- 1. UNIQUE CONSTRAINTS FOR APPROVALS
-- =============================================================================

-- Only one APPROVE action per plan (prevent double-click approve)
CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_approvals_unique_approve
ON plan_approvals (plan_version_id)
WHERE action = 'APPROVE' AND to_state = 'APPROVED';

-- Only one PUBLISH action per plan (prevent double-click publish)
CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_approvals_unique_publish
ON plan_approvals (plan_version_id)
WHERE action = 'PUBLISH' AND to_state = 'PUBLISHED';

COMMENT ON INDEX idx_plan_approvals_unique_approve IS 'Prevents duplicate APPROVE actions (idempotency)';
COMMENT ON INDEX idx_plan_approvals_unique_publish IS 'Prevents duplicate PUBLISH actions (idempotency)';


-- =============================================================================
-- 2. ADD MISSING DETERMINISM FIELDS TO SOLVER_RUNS
-- =============================================================================

DO $$
BEGIN
    -- Add evidence_hash for integrity verification
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'solver_runs' AND column_name = 'evidence_hash'
    ) THEN
        ALTER TABLE solver_runs ADD COLUMN evidence_hash VARCHAR(64);
    END IF;

    -- Add determinism_mode to record if run was deterministic
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'solver_runs' AND column_name = 'determinism_mode'
    ) THEN
        ALTER TABLE solver_runs ADD COLUMN determinism_mode VARCHAR(20) DEFAULT 'deterministic';
        ALTER TABLE solver_runs ADD CONSTRAINT solver_runs_determinism_check CHECK (
            determinism_mode IN ('deterministic', 'parallel', 'best_effort')
        );
    END IF;

    -- Add workers count (1 = deterministic)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'solver_runs' AND column_name = 'workers'
    ) THEN
        ALTER TABLE solver_runs ADD COLUMN workers INTEGER DEFAULT 1;
    END IF;

    -- Add routing_provider version for matrix reproducibility
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'solver_runs' AND column_name = 'routing_provider'
    ) THEN
        ALTER TABLE solver_runs ADD COLUMN routing_provider VARCHAR(50);
        ALTER TABLE solver_runs ADD COLUMN routing_provider_version VARCHAR(50);
    END IF;
END $$;


-- =============================================================================
-- 3. IMPROVED TRANSITION FUNCTION WITH ROW LOCKING
-- =============================================================================

CREATE OR REPLACE FUNCTION transition_plan_state(
    p_plan_version_id INTEGER,
    p_to_state VARCHAR,
    p_performed_by VARCHAR,
    p_reason TEXT DEFAULT NULL,
    p_kpi_snapshot JSONB DEFAULT NULL
)
RETURNS JSONB
SECURITY DEFINER
SET search_path = public, core
AS $$
DECLARE
    v_current_state VARCHAR;
    v_tenant_id INTEGER;
    v_solver_run_id UUID;
    v_allowed BOOLEAN := FALSE;
    v_result JSONB;
    v_existing_action INTEGER;
BEGIN
    -- CRITICAL: Lock the row to prevent concurrent transitions
    SELECT plan_state, tenant_id, solver_run_id
    INTO v_current_state, v_tenant_id, v_solver_run_id
    FROM plan_versions
    WHERE id = p_plan_version_id
    FOR UPDATE NOWAIT;  -- Fail fast if locked

    IF v_current_state IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Plan version not found',
            'plan_version_id', p_plan_version_id
        );
    END IF;

    -- Idempotency check: if already in target state, return success
    IF v_current_state = p_to_state THEN
        RETURN jsonb_build_object(
            'success', TRUE,
            'idempotent', TRUE,
            'from_state', v_current_state,
            'to_state', p_to_state,
            'message', 'Plan already in requested state'
        );
    END IF;

    -- Validate state transition (strict state machine)
    CASE v_current_state
        WHEN 'DRAFT' THEN
            v_allowed := p_to_state IN ('SOLVING', 'REJECTED');
        WHEN 'SOLVING' THEN
            v_allowed := p_to_state IN ('SOLVED', 'FAILED');
        WHEN 'SOLVED' THEN
            v_allowed := p_to_state IN ('APPROVED', 'REJECTED', 'DRAFT');
        WHEN 'APPROVED' THEN
            v_allowed := p_to_state IN ('PUBLISHED', 'REJECTED', 'DRAFT');
        WHEN 'REJECTED' THEN
            v_allowed := p_to_state IN ('DRAFT');
        WHEN 'FAILED' THEN
            v_allowed := p_to_state IN ('DRAFT');
        WHEN 'PUBLISHED' THEN
            v_allowed := FALSE;  -- PUBLISHED is TERMINAL - no transitions allowed
        ELSE
            v_allowed := FALSE;
    END CASE;

    IF NOT v_allowed THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Invalid state transition: %s -> %s', v_current_state, p_to_state),
            'from_state', v_current_state,
            'to_state', p_to_state,
            'allowed_from', CASE v_current_state
                WHEN 'DRAFT' THEN ARRAY['SOLVING', 'REJECTED']
                WHEN 'SOLVING' THEN ARRAY['SOLVED', 'FAILED']
                WHEN 'SOLVED' THEN ARRAY['APPROVED', 'REJECTED', 'DRAFT']
                WHEN 'APPROVED' THEN ARRAY['PUBLISHED', 'REJECTED', 'DRAFT']
                WHEN 'REJECTED' THEN ARRAY['DRAFT']
                WHEN 'FAILED' THEN ARRAY['DRAFT']
                WHEN 'PUBLISHED' THEN ARRAY[]::TEXT[]
                ELSE ARRAY[]::TEXT[]
            END
        );
    END IF;

    -- Check for duplicate APPROVE/PUBLISH (handled by unique index but give better error)
    IF p_to_state IN ('APPROVED', 'PUBLISHED') THEN
        SELECT COUNT(*) INTO v_existing_action
        FROM plan_approvals
        WHERE plan_version_id = p_plan_version_id
          AND to_state = p_to_state;

        IF v_existing_action > 0 THEN
            RETURN jsonb_build_object(
                'success', FALSE,
                'error', format('Plan already has %s action recorded', p_to_state),
                'from_state', v_current_state,
                'to_state', p_to_state
            );
        END IF;
    END IF;

    -- Perform state transition
    UPDATE plan_versions
    SET plan_state = p_to_state,
        plan_state_changed_at = NOW(),
        published_at = CASE WHEN p_to_state = 'PUBLISHED' THEN NOW() ELSE published_at END,
        published_by = CASE WHEN p_to_state = 'PUBLISHED' THEN p_performed_by ELSE published_by END,
        freeze_until = CASE WHEN p_to_state = 'PUBLISHED' THEN NOW() + INTERVAL '12 hours' ELSE freeze_until END
    WHERE id = p_plan_version_id;

    -- Record approval action in audit trail
    INSERT INTO plan_approvals (
        plan_version_id,
        solver_run_id,
        tenant_id,
        action,
        performed_by,
        from_state,
        to_state,
        reason,
        kpi_snapshot
    ) VALUES (
        p_plan_version_id,
        v_solver_run_id,
        v_tenant_id,
        CASE p_to_state
            WHEN 'APPROVED' THEN 'APPROVE'
            WHEN 'REJECTED' THEN 'REJECT'
            WHEN 'PUBLISHED' THEN 'PUBLISH'
            ELSE 'REVERT'
        END,
        p_performed_by,
        v_current_state,
        p_to_state,
        p_reason,
        p_kpi_snapshot
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'from_state', v_current_state,
        'to_state', p_to_state,
        'plan_version_id', p_plan_version_id,
        'performed_by', p_performed_by,
        'performed_at', NOW(),
        'freeze_until', CASE WHEN p_to_state = 'PUBLISHED' THEN NOW() + INTERVAL '12 hours' ELSE NULL END
    );

EXCEPTION
    WHEN lock_not_available THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Plan is locked by another transaction',
            'retry', TRUE
        );
    WHEN unique_violation THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Duplicate %s action (idempotency violation)', p_to_state),
            'retry', FALSE
        );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION transition_plan_state IS
'Atomic state transition with row locking, idempotency, and audit trail.
PUBLISHED state is terminal - no further transitions allowed.';


-- =============================================================================
-- 4. ADD plan_state_changed_at COLUMN
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_versions' AND column_name = 'plan_state_changed_at'
    ) THEN
        ALTER TABLE plan_versions ADD COLUMN plan_state_changed_at TIMESTAMPTZ;
    END IF;
END $$;


-- =============================================================================
-- 5. VERIFICATION FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION verify_state_machine_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: No PUBLISHED plans with modifications after publish
    RETURN QUERY
    SELECT
        'published_immutability'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s plans modified after publish', COUNT(*))
    FROM plan_versions
    WHERE plan_state = 'PUBLISHED'
      AND updated_at > published_at;

    -- Check 2: All PUBLISHED plans have approval record
    RETURN QUERY
    SELECT
        'publish_audit_trail'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s published plans without audit record', COUNT(*))
    FROM plan_versions pv
    WHERE pv.plan_state = 'PUBLISHED'
      AND NOT EXISTS (
          SELECT 1 FROM plan_approvals pa
          WHERE pa.plan_version_id = pv.id
            AND pa.action = 'PUBLISH'
      );

    -- Check 3: No duplicate APPROVE actions
    RETURN QUERY
    SELECT
        'unique_approve'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s plans with duplicate APPROVE', COUNT(*))
    FROM (
        SELECT plan_version_id, COUNT(*)
        FROM plan_approvals
        WHERE action = 'APPROVE'
        GROUP BY plan_version_id
        HAVING COUNT(*) > 1
    ) dups;

    -- Check 4: No duplicate PUBLISH actions
    RETURN QUERY
    SELECT
        'unique_publish'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s plans with duplicate PUBLISH', COUNT(*))
    FROM (
        SELECT plan_version_id, COUNT(*)
        FROM plan_approvals
        WHERE action = 'PUBLISH'
        GROUP BY plan_version_id
        HAVING COUNT(*) > 1
    ) dups;

    -- Check 5: solver_runs have determinism fields
    RETURN QUERY
    SELECT
        'determinism_fields'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s runs missing determinism_mode', COUNT(*))
    FROM solver_runs
    WHERE determinism_mode IS NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION verify_state_machine_integrity IS 'Verifies state machine invariants. Run periodically.';


-- =============================================================================
-- SUCCESS
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Migration 026a completed successfully';
    RAISE NOTICE 'Added: unique constraints, row locking, determinism fields';
    RAISE NOTICE 'Run SELECT * FROM verify_state_machine_integrity() to check invariants';
END $$;
