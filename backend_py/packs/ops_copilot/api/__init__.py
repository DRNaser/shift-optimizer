"""
Ops-Copilot API Router Aggregation

Aggregates all sub-routers for the Ops-Copilot pack.
"""

from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops-copilot"])

# Track component availability
_components = {
    "whatsapp": False,
    "drafts": False,
    "tickets": False,
    "broadcast": False,
}

# Import and register sub-routers with graceful fallback
try:
    from .routers.whatsapp import router as whatsapp_router
    router.include_router(whatsapp_router)
    _components["whatsapp"] = True
except ImportError as e:
    logger.warning(f"WhatsApp router not available: {e}")

try:
    from .routers.drafts import router as drafts_router
    router.include_router(drafts_router)
    _components["drafts"] = True
except ImportError as e:
    logger.warning(f"Drafts router not available: {e}")

try:
    from .routers.tickets import router as tickets_router
    router.include_router(tickets_router)
    _components["tickets"] = True
except ImportError as e:
    logger.warning(f"Tickets router not available: {e}")

try:
    from .routers.broadcast import router as broadcast_router
    router.include_router(broadcast_router)
    _components["broadcast"] = True
except ImportError as e:
    logger.warning(f"Broadcast router not available: {e}")


@router.get("/health", summary="Ops-Copilot Pack Health")
async def ops_copilot_health():
    """
    Health check endpoint for the Ops-Copilot pack.

    Returns component availability status.
    """
    all_healthy = all(_components.values())
    return {
        "pack": "ops_copilot",
        "version": "1.0.0",
        "status": "healthy" if all_healthy else "degraded",
        "components": _components,
    }


__all__ = ["router"]
