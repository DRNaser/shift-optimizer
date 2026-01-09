"""
SOLVEREIGN V4.1 - Notification Models
======================================

Data classes for the notification pipeline.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4


class DeliveryChannel(str, Enum):
    """Notification delivery channel."""
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


class NotificationJobType(str, Enum):
    """Type of notification job."""
    SNAPSHOT_PUBLISH = "SNAPSHOT_PUBLISH"  # New schedule published
    REMINDER = "REMINDER"                   # Reminder for unacknowledged
    RESEND = "RESEND"                       # Manual resend by dispatcher
    PORTAL_INVITE = "PORTAL_INVITE"         # First-time portal access
    CUSTOM = "CUSTOM"                       # Custom notification


class JobStatus(str, Enum):
    """Notification job status."""
    PENDING = "PENDING"              # Not yet started
    PROCESSING = "PROCESSING"        # Worker is processing
    COMPLETED = "COMPLETED"          # All messages sent/delivered
    PARTIALLY_FAILED = "PARTIALLY_FAILED"  # Some failures
    FAILED = "FAILED"                # All failed
    CANCELLED = "CANCELLED"          # Cancelled by user


class OutboxStatus(str, Enum):
    """Individual outbox message status."""
    PENDING = "PENDING"          # Waiting to be sent
    SENDING = "SENDING"          # Claimed by worker, sending in progress
    PROCESSING = "PROCESSING"    # Currently being sent (legacy, use SENDING)
    SENT = "SENT"                # Sent to provider
    DELIVERED = "DELIVERED"      # Confirmed delivered (webhook)
    RETRYING = "RETRYING"        # Failed, waiting for retry
    SKIPPED = "SKIPPED"          # Skipped (e.g., do-not-contact, opted-out)
    FAILED = "FAILED"            # Failed after all retries
    DEAD = "DEAD"                # Dead-letter queue (manual intervention needed)
    EXPIRED = "EXPIRED"          # Past expires_at
    CANCELLED = "CANCELLED"      # Cancelled


class WebhookEventType(str, Enum):
    """Webhook event types from providers."""
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"
    UNDELIVERABLE = "UNDELIVERABLE"
    # Bounce/complaint events (trigger auto-opt-out)
    BOUNCE = "BOUNCE"              # Hard bounce (invalid address)
    SOFT_BOUNCE = "SOFT_BOUNCE"    # Soft bounce (temporary, retryable)
    COMPLAINT = "COMPLAINT"        # Spam complaint (user marked as spam)
    UNSUBSCRIBE = "UNSUBSCRIBE"    # User unsubscribed


class DoNotContactReason(str, Enum):
    """Reason for do_not_contact flag."""
    HARD_BOUNCE = "HARD_BOUNCE"         # Email bounced (invalid address)
    SOFT_BOUNCE_LIMIT = "SOFT_BOUNCE_LIMIT"  # Too many soft bounces
    SPAM_COMPLAINT = "SPAM_COMPLAINT"   # User reported as spam
    UNSUBSCRIBE = "UNSUBSCRIBE"         # User unsubscribed
    MANUAL = "MANUAL"                   # Manually set by admin
    INVALID_PHONE = "INVALID_PHONE"     # WhatsApp invalid phone number


@dataclass
class RetryPolicy:
    """Retry policy for failed messages."""
    max_attempts: int = 3
    backoff_seconds: List[int] = field(default_factory=lambda: [60, 300, 900])

    def get_next_delay(self, attempt_count: int) -> int:
        """Get delay in seconds for next retry attempt."""
        if attempt_count >= len(self.backoff_seconds):
            return self.backoff_seconds[-1]
        return self.backoff_seconds[attempt_count]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "max_attempts": self.max_attempts,
            "backoff_seconds": self.backoff_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryPolicy":
        """Create from dict."""
        return cls(
            max_attempts=data.get("max_attempts", 3),
            backoff_seconds=data.get("backoff_seconds", [60, 300, 900]),
        )


@dataclass
class NotificationJob:
    """High-level notification job tracking."""
    id: UUID
    tenant_id: int
    site_id: Optional[UUID]

    job_type: NotificationJobType
    reference_type: Optional[str]
    reference_id: Optional[UUID]

    target_driver_ids: Optional[List[str]]
    target_group: Optional[str]  # UNREAD, UNACKED, DECLINED, ALL
    delivery_channel: DeliveryChannel

    status: JobStatus
    total_count: int
    sent_count: int
    delivered_count: int
    failed_count: int

    initiated_by: str
    initiated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    priority: int
    retry_policy: RetryPolicy
    scheduled_at: Optional[datetime]
    expires_at: Optional[datetime]

    last_error: Optional[str]
    error_count: int

    created_at: datetime
    updated_at: datetime

    @property
    def completion_rate(self) -> float:
        """Percentage of messages successfully sent/delivered."""
        if self.total_count == 0:
            return 0.0
        return (self.sent_count + self.delivered_count) / self.total_count * 100

    @property
    def is_complete(self) -> bool:
        """Check if job is in terminal state."""
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.PARTIALLY_FAILED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )


@dataclass
class NotificationOutbox:
    """Individual message in the outbox."""
    id: UUID
    tenant_id: int
    job_id: Optional[UUID]

    driver_id: str
    driver_name: Optional[str]
    recipient_hash: Optional[str]  # SHA-256 of phone/email
    delivery_channel: DeliveryChannel

    message_template: str
    message_params: Dict[str, Any]
    portal_url: Optional[str]

    snapshot_id: Optional[UUID]
    reference_type: Optional[str]
    reference_id: Optional[UUID]

    status: OutboxStatus
    attempt_count: int
    max_attempts: int
    next_attempt_at: Optional[datetime]
    last_attempt_at: Optional[datetime]

    provider_message_id: Optional[str]
    provider_status: Optional[str]
    provider_response: Optional[Dict[str, Any]]

    error_code: Optional[str]
    error_message: Optional[str]

    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime]
    expires_at: Optional[datetime]

    @property
    def can_retry(self) -> bool:
        """Check if message can be retried."""
        return (
            self.status in (OutboxStatus.PENDING, OutboxStatus.PROCESSING)
            and self.attempt_count < self.max_attempts
            and (self.expires_at is None or self.expires_at > datetime.utcnow())
        )


@dataclass
class DeliveryLog:
    """Log entry for delivery attempt or webhook."""
    id: int
    log_id: UUID
    tenant_id: int
    outbox_id: UUID

    attempt_number: int
    event_type: str  # ATTEMPT, SENT, DELIVERED, FAILED, WEBHOOK

    provider: Optional[str]
    provider_message_id: Optional[str]
    provider_status: Optional[str]
    provider_response: Optional[Dict[str, Any]]

    webhook_event_id: Optional[str]
    webhook_timestamp: Optional[datetime]
    webhook_raw: Optional[Dict[str, Any]]

    error_code: Optional[str]
    error_message: Optional[str]
    is_retryable: bool

    event_at: datetime
    duration_ms: Optional[int]
    created_at: datetime


@dataclass
class NotificationTemplate:
    """Message template for notifications."""
    id: UUID
    tenant_id: Optional[int]  # NULL = system default
    site_id: Optional[UUID]

    template_key: str
    delivery_channel: DeliveryChannel
    language: str

    whatsapp_template_name: Optional[str]
    whatsapp_template_namespace: Optional[str]

    subject: Optional[str]  # For email
    body_template: str
    body_html: Optional[str]  # HTML version for email

    is_active: bool
    requires_approval: bool
    approval_status: Optional[str]

    expected_params: List[str]

    created_at: datetime
    updated_at: datetime

    def render(self, params: Dict[str, Any]) -> str:
        """Render template with given parameters."""
        result = self.body_template
        for key, value in params.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def render_html(self, params: Dict[str, Any]) -> Optional[str]:
        """Render HTML template with given parameters."""
        if not self.body_html:
            return None
        result = self.body_html
        for key, value in params.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result


@dataclass
class DriverPreferences:
    """Driver notification preferences."""
    id: UUID
    tenant_id: int
    driver_id: str

    preferred_channel: DeliveryChannel
    whatsapp_opted_in: bool
    whatsapp_opted_in_at: Optional[datetime]
    email_opted_in: bool
    email_opted_in_at: Optional[datetime]
    sms_opted_in: bool
    sms_opted_in_at: Optional[datetime]

    contact_verified: bool
    contact_verified_at: Optional[datetime]

    quiet_hours_start: Optional[time]
    quiet_hours_end: Optional[time]
    timezone: str

    consent_given_at: Optional[datetime]
    consent_source: Optional[str]

    # Bounce/complaint handling - auto-set by webhook handlers
    do_not_contact_email: bool = False
    do_not_contact_email_reason: Optional[str] = None  # DoNotContactReason value
    do_not_contact_email_at: Optional[datetime] = None
    do_not_contact_whatsapp: bool = False
    do_not_contact_whatsapp_reason: Optional[str] = None
    do_not_contact_whatsapp_at: Optional[datetime] = None
    do_not_contact_sms: bool = False
    do_not_contact_sms_reason: Optional[str] = None
    do_not_contact_sms_at: Optional[datetime] = None

    # Bounce tracking (soft bounces don't immediately trigger do_not_contact)
    email_soft_bounce_count: int = 0
    whatsapp_soft_bounce_count: int = 0
    sms_soft_bounce_count: int = 0

    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_opted_in(self, channel: DeliveryChannel) -> bool:
        """Check if driver opted in for given channel."""
        if channel == DeliveryChannel.WHATSAPP:
            return self.whatsapp_opted_in
        elif channel == DeliveryChannel.EMAIL:
            return self.email_opted_in
        elif channel == DeliveryChannel.SMS:
            return self.sms_opted_in
        return False

    def can_contact(self, channel: DeliveryChannel) -> bool:
        """Check if driver can be contacted on given channel (opted in AND not do_not_contact)."""
        if not self.is_opted_in(channel):
            return False
        if channel == DeliveryChannel.WHATSAPP:
            return not self.do_not_contact_whatsapp
        elif channel == DeliveryChannel.EMAIL:
            return not self.do_not_contact_email
        elif channel == DeliveryChannel.SMS:
            return not self.do_not_contact_sms
        return False

    def is_quiet_hours(self, current_time: time) -> bool:
        """Check if current time is within quiet hours."""
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False

        # Handle overnight quiet hours (e.g., 22:00 - 07:00)
        if self.quiet_hours_start > self.quiet_hours_end:
            return current_time >= self.quiet_hours_start or current_time <= self.quiet_hours_end
        else:
            return self.quiet_hours_start <= current_time <= self.quiet_hours_end


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

@dataclass
class SendNotificationRequest:
    """Request to send notifications to drivers."""
    tenant_id: int
    site_id: Optional[UUID]
    job_type: NotificationJobType
    reference_type: str
    reference_id: UUID
    driver_ids: List[str]
    portal_urls: Dict[str, str]  # {driver_id: portal_url}
    delivery_channel: DeliveryChannel
    template_key: str
    template_params: Dict[str, Any] = field(default_factory=dict)
    initiated_by: str = ""
    scheduled_at: Optional[datetime] = None
    priority: int = 5


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""
    outbox_id: UUID
    driver_id: str
    success: bool
    provider_message_id: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]


@dataclass
class JobStatusResponse:
    """Response for job status query."""
    job_id: UUID
    status: JobStatus
    total_count: int
    sent_count: int
    delivered_count: int
    failed_count: int
    pending_count: int
    completion_rate: float
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    @property
    def pending_count(self) -> int:
        """Calculate pending count."""
        return self.total_count - self.sent_count - self.delivered_count - self.failed_count
