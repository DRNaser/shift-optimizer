-- SOLVEREIGN Stripe Billing Schema (P1.1)
-- ========================================
--
-- B2B Invoice-first billing for DACH market.
-- Tracks Stripe customers, subscriptions, and invoices.
--
-- Usage:
--   psql $DATABASE_URL < backend_py/db/migrations/045_stripe_billing.sql

BEGIN;

-- =============================================================================
-- BILLING SCHEMA
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS billing;

-- Grant access
GRANT USAGE ON SCHEMA billing TO solvereign_platform, solvereign_api;

-- =============================================================================
-- STRIPE CUSTOMERS
-- =============================================================================

-- Link tenants to Stripe customers
CREATE TABLE IF NOT EXISTS billing.stripe_customers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE UNIQUE,
    stripe_customer_id TEXT NOT NULL UNIQUE,
    stripe_default_payment_method_id TEXT,
    billing_email TEXT NOT NULL,
    billing_name TEXT,
    billing_address JSONB,  -- {line1, line2, city, postal_code, country}
    tax_id TEXT,  -- VAT/UID number
    tax_exempt TEXT DEFAULT 'none' CHECK (tax_exempt IN ('none', 'exempt', 'reverse')),
    currency TEXT NOT NULL DEFAULT 'eur',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_stripe_customers_stripe_id ON billing.stripe_customers(stripe_customer_id);

-- =============================================================================
-- PRODUCTS & PRICES (cached from Stripe)
-- =============================================================================

-- Cache Stripe products for reference
CREATE TABLE IF NOT EXISTS billing.products (
    id SERIAL PRIMARY KEY,
    stripe_product_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Cache Stripe prices
CREATE TABLE IF NOT EXISTS billing.prices (
    id SERIAL PRIMARY KEY,
    stripe_price_id TEXT NOT NULL UNIQUE,
    product_id INTEGER REFERENCES billing.products(id),
    stripe_product_id TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'eur',
    unit_amount INTEGER,  -- Amount in cents
    recurring_interval TEXT CHECK (recurring_interval IN ('month', 'year')),
    recurring_interval_count INTEGER DEFAULT 1,
    billing_scheme TEXT DEFAULT 'per_unit' CHECK (billing_scheme IN ('per_unit', 'tiered')),
    tiers JSONB,  -- For tiered pricing
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_prices_product ON billing.prices(stripe_product_id);

-- =============================================================================
-- SUBSCRIPTIONS
-- =============================================================================

-- Track Stripe subscriptions
CREATE TABLE IF NOT EXISTS billing.subscriptions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES billing.stripe_customers(id),
    stripe_subscription_id TEXT NOT NULL UNIQUE,
    stripe_price_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'trialing', 'active', 'past_due', 'canceled',
        'unpaid', 'incomplete', 'incomplete_expired', 'paused'
    )),
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    canceled_at TIMESTAMPTZ,
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,
    quantity INTEGER DEFAULT 1,  -- e.g., number of seats/drivers
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_subscriptions_tenant ON billing.subscriptions(tenant_id);
CREATE INDEX idx_subscriptions_customer ON billing.subscriptions(customer_id);
CREATE INDEX idx_subscriptions_stripe_id ON billing.subscriptions(stripe_subscription_id);
CREATE INDEX idx_subscriptions_status ON billing.subscriptions(status);

-- =============================================================================
-- INVOICES
-- =============================================================================

-- Track Stripe invoices
CREATE TABLE IF NOT EXISTS billing.invoices (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES billing.stripe_customers(id),
    stripe_invoice_id TEXT NOT NULL UNIQUE,
    stripe_subscription_id TEXT,
    number TEXT,  -- Invoice number (e.g., SOLV-2026-0001)
    status TEXT NOT NULL CHECK (status IN (
        'draft', 'open', 'paid', 'void', 'uncollectible'
    )),
    currency TEXT NOT NULL DEFAULT 'eur',
    amount_due INTEGER NOT NULL,  -- In cents
    amount_paid INTEGER DEFAULT 0,
    amount_remaining INTEGER DEFAULT 0,
    tax INTEGER DEFAULT 0,
    total INTEGER NOT NULL,
    subtotal INTEGER NOT NULL,
    hosted_invoice_url TEXT,
    invoice_pdf TEXT,
    due_date TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_invoices_tenant ON billing.invoices(tenant_id);
CREATE INDEX idx_invoices_customer ON billing.invoices(customer_id);
CREATE INDEX idx_invoices_stripe_id ON billing.invoices(stripe_invoice_id);
CREATE INDEX idx_invoices_status ON billing.invoices(status);

-- =============================================================================
-- PAYMENT METHODS
-- =============================================================================

-- Track payment methods (cards, SEPA, etc.)
CREATE TABLE IF NOT EXISTS billing.payment_methods (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES billing.stripe_customers(id) ON DELETE CASCADE,
    stripe_payment_method_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('card', 'sepa_debit', 'bank_transfer')),
    is_default BOOLEAN DEFAULT FALSE,
    card_brand TEXT,  -- visa, mastercard, etc.
    card_last4 TEXT,
    card_exp_month INTEGER,
    card_exp_year INTEGER,
    sepa_last4 TEXT,
    sepa_bank_code TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payment_methods_customer ON billing.payment_methods(customer_id);

-- =============================================================================
-- WEBHOOK EVENTS (idempotency)
-- =============================================================================

-- Track processed webhook events to prevent duplicates
CREATE TABLE IF NOT EXISTS billing.webhook_events (
    id SERIAL PRIMARY KEY,
    stripe_event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_hash TEXT,  -- For debugging
    error TEXT  -- If processing failed
);

CREATE INDEX idx_webhook_events_type ON billing.webhook_events(event_type);
CREATE INDEX idx_webhook_events_processed ON billing.webhook_events(processed_at);

-- Cleanup old webhook events (keep 90 days)
CREATE OR REPLACE FUNCTION billing.cleanup_old_webhook_events()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM billing.webhook_events
    WHERE processed_at < NOW() - INTERVAL '90 days';
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- BILLING STATUS HELPERS
-- =============================================================================

-- Get tenant's current billing status
CREATE OR REPLACE FUNCTION billing.get_tenant_billing_status(p_tenant_id INTEGER)
RETURNS TABLE (
    has_customer BOOLEAN,
    subscription_status TEXT,
    is_active BOOLEAN,
    is_trialing BOOLEAN,
    is_past_due BOOLEAN,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id IS NOT NULL AS has_customer,
        COALESCE(s.status, 'none') AS subscription_status,
        COALESCE(s.status IN ('active', 'trialing'), FALSE) AS is_active,
        COALESCE(s.status = 'trialing', FALSE) AS is_trialing,
        COALESCE(s.status = 'past_due', FALSE) AS is_past_due,
        s.current_period_end,
        COALESCE(s.cancel_at_period_end, FALSE)
    FROM tenants t
    LEFT JOIN billing.stripe_customers c ON c.tenant_id = t.id
    LEFT JOIN billing.subscriptions s ON s.tenant_id = t.id
        AND s.status NOT IN ('canceled', 'incomplete_expired')
    WHERE t.id = p_tenant_id
    ORDER BY s.created_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

-- Check if tenant has active subscription (for gating)
CREATE OR REPLACE FUNCTION billing.is_subscription_active(p_tenant_id INTEGER)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM billing.subscriptions
        WHERE tenant_id = p_tenant_id
          AND status IN ('active', 'trialing')
    );
$$ LANGUAGE SQL STABLE;

-- Get tenant's grace period status (for past_due)
CREATE OR REPLACE FUNCTION billing.is_in_grace_period(p_tenant_id INTEGER)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM billing.subscriptions s
        WHERE s.tenant_id = p_tenant_id
          AND s.status = 'past_due'
          -- Grace period: 14 days after period end
          AND s.current_period_end + INTERVAL '14 days' > NOW()
    );
$$ LANGUAGE SQL STABLE;

-- =============================================================================
-- EXTEND TENANTS TABLE
-- =============================================================================

-- Add billing-related columns to tenants
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS billing_plan TEXT DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS billing_status TEXT DEFAULT 'none'
        CHECK (billing_status IN ('none', 'trialing', 'active', 'past_due', 'canceled', 'suspended'));

-- Index for billing queries
CREATE INDEX IF NOT EXISTS idx_tenants_billing_status ON tenants(billing_status);

-- =============================================================================
-- RLS POLICIES
-- =============================================================================

-- Enable RLS on all billing tables
ALTER TABLE billing.stripe_customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.payment_methods ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.webhook_events ENABLE ROW LEVEL SECURITY;

-- Platform admin can access everything
CREATE POLICY billing_customers_platform ON billing.stripe_customers
    FOR ALL TO solvereign_platform USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY billing_products_platform ON billing.products
    FOR ALL TO solvereign_platform USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY billing_prices_platform ON billing.prices
    FOR ALL TO solvereign_platform USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY billing_subscriptions_platform ON billing.subscriptions
    FOR ALL TO solvereign_platform USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY billing_invoices_platform ON billing.invoices
    FOR ALL TO solvereign_platform USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY billing_payment_methods_platform ON billing.payment_methods
    FOR ALL TO solvereign_platform USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY billing_webhook_events_platform ON billing.webhook_events
    FOR ALL TO solvereign_platform USING (TRUE) WITH CHECK (TRUE);

-- Tenants can view their own billing data
CREATE POLICY billing_customers_tenant ON billing.stripe_customers
    FOR SELECT TO solvereign_api
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::INTEGER);

CREATE POLICY billing_subscriptions_tenant ON billing.subscriptions
    FOR SELECT TO solvereign_api
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::INTEGER);

CREATE POLICY billing_invoices_tenant ON billing.invoices
    FOR SELECT TO solvereign_api
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::INTEGER);

-- Products and prices are public (catalog)
CREATE POLICY billing_products_public ON billing.products
    FOR SELECT TO solvereign_api USING (is_active = TRUE);

CREATE POLICY billing_prices_public ON billing.prices
    FOR SELECT TO solvereign_api USING (is_active = TRUE);

-- =============================================================================
-- VERIFICATION
-- =============================================================================

CREATE OR REPLACE FUNCTION billing.verify_billing_schema()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Schema exists
    check_name := 'billing_schema';
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'billing') THEN
        status := 'PASS';
        details := 'Schema exists';
    ELSE
        status := 'FAIL';
        details := 'Schema missing';
    END IF;
    RETURN NEXT;

    -- Check 2: Core tables exist
    check_name := 'core_tables';
    IF (SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'billing'
        AND table_name IN ('stripe_customers', 'subscriptions', 'invoices')) = 3 THEN
        status := 'PASS';
        details := 'All core tables exist';
    ELSE
        status := 'FAIL';
        details := 'Missing tables';
    END IF;
    RETURN NEXT;

    -- Check 3: RLS enabled
    check_name := 'rls_enabled';
    IF (SELECT bool_and(relrowsecurity) FROM pg_class
        WHERE relname IN ('stripe_customers', 'subscriptions', 'invoices')
        AND relnamespace = 'billing'::regnamespace) THEN
        status := 'PASS';
        details := 'RLS enabled on all tables';
    ELSE
        status := 'FAIL';
        details := 'RLS not enabled on some tables';
    END IF;
    RETURN NEXT;

    -- Check 4: Helper functions exist
    check_name := 'helper_functions';
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'is_subscription_active' AND pronamespace = 'billing'::regnamespace) THEN
        status := 'PASS';
        details := 'Helper functions exist';
    ELSE
        status := 'FAIL';
        details := 'Helper functions missing';
    END IF;
    RETURN NEXT;

    -- Check 5: Tenants billing columns
    check_name := 'tenants_billing_columns';
    IF EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tenants' AND column_name = 'billing_status') THEN
        status := 'PASS';
        details := 'billing_status column exists';
    ELSE
        status := 'FAIL';
        details := 'billing_status column missing';
    END IF;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Run verification
SELECT * FROM billing.verify_billing_schema();

COMMIT;
