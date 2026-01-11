"""
SOLVEREIGN Billing Service (P1.2)
=================================

Core billing operations using Stripe API.
B2B Invoice-first model for DACH market.

Usage:
    service = BillingService(settings)
    customer = await service.create_customer(tenant_id, email, name)
    subscription = await service.create_subscription(customer_id, price_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any
from dataclasses import dataclass

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class BillingStatus:
    """Current billing status for a tenant."""
    has_customer: bool
    subscription_status: str  # none, trialing, active, past_due, canceled
    is_active: bool
    is_trialing: bool
    is_past_due: bool
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool


class BillingService:
    """
    Stripe billing service for B2B subscriptions.

    Features:
    - Customer management (linked to tenants)
    - Subscription lifecycle (create, update, cancel)
    - Invoice retrieval
    - Payment method management
    - B2B invoice-first billing (NET 14)
    """

    def __init__(
        self,
        api_key: str,
        webhook_secret: str,
        default_currency: str = "eur",
    ):
        if not STRIPE_AVAILABLE:
            raise ImportError("stripe package not installed")

        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.default_currency = default_currency

        # Configure Stripe
        stripe.api_key = api_key
        stripe.api_version = "2024-12-18.acacia"  # Use latest stable API

    # =========================================================================
    # CUSTOMERS
    # =========================================================================

    async def create_customer(
        self,
        tenant_id: int,
        email: str,
        name: str,
        tax_id: Optional[str] = None,
        address: Optional[dict] = None,
    ) -> stripe.Customer:
        """
        Create a Stripe customer for a tenant.

        Args:
            tenant_id: SOLVEREIGN tenant ID
            email: Billing email address
            name: Company name
            tax_id: VAT/UID number (e.g., ATU12345678)
            address: Billing address dict

        Returns:
            Stripe Customer object
        """
        logger.info(f"Creating Stripe customer for tenant {tenant_id}")

        params: dict[str, Any] = {
            "email": email,
            "name": name,
            "metadata": {
                "tenant_id": str(tenant_id),
                "platform": "solvereign",
            },
            "invoice_settings": {
                "default_payment_method": None,
            },
        }

        if address:
            params["address"] = address

        customer = stripe.Customer.create(**params)

        # Add tax ID if provided (for EU reverse charge)
        if tax_id:
            try:
                stripe.Customer.create_tax_id(
                    customer.id,
                    type="eu_vat",
                    value=tax_id,
                )
            except stripe.StripeError as e:
                logger.warning(f"Failed to add tax ID: {e}")

        logger.info(f"Created Stripe customer {customer.id} for tenant {tenant_id}")
        return customer

    async def get_customer(self, stripe_customer_id: str) -> Optional[stripe.Customer]:
        """Get Stripe customer by ID."""
        try:
            return stripe.Customer.retrieve(stripe_customer_id)
        except stripe.StripeError as e:
            logger.error(f"Failed to retrieve customer {stripe_customer_id}: {e}")
            return None

    async def update_customer(
        self,
        stripe_customer_id: str,
        **kwargs
    ) -> stripe.Customer:
        """Update customer details."""
        return stripe.Customer.modify(stripe_customer_id, **kwargs)

    # =========================================================================
    # SUBSCRIPTIONS
    # =========================================================================

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        quantity: int = 1,
        trial_days: Optional[int] = None,
        collection_method: str = "send_invoice",  # B2B invoice-first
        days_until_due: int = 14,  # NET 14
    ) -> stripe.Subscription:
        """
        Create a subscription for a customer.

        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID
            quantity: Number of units (e.g., drivers)
            trial_days: Free trial period
            collection_method: send_invoice (B2B) or charge_automatically
            days_until_due: Days until invoice is due (for send_invoice)

        Returns:
            Stripe Subscription object
        """
        logger.info(f"Creating subscription for customer {customer_id}")

        params: dict[str, Any] = {
            "customer": customer_id,
            "items": [{"price": price_id, "quantity": quantity}],
            "collection_method": collection_method,
            "payment_settings": {
                "payment_method_types": ["card", "sepa_debit"],
            },
            "metadata": {
                "platform": "solvereign",
            },
        }

        # B2B invoice settings
        if collection_method == "send_invoice":
            params["days_until_due"] = days_until_due

        # Trial period
        if trial_days:
            params["trial_period_days"] = trial_days

        subscription = stripe.Subscription.create(**params)
        logger.info(f"Created subscription {subscription.id}")
        return subscription

    async def get_subscription(
        self, stripe_subscription_id: str
    ) -> Optional[stripe.Subscription]:
        """Get subscription by ID."""
        try:
            return stripe.Subscription.retrieve(stripe_subscription_id)
        except stripe.StripeError as e:
            logger.error(f"Failed to retrieve subscription: {e}")
            return None

    async def update_subscription(
        self,
        stripe_subscription_id: str,
        **kwargs
    ) -> stripe.Subscription:
        """Update subscription (e.g., change quantity)."""
        return stripe.Subscription.modify(stripe_subscription_id, **kwargs)

    async def cancel_subscription(
        self,
        stripe_subscription_id: str,
        at_period_end: bool = True,
    ) -> stripe.Subscription:
        """
        Cancel a subscription.

        Args:
            stripe_subscription_id: Subscription to cancel
            at_period_end: If True, cancel at end of period (recommended)

        Returns:
            Updated subscription
        """
        logger.info(f"Canceling subscription {stripe_subscription_id}")

        if at_period_end:
            return stripe.Subscription.modify(
                stripe_subscription_id,
                cancel_at_period_end=True,
            )
        else:
            return stripe.Subscription.cancel(stripe_subscription_id)

    async def reactivate_subscription(
        self, stripe_subscription_id: str
    ) -> stripe.Subscription:
        """Reactivate a subscription scheduled for cancellation."""
        return stripe.Subscription.modify(
            stripe_subscription_id,
            cancel_at_period_end=False,
        )

    # =========================================================================
    # INVOICES
    # =========================================================================

    async def list_invoices(
        self,
        customer_id: str,
        limit: int = 10,
        status: Optional[str] = None,
    ) -> list[stripe.Invoice]:
        """List invoices for a customer."""
        params: dict[str, Any] = {
            "customer": customer_id,
            "limit": limit,
        }
        if status:
            params["status"] = status

        invoices = stripe.Invoice.list(**params)
        return list(invoices.data)

    async def get_invoice(self, stripe_invoice_id: str) -> Optional[stripe.Invoice]:
        """Get invoice by ID."""
        try:
            return stripe.Invoice.retrieve(stripe_invoice_id)
        except stripe.StripeError as e:
            logger.error(f"Failed to retrieve invoice: {e}")
            return None

    async def pay_invoice(self, stripe_invoice_id: str) -> stripe.Invoice:
        """Manually pay an invoice (e.g., after bank transfer)."""
        return stripe.Invoice.pay(stripe_invoice_id)

    async def void_invoice(self, stripe_invoice_id: str) -> stripe.Invoice:
        """Void an invoice."""
        return stripe.Invoice.void_invoice(stripe_invoice_id)

    # =========================================================================
    # PAYMENT METHODS
    # =========================================================================

    async def attach_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
        set_default: bool = True,
    ) -> stripe.PaymentMethod:
        """Attach a payment method to a customer."""
        pm = stripe.PaymentMethod.attach(
            payment_method_id,
            customer=customer_id,
        )

        if set_default:
            stripe.Customer.modify(
                customer_id,
                invoice_settings={"default_payment_method": payment_method_id},
            )

        return pm

    async def list_payment_methods(
        self,
        customer_id: str,
        type: str = "card",
    ) -> list[stripe.PaymentMethod]:
        """List payment methods for a customer."""
        pms = stripe.PaymentMethod.list(customer=customer_id, type=type)
        return list(pms.data)

    # =========================================================================
    # CHECKOUT (for self-service)
    # =========================================================================

    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        quantity: int = 1,
        trial_days: Optional[int] = None,
    ) -> stripe.checkout.Session:
        """
        Create a Stripe Checkout session for self-service signup.

        Returns:
            Checkout session with URL to redirect customer
        """
        params: dict[str, Any] = {
            "customer": customer_id,
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": quantity}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "payment_method_types": ["card", "sepa_debit"],
            "billing_address_collection": "required",
            "tax_id_collection": {"enabled": True},
        }

        if trial_days:
            params["subscription_data"] = {"trial_period_days": trial_days}

        return stripe.checkout.Session.create(**params)

    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> stripe.billing_portal.Session:
        """Create a Billing Portal session for customer self-service."""
        return stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )

    # =========================================================================
    # PRODUCTS & PRICES
    # =========================================================================

    async def list_products(self, active_only: bool = True) -> list[stripe.Product]:
        """List available products."""
        return list(stripe.Product.list(active=active_only).data)

    async def list_prices(
        self,
        product_id: Optional[str] = None,
        active_only: bool = True,
    ) -> list[stripe.Price]:
        """List prices, optionally filtered by product."""
        params: dict[str, Any] = {"active": active_only}
        if product_id:
            params["product"] = product_id
        return list(stripe.Price.list(**params).data)

    # =========================================================================
    # WEBHOOKS
    # =========================================================================

    def construct_webhook_event(
        self,
        payload: bytes,
        signature: str,
    ) -> stripe.Event:
        """
        Construct and verify a webhook event.

        Args:
            payload: Raw request body
            signature: Stripe-Signature header

        Returns:
            Verified Stripe Event

        Raises:
            stripe.SignatureVerificationError: Invalid signature
        """
        return stripe.Webhook.construct_event(
            payload,
            signature,
            self.webhook_secret,
        )
