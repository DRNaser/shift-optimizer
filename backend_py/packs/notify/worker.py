"""
SOLVEREIGN V4.1 - Notification Worker
======================================

Background worker for processing notification outbox.

USAGE:
    # As standalone worker
    python -m backend_py.packs.notify.worker

    # Or embedded in existing service
    from backend_py.packs.notify.worker import NotificationWorker
    worker = NotificationWorker(repository, providers)
    await worker.start()

CONFIGURATION:
    NOTIFY_WORKER_BATCH_SIZE: Messages per batch (default: 10)
    NOTIFY_WORKER_POLL_INTERVAL: Seconds between polls (default: 5)
    NOTIFY_WORKER_MAX_CONCURRENT: Max concurrent sends (default: 5)
"""

import asyncio
import logging
import os
import signal
from datetime import datetime
from typing import Dict, Optional, List

from .models import (
    DeliveryChannel,
    OutboxStatus,
    NotificationOutbox,
)
from .providers.base import NotificationProvider, ProviderResult
from .repository import NotificationRepository

logger = logging.getLogger(__name__)


class NotificationWorker:
    """
    Background worker for processing notification outbox.

    Uses transactional outbox pattern:
    1. Claim batch of pending messages (with row lock)
    2. Send via appropriate provider
    3. Update status and log result
    4. Repeat
    """

    def __init__(
        self,
        repository: NotificationRepository,
        providers: Dict[DeliveryChannel, NotificationProvider],
        batch_size: int = 10,
        poll_interval: float = 5.0,
        max_concurrent: int = 5,
        contact_resolver: Optional[callable] = None,
    ):
        """
        Initialize notification worker.

        Args:
            repository: Notification repository instance
            providers: Map of channel to provider instance
            batch_size: Number of messages to process per batch
            poll_interval: Seconds to wait between batch polls
            max_concurrent: Max concurrent sends within a batch
            contact_resolver: Async function(driver_id) -> contact info
        """
        self._repository = repository
        self._providers = providers
        self._batch_size = int(os.environ.get("NOTIFY_WORKER_BATCH_SIZE", batch_size))
        self._poll_interval = float(os.environ.get("NOTIFY_WORKER_POLL_INTERVAL", poll_interval))
        self._max_concurrent = int(os.environ.get("NOTIFY_WORKER_MAX_CONCURRENT", max_concurrent))
        self._contact_resolver = contact_resolver
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._metrics = {
            "batches_processed": 0,
            "messages_sent": 0,
            "messages_failed": 0,
            "total_duration_ms": 0,
        }

    async def start(self) -> None:
        """Start the worker loop."""
        logger.info(
            "notification_worker_starting",
            extra={
                "batch_size": self._batch_size,
                "poll_interval": self._poll_interval,
                "max_concurrent": self._max_concurrent,
                "providers": list(self._providers.keys()),
            }
        )

        self._running = True

        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._handle_shutdown)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        while self._running:
            try:
                await self._process_batch()
            except Exception as e:
                logger.exception("notification_worker_error", extra={"error": str(e)})
                # Continue running after error

            # Wait for next poll or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue processing

        logger.info("notification_worker_stopped", extra={"metrics": self._metrics})

    async def stop(self) -> None:
        """Stop the worker gracefully."""
        logger.info("notification_worker_stopping")
        self._running = False
        self._shutdown_event.set()

    def _handle_shutdown(self) -> None:
        """Handle shutdown signal."""
        logger.info("notification_worker_shutdown_signal")
        asyncio.create_task(self.stop())

    async def _process_batch(self) -> None:
        """Process a batch of pending messages."""
        # Claim batch from outbox
        messages = await self._repository.claim_outbox_batch(self._batch_size)

        if not messages:
            return  # Nothing to process

        logger.info(
            "notification_batch_claimed",
            extra={"count": len(messages)}
        )

        self._metrics["batches_processed"] += 1

        # Process messages with concurrency limit
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def process_with_limit(msg: NotificationOutbox):
            async with semaphore:
                await self._process_message(msg)

        await asyncio.gather(
            *[process_with_limit(msg) for msg in messages],
            return_exceptions=True
        )

    async def _process_message(self, message: NotificationOutbox) -> None:
        """Process a single message."""
        start_time = datetime.utcnow()

        # STEP 1: Re-check DNC status (defense in depth - may have changed since outbox creation)
        can_contact = await self._repository.check_can_contact(
            tenant_id=message.tenant_id,
            driver_id=message.driver_id,
            channel=message.delivery_channel,
        )

        if not can_contact:
            logger.info(
                "notification_skipped_dnc",
                extra={
                    "outbox_id": str(message.id),
                    "driver_id": message.driver_id,
                    "channel": message.delivery_channel.value,
                    "reason": "DO_NOT_CONTACT",
                }
            )
            # Mark as SKIPPED instead of sending
            await self._repository.mark_skipped(
                outbox_id=message.id,
                skip_reason="DO_NOT_CONTACT",
                skip_message="Driver is on do-not-contact list for this channel",
            )
            return

        # STEP 2: Get provider for channel
        provider = self._providers.get(message.delivery_channel)
        if not provider:
            logger.error(
                "notification_no_provider",
                extra={
                    "channel": message.delivery_channel.value,
                    "outbox_id": str(message.id),
                }
            )
            await self._update_result(
                message,
                ProviderResult.error(
                    code="NO_PROVIDER",
                    message=f"No provider for channel {message.delivery_channel.value}",
                    is_retryable=False,
                )
            )
            return

        # Resolve contact info if needed
        recipient = await self._resolve_contact(message)
        if not recipient:
            await self._update_result(
                message,
                ProviderResult.error(
                    code="NO_CONTACT",
                    message=f"Could not resolve contact for driver {message.driver_id}",
                    is_retryable=False,
                )
            )
            return

        # Build template params
        template_params = {
            **message.message_params,
            "driver_name": message.driver_name or message.driver_id,
            "portal_url": message.portal_url,
        }

        # Send via provider
        try:
            result = await provider.send(
                recipient=recipient,
                template_name=message.message_template,
                template_params=template_params,
            )
        except Exception as e:
            logger.exception(
                "notification_send_error",
                extra={"outbox_id": str(message.id), "error": str(e)}
            )
            result = ProviderResult.error(
                code="SEND_ERROR",
                message=str(e),
                is_retryable=True,
            )

        # Calculate duration
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        result.duration_ms = duration_ms

        # Update metrics
        if result.success:
            self._metrics["messages_sent"] += 1
        else:
            self._metrics["messages_failed"] += 1
        self._metrics["total_duration_ms"] += duration_ms

        # Update outbox and log
        await self._update_result(message, result, provider.provider_name)

    async def _resolve_contact(self, message: NotificationOutbox) -> Optional[str]:
        """
        Resolve contact info for a driver.

        Priority:
        1. Custom resolver (if provided)
        2. Message params (if pre-populated)
        3. Return None (message will fail)
        """
        # Check if contact is in message params
        if message.delivery_channel == DeliveryChannel.WHATSAPP:
            if "phone" in message.message_params:
                return message.message_params["phone"]
        elif message.delivery_channel == DeliveryChannel.EMAIL:
            if "email" in message.message_params:
                return message.message_params["email"]

        # Use custom resolver if available
        if self._contact_resolver:
            try:
                contact = await self._contact_resolver(
                    message.driver_id,
                    message.delivery_channel,
                )
                return contact
            except Exception as e:
                logger.warning(
                    "contact_resolver_error",
                    extra={"driver_id": message.driver_id, "error": str(e)}
                )

        return None

    async def _update_result(
        self,
        message: NotificationOutbox,
        result: ProviderResult,
        provider_name: Optional[str] = None,
    ) -> None:
        """Update outbox and create delivery log."""
        # Update outbox
        await self._repository.update_outbox_result(
            outbox_id=message.id,
            success=result.success,
            provider_message_id=result.provider_message_id,
            provider_status=result.provider_status,
            provider_response=result.provider_response,
            error_code=result.error_code,
            error_message=result.error_message,
            is_retryable=result.is_retryable,
        )

        # Log delivery event
        await self._repository.log_delivery_event(
            tenant_id=message.tenant_id,
            outbox_id=message.id,
            attempt_number=message.attempt_count,
            event_type="SENT" if result.success else "FAILED",
            provider=provider_name,
            provider_message_id=result.provider_message_id,
            provider_status=result.provider_status,
            provider_response=result.provider_response,
            error_code=result.error_code,
            error_message=result.error_message,
            is_retryable=result.is_retryable,
            duration_ms=result.duration_ms,
        )

        # Update job counts if job exists
        if message.job_id:
            if result.success:
                await self._repository.increment_job_counts(
                    tenant_id=message.tenant_id,
                    job_id=message.job_id,
                    sent_delta=1,
                )
            elif not result.is_retryable or message.attempt_count >= message.max_attempts:
                await self._repository.increment_job_counts(
                    tenant_id=message.tenant_id,
                    job_id=message.job_id,
                    failed_delta=1,
                )

        logger.info(
            "notification_processed",
            extra={
                "outbox_id": str(message.id),
                "driver_id": message.driver_id,
                "success": result.success,
                "attempt": message.attempt_count,
                "duration_ms": result.duration_ms,
                "error_code": result.error_code,
            }
        )

    @property
    def metrics(self) -> Dict[str, int]:
        """Get worker metrics."""
        return self._metrics.copy()


# =============================================================================
# STANDALONE ENTRY POINT
# =============================================================================

async def main():
    """Run worker as standalone process."""
    import asyncpg

    from .providers.whatsapp import WhatsAppCloudProvider
    from .providers.email import SendGridProvider

    # Get database URL from environment
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set")
        return

    # Create connection pool
    pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)

    try:
        # Create repository
        repository = NotificationRepository(pool)

        # Create providers
        providers = {
            DeliveryChannel.WHATSAPP: WhatsAppCloudProvider(),
            DeliveryChannel.EMAIL: SendGridProvider(),
        }

        # Create and start worker
        worker = NotificationWorker(
            repository=repository,
            providers=providers,
        )

        await worker.start()

    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main())
