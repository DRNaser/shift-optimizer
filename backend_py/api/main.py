"""
SOLVEREIGN V3.3b API - Main Application
=======================================

FastAPI application with:
- JWT authentication (RS256) with RBAC
- Security headers (CSP, HSTS, etc.)
- Rate limiting (per-tenant, per-user, per-IP)
- Tenant isolation with RLS
- PII encryption (AES-256-GCM)
- Security audit logging with hash chain
- Prometheus metrics
- Structured logging
- Idempotency support
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .logging_config import setup_logging, get_logger
from .database import DatabaseManager

# Setup logging first
setup_logging()
logger = get_logger(__name__)


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events:
    - Database connection pool initialization
    - Metrics setup
    - Cleanup on shutdown
    """
    logger.info(
        "starting_application",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        }
    )

    # Startup: Initialize database pool
    db_manager = DatabaseManager()
    await db_manager.initialize()
    app.state.db = db_manager

    logger.info("database_pool_initialized")

    yield

    # Shutdown: Close database connections
    await db_manager.close()
    logger.info("application_shutdown_complete")


# =============================================================================
# APPLICATION FACTORY
# =============================================================================

def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Returns:
        Configured FastAPI instance
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production-ready shift scheduling optimization API",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # Configure middleware
    configure_middleware(app)

    # Register routers
    register_routers(app)

    # Register exception handlers
    register_exception_handlers(app)

    return app


# =============================================================================
# MIDDLEWARE CONFIGURATION
# =============================================================================

def configure_middleware(app: FastAPI) -> None:
    """
    Configure all middleware.

    CRITICAL: Order matters! Execution is LIFO (last added = first executed).
    Adding order (bottom-up) → Execution order (top-down):

    1. SecurityHeaders (outermost - always runs)
    2. CORS (before auth to handle preflight)
    3. RequestContext (sets request_id, timing)
    4. Auth (JWT validation, sets tenant_id/user_id)
    5. RateLimit (AFTER auth - can use tenant_id/user_id)
    6. Router handlers (innermost)
    """
    from .security.headers import SecurityHeadersMiddleware
    from .security.rate_limit import RateLimitMiddleware

    # NOTE: FastAPI middleware is LIFO - last added executes FIRST
    # So we add in REVERSE order of desired execution

    # 5. Rate limiting - runs AFTER auth (has access to tenant_id/user_id)
    app.add_middleware(RateLimitMiddleware)

    # 4. Auth middleware will be applied via dependencies (per-route)
    # This allows public endpoints (/health, /metrics) to skip auth

    # 3. RequestContext is added below as @app.middleware("http")

    # 2. CORS - must run before auth to handle OPTIONS preflight
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # 1. Security headers - outermost, always runs
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)

    # Request ID, timing, and metrics middleware
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        """Add request ID, timing, and record metrics for all requests."""
        import uuid
        from .metrics import record_http_request

        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.perf_counter()

        # Store in request state
        request.state.request_id = request_id
        request.state.start_time = start_time

        # Process request
        response: Response = await call_next(request)

        # Calculate duration
        duration_seconds = time.perf_counter() - start_time
        duration_ms = duration_seconds * 1000

        # Add response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"

        # Record Prometheus metrics (skip /metrics endpoint itself)
        if request.url.path != "/metrics":
            record_http_request(
                method=request.method,
                endpoint=request.url.path,
                status_code=response.status_code,
                duration_seconds=duration_seconds
            )

        # Log request completion
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            }
        )

        return response


# =============================================================================
# ROUTER REGISTRATION
# =============================================================================

def register_routers(app: FastAPI) -> None:
    """Register all API routers."""

    # Import routers here to avoid circular imports
    from .routers import health, forecasts, plans, tenants, simulations

    # Health check (no auth required)
    app.include_router(
        health.router,
        prefix="/health",
        tags=["Health"],
    )

    # API v1 routes
    api_prefix = "/api/v1"

    app.include_router(
        tenants.router,
        prefix=f"{api_prefix}/tenants",
        tags=["Tenants"],
    )

    app.include_router(
        forecasts.router,
        prefix=f"{api_prefix}/forecasts",
        tags=["Forecasts"],
    )

    app.include_router(
        plans.router,
        prefix=f"{api_prefix}/plans",
        tags=["Plans"],
    )

    app.include_router(
        simulations.router,
        prefix=f"{api_prefix}/simulations",
        tags=["Simulations"],
    )

    # Prometheus metrics endpoint (always registered)
    from .metrics import get_metrics_response

    @app.get("/metrics", tags=["Monitoring"], include_in_schema=False)
    async def metrics_endpoint():
        """
        Prometheus metrics endpoint.

        Returns metrics in Prometheus text format:
        - solve_duration_seconds (Histogram)
        - solve_failures_total (Counter)
        - audit_failures_total (Counter)
        - http_requests_total (Counter)
        - http_request_duration_seconds (Histogram)
        - solvereign_build_info (Info)
        """
        return get_metrics_response()

    logger.info("metrics_endpoint_registered", extra={"path": "/metrics"})


# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================

def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers."""

    from .exceptions import (
        SolvereIgnError,
        TenantNotFoundError,
        ForecastNotFoundError,
        PlanNotFoundError,
        ConcurrencyError,
        IdempotencyConflictError,
        ValidationError,
    )
    from .security.rate_limit import RateLimitExceeded

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded", "message": str(exc)},
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(TenantNotFoundError)
    async def tenant_not_found_handler(request: Request, exc: TenantNotFoundError):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": str(exc)},
        )

    @app.exception_handler(ForecastNotFoundError)
    async def forecast_not_found_handler(request: Request, exc: ForecastNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": str(exc)},
        )

    @app.exception_handler(PlanNotFoundError)
    async def plan_not_found_handler(request: Request, exc: PlanNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": str(exc)},
        )

    @app.exception_handler(ConcurrencyError)
    async def concurrency_handler(request: Request, exc: ConcurrencyError):
        return JSONResponse(
            status_code=423,  # Locked
            content={"error": "locked", "message": str(exc)},
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(request: Request, exc: IdempotencyConflictError):
        return JSONResponse(
            status_code=409,
            content={"error": "conflict", "message": str(exc)},
        )

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": str(exc), "details": exc.details},
        )

    @app.exception_handler(SolvereIgnError)
    async def generic_error_handler(request: Request, exc: SolvereIgnError):
        logger.error(
            "unhandled_application_error",
            extra={"error": str(exc), "type": type(exc).__name__}
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "An unexpected error occurred"},
        )


# =============================================================================
# APPLICATION INSTANCE
# =============================================================================

app = create_app()


# =============================================================================
# ROOT ENDPOINT
# =============================================================================

@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint with API info."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if not settings.is_production else None,
        "health": "/health",
    }


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
        log_level=settings.log_level.lower(),
    )
