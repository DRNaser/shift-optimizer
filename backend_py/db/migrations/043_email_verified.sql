-- =============================================================================
-- MIGRATION 043: Email Verification Field
-- =============================================================================
--
-- Purpose:
--   Adds email_verified_at column to auth.users for tracking email verification.
--   Used by bootstrap scripts to mark email as verified without email flow.
--
-- =============================================================================

BEGIN;

-- Add email_verified_at column to auth.users
ALTER TABLE auth.users
ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ NULL;

-- Comment for documentation
COMMENT ON COLUMN auth.users.email_verified_at IS 'Timestamp when email was verified. NULL = not verified.';

-- Index for querying verified users (optional, for future email login flows)
CREATE INDEX IF NOT EXISTS idx_users_email_verified
ON auth.users(email_verified_at) WHERE email_verified_at IS NOT NULL;

COMMIT;
