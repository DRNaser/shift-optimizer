-- =============================================================================
-- Migration 018: Security Hardening Fixes
-- =============================================================================
-- Addresses blindspots identified in security review:
--   A) Signature cleanup automation + TTL optimization
--   D) Reason code validation in record_escalation
--   E) Worst-case severity aggregation functions
-- =============================================================================

BEGIN;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('018', 'Security hardening fixes')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- A) SIGNATURE CLEANUP OPTIMIZATION
-- =============================================================================

-- Add index for faster cleanup queries (non-partial, NOW() is not IMMUTABLE)
-- GREENFIELD FIX: Removed partial index predicate using NOW()
CREATE INDEX IF NOT EXISTS idx_core_used_signatures_cleanup
ON core.used_signatures(expires_at);

-- Batch cleanup function (more efficient for large tables)
CREATE OR REPLACE FUNCTION core.cleanup_expired_signatures_batch(
    p_batch_size INTEGER DEFAULT 1000
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted INTEGER := 0;
    v_batch INTEGER;
BEGIN
    LOOP
        DELETE FROM core.used_signatures
        WHERE signature IN (
            SELECT signature FROM core.used_signatures
            WHERE expires_at < NOW()
            LIMIT p_batch_size
        );
        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_deleted := v_deleted + v_batch;

        -- Exit when no more rows to delete
        EXIT WHEN v_batch < p_batch_size;

        -- Brief pause to avoid lock contention
        PERFORM pg_sleep(0.01);
    END LOOP;

    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION core.cleanup_expired_signatures_batch IS
    'Batch cleanup of expired signatures. Use for large tables to avoid long locks.';

-- Cleanup escalation counters as well
CREATE OR REPLACE FUNCTION core.cleanup_all_expired()
RETURNS TABLE(signatures_deleted INTEGER, counters_deleted INTEGER)
LANGUAGE plpgsql
AS $$
DECLARE
    v_sigs INTEGER;
    v_counters INTEGER;
BEGIN
    -- Cleanup signatures
    DELETE FROM core.used_signatures WHERE expires_at < NOW();
    GET DIAGNOSTICS v_sigs = ROW_COUNT;

    -- Cleanup counters
    DELETE FROM core.escalation_counters WHERE expires_at < NOW();
    GET DIAGNOSTICS v_counters = ROW_COUNT;

    RETURN QUERY SELECT v_sigs, v_counters;
END;
$$;

COMMENT ON FUNCTION core.cleanup_all_expired IS
    'Cleanup all expired signatures and counters. Call every 5 minutes.';

-- =============================================================================
-- D) REASON CODE VALIDATION IN RECORD_ESCALATION
-- =============================================================================

-- Replace record_escalation with validation
CREATE OR REPLACE FUNCTION core.record_escalation(
    p_scope_type core.scope_type,
    p_scope_id UUID,
    p_reason_code VARCHAR,
    p_details JSONB DEFAULT '{}'
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_registry_row core.reason_code_registry;
    v_status_id UUID;
BEGIN
    -- VALIDATION: Reason code MUST exist in registry
    SELECT * INTO v_registry_row
    FROM core.reason_code_registry
    WHERE reason_code = p_reason_code;

    IF NOT FOUND THEN
        -- STRICT: Reject unknown reason codes
        RAISE EXCEPTION 'Unknown reason_code: %. Register in core.reason_code_registry first.', p_reason_code
            USING ERRCODE = 'check_violation';
    END IF;

    -- Check for existing active escalation (prevent duplicates)
    SELECT id INTO v_status_id
    FROM core.service_status
    WHERE scope_type = p_scope_type
      AND (scope_id = p_scope_id OR (scope_id IS NULL AND p_scope_id IS NULL))
      AND reason_code = p_reason_code
      AND ended_at IS NULL;

    IF FOUND THEN
        -- Update existing instead of creating new
        UPDATE core.service_status
        SET details = p_details,
            updated_at = NOW()
        WHERE id = v_status_id;
        RETURN v_status_id;
    END IF;

    -- Insert new status record
    INSERT INTO core.service_status (
        scope_type, scope_id, status, severity,
        reason_code, reason_message,
        fix_steps, runbook_link, details
    ) VALUES (
        p_scope_type, p_scope_id,
        CASE
            WHEN v_registry_row.severity = 'S0' THEN 'blocked'::core.service_status_enum
            WHEN v_registry_row.severity = 'S1' THEN 'blocked'::core.service_status_enum
            WHEN v_registry_row.severity = 'S2' THEN 'degraded'::core.service_status_enum
            ELSE 'healthy'::core.service_status_enum
        END,
        v_registry_row.severity,
        p_reason_code,
        v_registry_row.description,
        v_registry_row.default_fix_steps,
        '/runbook/' || COALESCE(v_registry_row.runbook_section, 'unknown'),
        p_details
    )
    RETURNING id INTO v_status_id;

    RETURN v_status_id;
END;
$$;

COMMENT ON FUNCTION core.record_escalation IS
    'Record escalation with STRICT reason code validation. Rejects unknown codes.';

-- =============================================================================
-- E) WORST-CASE SEVERITY AGGREGATION
-- =============================================================================

-- Aggregation: Get worst severity for a scope (including child scopes)
CREATE OR REPLACE FUNCTION core.get_aggregated_status(
    p_scope_type core.scope_type,
    p_scope_id UUID DEFAULT NULL
)
RETURNS TABLE(
    overall_status core.service_status_enum,
    worst_severity core.severity_level,
    blocked_count BIGINT,
    degraded_count BIGINT,
    total_active BIGINT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
AS $$
DECLARE
    v_org_id UUID;
BEGIN
    IF p_scope_type = 'platform' THEN
        -- Platform: aggregate ALL active escalations
        RETURN QUERY
        SELECT
            CASE
                WHEN COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')) > 0 THEN 'blocked'::core.service_status_enum
                WHEN COUNT(*) FILTER (WHERE ss.severity = 'S2') > 0 THEN 'degraded'::core.service_status_enum
                ELSE 'healthy'::core.service_status_enum
            END,
            MIN(ss.severity)::core.severity_level,
            COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')),
            COUNT(*) FILTER (WHERE ss.severity = 'S2'),
            COUNT(*)
        FROM core.service_status ss
        WHERE ss.ended_at IS NULL;

    ELSIF p_scope_type = 'org' THEN
        -- Org: aggregate org scope + all tenant scopes in org
        RETURN QUERY
        SELECT
            CASE
                WHEN COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')) > 0 THEN 'blocked'::core.service_status_enum
                WHEN COUNT(*) FILTER (WHERE ss.severity = 'S2') > 0 THEN 'degraded'::core.service_status_enum
                ELSE 'healthy'::core.service_status_enum
            END,
            MIN(ss.severity)::core.severity_level,
            COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')),
            COUNT(*) FILTER (WHERE ss.severity = 'S2'),
            COUNT(*)
        FROM core.service_status ss
        WHERE ss.ended_at IS NULL
          AND (
              -- Platform-wide
              ss.scope_type = 'platform'
              -- Org-specific
              OR (ss.scope_type = 'org' AND ss.scope_id = p_scope_id)
              -- Tenants in this org
              OR (ss.scope_type = 'tenant' AND ss.scope_id IN (
                  SELECT id FROM core.tenants WHERE owner_org_id = p_scope_id
              ))
              -- Sites in tenants in this org
              OR (ss.scope_type = 'site' AND ss.scope_id IN (
                  SELECT s.id FROM core.sites s
                  JOIN core.tenants t ON s.tenant_id = t.id
                  WHERE t.owner_org_id = p_scope_id
              ))
          );

    ELSIF p_scope_type = 'tenant' THEN
        -- Tenant: aggregate platform + org + tenant + sites
        SELECT owner_org_id INTO v_org_id FROM core.tenants WHERE id = p_scope_id;

        RETURN QUERY
        SELECT
            CASE
                WHEN COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')) > 0 THEN 'blocked'::core.service_status_enum
                WHEN COUNT(*) FILTER (WHERE ss.severity = 'S2') > 0 THEN 'degraded'::core.service_status_enum
                ELSE 'healthy'::core.service_status_enum
            END,
            MIN(ss.severity)::core.severity_level,
            COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')),
            COUNT(*) FILTER (WHERE ss.severity = 'S2'),
            COUNT(*)
        FROM core.service_status ss
        WHERE ss.ended_at IS NULL
          AND (
              ss.scope_type = 'platform'
              OR (ss.scope_type = 'org' AND ss.scope_id = v_org_id)
              OR (ss.scope_type = 'tenant' AND ss.scope_id = p_scope_id)
              OR (ss.scope_type = 'site' AND ss.scope_id IN (
                  SELECT id FROM core.sites WHERE tenant_id = p_scope_id
              ))
          );

    ELSIF p_scope_type = 'site' THEN
        -- Site: aggregate platform + org + tenant + site
        RETURN QUERY
        SELECT
            CASE
                WHEN COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')) > 0 THEN 'blocked'::core.service_status_enum
                WHEN COUNT(*) FILTER (WHERE ss.severity = 'S2') > 0 THEN 'degraded'::core.service_status_enum
                ELSE 'healthy'::core.service_status_enum
            END,
            MIN(ss.severity)::core.severity_level,
            COUNT(*) FILTER (WHERE ss.severity IN ('S0', 'S1')),
            COUNT(*) FILTER (WHERE ss.severity = 'S2'),
            COUNT(*)
        FROM core.service_status ss
        WHERE ss.ended_at IS NULL
          AND (
              ss.scope_type = 'platform'
              OR ss.scope_id = p_scope_id
              OR ss.scope_id IN (
                  SELECT tenant_id FROM core.sites WHERE id = p_scope_id
              )
              OR ss.scope_id IN (
                  SELECT owner_org_id FROM core.tenants t
                  JOIN core.sites s ON s.tenant_id = t.id
                  WHERE s.id = p_scope_id
              )
          );
    END IF;
END;
$$;

COMMENT ON FUNCTION core.get_aggregated_status IS
    'Get aggregated status for scope including all parent/child scopes. Worst severity wins.';

-- =============================================================================
-- F) PLATFORM ADMIN CONTEXT GUARD
-- =============================================================================

-- Function to set platform admin context with validation
CREATE OR REPLACE FUNCTION core.set_platform_admin_context()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Set platform admin context
    PERFORM set_config('app.current_tenant_id', '', true);
    PERFORM set_config('app.current_site_id', '', true);
    PERFORM set_config('app.is_platform_admin', 'true', true);

    -- Log for audit trail (in security_events via trigger would be too expensive)
    -- Instead, this is logged at the API layer
END;
$$;

-- Guard function: assert platform admin only used with valid signature
-- This is called from API layer after signature verification
CREATE OR REPLACE FUNCTION core.assert_platform_admin_valid()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    -- Returns true if platform admin flag is set
    -- API layer must call this ONLY after signature verification
    SELECT core.app_is_platform_admin();
$$;

COMMENT ON FUNCTION core.set_platform_admin_context IS
    'Set platform admin context. ONLY call after signature verification in API layer.';

COMMIT;
