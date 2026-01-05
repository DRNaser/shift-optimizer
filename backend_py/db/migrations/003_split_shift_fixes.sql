-- ============================================================================
-- MIGRATION 003: Split Shift Fixes (Critical Bug Fixes)
-- ============================================================================
-- Fixes identified in expert review:
-- 1. span_group_key missing from tour_instances
-- 2. split_break_minutes not persisted
-- ============================================================================

-- 1. Add split_break_minutes to tours_normalized
ALTER TABLE tours_normalized
ADD COLUMN IF NOT EXISTS split_break_minutes INTEGER;

COMMENT ON COLUMN tours_normalized.split_break_minutes IS 'Break duration in minutes for split shifts (240-360min valid range)';

-- 2. Add span_group_key and split_break_minutes to tour_instances
ALTER TABLE tour_instances
ADD COLUMN IF NOT EXISTS span_group_key VARCHAR(50);

ALTER TABLE tour_instances
ADD COLUMN IF NOT EXISTS split_break_minutes INTEGER;

CREATE INDEX IF NOT EXISTS idx_tour_instances_span_group ON tour_instances(span_group_key);

COMMENT ON COLUMN tour_instances.span_group_key IS 'Split shift identifier for grouping parts (e.g., Mo_0600-1000_1500-1900)';
COMMENT ON COLUMN tour_instances.split_break_minutes IS 'Break duration in minutes for split shifts';

-- 3. Update expand_tour_instances to include new fields
CREATE OR REPLACE FUNCTION expand_tour_instances(p_forecast_version_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    v_tour RECORD;
    v_instance INTEGER;
    v_crosses_midnight BOOLEAN;
    v_instances_created INTEGER := 0;
BEGIN
    -- Für jede Tour im Forecast
    FOR v_tour IN
        SELECT * FROM tours_normalized
        WHERE forecast_version_id = p_forecast_version_id
    LOOP
        -- Cross-midnight detection
        v_crosses_midnight := (v_tour.end_ts < v_tour.start_ts);

        -- Erstelle count Instanzen
        FOR v_instance IN 1..v_tour.count LOOP
            INSERT INTO tour_instances (
                tour_template_id, instance_number, forecast_version_id,
                day, start_ts, end_ts, crosses_midnight,
                duration_min, work_hours, depot, skill,
                span_group_key, split_break_minutes
            ) VALUES (
                v_tour.id, v_instance, p_forecast_version_id,
                v_tour.day, v_tour.start_ts, v_tour.end_ts, v_crosses_midnight,
                v_tour.duration_min, v_tour.work_hours, v_tour.depot, v_tour.skill,
                v_tour.span_group_key, v_tour.split_break_minutes
            )
            ON CONFLICT (tour_template_id, instance_number) DO UPDATE SET
                span_group_key = EXCLUDED.span_group_key,
                split_break_minutes = EXCLUDED.split_break_minutes;

            v_instances_created := v_instances_created + 1;
        END LOOP;
    END LOOP;

    RETURN v_instances_created;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION expand_tour_instances IS 'Auto-expand tours_normalized.count to tour_instances (includes span_group_key, split_break_minutes)';

-- 4. Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('003', 'Add span_group_key and split_break_minutes to tour_instances', NOW())
ON CONFLICT (version) DO NOTHING;

-- 5. Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 003 Applied: Split shift fixes';
    RAISE NOTICE '   - Added split_break_minutes to tours_normalized';
    RAISE NOTICE '   - Added span_group_key to tour_instances';
    RAISE NOTICE '   - Added split_break_minutes to tour_instances';
    RAISE NOTICE '   - Updated expand_tour_instances() function';
END $$;
