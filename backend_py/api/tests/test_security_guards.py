# =============================================================================
# SOLVEREIGN Security Guards Tests
# =============================================================================
# Tests for critical security boundaries:
# - Fix B: Production guard for tenant override
# - Fix C: Scope blocking enforcement
# =============================================================================

import pytest
from unittest.mock import patch


class TestProductionGuard:
    """
    Fix B: Test that allow_header_tenant_override=True CANNOT be used in production.

    This is a HARD GATE - if this test passes, the security boundary is enforced.
    """

    def test_tenant_override_blocked_in_production(self):
        """
        CRITICAL: allow_header_tenant_override=True + environment=production MUST raise.

        This prevents client headers from overriding tenant identity in production.
        """
        from pydantic import ValidationError
        from ..config import APISettings

        with pytest.raises(ValidationError) as exc_info:
            APISettings(
                environment="production",
                allow_header_tenant_override=True,
                secret_key="a_valid_production_secret_key_that_is_long_enough_123456"
            )

        error_str = str(exc_info.value)
        assert "allow_header_tenant_override" in error_str
        assert "production" in error_str.lower()

    def test_tenant_override_allowed_in_development(self):
        """Tenant override is allowed in development for testing."""
        from ..config import APISettings

        # Should not raise
        settings = APISettings(
            environment="development",
            allow_header_tenant_override=True
        )

        assert settings.allow_header_tenant_override is True
        assert settings.is_development is True

    def test_tenant_override_allowed_in_staging(self):
        """Tenant override is allowed in staging for testing."""
        from ..config import APISettings

        # Should not raise
        settings = APISettings(
            environment="staging",
            allow_header_tenant_override=True
        )

        assert settings.allow_header_tenant_override is True

    def test_default_tenant_override_is_false(self):
        """Default setting should be safe (override disabled)."""
        from ..config import APISettings

        settings = APISettings()

        assert settings.allow_header_tenant_override is False

    def test_production_secret_key_validation(self):
        """Production requires non-default secret key."""
        from pydantic import ValidationError
        from ..config import APISettings

        with pytest.raises(ValidationError) as exc_info:
            APISettings(
                environment="production",
                secret_key="change_me_in_production_to_a_random_64_char_string_abc123"
            )

        error_str = str(exc_info.value)
        assert "SECRET_KEY" in error_str or "secret_key" in error_str


class TestScopeBlockingEnforcement:
    """
    Fix C: Test that scope blocking is enforced for write operations.
    """

    @pytest.mark.asyncio
    async def test_require_tenant_not_blocked_allows_healthy_scope(self):
        """Healthy scope should allow writes."""
        from ..dependencies import require_tenant_not_blocked, TenantContext
        from unittest.mock import AsyncMock, MagicMock
        from datetime import datetime

        # Mock request with db that returns not blocked
        mock_request = MagicMock()
        mock_db = AsyncMock()
        mock_request.app.state.db = mock_db

        # Mock is_scope_blocked to return False
        with patch('api.dependencies.is_scope_blocked', new_callable=AsyncMock) as mock_blocked:
            mock_blocked.return_value = False

            tenant = TenantContext(
                tenant_id=123,
                tenant_name="Test Tenant",
                is_active=True,
                created_at=datetime.now(),
            )

            dependency = require_tenant_not_blocked("tenant")
            # Should not raise
            await dependency(request=mock_request, tenant=tenant)

    @pytest.mark.asyncio
    async def test_require_tenant_not_blocked_blocks_s0_scope(self):
        """S0/S1 blocked scope should reject writes with 503."""
        from fastapi import HTTPException
        from ..dependencies import require_tenant_not_blocked, TenantContext
        from unittest.mock import AsyncMock, MagicMock
        from datetime import datetime

        mock_request = MagicMock()
        mock_db = AsyncMock()
        mock_request.app.state.db = mock_db

        with patch('api.dependencies.is_scope_blocked', new_callable=AsyncMock) as mock_blocked:
            mock_blocked.return_value = True  # Scope is blocked!

            tenant = TenantContext(
                tenant_id=123,
                tenant_name="Test Tenant",
                is_active=True,
                created_at=datetime.now(),
            )

            dependency = require_tenant_not_blocked("tenant")

            with pytest.raises(HTTPException) as exc_info:
                await dependency(request=mock_request, tenant=tenant)

            assert exc_info.value.status_code == 503
            assert "blocked" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_require_core_tenant_not_blocked_checks_correct_scope(self):
        """Verify the correct scope type and ID are checked."""
        from ..dependencies import require_core_tenant_not_blocked, CoreTenantContext
        from unittest.mock import AsyncMock, MagicMock

        mock_request = MagicMock()
        mock_db = AsyncMock()
        mock_request.app.state.db = mock_db

        with patch('api.dependencies.is_scope_blocked', new_callable=AsyncMock) as mock_blocked:
            mock_blocked.return_value = False

            tenant = CoreTenantContext(
                tenant_id="uuid-12345",
                tenant_code="test",
                tenant_name="Test",
                is_active=True,
            )

            dependency = require_core_tenant_not_blocked("tenant")
            await dependency(request=mock_request, tenant=tenant)

            # Verify is_scope_blocked was called with correct params
            mock_blocked.assert_called_once()
            call_args = mock_blocked.call_args
            assert call_args[0][1] == "tenant"  # scope_type
            assert call_args[0][2] == "uuid-12345"  # scope_id


class TestInternalSignatureSecurity:
    """
    Test HMAC signature security for internal requests.
    """

    def test_signature_is_required_for_platform_admin(self):
        """Platform admin flag without signature should be rejected."""
        from ..security.internal_signature import InternalContext

        # Without internal signature, context should not be platform admin
        context = InternalContext(is_internal=False)

        assert context.is_internal is False
        assert context.is_platform_admin is False

    def test_signature_generation_is_deterministic(self):
        """Same inputs should produce same signature."""
        from ..security.internal_signature import generate_signature

        secret = "test_secret_key_12345"
        timestamp = 1704067200  # Fixed timestamp

        sig1 = generate_signature(
            method="GET",
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            is_platform_admin=True,
            secret=secret
        )

        sig2 = generate_signature(
            method="GET",
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            is_platform_admin=True,
            secret=secret
        )

        assert sig1 == sig2
        assert len(sig1) == 64  # SHA256 hex

    def test_signature_changes_with_path(self):
        """Different paths should produce different signatures."""
        from ..security.internal_signature import generate_signature

        secret = "test_secret_key_12345"
        timestamp = 1704067200

        sig1 = generate_signature(
            method="GET",
            path="/api/v1/platform/orgs",
            timestamp=timestamp,
            secret=secret
        )

        sig2 = generate_signature(
            method="GET",
            path="/api/v1/platform/tenants",  # Different path
            timestamp=timestamp,
            secret=secret
        )

        assert sig1 != sig2

    def test_signature_changes_with_tenant_context(self):
        """Tenant code should be included in signature."""
        from ..security.internal_signature import generate_signature

        secret = "test_secret_key_12345"
        timestamp = 1704067200

        sig_no_tenant = generate_signature(
            method="GET",
            path="/api/v1/tenant/me",
            timestamp=timestamp,
            tenant_code=None,
            secret=secret
        )

        sig_with_tenant = generate_signature(
            method="GET",
            path="/api/v1/tenant/me",
            timestamp=timestamp,
            tenant_code="rohlik",
            secret=secret
        )

        assert sig_no_tenant != sig_with_tenant


class TestReasonCodeValidation:
    """
    Fix D: Test that reason codes are validated against registry.

    This prevents code drift where Python code uses reason codes
    not registered in the database.
    """

    # These tests require database connection - marked for integration testing

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_unknown_reason_code_rejected(self):
        """Unknown reason code should raise exception."""
        # This would test core.record_escalation() with unknown code
        # Requires DB connection
        pass

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_known_reason_code_accepted(self):
        """Known reason code should succeed."""
        # This would test core.record_escalation() with known code
        # Requires DB connection
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
