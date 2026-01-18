-- =============================================================================
-- Migration 062: RLS Policies Dual Context Rewrite
-- =============================================================================
-- PURPOSE:
--   Remove ALL direct current_setting() calls from RLS policies.
--   Replace with type-safe helper functions that:
--     1. Support dual-variable tenant context (app.current_tenant_id_int + app.current_tenant_id_uuid)
--     2. FAIL-CLOSED on missing context (no COALESCE to 0 or tenant_id)
--     3. Eliminate ::text casts that caused type confusion
--
-- ACCEPTANCE CRITERIA (must be 0 rows after migration):
--   SELECT * FROM pg_policies WHERE qual ILIKE '%current_setting(%' OR with_check ILIKE '%current_setting(%';
--   SELECT * FROM pg_policies WHERE qual ILIKE '%app.current_tenant_id%' OR with_check ILIKE '%app.current_tenant_id%';
--
-- =============================================================================

BEGIN;

-- Verify migration 061 helpers exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'current_tenant_id_int' AND pronamespace = 'auth'::regnamespace) THEN
        RAISE EXCEPTION 'Missing prerequisite: auth.current_tenant_id_int() - run migration 061 first';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'current_tenant_id_uuid' AND pronamespace = 'auth'::regnamespace) THEN
        RAISE EXCEPTION 'Missing prerequisite: auth.current_tenant_id_uuid() - run migration 061 first';
    END IF;
END;
$$;

-- =============================================================================
-- PHASE 1: Create missing helper functions
-- =============================================================================

-- is_super_admin(): Checks app.is_super_admin session variable
CREATE OR REPLACE FUNCTION auth.is_super_admin()
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_raw TEXT;
BEGIN
    v_raw := current_setting('app.is_super_admin', true);
    RETURN v_raw = 'true';
END;
$$;

COMMENT ON FUNCTION auth.is_super_admin() IS 'Returns TRUE if app.is_super_admin is set to "true", FALSE otherwise. Does NOT fail-closed.';

-- is_platform_admin(): Checks app.is_platform_admin session variable
CREATE OR REPLACE FUNCTION auth.is_platform_admin()
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_raw TEXT;
BEGIN
    v_raw := current_setting('app.is_platform_admin', true);
    RETURN v_raw = 'true';
END;
$$;

COMMENT ON FUNCTION auth.is_platform_admin() IS 'Returns TRUE if app.is_platform_admin is set to "true", FALSE otherwise. Does NOT fail-closed.';

-- current_user_id_uuid(): Gets current user ID as UUID (fail-closed)
CREATE OR REPLACE FUNCTION auth.current_user_id_uuid()
RETURNS UUID
LANGUAGE plpgsql
STABLE
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_raw TEXT;
    v_result UUID;
BEGIN
    v_raw := current_setting('app.current_user_id', true);

    IF v_raw IS NULL OR v_raw = '' THEN
        RAISE EXCEPTION 'RLS VIOLATION: app.current_user_id not set. User context required.'
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    BEGIN
        v_result := v_raw::UUID;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'RLS VIOLATION: app.current_user_id is not a valid UUID: "%"', v_raw
            USING ERRCODE = 'data_exception';
    END;

    RETURN v_result;
END;
$$;

COMMENT ON FUNCTION auth.current_user_id_uuid() IS 'Returns current user ID as UUID. FAIL-CLOSED: raises exception if not set.';

-- current_user_id_uuid_or_null(): Gets current user ID as UUID (returns NULL if not set)
CREATE OR REPLACE FUNCTION auth.current_user_id_uuid_or_null()
RETURNS UUID
LANGUAGE plpgsql
STABLE
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_raw TEXT;
BEGIN
    v_raw := current_setting('app.current_user_id', true);

    IF v_raw IS NULL OR v_raw = '' THEN
        RETURN NULL;
    END IF;

    BEGIN
        RETURN v_raw::UUID;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN NULL;
    END;
END;
$$;

COMMENT ON FUNCTION auth.current_user_id_uuid_or_null() IS 'Returns current user ID as UUID or NULL if not set/invalid.';

-- Grant execute on new functions
GRANT EXECUTE ON FUNCTION auth.is_super_admin() TO solvereign_api, solvereign_platform;
GRANT EXECUTE ON FUNCTION auth.is_platform_admin() TO solvereign_api, solvereign_platform;
GRANT EXECUTE ON FUNCTION auth.current_user_id_uuid() TO solvereign_api, solvereign_platform;
GRANT EXECUTE ON FUNCTION auth.current_user_id_uuid_or_null() TO solvereign_api, solvereign_platform;

-- =============================================================================
-- PHASE 2: Rewrite AUTH schema policies
-- =============================================================================

-- auth.approval_decisions (tenant_id: INTEGER)
DROP POLICY IF EXISTS decisions_tenant ON auth.approval_decisions;
CREATE POLICY decisions_tenant ON auth.approval_decisions FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- auth.approval_policies (tenant_id: INTEGER, allows NULL for global policies)
DROP POLICY IF EXISTS policies_access ON auth.approval_policies;
CREATE POLICY policies_access ON auth.approval_policies FOR ALL TO public
    USING (tenant_id IS NULL OR tenant_id = auth.current_tenant_id_int());

-- auth.approval_requests (tenant_id: INTEGER)
DROP POLICY IF EXISTS requests_tenant ON auth.approval_requests;
CREATE POLICY requests_tenant ON auth.approval_requests FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- auth.audit_log (tenant_id: INTEGER) - SELECT only for API role
DROP POLICY IF EXISTS audit_api_tenant ON auth.audit_log;
CREATE POLICY audit_api_tenant ON auth.audit_log FOR SELECT TO public
    USING (pg_has_role(SESSION_USER, 'solvereign_api', 'MEMBER')
           AND tenant_id = auth.current_tenant_id_int());

-- auth.emergency_review_queue (tenant_id: INTEGER)
DROP POLICY IF EXISTS emergency_tenant ON auth.emergency_review_queue;
CREATE POLICY emergency_tenant ON auth.emergency_review_queue FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- auth.legal_acceptances (user_id: UUID)
DROP POLICY IF EXISTS legal_acceptances_insert ON auth.legal_acceptances;
CREATE POLICY legal_acceptances_insert ON auth.legal_acceptances FOR INSERT TO solvereign_api
    WITH CHECK (user_id = auth.current_user_id_uuid());

DROP POLICY IF EXISTS legal_acceptances_select ON auth.legal_acceptances;
CREATE POLICY legal_acceptances_select ON auth.legal_acceptances FOR SELECT TO solvereign_api
    USING (user_id = auth.current_user_id_uuid());

-- auth.sessions (tenant_id: INTEGER) - API role only
DROP POLICY IF EXISTS sessions_api_tenant ON auth.sessions;
CREATE POLICY sessions_api_tenant ON auth.sessions FOR ALL TO public
    USING (pg_has_role(SESSION_USER, 'solvereign_api', 'MEMBER')
           AND tenant_id = auth.current_tenant_id_int());

-- auth.tenant_legal_acceptances (tenant_id: UUID)
DROP POLICY IF EXISTS tenant_legal_acceptances_select ON auth.tenant_legal_acceptances;
CREATE POLICY tenant_legal_acceptances_select ON auth.tenant_legal_acceptances FOR SELECT TO solvereign_api
    USING (tenant_id = auth.current_tenant_id_uuid());

-- auth.user_bindings (tenant_id: INTEGER) - API role only, SELECT
DROP POLICY IF EXISTS bindings_api_tenant ON auth.user_bindings;
CREATE POLICY bindings_api_tenant ON auth.user_bindings FOR SELECT TO public
    USING (pg_has_role(SESSION_USER, 'solvereign_api', 'MEMBER')
           AND tenant_id = auth.current_tenant_id_int());

-- =============================================================================
-- PHASE 3: Rewrite BILLING schema policies
-- =============================================================================

-- billing.invoices (tenant_id: INTEGER)
DROP POLICY IF EXISTS billing_invoices_tenant ON billing.invoices;
CREATE POLICY billing_invoices_tenant ON billing.invoices FOR SELECT TO solvereign_api
    USING (tenant_id = auth.current_tenant_id_int());

-- billing.stripe_customers (tenant_id: INTEGER)
DROP POLICY IF EXISTS billing_customers_tenant ON billing.stripe_customers;
CREATE POLICY billing_customers_tenant ON billing.stripe_customers FOR SELECT TO solvereign_api
    USING (tenant_id = auth.current_tenant_id_int());

-- billing.subscriptions (tenant_id: INTEGER)
DROP POLICY IF EXISTS billing_subscriptions_tenant ON billing.subscriptions;
CREATE POLICY billing_subscriptions_tenant ON billing.subscriptions FOR SELECT TO solvereign_api
    USING (tenant_id = auth.current_tenant_id_int());

-- =============================================================================
-- PHASE 4: Rewrite CONSENT schema policies
-- =============================================================================

-- consent.driver_consents (tenant_id: UUID)
DROP POLICY IF EXISTS driver_consents_tenant ON consent.driver_consents;
CREATE POLICY driver_consents_tenant ON consent.driver_consents FOR ALL TO solvereign_api
    USING (tenant_id = auth.current_tenant_id_uuid())
    WITH CHECK (tenant_id = auth.current_tenant_id_uuid());

-- consent.user_consents (user_id: UUID)
DROP POLICY IF EXISTS user_consents_own ON consent.user_consents;
CREATE POLICY user_consents_own ON consent.user_consents FOR ALL TO solvereign_api
    USING (user_id = auth.current_user_id_uuid())
    WITH CHECK (user_id = auth.current_user_id_uuid());

-- =============================================================================
-- PHASE 5: Rewrite CORE schema policies
-- =============================================================================

-- core.policy_profiles (tenant_id: UUID, platform admin bypass)
DROP POLICY IF EXISTS policy_profiles_tenant_isolation ON core.policy_profiles;
CREATE POLICY policy_profiles_tenant_isolation ON core.policy_profiles FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid() OR auth.is_platform_admin());

-- core.tenant_pack_settings (tenant_id: UUID, platform admin bypass)
DROP POLICY IF EXISTS tenant_pack_settings_isolation ON core.tenant_pack_settings;
CREATE POLICY tenant_pack_settings_isolation ON core.tenant_pack_settings FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid() OR auth.is_platform_admin());

-- =============================================================================
-- PHASE 6: Rewrite DISPATCH schema policies
-- =============================================================================

-- dispatch.dispatch_apply_audit (tenant_id: INTEGER)
DROP POLICY IF EXISTS dispatch_apply_audit_tenant_isolation ON dispatch.dispatch_apply_audit;
CREATE POLICY dispatch_apply_audit_tenant_isolation ON dispatch.dispatch_apply_audit FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- dispatch.dispatch_open_shifts (tenant_id: INTEGER)
DROP POLICY IF EXISTS dispatch_open_shifts_tenant_isolation ON dispatch.dispatch_open_shifts;
CREATE POLICY dispatch_open_shifts_tenant_isolation ON dispatch.dispatch_open_shifts FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- dispatch.dispatch_proposals (tenant_id: INTEGER)
DROP POLICY IF EXISTS dispatch_proposals_tenant_isolation ON dispatch.dispatch_proposals;
CREATE POLICY dispatch_proposals_tenant_isolation ON dispatch.dispatch_proposals FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- =============================================================================
-- PHASE 7: Rewrite MASTERDATA schema policies
-- =============================================================================

-- masterdata.driver_contacts (tenant_id: INTEGER)
DROP POLICY IF EXISTS driver_contacts_tenant_isolation ON masterdata.driver_contacts;
CREATE POLICY driver_contacts_tenant_isolation ON masterdata.driver_contacts FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- masterdata.md_external_mappings (tenant_id: INTEGER)
DROP POLICY IF EXISTS md_external_mappings_tenant_isolation ON masterdata.md_external_mappings;
CREATE POLICY md_external_mappings_tenant_isolation ON masterdata.md_external_mappings FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- masterdata.md_locations (tenant_id: INTEGER)
DROP POLICY IF EXISTS md_locations_tenant_isolation ON masterdata.md_locations;
CREATE POLICY md_locations_tenant_isolation ON masterdata.md_locations FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- masterdata.md_sites (tenant_id: INTEGER)
DROP POLICY IF EXISTS md_sites_tenant_isolation ON masterdata.md_sites;
CREATE POLICY md_sites_tenant_isolation ON masterdata.md_sites FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- masterdata.md_vehicles (tenant_id: INTEGER)
DROP POLICY IF EXISTS md_vehicles_tenant_isolation ON masterdata.md_vehicles;
CREATE POLICY md_vehicles_tenant_isolation ON masterdata.md_vehicles FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int())
    WITH CHECK (tenant_id = auth.current_tenant_id_int());

-- =============================================================================
-- PHASE 8: Rewrite NOTIFY schema policies
-- =============================================================================

-- notify.driver_preferences (tenant_id: INTEGER)
DROP POLICY IF EXISTS tenant_isolation_preferences ON notify.driver_preferences;
CREATE POLICY tenant_isolation_preferences ON notify.driver_preferences FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- notify.notification_archive (tenant_id: INTEGER, platform bypass via role check)
DROP POLICY IF EXISTS notification_archive_tenant_isolation ON notify.notification_archive;
CREATE POLICY notification_archive_tenant_isolation ON notify.notification_archive FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int()
           OR pg_has_role(SESSION_USER, 'solvereign_platform', 'MEMBER'));

-- notify.notification_delivery_log (tenant_id: INTEGER)
DROP POLICY IF EXISTS tenant_isolation_delivery_log ON notify.notification_delivery_log;
CREATE POLICY tenant_isolation_delivery_log ON notify.notification_delivery_log FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- notify.notification_jobs (tenant_id: INTEGER)
DROP POLICY IF EXISTS tenant_isolation_jobs ON notify.notification_jobs;
CREATE POLICY tenant_isolation_jobs ON notify.notification_jobs FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- notify.notification_outbox (tenant_id: INTEGER)
DROP POLICY IF EXISTS tenant_isolation_outbox ON notify.notification_outbox;
CREATE POLICY tenant_isolation_outbox ON notify.notification_outbox FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- notify.notification_templates (tenant_id: INTEGER, NULL means global template)
DROP POLICY IF EXISTS template_access ON notify.notification_templates;
CREATE POLICY template_access ON notify.notification_templates FOR ALL TO public
    USING (tenant_id IS NULL OR tenant_id = auth.current_tenant_id_int());

-- notify.rate_limit_buckets (tenant_id: INTEGER)
DROP POLICY IF EXISTS tenant_isolation_rate_limit ON notify.rate_limit_buckets;
CREATE POLICY tenant_isolation_rate_limit ON notify.rate_limit_buckets FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- notify.webhook_events (tenant_id: INTEGER)
DROP POLICY IF EXISTS tenant_isolation_webhook ON notify.webhook_events;
CREATE POLICY tenant_isolation_webhook ON notify.webhook_events FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- =============================================================================
-- PHASE 9: Rewrite PORTAL schema policies
-- =============================================================================

-- portal.driver_ack (tenant_id: INTEGER)
DROP POLICY IF EXISTS driver_ack_tenant_isolation ON portal.driver_ack;
CREATE POLICY driver_ack_tenant_isolation ON portal.driver_ack FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- portal.driver_views (tenant_id: INTEGER)
DROP POLICY IF EXISTS driver_views_tenant_isolation ON portal.driver_views;
CREATE POLICY driver_views_tenant_isolation ON portal.driver_views FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- portal.portal_audit (tenant_id: INTEGER)
DROP POLICY IF EXISTS portal_audit_tenant_isolation ON portal.portal_audit;
CREATE POLICY portal_audit_tenant_isolation ON portal.portal_audit FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- portal.portal_tokens (tenant_id: INTEGER)
DROP POLICY IF EXISTS portal_tokens_tenant_isolation ON portal.portal_tokens;
CREATE POLICY portal_tokens_tenant_isolation ON portal.portal_tokens FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- portal.read_receipts (tenant_id: INTEGER)
DROP POLICY IF EXISTS read_receipts_tenant_isolation ON portal.read_receipts;
CREATE POLICY read_receipts_tenant_isolation ON portal.read_receipts FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- portal.snapshot_supersedes (tenant_id: INTEGER)
DROP POLICY IF EXISTS snapshot_supersedes_tenant_isolation ON portal.snapshot_supersedes;
CREATE POLICY snapshot_supersedes_tenant_isolation ON portal.snapshot_supersedes FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- =============================================================================
-- PHASE 10: Rewrite PUBLIC schema policies
-- =============================================================================

-- public.assignments (tenant via plan_versions FK) - Rewrite subquery
DROP POLICY IF EXISTS tenant_isolation_assignments ON public.assignments;
CREATE POLICY tenant_isolation_assignments ON public.assignments FOR ALL TO public
    USING (EXISTS (
        SELECT 1 FROM plan_versions pv
        WHERE pv.id = assignments.plan_version_id
          AND (pv.tenant_id = auth.current_tenant_id_int() OR auth.is_super_admin())
    ));

-- public.audit_log (tenant_id: INTEGER, super admin bypass)
DROP POLICY IF EXISTS tenant_isolation_audit_log ON public.audit_log;
CREATE POLICY tenant_isolation_audit_log ON public.audit_log FOR SELECT TO public
    USING (tenant_id = auth.current_tenant_id_int() OR auth.is_super_admin());

-- public.driver_availability (tenant_id: UUID, super admin bypass)
DROP POLICY IF EXISTS tenant_isolation_driver_availability ON public.driver_availability;
CREATE POLICY tenant_isolation_driver_availability ON public.driver_availability FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid() OR auth.is_super_admin());

-- public.driver_skills (tenant_id: UUID, super admin bypass)
DROP POLICY IF EXISTS tenant_isolation_driver_skills ON public.driver_skills;
CREATE POLICY tenant_isolation_driver_skills ON public.driver_skills FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid() OR auth.is_super_admin());

-- public.drivers (tenant_id: UUID, super admin bypass)
DROP POLICY IF EXISTS tenant_isolation_drivers ON public.drivers;
CREATE POLICY tenant_isolation_drivers ON public.drivers FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid() OR auth.is_super_admin());

-- public.forecast_versions (tenant_id: INTEGER, super admin bypass)
DROP POLICY IF EXISTS tenant_isolation_forecast ON public.forecast_versions;
CREATE POLICY tenant_isolation_forecast ON public.forecast_versions FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int() OR auth.is_super_admin());

-- public.idempotency_keys (tenant_id: INTEGER, platform bypass)
DROP POLICY IF EXISTS idempotency_keys_tenant_or_platform ON public.idempotency_keys;
CREATE POLICY idempotency_keys_tenant_or_platform ON public.idempotency_keys FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int()
           OR pg_has_role(CURRENT_USER, 'solvereign_platform', 'MEMBER'))
    WITH CHECK (tenant_id = auth.current_tenant_id_int()
                OR pg_has_role(CURRENT_USER, 'solvereign_platform', 'MEMBER'));

-- public.import_runs (tenant_id: UUID)
DROP POLICY IF EXISTS import_runs_tenant_isolation ON public.import_runs;
CREATE POLICY import_runs_tenant_isolation ON public.import_runs FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid());

-- public.plan_approvals (tenant_id: UUID)
DROP POLICY IF EXISTS plan_approvals_tenant_isolation ON public.plan_approvals;
CREATE POLICY plan_approvals_tenant_isolation ON public.plan_approvals FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid());

-- public.plan_snapshots (tenant_id: UUID)
DROP POLICY IF EXISTS plan_snapshots_tenant_isolation ON public.plan_snapshots;
CREATE POLICY plan_snapshots_tenant_isolation ON public.plan_snapshots FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid());

-- public.plan_versions (tenant_id: INTEGER, super admin bypass)
DROP POLICY IF EXISTS tenant_isolation_plan ON public.plan_versions;
CREATE POLICY tenant_isolation_plan ON public.plan_versions FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int() OR auth.is_super_admin());

-- public.repair_log (tenant_id: UUID, super admin bypass)
DROP POLICY IF EXISTS tenant_isolation_repair_log ON public.repair_log;
CREATE POLICY tenant_isolation_repair_log ON public.repair_log FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid() OR auth.is_super_admin());

-- public.routing_evidence (tenant_id: UUID)
DROP POLICY IF EXISTS routing_evidence_tenant_isolation ON public.routing_evidence;
CREATE POLICY routing_evidence_tenant_isolation ON public.routing_evidence FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid());

-- public.security_audit_log (tenant_id: UUID, super admin bypass)
DROP POLICY IF EXISTS security_audit_read_policy ON public.security_audit_log;
CREATE POLICY security_audit_read_policy ON public.security_audit_log FOR SELECT TO public
    USING (tenant_id = auth.current_tenant_id_uuid() OR auth.is_super_admin());

-- public.solver_runs (tenant_id: UUID)
DROP POLICY IF EXISTS solver_runs_tenant_isolation ON public.solver_runs;
CREATE POLICY solver_runs_tenant_isolation ON public.solver_runs FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_uuid());

-- public.tenant_identities (super admin only - no tenant context needed)
DROP POLICY IF EXISTS tenant_identities_super_admin ON public.tenant_identities;
CREATE POLICY tenant_identities_super_admin ON public.tenant_identities FOR ALL TO public
    USING (auth.is_super_admin());

-- public.tour_instances (tenant via forecast_versions FK)
DROP POLICY IF EXISTS tenant_isolation_tour_instances ON public.tour_instances;
CREATE POLICY tenant_isolation_tour_instances ON public.tour_instances FOR ALL TO public
    USING (EXISTS (
        SELECT 1 FROM forecast_versions fv
        WHERE fv.id = tour_instances.forecast_version_id
          AND (fv.tenant_id = auth.current_tenant_id_int() OR auth.is_super_admin())
    ));

-- public.tours_normalized (tenant via forecast_versions FK)
DROP POLICY IF EXISTS tenant_isolation_tours_normalized ON public.tours_normalized;
CREATE POLICY tenant_isolation_tours_normalized ON public.tours_normalized FOR ALL TO public
    USING (EXISTS (
        SELECT 1 FROM forecast_versions fv
        WHERE fv.id = tours_normalized.forecast_version_id
          AND (fv.tenant_id = auth.current_tenant_id_int() OR auth.is_super_admin())
    ));

-- public.tours_raw (tenant via forecast_versions FK)
DROP POLICY IF EXISTS tenant_isolation_tours_raw ON public.tours_raw;
CREATE POLICY tenant_isolation_tours_raw ON public.tours_raw FOR ALL TO public
    USING (EXISTS (
        SELECT 1 FROM forecast_versions fv
        WHERE fv.id = tours_raw.forecast_version_id
          AND (fv.tenant_id = auth.current_tenant_id_int() OR auth.is_super_admin())
    ));

-- =============================================================================
-- PHASE 11: Rewrite ROSTER schema policies
-- =============================================================================

-- roster.audit_notes (tenant_id: INTEGER)
DROP POLICY IF EXISTS audit_notes_tenant_isolation ON roster.audit_notes;
CREATE POLICY audit_notes_tenant_isolation ON roster.audit_notes FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- roster.pins (tenant_id: INTEGER)
DROP POLICY IF EXISTS pins_tenant_isolation ON roster.pins;
CREATE POLICY pins_tenant_isolation ON roster.pins FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- roster.repair_actions (tenant_id: INTEGER)
DROP POLICY IF EXISTS repair_actions_tenant_isolation ON roster.repair_actions;
CREATE POLICY repair_actions_tenant_isolation ON roster.repair_actions FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- roster.repairs (tenant_id: INTEGER)
DROP POLICY IF EXISTS repairs_tenant_isolation ON roster.repairs;
CREATE POLICY repairs_tenant_isolation ON roster.repairs FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- roster.violations_cache (tenant_id: INTEGER)
DROP POLICY IF EXISTS violations_cache_tenant_isolation ON roster.violations_cache;
CREATE POLICY violations_cache_tenant_isolation ON roster.violations_cache FOR ALL TO public
    USING (tenant_id = auth.current_tenant_id_int());

-- =============================================================================
-- PHASE 12: Verification
-- =============================================================================

-- Verify no policies use current_setting directly
DO $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM pg_policies
    WHERE qual ILIKE '%current_setting(%' OR with_check ILIKE '%current_setting(%';

    IF v_count > 0 THEN
        RAISE EXCEPTION 'MIGRATION FAILED: % policies still use current_setting directly', v_count;
    END IF;

    RAISE NOTICE '[062] SUCCESS: All policies rewritten to use helper functions';
END;
$$;

-- =============================================================================
-- Record migration
-- =============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('062', 'RLS policies dual context rewrite - no current_setting in policies', NOW())
ON CONFLICT (version) DO UPDATE SET applied_at = NOW();

COMMIT;
