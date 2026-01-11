"""
SOLVEREIGN Billing Gating (P1.3)
================================

Middleware and dependencies for subscription-based access control.

Usage:
    # As FastAPI dependency
    @router.get("/protected")
    async def protected_endpoint(
        _: None = Depends(require_active_subscription),
    ):
        ...

    # As middleware for entire router
    router = APIRouter(dependencies=[Depends(require_active_subscription)])

Break Glass (Emergency Override):
    # Disable all billing enforcement (use with caution!)
    SOLVEREIGN_BILLING_ENFORCEMENT=off

    # Per-tenant override in database:
    UPDATE tenants SET billing_override_until = NOW() + INTERVAL '24 hours' WHERE id = 1;
"""

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from typing import Optional, Callable

from fastapi import HTTPException, Request, Depends
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# =============================================================================
# BREAK GLASS: Global billing enforcement toggle
# =============================================================================
# Set SOLVEREIGN_BILLING_ENFORCEMENT=off to disable ALL billing checks
# WARNING: Use only in emergencies (e.g., Stripe misconfiguration locking everyone out)
BILLING_ENFORCEMENT_ENABLED = os.getenv("SOLVEREIGN_BILLING_ENFORCEMENT", "on").lower() != "off"

if not BILLING_ENFORCEMENT_ENABLED:
    logger.warning(
        "BILLING ENFORCEMENT DISABLED - All billing checks bypassed! "
        "Set SOLVEREIGN_BILLING_ENFORCEMENT=on to re-enable."
    )


class BillingStatus(str, Enum):
    """Subscription status levels."""
    NONE = "none"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    SUSPENDED = "suspended"


class BillingGate:
    """
    Billing gating logic.

    Determines access based on subscription status:
    - ACTIVE, TRIALING: Full access
    - PAST_DUE: Grace period (14 days), then read-only
    - CANCELED: Read-only until period end
    - NONE, SUSPENDED: No access to paid features
    """

    # Paths that are always accessible (no subscription required)
    # NOTE: Matching uses prefix check with normalization (see is_always_allowed)
    ALWAYS_ALLOWED_PATHS = {
        "/api/auth",
        "/api/platform",
        "/api/portal",
        "/api/health",
        "/api/billing",  # Billing management always accessible
        "/api/consent",  # GDPR consent always accessible
        "/docs",
        "/openapi.json",
        "/health",
        "/metrics",
    }

    # Paths that require active subscription
    PAID_FEATURE_PATHS = {
        "/api/v1/solver/",
        "/api/v1/roster/",
        "/api/v1/dispatch/",
        "/api/v1/forecast/",
    }

    def __init__(self, grace_period_days: int = 14):
        self.grace_period_days = grace_period_days

    def is_always_allowed(self, path: str) -> bool:
        """
        Check if path is always accessible.

        Uses prefix matching with boundary check to prevent bypass:
        - /api/auth matches /api/auth and /api/auth/login
        - /api/auth does NOT match /api/authXYZ
        """
        # Normalize: strip trailing slash for consistent matching
        normalized = path.rstrip("/") if path != "/" else path

        for allowed in self.ALWAYS_ALLOWED_PATHS:
            allowed_normalized = allowed.rstrip("/")
            # Exact match or prefix with path separator
            if normalized == allowed_normalized or normalized.startswith(allowed_normalized + "/"):
                return True
        return False

    def requires_paid_subscription(self, path: str) -> bool:
        """Check if path requires paid subscription."""
        return any(path.startswith(paid) for paid in self.PAID_FEATURE_PATHS)

    def can_access(
        self,
        status: BillingStatus,
        is_write_operation: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if access is allowed based on billing status.

        Args:
            status: Current subscription status
            is_write_operation: True for POST/PUT/DELETE

        Returns:
            (allowed, reason) - reason is None if allowed
        """
        if status in (BillingStatus.ACTIVE, BillingStatus.TRIALING):
            return True, None

        if status == BillingStatus.PAST_DUE:
            # Grace period: full access
            # After grace period: read-only
            if is_write_operation:
                return False, "Payment overdue. Please update your payment method."
            return True, None

        if status == BillingStatus.CANCELED:
            # Allow read-only until period end
            if is_write_operation:
                return False, "Subscription canceled. Reactivate to make changes."
            return True, None

        # NONE or SUSPENDED
        return False, "Active subscription required."


# Global gating instance
_billing_gate = BillingGate()


async def get_tenant_billing_status(request: Request) -> BillingStatus:
    """
    Get billing status for current tenant from request state.

    This should be set by auth middleware after loading tenant context.
    Supports per-tenant override via billing_override_until column.
    """
    # Check if billing status is already in request state
    billing_status = getattr(request.state, "billing_status", None)
    if billing_status:
        return BillingStatus(billing_status)

    # If no tenant context, assume no subscription needed
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        return BillingStatus.ACTIVE  # Platform-level requests don't need subscription

    # Look up billing status from database
    # This is set by the auth/session middleware
    db = getattr(request.state, "db", None)
    if db:
        try:
            result = await db.fetchrow(
                """SELECT billing_status, billing_override_until
                   FROM tenants WHERE id = $1""",
                tenant_id
            )
            if result:
                # Check for per-tenant override (break glass)
                override_until = result.get("billing_override_until")
                if override_until and override_until > datetime.now(timezone.utc):
                    logger.info(
                        f"Billing override active for tenant {tenant_id} "
                        f"until {override_until.isoformat()}"
                    )
                    return BillingStatus.ACTIVE

                return BillingStatus(result["billing_status"] or "none")
        except Exception as e:
            logger.warning(f"Failed to get billing status: {e}")

    return BillingStatus.NONE


async def require_active_subscription(request: Request) -> None:
    """
    FastAPI dependency that requires an active subscription.

    Usage:
        @router.post("/solve")
        async def solve(
            _: None = Depends(require_active_subscription),
        ):
            ...
    """
    # BREAK GLASS: Skip all checks if enforcement is disabled
    if not BILLING_ENFORCEMENT_ENABLED:
        return

    # Skip for always-allowed paths
    if _billing_gate.is_always_allowed(request.url.path):
        return

    # Skip for non-paid features
    if not _billing_gate.requires_paid_subscription(request.url.path):
        return

    # Get billing status (includes per-tenant override check)
    status = await get_tenant_billing_status(request)

    # Check access
    is_write = request.method in ("POST", "PUT", "PATCH", "DELETE")
    allowed, reason = _billing_gate.can_access(status, is_write)

    if not allowed:
        raise HTTPException(
            status_code=402,  # Payment Required
            detail={
                "error": "subscription_required",
                "message": reason,
                "billing_status": status.value,
            },
        )


class BillingGatingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for billing gating across all routes.

    Alternative to using Depends() on individual routes.
    """

    def __init__(self, app, gate: Optional[BillingGate] = None):
        super().__init__(app)
        self.gate = gate or _billing_gate

    async def dispatch(self, request: Request, call_next):
        # Skip for always-allowed paths
        if self.gate.is_always_allowed(request.url.path):
            return await call_next(request)

        # Skip for non-paid features
        if not self.gate.requires_paid_subscription(request.url.path):
            return await call_next(request)

        # Get billing status
        status = await get_tenant_billing_status(request)

        # Check access
        is_write = request.method in ("POST", "PUT", "PATCH", "DELETE")
        allowed, reason = self.gate.can_access(status, is_write)

        if not allowed:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=402,
                content={
                    "error": "subscription_required",
                    "message": reason,
                    "billing_status": status.value,
                },
            )

        return await call_next(request)


def require_subscription(min_status: BillingStatus = BillingStatus.ACTIVE):
    """
    Decorator for requiring specific subscription level.

    Usage:
        @require_subscription(BillingStatus.ACTIVE)
        async def premium_feature():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            if request is None:
                # Try to find request in kwargs
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if request:
                status = await get_tenant_billing_status(request)
                if status.value < min_status.value:
                    raise HTTPException(
                        status_code=402,
                        detail={
                            "error": "subscription_required",
                            "message": f"This feature requires {min_status.value} subscription.",
                            "current_status": status.value,
                        },
                    )

            return await func(*args, **kwargs)
        return wrapper
    return decorator
