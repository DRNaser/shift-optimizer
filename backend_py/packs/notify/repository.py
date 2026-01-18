"""
SOLVEREIGN V4.1 - Notification Repository
==========================================

Database operations for notification pipeline.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

from .models import (
    DeliveryChannel,
    NotificationJobType,
    JobStatus,
    OutboxStatus,
    WebhookEventType,
    DoNotContactReason,
    NotificationJob,
    NotificationOutbox,
    DeliveryLog,
    NotificationTemplate,
    DriverPreferences,
    RetryPolicy,
)

logger = logging.getLogger(__name__)


class NotificationRepository:
    """Repository for notification database operations."""

    def __init__(self, pool):
        """
        Initialize with database connection pool.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool

    async def _set_tenant_context(self, conn, tenant_id: int) -> None:
        """Set dual RLS tenant context for connection (P0 fix: migration 061)."""
        await conn.execute(
            "SELECT auth.set_dual_tenant_context($1, $2, $3)",
            tenant_id, None, False
        )

    # =========================================================================
    # JOB OPERATIONS
    # =========================================================================

    async def create_job(
        self,
        tenant_id: int,
        site_id: Optional[UUID],
        job_type: NotificationJobType,
        reference_type: str,
        reference_id: UUID,
        delivery_channel: DeliveryChannel,
        initiated_by: str,
        driver_ids: List[str],
        priority: int = 5,
        scheduled_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
    ) -> NotificationJob:
        """Create a new notification job."""
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                """
                INSERT INTO notify.notification_jobs (
                    tenant_id, site_id, job_type, reference_type, reference_id,
                    delivery_channel, initiated_by, target_driver_ids,
                    status, total_count, priority, scheduled_at, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING *
                """,
                tenant_id, site_id, job_type.value, reference_type, reference_id,
                delivery_channel.value, initiated_by, driver_ids,
                JobStatus.PENDING.value, len(driver_ids), priority, scheduled_at, expires_at
            )

            return self._row_to_job(row)

    async def get_job(self, tenant_id: int, job_id: UUID) -> Optional[NotificationJob]:
        """Get job by ID."""
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                "SELECT * FROM notify.notification_jobs WHERE id = $1",
                job_id
            )

            return self._row_to_job(row) if row else None

    async def update_job_status(
        self,
        tenant_id: int,
        job_id: UUID,
        status: JobStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        last_error: Optional[str] = None,
    ) -> None:
        """Update job status."""
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            await conn.execute(
                """
                UPDATE notify.notification_jobs
                SET status = $2,
                    started_at = COALESCE($3, started_at),
                    completed_at = COALESCE($4, completed_at),
                    last_error = COALESCE($5, last_error),
                    error_count = CASE WHEN $5 IS NOT NULL THEN error_count + 1 ELSE error_count END,
                    updated_at = NOW()
                WHERE id = $1
                """,
                job_id, status.value, started_at, completed_at, last_error
            )

    async def increment_job_counts(
        self,
        tenant_id: int,
        job_id: UUID,
        sent_delta: int = 0,
        delivered_delta: int = 0,
        failed_delta: int = 0,
    ) -> None:
        """Increment job counts atomically."""
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            await conn.execute(
                """
                UPDATE notify.notification_jobs
                SET sent_count = sent_count + $2,
                    delivered_count = delivered_count + $3,
                    failed_count = failed_count + $4,
                    updated_at = NOW()
                WHERE id = $1
                """,
                job_id, sent_delta, delivered_delta, failed_delta
            )

    # =========================================================================
    # OUTBOX OPERATIONS
    # =========================================================================

    async def create_outbox_entries(
        self,
        tenant_id: int,
        job_id: UUID,
        entries: List[Dict[str, Any]],
    ) -> List[UUID]:
        """
        Create outbox entries for a job.

        Args:
            tenant_id: Tenant ID
            job_id: Parent job ID
            entries: List of dicts with driver_id, portal_url, template, params

        Returns:
            List of created outbox IDs
        """
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            outbox_ids = []
            for entry in entries:
                row = await conn.fetchrow(
                    """
                    INSERT INTO notify.notification_outbox (
                        tenant_id, job_id, driver_id, driver_name, delivery_channel,
                        message_template, message_params, portal_url,
                        snapshot_id, reference_type, reference_id,
                        status, max_attempts, next_attempt_at, expires_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW(), $14)
                    RETURNING id
                    """,
                    tenant_id, job_id,
                    entry["driver_id"],
                    entry.get("driver_name"),
                    entry["delivery_channel"],
                    entry["message_template"],
                    entry.get("message_params", {}),
                    entry.get("portal_url"),
                    entry.get("snapshot_id"),
                    entry.get("reference_type"),
                    entry.get("reference_id"),
                    OutboxStatus.PENDING.value,
                    entry.get("max_attempts", 3),
                    entry.get("expires_at", datetime.utcnow() + timedelta(days=7)),
                )
                outbox_ids.append(row["id"])

            return outbox_ids

    async def claim_outbox_batch(
        self,
        batch_size: int = 10,
    ) -> List[NotificationOutbox]:
        """
        Claim a batch of pending messages for processing.

        Uses SKIP LOCKED for concurrent worker safety.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH claimed AS (
                    SELECT id
                    FROM notify.notification_outbox
                    WHERE status = 'PENDING'
                      AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE notify.notification_outbox o
                SET status = 'PROCESSING',
                    attempt_count = o.attempt_count + 1,
                    last_attempt_at = NOW(),
                    updated_at = NOW()
                FROM claimed c
                WHERE o.id = c.id
                RETURNING o.*
                """,
                batch_size
            )

            return [self._row_to_outbox(row) for row in rows]

    async def update_outbox_result(
        self,
        outbox_id: UUID,
        success: bool,
        provider_message_id: Optional[str] = None,
        provider_status: Optional[str] = None,
        provider_response: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        is_retryable: bool = True,
    ) -> None:
        """Update outbox entry with send result."""
        async with self._pool.acquire() as conn:
            # Get current state
            row = await conn.fetchrow(
                "SELECT * FROM notify.notification_outbox WHERE id = $1",
                outbox_id
            )

            if not row:
                logger.warning("outbox_not_found", extra={"outbox_id": str(outbox_id)})
                return

            # Determine new status
            if success:
                new_status = OutboxStatus.SENT.value
                next_attempt = None
            elif not is_retryable or row["attempt_count"] >= row["max_attempts"]:
                new_status = OutboxStatus.FAILED.value
                next_attempt = None
            else:
                new_status = OutboxStatus.PENDING.value
                # Exponential backoff: 60s, 300s, 900s
                backoff = [60, 300, 900]
                delay = backoff[min(row["attempt_count"] - 1, len(backoff) - 1)]
                next_attempt = datetime.utcnow() + timedelta(seconds=delay)

            await conn.execute(
                """
                UPDATE notify.notification_outbox
                SET status = $2,
                    provider_message_id = COALESCE($3, provider_message_id),
                    provider_status = $4,
                    provider_response = $5,
                    error_code = $6,
                    error_message = $7,
                    next_attempt_at = $8,
                    sent_at = CASE WHEN $9 THEN NOW() ELSE sent_at END,
                    updated_at = NOW()
                WHERE id = $1
                """,
                outbox_id, new_status, provider_message_id, provider_status,
                provider_response, error_code, error_message, next_attempt, success
            )

    async def get_outbox_by_provider_message_id(
        self,
        provider_message_id: str,
    ) -> Optional[NotificationOutbox]:
        """Get outbox entry by provider message ID (for webhooks)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM notify.notification_outbox
                WHERE provider_message_id = $1
                """,
                provider_message_id
            )

            return self._row_to_outbox(row) if row else None

    async def mark_delivered(
        self,
        outbox_id: UUID,
        provider_status: Optional[str] = None,
        delivered_at: Optional[datetime] = None,
    ) -> None:
        """Mark outbox entry as delivered (from webhook)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE notify.notification_outbox
                SET status = 'DELIVERED',
                    provider_status = COALESCE($2, provider_status),
                    delivered_at = COALESCE($3, NOW()),
                    updated_at = NOW()
                WHERE id = $1
                """,
                outbox_id, provider_status, delivered_at
            )

    async def mark_skipped(
        self,
        outbox_id: UUID,
        skip_reason: str,
        skip_message: Optional[str] = None,
    ) -> None:
        """
        Mark outbox entry as skipped (will not be sent).

        Use for do-not-contact, opted-out, invalid contact, etc.

        Args:
            outbox_id: Outbox entry ID
            skip_reason: Reason code (e.g., 'DO_NOT_CONTACT', 'OPTED_OUT')
            skip_message: Optional human-readable message
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE notify.notification_outbox
                SET status = 'SKIPPED',
                    skip_reason = $2,
                    error_code = $2,
                    error_message = $3,
                    updated_at = NOW()
                WHERE id = $1
                """,
                outbox_id, skip_reason, skip_message
            )

    # =========================================================================
    # DELIVERY LOG OPERATIONS
    # =========================================================================

    async def log_delivery_event(
        self,
        tenant_id: int,
        outbox_id: UUID,
        attempt_number: int,
        event_type: str,
        provider: Optional[str] = None,
        provider_message_id: Optional[str] = None,
        provider_status: Optional[str] = None,
        provider_response: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        is_retryable: bool = True,
        duration_ms: Optional[int] = None,
        webhook_event_id: Optional[str] = None,
        webhook_timestamp: Optional[datetime] = None,
        webhook_raw: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a delivery event."""
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            await conn.execute(
                """
                INSERT INTO notify.notification_delivery_log (
                    tenant_id, outbox_id, attempt_number, event_type,
                    provider, provider_message_id, provider_status, provider_response,
                    error_code, error_message, is_retryable, duration_ms,
                    webhook_event_id, webhook_timestamp, webhook_raw
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """,
                tenant_id, outbox_id, attempt_number, event_type,
                provider, provider_message_id, provider_status, provider_response,
                error_code, error_message, is_retryable, duration_ms,
                webhook_event_id, webhook_timestamp, webhook_raw
            )

    # =========================================================================
    # TEMPLATE OPERATIONS
    # =========================================================================

    async def get_template(
        self,
        tenant_id: int,
        template_key: str,
        delivery_channel: DeliveryChannel,
        language: str = "de",
    ) -> Optional[NotificationTemplate]:
        """
        Get template by key, channel, and language.

        Falls back to system template if tenant-specific not found.
        """
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            # Try tenant-specific first, then system default
            row = await conn.fetchrow(
                """
                SELECT * FROM notify.notification_templates
                WHERE template_key = $1
                  AND delivery_channel = $2
                  AND language = $3
                  AND is_active = TRUE
                  AND (tenant_id = $4 OR tenant_id IS NULL)
                ORDER BY tenant_id NULLS LAST
                LIMIT 1
                """,
                template_key, delivery_channel.value, language, tenant_id
            )

            return self._row_to_template(row) if row else None

    # =========================================================================
    # PREFERENCES OPERATIONS
    # =========================================================================

    async def check_can_contact(
        self,
        tenant_id: int,
        driver_id: str,
        channel: DeliveryChannel,
    ) -> bool:
        """
        Check if driver can be contacted via the given channel.

        This checks:
        1. Driver has opted in to the channel
        2. Driver is NOT on the do-not-contact list for the channel

        Args:
            tenant_id: Tenant ID
            driver_id: Driver ID
            channel: Delivery channel to check

        Returns:
            True if driver can be contacted, False otherwise
        """
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            # Use the SQL function for consistency
            result = await conn.fetchval(
                "SELECT notify.check_can_contact($1, $2, $3)",
                tenant_id, driver_id, channel.value
            )

            return result if result is not None else True  # Default to contactable if no preferences

    async def get_driver_preferences(
        self,
        tenant_id: int,
        driver_id: str,
    ) -> Optional[DriverPreferences]:
        """Get driver notification preferences."""
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            row = await conn.fetchrow(
                """
                SELECT * FROM notify.driver_preferences
                WHERE tenant_id = $1 AND driver_id = $2
                """,
                tenant_id, driver_id
            )

            return self._row_to_preferences(row) if row else None

    async def upsert_driver_preferences(
        self,
        tenant_id: int,
        driver_id: str,
        **updates,
    ) -> DriverPreferences:
        """Create or update driver preferences."""
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            # Build SET clause dynamically
            set_parts = []
            values = [tenant_id, driver_id]
            idx = 3

            for key, value in updates.items():
                set_parts.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1

            if not set_parts:
                # Just fetch existing or create default
                row = await conn.fetchrow(
                    """
                    INSERT INTO notify.driver_preferences (tenant_id, driver_id)
                    VALUES ($1, $2)
                    ON CONFLICT (tenant_id, driver_id) DO UPDATE
                    SET updated_at = NOW()
                    RETURNING *
                    """,
                    tenant_id, driver_id
                )
            else:
                set_clause = ", ".join(set_parts)
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO notify.driver_preferences (tenant_id, driver_id)
                    VALUES ($1, $2)
                    ON CONFLICT (tenant_id, driver_id) DO UPDATE
                    SET {set_clause}, updated_at = NOW()
                    RETURNING *
                    """,
                    *values
                )

            return self._row_to_preferences(row)

    # =========================================================================
    # BOUNCE/COMPLAINT HANDLING
    # =========================================================================

    # Soft bounce threshold before triggering do_not_contact
    SOFT_BOUNCE_THRESHOLD = 3

    async def handle_bounce_complaint(
        self,
        tenant_id: int,
        driver_id: str,
        channel: DeliveryChannel,
        event_type: WebhookEventType,
        _provider_event_id: Optional[str] = None,  # Reserved for future audit logging
        _provider_response: Optional[Dict[str, Any]] = None,  # Reserved for future audit logging
    ) -> Dict[str, Any]:
        """
        Handle bounce/complaint webhook events by updating driver preferences.

        Auto-sets do_not_contact flags based on event type:
        - BOUNCE (hard): Immediately set do_not_contact
        - SOFT_BOUNCE: Increment counter, set do_not_contact after threshold
        - COMPLAINT: Immediately set do_not_contact
        - UNSUBSCRIBE: Immediately set do_not_contact

        Args:
            tenant_id: Tenant ID
            driver_id: Driver ID
            channel: Delivery channel (EMAIL, WHATSAPP, SMS)
            event_type: Webhook event type
            provider_event_id: Provider's event ID for dedup
            provider_response: Raw webhook payload

        Returns:
            Dict with action taken and current state
        """
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            # Map event type to do_not_contact reason
            reason_map = {
                WebhookEventType.BOUNCE: DoNotContactReason.HARD_BOUNCE,
                WebhookEventType.COMPLAINT: DoNotContactReason.SPAM_COMPLAINT,
                WebhookEventType.UNSUBSCRIBE: DoNotContactReason.UNSUBSCRIBE,
            }

            # Map channel to column prefix
            channel_prefix = {
                DeliveryChannel.EMAIL: "email",
                DeliveryChannel.WHATSAPP: "whatsapp",
                DeliveryChannel.SMS: "sms",
            }.get(channel, "email")

            result = {
                "driver_id": driver_id,
                "channel": channel.value,
                "event_type": event_type.value,
                "action": None,
                "do_not_contact": False,
            }

            if event_type == WebhookEventType.SOFT_BOUNCE:
                # Increment soft bounce counter
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO notify.driver_preferences (tenant_id, driver_id)
                    VALUES ($1, $2)
                    ON CONFLICT (tenant_id, driver_id) DO UPDATE
                    SET {channel_prefix}_soft_bounce_count =
                        COALESCE(notify.driver_preferences.{channel_prefix}_soft_bounce_count, 0) + 1,
                        updated_at = NOW()
                    RETURNING {channel_prefix}_soft_bounce_count as bounce_count
                    """,
                    tenant_id, driver_id
                )

                bounce_count = row["bounce_count"]
                result["soft_bounce_count"] = bounce_count

                if bounce_count >= self.SOFT_BOUNCE_THRESHOLD:
                    # Threshold reached, set do_not_contact
                    await conn.execute(
                        f"""
                        UPDATE notify.driver_preferences
                        SET do_not_contact_{channel_prefix} = TRUE,
                            do_not_contact_{channel_prefix}_reason = $3,
                            do_not_contact_{channel_prefix}_at = NOW(),
                            updated_at = NOW()
                        WHERE tenant_id = $1 AND driver_id = $2
                        """,
                        tenant_id, driver_id, DoNotContactReason.SOFT_BOUNCE_LIMIT.value
                    )
                    result["action"] = "do_not_contact_set"
                    result["do_not_contact"] = True
                    result["reason"] = DoNotContactReason.SOFT_BOUNCE_LIMIT.value
                    logger.warning(
                        f"NOTIFY_DO_NOT_CONTACT: driver={driver_id}, channel={channel.value}, "
                        f"reason=SOFT_BOUNCE_LIMIT, bounce_count={bounce_count}"
                    )
                else:
                    result["action"] = "soft_bounce_recorded"

            elif event_type in reason_map:
                # Hard bounce, complaint, or unsubscribe - immediately set do_not_contact
                reason = reason_map[event_type]

                await conn.execute(
                    f"""
                    INSERT INTO notify.driver_preferences (tenant_id, driver_id)
                    VALUES ($1, $2)
                    ON CONFLICT (tenant_id, driver_id) DO UPDATE
                    SET do_not_contact_{channel_prefix} = TRUE,
                        do_not_contact_{channel_prefix}_reason = $3,
                        do_not_contact_{channel_prefix}_at = NOW(),
                        updated_at = NOW()
                    """,
                    tenant_id, driver_id, reason.value
                )

                result["action"] = "do_not_contact_set"
                result["do_not_contact"] = True
                result["reason"] = reason.value

                logger.warning(
                    f"NOTIFY_DO_NOT_CONTACT: driver={driver_id}, channel={channel.value}, "
                    f"reason={reason.value}, event={event_type.value}"
                )

            else:
                result["action"] = "ignored"

            return result

    async def clear_do_not_contact(
        self,
        tenant_id: int,
        driver_id: str,
        channel: DeliveryChannel,
        cleared_by: str,
        clear_reason: str,
    ) -> bool:
        """
        Manually clear do_not_contact flag (admin action).

        Requires audit reason. Resets soft bounce counter.
        """
        async with self._pool.acquire() as conn:
            await self._set_tenant_context(conn, tenant_id)

            channel_prefix = {
                DeliveryChannel.EMAIL: "email",
                DeliveryChannel.WHATSAPP: "whatsapp",
                DeliveryChannel.SMS: "sms",
            }.get(channel, "email")

            await conn.execute(
                f"""
                UPDATE notify.driver_preferences
                SET do_not_contact_{channel_prefix} = FALSE,
                    do_not_contact_{channel_prefix}_reason = NULL,
                    do_not_contact_{channel_prefix}_at = NULL,
                    {channel_prefix}_soft_bounce_count = 0,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND driver_id = $2
                """,
                tenant_id, driver_id
            )

            logger.info(
                f"NOTIFY_DO_NOT_CONTACT_CLEARED: driver={driver_id}, channel={channel.value}, "
                f"by={cleared_by}, reason={clear_reason}"
            )

            return True

    # =========================================================================
    # ROW MAPPERS
    # =========================================================================

    def _row_to_job(self, row) -> NotificationJob:
        """Convert database row to NotificationJob."""
        return NotificationJob(
            id=row["id"],
            tenant_id=row["tenant_id"],
            site_id=row["site_id"],
            job_type=NotificationJobType(row["job_type"]),
            reference_type=row["reference_type"],
            reference_id=row["reference_id"],
            target_driver_ids=row["target_driver_ids"],
            target_group=row["target_group"],
            delivery_channel=DeliveryChannel(row["delivery_channel"]),
            status=JobStatus(row["status"]),
            total_count=row["total_count"],
            sent_count=row["sent_count"],
            delivered_count=row["delivered_count"],
            failed_count=row["failed_count"],
            initiated_by=row["initiated_by"],
            initiated_at=row["initiated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            priority=row["priority"],
            retry_policy=RetryPolicy.from_dict(row["retry_policy"] or {}),
            scheduled_at=row["scheduled_at"],
            expires_at=row["expires_at"],
            last_error=row["last_error"],
            error_count=row["error_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_outbox(self, row) -> NotificationOutbox:
        """Convert database row to NotificationOutbox."""
        return NotificationOutbox(
            id=row["id"],
            tenant_id=row["tenant_id"],
            job_id=row["job_id"],
            driver_id=row["driver_id"],
            driver_name=row["driver_name"],
            recipient_hash=row["recipient_hash"],
            delivery_channel=DeliveryChannel(row["delivery_channel"]),
            message_template=row["message_template"],
            message_params=row["message_params"] or {},
            portal_url=row["portal_url"],
            snapshot_id=row["snapshot_id"],
            reference_type=row["reference_type"],
            reference_id=row["reference_id"],
            status=OutboxStatus(row["status"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            next_attempt_at=row["next_attempt_at"],
            last_attempt_at=row["last_attempt_at"],
            provider_message_id=row["provider_message_id"],
            provider_status=row["provider_status"],
            provider_response=row["provider_response"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sent_at=row["sent_at"],
            delivered_at=row["delivered_at"],
            expires_at=row["expires_at"],
        )

    def _row_to_template(self, row) -> NotificationTemplate:
        """Convert database row to NotificationTemplate."""
        return NotificationTemplate(
            id=row["id"],
            tenant_id=row["tenant_id"],
            site_id=row["site_id"],
            template_key=row["template_key"],
            delivery_channel=DeliveryChannel(row["delivery_channel"]),
            language=row["language"],
            whatsapp_template_name=row["whatsapp_template_name"],
            whatsapp_template_namespace=row["whatsapp_template_namespace"],
            subject=row["subject"],
            body_template=row["body_template"],
            body_html=row["body_html"],
            is_active=row["is_active"],
            requires_approval=row["requires_approval"],
            approval_status=row["approval_status"],
            expected_params=row["expected_params"] or [],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_preferences(self, row) -> DriverPreferences:
        """Convert database row to DriverPreferences."""
        return DriverPreferences(
            id=row["id"],
            tenant_id=row["tenant_id"],
            driver_id=row["driver_id"],
            preferred_channel=DeliveryChannel(row["preferred_channel"]),
            whatsapp_opted_in=row["whatsapp_opted_in"],
            whatsapp_opted_in_at=row["whatsapp_opted_in_at"],
            email_opted_in=row["email_opted_in"],
            email_opted_in_at=row["email_opted_in_at"],
            sms_opted_in=row["sms_opted_in"],
            sms_opted_in_at=row["sms_opted_in_at"],
            contact_verified=row["contact_verified"],
            contact_verified_at=row["contact_verified_at"],
            quiet_hours_start=row["quiet_hours_start"],
            quiet_hours_end=row["quiet_hours_end"],
            timezone=row["timezone"],
            consent_given_at=row["consent_given_at"],
            consent_source=row["consent_source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# =============================================================================
# MOCK REPOSITORY (For Testing)
# =============================================================================

class MockNotificationRepository:
    """In-memory mock repository for testing."""

    def __init__(self):
        self._jobs: Dict[UUID, NotificationJob] = {}
        self._outbox: Dict[UUID, NotificationOutbox] = {}
        self._delivery_logs: List[DeliveryLog] = []
        self._templates: Dict[str, NotificationTemplate] = {}
        self._preferences: Dict[str, DriverPreferences] = {}

    async def create_job(self, **kwargs) -> NotificationJob:
        """Create a mock job."""
        from uuid import uuid4
        job_id = uuid4()
        job = NotificationJob(
            id=job_id,
            tenant_id=kwargs["tenant_id"],
            site_id=kwargs.get("site_id"),
            job_type=kwargs["job_type"],
            reference_type=kwargs["reference_type"],
            reference_id=kwargs["reference_id"],
            target_driver_ids=kwargs.get("driver_ids", []),
            target_group=kwargs.get("target_group"),
            delivery_channel=kwargs["delivery_channel"],
            status=JobStatus.PENDING,
            total_count=len(kwargs.get("driver_ids", [])),
            sent_count=0,
            delivered_count=0,
            failed_count=0,
            initiated_by=kwargs["initiated_by"],
            initiated_at=datetime.utcnow(),
            started_at=None,
            completed_at=None,
            priority=kwargs.get("priority", 5),
            retry_policy=RetryPolicy(),
            scheduled_at=kwargs.get("scheduled_at"),
            expires_at=kwargs.get("expires_at"),
            last_error=None,
            error_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self._jobs[job_id] = job
        return job

    async def get_job(self, tenant_id: int, job_id: UUID) -> Optional[NotificationJob]:
        return self._jobs.get(job_id)

    async def claim_outbox_batch(self, batch_size: int = 10) -> List[NotificationOutbox]:
        pending = [o for o in self._outbox.values() if o.status == OutboxStatus.PENDING]
        return pending[:batch_size]

    # Add other mock methods as needed...
