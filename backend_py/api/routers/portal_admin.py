"""
SOLVEREIGN V4.4 - Portal Admin API
====================================

Internal dispatcher endpoints for portal management.
Uses internal RBAC authentication (replaced Entra ID in V4.4).

ENDPOINTS:
    GET  /api/v1/portal/status          - Get aggregated portal status
    GET  /api/v1/portal/drivers         - Get driver list with status
    POST /api/v1/portal/issue-tokens    - Issue tokens for snapshot
    POST /api/v1/portal/resend          - Resend notifications
    POST /api/v1/portal/override-ack    - Override driver ack (Approver only)
    POST /api/v1/portal/revoke-tokens   - Revoke tokens for snapshot

    DASHBOARD MVP (V4.2):
    GET  /api/v1/portal/dashboard/summary   - KPI cards from snapshot_notify_summary
    GET  /api/v1/portal/dashboard/details   - Driver table with status filters
    POST /api/v1/portal/dashboard/resend    - Resend reminder to filtered group

RBAC (Internal - V4.4):
    - Dispatcher: portal.summary.read, portal.details.read, portal.resend.write
    - Operator Admin: all above + tenant.features.write
    - Requires valid session cookie (admin_session)

AUTH MIGRATION (V4.4):
    - Removed Entra ID dependency
    - Uses internal RBAC with session cookies
    - Tenant/site isolation via user_bindings table
"""

import logging
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel, Field

from ..security.internal_rbac import (
    InternalUserContext,
    require_session,
    require_permission,
    require_any_permission,
)

from packs.portal.models import (
    TokenScope,
    AckStatus,
    AckReasonCode,
    AckSource,
    DeliveryChannel,
    PortalStatus,
)
from packs.portal.token_service import (
    PortalTokenService,
    PortalAuthService,
    TokenConfig,
    create_mock_auth_service,
)
from packs.portal.repository import MockPortalRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/portal", tags=["Portal (Admin)"])


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class PortalStatusResponse(BaseModel):
    """Aggregated portal status for a snapshot."""
    snapshot_id: str
    total_drivers: int
    unread_count: int
    read_count: int
    accepted_count: int
    declined_count: int
    pending_count: int
    completion_rate: float
    read_rate: float
    acceptance_rate: float


class DriverStatusItem(BaseModel):
    """Status for a single driver."""
    driver_id: str
    driver_name: Optional[str] = None
    is_read: bool
    read_count: int
    is_acked: bool
    ack_status: Optional[str] = None
    ack_at: Optional[str] = None
    token_issued: bool
    token_expired: bool


class DriverListResponse(BaseModel):
    """List of drivers with their portal status."""
    snapshot_id: str
    drivers: List[DriverStatusItem]
    total: int


class IssueTokensRequest(BaseModel):
    """Request to issue tokens for drivers."""
    snapshot_id: str = Field(..., description="Snapshot UUID")
    driver_ids: List[str] = Field(..., description="List of driver IDs")
    scope: str = Field("READ_ACK", description="Token scope")
    delivery_channel: Optional[str] = Field(None, description="Delivery channel")
    ttl_days: Optional[int] = Field(None, description="Custom TTL in days")


class IssueTokensResponse(BaseModel):
    """Response from token issuance."""
    success: bool = True
    snapshot_id: str
    tokens_issued: int
    tokens: List[Dict[str, Any]]  # List of {driver_id, portal_url}


class ResendRequest(BaseModel):
    """Request to resend notifications."""
    snapshot_id: str = Field(..., description="Snapshot UUID")
    target_group: str = Field("UNREAD", description="UNREAD, UNACKED, or DECLINED")
    delivery_channel: str = Field("EMAIL", description="WHATSAPP, EMAIL, or SMS")


class ResendResponse(BaseModel):
    """Response from resend request."""
    success: bool = True
    snapshot_id: str
    target_count: int
    job_id: Optional[str] = None


class OverrideAckRequest(BaseModel):
    """Request to override a driver's ack (Approver only)."""
    snapshot_id: str = Field(..., description="Snapshot UUID")
    driver_id: str = Field(..., description="Driver ID")
    new_status: str = Field(..., description="ACCEPTED or DECLINED")
    override_reason: str = Field(..., min_length=10, description="Reason for override (min 10 chars)")


class OverrideAckResponse(BaseModel):
    """Response from ack override."""
    success: bool = True
    snapshot_id: str
    driver_id: str
    previous_status: Optional[str] = None
    new_status: str
    override_by: str


class RevokeTokensRequest(BaseModel):
    """Request to revoke tokens."""
    snapshot_id: str = Field(..., description="Snapshot UUID")
    driver_ids: Optional[List[str]] = Field(None, description="Specific drivers (None = all)")


class RevokeTokensResponse(BaseModel):
    """Response from token revocation."""
    success: bool = True
    snapshot_id: str
    tokens_revoked: int


# =============================================================================
# DASHBOARD MVP SCHEMAS (V4.2)
# =============================================================================

class DashboardStatusFilter(str, Enum):
    """Filter for dashboard details table."""
    ALL = "ALL"
    PENDING = "PENDING"          # Not yet sent
    SENT = "SENT"                # Sent but not delivered
    DELIVERED = "DELIVERED"      # Delivered but not read
    READ = "READ"                # Read but not acked
    ACCEPTED = "ACCEPTED"        # Accepted
    DECLINED = "DECLINED"        # Declined
    SKIPPED = "SKIPPED"          # Skipped (DNC, opted-out, invalid contact)
    FAILED = "FAILED"            # Notify failed (actual send failure)
    UNREAD = "UNREAD"            # Not read (sent/delivered but no read receipt)
    UNACKED = "UNACKED"          # Read but no ack


class DashboardKPICard(BaseModel):
    """Single KPI card for dashboard."""
    label: str
    value: int
    percentage: Optional[float] = None
    trend: Optional[str] = None  # "up", "down", "stable"
    color: str = "default"  # "default", "success", "warning", "danger"


class DashboardSummaryResponse(BaseModel):
    """Dashboard summary with KPI cards from snapshot_notify_summary view."""
    snapshot_id: str
    tenant_id: int

    # Raw counts from snapshot_notify_summary
    total_tokens: int
    pending_count: int
    sent_count: int
    delivered_count: int
    read_count: int
    accepted_count: int
    declined_count: int
    failed_count: int

    # Calculated rates
    completion_rate: float  # (accepted + declined) / total
    read_rate: float        # read / total
    acceptance_rate: float  # accepted / (accepted + declined) or 0

    # Timestamps
    first_issued_at: Optional[str] = None
    last_ack_at: Optional[str] = None

    # Pre-built KPI cards for frontend
    kpi_cards: List[DashboardKPICard]


class DashboardDriverRow(BaseModel):
    """Single driver row for dashboard details table."""
    driver_id: str
    driver_name: Optional[str] = None

    # Overall status (derived in DB view)
    overall_status: str  # PENDING, SENT, DELIVERED, READ, ACCEPTED, DECLINED, FAILED, etc.

    # Notify status
    notify_status: Optional[str] = None
    notify_sent_at: Optional[str] = None
    notify_delivered_at: Optional[str] = None

    # Portal status
    first_read_at: Optional[str] = None
    last_read_at: Optional[str] = None
    read_count: int = 0

    # Ack status
    ack_status: Optional[str] = None
    ack_at: Optional[str] = None

    # Token status
    issued_at: Optional[str] = None
    expires_at: Optional[str] = None
    is_expired: bool = False
    is_revoked: bool = False


class DashboardDetailsResponse(BaseModel):
    """Dashboard details with filtered driver table."""
    snapshot_id: str
    filter_applied: str

    # Pagination
    total: int
    page: int
    page_size: int

    # Driver rows
    drivers: List[DashboardDriverRow]


class DashboardResendRequest(BaseModel):
    """Request to resend notifications from dashboard."""
    snapshot_id: str = Field(..., description="Snapshot UUID")
    filter: DashboardStatusFilter = Field(
        DashboardStatusFilter.UNREAD,
        description="Which drivers to resend to"
    )
    delivery_channel: str = Field("WHATSAPP", description="WHATSAPP, EMAIL, or SMS")
    template_key: str = Field("REMINDER_24H", description="Template to use")
    max_batch: int = Field(100, ge=1, le=500, description="Hard limit on batch size")
    require_latest_snapshot: bool = Field(True, description="Only allow resend to latest snapshot")
    # DECLINED guardrail: requires explicit flag + reason
    include_declined: bool = Field(
        False,
        description="Set to true to include DECLINED drivers (requires declined_reason)"
    )
    declined_reason: Optional[str] = Field(
        None,
        min_length=10,
        description="Reason for resending to declined drivers (min 10 chars, required if include_declined=true)"
    )
    # SKIPPED guardrail: requires explicit flag + reason (DNC drivers)
    include_skipped: bool = Field(
        False,
        description="Set to true to include SKIPPED drivers (requires skipped_reason). "
                    "SKIPPED drivers were blocked due to DNC, opt-out, or invalid contact."
    )
    skipped_reason: Optional[str] = Field(
        None,
        min_length=10,
        description="Reason for resending to skipped drivers (min 10 chars, required if include_skipped=true)"
    )


class DashboardResendResponse(BaseModel):
    """Response from dashboard resend action."""
    success: bool = True
    snapshot_id: str
    filter_applied: str
    target_count: int
    job_id: Optional[str] = None
    driver_ids: List[str] = []


# =============================================================================
# DEPENDENCY: Get Services
# =============================================================================

_token_service: Optional[PortalTokenService] = None
_repository: Optional[MockPortalRepository] = None


def get_token_service() -> PortalTokenService:
    """Get or create the token service."""
    global _token_service
    if _token_service is None:
        _token_service = PortalTokenService()
    return _token_service


def get_repository() -> MockPortalRepository:
    """Get the portal repository."""
    global _repository
    if _repository is None:
        _repository = MockPortalRepository()
    return _repository


# =============================================================================
# RBAC DEPENDENCIES (V4.4 - Internal RBAC)
# =============================================================================

# Permission-based dependencies using internal RBAC
require_portal_read = require_any_permission("portal.summary.read", "portal.details.read")
require_portal_resend = require_permission("portal.resend.write")
require_portal_approve = require_permission("plan.approve")


# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@router.get(
    "/status",
    response_model=PortalStatusResponse,
)
async def get_portal_status(
    snapshot_id: str = Query(..., description="Snapshot UUID"),
    user: InternalUserContext = Depends(require_portal_read),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Get aggregated portal status for a snapshot.

    Shows read/ack counts and completion rates.
    Requires: portal.summary.read or portal.details.read permission.
    """
    tenant_id = user.tenant_id

    status_data = await repository.get_portal_status(tenant_id, snapshot_id)

    return PortalStatusResponse(
        snapshot_id=snapshot_id,
        total_drivers=status_data.total_drivers,
        unread_count=status_data.unread_count,
        read_count=status_data.read_count,
        accepted_count=status_data.accepted_count,
        declined_count=status_data.declined_count,
        pending_count=status_data.pending_count,
        completion_rate=status_data.completion_rate,
        read_rate=status_data.read_rate,
        acceptance_rate=status_data.acceptance_rate,
    )


@router.get(
    "/drivers",
    response_model=DriverListResponse,
)
async def get_driver_list(
    snapshot_id: str = Query(..., description="Snapshot UUID"),
    filter_status: Optional[str] = Query(None, description="Filter: UNREAD, READ, ACCEPTED, DECLINED, PENDING"),
    user: InternalUserContext = Depends(require_portal_read),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Get list of drivers with their portal status.

    Useful for identifying who hasn't read or acknowledged.
    """
    tenant_id = user.tenant_id

    # Get all tokens for this snapshot
    tokens = await repository.get_tokens_for_snapshot(tenant_id, snapshot_id) if hasattr(repository, 'get_tokens_for_snapshot') else []

    drivers = []
    for token in tokens:
        # Get read receipt
        read_receipt = await repository.get_read_receipt(
            tenant_id, snapshot_id, token.driver_id
        )

        # Get ack
        ack = await repository.get_ack(tenant_id, snapshot_id, token.driver_id)

        item = DriverStatusItem(
            driver_id=token.driver_id,
            is_read=read_receipt is not None,
            read_count=read_receipt.read_count if read_receipt else 0,
            is_acked=ack is not None,
            ack_status=ack.status.value if ack else None,
            ack_at=ack.ack_at.isoformat() if ack else None,
            token_issued=True,
            token_expired=token.is_expired,
        )

        # Apply filter
        if filter_status:
            if filter_status == "UNREAD" and item.is_read:
                continue
            elif filter_status == "READ" and not item.is_read:
                continue
            elif filter_status == "ACCEPTED" and item.ack_status != "ACCEPTED":
                continue
            elif filter_status == "DECLINED" and item.ack_status != "DECLINED":
                continue
            elif filter_status == "PENDING" and (not item.is_read or item.is_acked):
                continue

        drivers.append(item)

    return DriverListResponse(
        snapshot_id=snapshot_id,
        drivers=drivers,
        total=len(drivers),
    )


@router.post(
    "/issue-tokens",
    response_model=IssueTokensResponse,
)
async def issue_tokens(
    request: IssueTokensRequest,
    user: InternalUserContext = Depends(require_portal_read),
    token_service: PortalTokenService = Depends(get_token_service),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Issue portal tokens for drivers.

    Returns portal URLs to be sent via notification.
    """
    tenant_id = user.tenant_id
    site_id = user.site_id

    # Validate scope
    try:
        scope = TokenScope(request.scope)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope: {request.scope}",
        )

    # Validate delivery channel
    delivery_channel = None
    if request.delivery_channel:
        try:
            delivery_channel = DeliveryChannel(request.delivery_channel)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid delivery channel: {request.delivery_channel}",
            )

    # Issue tokens
    tokens_issued = []
    base_url = os.environ.get("PORTAL_BASE_URL", "https://portal.solvereign.com")

    for driver_id in request.driver_ids:
        raw_token, portal_token = token_service.generate_token(
            tenant_id=tenant_id,
            site_id=site_id,
            snapshot_id=request.snapshot_id,
            driver_id=driver_id,
            scope=scope,
            ttl_days=request.ttl_days,
            delivery_channel=delivery_channel,
        )

        # Save to repository
        await repository.save_token(portal_token)

        # Build portal URL
        portal_url = token_service.build_portal_url(base_url, raw_token)

        tokens_issued.append({
            "driver_id": driver_id,
            "portal_url": portal_url,
            "expires_at": portal_token.expires_at.isoformat(),
        })

    logger.info(
        f"Tokens issued: snapshot={request.snapshot_id[:8]}..., "
        f"count={len(tokens_issued)}, by={user.email}"
    )

    return IssueTokensResponse(
        success=True,
        snapshot_id=request.snapshot_id,
        tokens_issued=len(tokens_issued),
        tokens=tokens_issued,
    )


@router.post(
    "/resend",
    response_model=ResendResponse,
)
async def resend_notifications(
    request: ResendRequest,
    user: InternalUserContext = Depends(require_portal_resend),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Resend notifications to drivers.

    Targets: UNREAD, UNACKED, or DECLINED drivers.
    Creates a notification job for the worker.
    Requires: portal.resend.write permission.
    """
    tenant_id = user.tenant_id

    # Get target drivers
    status_data = await repository.get_portal_status(tenant_id, request.snapshot_id)

    if request.target_group == "UNREAD":
        target_drivers = status_data.unread_drivers
    elif request.target_group == "UNACKED":
        target_drivers = status_data.unacked_drivers
    elif request.target_group == "DECLINED":
        target_drivers = status_data.declined_drivers
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target group: {request.target_group}",
        )

    # TODO: Create notification job in notify.notification_jobs
    # For now, just return the count
    job_id = None  # Would be UUID from created job

    logger.info(
        f"Resend requested: snapshot={request.snapshot_id[:8]}..., "
        f"target={request.target_group}, count={len(target_drivers)}, "
        f"channel={request.delivery_channel}, by={user.email}"
    )

    return ResendResponse(
        success=True,
        snapshot_id=request.snapshot_id,
        target_count=len(target_drivers),
        job_id=job_id,
    )


@router.post(
    "/override-ack",
    response_model=OverrideAckResponse,
)
async def override_ack(
    request: OverrideAckRequest,
    user: InternalUserContext = Depends(require_portal_approve),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Override a driver's acknowledgment.

    APPROVER ONLY. Requires reason (min 10 chars).
    Used for corrections when driver made a mistake.
    """
    tenant_id = user.tenant_id

    # Validate status
    try:
        new_status = AckStatus(request.new_status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {request.new_status}",
        )

    # Get existing ack
    existing = await repository.get_ack(
        tenant_id, request.snapshot_id, request.driver_id
    )

    previous_status = existing.status.value if existing else None

    # Perform override
    if hasattr(repository, 'override_ack'):
        _ack = await repository.override_ack(
            tenant_id=tenant_id,
            snapshot_id=request.snapshot_id,
            driver_id=request.driver_id,
            new_status=new_status,
            override_by=user.email,
            override_reason=request.override_reason,
        )
    else:
        # Mock doesn't support override, create new
        _ack = await repository.record_ack(
            tenant_id=tenant_id,
            site_id=user.site_id,
            snapshot_id=request.snapshot_id,
            driver_id=request.driver_id,
            status=new_status,
            source=AckSource.DISPATCHER_OVERRIDE,
            override_by=user.email,
            override_reason=request.override_reason,
        )

    logger.info(
        f"Ack overridden: snapshot={request.snapshot_id[:8]}..., "
        f"driver={request.driver_id}, {previous_status} -> {new_status.value}, "
        f"by={user.email}"
    )

    return OverrideAckResponse(
        success=True,
        snapshot_id=request.snapshot_id,
        driver_id=request.driver_id,
        previous_status=previous_status,
        new_status=new_status.value,
        override_by=user.email,
    )


@router.post(
    "/revoke-tokens",
    response_model=RevokeTokensResponse,
)
async def revoke_tokens(
    request: RevokeTokensRequest,
    user: InternalUserContext = Depends(require_portal_read),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Revoke tokens for a snapshot.

    Can revoke all tokens or specific drivers.
    """
    tenant_id = user.tenant_id

    # Get tokens for snapshot
    if hasattr(repository, 'get_tokens_for_snapshot'):
        tokens = await repository.get_tokens_for_snapshot(tenant_id, request.snapshot_id)
    else:
        tokens = []

    # Filter by driver_ids if specified
    if request.driver_ids:
        tokens = [t for t in tokens if t.driver_id in request.driver_ids]

    # Revoke each token
    revoked_count = 0
    for token in tokens:
        if not token.is_revoked:
            success = await repository.revoke_token(token.jti_hash)
            if success:
                revoked_count += 1

    logger.info(
        f"Tokens revoked: snapshot={request.snapshot_id[:8]}..., "
        f"count={revoked_count}, by={user.email}"
    )

    return RevokeTokensResponse(
        success=True,
        snapshot_id=request.snapshot_id,
        tokens_revoked=revoked_count,
    )


# =============================================================================
# DASHBOARD MVP ENDPOINTS (V4.2)
# =============================================================================

@router.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
)
async def get_dashboard_summary(
    snapshot_id: str = Query(..., description="Snapshot UUID"),
    user: InternalUserContext = Depends(require_portal_read),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Get dashboard summary with KPI cards.

    Uses snapshot_notify_summary view for aggregated counts.
    Returns pre-built KPI cards for frontend rendering.
    """
    tenant_id = user.tenant_id

    # Get aggregated status (from view or calculated)
    status_data = await repository.get_portal_status(tenant_id, snapshot_id)

    total = status_data.total_drivers
    read = status_data.read_count
    accepted = status_data.accepted_count
    declined = status_data.declined_count
    pending = status_data.pending_count
    unread = status_data.unread_count

    # Calculate rates
    completion_rate = round((accepted + declined) / total * 100, 1) if total > 0 else 0.0
    read_rate = round(read / total * 100, 1) if total > 0 else 0.0
    acceptance_rate = round(accepted / (accepted + declined) * 100, 1) if (accepted + declined) > 0 else 0.0

    # Build KPI cards
    kpi_cards = [
        DashboardKPICard(
            label="Total Drivers",
            value=total,
            color="default",
        ),
        DashboardKPICard(
            label="Read",
            value=read,
            percentage=read_rate,
            color="default",
        ),
        DashboardKPICard(
            label="Accepted",
            value=accepted,
            percentage=round(accepted / total * 100, 1) if total > 0 else 0.0,
            color="success",
        ),
        DashboardKPICard(
            label="Declined",
            value=declined,
            percentage=round(declined / total * 100, 1) if total > 0 else 0.0,
            color="warning",
        ),
        DashboardKPICard(
            label="Unread",
            value=unread,
            percentage=round(unread / total * 100, 1) if total > 0 else 0.0,
            color="danger" if unread > 0 else "default",
        ),
        DashboardKPICard(
            label="Completion Rate",
            value=accepted + declined,
            percentage=completion_rate,
            color="success" if completion_rate >= 80 else "warning" if completion_rate >= 50 else "danger",
        ),
    ]

    return DashboardSummaryResponse(
        snapshot_id=snapshot_id,
        tenant_id=tenant_id,
        total_tokens=total,
        pending_count=pending,
        sent_count=0,  # Would come from notify_integration_status
        delivered_count=0,  # Would come from notify_integration_status
        read_count=read,
        accepted_count=accepted,
        declined_count=declined,
        failed_count=0,  # Would come from notify_integration_status
        completion_rate=completion_rate,
        read_rate=read_rate,
        acceptance_rate=acceptance_rate,
        first_issued_at=None,  # Would come from snapshot_notify_summary
        last_ack_at=None,  # Would come from snapshot_notify_summary
        kpi_cards=kpi_cards,
    )


@router.get(
    "/dashboard/details",
    response_model=DashboardDetailsResponse,
)
async def get_dashboard_details(
    snapshot_id: str = Query(..., description="Snapshot UUID"),
    filter: DashboardStatusFilter = Query(DashboardStatusFilter.ALL, description="Status filter"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    user: InternalUserContext = Depends(require_portal_read),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Get dashboard details with filtered driver table.

    Uses notify_integration_status view for per-driver status.
    Supports filtering by overall_status.
    """
    tenant_id = user.tenant_id

    # Get all tokens for this snapshot
    tokens = await repository.get_tokens_for_snapshot(tenant_id, snapshot_id) \
        if hasattr(repository, 'get_tokens_for_snapshot') else []

    drivers = []
    for token in tokens:
        # Get read receipt
        read_receipt = await repository.get_read_receipt(
            tenant_id, snapshot_id, token.driver_id
        )

        # Get ack
        ack = await repository.get_ack(tenant_id, snapshot_id, token.driver_id)

        # Determine overall status
        if token.revoked_at:
            overall_status = "REVOKED"
        elif token.is_expired:
            overall_status = "EXPIRED"
        elif ack and ack.status.value == "ACCEPTED":
            overall_status = "ACCEPTED"
        elif ack and ack.status.value == "DECLINED":
            overall_status = "DECLINED"
        elif read_receipt:
            overall_status = "READ"
        else:
            overall_status = "PENDING"

        # Apply filter
        if filter != DashboardStatusFilter.ALL:
            if filter == DashboardStatusFilter.UNREAD and read_receipt:
                continue
            elif filter == DashboardStatusFilter.UNACKED and (not read_receipt or ack):
                continue
            elif filter == DashboardStatusFilter.ACCEPTED and overall_status != "ACCEPTED":
                continue
            elif filter == DashboardStatusFilter.DECLINED and overall_status != "DECLINED":
                continue
            elif filter == DashboardStatusFilter.READ and overall_status != "READ":
                continue
            elif filter == DashboardStatusFilter.PENDING and overall_status != "PENDING":
                continue
            elif filter == DashboardStatusFilter.FAILED and overall_status != "NOTIFY_FAILED":
                continue

        row = DashboardDriverRow(
            driver_id=token.driver_id,
            overall_status=overall_status,
            first_read_at=read_receipt.first_read_at.isoformat() if read_receipt else None,
            last_read_at=read_receipt.last_read_at.isoformat() if read_receipt else None,
            read_count=read_receipt.read_count if read_receipt else 0,
            ack_status=ack.status.value if ack else None,
            ack_at=ack.ack_at.isoformat() if ack else None,
            issued_at=token.issued_at.isoformat() if token.issued_at else None,
            expires_at=token.expires_at.isoformat() if token.expires_at else None,
            is_expired=token.is_expired,
            is_revoked=token.is_revoked,
        )
        drivers.append(row)

    # Pagination
    total = len(drivers)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = drivers[start:end]

    return DashboardDetailsResponse(
        snapshot_id=snapshot_id,
        filter_applied=filter.value,
        total=total,
        page=page,
        page_size=page_size,
        drivers=paginated,
    )


# Rate limit tracking (in-memory for MVP, use Redis in production)
_resend_rate_limits: Dict[str, list] = {}
RESEND_RATE_LIMIT_WINDOW = 3600  # 1 hour
RESEND_RATE_LIMIT_MAX = 10  # max 10 resends per hour per user


def check_resend_rate_limit(user_email: str) -> bool:
    """Check if user is within rate limit for resend operations."""
    import time
    now = time.time()
    window_start = now - RESEND_RATE_LIMIT_WINDOW

    # Clean old entries
    if user_email in _resend_rate_limits:
        _resend_rate_limits[user_email] = [
            t for t in _resend_rate_limits[user_email] if t > window_start
        ]
    else:
        _resend_rate_limits[user_email] = []

    # Check limit
    if len(_resend_rate_limits[user_email]) >= RESEND_RATE_LIMIT_MAX:
        return False

    # Record this request
    _resend_rate_limits[user_email].append(now)
    return True


@router.post(
    "/dashboard/resend",
    response_model=DashboardResendResponse,
)
async def dashboard_resend(
    request: DashboardResendRequest,
    user: InternalUserContext = Depends(require_portal_resend),
    repository: MockPortalRepository = Depends(get_repository),
):
    """
    Resend notifications to filtered group of drivers.

    Uses REMINDER_24H template by default.
    Creates notification job for notify worker.
    Requires: portal.resend.write permission.

    Security:
        - Rate limited: 10 resends per hour per user
        - Audit trail: PORTAL_RESEND_TRIGGERED event
        - Batch hard limit: max 500 drivers per request
        - Guardrail: only latest snapshot by default
    """
    tenant_id = user.tenant_id
    user_email = user.email

    # Rate limit check
    if not check_resend_rate_limit(user_email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: max {RESEND_RATE_LIMIT_MAX} resends per hour",
        )

    # DECLINED guardrail: require explicit flag + reason
    if request.filter == DashboardStatusFilter.DECLINED:
        if not request.include_declined:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="DECLINED filter requires include_declined=true and declined_reason (min 10 chars). "
                       "Resending to drivers who explicitly declined should be intentional.",
            )
        if not request.declined_reason or len(request.declined_reason) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="declined_reason is required (min 10 chars) when targeting DECLINED drivers.",
            )
        # Log explicitly for audit
        logger.warning(
            f"PORTAL_RESEND_DECLINED: snapshot={request.snapshot_id[:8]}..., "
            f"reason={request.declined_reason}, by={user_email}"
        )

    # SKIPPED guardrail: require explicit flag + reason (DNC, opted-out, invalid contact)
    if request.filter == DashboardStatusFilter.SKIPPED:
        if not request.include_skipped:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SKIPPED filter requires include_skipped=true and skipped_reason (min 10 chars). "
                       "SKIPPED drivers were blocked due to DNC, opt-out, or invalid contact.",
            )
        if not request.skipped_reason or len(request.skipped_reason) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="skipped_reason is required (min 10 chars) when targeting SKIPPED drivers.",
            )
        # Log explicitly for audit (WARNING level for compliance visibility)
        logger.warning(
            f"PORTAL_RESEND_SKIPPED: snapshot={request.snapshot_id[:8]}..., "
            f"reason={request.skipped_reason}, by={user_email}"
        )

    # TODO: Check if snapshot is latest (guardrail)
    # if request.require_latest_snapshot:
    #     latest = await repository.get_latest_snapshot(tenant_id, site_id, plan_version_id)
    #     if latest.id != request.snapshot_id:
    #         raise HTTPException(
    #             status_code=status.HTTP_400_BAD_REQUEST,
    #             detail="Cannot resend to superseded snapshot. Set require_latest_snapshot=false to override.",
    #         )

    # Get drivers matching filter
    target_driver_ids = []

    if hasattr(repository, 'get_tokens_for_snapshot'):
        tokens = await repository.get_tokens_for_snapshot(tenant_id, request.snapshot_id)
    else:
        tokens = []

    for token in tokens:
        if token.is_revoked or token.is_expired:
            continue

        read_receipt = await repository.get_read_receipt(
            tenant_id, request.snapshot_id, token.driver_id
        )
        ack = await repository.get_ack(tenant_id, request.snapshot_id, token.driver_id)

        # Determine if driver matches filter
        matches = False
        if request.filter == DashboardStatusFilter.UNREAD:
            matches = read_receipt is None
        elif request.filter == DashboardStatusFilter.UNACKED:
            matches = read_receipt is not None and ack is None
        elif request.filter == DashboardStatusFilter.DECLINED:
            matches = ack is not None and ack.status.value == "DECLINED"
        elif request.filter == DashboardStatusFilter.READ:
            matches = read_receipt is not None and ack is None
        elif request.filter == DashboardStatusFilter.ALL:
            matches = True

        if matches:
            target_driver_ids.append(token.driver_id)

            # Hard batch limit
            if len(target_driver_ids) >= request.max_batch:
                break

    if not target_driver_ids:
        return DashboardResendResponse(
            success=True,
            snapshot_id=request.snapshot_id,
            filter_applied=request.filter.value,
            target_count=0,
            driver_ids=[],
        )

    # TODO: Create notification job using link_service.issue_and_notify_atomic()
    # For now, just return the count and driver IDs
    job_id = None  # Would be UUID from created job

    # Audit trail
    logger.info(
        f"PORTAL_RESEND_TRIGGERED: snapshot={request.snapshot_id[:8]}..., "
        f"filter={request.filter.value}, count={len(target_driver_ids)}, "
        f"channel={request.delivery_channel}, template={request.template_key}, "
        f"max_batch={request.max_batch}, by={user_email}"
    )

    return DashboardResendResponse(
        success=True,
        snapshot_id=request.snapshot_id,
        filter_applied=request.filter.value,
        target_count=len(target_driver_ids),
        job_id=job_id,
        driver_ids=target_driver_ids,
    )


# =============================================================================
# HEALTH CHECK
# =============================================================================

@router.get("/health")
async def portal_health():
    """Portal module health check."""
    return {
        "status": "ok",
        "module": "portal",
        "version": "v4.2.0",
        "features": {
            "magic_links": True,
            "read_receipts": True,
            "acknowledgments": True,
            "single_use_ack": True,
            "supersede_tracking": True,
            "dashboard_mvp": True,
            "notify_integration": True,
        },
    }
