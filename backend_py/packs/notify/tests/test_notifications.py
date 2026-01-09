"""
SOLVEREIGN V4.1 - Notification Pipeline Tests
==============================================

Tests for notification models, providers, and worker.
"""

import asyncio
import pytest
from datetime import datetime, timedelta, time
from uuid import uuid4

from ..models import (
    DeliveryChannel,
    NotificationJobType,
    JobStatus,
    OutboxStatus,
    RetryPolicy,
    NotificationJob,
    NotificationOutbox,
    NotificationTemplate,
    DriverPreferences,
)
from ..providers.base import MockProvider, ProviderResult


# =============================================================================
# MODEL TESTS
# =============================================================================

class TestRetryPolicy:
    """Tests for RetryPolicy."""

    def test_default_values(self):
        """Default retry policy has 3 attempts with backoff."""
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.backoff_seconds == [60, 300, 900]

    def test_get_next_delay_first_attempt(self):
        """First retry delay is 60 seconds."""
        policy = RetryPolicy()
        assert policy.get_next_delay(0) == 60

    def test_get_next_delay_second_attempt(self):
        """Second retry delay is 300 seconds."""
        policy = RetryPolicy()
        assert policy.get_next_delay(1) == 300

    def test_get_next_delay_beyond_list(self):
        """Delays beyond list use last value."""
        policy = RetryPolicy()
        assert policy.get_next_delay(10) == 900

    def test_to_dict(self):
        """Policy can be serialized to dict."""
        policy = RetryPolicy(max_attempts=5, backoff_seconds=[10, 20, 30])
        d = policy.to_dict()
        assert d["max_attempts"] == 5
        assert d["backoff_seconds"] == [10, 20, 30]

    def test_from_dict(self):
        """Policy can be deserialized from dict."""
        d = {"max_attempts": 5, "backoff_seconds": [10, 20, 30]}
        policy = RetryPolicy.from_dict(d)
        assert policy.max_attempts == 5
        assert policy.backoff_seconds == [10, 20, 30]


class TestNotificationTemplate:
    """Tests for NotificationTemplate."""

    def test_render_simple(self):
        """Template renders with simple variables."""
        template = NotificationTemplate(
            id=uuid4(),
            tenant_id=None,
            site_id=None,
            template_key="TEST",
            delivery_channel=DeliveryChannel.WHATSAPP,
            language="de",
            whatsapp_template_name=None,
            whatsapp_template_namespace=None,
            subject=None,
            body_template="Hallo {{driver_name}}, klicke hier: {{portal_url}}",
            body_html=None,
            is_active=True,
            requires_approval=False,
            approval_status=None,
            expected_params=["driver_name", "portal_url"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        result = template.render({
            "driver_name": "Max",
            "portal_url": "https://example.com/abc",
        })

        assert "Hallo Max" in result
        assert "https://example.com/abc" in result

    def test_render_html(self):
        """HTML template renders correctly."""
        template = NotificationTemplate(
            id=uuid4(),
            tenant_id=None,
            site_id=None,
            template_key="TEST",
            delivery_channel=DeliveryChannel.EMAIL,
            language="de",
            whatsapp_template_name=None,
            whatsapp_template_namespace=None,
            subject="Test",
            body_template="Plain text",
            body_html="<h1>Hallo {{driver_name}}</h1>",
            is_active=True,
            requires_approval=False,
            approval_status=None,
            expected_params=["driver_name"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        result = template.render_html({"driver_name": "Max"})
        assert result == "<h1>Hallo Max</h1>"

    def test_render_html_none(self):
        """Returns None if no HTML template."""
        template = NotificationTemplate(
            id=uuid4(),
            tenant_id=None,
            site_id=None,
            template_key="TEST",
            delivery_channel=DeliveryChannel.WHATSAPP,
            language="de",
            whatsapp_template_name=None,
            whatsapp_template_namespace=None,
            subject=None,
            body_template="Plain only",
            body_html=None,
            is_active=True,
            requires_approval=False,
            approval_status=None,
            expected_params=[],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        assert template.render_html({}) is None


class TestDriverPreferences:
    """Tests for DriverPreferences."""

    def test_is_opted_in_whatsapp(self):
        """Check WhatsApp opt-in status."""
        prefs = DriverPreferences(
            id=uuid4(),
            tenant_id=1,
            driver_id="D001",
            preferred_channel=DeliveryChannel.WHATSAPP,
            whatsapp_opted_in=True,
            whatsapp_opted_in_at=datetime.utcnow(),
            email_opted_in=False,
            email_opted_in_at=None,
            sms_opted_in=False,
            sms_opted_in_at=None,
            contact_verified=True,
            contact_verified_at=datetime.utcnow(),
            quiet_hours_start=None,
            quiet_hours_end=None,
            timezone="Europe/Vienna",
            consent_given_at=datetime.utcnow(),
            consent_source="PORTAL",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        assert prefs.is_opted_in(DeliveryChannel.WHATSAPP) is True
        assert prefs.is_opted_in(DeliveryChannel.EMAIL) is False
        assert prefs.is_opted_in(DeliveryChannel.SMS) is False

    def test_quiet_hours_normal(self):
        """Quiet hours during normal range (e.g., 14:00-18:00)."""
        prefs = DriverPreferences(
            id=uuid4(),
            tenant_id=1,
            driver_id="D001",
            preferred_channel=DeliveryChannel.WHATSAPP,
            whatsapp_opted_in=True,
            whatsapp_opted_in_at=datetime.utcnow(),
            email_opted_in=False,
            email_opted_in_at=None,
            sms_opted_in=False,
            sms_opted_in_at=None,
            contact_verified=True,
            contact_verified_at=datetime.utcnow(),
            quiet_hours_start=time(14, 0),
            quiet_hours_end=time(18, 0),
            timezone="Europe/Vienna",
            consent_given_at=datetime.utcnow(),
            consent_source="PORTAL",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        assert prefs.is_quiet_hours(time(15, 0)) is True
        assert prefs.is_quiet_hours(time(10, 0)) is False
        assert prefs.is_quiet_hours(time(19, 0)) is False

    def test_quiet_hours_overnight(self):
        """Quiet hours spanning midnight (e.g., 22:00-07:00)."""
        prefs = DriverPreferences(
            id=uuid4(),
            tenant_id=1,
            driver_id="D001",
            preferred_channel=DeliveryChannel.WHATSAPP,
            whatsapp_opted_in=True,
            whatsapp_opted_in_at=datetime.utcnow(),
            email_opted_in=False,
            email_opted_in_at=None,
            sms_opted_in=False,
            sms_opted_in_at=None,
            contact_verified=True,
            contact_verified_at=datetime.utcnow(),
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(7, 0),
            timezone="Europe/Vienna",
            consent_given_at=datetime.utcnow(),
            consent_source="PORTAL",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        assert prefs.is_quiet_hours(time(23, 0)) is True
        assert prefs.is_quiet_hours(time(3, 0)) is True
        assert prefs.is_quiet_hours(time(10, 0)) is False
        assert prefs.is_quiet_hours(time(12, 0)) is False


class TestNotificationOutbox:
    """Tests for NotificationOutbox."""

    def test_can_retry_pending(self):
        """Pending message with attempts left can retry."""
        outbox = NotificationOutbox(
            id=uuid4(),
            tenant_id=1,
            job_id=uuid4(),
            driver_id="D001",
            driver_name="Max",
            recipient_hash=None,
            delivery_channel=DeliveryChannel.WHATSAPP,
            message_template="PORTAL_INVITE",
            message_params={},
            portal_url="https://example.com",
            snapshot_id=uuid4(),
            reference_type="SNAPSHOT",
            reference_id=uuid4(),
            status=OutboxStatus.PENDING,
            attempt_count=1,
            max_attempts=3,
            next_attempt_at=datetime.utcnow(),
            last_attempt_at=datetime.utcnow(),
            provider_message_id=None,
            provider_status=None,
            provider_response=None,
            error_code=None,
            error_message=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            sent_at=None,
            delivered_at=None,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        assert outbox.can_retry is True

    def test_cannot_retry_max_attempts(self):
        """Message at max attempts cannot retry."""
        outbox = NotificationOutbox(
            id=uuid4(),
            tenant_id=1,
            job_id=uuid4(),
            driver_id="D001",
            driver_name="Max",
            recipient_hash=None,
            delivery_channel=DeliveryChannel.WHATSAPP,
            message_template="PORTAL_INVITE",
            message_params={},
            portal_url="https://example.com",
            snapshot_id=uuid4(),
            reference_type="SNAPSHOT",
            reference_id=uuid4(),
            status=OutboxStatus.PENDING,
            attempt_count=3,
            max_attempts=3,
            next_attempt_at=datetime.utcnow(),
            last_attempt_at=datetime.utcnow(),
            provider_message_id=None,
            provider_status=None,
            provider_response=None,
            error_code=None,
            error_message=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            sent_at=None,
            delivered_at=None,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        assert outbox.can_retry is False

    def test_cannot_retry_expired(self):
        """Expired message cannot retry."""
        outbox = NotificationOutbox(
            id=uuid4(),
            tenant_id=1,
            job_id=uuid4(),
            driver_id="D001",
            driver_name="Max",
            recipient_hash=None,
            delivery_channel=DeliveryChannel.WHATSAPP,
            message_template="PORTAL_INVITE",
            message_params={},
            portal_url="https://example.com",
            snapshot_id=uuid4(),
            reference_type="SNAPSHOT",
            reference_id=uuid4(),
            status=OutboxStatus.PENDING,
            attempt_count=1,
            max_attempts=3,
            next_attempt_at=datetime.utcnow(),
            last_attempt_at=datetime.utcnow(),
            provider_message_id=None,
            provider_status=None,
            provider_response=None,
            error_code=None,
            error_message=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            sent_at=None,
            delivered_at=None,
            expires_at=datetime.utcnow() - timedelta(hours=1),  # Expired
        )

        assert outbox.can_retry is False


# =============================================================================
# PROVIDER TESTS
# =============================================================================

class TestMockProvider:
    """Tests for MockProvider."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Mock provider sends successfully."""
        provider = MockProvider()

        result = await provider.send(
            recipient="436641234567",
            template_name="TEST",
            template_params={"name": "Max"},
        )

        assert result.success is True
        assert result.provider_message_id is not None
        assert len(provider.get_sent_messages()) == 1

    @pytest.mark.asyncio
    async def test_send_failure(self):
        """Mock provider fails when configured."""
        provider = MockProvider(should_fail=True)

        result = await provider.send(
            recipient="436641234567",
            template_name="TEST",
            template_params={},
        )

        assert result.success is False
        assert result.error_code == "MOCK_FAILURE"
        assert len(provider.get_sent_messages()) == 0

    @pytest.mark.asyncio
    async def test_send_with_delay(self):
        """Mock provider respects delay."""
        provider = MockProvider(delay_ms=100)

        start = datetime.utcnow()
        result = await provider.send(
            recipient="test@example.com",
            template_name="TEST",
            template_params={},
        )
        duration = (datetime.utcnow() - start).total_seconds()

        assert result.success is True
        assert duration >= 0.09  # At least 90ms

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Health check passes when not failing."""
        provider = MockProvider()
        assert await provider.check_health() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Health check fails when configured to fail."""
        provider = MockProvider(should_fail=True)
        assert await provider.check_health() is False

    def test_clear_messages(self):
        """Sent messages can be cleared."""
        provider = MockProvider()
        provider._sent_messages = [{"id": "1"}, {"id": "2"}]

        provider.clear_messages()

        assert len(provider.get_sent_messages()) == 0


class TestProviderResult:
    """Tests for ProviderResult."""

    def test_ok_result(self):
        """Create successful result."""
        result = ProviderResult.ok(
            message_id="msg-123",
            status="sent",
            duration_ms=50,
        )

        assert result.success is True
        assert result.provider_message_id == "msg-123"
        assert result.provider_status == "sent"
        assert result.duration_ms == 50
        assert result.error_code is None

    def test_error_result(self):
        """Create error result."""
        result = ProviderResult.error(
            code="TIMEOUT",
            message="Request timed out",
            is_retryable=True,
        )

        assert result.success is False
        assert result.error_code == "TIMEOUT"
        assert result.error_message == "Request timed out"
        assert result.is_retryable is True

    def test_error_non_retryable(self):
        """Non-retryable error result."""
        result = ProviderResult.error(
            code="INVALID_RECIPIENT",
            message="Phone number invalid",
            is_retryable=False,
        )

        assert result.success is False
        assert result.is_retryable is False


# =============================================================================
# WHATSAPP PROVIDER TESTS
# =============================================================================

class TestWhatsAppProvider:
    """Tests for WhatsApp provider."""

    def test_validate_recipient_valid(self):
        """Valid phone numbers pass validation."""
        from ..providers.whatsapp import WhatsAppCloudProvider

        provider = WhatsAppCloudProvider(
            phone_number_id="test",
            access_token="test",
        )

        assert provider.validate_recipient("436641234567") is True
        assert provider.validate_recipient("+436641234567") is True
        assert provider.validate_recipient("43 664 1234567") is True

    def test_validate_recipient_invalid(self):
        """Invalid phone numbers fail validation."""
        from ..providers.whatsapp import WhatsAppCloudProvider

        provider = WhatsAppCloudProvider(
            phone_number_id="test",
            access_token="test",
        )

        assert provider.validate_recipient("") is False
        assert provider.validate_recipient("abc") is False
        assert provider.validate_recipient("123") is False  # Too short


class TestEmailProvider:
    """Tests for Email provider."""

    def test_validate_recipient_valid(self):
        """Valid email addresses pass validation."""
        from ..providers.email import SendGridProvider

        provider = SendGridProvider(api_key="test")

        assert provider.validate_recipient("test@example.com") is True
        assert provider.validate_recipient("user.name@domain.co.at") is True
        assert provider.validate_recipient("user+tag@example.com") is True

    def test_validate_recipient_invalid(self):
        """Invalid email addresses fail validation."""
        from ..providers.email import SendGridProvider

        provider = SendGridProvider(api_key="test")

        assert provider.validate_recipient("") is False
        assert provider.validate_recipient("not-an-email") is False
        assert provider.validate_recipient("@example.com") is False


# =============================================================================
# WEBHOOK PARSING TESTS
# =============================================================================

class TestWhatsAppWebhook:
    """Tests for WhatsApp webhook parsing."""

    def test_parse_delivered_status(self):
        """Parse delivered status webhook."""
        from ..providers.whatsapp import parse_whatsapp_webhook

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.123",
                            "recipient_id": "436641234567",
                            "status": "delivered",
                            "timestamp": "1704067200",
                        }]
                    }
                }]
            }]
        }

        events = parse_whatsapp_webhook(payload)

        assert len(events) == 1
        assert events[0]["message_id"] == "wamid.123"
        assert events[0]["event_type"] == "DELIVERED"

    def test_parse_failed_status(self):
        """Parse failed status webhook with error."""
        from ..providers.whatsapp import parse_whatsapp_webhook

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.456",
                            "recipient_id": "436641234567",
                            "status": "failed",
                            "timestamp": "1704067200",
                            "errors": [{
                                "code": 131047,
                                "title": "Re-engagement message",
                            }]
                        }]
                    }
                }]
            }]
        }

        events = parse_whatsapp_webhook(payload)

        assert len(events) == 1
        assert events[0]["event_type"] == "FAILED"
        assert events[0]["error_code"] == 131047


class TestSendGridWebhook:
    """Tests for SendGrid webhook parsing."""

    def test_parse_delivered_event(self):
        """Parse delivered event from SendGrid."""
        from ..providers.email import parse_sendgrid_webhook

        events = [{
            "email": "test@example.com",
            "event": "delivered",
            "sg_message_id": "msg-123.filter",
            "timestamp": 1704067200,
        }]

        normalized = parse_sendgrid_webhook(events)

        assert len(normalized) == 1
        assert normalized[0]["message_id"] == "msg-123"
        assert normalized[0]["event_type"] == "DELIVERED"

    def test_parse_bounce_event(self):
        """Parse bounce event from SendGrid."""
        from ..providers.email import parse_sendgrid_webhook

        events = [{
            "email": "test@example.com",
            "event": "bounce",
            "sg_message_id": "msg-456",
            "timestamp": 1704067200,
            "reason": "Invalid mailbox",
        }]

        normalized = parse_sendgrid_webhook(events)

        assert len(normalized) == 1
        assert normalized[0]["event_type"] == "FAILED"
        assert normalized[0]["error_code"] == "BOUNCE"


# =============================================================================
# JOB STATUS TESTS
# =============================================================================

class TestNotificationJob:
    """Tests for NotificationJob."""

    def test_completion_rate_empty(self):
        """Completion rate is 0 for empty job."""
        job = NotificationJob(
            id=uuid4(),
            tenant_id=1,
            site_id=None,
            job_type=NotificationJobType.SNAPSHOT_PUBLISH,
            reference_type="SNAPSHOT",
            reference_id=uuid4(),
            target_driver_ids=[],
            target_group=None,
            delivery_channel=DeliveryChannel.WHATSAPP,
            status=JobStatus.PENDING,
            total_count=0,
            sent_count=0,
            delivered_count=0,
            failed_count=0,
            initiated_by="test@example.com",
            initiated_at=datetime.utcnow(),
            started_at=None,
            completed_at=None,
            priority=5,
            retry_policy=RetryPolicy(),
            scheduled_at=None,
            expires_at=None,
            last_error=None,
            error_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        assert job.completion_rate == 0.0

    def test_completion_rate_partial(self):
        """Completion rate calculated for partial completion."""
        job = NotificationJob(
            id=uuid4(),
            tenant_id=1,
            site_id=None,
            job_type=NotificationJobType.SNAPSHOT_PUBLISH,
            reference_type="SNAPSHOT",
            reference_id=uuid4(),
            target_driver_ids=["D1", "D2", "D3", "D4"],
            target_group=None,
            delivery_channel=DeliveryChannel.WHATSAPP,
            status=JobStatus.PROCESSING,
            total_count=4,
            sent_count=2,
            delivered_count=1,
            failed_count=0,
            initiated_by="test@example.com",
            initiated_at=datetime.utcnow(),
            started_at=datetime.utcnow(),
            completed_at=None,
            priority=5,
            retry_policy=RetryPolicy(),
            scheduled_at=None,
            expires_at=None,
            last_error=None,
            error_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # (2 + 1) / 4 * 100 = 75%
        assert job.completion_rate == 75.0

    def test_is_complete_pending(self):
        """Pending job is not complete."""
        job = NotificationJob(
            id=uuid4(),
            tenant_id=1,
            site_id=None,
            job_type=NotificationJobType.SNAPSHOT_PUBLISH,
            reference_type="SNAPSHOT",
            reference_id=uuid4(),
            target_driver_ids=["D1"],
            target_group=None,
            delivery_channel=DeliveryChannel.WHATSAPP,
            status=JobStatus.PENDING,
            total_count=1,
            sent_count=0,
            delivered_count=0,
            failed_count=0,
            initiated_by="test@example.com",
            initiated_at=datetime.utcnow(),
            started_at=None,
            completed_at=None,
            priority=5,
            retry_policy=RetryPolicy(),
            scheduled_at=None,
            expires_at=None,
            last_error=None,
            error_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        assert job.is_complete is False

    def test_is_complete_completed(self):
        """Completed job is complete."""
        job = NotificationJob(
            id=uuid4(),
            tenant_id=1,
            site_id=None,
            job_type=NotificationJobType.SNAPSHOT_PUBLISH,
            reference_type="SNAPSHOT",
            reference_id=uuid4(),
            target_driver_ids=["D1"],
            target_group=None,
            delivery_channel=DeliveryChannel.WHATSAPP,
            status=JobStatus.COMPLETED,
            total_count=1,
            sent_count=1,
            delivered_count=1,
            failed_count=0,
            initiated_by="test@example.com",
            initiated_at=datetime.utcnow(),
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            priority=5,
            retry_policy=RetryPolicy(),
            scheduled_at=None,
            expires_at=None,
            last_error=None,
            error_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        assert job.is_complete is True
