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
    - (Future: Redis, external services)

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
