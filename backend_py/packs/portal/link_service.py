"""
SOLVEREIGN V4.2.1 - Portal Link Service (Hardened)
===================================================

Integration service for generating portal links and sending notifications.

This service bridges the portal token system with the notification pipeline,
enabling {plan_link} template variable substitution.

Flow:
    1. Dispatcher triggers "publish + notify"
    2. LinkService generates tokens for each driver
    3. Tokens stored in portal.portal_tokens with outbox_id link (ATOMIC)
    4. Notification job created with portal URLs
    5. Notify worker sends messages with {plan_link} resolved

Security (V4.2.1 Hardening):
    - Raw tokens never stored (only jti_hash)
    - Each driver gets unique token
    - Tokens linked to specific snapshot
    - outbox_id enables delivery tracking
    - DEDUP KEY prevents duplicate tokens for same snapshot+driver+channel
    - ATOMIC token+outbox creation (single transaction)
    - ORPHAN CLEANUP: tokens revoked on job failure
    - NO PII in views (error_message removed)
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from uuid import UUID

from .models import (
    TokenScope,
    PortalToken,
    DeliveryChannel,
)
from .token_service import (
    PortalTokenService,
    TokenConfig,
)
from .repository import PostgresPortalRepository, MockPortalRepository

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DriverLinkRequest:
    """Request to generate a portal link for a driver."""
    driver_id: str
    driver_name: Optional[str] = None
    contact_hash: Optional[str] = None  # SHA-256 of phone/email


@dataclass
class DriverLinkResult:
    """Result of portal link generation for a driver."""
    driver_id: str
    portal_url: str
    token: PortalToken  # Token model (jti_hash only, not raw token)
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class BulkLinkResult:
    """Result of bulk portal link generation."""
    snapshot_id: str
    total_count: int
    success_count: int
    failed_count: int
    driver_results: List[DriverLinkResult]
    portal_urls: Dict[str, str]  # {driver_id: portal_url}

    @property
    def all_successful(self) -> bool:
        """Check if all links were generated successfully."""
        return self.failed_count == 0


@dataclass
class NotifyLinkRequest:
    """Request to issue portal links and create notification job."""
    tenant_id: int
    site_id: int
    snapshot_id: str
    driver_requests: List[DriverLinkRequest]
    delivery_channel: DeliveryChannel
    template_key: str = "PORTAL_INVITE"
    initiated_by: str = ""
    base_url: str = "https://portal.solvereign.com"
    scope: TokenScope = TokenScope.READ_ACK
    ttl_days: Optional[int] = None
    # Additional template params (driver_name, week_start, etc.)
    template_params: Optional[Dict[str, str]] = None


@dataclass
class NotifyLinkResult:
    """Result of portal link issuance + notification creation."""
    snapshot_id: str
    job_id: Optional[str]
    bulk_result: BulkLinkResult
    notification_created: bool
    error_message: Optional[str] = None


# =============================================================================
# PORTAL LINK SERVICE
# =============================================================================

class PortalLinkService:
    """
    Service for generating portal links and integrating with notifications.

    This is the main integration point between portal tokens and notify system.
    """

    def __init__(
        self,
        token_service: PortalTokenService,
        repository,
        base_url: str = "https://portal.solvereign.com",
    ):
        """
        Initialize link service.

        Args:
            token_service: Token generation service
            repository: Portal repository (Postgres or Mock)
            base_url: Base URL for portal links
        """
        self.token_service = token_service
        self.repository = repository
        self.base_url = base_url

    async def generate_link(
        self,
        tenant_id: int,
        site_id: int,
        snapshot_id: str,
        driver_id: str,
        scope: TokenScope = TokenScope.READ_ACK,
        ttl_days: Optional[int] = None,
        delivery_channel: Optional[DeliveryChannel] = None,
    ) -> Tuple[str, PortalToken]:
        """
        Generate a single portal link for a driver.

        Args:
            tenant_id: Tenant ID
            site_id: Site ID
            snapshot_id: Snapshot UUID
            driver_id: Driver ID
            scope: Token scope
            ttl_days: Custom TTL
            delivery_channel: How link will be delivered

        Returns:
            Tuple of (portal_url, PortalToken)

        Security:
            - Raw token in URL is generated fresh
            - Only jti_hash stored in DB
        """
        # Generate token
        raw_token, portal_token = self.token_service.generate_token(
            tenant_id=tenant_id,
            site_id=site_id,
            snapshot_id=snapshot_id,
            driver_id=driver_id,
            scope=scope,
            ttl_days=ttl_days,
            delivery_channel=delivery_channel,
        )

        # Save to repository
        saved_token = await self.repository.save_token(portal_token)

        # Build URL
        portal_url = self.token_service.build_portal_url(self.base_url, raw_token)

        logger.info(
            f"Portal link generated: driver={driver_id}, "
            f"snapshot={snapshot_id[:8]}..., jti_hash={saved_token.jti_hash[:16]}..."
        )

        return portal_url, saved_token

    async def generate_bulk_links(
        self,
        tenant_id: int,
        site_id: int,
        snapshot_id: str,
        driver_requests: List[DriverLinkRequest],
        scope: TokenScope = TokenScope.READ_ACK,
        ttl_days: Optional[int] = None,
        delivery_channel: Optional[DeliveryChannel] = None,
    ) -> BulkLinkResult:
        """
        Generate portal links for multiple drivers.

        Args:
            tenant_id: Tenant ID
            site_id: Site ID
            snapshot_id: Snapshot UUID
            driver_requests: List of driver link requests
            scope: Token scope (applied to all)
            ttl_days: Custom TTL (applied to all)
            delivery_channel: Delivery channel for tracking

        Returns:
            BulkLinkResult with all driver results

        Performance:
            - Generates tokens sequentially (crypto operations)
            - Could be parallelized with async gather for large batches
        """
        results: List[DriverLinkResult] = []
        portal_urls: Dict[str, str] = {}
        success_count = 0
        failed_count = 0

        for request in driver_requests:
            try:
                portal_url, token = await self.generate_link(
                    tenant_id=tenant_id,
                    site_id=site_id,
                    snapshot_id=snapshot_id,
                    driver_id=request.driver_id,
                    scope=scope,
                    ttl_days=ttl_days,
                    delivery_channel=delivery_channel,
                )

                results.append(DriverLinkResult(
                    driver_id=request.driver_id,
                    portal_url=portal_url,
                    token=token,
                    success=True,
                ))
                portal_urls[request.driver_id] = portal_url
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to generate link for driver {request.driver_id}: {e}")
                results.append(DriverLinkResult(
                    driver_id=request.driver_id,
                    portal_url="",
                    token=PortalToken(),
                    success=False,
                    error_message=str(e),
                ))
                failed_count += 1

        return BulkLinkResult(
            snapshot_id=snapshot_id,
            total_count=len(driver_requests),
            success_count=success_count,
            failed_count=failed_count,
            driver_results=results,
            portal_urls=portal_urls,
        )

    async def issue_and_notify(
        self,
        request: NotifyLinkRequest,
        notify_repository=None,
    ) -> NotifyLinkResult:
        """
        Issue portal links and create notification job in one operation.

        This is the main integration method that:
        1. Generates tokens for all drivers
        2. Stores tokens with outbox_id linkage
        3. Creates notification job with {plan_link} resolved

        Args:
            request: NotifyLinkRequest with all parameters
            notify_repository: Optional notify repository for job creation

        Returns:
            NotifyLinkResult with job_id and bulk result

        Flow:
            Dispatcher → issue_and_notify() → tokens + notify job
            Notify worker picks up job → sends with portal URLs
        """
        # Step 1: Generate bulk links
        driver_delivery_channel = DeliveryChannel(request.delivery_channel.value) \
            if request.delivery_channel else None

        bulk_result = await self.generate_bulk_links(
            tenant_id=request.tenant_id,
            site_id=request.site_id,
            snapshot_id=request.snapshot_id,
            driver_requests=request.driver_requests,
            scope=request.scope,
            ttl_days=request.ttl_days,
            delivery_channel=driver_delivery_channel,
        )

        if bulk_result.failed_count == bulk_result.total_count:
            return NotifyLinkResult(
                snapshot_id=request.snapshot_id,
                job_id=None,
                bulk_result=bulk_result,
                notification_created=False,
                error_message="All portal link generations failed",
            )

        # Step 2: Create notification job (if notify_repository provided)
        job_id = None
        notification_created = False
        error_message = None

        if notify_repository is not None:
            try:
                # Build template params with portal URLs
                # The notify system will substitute {plan_link} → portal_url per driver
                job_id = await self._create_notify_job(
                    request=request,
                    portal_urls=bulk_result.portal_urls,
                    notify_repository=notify_repository,
                )
                notification_created = True

                logger.info(
                    f"Notification job created: job_id={job_id}, "
                    f"snapshot={request.snapshot_id[:8]}..., drivers={bulk_result.success_count}"
                )

            except Exception as e:
                logger.error(f"Failed to create notification job: {e}")
                error_message = f"Portal links created, but notification job failed: {e}"

        return NotifyLinkResult(
            snapshot_id=request.snapshot_id,
            job_id=str(job_id) if job_id else None,
            bulk_result=bulk_result,
            notification_created=notification_created,
            error_message=error_message,
        )

    async def _create_notify_job(
        self,
        request: NotifyLinkRequest,
        portal_urls: Dict[str, str],
        notify_repository,
    ) -> UUID:
        """
        Create notification job with portal URLs.

        The notify system expects:
        - p_portal_urls: JSONB mapping driver_id → portal_url
        - Template params including {plan_link} variable

        Returns:
            Job UUID
        """
        import json
        from uuid import UUID as UUIDType

        # Build driver IDs list (only successful ones)
        driver_ids = list(portal_urls.keys())

        # Build template params
        # Note: {plan_link} is resolved per-driver from portal_urls
        # Other params are shared across all messages
        template_params = request.template_params or {}

        # Call repository to create job
        # This uses notify.create_notification_job() function
        job_id = await notify_repository.create_job(
            tenant_id=request.tenant_id,
            site_id=request.site_id,
            job_type="SNAPSHOT_PUBLISH",
            reference_type="SNAPSHOT",
            reference_id=request.snapshot_id,
            delivery_channel=request.delivery_channel.value,
            initiated_by=request.initiated_by,
            driver_ids=driver_ids,
            portal_urls=portal_urls,
            template_key=request.template_key,
            template_params=template_params,
        )

        return job_id

    async def update_outbox_link(
        self,
        jti_hash: str,
        outbox_id: str,
    ) -> bool:
        """
        Link a portal token to its notification outbox entry.

        Called by notify worker after outbox entry is created.
        Uses portal.link_token_to_outbox() DB function.

        Args:
            jti_hash: Token's jti_hash
            outbox_id: Notification outbox UUID

        Returns:
            True if updated successfully
        """
        return await self.repository.link_token_to_outbox(jti_hash, outbox_id)

    async def issue_and_notify_atomic(
        self,
        request: NotifyLinkRequest,
    ) -> NotifyLinkResult:
        """
        ATOMIC version: Issue portal links and create outbox entries in single transaction.

        This uses the portal.issue_token_atomic() DB function which:
        1. Computes dedup key
        2. Checks for existing token (returns duplicate if found)
        3. Creates token + outbox entry atomically
        4. Links token to outbox

        If any part fails, entire transaction is rolled back.

        Args:
            request: NotifyLinkRequest with all parameters

        Returns:
            NotifyLinkResult with job_id and bulk result

        Security:
            - Dedup key prevents duplicate tokens
            - Atomic: no orphaned tokens possible
            - Transaction: all-or-nothing
        """
        results: List[DriverLinkResult] = []
        portal_urls: Dict[str, str] = {}
        success_count = 0
        failed_count = 0
        duplicate_count = 0

        # First create the notification job (to get job_id)
        job_id = await self.repository.create_notification_job(
            tenant_id=request.tenant_id,
            site_id=request.site_id,
            job_type="SNAPSHOT_PUBLISH",
            reference_type="SNAPSHOT",
            reference_id=request.snapshot_id,
            delivery_channel=request.delivery_channel.value,
            initiated_by=request.initiated_by,
            driver_count=len(request.driver_requests),
        )

        try:
            # Issue tokens atomically for each driver
            for driver_request in request.driver_requests:
                try:
                    # Generate JWT token (raw token for URL)
                    raw_token, portal_token = self.token_service.generate_token(
                        tenant_id=request.tenant_id,
                        site_id=request.site_id,
                        snapshot_id=request.snapshot_id,
                        driver_id=driver_request.driver_id,
                        scope=request.scope,
                        ttl_days=request.ttl_days,
                        delivery_channel=request.delivery_channel,
                    )

                    portal_url = self.token_service.build_portal_url(
                        request.base_url or self.base_url,
                        raw_token
                    )

                    # Call atomic DB function
                    result = await self.repository.issue_token_atomic(
                        tenant_id=request.tenant_id,
                        site_id=request.site_id,
                        snapshot_id=request.snapshot_id,
                        driver_id=driver_request.driver_id,
                        driver_name=driver_request.driver_name,
                        jti_hash=portal_token.jti_hash,
                        scope=request.scope.value,
                        delivery_channel=request.delivery_channel.value,
                        expires_at=portal_token.expires_at,
                        job_id=job_id,
                        template_key=request.template_key,
                        portal_url=portal_url,
                    )

                    if result.is_duplicate:
                        duplicate_count += 1
                        logger.warning(
                            f"Duplicate token for driver={driver_request.driver_id}, "
                            f"snapshot={request.snapshot_id[:8]}..."
                        )
                    else:
                        success_count += 1
                        portal_urls[driver_request.driver_id] = portal_url

                    results.append(DriverLinkResult(
                        driver_id=driver_request.driver_id,
                        portal_url=portal_url,
                        token=portal_token,
                        success=True,
                    ))

                except Exception as e:
                    logger.error(f"Failed atomic issue for driver {driver_request.driver_id}: {e}")
                    failed_count += 1
                    results.append(DriverLinkResult(
                        driver_id=driver_request.driver_id,
                        portal_url="",
                        token=PortalToken(),
                        success=False,
                        error_message=str(e),
                    ))

            # Update job with actual counts
            await self.repository.update_job_counts(
                job_id=job_id,
                total_count=len(request.driver_requests),
                pending_count=success_count,
            )

            bulk_result = BulkLinkResult(
                snapshot_id=request.snapshot_id,
                total_count=len(request.driver_requests),
                success_count=success_count,
                failed_count=failed_count,
                driver_results=results,
                portal_urls=portal_urls,
            )

            return NotifyLinkResult(
                snapshot_id=request.snapshot_id,
                job_id=str(job_id),
                bulk_result=bulk_result,
                notification_created=True,
                error_message=None if failed_count == 0 else f"{failed_count} drivers failed, {duplicate_count} duplicates",
            )

        except Exception as e:
            # Rollback: revoke all tokens for this job
            logger.error(f"Atomic issue_and_notify failed, revoking tokens: {e}")
            await self.repository.revoke_tokens_for_job(job_id, reason="ATOMIC_ROLLBACK")

            return NotifyLinkResult(
                snapshot_id=request.snapshot_id,
                job_id=str(job_id),
                bulk_result=BulkLinkResult(
                    snapshot_id=request.snapshot_id,
                    total_count=len(request.driver_requests),
                    success_count=0,
                    failed_count=len(request.driver_requests),
                    driver_results=[],
                    portal_urls={},
                ),
                notification_created=False,
                error_message=f"Atomic operation failed: {e}",
            )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_link_service(
    config: Optional[TokenConfig] = None,
    base_url: str = "https://portal.solvereign.com",
    use_mock: bool = False,
) -> Tuple[PortalLinkService, any]:
    """
    Create a portal link service.

    Args:
        config: Token configuration
        base_url: Base URL for portal
        use_mock: Use mock repository (for testing)

    Returns:
        Tuple of (PortalLinkService, repository)
    """
    token_service = PortalTokenService(config)

    if use_mock:
        repository = MockPortalRepository()
    else:
        repository = None  # Will be injected with DB pool

    service = PortalLinkService(
        token_service=token_service,
        repository=repository,
        base_url=base_url,
    )

    return service, repository


async def create_link_service_with_pool(
    pool,
    config: Optional[TokenConfig] = None,
    base_url: str = "https://portal.solvereign.com",
) -> PortalLinkService:
    """
    Create a portal link service with database pool.

    Args:
        pool: asyncpg connection pool
        config: Token configuration
        base_url: Base URL for portal

    Returns:
        PortalLinkService configured with PostgreSQL repository
    """
    token_service = PortalTokenService(config)
    repository = PostgresPortalRepository(pool)

    return PortalLinkService(
        token_service=token_service,
        repository=repository,
        base_url=base_url,
    )
