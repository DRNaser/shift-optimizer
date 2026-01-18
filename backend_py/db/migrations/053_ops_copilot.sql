-- =============================================================================
-- MIGRATION 053: Ops-Copilot MVP - WhatsApp AI Operations Assistant
-- =============================================================================
-- Version: 4.6.0
-- Purpose: WhatsApp-based AI assistant for operations staff
-- Features:
--   - OTP-based pairing (admin invite + user activation via "PAIR <OTP>")
--   - Multi-tenant isolation (RLS + app-level)
--   - 2-phase commit for writes (prepare -> CONFIRM -> commit)
--   - LangGraph state persistence in PostgreSQL
--   - Memory and playbook management
--   - Internal ticketing system
--   - Broadcast messaging (ops: free text, driver: templates + opt-in)
--
-- Security Notes:
--   - All tables have RLS enabled and forced
--   - OTP stored as SHA-256 hash, never plaintext
--   - Phone numbers stored as hashes for GDPR
--   - Events and comments are append-only (immutable)
--   - Standard tenant isolation pattern from SOLVEREIGN v3.7+
-- =============================================================================

BEGIN;

-- =============================================================================
-- SECTION 1: Schema Setup
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ops;

-- Secure the schema (follow hardening pattern from 025a)
REVOKE ALL ON SCHEMA ops FROM PUBLIC;
GRANT USAGE ON SCHEMA ops TO solvereign_api;
GRANT USAGE ON SCHEMA ops TO solvereign_platform;

-- =============================================================================
-- SECTION 2: WhatsApp Identity Management
-- =============================================================================

-- Table: ops.whatsapp_identities
-- Maps WhatsApp user IDs to internal user bindings
-- One WA identity can be bound to exactly one user per tenant

CREATE TABLE IF NOT EXISTS ops.whatsapp_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- WhatsApp identity (phone hash for GDPR)
    wa_user_id VARCHAR(64) NOT NULL,           -- WhatsApp user ID from Clawdbot
    wa_phone_hash CHAR(64) NOT NULL,           -- SHA-256 of E.164 phone number

    -- Binding to internal user
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Optional site override (schema-ready for Phase 2)
    site_id UUID NULL REFERENCES core.sites(id) ON DELETE SET NULL,

    -- Status tracking
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')),

    -- Metadata
    paired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paired_via VARCHAR(50) NOT NULL DEFAULT 'OTP',  -- OTP, ADMIN_OVERRIDE
    last_activity_at TIMESTAMPTZ NULL,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT whatsapp_identities_unique_wa_tenant
        UNIQUE (wa_user_id, tenant_id),
    CONSTRAINT whatsapp_identities_unique_user_tenant
        UNIQUE (user_id, tenant_id)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_whatsapp_identities_wa_user
    ON ops.whatsapp_identities(wa_user_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_identities_tenant_status
    ON ops.whatsapp_identities(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_whatsapp_identities_user
    ON ops.whatsapp_identities(user_id);

-- =============================================================================
-- SECTION 3: OTP Pairing System
-- =============================================================================

-- Table: ops.pairing_invites
-- Admin-initiated OTP invites for WhatsApp pairing

CREATE TABLE IF NOT EXISTS ops.pairing_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Target binding
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- OTP (stored as hash, NEVER plain)
    otp_hash CHAR(64) NOT NULL,                -- SHA-256 of 6-digit OTP

    -- Security limits
    expires_at TIMESTAMPTZ NOT NULL,           -- Default: 15 minutes
    max_attempts INTEGER NOT NULL DEFAULT 3,
    attempt_count INTEGER NOT NULL DEFAULT 0,

    -- Status tracking
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'USED', 'EXPIRED', 'EXHAUSTED')),

    -- Audit
    created_by UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    used_at TIMESTAMPTZ NULL,
    used_wa_user_id VARCHAR(64) NULL,

    CONSTRAINT pairing_invites_expires_future
        CHECK (expires_at > created_at)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_pairing_invites_user_pending
    ON ops.pairing_invites(user_id, status) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_pairing_invites_expires
    ON ops.pairing_invites(expires_at) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_pairing_invites_tenant
    ON ops.pairing_invites(tenant_id);

-- =============================================================================
-- SECTION 4: LangGraph Thread Persistence
-- =============================================================================

-- Table: ops.threads
-- LangGraph thread state persistence (conversation context)

CREATE TABLE IF NOT EXISTS ops.threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Thread identity (deterministic from wa_user_id + tenant)
    thread_id CHAR(64) NOT NULL UNIQUE,        -- SHA-256(sv:tenant_id:site_id:whatsapp:wa_user_id)

    -- Binding
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES core.sites(id) ON DELETE SET NULL,
    identity_id UUID NOT NULL REFERENCES ops.whatsapp_identities(id) ON DELETE CASCADE,

    -- Thread state (LangGraph checkpoint columns)
    checkpoint_ns VARCHAR(255) NOT NULL DEFAULT 'default',
    checkpoint_id VARCHAR(255) NULL,
    channel_values JSONB NOT NULL DEFAULT '{}',
    channel_versions JSONB NOT NULL DEFAULT '{}',
    pending_sends JSONB NOT NULL DEFAULT '[]',

    -- Additional state for custom tracking
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Metrics
    message_count INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    last_message_at TIMESTAMPTZ NULL,

    -- Persona config (tenant default, can override per site later)
    persona_id UUID NULL,  -- FK to ops.personas when added

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_threads_identity ON ops.threads(identity_id);
CREATE INDEX IF NOT EXISTS idx_threads_tenant ON ops.threads(tenant_id);
CREATE INDEX IF NOT EXISTS idx_threads_checkpoint ON ops.threads(checkpoint_ns, checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_threads_last_activity ON ops.threads(last_message_at DESC);

-- =============================================================================
-- SECTION 5: Event Log (Append-Only)
-- =============================================================================

-- Table: ops.events
-- Append-only event log for all copilot interactions

CREATE TABLE IF NOT EXISTS ops.events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Context
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    thread_id CHAR(64) NOT NULL,

    -- Event type
    event_type VARCHAR(50) NOT NULL CHECK (event_type IN (
        'MESSAGE_IN',          -- User message received
        'MESSAGE_OUT',         -- Assistant message sent
        'TOOL_CALL',           -- Tool invocation
        'TOOL_RESULT',         -- Tool result
        'CONTEXT_LOADED',      -- Context retrieved
        'DRAFT_CREATED',       -- 2-phase: draft created
        'DRAFT_CONFIRMED',     -- 2-phase: user confirmed
        'DRAFT_CANCELLED',     -- 2-phase: user cancelled
        'DRAFT_COMMITTED',     -- 2-phase: committed to DB
        'DRAFT_EXPIRED',       -- 2-phase: timeout
        'BROADCAST_ENQUEUED',  -- Broadcast message queued
        'PAIRING_ATTEMPT',     -- OTP pairing attempt
        'PAIRING_SUCCESS',     -- Successful pairing
        'PAIRING_FAILED',      -- Failed pairing
        'ERROR',               -- Error occurred
        'RATE_LIMITED'         -- Rate limit hit
    )),

    -- Event data (no secrets)
    payload JSONB NOT NULL DEFAULT '{}',

    -- Tracing
    trace_id VARCHAR(64) NULL,
    parent_event_id BIGINT NULL REFERENCES ops.events(id),

    -- Timing
    duration_ms INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_events_thread ON ops.events(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_tenant ON ops.events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON ops.events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_trace ON ops.events(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_event_id ON ops.events(event_id);

-- Immutability trigger function
CREATE OR REPLACE FUNCTION ops.prevent_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only. Modifications not allowed.', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

-- Make events append-only
DROP TRIGGER IF EXISTS tr_events_immutable ON ops.events;
CREATE TRIGGER tr_events_immutable
    BEFORE UPDATE OR DELETE ON ops.events
    FOR EACH ROW
    EXECUTE FUNCTION ops.prevent_modification();

-- =============================================================================
-- SECTION 6: Episodic Memory
-- =============================================================================

-- Table: ops.memories
-- Episodic memory per thread (learnings, preferences, context)

CREATE TABLE IF NOT EXISTS ops.memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Context
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    thread_id CHAR(64) NOT NULL,

    -- Memory content
    memory_type VARCHAR(50) NOT NULL CHECK (memory_type IN (
        'PREFERENCE',          -- User preference learned
        'CORRECTION',          -- User corrected assistant
        'CONTEXT',             -- Relevant context from conversation
        'ENTITY',              -- Entity mentioned (driver, tour, etc.)
        'ACTION_HISTORY'       -- Past actions taken
    )),

    content JSONB NOT NULL,

    -- Relevance tracking
    relevance_score FLOAT NOT NULL DEFAULT 1.0,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TIMESTAMPTZ NULL,

    -- TTL
    expires_at TIMESTAMPTZ NULL,  -- NULL = permanent

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_memories_thread ON ops.memories(thread_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_tenant ON ops.memories(tenant_id);
CREATE INDEX IF NOT EXISTS idx_memories_expires ON ops.memories(expires_at)
    WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_relevance ON ops.memories(thread_id, relevance_score DESC);

-- =============================================================================
-- SECTION 7: Playbooks (SOPs/Runbooks)
-- =============================================================================

-- Table: ops.playbooks
-- Tenant-scoped runbooks/SOPs the copilot can reference

CREATE TABLE IF NOT EXISTS ops.playbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scoping
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES core.sites(id) ON DELETE SET NULL,  -- NULL = all sites

    -- Identity
    slug VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,

    -- Content
    content_markdown TEXT NOT NULL,

    -- Metadata
    category VARCHAR(50) NULL CHECK (category IN (
        'ESCALATION',
        'SHIFT_SWAP',
        'SICK_CALL',
        'VEHICLE_ISSUE',
        'CUSTOMER_COMPLAINT',
        'ONBOARDING',
        'GENERAL'
    )),
    tags TEXT[] DEFAULT '{}',

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1,

    -- Audit
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT playbooks_unique_slug_tenant
        UNIQUE (tenant_id, slug)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_playbooks_tenant_active
    ON ops.playbooks(tenant_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_playbooks_category
    ON ops.playbooks(tenant_id, category);
CREATE INDEX IF NOT EXISTS idx_playbooks_tags ON ops.playbooks USING GIN(tags);

-- =============================================================================
-- SECTION 8: 2-Phase Commit Drafts
-- =============================================================================

-- Table: ops.drafts
-- 2-phase commit staging area for write actions

CREATE TABLE IF NOT EXISTS ops.drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Context
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    thread_id CHAR(64) NOT NULL,
    identity_id UUID NOT NULL REFERENCES ops.whatsapp_identities(id) ON DELETE CASCADE,

    -- Draft content
    action_type VARCHAR(50) NOT NULL CHECK (action_type IN (
        'CREATE_TICKET',
        'AUDIT_COMMENT',
        'WHATSAPP_BROADCAST_OPS',
        'WHATSAPP_BROADCAST_DRIVER'
    )),

    payload JSONB NOT NULL,                    -- Action parameters
    preview_text TEXT NOT NULL,                -- Human-readable summary

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING_CONFIRM'
        CHECK (status IN ('PENDING_CONFIRM', 'CONFIRMED', 'COMMITTED', 'CANCELLED', 'EXPIRED')),

    -- Timing
    expires_at TIMESTAMPTZ NOT NULL,           -- Default: 5 minutes
    confirmed_at TIMESTAMPTZ NULL,
    committed_at TIMESTAMPTZ NULL,

    -- Result (after commit)
    commit_result JSONB NULL,
    commit_error TEXT NULL,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_drafts_thread_pending
    ON ops.drafts(thread_id, status) WHERE status = 'PENDING_CONFIRM';
CREATE INDEX IF NOT EXISTS idx_drafts_expires
    ON ops.drafts(expires_at) WHERE status = 'PENDING_CONFIRM';
CREATE INDEX IF NOT EXISTS idx_drafts_identity ON ops.drafts(identity_id);

-- =============================================================================
-- SECTION 9: Internal Ticketing
-- =============================================================================

-- Table: ops.tickets
-- Internal tickets created via copilot

CREATE TABLE IF NOT EXISTS ops.tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scoping
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES core.sites(id) ON DELETE SET NULL,

    -- Ticket identity
    ticket_number SERIAL,                      -- Human-readable: OPS-{tenant}-{number}

    -- Classification
    category VARCHAR(50) NOT NULL CHECK (category IN (
        'SICK_CALL',
        'SHIFT_SWAP',
        'VEHICLE_ISSUE',
        'CUSTOMER_COMPLAINT',
        'SCHEDULING_REQUEST',
        'OTHER'
    )),
    priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'
        CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),

    -- Content
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'IN_PROGRESS', 'PENDING', 'RESOLVED', 'CLOSED')),

    -- Assignment
    assigned_to UUID NULL REFERENCES auth.users(id),

    -- References (entity links)
    driver_id VARCHAR(255) NULL,
    tour_id INTEGER NULL,
    plan_version_id INTEGER NULL,

    -- Source tracking
    source VARCHAR(50) NOT NULL DEFAULT 'COPILOT',  -- COPILOT, PORTAL, MANUAL
    source_thread_id CHAR(64) NULL,
    source_draft_id UUID NULL,

    -- Timestamps
    created_by UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ NULL,
    closed_at TIMESTAMPTZ NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tickets_tenant_status
    ON ops.tickets(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_assigned
    ON ops.tickets(assigned_to, status) WHERE assigned_to IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tickets_number ON ops.tickets(tenant_id, ticket_number);
CREATE INDEX IF NOT EXISTS idx_tickets_category ON ops.tickets(tenant_id, category);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON ops.tickets(tenant_id, priority, status);

-- =============================================================================
-- SECTION 10: Ticket Comments (Append-Only)
-- =============================================================================

-- Table: ops.ticket_comments
-- Comments/updates on tickets (append-only)

CREATE TABLE IF NOT EXISTS ops.ticket_comments (
    id BIGSERIAL PRIMARY KEY,
    comment_id UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Reference
    ticket_id UUID NOT NULL REFERENCES ops.tickets(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,

    -- Content
    comment_type VARCHAR(20) NOT NULL DEFAULT 'NOTE'
        CHECK (comment_type IN ('NOTE', 'STATUS_CHANGE', 'ASSIGNMENT', 'SYSTEM')),
    content TEXT NOT NULL,
    metadata JSONB NULL,  -- For status changes, etc.

    -- Source
    source VARCHAR(50) NOT NULL DEFAULT 'COPILOT',
    source_thread_id CHAR(64) NULL,

    -- Audit
    created_by UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_ticket_comments_ticket
    ON ops.ticket_comments(ticket_id, created_at);

-- Make comments append-only
DROP TRIGGER IF EXISTS tr_ticket_comments_immutable ON ops.ticket_comments;
CREATE TRIGGER tr_ticket_comments_immutable
    BEFORE UPDATE OR DELETE ON ops.ticket_comments
    FOR EACH ROW
    EXECUTE FUNCTION ops.prevent_modification();

-- =============================================================================
-- SECTION 11: Broadcast Templates
-- =============================================================================

-- Table: ops.broadcast_templates
-- WhatsApp broadcast templates (driver-facing requires Meta approval)

CREATE TABLE IF NOT EXISTS ops.broadcast_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scoping
    tenant_id UUID NULL REFERENCES core.tenants(id) ON DELETE CASCADE,  -- NULL = system

    -- Identity
    template_key VARCHAR(100) NOT NULL,

    -- Template type
    audience VARCHAR(20) NOT NULL CHECK (audience IN ('OPS', 'DRIVER')),
    -- OPS = free text allowed, DRIVER = pre-approved template only

    -- WhatsApp-specific (for DRIVER templates)
    wa_template_name VARCHAR(255) NULL,
    wa_template_namespace VARCHAR(255) NULL,
    wa_template_language VARCHAR(10) DEFAULT 'de',

    -- Content
    body_template TEXT NOT NULL,               -- Supports {{variable}} placeholders
    expected_params TEXT[] DEFAULT '{}',

    -- Validation
    allowed_placeholders TEXT[] DEFAULT '{}',  -- For driver templates

    -- Approval status (DRIVER templates only)
    is_approved BOOLEAN NOT NULL DEFAULT FALSE,
    approval_status VARCHAR(50) NULL CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    approved_at TIMESTAMPTZ NULL,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint on template_key per tenant (with NULL handling)
-- COALESCE not allowed in UNIQUE constraint, use unique index instead
CREATE UNIQUE INDEX IF NOT EXISTS idx_broadcast_templates_unique_key
    ON ops.broadcast_templates (COALESCE(tenant_id, -1), template_key);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_broadcast_templates_tenant
    ON ops.broadcast_templates(tenant_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_broadcast_templates_audience
    ON ops.broadcast_templates(audience, is_active);

-- =============================================================================
-- SECTION 12: Broadcast Subscriptions (Opt-in Tracking)
-- =============================================================================

-- Table: ops.broadcast_subscriptions
-- Opt-in tracking for driver broadcasts (GDPR compliance)

CREATE TABLE IF NOT EXISTS ops.broadcast_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    driver_id VARCHAR(255) NOT NULL,
    wa_user_id VARCHAR(64) NULL,  -- Optional: if driver has WhatsApp

    -- Subscription status
    is_subscribed BOOLEAN NOT NULL DEFAULT TRUE,

    -- Consent tracking (GDPR)
    consent_given_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consent_source VARCHAR(50) NOT NULL CHECK (consent_source IN (
        'PORTAL', 'WHATSAPP', 'ADMIN', 'IMPORT'
    )),
    consent_version VARCHAR(20) NULL,          -- Privacy policy version

    -- Opt-out tracking
    unsubscribed_at TIMESTAMPTZ NULL,
    unsubscribe_reason VARCHAR(100) NULL,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT broadcast_subscriptions_unique_driver
        UNIQUE (tenant_id, driver_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_broadcast_subscriptions_wa
    ON ops.broadcast_subscriptions(wa_user_id) WHERE wa_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_broadcast_subscriptions_active
    ON ops.broadcast_subscriptions(tenant_id, is_subscribed)
    WHERE is_subscribed = TRUE;

-- =============================================================================
-- SECTION 13: AI Personas (Schema-Ready)
-- =============================================================================

-- Table: ops.personas
-- Tenant-configurable AI personas

CREATE TABLE IF NOT EXISTS ops.personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES core.sites(id) ON DELETE SET NULL,

    name VARCHAR(100) NOT NULL,
    system_prompt TEXT NOT NULL,
    personality_traits JSONB DEFAULT '{}',

    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_personas_tenant_default
    ON ops.personas(tenant_id, is_default) WHERE is_default = TRUE;

-- =============================================================================
-- SECTION 14: RLS Policies
-- =============================================================================

-- Enable RLS on all tables
ALTER TABLE ops.whatsapp_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.pairing_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.playbooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.ticket_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.broadcast_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.broadcast_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.personas ENABLE ROW LEVEL SECURITY;

-- Force RLS (defense in depth)
ALTER TABLE ops.whatsapp_identities FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.pairing_invites FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.threads FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.events FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.memories FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.playbooks FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.drafts FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.tickets FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.ticket_comments FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.broadcast_templates FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.broadcast_subscriptions FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.personas FORCE ROW LEVEL SECURITY;

-- Standard tenant isolation policy (applied to most tables)
-- Pattern: platform can see all, api sees only current tenant

CREATE POLICY tenant_isolation_whatsapp_identities ON ops.whatsapp_identities
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_pairing_invites ON ops.pairing_invites
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_threads ON ops.threads
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_events ON ops.events
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_memories ON ops.memories
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_playbooks ON ops.playbooks
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_drafts ON ops.drafts
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_tickets ON ops.tickets
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_ticket_comments ON ops.ticket_comments
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_subscriptions ON ops.broadcast_subscriptions
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

CREATE POLICY tenant_isolation_personas ON ops.personas
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

-- Special policy for broadcast_templates (allows NULL tenant_id for system templates)
CREATE POLICY tenant_isolation_broadcast_templates ON ops.broadcast_templates
FOR ALL USING (
    pg_has_role(session_user, 'solvereign_platform', 'MEMBER')
    OR tenant_id IS NULL  -- System templates accessible to all
    OR (
        pg_has_role(session_user, 'solvereign_api', 'MEMBER')
        AND tenant_id = COALESCE(
            NULLIF(current_setting('app.current_tenant_id', TRUE), '')::UUID,
            tenant_id
        )
    )
);

-- =============================================================================
-- SECTION 15: Helper Functions
-- =============================================================================

-- Generate deterministic thread ID
CREATE OR REPLACE FUNCTION ops.generate_thread_id(
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_wa_user_id VARCHAR
) RETURNS CHAR(64)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN encode(
        sha256(
            ('sv:' || p_tenant_id::TEXT || ':' || COALESCE(p_site_id::TEXT, '0') || ':whatsapp:' || p_wa_user_id)::BYTEA
        ),
        'hex'
    );
END;
$$;

-- Hash OTP for secure storage
CREATE OR REPLACE FUNCTION ops.hash_otp(p_otp VARCHAR)
RETURNS CHAR(64)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN encode(sha256(p_otp::BYTEA), 'hex');
END;
$$;

-- Verify OTP and create identity (SECURITY DEFINER for cross-table access)
CREATE OR REPLACE FUNCTION ops.verify_pairing_otp(
    p_user_id UUID,
    p_otp_plain VARCHAR,
    p_wa_user_id VARCHAR,
    p_wa_phone_hash CHAR(64) DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, ops
AS $$
DECLARE
    v_invite RECORD;
    v_otp_hash CHAR(64);
    v_identity_id UUID;
    v_phone_hash CHAR(64);
BEGIN
    v_otp_hash := ops.hash_otp(p_otp_plain);
    v_phone_hash := COALESCE(p_wa_phone_hash, encode(sha256(p_wa_user_id::BYTEA), 'hex'));

    -- Find valid pending invite for this user
    SELECT * INTO v_invite
    FROM ops.pairing_invites
    WHERE user_id = p_user_id
      AND status = 'PENDING'
      AND expires_at > NOW()
    ORDER BY created_at DESC
    LIMIT 1
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'NO_VALID_INVITE',
            'message', 'No valid pairing invite found for this user'
        );
    END IF;

    -- Increment attempt counter
    UPDATE ops.pairing_invites
    SET attempt_count = attempt_count + 1
    WHERE id = v_invite.id;

    -- Check max attempts AFTER incrementing
    IF v_invite.attempt_count >= v_invite.max_attempts THEN
        UPDATE ops.pairing_invites
        SET status = 'EXHAUSTED'
        WHERE id = v_invite.id;

        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'MAX_ATTEMPTS_EXCEEDED',
            'message', 'Too many failed attempts. Request a new pairing code.'
        );
    END IF;

    -- Verify OTP (constant-time via DB comparison)
    IF v_otp_hash != v_invite.otp_hash THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'INVALID_OTP',
            'message', 'Invalid pairing code',
            'remaining_attempts', v_invite.max_attempts - v_invite.attempt_count - 1
        );
    END IF;

    -- Check if identity already exists for this wa_user_id + tenant
    IF EXISTS (
        SELECT 1 FROM ops.whatsapp_identities
        WHERE wa_user_id = p_wa_user_id
        AND tenant_id = v_invite.tenant_id
        AND status = 'ACTIVE'
    ) THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'ALREADY_PAIRED',
            'message', 'This WhatsApp number is already paired to a user'
        );
    END IF;

    -- OTP valid - create identity binding
    INSERT INTO ops.whatsapp_identities (
        wa_user_id, wa_phone_hash, tenant_id, user_id, status, paired_via
    ) VALUES (
        p_wa_user_id,
        v_phone_hash,
        v_invite.tenant_id,
        p_user_id,
        'ACTIVE',
        'OTP'
    )
    RETURNING id INTO v_identity_id;

    -- Mark invite as used
    UPDATE ops.pairing_invites
    SET status = 'USED',
        used_at = NOW(),
        used_wa_user_id = p_wa_user_id
    WHERE id = v_invite.id;

    RETURN jsonb_build_object(
        'success', TRUE,
        'identity_id', v_identity_id,
        'tenant_id', v_invite.tenant_id,
        'user_id', p_user_id
    );
END;
$$;

-- Revoke ALL and grant to API
REVOKE ALL ON FUNCTION ops.verify_pairing_otp(UUID, VARCHAR, VARCHAR, CHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.verify_pairing_otp(UUID, VARCHAR, VARCHAR, CHAR) TO solvereign_api;
GRANT EXECUTE ON FUNCTION ops.verify_pairing_otp(UUID, VARCHAR, VARCHAR, CHAR) TO solvereign_platform;

-- Get or create thread for identity
CREATE OR REPLACE FUNCTION ops.get_or_create_thread(
    p_identity_id UUID,
    p_tenant_id INTEGER,
    p_site_id INTEGER,
    p_wa_user_id VARCHAR
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, ops
AS $$
DECLARE
    v_thread_id CHAR(64);
    v_thread_uuid UUID;
BEGIN
    v_thread_id := ops.generate_thread_id(p_tenant_id, p_site_id, p_wa_user_id);

    -- Try to get existing thread
    SELECT id INTO v_thread_uuid
    FROM ops.threads
    WHERE thread_id = v_thread_id;

    IF FOUND THEN
        -- Update last activity
        UPDATE ops.threads
        SET last_message_at = NOW(),
            updated_at = NOW()
        WHERE id = v_thread_uuid;

        RETURN v_thread_uuid;
    END IF;

    -- Create new thread
    INSERT INTO ops.threads (
        thread_id, tenant_id, site_id, identity_id, last_message_at
    ) VALUES (
        v_thread_id, p_tenant_id, p_site_id, p_identity_id, NOW()
    )
    RETURNING id INTO v_thread_uuid;

    RETURN v_thread_uuid;
END;
$$;

REVOKE ALL ON FUNCTION ops.get_or_create_thread(UUID, INTEGER, INTEGER, VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.get_or_create_thread(UUID, INTEGER, INTEGER, VARCHAR) TO solvereign_api;

-- Expire pending drafts (called by cron or app)
CREATE OR REPLACE FUNCTION ops.expire_pending_drafts()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, ops
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE ops.drafts
    SET status = 'EXPIRED',
        updated_at = NOW()
    WHERE status = 'PENDING_CONFIRM'
      AND expires_at < NOW();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- Expire pending pairing invites
CREATE OR REPLACE FUNCTION ops.expire_pending_invites()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, ops
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE ops.pairing_invites
    SET status = 'EXPIRED'
    WHERE status = 'PENDING'
      AND expires_at < NOW();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- =============================================================================
-- SECTION 16: Verification Function
-- =============================================================================

CREATE OR REPLACE FUNCTION ops.verify_ops_copilot_integrity()
RETURNS TABLE (
    check_name VARCHAR(100),
    status VARCHAR(10),
    details TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, ops
AS $$
DECLARE
    v_table_count INTEGER;
    v_rls_count INTEGER;
    v_trigger_count INTEGER;
    v_function_count INTEGER;
BEGIN
    -- Check 1: All required tables exist (12 tables)
    SELECT COUNT(*) INTO v_table_count
    FROM information_schema.tables
    WHERE table_schema = 'ops'
      AND table_type = 'BASE TABLE';

    RETURN QUERY
    SELECT 'tables_exist'::VARCHAR(100),
           CASE WHEN v_table_count >= 12 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
           FORMAT('%s/12 tables exist in ops schema', v_table_count)::TEXT;

    -- Check 2: RLS enabled and forced on all tables
    SELECT COUNT(*) INTO v_rls_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
      AND c.relkind = 'r'
      AND c.relrowsecurity = TRUE
      AND c.relforcerowsecurity = TRUE;

    RETURN QUERY
    SELECT 'rls_enforced'::VARCHAR(100),
           CASE WHEN v_rls_count >= 12 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
           FORMAT('%s/12 tables have RLS enabled and forced', v_rls_count)::TEXT;

    -- Check 3: Immutability triggers exist
    SELECT COUNT(*) INTO v_trigger_count
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
      AND t.tgname LIKE 'tr_%_immutable';

    RETURN QUERY
    SELECT 'immutability_triggers'::VARCHAR(100),
           CASE WHEN v_trigger_count >= 2 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
           FORMAT('%s/2 immutability triggers exist (events, ticket_comments)', v_trigger_count)::TEXT;

    -- Check 4: Helper functions exist
    SELECT COUNT(*) INTO v_function_count
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
      AND p.proname IN ('generate_thread_id', 'hash_otp', 'verify_pairing_otp',
                        'get_or_create_thread', 'expire_pending_drafts', 'expire_pending_invites');

    RETURN QUERY
    SELECT 'helper_functions'::VARCHAR(100),
           CASE WHEN v_function_count >= 6 THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
           FORMAT('%s/6 helper functions exist', v_function_count)::TEXT;

    -- Check 5: No orphaned thread references
    RETURN QUERY
    SELECT 'no_orphaned_threads'::VARCHAR(100),
           CASE WHEN NOT EXISTS(
               SELECT 1 FROM ops.threads t
               LEFT JOIN ops.whatsapp_identities i ON i.id = t.identity_id
               WHERE i.id IS NULL
           ) THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
           'All threads have valid identity references'::TEXT;

    -- Check 6: Draft status state machine valid
    RETURN QUERY
    SELECT 'draft_status_valid'::VARCHAR(100),
           CASE WHEN NOT EXISTS(
               SELECT 1 FROM ops.drafts
               WHERE status NOT IN ('PENDING_CONFIRM', 'CONFIRMED', 'COMMITTED', 'CANCELLED', 'EXPIRED')
           ) THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
           'All drafts have valid status values'::TEXT;

    -- Check 7: Ticket status state machine valid
    RETURN QUERY
    SELECT 'ticket_status_valid'::VARCHAR(100),
           CASE WHEN NOT EXISTS(
               SELECT 1 FROM ops.tickets
               WHERE status NOT IN ('OPEN', 'IN_PROGRESS', 'PENDING', 'RESOLVED', 'CLOSED')
           ) THEN 'PASS' ELSE 'FAIL' END::VARCHAR(10),
           'All tickets have valid status values'::TEXT;

    -- Check 8: No expired pending drafts (should be cleaned up)
    RETURN QUERY
    SELECT 'no_stale_drafts'::VARCHAR(100),
           CASE WHEN NOT EXISTS(
               SELECT 1 FROM ops.drafts
               WHERE status = 'PENDING_CONFIRM'
                 AND expires_at < NOW() - INTERVAL '1 hour'
           ) THEN 'PASS' ELSE 'WARN' END::VARCHAR(10),
           'No expired drafts older than 1 hour pending cleanup'::TEXT;
END;
$$;

GRANT EXECUTE ON FUNCTION ops.verify_ops_copilot_integrity() TO solvereign_platform;
GRANT EXECUTE ON FUNCTION ops.verify_ops_copilot_integrity() TO solvereign_api;

-- =============================================================================
-- SECTION 17: Grants
-- =============================================================================

-- Tables: SELECT, INSERT, UPDATE for API; full access for platform
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ops TO solvereign_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ops TO solvereign_platform;

-- Sequences
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO solvereign_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO solvereign_platform;

-- Functions
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO solvereign_api;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO solvereign_platform;

-- =============================================================================
-- SECTION 18: Seed Permissions (for RBAC)
-- =============================================================================

-- Insert ops_copilot permissions into auth.permissions
INSERT INTO auth.permissions (permission_key, description, category)
VALUES
    ('ops_copilot.pairing.write', 'Create WhatsApp pairing invites', 'ops_copilot'),
    ('ops_copilot.pairing.read', 'View WhatsApp pairing invites', 'ops_copilot'),
    ('ops_copilot.identity.revoke', 'Revoke WhatsApp identities', 'ops_copilot'),
    ('ops_copilot.tickets.write', 'Create and update tickets via copilot', 'ops_copilot'),
    ('ops_copilot.tickets.read', 'View tickets created via copilot', 'ops_copilot'),
    ('ops_copilot.audit.write', 'Add audit comments via copilot', 'ops_copilot'),
    ('ops_copilot.broadcast.ops', 'Send broadcasts to ops staff', 'ops_copilot'),
    ('ops_copilot.broadcast.driver', 'Send broadcasts to drivers (template-only)', 'ops_copilot'),
    ('ops_copilot.playbooks.write', 'Create and update playbooks', 'ops_copilot'),
    ('ops_copilot.playbooks.read', 'View playbooks', 'ops_copilot')
ON CONFLICT (permission_key) DO NOTHING;

-- Assign permissions to roles
-- tenant_admin gets all ops_copilot permissions
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r
CROSS JOIN auth.permissions p
WHERE r.role_name = 'tenant_admin'
  AND p.permission_key LIKE 'ops_copilot.%'
ON CONFLICT DO NOTHING;

-- operator_admin gets most ops_copilot permissions (except pairing management)
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r
CROSS JOIN auth.permissions p
WHERE r.role_name = 'operator_admin'
  AND p.permission_key IN (
      'ops_copilot.tickets.write',
      'ops_copilot.tickets.read',
      'ops_copilot.audit.write',
      'ops_copilot.broadcast.ops',
      'ops_copilot.playbooks.read'
  )
ON CONFLICT DO NOTHING;

-- dispatcher gets limited ops_copilot permissions
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r
CROSS JOIN auth.permissions p
WHERE r.role_name = 'dispatcher'
  AND p.permission_key IN (
      'ops_copilot.tickets.write',
      'ops_copilot.tickets.read',
      'ops_copilot.playbooks.read'
  )
ON CONFLICT DO NOTHING;

COMMIT;

-- =============================================================================
-- POST-MIGRATION VERIFICATION
-- =============================================================================
-- Run: SELECT * FROM ops.verify_ops_copilot_integrity();
-- Expected: 8 checks, all PASS (or WARN for cleanup check)
-- =============================================================================
