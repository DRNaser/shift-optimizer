"""
SOLVEREIGN Stripe Webhooks (P1.2)
=================================

Handles Stripe webhook events for subscription lifecycle.

Events handled:
- customer.subscription.created
- customer.subscription.updated
- customer.subscription.deleted
- invoice.paid
- invoice.payment_failed
- payment_method.attached

Webhook endpoint: POST /api/billing/webhook
"""

import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, Callable, Any

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False

logger = logging.getLogger(__name__)


class StripeWebhookHandler:
    """
    Handles Stripe webhook events with idempotency.

    Usage:
        handler = StripeWebhookHandler(db_pool)
        await handler.handle_event(event)
    """

    def __init__(self, db_pool):
        self.db = db_pool
        self._handlers: dict[str, Callable] = {
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.paid": self._handle_invoice_paid,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
            "payment_method.attached": self._handle_payment_method_attached,
            "customer.created": self._handle_customer_created,
            "customer.updated": self._handle_customer_updated,
        }

    async def handle_event(self, event: "stripe.Event") -> dict[str, Any]:
        """
        Process a Stripe webhook event.

        Args:
            event: Verified Stripe event

        Returns:
            Processing result dict
        """
        event_id = event.id
        event_type = event.type

        logger.info(f"Processing Stripe event: {event_type} ({event_id})")

        # Check idempotency (prevent duplicate processing)
        if await self._is_event_processed(event_id):
            logger.info(f"Event already processed: {event_id}")
            return {"status": "skipped", "reason": "already_processed"}

        # Get handler for event type
        handler = self._handlers.get(event_type)
        if not handler:
            logger.info(f"No handler for event type: {event_type}")
            await self._record_event(event_id, event_type, None)
            return {"status": "ignored", "reason": "no_handler"}

        # Process event
        try:
            result = await handler(event.data.object)
            await self._record_event(event_id, event_type, None)
            logger.info(f"Event processed successfully: {event_id}")
            return {"status": "processed", "result": result}
        except Exception as e:
            logger.exception(f"Event processing failed: {event_id}")
            await self._record_event(event_id, event_type, str(e))
            raise

    async def _is_event_processed(self, event_id: str) -> bool:
        """Check if event has already been processed."""
        async with self.db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT 1 FROM billing.webhook_events WHERE stripe_event_id = $1",
                event_id
            )
            return result is not None

    async def _record_event(
        self,
        event_id: str,
        event_type: str,
        error: Optional[str]
    ) -> None:
        """Record processed event for idempotency."""
        async with self.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO billing.webhook_events (stripe_event_id, event_type, error)
                VALUES ($1, $2, $3)
                ON CONFLICT (stripe_event_id) DO UPDATE SET error = $3
            """, event_id, event_type, error)

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================

    async def _handle_subscription_created(self, subscription: dict) -> dict:
        """Handle new subscription creation."""
        stripe_sub_id = subscription["id"]
        stripe_customer_id = subscription["customer"]
        status = subscription["status"]
        price_id = subscription["items"]["data"][0]["price"]["id"]

        logger.info(f"Subscription created: {stripe_sub_id} (status: {status})")

        async with self.db.acquire() as conn:
            # Get tenant from customer
            customer = await conn.fetchrow(
                "SELECT id, tenant_id FROM billing.stripe_customers WHERE stripe_customer_id = $1",
                stripe_customer_id
            )

            if not customer:
                logger.error(f"No customer found for {stripe_customer_id}")
                return {"error": "customer_not_found"}

            # Insert subscription
            await conn.execute("""
                INSERT INTO billing.subscriptions (
                    tenant_id, customer_id, stripe_subscription_id, stripe_price_id,
                    status, current_period_start, current_period_end,
                    cancel_at_period_end, trial_start, trial_end, quantity
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (stripe_subscription_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    current_period_start = EXCLUDED.current_period_start,
                    current_period_end = EXCLUDED.current_period_end,
                    updated_at = NOW()
            """,
                customer["tenant_id"],
                customer["id"],
                stripe_sub_id,
                price_id,
                status,
                _timestamp_to_datetime(subscription.get("current_period_start")),
                _timestamp_to_datetime(subscription.get("current_period_end")),
                subscription.get("cancel_at_period_end", False),
                _timestamp_to_datetime(subscription.get("trial_start")),
                _timestamp_to_datetime(subscription.get("trial_end")),
                subscription["items"]["data"][0].get("quantity", 1),
            )

            # Update tenant billing status
            await self._update_tenant_billing_status(conn, customer["tenant_id"], status)

        return {"subscription_id": stripe_sub_id, "status": status}

    async def _handle_subscription_updated(self, subscription: dict) -> dict:
        """Handle subscription updates (status changes, renewals)."""
        stripe_sub_id = subscription["id"]
        status = subscription["status"]

        logger.info(f"Subscription updated: {stripe_sub_id} (status: {status})")

        async with self.db.acquire() as conn:
            # Update subscription
            result = await conn.fetchrow("""
                UPDATE billing.subscriptions SET
                    status = $2,
                    current_period_start = $3,
                    current_period_end = $4,
                    cancel_at_period_end = $5,
                    canceled_at = $6,
                    updated_at = NOW()
                WHERE stripe_subscription_id = $1
                RETURNING tenant_id
            """,
                stripe_sub_id,
                status,
                _timestamp_to_datetime(subscription.get("current_period_start")),
                _timestamp_to_datetime(subscription.get("current_period_end")),
                subscription.get("cancel_at_period_end", False),
                _timestamp_to_datetime(subscription.get("canceled_at")),
            )

            if result:
                await self._update_tenant_billing_status(conn, result["tenant_id"], status)

        return {"subscription_id": stripe_sub_id, "status": status}

    async def _handle_subscription_deleted(self, subscription: dict) -> dict:
        """Handle subscription cancellation/deletion."""
        stripe_sub_id = subscription["id"]

        logger.info(f"Subscription deleted: {stripe_sub_id}")

        async with self.db.acquire() as conn:
            result = await conn.fetchrow("""
                UPDATE billing.subscriptions SET
                    status = 'canceled',
                    canceled_at = NOW(),
                    updated_at = NOW()
                WHERE stripe_subscription_id = $1
                RETURNING tenant_id
            """, stripe_sub_id)

            if result:
                await self._update_tenant_billing_status(conn, result["tenant_id"], "canceled")

        return {"subscription_id": stripe_sub_id, "status": "canceled"}

    async def _handle_invoice_paid(self, invoice: dict) -> dict:
        """Handle successful invoice payment."""
        stripe_invoice_id = invoice["id"]
        stripe_customer_id = invoice["customer"]

        logger.info(f"Invoice paid: {stripe_invoice_id}")

        async with self.db.acquire() as conn:
            customer = await conn.fetchrow(
                "SELECT id, tenant_id FROM billing.stripe_customers WHERE stripe_customer_id = $1",
                stripe_customer_id
            )

            if not customer:
                return {"error": "customer_not_found"}

            # Upsert invoice
            await conn.execute("""
                INSERT INTO billing.invoices (
                    tenant_id, customer_id, stripe_invoice_id, stripe_subscription_id,
                    number, status, currency, amount_due, amount_paid, amount_remaining,
                    tax, total, subtotal, hosted_invoice_url, invoice_pdf,
                    due_date, paid_at, period_start, period_end
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                ON CONFLICT (stripe_invoice_id) DO UPDATE SET
                    status = 'paid',
                    amount_paid = EXCLUDED.amount_paid,
                    amount_remaining = 0,
                    paid_at = EXCLUDED.paid_at,
                    updated_at = NOW()
            """,
                customer["tenant_id"],
                customer["id"],
                stripe_invoice_id,
                invoice.get("subscription"),
                invoice.get("number"),
                "paid",
                invoice.get("currency", "eur"),
                invoice.get("amount_due", 0),
                invoice.get("amount_paid", 0),
                0,  # amount_remaining
                invoice.get("tax", 0),
                invoice.get("total", 0),
                invoice.get("subtotal", 0),
                invoice.get("hosted_invoice_url"),
                invoice.get("invoice_pdf"),
                _timestamp_to_datetime(invoice.get("due_date")),
                datetime.now(timezone.utc),
                _timestamp_to_datetime(invoice.get("period_start")),
                _timestamp_to_datetime(invoice.get("period_end")),
            )

        return {"invoice_id": stripe_invoice_id, "status": "paid"}

    async def _handle_invoice_payment_failed(self, invoice: dict) -> dict:
        """Handle failed invoice payment."""
        stripe_invoice_id = invoice["id"]
        stripe_customer_id = invoice["customer"]

        logger.warning(f"Invoice payment failed: {stripe_invoice_id}")

        async with self.db.acquire() as conn:
            customer = await conn.fetchrow(
                "SELECT id, tenant_id FROM billing.stripe_customers WHERE stripe_customer_id = $1",
                stripe_customer_id
            )

            if customer:
                # Update invoice status
                await conn.execute("""
                    UPDATE billing.invoices SET
                        status = 'open',
                        updated_at = NOW()
                    WHERE stripe_invoice_id = $1
                """, stripe_invoice_id)

                # Note: Subscription status will be updated by subscription.updated event

        return {"invoice_id": stripe_invoice_id, "status": "payment_failed"}

    async def _handle_payment_method_attached(self, payment_method: dict) -> dict:
        """Handle new payment method attached."""
        pm_id = payment_method["id"]
        stripe_customer_id = payment_method["customer"]
        pm_type = payment_method["type"]

        logger.info(f"Payment method attached: {pm_id} ({pm_type})")

        async with self.db.acquire() as conn:
            customer = await conn.fetchrow(
                "SELECT id FROM billing.stripe_customers WHERE stripe_customer_id = $1",
                stripe_customer_id
            )

            if not customer:
                return {"error": "customer_not_found"}

            # Extract card/sepa details
            card_brand = None
            card_last4 = None
            card_exp_month = None
            card_exp_year = None
            sepa_last4 = None
            sepa_bank_code = None

            if pm_type == "card" and "card" in payment_method:
                card = payment_method["card"]
                card_brand = card.get("brand")
                card_last4 = card.get("last4")
                card_exp_month = card.get("exp_month")
                card_exp_year = card.get("exp_year")
            elif pm_type == "sepa_debit" and "sepa_debit" in payment_method:
                sepa = payment_method["sepa_debit"]
                sepa_last4 = sepa.get("last4")
                sepa_bank_code = sepa.get("bank_code")

            await conn.execute("""
                INSERT INTO billing.payment_methods (
                    customer_id, stripe_payment_method_id, type,
                    card_brand, card_last4, card_exp_month, card_exp_year,
                    sepa_last4, sepa_bank_code
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (stripe_payment_method_id) DO UPDATE SET
                    card_brand = EXCLUDED.card_brand,
                    card_last4 = EXCLUDED.card_last4
            """,
                customer["id"],
                pm_id,
                pm_type,
                card_brand,
                card_last4,
                card_exp_month,
                card_exp_year,
                sepa_last4,
                sepa_bank_code,
            )

        return {"payment_method_id": pm_id, "type": pm_type}

    async def _handle_customer_created(self, customer: dict) -> dict:
        """Handle new customer creation (if created via Stripe directly)."""
        # Usually customers are created via our API, but handle direct creation too
        logger.info(f"Customer created via Stripe: {customer['id']}")
        return {"customer_id": customer["id"]}

    async def _handle_customer_updated(self, customer: dict) -> dict:
        """Handle customer updates."""
        stripe_customer_id = customer["id"]

        logger.info(f"Customer updated: {stripe_customer_id}")

        async with self.db.acquire() as conn:
            await conn.execute("""
                UPDATE billing.stripe_customers SET
                    billing_email = $2,
                    billing_name = $3,
                    updated_at = NOW()
                WHERE stripe_customer_id = $1
            """,
                stripe_customer_id,
                customer.get("email"),
                customer.get("name"),
            )

        return {"customer_id": stripe_customer_id}

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _update_tenant_billing_status(
        self,
        conn,
        tenant_id: int,
        stripe_status: str
    ) -> None:
        """Update tenant's billing_status based on subscription status."""
        # Map Stripe status to our status
        status_map = {
            "trialing": "trialing",
            "active": "active",
            "past_due": "past_due",
            "canceled": "canceled",
            "unpaid": "suspended",
            "incomplete": "none",
            "incomplete_expired": "none",
            "paused": "suspended",
        }
        billing_status = status_map.get(stripe_status, "none")

        await conn.execute(
            "UPDATE tenants SET billing_status = $1 WHERE id = $2",
            billing_status,
            tenant_id,
        )


def _timestamp_to_datetime(ts: Optional[int]) -> Optional[datetime]:
    """Convert Unix timestamp to datetime."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)
