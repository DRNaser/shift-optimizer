"""
SOLVEREIGN Billing Gating Boundary Tests (GA Blocker B2)
=========================================================

Tests for billing gating path matching to ensure:
1. Boundary-aware matching (no prefix bypass attacks)
2. Consistent path normalization
3. All exempted paths work correctly
4. Paid feature paths are properly gated

Security invariant: /api/authXYZ must NOT match /api/auth exemption.
"""

import pytest
from ..billing.gating import BillingGate, BillingStatus


class TestPathBoundaryMatching:
    """
    Tests that path matching is boundary-aware.

    Security: Attackers should not bypass billing by appending to allowed paths.
    """

    @pytest.fixture
    def gate(self):
        return BillingGate()

    # =========================================================================
    # ALLOWED PATHS - Must bypass billing
    # =========================================================================

    @pytest.mark.parametrize("path", [
        "/api/auth",
        "/api/auth/",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
    ])
    def test_auth_paths_allowed(self, gate, path):
        """Auth paths must bypass billing gating."""
        assert gate.is_always_allowed(path), f"{path} should be allowed"

    @pytest.mark.parametrize("path", [
        "/api/platform",
        "/api/platform/",
        "/api/platform/tenants",
        "/api/platform/users",
        "/api/platform/context",
    ])
    def test_platform_paths_allowed(self, gate, path):
        """Platform admin paths must bypass billing gating."""
        assert gate.is_always_allowed(path), f"{path} should be allowed"

    @pytest.mark.parametrize("path", [
        "/api/portal",
        "/api/portal/",
        "/api/portal/session",
        "/api/portal/read",
        "/api/portal/ack",
    ])
    def test_portal_paths_allowed(self, gate, path):
        """Portal paths must bypass billing gating."""
        assert gate.is_always_allowed(path), f"{path} should be allowed"

    @pytest.mark.parametrize("path", [
        "/api/health",
        "/api/health/",
        "/api/health/ready",
        "/api/health/live",
    ])
    def test_health_paths_allowed(self, gate, path):
        """Health check paths must bypass billing gating."""
        assert gate.is_always_allowed(path), f"{path} should be allowed"

    @pytest.mark.parametrize("path", [
        "/api/billing",
        "/api/billing/",
        "/api/billing/webhooks",
        "/api/billing/webhooks/stripe",
        "/api/billing/subscription",
    ])
    def test_billing_paths_allowed(self, gate, path):
        """Billing management paths must bypass billing gating."""
        assert gate.is_always_allowed(path), f"{path} should be allowed"

    @pytest.mark.parametrize("path", [
        "/api/consent",
        "/api/consent/",
        "/api/consent/gdpr",
    ])
    def test_consent_paths_allowed(self, gate, path):
        """GDPR consent paths must bypass billing gating."""
        assert gate.is_always_allowed(path), f"{path} should be allowed"

    @pytest.mark.parametrize("path", [
        "/docs",
        "/docs/",
        "/openapi.json",
        "/health",
        "/metrics",
    ])
    def test_infrastructure_paths_allowed(self, gate, path):
        """Infrastructure paths must bypass billing gating."""
        assert gate.is_always_allowed(path), f"{path} should be allowed"

    # =========================================================================
    # BOUNDARY ATTACKS - Must NOT bypass billing
    # =========================================================================

    @pytest.mark.parametrize("path", [
        "/api/authXYZ",
        "/api/auth_fake",
        "/api/authentication",
        "/api/authorize",
    ])
    def test_auth_boundary_attack_blocked(self, gate, path):
        """
        Paths starting with 'auth' but not under /api/auth/ must be blocked.

        Security: Prevents bypass via /api/authMalicious.
        """
        assert not gate.is_always_allowed(path), f"{path} should NOT be allowed"

    @pytest.mark.parametrize("path", [
        "/api/platformXYZ",
        "/api/platform_admin_bypass",
        "/api/platforms",
    ])
    def test_platform_boundary_attack_blocked(self, gate, path):
        """Platform boundary attacks must be blocked."""
        assert not gate.is_always_allowed(path), f"{path} should NOT be allowed"

    @pytest.mark.parametrize("path", [
        "/api/portalXYZ",
        "/api/portal_bypass",
        "/api/portals",
    ])
    def test_portal_boundary_attack_blocked(self, gate, path):
        """Portal boundary attacks must be blocked."""
        assert not gate.is_always_allowed(path), f"{path} should NOT be allowed"

    @pytest.mark.parametrize("path", [
        "/api/healthXYZ",
        "/api/health_check_bypass",
        "/api/healthy",
    ])
    def test_health_boundary_attack_blocked(self, gate, path):
        """Health boundary attacks must be blocked."""
        assert not gate.is_always_allowed(path), f"{path} should NOT be allowed"

    @pytest.mark.parametrize("path", [
        "/api/billingXYZ",
        "/api/billing_bypass",
        "/api/billings",
    ])
    def test_billing_boundary_attack_blocked(self, gate, path):
        """Billing boundary attacks must be blocked."""
        assert not gate.is_always_allowed(path), f"{path} should NOT be allowed"

    @pytest.mark.parametrize("path", [
        "/api/consentXYZ",
        "/api/consent_bypass",
        "/api/consents",
    ])
    def test_consent_boundary_attack_blocked(self, gate, path):
        """Consent boundary attacks must be blocked."""
        assert not gate.is_always_allowed(path), f"{path} should NOT be allowed"

    # =========================================================================
    # PAID FEATURES - Must require subscription
    # =========================================================================

    @pytest.mark.parametrize("path", [
        "/api/v1/solver/",
        "/api/v1/solver/run",
        "/api/v1/roster/",
        "/api/v1/roster/plans",
        "/api/v1/dispatch/",
        "/api/v1/forecast/",
    ])
    def test_paid_feature_paths_require_subscription(self, gate, path):
        """Paid feature paths must require subscription."""
        assert gate.requires_paid_subscription(path), f"{path} should require subscription"
        assert not gate.is_always_allowed(path), f"{path} should NOT be always allowed"


class TestBillingStatusAccess:
    """
    Tests for access control based on billing status.
    """

    @pytest.fixture
    def gate(self):
        return BillingGate()

    @pytest.mark.parametrize("status", [
        BillingStatus.ACTIVE,
        BillingStatus.TRIALING,
    ])
    def test_active_statuses_full_access(self, gate, status):
        """Active and trialing subscriptions have full access."""
        # Read access
        allowed, reason = gate.can_access(status, is_write_operation=False)
        assert allowed, f"{status} should allow reads"
        assert reason is None

        # Write access
        allowed, reason = gate.can_access(status, is_write_operation=True)
        assert allowed, f"{status} should allow writes"
        assert reason is None

    def test_past_due_read_only(self, gate):
        """Past due subscriptions have read-only access."""
        # Read access allowed
        allowed, reason = gate.can_access(BillingStatus.PAST_DUE, is_write_operation=False)
        assert allowed, "Past due should allow reads"

        # Write access blocked
        allowed, reason = gate.can_access(BillingStatus.PAST_DUE, is_write_operation=True)
        assert not allowed, "Past due should block writes"
        assert "payment" in reason.lower()

    def test_canceled_read_only(self, gate):
        """Canceled subscriptions have read-only access until period end."""
        # Read access allowed
        allowed, reason = gate.can_access(BillingStatus.CANCELED, is_write_operation=False)
        assert allowed, "Canceled should allow reads"

        # Write access blocked
        allowed, reason = gate.can_access(BillingStatus.CANCELED, is_write_operation=True)
        assert not allowed, "Canceled should block writes"
        assert "cancel" in reason.lower() or "reactivate" in reason.lower()

    @pytest.mark.parametrize("status", [
        BillingStatus.NONE,
        BillingStatus.SUSPENDED,
    ])
    def test_no_subscription_blocked(self, gate, status):
        """No subscription or suspended blocks all access."""
        # Read access blocked
        allowed, reason = gate.can_access(status, is_write_operation=False)
        assert not allowed, f"{status} should block reads"
        assert "subscription" in reason.lower()

        # Write access blocked
        allowed, reason = gate.can_access(status, is_write_operation=True)
        assert not allowed, f"{status} should block writes"


class TestPathNormalization:
    """
    Tests for consistent path normalization.
    """

    @pytest.fixture
    def gate(self):
        return BillingGate()

    def test_trailing_slash_normalization(self, gate):
        """Trailing slashes should not affect matching."""
        # Both should be equivalent
        assert gate.is_always_allowed("/api/auth") == gate.is_always_allowed("/api/auth/")
        assert gate.is_always_allowed("/api/platform") == gate.is_always_allowed("/api/platform/")

    def test_root_path_handling(self, gate):
        """Root path / should be handled correctly."""
        # Root is not in allowed list
        result = gate.is_always_allowed("/")
        # Just ensure it doesn't crash
        assert isinstance(result, bool)

    def test_empty_path_handling(self, gate):
        """Empty path should be handled gracefully."""
        result = gate.is_always_allowed("")
        assert isinstance(result, bool)


class TestBreakGlassEnforcement:
    """
    Tests for billing enforcement break glass.
    """

    def test_enforcement_env_var_respected(self):
        """SOLVEREIGN_BILLING_ENFORCEMENT=off should bypass all checks."""
        import os
        from importlib import reload
        from ..billing import gating as gating_module

        # Save original value
        original = os.environ.get("SOLVEREIGN_BILLING_ENFORCEMENT")

        try:
            # Test with enforcement off
            os.environ["SOLVEREIGN_BILLING_ENFORCEMENT"] = "off"

            # Reload module to pick up new env var
            reload(gating_module)

            assert not gating_module.BILLING_ENFORCEMENT_ENABLED

        finally:
            # Restore original value
            if original is not None:
                os.environ["SOLVEREIGN_BILLING_ENFORCEMENT"] = original
            else:
                os.environ.pop("SOLVEREIGN_BILLING_ENFORCEMENT", None)

            # Reload to restore original state
            reload(gating_module)
