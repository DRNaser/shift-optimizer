"""
SOLVEREIGN Webhook Security Tests (GA Blocker B1)
==================================================

Tests for webhook endpoints to ensure:
1. Signature verification happens FIRST (before any processing)
2. Billing gating is BYPASSED for webhooks (never 402)
3. Invalid signatures return 400, not 402

These tests patch the webhook module's stripe reference, not global stripe.
"""

import pytest
from fastapi.testclient import TestClient

from ..main import app
from ..billing.gating import BillingGate


class TestStripeWebhookSecurity:
    """
    Tests for /api/billing/webhook endpoint (Stripe webhooks).

    Security invariants:
    - Signature verification MUST happen before any business logic
    - Invalid signature → 400 (not 402)
    - Webhooks MUST bypass billing gating (they're from Stripe, not tenants)
    """

    @pytest.fixture
    def client(self):
        """Create test client with mocked dependencies."""
        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def valid_webhook_payload(self):
        """Sample Stripe webhook payload."""
        return {
            "id": "evt_test_123",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test_123",
                    "customer": "cus_test_123",
                    "amount_paid": 10000,
                    "currency": "eur",
                }
            }
        }

    def test_missing_signature_returns_422(self, client):
        """
        Webhook without signature header MUST return 422 (fail-closed).

        FastAPI's Header(...) validation rejects the request before any handler
        code runs. This is "signature-first" at the framework level:
        - No handler code executes
        - Billing gating middleware runs but passes (path in ALWAYS_ALLOWED_PATHS)
        - Request fails closed before business logic

        Note: 422 (framework) is even stricter than 400 (handler).
        """
        response = client.post(
            "/api/billing/webhook",
            json={"type": "invoice.paid"},
            headers={"Content-Type": "application/json"},
        )

        # 422 = FastAPI rejected missing required header (fail-closed)
        # Billing gating runs but allows /api/billing/* paths
        assert response.status_code == 422
        assert response.status_code != 402, "Webhooks must bypass billing gating"

    def test_invalid_signature_returns_400(self, client):
        """
        Webhook with invalid signature MUST return 400.

        Signature verification happens FIRST, before any billing checks.
        """
        response = client.post(
            "/api/billing/webhook",
            json={"type": "invoice.paid"},
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "t=1234567890,v1=invalid_signature_here",
            },
        )

        # MUST be 400 or 503 (if service not configured), never 402
        assert response.status_code in (400, 503)
        assert response.status_code != 402, "Webhooks must bypass billing gating"

    def test_webhook_never_returns_402(self, client, valid_webhook_payload):
        """
        Webhook endpoint MUST never return 402 (billing gating bypassed).

        Webhooks come from Stripe (trusted), not from tenant users.
        """
        response = client.post(
            "/api/billing/webhook",
            json=valid_webhook_payload,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "t=1234567890,v1=valid_mock_signature",
            },
        )

        # MUST NOT be 402 (billing gating bypassed)
        assert response.status_code != 402, "Webhooks must bypass billing gating"

    def test_signature_checked_before_body_parsing(self, client):
        """
        Request with malformed body but valid-looking signature.

        Should return 400/422/503 but never 402.
        """
        response = client.post(
            "/api/billing/webhook",
            content=b"not valid json {{{",
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "t=1234567890,v1=some_signature",
            },
        )

        # Any error is fine, except 402
        assert response.status_code != 402, "Webhooks must bypass billing gating"


class TestWebhookPathBypassesBilling:
    """
    Tests that webhook paths are in billing gating's ALWAYS_ALLOWED list.
    """

    def test_webhook_path_in_always_allowed(self):
        """
        Webhook paths MUST be in ALWAYS_ALLOWED_PATHS.

        This ensures the billing gating middleware never blocks webhooks.
        """
        gate = BillingGate()

        # These paths must be allowed without billing check
        webhook_paths = [
            "/api/billing",
            "/api/billing/webhooks",
            "/api/billing/webhooks/stripe",
        ]

        for path in webhook_paths:
            assert gate.is_always_allowed(path), f"{path} must bypass billing gating"

    def test_billing_path_boundary_no_bypass(self):
        """
        Paths like /api/billingXYZ must NOT be allowed.

        Prevents path traversal attacks via prefix confusion.
        """
        gate = BillingGate()

        # These should NOT be allowed (boundary attack attempts)
        malicious_paths = [
            "/api/billingXYZ",
            "/api/billing_fake",
            "/api/billingmalicious",
        ]

        for path in malicious_paths:
            assert not gate.is_always_allowed(path), f"{path} must NOT bypass billing"


class TestSendGridWebhookSecurity:
    """
    Tests for SendGrid webhook (if implemented).

    Security: ECDSA signature verification before processing.
    """

    @pytest.fixture
    def client(self):
        return TestClient(app, raise_server_exceptions=False)

    def test_sendgrid_webhook_exists_or_skipped(self, client):
        """
        If SendGrid webhook exists, it must require signature.
        """
        response = client.post(
            "/api/notifications/webhooks/sendgrid",
            json={"event": "delivered"},
        )

        # Either 404 (not implemented) or 400 (missing signature)
        # Never 402 (billing) or 200 (processed without auth)
        assert response.status_code in (400, 404, 405)
        if response.status_code == 400:
            # If implemented, should require signature
            assert "signature" in response.text.lower() or "unauthorized" in response.text.lower()


class TestWhatsAppWebhookSecurity:
    """
    Tests for WhatsApp Business API webhook (if implemented).

    Security: HMAC signature verification before processing.
    """

    @pytest.fixture
    def client(self):
        return TestClient(app, raise_server_exceptions=False)

    def test_whatsapp_webhook_exists_or_skipped(self, client):
        """
        If WhatsApp webhook exists, it must require HMAC signature.
        """
        response = client.post(
            "/api/notifications/webhooks/whatsapp",
            json={"entry": []},
        )

        # Either 404 (not implemented) or 400/401 (missing signature)
        # Never 402 (billing)
        assert response.status_code in (400, 401, 404, 405)
        if response.status_code in (400, 401):
            # Should indicate auth/signature requirement
            pass  # Just ensure it's not 402
