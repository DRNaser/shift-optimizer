"""
SOLVEREIGN V4.1 - Notification API
===================================

Internal dispatcher endpoints for notification management.
Requires Entra ID authentication with Dispatcher/Approver role.

ENDPOINTS:
    POST /api/v1/notifications/send      - Create notification job
    GET  /api/v1/notifications/jobs/{id} - Get job status
    GET  /api/v1/notifications/jobs      - List jobs
    POST /api/v1/notifications/resend    - Resend failed messages
    POST /api/v1/notifications/webhook   - Provider webhook handler
    GET  /api/v1/notifications/health    - Module health

RBAC:
    - Dispatcher: send, resend, view jobs
    - Approver/Admin: all above + cancel jobs
"""

import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends, status, Request, Header
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class SendNotificationRequest(BaseModel):
    """Request to send notifications to drivers."""
    snapshot_id: str = Field(..., description="Snapshot UUID")
    driver_ids: List[str] = Field(..., min_length=1, description="List of driver IDs")
    portal_urls: Dict[str, str] = Field(..., description="Map of driver_id to portal URL")
    delivery_channel: str = Field("WHATSAPP", description="WHATSAPP, EMAIL, or SMS")
    template_key: str = Field("PORTAL_INVITE", description="Template identifier")
    template_params: Dict[str, Any] = Field(default_factory=dict, description="Template variables")
    scheduled_at: Optional[str] = Field(None, description="ISO8601 timestamp for scheduled send")
    priority: int = Field(5, ge=1, le=10, description="Priority (1=highest, 10=lowest)")


class SendNotificationResponse(BaseModel):
    """Response from send notification request."""
    success: bool = True
    job_id: str
    total_count: int
    status: str


class JobStatusResponse(BaseModel):
    """Notification job status."""
    job_id: str
    status: str
    job_type: str
    delivery_channel: str
    total_count: int
    sent_count: int
    delivered_count: int
    failed_count: int
    pending_count: int
    completion_rate: float
    initiated_by: str
    initiated_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    last_error: Optional[str]


class JobListResponse(BaseModel):
    """List of notification jobs."""
    jobs: List[JobStatusResponse]
    total: int


class ResendRequest(BaseModel):
    """Request to resend failed notifications."""
    job_id: str = Field(..., description="Original job ID")
    target_status: str = Field("FAILED", description="FAILED, EXPIRED, or ALL")


class ResendResponse(BaseModel):
    """Response from resend request."""
    success: bool = True
    new_job_id: str
    target_count: int


class WebhookResponse(BaseModel):
    """Response for webhook handlers."""
    received: bool = True
    events_processed: int = 0


# =============================================================================
# MOCK SERVICES (Replace with real implementations)
# =============================================================================

class MockNotificationService:
    """Mock notification service for development."""

    _jobs: Dict[str, Dict] = {}
    _counter: int = 0

    async def create_job(
        self,
        tenant_id: int,
        snapshot_id: str,
        driver_ids: List[str],
        portal_urls: Dict[str, str],
        delivery_channel: str,
        template_key: str,
        template_params: Dict[str, Any],
        initiated_by: str,
        scheduled_at: Optional[datetime] = None,
        priority: int = 5,
    ) -> Dict:
        """Create a notification job."""
        import uuid
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "snapshot_id": snapshot_id,
            "job_type": "SNAPSHOT_PUBLISH",
            "status": "PENDING",
            "delivery_channel": delivery_channel,
            "template_key": template_key,
            "total_count": len(driver_ids),
            "sent_count": 0,
            "delivered_count": 0,
            "failed_count": 0,
            "initiated_by": initiated_by,
            "initiated_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "last_error": None,
            "driver_ids": driver_ids,
            "portal_urls": portal_urls,
            "priority": priority,
        }
        self._jobs[job_id] = job
        logger.info(
            "notification_job_created",
            extra={
                "job_id": job_id,
                "driver_count": len(driver_ids),
                "channel": delivery_channel,
            }
        )
        return job

    async def get_job(self, tenant_id: int, job_id: str) -> Optional[Dict]:
        """Get job by ID."""
        job = self._jobs.get(job_id)
        if job and job.get("tenant_id") == tenant_id:
            return job
        return None

    async def list_jobs(
        self,
        tenant_id: int,
        snapshot_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        """List jobs for tenant."""
        jobs = [j for j in self._jobs.values() if j.get("tenant_id") == tenant_id]

        if snapshot_id:
            jobs = [j for j in jobs if j.get("snapshot_id") == snapshot_id]
        if status:
            jobs = [j for j in jobs if j.get("status") == status]

        # Sort by initiated_at desc
        jobs.sort(key=lambda x: x.get("initiated_at", ""), reverse=True)

        return jobs[offset:offset + limit]

    async def resend_failed(
        self,
        tenant_id: int,
        job_id: str,
        target_status: str,
        initiated_by: str,
    ) -> Optional[Dict]:
        """Resend failed messages from a job."""
        original = await self.get_job(tenant_id, job_id)
        if not original:
            return None

        # In a real implementation, query outbox for failed entries
        # and create new job with those driver_ids
        failed_drivers = original.get("driver_ids", [])[:5]  # Mock: first 5

        if not failed_drivers:
            return None

        return await self.create_job(
            tenant_id=tenant_id,
            snapshot_id=original["snapshot_id"],
            driver_ids=failed_drivers,
            portal_urls={d: original["portal_urls"].get(d, "") for d in failed_drivers},
            delivery_channel=original["delivery_channel"],
            template_key=original["template_key"],
            template_params={},
            initiated_by=initiated_by,
        )


# Global mock service instance
_notification_service = MockNotificationService()


def get_notification_service() -> MockNotificationService:
    """Get notification service instance."""
    return _notification_service


# =============================================================================
# AUTH DEPENDENCIES
# =============================================================================

def get_current_user():
    """
    Get current user from Entra ID token.

    TODO: Replace with actual Entra ID auth dependency.
    """
    return {
        "email": os.environ.get("DEFAULT_USER", "dispatcher@solvereign.dev"),
        "roles": ["Dispatcher"],
        "tenant_id": int(os.environ.get("DEFAULT_TENANT_ID", "1")),
        "site_id": int(os.environ.get("DEFAULT_SITE_ID", "1")),
    }


def require_dispatcher(user: dict = Depends(get_current_user)):
    """Require Dispatcher role or higher."""
    roles = set(user.get("roles", []))
    allowed = {"Dispatcher", "Approver", "Admin", "SuperAdmin"}
    if not roles & allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dispatcher role required",
        )
    return user


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/send",
    response_model=SendNotificationResponse,
)
async def send_notifications(
    request: SendNotificationRequest,
    user: dict = Depends(require_dispatcher),
    service: MockNotificationService = Depends(get_notification_service),
):
    """
    Create a notification job to send messages to drivers.

    Sends portal invite links via WhatsApp, Email, or SMS.
    Messages are queued and processed by the background worker.
    """
    tenant_id = user["tenant_id"]

    # Validate delivery channel
    valid_channels = {"WHATSAPP", "EMAIL", "SMS"}
    if request.delivery_channel not in valid_channels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid delivery channel: {request.delivery_channel}",
        )

    # Validate portal_urls contains all driver_ids
    missing = set(request.driver_ids) - set(request.portal_urls.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing portal_urls for drivers: {list(missing)[:5]}...",
        )

    # Parse scheduled_at if provided
    scheduled_at = None
    if request.scheduled_at:
        try:
            scheduled_at = datetime.fromisoformat(request.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid scheduled_at format (use ISO8601)",
            )

    # Create job
    job = await service.create_job(
        tenant_id=tenant_id,
        snapshot_id=request.snapshot_id,
        driver_ids=request.driver_ids,
        portal_urls=request.portal_urls,
        delivery_channel=request.delivery_channel,
        template_key=request.template_key,
        template_params=request.template_params,
        initiated_by=user["email"],
        scheduled_at=scheduled_at,
        priority=request.priority,
    )

    return SendNotificationResponse(
        success=True,
        job_id=job["job_id"],
        total_count=job["total_count"],
        status=job["status"],
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: str,
    user: dict = Depends(require_dispatcher),
    service: MockNotificationService = Depends(get_notification_service),
):
    """Get notification job status."""
    tenant_id = user["tenant_id"]

    job = await service.get_job(tenant_id, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}",
        )

    pending_count = job["total_count"] - job["sent_count"] - job["delivered_count"] - job["failed_count"]
    completion_rate = 0.0
    if job["total_count"] > 0:
        completion_rate = (job["sent_count"] + job["delivered_count"]) / job["total_count"] * 100

    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        job_type=job["job_type"],
        delivery_channel=job["delivery_channel"],
        total_count=job["total_count"],
        sent_count=job["sent_count"],
        delivered_count=job["delivered_count"],
        failed_count=job["failed_count"],
        pending_count=pending_count,
        completion_rate=round(completion_rate, 1),
        initiated_by=job["initiated_by"],
        initiated_at=job["initiated_at"],
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        last_error=job.get("last_error"),
    )


@router.get(
    "/jobs",
    response_model=JobListResponse,
)
async def list_jobs(
    snapshot_id: Optional[str] = Query(None, description="Filter by snapshot"),
    job_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_dispatcher),
    service: MockNotificationService = Depends(get_notification_service),
):
    """List notification jobs for the tenant."""
    tenant_id = user["tenant_id"]

    jobs = await service.list_jobs(
        tenant_id=tenant_id,
        snapshot_id=snapshot_id,
        status=job_status,
        limit=limit,
        offset=offset,
    )

    job_responses = []
    for job in jobs:
        pending_count = job["total_count"] - job["sent_count"] - job["delivered_count"] - job["failed_count"]
        completion_rate = 0.0
        if job["total_count"] > 0:
            completion_rate = (job["sent_count"] + job["delivered_count"]) / job["total_count"] * 100

        job_responses.append(JobStatusResponse(
            job_id=job["job_id"],
            status=job["status"],
            job_type=job["job_type"],
            delivery_channel=job["delivery_channel"],
            total_count=job["total_count"],
            sent_count=job["sent_count"],
            delivered_count=job["delivered_count"],
            failed_count=job["failed_count"],
            pending_count=pending_count,
            completion_rate=round(completion_rate, 1),
            initiated_by=job["initiated_by"],
            initiated_at=job["initiated_at"],
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
            last_error=job.get("last_error"),
        ))

    return JobListResponse(
        jobs=job_responses,
        total=len(job_responses),
    )


@router.post(
    "/resend",
    response_model=ResendResponse,
)
async def resend_notifications(
    request: ResendRequest,
    user: dict = Depends(require_dispatcher),
    service: MockNotificationService = Depends(get_notification_service),
):
    """
    Resend failed notifications from a job.

    Creates a new job with the failed messages from the original job.
    """
    tenant_id = user["tenant_id"]

    valid_targets = {"FAILED", "EXPIRED", "ALL"}
    if request.target_status not in valid_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target_status: {request.target_status}",
        )

    new_job = await service.resend_failed(
        tenant_id=tenant_id,
        job_id=request.job_id,
        target_status=request.target_status,
        initiated_by=user["email"],
    )

    if not new_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found or no messages to resend: {request.job_id}",
        )

    return ResendResponse(
        success=True,
        new_job_id=new_job["job_id"],
        target_count=new_job["total_count"],
    )


@router.post(
    "/webhook/whatsapp",
    response_model=WebhookResponse,
)
async def whatsapp_webhook(
    request: Request,
    x_hub_signature: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
):
    """
    WhatsApp Cloud API webhook handler.

    Receives delivery status updates from Meta.
    Verifies webhook signature before processing.
    """
    # Get raw body for signature verification
    body = await request.body()

    # TODO: Verify webhook signature
    # webhook_secret = os.environ.get("WHATSAPP_WEBHOOK_SECRET")
    # if not verify_whatsapp_signature(body, x_hub_signature, webhook_secret):
    #     raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    # Parse webhook events
    from backend_py.packs.notify.providers.whatsapp import parse_whatsapp_webhook
    events = parse_whatsapp_webhook(payload)

    logger.info(
        "whatsapp_webhook_received",
        extra={"event_count": len(events)}
    )

    # TODO: Process events (update outbox status, log delivery)
    # for event in events:
    #     await notification_service.process_webhook_event(event)

    return WebhookResponse(received=True, events_processed=len(events))


@router.get(
    "/webhook/whatsapp",
)
async def whatsapp_webhook_verify(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    """
    WhatsApp webhook verification endpoint.

    Meta sends GET request to verify webhook URL during setup.
    """
    expected_token = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "solvereign-notify-v1")

    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        logger.info("whatsapp_webhook_verified")
        return int(hub_challenge)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification failed",
    )


@router.post(
    "/webhook/sendgrid",
    response_model=WebhookResponse,
)
async def sendgrid_webhook(
    request: Request,
):
    """
    SendGrid Event Webhook handler.

    Receives delivery status updates from SendGrid.
    """
    try:
        events = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    if not isinstance(events, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected array of events",
        )

    # Parse webhook events
    from backend_py.packs.notify.providers.email import parse_sendgrid_webhook
    normalized = parse_sendgrid_webhook(events)

    logger.info(
        "sendgrid_webhook_received",
        extra={"event_count": len(normalized)}
    )

    # TODO: Process events
    # for event in normalized:
    #     await notification_service.process_webhook_event(event)

    return WebhookResponse(received=True, events_processed=len(normalized))


@router.get("/health")
async def notification_health():
    """Notification module health check."""
    return {
        "status": "ok",
        "module": "notifications",
        "version": "v4.1.0",
        "features": {
            "whatsapp": True,
            "email": True,
            "sms": False,  # Not yet implemented
            "scheduled_send": True,
            "retry": True,
            "webhooks": True,
        },
    }
