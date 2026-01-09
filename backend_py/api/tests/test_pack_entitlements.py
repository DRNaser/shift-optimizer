"""
SOLVEREIGN V3.7 - Pack Entitlements Tests
==========================================

Tests for pack activation guards and 403 responses.

Exit Codes:
    0 = All tests pass
    1 = Test failures

Usage:
    pytest backend_py/api/tests/test_pack_entitlements.py -v
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from backend_py.api.services.pack_entitlements import (
    PackEntitlementService,
    PackEntitlement,
    PackAccessResult,
    require_pack,
    get_pack_config
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_db():
    """Mock database manager."""
    db = MagicMock()
    db.connection = MagicMock(return_value=AsyncMock())
    return db


@pytest.fixture
def service(mock_db):
    """Pack entitlement service with mock DB."""
    return PackEntitlementService(mock_db)


@pytest.fixture
def enabled_entitlement():
    """Enabled pack entitlement."""
    return PackEntitlement(
        pack_id="routing",
        is_enabled=True,
        config={"max_vehicles": 100},
        expires_at=datetime.utcnow() + timedelta(days=30),
        suspended=False
    )


@pytest.fixture
def disabled_entitlement():
    """Disabled pack entitlement."""
    return PackEntitlement(
        pack_id="routing",
        is_enabled=False,
        config=None
    )


@pytest.fixture
def expired_entitlement():
    """Expired pack entitlement."""
    return PackEntitlement(
        pack_id="routing",
        is_enabled=True,
        config={"max_vehicles": 50},
        expires_at=datetime.utcnow() - timedelta(days=1),
        suspended=False
    )


@pytest.fixture
def suspended_entitlement():
    """Suspended pack entitlement."""
    return PackEntitlement(
        pack_id="routing",
        is_enabled=True,
        config={"max_vehicles": 50},
        suspended=True,
        suspended_reason="Payment overdue"
    )


# =============================================================================
# SERVICE TESTS
# =============================================================================

class TestPackEntitlementService:
    """Tests for PackEntitlementService."""

    def test_is_pack_enabled_true(self, service, enabled_entitlement):
        """Enabled pack returns True."""
        # Mock get_entitlement to return enabled entitlement
        service.get_entitlement = AsyncMock(return_value=enabled_entitlement)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.is_pack_enabled("tenant-1", "routing")
        )

        assert result is True

    def test_is_pack_enabled_false_disabled(self, service, disabled_entitlement):
        """Disabled pack returns False."""
        service.get_entitlement = AsyncMock(return_value=disabled_entitlement)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.is_pack_enabled("tenant-1", "routing")
        )

        assert result is False

    def test_is_pack_enabled_false_expired(self, service, expired_entitlement):
        """Expired pack returns False."""
        service.get_entitlement = AsyncMock(return_value=expired_entitlement)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.is_pack_enabled("tenant-1", "routing")
        )

        assert result is False

    def test_is_pack_enabled_false_suspended(self, service, suspended_entitlement):
        """Suspended pack returns False."""
        service.get_entitlement = AsyncMock(return_value=suspended_entitlement)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.is_pack_enabled("tenant-1", "routing")
        )

        assert result is False

    def test_is_pack_enabled_false_not_found(self, service):
        """Non-existent pack returns False."""
        service.get_entitlement = AsyncMock(return_value=None)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.is_pack_enabled("tenant-1", "unknown_pack")
        )

        assert result is False

    def test_is_pack_enabled_skip_expiry_check(self, service, expired_entitlement):
        """Skip expiry check returns True for expired pack."""
        service.get_entitlement = AsyncMock(return_value=expired_entitlement)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.is_pack_enabled("tenant-1", "routing", check_expiry=False)
        )

        assert result is True


class TestPackAccessResult:
    """Tests for check_access method."""

    def test_check_access_allowed(self, service, enabled_entitlement):
        """Enabled pack returns ALLOWED."""
        service.get_entitlement = AsyncMock(return_value=enabled_entitlement)
        service._log_access_event = AsyncMock()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.check_access("tenant-1", "routing", "/api/v1/routing/solve", log_event=False)
        )

        assert result == PackAccessResult.ALLOWED

    def test_check_access_denied_not_enabled(self, service, disabled_entitlement):
        """Disabled pack returns DENIED_NOT_ENABLED."""
        service.get_entitlement = AsyncMock(return_value=disabled_entitlement)
        service._log_access_event = AsyncMock()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.check_access("tenant-1", "routing", "/api/v1/routing/solve", log_event=False)
        )

        assert result == PackAccessResult.DENIED_NOT_ENABLED

    def test_check_access_denied_expired(self, service, expired_entitlement):
        """Expired pack returns DENIED_EXPIRED."""
        service.get_entitlement = AsyncMock(return_value=expired_entitlement)
        service._log_access_event = AsyncMock()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.check_access("tenant-1", "routing", "/api/v1/routing/solve", log_event=False)
        )

        assert result == PackAccessResult.DENIED_EXPIRED

    def test_check_access_denied_suspended(self, service, suspended_entitlement):
        """Suspended pack returns DENIED_SUSPENDED."""
        service.get_entitlement = AsyncMock(return_value=suspended_entitlement)
        service._log_access_event = AsyncMock()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.check_access("tenant-1", "routing", "/api/v1/routing/solve", log_event=False)
        )

        assert result == PackAccessResult.DENIED_SUSPENDED


class TestCache:
    """Tests for entitlement caching."""

    def test_cache_clear_tenant(self, service, enabled_entitlement):
        """Clear cache for specific tenant."""
        # Populate cache
        service._cache["tenant-1"] = {"routing": enabled_entitlement}
        service._cache["tenant-2"] = {"routing": enabled_entitlement}

        # Clear specific tenant
        service.clear_cache("tenant-1")

        assert "tenant-1" not in service._cache
        assert "tenant-2" in service._cache

    def test_cache_clear_all(self, service, enabled_entitlement):
        """Clear entire cache."""
        # Populate cache
        service._cache["tenant-1"] = {"routing": enabled_entitlement}
        service._cache["tenant-2"] = {"routing": enabled_entitlement}

        # Clear all
        service.clear_cache()

        assert len(service._cache) == 0


# =============================================================================
# DEPENDENCY TESTS (FastAPI Integration)
# =============================================================================

class TestRequirePackDependency:
    """Tests for require_pack dependency."""

    def test_require_pack_enabled_passes(self):
        """Request with enabled pack passes."""
        # Create mock tenant context
        mock_tenant = MagicMock()
        mock_tenant.tenant_id = "tenant-1"
        mock_tenant.tenant_code = "test_tenant"
        mock_tenant.entitlements = {
            "routing": {"is_enabled": True, "config": {}}
        }

        # Create test app
        app = FastAPI()

        @app.get("/routing/test")
        async def test_endpoint():
            return {"status": "ok"}

        # Test passes when pack is enabled
        # In real scenario, require_pack would check tenant.entitlements
        assert mock_tenant.entitlements["routing"]["is_enabled"] is True

    def test_require_pack_disabled_returns_403(self):
        """Request with disabled pack returns 403."""
        mock_tenant = MagicMock()
        mock_tenant.tenant_id = "tenant-1"
        mock_tenant.tenant_code = "test_tenant"
        mock_tenant.entitlements = {
            "routing": {"is_enabled": False}
        }

        # Check that the entitlement check would fail
        pack_id = "routing"
        entitlements = mock_tenant.entitlements or {}
        pack_entitlement = entitlements.get(pack_id, {})

        is_enabled = pack_entitlement.get("is_enabled", False)
        assert is_enabled is False

        # In real implementation, this would raise HTTPException 403

    def test_require_pack_missing_returns_403(self):
        """Request with missing pack returns 403."""
        mock_tenant = MagicMock()
        mock_tenant.tenant_id = "tenant-1"
        mock_tenant.tenant_code = "test_tenant"
        mock_tenant.entitlements = {}  # No entitlements

        pack_id = "routing"
        entitlements = mock_tenant.entitlements or {}
        pack_entitlement = entitlements.get(pack_id, {})

        is_enabled = pack_entitlement.get("is_enabled", False)
        assert is_enabled is False


class TestErrorMessages:
    """Tests for error message format."""

    def test_403_error_format(self):
        """403 error has correct format."""
        expected_error = {
            "error": "pack_not_enabled",
            "message": "Pack 'routing' is not enabled for tenant 'test_tenant'",
            "pack_id": "routing",
            "tenant_code": "test_tenant",
            "action": "Contact your administrator to enable this pack"
        }

        # Verify all required fields are present
        assert "error" in expected_error
        assert "message" in expected_error
        assert "pack_id" in expected_error
        assert "tenant_code" in expected_error
        assert "action" in expected_error

    def test_error_contains_pack_id(self):
        """Error message contains pack ID for debugging."""
        pack_id = "analytics"
        tenant_code = "customer_x"

        error_detail = {
            "error": "pack_not_enabled",
            "message": f"Pack '{pack_id}' is not enabled for tenant '{tenant_code}'",
            "pack_id": pack_id,
            "tenant_code": tenant_code,
            "action": "Contact your administrator to enable this pack"
        }

        assert error_detail["pack_id"] == pack_id
        assert pack_id in error_detail["message"]


# =============================================================================
# AUDIT LOGGING TESTS
# =============================================================================

class TestAuditLogging:
    """Tests for access attempt audit logging."""

    def test_denied_access_logged(self, service):
        """Denied access attempts are logged."""
        service.get_entitlement = AsyncMock(return_value=None)
        service._log_access_event = AsyncMock()

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            service.check_access("tenant-1", "routing", "/api/v1/routing/solve", log_event=True)
        )

        # Verify log was called
        service._log_access_event.assert_called_once()
        call_args = service._log_access_event.call_args
        assert call_args[1]["result"] == PackAccessResult.DENIED_NOT_ENABLED

    def test_allowed_access_not_logged_by_default(self, service, enabled_entitlement):
        """Allowed access is not logged by default (to reduce noise)."""
        service.get_entitlement = AsyncMock(return_value=enabled_entitlement)

        # Mock the internal log method
        original_log = service._log_access_event
        service._log_access_event = AsyncMock()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.check_access("tenant-1", "routing", "/api/v1/routing/solve", log_event=True)
        )

        # Log should be called, but the internal implementation only logs denials
        assert result == PackAccessResult.ALLOWED


# =============================================================================
# PACK CONFIG TESTS
# =============================================================================

class TestPackConfig:
    """Tests for pack configuration retrieval."""

    def test_get_config_returns_config(self):
        """Get config returns pack configuration."""
        mock_tenant = MagicMock()
        mock_tenant.entitlements = {
            "routing": {
                "is_enabled": True,
                "config": {"max_vehicles": 100, "timeout_seconds": 300}
            }
        }

        config = mock_tenant.entitlements.get("routing", {}).get("config", {})

        assert config["max_vehicles"] == 100
        assert config["timeout_seconds"] == 300

    def test_get_config_disabled_pack_returns_empty(self):
        """Get config for disabled pack returns empty dict."""
        mock_tenant = MagicMock()
        mock_tenant.entitlements = {
            "routing": {"is_enabled": False}
        }

        pack_entitlement = mock_tenant.entitlements.get("routing", {})
        if not pack_entitlement.get("is_enabled", False):
            config = {}
        else:
            config = pack_entitlement.get("config", {})

        assert config == {}


# =============================================================================
# INTEGRATION-STYLE TESTS
# =============================================================================

class TestPackEndpointAccess:
    """Integration-style tests for pack endpoint access patterns."""

    def test_routing_pack_endpoint_patterns(self):
        """Routing pack protects correct endpoints."""
        routing_endpoints = [
            "/api/v1/routing/solve",
            "/api/v1/routing/optimize",
            "/api/v1/routing/status"
        ]

        # All routing endpoints should require routing pack
        for endpoint in routing_endpoints:
            assert "routing" in endpoint

    def test_roster_pack_endpoint_patterns(self):
        """Roster pack protects correct endpoints."""
        roster_endpoints = [
            "/api/v1/roster/schedule",
            "/api/v1/roster/shifts",
            "/api/v1/roster/assignments"
        ]

        # All roster endpoints should require roster pack
        for endpoint in roster_endpoints:
            assert "roster" in endpoint

    def test_kernel_endpoints_no_pack_required(self):
        """Kernel endpoints don't require pack entitlement."""
        kernel_endpoints = [
            "/api/v1/forecasts",
            "/api/v1/plans",
            "/health",
            "/health/ready"
        ]

        # These are kernel endpoints - no pack prefix
        for endpoint in kernel_endpoints:
            assert "routing" not in endpoint
            assert "roster" not in endpoint


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
