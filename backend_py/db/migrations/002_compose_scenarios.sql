-- ============================================================================
-- SOLVEREIGN V3 Migration 002: Compose Engine + Scenario Support
-- ============================================================================
-- Purpose: Support partial forecasts (PATCH), composition (LWW), and scenarios
-- Created: 2026-01-04
-- Version: 3.1.0
-- ============================================================================

-- ============================================================================
-- 1. FORECAST_VERSIONS EXTENSIONS
-- ============================================================================

-- Add week_key for week identification (e.g., "2026-W01" or "2026-01-06")
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS week_key VARCHAR(20);

-- Expand source enum to include PATCH and COMPOSED
ALTER TABLE forecast_versions
DROP CONSTRAINT IF EXISTS forecast_versions_source_check;

ALTER TABLE forecast_versions
ADD CONSTRAINT forecast_versions_source_check
CHECK (source IN ('slack', 'csv', 'manual', 'patch', 'composed'));

-- Add completeness status for partial forecast gating
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS completeness_status VARCHAR(20) DEFAULT 'UNKNOWN'
CHECK (completeness_status IN ('UNKNOWN', 'PARTIAL', 'COMPLETE'));

-- Add expected days for the week (default 6 = Mo-Sa)
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS expected_days INTEGER DEFAULT 6 CHECK (expected_days BETWEEN 1 AND 7);

-- Add days present (actual count of days with tours)
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS days_present INTEGER DEFAULT 0 CHECK (days_present >= 0);

-- Add provenance for COMPOSED forecasts (which patches contributed)
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS provenance_json JSONB;

-- Add parent_version_id for patch chain
ALTER TABLE forecast_versions
ADD COLUMN IF NOT EXISTS parent_version_id INTEGER REFERENCES forecast_versions(id);

-- Index for week_key queries
CREATE INDEX IF NOT EXISTS idx_forecast_versions_week_key ON forecast_versions(week_key);

-- ============================================================================
-- 2. TOURS_NORMALIZED EXTENSIONS
-- ============================================================================

-- Add tombstone marker for removed tours in composition
ALTER TABLE tours_normalized
ADD COLUMN IF NOT EXISTS is_removed BOOLEAN DEFAULT FALSE;

-- Add source_version_id to track which patch a tour came from
ALTER TABLE tours_normalized
ADD COLUMN IF NOT EXISTS source_version_id INTEGER REFERENCES forecast_versions(id);

-- Index for composition queries
CREATE INDEX IF NOT EXISTS idx_tours_normalized_removed ON tours_normalized(is_removed);

-- ============================================================================
-- 3. PLAN_VERSIONS EXTENSIONS
-- ============================================================================

-- Add scenario_label for named scenarios
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS scenario_label VARCHAR(100);

-- Add baseline_plan_version_id for churn calculation
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS baseline_plan_version_id INTEGER REFERENCES plan_versions(id);

-- Add full solver config JSON
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS solver_config_json JSONB;

-- Add churn metrics
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS churn_count INTEGER DEFAULT 0;
ALTER TABLE plan_versions
ADD COLUMN IF NOT EXISTS churn_drivers_affected INTEGER DEFAULT 0;

-- Expand status enum to include SOLVING and FAILED
ALTER TABLE plan_versions
DROP CONSTRAINT IF EXISTS plan_versions_status_check;

ALTER TABLE plan_versions
ADD CONSTRAINT plan_versions_status_check
CHECK (status IN ('SOLVING', 'DRAFT', 'LOCKED', 'SUPERSEDED', 'FAILED'));

-- Index for scenario queries
CREATE INDEX IF NOT EXISTS idx_plan_versions_scenario ON plan_versions(scenario_label);
CREATE INDEX IF NOT EXISTS idx_plan_versions_baseline ON plan_versions(baseline_plan_version_id);

-- ============================================================================
-- 4. NEW TABLE: FORECAST_COMPOSITIONS
-- ============================================================================
-- Tracks which patches were composed into a COMPOSED forecast

CREATE TABLE IF NOT EXISTS forecast_compositions (
    id                  SERIAL PRIMARY KEY,
    composed_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    patch_version_id    INTEGER NOT NULL REFERENCES forecast_versions(id),
    patch_order         INTEGER NOT NULL,  -- Order in which patches were applied
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT forecast_compositions_unique UNIQUE (composed_version_id, patch_version_id)
);

CREATE INDEX IF NOT EXISTS idx_forecast_compositions_composed ON forecast_compositions(composed_version_id);
CREATE INDEX IF NOT EXISTS idx_forecast_compositions_patch ON forecast_compositions(patch_version_id);

-- ============================================================================
-- 5. NEW TABLE: TOUR_REMOVALS
-- ============================================================================
-- Explicit tombstones for removed tours (not just is_removed flag)

CREATE TABLE IF NOT EXISTS tour_removals (
    id                  SERIAL PRIMARY KEY,
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    tour_fingerprint    VARCHAR(64) NOT NULL,  -- Which tour was removed
    removed_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    reason              TEXT,
    CONSTRAINT tour_removals_unique UNIQUE (forecast_version_id, tour_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_tour_removals_fingerprint ON tour_removals(tour_fingerprint);

-- ============================================================================
-- 6. AUDIT LOG EXTENSIONS
-- ============================================================================

-- Add new audit check names for compose/scenarios
-- (No schema change needed, just documentation)

COMMENT ON TABLE forecast_compositions IS 'Tracks patch provenance for COMPOSED forecasts';
COMMENT ON TABLE tour_removals IS 'Explicit tombstones for tour removals in patches';

-- ============================================================================
-- 7. SCHEMA MIGRATION RECORD
-- ============================================================================

INSERT INTO schema_migrations (version, description)
VALUES ('002', 'Compose Engine + Scenario Support')
ON CONFLICT (version) DO NOTHING;
