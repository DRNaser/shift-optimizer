-- ============================================================================
-- MIGRATION 025f: ACL FIX - Revoke Existing PUBLIC Grants (IDEMPOTENT)
-- ============================================================================
-- This migration fixes existing PUBLIC grants on user-defined objects.
-- Default privileges only protect NEW objects - this fixes existing ones.
--
-- SAFE TO RUN MULTIPLE TIMES: All operations are idempotent.
--
-- ALLOWLIST APPROACH:
--   Extension patterns are excluded (pgcrypto, PostGIS, uuid-ossp, etc.)
--   Everything else: REVOKE PUBLIC grants
--
-- EXTENSION PATTERNS EXCLUDED:
--   Functions: pg_*, pgp_*, armor*, dearmor*, crypt*, gen_random*, gen_salt*,
--              digest*, hmac*, encrypt*, decrypt*, uuid_*, st_*, geography_*,
--              geometry_*, box2d*, box3d*, postgis_*, _*
--   Tables: pg_*, spatial_ref_sys*, geometry_columns*, geography_columns*
-- ============================================================================

-- ============================================================================
-- 1. SCAN AND REPORT CURRENT STATE
-- ============================================================================

CREATE OR REPLACE FUNCTION acl_scan_report()
RETURNS TABLE (
    schema_name TEXT,
    object_type TEXT,
    object_name TEXT,
    privilege TEXT,
    grantee TEXT,
    is_extension BOOLEAN,
    action TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- Functions with PUBLIC EXECUTE
    RETURN QUERY
    SELECT
        n.nspname::TEXT AS schema_name,
        'FUNCTION'::TEXT AS object_type,
        p.proname::TEXT AS object_name,
        'EXECUTE'::TEXT AS privilege,
        'PUBLIC'::TEXT AS grantee,
        -- Check if extension pattern
        (p.proname LIKE 'pg_%' OR p.proname LIKE 'pgp_%' OR
         p.proname LIKE 'armor%' OR p.proname LIKE 'dearmor%' OR
         p.proname LIKE 'crypt%' OR p.proname LIKE 'gen_random%' OR
         p.proname LIKE 'gen_salt%' OR p.proname LIKE 'digest%' OR
         p.proname LIKE 'hmac%' OR p.proname LIKE 'encrypt%' OR
         p.proname LIKE 'decrypt%' OR p.proname LIKE 'uuid_%' OR
         p.proname LIKE 'st_%' OR p.proname LIKE 'geography_%' OR
         p.proname LIKE 'geometry_%' OR p.proname LIKE 'box2d%' OR
         p.proname LIKE 'box3d%' OR p.proname LIKE 'postgis_%' OR
         p.proname LIKE '_%') AS is_extension,
        CASE
            WHEN (p.proname LIKE 'pg_%' OR p.proname LIKE 'pgp_%' OR
                  p.proname LIKE 'armor%' OR p.proname LIKE 'dearmor%' OR
                  p.proname LIKE 'crypt%' OR p.proname LIKE 'gen_random%' OR
                  p.proname LIKE 'gen_salt%' OR p.proname LIKE 'digest%' OR
                  p.proname LIKE 'hmac%' OR p.proname LIKE 'encrypt%' OR
                  p.proname LIKE 'decrypt%' OR p.proname LIKE 'uuid_%' OR
                  p.proname LIKE 'st_%' OR p.proname LIKE 'geography_%' OR
                  p.proname LIKE 'geometry_%' OR p.proname LIKE 'box2d%' OR
                  p.proname LIKE 'box3d%' OR p.proname LIKE 'postgis_%' OR
                  p.proname LIKE '_%')
            THEN 'SKIP (extension)'
            ELSE 'REVOKE'
        END AS action
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname IN ('public', 'core')
      AND has_function_privilege('PUBLIC', p.oid, 'EXECUTE') = true;

    -- Tables with PUBLIC SELECT
    RETURN QUERY
    SELECT
        n.nspname::TEXT AS schema_name,
        'TABLE'::TEXT AS object_type,
        c.relname::TEXT AS object_name,
        'SELECT'::TEXT AS privilege,
        'PUBLIC'::TEXT AS grantee,
        (c.relname LIKE 'pg_%' OR c.relname LIKE 'spatial_ref_sys%' OR
         c.relname LIKE 'geometry_columns%' OR c.relname LIKE 'geography_columns%') AS is_extension,
        CASE
            WHEN (c.relname LIKE 'pg_%' OR c.relname LIKE 'spatial_ref_sys%' OR
                  c.relname LIKE 'geometry_columns%' OR c.relname LIKE 'geography_columns%')
            THEN 'SKIP (extension)'
            ELSE 'REVOKE'
        END AS action
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname IN ('public', 'core')
      AND c.relkind = 'r'
      AND has_table_privilege('PUBLIC', c.oid, 'SELECT') = true;
END;
$$;

-- ============================================================================
-- 2. GENERATE FIX COMMANDS (DRY RUN VIEW)
-- ============================================================================

CREATE OR REPLACE FUNCTION acl_generate_fix_commands()
RETURNS TABLE (
    fix_command TEXT,
    object_info TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    r RECORD;
    func_sig TEXT;
BEGIN
    -- Functions to fix
    FOR r IN
        SELECT n.nspname, p.proname, p.oid,
               pg_get_function_identity_arguments(p.oid) AS args
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname IN ('public', 'core')
          AND has_function_privilege('PUBLIC', p.oid, 'EXECUTE') = true
          -- Exclude extension patterns
          AND p.proname NOT LIKE 'pg_%'
          AND p.proname NOT LIKE 'pgp_%'
          AND p.proname NOT LIKE 'armor%'
          AND p.proname NOT LIKE 'dearmor%'
          AND p.proname NOT LIKE 'crypt%'
          AND p.proname NOT LIKE 'gen_random%'
          AND p.proname NOT LIKE 'gen_salt%'
          AND p.proname NOT LIKE 'digest%'
          AND p.proname NOT LIKE 'hmac%'
          AND p.proname NOT LIKE 'encrypt%'
          AND p.proname NOT LIKE 'decrypt%'
          AND p.proname NOT LIKE 'uuid_%'
          AND p.proname NOT LIKE 'st_%'
          AND p.proname NOT LIKE 'geography_%'
          AND p.proname NOT LIKE 'geometry_%'
          AND p.proname NOT LIKE 'box2d%'
          AND p.proname NOT LIKE 'box3d%'
          AND p.proname NOT LIKE 'postgis_%'
          AND p.proname NOT LIKE '_%'
    LOOP
        func_sig := r.nspname || '.' || r.proname || '(' || COALESCE(r.args, '') || ')';
        fix_command := format('REVOKE EXECUTE ON FUNCTION %I.%I(%s) FROM PUBLIC;',
                              r.nspname, r.proname, COALESCE(r.args, ''));
        object_info := 'FUNCTION: ' || func_sig;
        RETURN NEXT;
    END LOOP;

    -- Tables to fix
    FOR r IN
        SELECT n.nspname, c.relname
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname IN ('public', 'core')
          AND c.relkind = 'r'
          AND has_table_privilege('PUBLIC', c.oid, 'SELECT') = true
          -- Exclude extension patterns
          AND c.relname NOT LIKE 'pg_%'
          AND c.relname NOT LIKE 'spatial_ref_sys%'
          AND c.relname NOT LIKE 'geometry_columns%'
          AND c.relname NOT LIKE 'geography_columns%'
    LOOP
        fix_command := format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC;', r.nspname, r.relname);
        object_info := 'TABLE: ' || r.nspname || '.' || r.relname;
        RETURN NEXT;
    END LOOP;
END;
$$;

-- ============================================================================
-- 3. APPLY FIXES (IDEMPOTENT)
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    fix_count INTEGER := 0;
    func_sig TEXT;
BEGIN
    RAISE NOTICE '[025f] Starting ACL fix (REVOKE PUBLIC grants on user-defined objects)...';

    -- Fix functions
    FOR r IN
        SELECT n.nspname, p.proname, p.oid,
               pg_get_function_identity_arguments(p.oid) AS args
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname IN ('public', 'core')
          AND has_function_privilege('PUBLIC', p.oid, 'EXECUTE') = true
          -- Exclude extension patterns
          AND p.proname NOT LIKE 'pg_%'
          AND p.proname NOT LIKE 'pgp_%'
          AND p.proname NOT LIKE 'armor%'
          AND p.proname NOT LIKE 'dearmor%'
          AND p.proname NOT LIKE 'crypt%'
          AND p.proname NOT LIKE 'gen_random%'
          AND p.proname NOT LIKE 'gen_salt%'
          AND p.proname NOT LIKE 'digest%'
          AND p.proname NOT LIKE 'hmac%'
          AND p.proname NOT LIKE 'encrypt%'
          AND p.proname NOT LIKE 'decrypt%'
          AND p.proname NOT LIKE 'uuid_%'
          AND p.proname NOT LIKE 'st_%'
          AND p.proname NOT LIKE 'geography_%'
          AND p.proname NOT LIKE 'geometry_%'
          AND p.proname NOT LIKE 'box2d%'
          AND p.proname NOT LIKE 'box3d%'
          AND p.proname NOT LIKE 'postgis_%'
          AND p.proname NOT LIKE '_%'
    LOOP
        func_sig := r.nspname || '.' || r.proname || '(' || COALESCE(r.args, '') || ')';
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %I.%I(%s) FROM PUBLIC',
                       r.nspname, r.proname, COALESCE(r.args, ''));
        RAISE NOTICE '[025f] REVOKED EXECUTE ON FUNCTION % FROM PUBLIC', func_sig;
        fix_count := fix_count + 1;
    END LOOP;

    -- Fix tables
    FOR r IN
        SELECT n.nspname, c.relname
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname IN ('public', 'core')
          AND c.relkind = 'r'
          AND has_table_privilege('PUBLIC', c.oid, 'SELECT') = true
          -- Exclude extension patterns
          AND c.relname NOT LIKE 'pg_%'
          AND c.relname NOT LIKE 'spatial_ref_sys%'
          AND c.relname NOT LIKE 'geometry_columns%'
          AND c.relname NOT LIKE 'geography_columns%'
    LOOP
        EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC', r.nspname, r.relname);
        RAISE NOTICE '[025f] REVOKED ALL ON TABLE %.% FROM PUBLIC', r.nspname, r.relname;
        fix_count := fix_count + 1;
    END LOOP;

    IF fix_count = 0 THEN
        RAISE NOTICE '[025f] No PUBLIC grants to fix - already clean!';
    ELSE
        RAISE NOTICE '[025f] Fixed % objects with PUBLIC grants', fix_count;
    END IF;
END $$;

-- ============================================================================
-- 4. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('025f', 'ACL fix: revoke existing PUBLIC grants on user-defined objects', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- 5. VERIFY FIX WAS APPLIED
-- ============================================================================

DO $$
DECLARE
    remaining_count INTEGER;
BEGIN
    -- Count remaining user objects with PUBLIC grants
    SELECT COUNT(*) INTO remaining_count
    FROM (
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname IN ('public', 'core')
          AND has_function_privilege('PUBLIC', p.oid, 'EXECUTE') = true
          AND p.proname NOT LIKE 'pg_%'
          AND p.proname NOT LIKE 'pgp_%'
          AND p.proname NOT LIKE 'armor%'
          AND p.proname NOT LIKE 'dearmor%'
          AND p.proname NOT LIKE 'crypt%'
          AND p.proname NOT LIKE 'gen_random%'
          AND p.proname NOT LIKE 'gen_salt%'
          AND p.proname NOT LIKE 'digest%'
          AND p.proname NOT LIKE 'hmac%'
          AND p.proname NOT LIKE 'encrypt%'
          AND p.proname NOT LIKE 'decrypt%'
          AND p.proname NOT LIKE 'uuid_%'
          AND p.proname NOT LIKE 'st_%'
          AND p.proname NOT LIKE 'geography_%'
          AND p.proname NOT LIKE 'geometry_%'
          AND p.proname NOT LIKE 'box2d%'
          AND p.proname NOT LIKE 'box3d%'
          AND p.proname NOT LIKE 'postgis_%'
          AND p.proname NOT LIKE '_%'
        UNION ALL
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname IN ('public', 'core')
          AND c.relkind = 'r'
          AND has_table_privilege('PUBLIC', c.oid, 'SELECT') = true
          AND c.relname NOT LIKE 'pg_%'
          AND c.relname NOT LIKE 'spatial_ref_sys%'
          AND c.relname NOT LIKE 'geometry_columns%'
          AND c.relname NOT LIKE 'geography_columns%'
    ) AS remaining;

    IF remaining_count > 0 THEN
        RAISE WARNING '[025f] WARNING: % objects still have PUBLIC grants after fix!', remaining_count;
    ELSE
        RAISE NOTICE '[025f] SUCCESS: No user-defined objects have PUBLIC grants';
    END IF;
END $$;

-- ============================================================================
-- 6. JSON REPORT FOR CI ARTIFACT
-- ============================================================================
-- Outputs structured JSON for CI upload

CREATE OR REPLACE FUNCTION acl_scan_report_json()
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'generated_at', NOW()::TEXT,
        'migration_version', '025f',
        'scan_results', (
            SELECT COALESCE(json_agg(row_to_json(t)), '[]'::JSON)
            FROM acl_scan_report() t
        ),
        'summary', json_build_object(
            'total_objects', (SELECT COUNT(*) FROM acl_scan_report()),
            'to_revoke', (SELECT COUNT(*) FROM acl_scan_report() WHERE action = 'REVOKE'),
            'skipped_extensions', (SELECT COUNT(*) FROM acl_scan_report() WHERE action = 'SKIP (extension)')
        ),
        'fix_commands', (
            SELECT COALESCE(json_agg(row_to_json(t)), '[]'::JSON)
            FROM acl_generate_fix_commands() t
        )
    ) INTO result;

    RETURN result;
END;
$$;

COMMENT ON FUNCTION acl_scan_report_json IS
'Generates JSON report of PUBLIC grants for CI artifact upload.
Usage: psql -c "SELECT acl_scan_report_json()" > acl_scan_report.json';

-- ============================================================================
-- 7. SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'Migration 025f: ACL Fix COMPLETE';
    RAISE NOTICE '==================================================================';
    RAISE NOTICE 'WHAT WAS DONE:';
    RAISE NOTICE '  1. Scanned public/core schemas for PUBLIC grants';
    RAISE NOTICE '  2. Excluded extension objects (pgcrypto, PostGIS, etc.)';
    RAISE NOTICE '  3. Revoked PUBLIC grants on user-defined objects';
    RAISE NOTICE '';
    RAISE NOTICE 'DIAGNOSTIC FUNCTIONS:';
    RAISE NOTICE '  SELECT * FROM acl_scan_report();           -- Full scan (table)';
    RAISE NOTICE '  SELECT * FROM acl_generate_fix_commands(); -- Dry run';
    RAISE NOTICE '  SELECT acl_scan_report_json();             -- JSON for CI artifact';
    RAISE NOTICE '';
    RAISE NOTICE 'CI ARTIFACT GENERATION:';
    RAISE NOTICE '  psql -c "SELECT acl_scan_report_json()" -t > acl_scan_report.json';
    RAISE NOTICE '';
    RAISE NOTICE 'THIS MIGRATION IS IDEMPOTENT - safe to run multiple times.';
    RAISE NOTICE '==================================================================';
END $$;
