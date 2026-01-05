-- ============================================================================
-- MIGRATION 010: Fix expand_tour_instances to include tenant_id
-- ============================================================================
-- After migration 006, tenant_id is NOT NULL on tour_instances.
-- The expand_tour_instances function must copy tenant_id from tours_normalized.
-- ============================================================================

CREATE OR REPLACE FUNCTION expand_tour_instances(p_forecast_version_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    v_tour RECORD;
    v_instance INTEGER;
    v_crosses_midnight BOOLEAN;
    v_instances_created INTEGER := 0;
BEGIN
    -- For each tour in the forecast
    FOR v_tour IN
        SELECT * FROM tours_normalized
        WHERE forecast_version_id = p_forecast_version_id
    LOOP
        -- Cross-midnight detection
        v_crosses_midnight := (v_tour.end_ts < v_tour.start_ts);

        -- Create count instances
        FOR v_instance IN 1..v_tour.count LOOP
            INSERT INTO tour_instances (
                tour_template_id, instance_number, forecast_version_id,
                day, start_ts, end_ts, crosses_midnight,
                duration_min, work_hours, depot, skill,
                span_group_key, split_break_minutes, tenant_id
            ) VALUES (
                v_tour.id, v_instance, p_forecast_version_id,
                v_tour.day, v_tour.start_ts, v_tour.end_ts, v_crosses_midnight,
                v_tour.duration_min, v_tour.work_hours, v_tour.depot, v_tour.skill,
                v_tour.span_group_key, v_tour.split_break_minutes, v_tour.tenant_id
            )
            ON CONFLICT (tour_template_id, instance_number) DO UPDATE SET
                span_group_key = EXCLUDED.span_group_key,
                split_break_minutes = EXCLUDED.split_break_minutes,
                tenant_id = EXCLUDED.tenant_id;

            v_instances_created := v_instances_created + 1;
        END LOOP;
    END LOOP;

    RETURN v_instances_created;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION expand_tour_instances IS 'Auto-expand tours_normalized.count to tour_instances (includes tenant_id)';

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('010', 'Fix expand_tour_instances to include tenant_id', NOW())
ON CONFLICT (version) DO NOTHING;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '[OK] Migration 010 Applied: expand_tour_instances now includes tenant_id';
END $$;
