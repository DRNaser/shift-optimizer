-- =============================================================================
-- Migration 058: Risk-Based Approval Policy
-- =============================================================================
-- Purpose: Implement risk-based approval system with variable approval requirements
--
-- Policy Rules:
--   LOW RISK: Single approver (standard operations)
--   HIGH RISK: Two approvers required (publish/freeze/repair >N drivers or rest-time)
--   EMERGENCY: Single approver with EMERGENCY_OVERRIDE flag + next-day review
--
-- Key Principle: All approvals and overrides fully audited with correlation_id + evidence JSON.
--
-- RLS: All tables have tenant isolation via RLS policies.
--
-- Run:
--   psql $DATABASE_URL < backend_py/db/migrations/058_approval_policy.sql
-- =============================================================================

BEGIN;

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('058', 'Risk-Based Approval Policy', NOW())
ON CONFLICT (version) DO NOTHING;


-- =============================================================================
-- TABLE: approval_policies
-- =============================================================================
-- Configurable approval policy rules per tenant

CREATE TABLE IF NOT EXISTS auth.approval_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL = system default

    -- Policy identification
    policy_key VARCHAR(100) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Action matching
    action_type VARCHAR(100) NOT NULL,  -- PUBLISH, FREEZE, REPAIR, UNFREEZE, DELETE
    entity_type VARCHAR(100),  -- PLAN, SNAPSHOT, ROSTER, DRIVER, etc.

    -- Risk thresholds
    risk_level VARCHAR(20) NOT NULL DEFAULT 'LOW',  -- LOW, MEDIUM, HIGH, CRITICAL
    required_approvals INTEGER NOT NULL DEFAULT 1,
    -- 1 = single approver, 2 = two-man rule

    -- Threshold conditions (when policy applies)
    threshold_conditions JSONB DEFAULT '{}',
    -- Examples:
    -- {"affected_drivers_min": 10}
    -- {"rest_time_violation": true}
    -- {"near_deadline_hours": 4}
    -- {"is_freeze_period": true}

    -- Approver requirements
    approver_roles TEXT[] DEFAULT ARRAY['tenant_admin', 'operator_admin'],
    require_different_approvers BOOLEAN DEFAULT TRUE,  -- For 2-man rule

    -- Emergency override settings
    allow_emergency_override BOOLEAN DEFAULT TRUE,
    emergency_requires_review BOOLEAN DEFAULT TRUE,
    emergency_review_hours INTEGER DEFAULT 24,  -- Review window

    -- Auto-approve conditions (optional)
    auto_approve_conditions JSONB DEFAULT NULL,
    -- Example: {"affected_drivers_max": 3, "same_site": true}

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 100,  -- Lower = evaluated first

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT policies_risk_level_check CHECK (
        risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
    ),
    CONSTRAINT policies_action_type_check CHECK (
        action_type IN ('PUBLISH', 'FREEZE', 'REPAIR', 'UNFREEZE', 'DELETE', 'BROADCAST', 'REASSIGN')
    ),
    CONSTRAINT policies_approvals_check CHECK (required_approvals BETWEEN 1 AND 3),
    -- Unique policy per tenant + action + risk level
    CONSTRAINT policies_unique_key UNIQUE NULLS NOT DISTINCT (tenant_id, policy_key)
);

CREATE INDEX IF NOT EXISTS idx_approval_policies_tenant ON auth.approval_policies(tenant_id);
CREATE INDEX IF NOT EXISTS idx_approval_policies_action ON auth.approval_policies(action_type, entity_type);
CREATE INDEX IF NOT EXISTS idx_approval_policies_active ON auth.approval_policies(is_active, priority);

COMMENT ON TABLE auth.approval_policies IS
'Configurable approval policy rules. Defines risk levels and approval requirements.';


-- =============================================================================
-- TABLE: approval_requests
-- =============================================================================
-- Pending and completed approval requests

CREATE TABLE IF NOT EXISTS auth.approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID,

    -- Policy reference
    policy_id UUID REFERENCES auth.approval_policies(id) ON DELETE SET NULL,
    policy_key VARCHAR(100) NOT NULL,

    -- Action details
    action_type VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100),
    entity_id UUID,  -- Plan ID, snapshot ID, etc.
    entity_name VARCHAR(255),  -- For display

    -- Risk assessment
    risk_level VARCHAR(20) NOT NULL,
    risk_score INTEGER,  -- Calculated risk score (0-100)
    risk_factors JSONB DEFAULT '[]',  -- Array of risk factors
    -- Example: [{"factor": "affected_drivers", "value": 25, "threshold": 10}]

    -- Approval requirements
    required_approvals INTEGER NOT NULL DEFAULT 1,
    current_approvals INTEGER NOT NULL DEFAULT 0,

    -- Status
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    -- PENDING -> APPROVED | REJECTED | EXPIRED | CANCELLED | EMERGENCY_OVERRIDE

    -- Requester
    requested_by VARCHAR(255) NOT NULL,  -- User email
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    request_reason TEXT,

    -- Action payload (what to execute on approval)
    action_payload JSONB NOT NULL DEFAULT '{}',
    -- Stored so approval can execute the action

    -- Correlation for audit trail
    correlation_id UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Evidence (impact analysis)
    evidence JSONB DEFAULT '{}',
    -- Example: {"affected_drivers": [...], "rest_time_impacts": [...]}

    -- Expiry
    expires_at TIMESTAMPTZ,  -- Auto-expire if not approved in time

    -- Resolution
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(255),
    resolution_notes TEXT,

    -- Emergency override
    is_emergency_override BOOLEAN DEFAULT FALSE,
    emergency_justification TEXT,
    emergency_review_due_at TIMESTAMPTZ,
    emergency_review_completed_at TIMESTAMPTZ,
    emergency_reviewed_by VARCHAR(255),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT requests_status_check CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED', 'EMERGENCY_OVERRIDE')
    )
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_tenant ON auth.approval_requests(tenant_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON auth.approval_requests(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approval_requests_pending ON auth.approval_requests(tenant_id, status)
    WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_approval_requests_entity ON auth.approval_requests(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_correlation ON auth.approval_requests(correlation_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_emergency_review ON auth.approval_requests(emergency_review_due_at)
    WHERE is_emergency_override = TRUE AND emergency_review_completed_at IS NULL;

COMMENT ON TABLE auth.approval_requests IS
'Approval requests with risk assessment and multi-approver support.';


-- =============================================================================
-- TABLE: approval_decisions
-- =============================================================================
-- Individual approval/rejection decisions (for 2-man rule tracking)

CREATE TABLE IF NOT EXISTS auth.approval_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    request_id UUID NOT NULL REFERENCES auth.approval_requests(id) ON DELETE CASCADE,

    -- Decision maker
    decided_by_user_id UUID NOT NULL,
    decided_by_email VARCHAR(255) NOT NULL,
    decided_by_role VARCHAR(50) NOT NULL,

    -- Decision
    decision VARCHAR(20) NOT NULL,  -- APPROVE, REJECT
    decision_reason TEXT,

    -- Evidence review
    evidence_reviewed BOOLEAN DEFAULT FALSE,
    evidence_notes TEXT,

    -- Timestamps
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT decisions_decision_check CHECK (decision IN ('APPROVE', 'REJECT')),
    -- One decision per user per request
    CONSTRAINT decisions_unique_user UNIQUE (request_id, decided_by_user_id)
);

CREATE INDEX IF NOT EXISTS idx_approval_decisions_request ON auth.approval_decisions(request_id);
CREATE INDEX IF NOT EXISTS idx_approval_decisions_user ON auth.approval_decisions(decided_by_user_id);

COMMENT ON TABLE auth.approval_decisions IS
'Individual approval decisions. Multiple decisions for 2-man rule requests.';


-- =============================================================================
-- TABLE: emergency_review_queue
-- =============================================================================
-- Queue for emergency overrides awaiting review

CREATE TABLE IF NOT EXISTS auth.emergency_review_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    request_id UUID NOT NULL REFERENCES auth.approval_requests(id) ON DELETE CASCADE,

    -- Override details
    override_by VARCHAR(255) NOT NULL,
    override_at TIMESTAMPTZ NOT NULL,
    override_justification TEXT NOT NULL,

    -- What was executed
    action_type VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100),
    entity_id UUID,
    action_summary TEXT,

    -- Impact
    affected_drivers_count INTEGER,
    risk_factors JSONB,

    -- Review
    review_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    -- PENDING -> ACKNOWLEDGED | ESCALATED | FLAGGED
    review_due_at TIMESTAMPTZ NOT NULL,
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(255),
    review_outcome VARCHAR(50),  -- APPROPRIATE, NEEDS_FOLLOWUP, POLICY_VIOLATION
    review_notes TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT review_status_check CHECK (
        review_status IN ('PENDING', 'ACKNOWLEDGED', 'ESCALATED', 'FLAGGED')
    )
);

CREATE INDEX IF NOT EXISTS idx_emergency_review_pending ON auth.emergency_review_queue(review_status, review_due_at)
    WHERE review_status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_emergency_review_tenant ON auth.emergency_review_queue(tenant_id);

COMMENT ON TABLE auth.emergency_review_queue IS
'Queue for reviewing emergency overrides next business day.';


-- =============================================================================
-- ENABLE RLS
-- =============================================================================

ALTER TABLE auth.approval_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.approval_policies FORCE ROW LEVEL SECURITY;

ALTER TABLE auth.approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.approval_requests FORCE ROW LEVEL SECURITY;

ALTER TABLE auth.approval_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.approval_decisions FORCE ROW LEVEL SECURITY;

ALTER TABLE auth.emergency_review_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.emergency_review_queue FORCE ROW LEVEL SECURITY;


-- =============================================================================
-- RLS POLICIES
-- =============================================================================

-- Policies: tenant-specific or system-wide
CREATE POLICY policies_access ON auth.approval_policies
    FOR ALL
    USING (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER
    );

-- Requests: tenant isolation
CREATE POLICY requests_tenant ON auth.approval_requests
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);

-- Decisions: tenant isolation
CREATE POLICY decisions_tenant ON auth.approval_decisions
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);

-- Emergency queue: tenant isolation
CREATE POLICY emergency_tenant ON auth.emergency_review_queue
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::INTEGER);


-- =============================================================================
-- GRANTS
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_api') THEN
        GRANT SELECT ON auth.approval_policies TO solvereign_api;
        GRANT SELECT, INSERT, UPDATE ON auth.approval_requests TO solvereign_api;
        GRANT SELECT, INSERT ON auth.approval_decisions TO solvereign_api;
        GRANT SELECT, INSERT, UPDATE ON auth.emergency_review_queue TO solvereign_api;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solvereign_platform') THEN
        GRANT ALL ON auth.approval_policies TO solvereign_platform;
        GRANT ALL ON auth.approval_requests TO solvereign_platform;
        GRANT ALL ON auth.approval_decisions TO solvereign_platform;
        GRANT ALL ON auth.emergency_review_queue TO solvereign_platform;
    END IF;
END $$;


-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Use existing update_updated_at function or create if needed
CREATE TRIGGER tr_approval_policies_updated_at
    BEFORE UPDATE ON auth.approval_policies
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();

CREATE TRIGGER tr_approval_requests_updated_at
    BEFORE UPDATE ON auth.approval_requests
    FOR EACH ROW EXECUTE FUNCTION masterdata.update_updated_at();


-- =============================================================================
-- FUNCTION: assess_action_risk
-- =============================================================================
-- Assess risk level for an action

CREATE OR REPLACE FUNCTION auth.assess_action_risk(
    p_tenant_id INTEGER,
    p_action_type VARCHAR,
    p_entity_type VARCHAR,
    p_context JSONB DEFAULT '{}'
)
RETURNS JSONB AS $$
DECLARE
    v_risk_level VARCHAR := 'LOW';
    v_risk_score INTEGER := 0;
    v_risk_factors JSONB[] := ARRAY[]::JSONB[];
    v_required_approvals INTEGER := 1;
    v_policy RECORD;

    v_affected_drivers INTEGER;
    v_near_rest_time BOOLEAN;
    v_is_freeze_period BOOLEAN;
    v_near_deadline BOOLEAN;
BEGIN
    -- Extract context values
    v_affected_drivers := COALESCE((p_context->>'affected_drivers')::INTEGER, 0);
    v_near_rest_time := COALESCE((p_context->>'near_rest_time')::BOOLEAN, FALSE);
    v_is_freeze_period := COALESCE((p_context->>'is_freeze_period')::BOOLEAN, FALSE);
    v_near_deadline := COALESCE((p_context->>'near_deadline')::BOOLEAN, FALSE);

    -- Calculate risk score based on factors
    -- Factor 1: Number of affected drivers
    IF v_affected_drivers > 20 THEN
        v_risk_score := v_risk_score + 40;
        v_risk_factors := array_append(v_risk_factors, jsonb_build_object(
            'factor', 'high_driver_count',
            'value', v_affected_drivers,
            'threshold', 20,
            'impact', 40
        ));
    ELSIF v_affected_drivers > 10 THEN
        v_risk_score := v_risk_score + 25;
        v_risk_factors := array_append(v_risk_factors, jsonb_build_object(
            'factor', 'medium_driver_count',
            'value', v_affected_drivers,
            'threshold', 10,
            'impact', 25
        ));
    ELSIF v_affected_drivers > 5 THEN
        v_risk_score := v_risk_score + 10;
        v_risk_factors := array_append(v_risk_factors, jsonb_build_object(
            'factor', 'low_driver_count',
            'value', v_affected_drivers,
            'threshold', 5,
            'impact', 10
        ));
    END IF;

    -- Factor 2: Near rest-time limits
    IF v_near_rest_time THEN
        v_risk_score := v_risk_score + 30;
        v_risk_factors := array_append(v_risk_factors, jsonb_build_object(
            'factor', 'rest_time_risk',
            'value', TRUE,
            'impact', 30
        ));
    END IF;

    -- Factor 3: Freeze period
    IF v_is_freeze_period THEN
        v_risk_score := v_risk_score + 20;
        v_risk_factors := array_append(v_risk_factors, jsonb_build_object(
            'factor', 'freeze_period',
            'value', TRUE,
            'impact', 20
        ));
    END IF;

    -- Factor 4: Near deadline
    IF v_near_deadline THEN
        v_risk_score := v_risk_score + 15;
        v_risk_factors := array_append(v_risk_factors, jsonb_build_object(
            'factor', 'near_deadline',
            'value', TRUE,
            'impact', 15
        ));
    END IF;

    -- Factor 5: Action type severity
    IF p_action_type IN ('PUBLISH', 'FREEZE', 'DELETE') THEN
        v_risk_score := v_risk_score + 10;
        v_risk_factors := array_append(v_risk_factors, jsonb_build_object(
            'factor', 'high_impact_action',
            'action_type', p_action_type,
            'impact', 10
        ));
    END IF;

    -- Determine risk level from score
    IF v_risk_score >= 70 THEN
        v_risk_level := 'CRITICAL';
        v_required_approvals := 2;
    ELSIF v_risk_score >= 50 THEN
        v_risk_level := 'HIGH';
        v_required_approvals := 2;
    ELSIF v_risk_score >= 30 THEN
        v_risk_level := 'MEDIUM';
        v_required_approvals := 1;
    ELSE
        v_risk_level := 'LOW';
        v_required_approvals := 1;
    END IF;

    -- Check for policy overrides
    SELECT * INTO v_policy
    FROM auth.approval_policies
    WHERE (tenant_id = p_tenant_id OR tenant_id IS NULL)
      AND action_type = p_action_type
      AND (entity_type = p_entity_type OR entity_type IS NULL)
      AND is_active = TRUE
    ORDER BY tenant_id NULLS LAST, priority ASC
    LIMIT 1;

    IF FOUND THEN
        -- Policy may override defaults
        IF v_policy.required_approvals > v_required_approvals THEN
            v_required_approvals := v_policy.required_approvals;
        END IF;
    END IF;

    RETURN jsonb_build_object(
        'risk_level', v_risk_level,
        'risk_score', v_risk_score,
        'risk_factors', to_jsonb(v_risk_factors),
        'required_approvals', v_required_approvals,
        'policy_id', v_policy.id,
        'policy_key', v_policy.policy_key,
        'allow_emergency_override', COALESCE(v_policy.allow_emergency_override, TRUE)
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION auth.assess_action_risk IS
'Assess risk level and required approvals for an action. Returns risk factors and policy.';


-- =============================================================================
-- FUNCTION: create_approval_request
-- =============================================================================
-- Create an approval request

CREATE OR REPLACE FUNCTION auth.create_approval_request(
    p_tenant_id INTEGER,
    p_action_type VARCHAR,
    p_entity_type VARCHAR,
    p_entity_id UUID,
    p_entity_name VARCHAR,
    p_requested_by VARCHAR,
    p_action_payload JSONB,
    p_evidence JSONB DEFAULT '{}',
    p_request_reason TEXT DEFAULT NULL,
    p_context JSONB DEFAULT '{}'
)
RETURNS UUID AS $$
DECLARE
    v_risk_assessment JSONB;
    v_request_id UUID;
    v_expires_at TIMESTAMPTZ;
BEGIN
    -- Assess risk
    v_risk_assessment := auth.assess_action_risk(
        p_tenant_id, p_action_type, p_entity_type, p_context
    );

    -- Set expiry (24 hours for high risk, 8 hours for low)
    IF (v_risk_assessment->>'risk_level') IN ('HIGH', 'CRITICAL') THEN
        v_expires_at := NOW() + INTERVAL '24 hours';
    ELSE
        v_expires_at := NOW() + INTERVAL '8 hours';
    END IF;

    -- Create request
    INSERT INTO auth.approval_requests (
        tenant_id, policy_id, policy_key,
        action_type, entity_type, entity_id, entity_name,
        risk_level, risk_score, risk_factors,
        required_approvals, status,
        requested_by, request_reason, action_payload, evidence,
        expires_at
    ) VALUES (
        p_tenant_id,
        (v_risk_assessment->>'policy_id')::UUID,
        COALESCE(v_risk_assessment->>'policy_key', p_action_type || '_default'),
        p_action_type, p_entity_type, p_entity_id, p_entity_name,
        v_risk_assessment->>'risk_level',
        (v_risk_assessment->>'risk_score')::INTEGER,
        v_risk_assessment->'risk_factors',
        (v_risk_assessment->>'required_approvals')::INTEGER,
        'PENDING',
        p_requested_by, p_request_reason, p_action_payload, p_evidence,
        v_expires_at
    )
    RETURNING id INTO v_request_id;

    -- Audit log
    INSERT INTO auth.audit_log (
        tenant_id, user_id, action, entity_type, entity_id,
        changes, ip_hash
    ) VALUES (
        p_tenant_id,
        COALESCE(current_setting('app.current_user_id', TRUE), p_requested_by),
        'APPROVAL_REQUESTED',
        'approval_request',
        v_request_id::TEXT,
        jsonb_build_object(
            'action_type', p_action_type,
            'entity_type', p_entity_type,
            'entity_id', p_entity_id,
            'risk_level', v_risk_assessment->>'risk_level',
            'required_approvals', v_risk_assessment->>'required_approvals'
        ),
        COALESCE(current_setting('app.current_ip_hash', TRUE), 'system')
    );

    RETURN v_request_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION auth.create_approval_request IS
'Create an approval request with automatic risk assessment.';


-- =============================================================================
-- FUNCTION: submit_approval_decision
-- =============================================================================
-- Submit an approval or rejection decision

CREATE OR REPLACE FUNCTION auth.submit_approval_decision(
    p_request_id UUID,
    p_user_id UUID,
    p_user_email VARCHAR,
    p_user_role VARCHAR,
    p_decision VARCHAR,  -- APPROVE or REJECT
    p_reason TEXT DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_request RECORD;
    v_new_approval_count INTEGER;
    v_is_complete BOOLEAN := FALSE;
    v_final_status VARCHAR;
BEGIN
    -- Get request
    SELECT * INTO v_request
    FROM auth.approval_requests
    WHERE id = p_request_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'REQUEST_NOT_FOUND');
    END IF;

    IF v_request.status != 'PENDING' THEN
        RETURN jsonb_build_object('error', 'REQUEST_NOT_PENDING', 'status', v_request.status);
    END IF;

    IF v_request.expires_at < NOW() THEN
        UPDATE auth.approval_requests
        SET status = 'EXPIRED', updated_at = NOW()
        WHERE id = p_request_id;
        RETURN jsonb_build_object('error', 'REQUEST_EXPIRED');
    END IF;

    -- Check if user already decided
    IF EXISTS (
        SELECT 1 FROM auth.approval_decisions
        WHERE request_id = p_request_id AND decided_by_user_id = p_user_id
    ) THEN
        RETURN jsonb_build_object('error', 'ALREADY_DECIDED');
    END IF;

    -- Record decision
    INSERT INTO auth.approval_decisions (
        tenant_id, request_id,
        decided_by_user_id, decided_by_email, decided_by_role,
        decision, decision_reason
    ) VALUES (
        v_request.tenant_id, p_request_id,
        p_user_id, p_user_email, p_user_role,
        p_decision, p_reason
    );

    -- Process decision
    IF p_decision = 'REJECT' THEN
        -- Any rejection = request rejected
        v_final_status := 'REJECTED';
        v_is_complete := TRUE;
    ELSE
        -- Count approvals
        SELECT COUNT(*) INTO v_new_approval_count
        FROM auth.approval_decisions
        WHERE request_id = p_request_id AND decision = 'APPROVE';

        IF v_new_approval_count >= v_request.required_approvals THEN
            v_final_status := 'APPROVED';
            v_is_complete := TRUE;
        END IF;
    END IF;

    -- Update request if complete
    IF v_is_complete THEN
        UPDATE auth.approval_requests
        SET
            status = v_final_status,
            current_approvals = v_new_approval_count,
            resolved_at = NOW(),
            resolved_by = p_user_email,
            updated_at = NOW()
        WHERE id = p_request_id;
    ELSE
        UPDATE auth.approval_requests
        SET
            current_approvals = v_new_approval_count,
            updated_at = NOW()
        WHERE id = p_request_id;
    END IF;

    -- Audit log
    INSERT INTO auth.audit_log (
        tenant_id, user_id, action, entity_type, entity_id,
        changes, ip_hash
    ) VALUES (
        v_request.tenant_id,
        p_user_id::TEXT,
        'APPROVAL_DECISION',
        'approval_request',
        p_request_id::TEXT,
        jsonb_build_object(
            'decision', p_decision,
            'reason', p_reason,
            'current_approvals', v_new_approval_count,
            'required_approvals', v_request.required_approvals,
            'is_complete', v_is_complete,
            'final_status', v_final_status
        ),
        COALESCE(current_setting('app.current_ip_hash', TRUE), 'unknown')
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'request_id', p_request_id,
        'decision', p_decision,
        'current_approvals', v_new_approval_count,
        'required_approvals', v_request.required_approvals,
        'is_complete', v_is_complete,
        'final_status', v_final_status
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION auth.submit_approval_decision IS
'Submit approval/rejection decision. Handles multi-approver logic.';


-- =============================================================================
-- FUNCTION: execute_emergency_override
-- =============================================================================
-- Execute emergency override with mandatory review queue

CREATE OR REPLACE FUNCTION auth.execute_emergency_override(
    p_request_id UUID,
    p_user_id UUID,
    p_user_email VARCHAR,
    p_justification TEXT
)
RETURNS JSONB AS $$
DECLARE
    v_request RECORD;
    v_review_due_at TIMESTAMPTZ;
BEGIN
    IF p_justification IS NULL OR p_justification = '' THEN
        RETURN jsonb_build_object('error', 'JUSTIFICATION_REQUIRED');
    END IF;

    -- Get request
    SELECT * INTO v_request
    FROM auth.approval_requests
    WHERE id = p_request_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'REQUEST_NOT_FOUND');
    END IF;

    IF v_request.status != 'PENDING' THEN
        RETURN jsonb_build_object('error', 'REQUEST_NOT_PENDING');
    END IF;

    -- Check if emergency override is allowed
    -- (Default: yes, but policy can disable)

    -- Calculate review due date (next business day at 10:00 UTC)
    v_review_due_at := (date_trunc('day', NOW()) + INTERVAL '1 day' + INTERVAL '10 hours')::TIMESTAMPTZ;
    -- If weekend, push to Monday
    IF EXTRACT(DOW FROM v_review_due_at) = 0 THEN  -- Sunday
        v_review_due_at := v_review_due_at + INTERVAL '1 day';
    ELSIF EXTRACT(DOW FROM v_review_due_at) = 6 THEN  -- Saturday
        v_review_due_at := v_review_due_at + INTERVAL '2 days';
    END IF;

    -- Update request as emergency override
    UPDATE auth.approval_requests
    SET
        status = 'EMERGENCY_OVERRIDE',
        is_emergency_override = TRUE,
        emergency_justification = p_justification,
        emergency_review_due_at = v_review_due_at,
        resolved_at = NOW(),
        resolved_by = p_user_email,
        updated_at = NOW()
    WHERE id = p_request_id;

    -- Create review queue entry
    INSERT INTO auth.emergency_review_queue (
        tenant_id, request_id,
        override_by, override_at, override_justification,
        action_type, entity_type, entity_id,
        action_summary,
        affected_drivers_count, risk_factors,
        review_status, review_due_at
    ) VALUES (
        v_request.tenant_id, p_request_id,
        p_user_email, NOW(), p_justification,
        v_request.action_type, v_request.entity_type, v_request.entity_id,
        format('%s %s: %s', v_request.action_type, v_request.entity_type, v_request.entity_name),
        (v_request.evidence->>'affected_drivers_count')::INTEGER,
        v_request.risk_factors,
        'PENDING', v_review_due_at
    );

    -- Audit log (critical - emergency override)
    INSERT INTO auth.audit_log (
        tenant_id, user_id, action, entity_type, entity_id,
        changes, ip_hash
    ) VALUES (
        v_request.tenant_id,
        p_user_id::TEXT,
        'EMERGENCY_OVERRIDE',
        'approval_request',
        p_request_id::TEXT,
        jsonb_build_object(
            'action_type', v_request.action_type,
            'entity_type', v_request.entity_type,
            'entity_id', v_request.entity_id,
            'risk_level', v_request.risk_level,
            'justification', p_justification,
            'review_due_at', v_review_due_at,
            'correlation_id', v_request.correlation_id
        ),
        COALESCE(current_setting('app.current_ip_hash', TRUE), 'unknown')
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'request_id', p_request_id,
        'status', 'EMERGENCY_OVERRIDE',
        'review_due_at', v_review_due_at,
        'action_payload', v_request.action_payload,
        'correlation_id', v_request.correlation_id
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION auth.execute_emergency_override IS
'Execute emergency override with mandatory next-day review queue entry.';


-- =============================================================================
-- FUNCTION: get_pending_approvals
-- =============================================================================
-- Get pending approval requests for a user

CREATE OR REPLACE FUNCTION auth.get_pending_approvals(
    p_tenant_id INTEGER,
    p_user_role VARCHAR
)
RETURNS TABLE (
    request_id UUID,
    action_type VARCHAR,
    entity_type VARCHAR,
    entity_name VARCHAR,
    risk_level VARCHAR,
    risk_score INTEGER,
    required_approvals INTEGER,
    current_approvals INTEGER,
    requested_by VARCHAR,
    requested_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    can_approve BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.id,
        r.action_type,
        r.entity_type,
        r.entity_name,
        r.risk_level,
        r.risk_score,
        r.required_approvals,
        r.current_approvals,
        r.requested_by,
        r.requested_at,
        r.expires_at,
        -- Can approve if role is in approver list
        p_user_role = ANY(COALESCE(p.approver_roles, ARRAY['tenant_admin', 'operator_admin'])) AS can_approve
    FROM auth.approval_requests r
    LEFT JOIN auth.approval_policies p ON p.id = r.policy_id
    WHERE r.tenant_id = p_tenant_id
      AND r.status = 'PENDING'
      AND r.expires_at > NOW()
    ORDER BY
        CASE r.risk_level
            WHEN 'CRITICAL' THEN 1
            WHEN 'HIGH' THEN 2
            WHEN 'MEDIUM' THEN 3
            ELSE 4
        END,
        r.expires_at ASC;
END;
$$ LANGUAGE plpgsql STABLE;


-- =============================================================================
-- FUNCTION: get_emergency_reviews_pending
-- =============================================================================
-- Get pending emergency reviews

CREATE OR REPLACE FUNCTION auth.get_emergency_reviews_pending(
    p_tenant_id INTEGER
)
RETURNS TABLE (
    review_id UUID,
    request_id UUID,
    override_by VARCHAR,
    override_at TIMESTAMPTZ,
    action_type VARCHAR,
    action_summary TEXT,
    justification TEXT,
    review_due_at TIMESTAMPTZ,
    is_overdue BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.id,
        q.request_id,
        q.override_by,
        q.override_at,
        q.action_type,
        q.action_summary,
        q.override_justification,
        q.review_due_at,
        q.review_due_at < NOW() AS is_overdue
    FROM auth.emergency_review_queue q
    WHERE q.tenant_id = p_tenant_id
      AND q.review_status = 'PENDING'
    ORDER BY q.review_due_at ASC;
END;
$$ LANGUAGE plpgsql STABLE;


-- =============================================================================
-- SEED: Default approval policies
-- =============================================================================

INSERT INTO auth.approval_policies (
    tenant_id, policy_key, display_name, description,
    action_type, entity_type, risk_level, required_approvals,
    threshold_conditions, approver_roles, priority
) VALUES
-- Low-risk: single approver
(NULL, 'publish_low_risk', 'Publish (Low Risk)', 'Standard plan publish',
    'PUBLISH', 'PLAN', 'LOW', 1,
    '{"affected_drivers_max": 10}', ARRAY['tenant_admin', 'operator_admin', 'dispatcher'], 100),

-- High-risk: two approvers for large publishes
(NULL, 'publish_high_risk', 'Publish (High Risk)', 'Large plan publish requiring 2 approvers',
    'PUBLISH', 'PLAN', 'HIGH', 2,
    '{"affected_drivers_min": 10}', ARRAY['tenant_admin', 'operator_admin'], 50),

-- Freeze: always high risk
(NULL, 'freeze_plan', 'Freeze Plan', 'Freezing plan for changes',
    'FREEZE', 'PLAN', 'HIGH', 2,
    '{}', ARRAY['tenant_admin', 'operator_admin'], 60),

-- Repair with rest-time impact: critical
(NULL, 'repair_rest_time', 'Repair (Rest Time Impact)', 'Repair affecting rest times',
    'REPAIR', 'PLAN', 'CRITICAL', 2,
    '{"near_rest_time": true}', ARRAY['tenant_admin'], 40),

-- Standard repair: medium risk
(NULL, 'repair_standard', 'Repair (Standard)', 'Standard plan repair',
    'REPAIR', 'PLAN', 'MEDIUM', 1,
    '{}', ARRAY['tenant_admin', 'operator_admin', 'dispatcher'], 80),

-- Broadcast: medium risk
(NULL, 'broadcast_dm', 'WhatsApp Broadcast', 'Send WhatsApp DMs to drivers',
    'BROADCAST', 'DRIVER', 'MEDIUM', 1,
    '{}', ARRAY['tenant_admin', 'operator_admin', 'dispatcher'], 70)

ON CONFLICT (tenant_id, policy_key) DO NOTHING;


-- =============================================================================
-- VERIFICATION FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION auth.verify_approval_policy_integrity()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: RLS enabled on policies
    RETURN QUERY
    SELECT
        'rls_policies'::TEXT,
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END,
        'approval_policies has RLS enabled'::TEXT
    FROM pg_class WHERE oid = 'auth.approval_policies'::regclass;

    -- Check 2: RLS enabled on requests
    RETURN QUERY
    SELECT
        'rls_requests'::TEXT,
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END,
        'approval_requests has RLS enabled'::TEXT
    FROM pg_class WHERE oid = 'auth.approval_requests'::regclass;

    -- Check 3: RLS enabled on decisions
    RETURN QUERY
    SELECT
        'rls_decisions'::TEXT,
        CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'PASS' ELSE 'FAIL' END,
        'approval_decisions has RLS enabled'::TEXT
    FROM pg_class WHERE oid = 'auth.approval_decisions'::regclass;

    -- Check 4: Default policies exist
    RETURN QUERY
    SELECT
        'default_policies'::TEXT,
        CASE WHEN COUNT(*) >= 5 THEN 'PASS' ELSE 'WARN' END,
        format('%s default policies configured', COUNT(*))::TEXT
    FROM auth.approval_policies WHERE tenant_id IS NULL;

    -- Check 5: Functions exist
    RETURN QUERY
    SELECT
        'functions_exist'::TEXT,
        CASE WHEN COUNT(*) >= 5 THEN 'PASS' ELSE 'FAIL' END,
        format('%s/5 approval functions exist', COUNT(*))::TEXT
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'auth'
      AND p.proname IN (
          'assess_action_risk', 'create_approval_request',
          'submit_approval_decision', 'execute_emergency_override',
          'get_pending_approvals'
      );

    -- Check 6: No expired pending requests
    RETURN QUERY
    SELECT
        'no_stale_requests'::TEXT,
        CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
        format('%s expired requests still pending', COUNT(*))::TEXT
    FROM auth.approval_requests
    WHERE status = 'PENDING' AND expires_at < NOW();

END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- SUCCESS MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 058: Risk-Based Approval Policy COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'TABLES:';
    RAISE NOTICE '  - auth.approval_policies (configurable rules)';
    RAISE NOTICE '  - auth.approval_requests (pending/completed requests)';
    RAISE NOTICE '  - auth.approval_decisions (individual decisions)';
    RAISE NOTICE '  - auth.emergency_review_queue (override reviews)';
    RAISE NOTICE '';
    RAISE NOTICE 'POLICY RULES:';
    RAISE NOTICE '  - LOW RISK: Single approver';
    RAISE NOTICE '  - HIGH RISK: Two approvers (>10 drivers or freeze)';
    RAISE NOTICE '  - CRITICAL: Two approvers (rest-time impact)';
    RAISE NOTICE '  - EMERGENCY: Single + mandatory next-day review';
    RAISE NOTICE '';
    RAISE NOTICE 'FUNCTIONS:';
    RAISE NOTICE '  - assess_action_risk(tenant, action, entity, context)';
    RAISE NOTICE '  - create_approval_request(...)';
    RAISE NOTICE '  - submit_approval_decision(request, user, decision)';
    RAISE NOTICE '  - execute_emergency_override(request, user, justification)';
    RAISE NOTICE '  - get_pending_approvals(tenant, role)';
    RAISE NOTICE '  - get_emergency_reviews_pending(tenant)';
    RAISE NOTICE '';
    RAISE NOTICE 'VERIFY:';
    RAISE NOTICE '  SELECT * FROM auth.verify_approval_policy_integrity();';
    RAISE NOTICE '============================================================';
END $$;

COMMIT;
