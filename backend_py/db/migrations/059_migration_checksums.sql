-- ============================================================================
-- MIGRATION 059: Migration Checksums for Idempotency Proof
-- ============================================================================
-- Purpose: Add checksum tracking to schema_migrations for RerunProof feature.
--
-- Behavior:
--   - Adds checksum VARCHAR(64) column (SHA256 hex)
--   - Adds file_name VARCHAR(100) column for file-to-version mapping
--   - NULL checksum = legacy migration (applied before checksums)
--   - Non-NULL checksum = verified migration content
--
-- Usage:
--   fresh-db-proof.ps1 -RerunProof  # Skips migrations with matching checksums
--
-- IDEMPOTENT: Safe to run multiple times
-- ============================================================================

-- Add checksum column if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'schema_migrations'
          AND column_name = 'checksum'
    ) THEN
        ALTER TABLE schema_migrations ADD COLUMN checksum VARCHAR(64);
        RAISE NOTICE '[059] Added checksum column to schema_migrations';
    ELSE
        RAISE NOTICE '[059] checksum column already exists - skipping';
    END IF;
END $$;

-- Add file_name column if not exists (for file-to-version mapping)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'schema_migrations'
          AND column_name = 'file_name'
    ) THEN
        ALTER TABLE schema_migrations ADD COLUMN file_name VARCHAR(100);
        RAISE NOTICE '[059] Added file_name column to schema_migrations';
    ELSE
        RAISE NOTICE '[059] file_name column already exists - skipping';
    END IF;
END $$;

-- Create unique index on file_name for efficient lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_schema_migrations_file_name
ON schema_migrations (file_name) WHERE file_name IS NOT NULL;

-- Comment for documentation
COMMENT ON COLUMN schema_migrations.checksum IS 'SHA256 hex of migration file content (NULL = legacy)';
COMMENT ON COLUMN schema_migrations.file_name IS 'Original migration filename for checksum tracking';

-- Record this migration (checksum will be updated by PowerShell after execution)
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('059', 'Migration checksums for idempotency proof', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- Success Message
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 059: Migration Checksums COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Added: schema_migrations.checksum VARCHAR(64)';
    RAISE NOTICE 'Added: schema_migrations.file_name VARCHAR(100)';
    RAISE NOTICE 'Use: fresh-db-proof.ps1 -RerunProof to test idempotency';
    RAISE NOTICE '============================================================';
END $$;
