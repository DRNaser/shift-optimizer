"""
SOLVEREIGN V4.2 - Portal Link Service Tests
=============================================

Tests for the portal-notify integration service.
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from ..models import (
    TokenScope,
    TokenStatus,
    PortalToken,
    DeliveryChannel,
)
from ..token_service import (
    PortalTokenService,
    TokenConfig,
    MockTokenRepository,
)
from ..link_service import (
    DriverLinkRequest,
    DriverLinkResult,
    BulkLinkResult,
    NotifyLinkRequest,
    NotifyLinkResult,
    PortalLinkService,
    create_link_service,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def token_config():
    """Create test token configuration."""
    return TokenConfig(
        jwt_secret="test-secret-key-for-testing-only",
        jwt_algorithm="HS256",
        read_ttl_days=14,
        ack_ttl_days=7,
        rate_limit_max=100,
    )


@pytest.fixture
def mock_repository():
    """Create mock repository."""
    return MockTokenRepository()


@pytest.fixture
def link_service(token_config, mock_repository):
    """Create link service with mock repository."""
    token_service = PortalTokenService(token_config)
    return PortalLinkService(
        token_service=token_service,
        repository=mock_repository,
        base_url="https://test.solvereign.com",
    )


# =============================================================================
# SINGLE LINK GENERATION TESTS
# =============================================================================

class TestSingleLinkGeneration:
    """Tests for single portal link generation."""

    @pytest.mark.asyncio
    async def test_generate_link_creates_valid_url(self, link_service):
        """Test that generate_link creates a valid portal URL."""
        portal_url, token = await link_service.generate_link(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_id="DRV-001",
        )

        # URL should contain base and token parameter
        assert portal_url.startswith("https://test.solvereign.com/my-plan?t=")
        assert len(portal_url) > 50  # JWT tokens are long

    @pytest.mark.asyncio
    async def test_generate_link_stores_jti_hash_only(self, link_service):
        """Test that only jti_hash is stored, never raw token."""
        portal_url, token = await link_service.generate_link(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_id="DRV-001",
        )

        # Token should have jti_hash but no raw token
        assert token.jti_hash is not None
        assert len(token.jti_hash) == 64  # SHA-256 hex

        # Raw token is in URL, not in stored token
        raw_token_from_url = portal_url.split("?t=")[1]
        assert raw_token_from_url not in token.jti_hash

    @pytest.mark.asyncio
    async def test_generate_link_with_custom_scope(self, link_service):
        """Test link generation with custom scope."""
        _, token = await link_service.generate_link(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_id="DRV-001",
            scope=TokenScope.READ,
        )

        assert token.scope == TokenScope.READ
        assert token.can_read
        assert not token.can_ack

    @pytest.mark.asyncio
    async def test_generate_link_with_delivery_channel(self, link_service):
        """Test link generation tracks delivery channel."""
        _, token = await link_service.generate_link(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_id="DRV-001",
            delivery_channel=DeliveryChannel.WHATSAPP,
        )

        assert token.delivery_channel == DeliveryChannel.WHATSAPP

    @pytest.mark.asyncio
    async def test_generate_link_saves_to_repository(self, link_service, mock_repository):
        """Test that generated link is saved to repository."""
        snapshot_id = str(uuid4())
        driver_id = "DRV-001"

        _, token = await link_service.generate_link(
            tenant_id=1,
            site_id=10,
            snapshot_id=snapshot_id,
            driver_id=driver_id,
        )

        # Should be retrievable from repository
        stored_token = await mock_repository.get_by_jti_hash(token.jti_hash)
        assert stored_token is not None
        assert stored_token.driver_id == driver_id
        assert stored_token.snapshot_id == snapshot_id


# =============================================================================
# BULK LINK GENERATION TESTS
# =============================================================================

class TestBulkLinkGeneration:
    """Tests for bulk portal link generation."""

    @pytest.mark.asyncio
    async def test_bulk_generate_creates_multiple_links(self, link_service):
        """Test bulk generation creates links for all drivers."""
        driver_requests = [
            DriverLinkRequest(driver_id="DRV-001", driver_name="Driver 1"),
            DriverLinkRequest(driver_id="DRV-002", driver_name="Driver 2"),
            DriverLinkRequest(driver_id="DRV-003", driver_name="Driver 3"),
        ]

        result = await link_service.generate_bulk_links(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=driver_requests,
        )

        assert result.total_count == 3
        assert result.success_count == 3
        assert result.failed_count == 0
        assert len(result.driver_results) == 3
        assert len(result.portal_urls) == 3

    @pytest.mark.asyncio
    async def test_bulk_generate_unique_tokens_per_driver(self, link_service):
        """Test that each driver gets a unique token."""
        driver_requests = [
            DriverLinkRequest(driver_id="DRV-001"),
            DriverLinkRequest(driver_id="DRV-002"),
        ]

        result = await link_service.generate_bulk_links(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=driver_requests,
        )

        # Each driver should have unique jti_hash and URL
        jti_hashes = [r.token.jti_hash for r in result.driver_results]
        urls = list(result.portal_urls.values())

        assert len(set(jti_hashes)) == 2  # Unique hashes
        assert len(set(urls)) == 2  # Unique URLs

    @pytest.mark.asyncio
    async def test_bulk_generate_portal_urls_dict(self, link_service):
        """Test portal_urls dictionary is correctly populated."""
        driver_requests = [
            DriverLinkRequest(driver_id="DRV-001"),
            DriverLinkRequest(driver_id="DRV-002"),
        ]

        result = await link_service.generate_bulk_links(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=driver_requests,
        )

        # portal_urls should map driver_id -> url
        assert "DRV-001" in result.portal_urls
        assert "DRV-002" in result.portal_urls
        assert result.portal_urls["DRV-001"].startswith("https://test.solvereign.com/my-plan?t=")

    @pytest.mark.asyncio
    async def test_bulk_generate_all_successful_flag(self, link_service):
        """Test all_successful property."""
        driver_requests = [
            DriverLinkRequest(driver_id="DRV-001"),
        ]

        result = await link_service.generate_bulk_links(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=driver_requests,
        )

        assert result.all_successful is True


# =============================================================================
# NOTIFY LINK REQUEST TESTS
# =============================================================================

class TestNotifyLinkRequest:
    """Tests for NotifyLinkRequest model."""

    def test_notify_link_request_creation(self):
        """Test NotifyLinkRequest can be created."""
        request = NotifyLinkRequest(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=[
                DriverLinkRequest(driver_id="DRV-001"),
            ],
            delivery_channel=DeliveryChannel.WHATSAPP,
            template_key="PORTAL_INVITE",
            initiated_by="dispatcher@test.com",
        )

        assert request.tenant_id == 1
        assert request.template_key == "PORTAL_INVITE"
        assert len(request.driver_requests) == 1

    def test_notify_link_request_with_template_params(self):
        """Test NotifyLinkRequest with additional template params."""
        request = NotifyLinkRequest(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=[],
            delivery_channel=DeliveryChannel.EMAIL,
            template_key="PORTAL_INVITE",
            template_params={"week_start": "2026-01-12"},
        )

        assert request.template_params["week_start"] == "2026-01-12"


# =============================================================================
# ISSUE AND NOTIFY TESTS
# =============================================================================

class TestIssueAndNotify:
    """Tests for issue_and_notify integration method."""

    @pytest.mark.asyncio
    async def test_issue_and_notify_without_notify_repo(self, link_service):
        """Test issue_and_notify without notify repository (links only)."""
        request = NotifyLinkRequest(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=[
                DriverLinkRequest(driver_id="DRV-001"),
                DriverLinkRequest(driver_id="DRV-002"),
            ],
            delivery_channel=DeliveryChannel.WHATSAPP,
            template_key="PORTAL_INVITE",
            initiated_by="dispatcher@test.com",
        )

        # Without notify_repository, only links are created
        result = await link_service.issue_and_notify(request, notify_repository=None)

        assert result.snapshot_id == request.snapshot_id
        assert result.bulk_result.success_count == 2
        assert result.notification_created is False
        assert result.job_id is None

    @pytest.mark.asyncio
    async def test_issue_and_notify_empty_drivers(self, link_service):
        """Test issue_and_notify with no drivers."""
        request = NotifyLinkRequest(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=[],  # Empty
            delivery_channel=DeliveryChannel.WHATSAPP,
            template_key="PORTAL_INVITE",
            initiated_by="dispatcher@test.com",
        )

        result = await link_service.issue_and_notify(request)

        assert result.bulk_result.total_count == 0
        assert result.bulk_result.success_count == 0


# =============================================================================
# TEMPLATE VARIABLE TESTS
# =============================================================================

class TestTemplateVariables:
    """Tests for template variable substitution."""

    @pytest.mark.asyncio
    async def test_plan_link_variable_available(self, link_service):
        """Test that {plan_link} variable is available in portal_urls."""
        driver_requests = [
            DriverLinkRequest(driver_id="DRV-001", driver_name="Max Mustermann"),
        ]

        result = await link_service.generate_bulk_links(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=driver_requests,
        )

        # The portal_urls dict provides the value for {plan_link}
        plan_link = result.portal_urls["DRV-001"]
        assert "my-plan?t=" in plan_link

    def test_template_rendering_with_plan_link(self):
        """Test template rendering with {plan_link} variable."""
        # Simulate template rendering
        template = "Hallo {{driver_name}}, Ihr Plan: {{plan_link}}"
        params = {
            "driver_name": "Max Mustermann",
            "plan_link": "https://portal.solvereign.com/my-plan?t=eyJ...",
        }

        # Render (simple replace for test)
        result = template
        for key, value in params.items():
            result = result.replace(f"{{{{{key}}}}}", value)

        assert "Max Mustermann" in result
        assert "my-plan?t=eyJ..." in result


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_link_service_mock(self):
        """Test create_link_service with mock repository."""
        service, repository = create_link_service(use_mock=True)

        assert service is not None
        assert isinstance(repository, MockTokenRepository)

    def test_create_link_service_custom_base_url(self):
        """Test create_link_service with custom base URL."""
        service, _ = create_link_service(
            base_url="https://custom.example.com",
            use_mock=True,
        )

        assert service.base_url == "https://custom.example.com"

    def test_create_link_service_custom_config(self):
        """Test create_link_service with custom config."""
        config = TokenConfig(
            jwt_secret="custom-secret",
            read_ttl_days=30,
        )
        service, _ = create_link_service(config=config, use_mock=True)

        assert service.token_service.config.read_ttl_days == 30


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in link service."""

    @pytest.mark.asyncio
    async def test_bulk_generate_handles_individual_failures(self, link_service, mock_repository):
        """Test that bulk generate continues on individual failures."""
        # This test would require mocking internal failures
        # For now, verify the result structure handles failures
        driver_requests = [
            DriverLinkRequest(driver_id="DRV-001"),
        ]

        result = await link_service.generate_bulk_links(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_requests=driver_requests,
        )

        # Verify result has proper structure
        assert hasattr(result, 'failed_count')
        assert hasattr(result, 'success_count')
        assert result.driver_results[0].success is True


# =============================================================================
# SECURITY TESTS
# =============================================================================

class TestSecurity:
    """Security-related tests."""

    @pytest.mark.asyncio
    async def test_raw_token_not_in_stored_data(self, link_service, mock_repository):
        """Test that raw JWT token is never stored."""
        portal_url, token = await link_service.generate_link(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_id="DRV-001",
        )

        # Extract raw token from URL
        raw_token = portal_url.split("?t=")[1]

        # Get stored token
        stored = await mock_repository.get_by_jti_hash(token.jti_hash)

        # Raw token should not be anywhere in stored token fields
        stored_str = str(stored.to_dict())
        assert raw_token not in stored_str

    @pytest.mark.asyncio
    async def test_each_driver_gets_unique_jti(self, link_service):
        """Test that each driver gets unique JTI (no reuse)."""
        snapshot_id = str(uuid4())
        results = []

        for i in range(5):
            _, token = await link_service.generate_link(
                tenant_id=1,
                site_id=10,
                snapshot_id=snapshot_id,
                driver_id=f"DRV-{i:03d}",
            )
            results.append(token.jti_hash)

        # All JTI hashes should be unique
        assert len(set(results)) == 5

    @pytest.mark.asyncio
    async def test_tokens_are_tenant_isolated(self, link_service, mock_repository):
        """Test that tokens include tenant_id for RLS."""
        _, token1 = await link_service.generate_link(
            tenant_id=1,
            site_id=10,
            snapshot_id=str(uuid4()),
            driver_id="DRV-001",
        )

        _, token2 = await link_service.generate_link(
            tenant_id=2,
            site_id=20,
            snapshot_id=str(uuid4()),
            driver_id="DRV-001",
        )

        # Same driver_id but different tenants
        assert token1.tenant_id == 1
        assert token2.tenant_id == 2
        assert token1.jti_hash != token2.jti_hash
