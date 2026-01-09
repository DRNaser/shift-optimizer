"""
SOLVEREIGN V4.2 - Driver Portal Package
========================================

Provides magic link authentication, driver acknowledgment,
and notification integration for published plan snapshots.

Components:
    - models: Data models for tokens, receipts, acks
    - token_service: JWT generation and validation
    - repository: Database operations
    - renderer: Driver view rendering from snapshots
    - link_service: Portal-Notify integration (V4.2)
"""

from .models import (
    TokenScope,
    TokenStatus,
    AckStatus,
    AckReasonCode,
    AckSource,
    PortalToken,
    ReadReceipt,
    DriverAck,
    DriverView,
    SnapshotSupersede,
    PortalStatus,
    TokenValidationResult,
    RateLimitResult,
    DeliveryChannel,
)

from .link_service import (
    DriverLinkRequest,
    DriverLinkResult,
    BulkLinkResult,
    NotifyLinkRequest,
    NotifyLinkResult,
    PortalLinkService,
    create_link_service,
    create_link_service_with_pool,
)

__all__ = [
    # Models
    "TokenScope",
    "TokenStatus",
    "AckStatus",
    "AckReasonCode",
    "AckSource",
    "PortalToken",
    "ReadReceipt",
    "DriverAck",
    "DriverView",
    "SnapshotSupersede",
    "PortalStatus",
    "TokenValidationResult",
    "RateLimitResult",
    "DeliveryChannel",
    # Link Service (V4.2)
    "DriverLinkRequest",
    "DriverLinkResult",
    "BulkLinkResult",
    "NotifyLinkRequest",
    "NotifyLinkResult",
    "PortalLinkService",
    "create_link_service",
    "create_link_service_with_pool",
]
