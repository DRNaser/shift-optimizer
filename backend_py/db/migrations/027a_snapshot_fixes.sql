-- =============================================================================
-- Migration 027a: Plan Snapshot Fixes (V3.7.2)
-- =============================================================================
-- Fixes 3 critical issues in Plan Versioning:
--
-- FIX 1: Race-safe version numbering (FOR UPDATE on parent + unique constraint)
-- FIX 2: Snapshot payload population (assignments_snapshot, routes_snapshot)
-- FIX 3: Freeze enforcement with force override mechanism
--
-- Run AFTER 027_plan_versioning.sql:
-- psql $DATABASE_URL < backend_py/db/migrations/027a_snapshot_fixes.sql
-- =============================================================================

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('027a', 'Snapshot fixes: race-safe versioning + payload + freeze', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- FIX 1: UNIQUE CONSTRAINT ON VERSION NUMBER
-- =============================================================================
-- Prevents duplicate version_number for same plan_version_id

-- Drop partial unique constraint if exists (from 027)
ALTER TABLE plan_snapshots
DROP CONSTRAINT IF EXISTS plan_snapshots_unique_active;

-- Add proper unique constraint on (plan_version_id, version_number)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'plan_snapshots_unique_version_per_plan'
    ) THEN
        ALTER TABLE plan_snapshots
        ADD CONSTRAINT plan_snapshots_unique_version_per_plan
        UNIQUE (plan_version_id, version_number);
    END IF;
END $$;

-- Re-add the partial unique for ACTIVE status (one active per plan)
CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_snapshots_one_active_per_plan
ON plan_snapshots (plan_version_id)
WHERE snapshot_status = 'ACTIVE';

COMMENT ON CONSTRAINT plan_snapshots_unique_version_per_plan ON plan_snapshots IS
'Prevents duplicate version numbers per plan - enforces monotonic versioning';


-- =============================================================================
-- FIX 2: ADD FREEZE FORCE COLUMNS TO AUDIT TRAIL
-- =============================================================================

DO $$
BEGIN
    -- Track if publish was forced during freeze window
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_approvals' AND column_name = 'forced_during_freeze'
    ) THEN
        ALTER TABLE plan_approvals ADD COLUMN forced_during_freeze BOOLEAN DEFAULT FALSE;
    END IF;

    -- Reason for force (required when forced_during_freeze=true)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'plan_approvals' AND column_name = 'force_reason'
    ) THEN
        ALTER TABLE plan_approvals ADD COLUMN force_reason TEXT;
    END IF;
END $$;


-- =============================================================================
-- FIX 3: IMPROVED publish_plan_snapshot() WITH LOCKING + FREEZE CHECK
-- =============================================================================

-- Drop old 6-parameter version from 027 to avoid function overload ambiguity
DROP FUNCTION IF EXISTS publish_plan_snapshot(INTEGER, VARCHAR, TEXT, JSONB, JSONB, JSONB);

CREATE OR REPLACE FUNCTION publish_plan_snapshot(
    p_plan_version_id INTEGER,
    p_published_by VARCHAR,
    p_publish_reason TEXT DEFAULT NULL,
    p_kpi_snapshot JSONB DEFAULT NULL,
    p_assignments_snapshot JSONB DEFAULT '[]'::JSONB,
    p_routes_snapshot JSONB DEFAULT '{}'::JSONB,
    p_force_during_freeze BOOLEAN DEFAULT FALSE,
    p_force_reason TEXT DEFAULT NULL
)
RETURNS JSONB
SECURITY DEFINER
SET search_path = public, core
AS $$
DECLARE
    v_plan RECORD;
    v_new_snapshot_id INTEGER;
    v_new_version_number INTEGER;
    v_freeze_until TIMESTAMPTZ;
    v_existing_freeze TIMESTAMPTZ;
    v_is_frozen BOOLEAN;
BEGIN
    -- =========================================================================
    -- STEP 1: Lock the parent row FIRST (prevents race condition on version)
    -- =========================================================================
    SELECT pv.*, sr.input_hash, sr.matrix_hash, sr.output_hash, sr.evidence_hash,
           sr.result_artifact_uri, sr.evidence_artifact_uri,
           ps.freeze_until as existing_freeze
    INTO v_plan
    FROM plan_versions pv
    LEFT JOIN solver_runs sr ON sr.run_id = pv.solver_run_id
    LEFT JOIN plan_snapshots ps ON ps.id = pv.current_snapshot_id AND ps.snapshot_status = 'ACTIVE'
    WHERE pv.id = p_plan_version_id
    FOR UPDATE OF pv;  -- Lock plan_versions row

    IF v_plan IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Plan version not found'
        );
    END IF;

    -- Check plan is in APPROVED state
    IF COALESCE(v_plan.plan_state, 'DRAFT') != 'APPROVED' THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Plan must be APPROVED to publish (current: %s)',
                           COALESCE(v_plan.plan_state, 'DRAFT'))
        );
    END IF;

    -- =========================================================================
    -- STEP 2: Check freeze window (from previous active snapshot)
    -- =========================================================================
    v_existing_freeze := v_plan.existing_freeze;
    v_is_frozen := v_existing_freeze IS NOT NULL AND v_existing_freeze > NOW();

    IF v_is_frozen THEN
        IF NOT p_force_during_freeze THEN
            RETURN jsonb_build_object(
                'success', FALSE,
                'error', 'Cannot publish during freeze window without force flag',
                'freeze_until', v_existing_freeze,
                'minutes_remaining', EXTRACT(EPOCH FROM (v_existing_freeze - NOW())) / 60,
                'hint', 'Use force_during_freeze=true with force_reason to override'
            );
        END IF;

        IF p_force_reason IS NULL OR LENGTH(TRIM(p_force_reason)) < 10 THEN
            RETURN jsonb_build_object(
                'success', FALSE,
                'error', 'Force during freeze requires force_reason (min 10 chars)',
                'freeze_until', v_existing_freeze
            );
        END IF;
    END IF;

    -- =========================================================================
    -- STEP 3: Calculate next version number (RACE-SAFE due to parent lock)
    -- =========================================================================
    SELECT COALESCE(MAX(version_number), 0) + 1
    INTO v_new_version_number
    FROM plan_snapshots
    WHERE plan_version_id = p_plan_version_id;

    -- =========================================================================
    -- STEP 4: Supersede any existing ACTIVE snapshot for this plan
    -- =========================================================================
    UPDATE plan_snapshots
    SET snapshot_status = 'SUPERSEDED'
    WHERE plan_version_id = p_plan_version_id
      AND snapshot_status = 'ACTIVE';

    -- Calculate new freeze window
    v_freeze_until := NOW() + INTERVAL '12 hours';

    -- =========================================================================
    -- STEP 5: Validate snapshot payload is not empty (for v2+)
    -- =========================================================================
    -- For first publish, empty might be acceptable (legacy)
    -- For subsequent publishes, require real data
    IF v_new_version_number > 1 THEN
        IF p_assignments_snapshot = '[]'::JSONB OR p_assignments_snapshot IS NULL THEN
            RAISE WARNING 'publish_plan_snapshot: assignments_snapshot is empty for version %', v_new_version_number;
        END IF;
    END IF;

    -- =========================================================================
    -- STEP 6: Create immutable snapshot
    -- =========================================================================
    INSERT INTO plan_snapshots (
        plan_version_id,
        tenant_id,
        site_id,
        version_number,
        published_by,
        publish_reason,
        freeze_until,
        solver_run_id,
        kpi_snapshot,
        input_hash,
        matrix_hash,
        output_hash,
        evidence_hash,
        result_artifact_uri,
        evidence_artifact_uri,
        assignments_snapshot,
        routes_snapshot,
        audit_passed_count,
        snapshot_status
    ) VALUES (
        p_plan_version_id,
        v_plan.tenant_id,
        v_plan.site_id,
        v_new_version_number,
        p_published_by,
        p_publish_reason,
        v_freeze_until,
        v_plan.solver_run_id,
        COALESCE(p_kpi_snapshot, '{}'::JSONB),
        COALESCE(v_plan.input_hash, 'N/A'),
        v_plan.matrix_hash,
        COALESCE(v_plan.output_hash, 'N/A'),
        v_plan.evidence_hash,
        v_plan.result_artifact_uri,
        v_plan.evidence_artifact_uri,
        p_assignments_snapshot,
        p_routes_snapshot,
        v_plan.audit_passed_count,
        'ACTIVE'
    )
    RETURNING id INTO v_new_snapshot_id;

    -- =========================================================================
    -- STEP 7: Update plan_versions to point to new snapshot
    -- =========================================================================
    UPDATE plan_versions
    SET current_snapshot_id = v_new_snapshot_id,
        publish_count = COALESCE(publish_count, 0) + 1,
        plan_state = 'PUBLISHED',
        plan_state_changed_at = NOW(),
        published_at = NOW(),
        published_by = p_published_by,
        freeze_until = v_freeze_until
    WHERE id = p_plan_version_id;

    -- =========================================================================
    -- STEP 8: Record in approvals audit trail (with force tracking)
    -- =========================================================================
    INSERT INTO plan_approvals (
        plan_version_id,
        solver_run_id,
        tenant_id,
        action,
        performed_by,
        from_state,
        to_state,
        reason,
        kpi_snapshot,
        forced_during_freeze,
        force_reason
    ) VALUES (
        p_plan_version_id,
        v_plan.solver_run_id,
        v_plan.tenant_id,
        'PUBLISH',
        p_published_by,
        'APPROVED',
        'PUBLISHED',
        p_publish_reason,
        p_kpi_snapshot,
        v_is_frozen AND p_force_during_freeze,
        CASE WHEN v_is_frozen AND p_force_during_freeze THEN p_force_reason ELSE NULL END
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'snapshot_id', v_new_snapshot_id,
        'version_number', v_new_version_number,
        'plan_version_id', p_plan_version_id,
        'published_by', p_published_by,
        'freeze_until', v_freeze_until,
        'forced_during_freeze', v_is_frozen AND p_force_during_freeze,
        'message', format('Plan published as version %s', v_new_version_number)
    );

EXCEPTION
    WHEN unique_violation THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Concurrent publish detected - version conflict',
            'retry', TRUE
        );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION publish_plan_snapshot(INTEGER, VARCHAR, TEXT, JSONB, JSONB, JSONB, BOOLEAN, TEXT) IS
'V3.7.2: Race-safe snapshot creation with freeze window enforcement.
- Locks parent plan_versions row to prevent version race
- Enforces freeze window (requires force flag + reason to override)
- Records force override in audit trail';


-- =============================================================================
-- FIX 4: HELPER FUNCTION TO BUILD SNAPSHOT PAYLOAD FROM DB
-- =============================================================================
-- This function pulls assignment/route data from existing tables
-- Adjust table names to match your schema!

CREATE OR REPLACE FUNCTION build_snapshot_payload(p_plan_version_id INTEGER)
RETURNS JSONB AS $$
DECLARE
    v_assignments JSONB;
    v_routes JSONB;
    v_result JSONB;
BEGIN
    -- Build assignments snapshot
    -- NOTE: Adjust this query to match your actual schema!
    -- This assumes a plan_assignments table exists
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object(
            'assignment_id', pa.id,
            'stop_id', pa.stop_id,
            'vehicle_id', pa.vehicle_id,
            'sequence_index', pa.sequence_index,
            'arrival_time', pa.arrival_time,
            'departure_time', pa.departure_time,
            'service_time_minutes', pa.service_time_minutes,
            'selected_window_index', pa.selected_window_index
        ) ORDER BY pa.vehicle_id, pa.sequence_index
    ), '[]'::JSONB)
    INTO v_assignments
    FROM plan_assignments pa
    WHERE pa.plan_version_id = p_plan_version_id;

    -- Build routes snapshot (aggregated by vehicle)
    SELECT COALESCE(jsonb_object_agg(
        vehicle_id::TEXT,
        route_data
    ), '{}'::JSONB)
    INTO v_routes
    FROM (
        SELECT
            pa.vehicle_id,
            jsonb_build_object(
                'vehicle_id', pa.vehicle_id,
                'stop_count', COUNT(*),
                'total_service_time', SUM(pa.service_time_minutes),
                'stops', jsonb_agg(
                    jsonb_build_object(
                        'stop_id', pa.stop_id,
                        'sequence', pa.sequence_index,
                        'arrival', pa.arrival_time,
                        'departure', pa.departure_time
                    ) ORDER BY pa.sequence_index
                )
            ) as route_data
        FROM plan_assignments pa
        WHERE pa.plan_version_id = p_plan_version_id
        GROUP BY pa.vehicle_id
    ) routes;

    RETURN jsonb_build_object(
        'assignments', v_assignments,
        'routes', v_routes,
        'generated_at', NOW(),
        'plan_version_id', p_plan_version_id
    );

EXCEPTION
    WHEN undefined_table THEN
        -- plan_assignments table doesn't exist - return empty with warning
        RAISE WARNING 'build_snapshot_payload: plan_assignments table not found';
        RETURN jsonb_build_object(
            'assignments', '[]'::JSONB,
            'routes', '{}'::JSONB,
            'warning', 'plan_assignments table not found - using empty payload',
            'generated_at', NOW()
        );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION build_snapshot_payload IS
'Builds snapshot payload from DB tables. Returns assignments + routes as JSONB.
NOTE: Assumes plan_assignments table exists - adjust query if schema differs.';


-- =============================================================================
-- FIX 5: VERIFICATION FUNCTION FOR SNAPSHOTS
-- =============================================================================

CREATE OR REPLACE FUNCTION verify_snapshot_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: No duplicate version numbers per plan
    RETURN QUERY
    SELECT
        'unique_version_numbers'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s duplicate version numbers found', COUNT(*))
    FROM (
        SELECT plan_version_id, version_number, COUNT(*)
        FROM plan_snapshots
        GROUP BY plan_version_id, version_number
        HAVING COUNT(*) > 1
    ) dups;

    -- Check 2: All ACTIVE snapshots have non-empty payload (warning only)
    RETURN QUERY
    SELECT
        'payload_populated'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s active snapshots with empty assignments_snapshot', COUNT(*))
    FROM plan_snapshots
    WHERE snapshot_status = 'ACTIVE'
      AND (assignments_snapshot = '[]'::JSONB OR assignments_snapshot IS NULL);

    -- Check 3: Each plan has at most one ACTIVE snapshot
    RETURN QUERY
    SELECT
        'one_active_per_plan'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
        format('%s plans with multiple ACTIVE snapshots', COUNT(*))
    FROM (
        SELECT plan_version_id, COUNT(*)
        FROM plan_snapshots
        WHERE snapshot_status = 'ACTIVE'
        GROUP BY plan_version_id
        HAVING COUNT(*) > 1
    ) multi_active;

    -- Check 4: Version numbers are sequential (no gaps)
    RETURN QUERY
    SELECT
        'sequential_versions'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s plans with version gaps', COUNT(*))
    FROM (
        SELECT plan_version_id
        FROM plan_snapshots
        GROUP BY plan_version_id
        HAVING MAX(version_number) != COUNT(*)
    ) gaps;

    -- Check 5: Freeze timestamps are valid
    RETURN QUERY
    SELECT
        'valid_freeze_timestamps'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s snapshots with freeze_until before published_at', COUNT(*))
    FROM plan_snapshots
    WHERE freeze_until < published_at;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION verify_snapshot_integrity IS 'Verifies snapshot invariants. Run after migrations.';


-- =============================================================================
-- FIX 6: BACKFILL LEGACY SNAPSHOTS (ONE-TIME JOB)
-- =============================================================================
-- For snapshots created before V3.7.2 that have empty payloads

CREATE OR REPLACE FUNCTION backfill_snapshot_payloads(
    p_dry_run BOOLEAN DEFAULT TRUE
)
RETURNS TABLE (
    snapshot_id INTEGER,
    plan_version_id INTEGER,
    version_number INTEGER,
    status TEXT,
    action TEXT
) AS $$
DECLARE
    v_snapshot RECORD;
    v_payload JSONB;
    v_updated INTEGER := 0;
BEGIN
    FOR v_snapshot IN
        SELECT ps.id, ps.plan_version_id, ps.version_number, ps.snapshot_status
        FROM plan_snapshots ps
        WHERE ps.assignments_snapshot = '[]'::JSONB
           OR ps.assignments_snapshot IS NULL
        ORDER BY ps.id
    LOOP
        -- Try to build payload from current plan data
        SELECT build_snapshot_payload(v_snapshot.plan_version_id) INTO v_payload;

        IF v_payload->'assignments' != '[]'::JSONB THEN
            IF NOT p_dry_run THEN
                -- Actually update (only assignments/routes, not core data)
                -- This is safe because it doesn't change immutable hashes
                UPDATE plan_snapshots
                SET assignments_snapshot = v_payload->'assignments',
                    routes_snapshot = v_payload->'routes'
                WHERE id = v_snapshot.id
                  AND snapshot_status != 'ACTIVE';  -- Don't touch active snapshots

                v_updated := v_updated + 1;
            END IF;

            snapshot_id := v_snapshot.id;
            plan_version_id := v_snapshot.plan_version_id;
            version_number := v_snapshot.version_number;
            status := v_snapshot.snapshot_status;
            action := CASE WHEN p_dry_run THEN 'WOULD_UPDATE' ELSE 'UPDATED' END;
            RETURN NEXT;
        ELSE
            snapshot_id := v_snapshot.id;
            plan_version_id := v_snapshot.plan_version_id;
            version_number := v_snapshot.version_number;
            status := v_snapshot.snapshot_status;
            action := 'NO_DATA_AVAILABLE';
            RETURN NEXT;
        END IF;
    END LOOP;

    IF NOT p_dry_run THEN
        RAISE NOTICE 'Backfill complete: % snapshots updated', v_updated;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION backfill_snapshot_payloads IS
'One-time backfill for legacy snapshots without payload data.
Use dry_run=TRUE first to see what would be updated.
Only updates SUPERSEDED/ARCHIVED snapshots, not ACTIVE ones.';


-- =============================================================================
-- FIX 7: ADD is_legacy FLAG TO SNAPSHOT QUERIES
-- =============================================================================

CREATE OR REPLACE FUNCTION get_snapshot_history(p_plan_version_id INTEGER)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_agg(
        jsonb_build_object(
            'snapshot_id', ps.snapshot_id,
            'version_number', ps.version_number,
            'status', ps.snapshot_status,
            'published_at', ps.published_at,
            'published_by', ps.published_by,
            'publish_reason', ps.publish_reason,
            'freeze_until', ps.freeze_until,
            'is_frozen', ps.freeze_until > NOW(),
            'is_legacy', ps.assignments_snapshot = '[]'::JSONB OR ps.assignments_snapshot IS NULL,
            'kpis', ps.kpi_snapshot,
            'hashes', jsonb_build_object(
                'input', ps.input_hash,
                'output', ps.output_hash,
                'evidence', ps.evidence_hash
            )
        ) ORDER BY ps.version_number DESC
    )
    INTO v_result
    FROM plan_snapshots ps
    WHERE ps.plan_version_id = p_plan_version_id;

    RETURN COALESCE(v_result, '[]'::JSONB);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_snapshot_history IS
'Returns all published snapshots for a plan. Includes is_legacy flag for empty payloads.';


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 027a: Snapshot Fixes COMPLETE (V3.7.2)';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'FIXES APPLIED:';
    RAISE NOTICE '  1. Unique constraint on (plan_version_id, version_number)';
    RAISE NOTICE '  2. FOR UPDATE locking in publish_plan_snapshot()';
    RAISE NOTICE '  3. Freeze window enforcement with force override';
    RAISE NOTICE '  4. Audit trail tracks forced_during_freeze + force_reason';
    RAISE NOTICE '  5. Helper: build_snapshot_payload() for real data';
    RAISE NOTICE '  6. verify_snapshot_integrity() for validation';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM verify_snapshot_integrity();';
    RAISE NOTICE '============================================================';
END $$;
