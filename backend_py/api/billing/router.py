"""
SOLVEREIGN Billing API Router (P1.5)
====================================

API endpoints for billing management.

Endpoints:
- POST /api/billing/webhook - Stripe webhook handler
- GET  /api/billing/status - Get tenant billing status
- GET  /api/billing/invoices - List invoices
- POST /api/billing/portal - Create billing portal session
- GET  /api/billing/products - List available products
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False

from .service import BillingService
from .webhooks import StripeWebhookHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


# =============================================================================
# MODELS
# =============================================================================

class BillingStatusResponse(BaseModel):
    """Billing status for current tenant."""
    has_subscription: bool
    status: str  # none, trialing, active, past_due, canceled, suspended
    is_active: bool
    current_period_end: Optional[str]
    cancel_at_period_end: bool


class CreatePortalSessionRequest(BaseModel):
    """Request to create billing portal session."""
    return_url: str


class CreatePortalSessionResponse(BaseModel):
    """Billing portal session URL."""
    url: str


class ProductResponse(BaseModel):
    """Product information."""
    id: str
    name: str
    description: Optional[str]
    prices: list[dict]


# =============================================================================
# DEPENDENCIES
# =============================================================================

async def get_billing_service(request: Request) -> BillingService:
    """Get billing service from app state."""
    service = getattr(request.app.state, "billing_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Billing service not configured"
        )
    return service


async def get_webhook_handler(request: Request) -> StripeWebhookHandler:
    """Get webhook handler from app state."""
    handler = getattr(request.app.state, "webhook_handler", None)
    if not handler:
        raise HTTPException(
            status_code=503,
            detail="Webhook handler not configured"
        )
    return handler


# =============================================================================
# WEBHOOK ENDPOINT
# =============================================================================

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="Stripe-Signature"),
):
    """
    Stripe webhook endpoint.

    Handles subscription lifecycle events from Stripe.
    Requires valid Stripe signature.
    """
    if not STRIPE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    # Get raw body
    payload = await request.body()

    # Get service and verify signature
    service = await get_billing_service(request)
    try:
        event = service.construct_webhook_event(payload, stripe_signature)
    except stripe.SignatureVerificationError:
        logger.warning("Invalid Stripe signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Process event
    handler = await get_webhook_handler(request)
    try:
        result = await handler.handle_event(event)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception(f"Webhook processing failed: {e}")
        # Return 200 to prevent Stripe retries for unrecoverable errors
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": str(e)}
        )


# =============================================================================
# BILLING STATUS
# =============================================================================

@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(request: Request):
    """
    Get billing status for current tenant.

    Returns subscription status, active period, etc.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT * FROM billing.get_tenant_billing_status($1)",
            tenant_id
        )

    if not result:
        return BillingStatusResponse(
            has_subscription=False,
            status="none",
            is_active=False,
            current_period_end=None,
            cancel_at_period_end=False,
        )

    return BillingStatusResponse(
        has_subscription=result["has_customer"],
        status=result["subscription_status"],
        is_active=result["is_active"],
        current_period_end=result["current_period_end"].isoformat() if result["current_period_end"] else None,
        cancel_at_period_end=result["cancel_at_period_end"],
    )


# =============================================================================
# INVOICES
# =============================================================================

@router.get("/invoices")
async def list_invoices(
    request: Request,
    limit: int = 10,
    status: Optional[str] = None,
):
    """
    List invoices for current tenant.

    Args:
        limit: Maximum number of invoices to return
        status: Filter by status (draft, open, paid, void, uncollectible)
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        query = """
            SELECT
                stripe_invoice_id,
                number,
                status,
                currency,
                total,
                amount_paid,
                hosted_invoice_url,
                invoice_pdf,
                due_date,
                paid_at,
                period_start,
                period_end,
                created_at
            FROM billing.invoices
            WHERE tenant_id = $1
        """
        params = [tenant_id]

        if status:
            query += " AND status = $2"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)

        rows = await conn.fetch(query, *params)

    return [
        {
            "id": row["stripe_invoice_id"],
            "number": row["number"],
            "status": row["status"],
            "currency": row["currency"],
            "total": row["total"],
            "amount_paid": row["amount_paid"],
            "hosted_url": row["hosted_invoice_url"],
            "pdf_url": row["invoice_pdf"],
            "due_date": row["due_date"].isoformat() if row["due_date"] else None,
            "paid_at": row["paid_at"].isoformat() if row["paid_at"] else None,
            "period_start": row["period_start"].isoformat() if row["period_start"] else None,
            "period_end": row["period_end"].isoformat() if row["period_end"] else None,
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


# =============================================================================
# BILLING PORTAL
# =============================================================================

@router.post("/portal", response_model=CreatePortalSessionResponse)
async def create_portal_session(
    request: Request,
    body: CreatePortalSessionRequest,
    service: BillingService = Depends(get_billing_service),
):
    """
    Create a Stripe Billing Portal session.

    The portal allows customers to:
    - Update payment methods
    - View invoice history
    - Cancel/reactivate subscription
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        customer = await conn.fetchrow(
            "SELECT stripe_customer_id FROM billing.stripe_customers WHERE tenant_id = $1",
            tenant_id
        )

    if not customer:
        raise HTTPException(status_code=404, detail="No billing customer found")

    session = await service.create_billing_portal_session(
        customer_id=customer["stripe_customer_id"],
        return_url=body.return_url,
    )

    return CreatePortalSessionResponse(url=session.url)


# =============================================================================
# PRODUCTS CATALOG
# =============================================================================

@router.get("/products")
async def list_products(request: Request):
    """
    List available products and prices.

    Public endpoint for pricing page.
    """
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        products = await conn.fetch("""
            SELECT
                p.stripe_product_id,
                p.name,
                p.description,
                json_agg(json_build_object(
                    'id', pr.stripe_price_id,
                    'currency', pr.currency,
                    'unit_amount', pr.unit_amount,
                    'interval', pr.recurring_interval,
                    'interval_count', pr.recurring_interval_count
                )) as prices
            FROM billing.products p
            LEFT JOIN billing.prices pr ON pr.stripe_product_id = p.stripe_product_id
            WHERE p.is_active = TRUE AND pr.is_active = TRUE
            GROUP BY p.id, p.stripe_product_id, p.name, p.description
        """)

    return [
        {
            "id": p["stripe_product_id"],
            "name": p["name"],
            "description": p["description"],
            "prices": p["prices"] or [],
        }
        for p in products
    ]


# =============================================================================
# ADMIN ENDPOINTS (Platform Admin only)
# =============================================================================

@router.post("/admin/customers")
async def create_customer(
    request: Request,
    tenant_id: int,
    email: str,
    name: str,
    tax_id: Optional[str] = None,
    service: BillingService = Depends(get_billing_service),
):
    """
    Create a Stripe customer for a tenant.

    Platform admin only.
    """
    # TODO: Add platform admin check
    user = getattr(request.state, "user", None)
    if not user or user.get("role_name") != "platform_admin":
        raise HTTPException(status_code=403, detail="Platform admin required")

    # Create Stripe customer
    customer = await service.create_customer(
        tenant_id=tenant_id,
        email=email,
        name=name,
        tax_id=tax_id,
    )

    # Save to database
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await conn.execute("""
            INSERT INTO billing.stripe_customers (
                tenant_id, stripe_customer_id, billing_email, billing_name, tax_id
            ) VALUES ($1, $2, $3, $4, $5)
        """, tenant_id, customer.id, email, name, tax_id)

    return {
        "customer_id": customer.id,
        "tenant_id": tenant_id,
    }


@router.post("/admin/subscriptions")
async def create_subscription(
    request: Request,
    tenant_id: int,
    price_id: str,
    quantity: int = 1,
    trial_days: Optional[int] = None,
    service: BillingService = Depends(get_billing_service),
):
    """
    Create a subscription for a tenant.

    Platform admin only.
    """
    # TODO: Add platform admin check
    user = getattr(request.state, "user", None)
    if not user or user.get("role_name") != "platform_admin":
        raise HTTPException(status_code=403, detail="Platform admin required")

    # Get Stripe customer ID
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        customer = await conn.fetchrow(
            "SELECT stripe_customer_id FROM billing.stripe_customers WHERE tenant_id = $1",
            tenant_id
        )

    if not customer:
        raise HTTPException(status_code=404, detail="No billing customer for tenant")

    # Create subscription
    subscription = await service.create_subscription(
        customer_id=customer["stripe_customer_id"],
        price_id=price_id,
        quantity=quantity,
        trial_days=trial_days,
    )

    return {
        "subscription_id": subscription.id,
        "status": subscription.status,
    }


@router.post("/admin/subscriptions/{subscription_id}/cancel")
async def cancel_subscription(
    request: Request,
    subscription_id: str,
    at_period_end: bool = True,
    service: BillingService = Depends(get_billing_service),
):
    """
    Cancel a subscription.

    Platform admin only.
    """
    user = getattr(request.state, "user", None)
    if not user or user.get("role_name") != "platform_admin":
        raise HTTPException(status_code=403, detail="Platform admin required")

    subscription = await service.cancel_subscription(
        stripe_subscription_id=subscription_id,
        at_period_end=at_period_end,
    )

    return {
        "subscription_id": subscription.id,
        "status": subscription.status,
        "cancel_at_period_end": subscription.cancel_at_period_end,
    }
