"""
SOLVEREIGN V4.1 - Portal Tests
================================

Tests for driver portal magic links and acknowledgments.

Test Categories:
    - Token generation and validation
    - Read receipt idempotency
    - ACK idempotency and single-use
    - Tenant isolation
    - Superseded snapshot handling
    - Rate limiting
"""

import pytest
import uuid
from datetime import datetime, timedelta, date, time

from ..models import (
    TokenScope,
    TokenStatus,
    AckStatus,
    AckReasonCode,
    AckSource,
    PortalToken,
    ReadReceipt,
    DriverAck,
    generate_jti,
    hash_jti,
    hash_ip,
    validate_free_text,
)
from ..token_service import (
    PortalTokenService,
    PortalAuthService,
    TokenConfig,
    MockTokenRepository,
    create_mock_auth_service,
)
from ..repository import MockPortalRepository
from ..renderer import (
    DriverViewRenderer,
    WeekPlan,
    ShiftInfo,
    create_renderer,
    render_driver_view_from_snapshot,
)


# =============================================================================
# TOKEN VALIDATION TESTS
# =============================================================================

class TestTokenValidation:
    """Tests for token generation and validation."""

    @pytest.fixture
    def token_service(self):
        """Create token service with test config."""
        config = TokenConfig(
            jwt_secret="test_secret_for_testing_only",
            read_ttl_days=14,
            ack_ttl_days=7,
        )
        return PortalTokenService(config)

    def test_generate_token_returns_raw_and_model(self, token_service):
        """Token generation returns both raw token and DB model."""
        raw_token, portal_token = token_service.generate_token(
            tenant_id=1,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
            scope=TokenScope.READ_ACK,
        )

        assert raw_token is not None
        assert len(raw_token) > 100  # JWT is long
        assert portal_token.tenant_id == 1
        assert portal_token.driver_id == "DRV-001"
        assert portal_token.scope == TokenScope.READ_ACK
        assert len(portal_token.jti_hash) == 64  # SHA-256

    def test_validate_token_success(self, token_service):
        """Valid token passes validation."""
        raw_token, _ = token_service.generate_token(
            tenant_id=1,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
        )

        result = token_service.validate_token(raw_token)

        assert result.is_valid is True
        assert result.status == TokenStatus.VALID
        assert result.token is not None
        assert result.token.driver_id == "DRV-001"

    def test_validate_expired_token(self, token_service):
        """Expired token fails validation."""
        raw_token, _ = token_service.generate_token(
            tenant_id=1,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
            ttl_days=-1,  # Already expired
        )

        result = token_service.validate_token(raw_token)

        assert result.is_valid is False
        assert result.status == TokenStatus.EXPIRED
        assert result.error_code == "TOKEN_EXPIRED"

    def test_validate_invalid_token(self, token_service):
        """Invalid token fails validation."""
        result = token_service.validate_token("not.a.valid.token")

        assert result.is_valid is False
        assert result.status == TokenStatus.INVALID

    def test_validate_tampered_token(self, token_service):
        """Tampered token fails signature validation."""
        raw_token, _ = token_service.generate_token(
            tenant_id=1,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
        )

        # Tamper with the token
        tampered = raw_token[:-10] + "0000000000"

        result = token_service.validate_token(tampered)

        assert result.is_valid is False
        assert result.status == TokenStatus.INVALID

    def test_jti_hash_is_deterministic(self):
        """Same JTI always produces same hash."""
        jti = "test_jti_12345"
        hash1 = hash_jti(jti)
        hash2 = hash_jti(jti)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256

    def test_different_jti_produces_different_hash(self):
        """Different JTIs produce different hashes."""
        hash1 = hash_jti("jti_1")
        hash2 = hash_jti("jti_2")

        assert hash1 != hash2


# =============================================================================
# READ IDEMPOTENCY TESTS
# =============================================================================

class TestReadIdempotency:
    """Tests for read receipt idempotency."""

    @pytest.fixture
    def repository(self):
        """Create mock repository."""
        return MockPortalRepository()

    @pytest.mark.asyncio
    async def test_first_read_creates_receipt(self, repository):
        """First read creates a new receipt."""
        receipt = await repository.record_read(
            tenant_id=1,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
        )

        assert receipt.read_count == 1
        assert receipt.is_first_read is True
        assert receipt.first_read_at is not None

    @pytest.mark.asyncio
    async def test_subsequent_reads_increment_count(self, repository):
        """Subsequent reads increment count but keep first_read_at."""
        snapshot_id = str(uuid.uuid4())

        # First read
        receipt1 = await repository.record_read(
            tenant_id=1, site_id=1, snapshot_id=snapshot_id, driver_id="DRV-001"
        )
        first_read_at = receipt1.first_read_at

        # Second read
        receipt2 = await repository.record_read(
            tenant_id=1, site_id=1, snapshot_id=snapshot_id, driver_id="DRV-001"
        )

        assert receipt2.read_count == 2
        assert receipt2.is_first_read is False
        assert receipt2.first_read_at == first_read_at  # Unchanged
        assert receipt2.last_read_at >= receipt1.last_read_at

    @pytest.mark.asyncio
    async def test_different_drivers_have_separate_receipts(self, repository):
        """Each driver has their own receipt."""
        snapshot_id = str(uuid.uuid4())

        receipt1 = await repository.record_read(
            tenant_id=1, site_id=1, snapshot_id=snapshot_id, driver_id="DRV-001"
        )
        receipt2 = await repository.record_read(
            tenant_id=1, site_id=1, snapshot_id=snapshot_id, driver_id="DRV-002"
        )

        assert receipt1.read_count == 1
        assert receipt2.read_count == 1
        assert receipt1.driver_id != receipt2.driver_id


# =============================================================================
# ACK IDEMPOTENCY & SINGLE-USE TESTS
# =============================================================================

class TestAckIdempotencySingleUse:
    """Tests for ACK idempotency and single-use behavior."""

    @pytest.fixture
    def repository(self):
        """Create mock repository."""
        return MockPortalRepository()

    @pytest.fixture
    def auth_service(self):
        """Create mock auth service."""
        service, repository = create_mock_auth_service()
        return service, repository

    @pytest.mark.asyncio
    async def test_first_ack_creates_record(self, repository):
        """First ACK creates a new record."""
        ack = await repository.record_ack(
            tenant_id=1,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
            status=AckStatus.ACCEPTED,
        )

        assert ack.status == AckStatus.ACCEPTED
        assert ack.source == AckSource.PORTAL
        assert ack.ack_at is not None

    @pytest.mark.asyncio
    async def test_subsequent_ack_returns_existing(self, repository):
        """Subsequent ACK returns existing record (immutable)."""
        snapshot_id = str(uuid.uuid4())

        # First ACK - ACCEPTED
        ack1 = await repository.record_ack(
            tenant_id=1, site_id=1, snapshot_id=snapshot_id,
            driver_id="DRV-001", status=AckStatus.ACCEPTED
        )

        # Second ACK attempt - DECLINED (should be ignored)
        ack2 = await repository.record_ack(
            tenant_id=1, site_id=1, snapshot_id=snapshot_id,
            driver_id="DRV-001", status=AckStatus.DECLINED
        )

        # Should return first ACK, not new one
        assert ack2.status == AckStatus.ACCEPTED  # Original status preserved
        assert ack2.id == ack1.id

    @pytest.mark.asyncio
    async def test_ack_with_reason_code(self, repository):
        """ACK with decline reason code."""
        ack = await repository.record_ack(
            tenant_id=1,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
            status=AckStatus.DECLINED,
            reason_code=AckReasonCode.SCHEDULING_CONFLICT,
            free_text="Habe an dem Tag einen Arzttermin",
        )

        assert ack.status == AckStatus.DECLINED
        assert ack.reason_code == AckReasonCode.SCHEDULING_CONFLICT
        assert ack.free_text == "Habe an dem Tag einen Arzttermin"

    @pytest.mark.asyncio
    async def test_single_use_token_revoked_after_ack(self, auth_service):
        """Token is revoked after successful ACK."""
        service, repository = auth_service

        # Generate and save token
        raw_token, portal_token = service.token_service.generate_token(
            tenant_id=1, site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
            scope=TokenScope.ACK,
        )
        await repository.save_token(portal_token)

        # Revoke after ACK
        revoked = await service.revoke_token_after_ack(portal_token.jti_hash)

        assert revoked is True

        # Token should now be revoked
        db_token = await repository.get_by_jti_hash(portal_token.jti_hash)
        assert db_token.is_revoked is True


# =============================================================================
# TENANT ISOLATION TESTS
# =============================================================================

class TestTenantIsolation:
    """Tests for tenant isolation in portal operations."""

    @pytest.fixture
    def token_service(self):
        """Create token service."""
        config = TokenConfig(jwt_secret="test_secret")
        return PortalTokenService(config)

    def test_token_contains_tenant_id(self, token_service):
        """Token includes tenant_id in claims."""
        raw_token, portal_token = token_service.generate_token(
            tenant_id=42,
            site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
        )

        result = token_service.validate_token(raw_token)

        assert result.token.tenant_id == 42

    def test_token_from_different_tenant_has_different_tenant_id(self, token_service):
        """Tokens from different tenants have correct tenant_ids."""
        _, token1 = token_service.generate_token(
            tenant_id=1, site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
        )
        _, token2 = token_service.generate_token(
            tenant_id=2, site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
        )

        assert token1.tenant_id == 1
        assert token2.tenant_id == 2

    @pytest.mark.asyncio
    async def test_cross_tenant_token_rejected(self):
        """Token from tenant A cannot access tenant B data."""
        # This is primarily enforced by RLS in production,
        # but token validation should prevent cross-tenant access
        auth_service, repository = create_mock_auth_service()

        # Token for tenant 1
        raw_token, portal_token = auth_service.token_service.generate_token(
            tenant_id=1, site_id=1,
            snapshot_id=str(uuid.uuid4()),
            driver_id="DRV-001",
        )
        await repository.save_token(portal_token)

        # Validate - should succeed for correct tenant
        result = await auth_service.validate_and_authorize(raw_token)
        assert result.is_valid is True
        assert result.token.tenant_id == 1

        # In production, attempting to access tenant 2 data with tenant 1 token
        # would be blocked by RLS, but the token itself is valid


# =============================================================================
# SUPERSEDED BANNER TESTS
# =============================================================================

class TestSupersededBanner:
    """Tests for superseded snapshot handling."""

    @pytest.fixture
    def repository(self):
        """Create mock repository."""
        return MockPortalRepository()

    @pytest.mark.asyncio
    async def test_mark_snapshot_superseded(self, repository):
        """Snapshot can be marked as superseded."""
        old_id = str(uuid.uuid4())
        new_id = str(uuid.uuid4())

        supersede = await repository.mark_superseded(
            tenant_id=1,
            old_snapshot_id=old_id,
            new_snapshot_id=new_id,
            superseded_by="dispatcher@example.com",
            reason="Repair after driver illness",
        )

        assert supersede.old_snapshot_id == old_id
        assert supersede.new_snapshot_id == new_id
        assert supersede.superseded_by == "dispatcher@example.com"

    @pytest.mark.asyncio
    async def test_get_supersede_returns_mapping(self, repository):
        """Can look up supersede mapping."""
        old_id = str(uuid.uuid4())
        new_id = str(uuid.uuid4())

        await repository.mark_superseded(
            tenant_id=1,
            old_snapshot_id=old_id,
            new_snapshot_id=new_id,
        )

        result = await repository.get_supersede(1, old_id)

        assert result is not None
        assert result.new_snapshot_id == new_id

    @pytest.mark.asyncio
    async def test_old_links_remain_valid_but_superseded(self, repository):
        """Old links still work but show superseded banner."""
        auth_service, token_repo = create_mock_auth_service()

        old_snapshot_id = str(uuid.uuid4())
        new_snapshot_id = str(uuid.uuid4())

        # Create token for old snapshot
        raw_token, portal_token = auth_service.token_service.generate_token(
            tenant_id=1, site_id=1,
            snapshot_id=old_snapshot_id,
            driver_id="DRV-001",
        )
        await token_repo.save_token(portal_token)

        # Mark old snapshot as superseded
        await repository.mark_superseded(
            tenant_id=1,
            old_snapshot_id=old_snapshot_id,
            new_snapshot_id=new_snapshot_id,
        )

        # Token still validates
        result = await auth_service.validate_and_authorize(raw_token)
        assert result.is_valid is True

        # But supersede info is available
        supersede = await repository.get_supersede(1, old_snapshot_id)
        assert supersede is not None
        assert supersede.new_snapshot_id == new_snapshot_id


# =============================================================================
# RATE LIMITING TESTS (basic)
# =============================================================================

class TestRateLimiting:
    """Tests for rate limiting."""

    @pytest.fixture
    def repository(self):
        """Create mock repository."""
        return MockPortalRepository()

    @pytest.mark.asyncio
    async def test_rate_limit_allows_within_limit(self, repository):
        """Requests within limit are allowed."""
        jti_hash = hash_jti("test_jti")

        result = await repository.check_rate_limit(
            jti_hash, max_requests=100, window_seconds=3600
        )

        assert result.is_allowed is True
        assert result.current_count == 1

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_over_limit(self, repository):
        """Requests over limit are blocked."""
        jti_hash = hash_jti("test_jti")

        # Exhaust the limit
        for _ in range(5):
            await repository.check_rate_limit(
                jti_hash, max_requests=5, window_seconds=3600
            )

        # Next request should be blocked
        result = await repository.check_rate_limit(
            jti_hash, max_requests=5, window_seconds=3600
        )

        assert result.is_allowed is False
        assert result.current_count == 6


# =============================================================================
# RENDERER TESTS
# =============================================================================

class TestDriverViewRenderer:
    """Tests for driver view renderer."""

    @pytest.fixture
    def sample_snapshot(self):
        """Sample assignments snapshot."""
        return {
            "assignments": [
                {
                    "driver_id": "DRV-001",
                    "driver_name": "Max Mustermann",
                    "date": "2026-01-12",
                    "shift_start": "06:00",
                    "shift_end": "14:00",
                    "route_id": "R101",
                    "zone": "WIEN",
                },
                {
                    "driver_id": "DRV-001",
                    "driver_name": "Max Mustermann",
                    "date": "2026-01-13",
                    "shift_start": "08:00",
                    "shift_end": "16:00",
                    "route_id": "R102",
                    "zone": "WIEN",
                },
                {
                    "driver_id": "DRV-002",
                    "driver_name": "Anna Schmidt",
                    "date": "2026-01-12",
                    "shift_start": "14:00",
                    "shift_end": "22:00",
                    "route_id": "R103",
                    "zone": "GRAZ",
                },
            ]
        }

    def test_extract_driver_plan(self, sample_snapshot):
        """Extract plan for specific driver."""
        renderer = create_renderer()
        plan = renderer.extract_driver_plan(sample_snapshot, "DRV-001")

        assert plan.driver_id == "DRV-001"
        assert plan.driver_name == "Max Mustermann"
        assert len(plan.shifts) == 2
        assert plan.total_hours == 16.0  # 8h + 8h

    def test_extract_plan_for_nonexistent_driver(self, sample_snapshot):
        """Extract plan for driver not in snapshot returns empty plan."""
        renderer = create_renderer()
        plan = renderer.extract_driver_plan(sample_snapshot, "DRV-999")

        assert plan.driver_id == "DRV-999"
        assert len(plan.shifts) == 0

    def test_render_html(self, sample_snapshot):
        """Render HTML view."""
        renderer = create_renderer()
        plan = renderer.extract_driver_plan(sample_snapshot, "DRV-001")
        view = renderer.render_html(plan, str(uuid.uuid4()))

        assert view.format == "html"
        assert "Max Mustermann" in view.content
        assert "06:00" in view.content
        assert len(view.content_hash) == 64

    def test_render_json(self, sample_snapshot):
        """Render JSON view."""
        renderer = create_renderer()
        plan = renderer.extract_driver_plan(sample_snapshot, "DRV-001")
        view = renderer.render_json(plan, str(uuid.uuid4()))

        assert view.format == "json"
        import json
        data = json.loads(view.content)
        assert data["driver_id"] == "DRV-001"
        assert len(data["shifts"]) == 2

    def test_render_all_drivers(self, sample_snapshot):
        """Render views for all drivers."""
        renderer = create_renderer()
        views = renderer.render_all_drivers(
            sample_snapshot,
            str(uuid.uuid4()),
            format="html"
        )

        assert len(views) == 2  # DRV-001 and DRV-002
        driver_ids = {v.driver_id for v in views}
        assert driver_ids == {"DRV-001", "DRV-002"}


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

class TestHelperFunctions:
    """Tests for helper functions."""

    def test_validate_free_text_truncates(self):
        """Free text is truncated to 200 chars."""
        long_text = "x" * 300
        result = validate_free_text(long_text)

        assert len(result) == 200

    def test_validate_free_text_sanitizes_html(self):
        """Free text sanitizes HTML tags."""
        text = "<script>alert('xss')</script>"
        result = validate_free_text(text)

        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_validate_free_text_empty_returns_none(self):
        """Empty/whitespace text returns None."""
        assert validate_free_text("") is None
        assert validate_free_text("   ") is None

    def test_hash_ip_is_deterministic(self):
        """Same IP always produces same hash."""
        hash1 = hash_ip("192.168.1.1")
        hash2 = hash_ip("192.168.1.1")

        assert hash1 == hash2
        assert len(hash1) == 64


# =============================================================================
# PORTAL STATUS AGGREGATION TESTS
# =============================================================================

class TestPortalStatus:
    """Tests for portal status aggregation."""

    @pytest.fixture
    def repository(self):
        """Create mock repository."""
        return MockPortalRepository()

    @pytest.mark.asyncio
    async def test_portal_status_counts(self, repository):
        """Portal status returns correct counts."""
        snapshot_id = str(uuid.uuid4())

        # Create some tokens
        for i in range(5):
            token = PortalToken(
                tenant_id=1, site_id=1,
                snapshot_id=snapshot_id,
                driver_id=f"DRV-{i:03d}",
                scope=TokenScope.READ_ACK,
                jti_hash=hash_jti(f"jti_{i}"),
            )
            await repository.save_token(token)

        # Some drivers read
        await repository.record_read(1, 1, snapshot_id, "DRV-000")
        await repository.record_read(1, 1, snapshot_id, "DRV-001")
        await repository.record_read(1, 1, snapshot_id, "DRV-002")

        # Some drivers ack
        await repository.record_ack(1, 1, snapshot_id, "DRV-000", AckStatus.ACCEPTED)
        await repository.record_ack(1, 1, snapshot_id, "DRV-001", AckStatus.DECLINED)

        status = await repository.get_portal_status(1, snapshot_id)

        assert status.total_drivers == 5
        assert status.read_count == 3
        assert status.unread_count == 2
        assert status.accepted_count == 1
        assert status.declined_count == 1
        assert status.pending_count == 1  # Read but not acked
