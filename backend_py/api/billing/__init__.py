"""
SOLVEREIGN Billing Module (P1)
==============================

Stripe integration for B2B invoice-first billing.

Components:
- service.py: Core billing operations
- webhooks.py: Stripe webhook handlers
- router.py: API endpoints
- gating.py: Subscription gating middleware
"""

from .service import BillingService
from .gating import require_active_subscription, BillingGate

__all__ = [
    "BillingService",
    "require_active_subscription",
    "BillingGate",
]
