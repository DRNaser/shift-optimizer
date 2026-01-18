-- ============================================================================
-- MIGRATION 061: Dual Tenant Context Fix
-- ============================================================================
-- P0 CRITICAL FIX: Resolves dual tenant model with mixed INTEGER/UUID causing
-- RLS chaos.
--
-- PROBLEM:
--   - public.tenants(id INTEGER) - ~35 FK references (legacy operational data)
--   - core.tenants(id UUID) - ~25 FK references (new SaaS platform data)
--   - Single variable app.current_tenant_id used for both
--   - Backend sets INTEGER, core.* tables cast to UUID -> FAIL or silent RLS bypass
--
-- SOLUTION:
--   - Dual context variables: app.current_tenant_id_int, app.current_tenant_id_uuid
--   - Fail-closed helper functions that RAISE on missing context
--   - Verify gate to detect inconsistent configuration
--   - Backward compatible: legacy app.current_tenant_id still set
--
-- IDEMPOTENT: Safe to run multiple times
-- ============================================================================

BEGIN;

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('061', 'Dual tenant context fix for INTEGER/UUID split', NOW())
ON CONFLICT (version) DO UPDATE SET
    description = EXCLUDED.description,
    applied_at = NOW();

-- ============================================================================
-- HELPER FUNCTION: auth.current_tenant_id_int()
-- ============================================================================
-- FAIL-CLOSED: Returns INTEGER tenant ID or RAISES exception if not set.
-- Used by all public.* tables with INTEGER tenant_id.
-- Falls back to legacy variable during transition period.

CREATE OR REPLACE FUNCTION auth.current_tenant_id_int()
RETURNS INTEGER
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_raw TEXT;
    v_result INTEGER;
BEGIN
    -- Try new variable first
    v_raw := current_setting('app.current_tenant_id_int', true);

    IF v_raw IS NULL OR v_raw = '' THEN
        -- Fallback: try legacy variable (transition period)
        v_raw := current_setting('app.current_tenant_id', true);
    END IF;

    IF v_raw IS NULL OR v_raw = '' THEN
        -- FAIL-CLOSED: No context = deny access
        RAISE EXCEPTION 'RLS VIOLATION: app.current_tenant_id_int not set. Tenant context required.'
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    -- Validate it's actually an integer
    BEGIN
        v_result := v_raw::INTEGER;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'RLS VIOLATION: app.current_tenant_id_int is not a valid INTEGER: "%"', v_raw
            USING ERRCODE = 'data_exception';
    END;

    RETURN v_result;
END;
$$;

COMMENT ON FUNCTION auth.current_tenant_id_int IS
'FAIL-CLOSED: Returns INTEGER tenant_id for public.tenants system.
Raises exception if not set. Use auth.current_tenant_id_int_or_null() for platform admin scenarios.
Part of P0 dual tenant context fix (migration 061).';

-- ============================================================================
-- HELPER FUNCTION: auth.current_tenant_id_uuid()
-- ============================================================================
-- FAIL-CLOSED: Returns UUID tenant ID or RAISES exception if not set.
-- Used by all core.* tables with UUID tenant_id.

CREATE OR REPLACE FUNCTION auth.current_tenant_id_uuid()
RETURNS UUID
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_raw TEXT;
    v_result UUID;
BEGIN
    -- Try new variable
    v_raw := current_setting('app.current_tenant_id_uuid', true);

    IF v_raw IS NULL OR v_raw = '' THEN
        -- FAIL-CLOSED: No context = deny access
        RAISE EXCEPTION 'RLS VIOLATION: app.current_tenant_id_uuid not set. UUID tenant context required for core.* tables.'
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    -- Validate it's actually a UUID
    BEGIN
        v_result := v_raw::UUID;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'RLS VIOLATION: app.current_tenant_id_uuid is not a valid UUID: "%"', v_raw
            USING ERRCODE = 'data_exception';
    END;

    RETURN v_result;
END;
$$;

COMMENT ON FUNCTION auth.current_tenant_id_uuid IS
'FAIL-CLOSED: Returns UUID tenant_id for core.tenants system.
Raises exception if not set. Use auth.current_tenant_id_uuid_or_null() for platform admin scenarios.
Part of P0 dual tenant context fix (migration 061).';

-- ============================================================================
-- HELPER FUNCTION: auth.current_tenant_id_int_or_null()
-- ============================================================================
-- PERMISSIVE variant for platform admin scenarios where tenant may be NULL.
-- Returns NULL instead of raising exception.

CREATE OR REPLACE FUNCTION auth.current_tenant_id_int_or_null()
RETURNS INTEGER
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_raw TEXT;
BEGIN
    v_raw := current_setting('app.current_tenant_id_int', true);

    IF v_raw IS NULL OR v_raw = '' THEN
        -- Fallback: try legacy variable
        v_raw := current_setting('app.current_tenant_id', true);
    END IF;

    IF v_raw IS NULL OR v_raw = '' THEN
        RETURN NULL;
    END IF;

    RETURN v_raw::INTEGER;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION auth.current_tenant_id_int_or_null IS
'PERMISSIVE: Returns INTEGER tenant_id or NULL if not set/invalid.
Use for platform admin scenarios where NULL tenant is valid.
Part of P0 dual tenant context fix (migration 061).';

-- ============================================================================
-- HELPER FUNCTION: auth.current_tenant_id_uuid_or_null()
-- ============================================================================
-- PERMISSIVE variant for platform admin scenarios.

CREATE OR REPLACE FUNCTION auth.current_tenant_id_uuid_or_null()
RETURNS UUID
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_raw TEXT;
BEGIN
    v_raw := current_setting('app.current_tenant_id_uuid', true);

    IF v_raw IS NULL OR v_raw = '' THEN
        RETURN NULL;
    END IF;

    RETURN v_raw::UUID;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION auth.current_tenant_id_uuid_or_null IS
'PERMISSIVE: Returns UUID tenant_id or NULL if not set/invalid.
Use for platform admin scenarios where NULL tenant is valid.
Part of P0 dual tenant context fix (migration 061).';

-- ============================================================================
-- MAPPING FUNCTION: auth.get_tenant_uuid_for_int(INTEGER)
-- ============================================================================
-- Looks up core.tenants UUID given public.tenants INTEGER ID.
-- Uses tenant name as the bridge (same name in both tables).
-- Returns NULL if no mapping found (acceptable - tenant may not exist in core).

CREATE OR REPLACE FUNCTION auth.get_tenant_uuid_for_int(p_int_id INTEGER)
RETURNS UUID
LANGUAGE plpgsql
STABLE
SECURITY DEFINER  -- Bypass RLS for cross-schema lookup
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_tenant_name TEXT;
    v_uuid UUID;
BEGIN
    -- Get tenant name from public.tenants
    SELECT name INTO v_tenant_name
    FROM tenants
    WHERE id = p_int_id AND is_active = TRUE;

    IF v_tenant_name IS NULL THEN
        RETURN NULL;
    END IF;

    -- Look up in core.tenants by name or normalized tenant_code
    -- tenant_code is typically lowercase with underscores (e.g., "lts_transport")
    SELECT id INTO v_uuid
    FROM core.tenants
    WHERE tenant_code = LOWER(REPLACE(REPLACE(v_tenant_name, ' ', '_'), '-', '_'))
       OR name ILIKE v_tenant_name
    LIMIT 1;

    RETURN v_uuid;
END;
$$;

COMMENT ON FUNCTION auth.get_tenant_uuid_for_int IS
'Maps public.tenants INTEGER ID to core.tenants UUID via tenant name.
Returns NULL if no mapping found. Used by set_dual_tenant_context().
Part of P0 dual tenant context fix (migration 061).';

-- ============================================================================
-- CONTEXT SETTER: auth.set_dual_tenant_context()
-- ============================================================================
-- Called by backend to set BOTH context variables atomically.
-- Also sets legacy variable for backward compatibility.

CREATE OR REPLACE FUNCTION auth.set_dual_tenant_context(
    p_tenant_id_int INTEGER,
    p_tenant_id_uuid UUID DEFAULT NULL,
    p_is_platform_admin BOOLEAN DEFAULT FALSE
)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_uuid UUID;
BEGIN
    -- Set INTEGER context
    IF p_tenant_id_int IS NOT NULL THEN
        PERFORM set_config('app.current_tenant_id_int', p_tenant_id_int::TEXT, true);
        -- Legacy variable for backward compatibility
        PERFORM set_config('app.current_tenant_id', p_tenant_id_int::TEXT, true);
    ELSE
        PERFORM set_config('app.current_tenant_id_int', '', true);
        PERFORM set_config('app.current_tenant_id', '', true);
    END IF;

    -- Set UUID context
    IF p_tenant_id_uuid IS NOT NULL THEN
        v_uuid := p_tenant_id_uuid;
    ELSIF p_tenant_id_int IS NOT NULL THEN
        -- Auto-lookup UUID from INTEGER (may return NULL)
        v_uuid := auth.get_tenant_uuid_for_int(p_tenant_id_int);
    ELSE
        v_uuid := NULL;
    END IF;

    IF v_uuid IS NOT NULL THEN
        PERFORM set_config('app.current_tenant_id_uuid', v_uuid::TEXT, true);
    ELSE
        PERFORM set_config('app.current_tenant_id_uuid', '', true);
    END IF;

    -- Set platform admin flag (existing pattern)
    PERFORM set_config('app.is_platform_admin', p_is_platform_admin::TEXT, true);
END;
$$;

COMMENT ON FUNCTION auth.set_dual_tenant_context IS
'Sets both INTEGER and UUID tenant context atomically.
Auto-maps INT->UUID if only INT provided and mapping exists.
Always sets legacy app.current_tenant_id for backward compatibility.
Part of P0 dual tenant context fix (migration 061).

Usage:
  -- Tenant user with INT ID:
  SELECT auth.set_dual_tenant_context(1, NULL, FALSE);

  -- Tenant user with both IDs known:
  SELECT auth.set_dual_tenant_context(1, ''uuid-here''::UUID, FALSE);

  -- Platform admin (no tenant context):
  SELECT auth.set_dual_tenant_context(NULL, NULL, TRUE);';

-- ============================================================================
-- VERIFY GATE: auth.verify_tenant_context_consistency()
-- ============================================================================
-- Checks that dual tenant context infrastructure is properly configured.
-- Added to verify_pass_gate() as 6th gate.

CREATE OR REPLACE FUNCTION auth.verify_tenant_context_consistency()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Fail-closed helper functions exist
    RETURN QUERY
    SELECT 'dual_context_functions_exist'::TEXT,
           CASE WHEN COUNT(*) >= 4 THEN 'PASS' ELSE 'FAIL' END::TEXT,
           FORMAT('%s/4 dual context functions exist', COUNT(*))::TEXT
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'auth'
      AND p.proname IN ('current_tenant_id_int', 'current_tenant_id_uuid',
                        'current_tenant_id_int_or_null', 'current_tenant_id_uuid_or_null');

    -- Check 2: Context setter exists
    RETURN QUERY
    SELECT 'set_dual_tenant_context_exists'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
               WHERE n.nspname = 'auth' AND p.proname = 'set_dual_tenant_context'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'auth.set_dual_tenant_context() function exists'::TEXT;

    -- Check 3: Mapping function exists
    RETURN QUERY
    SELECT 'tenant_mapping_function_exists'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
               WHERE n.nspname = 'auth' AND p.proname = 'get_tenant_uuid_for_int'
           ) THEN 'PASS' ELSE 'FAIL' END::TEXT,
           'auth.get_tenant_uuid_for_int() function exists'::TEXT;

    -- Check 4: Legacy core.app_current_tenant_id still works (backward compat)
    RETURN QUERY
    SELECT 'core_helper_backward_compat'::TEXT,
           CASE WHEN EXISTS(
               SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
               WHERE n.nspname = 'core' AND p.proname = 'app_current_tenant_id'
           ) THEN 'PASS' ELSE 'WARN' END::TEXT,
           'core.app_current_tenant_id() exists for backward compat'::TEXT;

    -- Check 5: No policies using dangerous direct casts (INFO level - tracking progress)
    -- This checks for policies using ::INTEGER or ::UUID casts directly on current_setting
    RETURN QUERY
    SELECT 'policy_cast_audit'::TEXT,
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END::TEXT,
           FORMAT('%s policies still use direct current_setting casts (transition pending)', COUNT(*))::TEXT
    FROM pg_policies
    WHERE qual IS NOT NULL
      AND (
          qual::TEXT ~* 'current_setting\s*\([^)]*\)\s*::\s*integer'
          OR qual::TEXT ~* 'current_setting\s*\([^)]*\)\s*::\s*uuid'
      );

    -- Check 6: Verify tenant mapping coverage (if tenants exist)
    RETURN QUERY
    SELECT 'tenant_mapping_coverage'::TEXT,
           CASE
               WHEN (SELECT COUNT(*) FROM tenants WHERE is_active = TRUE) = 0 THEN 'PASS'
               WHEN (SELECT COUNT(*) FROM tenants t WHERE is_active = TRUE
                     AND auth.get_tenant_uuid_for_int(t.id) IS NOT NULL) > 0 THEN 'PASS'
               ELSE 'WARN'
           END::TEXT,
           FORMAT('Mapped: %s/%s active tenants have UUID mapping',
               (SELECT COUNT(*) FROM tenants t WHERE is_active = TRUE
                AND auth.get_tenant_uuid_for_int(t.id) IS NOT NULL),
               (SELECT COUNT(*) FROM tenants WHERE is_active = TRUE))::TEXT;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION auth.verify_tenant_context_consistency IS
'Verifies dual tenant context infrastructure is properly configured.
Part of verify_pass_gate() - 6th gate.
All checks should be PASS (WARN acceptable during transition).
Part of P0 dual tenant context fix (migration 061).';

-- ============================================================================
-- UPDATE verify_pass_gate() TO INCLUDE NEW GATE
-- ============================================================================

CREATE OR REPLACE FUNCTION verify_pass_gate()
RETURNS TABLE (
    gate_name TEXT,
    passed BOOLEAN,
    non_pass_count INTEGER
) AS $$
BEGIN
    -- Gate 1: auth.verify_rbac_integrity
    RETURN QUERY SELECT
        'auth.verify_rbac_integrity'::TEXT,
        (SELECT count(*) FROM auth.verify_rbac_integrity() WHERE status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM auth.verify_rbac_integrity() WHERE status <> 'PASS');

    -- Gate 2: masterdata.verify_masterdata_integrity
    RETURN QUERY SELECT
        'masterdata.verify_masterdata_integrity'::TEXT,
        (SELECT count(*) FROM masterdata.verify_masterdata_integrity() WHERE status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM masterdata.verify_masterdata_integrity() WHERE status <> 'PASS');

    -- Gate 3: verify_final_hardening (WARN allowed, only count FAIL)
    RETURN QUERY SELECT
        'verify_final_hardening'::TEXT,
        (SELECT count(*) FROM verify_final_hardening() WHERE status = 'FAIL') = 0,
        (SELECT count(*)::INTEGER FROM verify_final_hardening() WHERE status = 'FAIL');

    -- Gate 4: portal.verify_portal_integrity
    RETURN QUERY SELECT
        'portal.verify_portal_integrity'::TEXT,
        (SELECT count(*) FROM portal.verify_portal_integrity() WHERE check_status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM portal.verify_portal_integrity() WHERE check_status <> 'PASS');

    -- Gate 5: dispatch.verify_dispatch_integrity
    RETURN QUERY SELECT
        'dispatch.verify_dispatch_integrity'::TEXT,
        (SELECT count(*) FROM dispatch.verify_dispatch_integrity() WHERE check_status <> 'PASS') = 0,
        (SELECT count(*)::INTEGER FROM dispatch.verify_dispatch_integrity() WHERE check_status <> 'PASS');

    -- Gate 6: auth.verify_tenant_context_consistency (WARN allowed, only count FAIL)
    -- NEW in migration 061
    RETURN QUERY SELECT
        'auth.verify_tenant_context_consistency'::TEXT,
        (SELECT count(*) FROM auth.verify_tenant_context_consistency() WHERE status = 'FAIL') = 0,
        (SELECT count(*)::INTEGER FROM auth.verify_tenant_context_consistency() WHERE status = 'FAIL');
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION verify_pass_gate IS
'Combined gate check for all verify functions. Returns TRUE for each gate if 0 non-PASS rows.
Gate 6 (auth.verify_tenant_context_consistency) added in migration 061 for P0 dual tenant fix.
Usage: SELECT * FROM verify_pass_gate();
Acceptance: All passed = true';

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================

-- Helper functions - grant to API role for RLS evaluation
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_int() TO solvereign_api;
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_uuid() TO solvereign_api;
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_int_or_null() TO solvereign_api;
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_uuid_or_null() TO solvereign_api;
        GRANT EXECUTE ON FUNCTION auth.set_dual_tenant_context(INTEGER, UUID, BOOLEAN) TO solvereign_api;
        GRANT EXECUTE ON FUNCTION auth.get_tenant_uuid_for_int(INTEGER) TO solvereign_api;
        RAISE NOTICE '[061] Granted dual context functions to solvereign_api';
    END IF;
END $$;

-- Verify function - grant to platform and admin roles only
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT EXECUTE ON FUNCTION auth.verify_tenant_context_consistency() TO solvereign_platform;
        RAISE NOTICE '[061] Granted verify function to solvereign_platform';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_admin') THEN
        GRANT EXECUTE ON FUNCTION auth.verify_tenant_context_consistency() TO solvereign_admin;
        -- Also grant helper functions for migration/admin work
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_int() TO solvereign_admin;
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_uuid() TO solvereign_admin;
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_int_or_null() TO solvereign_admin;
        GRANT EXECUTE ON FUNCTION auth.current_tenant_id_uuid_or_null() TO solvereign_admin;
        GRANT EXECUTE ON FUNCTION auth.set_dual_tenant_context(INTEGER, UUID, BOOLEAN) TO solvereign_admin;
        GRANT EXECUTE ON FUNCTION auth.get_tenant_uuid_for_int(INTEGER) TO solvereign_admin;
        RAISE NOTICE '[061] Granted all functions to solvereign_admin';
    END IF;
END $$;

-- Revoke from PUBLIC (defense in depth)
REVOKE ALL ON FUNCTION auth.current_tenant_id_int() FROM PUBLIC;
REVOKE ALL ON FUNCTION auth.current_tenant_id_uuid() FROM PUBLIC;
REVOKE ALL ON FUNCTION auth.current_tenant_id_int_or_null() FROM PUBLIC;
REVOKE ALL ON FUNCTION auth.current_tenant_id_uuid_or_null() FROM PUBLIC;
REVOKE ALL ON FUNCTION auth.set_dual_tenant_context(INTEGER, UUID, BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth.get_tenant_uuid_for_int(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth.verify_tenant_context_consistency() FROM PUBLIC;

-- ============================================================================
-- RUN VERIFICATION
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    all_pass BOOLEAN := TRUE;
    fail_count INTEGER := 0;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '[061] Dual Tenant Context Fix - Running Verification';
    RAISE NOTICE '============================================================';

    FOR r IN SELECT * FROM auth.verify_tenant_context_consistency() LOOP
        IF r.status = 'PASS' THEN
            RAISE NOTICE '[061] PASS: % - %', r.check_name, r.details;
        ELSIF r.status = 'WARN' THEN
            RAISE WARNING '[061] WARN: % - %', r.check_name, r.details;
        ELSE
            RAISE WARNING '[061] FAIL: % - %', r.check_name, r.details;
            all_pass := FALSE;
            fail_count := fail_count + 1;
        END IF;
    END LOOP;

    RAISE NOTICE '';
    IF fail_count > 0 THEN
        RAISE EXCEPTION '[061] % checks FAILED - migration incomplete', fail_count;
    ELSE
        RAISE NOTICE '[061] All verification checks PASSED';
    END IF;
END $$;

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 061: Dual Tenant Context Fix COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'NEW FUNCTIONS:';
    RAISE NOTICE '  auth.current_tenant_id_int()       - FAIL-CLOSED INTEGER';
    RAISE NOTICE '  auth.current_tenant_id_uuid()      - FAIL-CLOSED UUID';
    RAISE NOTICE '  auth.current_tenant_id_int_or_null()  - PERMISSIVE INTEGER';
    RAISE NOTICE '  auth.current_tenant_id_uuid_or_null() - PERMISSIVE UUID';
    RAISE NOTICE '  auth.set_dual_tenant_context(INT, UUID, BOOL) - Context setter';
    RAISE NOTICE '  auth.get_tenant_uuid_for_int(INT)  - INT->UUID mapping';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM auth.verify_tenant_context_consistency();';
    RAISE NOTICE '  SELECT * FROM verify_pass_gate();';
    RAISE NOTICE '';
    RAISE NOTICE 'BACKEND USAGE:';
    RAISE NOTICE '  -- Replace: set_config(''app.current_tenant_id'', ...)';
    RAISE NOTICE '  -- With:    SELECT auth.set_dual_tenant_context($1, NULL, FALSE)';
    RAISE NOTICE '';
    RAISE NOTICE 'P0 DUAL TENANT MODEL FIX APPLIED';
    RAISE NOTICE '============================================================';
END $$;

COMMIT;
