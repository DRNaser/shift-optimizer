"""
SOLVEREIGN V3.3a API - Health Check Router
==========================================

Kubernetes-compatible health endpoints.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import settings


router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    timestamp: str
    environment: str


class ReadinessResponse(BaseModel):
    """Readiness check response with component status."""
    status: str
    checks: dict[str, str]
    timestamp: str


@router.get("", response_model=HealthResponse)
@router.get("/", response_model=HealthResponse, include_in_schema=False)
async def health_check():
    """
    Basic health check.

    Returns 200 if the service is running.
    Used for Kubernetes liveness probes.
    """
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc).isoformat(),
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(request: Request):
    """
    Readiness check with dependency verification.

    Checks:
    - Database connection
    - PolicyService availability
    - Pack availability (roster, routing)

    Returns 200 if ready to serve traffic.
    Used for Kubernetes readiness probes.
    """
    checks = {}
    overall_status = "ready"

    # Check database
    try:
        db = request.app.state.db
        async with db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"
        overall_status = "not_ready"

    # Check PolicyService
    try:
        policy_service = getattr(request.app.state, 'policy_service', None)
        if policy_service:
            checks["policy_service"] = "healthy"
        else:
            checks["policy_service"] = "not_initialized"
    except Exception as e:
        checks["policy_service"] = f"error: {str(e)}"

    # Check pack availability
    packs_status = {}

    # Roster pack
    try:
        import importlib
        importlib.import_module("backend_py.packs.roster.api")
        packs_status["roster"] = "available"
    except ImportError as e:
        packs_status["roster"] = f"unavailable: {str(e)}"

    # Routing pack
    try:
        importlib.import_module("backend_py.packs.routing.api.routers.scenarios")
        packs_status["routing"] = "available"
    except ImportError as e:
        packs_status["routing"] = f"unavailable: {str(e)}"

    checks["packs"] = packs_status

    return ReadinessResponse(
        status=overall_status,
        checks=checks,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/live")
async def liveness_check():
    """
    Simple liveness check.

    Always returns 200 if the process is running.
    """
    return {"status": "alive"}
