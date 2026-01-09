"""
SOLVEREIGN V4.1 - Portal Models
================================

Data models for driver portal magic links and acknowledgments.

Security:
    - Tokens are stored as jti_hash (SHA-256) - NEVER store raw token
    - ACK records are immutable (arbeitsrechtlich relevant)
    - All models include tenant_id for RLS isolation

GDPR:
    - Minimal data storage
    - IP addresses stored as hash only
    - No raw token logging
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional
import hashlib
import secrets


# =============================================================================
# ENUMS
# =============================================================================

class TokenScope(str, Enum):
    """Scope of portal token permissions."""
    READ = "READ"           # Can view plan only
    ACK = "ACK"             # Can acknowledge only
    READ_ACK = "READ_ACK"   # Can view and acknowledge


class TokenStatus(str, Enum):
    """Status of a portal token."""
    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"
    RATE_LIMITED = "rate_limited"


class AckStatus(str, Enum):
    """Driver acknowledgment status."""
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class AckReasonCode(str, Enum):
    """Reason codes for declining a plan."""
    SCHEDULING_CONFLICT = "SCHEDULING_CONFLICT"
    PERSONAL_REASONS = "PERSONAL_REASONS"
    HEALTH_ISSUE = "HEALTH_ISSUE"
    VACATION_CONFLICT = "VACATION_CONFLICT"
    OTHER = "OTHER"


class AckSource(str, Enum):
    """Source of acknowledgment."""
    PORTAL = "PORTAL"                       # Driver via portal
    DISPATCHER_OVERRIDE = "DISPATCHER_OVERRIDE"  # Dispatcher override


class DeliveryChannel(str, Enum):
    """Notification delivery channel."""
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"
    SMS = "SMS"
    MANUAL = "MANUAL"


class PortalAction(str, Enum):
    """Actions for audit trail."""
    TOKEN_ISSUED = "TOKEN_ISSUED"
    TOKEN_VALIDATED = "TOKEN_VALIDATED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    PLAN_READ = "PLAN_READ"
    PLAN_ACCEPTED = "PLAN_ACCEPTED"
    PLAN_DECLINED = "PLAN_DECLINED"
    ACK_OVERRIDE = "ACK_OVERRIDE"
    VIEW_RENDERED = "VIEW_RENDERED"
    RATE_LIMITED = "RATE_LIMITED"


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class PortalToken:
    """
    Portal magic link token.

    Security: Only jti_hash is stored in DB, never the raw token.
    """
    id: Optional[int] = None

    # Tenant/Site context
    tenant_id: int = 0
    site_id: int = 0

    # Reference
    snapshot_id: str = ""
    driver_id: str = ""

    # Token properties
    scope: TokenScope = TokenScope.READ_ACK
    jti_hash: str = ""  # SHA-256 of jti (NEVER store raw jti)

    # Timestamps
    issued_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(days=14))
    revoked_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    # Delivery tracking
    delivery_channel: Optional[DeliveryChannel] = None
    outbox_id: Optional[str] = None

    # Security metadata (hashed)
    ip_hash: Optional[str] = None
    ua_class: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return datetime.utcnow() > self.expires_at

    @property
    def is_revoked(self) -> bool:
        """Check if token is revoked."""
        return self.revoked_at is not None

    @property
    def is_valid(self) -> bool:
        """Check if token is still valid."""
        return not self.is_expired and not self.is_revoked

    @property
    def status(self) -> TokenStatus:
        """Get current token status."""
        if self.is_revoked:
            return TokenStatus.REVOKED
        if self.is_expired:
            return TokenStatus.EXPIRED
        return TokenStatus.VALID

    @property
    def can_read(self) -> bool:
        """Check if token allows reading."""
        return self.scope in (TokenScope.READ, TokenScope.READ_ACK) and self.is_valid

    @property
    def can_ack(self) -> bool:
        """Check if token allows acknowledgment."""
        return self.scope in (TokenScope.ACK, TokenScope.READ_ACK) and self.is_valid

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (excludes sensitive data)."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "site_id": self.site_id,
            "snapshot_id": self.snapshot_id,
            "driver_id": self.driver_id,
            "scope": self.scope.value,
            "status": self.status.value,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_valid": self.is_valid,
        }


@dataclass
class ReadReceipt:
    """
    Tracks when a driver reads their published plan.

    Idempotent: multiple reads update last_read_at and increment count.
    """
    id: Optional[int] = None

    # Tenant/Site context
    tenant_id: int = 0
    site_id: int = 0

    # Reference
    snapshot_id: str = ""
    driver_id: str = ""

    # Read tracking
    first_read_at: datetime = field(default_factory=datetime.utcnow)
    last_read_at: datetime = field(default_factory=datetime.utcnow)
    read_count: int = 1

    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_first_read(self) -> bool:
        """Check if this is the first read."""
        return self.read_count == 1

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "driver_id": self.driver_id,
            "first_read_at": self.first_read_at.isoformat() if self.first_read_at else None,
            "last_read_at": self.last_read_at.isoformat() if self.last_read_at else None,
            "read_count": self.read_count,
            "is_first_read": self.is_first_read,
        }


@dataclass
class DriverAck:
    """
    Driver acknowledgment for published plan.

    IMMUTABLE: Once created, cannot be modified except via DISPATCHER_OVERRIDE.
    This is arbeitsrechtlich relevant.
    """
    id: Optional[int] = None

    # Tenant/Site context
    tenant_id: int = 0
    site_id: int = 0

    # Reference
    snapshot_id: str = ""
    driver_id: str = ""

    # Acknowledgment
    status: AckStatus = AckStatus.ACCEPTED
    ack_at: datetime = field(default_factory=datetime.utcnow)

    # Optional reason (for DECLINED)
    reason_code: Optional[AckReasonCode] = None
    free_text: Optional[str] = None  # Max 200 chars

    # Source tracking
    source: AckSource = AckSource.PORTAL

    # Override tracking (only for DISPATCHER_OVERRIDE)
    override_by: Optional[str] = None
    override_reason: Optional[str] = None

    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_accepted(self) -> bool:
        """Check if plan was accepted."""
        return self.status == AckStatus.ACCEPTED

    @property
    def is_declined(self) -> bool:
        """Check if plan was declined."""
        return self.status == AckStatus.DECLINED

    @property
    def is_override(self) -> bool:
        """Check if this was a dispatcher override."""
        return self.source == AckSource.DISPATCHER_OVERRIDE

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        result = {
            "snapshot_id": self.snapshot_id,
            "driver_id": self.driver_id,
            "status": self.status.value,
            "ack_at": self.ack_at.isoformat() if self.ack_at else None,
            "source": self.source.value,
        }
        if self.reason_code:
            result["reason_code"] = self.reason_code.value
        if self.free_text:
            result["free_text"] = self.free_text
        if self.is_override:
            result["override_by"] = self.override_by
            result["override_reason"] = self.override_reason
        return result


@dataclass
class DriverView:
    """
    Pre-rendered driver view for a snapshot.

    Generated from plan_snapshots.assignments_snapshot (DB),
    NOT from Google Sheets.
    """
    id: Optional[int] = None

    # Tenant/Site context
    tenant_id: int = 0
    site_id: int = 0

    # Reference
    snapshot_id: str = ""
    driver_id: str = ""

    # Artifact
    artifact_uri: str = ""      # Path to rendered view
    artifact_hash: Optional[str] = None  # SHA-256 for integrity

    # Version
    render_version: int = 1

    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "driver_id": self.driver_id,
            "artifact_uri": self.artifact_uri,
            "render_version": self.render_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class SnapshotSupersede:
    """
    Maps old snapshots to their replacements.

    Used to show "superseded" banner on old links.
    """
    id: Optional[int] = None

    tenant_id: int = 0

    old_snapshot_id: str = ""
    new_snapshot_id: str = ""

    superseded_at: datetime = field(default_factory=datetime.utcnow)
    superseded_by: Optional[str] = None
    reason: Optional[str] = None

    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "old_snapshot_id": self.old_snapshot_id,
            "new_snapshot_id": self.new_snapshot_id,
            "superseded_at": self.superseded_at.isoformat() if self.superseded_at else None,
            "superseded_by": self.superseded_by,
            "reason": self.reason,
        }


# =============================================================================
# AGGREGATED MODELS
# =============================================================================

@dataclass
class PortalStatus:
    """
    Aggregated portal status for a snapshot.

    Used by dispatchers to monitor acknowledgment progress.
    """
    snapshot_id: str = ""

    total_drivers: int = 0
    unread_count: int = 0
    read_count: int = 0
    accepted_count: int = 0
    declined_count: int = 0
    pending_count: int = 0  # Read but not acked

    # Lists for follow-up
    unread_drivers: List[str] = field(default_factory=list)
    unacked_drivers: List[str] = field(default_factory=list)
    declined_drivers: List[str] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        """Percentage of drivers who have acknowledged."""
        if self.total_drivers == 0:
            return 0.0
        return (self.accepted_count + self.declined_count) / self.total_drivers * 100

    @property
    def read_rate(self) -> float:
        """Percentage of drivers who have read the plan."""
        if self.total_drivers == 0:
            return 0.0
        return self.read_count / self.total_drivers * 100

    @property
    def acceptance_rate(self) -> float:
        """Percentage of acknowledged drivers who accepted."""
        acked = self.accepted_count + self.declined_count
        if acked == 0:
            return 0.0
        return self.accepted_count / acked * 100

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "total_drivers": self.total_drivers,
            "unread_count": self.unread_count,
            "read_count": self.read_count,
            "accepted_count": self.accepted_count,
            "declined_count": self.declined_count,
            "pending_count": self.pending_count,
            "completion_rate": round(self.completion_rate, 1),
            "read_rate": round(self.read_rate, 1),
            "acceptance_rate": round(self.acceptance_rate, 1),
        }


@dataclass
class TokenValidationResult:
    """
    Result of token validation.

    Security: Never includes raw token, only jti_hash.
    """
    is_valid: bool = False
    status: TokenStatus = TokenStatus.INVALID

    # Token data (if valid)
    token: Optional[PortalToken] = None

    # Error details
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # Rate limit info
    rate_limited: bool = False
    retry_after_seconds: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (excludes token details for security)."""
        result = {
            "is_valid": self.is_valid,
            "status": self.status.value,
        }
        if self.error_code:
            result["error_code"] = self.error_code
            result["error_message"] = self.error_message
        if self.rate_limited:
            result["rate_limited"] = True
            result["retry_after_seconds"] = self.retry_after_seconds
        return result


@dataclass
class RateLimitResult:
    """
    Result of rate limit check.
    """
    is_allowed: bool = True
    current_count: int = 0
    max_requests: int = 100
    window_resets_at: Optional[datetime] = None

    @property
    def remaining_requests(self) -> int:
        """Number of requests remaining in window."""
        return max(0, self.max_requests - self.current_count)

    @property
    def retry_after_seconds(self) -> int:
        """Seconds until rate limit resets."""
        if self.window_resets_at is None:
            return 0
        delta = self.window_resets_at - datetime.utcnow()
        return max(0, int(delta.total_seconds()))


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_jti() -> str:
    """Generate a cryptographically secure JTI (JWT ID)."""
    return secrets.token_hex(16)  # 128-bit random


def hash_jti(jti: str) -> str:
    """Hash a JTI for storage. NEVER store raw JTI."""
    return hashlib.sha256(jti.encode()).hexdigest()


def hash_ip(ip: str) -> str:
    """Hash an IP address for privacy. NEVER store raw IP."""
    # Add salt from environment or config in production
    salted = f"solvereign_portal:{ip}"
    return hashlib.sha256(salted.encode()).hexdigest()


def validate_free_text(text: Optional[str]) -> Optional[str]:
    """Validate and sanitize free text input."""
    if text is None:
        return None
    text = text.strip()
    if len(text) > 200:
        text = text[:200]
    # Basic XSS prevention
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text if text else None
