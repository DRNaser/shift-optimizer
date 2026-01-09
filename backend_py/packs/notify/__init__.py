"""
SOLVEREIGN V4.1 - Notification Pack
====================================

Transactional outbox pattern for reliable driver notifications.

COMPONENTS:
    - models: Data classes for jobs, outbox, templates
    - providers: WhatsApp, Email, SMS provider adapters
    - worker: Outbox processor for async delivery
    - repository: DB operations for notification data

USAGE:
    from backend_py.packs.notify import NotificationService

    service = NotificationService(repository, providers)
    job_id = await service.create_notification_job(
        tenant_id=1,
        reference_type="SNAPSHOT",
        reference_id=snapshot_id,
        driver_ids=["D001", "D002"],
        portal_urls={"D001": "https://...", "D002": "https://..."},
        channel=DeliveryChannel.WHATSAPP,
    )
"""

from .models import (
    DeliveryChannel,
    NotificationJobType,
    JobStatus,
    OutboxStatus,
    NotificationJob,
    NotificationOutbox,
    DeliveryLog,
    NotificationTemplate,
    DriverPreferences,
)

__all__ = [
    "DeliveryChannel",
    "NotificationJobType",
    "JobStatus",
    "OutboxStatus",
    "NotificationJob",
    "NotificationOutbox",
    "DeliveryLog",
    "NotificationTemplate",
    "DriverPreferences",
]
