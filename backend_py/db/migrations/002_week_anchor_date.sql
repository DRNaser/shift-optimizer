-- ============================================================================
-- Migration 002: Add week_anchor_date and week_key to forecast_versions
-- ============================================================================
-- Purpose: Enable deterministic datetime computation for tours
-- Created: 2026-01-05
-- Issue: week_anchor_date was documented but missing from schema
-- ============================================================================

-- Add week_key column (e.g., "2026-W01")
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS week_key VARCHAR(20);

-- Add week_anchor_date column (Monday of the week)
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS week_anchor_date DATE;

-- Add comments
COMMENT ON COLUMN forecast_versions.week_key IS 'Week identifier (e.g., "2026-W01") for compose operations';
COMMENT ON COLUMN forecast_versions.week_anchor_date IS 'Monday of the week for deterministic datetime computation from (day, start_ts, crosses_midnight)';

-- Create index for week_key lookups
CREATE INDEX IF NOT EXISTS idx_forecast_versions_week_key ON forecast_versions(week_key);

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('002', 'Add week_anchor_date and week_key to forecast_versions', NOW())
ON CONFLICT (version) DO NOTHING;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 002 Applied: week_anchor_date and week_key added to forecast_versions';
END $$;
