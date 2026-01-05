-- ============================================================================
-- MIGRATION 008: Tour Groups & Segments (Segment Adapter Pattern)
-- ============================================================================
-- V3.3a Product Core: Additive segment model for explicit work intervals
--
-- Pattern: Segment Adapter
-- - tour_groups: Logical grouping of segments (1er, 2er, 3er blocks)
-- - tour_segments: Individual work intervals with TIMESTAMPTZ
-- - Adapter function: get_work_intervals() bridges to existing tour model
--
-- NOTE: This is ADDITIVE - existing TIME columns in tours_normalized and
--       tour_instances remain unchanged for backward compatibility.
-- ============================================================================

-- ============================================================================
-- 1. TOUR GROUPS TABLE
-- ============================================================================
-- Logical grouping for multi-segment duties (2er, 3er blocks)

CREATE TABLE IF NOT EXISTS tour_groups (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id),
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    group_type          VARCHAR(20) NOT NULL CHECK (group_type IN ('1ER', '2ER_REG', '2ER_SPLIT', '3ER')),
    driver_id           VARCHAR(50),                -- NULL until assigned
    day                 INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),
    total_work_minutes  INTEGER NOT NULL CHECK (total_work_minutes > 0),
    total_span_minutes  INTEGER NOT NULL CHECK (total_span_minutes > 0),
    crosses_midnight    BOOLEAN NOT NULL DEFAULT FALSE,
    metadata            JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tour_groups_tenant
ON tour_groups(tenant_id);

CREATE INDEX IF NOT EXISTS idx_tour_groups_forecast
ON tour_groups(tenant_id, forecast_version_id);

CREATE INDEX IF NOT EXISTS idx_tour_groups_driver
ON tour_groups(tenant_id, driver_id)
WHERE driver_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tour_groups_day
ON tour_groups(tenant_id, forecast_version_id, day);

COMMENT ON TABLE tour_groups IS 'Logical grouping of segments into block types (V3.3a Segment Adapter)';
COMMENT ON COLUMN tour_groups.group_type IS '1ER=single, 2ER_REG=double regular, 2ER_SPLIT=double split, 3ER=triple';
COMMENT ON COLUMN tour_groups.total_work_minutes IS 'Sum of all segment durations (excluding breaks)';
COMMENT ON COLUMN tour_groups.total_span_minutes IS 'First segment start to last segment end';

-- ============================================================================
-- 2. TOUR SEGMENTS TABLE
-- ============================================================================
-- Individual work intervals with explicit TIMESTAMPTZ

CREATE TABLE IF NOT EXISTS tour_segments (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id),
    tour_group_id       INTEGER NOT NULL REFERENCES tour_groups(id) ON DELETE CASCADE,
    segment_index       INTEGER NOT NULL CHECK (segment_index >= 0),  -- 0, 1, 2 for 3er

    -- TIMESTAMPTZ for explicit datetime (anchor-aware)
    start_at            TIMESTAMPTZ NOT NULL,
    end_at              TIMESTAMPTZ NOT NULL,

    -- Backward-compatible TIME columns (derived, for audit compatibility)
    start_ts            TIME NOT NULL,
    end_ts              TIME NOT NULL,

    duration_min        INTEGER NOT NULL CHECK (duration_min > 0),
    work_hours          DECIMAL(5,2) NOT NULL CHECK (work_hours > 0),
    crosses_midnight    BOOLEAN NOT NULL DEFAULT FALSE,

    -- Link to original tour_instance (if migrated)
    tour_instance_id    INTEGER REFERENCES tour_instances(id),

    metadata            JSONB,

    CONSTRAINT tour_segments_unique_index
        UNIQUE (tour_group_id, segment_index)
);

CREATE INDEX IF NOT EXISTS idx_tour_segments_tenant
ON tour_segments(tenant_id);

CREATE INDEX IF NOT EXISTS idx_tour_segments_group
ON tour_segments(tour_group_id);

CREATE INDEX IF NOT EXISTS idx_tour_segments_instance
ON tour_segments(tour_instance_id)
WHERE tour_instance_id IS NOT NULL;

-- Index for time-range queries
CREATE INDEX IF NOT EXISTS idx_tour_segments_time_range
ON tour_segments(tenant_id, start_at, end_at);

COMMENT ON TABLE tour_segments IS 'Individual work intervals with TIMESTAMPTZ (V3.3a Segment Adapter)';
COMMENT ON COLUMN tour_segments.start_at IS 'Absolute datetime (TIMESTAMPTZ) for anchor-aware scheduling';
COMMENT ON COLUMN tour_segments.end_at IS 'Absolute datetime (TIMESTAMPTZ) for anchor-aware scheduling';
COMMENT ON COLUMN tour_segments.start_ts IS 'TIME-only for backward compatibility with existing audits';
COMMENT ON COLUMN tour_segments.tour_instance_id IS 'Optional link to legacy tour_instance';

-- ============================================================================
-- 3. SEGMENT ADAPTER: get_work_intervals()
-- ============================================================================
-- Bridge function for existing audit/solver code

CREATE OR REPLACE FUNCTION get_work_intervals(
    p_tenant_id INTEGER,
    p_forecast_version_id INTEGER,
    p_driver_id VARCHAR(50) DEFAULT NULL
)
RETURNS TABLE (
    tour_group_id INTEGER,
    segment_id INTEGER,
    segment_index INTEGER,
    group_type VARCHAR(20),
    driver_id VARCHAR(50),
    day INTEGER,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    start_ts TIME,
    end_ts TIME,
    duration_min INTEGER,
    work_hours DECIMAL(5,2),
    crosses_midnight BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        tg.id AS tour_group_id,
        ts.id AS segment_id,
        ts.segment_index,
        tg.group_type,
        tg.driver_id,
        tg.day,
        ts.start_at,
        ts.end_at,
        ts.start_ts,
        ts.end_ts,
        ts.duration_min,
        ts.work_hours,
        ts.crosses_midnight
    FROM tour_groups tg
    JOIN tour_segments ts ON tg.id = ts.tour_group_id
    WHERE tg.tenant_id = p_tenant_id
      AND tg.forecast_version_id = p_forecast_version_id
      AND (p_driver_id IS NULL OR tg.driver_id = p_driver_id)
    ORDER BY tg.day, ts.start_at, ts.segment_index;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_work_intervals(INTEGER, INTEGER, VARCHAR) IS
    'Segment Adapter: Returns flattened work intervals for audit/solver compatibility';

-- ============================================================================
-- 4. HELPER: Create Segments from Tour Instance
-- ============================================================================
-- Migrates existing tour_instance data to segment model

CREATE OR REPLACE FUNCTION create_segment_from_instance(
    p_tenant_id INTEGER,
    p_forecast_version_id INTEGER,
    p_tour_instance_id INTEGER,
    p_week_anchor_date DATE,
    p_group_type VARCHAR(20) DEFAULT '1ER'
)
RETURNS INTEGER AS $$
DECLARE
    v_instance RECORD;
    v_group_id INTEGER;
    v_segment_id INTEGER;
    v_start_at TIMESTAMPTZ;
    v_end_at TIMESTAMPTZ;
BEGIN
    -- Get tour instance data
    SELECT * INTO v_instance
    FROM tour_instances
    WHERE id = p_tour_instance_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Tour instance % not found', p_tour_instance_id;
    END IF;

    -- Compute TIMESTAMPTZ from week anchor + day + time
    v_start_at := (p_week_anchor_date + (v_instance.day - 1) * INTERVAL '1 day')::DATE + v_instance.start_ts;

    IF v_instance.crosses_midnight THEN
        v_end_at := (p_week_anchor_date + v_instance.day * INTERVAL '1 day')::DATE + v_instance.end_ts;
    ELSE
        v_end_at := (p_week_anchor_date + (v_instance.day - 1) * INTERVAL '1 day')::DATE + v_instance.end_ts;
    END IF;

    -- Create tour_group
    INSERT INTO tour_groups (
        tenant_id, forecast_version_id, group_type, day,
        total_work_minutes, total_span_minutes, crosses_midnight
    )
    VALUES (
        p_tenant_id, p_forecast_version_id, p_group_type, v_instance.day,
        v_instance.duration_min, v_instance.duration_min, v_instance.crosses_midnight
    )
    RETURNING id INTO v_group_id;

    -- Create tour_segment
    INSERT INTO tour_segments (
        tenant_id, tour_group_id, segment_index,
        start_at, end_at, start_ts, end_ts,
        duration_min, work_hours, crosses_midnight,
        tour_instance_id
    )
    VALUES (
        p_tenant_id, v_group_id, 0,
        v_start_at, v_end_at, v_instance.start_ts, v_instance.end_ts,
        v_instance.duration_min, v_instance.work_hours, v_instance.crosses_midnight,
        p_tour_instance_id
    )
    RETURNING id INTO v_segment_id;

    RETURN v_group_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_segment_from_instance(INTEGER, INTEGER, INTEGER, DATE, VARCHAR) IS
    'Migrate single tour_instance to segment model with computed TIMESTAMPTZ';

-- ============================================================================
-- 5. GAP VALIDATION FUNCTION
-- ============================================================================
-- Validates gaps between segments in a group (for 2er/3er quality checks)

CREATE OR REPLACE FUNCTION validate_segment_gaps(
    p_tour_group_id INTEGER,
    p_min_gap_minutes INTEGER DEFAULT 30,
    p_max_gap_minutes INTEGER DEFAULT 60
)
RETURNS TABLE (
    segment_index INTEGER,
    gap_to_next_minutes INTEGER,
    gap_valid BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    WITH segments_ordered AS (
        SELECT
            ts.segment_index,
            ts.end_at,
            LEAD(ts.start_at) OVER (ORDER BY ts.segment_index) AS next_start
        FROM tour_segments ts
        WHERE ts.tour_group_id = p_tour_group_id
    )
    SELECT
        so.segment_index,
        EXTRACT(EPOCH FROM (so.next_start - so.end_at))::INTEGER / 60 AS gap_to_next_minutes,
        (EXTRACT(EPOCH FROM (so.next_start - so.end_at))::INTEGER / 60 BETWEEN p_min_gap_minutes AND p_max_gap_minutes) AS gap_valid
    FROM segments_ordered so
    WHERE so.next_start IS NOT NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION validate_segment_gaps(INTEGER, INTEGER, INTEGER) IS
    'Check gap validity between segments (30-60min for quality 3er chains)';

-- ============================================================================
-- 6. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('008', 'Tour groups and segments with TIMESTAMPTZ (V3.3a Segment Adapter)', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 7. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 008: Tour Groups & Segments COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - tour_groups table (1ER, 2ER_REG, 2ER_SPLIT, 3ER)';
    RAISE NOTICE '  - tour_segments table with TIMESTAMPTZ';
    RAISE NOTICE '  - get_work_intervals() adapter function';
    RAISE NOTICE '  - create_segment_from_instance() migration helper';
    RAISE NOTICE '  - validate_segment_gaps() quality check function';
    RAISE NOTICE '';
    RAISE NOTICE 'Pattern: Segment Adapter';
    RAISE NOTICE '  - Existing TIME columns preserved for backward compatibility';
    RAISE NOTICE '  - New TIMESTAMPTZ columns for anchor-aware scheduling';
    RAISE NOTICE '  - Adapter bridges between models';
    RAISE NOTICE '==================================================================';
END $$;
