"""
Ops-Copilot Pydantic Schemas

Request and response models for the Ops-Copilot API.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
import re


# =============================================================================
# Enums
# =============================================================================


class IdentityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class InviteStatus(str, Enum):
    PENDING = "PENDING"
    USED = "USED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class DraftStatus(str, Enum):
    PENDING_CONFIRM = "PENDING_CONFIRM"
    CONFIRMED = "CONFIRMED"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ActionType(str, Enum):
    CREATE_TICKET = "CREATE_TICKET"
    AUDIT_COMMENT = "AUDIT_COMMENT"
    WHATSAPP_BROADCAST_OPS = "WHATSAPP_BROADCAST_OPS"
    WHATSAPP_BROADCAST_DRIVER = "WHATSAPP_BROADCAST_DRIVER"


class TicketCategory(str, Enum):
    SICK_CALL = "SICK_CALL"
    SHIFT_SWAP = "SHIFT_SWAP"
    VEHICLE_ISSUE = "VEHICLE_ISSUE"
    CUSTOMER_COMPLAINT = "CUSTOMER_COMPLAINT"
    SCHEDULING_REQUEST = "SCHEDULING_REQUEST"
    OTHER = "OTHER"


class TicketPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class BroadcastAudience(str, Enum):
    OPS = "OPS"
    DRIVER = "DRIVER"


class IngestStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


# =============================================================================
# WhatsApp Ingest Schemas
# =============================================================================


class WhatsAppMessage(BaseModel):
    """Incoming WhatsApp message from Clawdbot Gateway."""

    message_id: str = Field(
        ...,
        description="Unique message ID from WhatsApp",
        min_length=1,
        max_length=128,
    )
    wa_user_id: str = Field(
        ...,
        description="WhatsApp user ID (sender)",
        min_length=1,
        max_length=64,
    )
    wa_phone: str = Field(
        ...,
        description="Phone number in E.164 format",
        pattern=r"^\+[1-9]\d{1,14}$",
    )
    text: str = Field(
        ...,
        description="Message text content",
        max_length=4096,
    )
    timestamp: datetime = Field(
        ...,
        description="Message timestamp from WhatsApp",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional message metadata",
    )


class IngestResponse(BaseModel):
    """Response to WhatsApp webhook ingest."""

    status: IngestStatus = Field(
        ...,
        description="Processing status",
    )
    trace_id: str = Field(
        ...,
        description="Trace ID for request correlation",
    )
    reply_text: Optional[str] = Field(
        None,
        description="Reply text for simple synchronous responses",
    )
    draft_id: Optional[str] = Field(
        None,
        description="Draft ID if a write action is pending confirmation",
    )
    error_code: Optional[str] = Field(
        None,
        description="Error code if status is ERROR or REJECTED",
    )
    error_message: Optional[str] = Field(
        None,
        description="Human-readable error message",
    )


# =============================================================================
# Pairing Schemas
# =============================================================================


class CreateInviteRequest(BaseModel):
    """Request to create a pairing invite."""

    user_id: str = Field(
        ...,
        description="UUID of the user to pair",
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    expires_minutes: int = Field(
        default=15,
        ge=5,
        le=60,
        description="Invite expiration time in minutes (5-60)",
    )


class CreateInviteResponse(BaseModel):
    """Response with created pairing invite."""

    invite_id: str = Field(
        ...,
        description="UUID of the created invite",
    )
    otp: str = Field(
        ...,
        description="6-digit OTP (shown once, communicate to user out-of-band)",
    )
    expires_at: datetime = Field(
        ...,
        description="Invite expiration timestamp",
    )
    user_id: str = Field(
        ...,
        description="Target user ID",
    )
    instructions: str = Field(
        ...,
        description="Instructions for the user",
    )


class RevokeIdentityRequest(BaseModel):
    """Request to revoke a WhatsApp identity."""

    identity_id: str = Field(
        ...,
        description="UUID of the identity to revoke",
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    reason: str = Field(
        ...,
        description="Reason for revocation",
        min_length=1,
        max_length=255,
    )


class IdentityResponse(BaseModel):
    """WhatsApp identity information."""

    id: str = Field(..., description="Identity UUID")
    wa_user_id: str = Field(..., description="WhatsApp user ID")
    tenant_id: int = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="Internal user UUID")
    site_id: Optional[int] = Field(None, description="Site ID override")
    status: IdentityStatus = Field(..., description="Identity status")
    paired_at: datetime = Field(..., description="Pairing timestamp")
    paired_via: str = Field(..., description="Pairing method")
    last_activity_at: Optional[datetime] = Field(None, description="Last activity")


# =============================================================================
# Draft Schemas
# =============================================================================


class ConfirmDraftRequest(BaseModel):
    """Request to confirm or cancel a pending draft."""

    confirmed: bool = Field(
        ...,
        description="True to confirm (CONFIRM), False to cancel (CANCEL)",
    )


class DraftResponse(BaseModel):
    """Draft status response."""

    draft_id: str = Field(..., description="Draft UUID")
    status: DraftStatus = Field(..., description="Current draft status")
    action_type: ActionType = Field(..., description="Type of action")
    preview_text: str = Field(..., description="Human-readable action preview")
    expires_at: datetime = Field(..., description="Draft expiration time")
    commit_result: Optional[Dict[str, Any]] = Field(
        None,
        description="Result after successful commit",
    )
    commit_error: Optional[str] = Field(
        None,
        description="Error message if commit failed",
    )


# =============================================================================
# Ticket Schemas
# =============================================================================


class CreateTicketRequest(BaseModel):
    """Request to create a ticket."""

    category: TicketCategory = Field(..., description="Ticket category")
    priority: TicketPriority = Field(
        default=TicketPriority.MEDIUM,
        description="Ticket priority",
    )
    title: str = Field(
        ...,
        description="Ticket title",
        min_length=1,
        max_length=255,
    )
    description: str = Field(
        ...,
        description="Ticket description",
        min_length=1,
        max_length=4000,
    )
    site_id: Optional[int] = Field(None, description="Site ID")
    driver_id: Optional[str] = Field(None, description="Related driver ID")
    tour_id: Optional[int] = Field(None, description="Related tour ID")
    assigned_to: Optional[str] = Field(
        None,
        description="Assignee user UUID",
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )


class UpdateTicketRequest(BaseModel):
    """Request to update a ticket."""

    status: Optional[TicketStatus] = Field(None, description="New status")
    priority: Optional[TicketPriority] = Field(None, description="New priority")
    assigned_to: Optional[str] = Field(None, description="New assignee UUID")


class AddTicketCommentRequest(BaseModel):
    """Request to add a comment to a ticket."""

    content: str = Field(
        ...,
        description="Comment content",
        min_length=1,
        max_length=4000,
    )


class TicketResponse(BaseModel):
    """Ticket information."""

    id: str = Field(..., description="Ticket UUID")
    ticket_number: int = Field(..., description="Human-readable ticket number")
    tenant_id: int = Field(..., description="Tenant ID")
    site_id: Optional[int] = Field(None, description="Site ID")
    category: TicketCategory = Field(..., description="Category")
    priority: TicketPriority = Field(..., description="Priority")
    title: str = Field(..., description="Title")
    description: str = Field(..., description="Description")
    status: TicketStatus = Field(..., description="Status")
    assigned_to: Optional[str] = Field(None, description="Assignee UUID")
    driver_id: Optional[str] = Field(None, description="Related driver")
    source: str = Field(..., description="Creation source")
    created_by: str = Field(..., description="Creator UUID")
    created_at: datetime = Field(..., description="Creation time")
    updated_at: datetime = Field(..., description="Last update time")
    resolved_at: Optional[datetime] = Field(None, description="Resolution time")


class TicketCommentResponse(BaseModel):
    """Ticket comment information."""

    id: int = Field(..., description="Comment ID")
    ticket_id: str = Field(..., description="Parent ticket UUID")
    comment_type: str = Field(..., description="Comment type")
    content: str = Field(..., description="Comment content")
    source: str = Field(..., description="Comment source")
    created_by: str = Field(..., description="Creator UUID")
    created_at: datetime = Field(..., description="Creation time")


# =============================================================================
# Broadcast Template Schemas
# =============================================================================


class CreateBroadcastTemplateRequest(BaseModel):
    """Request to create a broadcast template."""

    template_key: str = Field(
        ...,
        description="Unique template key",
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9_]+$",
    )
    audience: BroadcastAudience = Field(..., description="Target audience")
    body_template: str = Field(
        ...,
        description="Template body with {{variable}} placeholders",
        min_length=1,
        max_length=4096,
    )
    expected_params: List[str] = Field(
        default_factory=list,
        description="Expected placeholder names",
    )
    wa_template_name: Optional[str] = Field(
        None,
        description="Meta WhatsApp template name (required for DRIVER)",
    )
    wa_template_namespace: Optional[str] = Field(
        None,
        description="Meta WhatsApp template namespace",
    )
    wa_template_language: str = Field(
        default="de",
        description="Template language code",
    )

    @field_validator("expected_params")
    @classmethod
    def validate_params_match_template(cls, v: List[str], info) -> List[str]:
        """Validate that expected params are alphanumeric."""
        for param in v:
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", param):
                raise ValueError(f"Invalid parameter name: {param}")
        return v


class UpdateBroadcastTemplateRequest(BaseModel):
    """Request to update a broadcast template."""

    body_template: Optional[str] = Field(
        None,
        description="Updated template body",
        max_length=4096,
    )
    expected_params: Optional[List[str]] = Field(
        None,
        description="Updated expected parameters",
    )
    is_active: Optional[bool] = Field(
        None,
        description="Active status",
    )
    is_deprecated: Optional[bool] = Field(
        None,
        description="Deprecation status",
    )


class BroadcastTemplateResponse(BaseModel):
    """Broadcast template information."""

    id: str = Field(..., description="Template UUID")
    tenant_id: Optional[int] = Field(None, description="Tenant ID (null for system)")
    template_key: str = Field(..., description="Template key")
    audience: BroadcastAudience = Field(..., description="Target audience")
    body_template: str = Field(..., description="Template body")
    expected_params: List[str] = Field(..., description="Expected parameters")
    wa_template_name: Optional[str] = Field(None, description="WhatsApp template name")
    is_approved: bool = Field(..., description="Approval status")
    approval_status: Optional[str] = Field(None, description="Approval workflow status")
    is_active: bool = Field(..., description="Active status")
    is_deprecated: bool = Field(..., description="Deprecation status")
    created_at: datetime = Field(..., description="Creation time")
    updated_at: datetime = Field(..., description="Last update time")


# =============================================================================
# Subscription Schemas
# =============================================================================


class SubscriptionResponse(BaseModel):
    """Broadcast subscription information."""

    id: str = Field(..., description="Subscription UUID")
    tenant_id: int = Field(..., description="Tenant ID")
    driver_id: str = Field(..., description="Driver ID")
    wa_user_id: Optional[str] = Field(None, description="WhatsApp user ID")
    is_subscribed: bool = Field(..., description="Subscription status")
    consent_given_at: datetime = Field(..., description="Consent timestamp")
    consent_source: str = Field(..., description="Consent source")
    unsubscribed_at: Optional[datetime] = Field(None, description="Unsubscribe time")


# =============================================================================
# Common Schemas
# =============================================================================


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: List[Any] = Field(..., description="List of items")
    total: int = Field(..., description="Total item count")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    has_more: bool = Field(..., description="Whether more pages exist")


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")
    trace_id: Optional[str] = Field(None, description="Request trace ID")
